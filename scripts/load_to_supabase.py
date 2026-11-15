"""Carga los Parquet del ETL (data/processed) y el manifiesto en Supabase.

Antes: cd data && python -m src.etl.nasa_etl   (ojo: reescribe data/source_manifest.csv)

Uso:
  python scripts/load_to_supabase.py --dry-run
  python scripts/load_to_supabase.py --sink memory --repeat 2     # verifica idempotencia sin base
  SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/load_to_supabase.py

Salida: 0 sin rechazos; 1 si algun dataset tuvo problema estructural; 2 por uso incorrecto.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ingestion_service import ingest
from app.domain.errors import DomainError
from app.domain.ingestion import IngestionSink
from app.infrastructure.ingestion.parquet_reader import iter_batches
from app.infrastructure.ingestion.sinks import CountingSink, InMemorySink, SupabaseSink

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_sink(kind: str) -> IngestionSink:
    if kind == "count":
        return CountingSink()
    if kind == "memory":
        return InMemorySink()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("Faltan SUPABASE_URL y SUPABASE_SERVICE_KEY (la clave solo vive en el servidor).")
    from supabase import create_client  # import tardio: no se necesita en dry-run
    return SupabaseSink(create_client(url, key))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--parquet-dir", type=Path, default=REPO_ROOT / "data" / "processed")
    p.add_argument("--manifest", type=Path, default=REPO_ROOT / "data" / "source_manifest.csv")
    p.add_argument("--dry-run", action="store_true", help="no escribe nada")
    p.add_argument("--sink", choices=["supabase", "memory"], default="supabase")
    p.add_argument("--repeat", type=int, default=1, help="repite la carga N veces con el mismo destino (solo memory)")
    args = p.parse_args(argv)

    if args.repeat > 1 and (args.dry_run or args.sink != "memory"):
        print("--repeat solo tiene sentido con --sink memory", file=sys.stderr)
        return 2
    if not args.parquet_dir.is_dir() or not args.manifest.is_file():
        print(f"No existen {args.parquet_dir} o {args.manifest}. Ejecuta el ETL primero.", file=sys.stderr)
        return 2

    sink = build_sink("count" if args.dry_run else args.sink)
    exit_code = 0
    try:
        for run in range(1, args.repeat + 1):
            report = ingest(iter_batches(args.parquet_dir, args.manifest), sink)
            label = "DRY-RUN" if args.dry_run else f"carga {run}/{args.repeat}"
            print(f"== {label} ==")
            print(json.dumps(report.summary(), indent=2, ensure_ascii=False))
            for o in report.problems:
                print(f"RECHAZADO {o.name}: {o.problem}", file=sys.stderr)
            if not report.ok:
                exit_code = 1
            if run > 1 and report.summary()["filas_escritas"] == 0:
                print("Segunda ejecucion: sin cambios.")
    except DomainError as exc:
        print(f"Error estructural: {exc}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
