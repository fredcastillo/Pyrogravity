"""Public-to-internal AI v1.1 mapper and response grounding checks.

The versioned JSON Schemas are authoritative; this module does not import the
AI service's Python package, so it also works when that service is remote.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from app.domain.public_ai_contract import PUBLIC_CONTRACT_VERSION, PublicAiQueryRequest, PublicAiResponse


SCHEMAS = Path(__file__).resolve().parents[2] / "ai" / "contracts" / "v1_1"
PUBLIC_CHART_TYPES = {"bar", "line", "scatter"}
NUMBER_PATTERN = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?")


class MapperValidationError(ValueError):
    """Raised when the public/internal contract or grounding checks fail."""


def _schema_validate(value: dict[str, Any], file_name: str) -> None:
    schema = json.loads((SCHEMAS / file_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _decimal_string(value: str) -> str:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError) as error:
        raise MapperValidationError("scientific value is not a decimal") from error
    if not number.is_finite():
        raise MapperValidationError("scientific value is not finite")
    if number.is_zero():
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _dataset_identity(dataset: dict[str, Any]) -> str:
    values = {key: dataset[key] for key in ("psi_code", "relative_path", "sha256")}
    return "ds_" + hashlib.sha256(_canonical_json(values)).hexdigest()[:48]


def _data_version(result: dict[str, Any]) -> str:
    if result.get("canonicalization_version") != "scientific-result-c14n-v1":
        raise MapperValidationError("unsupported scientific canonicalization version")
    canonical = {k: v for k, v in result.items() if k not in {"result_id", "data_version", "source"}}
    canonical["datasets"] = sorted(
        ({k: v for k, v in dataset.items() if k != "database_dataset_id"} for dataset in result["datasets"]),
        key=lambda item: item["ref_id"],
    )
    data = []
    for datum in result["data"]:
        item = dict(datum)
        item["value"] = _decimal_string(item["value"])
        if item.get("kind") == "derived":
            item["dataset_ref_ids"] = sorted(item["dataset_ref_ids"])
        data.append(item)
    canonical["data"] = sorted(data, key=lambda item: item["datum_id"])
    return hashlib.sha256(_canonical_json(canonical)).hexdigest()


def _validate_scientific_result(result: dict[str, Any]) -> None:
    _schema_validate(result, "ScientificResult.schema.json")
    datasets = {item["ref_id"]: item for item in result["datasets"]}
    if len(datasets) != len(result["datasets"]):
        raise MapperValidationError("duplicate dataset reference")
    datum_ids = [item["datum_id"] for item in result["data"]]
    if len(datum_ids) != len(set(datum_ids)):
        raise MapperValidationError("duplicate datum reference")
    for dataset in datasets.values():
        if dataset["ref_id"] != _dataset_identity(dataset):
            raise MapperValidationError("dataset ref_id does not match source identity")
    for datum in result["data"]:
        refs = [datum["dataset_ref_id"]] if datum["kind"] == "measurement" else datum["dataset_ref_ids"]
        if any(ref not in datasets for ref in refs):
            raise MapperValidationError("datum references an unknown dataset")
        if datum["kind"] == "measurement":
            source = datasets[datum["dataset_ref_id"]]
            if datum["trial_code"] != f"{source['psi_code']}:{source['table_name']}:{datum['source_record']}":
                raise MapperValidationError("trial code does not match source row")
    if result["data_version"] != _data_version(result):
        raise MapperValidationError("scientific result data_version mismatch")


def _issue_chart_refs(results: list[dict[str, Any]], public: PublicAiQueryRequest) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], set[str]] = {}
    for result in results:
        for datum in result["data"]:
            if (datum.get("kind") != "measurement" or datum.get("validation_status") != "validated"
                    or datum.get("interpretation_status") != "exact"
                    or datum["trial_code"] not in public.experiment_ids
                    or (public.variables and datum["variable_code"] not in public.variables)):
                continue
            groups.setdefault((datum["variable_code"], datum["unit"]), set()).add(datum["trial_code"])
    refs = []
    for (variable, unit), trials in sorted(groups.items()):
        token = hashlib.sha256(f"{variable}|{unit}|{'|'.join(sorted(trials))}".encode()).hexdigest()[:16]
        refs.append({"data_ref": f"chart:{token}", "label": variable, "variable": variable,
                     "unit": unit, "trial_codes": sorted(trials)})
    return refs


def map_public_request(
    request: PublicAiQueryRequest | dict[str, Any], *, scientific_results: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Map the browser request to Johan's internal request and validate v1.1 JSON Schema."""
    public = request if isinstance(request, PublicAiQueryRequest) else PublicAiQueryRequest.model_validate(request)
    try:
        request_id = str(UUID(public.id))
    except ValueError as error:
        raise MapperValidationError("public id must be a UUID") from error
    results = scientific_results or []
    for result in results:
        _validate_scientific_result(result)
    if not public.experiment_ids and results:
        raise MapperValidationError("scientific results are forbidden without selected trials")
    if any(datum.get("kind") == "measurement" and datum["trial_code"] not in public.experiment_ids
           for result in results for datum in result["data"]):
        raise MapperValidationError("scientific result contains an unselected trial")
    internal = {
        "schema_version": "1.1", "request_id": request_id, "question": public.question,
        "language": public.language, "experiment_ids": public.experiment_ids,
        "variables": public.variables,
        "chart_preference": "required" if public.chart_preference else "auto",
        "scientific_results": results,
        "chart_refs": _issue_chart_refs(results, public),
    }
    _schema_validate(internal, "AiQueryRequest.schema.json")
    return internal


def _numbers(text: str) -> set[Decimal]:
    values = set()
    for token in NUMBER_PATTERN.findall(text):
        try:
            values.add(Decimal(token.replace(",", ".")))
        except InvalidOperation:
            pass
    return values


def _verify_numeric_text(text: str, evidence_datums: list[dict[str, Any]]) -> None:
    numbers = _numbers(text)
    supported = {Decimal(item["value"]) for item in evidence_datums}
    if numbers and (not evidence_datums or not numbers.issubset(supported)):
        raise MapperValidationError("response contains unsupported figures")
    for datum in evidence_datums:
        if Decimal(datum["value"]) in numbers:
            unit = rf"(?<![A-Za-z]){re.escape(datum['unit'])}(?![A-Za-z])"
            if re.search(unit, text, re.IGNORECASE) is None:
                raise MapperValidationError("response omits or changes a scientific unit")


def _chart_number(value: str) -> float:
    decimal_value = Decimal(value)
    number = float(decimal_value)
    if not Decimal(str(number)) == decimal_value:
        raise MapperValidationError("chart value cannot be represented without precision loss")
    return number


def _verified_passage(citation: dict[str, Any], lookup: Callable[[str], dict[str, Any] | None]) -> dict[str, Any]:
    passage = lookup(citation["passage_id"])
    if passage is None:
        raise MapperValidationError("citation passage missing from private view")
    for field in ("document_id", "document_sha256", "page_number", "passage_id", "passage_sha256", "source_id"):
        if str(passage[field]) != str(citation[field]):
            raise MapperValidationError(f"citation {field} mismatch")
    text = passage["passage_text"]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != citation["passage_sha256"]:
        raise MapperValidationError("citation passage hash mismatch")
    if citation["quote"] not in text:
        raise MapperValidationError("citation quote is not literal passage text")
    return passage


def map_internal_response(
    request: dict[str, Any], response: dict[str, Any], *, provenance: str,
    citation_lookup: Callable[[str], dict[str, Any] | None],
) -> PublicAiResponse:
    """Validate AI output, ground every ref/citation/number/unit, then build Bryant's response."""
    _schema_validate(request, "AiQueryRequest.schema.json")
    _schema_validate(response, "AiResponse.schema.json")
    if response["request_id"] != request["request_id"]:
        raise MapperValidationError("response request_id differs from request")
    for result in request["scientific_results"]:
        _validate_scientific_result(result)
    if not request["experiment_ids"] and request["scientific_results"]:
        raise MapperValidationError("scientific results are forbidden without selected trials")
    if any(datum.get("kind") == "measurement" and datum["trial_code"] not in request["experiment_ids"]
           for result in request["scientific_results"] for datum in result["data"]):
        raise MapperValidationError("scientific result contains an unselected trial")
    if len({item["evidence_id"] for item in response["evidence"]}) != len(response["evidence"]):
        raise MapperValidationError("duplicate evidence ID")
    evidence_ids = {item["evidence_id"] for item in response["evidence"]}
    if any(ref not in evidence_ids for claim in response["claims"] for ref in claim["evidence_ids"]):
        raise MapperValidationError("claim references unknown evidence")
    if response["status"] != "insufficient_evidence" and not response["claims"]:
        raise MapperValidationError("supported response requires claims")
    if response["status"] == "insufficient_evidence" and (response["claims"] or response["evidence"] or response["visualizations"]):
        raise MapperValidationError("insufficient evidence response cannot contain claims or charts")
    datums = {(result["result_id"], datum["datum_id"]): (result, datum)
              for result in request["scientific_results"] for datum in result["data"]}
    allowed_charts = {item["data_ref"]: item for item in request["chart_refs"]}
    evidence = {item["evidence_id"]: item for item in response["evidence"]}
    citations: dict[str, dict[str, Any]] = {}
    scientific_evidence: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for item in response["evidence"]:
        if item["kind"] == "document":
            citation = item["citation"]
            passage = _verified_passage(citation, citation_lookup)
            citations[item["evidence_id"]] = {
                "id": item["evidence_id"], "kind": "document", "title": passage["source_title"],
                "url": passage["source_url"], "page": passage["page_number"], "snippet": citation["quote"],
                "source": passage["source_id"],
            }
        else:
            key = (item["result_id"], item["datum_id"])
            if key not in datums:
                raise MapperValidationError("scientific evidence was not supplied by backend")
            result, datum = datums[key]
            if datum.get("validation_status") != "validated" or (datum["kind"] == "measurement" and datum.get("interpretation_status") != "exact"):
                raise MapperValidationError("scientific evidence is not validated exact data")
            ref_id = datum["dataset_ref_id"] if datum["kind"] == "measurement" else datum["dataset_ref_ids"][0]
            dataset = next(ds for ds in result["datasets"] if ds["ref_id"] == ref_id)
            scientific_evidence[item["evidence_id"]] = (result, datum, dataset)
            citations[item["evidence_id"]] = {
                "id": item["evidence_id"], "kind": "scientific", "title": dataset["source_title"],
                "url": dataset["source_url"], "page": None,
                "snippet": (f"{datum['trial_code']}; {datum['source_header']}: {datum['raw_value']} {datum['unit']}"
                            if datum["kind"] == "measurement" else
                            f"{datum['method']} v{datum['method_version']}; n={datum['sample_count']}; "
                            + "; ".join(f"{cell['dataset_ref_id']}:{cell['source_record']}:{cell['column_ordinal']}"
                                        for cell in datum["input_cells"])),
                "source": dataset["source_id"],
                "measurement": {"variable": datum["variable_code"], "value": _decimal_string(datum["value"]),
                                "unit": datum["unit"], "provenance": provenance},
            }
    claims = []
    all_scientific_datums: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in response["claims"]:
        linked = [evidence[item] for item in claim["evidence_ids"]]
        scientific = [scientific_evidence[item["evidence_id"]][1] for item in linked
                      if item["kind"] == "scientific"]
        if claim["kind"] == "numeric":
            if not scientific:
                raise MapperValidationError("numeric claim requires scientific evidence")
            _verify_numeric_text(claim["text"], scientific)
        elif _numbers(claim["text"]) and not any(item["kind"] == "document" and claim["text"] in item["citation"]["quote"] for item in linked):
            raise MapperValidationError("conceptual claim must be a literal verified quote")
        for item in linked:
            if item["kind"] == "scientific":
                all_scientific_datums[(item["result_id"], item["datum_id"])] = scientific_evidence[item["evidence_id"]][1]
        claims.append({"id": claim["claim_id"], "text": claim["text"], "citation_ids": claim["evidence_ids"]})
    assembled = "\n".join(f"{index}. {claim['text']}" for index, claim in enumerate(response["claims"], 1))
    if response["answer"] != assembled:
        _verify_numeric_text(response["answer"], list(all_scientific_datums.values()))
    charts = []
    if request["chart_preference"] != "none":
        for spec in response["visualizations"]:
            if spec["type"] not in PUBLIC_CHART_TYPES:
                continue
            ref = allowed_charts.get(spec["data_ref"])
            if ref is None or spec["y_field"] != ref["variable"] or spec["y_unit"] != ref["unit"]:
                raise MapperValidationError("chart uses unauthorized reference, variable, or unit")
            points = []
            for result in request["scientific_results"]:
                for datum in result["data"]:
                    if (datum.get("kind") == "measurement" and datum["trial_code"] in ref["trial_codes"]
                            and datum["variable_code"] == ref["variable"] and datum["unit"] == ref["unit"]
                            and datum.get("validation_status") == "validated"
                            and datum.get("interpretation_status") == "exact"):
                        points.append({"x": datum["trial_code"], "y": _chart_number(datum["value"])})
            if not points:
                raise MapperValidationError("chart has no backend-verified points")
            charts.append({
                "id": spec["chart_id"], "type": spec["type"], "title": spec["title"],
                "x_label": spec["x_field"], "y_label": spec["y_field"], "provenance": provenance,
                # Points are embedded; the internal opaque data_ref must not escape to Bryant.
                "data_ref": None,
                "series": [{"id": spec["chart_id"], "label": ref["label"], "unit": ref["unit"],
                            "validated": True, "points": points}],
                "limitations": response["limitations"],
            })
    return PublicAiResponse(
        schema_version=PUBLIC_CONTRACT_VERSION, id=response["request_id"], status=response["status"],
        answer=response["answer"], claims=claims, citations=list(citations.values()),
        limitations=response["limitations"], charts=charts, provenance=provenance,
    )
