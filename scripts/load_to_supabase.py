"""Carga los Parquet del ETL y el manifiesto en Supabase o PostgreSQL.

Modos:
- Ingesta por lotes (por defecto): usa app.application.ingestion_service.
- Compatibilidad PostgreSQL (--data-dir): delega en data.src.database.nasa_loader.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.src.database.nasa_loader import DATABASE_URL, LoadError, load_datasets, prepare_load

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_sink(kind: str):
    from app.infrastructure.ingestion.sinks import CountingSink, InMemorySink, SupabaseSink

    if kind == "count":
        return CountingSink()
    if kind == "memory":
        return InMemorySink()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("Faltan SUPABASE_URL y SUPABASE_SERVICE_KEY (la clave solo vive en el servidor).")
    from supabase import create_client  # import tardio: no se necesita en dry-run

    return SupabaseSink(create_client(url, key))


def run_compatibility_mode(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    root = args.data_dir.resolve()
    if args.manifest and args.manifest.resolve() != root / "source_manifest.csv":
        parser.error("--manifest debe ser source_manifest.csv dentro de --data-dir")
    if args.parquet_dir and args.parquet_dir.resolve() != root / "processed":
        parser.error("--parquet-dir debe ser processed dentro de --data-dir")

    try:
        datasets = prepare_load(root)
        inserted = 0 if args.dry_run else load_datasets(datasets, os.environ.get(DATABASE_URL, ""))
    except LoadError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"datasets={len(datasets)} records={sum(len(d.records) for d in datasets)} inserted={inserted}")
    if args.dry_run:
        print("dry-run: datos y procedencia validados; sin conexion ni escrituras")
    return 0


def run_ingestion_mode(args: argparse.Namespace) -> int:
    from app.application.ingestion_service import ingest
    from app.domain.errors import DomainError
    from app.infrastructure.ingestion.parquet_reader import iter_batches

    parquet_dir = args.parquet_dir or (REPO_ROOT / "data" / "processed")
    manifest = args.manifest or (REPO_ROOT / "data" / "source_manifest.csv")

    if args.repeat > 1 and (args.dry_run or args.sink != "memory"):
        print("--repeat solo tiene sentido con --sink memory", file=sys.stderr)
        return 2
    if not parquet_dir.is_dir() or not manifest.is_file():
        print(f"No existen {parquet_dir} o {manifest}. Ejecuta el ETL primero.", file=sys.stderr)
        return 2

    sink = build_sink("count" if args.dry_run else args.sink)
    exit_code = 0
    try:
        for run in range(1, args.repeat + 1):
            report = ingest(iter_batches(parquet_dir, manifest), sink)
            label = "DRY-RUN" if args.dry_run else f"carga {run}/{args.repeat}"
            print(f"== {label} ==")
            print(json.dumps(report.summary(), indent=2, ensure_ascii=False))
            for outcome in report.problems:
                print(f"RECHAZADO {outcome.name}: {outcome.problem}", file=sys.stderr)
            if not report.ok:
                exit_code = 1
            if run > 1 and report.summary()["filas_escritas"] == 0:
                print("Segunda ejecucion: sin cambios.")
    except DomainError as exc:
        print(f"Error estructural: {exc}", file=sys.stderr)
        return 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--parquet-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dry-run", "--validate-only", action="store_true", help="no escribe nada")
    parser.add_argument("--sink", choices=["supabase", "memory"], default="supabase")
    parser.add_argument("--repeat", type=int, default=1, help="repite la carga N veces con el mismo destino (solo memory)")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        return run_compatibility_mode(args, parser)
    return run_ingestion_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
