"""Read-only summaries of recorded burn duration in NASA PSI-159 CFI-G."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Context, Decimal, localcontext
from pathlib import Path
from statistics import quantiles

import pyarrow.parquet as pq
from psycopg import Connection
from psycopg.rows import dict_row

from ..database.nasa_loader import field_kind, read_manifest
from ..etl.nasa_etl import DATA_DIR, is_empty_row, snake_case


STUDY = "PSI-159"
TITLES = {"normal": "CFI-G_Normal Flames", "inverse": "CFI-G_Inverse Flames"}
PATHS = {name: f"raw/{STUDY}_Experimental table_{title}.csv" for name, title in TITLES.items()}
DURATION = "burn_time_sec"
END = "self_ext_or_flow_term"
PRESSURE = "approx_p_bar"
UNIT = "sec"
TERMINATIONS = {"SE": "self-extinction", "FT": "flow termination"}
TERMINATION_SOURCE = "https://doi.org/10.1016/j.proci.2022.07.015"
KELVIN_OFFSET = Decimal("273.15")
CONDITION_FIELDS = {
    "normal": ("xf", "xo2_before_test", "mhc_mg_s"),
    "inverse": ("xf_before_test", "xo2", "hc_burnrate_mg_s", "o2_flow_rate_mg_s"),
}
CONTEXT_HEADERS = {"flame_type": "Flame Type", "day": "Day", "test": "Test", "fuel": "Fuel",
                   "hot_ignition": "Hot ignition", "comments": "Comments"}
TEMPERATURE_COLUMNS = {
    "normal": {"peak_burner_t_c": ("Peak burner T (C )", "C")},
    "inverse": {"peak_burner_temp_c": ("Peak burner Temp (C)", "C"),
                "peak_burner_temp_k": ("Peak burner temp (K)", "K")},
}

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
    SELECT source_record, original_values, text_cell_statuses, source_row_empty, quality_flags
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
            raise ValueError(f"Invalid CFI-G column order or name: {configuration}")
        columns[name] = {"ordinal": ordinal, "source_header": header, "unit": unit, "type": kind}
    if len(columns) != count:
        raise ValueError(f"CFI-G column count differs from provenance: {configuration}")
    end_header = "Self-ext or flow term" if configuration == "normal" else "Self -ext or flow term"
    expected = {name: (header, None, "text") for name, header in {**CONTEXT_HEADERS, END: end_header}.items()}
    expected.update({name: (header, unit, "decimal") for name, (header, unit) in {
        DURATION: ("burn time (sec)", UNIT), PRESSURE: ("approx p (bar)", "bar"),
        **TEMPERATURE_COLUMNS[configuration],
    }.items()})
    for name, metadata in expected.items():
        column = columns.get(name, {})
        if (column.get("source_header"), column.get("unit"), column.get("type")) != metadata:
            raise ValueError(f"Invalid CFI-G column metadata: {configuration}, {name}")
    if any(columns.get(name, {}).get("type") != "decimal" for name in CONDITION_FIELDS[configuration]):
        raise ValueError(f"Missing or invalid CFI-G condition columns: {configuration}")
    return columns


def analyze_parquet(data_dir: Path = DATA_DIR) -> dict:
    """Analyze the normal and inverse CFI-G versions in the local manifest."""
    manifest = read_manifest(data_dir / "source_manifest.csv")
    configurations = {}
    for configuration, path in PATHS.items():
        entry = manifest.get(path)
        parquet_name = f"{STUDY.lower()}_{snake_case(TITLES[configuration])}.parquet"
        if entry is None or (entry["psi_code"], entry["source_filename"], entry["parquet_filename"]) != (
            STUDY, Path(path).name, parquet_name,
        ):
            raise ValueError(f"No matching CFI-G version in the manifest: {configuration}")
        with pq.ParquetFile(data_dir / "processed" / parquet_name) as parquet:
            schema = parquet.schema_arrow
            metadata = schema.metadata or {}
            for key, value in {b"source_path": path, b"source_sha256": entry["sha256"],
                               b"source_investigation": entry["nasa_psi_url"]}.items():
                if metadata.get(key) != value.encode():
                    raise ValueError(f"CFI-G Parquet provenance differs: {configuration}, {key.decode()}")
            fields = [field for field in schema if b"source_header" in (field.metadata or {})]
            columns = _columns(
                ((ordinal, field.name, field.metadata[b"source_header"].decode(),
                  field.metadata[b"source_unit"].decode() if b"source_unit" in field.metadata else None,
                  field_kind(field.type)) for ordinal, field in enumerate(fields, start=1)),
                configuration, int(entry["column_count"]),
            )
            selected = ["source_record", "source_study", "source_row_empty", "anomalies"]
            for name, column in columns.items():
                selected.extend((name, f"{name}_status"))
                if column["type"] != "text":
                    selected.append(f"{name}_raw")
            if not set(selected).issubset(schema.names):
                raise ValueError(f"Missing CFI-G Parquet fields: {configuration}")
            records = parquet.read(columns=selected).to_pylist()
        rows = []
        for record in records:
            if record["source_study"] != STUDY:
                raise ValueError(f"Unexpected study in CFI-G Parquet: {configuration}")
            cells = {name: {"raw": record.get(f"{name}_raw", record[name]), "status": record[f"{name}_status"],
                            "value": record[name]} for name in columns}
            rows.append((record["source_record"], record["source_row_empty"], record["anomalies"], cells))
        configurations[configuration] = _analyze_dataset(configuration, entry, columns, rows)
    return _result(configurations)


def analyze_postgres(connection: Connection, sha256_by_configuration: Mapping[str, str]) -> dict:
    """Read explicit normal and inverse versions on a caller-managed connection."""
    if sha256_by_configuration.keys() != PATHS.keys():
        raise ValueError("Provide a SHA-256 for each CFI-G configuration: normal and inverse")
    configurations = {}
    with connection.cursor(row_factory=dict_row) as cursor:
        for configuration, path in PATHS.items():
            cursor.execute(SELECT_COLUMNS, (STUDY, path, sha256_by_configuration[configuration]))
            catalog = cursor.fetchall()
            if not catalog:
                raise ValueError(f"CFI-G dataset version is missing or not visible: {configuration}")
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
                rows.append((number, record["source_row_empty"], record["quality_flags"], cells))
            configurations[configuration] = _analyze_dataset(configuration, dataset, columns, rows)
    return _result(configurations)


def _label(cell):
    return (cell["raw"].strip() or None) if cell["status"] == "text" else None


def _exact_value(cell):
    value = cell["value"]
    return value if cell["status"] == "exact" and isinstance(value, Decimal) and value.is_finite() else None


def _duration_exclusion(cell):
    if cell["status"] != "exact":
        return cell["status"] or "missing_measurement"
    value = _exact_value(cell)
    if value is None:
        return "invalid_numeric_value"
    if value < 0:
        return "negative_duration"
    if value == 0:
        return "zero_duration"
    return None


def _statistics(values):
    if not values:
        return None
    q1, median, q3 = quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
    return {"minimum": min(values), "q1": q1, "median": median, "q3": q3, "maximum": max(values),
            "mean": (sum(values) / len(values)).quantize(Decimal("0.001"))}


def _groups(records, name):
    groups = defaultdict(list)
    for record in records:
        if record[name] is not None:
            groups[record[name]].append(record)
    return dict(sorted(groups.items()))


def _summary(records):
    valid = [row for row in records if "duration" in row]
    categories = {row["termination"] for row in valid}
    return {"trial_count": len(records), "valid_count": len(valid),
            "excluded_count": len(records) - len(valid), "unit": UNIT,
            "source_records": [row["source_record"] for row in records],
            "statistics": _statistics([row["duration"] for row in valid]) if len(categories) == 1 else None}


def _flag_outliers(records, grouped):
    for category, group in _groups(records, "termination").items():
        stats = grouped[category]["statistics"]
        if grouped[category]["valid_count"] < 4:
            continue
        span = Decimal("1.5") * (stats["q3"] - stats["q1"])
        lower, upper = stats["q1"] - span, stats["q3"] + span
        for row in group:
            row["duration_outlier"] = not lower <= row["duration"] <= upper


def _temperature_check(records, configuration):
    if configuration == "normal":
        return {"paired_peak_temperature_columns": False}
    matches, mismatches = [], []
    for row in records:
        values = row["conditions"]
        celsius = _exact_value(values["peak_burner_temp_c"])
        kelvin = _exact_value(values["peak_burner_temp_k"])
        if celsius is None or kelvin is None:
            continue
        difference = kelvin - celsius
        if difference == KELVIN_OFFSET:
            matches.append(row["source_record"])
        else:
            mismatches.append({"source_record": row["source_record"], "kelvin_minus_celsius": difference})
    return {"paired_peak_temperature_columns": True, "expected_kelvin_offset": KELVIN_OFFSET,
            "exact_pair_count": len(matches) + len(mismatches), "matching_pair_count": len(matches),
            "matching_source_records": matches, "mismatches": mismatches}


def _condition_comparison(records, configuration):
    fields = CONDITION_FIELDS[configuration]
    groups = defaultdict(list)
    for row in records:
        values = row["conditions"]
        pressure = values[PRESSURE]["raw"].strip()
        exact = tuple(_exact_value(values[name]) for name in fields)
        if row["fuel"] is not None and pressure and values[PRESSURE]["status"] == "approximate" and None not in exact:
            groups[(row["fuel"], pressure, *exact)].append(row)
    return {
        "match_fields": ["fuel", PRESSURE, *fields], "nominal_pressure_unit": "bar",
        "eligible_count": sum(map(len, groups.values())), "distinct_condition_count": len(groups),
        "matched_groups": [
            {"fuel": fuel, "approximate_pressure_raw": pressure, "exact_inputs": dict(zip(fields, values, strict=True)),
             "by_termination": {name: _summary(group) for name, group in _groups(rows, "termination").items()}}
            for (fuel, pressure, *values), rows in sorted(groups.items()) if len(rows) > 1
        ],
    }


def _analyze_dataset(configuration, dataset, columns, rows):
    count = int(dataset["row_count"])
    if [row[0] for row in rows] != list(range(1, count + 1)):
        raise ValueError(f"CFI-G records are incomplete or out of order: {configuration}")
    tests, identical = defaultdict(list), defaultdict(list)
    for number, empty, _, cells in rows:
        raw = tuple(cells[name]["raw"] for name in columns)
        if empty != is_empty_row(raw):
            raise ValueError(f"CFI-G empty marker differs from original cells: {configuration}, {number}")
        if not empty:
            if test := _label(cells["test"]):
                tests[test].append(number)
            identical[raw].append(number)
    repeated_tests = {label: numbers for label, numbers in sorted(tests.items()) if len(numbers) > 1}
    repeated_rows = [numbers for numbers in identical.values() if len(numbers) > 1]
    duplicate_numbers = {number for numbers in repeated_rows for number in numbers}

    empty_records, records, included, exclusions, errors = [], [], [], [], []
    reasons_total = Counter()
    for number, empty, flags, cells in rows:
        reference = {"source_record": number, "dataset_sha256": dataset["sha256"]}
        if empty:
            empty_records.append({**reference, "reasons": {"source_record": "empty_record"}})
            continue
        test = _label(cells["test"])
        flame = _label(cells["flame_type"])
        ignition = _label(cells["hot_ignition"])
        end = cells[END]["raw"].strip() or None
        notes = cells["comments"]["raw"].casefold()
        review = end == "SE" and any(text in notes for text in ("manually stopped", "burner t limit", "flow cut"))
        record = {
            **reference, "configuration": configuration, "test": test, "fuel": _label(cells["fuel"]),
            "day": _label(cells["day"]), "termination": end, "quality_flags": flags,
            "termination_review": "se_note_mentions_intervention_or_limit" if review else None,
            "context": {name: cells[name] for name in (*CONTEXT_HEADERS, END)}, "duration_reading": cells[DURATION],
            "conditions": {name: cell for name, cell in cells.items() if name not in (*CONTEXT_HEADERS, END, DURATION)},
        }
        errors.extend({**reference, "column": name, "raw": cell["raw"]}
                      for name, cell in cells.items() if cell["status"] == "source_error")
        reasons = {}
        if reason := _duration_exclusion(cells[DURATION]):
            reasons[DURATION] = reason
        if ignition is None or ignition.casefold() != "yes":
            reasons["hot_ignition"] = "not_affirmative"
        if cells[END]["status"] != "text":
            reasons[END] = cells[END]["status"] or "missing_termination"
        elif end not in TERMINATIONS:
            reasons[END] = "unknown_termination"
        if not test:
            reasons["test"] = "missing_or_unusable_identifier"
        elif test in repeated_tests:
            reasons["test"] = "repeated_identifier"
        if flame is None or flame.casefold() != configuration:
            reasons["flame_type"] = "missing_or_mismatched_configuration"
        if number in duplicate_numbers:
            reasons["source_record"] = "repeated_source_record"
        if reasons:
            record["reasons"] = reasons
            exclusions.append(record)
            reasons_total.update(f"{name}:{reason}" for name, reason in reasons.items())
        else:
            record.update(duration=cells[DURATION]["value"], duration_outlier=False)
            included.append(record)
        records.append(record)

    with localcontext(Context(prec=80)):
        termination = {name: _summary(group) for name, group in _groups(records, "termination").items()}
        _flag_outliers(included, termination)
        return {
            "dataset": {
                **{name: dataset[name] for name in ("psi_code", "investigation_name", "nasa_psi_url", "relative_path", "sha256")},
                "dataset_id": dataset.get("dataset_id"), "source_filename": Path(dataset["relative_path"]).name,
                "row_count": count, "columns": columns, "source_record_index": "1-based CSV data record, excluding the header",
            },
            **_summary(records), "included": included, "exclusions": exclusions, "empty_records": empty_records,
            "excluded_by_field_reason": dict(sorted(reasons_total.items())),
            "quality": {
                "empty_row_count": len(empty_records), "source_error_count": len(errors), "source_errors": errors,
                "duration_status_counts": dict(sorted(Counter(r["duration_reading"]["status"] or "missing_measurement"
                                                             for r in records).items())),
                "repeated_tests": repeated_tests, "repeated_source_records": repeated_rows,
                "duration_outlier_records": [r["source_record"] for r in included if r["duration_outlier"]],
                "termination_review_records": [r["source_record"] for r in records if r["termination_review"]],
                "peak_temperature_check": _temperature_check(records, configuration),
            },
            "grouped_results": {
                "termination": termination,
                "fuel": {fuel: {**_summary(group), "by_termination": {
                    name: _summary(rows) for name, rows in _groups(group, "termination").items()}}
                    for fuel, group in _groups(records, "fuel").items()},
            },
            "condition_comparison": _condition_comparison(included, configuration),
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
        raise ValueError("Inconsistent NASA investigation metadata between CFI-G datasets")
    return _json_ready({
        "analysis_id": "cfi_g_duration", "method_version": "1.0.0", "decimal_encoding": "string",
        "investigation": investigation, "configurations": configurations,
        "criteria": {
            "duration_unit": UNIT, "duration_status": "exact", "duration_range": "positive",
            "hot_ignition": "yes after trimming and case folding", "termination_codes": list(TERMINATIONS),
            "repeats": "exclude all repeated test labels or identical informative rows within each dataset",
            "quartiles": "inclusive linear interpolation", "mean": "rounded to 0.001 sec",
            "outliers": "flag outside 1.5 times IQR from Q1 or Q3 by configuration and termination, with at least four values",
            "row_identity": "dataset SHA-256 and source_record. Dataset metadata carries dataset_id only in PostgreSQL.",
        },
        "termination_interpretation": {
            "labels": TERMINATIONS, "verification": "Interpreted from CSV headers and study terminology. No verified row-level codebook.",
            "reference_url": TERMINATION_SOURCE,
            "censoring": "FT could be right censored for natural extinction if the flame was still burning at cutoff and timing were validated. No censoring is assigned here.",
        },
        "plots": {
            "duration_distribution": {"data": "configurations.*.included", "value": "duration", "unit": UNIT,
                                      "group": "termination", "facet": "configuration"},
            "by_fuel": {"data": "configurations.*.grouped_results.fuel", "unit": UNIT},
            "coverage": {"data": "configurations", "counts": ["trial_count", "valid_count", "excluded_count", "quality.empty_row_count"]},
            "compatible_conditions": {"data": "configurations.*.condition_comparison.matched_groups", "unit": UNIT},
        },
        "warnings": [
            "SE and FT are original codes. A recorded duration is not a verified natural extinction time.",
            "Some SE comments mention intervention or a burner temperature limit; the original code is retained.",
            "Fuel labels and approximate pressure are kept as recorded. Matched recorded settings cannot establish experimental control.",
            "Normal and inverse have different coverage. Comparisons are descriptive.",
            "Peak burner temperatures and Tad refer to different quantities. The C to K offset check never replaces raw values.",
        ],
    })
