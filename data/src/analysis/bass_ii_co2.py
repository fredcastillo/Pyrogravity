"""Read-only, paired CO2 summaries for NASA PSI-25 BASS-II."""

from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from pathlib import Path
from statistics import median, quantiles

import pyarrow.parquet as pq
from psycopg import Connection
from psycopg.rows import dict_row

from ..database.nasa_loader import field_kind, read_manifest
from ..etl.nasa_etl import BASS_II, BASS_REPORT, DATA_DIR, PERCENT_BY_VOLUME


READINGS = ("initial_co2", "final_co2")
CONTEXT = ("test_number", "sample_number", "pi", "fuel_sample_material")
SOURCE_COLUMNS = {column.name: column for column in BASS_II.columns if column.name in READINGS + CONTEXT}
SENSOR_MIN = Decimal("0")
SENSOR_MAX = Decimal("5")
SENSOR_RESOLUTION = Decimal("0.1")
DELTA_UNIT = "percentage points"

SELECT_COLUMNS = """
    SELECT d.dataset_id, d.relative_path, d.sha256, d.row_count,
           i.psi_code, i.investigation_name, i.nasa_psi_url,
           c.column_ordinal, c.column_name, c.source_header, c.source_unit, c.value_kind
    FROM scientific.datasets AS d
    JOIN scientific.investigations AS i ON i.psi_code = d.psi_code
    LEFT JOIN scientific.dataset_columns AS c ON c.dataset_id = d.dataset_id
    WHERE d.psi_code = %s AND d.relative_path = %s AND d.sha256 = %s
    ORDER BY c.column_ordinal
"""

SELECT_RECORDS = """
    SELECT r.source_record, r.original_values, r.text_cell_statuses,
           r.quality_flags AS anomalies,
           initial.interpretation_status AS initial_co2_status,
           initial.numeric_value AS initial_co2,
           final.interpretation_status AS final_co2_status,
           final.numeric_value AS final_co2
    FROM scientific.records AS r
    LEFT JOIN scientific.measurements AS initial
      ON initial.dataset_id = r.dataset_id AND initial.source_record = r.source_record
      AND initial.column_ordinal = %s
    LEFT JOIN scientific.measurements AS final
      ON final.dataset_id = r.dataset_id AND final.source_record = r.source_record
      AND final.column_ordinal = %s
    WHERE r.dataset_id = %s
    ORDER BY r.source_record
"""


def _column_metadata(columns):
    selected = {}
    for ordinal, name, header, unit, kind in columns:
        if name not in SOURCE_COLUMNS:
            continue
        expected = SOURCE_COLUMNS[name]
        if name in selected or (header, unit, kind) != (
            expected.header, expected.unit, field_kind(expected.kind)
        ):
            raise ValueError(f"Unexpected BASS-II column metadata: {name}")
        selected[name] = {"ordinal": ordinal, "source_header": header, "unit": unit, "type": kind}
    if selected.keys() != SOURCE_COLUMNS.keys():
        raise ValueError("Missing required BASS-II columns")
    return selected


def analyze_parquet(data_dir: Path = DATA_DIR, *, pi: str | None = None, material: str | None = None) -> dict:
    """Analyze the BASS-II version named by the local manifest."""
    path = BASS_II.source.as_posix()
    entry = read_manifest(data_dir / "source_manifest.csv").get(path)
    parquet_name = f"{BASS_II.study.lower()}_{BASS_II.name}.parquet"
    if entry is None or (entry["psi_code"], entry["source_filename"], entry["parquet_filename"]) != (
        BASS_II.study, BASS_II.source.name, parquet_name
    ):
        raise ValueError("No matching BASS-II version in the source manifest")

    parquet = pq.ParquetFile(data_dir / "processed" / parquet_name)
    schema = parquet.schema_arrow
    metadata = schema.metadata or {}
    for key, expected in {
        b"source_path": path,
        b"source_sha256": entry["sha256"],
        b"source_investigation": entry["nasa_psi_url"],
    }.items():
        if metadata.get(key) != expected.encode():
            raise ValueError(f"BASS-II Parquet provenance differs from the manifest: {key.decode()}")

    original_fields = [field for field in schema if b"source_header" in (field.metadata or {})]
    columns = _column_metadata(
        (ordinal, field.name, field.metadata[b"source_header"].decode(),
         field.metadata[b"source_unit"].decode() if b"source_unit" in field.metadata else None,
         field_kind(field.type))
        for ordinal, field in enumerate(original_fields, start=1)
        if field.name in SOURCE_COLUMNS
    )
    field_names = ["source_record", "source_study", "anomalies", *CONTEXT, *READINGS]
    field_names.extend(f"{name}_status" for name in CONTEXT + READINGS)
    field_names.extend(f"{name}_raw" for name in READINGS)
    if not set(field_names).issubset(schema.names):
        raise ValueError("Missing required BASS-II Parquet fields")
    rows = parquet.read(columns=field_names).to_pylist()
    if any(row["source_study"] != BASS_II.study for row in rows):
        raise ValueError("Unexpected study in BASS-II Parquet records")
    return _analyze(entry, int(entry["row_count"]), columns, rows, pi=pi, material=material)


def analyze_postgres(
    connection: Connection, sha256: str, *, pi: str | None = None, material: str | None = None,
) -> dict:
    """Run SELECTs on a caller-managed psycopg connection for an explicit CSV version."""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(SELECT_COLUMNS, (BASS_II.study, BASS_II.source.as_posix(), sha256))
        catalog = cursor.fetchall()
        if not catalog:
            raise ValueError("BASS-II dataset version is missing or not visible")
        dataset = catalog[0]
        columns = _column_metadata(
            (row["column_ordinal"], row["column_name"], row["source_header"], row["source_unit"], row["value_kind"])
            for row in catalog
        )
        initial_ordinal, final_ordinal = (columns[name]["ordinal"] for name in READINGS)
        cursor.execute(SELECT_RECORDS, (initial_ordinal, final_ordinal, dataset["dataset_id"]))
        rows = cursor.fetchall()

    for row in rows:
        raw = row.pop("original_values")
        statuses = row.pop("text_cell_statuses")
        for name in CONTEXT:
            row[name] = raw[columns[name]["ordinal"] - 1]
            row[f"{name}_status"] = statuses.get(name)
        for name in READINGS:
            row[f"{name}_raw"] = raw[columns[name]["ordinal"] - 1]
    return _analyze(dataset, dataset["row_count"], columns, rows, pi=pi, material=material)


def _context(row, name):
    if row[f"{name}_status"] == "text":
        return row[name].strip() or None
    return None


def _exclusion_reason(reading):
    status, value = reading["status"], reading["value"]
    if status != "exact":
        return status or "missing_measurement"
    if not isinstance(value, Decimal) or not value.is_finite():
        return "invalid_numeric_value"
    if not SENSOR_MIN <= value <= SENSOR_MAX:
        return "outside_sensor_range"
    return None


def _statistics(deltas):
    if not deltas:
        return None
    quartiles = quantiles(deltas, n=4, method="inclusive") if len(deltas) > 1 else deltas * 3
    return {
        "minimum": min(deltas), "q1": quartiles[0], "median": median(deltas), "q3": quartiles[2],
        "maximum": max(deltas),
        "positive_count": sum(value > 0 for value in deltas),
        "negative_count": sum(value < 0 for value in deltas),
        "zero_count": sum(value == 0 for value in deltas),
        "below_sensor_resolution_count": sum(abs(value) < SENSOR_RESOLUTION for value in deltas),
    }


def _group_by(trials, field):
    groups = defaultdict(list)
    for trial in trials:
        if trial[field] is not None:
            groups[trial[field]].append(trial)
    summaries = {}
    for label, group in sorted(groups.items()):
        pairs = [trial for trial in group if "delta_co2" in trial]
        samples = {trial["sample_number"] for trial in pairs if trial["sample_number"] is not None}
        summaries[label] = {
            "trial_count": len(group), "valid_pair_count": len(pairs), "distinct_sample_count": len(samples),
            "source_records": [trial["source_record"] for trial in group],
            "statistics": _statistics([trial["delta_co2"] for trial in pairs]) if len(samples) >= 2 else None,
        }
    return summaries


def _json_ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _analyze(dataset, row_count, columns, rows, *, pi, material):
    if [row["source_record"] for row in rows] != list(range(1, row_count + 1)):
        raise ValueError("BASS-II records are incomplete or out of order for this dataset version")

    sample_records = defaultdict(list)
    for row in rows:
        sample = _context(row, "sample_number")
        if sample is not None:
            sample_records[sample].append(row["source_record"])

    filters = {"pi": pi.strip() if pi is not None else None,
               "fuel_sample_material": material.strip() if material is not None else None}
    with localcontext() as context:
        # Preserve the ETL decimal precision, including interpolation, under caller contexts.
        context.prec = 32
        results = _summarize(rows, filters, sample_records)
    return _json_ready({
        "analysis_id": "bass_ii_co2", "method_version": "1.0.0", "decimal_encoding": "string",
        "dataset": {
            **{key: dataset[key] for key in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")},
            "source_filename": BASS_II.source.name, "row_count": row_count, "columns": columns,
            "source_record_index": "1-based CSV data record, excluding the header",
        },
        "criteria": {
            "pairing": "same dataset version and source_record",
            "required_status": "exact", "reading_range_inclusive": [SENSOR_MIN, SENSOR_MAX],
            "reading_unit": PERCENT_BY_VOLUME, "delta_unit": DELTA_UNIT, "delta": "final_co2 - initial_co2",
            "quartiles": "inclusive linear interpolation", "group_minimum_distinct_samples": 2,
            "filters": filters,
        },
        "sensor": {"resolution": SENSOR_RESOLUTION, "delta_unit": DELTA_UNIT, "reference_url": BASS_REPORT},
        **results,
        "plots": {
            "scatter": {"data": "pairs", "x": "initial_co2", "y": "final_co2", "unit": PERCENT_BY_VOLUME,
                        "equality_line": [[SENSOR_MIN, SENSOR_MIN], [SENSOR_MAX, SENSOR_MAX]]},
            "delta_distribution": {"data": "pairs", "value": "delta_co2", "unit": DELTA_UNIT,
                                   "resolution_band": [-SENSOR_RESOLUTION, SENSOR_RESOLUTION]},
        },
        "warnings": [
            "Changes smaller than the published sensor resolution do not establish a physical change.",
            "Repeated sample identifiers are retained. Trials and grouped observations may be dependent.",
            "This describes paired concentration readings without estimating emitted mass or causal effects.",
            "Other recorded quality flags are carried through without excluding usable CO2 readings.",
        ],
    })


def _summarize(rows, filters, sample_records):
    pairs, exclusions = [], []
    reasons = Counter()
    selected_samples = set()
    for row in rows:
        trial = {name: _context(row, name) for name in CONTEXT}
        if any(value is not None and trial[name] != value for name, value in filters.items()):
            continue
        sample = trial["sample_number"]
        if sample is not None:
            selected_samples.add(sample)
        trial.update(source_record=row["source_record"], quality_flags=row["anomalies"],
                     repeated_sample=len(sample_records.get(sample, ())) > 1)
        readings = {
            name: {"value": row[name], "raw": row[f"{name}_raw"], "status": row[f"{name}_status"]}
            for name in READINGS
        }
        rejected = {name: reason for name, reading in readings.items() if (reason := _exclusion_reason(reading))}
        if rejected:
            reasons.update(f"{name}:{reason}" for name, reason in rejected.items())
            exclusions.append({**trial, "reasons": rejected, "readings": readings})
            continue
        initial, final = (readings[name]["value"] for name in READINGS)
        delta = final - initial
        pairs.append({**trial, "initial_co2": initial, "final_co2": final, "delta_co2": delta,
                      "below_sensor_resolution": abs(delta) < SENSOR_RESOLUTION, "readings": readings})

    trials = sorted(pairs + exclusions, key=lambda trial: trial["source_record"])
    return {
        "trial_count": len(trials), "filtered_out_count": len(rows) - len(trials),
        "valid_pair_count": len(pairs), "excluded_count": len(exclusions),
        "excluded_by_reading_reason": dict(sorted(reasons.items())), "exclusions": exclusions,
        "statistics": _statistics([pair["delta_co2"] for pair in pairs]),
        "distinct_sample_count": len(selected_samples),
        "repeated_samples": {sample: sample_records[sample] for sample in sorted(selected_samples)
                             if len(sample_records[sample]) > 1},
        "grouped_results": {field: _group_by(trials, field) for field in filters},
        "pairs": pairs,
    }
