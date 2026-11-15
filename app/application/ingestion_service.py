"""Caso de uso: cargar lotes de datasets en un destino y producir el reporte."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from app.domain.errors import RepositoryError
from app.domain.ingestion import (
    BatchResult,
    DatasetOutcome,
    IngestionReport,
    IngestionSink,
)


def ingest(results: Iterable[BatchResult], sink: IngestionSink) -> IngestionReport:
    report = IngestionReport(started_at=datetime.now(UTC))
    for result in results:
        outcome = DatasetOutcome(name=result.name)
        report.outcomes.append(outcome)
        if result.batch is None:
            outcome.problem = result.problem or "Motivo desconocido"
            continue
        batch = result.batch
        try:
            stats = sink.write(batch)
        except RepositoryError as exc:
            outcome.problem = f"Destino no disponible: {exc}"
            continue
        outcome.trials = len(batch.trials)
        outcome.empty_rows_skipped = batch.dataset.empty_row_count
        outcome.measurements = len(batch.measurements)
        outcome.blank_cells_skipped = batch.blank_cells_skipped
        outcome.unitless_cells = sum(1 for m in batch.measurements if m.unit is None)
        for m in batch.measurements:
            outcome.statuses[m.status] += 1
        outcome.written = stats.written
        outcome.unchanged = stats.unchanged
    return report
