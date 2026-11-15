import shutil
from decimal import Decimal
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from app.main import app
from app.core.settings import Settings, get_settings
from app.domain.ai_contract import Evidence
from data.src.analysis.scientific_catalog import run_analysis
from data.src.etl.nasa_etl import DATA_DIR, run_etl
from scripts.load_to_supabase import main as load_main

@pytest.fixture(scope="module")
def scientific_data(tmp_path_factory):
    root = tmp_path_factory.mktemp("backend-science")
    shutil.copytree(DATA_DIR / "raw", root / "raw")
    run_etl(data_dir=root)
    return root

@pytest.fixture
def client(scientific_data):
    app.dependency_overrides[get_settings] = lambda: Settings(demo_mode=True, scientific_data_dir=scientific_data)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

@pytest.mark.parametrize("analysis_id", ["bass-ii", "flex", "flame-design", "cfi-g", "spice"])
def test_catalog_results_match_scientific_engine(client, scientific_data, analysis_id):
    response = client.get("/api/v1/analyses/" + analysis_id)
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json() == run_analysis(analysis_id, data_dir=scientific_data)

def test_catalog_invalid_id_and_filter(client):
    assert len(client.get("/api/v1/analyses").json()) == 5
    assert client.get("/api/v1/analyses/unknown").status_code == 404
    assert client.get("/api/v1/analyses/flex?material=PMMA").status_code == 422

def test_loader_validates_real_manifest_without_connection(scientific_data):
    with patch("scripts.load_to_supabase.load_datasets", side_effect=AssertionError("must not connect")):
        assert load_main(["--data-dir", str(scientific_data), "--dry-run"]) == 0

def test_real_mode_never_claims_demo_is_real(client, scientific_data):
    app.dependency_overrides[get_settings] = lambda: Settings(
        demo_mode=False, scientific_data_dir=scientific_data,
        pyrogravity_database_url=SecretStr("postgresql://reader:do-not-disclose@127.0.0.1:1/postgres"))
    response = client.post("/api/v1/ai/query", json={"query_type":"concept","question":"What is combustion?"})
    assert response.status_code == 503
    health = client.get("/health")
    assert health.status_code == 503
    assert "do-not-disclose" not in health.text

def test_demo_is_explicit_fallback(client):
    response = client.post("/api/v1/ai/query", json={"query_type":"concept","question":"What is combustion?"})
    assert response.json()["status"] == "fallback"

def test_decimal_evidence_is_not_serialized_as_float():
    evidence = Evidence(experiment_id="PSI-25", variable="co2", metric="exact",
        value=Decimal("0.123456789123456789"), dataset_id="1", dataset_version="sha256",
        trial_id="1", source_id="NASA")
    assert evidence.model_dump(mode="json")["value"] == "0.123456789123456789"
