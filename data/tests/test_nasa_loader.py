import csv
import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from shutil import copytree

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from psycopg.types.json import Jsonb

from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, run_etl


@pytest.fixture(scope="module")
def etl_outputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("nasa_loader")
    copytree(DATA_DIR / "raw", root / "raw")
    run_etl(root)
    return root


@pytest.fixture(scope="module")
def datasets(etl_outputs):
    return loader.prepare_load(etl_outputs)


def test_maps_full_manifest_and_parquet(datasets, etl_outputs):
    manifest = loader.read_manifest(etl_outputs / "source_manifest.csv")
    assert len(datasets) == len(manifest) == 21
    assert len({dataset.investigation[0] for dataset in datasets}) == 19
    assert sum(len(dataset.columns) for dataset in datasets) == 227
    assert sum(len(dataset.records) for dataset in datasets) == 2862
    assert sum(record[3] for dataset in datasets for record in dataset.records) == 861
    assert sum(record[4] for dataset in datasets for record in dataset.records) == 1489
    assert sum(len(dataset.measurements) for dataset in datasets) == 24252
    assert sum(row[3] == "exact" for dataset in datasets for row in dataset.measurements) == 13139

    for dataset in datasets:
        entry = manifest[dataset.relative_path]
        with (etl_outputs / dataset.relative_path).open(encoding=entry["encoding"], newline="") as file:
            header, *originals = list(csv.reader(file, delimiter=entry["delimiter"]))
        assert [column[2] for column in dataset.columns] == header
        assert [record[1] for record in dataset.records] == originals
        records_by_number = {row[0]: row for row in dataset.records}
        columns_by_ordinal = {column[0]: column for column in dataset.columns}
        keys = {(row, ordinal) for row, ordinal, *_ in dataset.measurements}
        assert len(keys) == len(dataset.measurements)
        numeric_ordinals = {ordinal for ordinal, *_, kind in dataset.columns if kind != "text"}
        assert keys == {(number, ordinal) for number in records_by_number for ordinal in numeric_ordinals}
        for number, ordinal, kind, status, value in dataset.measurements:
            assert columns_by_ordinal[ordinal][-1] == kind
            assert (value is not None) == (status == "exact")
            if value is not None:
                assert type(value) is (int if kind == "integer" else Decimal)

    flex = next(dataset for dataset in datasets if dataset.investigation[0] == "PSI-69")
    burn_ordinal = next(column[0] for column in flex.columns if column[1] == "burn_time")
    assert flex.columns[burn_ordinal - 1][3] == "s"
    assert flex.records[222][1][burn_ordinal - 1] == "~6"
    assert (223, burn_ordinal, "decimal", "approximate", None) in flex.measurements
    bass = next(dataset for dataset in datasets if dataset.investigation[0] == "PSI-25")
    fan_ordinal = next(column[0] for column in bass.columns if column[1] == "fan_display")
    fan_record = next(record for record in bass.records if record[1][fan_ordinal - 1] == "80122")
    assert (fan_record[0], fan_ordinal, "decimal", "ambiguous", None) in bass.measurements


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("duplicate", "Duplicate source manifest path"),
        ("incomplete", "exactly the expected NASA datasets"),
        ("wrong_parquet", "does not match the expected source"),
        ("missing_parquet", "Missing Parquet"),
        ("bad_hash", "SHA-256 does not match"),
    ],
)
def test_rejects_invalid_source_inventory(etl_outputs, tmp_path, mutation, expected_error):
    copytree(etl_outputs, tmp_path, dirs_exist_ok=True)
    manifest_path = tmp_path / "source_manifest.csv"
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        rows = list(reader)
    if mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "incomplete":
        rows.pop()
    elif mutation == "wrong_parquet":
        rows[0]["parquet_filename"] = rows[1]["parquet_filename"]
    elif mutation == "missing_parquet":
        (tmp_path / "processed" / rows[0]["parquet_filename"]).unlink()
    else:
        path = tmp_path / rows[0]["relative_path"]
        # Change bytes without changing the shape of the source CSV.
        path.write_bytes(path.read_bytes().replace(b"Inverse", b"inverse", 1))
    with manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(loader.LoadError, match=expected_error):
        loader.prepare_load(tmp_path)


def test_rejects_numeric_payload_on_ambiguous_cell(etl_outputs, datasets):
    bass = next(dataset for dataset in datasets if dataset.investigation[0] == "PSI-25")
    table = pq.read_table(etl_outputs / "processed/psi-25_bass_ii.parquet")
    column = table.schema.get_field_index("fan_display")
    values = table.column(column).to_pylist()
    record = next(row for row in table.to_pylist() if row["fan_display_raw"] == "80122")
    values[record["source_record"] - 1] = Decimal("80122")
    modified = table.set_column(column, table.schema.field(column), pa.array(values, type=table.schema.field(column).type))
    with pytest.raises(loader.LoadError, match="Non-exact value is numeric"):
        loader.map_rows(modified, bass.columns, [row[1] for row in bass.records], "PSI-25")


@pytest.mark.parametrize("alteration", ("cell_status", "quality_flag"))
def test_rejects_parquet_quality_drift_with_unchanged_counts(etl_outputs, monkeypatch, alteration):
    source = next(source for source in loader.discover_sources(etl_outputs) if source.study == "PSI-107")
    entry = loader.read_manifest(etl_outputs / "source_manifest.csv")[source.path.as_posix()]
    table = pq.read_table(etl_outputs / "processed" / entry["parquet_filename"])

    if alteration == "cell_status":
        field = "air_rate_cm_s_status"
        row = table[field].to_pylist().index("exact")
        changes = {field: (row, "blank"), "air_rate_cm_s": (row, None)}
    else:
        field = "anomalies"
        row = next(index for index, flags in enumerate(table[field].to_pylist()) if flags)
        changes = {field: (row, ["different_flag"])}

    for name, (row, value) in changes.items():
        index = table.schema.get_field_index(name)
        values = table[name].to_pylist()
        values[row] = value
        arrow_field = table.schema.field(index)
        table = table.set_column(index, arrow_field, pa.array(values, type=arrow_field.type))

    monkeypatch.setattr(loader.pq, "read_table", lambda _: table)
    with pytest.raises(loader.LoadError, match=rf"differs from the ETL \({field}\)"):
        loader.prepare_dataset(etl_outputs, source, entry)


def test_connection_errors_do_not_disclose_dsn(monkeypatch):
    def refuse(*args, **kwargs):
        raise psycopg.OperationalError("postgresql://account:secret@127.0.0.1/test")

    monkeypatch.setattr(loader.psycopg, "connect", refuse)
    with pytest.raises(loader.LoadError, match="Set PYROGRAVITY_DATABASE_URL"):
        loader.load_datasets([], "")
    with pytest.raises(loader.LoadError, match="Could not connect") as error:
        loader.load_datasets([], "postgresql://account:secret@127.0.0.1/test")
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


class SimulatedCursor:
    # SQLite executes the loader's SQL and transaction logic without a PostgreSQL connection.
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cursor.close()

    def execute(self, query, params):
        self.cursor.execute(query.replace("%s", "?"), self.adapt(params))

    def executemany(self, query, params):
        try:
            self.cursor.executemany(query.replace("%s", "?"), map(self.adapt, params))
        except sqlite3.IntegrityError as error:
            raise psycopg.errors.CheckViolation("simulated statement failure") from error

    @staticmethod
    def adapt(params):
        return tuple(
            json.dumps(value.obj) if isinstance(value, Jsonb)
            else json.dumps(value) if isinstance(value, list)
            else str(value) if isinstance(value, Decimal)
            else value
            for value in params
        )

    def decode(self, row):
        json_fields = {"quantitative_criteria", "original_values", "text_cell_statuses", "quality_flags"}
        return tuple(
            json.loads(value) if name in json_fields
            else Decimal(value) if name == "numeric_value" and value is not None
            else value
            for (name, *_), value in zip(self.cursor.description, row, strict=True)
        )

    def fetchone(self):
        row = self.cursor.fetchone()
        return None if row is None else self.decode(row)

    def fetchall(self):
        return [self.decode(row) for row in self.cursor.fetchall()]


@pytest.fixture
def simulated_database(monkeypatch):
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            ATTACH DATABASE ':memory:' AS scientific;
            CREATE TABLE scientific.investigations (
                psi_code TEXT PRIMARY KEY, investigation_name TEXT, nasa_psi_url TEXT
            );
            CREATE TABLE scientific.datasets (
                dataset_id INTEGER PRIMARY KEY, psi_code TEXT, relative_path TEXT, sha256 TEXT,
                encoding TEXT, delimiter TEXT, row_count INTEGER, column_count INTEGER, data_scope TEXT,
                quantitative_criteria TEXT, source_observations TEXT, quality_reference TEXT,
                UNIQUE (psi_code, relative_path, sha256)
            );
            CREATE TABLE scientific.dataset_columns (
                dataset_id INTEGER, column_ordinal INTEGER, column_name TEXT, source_header TEXT,
                source_unit TEXT, value_kind TEXT, PRIMARY KEY (dataset_id, column_ordinal)
            );
            CREATE TABLE scientific.records (
                dataset_id INTEGER, source_record INTEGER, original_values TEXT, text_cell_statuses TEXT,
                source_row_empty INTEGER, quantitative_candidate INTEGER, quality_flags TEXT,
                PRIMARY KEY (dataset_id, source_record)
            );
            CREATE TABLE scientific.measurements (
                dataset_id INTEGER, source_record INTEGER, column_ordinal INTEGER, value_kind TEXT,
                interpretation_status TEXT, numeric_value TEXT,
                PRIMARY KEY (dataset_id, source_record, column_ordinal)
            );
        """)

        class Transaction:
            def __enter__(self):
                db.__enter__()
                return self

            def __exit__(self, *exc):
                return db.__exit__(*exc)

            def cursor(self):
                return SimulatedCursor(db.cursor())

        def connect(*args, **kwargs):
            return Transaction()

        monkeypatch.setattr(loader.psycopg, "connect", connect)
        yield db
    db.close()


def test_load_is_idempotent_and_rejects_drift(simulated_database, datasets):
    db = simulated_database
    assert loader.load_datasets(datasets, "simulated") == 21
    assert loader.load_datasets(datasets, "simulated") == 0
    for table, count in (
        ("investigations", 19), ("datasets", 21), ("dataset_columns", 227),
        ("records", 2862), ("measurements", 24252),
    ):
        assert db.execute(f"SELECT count(*) FROM scientific.{table}").fetchone() == (count,)
    db.execute("UPDATE scientific.records SET original_values = '[]' WHERE dataset_id = 1 AND source_record = 1")
    db.commit()
    with pytest.raises(loader.LoadError, match="Existing records differ"):
        loader.load_datasets(datasets, "simulated")
    assert db.execute("SELECT count(*) FROM scientific.datasets").fetchone() == (21,)


def test_load_appends_a_new_hash_version(simulated_database, datasets):
    first = datasets[0]
    second_version = replace(first, sha256="f" * 64)
    assert loader.load_datasets([first], "simulated") == 1
    assert loader.load_datasets([second_version], "simulated") == 1
    assert loader.load_datasets([first, second_version], "simulated") == 0
    assert simulated_database.execute("SELECT count(*) FROM scientific.datasets").fetchone() == (2,)
    assert simulated_database.execute("SELECT count(*) FROM scientific.records").fetchone() == (2 * len(first.records),)


def test_partial_database_write_rolls_back_entire_batch(simulated_database, datasets):
    db = simulated_database
    db.executescript("""
        CREATE TRIGGER scientific.reject_second_dataset
        BEFORE INSERT ON measurements WHEN NEW.dataset_id = 2
        BEGIN SELECT RAISE(ABORT, 'Simulated failure during the second dataset'); END;
    """)
    with pytest.raises(loader.LoadError, match="PostgreSQL load failed"):
        loader.load_datasets(datasets[:2], "simulated")
    for table in ("investigations", "datasets", "dataset_columns", "records", "measurements"):
        assert db.execute(f"SELECT count(*) FROM scientific.{table}").fetchone() == (0,)
