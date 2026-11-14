"""Exporta las columnas de la demo usando el ETL del repositorio."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from data.src.etl.nasa_etl import run_etl

OUTPUT = Path(__file__).with_name("snapshot.json")

DATASETS = {
    "flex": {
        "table": "psi-69_flex",
        "label": "FLEX",
        "trial": "flex_test_number",
        "metric": "burn_time",
        "metric_label": "Tiempo de combustión",
        "group": "fuel",
        "examples": ["1", "2", "3"],
    },
    "bass_ii": {
        "table": "psi-25_bass_ii",
        "label": "BASS-II",
        "trial": "test_number",
        "metric": "calibrated_initial_o2",
        "metric_label": "Oxígeno inicial calibrado",
        "group": "fuel_sample_material",
        "examples": ["B1", "B2", "B3"],
    },
}


def export() -> None:
    with TemporaryDirectory(prefix="pyrogravity-etl-") as directory:
        tables = run_etl(output_dir=Path(directory))

    datasets = {}
    for name, fields in DATASETS.items():
        trial, metric, group = (fields[key] for key in ("trial", "metric", "group"))
        status = f"{metric}_status"
        table = tables[fields["table"]].select([trial, metric, status, group, "source_record", "anomalies"])
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
