import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from ..etl.nasa_etl import (
    BASS_II, DATA_DIR, FLEX, INTEGER, MEASUREMENT, Source, classify_rows, discover_sources,
    is_empty_row, parse_cell, profile_columns, transform, transform_profile,
)
from ..etl.nasa_tables import INVESTIGATION_TITLES
from ..ingestion.nasa_csv import inspect_nasa_csv


DATABASE_URL = "PYROGRAVITY_DATABASE_URL"
NUMERIC_STATUSES = {
    "exact", "blank", "missing_marker", "approximate", "bound", "range",
    "multiple_values", "annotation", "ambiguous", "source_error",
}
TEXT_STATUSES = (NUMERIC_STATUSES - {"exact"}) | {"text"}
MANIFEST_FIELDS = {
    "psi_code", "investigation_name", "nasa_psi_url", "relative_path", "source_filename",
    "parquet_filename", "sha256", "encoding", "delimiter", "row_count", "column_count",
    "data_scope", "observations", "empty_row_count", "informative_row_count",
    "flagged_row_count", "quantitative_candidate_row_count",
}
DATASET_FIELDS = (
    "encoding, delimiter, row_count, column_count, data_scope, "
    "quantitative_criteria, source_observations, quality_reference"
)
DATASET_KEY = "psi_code = %s AND relative_path = %s AND sha256 = %s"
ColumnRow = tuple[int, str, str, str | None, str]
RecordRow = tuple[int, list[str], dict[str, str], bool, bool, list[str]]
MeasurementRow = tuple[int, int, str, str, Decimal | int | None]


class LoadError(Exception):
    pass


@dataclass(frozen=True)
class DatasetLoad:
    investigation: tuple[str, str, str]
    relative_path: str
    sha256: str
    metadata: tuple
    columns: list[ColumnRow]
    records: list[RecordRow]
    measurements: list[MeasurementRow]

    @property
    def key(self) -> tuple[str, str, str]:
        return self.investigation[0], self.relative_path, self.sha256


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    entries = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        if not MANIFEST_FIELDS.issubset(fields) or len(fields) != len(set(fields)):
            raise LoadError("Missing or repeated source manifest headers")
        for entry in reader:
            if None in entry or any(entry[field] is None for field in MANIFEST_FIELDS):
                raise LoadError(f"Invalid source manifest row at line {reader.line_num}")
            relative_path = entry["relative_path"]
            if relative_path in entries:
                raise LoadError(f"Duplicate source manifest path: {relative_path}")
            entries[relative_path] = entry
    return entries


def field_kind(data_type: pa.DataType) -> str:
    if pa.types.is_string(data_type):
        return "text"
    if pa.types.is_integer(data_type):
        return "integer"
    if pa.types.is_decimal(data_type):
        return "decimal"
    raise LoadError(f"Unsupported source column type: {data_type}")


def prepare_dataset(data_dir: Path, source: Source, entry: dict[str, str]) -> DatasetLoad:
    relative_path = source.path.as_posix()
    parquet_name = f"{source.output_name}.parquet"
    if (
        entry["psi_code"] != source.study
        or entry["source_filename"] != source.path.name
        or entry["parquet_filename"] != parquet_name
        or entry["investigation_name"] != INVESTIGATION_TITLES[source.study]
        or entry["data_scope"] != source.profile.scope
    ):
        raise LoadError("Manifest does not match the expected source or Parquet")

    original = inspect_nasa_csv(data_dir / source.path)
    if original.sha256 != entry["sha256"]:
        raise LoadError("Original CSV SHA-256 does not match the manifest")
    row_count, column_count = int(entry["row_count"]), int(entry["column_count"])
    if (original.encoding, original.delimiter, len(original.rows), len(original.header)) != (
        entry["encoding"], entry["delimiter"], row_count, column_count
    ):
        raise LoadError("CSV encoding, delimiter or dimensions do not match the manifest")

    parquet_path = data_dir / "processed" / parquet_name
    if not parquet_path.is_file():
        raise LoadError(f"Missing Parquet: {parquet_name}")
    table = pq.read_table(parquet_path)
    meta = {key.decode(): value.decode() for key, value in (table.schema.metadata or {}).items()}
    for key, expected in {
        "source_path": relative_path,
        "source_sha256": original.sha256,
        "source_encoding": original.encoding,
        "source_delimiter": original.delimiter,
        "source_investigation": entry["nasa_psi_url"],
        "source_scope": entry["data_scope"],
    }.items():
        if meta.get(key) != expected:
            raise LoadError(f"Parquet provenance does not match the manifest ({key})")
    if table.num_rows != row_count or len(set(table.column_names)) != table.num_columns:
        raise LoadError("Parquet row count or column names are invalid")

    criteria = json.loads(meta["quantitative_candidate_criteria"])
    if criteria != {
        "required_context_headers": list(source.profile.quantitative_context),
        "required_exact_value_headers": list(source.profile.quantitative_values),
        "blocking_anomaly_flags": list(source.profile.quantitative_blockers),
    }:
        raise LoadError("Parquet quantitative criteria do not match the source profile")
    columns = []
    for ordinal, field in enumerate(
        (field for field in table.schema if b"source_header" in (field.metadata or {})), start=1
    ):
        header = field.metadata[b"source_header"].decode()
        unit = field.metadata.get(b"source_unit")
        columns.append((ordinal, field.name, header, unit.decode() if unit is not None else None,
                        field_kind(field.type)))
    adapter = {FLEX.source: FLEX, BASS_II.source: BASS_II}.get(source.path)
    expected_columns = adapter.columns if adapter else profile_columns(original, source.profile)
    if tuple(column[2] for column in columns) != original.header or columns != [
        (ordinal, column.name, column.header, column.unit, field_kind(column.kind))
        for ordinal, column in enumerate(expected_columns, start=1)
    ]:
        raise LoadError("Parquet column order, headers, types or units differ from the CSV profile")

    records, measurements = map_rows(table, columns, original.rows, source.study)
    # Aggregate counts alone cannot detect a changed cell status or moved quality flag.
    reference = transform(adapter, data_dir, original) if adapter else transform_profile(source, original)
    reference = classify_rows(reference, original, source.profile)
    quality_fields = [f"{name}_status" for _, name, *_ in columns]
    quality_fields.extend(("anomalies", "quantitative_candidate"))
    for field in quality_fields:
        if not table[field].equals(reference[field]):
            raise LoadError(f"Parquet interpretation or quality differs from the ETL ({field})")

    empty = sum(row[3] for row in records)
    candidates = sum(row[4] for row in records)
    flagged = sum(bool(row[5]) for row in records)
    if (empty, row_count - empty, candidates, flagged) != tuple(
        int(entry[field]) for field in (
            "empty_row_count", "informative_row_count", "quantitative_candidate_row_count",
            "flagged_row_count",
        )
    ):
        raise LoadError("Parquet quality counts do not match the manifest")

    return DatasetLoad(
        (source.study, entry["investigation_name"], entry["nasa_psi_url"]),
        relative_path,
        original.sha256,
        (original.encoding, original.delimiter, row_count, column_count, entry["data_scope"],
         criteria, entry["observations"], meta.get("quality_reference")),
        columns, records, measurements,
    )


def map_rows(
    table: pa.Table, columns: list[ColumnRow], source_rows: list[list[str]], study: str,
) -> tuple[list[RecordRow], list[MeasurementRow]]:
    records = []
    measurements = []
    for number, (row, original) in enumerate(zip(table.to_pylist(), source_rows, strict=True), start=1):
        if type(row["source_record"]) is not int or row["source_record"] != number or row["source_study"] != study:
            raise LoadError(f"Invalid provenance or ordering in record {number}")
        empty, candidate, flags = row["source_row_empty"], row["quantitative_candidate"], row["anomalies"]
        if (
            type(empty) is not bool or type(candidate) is not bool or empty != is_empty_row(original)
            or (empty and candidate) or not isinstance(flags, list)
            or any(not isinstance(flag, str) for flag in flags)
        ):
            raise LoadError(f"Invalid quality indicators in record {number}")

        text_statuses = {}
        for (ordinal, name, _, unit, kind), cell in zip(columns, original, strict=True):
            status = row[f"{name}_status"]
            numeric = kind != "text"
            raw_name = f"{name}_raw" if numeric else name
            allowed_statuses = NUMERIC_STATUSES if numeric else TEXT_STATUSES
            if row[raw_name] != cell or status not in allowed_statuses:
                raise LoadError(f"Invalid original value or status in record {number}, column {name}")
            if not numeric:
                text_statuses[name] = status
                continue
            value = row[name]
            if status == "exact":
                expected, _ = parse_cell(cell, INTEGER if kind == "integer" else MEASUREMENT, set(), unit)
                valid_type = type(value) is int if kind == "integer" else (
                    isinstance(value, Decimal) and value.is_finite()
                )
                if not valid_type or value != expected:
                    raise LoadError(f"Invalid exact numeric value in record {number}, column {name}")
            elif value is not None:
                raise LoadError(f"Non-exact value is numeric in record {number}, column {name}")
            measurements.append((number, ordinal, kind, status, value))
        records.append((number, original, text_statuses, empty, candidate, flags))
    return records, measurements


def prepare_load(data_dir: Path = DATA_DIR) -> list[DatasetLoad]:
    try:
        entries = read_manifest(data_dir / "source_manifest.csv")
        sources = discover_sources(data_dir)
    except (OSError, ValueError, csv.Error) as error:
        raise LoadError(f"Cannot read source inventory: {error}") from None
    if entries.keys() != {source.path.as_posix() for source in sources}:
        raise LoadError("Manifest does not contain exactly the expected NASA datasets")

    datasets = []
    investigations = {}
    for source in sources:
        path = source.path.as_posix()
        try:
            dataset = prepare_dataset(data_dir, source, entries[path])
            study, *details = dataset.investigation
            if investigations.setdefault(study, details) != details:
                raise LoadError(f"Conflicting investigation metadata for {study}")
        except (LoadError, OSError, KeyError, ValueError, TypeError, csv.Error, pa.ArrowException) as error:
            raise LoadError(f"{path}: {error}") from None
        datasets.append(dataset)
    return datasets


def ensure_investigation(cursor: psycopg.Cursor, investigation: tuple[str, str, str]) -> None:
    code, name, url = investigation
    cursor.execute(
        """INSERT INTO scientific.investigations (psi_code, investigation_name, nasa_psi_url)
           VALUES (%s, %s, %s) ON CONFLICT (psi_code) DO NOTHING""",
        investigation,
    )
    cursor.execute(
        "SELECT investigation_name, nasa_psi_url FROM scientific.investigations WHERE psi_code = %s",
        (code,),
    )
    if cursor.fetchone() != (name, url):
        raise LoadError(f"Existing investigation differs or is not visible: {code}")


def get_dataset(cursor: psycopg.Cursor, dataset: DatasetLoad) -> tuple[int, bool]:
    select = f"SELECT dataset_id, {DATASET_FIELDS} FROM scientific.datasets WHERE {DATASET_KEY}"
    cursor.execute(select, dataset.key)
    existing = cursor.fetchone()
    if existing is None:
        encoding, delimiter, row_count, column_count, scope, criteria, notes, reference = dataset.metadata
        cursor.execute(
            f"""INSERT INTO scientific.datasets (psi_code, relative_path, sha256, {DATASET_FIELDS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (psi_code, relative_path, sha256) DO NOTHING RETURNING dataset_id""",
            (*dataset.key, encoding, delimiter, row_count, column_count, scope, Jsonb(criteria), notes,
             reference),
        )
        inserted = cursor.fetchone()
        if inserted is not None:
            return inserted[0], True
        # A concurrent load may have inserted the same version.
        cursor.execute(select, dataset.key)
        existing = cursor.fetchone()
    if existing is None or existing[1:] != dataset.metadata:
        raise LoadError(f"Existing dataset differs or is not visible: {dataset.relative_path}")
    return existing[0], False


def sync_children(cursor: psycopg.Cursor, dataset_id: int, dataset: DatasetLoad, created: bool) -> None:
    children = (
        ("dataset_columns", "column_ordinal, column_name, source_header, source_unit, value_kind",
         "column_ordinal", dataset.columns),
        ("records", "source_record, original_values, text_cell_statuses, source_row_empty, "
         "quantitative_candidate, quality_flags", "source_record", dataset.records),
        ("measurements", "source_record, column_ordinal, value_kind, interpretation_status, numeric_value",
         "source_record, column_ordinal", dataset.measurements),
    )
    for table, fields, order, rows in children:
        if not created:
            cursor.execute(
                f"SELECT {fields} FROM scientific.{table} WHERE dataset_id = %s ORDER BY {order}",
                (dataset_id,),
            )
            if cursor.fetchall() != rows:
                raise LoadError(f"Existing {table} differ: {dataset.relative_path}")
        elif rows:
            if table == "records":
                params = ((dataset_id, number, Jsonb(values), Jsonb(statuses), empty, candidate, flags)
                          for number, values, statuses, empty, candidate, flags in dataset.records)
            else:
                params = ((dataset_id, *row) for row in rows)
            placeholders = ", ".join(["%s"] * (len(rows[0]) + 1))
            cursor.executemany(
                f"INSERT INTO scientific.{table} (dataset_id, {fields}) VALUES ({placeholders})",
                params,
            )


def load_datasets(datasets: list[DatasetLoad], dsn: str) -> int:
    if not dsn.strip():
        raise LoadError(f"Set {DATABASE_URL} before loading")
    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except (psycopg.Error, ValueError):
        raise LoadError(f"Could not connect to PostgreSQL. Check {DATABASE_URL} and access") from None

    inserted = 0
    try:
        with conn, conn.cursor() as cursor:
            for investigation in sorted({dataset.investigation for dataset in datasets}):
                ensure_investigation(cursor, investigation)
            for dataset in datasets:
                dataset_id, created = get_dataset(cursor, dataset)
                sync_children(cursor, dataset_id, dataset, created)
                inserted += created
    except psycopg.Error as error:
        state = f" (SQLSTATE {error.sqlstate})" if error.sqlstate else ""
        raise LoadError(f"PostgreSQL load failed{state}. Check schema, permissions and connectivity") from None
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and load the NASA PSI ETL outputs")
    parser.add_argument("--validate-only", action="store_true", help="Check inputs without connecting")
    args = parser.parse_args()
    dsn = os.environ.get(DATABASE_URL, "")
    try:
        if not args.validate_only and not dsn.strip():
            raise LoadError(f"Set {DATABASE_URL} before loading")
        datasets = prepare_load()
        if not args.validate_only:
            inserted = load_datasets(datasets, dsn)
            print(f"Committed {inserted} new dataset versions. Verified {len(datasets) - inserted} existing.")
    except LoadError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"{len({dataset.investigation[0] for dataset in datasets})} investigations, "
          f"{len(datasets)} datasets, {sum(len(dataset.columns) for dataset in datasets)} columns, "
          f"{sum(len(dataset.records) for dataset in datasets)} records, "
          f"{sum(len(dataset.measurements) for dataset in datasets)} numeric field states "
          f"({sum(row[3] == 'exact' for dataset in datasets for row in dataset.measurements)} exact).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
