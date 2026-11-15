"""Read-only analysis of recorded flow settings in NASA PSI-107 SPICE."""

from collections import Counter, defaultdict
from decimal import Context, Decimal, localcontext
from pathlib import Path
from statistics import quantiles

import pyarrow.parquet as pq
from psycopg import Connection
from psycopg.rows import dict_row

from ..database.nasa_loader import field_kind, read_manifest
from ..etl.nasa_etl import DATA_DIR


STUDY = "PSI-107"
DOI = "10.60555/9kbh-e962"
SOURCE = Path("raw/PSI-107_Experimental table_Spice.csv")
PARQUET = "psi-107_spice.parquet"
NOZZLE, AIR, FUEL_RATE = "nozzle_mm", "air_rate_cm_s", "fuel_rate_mg_s"
PRIMARY = (NOZZLE, AIR, FUEL_RATE)
TIMES = ("gmt_date", "gmt_ignition", "gmt_flame_off")
SOURCE_COLUMNS = {
    "gmt_date": ("GMT date", None), "gmt_ignition": ("GMT ignition", None),
    "gmt_flame_off": ("GMT  Flame Off ", None), "fuel": ("Fuel", None),
    NOZZLE: ("Nozzle (mm)", "mm"), "fuel_rate_sccm": ("Fuel Rate (sccm)", "sccm"),
    FUEL_RATE: ("Fuel Rate (mg/s)", "mg/s"), "hc_fuel_rate_mg_s": ("HC Fuel Rate (mg/s)", "mg/s"),
    AIR: ("Air Rate (cm/s)", "cm/s"),
}
NUMERIC = {name: unit for name, (_, unit) in SOURCE_COLUMNS.items() if unit is not None}
MIN_ASSOCIATION_ROWS = 5

SELECT_COLUMNS = """
    SELECT d.dataset_id, d.relative_path, d.sha256, d.row_count, d.column_count,
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


def _columns(fields, count):
    columns = {}
    for position, (ordinal, name, header, unit, kind) in enumerate(fields, start=1):
        expected = SOURCE_COLUMNS.get(name)
        if position != ordinal or name in columns or expected != (header, unit) or kind != (
            "decimal" if name in NUMERIC else "text"
        ):
            raise ValueError(f"Unexpected SPICE column metadata: {name}")
        columns[name] = {"ordinal": ordinal, "source_header": header, "unit": unit, "type": kind}
    if len(columns) != count or columns.keys() != SOURCE_COLUMNS.keys():
        raise ValueError("Missing required SPICE columns or mismatching column count")
    return columns


def analyze_parquet(data_dir: Path = DATA_DIR) -> dict:
    """Analyze the local SPICE Parquet version selected by the source manifest."""
    path = SOURCE.as_posix()
    entry = read_manifest(data_dir / "source_manifest.csv").get(path)
    if entry is None or (entry["psi_code"], entry["source_filename"], entry["parquet_filename"]) != (
        STUDY, SOURCE.name, PARQUET,
    ):
        raise ValueError("No matching SPICE version in the source manifest")
    with pq.ParquetFile(data_dir / "processed" / PARQUET) as parquet:
        schema = parquet.schema_arrow
        metadata = schema.metadata or {}
        for key, expected in {b"source_path": path, b"source_sha256": entry["sha256"],
                              b"source_investigation": entry["nasa_psi_url"]}.items():
            if metadata.get(key) != expected.encode():
                raise ValueError(f"SPICE Parquet provenance differs from the manifest: {key.decode()}")
        fields = [field for field in schema if b"source_header" in (field.metadata or {})]
        columns = _columns(
            ((ordinal, field.name, field.metadata[b"source_header"].decode(),
              field.metadata[b"source_unit"].decode() if b"source_unit" in field.metadata else None,
              field_kind(field.type)) for ordinal, field in enumerate(fields, start=1)),
            int(entry["column_count"]),
        )
        selected = ["source_record", "source_study", "anomalies", *columns]
        selected.extend(f"{name}_status" for name in columns)
        selected.extend(f"{name}_raw" for name in NUMERIC)
        if not set(selected).issubset(schema.names):
            raise ValueError("Missing required SPICE Parquet fields")
        records = parquet.read(columns=selected).to_pylist()
    rows = []
    for record in records:
        if record["source_study"] != STUDY:
            raise ValueError("Unexpected study in SPICE Parquet records")
        cells = {name: {"raw": record.get(f"{name}_raw", record[name]), "status": record[f"{name}_status"],
                        "value": record[name]} for name in columns}
        rows.append((record["source_record"], record["anomalies"], cells))
    return _analyze(entry, columns, rows)


def analyze_postgres(connection: Connection, sha256: str) -> dict:
    """Analyze an explicit SPICE version using only SELECTs on the caller connection."""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(SELECT_COLUMNS, (STUDY, SOURCE.as_posix(), sha256))
        catalog = cursor.fetchall()
        if not catalog:
            raise ValueError("SPICE dataset version is missing or not visible")
        dataset = catalog[0]
        columns = _columns(
            ((row["column_ordinal"], row["column_name"], row["source_header"], row["source_unit"],
              row["value_kind"]) for row in catalog), dataset["column_count"],
        )
        params = (dataset["dataset_id"],)
        cursor.execute(SELECT_RECORDS, params)
        originals = cursor.fetchall()
        cursor.execute(SELECT_MEASUREMENTS, params)
        measurements = {
            (row["source_record"], row["column_ordinal"]): (row["interpretation_status"], row["numeric_value"])
            for row in cursor.fetchall()
        }
    rows = []
    for original in originals:
        number = original["source_record"]
        cells = {}
        for name, column in columns.items():
            ordinal = column["ordinal"]
            raw = original["original_values"][ordinal - 1]
            if name in NUMERIC:
                status, value = measurements.get((number, ordinal), (None, None))
            else:
                status, value = original["text_cell_statuses"].get(name), raw
            cells[name] = {"raw": raw, "status": status, "value": value}
        rows.append((number, original["quality_flags"], cells))
    return _analyze(dataset, columns, rows)


def _status(cell):
    status = cell["status"]
    if status == "exact" and (not isinstance(cell["value"], Decimal) or not cell["value"].is_finite()):
        return "invalid_numeric_value"
    return status or "missing_measurement"


def _label(cell):
    return (cell["raw"].strip() or None) if cell["status"] == "text" else None


def _statistics(records):
    result = {}
    for name, unit in NUMERIC.items():
        cells = [row["cells"][name] for row in records]
        counts = Counter(_status(cell) for cell in cells)
        values = [cell["value"] for cell in cells if _status(cell) == "exact"]
        missing = sum(counts[key] for key in ("blank", "missing_marker", "missing_measurement"))
        summary = None
        if values:
            q1, median, q3 = quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
            summary = {"minimum": min(values), "q1": q1, "median": median, "q3": q3, "maximum": max(values),
                       "mean": (sum(values) / len(values)).quantize(Decimal("0.000000001"))}
        result[name] = {"unit": unit, "exact_count": len(values), "missing_count": missing,
                        "non_exact_or_invalid_count": len(cells) - len(values) - missing,
                        "zero_count": sum(value == 0 for value in values), "negative_count": sum(value < 0 for value in values),
                        "status_counts": dict(sorted(counts.items())), "summary": summary}
    return result


def _pearson(records):
    n = len(records)
    if n < MIN_ASSOCIATION_ROWS:
        return None
    x = [row[AIR] for row in records]
    y = [row[FUEL_RATE] for row in records]
    mean_x, mean_y = sum(x) / n, sum(y) / n
    dx = [value - mean_x for value in x]
    dy = [value - mean_y for value in y]
    variance_product = sum(value ** 2 for value in dx) * sum(value ** 2 for value in dy)
    if variance_product == 0:
        return None
    covariance = sum(a * b for a, b in zip(dx, dy, strict=True))
    return (covariance / variance_product.sqrt()).quantize(Decimal("0.0001"))


def _group_by(records, key):
    groups = defaultdict(list)
    for row in records:
        label = key(row)
        if label is not None:
            groups[label].append(row)
    return dict(sorted(groups.items()))


def _group_summary(rows):
    return {"record_count": len(rows), "source_records": [row["source_record"] for row in rows],
            "statistics": _statistics(rows)}


def _cohort(records, exclusions, *, additional_exclusions=0):
    nozzles = _group_by(records, lambda row: row[NOZZLE])
    grouped_by_nozzle = {}
    for nozzle, rows in nozzles.items():
        fuels = {}
        for fuel, group in _group_by(rows, lambda row: row["fuel"]).items():
            coefficient = _pearson(group)
            fuels[fuel] = {**_group_summary(group), "association": {
                "variables": [AIR, FUEL_RATE], "units": [NUMERIC[AIR], NUMERIC[FUEL_RATE]],
                "record_count": len(group), "pearson_r": coefficient,
            } if coefficient is not None else None}
        grouped_by_nozzle[format(nozzle, "f")] = {**_group_summary(rows), "by_fuel": fuels}
    grouped = {"nozzle": grouped_by_nozzle}
    for key in ("fuel", "gmt_date", "air_rate_sign", "fuel_rate_sign"):
        grouped[key] = {label: _group_summary(rows) for label, rows in _group_by(records, lambda row: row[key]).items()}
    return {**_group_summary(records), "excluded_count": len(exclusions),
            "additional_exclusions": additional_exclusions, "exclusions": exclusions,
            "excluded_by_field_reason": dict(sorted(Counter(
                f"{field}:{reason}" for row in exclusions for field, reason in row["reasons"].items()
            ).items())), "grouped_results": grouped}


def _sign(value):
    if value is None:
        return None
    return "negative" if value < 0 else "positive" if value > 0 else "zero"


def _assess_rows(rows, columns, digest):
    signatures = defaultdict(list)
    for number, _, cells in rows:
        signatures[tuple(cells[name]["raw"] for name in columns)].append(number)
    identical = [numbers for numbers in signatures.values() if len(numbers) > 1]
    repeated = {number for numbers in identical for number in numbers}
    records, available, conservative, exclusions, duplicates = [], [], [], [], []
    for number, flags, cells in rows:
        numeric = {name: cells[name]["value"] if _status(cells[name]) == "exact" else None for name in NUMERIC}
        time_labels = [_label(cells[name]) for name in TIMES]
        air_sign, fuel_sign = _sign(numeric[AIR]), _sign(numeric[FUEL_RATE])
        review = []
        if air_sign in ("negative", "zero"):
            review.append(f"{air_sign}_air_rate")
        if fuel_sign in ("negative", "zero"):
            review.append(f"{fuel_sign}_fuel_rate")
        if _sign(numeric[NOZZLE]) in ("negative", "zero"):
            review.append("nonpositive_nozzle")
        reference = {"source_record": number, "dataset_sha256": digest}
        record = {**reference, **numeric, "fuel": _label(cells["fuel"]), "gmt_date": time_labels[0],
                  "time_reference": time_labels if all(time_labels) else None,
                  "air_rate_sign": air_sign, "fuel_rate_sign": fuel_sign, "cells": cells,
                  "quality_flags": flags, "review_flags": review, "identical_source_row": number in repeated}
        records.append(record)
        reasons = {name: _status(cells[name]) for name in PRIMARY if numeric[name] is None}
        if reasons:
            exclusions.append({**reference, "reasons": reasons})
            continue
        available.append(record)
        if number in repeated:
            duplicates.append({**reference, "reasons": {"source_record": "identical_source_row"}})
        else:
            conservative.append(record)
    return records, available, conservative, exclusions, duplicates, identical


def _repetitions(records, available, identical):
    available_numbers = {row["source_record"] for row in available}
    time_groups = defaultdict(list)
    for row in records:
        if row["time_reference"] is not None:
            time_groups[tuple(row["time_reference"])].append(row["source_record"])
    conditions = defaultdict(list)
    for row in available:
        if row["fuel"] is not None:
            conditions[(row["fuel"], *(row[name] for name in PRIMARY))].append(row)
    return {
        "identical_rows": [{"source_records": numbers,
                            "available_source_records": [n for n in numbers if n in available_numbers]} for numbers in identical],
        "repeated_time_references": [
            {"labels": dict(zip(TIMES, key, strict=True)), "source_records": numbers}
            for key, numbers in sorted(time_groups.items()) if len(numbers) > 1
        ],
        "repeated_primary_conditions": [
            {"fuel": fuel, **dict(zip(PRIMARY, values, strict=True)), "source_records": [row["source_record"] for row in group],
             "distinct_time_references": len({tuple(row["time_reference"]) for row in group if row["time_reference"]})}
            for (fuel, *values), group in sorted(conditions.items()) if len(group) > 1
        ],
    }


def _json_ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _analyze(dataset, columns, rows):
    count = int(dataset["row_count"])
    if [number for number, _, _ in rows] != list(range(1, count + 1)):
        raise ValueError("SPICE records are incomplete or out of order for this dataset version")
    digest = dataset["sha256"]
    records, available, conservative, exclusions, duplicates, identical = _assess_rows(rows, columns, digest)
    with localcontext(Context(prec=80)):
        return _json_ready({
            "analysis_id": "spice_flow", "method_version": "1.0.0", "decimal_encoding": "string",
            "dataset": {**{key: dataset[key] for key in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")},
                        "doi": DOI, "source_filename": SOURCE.name, "row_count": count, "columns": columns,
                        "source_record_index": "1-based CSV data record, excluding the header"},
            "criteria": {
                "available": "finite exact readings for all three primary fields", "primary_fields": list(PRIMARY),
                "conservative": "available rows excluding all members of identical groups across every original CSV cell",
                "repeated_time_or_conditions": "diagnostic only. Neither is a unique test identifier.",
                "signed_and_zero_values": "preserved and flagged when relevant",
                "quartiles": "inclusive linear interpolation", "mean": "rounded to nine decimal places",
                "association": "Pearson within each recorded fuel and nozzle group, four decimals, nonzero variance",
                "association_minimum_records": MIN_ASSOCIATION_ROWS,
            },
            "records": records,
            "cohorts": {"available": _cohort(available, exclusions),
                        "conservative": _cohort(conservative, sorted(exclusions + duplicates, key=lambda row: row["source_record"]),
                                                additional_exclusions=len(duplicates))},
            "quality": {
                "numeric_fields": _statistics(records),
                "text_status_counts": {name: dict(sorted(Counter(_status(row["cells"][name]) for row in records).items()))
                                       for name in columns if name not in NUMERIC},
                "flagged_source_records": [row["source_record"] for row in records if row["quality_flags"]],
                "flow_review_records": [row["source_record"] for row in records if row["review_flags"]],
                **_repetitions(records, available, identical),
            },
            "plots": {
                "air_by_nozzle": {"value": AIR, "unit": NUMERIC[AIR], "group": NOZZLE},
                "fuel_by_nozzle": {"value": FUEL_RATE, "unit": NUMERIC[FUEL_RATE], "group": NOZZLE},
                "air_and_fuel": {"x": AIR, "x_unit": NUMERIC[AIR], "y": FUEL_RATE, "y_unit": NUMERIC[FUEL_RATE],
                                 "color": "fuel", "facet": NOZZLE},
                "by_fuel": {"data": "cohorts.*.grouped_results.fuel"},
                "quality": {"data": "quality", "selection_counts": "cohorts"},
                "points": {"data": "records", "cohort_selection": "cohorts.*.source_records", "key": "source_record"},
            },
            "warnings": [
                "This CSV contains operating conditions without a documented row-level smoke-point indicator.",
                "Signed air readings and zero fuel readings retain their recorded values. Direction is not inferred.",
                "The conservative cohort is a sensitivity check. Identical rows could be legitimate repeated observations.",
                "Time labels are unparsed and repeated times or numeric conditions do not prove duplicate tests.",
                "Fuel mix labels are kept separate. Mass flow and volumetric flow are not converted or combined.",
                "Pearson coefficients describe associations among recorded settings within a group. Observations may be dependent.",
            ],
        })
