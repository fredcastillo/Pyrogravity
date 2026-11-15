import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from data.src.analysis import spice_flow as spice
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, discover_sources
from test_nasa_loader import SimulatedCursor, etl_outputs, simulated_database


@pytest.fixture(scope="module")
def dataset_dir(request):
    if (DATA_DIR / "source_manifest.csv").is_file() and (DATA_DIR / "processed" / spice.PARQUET).is_file():
        return DATA_DIR
    return request.getfixturevalue("etl_outputs")


@pytest.fixture(scope="module")
def result(dataset_dir):
    return spice.analyze_parquet(dataset_dir)


def test_population_and_two_selection_policies(result):
    assert result["dataset"]["row_count"] == 469
    assert [row["source_record"] for row in result["records"]] == list(range(1, 470))
    available, conservative = (result["cohorts"][name] for name in ("available", "conservative"))
    assert (available["record_count"], available["excluded_count"]) == (444, 25)
    assert (conservative["record_count"], conservative["excluded_count"], conservative["additional_exclusions"]) == (387, 82, 57)
    assert available["excluded_by_field_reason"] == {"air_rate_cm_s:blank": 25, "fuel_rate_mg_s:blank": 12}
    assert conservative["excluded_by_field_reason"] == {
        **available["excluded_by_field_reason"], "source_record:identical_source_row": 57,
    }
    for cohort in (available, conservative):
        assert sorted(cohort["source_records"] + [row["source_record"] for row in cohort["exclusions"]]) == list(range(1, 470))


@pytest.mark.parametrize(("name", "field", "values"), [
    ("available", spice.AIR, ("-5.92", "15.71", "27.93", "40.15", "85.28", "30.581666667")),
    ("conservative", spice.AIR, ("-5.92", "15.71", "27.93", "40.15", "85.28", "30.651395349")),
    ("available", spice.FUEL_RATE, ("0.000", "0.590", "1.010", "1.66625", "4.397", "1.224337838")),
    ("conservative", spice.FUEL_RATE, ("0.000", "0.584", "0.985", "1.6615", "4.397", "1.209780362")),
])
def test_flow_statistics(result, name, field, values):
    stats = result["cohorts"][name]["statistics"][field]
    assert stats["summary"] == dict(zip(("minimum", "q1", "median", "q3", "maximum", "mean"), values, strict=True))
    assert stats["unit"] == spice.NUMERIC[field]
    assert (stats["negative_count"], stats["zero_count"]) == ((8, 0) if field == spice.AIR else (0, 1))


def test_numeric_fields_are_audited_independently_of_the_joint_selection(result):
    stats = result["quality"]["numeric_fields"]
    assert {name: (item["exact_count"], item["missing_count"]) for name, item in stats.items()} == {
        "nozzle_mm": (469, 0), "fuel_rate_sccm": (457, 12), "fuel_rate_mg_s": (457, 12),
        "hc_fuel_rate_mg_s": (469, 0), "air_rate_cm_s": (444, 25),
    }
    assert stats["hc_fuel_rate_mg_s"]["zero_count"] == 13
    fields = result["quality"]["text_status_counts"]
    assert fields["gmt_ignition"] == {"ambiguous": 2, "annotation": 12, "missing_marker": 1, "text": 454}
    assert fields["gmt_flame_off"]["blank"] == 11


def test_all_members_of_identical_raw_groups_are_excluded_only_from_conservative(result):
    available = set(result["cohorts"]["available"]["source_records"])
    conservative = set(result["cohorts"]["conservative"]["source_records"])
    identical = result["quality"]["identical_rows"]
    assert len(identical) == 31
    assert sum(len(group["source_records"]) for group in identical) == 65
    assert available - conservative == {number for group in identical for number in group["available_source_records"]}
    by_number = {row["source_record"]: row for row in result["records"]}
    for group in identical:
        raw = [tuple(by_number[n]["cells"][field]["raw"] for field in spice.SOURCE_COLUMNS) for n in group["source_records"]]
        assert len(set(raw)) == 1
        assert all(by_number[n]["identical_source_row"] for n in group["source_records"])


def test_repeated_time_labels_and_conditions_do_not_trigger_deduplication(result):
    conservative = set(result["cohorts"]["conservative"]["source_records"])
    repeated_times = result["quality"]["repeated_time_references"]
    repeated_conditions = result["quality"]["repeated_primary_conditions"]
    assert len(repeated_times) == 112
    assert len(repeated_conditions) == 44
    assert sum(len(conservative.intersection(group["source_records"])) > 1 for group in repeated_conditions) == 16
    assert any(len(conservative.intersection(group["source_records"])) > 1 for group in repeated_times)
    row = next(row for row in result["records"] if row["cells"]["gmt_ignition"]["raw"] == "1744")
    assert row["cells"]["gmt_ignition"]["status"] == "ambiguous"
    assert row["time_reference"] is None
    assert "compact_ignition_time" in row["quality_flags"]


def test_signed_air_and_zero_fuel_are_retained_and_traceable(result):
    negatives = [row for row in result["records"] if "negative_air_rate" in row["review_flags"]]
    zeros = [row for row in result["records"] if "zero_fuel_rate" in row["review_flags"]]
    assert [row["source_record"] for row in negatives] == [295, 297, 298, 299, 300, 336, 337, 338]
    assert [row["source_record"] for row in zeros] == [402]
    assert all(row["air_rate_sign"] == "negative" and Decimal(row[spice.AIR]) < 0 for row in negatives)
    assert zeros[0]["fuel_rate_sign"] == "zero"
    assert set(result["quality"]["flow_review_records"]).issubset(result["cohorts"]["conservative"]["source_records"])


@pytest.mark.parametrize(("status", "value", "expected"), [
    ("exact", Decimal("-5.92"), "exact"), ("exact", Decimal("0"), "exact"),
    ("exact", Decimal("NaN"), "invalid_numeric_value"), ("exact", 0.5, "invalid_numeric_value"),
    ("approximate", Decimal("2"), "approximate"), ("ambiguous", None, "ambiguous"),
    ("blank", None, "blank"), (None, None, "missing_measurement"),
])
def test_numeric_selection_uses_exact_state_and_decimal_values(status, value, expected):
    assert spice._status({"status": status, "value": value}) == expected


def test_apparent_numeric_values_on_nonexact_cells_are_excluded(result):
    original = result["records"][0]
    columns = result["dataset"]["columns"]
    cells = deepcopy(original["cells"])
    for name in spice.NUMERIC:
        value = cells[name]["value"]
        cells[name]["value"] = Decimal(value) if value is not None else None
    cells[spice.AIR].update(status="approximate", raw="~4", value=Decimal("4"))
    rows, available, conservative, exclusions, _, _ = spice._assess_rows([(1, [], cells)], columns, "test")
    assert available == conservative == []
    assert exclusions == [{"source_record": 1, "dataset_sha256": "test", "reasons": {spice.AIR: "approximate"}}]
    assert rows[0][spice.AIR] is None
    assert rows[0]["cells"][spice.AIR]["raw"] == "~4"


def test_groups_keep_source_fuels_nozzle_units_and_association_scope(result):
    groups = result["cohorts"]["available"]["grouped_results"]
    assert [*groups["nozzle"]] == ["0.4064", "0.7620", "1.6002"]
    assert [item["record_count"] for item in groups["nozzle"].values()] == [169, 114, 161]
    assert groups["fuel"]["75 % Propylene"]["record_count"] == 110
    assert groups["fuel"]["75% Propylene"]["record_count"] == 16
    by_fuel = groups["nozzle"]["0.4064"]["by_fuel"]
    assert by_fuel["Propylene"]["association"] == {
        "variables": [spice.AIR, spice.FUEL_RATE], "units": ["cm/s", "mg/s"],
        "record_count": 44, "pearson_r": "0.4044",
    }
    better = result["cohorts"]["conservative"]["grouped_results"]["nozzle"]["0.4064"]["by_fuel"]["Propylene"]
    assert (better["record_count"], better["association"]["pearson_r"]) == (42, "0.4132")
    assert by_fuel["Methane"]["association"] is None
    assert groups["air_rate_sign"]["negative"]["statistics"][spice.AIR]["unit"] == "cm/s"
    assert spice._pearson([{spice.AIR: Decimal("1"), spice.FUEL_RATE: Decimal(i)} for i in range(5)]) is None


def test_provenance_determinism_and_serializable_plot_data(dataset_dir, result):
    with localcontext() as context:
        context.prec = 3
        assert spice.analyze_parquet(dataset_dir) == result
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    dataset = result["dataset"]
    assert (dataset["psi_code"], dataset["doi"]) == ("PSI-107", "10.60555/9kbh-e962")
    assert dataset["relative_path"] == spice.SOURCE.as_posix()
    assert dataset["sha256"] == sha256((dataset_dir / spice.SOURCE).read_bytes()).hexdigest()
    assert dataset["nasa_psi_url"].endswith("/PSI-107")
    assert all(row["dataset_sha256"] == dataset["sha256"] for row in result["records"])
    assert dataset["columns"]["gmt_flame_off"]["source_header"] == "GMT  Flame Off "
    assert dataset["columns"][spice.AIR] == {
        "ordinal": 9, "source_header": "Air Rate (cm/s)", "unit": "cm/s", "type": "decimal",
    }
    assert dataset["columns"]["fuel_rate_sccm"]["unit"] == "sccm"
    assert result["plots"]["points"]["cohort_selection"] == "cohorts.*.source_records"


def test_rejects_parquet_manifest_drift(dataset_dir, monkeypatch):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[spice.SOURCE.as_posix()]["sha256"] = "0" * 64
    monkeypatch.setattr(spice, "read_manifest", lambda _: manifest)
    with pytest.raises(ValueError, match="source_sha256"):
        spice.analyze_parquet(dataset_dir)


def test_rejects_changed_air_speed_unit(result):
    columns = result["dataset"]["columns"]
    fields = [(m["ordinal"], field, m["source_header"], "m/s" if field == spice.AIR else m["unit"], m["type"])
              for field, m in columns.items()]
    with pytest.raises(ValueError, match=spice.AIR):
        spice._columns(fields, len(fields))


def test_parameterized_selects_match_parquet_for_explicit_version(simulated_database, dataset_dir, result):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    source = next(item for item in discover_sources(dataset_dir) if item.path == spice.SOURCE)
    dataset = loader.prepare_dataset(dataset_dir, source, manifest[source.path.as_posix()])
    record = result["cohorts"]["conservative"]["source_records"][0]
    ordinal = result["dataset"]["columns"][spice.AIR]["ordinal"]
    other = replace(dataset, sha256="0" * 64,
                    measurements=[row for row in dataset.measurements if row[:2] != (record, ordinal)])
    assert loader.load_datasets([other, dataset], "simulated") == 2
    queries = []

    class ReadCursor(SimulatedCursor):
        def execute(self, statement, params):
            assert statement.lstrip().startswith("SELECT")
            assert statement.count("%s") == len(params)
            queries.append((statement, params))
            super().execute(statement, params)

        def fetchall(self):
            names = [column[0] for column in self.cursor.description]
            return [dict(zip(names, row, strict=True)) for row in super().fetchall()]

    class Connection:
        def cursor(self, *, row_factory):
            return ReadCursor(simulated_database.cursor())

    simulated_database.execute("PRAGMA query_only = ON")
    connection = Connection()
    assert spice.analyze_postgres(connection, dataset.sha256) == result
    assert queries[0] == (spice.SELECT_COLUMNS, (spice.STUDY, spice.SOURCE.as_posix(), dataset.sha256))
    alternate = spice.analyze_postgres(connection, other.sha256)
    assert alternate["cohorts"]["available"]["record_count"] == 443
    assert alternate["cohorts"]["conservative"]["record_count"] == 386
    assert alternate["cohorts"]["available"]["excluded_by_field_reason"]["air_rate_cm_s:missing_measurement"] == 1
    with pytest.raises(ValueError, match="not visible"):
        spice.analyze_postgres(connection, "1" * 64)
