import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.public_ai_contract import (
    PUBLIC_CONTRACT_VERSION,
    PublicAiQueryRequest,
    PublicAiResponse,
)
from app.main import app


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "api" / "examples"
client = TestClient(app)


def example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def test_public_request_and_response_examples_validate():
    PublicAiQueryRequest.model_validate(example("public_ai_request"))
    supported = PublicAiResponse.model_validate(example("public_ai_supported"))
    insufficient = PublicAiResponse.model_validate(example("public_ai_insufficient"))
    assert supported.schema_version == insufficient.schema_version == PUBLIC_CONTRACT_VERSION


def test_unselected_query_returns_insufficient_evidence_and_trace_id():
    payload = example("public_ai_request")
    payload["experiment_ids"] = []
    response = client.post("/api/v1/ai/query", json=payload)
    assert response.status_code == 200
    body = PublicAiResponse.model_validate(response.json())
    assert body.status == "insufficient_evidence"
    assert body.charts == []
    assert response.headers["X-Request-ID"] == payload["id"]


def test_selected_query_returns_traceable_error_while_provider_disabled():
    payload = example("public_ai_request")
    response = client.post("/api/v1/ai/query", json=payload)
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "AI_UNAVAILABLE"
    assert body["request_id"] == payload["id"]
    assert response.headers["X-Request-ID"] == payload["id"]
    assert response.headers["X-Served-From"] == "demo"


def test_public_openapi_has_v1_1_examples():
    from scripts.export_openapi import build_openapi

    operation = build_openapi()["paths"]["/api/v1/ai/query"]["post"]
    assert operation["operationId"] == "public_ai_query_v1_1"
    assert "public_request" in operation["requestBody"]["content"]["application/json"]["examples"]
