"""Lee los Parquet que genera el ETL de Stanley (data/src/etl/nasa_etl.py).

NO reimplementa el parseo del CSV: solo interpreta la convencion de columnas del ETL:
  <col>, <col>_raw, <col>_status  -> columna numerica (valor, texto original, estado)
  <col>, <col>_status             -> columna de texto
  source_record, source_study, anomalies, source_row_empty, quantitative_candidate
y los metadatos de esquema (source_sha256, source_scope, source_observations por tabla;
source_header y source_unit por campo).
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.domain.ingestion import (
    BatchResult,
    DatasetBatch,
    DatasetRow,
    MeasurementRow,
    SourceRow,
    StructuralProblem,
    TrialRow,
    VariableRow,
    dataset_id,
    trial_id,
    variable_id,
)

REQUIRED_COLUMNS = ("source_record", "source_study", "anomalies", "source_row_empty", "quantitative_candidate")
REQUIRED_MANIFEST = ("psi_code", "investigation_name", "source_filename", "sha256", "nasa_psi_url",
                     "data_scope", "quantitative_status", "observations", "parquet_filename",
                     "row_count", "informative_row_count", "empty_row_count")
KNOWN_STATUSES = frozenset({
    "exact", "approximate", "range", "bound", "multiple_values", "ambiguous",
    "source_error", "annotation", "missing_marker", "blank",
})

# Columna que mejor identifica un ensayo, en orden de preferencia.
# TODO(PENDIENTE: Stanley): exponer las columnas identificadoras en los metadatos del Parquet.
LABEL_COLUMNS = ("flex_test_number", "test_number", "test", "as_run_test", "sample_number",
                 "test_day", "flex_number", "session_name", "sample")


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    """Devuelve {parquet_filename: fila del manifiesto}."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise StructuralProblem(f"No se pudo leer el manifiesto {path}: {exc}") from exc
    if not rows:
        raise StructuralProblem(f"Manifiesto vacio: {path}")
    missing = [c for c in REQUIRED_MANIFEST if c not in rows[0]]
    if missing:
        raise StructuralProblem(f"Manifiesto sin columnas: {missing}")
    return {r["parquet_filename"]: r for r in rows}


def iter_batches(parquet_dir: Path, manifest_path: Path) -> Iterator[BatchResult]:
    manifest = read_manifest(manifest_path)
    on_disk = {p.name for p in parquet_dir.glob("*.parquet")}
    for name in sorted(on_disk - manifest.keys()):
        yield BatchResult(name, problem="Parquet sin fila en el manifiesto")
    for name in sorted(manifest):
        if name not in on_disk:
            yield BatchResult(name, problem="Listado en el manifiesto pero ausente en el directorio")
            continue
        try:
            yield BatchResult(name, batch=read_dataset(parquet_dir / name, manifest[name]))
        except StructuralProblem as exc:
            yield BatchResult(name, problem=str(exc))
        except (OSError, ValueError, pa.ArrowException) as exc:  # archivo corrupto o ilegible
            yield BatchResult(name, problem=f"No se pudo leer el Parquet: {exc}")


def _decode(meta: dict[bytes, bytes] | None) -> dict[str, str]:
    return {k.decode(): v.decode() for k, v in (meta or {}).items()}


def read_dataset(path: Path, manifest_row: dict[str, str]) -> DatasetBatch:
    table = pq.read_table(path)
    names = table.column_names
    meta = _decode(table.schema.metadata)

    missing = [c for c in REQUIRED_COLUMNS if c not in names]
    if missing:
        raise StructuralProblem(f"Faltan columnas requeridas: {missing}")
    sha = meta.get("source_sha256")
    if not sha:
        raise StructuralProblem("El Parquet no trae source_sha256 en sus metadatos")
    if sha != manifest_row["sha256"]:
        raise StructuralProblem(
            f"sha256 del Parquet ({sha[:12]}...) no coincide con el manifiesto ({manifest_row['sha256'][:12]}...)"
        )

    psi_code = manifest_row["psi_code"]
    table_name = path.stem
    ds_id = dataset_id(sha)

    bases = {c[: -len("_status")] for c in names if c.endswith("_status")}
    numeric = sorted((b for b in bases if f"{b}_raw" in names and b in names), key=names.index)
    text = sorted((b for b in bases if b in names and b not in numeric), key=names.index)

    variables: list[VariableRow] = []
    var_by_col: dict[str, VariableRow] = {}
    for col in numeric:
        fmeta = _decode(table.schema.field(col).metadata)
        unit = fmeta.get("source_unit") or None
        row = VariableRow(variable_id(sha, col), ds_id, col, fmeta.get("source_header", col), unit, unit is not None)
        variables.append(row)
        var_by_col[col] = row

    data: dict[str, list[Any]] = {n: table[n].to_pylist() for n in names}
    n_rows = table.num_rows
    trials: list[TrialRow] = []
    measurements: list[MeasurementRow] = []
    blank_skipped = 0
    empty_rows = 0

    for i in range(n_rows):
        if data["source_row_empty"][i]:
            empty_rows += 1
            continue
        record = int(data["source_record"][i])
        tid = trial_id(sha, record)
        attributes = {c: str(data[c][i]) for c in text if data[c][i] not in (None, "")}
        trials.append(TrialRow(
            id=tid, dataset_id=ds_id, source_record=record, label=_label(attributes, record),
            anomalies=tuple(data["anomalies"][i] or ()),
            quantitative_candidate=bool(data["quantitative_candidate"][i]),
            attributes=attributes,
        ))
        for col in numeric:
            status = data[f"{col}_status"][i]
            if status not in KNOWN_STATUSES:
                raise StructuralProblem(f"Estado desconocido '{status}' en {col}, registro {record}")
            if status == "blank":
                blank_skipped += 1
                continue
            raw = data[f"{col}_raw"][i]
            value = data[col][i]
            if status == "exact" and value is None:
                raise StructuralProblem(f"Estado exact sin valor en {col}, registro {record}")
            var = var_by_col[col]
            measurements.append(MeasurementRow(
                trial_id=tid, variable_id=var.id,
                value=Decimal(value) if status == "exact" else None,  # nunca se infiere un valor de otro estado
                raw_value="" if raw is None else str(raw),
                status=status, unit=var.unit,
            ))

    if n_rows != int(manifest_row["row_count"]):
        raise StructuralProblem(f"{n_rows} filas en el Parquet, el manifiesto declara {manifest_row['row_count']}")
    if empty_rows != int(manifest_row["empty_row_count"]):
        raise StructuralProblem(f"{empty_rows} filas vacias, el manifiesto declara {manifest_row['empty_row_count']}")

    dataset = DatasetRow(
        id=ds_id, psi_code=psi_code, table_name=table_name,
        source_filename=manifest_row["source_filename"], sha256=sha,
        scope=meta.get("source_scope", manifest_row["data_scope"]),
        quantitative_status=manifest_row["quantitative_status"],
        observations=manifest_row["observations"],
        row_count=n_rows, informative_row_count=n_rows - empty_rows, empty_row_count=empty_rows,
    )
    source = SourceRow(psi_code, manifest_row["investigation_name"], manifest_row["nasa_psi_url"])
    return DatasetBatch(source, dataset, tuple(trials), tuple(variables), tuple(measurements), blank_skipped)


def _label(attributes: dict[str, str], record: int) -> str:
    for col in LABEL_COLUMNS:
        if col in attributes:
            return attributes[col]
    return f"#{record}"
