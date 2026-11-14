import csv
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pyarrow.parquet as pq
import pytest

from data.src.etl.nasa_etl import BASS_II, DATA_DIR, FLEX, TEXT, run_etl, transform
from data.src.ingestion.nasa_csv import read_nasa_csv


@pytest.mark.parametrize(
    ("dataset", "encoding", "row_count", "column_count", "identifier_columns"),
    [
        (FLEX, "cp1252", 274, 15, {0: "flex_test_number", 1: "flex_identifier"}),
        (BASS_II, "utf-8-sig", 129, 17, {1: "test_number", 4: "sample_number"}),
    ],
)
def test_preserves_every_source_cell(dataset, encoding, row_count, column_count, identifier_columns):
    source = DATA_DIR / dataset.source
    content = source.read_bytes()
    if dataset == FLEX:
        assert b"\x96" in content
        with pytest.raises(UnicodeDecodeError):
            content.decode("utf-8")
    else:
        assert content.startswith(b"\xef\xbb\xbfPI,")

    with source.open(encoding=encoding, newline="") as stream:
        header, *rows = csv.reader(stream)
    table = transform(dataset, DATA_DIR)

    assert len(header) == column_count
    assert len(rows) == table.num_rows == row_count
    assert table["source_record"].to_pylist() == list(range(1, row_count + 1))
    assert set(table["source_study"].to_pylist()) == {dataset.study}
    assert table.schema.metadata[b"source_path"].decode() == dataset.source.as_posix()
    assert table.schema.metadata[b"source_encoding"].decode() == encoding
    assert table.schema.metadata[b"source_sha256"].decode() == sha256(content).hexdigest()
    for index, name in identifier_columns.items():
        assert table[name].to_pylist() == [row[index] for row in rows]

    for column, original_header, originals in zip(dataset.columns, header, zip(*rows)):
        assert table.schema.field(column.name).metadata[b"source_header"].decode() == original_header
        if column.kind == TEXT:
            assert table[column.name].to_pylist() == list(originals)
            continue

        assert table[f"{column.name}_raw"].to_pylist() == list(originals)
        values = table[column.name].to_pylist()
        statuses = table[f"{column.name}_status"].to_pylist()
        for value, status, original in zip(values, statuses, originals):
            if status == "exact":
                assert value == Decimal(original)
            else:
                assert value is None


def test_rejects_unexpected_header_and_record_count():
    source = DATA_DIR / FLEX.source
    headers = tuple(column.header for column in FLEX.columns)
    with pytest.raises(ValueError, match="unexpected header"):
        read_nasa_csv(source, FLEX.encoding, headers[::-1], 274)
    with pytest.raises(ValueError, match="found 274 records; expected 275"):
        read_nasa_csv(source, FLEX.encoding, headers, 275)


def test_flex_special_cells_and_anomalies():
    table = transform(FLEX, DATA_DIR)
    records = {row["flex_test_number"]: row for row in table.to_pylist()}
    for test, original in (("223", "~6"), ("224", "~9")):
        assert records[test]["burn_time_raw"] == original
        assert records[test]["burn_time_status"] == "approximate"
        assert records[test]["burn_time"] is None

    dash_rows = [row for row in records.values() if row["droplet_initial_diameter_raw"] == "\u2013"]
    assert len(dash_rows) == 6
    assert all(row["droplet_initial_diameter_status"] == "missing_marker" for row in dash_rows)
    assert records["9"]["test_gmt"] == ""
    assert records["9"]["test_gmt_status"] == "blank"
    assert records["1"]["test_gmt"] == "17:22:03"
    assert records["114"]["ambient_pressure"] == 0
    assert "nonpositive_ambient_pressure" in records["114"]["anomalies"]
    for test in ("70", "73"):
        assert records[test]["flex_identifier"] == "193F001"
        assert "repeated_flex_identifier" in records[test]["anomalies"]


def test_bass_special_cells_and_anomalies():
    table = transform(BASS_II, DATA_DIR)
    records = {row["test_number"]: row for row in table.to_pylist()}
    for test, name, original, status in [
        ("B2", "total_frames_shot", "none", "missing_marker"),
        ("B2", "final_co2", "", "blank"),
        ("M5", "final_co", ">500", "bound"),
        ("O12", "final_co", "OR", "annotation"),
        ("O13b", "final_co", "over", "annotation"),
        ("M10", "radiometer_gain", "250  50  250", "multiple_values"),
        ("T15", "fan_display", "80122", "ambiguous"),
    ]:
        assert records[test][f"{name}_raw"] == original
        assert records[test][f"{name}_status"] == status
        assert records[test][name] is None

    assert records["B1"]["sample_number"] == "147"
    assert records["B1"]["initial_co"] == 0
    assert records["B4"]["initial_co"] == -1
    assert "initial_co_outside_sensor_range" in records["B4"]["anomalies"]
    assert records["O10"]["gmt"] == 213
    assert "gmt_date_mismatch" in records["O10"]["anomalies"]
    assert "fan_display_combined_values" in records["T15"]["anomalies"]
    assert records["T28b"]["calibrated_final_o2"] == Decimal("40.4")
    assert "o2_increase_exceeds_sensor_resolution" in records["T28b"]["anomalies"]


def test_parquet_round_trip_and_repeated_run_keep_sources_intact():
    hashes_before = {
        dataset.name: sha256((DATA_DIR / dataset.source).read_bytes()).hexdigest()
        for dataset in (FLEX, BASS_II)
    }
    with TemporaryDirectory(dir=DATA_DIR) as directory:
        output = Path(directory)
        initial = run_etl(output_dir=output)
        assert {file.name for file in output.iterdir()} == {"flex.parquet", "bass_ii.parquet"}
        for dataset in (FLEX, BASS_II):
            path = output / f"{dataset.name}.parquet"
            assert pq.read_table(path).equals(initial[dataset.name], check_metadata=True)
            pd.testing.assert_frame_equal(pd.read_parquet(path), initial[dataset.name].to_pandas())

        repeated = run_etl(output_dir=output)
        for name, table in repeated.items():
            assert table.equals(initial[name], check_metadata=True)
            assert pq.read_table(output / f"{name}.parquet").equals(table, check_metadata=True)

        expected_units = {
            "flex": {"burning_rate": b"mm", "ambient_pressure": b"mmHg", "burn_time": b"s"},
            "bass_ii": {"calibrated_final_o2": b"% by vol", "final_co": b"ppm"},
        }
        for name, units in expected_units.items():
            schema = pq.read_schema(output / f"{name}.parquet")
            for column, unit in units.items():
                assert schema.field(column).metadata[b"source_unit"] == unit

    for dataset in (FLEX, BASS_II):
        assert sha256((DATA_DIR / dataset.source).read_bytes()).hexdigest() == hashes_before[dataset.name]
