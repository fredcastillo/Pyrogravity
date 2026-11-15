"""Destinos de la ingesta. Todos implementan IngestionSink (app.domain.ingestion)."""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.errors import RepositoryError
from app.domain.ingestion import DatasetBatch, WriteStats

CHUNK = 500


def _tables(batch: DatasetBatch) -> dict[str, tuple[Any, ...]]:
    """Tablas en orden de dependencia (respeta las llaves foraneas)."""
    return {
        "sources": (batch.source,),
        "datasets": (batch.dataset,),
        "variables": batch.variables,
        "trials": batch.trials,
        "measurements": batch.measurements,
    }


# Clave natural de cada tabla (misma que el UNIQUE de la migracion).
_KEYS: dict[str, tuple[str, ...]] = {
    "sources": ("psi_code",),
    "datasets": ("sha256",),
    "variables": ("dataset_id", "column_name"),
    "trials": ("dataset_id", "source_record"),
    "measurements": ("trial_id", "variable_id"),
}


class InMemorySink:
    """Para pruebas: detecta insertado / actualizado / sin cambios por clave natural."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[tuple[Any, ...], Any]] = {t: {} for t in _KEYS}

    def write(self, batch: DatasetBatch) -> WriteStats:
        stats = WriteStats()
        for table, rows in _tables(batch).items():
            store = self.tables[table]
            for row in rows:
                key = tuple(getattr(row, k) for k in _KEYS[table])
                if key not in store:
                    stats.add(table, "inserted")
                elif store[key] != row:
                    stats.add(table, "updated")
                else:
                    stats.add(table, "unchanged")
                    continue
                store[key] = row
        return stats

    def count(self, table: str) -> int:
        return len(self.tables[table])


class CountingSink:
    """--dry-run: no escribe nada; cuenta lo que se insertaria (una fuente PSI se cuenta una vez)."""

    def __init__(self) -> None:
        self._seen_sources: set[str] = set()

    def write(self, batch: DatasetBatch) -> WriteStats:
        stats = WriteStats()
        for table, rows in _tables(batch).items():
            if table == "sources":
                rows = tuple(r for r in rows if r.psi_code not in self._seen_sources)
                self._seen_sources.update(r.psi_code for r in rows)
            stats.add(table, "inserted", len(rows))
        return stats


def _json(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)  # string: PostgREST lo acepta en numeric sin perder precision
    if isinstance(value, tuple):
        return list(value)
    return value


def _serialize(row: Any) -> dict[str, Any]:
    return {f.name: _json(getattr(row, f.name)) for f in dataclasses.fields(row)}


def _chunks(rows: Sequence[Any], size: int = CHUNK) -> Iterator[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


class SupabaseSink:
    """Upserts por lotes con supabase-py.

    - Un dataset (sha256) ya cargado por completo se omite: las filas de un sha256 no cambian.
    - La fila de datasets se crea primero (llave foranea) con ingested_at NULL y se marca al
      terminar. Una carga interrumpida queda con ingested_at NULL y se reintenta completa.
    - Todo error del SDK se convierte en RepositoryError.

    ASUNCION: nombres de tablas/columnas segun la especificacion de la ronda 3. No probado
    contra una base real (ver tests con cliente falso y la prueba de integracion pendiente).
    """

    def __init__(self, client: Any, chunk_size: int = CHUNK) -> None:
        self._client = client
        self._chunk = chunk_size

    def write(self, batch: DatasetBatch) -> WriteStats:
        stats = WriteStats()
        try:
            if self._already_ingested(batch):
                for table, rows in _tables(batch).items():
                    stats.add(table, "unchanged", len(rows))
                return stats
            for table, rows in _tables(batch).items():
                self._upsert(table, rows)
                stats.add(table, "inserted", len(rows))
            (self._client.table("datasets")
                .update({"ingested_at": datetime.now(UTC).isoformat()})
                .eq("sha256", batch.dataset.sha256).execute())
        except Exception as exc:
            raise RepositoryError(f"Fallo al escribir {batch.dataset.table_name}: {exc}") from exc
        return stats

    def _already_ingested(self, batch: DatasetBatch) -> bool:
        res = (self._client.table("datasets").select("sha256,ingested_at")
               .eq("sha256", batch.dataset.sha256).execute())
        return any(r.get("ingested_at") for r in (res.data or []))

    def _upsert(self, table: str, rows: Iterable[Any]) -> None:
        rows = list(rows)
        for chunk in _chunks(rows, self._chunk):
            payload = [_serialize(r) for r in chunk]
            self._client.table(table).upsert(payload, on_conflict=",".join(_KEYS[table])).execute()
