import argparse
import csv
import os
import json
from typing import Protocol
try:
    import pyarrow.parquet as pq  # type: ignore
except Exception:  # pragma: no cover
    pq = None


class IngestionSink(Protocol):
    def upsert(self, table: str, rows: list[dict]) -> int: ...


class InMemorySink:
    def __init__(self):
        self.data = {}
    def upsert(self, table, rows):
        self.data.setdefault(table, [])
        self.data[table].extend(rows)
        return len(rows)


class CountingSink:
    def __init__(self):
        self.counts = {}
    def upsert(self, table, rows):
        self.counts[table] = self.counts.get(table, 0) + len(rows)
        return len(rows)


class SupabaseSink:
    def __init__(self, client):
        self.client = client
    def upsert(self, table, rows):
        try:
            self.client.table(table).upsert(rows).execute()
            return len(rows)
        except Exception as e:
            from app.domain.errors import RepositoryError
            raise RepositoryError(str(e))


def read_manifest(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def process_parquet(path, manifest_row, sink, dry_run):
    table = pq.read_table(path)
    meta = table.schema.metadata or {}
    def m(k):
        v = meta.get(k.encode()) if isinstance(k, str) else None
        return v.decode() if v else None
    sha = m("source_sha256")
    if sha != manifest_row.get("sha256"):
        raise ValueError("sha256 inconsistente")
    rows = table.to_pylist()
    # columns metadata
    col_meta = json.loads(m("columns") or "{}") if m("columns") else {}
    empty_count = 0
    trials_loaded = 0
    status_counts = {}
    no_unit = 0
    for r in rows:
        if r.get("source_row_empty"):
            empty_count += 1
            continue
        trial_id = f"{manifest_row.get('psi_code')}:{manifest_row.get('table_name')}:{r.get('source_record')}"
        attrs = {k: v for k, v in r.items() if isinstance(v, str)}
        sink.upsert("trials", [{"id": trial_id, "dataset_id": manifest_row.get("dataset_id"), "source_record": r.get("source_record"), "label": str(r.get("source_record")), "anomalies": r.get("anomalies", []), "quantitative_candidate": r.get("quantitative_candidate", False), "attributes": attrs}])
        trials_loaded += 1
        for col, cm in col_meta.items():
            if col not in r:
                continue
            if cm.get("type") != "numeric":
                continue
            val = r.get(col)
            if val is None or val == "":
                continue
            status = r.get(f"{col}_status", "exact")
            raw = r.get(f"{col}_raw", str(val))
            status_counts[status] = status_counts.get(status, 0) + 1
            unit = cm.get("unit")
            if unit is None:
                no_unit += 1
            value = float(val) if status == "exact" else None
            sink.upsert("measurements", [{"trial_id": trial_id, "variable_id": f"{manifest_row.get('dataset_id')}:{col}", "value": value, "raw_value": raw, "status": status, "unit": unit}])
        # variables
        for col, cm in col_meta.items():
            if cm.get("type") == "numeric":
                sink.upsert("variables", [{"id": f"{manifest_row.get('dataset_id')}:{col}", "dataset_id": manifest_row.get("dataset_id"), "column_name": col, "source_header": cm.get("source_header"), "unit": cm.get("unit"), "unit_known": cm.get("unit") is not None, "canonical_variable": cm.get("canonical_variable")}])
    return {"trials": trials_loaded, "empty": empty_count, "status": status_counts, "no_unit": no_unit}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--parquet-dir", default="data/processed")
    p.add_argument("--manifest", default="data/source_manifest.csv")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sink = CountingSink() if args.dry_run else InMemorySink()

    manifest = read_manifest(args.manifest)
    datasets = 0
    total_trials = 0
    total_empty = 0
    total_status = {}
    total_no_unit = 0
    for mrow in manifest:
        fname = mrow.get("parquet_file") or mrow.get("file")
        path = os.path.join(args.parquet_dir, fname)
        if not os.path.exists(path):
            print("MISSING", path)
            continue
        try:
            rep = process_parquet(path, mrow, sink, args.dry_run)
        except Exception as e:
            print("STRUCTURAL ERROR", e)
            raise SystemExit(1)
        datasets += 1
        total_trials += rep["trials"]
        total_empty += rep["empty"]
        for k, v in rep["status"].items():
            total_status[k] = total_status.get(k, 0) + v
        total_no_unit += rep["no_unit"]

    print(f"datasets={datasets}")
    print(f"trials_loaded={total_trials}")
    print(f"empty_omitted={total_empty}")
    print(f"status_counts={total_status}")
    print(f"cells_without_unit={total_no_unit}")
    if args.dry_run:
        print("dry-run: no writes")


if __name__ == "__main__":
    main()
