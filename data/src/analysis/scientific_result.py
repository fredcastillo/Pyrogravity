"""Adapt trusted Scientific Catalog v1.0 results using the published pyrogravity_ai v1.1 contract."""

from collections import Counter
from collections.abc import Mapping
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path

from psycopg import Connection, Error
from psycopg.rows import tuple_row
from pyrogravity_ai.schemas.contracts_v11 import ScientificResult
from pyrogravity_ai.schemas.scientific_canonical import (
    DATA_VERSION_RULE,
    INPUT_SET_RULE,
    canonical_decimal,
    canonical_json_bytes,
    dataset_ref_id,
    scientific_data_version,
    scientific_input_set_sha256,
)

from ..database.nasa_loader import DATASET_KEY
from ..etl.nasa_etl import DATA_DIR, MEASUREMENT, parse_cell
from . import bass_ii_co2 as bass, cfi_g_duration as cfi
from . import flame_design_pressure as flame, flex_combustion as flex, spice_flow as spice
from .scientific_catalog import CatalogError, _ANALYSES, _filters, _versions, run_analysis


_BASS_UNITS = {name: bass.SOURCE_COLUMNS[name].unit for name in bass.READINGS}
_FLEX_UNITS = {name: flex.SOURCE_COLUMNS[name].unit for name in (flex.DIAMETER, flex.DURATION, flex.PRESSURE)}
_FLAME_UNITS = dict.fromkeys(flame.PRESSURES, flame.UNIT)
_SPICE_UNITS = {name: spice.NUMERIC[name] for name in spice.PRIMARY}
_BASS_FLAGS = {"initial_co_outside_sensor_range", "final_co_outside_sensor_range",
               "gmt_date_mismatch", "fan_display_combined_values"}
_SPICE_FLAGS = {"compact_ignition_time", "repeated_source_record"}
_BASS_LABELS = {"pi": "pi", "material": "fuel_sample_material"}


def _identity(prefix, *parts):
    return prefix + sha256(canonical_json_bytes(parts)).hexdigest()[:48]


def _verify(condition, message):
    if not condition:
        raise CatalogError("inconsistent_result", message)


def _amount(value):
    return canonical_decimal(str(value))


def _dataset(metadata, entry, source, connection):
    path, psi, digest = (entry[key] for key in ("relative_path", "psi_code", "sha256"))
    _verify(all(metadata.get(key) == entry[key] for key in (
        "relative_path", "psi_code", "sha256", "investigation_name", "nasa_psi_url", "source_filename",
    )) and metadata["row_count"] == int(entry["row_count"]), "Dataset provenance differs from the manifest.")
    database_id = None
    if source == "postgres":
        try:
            with connection.cursor(row_factory=tuple_row) as cursor:
                cursor.execute(f"SELECT dataset_id FROM scientific.datasets WHERE {DATASET_KEY}", (psi, path, digest))
                row = cursor.fetchone()
        except Error as error:
            detail = f"SQLSTATE {error.sqlstate}" if error.sqlstate else type(error).__name__
            raise CatalogError("read_error", f"PostgreSQL dataset lookup failed ({detail}).") from None
        _verify(row is not None, "The catalog's PostgreSQL dataset version is no longer visible.")
        database_id = row[0]
        _verify(metadata.get("dataset_id", database_id) == database_id, "PostgreSQL dataset identity differs.")
    return {
        "ref_id": dataset_ref_id(psi, path, digest), "psi_code": psi,
        "table_name": Path(entry["parquet_filename"]).stem, "relative_path": path, "sha256": digest,
        "source_id": psi, "source_title": entry["investigation_name"], "source_url": entry["nasa_psi_url"],
        "database_dataset_id": database_id,
    }


class _Evidence:
    def __init__(self, reference, metadata, method_version, filters, configuration):
        self.reference = reference
        self.metadata = metadata
        self.method_version = method_version
        self.filters = filters
        self.configuration = configuration
        self.measurements = {}
        self.rejected_records = set()
        self.data = []
        self.warnings = []
        self.exclusions = 0
        self.rejections = Counter()

    def _measurement(self, number, name, column_name, unit, reading, flags):
        dataset = self.reference
        column = self.metadata["columns"][column_name]
        ordinal = column["ordinal"]
        _verify(type(ordinal) is int and ordinal >= 1 and column["source_header"]
                and column["unit"] == unit and column["type"] in {"decimal", "integer"},
                f"Unexpected source column metadata for {name}.")
        raw = reading["raw"]
        if reading["status"] != "exact" or not isinstance(raw, str) or reading["value"] is None:
            return None
        original, status = parse_cell(raw, MEASUREMENT, set(), unit)
        value = _amount(reading["value"])
        if status != "exact" or original != Decimal(value):
            return None
        ref = dataset["ref_id"]
        trial = f"{dataset['psi_code']}:{dataset['table_name']}:{number}"
        return {
            "kind": "measurement", "datum_id": _identity("m_", ref, number, ordinal),
            "dataset_ref_id": ref, "trial_code": trial, "source_record": number, "column_ordinal": ordinal,
            "source_header": column["source_header"], "variable_code": name,
            "value": value, "raw_value": raw, "unit": unit, "interpretation_status": "exact",
            "validation_status": "validated", "anomalies": sorted(set(flags)),
        }

    def add_row(self, row, readings, units, *, eligible, review=(), column_names=None):
        number = row["source_record"]
        _verify(type(number) is int and 1 <= number <= self.metadata["row_count"]
                and number not in self.measurements and number not in self.rejected_records
                and row.get("dataset_sha256", self.reference["sha256"]) == self.reference["sha256"],
                "Invalid or duplicate catalog record locator.")
        if not eligible:
            self.rejected_records.add(number)
            self.rejections["incompatible trial context or quality flags"] += 1
            return
        flags = (*row["quality_flags"], *review)
        column_names = column_names or {}
        cells = {name: self._measurement(number, name, column_names.get(name, name), unit, readings[name], flags)
                 for name, unit in units.items()}
        if any(cell is None for cell in cells.values()):
            self.rejected_records.add(number)
            self.rejections["cell provenance or exact interpretation could not be verified"] += 1
            return
        self.measurements[number] = cells
        self.data.extend(cells.values())

    def _derived(self, method, variable, value, unit, count, group, cohort, *, cells=(), input_hash=None, trial=None):
        ref = self.reference["ref_id"]
        return {
            "kind": "derived", "datum_id": _identity("d_", ref, method, variable, group, cohort, trial, self.filters),
            "dataset_ref_ids": [ref], "variable_code": variable, "value": _amount(value), "unit": unit,
            "validation_status": "validated", "method": method, "method_version": self.method_version,
            "sample_count": count, "group": group, "cohort": cohort, "applied_filters": self.filters,
            "input_cells": list(cells), "input_set_sha256": input_hash,
            "input_set_version": INPUT_SET_RULE if input_hash is not None else None,
        }

    def add_delta(self, row, variables, variable, unit):
        number = row["source_record"]
        if number not in self.measurements:
            return
        initial, final = (self.measurements[number][name] for name in variables)
        with localcontext(prec=80):
            _verify(Decimal(final["value"]) - Decimal(initial["value"]) == Decimal(row[variable]),
                    "Catalog delta differs from final minus initial.")
        locators = [{key: cell[key] for key in ("dataset_ref_id", "source_record", "column_ordinal")}
                    for cell in (initial, final)]
        self.data.append(self._derived("delta", variable, row[variable], unit, 1, self.configuration, None,
                                       cells=locators, trial=number))

    def add_statistics(self, summary, count_key, statistics, variables, variable, unit, group=None, cohort=None):
        if not statistics or all(value is None for value in statistics.values()):
            return
        records = summary["source_records"]
        _verify(len(records) == len(set(records))
                and all(type(number) is int and 1 <= number <= self.metadata["row_count"] for number in records),
                "Aggregate has invalid or repeated source records.")
        included = [self.measurements[number] for number in records if number in self.measurements]
        rejected = self.rejected_records.intersection(records)
        count = summary[count_key]
        _verify(type(count) is int and count > 0 and len(included) + len(rejected) == count,
                "Aggregate sample_count differs from catalog inputs.")
        if rejected:
            self.rejections["aggregate lacks its complete validated input set"] += 1
            return
        dataset = self.reference
        inputs = [
            {"psi_code": dataset["psi_code"], "relative_path": dataset["relative_path"],
             "dataset_sha256": dataset["sha256"], **{key: cell[key] for key in (
                 "dataset_ref_id", "source_record", "column_ordinal", "source_header", "variable_code",
                 "value", "raw_value", "unit", "interpretation_status",
             )}}
            for row in included for name in variables for cell in (row[name],)
        ]
        digest = scientific_input_set_sha256(inputs)
        for method, value in statistics.items():
            if value is not None:
                code = variable if method == "pearson_r" else f"{variable}_{method}"
                self.data.append(self._derived(method, code, value, "1" if method.endswith("_count") else unit,
                                               count, group, cohort, input_hash=digest))

    def carry_exclusions(self, part, reasons_key):
        count = part["excluded_count"]
        self.exclusions += count
        if count:
            label = self.configuration or "dataset"
            reasons = ", ".join(f"{key}={value}" for key, value in sorted(part[reasons_key].items()))
            self.warnings.append(f"{label}: {count} source records excluded by catalog criteria ({reasons}).")


def _in_range(readings, units, lower, upper=None):
    if any(readings[name]["status"] != "exact" or readings[name]["value"] is None for name in units):
        return False
    values = (Decimal(_amount(readings[name]["value"])) for name in units)
    if upper is None:
        return all(value > lower for value in values)
    return all(lower <= value <= upper for value in values)


def _adapt_bass(evidence, part):
    evidence.carry_exclusions(part, "excluded_by_reading_reason")
    for row in part["pairs"]:
        readings = row["readings"]
        eligible = (bool(row["test_number"]) and set(row["quality_flags"]) <= _BASS_FLAGS
                    and all(row[_BASS_LABELS[key]] == value for key, value in evidence.filters.items())
                    and _in_range(readings, _BASS_UNITS, bass.SENSOR_MIN, bass.SENSOR_MAX))
        evidence.add_row(row, readings, _BASS_UNITS, eligible=eligible)
        evidence.add_delta(row, bass.READINGS, "delta_co2", bass.DELTA_UNIT)

    def statistics(summary, group):
        evidence.add_statistics(summary, "valid_pair_count", summary["statistics"], bass.READINGS,
                                "delta_co2", bass.DELTA_UNIT, group)

    statistics({**part, "source_records": [row["source_record"] for row in part["pairs"]]}, None)
    for field, groups in part["grouped_results"].items():
        for label, summary in groups.items():
            statistics(summary, f"{field}={label}")


def _adapt_flex(evidence, part):
    evidence.carry_exclusions(part, "excluded_by_field_reason")
    for row in part["pairs"]:
        readings = row["readings"]
        eligible = (all(row[name] for name in flex.TEXT_FIELDS)
                    and not row["quality_flags"] and not row["repeated_identifier_fields"]
                    and _in_range(readings, _FLEX_UNITS, 0)
                    and _in_range(readings, flex.COMPOSITION_NAMES.values(), 0, 1))
        evidence.add_row(row, readings, _FLEX_UNITS, eligible=eligible)

    def statistics(summary, group, cohort):
        for name in (flex.DIAMETER, flex.DURATION):
            evidence.add_statistics(summary, "valid_pair_count", summary["statistics"][name], (name,),
                                    name, _FLEX_UNITS[name], group, cohort)
        evidence.add_statistics(summary, "valid_pair_count", {"pearson_r": summary["statistics"]["pearson_r"]},
                                (flex.DIAMETER, flex.DURATION), f"{flex.DIAMETER}:{flex.DURATION}",
                                "1", group, cohort)

    for summary, cohort in ((part, None), (part["condition_comparison"], "condition_comparison")):
        statistics(summary, None, cohort)
        for fuel, by_fuel in summary["grouped_results"].items():
            group = f"fuel={fuel}"
            statistics(by_fuel, group, cohort)
            for end, by_end in by_fuel["by_test_end"].items():
                statistics(by_end, f"{group}, test_end={end}", cohort)


def _adapt_flame(evidence, part):
    evidence.carry_exclusions(part, "excluded_by_field_reason")
    config = evidence.configuration
    for row in part["pairs"]:
        readings = row["readings"]
        eligible = (bool(row["test"]) and row["configuration"] == config and not row["quality_flags"]
                    and _in_range(readings, _FLAME_UNITS, 0))
        evidence.add_row(row, readings, _FLAME_UNITS, eligible=eligible)
        evidence.add_delta(row, flame.PRESSURES, "delta_pressure", flame.UNIT)

    def statistics(summary, group):
        evidence.add_statistics(summary, "valid_pair_count", summary["statistics"], flame.PRESSURES,
                                "delta_pressure", flame.UNIT, group)

    statistics(part, config)
    for field, groups in part["grouped_results"].items():
        for label, summary in groups.items():
            statistics(summary, f"{config}, {field}={label}")


def _adapt_cfi(evidence, part):
    evidence.carry_exclusions(part, "excluded_by_field_reason")
    config = evidence.configuration
    for row in part["included"]:
        readings = {"duration": row["duration_reading"]}
        eligible = (bool(row["test"]) and row["configuration"] == config and row["termination"] in cfi.TERMINATIONS
                    and row["context"]["hot_ignition"]["raw"].strip().casefold() == "yes"
                    and not row["quality_flags"] and _in_range(readings, ("duration",), 0))
        review = ["duration_outlier"] if row["duration_outlier"] else []
        if row["termination_review"]:
            review.append(row["termination_review"])
        evidence.add_row(row, readings, {"duration": cfi.UNIT}, eligible=eligible, review=review,
                         column_names={"duration": cfi.DURATION})

    def statistics(summary, group):
        evidence.add_statistics(summary, "valid_count", summary["statistics"], ("duration",),
                                "duration", cfi.UNIT, group)

    statistics(part, config)
    for end, summary in part["grouped_results"]["termination"].items():
        statistics(summary, f"{config}, termination={end}")
    for fuel, summary in part["grouped_results"]["fuel"].items():
        group = f"{config}, fuel={fuel}"
        statistics(summary, group)
        for end, by_end in summary["by_termination"].items():
            statistics(by_end, f"{group}, termination={end}")
    empty = part["quality"]["empty_row_count"]
    if empty:
        evidence.warnings.append(f"{config}: {empty} empty source records are outside the trial population.")


def _adapt_spice(evidence, part):
    available = part["cohorts"]["available"]
    evidence.carry_exclusions(available, "excluded_by_field_reason")
    included = set(available["source_records"])
    for row in part["records"]:
        if row["source_record"] in included:
            evidence.add_row(row, row["cells"], _SPICE_UNITS,
                             eligible=set(row["quality_flags"]) <= _SPICE_FLAGS, review=row["review_flags"])

    def statistics(summary, group, cohort):
        for name, unit in _SPICE_UNITS.items():
            metric = summary["statistics"][name]
            _verify(metric["exact_count"] == summary["record_count"], "SPICE cohort contains an inexact primary cell.")
            evidence.add_statistics(summary, "record_count", metric["summary"], (name,), name, unit, group, cohort)

    for cohort, summary in part["cohorts"].items():
        statistics(summary, None, cohort)
        for field, groups in summary["grouped_results"].items():
            for label, group in groups.items():
                name = f"{field}={label}"
                statistics(group, name, cohort)
                for fuel, by_fuel in group.get("by_fuel", {}).items():
                    group_name = f"{name}, fuel={fuel}"
                    statistics(by_fuel, group_name, cohort)
                    if association := by_fuel["association"]:
                        _verify(association["record_count"] == by_fuel["record_count"],
                                "SPICE Pearson sample_count differs from its cohort group.")
                        evidence.add_statistics(by_fuel, "record_count", {"pearson_r": association["pearson_r"]},
                                                (spice.AIR, spice.FUEL_RATE), f"{spice.AIR}:{spice.FUEL_RATE}",
                                                "1", group_name, cohort)


_ADAPTERS = {"bass-ii": _adapt_bass, "flex": _adapt_flex, "flame-design": _adapt_flame,
             "cfi-g": _adapt_cfi, "spice": _adapt_spice}
_LIMITATIONS = {
    "bass-ii": ("Repeated samples and differences below the sensor resolution retain the catalog's limitations.",),
    "flex": ("The reference cohort uses the catalog's recorded composition and pressure window. "
             "Its membership is a descriptive selection, independent of input filters.",),
    "flame-design": ("Inverse Flame has no Fuel column in the audited source version.",),
    "cfi-g": ("SE and FT use the source labels. Duration is recorded burn time; FT does not establish natural extinction.",
              "Duration outliers are retained with flags. No physical termination mechanism or censoring is assigned."),
    "spice": ("SPICE has no documented row-level smoke-point indicator. Flow sign does not establish physical direction.",
              "The available cohort retains identical rows. The conservative cohort excludes every member of an identical group.",
              "Signed readings and zero values remain as recorded. Associations between settings are descriptive."),
}


def adapt_catalog_result(
    catalog: dict, *, data_dir: Path = DATA_DIR, connection: Connection | None = None,
) -> ScientificResult:
    """Convert an unmodified run_analysis result using the same manifest and PostgreSQL connection."""
    name, source = catalog["analysis_id"], catalog["source"]
    _verify(name in _ADAPTERS and source in {"parquet", "postgres"} and catalog["contract_version"] == "1.0",
            "Unsupported Scientific Catalog result.")
    if source == "postgres" and connection is None:
        raise CatalogError("missing_connection", "Provide the caller-managed PostgreSQL connection used by the catalog.")
    spec = _ANALYSES[name]
    selected = {key: value for key, value in _filters(spec, catalog["filters"]).items() if value is not None}
    versions = _versions(spec, data_dir)
    result = catalog["result"]
    _verify(catalog["psi_code"] == spec.psi_code and result["analysis_id"] == spec.result_id
            and result["method_version"] == "1.0.0",
            "Catalog analysis or method version is unsupported by this adapter.")
    parts = result.get("configurations", {"dataset": result})
    _verify(parts.keys() == versions.keys(), "Catalog configurations differ from the manifest selection.")
    datasets, data, warnings = [], [], list(result["warnings"])
    limitations = list(_LIMITATIONS[name])
    incomplete = False
    for label in sorted(parts):
        part = parts[label]
        metadata = part["dataset"]
        reference = _dataset(metadata, versions[label], source, connection)
        evidence = _Evidence(reference, metadata, result["method_version"], selected, None if label == "dataset" else label)
        _ADAPTERS[name](evidence, part)
        datasets.append(reference)
        data.extend(evidence.data)
        warnings.extend(evidence.warnings)
        warnings.extend(f"{label}: {count} rejected ({reason})." for reason, count in sorted(evidence.rejections.items()))
        incomplete |= bool(evidence.exclusions or evidence.rejections or not evidence.data)
    if name == "cfi-g":
        limits = result["termination_interpretation"]
        limitations.extend((limits["verification"], limits["censoring"]))
    status = "insufficient_evidence" if not data else "partial" if incomplete else "ok"
    datasets.sort(key=lambda item: item["ref_id"])
    data.sort(key=lambda item: item["datum_id"])
    payload = {
        "schema_version": "1.1", "canonicalization_version": DATA_VERSION_RULE,
        "analysis_id": name, "source": source, "status": status, "datasets": datasets,
        "result_id": _identity("result_", name, [item["ref_id"] for item in datasets], selected),
        "data": data, "warnings": warnings, "limitations": limitations,
    }
    payload["data_version"] = scientific_data_version(payload)
    return ScientificResult.model_validate(payload)


def run_scientific_result(
    analysis_name: str, source: str = "parquet", connection: Connection | None = None,
    filters: Mapping[str, str | None] | None = None, *, data_dir: Path = DATA_DIR,
) -> ScientificResult:
    """Run the catalog and return its validated ScientificResult v1.1 representation."""
    catalog = run_analysis(analysis_name, source, connection, filters, data_dir=data_dir)
    return adapt_catalog_result(catalog, data_dir=data_dir, connection=connection)
