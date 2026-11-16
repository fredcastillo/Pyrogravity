"""Internal HTTP contract and fail-closed authentication tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyrogravity_ai.core.engine import AiEngine
from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.service.app import create_app

TOKEN = "unit-test-only-internal-token-32-characters"
EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "v1_1" / "AiQueryRequest.example.json"


class EmptyRetriever:
    def retrieve(self, question: str, *, limit: int) -> tuple:
        return ()


class SelectAll:
    def select(self, question: str, candidates: tuple) -> tuple[str, ...]:
        return tuple(candidate.evidence_id for candidate in candidates[:4])


def payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def client(engine=None) -> TestClient:
    return TestClient(create_app(engine=engine or AiEngine(EmptyRetriever(), SelectAll()), token=TOKEN))


def test_token_is_required_before_request_parsing() -> None:
    service = client()
    result = service.post("/internal/v1/ai/query", content="broken-json")
    assert result.status_code == 401
    assert result.json()["error"]["code"] == "unauthorized"
    assert service.get("/health").json() == {"status": "ok"}
    with pytest.raises(ValueError, match="AI_INTERNAL_TOKEN"):
        create_app(token="short")


def test_valid_request_and_scientific_insufficiency_are_http_200() -> None:
    service = client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = service.post("/internal/v1/ai/query", json=payload(), headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "supported"
    assert response.json()["evidence"][0]["datum_id"] == "datum_1"
    invalid = payload()
    invalid["scientific_results"][0]["data"][0]["value"] = "999"
    error = service.post("/internal/v1/ai/query", json=invalid, headers=headers)
    assert error.status_code == 422
    assert error.json()["error"]["code"] == "invalid_request"
    assert "999" not in error.text


def test_provider_timeout_maps_to_retryable_error_without_detail() -> None:
    class FailingEngine:
        def answer(self, _request):
            raise CohereServiceError("timeout", retryable=True)

    response = client(FailingEngine()).post(
        "/internal/v1/ai/query", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "timeout",
        "message": "El proveedor de IA agotó el tiempo de espera.",
        "retryable": True,
    }
    assert response.json()["request_id"] == payload()["request_id"]
