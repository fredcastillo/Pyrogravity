import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from data.src.analysis import bass_ii_co2 as co2
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import BASS_II, DATA_DIR, discover_sources
from test_nasa_loader import etl_outputs, simulated_database


@pytest.fixture(scope="module")
def dataset_dir(request):
    manifest = DATA_DIR / "source_manifest.csv"
    parquet = DATA_DIR / "processed" / "psi-25_bass_ii.parquet"
    if manifest.is_file() and parquet.is_file():
        return DATA_DIR
    return request.getfixturevalue("etl_outputs")


@pytest.fixture(scope="module")
def result(dataset_dir):
    return co2.analyze_parquet(dataset_dir)


def test_reproduces_reference_results(result):
    assert (result["trial_count"], result["valid_pair_count"], result["excluded_count"]) == (129, 121, 8)
    assert result["statistics"] == {
        "minimum": "-0.01", "q1": "0.04", "median": "0.24", "q3": "0.62", "maximum": "2.78",
        "positive_count": 113, "negative_count": 2, "zero_count": 6, "below_sensor_resolution_count": 48,
    }
    pairs = result["pairs"]
    assert len({pair["source_record"] for pair in pairs}) == 121
    assert sum(pair["below_sensor_resolution"] for pair in pairs) == 48
    for pair in pairs:
        assert Decimal(pair["delta_co2"]) == Decimal(pair["final_co2"]) - Decimal(pair["initial_co2"])


def test_retains_each_missing_reading_and_its_source(result):
    assert result["excluded_by_reading_reason"] == {
        "final_co2:blank": 1, "final_co2:missing_marker": 5, "initial_co2:missing_marker": 2,
    }
    exclusions = {row["source_record"]: row for row in result["exclusions"]}
    assert set(exclusions) == {2, 14, 25, 77, 96, 97, 127, 128}
    assert exclusions[2]["test_number"] == "B2"
    assert exclusions[2]["readings"]["final_co2"] == {"raw": "", "status": "blank", "value": None}
    assert exclusions[97]["readings"]["initial_co2"] == {
        "raw": "none", "status": "missing_marker", "value": None,
    }


@pytest.mark.parametrize(("status", "value", "reason"), [
    ("exact", Decimal("0"), None),
    ("exact", Decimal("5"), None),
    ("exact", Decimal("-0.01"), "outside_sensor_range"),
    ("exact", Decimal("5.01"), "outside_sensor_range"),
    ("ambiguous", Decimal("0.25"), "ambiguous"),
    ("bound", None, "bound"),
    ("range", None, "range"),
    ("exact", Decimal("NaN"), "invalid_numeric_value"),
    ("exact", 0.25, "invalid_numeric_value"),
    (None, None, "missing_measurement"),
])
def test_requires_unambiguous_in_range_decimal_readings(status, value, reason):
    assert co2._exclusion_reason({"status": status, "value": value}) == reason


def test_precision_and_exact_resolution_boundary():
    row = {name: "sample" for name in co2.CONTEXT}
    row.update({f"{name}_status": "text" for name in co2.CONTEXT})
    row.update(source_record=1, anomalies=[], initial_co2_status="exact", final_co2_status="exact",
               initial_co2_raw="0.10000000000000001", final_co2_raw="0.20000000000000001",
               initial_co2=Decimal("0.10000000000000001"), final_co2=Decimal("0.20000000000000001"))
    dataset = {name: "test" for name in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")}
    with localcontext() as context:
        context.prec = 3
        result = co2._analyze(dataset, 1, {}, [row], pi=None, material=None)
    assert result["pairs"][0]["delta_co2"] == "0.10000000000000000"
    assert result["pairs"][0]["below_sensor_resolution"] is False
    assert result["statistics"]["q1"] == "0.10000000000000000"
    assert result["grouped_results"]["pi"]["sample"]["statistics"] is None


def test_repeated_samples_are_retained_and_grouped(result):
    assert result["distinct_sample_count"] == 107
    all_trials = {row["source_record"]: row for row in result["pairs"] + result["exclusions"]}
    records = result["repeated_samples"]["220m"]
    assert len(records) == 3
    assert len({all_trials[record]["test_number"] for record in records}) == 3
    assert all(all_trials[record]["repeated_sample"] for record in records)
    olson = result["grouped_results"]["pi"]["Olson"]
    assert (olson["trial_count"], olson["valid_pair_count"], olson["distinct_sample_count"]) == (27, 27, 20)
    assert olson["statistics"]["median"] == "0.41"


def test_filters_combine_without_changing_version_or_repeat_detection(dataset_dir, result):
    first = next(row for row in result["pairs"] if row["repeated_sample"])
    material, pi = first["fuel_sample_material"], first["pi"]
    selected = co2.analyze_parquet(dataset_dir, pi=f" {pi} ", material=material)
    assert selected["dataset"] == result["dataset"]
    assert selected["pairs"] == [
        row for row in result["pairs"] if (row["pi"], row["fuel_sample_material"]) == (pi, material)
    ]
    assert first in selected["pairs"]
    assert selected["repeated_samples"][first["sample_number"]] == result["repeated_samples"][first["sample_number"]]
    assert selected["trial_count"] + selected["filtered_out_count"] == 129
    assert selected["trial_count"] == selected["valid_pair_count"] + selected["excluded_count"]
    empty = co2.analyze_parquet(dataset_dir, pi="no matching PI")
    assert empty["trial_count"] == 0 and empty["filtered_out_count"] == 129
    assert empty["statistics"] is None and empty["pairs"] == empty["exclusions"] == []


def test_serializable_provenance_and_plot_contract(dataset_dir, result):
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    source = result["dataset"]
    assert source["psi_code"] == "PSI-25"
    assert source["investigation_name"] == "Burning and Suppression of Solids - II"
    assert source["nasa_psi_url"].endswith("/PSI-25")
    assert source["relative_path"] == BASS_II.source.as_posix()
    assert source["sha256"] == sha256((dataset_dir / BASS_II.source).read_bytes()).hexdigest()
    for field, ordinal, header in (("initial_co2", 14, "Initial CO2 % by vol"),
                                   ("final_co2", 15, "Final CO2 % by vol")):
        assert source["columns"][field] == {"ordinal": ordinal, "source_header": header,
                                             "unit": "% by vol", "type": "decimal"}
    assert result["method_version"] == "1.0.0"
    assert result["plots"]["scatter"]["equality_line"] == [["0", "0"], ["5", "5"]]
    assert result["plots"]["delta_distribution"]["resolution_band"] == ["-0.1", "0.1"]
    assert result["sensor"]["reference_url"].endswith("/20210011385")


def test_rejects_parquet_version_mismatch(dataset_dir, monkeypatch):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[BASS_II.source.as_posix()]["sha256"] = "0" * 64
    monkeypatch.setattr(co2, "read_manifest", lambda path: manifest)
    with pytest.raises(ValueError, match="source_sha256"):
        co2.analyze_parquet(dataset_dir)


def test_parameterized_selects_match_parquet(simulated_database, dataset_dir, result):
    source = next(source for source in discover_sources(dataset_dir) if source.path == BASS_II.source)
    entry = loader.read_manifest(dataset_dir / "source_manifest.csv")[source.path.as_posix()]
    dataset = loader.prepare_dataset(dataset_dir, source, entry)
    first = result["pairs"][0]
    final_ordinal = result["dataset"]["columns"]["final_co2"]["ordinal"]
    other_measurements = [
        (record, ordinal, kind, "missing_marker", None)
        if (record, ordinal) == (first["source_record"], final_ordinal)
        else (record, ordinal, kind, status, value)
        for record, ordinal, kind, status, value in dataset.measurements
    ]
    other_version = replace(dataset, sha256="0" * 64, measurements=other_measurements)
    assert loader.load_datasets([other_version, dataset], "simulated") == 2

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def execute(self, statement, params):
            assert statement.lstrip().startswith("SELECT")
            self.cursor.execute(statement.replace("%s", "?"), params)

        def fetchall(self):
            rows = [dict(row) for row in self.cursor.fetchall()]
            for row in rows:
                for field in ("original_values", "text_cell_statuses", "anomalies"):
                    if field in row:
                        row[field] = json.loads(row[field])
                for field in co2.READINGS:
                    if row.get(field) is not None:
                        row[field] = Decimal(row[field])
            return rows

    class Connection:
        @contextmanager
        def cursor(self, *, row_factory):
            cursor = simulated_database.cursor()
            cursor.row_factory = sqlite3.Row
            try:
                yield Cursor(cursor)
            finally:
                cursor.close()

    simulated_database.execute("PRAGMA query_only = ON")
    connection = Connection()
    assert co2.analyze_postgres(connection, dataset.sha256) == result
    other_result = co2.analyze_postgres(connection, other_version.sha256)
    assert other_result["dataset"]["sha256"] == other_version.sha256
    assert other_result["valid_pair_count"] == result["valid_pair_count"] - 1
    assert co2.analyze_postgres(connection, dataset.sha256, pi="Miller") == co2.analyze_parquet(dataset_dir, pi="Miller")
    with pytest.raises(ValueError, match="missing or not visible"):
        co2.analyze_postgres(connection, "1" * 64)
