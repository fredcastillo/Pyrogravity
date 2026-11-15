import csv
import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pyarrow.parquet as pq
import pytest

from data.src.etl.nasa_etl import BASS_II, DATA_DIR, FLEX, TEXT, discover_sources, run_etl, transform
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
    sources = discover_sources()
    hashes_before = {
        source.path: sha256((DATA_DIR / source.path).read_bytes()).hexdigest()
        for source in sources
    }
    with TemporaryDirectory(dir=DATA_DIR) as directory:
        output = Path(directory)
        manifest = output / "source_manifest.csv"
        initial = run_etl(output_dir=output, manifest_path=manifest)
        assert {file.stem for file in output.glob("*.parquet")} == {source.output_name for source in sources}
        for source in sources:
            path = output / f"{source.output_name}.parquet"
            expected = initial[source.output_name]
            assert pq.read_table(path).equals(expected, check_metadata=True)
            pd.testing.assert_frame_equal(pd.read_parquet(path), expected.to_pandas())

        manifest_before = manifest.read_bytes()
        repeated = run_etl(output_dir=output, manifest_path=manifest)
        assert manifest.read_bytes() == manifest_before
        for name, table in repeated.items():
            assert table.equals(initial[name], check_metadata=True)
            assert pq.read_table(output / f"{name}.parquet").equals(table, check_metadata=True)

        expected_units = {
            "psi-69_flex": {"burning_rate": b"mm", "ambient_pressure": b"mmHg", "burn_time": b"s"},
            "psi-25_bass_ii": {"calibrated_final_o2": b"% by vol", "final_co": b"ppm"},
            "psi-100_saffire_3": {"sample_thickness": b"cm", "air_flow": b"cm/s"},
        }
        for name, units in expected_units.items():
            schema = pq.read_schema(output / f"{name}.parquet")
            for column, unit in units.items():
                assert schema.field(column).metadata[b"source_unit"] == unit

    for path, digest in hashes_before.items():
        assert sha256((DATA_DIR / path).read_bytes()).hexdigest() == digest


def test_discovers_all_tables_without_merging_same_investigation():
    sources = discover_sources()
    assert {source.path for source in sources} == {
        path.relative_to(DATA_DIR) for path in (DATA_DIR / "raw").glob("*.csv")
    }
    assert len(sources) == len({source.output_name for source in sources}) == 21
    assert len({source.study for source in sources}) == 19
    for study in ("PSI-10", "PSI-159"):
        matching = [source.output_name for source in sources if source.study == study]
        assert len(matching) == 2
        assert any("normal" in name for name in matching)
        assert any("inverse" in name for name in matching)


@pytest.fixture(scope="module")
def nasa_outputs():
    with TemporaryDirectory(dir=DATA_DIR) as directory:
        output = Path(directory)
        manifest = output / "source_manifest.csv"
        tables = run_etl(output_dir=output, manifest_path=manifest)
        with manifest.open(encoding="utf-8", newline="") as stream:
            entries = list(csv.DictReader(stream))
        yield tables, entries


def test_manifest_and_parquet_preserve_every_input_header_and_value(nasa_outputs):
    tables, manifest = nasa_outputs
    assert len(manifest) == len(tables) == 21
    assert {entry["encoding"] for entry in manifest} == {"cp1252", "utf-8", "utf-8-sig"}
    assert {entry["delimiter"] for entry in manifest} == {","}
    for source, entry in zip(discover_sources(), manifest, strict=True):
        path = DATA_DIR / source.path
        encoding = {"PSI-69": "cp1252", "PSI-25": "utf-8-sig", "PSI-26": "utf-8-sig"}.get(
            source.study, "utf-8"
        )
        with path.open(encoding=encoding, newline="") as stream:
            header, *rows = csv.reader(stream, strict=True)
        table = tables[source.output_name]
        assert entry["source_filename"] == path.name
        assert entry["psi_code"] == source.study
        assert entry["relative_path"] == source.path.as_posix()
        assert entry["parquet_filename"] == f"{source.output_name}.parquet"
        assert entry["investigation_name"]
        assert entry["nasa_psi_url"].endswith(f"/{source.study}")
        assert entry["validation_status"] in {"validated", "validated_with_flags"}
        assert entry["sha256"] == sha256(path.read_bytes()).hexdigest()
        assert table.schema.metadata[b"source_sha256"].decode() == entry["sha256"]
        assert int(entry["row_count"]) == len(rows) == table.num_rows
        assert int(entry["column_count"]) == len(header)
        assert table["source_record"].to_pylist() == list(range(1, len(rows) + 1))
        assert set(table["source_study"].to_pylist()) == {source.study}

        fields = [field for field in table.schema if field.metadata and b"source_header" in field.metadata]
        assert [field.metadata[b"source_header"].decode() for field in fields] == header
        for field, originals in zip(fields, zip(*rows), strict=True):
            name = field.name if field.type == TEXT else f"{field.name}_raw"
            assert table[name].to_pylist() == list(originals)
            if field.type == TEXT:
                continue
            unit = field.metadata.get(b"source_unit", b"").decode()
            statuses = table[f"{field.name}_status"].to_pylist()
            for value, status, original in zip(table[field.name].to_pylist(), statuses, originals):
                if status == "exact":
                    number_text = original.strip().removesuffix(unit).rstrip() if unit else original.strip()
                    assert value == Decimal(number_text)
                else:
                    assert value is None


def test_preserves_new_special_values_and_sparse_rows(nasa_outputs):
    tables, _ = nasa_outputs
    saffire = tables["psi-99_saffire_2"].to_pylist()
    assert saffire[3]["samle_thickness"] == "037 mm"
    assert saffire[3]["samle_thickness_status"] == "ambiguous"
    assert saffire[4]["g_spread_length_status"] == "ambiguous"
    assert saffire[4]["g_spread_length"] == "2.1 mm/s"
    assert saffire[0]["percent_o2_note_1_status"] == "approximate"
    assert saffire[0]["percent_o2_note_1"] is None
    assert saffire[0]["air_flow_cm_s_raw"] == "20 cm/s"
    assert saffire[0]["air_flow_cm_s"] == Decimal("20")
    assert saffire[6]["g_spread_length_status"] == "missing_marker"

    flex2 = tables["psi-68_flex2"].to_pylist()[0]
    assert flex2["flow_velocity_cm_s_status"] == "range"
    assert flex2["oxygen_mole_fraction_status"] == "multiple_values"
    assert flex2["ambient_temperature_c"] == Decimal("25")

    cfi = tables["psi-159_cfi_g_inverse_flames"].to_pylist()
    assert cfi[94]["peak_burner_temp_k_raw"] == "#VALUE!"
    assert cfi[94]["peak_burner_temp_k_status"] == "source_error"
    assert cfi[0]["approx_p_bar_status"] == "approximate"
    assert cfi[0]["approx_p_bar"] is None
    inverse = next(source for source in discover_sources() if source.output_name == "psi-159_cfi_g_inverse_flames")
    with (DATA_DIR / inverse.path).open(encoding="utf-8", newline="") as stream:
        _, *rows = csv.reader(stream)
    assert ["empty_record" in row["anomalies"] for row in cfi] == [
        not any(cell.strip() for cell in row) for row in rows
    ]

    e_field = tables["psi-22_acme_e_field_flames"].to_pylist()
    assert e_field[2]["test_day"] == ""
    assert e_field[2]["fuel_conc"] == Decimal("100")
    assert "missing_primary_identifier" in e_field[2]["anomalies"]
    assert "repeated_test_day" in e_field[24]["anomalies"]

    spice = tables["psi-107_spice"].to_pylist()
    assert spice[52]["gmt_ignition"] == "1744"
    assert spice[52]["gmt_ignition_status"] == "ambiguous"


def test_manifest_counts_source_rows_and_keeps_empty_rows(nasa_outputs):
    tables, entries = nasa_outputs
    total_rows = total_empty = total_flagged = 0
    for entry in entries:
        path = DATA_DIR / entry["relative_path"]
        with path.open(encoding=entry["encoding"], newline="") as stream:
            reader = csv.reader(stream, delimiter=entry["delimiter"])
            next(reader)
            empty = [not any(cell.strip() for cell in row) for row in reader]
        table = tables[Path(entry["parquet_filename"]).stem]
        flags = table["anomalies"].to_pylist()
        candidates = table["quantitative_candidate"].to_pylist()
        assert table["source_row_empty"].to_pylist() == empty
        assert ["empty_record" in row_flags for row_flags in flags] == empty
        assert all(not is_empty or not candidate for is_empty, candidate in zip(empty, candidates))
        assert int(entry["row_count"]) == len(empty) == table.num_rows
        assert int(entry["empty_row_count"]) == sum(empty)
        assert int(entry["informative_row_count"]) == len(empty) - sum(empty)
        assert int(entry["flagged_row_count"]) == sum(map(bool, flags))
        assert int(entry["quantitative_candidate_row_count"]) == sum(candidates)
        total_rows += len(empty)
        total_empty += sum(empty)
        total_flagged += sum(map(bool, flags))
    assert len(entries) == 21
    assert (total_rows, total_empty, total_flagged) == (2862, 861, 1039)
    inverse = tables["psi-159_cfi_g_inverse_flames"]
    assert inverse["source_row_empty"].to_pylist() == [False] * 154 + [True] * 861


def test_quantitative_candidates_require_specific_evidence(nasa_outputs):
    tables, entries = nasa_outputs
    for entry in entries:
        table = tables[Path(entry["parquet_filename"]).stem]
        rule = json.loads(table.schema.metadata[b"quantitative_candidate_criteria"])
        source_columns = {
            field.metadata[b"source_header"].decode(): field.name
            for field in table.schema if field.metadata and b"source_header" in field.metadata
        }
        required = {
            **{header: "text" for header in rule["required_context_headers"]},
            **{header: "exact" for header in rule["required_exact_value_headers"]},
        }
        expected = [
            bool(rule["required_exact_value_headers"])
            and not row["source_row_empty"]
            and all(row[f"{source_columns[header]}_status"] == status for header, status in required.items())
            and not set(rule["blocking_anomaly_flags"]).intersection(row["anomalies"])
            for row in table.to_pylist()
        ]
        assert table["quantitative_candidate"].to_pylist() == expected
        status = "has_candidates" if any(expected) else "insufficient_values"
        if not rule["required_exact_value_headers"]:
            status = "limited_to_source_scope"
        assert entry["quantitative_status"] == status

    flex = tables["psi-69_flex"].to_pylist()
    assert flex[69]["quantitative_candidate"] and flex[69]["anomalies"]
    assert not flex[8]["quantitative_candidate"] and not flex[8]["anomalies"]
    assert flex[222]["burn_time_status"] == "approximate"
    assert not flex[222]["quantitative_candidate"]

    bass = tables["psi-25_bass_ii"].to_pylist()
    assert bass[1]["final_co2_status"] == "blank"
    assert not bass[1]["quantitative_candidate"] and not bass[1]["anomalies"]
    assert bass[3]["quantitative_candidate"] and "initial_co_outside_sensor_range" in bass[3]["anomalies"]

    saffire = tables["psi-99_saffire_2"]["quantitative_candidate"].to_pylist()
    assert sum(saffire) == 3 and not any(saffire[9:])
    assert not any(tables["psi-20_acme_bre"]["quantitative_candidate"].to_pylist())
