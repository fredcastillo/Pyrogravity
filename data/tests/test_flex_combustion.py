import json
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from data.src.analysis import flex_combustion as flex
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, FLEX, discover_sources
from test_nasa_loader import SimulatedCursor, etl_outputs, simulated_database


@pytest.fixture(scope="module")
def dataset_dir(request):
    if (DATA_DIR / "processed" / "psi-69_flex.parquet").is_file():
        return DATA_DIR
    return request.getfixturevalue("etl_outputs")


@pytest.fixture(scope="module")
def result(dataset_dir):
    return flex.analyze_parquet(dataset_dir)


def test_reference_population_and_statistics(result):
    assert (result["trial_count"], result["valid_pair_count"], result["excluded_count"]) == (274, 256, 18)
    records = result["pairs"] + result["exclusions"]
    assert sorted(record["source_record"] for record in records) == list(range(1, 275))
    assert result["statistics"] == {
        "droplet_initial_diameter": {"minimum": "1.10", "q1": "2.5775", "median": "3.01", "q3": "3.5125", "maximum": "4.53"},
        "burn_time": {"minimum": "0.30", "q1": "5.50", "median": "10.10", "q3": "15.60", "maximum": "39.20"},
        "pearson_r": "0.5366",
    }
    assert all(Decimal(row["ambient_pressure"]) > 0 for row in result["pairs"])
    assert all(row["readings"][name]["status"] == "exact" for row in result["pairs"] for name in flex.NUMERIC_FIELDS)


def test_keeps_fuel_and_termination_groups(result):
    groups = result["grouped_results"]
    assert result["termination_counts"] == {"Completion": 26, "Disruption": 54, "Extinction": 176}
    assert groups["Heptane"]["valid_pair_count"] == 104
    assert groups["Methanol"]["valid_pair_count"] == 152
    assert groups["Heptane"]["termination_counts"] == {"Completion": 18, "Disruption": 31, "Extinction": 55}
    assert groups["Methanol"]["termination_counts"] == {"Completion": 8, "Disruption": 23, "Extinction": 121}
    for fuel, group in groups.items():
        for label, summary in group["by_test_end"].items():
            assert summary["source_records"] == [
                row["source_record"] for row in result["pairs"] if (row["fuel"], row["test_end"]) == (fuel, label)
            ]
    assert groups["Heptane"]["by_test_end"]["Extinction"]["statistics"]["burn_time"]["median"] == "4.50"


def test_reference_conditions_preserve_original_composition_labels(result):
    reference = result["condition_comparison"]
    assert reference["recorded_composition"] == {"O": "0.21", "N": "0.79", "CO": "0", "He": "0"}
    assert reference["pressure_unit"] == "mmHg"
    assert reference["pressure_range_inclusive"] == ["740", "780"]
    assert reference["valid_pair_count"] == 27
    assert reference["termination_counts"] == {"Completion": 4, "Disruption": 9, "Extinction": 14}
    assert reference["grouped_results"]["Heptane"]["termination_counts"]["Extinction"] == 5
    assert reference["grouped_results"]["Methanol"]["termination_counts"]["Extinction"] == 9
    assert reference["source_records"] == [
        row["source_record"] for row in result["pairs"] if 740 <= Decimal(row["ambient_pressure"]) <= 780
        and tuple(map(Decimal, row["recorded_composition"].values())) == (Decimal("0.21"), Decimal("0.79"), 0, 0)
    ]


def test_reference_pressure_window_includes_both_boundaries(result):
    original = result["pairs"][0]
    rows = []
    for number, pressure in enumerate(("739.99", "740", "780", "780.01"), start=1):
        row = {"source_record": number, "anomalies": []}
        for name in flex.TEXT_FIELDS:
            row[name] = str(number) if name in ("flex_test_number", "flex_identifier") else original[name]
            row[f"{name}_status"] = "text"
        values = {flex.DIAMETER: "2.10", flex.DURATION: "0.30", flex.PRESSURE: pressure,
                  **{name: str(flex.REFERENCE_COMPOSITION[label]) for label, name in flex.COMPOSITION_NAMES.items()}}
        for name, value in values.items():
            row[name], row[f"{name}_raw"], row[f"{name}_status"] = Decimal(value), value, "exact"
        rows.append(row)
    assert flex._summarize(rows)["condition_comparison"]["source_records"] == [2, 3]
    rows[3]["flex_test_number"] = rows[2]["flex_test_number"]
    repeated = flex._summarize(rows)
    assert repeated["repeated_identifiers"]["flex_test_number"] == {"3": [3, 4]}
    assert repeated["condition_comparison"]["source_records"] == [2]


def test_exclusion_trace_keeps_repeated_ids_and_missing_cells(result):
    assert result["repeated_identifiers"] == {"flex_identifier": {"193F001": [70, 73]}, "flex_test_number": {}}
    excluded = {row["source_record"]: row for row in result["exclusions"]}
    assert [excluded[n]["readings"]["burn_time"]["value"] for n in (70, 73)] == ["1.60", "1.50"]
    assert excluded[70]["reasons"] == excluded[73]["reasons"] == {"flex_identifier": "repeated_identifier"}
    assert excluded[114]["reasons"] == {"ambient_pressure": "nonpositive"}
    assert excluded[223]["readings"]["burn_time"] == {"value": None, "raw": "~6", "status": "approximate"}
    assert excluded[9]["reasons"] == {"droplet_initial_diameter": "blank", "burn_time": "blank"}
    assert result["excluded_by_field_reason"]["droplet_initial_diameter:missing_marker"] == 6


@pytest.mark.parametrize(("field", "status", "value", "reason"), [
    (flex.DIAMETER, "exact", Decimal("0.01"), None),
    (flex.DURATION, "exact", Decimal("0"), "nonpositive"),
    (flex.PRESSURE, "exact", Decimal("-0.01"), "nonpositive"),
    (flex.PRESSURE, "exact", Decimal("NaN"), "invalid_numeric_value"),
    (flex.DIAMETER, "ambiguous", Decimal("1.20"), "ambiguous"),
    (flex.DURATION, None, None, "missing_measurement"),
    (flex.COMPOSITION_NAMES["CO"], "exact", Decimal("0"), None),
    (flex.COMPOSITION_NAMES["N"], "exact", Decimal("1"), None),
    (flex.COMPOSITION_NAMES["O"], "exact", Decimal("1.01"), "outside_fraction_range"),
    (flex.COMPOSITION_NAMES["He"], "approximate", None, "approximate"),
])
def test_numeric_selection_rules(field, status, value, reason):
    assert flex._reading_exclusion(field, {"status": status, "value": value}) == reason


def test_decimal_calculations_ignore_callers_precision(dataset_dir, result):
    with localcontext() as context:
        context.prec = 3
        assert flex.analyze_parquet(dataset_dir) == result
    assert flex._pearson([Decimal("1")] * 3, [Decimal("1"), Decimal("2"), Decimal("3")]) is None


def test_serializable_units_plots_and_provenance(dataset_dir, result):
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    source = result["dataset"]
    assert source["psi_code"] == "PSI-69"
    assert source["relative_path"] == FLEX.source.as_posix()
    assert source["nasa_psi_url"] == "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"
    assert source["sha256"] == sha256((dataset_dir / FLEX.source).read_bytes()).hexdigest()
    assert source["columns"][flex.DIAMETER] == {
        "ordinal": 11, "source_header": "Droplet initial diameter; mm", "unit": "mm", "type": "decimal",
    }
    assert source["columns"][flex.DURATION]["source_header"] == "Burn time; s"
    assert source["columns"][flex.COMPOSITION_NAMES["CO"]]["source_header"].startswith("CO ")
    assert "burning_rate" not in source["columns"]
    assert result["plots"]["scatter"]["x_unit"] == "mm"
    assert result["plots"]["by_termination"]["unit"] == "s"
    assert result["plots"]["condition_comparison"]["selection"] == "condition_comparison.source_records"


def test_parquet_rejects_mismatching_manifest_version(dataset_dir, monkeypatch):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[FLEX.source.as_posix()]["sha256"] = "0" * 64
    monkeypatch.setattr(flex, "read_manifest", lambda _: manifest)
    with pytest.raises(ValueError, match="source_sha256"):
        flex.analyze_parquet(dataset_dir)


def test_parameterized_selects_match_parquet_and_select_correct_version(simulated_database, dataset_dir, result):
    source = next(item for item in discover_sources(dataset_dir) if item.path == FLEX.source)
    entry = loader.read_manifest(dataset_dir / "source_manifest.csv")[source.path.as_posix()]
    dataset = loader.prepare_dataset(dataset_dir, source, entry)
    record = result["pairs"][0]["source_record"]
    ordinal = result["dataset"]["columns"][flex.DURATION]["ordinal"]
    other = replace(dataset, sha256="0" * 64,
                    measurements=[row for row in dataset.measurements if row[:2] != (record, ordinal)])
    assert loader.load_datasets([other, dataset], "simulated") == 2

    class ReadCursor(SimulatedCursor):
        def execute(self, statement, params):
            assert statement.lstrip().startswith("SELECT")
            super().execute(statement, params)

        def fetchall(self):
            names = [column[0] for column in self.cursor.description]
            return [dict(zip(names, row, strict=True)) for row in super().fetchall()]

    class Connection:
        def cursor(self, *, row_factory):
            return ReadCursor(simulated_database.cursor())

    simulated_database.execute("PRAGMA query_only = ON")
    connection = Connection()
    assert flex.analyze_postgres(connection, dataset.sha256) == result
    other_result = flex.analyze_postgres(connection, other.sha256)
    assert other_result["valid_pair_count"] == 255
    assert other_result["excluded_by_field_reason"]["burn_time:missing_measurement"] == 1
    with pytest.raises(ValueError, match="missing or not visible"):
        flex.analyze_postgres(connection, "1" * 64)
