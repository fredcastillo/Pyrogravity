"""Exporta las columnas de la demo desde los Parquet que genera el ETL."""

import json
from pathlib import Path

import pyarrow.parquet as parquet

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).with_name("snapshot.json")

DATASETS = {
    "flex": {
        "label": "FLEX",
        "trial": "flex_test_number",
        "metric": "burn_time",
        "metric_label": "Tiempo de combustión",
        "group": "fuel",
        "examples": ["1", "2", "3"],
    },
    "bass_ii": {
        "label": "BASS-II",
        "trial": "test_number",
        "metric": "calibrated_initial_o2",
        "metric_label": "Oxígeno inicial calibrado",
        "group": "fuel_sample_material",
        "examples": ["B1", "B2", "B3"],
    },
}


def export() -> None:
    datasets = {}
    for name, fields in DATASETS.items():
        trial, metric, group = (fields[key] for key in ("trial", "metric", "group"))
        status = f"{metric}_status"
        table = parquet.read_table(
            ROOT / "data" / "processed" / f"{name}.parquet",
            columns=[trial, metric, status, group, "source_record", "anomalies"],
        )
        metadata = table.schema.metadata
        records = []
        for row in table.to_pylist():
            value = row[metric]
            records.append(
                {
                    "trial": row[trial],
                    "value": str(value) if value is not None else None,
                    "status": row[status],
                    "material": row[group],
                    "source_record": row["source_record"],
                    "flags": row["anomalies"],
                }
            )

        datasets[name] = {
            "label": fields["label"],
            "metric": metric,
            "metric_label": fields["metric_label"],
            "unit": table.schema.field(metric).metadata[b"source_unit"].decode(),
            "examples": fields["examples"],
            "study": metadata[b"source_investigation"].decode().rsplit("/", 1)[-1],
            "source": metadata[b"source_investigation"].decode(),
            "source_path": metadata[b"source_path"].decode(),
            "source_sha256": metadata[b"source_sha256"].decode(),
            "records": records,
        }

    OUTPUT.write_text(json.dumps(datasets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export()
