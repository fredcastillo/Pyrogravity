import csv
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from ..ingestion.nasa_csv import CsvTable, inspect_nasa_csv, validate_nasa_csv
from .nasa_tables import INVESTIGATION_TITLES, PROFILES, TableProfile


DATA_DIR = Path(__file__).resolve().parents[2]
TEXT = pa.string()
INTEGER = pa.int64()
MEASUREMENT = pa.decimal128(18, 2)
NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
MOLE_FRACTION = "mole fraction"
PERCENT_BY_VOLUME = "% by vol"
BASS_REPORT = "https://ntrs.nasa.gov/citations/20210011385"
PSI_URL = "https://psi.nasa.gov/physci/repo/data/investigations"
SOURCE_NAME = re.compile(r"(PSI-[0-9]+)_Experimental table_(.+)\.csv", re.IGNORECASE)
FORMULA_ERRORS = {"#DIV/0!", "#VALUE!"}
MISSING_MARKERS = {"-", "\u2013", "\u2014", "n/a"}
QUALITY_FIELDS = {"source_row_empty", "quantitative_candidate"}
HEADER_UNIT = re.compile(
    r"\((mm|cm|cm/s|mg/s|mg/min|mm/s|s|sec|minutes|K|C|atm|bar|percent|sccm|W)\s*\)\s*$"
)
SPICE_TIMES = {"GMT ignition", "GMT  Flame Off "}
TIME_LABEL = re.compile(r"[0-9]{1,2}(?::[0-9]{2}){2}|[0-9]{1,2}(?:\.[0-9]{2}){2}")


@dataclass(frozen=True)
class Column:
    header: str
    name: str
    kind: pa.DataType = TEXT
    unit: str | None = None


@dataclass(frozen=True)
class Dataset:
    name: str
    study: str
    source: Path
    encoding: str
    expected_rows: int
    missing_marker: str
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Source:
    path: Path
    study: str
    output_name: str
    profile: TableProfile


FLEX = Dataset(
    name="flex",
    study="PSI-69",
    source=Path("raw/PSI-69_Experimental table_FLEX.csv"),
    encoding="cp1252",
    expected_rows=274,
    missing_marker="\u2013",
    columns=(
        Column("FLEX Test #", "flex_test_number"),
        Column("FLEX Identifier", "flex_identifier"),
        Column("Test Date", "test_date"),
        Column("Test GMT", "test_gmt"),
        Column("Fuel", "fuel"),
        Column("Ambient pressure; mmHg", "ambient_pressure", MEASUREMENT, "mmHg"),
        Column("O initial ambient composition; mole fraction", "o_initial_ambient_composition", MEASUREMENT, MOLE_FRACTION),
        Column("N initial ambient composition; mole fraction", "n_initial_ambient_composition", MEASUREMENT, MOLE_FRACTION),
        Column("CO initial ambient composition; mole fraction", "co_initial_ambient_composition", MEASUREMENT, MOLE_FRACTION),
        Column("He initial ambient composition; mole fraction", "he_initial_ambient_composition", MEASUREMENT, MOLE_FRACTION),
        Column("Droplet initial diameter; mm", "droplet_initial_diameter", MEASUREMENT, "mm"),
        Column("Visible flame extinction diameter; mm", "visible_flame_extinction_diameter", MEASUREMENT, "mm"),
        Column("Burning rate; mm", "burning_rate", MEASUREMENT, "mm"),
        Column("Burn time; s", "burn_time", MEASUREMENT, "s"),
        Column("Test end", "test_end"),
    ),
)

BASS_II = Dataset(
    name="bass_ii",
    study="PSI-25",
    source=Path("raw/PSI-25_Experimental table_BASS-II.csv"),
    encoding="utf-8-sig",
    expected_rows=129,
    missing_marker="none",
    columns=(
        Column("PI", "pi"),
        Column("Test #", "test_number"),
        Column("Date", "date"),
        Column("GMT", "gmt", INTEGER),
        Column("Sample #", "sample_number"),
        Column("Fuel Sample Material", "fuel_sample_material"),
        Column("Flow restrictor", "flow_restrictor", INTEGER),
        Column("Fan display", "fan_display", MEASUREMENT),
        Column("Air display", "air_display", MEASUREMENT),
        Column("Radiometer gain   (1000   250   50   10)", "radiometer_gain", INTEGER),
        Column("Total Frames Shot", "total_frames_shot", INTEGER),
        Column("Calibrated  initial O2 % by vol ", "calibrated_initial_o2", MEASUREMENT, PERCENT_BY_VOLUME),
        Column("Calibrated final O2 % by vol", "calibrated_final_o2", MEASUREMENT, PERCENT_BY_VOLUME),
        Column("Initial CO2 % by vol", "initial_co2", MEASUREMENT, PERCENT_BY_VOLUME),
        Column("Final CO2 % by vol", "final_co2", MEASUREMENT, PERCENT_BY_VOLUME),
        Column("Initial CO (ppm)", "initial_co", MEASUREMENT, "ppm"),
        Column("Final CO (ppm)", "final_co", MEASUREMENT, "ppm"),
    ),
)


def discover_sources(data_dir: Path = DATA_DIR) -> list[Source]:
    sources = []
    found_profiles = set()
    output_names = set()
    for path in (data_dir / "raw").iterdir():
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        match = SOURCE_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Unexpected NASA CSV filename: {path.name}")
        study, title = match.groups()
        key = (study.upper(), title)
        if key not in PROFILES:
            raise ValueError(f"No audited table profile for {path.name}")
        output_name = f"{study.lower()}_{snake_case(title)}"
        if key in found_profiles or output_name in output_names:
            raise ValueError(f"Conflicting CSV output name: {path.name}")
        found_profiles.add(key)
        output_names.add(output_name)
        sources.append(Source(path.relative_to(data_dir), key[0], output_name, PROFILES[key]))

    missing = PROFILES.keys() - found_profiles
    if missing:
        raise ValueError(f"Missing NASA CSV tables: {sorted(missing)}")
    return sorted(sources, key=lambda source: (int(source.study[4:]), source.path.name))


def snake_case(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def parse_cell(
    raw: str, kind: pa.DataType, missing_markers: str | set[str], unit: str | None = None
) -> tuple[str | Decimal | int | None, str]:
    value = raw.strip()
    if not value:
        return None, "blank"
    markers = {missing_markers} if isinstance(missing_markers, str) else missing_markers
    if value.casefold() in markers or (
        "n/a" in markers and re.fullmatch(r"n/a\s*\(.+\)", value, re.I)
    ):
        return None, "missing_marker"
    if value in FORMULA_ERRORS:
        return None, "source_error"
    if kind == TEXT:
        return raw, "text"
    if unit and value.endswith(unit):
        value = value.removesuffix(unit).rstrip()
    if re.match(rf"~\s*{NUMBER}", value):
        return None, "approximate"
    if re.fullmatch(rf"[<>]=?\s*{NUMBER}", value):
        return None, "bound"
    if re.fullmatch(rf"{NUMBER}%?\s*(?:-|\u2013|to)\s*{NUMBER}%?", value):
        return None, "range"
    if re.fullmatch(rf"{NUMBER}(?:(?:\s+|\s*[>,;]\s*|\s+(?:or|and)\s+){NUMBER})+", value):
        return None, "multiple_values"
    if re.fullmatch(NUMBER, value):
        number = Decimal(value)
        if kind == MEASUREMENT:
            return number, "exact"
        if number == number.to_integral_value():
            return int(number), "exact"
    return None, "annotation"


def flex_anomalies(values, identifiers):
    flags = []
    identifier = values["flex_identifier"]
    if identifier is not None and identifiers[identifier] > 1:
        flags.append("repeated_flex_identifier")
    pressure = values["ambient_pressure"]
    if pressure is not None and pressure <= 0:
        flags.append("nonpositive_ambient_pressure")
    return flags


def bass_anomalies(values, ambiguous_fan: bool):
    flags = []
    # NASA/TM-20210011385, Appendix A, records GMT as the ordinal day.
    if values["date"] is not None and values["gmt"] is not None:
        try:
            date = datetime.strptime(values["date"].strip(), "%m/%d/%Y")
        except ValueError:
            flags.append("invalid_date")
        else:
            if values["gmt"] != date.timetuple().tm_yday:
                flags.append("gmt_date_mismatch")
    if ambiguous_fan:
        flags.append("fan_display_combined_values")

    # NASA/TM-20210011385, section 1.2, gives the sensor ranges and O2 resolution.
    for name in ("initial_co", "final_co", "initial_co2", "final_co2"):
        upper_limit = 1000 if name.endswith("_co") else 5
        if values[name] is not None and not 0 <= values[name] <= upper_limit:
            flags.append(f"{name}_outside_sensor_range")
    initial_o2 = values["calibrated_initial_o2"]
    final_o2 = values["calibrated_final_o2"]
    if (
        initial_o2 is not None
        and final_o2 is not None
        and final_o2 - initial_o2 > Decimal("0.1")
    ):
        flags.append("o2_increase_exceeds_sensor_resolution")
    return flags


def transform(dataset: Dataset, data_dir: Path, source: CsvTable | None = None) -> pa.Table:
    path = data_dir / dataset.source
    if source is None:
        source = inspect_nasa_csv(path, dataset.encoding)
    validate_nasa_csv(path, source, tuple(column.header for column in dataset.columns), dataset.expected_rows)
    names = [column.name for column in dataset.columns]
    raw_rows = [dict(zip(names, row)) for row in source.rows]
    identifiers = Counter(row["flex_identifier"] for row in raw_rows) if dataset == FLEX else None
    records = []
    for record_number, raw_row in enumerate(raw_rows, start=1):
        record = {"source_record": record_number, "source_study": dataset.study}
        values = {}
        # Appendix A, test T15, lists 80 and 122 separately. Keep the CSV cell intact.
        ambiguous_fan = (
            dataset == BASS_II
            and raw_row["test_number"] == "T15"
            and raw_row["fan_display"] == "80122"
        )
        for column in dataset.columns:
            raw = raw_row[column.name]
            value, status = parse_cell(raw, column.kind, dataset.missing_marker)
            if column.name == "fan_display" and ambiguous_fan:
                value, status = None, "ambiguous"
            values[column.name] = value
            record[column.name] = raw if column.kind == TEXT else value
            if column.kind != TEXT:
                record[f"{column.name}_raw"] = raw
            record[f"{column.name}_status"] = status

        if is_empty_row(raw_row.values()):
            record["anomalies"] = ["empty_record"]
        elif dataset == FLEX:
            record["anomalies"] = flex_anomalies(values, identifiers)
        else:
            record["anomalies"] = bass_anomalies(values, ambiguous_fan)
        records.append(record)

    return make_table(dataset.columns, records, source, dataset.study, dataset.source)


def make_table(
    columns: tuple[Column, ...], records: list[dict], source: CsvTable, study: str,
    path: Path, *, infer_precision: bool = False,
) -> pa.Table:
    fields = [pa.field("source_record", INTEGER), pa.field("source_study", TEXT)]
    for column in columns:
        metadata = {"source_header": column.header}
        if column.unit is not None:
            metadata["source_unit"] = column.unit
        kind = column.kind
        if infer_precision and kind == MEASUREMENT:
            numbers = [record[column.name] for record in records if record[column.name] is not None]
            scale = max((max(0, -number.as_tuple().exponent) for number in numbers), default=0)
            whole_digits = max((max(0, number.adjusted() + 1) for number in numbers if number), default=0)
            precision = max(1, whole_digits + scale)
            kind = pa.decimal128(precision, scale) if precision <= 38 else pa.decimal256(precision, scale)
        fields.append(pa.field(column.name, kind, metadata=metadata))
        if column.kind != TEXT:
            fields.append(pa.field(f"{column.name}_raw", TEXT))
        fields.append(pa.field(f"{column.name}_status", TEXT))
    fields.append(pa.field("anomalies", pa.list_(pa.field("element", TEXT))))
    metadata = {
        "source_path": path.as_posix(),
        "source_encoding": source.encoding,
        "source_delimiter": source.delimiter,
        "source_sha256": source.sha256,
        "source_investigation": f"{PSI_URL}/{study}",
        "source_record_index": "1-based data record, excluding the header",
    }
    if study == BASS_II.study:
        metadata["quality_reference"] = BASS_REPORT
    return pa.Table.from_pylist(records, schema=pa.schema(fields, metadata=metadata))


def profile_columns(source: CsvTable, profile: TableProfile) -> tuple[Column, ...]:
    columns = []
    names = {"source_record", "source_study", "anomalies"} | QUALITY_FIELDS
    for position, header in enumerate(source.header, start=1):
        name = snake_case(header) or f"column_{position}"
        if name in names or f"{name}_raw" in names or f"{name}_status" in names:
            raise ValueError(f"Column name collision at source column {position}: {header!r}")
        names.update((name, f"{name}_raw", f"{name}_status"))

        kind = TEXT
        if header in profile.quantities:
            kind = MEASUREMENT
        elif header in profile.counts:
            kind = INTEGER
        unit = profile.units.get(header)
        if unit is None and kind == MEASUREMENT:
            declared = HEADER_UNIT.search(header)
            if declared:
                unit = declared[1]
        columns.append(Column(header, name, kind, unit))

    profiled_headers = set(profile.quantities + profile.counts + profile.identifiers)
    profiled_headers.update(profile.units)
    if profile.required_identifier:
        profiled_headers.add(profile.required_identifier)
    if missing := profiled_headers.difference(source.header):
        raise ValueError(f"Missing audited CSV headers: {sorted(missing)}")
    return tuple(columns)


def profile_anomalies(study: str, raw: dict[str, str]) -> dict[str, tuple[str, str]]:
    if study == "PSI-20" and raw["Oxygen Conc (percent)"].strip() in {"2100%", "3400%"}:
        return {"Oxygen Conc (percent)": ("ambiguous", "oxygen_percent_exceeds_100")}
    if study == "PSI-21":
        fuel = raw["Fuel Bottle"].strip()
        if fuel and not fuel.endswith((" CH4", " C2H4")):
            return {"Fuel Bottle": ("ambiguous", "fuel_label_differs_from_expected_fuels")}
    if study == "PSI-23" and re.search(r"\bN[3-6]\b", raw["Atmosphere*"]):
        return {"Atmosphere*": ("ambiguous", "ambiguous_atmosphere_label")}
    if study == "PSI-99":
        ambiguous = {}
        if raw["Samle Thickness "].strip() == "037 mm":
            ambiguous["Samle Thickness "] = ("ambiguous", "ambiguous_sample_thickness")
        if raw["?-g Spread Length"].strip().endswith("mm/s"):
            ambiguous["?-g Spread Length"] = ("ambiguous", "spread_length_contains_rate")
        return ambiguous
    if study == "PSI-107" and raw["GMT ignition"].strip() in {"1744", "1746"}:
        return {"GMT ignition": ("ambiguous", "compact_ignition_time")}
    return {}


def transform_profile(dataset: Source, source: CsvTable) -> pa.Table:
    profile = dataset.profile
    columns = profile_columns(source, profile)
    positions = {column.header: index for index, column in enumerate(columns)}
    counts = {
        header: Counter(row[positions[header]].strip() for row in source.rows)
        for header in profile.identifiers
    }
    row_counts = Counter(map(tuple, source.rows))
    records = []
    for number, cells in enumerate(source.rows, start=1):
        raw = dict(zip(source.header, cells))
        record = {"source_record": number, "source_study": dataset.study}
        flags = []
        if is_empty_row(cells):
            flags.append("empty_record")
        else:
            if profile.required_identifier and not raw[profile.required_identifier].strip():
                flags.append("missing_primary_identifier")
            if row_counts[tuple(cells)] > 1:
                flags.append("repeated_source_record")
        for header, occurrences in counts.items():
            key = raw[header].strip()
            if key and occurrences[key] > 1:
                flags.append(f"repeated_{columns[positions[header]].name}")
        special_cells = profile_anomalies(dataset.study, raw)
        for column in columns:
            cell = raw[column.header]
            value, status = parse_cell(cell, column.kind, MISSING_MARKERS, column.unit)
            if column.header in special_cells:
                status, flag = special_cells[column.header]
                value = None
                flags.append(flag)
            elif status == "source_error":
                flags.append(f"source_error_{column.name}")
            elif status == "exact" and (
                column.header.startswith("approx ") or column.header == "Oxygen Conc (percent)"
            ):
                value, status = None, "approximate"
            elif column.header == "Atmosphere*" and cell.lstrip().startswith("~"):
                status = "approximate"
            elif (
                dataset.study == "PSI-107" and column.header in SPICE_TIMES
                and status == "text" and not TIME_LABEL.fullmatch(cell.strip())
            ):
                status = "annotation"
            record[column.name] = cell if column.kind == TEXT else value
            if column.kind != TEXT:
                record[f"{column.name}_raw"] = cell
            record[f"{column.name}_status"] = status
        record["anomalies"] = flags
        records.append(record)
    return make_table(columns, records, source, dataset.study, dataset.path, infer_precision=True)


def is_empty_row(cells: Iterable[str]) -> bool:
    return not any(cell.strip() for cell in cells)


def classify_rows(table: pa.Table, source: CsvTable, profile: TableProfile) -> pa.Table:
    empty = [is_empty_row(row) for row in source.rows]
    candidates = [False] * table.num_rows
    rule = {
        "required_context_headers": profile.quantitative_context,
        "required_exact_value_headers": profile.quantitative_values,
        "blocking_anomaly_flags": profile.quantitative_blockers,
    }
    if profile.quantitative_values:
        names_by_header = {
            field.metadata[b"source_header"].decode(): field.name
            for field in table.schema
            if field.metadata and b"source_header" in field.metadata
        }
        context = [names_by_header[header] for header in profile.quantitative_context]
        quantities = [names_by_header[header] for header in profile.quantitative_values]
        status_columns = [f"{name}_status" for name in context + quantities]
        blockers = set(profile.quantitative_blockers)
        # Each candidate supplies one documented set of context and exact values.
        rows = table.select([*status_columns, "anomalies"]).to_pylist()
        candidates = [
            not row_empty
            and all(row[f"{name}_status"] == "text" for name in context)
            and all(row[f"{name}_status"] == "exact" for name in quantities)
            and blockers.isdisjoint(row["anomalies"])
            for row_empty, row in zip(empty, rows, strict=True)
        ]
    table = table.append_column("source_row_empty", pa.array(empty, type=pa.bool_()))
    table = table.append_column("quantitative_candidate", pa.array(candidates, type=pa.bool_()))
    return table.replace_schema_metadata({
        **table.schema.metadata,
        b"quantitative_candidate_criteria": json.dumps(rule).encode(),
    })


def write_manifest(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_etl(
    data_dir: Path = DATA_DIR, output_dir: Path | None = None, *, manifest_path: Path | None = None,
) -> dict[str, pa.Table]:
    if output_dir is None:
        output_dir = data_dir / "processed"
        if manifest_path is None:
            manifest_path = data_dir / "source_manifest.csv"
    tables = {}
    manifest = []
    legacy = {dataset.source: dataset for dataset in (FLEX, BASS_II)}
    for dataset in discover_sources(data_dir):
        csv_table = inspect_nasa_csv(data_dir / dataset.path)
        adapter = legacy.get(dataset.path)
        if adapter:
            table = transform(adapter, data_dir, csv_table)
        else:
            table = transform_profile(dataset, csv_table)
        table = classify_rows(table, csv_table, dataset.profile)
        metadata = {
            **table.schema.metadata,
            b"source_scope": dataset.profile.scope.encode(),
            b"source_observations": dataset.profile.observations.encode(),
        }
        tables[dataset.output_name] = table.replace_schema_metadata(metadata)
        flagged_rows = sum(bool(flags) for flags in table["anomalies"].to_pylist())
        empty_rows = sum(table["source_row_empty"].to_pylist())
        candidate_rows = sum(table["quantitative_candidate"].to_pylist())
        if not dataset.profile.quantitative_values:
            quantitative_status = "limited_to_source_scope"
        elif candidate_rows:
            quantitative_status = "has_candidates"
        else:
            quantitative_status = "insufficient_values"
        observations = dataset.profile.observations
        if flagged_rows:
            observations += f" {flagged_rows} source records have review flags."
        manifest.append({
            "psi_code": dataset.study,
            "investigation_name": INVESTIGATION_TITLES[dataset.study],
            "source_filename": dataset.path.name,
            "relative_path": dataset.path.as_posix(),
            "row_count": len(csv_table.rows),
            "column_count": len(csv_table.header),
            "encoding": csv_table.encoding,
            "delimiter": csv_table.delimiter,
            "sha256": csv_table.sha256,
            "nasa_psi_url": f"{PSI_URL}/{dataset.study}",
            "validation_status": "validated_with_flags" if flagged_rows else "validated",
            "data_scope": dataset.profile.scope,
            "observations": observations,
            "parquet_filename": f"{dataset.output_name}.parquet",
            "empty_row_count": empty_rows,
            "informative_row_count": table.num_rows - empty_rows,
            "flagged_row_count": flagged_rows,
            "quantitative_candidate_row_count": candidate_rows,
            "quantitative_status": quantitative_status,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir) as temporary_dir:
        staging = Path(temporary_dir)
        for name, table in tables.items():
            pq.write_table(table, staging / f"{name}.parquet")
        if manifest_path is not None:
            write_manifest(staging / "source_manifest.csv", manifest)
        for name in tables:
            filename = f"{name}.parquet"
            (staging / filename).replace(output_dir / filename)
        if manifest_path is not None:
            (staging / "source_manifest.csv").replace(manifest_path)
    return tables


def main() -> None:
    for name, table in run_etl().items():
        statuses = Counter(
            value
            for column in table.column_names
            if column.endswith("_status")
            for value in table[column].to_pylist()
            if value not in {"exact", "text"}
        )
        anomalies = Counter(flag for flags in table["anomalies"].to_pylist() for flag in flags)
        empty_rows = sum(table["source_row_empty"].to_pylist())
        candidate_rows = sum(table["quantitative_candidate"].to_pylist())
        print(f"{name}: {table.num_rows} records, {empty_rows} empty, "
              f"{table.num_rows - empty_rows} informative, {candidate_rows} quantitative candidates")
        print(f"  Missing and special cells: {dict(sorted(statuses.items()))}")
        print(f"  Anomaly flags: {dict(sorted(anomalies.items()))}")


if __name__ == "__main__":
    main()
