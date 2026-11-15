"""Pruebas de la ingesta.

- Los Parquet de estas pruebas son SINTETICOS DE EJEMPLO (solo prueban mecanica, no ciencia).
- Las pruebas marcadas `real_data` usan los Parquet reales del ETL y se omiten si no existen.
  Genera con:  cd data && python -m src.etl.nasa_etl   (o define PYROGRAVITY_PARQUET_DIR / PYROGRAVITY_MANIFEST)
"""
from __future__ import annotations

import csv
import hashlib
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.application.ingestion_service import ingest
from app.domain.errors import RepositoryError
from app.domain.ingestion import StructuralProblem, dataset_id, trial_id
from app.infrastructure.ingestion.parquet_reader import (
    REQUIRED_MANIFEST,
    iter_batches,
    read_manifest,
)
from app.infrastructure.ingestion.sinks import CountingSink, InMemorySink, SupabaseSink
from scripts.load_to_supabase import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DIR = Path(os.environ.get("PYROGRAVITY_PARQUET_DIR", REPO_ROOT / "data" / "processed"))
REAL_MANIFEST = Path(os.environ.get("PYROGRAVITY_MANIFEST", REPO_ROOT / "data" / "source_manifest.csv"))
real_data = pytest.mark.skipif(
    not (REAL_DIR.is_dir() and any(REAL_DIR.glob("*.parquet")) and REAL_MANIFEST.is_file()),
    reason="Faltan los Parquet reales: ejecuta el ETL (cd data && python -m src.etl.nasa_etl) "
           "o define PYROGRAVITY_PARQUET_DIR y PYROGRAVITY_MANIFEST",
)


# ---------- construccion de datos sinteticos ----------
def _field(name: str, typ: pa.DataType, unit: str | None = None, header: str | None = None) -> pa.Field:
    meta = {"source_header": header or name}
    if unit:
        meta["source_unit"] = unit
    return pa.field(name, typ, metadata=meta)


def make_parquet(dirpath: Path, name: str = "psi-00_demo", sha: str = "a" * 64, rows: int = 4) -> dict[str, str]:
    """4 filas: 1 normal, 2 con estado 'approximate', 3 con celda blank, 4 vacia."""
    d = pa.decimal128(18, 2)
    fields = [
        pa.field("source_record", pa.int64()), pa.field("source_study", pa.string()),
        pa.field("fuel", pa.string()), pa.field("fuel_status", pa.string()),
        _field("burn_time", d, unit="s", header="Burn time; s"),
        pa.field("burn_time_raw", pa.string()), pa.field("burn_time_status", pa.string()),
        _field("mystery", d, header="Mystery col"),  # SIN unidad
        pa.field("mystery_raw", pa.string()), pa.field("mystery_status", pa.string()),
        pa.field("anomalies", pa.list_(pa.string())),
        pa.field("source_row_empty", pa.bool_()), pa.field("quantitative_candidate", pa.bool_()),
    ]
    dec = Decimal
    cols: dict[str, list[Any]] = {
        "source_record": [1, 2, 3, 4], "source_study": ["PSI-00"] * 4,
        "fuel": ["Methanol", "Heptane", "", ""], "fuel_status": ["text", "text", "blank", "blank"],
        "burn_time": [dec("4.30"), None, None, None],
        "burn_time_raw": ["4.3", "~5", "", ""], "burn_time_status": ["exact", "approximate", "blank", "blank"],
        "mystery": [dec("1.50"), dec("2.00"), dec("3.00"), None],
        "mystery_raw": ["1.5", "2", "3", ""], "mystery_status": ["exact", "exact", "exact", "blank"],
        "anomalies": [[], ["repeated_test"], [], ["empty_record"]],
        "source_row_empty": [False, False, False, True], "quantitative_candidate": [True, False, True, False],
    }
    table = pa.Table.from_pydict(cols, schema=pa.schema(fields, metadata={
        "source_sha256": sha, "source_scope": "experimental_summary"}))
    pq.write_table(table.slice(0, rows) if rows != 4 else table, dirpath / f"{name}.parquet")
    return manifest_row(name, sha, rows=rows, empty=1)


def manifest_row(name: str, sha: str, rows: int = 4, empty: int = 1) -> dict[str, str]:
    return {
        "psi_code": "PSI-00", "investigation_name": "Demo sintetico de ejemplo",
        "source_filename": f"{name}.csv", "sha256": sha, "nasa_psi_url": "https://example.invalid/PSI-00",
        "data_scope": "experimental_summary", "quantitative_status": "has_candidates",
        "observations": "sintetico", "parquet_filename": f"{name}.parquet",
        "row_count": str(rows), "informative_row_count": str(rows - empty), "empty_row_count": str(empty),
    }


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(REQUIRED_MANIFEST), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def demo(tmp_path: Path) -> tuple[Path, Path]:
    row = make_parquet(tmp_path)
    write_manifest(tmp_path / "manifest.csv", [row])
    return tmp_path, tmp_path / "manifest.csv"


# ---------- mecanica ----------
def test_empty_rows_are_skipped_and_blank_cells_not_stored(demo):
    report = ingest(iter_batches(*demo), InMemorySink())
    o = report.outcomes[0]
    assert report.ok
    assert o.trials == 3 and o.empty_rows_skipped == 1
    # 3 filas x 2 columnas = 6 celdas, 1 blank (burn_time fila 3) -> 5 guardadas
    assert o.measurements == 5 and o.blank_cells_skipped == 1


def test_non_exact_status_keeps_raw_and_null_value(demo):
    sink = InMemorySink()
    ingest(iter_batches(*demo), sink)
    rows = [m for m in sink.tables["measurements"].values() if m.status == "approximate"]
    assert len(rows) == 1
    assert rows[0].value is None and rows[0].raw_value == "~5"


def test_exact_status_keeps_value_and_raw(demo):
    sink = InMemorySink()
    ingest(iter_batches(*demo), sink)
    exact = [m for m in sink.tables["measurements"].values() if m.status == "exact" and m.unit == "s"]
    assert [(m.value, m.raw_value) for m in exact] == [(Decimal("4.30"), "4.3")]


def test_unitless_column_has_null_unit_and_unit_known_false(demo):
    sink = InMemorySink()
    report = ingest(iter_batches(*demo), sink)
    by_col = {v.column_name: v for v in sink.tables["variables"].values()}
    assert by_col["burn_time"].unit == "s" and by_col["burn_time"].unit_known is True
    assert by_col["mystery"].unit is None and by_col["mystery"].unit_known is False
    assert report.outcomes[0].unitless_cells == 3  # 3 celdas de 'mystery' no blank


def test_anomalies_and_attributes_are_preserved(demo):
    sink = InMemorySink()
    ingest(iter_batches(*demo), sink)
    trials = {t.source_record: t for t in sink.tables["trials"].values()}
    assert trials[2].anomalies == ("repeated_test",)
    assert trials[1].attributes == {"fuel": "Methanol"}
    assert trials[3].attributes == {}  # texto en blanco no se guarda
    assert 4 not in trials  # fila vacia omitida


def test_dry_run_writes_nothing_via_cli(demo, capsys):
    pdir, man = demo
    code = cli_main(["--parquet-dir", str(pdir), "--manifest", str(man), "--dry-run"])
    assert code == 0
    assert '"datasets_cargados": 1' in capsys.readouterr().out


def test_counting_sink_keeps_no_state(demo):
    sink = CountingSink()
    first = ingest(iter_batches(*demo), sink).summary()["filas_escritas"]
    second = ingest(iter_batches(*demo), sink).summary()["filas_escritas"]
    assert first > 0 and second == first - 1  # la fuente PSI ya vista no se cuenta de nuevo


def test_second_run_is_unchanged(demo):
    sink = InMemorySink()
    first = ingest(iter_batches(*demo), sink)
    second = ingest(iter_batches(*demo), sink)
    assert first.summary()["filas_escritas"] > 0
    assert second.summary()["filas_escritas"] == 0
    assert second.summary()["filas_sin_cambios"] == first.summary()["filas_escritas"]


def test_changed_sha256_creates_new_dataset_and_keeps_old(tmp_path):
    sink = InMemorySink()
    for sha in ("a" * 64, "b" * 64):
        sub = tmp_path / sha[0]
        sub.mkdir()
        write_manifest(sub / "m.csv", [make_parquet(sub, sha=sha)])
        ingest(iter_batches(sub, sub / "m.csv"), sink)
    assert sink.count("datasets") == 2
    assert sink.count("trials") == 6 and sink.count("sources") == 1


def test_sha256_mismatch_is_structural_problem_and_exit_1(demo, capsys):
    pdir, man = demo
    write_manifest(man, [manifest_row("psi-00_demo", "f" * 64)])
    report = ingest(iter_batches(pdir, man), InMemorySink())
    assert not report.ok and "sha256" in report.problems[0].problem
    assert report.outcomes[0].trials == 0  # nada se cargo
    assert cli_main(["--parquet-dir", str(pdir), "--manifest", str(man), "--sink", "memory"]) == 1
    assert "RECHAZADO" in capsys.readouterr().err


def test_row_count_mismatch_with_manifest_is_rejected(demo):
    pdir, man = demo
    bad = manifest_row("psi-00_demo", "a" * 64, rows=9)
    write_manifest(man, [bad])
    report = ingest(iter_batches(pdir, man), InMemorySink())
    assert "filas" in report.problems[0].problem


def test_parquet_without_manifest_row_and_missing_parquet(demo):
    pdir, man = demo
    write_manifest(man, [manifest_row("otro", "c" * 64)])
    problems = [o.problem for o in ingest(iter_batches(pdir, man), InMemorySink()).outcomes]
    assert any("sin fila en el manifiesto" in p for p in problems)
    assert any("ausente" in p for p in problems)


def test_missing_required_columns_is_rejected(tmp_path):
    pq.write_table(pa.table({"x": [1]}, schema=pa.schema([pa.field("x", pa.int64())],
                   metadata={"source_sha256": "a" * 64})), tmp_path / "psi-00_demo.parquet")
    write_manifest(tmp_path / "m.csv", [manifest_row("psi-00_demo", "a" * 64)])
    report = ingest(iter_batches(tmp_path, tmp_path / "m.csv"), InMemorySink())
    assert "Faltan columnas" in report.problems[0].problem


def test_corrupt_parquet_is_rejected_not_crashing(tmp_path):
    (tmp_path / "psi-00_demo.parquet").write_bytes(b"esto no es parquet")
    write_manifest(tmp_path / "m.csv", [manifest_row("psi-00_demo", "a" * 64)])
    report = ingest(iter_batches(tmp_path, tmp_path / "m.csv"), InMemorySink())
    assert "No se pudo leer el Parquet" in report.problems[0].problem


def test_missing_manifest_columns_is_rejected(tmp_path):
    (tmp_path / "m.csv").write_text("psi_code\nPSI-00\n", encoding="utf-8")
    with pytest.raises(StructuralProblem, match="Manifiesto sin columnas"):
        read_manifest(tmp_path / "m.csv")


def test_ids_are_deterministic():
    assert dataset_id("x") == dataset_id("x") != dataset_id("y")
    assert trial_id("x", 1) != trial_id("x", 2)
    assert isinstance(trial_id("x", 1), uuid.UUID)


# ---------- SupabaseSink con cliente falso ----------
class FakeQuery:
    def __init__(self, client: FakeClient, table: str) -> None:
        self.c, self.t, self.op, self.payload, self.filters = client, table, "select", None, {}

    def select(self, *_a: Any) -> FakeQuery:
        self.op = "select"
        return self

    def upsert(self, rows: Any, on_conflict: str = "") -> FakeQuery:
        self.op, self.payload, self.conflict = "upsert", rows, on_conflict
        return self

    def update(self, values: Any) -> FakeQuery:
        self.op, self.payload = "update", values
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        self.filters[col] = val
        return self

    def execute(self) -> Any:
        if self.c.fail_on == self.t and self.op == "upsert":
            raise ConnectionError("red caida")
        self.c.calls.append((self.op, self.t, len(self.payload) if self.op == "upsert" else self.payload))
        if self.op == "select":
            return type("R", (), {"data": self.c.existing.get(self.filters.get("sha256"), [])})()
        return type("R", (), {"data": []})()


class FakeClient:
    def __init__(self, existing: dict[str, list[dict[str, Any]]] | None = None, fail_on: str | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.existing, self.fail_on = existing or {}, fail_on

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def _one_batch(demo):
    return next(r.batch for r in iter_batches(*demo) if r.batch)


def test_supabase_sink_upserts_in_chunks_dataset_first_and_marks_ingested_last(demo):
    client = FakeClient()
    SupabaseSink(client, chunk_size=2).write(_one_batch(demo))
    ups = [c for c in client.calls if c[0] == "upsert"]
    assert [c[1] for c in ups][:2] == ["sources", "datasets"]  # orden por llaves foraneas
    assert max(c[2] for c in ups) <= 2  # lotes
    assert sum(c[2] for c in ups if c[1] == "measurements") == 5
    assert client.calls[-1][0] == "update" and "ingested_at" in client.calls[-1][2]


def test_supabase_sink_skips_dataset_already_ingested(demo):
    batch = _one_batch(demo)
    client = FakeClient(existing={batch.dataset.sha256: [{"sha256": batch.dataset.sha256, "ingested_at": "2026-01-01"}]})
    stats = SupabaseSink(client).write(batch)
    assert stats.written == 0 and stats.unchanged > 0
    assert not [c for c in client.calls if c[0] in ("upsert", "update")]


def test_supabase_sink_retries_incomplete_dataset(demo):
    batch = _one_batch(demo)
    client = FakeClient(existing={batch.dataset.sha256: [{"sha256": batch.dataset.sha256, "ingested_at": None}]})
    assert SupabaseSink(client).write(batch).written > 0


def test_supabase_sink_sdk_error_becomes_repository_error(demo):
    with pytest.raises(RepositoryError):
        SupabaseSink(FakeClient(fail_on="trials")).write(_one_batch(demo))


def test_repository_error_is_reported_not_raised_by_service(demo):
    report = ingest(iter_batches(*demo), SupabaseSink(FakeClient(fail_on="measurements")))
    assert not report.ok and "Destino no disponible" in report.problems[0].problem


def test_supabase_payload_is_json_serializable(demo):
    import json
    client = FakeClient()
    SupabaseSink(client).write(_one_batch(demo))
    # el payload se serializo dentro de upsert; comprobar tipos directamente
    from app.infrastructure.ingestion.sinks import _serialize
    for m in _one_batch(demo).measurements:
        json.dumps(_serialize(m))
    for t in _one_batch(demo).trials:
        json.dumps(_serialize(t))


# ---------- datos reales ----------
@pytest.fixture(scope="module")
def real_report_and_sink():
    sink = InMemorySink()
    report = ingest(iter_batches(REAL_DIR, REAL_MANIFEST), sink)
    return report, sink


@real_data
def test_real_counts(real_report_and_sink):
    report, sink = real_report_and_sink
    s = report.summary()
    assert report.ok, [(o.name, o.problem) for o in report.problems]
    assert s["datasets_cargados"] == 21
    assert s["ensayos"] == 2001
    assert s["filas_vacias_omitidas"] == 861
    assert sink.count("sources") == 19  # PSI-10 y PSI-159 tienen dos tablas
    assert s["mediciones_por_estado"]["exact"] == 13139


@real_data
def test_real_empty_rows_all_in_psi159_inverse(real_report_and_sink):
    report, _ = real_report_and_sink
    by_name = {o.name: o for o in report.outcomes}
    assert by_name["psi-159_cfi_g_inverse_flames.parquet"].empty_rows_skipped == 861
    assert sum(o.empty_rows_skipped for o in report.outcomes if "inverse_flames" not in o.name) == 0


@real_data
def test_real_value_only_if_exact(real_report_and_sink):
    _, sink = real_report_and_sink
    ms = list(sink.tables["measurements"].values())
    assert all((m.value is not None) == (m.status == "exact") for m in ms)
    assert all(m.raw_value is not None for m in ms)


@real_data
def test_real_second_run_unchanged():
    sink = InMemorySink()
    ingest(iter_batches(REAL_DIR, REAL_MANIFEST), sink)
    again = ingest(iter_batches(REAL_DIR, REAL_MANIFEST), sink).summary()
    assert again["filas_escritas"] == 0 and again["filas_sin_cambios"] > 16000


@real_data
def test_real_recorrido_1_flex_test_1_burn_time(real_report_and_sink):
    """FLEX test #1 (20CAL08, metanol): burn time 4.30 s, registro 1, PSI-69, rastreable hasta la fuente."""
    _, sink = real_report_and_sink
    manifest = read_manifest(REAL_MANIFEST)["psi-69_flex.parquet"]
    ds = sink.tables["datasets"][(manifest["sha256"],)]
    assert ds.psi_code == "PSI-69" and ds.source_filename == "PSI-69_Experimental table_FLEX.csv"
    trial = sink.tables["trials"][(ds.id, 1)]
    assert trial.attributes["fuel"] == "Methanol" and trial.attributes["flex_identifier"] == "20CAL08"
    var = sink.tables["variables"][(ds.id, "burn_time")]
    m = sink.tables["measurements"][(trial.id, var.id)]
    assert (m.value, m.unit, m.status, m.raw_value) == (Decimal("4.30"), "s", "exact", "4.3")
    assert sink.tables["sources"][("PSI-69",)].url.endswith("/PSI-69")


@real_data
def test_real_recorrido_4_saffire3_is_conditions_only(real_report_and_sink):
    """SAFFIRE-3 no tiene resultados de quemado: el dataset lo declara para responder insufficient_evidence."""
    _, sink = real_report_and_sink
    ds = next(d for d in sink.tables["datasets"].values() if d.table_name == "psi-100_saffire_3")
    assert ds.scope == "conditions_only" and ds.quantitative_status == "limited_to_source_scope"
    variables = {v.column_name for v in sink.tables["variables"].values() if v.dataset_id == ds.id}
    assert "burn_time" not in variables


@real_data
def test_real_unit_preserved_as_in_source(real_report_and_sink):
    """El ETL conserva 'Burning rate; mm' de FLEX; no se corrige aguas abajo."""
    _, sink = real_report_and_sink
    flex = next(d for d in sink.tables["datasets"].values() if d.table_name == "psi-69_flex")
    assert sink.tables["variables"][(flex.id, "burning_rate")].unit == "mm"


@real_data
def test_real_sha256_alterado_en_manifiesto_se_rechaza(tmp_path):
    rows = list(read_manifest(REAL_MANIFEST).values())
    rows[0] = {**rows[0], "sha256": "0" * 64}
    write_manifest(tmp_path / "m.csv", rows)
    report = ingest(iter_batches(REAL_DIR, tmp_path / "m.csv"), InMemorySink())
    assert len(report.problems) == 1 and report.summary()["datasets_cargados"] == 20


def test_sha_of_real_csv_matches_manifest_when_available():
    """Sanidad: el sha256 del manifiesto corresponde al CSV crudo (si el repo esta presente)."""
    raw = REPO_ROOT / "data" / "raw"
    if not raw.is_dir() or not REAL_MANIFEST.is_file():
        pytest.skip("repo de datos no presente")
    for row in read_manifest(REAL_MANIFEST).values():
        f = raw / row["source_filename"]
        if f.is_file():
            assert hashlib.sha256(f.read_bytes()).hexdigest() == row["sha256"], row["source_filename"]
