import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from ..ingestion.nasa_csv import read_nasa_csv


DATA_DIR = Path(__file__).resolve().parents[2]
TEXT = pa.string()
INTEGER = pa.int64()
MEASUREMENT = pa.decimal128(18, 2)
NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
MOLE_FRACTION = "mole fraction"
PERCENT_BY_VOLUME = "% by vol"
BASS_REPORT = "https://ntrs.nasa.gov/citations/20210011385"


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


FLEX = Dataset(
    name="flex",
    study="PSI-69",
    source=Path("raw/flex/PSI-69_Experimental table_FLEX.csv"),
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
    source=Path("raw/bass_ii/PSI-25_Experimental table_BASS-II.csv"),
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


def parse_cell(
    raw: str, kind: pa.DataType, missing_marker: str
) -> tuple[str | Decimal | int | None, str]:
    value = raw.strip()
    if not value:
        return None, "blank"
    if value.casefold() == missing_marker:
        return None, "missing_marker"
    if kind == TEXT:
        return raw, "text"
    if re.fullmatch(rf"~\s*{NUMBER}", value):
        return None, "approximate"
    if re.fullmatch(rf"[<>]=?\s*{NUMBER}", value):
        return None, "bound"
    if re.fullmatch(rf"{NUMBER}(?:(?:\s+|\s*[>,;]\s*){NUMBER})+", value):
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


def transform(dataset: Dataset, data_dir: Path) -> pa.Table:
    rows, source_hash = read_nasa_csv(
        data_dir / dataset.source,
        dataset.encoding,
        tuple(column.header for column in dataset.columns),
        dataset.expected_rows,
    )
    names = [column.name for column in dataset.columns]
    raw_rows = [dict(zip(names, row)) for row in rows]
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

        if dataset == FLEX:
            record["anomalies"] = flex_anomalies(values, identifiers)
        else:
            record["anomalies"] = bass_anomalies(values, ambiguous_fan)
        records.append(record)

    fields = [pa.field("source_record", INTEGER), pa.field("source_study", TEXT)]
    for column in dataset.columns:
        metadata = {"source_header": column.header}
        if column.unit is not None:
            metadata["source_unit"] = column.unit
        fields.append(pa.field(column.name, column.kind, metadata=metadata))
        if column.kind != TEXT:
            fields.append(pa.field(f"{column.name}_raw", TEXT))
        fields.append(pa.field(f"{column.name}_status", TEXT))
    fields.append(pa.field("anomalies", pa.list_(pa.field("element", TEXT))))
    metadata = {
        "source_path": dataset.source.as_posix(),
        "source_encoding": dataset.encoding,
        "source_sha256": source_hash,
        "source_investigation": f"https://psi.nasa.gov/physci/repo/data/investigations/{dataset.study}",
        "source_record_index": "1-based data record, excluding the header",
    }
    if dataset == BASS_II:
        metadata["quality_reference"] = BASS_REPORT
    return pa.Table.from_pylist(records, schema=pa.schema(fields, metadata=metadata))


def run_etl(data_dir: Path = DATA_DIR, output_dir: Path | None = None) -> dict[str, pa.Table]:
    if output_dir is None:
        output_dir = data_dir / "processed"
    tables = {dataset.name: transform(dataset, data_dir) for dataset in (FLEX, BASS_II)}
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir) as temporary_dir:
        for name, table in tables.items():
            pq.write_table(table, Path(temporary_dir) / f"{name}.parquet")
        for name in tables:
            filename = f"{name}.parquet"
            (Path(temporary_dir) / filename).replace(output_dir / filename)
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
        print(f"{name}: {table.num_rows} records")
        print(f"  Missing and special cells: {dict(sorted(statuses.items()))}")
        print(f"  Anomaly flags: {dict(sorted(anomalies.items()))}")


if __name__ == "__main__":
    main()
