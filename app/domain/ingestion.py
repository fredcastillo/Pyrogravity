"""Modelo de ingesta: filas normalizadas, puerto de salida y reporte.

Un dataset = un CSV de NASA PSI, identificado por su sha256. El id de cada fila es
un UUID determinista derivado de su clave natural, de modo que reintentar una carga
nunca duplica datos y no hace falta leer ids de vuelta de la base.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.domain.errors import DomainError

_NS = uuid.UUID("5b0f3f0e-6a0e-4a53-9a39-0b7d6c2f1e11")  # fijo: no cambiar nunca


def _uid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NS, "|".join(str(p) for p in parts))


def dataset_id(sha256: str) -> uuid.UUID:
    return _uid("dataset", sha256)


def trial_id(sha256: str, source_record: int) -> uuid.UUID:
    return _uid("trial", sha256, source_record)


def variable_id(sha256: str, column_name: str) -> uuid.UUID:
    return _uid("variable", sha256, column_name)


class StructuralProblem(DomainError):
    """El archivo no cumple el formato esperado; ese dataset no se carga."""

    code = "INGESTION_STRUCTURAL_PROBLEM"


@dataclass(frozen=True)
class SourceRow:
    psi_code: str
    title: str
    url: str
    # TODO(PENDIENTE: Stanley): version NASA y DOI por investigacion (solo PSI-69 v5 y PSI-25 v4 estan en el README)
    nasa_version: str | None = None
    doi: str | None = None


@dataclass(frozen=True)
class DatasetRow:
    id: uuid.UUID
    psi_code: str
    table_name: str
    source_filename: str
    sha256: str
    scope: str
    quantitative_status: str
    observations: str
    row_count: int
    informative_row_count: int
    empty_row_count: int


@dataclass(frozen=True)
class TrialRow:
    id: uuid.UUID
    dataset_id: uuid.UUID
    source_record: int  # fila del CSV, base 1, sin contar el encabezado
    label: str
    anomalies: tuple[str, ...]
    quantitative_candidate: bool
    attributes: dict[str, str]  # columnas de texto con valor (combustible, material, fecha...)


@dataclass(frozen=True)
class VariableRow:
    id: uuid.UUID
    dataset_id: uuid.UUID
    column_name: str
    source_header: str
    unit: str | None
    unit_known: bool


@dataclass(frozen=True)
class MeasurementRow:
    trial_id: uuid.UUID
    variable_id: uuid.UUID
    value: Decimal | None  # solo se rellena si status == "exact"
    raw_value: str  # texto original de la fuente, siempre
    status: str
    unit: str | None


@dataclass(frozen=True)
class DatasetBatch:
    source: SourceRow
    dataset: DatasetRow
    trials: tuple[TrialRow, ...]
    variables: tuple[VariableRow, ...]
    measurements: tuple[MeasurementRow, ...]
    blank_cells_skipped: int


@dataclass
class WriteStats:
    by_table: dict[str, Counter[str]] = field(default_factory=dict)

    def add(self, table: str, outcome: str, n: int = 1) -> None:
        self.by_table.setdefault(table, Counter())[outcome] += n

    def total(self, outcome: str) -> int:
        return sum(c[outcome] for c in self.by_table.values())

    @property
    def written(self) -> int:
        return self.total("inserted") + self.total("updated")

    @property
    def unchanged(self) -> int:
        return self.total("unchanged")


@dataclass(frozen=True)
class BatchResult:
    """Resultado de leer un dataset: o trae el lote, o trae el motivo del rechazo."""

    name: str
    batch: DatasetBatch | None = None
    problem: str | None = None


class IngestionSink(Protocol):
    def write(self, batch: DatasetBatch) -> WriteStats: ...


@dataclass
class DatasetOutcome:
    name: str
    problem: str | None = None
    trials: int = 0
    empty_rows_skipped: int = 0
    measurements: int = 0
    unitless_cells: int = 0
    blank_cells_skipped: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    written: int = 0
    unchanged: int = 0


@dataclass
class IngestionReport:
    started_at: datetime
    outcomes: list[DatasetOutcome] = field(default_factory=list)

    @property
    def problems(self) -> list[DatasetOutcome]:
        return [o for o in self.outcomes if o.problem]

    @property
    def ok(self) -> bool:
        return not self.problems

    def _sum(self, attr: str) -> int:
        return sum(getattr(o, attr) for o in self.outcomes if not o.problem)

    def statuses(self) -> Counter[str]:
        total: Counter[str] = Counter()
        for o in self.outcomes:
            if not o.problem:
                total.update(o.statuses)
        return total

    def summary(self) -> dict[str, Any]:
        return {
            "datasets_cargados": sum(1 for o in self.outcomes if not o.problem),
            "rechazos_estructurales": len(self.problems),
            "ensayos": self._sum("trials"),
            "filas_vacias_omitidas": self._sum("empty_rows_skipped"),
            "mediciones": self._sum("measurements"),
            "celdas_blank_omitidas": self._sum("blank_cells_skipped"),
            "celdas_sin_unidad": self._sum("unitless_cells"),
            "filas_escritas": self._sum("written"),
            "filas_sin_cambios": self._sum("unchanged"),
            "mediciones_por_estado": dict(self.statuses().most_common()),
        }
