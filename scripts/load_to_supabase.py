"""Delegate ingestion to Stanley's validated scientific loader."""
import argparse
import os
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.src.database.nasa_loader import DATABASE_URL, LoadError, load_datasets, prepare_load
from data.src.etl.nasa_etl import DATA_DIR

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--parquet-dir", type=Path)
    parser.add_argument("--dry-run", "--validate-only", action="store_true")
    args = parser.parse_args(argv)
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

if __name__ == "__main__":
    raise SystemExit(main())
