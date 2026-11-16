"""Read-only summaries of initial droplet diameter and recorded burn duration in FLEX."""

from collections import Counter, defaultdict
from decimal import Context, Decimal, localcontext
from pathlib import Path
from statistics import quantiles

import pyarrow.parquet as pq
from psycopg import Connection
from psycopg.rows import dict_row

from ..database.nasa_loader import field_kind, read_manifest
from ..etl.nasa_etl import DATA_DIR, FLEX


DIAMETER = "droplet_initial_diameter"
DURATION = "burn_time"
PRESSURE = "ambient_pressure"
COMPOSITION_NAMES = {label: f"{label.lower()}_initial_ambient_composition" for label in ("O", "N", "CO", "He")}
NUMERIC_FIELDS = (DIAMETER, DURATION, PRESSURE, *COMPOSITION_NAMES.values())
TEXT_FIELDS = ("flex_test_number", "flex_identifier", "fuel", "test_end")
SOURCE_COLUMNS = {column.name: column for column in FLEX.columns if column.name in NUMERIC_FIELDS + TEXT_FIELDS}
REFERENCE_COMPOSITION = {"O": Decimal("0.21"), "N": Decimal("0.79"), "CO": Decimal("0"), "He": Decimal("0")}
REFERENCE_PRESSURE = (Decimal("740"), Decimal("780"))

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
    SELECT source_record, original_values, text_cell_statuses, quality_flags
    FROM scientific.records WHERE dataset_id = %s ORDER BY source_record
"""

SELECT_MEASUREMENTS = """
    SELECT source_record, column_ordinal, interpretation_status, numeric_value
    FROM scientific.measurements WHERE dataset_id = %s
"""


def _column_metadata(columns):
    selected = {}
    for ordinal, name, header, unit, kind in columns:
        if name not in SOURCE_COLUMNS:
            continue
        expected = SOURCE_COLUMNS[name]
        if name in selected or (header, unit, kind) != (expected.header, expected.unit, field_kind(expected.kind)):
            raise ValueError(f"Unexpected FLEX column metadata: {name}")
        selected[name] = {"ordinal": ordinal, "source_header": header, "unit": unit, "type": kind}
    if selected.keys() != SOURCE_COLUMNS.keys():
        raise ValueError("Missing required FLEX columns")
    return selected


def analyze_parquet(data_dir: Path = DATA_DIR) -> dict:
    """Analyze the FLEX Parquet version named by the local manifest."""
    path = FLEX.source.as_posix()
    entry = read_manifest(data_dir / "source_manifest.csv").get(path)
    parquet_name = f"{FLEX.study.lower()}_{FLEX.name}.parquet"
    if entry is None or (entry["psi_code"], entry["source_filename"], entry["parquet_filename"]) != (
        FLEX.study, FLEX.source.name, parquet_name
    ):
        raise ValueError("No matching FLEX version in the source manifest")

    with pq.ParquetFile(data_dir / "processed" / parquet_name) as parquet:
        schema = parquet.schema_arrow
        metadata = schema.metadata or {}
        for key, expected in {
            b"source_path": path,
            b"source_sha256": entry["sha256"],
            b"source_investigation": entry["nasa_psi_url"],
        }.items():
            if metadata.get(key) != expected.encode():
                raise ValueError(f"FLEX Parquet provenance differs from the manifest: {key.decode()}")
        original_fields = [field for field in schema if b"source_header" in (field.metadata or {})]
        columns = _column_metadata(
            (ordinal, field.name, field.metadata[b"source_header"].decode(),
             field.metadata[b"source_unit"].decode() if b"source_unit" in field.metadata else None,
             field_kind(field.type))
            for ordinal, field in enumerate(original_fields, start=1)
            if field.name in SOURCE_COLUMNS
        )
        fields = ["source_record", "source_study", "anomalies", *TEXT_FIELDS, *NUMERIC_FIELDS]
        fields.extend(f"{name}_status" for name in TEXT_FIELDS + NUMERIC_FIELDS)
        fields.extend(f"{name}_raw" for name in NUMERIC_FIELDS)
        if not set(fields).issubset(schema.names):
            raise ValueError("Missing required FLEX Parquet fields")
        rows = parquet.read(columns=fields).to_pylist()
    if any(row["source_study"] != FLEX.study for row in rows):
        raise ValueError("Unexpected study in FLEX Parquet records")
    return _analyze(entry, columns, rows)


def analyze_postgres(connection: Connection, sha256: str) -> dict:
    """Analyze an explicit FLEX version using SELECTs on a caller-managed connection."""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(SELECT_COLUMNS, (FLEX.study, FLEX.source.as_posix(), sha256))
        catalog = cursor.fetchall()
        if not catalog:
            raise ValueError("FLEX dataset version is missing or not visible")
        dataset = catalog[0]
        columns = _column_metadata(
            (row["column_ordinal"], row["column_name"], row["source_header"], row["source_unit"], row["value_kind"])
            for row in catalog
        )
        key = (dataset["dataset_id"],)
        cursor.execute(SELECT_RECORDS, key)
        originals = cursor.fetchall()
        cursor.execute(SELECT_MEASUREMENTS, key)
        measurements = {
            (row["source_record"], row["column_ordinal"]): (row["interpretation_status"], row["numeric_value"])
            for row in cursor.fetchall()
        }

    rows = []
    for original in originals:
        number = original["source_record"]
        values = original["original_values"]
        row = {"source_record": number, "anomalies": original["quality_flags"]}
        for name in TEXT_FIELDS:
            row[name] = values[columns[name]["ordinal"] - 1]
            row[f"{name}_status"] = original["text_cell_statuses"].get(name)
        for name in NUMERIC_FIELDS:
            ordinal = columns[name]["ordinal"]
            row[f"{name}_raw"] = values[ordinal - 1]
            row[f"{name}_status"], row[name] = measurements.get((number, ordinal), (None, None))
        rows.append(row)
    return _analyze(dataset, columns, rows)


def _labels(row):
    return {name: (row[name].strip() or None) if row[f"{name}_status"] == "text" else None for name in TEXT_FIELDS}


def _reading_exclusion(name, reading):
    status, value = reading["status"], reading["value"]
    if status != "exact":
        return status or "missing_measurement"
    if not isinstance(value, Decimal) or not value.is_finite():
        return "invalid_numeric_value"
    if name in COMPOSITION_NAMES.values():
        if not 0 <= value <= 1:
            return "outside_fraction_range"
    elif value <= 0:
        return "nonpositive"
    return None


def _statistics(values):
    if not values:
        return None
    q1, middle, q3 = quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
    return {"minimum": min(values), "q1": q1, "median": middle, "q3": q3, "maximum": max(values)}


def _pearson(diameters, durations):
    count = len(diameters)
    if count < 3:
        return None
    mean_x, mean_y = sum(diameters) / count, sum(durations) / count
    dx = [value - mean_x for value in diameters]
    dy = [value - mean_y for value in durations]
    variance_product = sum(value ** 2 for value in dx) * sum(value ** 2 for value in dy)
    if not variance_product:
        return None
    covariance = sum(x * y for x, y in zip(dx, dy, strict=True))
    return (covariance / variance_product.sqrt()).quantize(Decimal("0.0001"))


def _summary(pairs):
    diameters = [row[DIAMETER] for row in pairs]
    durations = [row[DURATION] for row in pairs]
    return {
        "valid_pair_count": len(pairs), "source_records": [row["source_record"] for row in pairs],
        "statistics": {DIAMETER: _statistics(diameters), DURATION: _statistics(durations),
                       "pearson_r": _pearson(diameters, durations)},
        "termination_counts": dict(sorted(Counter(row["test_end"] for row in pairs).items())),
    }


def _group_by_fuel(pairs):
    fuels = defaultdict(list)
    for row in pairs:
        fuels[row["fuel"]].append(row)
    summaries = {}
    for fuel, group in sorted(fuels.items()):
        categories = defaultdict(list)
        for row in group:
            categories[row["test_end"]].append(row)
        summaries[fuel] = {
            **_summary(group), "by_test_end": {label: _summary(rows) for label, rows in sorted(categories.items())},
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


def _analyze(dataset, columns, rows):
    row_count = int(dataset["row_count"])
    if [row["source_record"] for row in rows] != list(range(1, row_count + 1)):
        raise ValueError("FLEX records are incomplete or out of order for this dataset version")
    with localcontext(Context(prec=32)):
        results = _summarize(rows)
    return _json_ready({
        "analysis_id": "flex_combustion", "method_version": "1.0.0", "decimal_encoding": "string",
        "dataset": {
            **{key: dataset[key] for key in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")},
            "source_filename": FLEX.source.name, "row_count": row_count, "columns": columns,
            "source_record_index": "1-based CSV data record, excluding the header",
        },
        "criteria": {
            "pairing": "same dataset version and source_record", "required_status": "exact",
            "positive_fields": [DIAMETER, DURATION, PRESSURE], "fraction_range_inclusive": [0, 1],
            "required_labels": list(TEXT_FIELDS), "repeated_identifiers": "exclude all records sharing an identifier",
            "quartiles": "inclusive linear interpolation", "pearson_r": "descriptive, four decimals, at least three pairs",
        },
        **results,
        "plots": {
            "scatter": {"data": "pairs", "x": DIAMETER, "x_unit": "mm", "y": DURATION, "y_unit": "s",
                        "color": "fuel", "facet": "test_end"},
            "by_termination": {"data": "pairs", "category": "test_end", "group": "fuel", "value": DURATION, "unit": "s"},
            "condition_comparison": {"data": "pairs", "selection": "condition_comparison.source_records",
                                     "x": DIAMETER, "x_unit": "mm", "y": DURATION, "y_unit": "s",
                                     "group": "fuel", "facet": "test_end"},
        },
        "warnings": [
            "Burn time is the recorded duration. Only Extinction is labeled as extinction in the source.",
            "O, N, CO and He retain their CSV labels. Fractions are neither rescaled nor assigned chemical species.",
            "Burning rate; mm is outside this analysis and no rate unit is inferred.",
            "The pressure window and recorded fractions define a descriptive subset. Other conditions may differ.",
            "Repeated identifiers are excluded conservatively. The remaining rows may still be dependent.",
            "The summaries and Pearson correlations describe associations without controlling for other conditions.",
        ],
    })


def _summarize(rows):
    identifiers = ("flex_identifier", "flex_test_number")
    occurrences = {name: defaultdict(list) for name in identifiers}
    for row in rows:
        labels = _labels(row)
        for name in identifiers:
            if labels[name] is not None:
                occurrences[name][labels[name]].append(row["source_record"])
    repeats = {name: {label: records for label, records in sorted(groups.items()) if len(records) > 1}
               for name, groups in occurrences.items()}

    pairs, exclusions = [], []
    reason_counts = Counter()
    for row in rows:
        labels = _labels(row)
        readings = {name: {"value": row[name], "raw": row[f"{name}_raw"], "status": row[f"{name}_status"]}
                    for name in NUMERIC_FIELDS}
        repeated_fields = [name for name in identifiers if labels[name] in repeats[name]]
        record = {**labels, "source_record": row["source_record"], "quality_flags": row["anomalies"],
                  "repeated_identifier_fields": repeated_fields, "readings": readings}
        reasons = {name: reason for name, reading in readings.items() if (reason := _reading_exclusion(name, reading))}
        for name, label in labels.items():
            if label is None:
                status = row[f"{name}_status"]
                reasons[name] = status if status not in (None, "text") else "missing_label"
        reasons.update({name: "repeated_identifier" for name in repeated_fields})
        if reasons:
            reason_counts.update(f"{name}:{reason}" for name, reason in reasons.items())
            exclusions.append({**record, "reasons": reasons})
            continue
        composition = {label: row[name] for label, name in COMPOSITION_NAMES.items()}
        pairs.append({**record, DIAMETER: row[DIAMETER], DURATION: row[DURATION], PRESSURE: row[PRESSURE],
                      "recorded_composition": composition})

    lower, upper = REFERENCE_PRESSURE
    reference = [row for row in pairs if row["recorded_composition"] == REFERENCE_COMPOSITION
                 and lower <= row[PRESSURE] <= upper]
    return {
        "trial_count": len(rows), **_summary(pairs), "excluded_count": len(exclusions),
        "excluded_by_field_reason": dict(sorted(reason_counts.items())), "exclusions": exclusions,
        "repeated_identifiers": repeats, "grouped_results": _group_by_fuel(pairs), "pairs": pairs,
        "condition_comparison": {
            "recorded_composition": REFERENCE_COMPOSITION, "pressure_range_inclusive": [lower, upper],
            "pressure_unit": "mmHg", **_summary(reference), "grouped_results": _group_by_fuel(reference),
        },
    }
