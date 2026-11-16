import copy
import csv
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.application.public_ai_mapper import (
    MapperValidationError,
    _data_version,
    map_internal_response,
    map_public_request,
)
from app.application.public_ai_orchestrator import PublicAiOrchestrator
from app.application.scientific_result_resolver import FlexScientificResultResolver
from app.domain.public_ai_contract import PublicAiQueryRequest, PublicAiResponse


ROOT = Path(__file__).resolve().parents[2]
AI_CONTRACTS = ROOT / "ai" / "contracts" / "v1_1"
PUBLIC_EXAMPLES = ROOT / "docs" / "api" / "examples"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fixtures():
    public = read(PUBLIC_EXAMPLES / "public_ai_request.json")
    public["experiment_ids"] = ["PSI-69:psi-69_flex:1"]
    result = read(AI_CONTRACTS / "ScientificResult.example.json")
    internal_response = read(AI_CONTRACTS / "AiResponse.example.json")
    internal_response["request_id"] = public["id"]
    return public, result, internal_response


def test_maps_public_request_to_johan_schema_and_issues_backend_chart_ref():
    public, result, _ = fixtures()
    internal = map_public_request(public, scientific_results=[result])
    assert internal["schema_version"] == "1.1"
    assert internal["request_id"] == public["id"]
    assert internal["chart_preference"] == "auto"
    assert internal["chart_refs"][0]["variable"] == "burn_time"
    assert internal["chart_refs"][0]["trial_codes"] == public["experiment_ids"]


def test_no_selected_trials_cannot_carry_scientific_results():
    public, result, _ = fixtures()
    public["experiment_ids"] = []
    with pytest.raises(MapperValidationError, match="without selected trials"):
        map_public_request(public, scientific_results=[result])


def test_rejects_tampered_scientific_hash_and_unselected_trial():
    public, result, _ = fixtures()
    tampered = copy.deepcopy(result)
    tampered["data_version"] = "0" * 64
    with pytest.raises(MapperValidationError, match="data_version mismatch"):
        map_public_request(public, scientific_results=[tampered])

    tampered = copy.deepcopy(result)
    tampered["data"][0]["trial_code"] = "PSI-69:psi-69_flex:2"
    tampered["data"][0]["source_record"] = 2
    tampered["data_version"] = _data_version(tampered)
    with pytest.raises(MapperValidationError, match="unselected trial"):
        map_public_request(public, scientific_results=[tampered])


def test_response_mapper_checks_scientific_refs_numbers_units_and_builds_verified_points():
    public, result, response = fixtures()
    internal = map_public_request(public, scientific_results=[result])
    response["visualizations"][0]["data_ref"] = internal["chart_refs"][0]["data_ref"]
    mapped = map_internal_response(internal, response, provenance="demo", citation_lookup=lambda _id: None)
    assert mapped.schema_version == "public-1.1"
    assert mapped.charts[0].series[0].validated is True
    assert mapped.charts[0].series[0].points[0].y == 12.5

    bad_number = copy.deepcopy(response)
    bad_number["claims"][0]["text"] = "La duración registrada es 99 s."
    with pytest.raises(MapperValidationError, match="unsupported figures"):
        map_internal_response(internal, bad_number, provenance="demo", citation_lookup=lambda _id: None)

    bad_unit = copy.deepcopy(response)
    bad_unit["claims"][0]["text"] = "La duración registrada es 12,5 mm."
    with pytest.raises(MapperValidationError, match="unit"):
        map_internal_response(internal, bad_unit, provenance="demo", citation_lookup=lambda _id: None)


def test_rejects_forged_chart_refs_and_drops_unaccepted_chart_types():
    public, result, response = fixtures()
    internal = map_public_request(public, scientific_results=[result])
    response["visualizations"][0]["data_ref"] = internal["chart_refs"][0]["data_ref"]
    forged = copy.deepcopy(response)
    forged["visualizations"][0]["data_ref"] = "chart:forged"
    with pytest.raises(MapperValidationError, match="unauthorized"):
        map_internal_response(internal, forged, provenance="demo", citation_lookup=lambda _id: None)

    unsupported = copy.deepcopy(response)
    unsupported["visualizations"][0]["type"] = "histogram"
    mapped = map_internal_response(internal, unsupported, provenance="demo", citation_lookup=lambda _id: None)
    assert mapped.charts == []


def test_document_citations_must_match_private_view_hash_and_literal_quote():
    public, _, _ = fixtures()
    public["experiment_ids"] = []
    internal = map_public_request(public)
    passage_text = "Combustion duration depends on the experimental conditions."
    citation = {
        "document_id": str(uuid4()), "document_sha256": "a" * 64,
        "page_number": 3, "passage_id": str(uuid4()),
        "passage_sha256": hashlib.sha256(passage_text.encode()).hexdigest(),
        "quote": "duration depends on the experimental conditions", "source_id": "NASA-REPORT",
    }
    response = {
        "schema_version": "1.1", "request_id": internal["request_id"],
        "status": "supported", "intent": "document_question",
        "answer": "The report describes the conditions.",
        "claims": [{"claim_id": "claim_doc", "kind": "conceptual", "text": "The report describes conditions.", "evidence_ids": ["evidence_doc"]}],
        "evidence": [{"kind": "document", "evidence_id": "evidence_doc", "citation": citation}],
        "visualizations": [], "limitations": [],
    }
    lookup = lambda _id: {
        **citation, "passage_text": passage_text,
        "source_title": "NASA report", "source_url": "https://example.org/report",
    }
    mapped = map_internal_response(internal, response, provenance="live", citation_lookup=lookup)
    assert mapped.citations[0].snippet == citation["quote"]

    response["evidence"][0]["citation"]["quote"] = "not in passage"
    with pytest.raises(MapperValidationError, match="literal"):
        map_internal_response(internal, response, provenance="live", citation_lookup=lookup)


def test_real_public_example_is_mapper_output_from_manifest_verified_etl_rows():
    public = read(PUBLIC_EXAMPLES / "public_ai_request.json")
    scientific = read(PUBLIC_EXAMPLES / "psi69_flex_scientific_result.json")
    internal_example = read(AI_CONTRACTS / "AiQueryRequest.example.json")
    supported = PublicAiResponse.model_validate(read(PUBLIC_EXAMPLES / "public_ai_supported.json"))

    internal_schema = read(AI_CONTRACTS / "AiQueryRequest.schema.json")
    result_schema = read(AI_CONTRACTS / "ScientificResult.schema.json")
    Draft202012Validator(internal_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(internal_example)
    Draft202012Validator(result_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(scientific)
    assert scientific["data_version"] == _data_version(scientific)

    from data.src.etl.nasa_etl import FLEX, DATA_DIR, classify_rows, inspect_nasa_csv, transform
    from data.src.etl.nasa_tables import PROFILES

    source_path = DATA_DIR / FLEX.source
    source = inspect_nasa_csv(source_path, FLEX.encoding)
    canonical_source = source_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with (DATA_DIR / "source_manifest.csv").open(encoding="utf-8", newline="") as stream:
        manifest = next(row for row in csv.DictReader(stream) if row["psi_code"] == "PSI-69")
    assert hashlib.sha256(canonical_source).hexdigest() == manifest["sha256"] == scientific["datasets"][0]["sha256"]
    official = classify_rows(transform(FLEX, DATA_DIR, source), source, PROFILES[("PSI-69", "FLEX")])
    rows = official.slice(0, 2).to_pylist()
    assert all(row["quantitative_candidate"] and row["burn_time_status"] == "exact" and not row["anomalies"] for row in rows)
    assert [(row["source_record"], str(row["burn_time"])) for row in rows] == [(1, "4.30"), (2, "5.00")]
    assert [(item["source_record"], item["raw_value"]) for item in scientific["data"]] == [(1, "4.3"), (2, "5")]

    internal = map_public_request(public, scientific_results=[scientific])
    ai_response = read(AI_CONTRACTS / "AiResponse.example.json")
    ai_response["request_id"] = internal["request_id"]
    ai_response["answer"] = "Los burn_time registrados fueron 4.30 s y 5.00 s."
    ai_response["claims"] = [
        {"claim_id": "claim_psi69_burn_time_1", "kind": "numeric", "text": "burn_time = 4.30 s.", "evidence_ids": ["evidence_psi69_row_1"]},
        {"claim_id": "claim_psi69_burn_time_2", "kind": "numeric", "text": "burn_time = 5.00 s.", "evidence_ids": ["evidence_psi69_row_2"]},
    ]
    ai_response["evidence"] = [
        {"kind": "scientific", "evidence_id": "evidence_psi69_row_1", "result_id": scientific["result_id"], "datum_id": "burn_time_trial_1"},
        {"kind": "scientific", "evidence_id": "evidence_psi69_row_2", "result_id": scientific["result_id"], "datum_id": "burn_time_trial_2"},
    ]
    ai_response["visualizations"] = [{
        "chart_id": "psi69_flex_burn_time", "type": "bar", "title": "PSI-69 FLEX burn time by test",
        "data_ref": internal["chart_refs"][0]["data_ref"], "x_field": "trial_code", "y_field": "burn_time", "y_unit": "s",
    }]
    ai_response["limitations"] = scientific["limitations"]
    mapped = map_internal_response(internal, ai_response, provenance="demo", citation_lookup=lambda _id: None)
    assert mapped == supported


def test_orchestrator_resolves_real_rows_calls_internal_contract_and_maps_response():
    public = PublicAiQueryRequest.model_validate(read(PUBLIC_EXAMPLES / "public_ai_request.json"))
    resolver = FlexScientificResultResolver(ROOT / "data")

    class RecordingInternalClient:
        payload = None

        def query(self, payload):
            self.payload = payload
            result = payload["scientific_results"][0]
            return {
                "schema_version": "1.1", "request_id": payload["request_id"],
                "status": "supported", "intent": "scientific_analysis",
                "answer": "Los burn_time registrados fueron 4.30 s y 5.00 s.",
                "claims": [
                    {"claim_id": "claim_psi69_burn_time_1", "kind": "numeric", "text": "burn_time = 4.30 s.", "evidence_ids": ["evidence_psi69_row_1"]},
                    {"claim_id": "claim_psi69_burn_time_2", "kind": "numeric", "text": "burn_time = 5.00 s.", "evidence_ids": ["evidence_psi69_row_2"]},
                ],
                "evidence": [
                    {"kind": "scientific", "evidence_id": "evidence_psi69_row_1", "result_id": result["result_id"], "datum_id": "burn_time_trial_1"},
                    {"kind": "scientific", "evidence_id": "evidence_psi69_row_2", "result_id": result["result_id"], "datum_id": "burn_time_trial_2"},
                ],
                "visualizations": [{
                    "chart_id": "psi69_flex_burn_time", "type": "bar", "title": "PSI-69 FLEX burn time by test",
                    "data_ref": payload["chart_refs"][0]["data_ref"], "x_field": "trial_code",
                    "y_field": "burn_time", "y_unit": "s",
                }],
                "limitations": result["limitations"],
            }

    client = RecordingInternalClient()
    orchestrator = PublicAiOrchestrator(resolver, client, lambda _passage_id: None)
    mapped = orchestrator.query(public)
    assert client.payload["schema_version"] == "1.1"
    assert [row["value"] for row in client.payload["scientific_results"][0]["data"]] == ["4.30", "5.00"]
    assert [point.y for point in mapped.charts[0].series[0].points] == [4.3, 5.0]
    assert all(series.validated for chart in mapped.charts for series in chart.series)
