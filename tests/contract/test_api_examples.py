import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.ai_contract import AiResponse, ApiErrorResponse, ChartData
from app.main import app
from scripts.export_openapi import OUTPUT_PATH, build_openapi


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "api" / "examples"
client = TestClient(app)


def read_example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def test_ai_example_validates_against_current_model():
    AiResponse.model_validate(read_example("ai_insufficient_evidence"))


def test_chart_example_validates_and_unverified_points_have_evidence():
    chart = ChartData.model_validate(read_example("chart_psi69_flex_burn_time"))
    for series in chart.series:
        if not series.validated:
            assert all(point.evidence_id for point in series.points)


def test_error_examples_validate():
    for path in sorted(EXAMPLES.glob("*_*.json")):
        if path.name[:3] in {"404", "422", "502", "503"}:
            ApiErrorResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_exported_openapi_matches_committed_file():
    committed = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    assert build_openapi() == committed


def test_ai_and_chart_provenance_headers():
    response = client.post(
        "/api/v1/ai/query",
        json={"query_type": "summary", "question": "demo"},
        headers={"X-Request-ID": "contract-test-id"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "contract-test-id"
    assert response.headers["X-Served-From"] == "demo"

    chart = client.get("/api/v1/ai/demo-1/charts/psi69-flex-burn-time")
    assert chart.status_code == 200
    assert chart.headers["X-Request-ID"]
    assert chart.headers["X-Served-From"] == "demo"


def test_unknown_chart_uses_error_contract_and_headers():
    response = client.get("/api/v1/ai/missing/charts/missing")
    assert response.status_code == 404
    ApiErrorResponse.model_validate(response.json())
    assert response.json()["error"]["code"] == "CHART_NOT_FOUND"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert response.headers["X-Served-From"] == "demo"


def test_validation_error_uses_error_contract():
    response = client.post("/api/v1/ai/query", json={"query_type": "invalid"})
    assert response.status_code == 422
    ApiErrorResponse.model_validate(response.json())
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cors_exposes_provenance_headers():
    response = client.get(
        "/api/v1/ai/demo-1/charts/psi69-flex-burn-time",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    exposed = {header.strip().lower() for header in response.headers["Access-Control-Expose-Headers"].split(",")}
    assert exposed == {"x-served-from", "x-request-id"}