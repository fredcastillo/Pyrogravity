"""Exporta las columnas de la demo usando el ETL del repositorio."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from data.src.etl.nasa_etl import run_etl
from data.src.etl.nasa_tables import INVESTIGATION_TITLES

OUTPUT = Path(__file__).with_name("snapshot.json")
CATALOG = Path(__file__).with_name("web") / "assets" / "catalog.json"

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
    catalog = [catalog_entry(name, table) for name, table in tables.items()]
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def catalog_entry(name, table) -> dict:
    metadata = {key.decode(): value.decode() for key, value in table.schema.metadata.items()}
    study = metadata["source_investigation"].rsplit("/", 1)[-1]
    source_file = Path(metadata["source_path"])
    source_columns = [field for field in table.schema if field.metadata and b"source_header" in field.metadata]
    columns = [
        {
            "label": field.metadata[b"source_header"].decode(),
            "unit": field.metadata.get(b"source_unit", b"").decode(),
        }
        for field in source_columns
    ]
    input_names = set(table.column_names)
    original_values = [
        f"{field.name}_raw" if f"{field.name}_raw" in input_names else field.name
        for field in source_columns
    ]
    rows = table.select(["source_record", "source_row_empty", *original_values]).to_pylist()
    return {
        "id": name,
        "study": study,
        "title": INVESTIGATION_TITLES[study],
        "label": source_file.stem.split("_", 2)[-1].replace("_", " "),
        "source": metadata["source_investigation"],
        "source_path": metadata["source_path"],
        "source_sha256": metadata["source_sha256"],
        "scope": metadata["source_scope"],
        "row_count": table.num_rows,
        "columns": columns,
        "rows": [
            [row["source_record"], *(row[column] for column in original_values)]
            for row in rows
            if not row["source_row_empty"]
        ],
    }


if __name__ == "__main__":
    export()
