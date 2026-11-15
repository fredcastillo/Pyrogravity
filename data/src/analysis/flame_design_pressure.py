"""Read-only paired pressures for the two NASA PSI-10 Flame Design datasets."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Context, Decimal, localcontext
from pathlib import Path
from statistics import quantiles

import pyarrow.parquet as pq
from psycopg import Connection
from psycopg.rows import dict_row

from ..database.nasa_loader import field_kind, read_manifest
from ..etl.nasa_etl import DATA_DIR, snake_case


STUDY = "PSI-10"
TITLES = {"normal": "Flame Design_Normal Flame", "inverse": "Flame Design_Inverse Flame"}
PATHS = {name: f"raw/{STUDY}_Experimental table_{title}.csv" for name, title in TITLES.items()}
PRESSURES = {"pinit_atm": "pinit (atm)", "pfinal_atm": "pfinal (atm)"}
CONTEXT_HEADERS = {"flame_type": "Flame Type", "day": "Day", "test": "Test", "fuel": "Fuel"}
UNIT = "atm"

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


def _columns(fields, configuration, count):
    columns = {}
    for position, (ordinal, name, header, unit, kind) in enumerate(fields, start=1):
        if position != ordinal or name in columns:
            raise ValueError(f"Invalid Flame Design column order or name: {configuration}")
        columns[name] = {"ordinal": ordinal, "source_header": header, "unit": unit, "type": kind}
    if len(columns) != count:
        raise ValueError(f"Flame Design column count differs from provenance: {configuration}")
    for name, header in PRESSURES.items():
        column = columns.get(name, {})
        if (column.get("source_header"), column.get("type"), column.get("unit")) != (header, "decimal", UNIT):
            raise ValueError(f"Invalid Flame Design pressure metadata: {configuration}, {header}")
    for name, header in CONTEXT_HEADERS.items():
        if name == "fuel" and configuration == "inverse" and name not in columns:
            continue
        column = columns.get(name, {})
        if (column.get("source_header"), column.get("type")) != (header, "text"):
            raise ValueError(f"Invalid Flame Design context column: {configuration}, {header}")
    return columns


def analyze_parquet(data_dir: Path = DATA_DIR) -> dict:
    """Analyze both Flame Design files selected by the local source manifest."""
    manifest = read_manifest(data_dir / "source_manifest.csv")
    configurations = {}
    for configuration, path in PATHS.items():
        entry = manifest.get(path)
        parquet_name = f"{STUDY.lower()}_{snake_case(TITLES[configuration])}.parquet"
        if entry is None or (entry["psi_code"], entry["source_filename"], entry["parquet_filename"]) != (
            STUDY, Path(path).name, parquet_name,
        ):
            raise ValueError(f"No matching Flame Design version in the manifest: {configuration}")
        with pq.ParquetFile(data_dir / "processed" / parquet_name) as parquet:
            schema = parquet.schema_arrow
            metadata = schema.metadata or {}
            for key, value in {b"source_path": path, b"source_sha256": entry["sha256"],
                               b"source_investigation": entry["nasa_psi_url"]}.items():
                if metadata.get(key) != value.encode():
                    raise ValueError(f"Flame Design Parquet provenance differs: {configuration}, {key.decode()}")
            fields = [f for f in schema if b"source_header" in (f.metadata or {})]
            columns = _columns(
                ((ordinal, field.name, field.metadata[b"source_header"].decode(),
                  field.metadata[b"source_unit"].decode() if b"source_unit" in field.metadata else None,
                  field_kind(field.type)) for ordinal, field in enumerate(fields, start=1)),
                configuration, int(entry["column_count"]),
            )
            selected = ["source_record", "source_study", "anomalies"]
            for name, column in columns.items():
                selected.extend((name, f"{name}_status"))
                if column["type"] != "text":
                    selected.append(f"{name}_raw")
            if not set(selected).issubset(schema.names):
                raise ValueError(f"Missing Flame Design Parquet fields: {configuration}")
            source_rows = parquet.read(columns=selected).to_pylist()
        rows = []
        for record in source_rows:
            if record["source_study"] != STUDY:
                raise ValueError(f"Unexpected study in Flame Design Parquet records: {configuration}")
            cells = {name: {"raw": record.get(f"{name}_raw", record[name]), "status": record[f"{name}_status"],
                            "value": record[name]} for name in columns}
            rows.append((record["source_record"], record["anomalies"], cells))
        configurations[configuration] = _analyze_dataset(configuration, entry, columns, rows)
    return _result(configurations)


def analyze_postgres(connection: Connection, sha256_by_configuration: Mapping[str, str]) -> dict:
    """Read explicit normal and inverse versions using a caller-managed connection."""
    if sha256_by_configuration.keys() != PATHS.keys():
        raise ValueError("Provide a SHA-256 for each Flame Design configuration: normal and inverse")
    configurations = {}
    with connection.cursor(row_factory=dict_row) as cursor:
        for configuration, path in PATHS.items():
            cursor.execute(SELECT_COLUMNS, (STUDY, path, sha256_by_configuration[configuration]))
            catalog = cursor.fetchall()
            if not catalog:
                raise ValueError(f"Flame Design dataset version is missing or not visible: {configuration}")
            dataset = catalog[0]
            columns = _columns(
                ((row["column_ordinal"], row["column_name"], row["source_header"], row["source_unit"],
                  row["value_kind"]) for row in catalog), configuration, dataset["column_count"],
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
            for record in originals:
                number = record["source_record"]
                cells = {}
                for name, column in columns.items():
                    ordinal = column["ordinal"]
                    raw = record["original_values"][ordinal - 1]
                    if column["type"] == "text":
                        status, value = record["text_cell_statuses"].get(name), raw
                    else:
                        status, value = measurements.get((number, ordinal), (None, None))
                    cells[name] = {"raw": raw, "status": status, "value": value}
                rows.append((number, record["quality_flags"], cells))
            configurations[configuration] = _analyze_dataset(configuration, dataset, columns, rows)
    return _result(configurations)


def _label(cells, name):
    cell = cells.get(name)
    return (cell["raw"].strip() or None) if cell and cell["status"] == "text" else None


def _pressure_exclusion(cell):
    status, value = cell["status"], cell["value"]
    if status != "exact":
        return status or "missing_measurement"
    if not isinstance(value, Decimal) or not value.is_finite():
        return "invalid_numeric_value"
    return "nonpositive_pressure" if value <= 0 else None


def _statistics(deltas):
    if not deltas:
        return None
    q1, median, q3 = quantiles(deltas, n=4, method="inclusive") if len(deltas) > 1 else deltas * 3
    return {
        "minimum": min(deltas), "q1": q1, "median": median, "q3": q3, "maximum": max(deltas),
        "positive_count": sum(delta > 0 for delta in deltas), "zero_count": sum(delta == 0 for delta in deltas),
        "negative_count": sum(delta < 0 for delta in deltas),
    }


def _summary(records, sha256, minimum_pairs):
    deltas = [record["delta_pressure"] for record in records if "delta_pressure" in record]
    return {
        "dataset_sha256": sha256, "unit": UNIT, "trial_count": len(records), "valid_pair_count": len(deltas),
        "excluded_count": len(records) - len(deltas), "source_records": [row["source_record"] for row in records],
        "statistics": _statistics(deltas) if len(deltas) >= minimum_pairs else None,
    }


def _grouped(records, name, sha256):
    groups = defaultdict(list)
    for record in records:
        if record[name] is not None:
            groups[record[name]].append(record)
    order = sorted(groups)
    if name == "day":
        order.sort(key=lambda label: (0, int(label)) if label.isdecimal() else (1, label))
    return {label: _summary(groups[label], sha256, 2) for label in order}


def _analyze_dataset(configuration, dataset, columns, rows):
    row_count = int(dataset["row_count"])
    if [number for number, _, _ in rows] != list(range(1, row_count + 1)):
        raise ValueError(f"Flame Design records are incomplete or out of order: {configuration}")
    tests, originals = defaultdict(list), defaultdict(list)
    for number, _, cells in rows:
        if test := _label(cells, "test"):
            tests[test].append(number)
        originals[tuple(cells[name]["raw"] for name in columns)].append(number)
    repeated_tests = {label: numbers for label, numbers in sorted(tests.items()) if len(numbers) > 1}
    repeated_rows = [numbers for numbers in originals.values() if len(numbers) > 1]
    repeated_numbers = {number for numbers in repeated_rows for number in numbers}

    records, pairs, exclusions = [], [], []
    reason_counts = Counter()
    dataset_sha256 = dataset["sha256"]
    with localcontext(Context(prec=80)):
        for number, flags, cells in rows:
            test = _label(cells, "test")
            flame_type = _label(cells, "flame_type")
            readings = {name: cells[name] for name in PRESSURES}
            reasons = {name: reason for name, cell in readings.items() if (reason := _pressure_exclusion(cell))}
            if test is None:
                reasons["test"] = "missing_or_unusable_identifier"
            elif test in repeated_tests or "repeated_test" in flags:
                reasons["test"] = "repeated_identifier"
            if flame_type is None or flame_type.casefold() != configuration:
                reasons["flame_type"] = "missing_or_mismatched_configuration"
            if number in repeated_numbers or "repeated_source_record" in flags:
                reasons["source_record"] = "repeated_source_record"

            record = {
                "source_record": number, "dataset_sha256": dataset_sha256, "configuration": configuration,
                "test": test, "day": _label(cells, "day"), "fuel": _label(cells, "fuel"), "quality_flags": flags,
                "readings": readings, "context": {name: cells[name] for name in CONTEXT_HEADERS if name in cells},
                "conditions": {name: cell for name, cell in cells.items() if name not in PRESSURES and name not in CONTEXT_HEADERS},
            }
            if reasons:
                record["reasons"] = reasons
                exclusions.append(record)
                reason_counts.update(f"{name}:{reason}" for name, reason in reasons.items())
            else:
                initial, final = (cell["value"] for cell in readings.values())
                record.update(pinit_atm=initial, pfinal_atm=final, delta_pressure=final - initial)
                pairs.append(record)
            records.append(record)

        return {
            "dataset": {
                **{key: dataset[key] for key in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")},
                "source_filename": Path(dataset["relative_path"]).name, "row_count": row_count, "columns": columns,
                "source_record_index": "1-based CSV data record, excluding the header",
            },
            **_summary(records, dataset_sha256, 1), "pairs": pairs, "exclusions": exclusions,
            "excluded_by_field_reason": dict(sorted(reason_counts.items())), "repeated_tests": repeated_tests,
            "repeated_source_records": repeated_rows,
            "grouped_results": {name: _grouped(records, name, dataset_sha256) for name in ("fuel", "day")},
        }


def _json_ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _result(configurations):
    keys = ("psi_code", "investigation_name", "nasa_psi_url")
    investigation = {key: configurations["normal"]["dataset"][key] for key in keys}
    if any(configurations["inverse"]["dataset"][key] != value for key, value in investigation.items()):
        raise ValueError("Inconsistent NASA investigation metadata between Flame Design datasets")
    return _json_ready({
        "analysis_id": "flame_design_pressure", "method_version": "1.0.0", "decimal_encoding": "string",
        "investigation": investigation, "configurations": configurations,
        "criteria": {
            "pairing": "same dataset version, source_record and identified test", "required_pressure_status": "exact",
            "pressure_range": "positive", "pressure_unit": UNIT, "delta": "pfinal_atm - pinit_atm",
            "repeats": "exclude every repeated test identifier or identical source row within its dataset",
            "quartiles": "inclusive linear interpolation", "group_minimum_valid_pairs": 2,
        },
        "plots": {
            "delta_distribution": {"data": "configurations.*.pairs", "value": "delta_pressure", "unit": UNIT},
            "configuration_summary": {"data": "configurations", "statistics": ["minimum", "q1", "median", "q3", "maximum"],
                                      "count": "valid_pair_count", "unit": UNIT},
            "scatter": {"data": "configurations.*.pairs", "x": "pinit_atm", "y": "pfinal_atm", "unit": UNIT},
            "by_fuel_and_day": {"data": "configurations.*.grouped_results", "groups": ["fuel", "day"],
                                "count": "valid_pair_count", "unit": UNIT},
        },
        "warnings": [
            "Normal and inverse describe flame configurations. A gravity level is not assigned from those labels.",
            "Recorded initial and final pressures support within-test differences. They do not show a time series.",
            "Differences between configurations are descriptive and may reflect differing conditions or coverage.",
            "Fuel groups use recorded Fuel labels. The inverse source has no Fuel column in the audited version.",
            "Day is the source experiment day label. Flow annotations are retained as recorded.",
        ],
    })
