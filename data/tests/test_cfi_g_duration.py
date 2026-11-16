import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from data.src.analysis import cfi_g_duration as cfi
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, discover_sources
from test_nasa_loader import SimulatedCursor, etl_outputs, simulated_database


@pytest.fixture(scope="module")
def dataset_dir(request):
    if (DATA_DIR / "source_manifest.csv").is_file() and all(
        (DATA_DIR / "processed" / f"psi-159_cfi_g_{name}_flames.parquet").is_file() for name in cfi.PATHS
    ):
        return DATA_DIR
    return request.getfixturevalue("etl_outputs")


@pytest.fixture(scope="module")
def result(dataset_dir):
    return cfi.analyze_parquet(dataset_dir)


@pytest.mark.parametrize(("name", "row_count", "empty_count", "trials", "valid", "excluded"), [
    ("normal", 179, 0, 179, 132, 47), ("inverse", 1015, 861, 154, 131, 23),
])
def test_keeps_empty_rows_out_of_trial_denominators(result, name, row_count, empty_count, trials, valid, excluded):
    part = result["configurations"][name]
    assert part["dataset"]["row_count"] == row_count
    assert (part["trial_count"], part["valid_count"], part["excluded_count"]) == (trials, valid, excluded)
    assert part["quality"]["empty_row_count"] == empty_count
    assert [row["source_record"] for row in part["empty_records"]] == list(range(trials + 1, row_count + 1))
    assert all(row["reasons"] == {"source_record": "empty_record"} for row in part["empty_records"])
    assert sorted(row["source_record"] for row in part["included"] + part["exclusions"]) == list(range(1, trials + 1))


@pytest.mark.parametrize(("name", "category", "n", "count", "stats"), [
    ("normal", "SE", 102, 102, ("1", "9", "29.5", "53.25", "304", "48.363")),
    ("normal", "FT", 31, 30, ("13", "34.25", "61.5", "127", "276", "91.767")),
    ("inverse", "SE", 81, 73, ("0.5", "5.0", "9.0", "16.0", "55.0", "13.110")),
    ("inverse", "FT", 58, 58, ("12.0", "43.0", "66.0", "66.0", "152.0", "60.328")),
])
def test_duration_statistics_by_configuration_and_termination(result, name, category, n, count, stats):
    part = result["configurations"][name]
    group = part["grouped_results"]["termination"][category]
    assert (group["trial_count"], group["valid_count"], group["excluded_count"]) == (n, count, n - count)
    assert group["statistics"] == dict(zip(("minimum", "q1", "median", "q3", "maximum", "mean"), stats, strict=True))
    assert part["statistics"] is None
    assert all(row["context"]["hot_ignition"]["raw"].strip().casefold() == "yes" for row in part["included"])


def test_preserves_termination_labels_and_flags_conflicting_notes(result):
    interpretation = result["termination_interpretation"]
    assert interpretation["labels"] == {"SE": "self-extinction", "FT": "flow termination"}
    assert "No verified row-level codebook" in interpretation["verification"]
    assert "No censoring is assigned" in interpretation["censoring"]
    normal = result["configurations"]["normal"]
    assert normal["quality"]["termination_review_records"] == [3, 15]
    review = [row for row in normal["included"] if row["termination_review"]]
    assert [row["source_record"] for row in review] == [3, 15]
    assert all(row["termination"] == "SE" and row["context"]["comments"]["raw"] for row in review)
    assert normal["grouped_results"]["termination"]["-"]["valid_count"] == 0


@pytest.mark.parametrize(("status", "value", "reason"), [
    ("exact", Decimal("0.1"), None), ("exact", Decimal("0"), "zero_duration"),
    ("exact", Decimal("-0.1"), "negative_duration"), ("exact", Decimal("NaN"), "invalid_numeric_value"),
    ("approximate", None, "approximate"), ("ambiguous", Decimal("2"), "ambiguous"),
    ("blank", None, "blank"), (None, None, "missing_measurement"),
])
def test_duration_requires_a_positive_exact_decimal(status, value, reason):
    assert cfi._duration_exclusion({"status": status, "value": value}) == reason


def test_outliers_exclusions_and_spreadsheet_errors_are_traceable(result):
    normal, inverse = (result["configurations"][name] for name in ("normal", "inverse"))
    assert normal["excluded_by_field_reason"] == {
        "burn_time_sec:blank": 4, "burn_time_sec:zero_duration": 42,
        "hot_ignition:not_affirmative": 47, "self_ext_or_flow_term:missing_marker": 46,
    }
    assert inverse["excluded_by_field_reason"] == {
        "burn_time_sec:zero_duration": 15, "hot_ignition:not_affirmative": 23, "self_ext_or_flow_term:missing_marker": 15,
    }
    for part, error_count, outlier_count in ((normal, 4, 14), (inverse, 2, 11)):
        assert part["quality"]["source_error_count"] == error_count
        assert len(part["quality"]["duration_outlier_records"]) == outlier_count
        assert part["quality"]["duration_outlier_records"] == [
            row["source_record"] for row in part["included"] if row["duration_outlier"]
        ]
    assert {r["raw"] for r in normal["quality"]["source_errors"]} == {"#DIV/0!"}
    assert {r["raw"] for r in inverse["quality"]["source_errors"]} == {"#VALUE!"}


def test_temperature_pairs_and_original_units(result):
    normal, inverse = (result["configurations"][name] for name in ("normal", "inverse"))
    assert normal["quality"]["peak_temperature_check"] == {"paired_peak_temperature_columns": False}
    check = inverse["quality"]["peak_temperature_check"]
    assert check["expected_kelvin_offset"] == "273.15"
    assert (check["exact_pair_count"], check["matching_pair_count"], check["mismatches"]) == (151, 151, [])
    row = next(row for row in inverse["included"] if row["source_record"] in check["matching_source_records"])
    celsius, kelvin = (row["conditions"][name] for name in ("peak_burner_temp_c", "peak_burner_temp_k"))
    assert Decimal(kelvin["value"]) - Decimal(celsius["value"]) == Decimal("273.15")
    assert celsius["raw"] and kelvin["raw"]
    assert inverse["dataset"]["columns"]["peak_burner_temp_c"]["unit"] == "C"
    assert inverse["dataset"]["columns"]["peak_burner_temp_k"]["unit"] == "K"
    assert normal["dataset"]["columns"]["tad_k"]["unit"] == "K"


def test_fuel_groups_and_condition_matching(result):
    for name, part in result["configurations"].items():
        assert sum(group["valid_count"] for group in part["grouped_results"]["fuel"].values()) == part["valid_count"]
        comparison = part["condition_comparison"]
        assert comparison["eligible_count"] == comparison["distinct_condition_count"] == part["valid_count"]
        assert comparison["matched_groups"] == []
        original = part["included"][0]
        row = {**original, "duration": Decimal(original["duration"]), "conditions": deepcopy(original["conditions"])}
        for field in cfi.CONDITION_FIELDS[name]:
            row["conditions"][field]["value"] = Decimal(row["conditions"][field]["value"])
        adjacent = {**row, "source_record": 2048, "termination": "FT" if row["termination"] == "SE" else "SE"}
        matched, = cfi._condition_comparison([row, adjacent], name)["matched_groups"]
        assert set(matched["by_termination"]) == {"SE", "FT"}
        different_pressure = deepcopy(adjacent)
        different_pressure["conditions"][cfi.PRESSURE]["raw"] = "~999"
        assert cfi._condition_comparison([row, different_pressure], name)["matched_groups"] == []


def test_synthetic_duplicates_unknown_endpoints_and_wrong_configuration(result):
    normal = result["configurations"]["normal"]
    original = normal["included"][0]
    columns = normal["dataset"]["columns"]
    cells = {**original["context"], **original["conditions"], cfi.DURATION: original["duration_reading"]}
    cells = {name: {**cell, "value": Decimal(cell["value"])}
             if columns[name]["type"] == "decimal" and cell["value"] is not None else cell for name, cell in cells.items()}
    other = deepcopy(cells)
    other["test"].update(raw="other", value="other")
    other["flame_type"].update(raw="Inverse", value="Inverse")
    other[cfi.END].update(raw="unrecognized endpoint", value="unrecognized endpoint")
    rows = [(1, False, [], cells), (2, False, [], cells), (3, False, [], other)]
    result = cfi._analyze_dataset("normal", {**normal["dataset"], "row_count": 3}, columns, rows)
    assert result["quality"]["repeated_tests"] == {original["test"]: [1, 2]}
    assert result["quality"]["repeated_source_records"] == [[1, 2]]
    assert result["valid_count"] == 0
    assert result["exclusions"][2]["reasons"] == {
        cfi.END: "unknown_termination", "flame_type": "missing_or_mismatched_configuration",
    }
    rows[2] = (3, True, [], other)
    with pytest.raises(ValueError, match="empty marker differs"):
        cfi._analyze_dataset("normal", {**normal["dataset"], "row_count": 3}, columns, rows)


def test_provenance_precision_and_serialization(dataset_dir, result):
    with localcontext() as context:
        context.prec = 3
        assert cfi.analyze_parquet(dataset_dir) == result
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result["investigation"]["nasa_psi_url"].endswith("/PSI-159")
    for name, part in result["configurations"].items():
        dataset = part["dataset"]
        assert dataset["dataset_id"] is None
        assert dataset["relative_path"] == cfi.PATHS[name]
        assert dataset["sha256"] == sha256((dataset_dir / dataset["relative_path"]).read_bytes()).hexdigest()
        assert dataset["columns"][cfi.DURATION] == {
            "ordinal": 15, "source_header": "burn time (sec)", "unit": "sec", "type": "decimal",
        }
        for rows in (part["included"], part["exclusions"], part["empty_records"]):
            assert all(row["dataset_sha256"] == dataset["sha256"] for row in rows)
            assert [row["source_record"] for row in rows] == sorted(row["source_record"] for row in rows)


@pytest.mark.parametrize("name", ("normal", "inverse"))
def test_rejects_manifest_hash_drift(dataset_dir, monkeypatch, name):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[cfi.PATHS[name]]["sha256"] = "0" * 64
    monkeypatch.setattr(cfi, "read_manifest", lambda _: manifest)
    with pytest.raises(ValueError, match=f"{name}, source_sha256"):
        cfi.analyze_parquet(dataset_dir)


@pytest.mark.parametrize("name", (cfi.DURATION, "peak_burner_temp_k"))
def test_rejects_unverified_duration_or_temperature_units(result, name):
    columns = result["configurations"]["inverse"]["dataset"]["columns"]
    fields = [(m["ordinal"], field, m["source_header"], "bad" if field == name else m["unit"], m["type"])
              for field, m in columns.items()]
    with pytest.raises(ValueError, match=f"inverse, {name}"):
        cfi._columns(fields, "inverse", len(fields))


def test_parameterized_reads_match_parquet_except_storage_id(simulated_database, dataset_dir, result):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    sources = {source.path.as_posix(): source for source in discover_sources(dataset_dir) if source.study == cfi.STUDY}
    datasets = {name: loader.prepare_dataset(dataset_dir, sources[path], manifest[path]) for name, path in cfi.PATHS.items()}
    other = replace(datasets["inverse"], sha256="0" * 64)
    assert loader.load_datasets([other, *datasets.values()], "simulated") == 3
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
    hashes = {name: dataset.sha256 for name, dataset in datasets.items()}
    actual = cfi.analyze_postgres(connection, hashes)
    for part in actual["configurations"].values():
        assert type(part["dataset"]["dataset_id"]) is int
        part["dataset"]["dataset_id"] = None
    assert actual == result
    assert [params for statement, params in queries if statement == cfi.SELECT_COLUMNS] == [
        (cfi.STUDY, path, hashes[name]) for name, path in cfi.PATHS.items()
    ]
    assert cfi.analyze_postgres(connection, {**hashes, "inverse": other.sha256})["configurations"]["inverse"]["dataset"]["sha256"] == other.sha256
    with pytest.raises(ValueError, match="not visible: inverse"):
        cfi.analyze_postgres(connection, {**hashes, "inverse": hashes["normal"]})
