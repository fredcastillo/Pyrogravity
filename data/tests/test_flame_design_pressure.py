import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from data.src.analysis import flame_design_pressure as flame
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, discover_sources
from test_nasa_loader import SimulatedCursor, etl_outputs, simulated_database


@pytest.fixture(scope="module")
def dataset_dir(request):
    if (DATA_DIR / "source_manifest.csv").is_file() and all(
        (DATA_DIR / "processed" / f"psi-10_flame_design_{name}_flame.parquet").is_file() for name in flame.PATHS
    ):
        return DATA_DIR
    return request.getfixturevalue("etl_outputs")


@pytest.fixture(scope="module")
def result(dataset_dir):
    return flame.analyze_parquet(dataset_dir)


def test_reference_counts_and_descriptive_statistics(result):
    normal, inverse = (result["configurations"][name] for name in ("normal", "inverse"))
    assert (normal["trial_count"], normal["valid_pair_count"], normal["excluded_count"]) == (207, 187, 20)
    assert (inverse["trial_count"], inverse["valid_pair_count"], inverse["excluded_count"]) == (120, 120, 0)
    assert normal["statistics"] == {
        "minimum": "-0.004082760", "q1": "0.003402300", "median": "0.006804600", "q3": "0.017351730",
        "maximum": "0.030620700", "positive_count": 182, "zero_count": 1, "negative_count": 4,
    }
    assert inverse["statistics"] == {
        "minimum": "0.00272184", "q1": "0.00884598", "median": "0.01122759", "q3": "0.013098855",
        "maximum": "0.08914026", "positive_count": 120, "zero_count": 0, "negative_count": 0,
    }
    for label, configuration in result["configurations"].items():
        for pair in configuration["pairs"]:
            assert pair["configuration"] == label
            assert Decimal(pair["delta_pressure"]) == Decimal(pair["pfinal_atm"]) - Decimal(pair["pinit_atm"])


def test_missing_pressure_fuel_and_day_coverage(result):
    normal, inverse = (result["configurations"][name] for name in ("normal", "inverse"))
    assert normal["excluded_by_field_reason"] == {"pfinal_atm:blank": 20}
    assert {row["fuel"] for row in normal["pairs"]} == {"C2H4"}
    assert all(row["fuel"] == "C3H8" and row["day"] == "13" for row in normal["exclusions"])
    assert all(row["readings"]["pfinal_atm"] == {"raw": "", "status": "blank", "value": None}
               for row in normal["exclusions"])
    assert normal["grouped_results"]["fuel"]["C2H4"]["valid_pair_count"] == 187
    for group in (normal["grouped_results"]["fuel"]["C3H8"], normal["grouped_results"]["day"]["13"]):
        assert (group["trial_count"], group["valid_pair_count"], group["excluded_count"]) == (20, 0, 20)
        assert group["statistics"] is None
        assert group["source_records"] == [row["source_record"] for row in normal["exclusions"]]
    assert list(normal["grouped_results"]["day"]) == list(map(str, range(14)))
    assert list(inverse["grouped_results"]["day"]) == list(map(str, range(1, 9)))
    assert inverse["grouped_results"]["fuel"] == {}
    assert all(row["fuel"] is None for row in inverse["pairs"])


def test_keeps_original_conditions_flags_and_annotations(result):
    normal = result["configurations"]["normal"]
    inverse = result["configurations"]["inverse"]
    assert {pair["conditions"]["xfuel"]["raw"].strip() for pair in normal["pairs"]
            if pair["conditions"]["xfuel"]["status"] == "annotation"} == {"RAMP", "RAMPED"}
    assert {pair["conditions"]["xo2"]["raw"].strip() for pair in inverse["pairs"]
            if pair["conditions"]["xo2"]["status"] == "annotation"} == {"RAMP", "LOW O2"}
    assert inverse["dataset"]["columns"]["mo2_mg_s"]["unit"] == "mg/s"
    assert "pmean_atm" in inverse["pairs"][0]["conditions"]
    assert all(group["repeated_tests"] == {} and group["repeated_source_records"] == []
               for group in (normal, inverse))


@pytest.mark.parametrize(("status", "value", "reason"), [
    ("exact", Decimal("0.000000001"), None),
    ("exact", Decimal("0"), "nonpositive_pressure"),
    ("exact", Decimal("NaN"), "invalid_numeric_value"),
    ("exact", None, "invalid_numeric_value"),
    ("ambiguous", Decimal("0.8"), "ambiguous"),
    ("missing_marker", None, "missing_marker"),
    (None, None, "missing_measurement"),
])
def test_pressure_requires_exact_positive_decimals(status, value, reason):
    assert flame._pressure_exclusion({"status": status, "value": value}) == reason


def test_excludes_duplicate_rows_repeated_tests_and_wrong_configuration(result):
    normal = result["configurations"]["normal"]
    pair = normal["pairs"][0]
    columns = normal["dataset"]["columns"]
    cells = {**pair["readings"], **pair["context"], **pair["conditions"]}
    for name, cell in cells.items():
        if columns[name]["type"] == "decimal" and cell["value"] is not None:
            cells[name] = {**cell, "value": Decimal(cell["value"])}
    moved = deepcopy(cells)
    moved["day"].update(raw="20", value="20")
    invalid = deepcopy(cells)
    invalid["test"].update(raw="", value="", status="blank")
    invalid["flame_type"].update(raw="Inverse", value="Inverse")
    valid = deepcopy(cells)
    valid["test"].update(raw="other test", value="other test")
    rows = [(1, [], cells), (2, [], cells), (3, [], moved), (4, [], invalid), (5, [], valid)]
    actual = flame._analyze_dataset("normal", {**normal["dataset"], "row_count": 5}, columns, rows)
    assert actual["repeated_tests"] == {pair["test"]: [1, 2, 3]}
    assert actual["repeated_source_records"] == [[1, 2]]
    assert actual["excluded_by_field_reason"] == {
        "test:repeated_identifier": 3, "source_record:repeated_source_record": 2,
        "test:missing_or_unusable_identifier": 1, "flame_type:missing_or_mismatched_configuration": 1,
    }
    assert [row["source_record"] for row in actual["pairs"]] == [5]
    assert actual["grouped_results"]["day"][pair["day"]]["statistics"] is None


def test_serialization_trace_and_deterministic_precision(dataset_dir, result):
    with localcontext() as context:
        context.prec = 3
        assert flame.analyze_parquet(dataset_dir) == result
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result["investigation"]["nasa_psi_url"] == "https://psi.nasa.gov/physci/repo/data/investigations/PSI-10"
    for name, configuration in result["configurations"].items():
        source = configuration["dataset"]
        assert source["psi_code"] == "PSI-10" and source["relative_path"] == flame.PATHS[name]
        assert source["sha256"] == sha256((dataset_dir / source["relative_path"]).read_bytes()).hexdigest()
        assert source["columns"]["pinit_atm"]["unit"] == source["columns"]["pfinal_atm"]["unit"] == "atm"
        ordinals = tuple(source["columns"][field]["ordinal"] for field in ("pinit_atm", "pfinal_atm"))
        assert ordinals == {"normal": (11, 12), "inverse": (10, 11)}[name]
        for rows in (configuration["pairs"], configuration["exclusions"]):
            assert all(row["dataset_sha256"] == source["sha256"] for row in rows)
            assert [row["source_record"] for row in rows] == sorted(row["source_record"] for row in rows)
    assert result["plots"]["scatter"]["unit"] == "atm"


@pytest.mark.parametrize("configuration", ("normal", "inverse"))
def test_parquet_rejects_mismatching_manifest_versions(dataset_dir, monkeypatch, configuration):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[flame.PATHS[configuration]]["sha256"] = "0" * 64
    monkeypatch.setattr(flame, "read_manifest", lambda _: manifest)
    with pytest.raises(ValueError, match=f"{configuration}, source_sha256"):
        flame.analyze_parquet(dataset_dir)


def test_rejects_incompatible_pressure_units(result):
    columns = result["configurations"]["normal"]["dataset"]["columns"]
    fields = [
        (metadata["ordinal"], name, metadata["source_header"], "bar" if name == "pfinal_atm" else metadata["unit"],
         metadata["type"])
        for name, metadata in columns.items()
    ]
    with pytest.raises(ValueError, match=r"pressure metadata: normal, pfinal"):
        flame._columns(fields, "normal", len(fields))


def test_parameterized_selects_match_both_parquet_versions(simulated_database, dataset_dir, result):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    sources = {source.path.as_posix(): source for source in discover_sources(dataset_dir) if source.study == "PSI-10"}
    datasets = {name: loader.prepare_dataset(dataset_dir, sources[path], manifest[path])
                for name, path in flame.PATHS.items()}
    inverse = datasets["inverse"]
    ordinal = result["configurations"]["inverse"]["dataset"]["columns"]["pfinal_atm"]["ordinal"]
    other = replace(inverse, sha256="0" * 64,
                    measurements=[row for row in inverse.measurements if row[:2] != (1, ordinal)])
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
    assert flame.analyze_postgres(connection, hashes) == result
    catalog_params = [params for statement, params in queries if statement == flame.SELECT_COLUMNS]
    assert catalog_params == [("PSI-10", path, hashes[name]) for name, path in flame.PATHS.items()]
    changed = flame.analyze_postgres(connection, {**hashes, "inverse": other.sha256})
    assert changed["configurations"]["normal"] == result["configurations"]["normal"]
    assert changed["configurations"]["inverse"]["valid_pair_count"] == 119
    assert changed["configurations"]["inverse"]["excluded_by_field_reason"] == {"pfinal_atm:missing_measurement": 1}
    with pytest.raises(ValueError, match="not visible: inverse"):
        flame.analyze_postgres(connection, {**hashes, "inverse": hashes["normal"]})
