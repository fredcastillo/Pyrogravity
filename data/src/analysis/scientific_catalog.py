"""Unified, read-only entry point for the registered scientific analyses."""

import csv
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import psycopg
from pyarrow import ArrowException

from ..database.nasa_loader import LoadError, read_manifest
from ..etl.nasa_etl import BASS_II, DATA_DIR, FLEX
from ..etl.nasa_tables import INVESTIGATION_TITLES
from . import bass_ii_co2, cfi_g_duration, flame_design_pressure, flex_combustion, spice_flow


_SOURCES = ("parquet", "postgres")
_CONTRACT_VERSION = "1.0"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class CatalogError(ValueError):
    """A safe error message and a stable code for callers of run_analysis."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Analysis:
    module: ModuleType
    result_id: str
    name: str
    psi_code: str
    description: str
    variables: tuple[tuple[str, str], ...]
    datasets: str | Mapping[str, str]
    filters: tuple[str, ...] = ()


_ANALYSES = {
    "bass-ii": _Analysis(
        bass_ii_co2, "bass_ii_co2", "BASS-II CO2", BASS_II.study,
        "Paired changes in recorded CO2 concentration.",
        (("initial_co2", "% by vol"), ("final_co2", "% by vol"), ("delta_co2", "percentage points")),
        BASS_II.source.as_posix(), ("pi", "material"),
    ),
    "flex": _Analysis(
        flex_combustion, "flex_combustion", "FLEX combustion", FLEX.study,
        "Recorded droplet diameter and burn duration by fuel and test end.",
        (("droplet_initial_diameter", "mm"), ("burn_time", "s"), ("ambient_pressure", "mmHg")),
        FLEX.source.as_posix(),
    ),
    "flame-design": _Analysis(
        flame_design_pressure, "flame_design_pressure", "Flame Design pressure", flame_design_pressure.STUDY,
        "Paired pressure changes in normal and inverse flame configurations.",
        (("pinit_atm", "atm"), ("pfinal_atm", "atm"), ("delta_pressure", "atm")),
        dict(flame_design_pressure.PATHS),
    ),
    "cfi-g": _Analysis(
        cfi_g_duration, "cfi_g_duration", "CFI-G duration", cfi_g_duration.STUDY,
        "Recorded burn duration by flame configuration and termination code.",
        (("duration", "sec"),), dict(cfi_g_duration.PATHS),
    ),
    "spice": _Analysis(
        spice_flow, "spice_flow", "SPICE flow", spice_flow.STUDY,
        "Recorded air and fuel flow settings by nozzle and fuel, with two selection cohorts.",
        (("nozzle_mm", "mm"), ("air_rate_cm_s", "cm/s"), ("fuel_rate_mg_s", "mg/s")),
        spice_flow.SOURCE.as_posix(),
    ),
}


def list_analyses() -> list[dict]:
    """Return the supported analyses in stable order with their input capabilities."""
    return [
        {
            "analysis_id": key, "analysis_name": spec.name, "psi_code": spec.psi_code,
            "investigation_name": INVESTIGATION_TITLES[spec.psi_code],
            "description": spec.description, "sources": list(_SOURCES), "filters": list(spec.filters),
            "variables": [{"name": name, "unit": unit} for name, unit in spec.variables],
        }
        for key, spec in _ANALYSES.items()
    ]


def _filters(spec: _Analysis, filters: Mapping[str, str | None] | None) -> dict[str, str | None]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise CatalogError("invalid_filter", "Filters must be a mapping.")
    if any(name not in spec.filters for name in filters):
        allowed = ", ".join(spec.filters) or "none"
        raise CatalogError("unsupported_filter", f"Unsupported filter. Allowed filters: {allowed}.")

    selected = {}
    for name in spec.filters:
        if name not in filters:
            continue
        value = filters[name]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CatalogError("invalid_filter", f"Filter '{name}' must be a non-empty string or None.")
        selected[name] = value.strip() if value is not None else None
    return selected


def _versions(spec: _Analysis, data_dir: Path) -> dict[str, dict[str, str]]:
    try:
        manifest = read_manifest(data_dir / "source_manifest.csv")
    except FileNotFoundError:
        raise CatalogError("dataset_not_found", "The source manifest was not found.") from None
    except (OSError, UnicodeError, csv.Error, LoadError) as error:
        raise CatalogError("read_error", f"Cannot read the source manifest ({type(error).__name__}).") from None

    paths = {"dataset": spec.datasets} if isinstance(spec.datasets, str) else spec.datasets
    versions = {}
    for group, path in paths.items():
        entry = manifest.get(path)
        if entry is None or entry["psi_code"] != spec.psi_code:
            raise CatalogError("dataset_not_found", f"Missing {spec.psi_code} manifest entry for {path}.")
        if _SHA256.fullmatch(entry["sha256"]) is None:
            raise CatalogError("invalid_dataset_version", f"Invalid SHA-256 in the manifest for {path}.")
        versions[group] = entry
    return versions


def _validate_result(result: dict, spec: _Analysis, versions: dict[str, dict[str, str]]) -> None:
    if not isinstance(result, dict) or result.get("analysis_id") != spec.result_id:
        raise CatalogError("inconsistent_result", "The module returned an unexpected analysis result.")
    if isinstance(spec.datasets, str):
        metadata = {"dataset": result.get("dataset")}
    else:
        configurations = result.get("configurations")
        if not isinstance(configurations, dict) or configurations.keys() != versions.keys():
            raise CatalogError("inconsistent_result", "The module returned unexpected dataset configurations.")
        metadata = {name: part.get("dataset") if isinstance(part, dict) else None
                    for name, part in configurations.items()}
    for group, entry in versions.items():
        dataset = metadata[group]
        if not isinstance(dataset, dict) or any(
            dataset.get(field) != entry[field] for field in ("psi_code", "relative_path", "investigation_name", "nasa_psi_url")
        ):
            raise CatalogError("inconsistent_result", f"The result has inconsistent dataset provenance for {group}.")
        if dataset.get("sha256") != entry["sha256"]:
            raise CatalogError("invalid_dataset_version", f"The result SHA-256 differs from the manifest for {group}.")
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise CatalogError("inconsistent_result", f"The module returned invalid JSON data ({type(error).__name__}).") from None


def run_analysis(
    analysis_name: str,
    source: str = "parquet",
    connection: psycopg.Connection | None = None,
    filters: Mapping[str, str | None] | None = None,
    *,
    data_dir: Path = DATA_DIR,
) -> dict:
    """Wrap an existing result. For postgres, the caller owns the read-only connection."""
    if not isinstance(analysis_name, str) or analysis_name not in _ANALYSES:
        allowed = ", ".join(_ANALYSES)
        raise CatalogError("unknown_analysis", f"Unknown analysis. Allowed analysis IDs: {allowed}.")
    if not isinstance(source, str) or source not in _SOURCES:
        raise CatalogError("unsupported_source", "Unsupported source. Allowed sources: parquet, postgres.")
    if source == "postgres" and (connection is None or not callable(getattr(connection, "cursor", None))):
        raise CatalogError("missing_connection", "Provide a caller-managed PostgreSQL connection.")

    spec = _ANALYSES[analysis_name]
    selected = _filters(spec, filters)
    versions = _versions(spec, data_dir)
    try:
        if source == "parquet":
            result = spec.module.analyze_parquet(data_dir=data_dir, **selected)
        else:
            sha256 = versions["dataset"]["sha256"] if isinstance(spec.datasets, str) else {
                name: entry["sha256"] for name, entry in versions.items()
            }
            result = spec.module.analyze_postgres(connection, sha256, **selected)
    except psycopg.Error as error:
        detail = f"SQLSTATE {error.sqlstate}" if error.sqlstate else type(error).__name__
        raise CatalogError("read_error", f"PostgreSQL read failed for {analysis_name} ({detail}).") from None
    except FileNotFoundError:
        raise CatalogError("dataset_not_found", f"The local dataset or manifest for {analysis_name} was not found.") from None
    except (OSError, ArrowException, UnicodeError, csv.Error, LoadError) as error:
        raise CatalogError("read_error", f"Cannot read {analysis_name} from {source} ({type(error).__name__}).") from None
    except ValueError as error:
        # The delegated modules use ValueError for version and data validation failures.
        message = str(error)
        if "dataset version is missing or not visible" in message or (
            message.startswith("No matching ") and "manifest" in message
        ):
            raise CatalogError("dataset_not_found", f"The manifest version for {analysis_name} is missing or not visible.") from None
        if "source_sha256" in message:
            raise CatalogError("invalid_dataset_version", f"The Parquet SHA-256 for {analysis_name} differs from the manifest.") from None
        raise CatalogError("read_error", f"The {source} metadata or records for {analysis_name} failed validation.") from None

    _validate_result(result, spec, versions)
    return {
        "analysis_id": analysis_name, "analysis_name": spec.name, "psi_code": spec.psi_code,
        "source": source, "contract_version": _CONTRACT_VERSION, "filters": selected, "result": result,
    }
