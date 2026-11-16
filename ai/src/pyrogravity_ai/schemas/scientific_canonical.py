"""Versioned, storage-independent hashes for ScientificResult v1.1."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation


DATA_VERSION_RULE = "scientific-result-c14n-v1"
INPUT_SET_RULE = "scientific-input-set-c14n-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
INPUT_KEYS = frozenset({
    "psi_code", "relative_path", "dataset_sha256", "dataset_ref_id",
    "source_record", "column_ordinal", "source_header", "variable_code",
    "value", "raw_value", "unit", "interpretation_status",
})


def canonical_decimal(value: str) -> str:
    """Render a finite decimal as plain text without redundant fractional zeroes."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("decimal must be a string of at most 128 characters")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("invalid decimal") from error
    if not number.is_finite():
        raise ValueError("decimal must be finite")
    if number.is_zero():
        return "0"
    if abs(number.adjusted()) > 1000:
        raise ValueError("decimal is outside supported magnitude")
    plain = format(number, "f")
    return plain.rstrip("0").rstrip(".") if "." in plain else plain


def canonical_json_bytes(value: object) -> bytes:
    """UTF-8 JSON with sorted keys and no formatting whitespace."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def dataset_ref_id(psi_code: str, relative_path: str, sha256: str) -> str:
    """Stable logical ID independent of a PostgreSQL sequence."""
    if (re.fullmatch(r"PSI-[0-9]+", psi_code) is None or not relative_path
            or relative_path.startswith(("/", "\\")) or "\\" in relative_path
            or ":" in relative_path or ".." in relative_path.split("/")
            or SHA256.fullmatch(sha256) is None):
        raise ValueError("invalid logical dataset identity")
    identity = {"psi_code": psi_code, "relative_path": relative_path, "sha256": sha256}
    return "ds_" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:48]


def scientific_data_version(payload: Mapping[str, object]) -> str:
    """Hash the normalized scientific content, excluding only named storage fields."""
    if payload.get("canonicalization_version") != DATA_VERSION_RULE:
        raise ValueError("unsupported scientific canonicalization version")
    canonical = {key: value for key, value in payload.items()
                 if key not in {"result_id", "data_version", "source"}}
    datasets = canonical.get("datasets")
    data = canonical.get("data")
    if not isinstance(datasets, list) or not isinstance(data, list):
        raise ValueError("scientific result requires datasets and data arrays")
    canonical["datasets"] = sorted(
        ({key: value for key, value in item.items() if key != "database_dataset_id"}
         for item in datasets),
        key=lambda item: item["ref_id"],
    )
    normalized_data = []
    for datum in data:
        item = dict(datum)
        item["value"] = canonical_decimal(item["value"])
        if item.get("kind") == "derived":
            item["dataset_ref_ids"] = sorted(item["dataset_ref_ids"])
        normalized_data.append(item)
    canonical["data"] = sorted(normalized_data, key=lambda item: item["datum_id"])
    return hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()


def scientific_input_set_sha256(inputs: Sequence[Mapping[str, object]]) -> str:
    """Hash exactly the included source cells used by one aggregate."""
    if not inputs:
        raise ValueError("aggregate input set cannot be empty")
    normalized = []
    seen: set[tuple[str, str, str, int, int]] = set()
    for source in inputs:
        if set(source) != INPUT_KEYS:
            raise ValueError("aggregate input has missing or unexpected fields")
        item = dict(source)
        for key in ("psi_code", "relative_path", "dataset_sha256", "dataset_ref_id",
                    "source_header", "variable_code", "raw_value", "unit"):
            if not isinstance(item[key], str) or not item[key]:
                raise ValueError("aggregate input contains an empty provenance field")
        if item["interpretation_status"] != "exact":
            raise ValueError("aggregate input interpretation must be exact")
        if item["dataset_ref_id"] != dataset_ref_id(
            item["psi_code"], item["relative_path"], item["dataset_sha256"]
        ):
            raise ValueError("aggregate input dataset ID differs from logical identity")
        for key in ("source_record", "column_ordinal"):
            if type(item[key]) is not int or item[key] < 1:
                raise ValueError("aggregate input cell locator is invalid")
        identity = (item["psi_code"], item["relative_path"], item["dataset_sha256"],
                    item["source_record"], item["column_ordinal"])
        if identity in seen:
            raise ValueError("duplicate aggregate input cell")
        seen.add(identity)
        item["value"] = canonical_decimal(item["value"])
        normalized.append(item)
    normalized.sort(key=lambda item: (
        item["psi_code"], item["relative_path"], item["dataset_sha256"],
        item["source_record"], item["column_ordinal"],
    ))
    return hashlib.sha256(canonical_json_bytes({
        "canonicalization_version": INPUT_SET_RULE,
        "inputs": normalized,
    })).hexdigest()
