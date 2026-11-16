import httpx
import pytest

from app.infrastructure.internal_ai_client import AiUpstreamError, InternalAiClient


def test_internal_client_sends_bearer_and_returns_json(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(200, json={"schema_version": "1.1", "status": "insufficient_evidence"})

    monkeypatch.setattr("app.infrastructure.internal_ai_client.httpx.post", post)
    client = InternalAiClient("https://ai.internal/", "t" * 32)
    result = client.query({"request_id": "request"})
    assert captured["url"] == "https://ai.internal/internal/v1/ai/query"
    assert captured["headers"]["Authorization"] == f"Bearer {'t' * 32}"
    assert result["schema_version"] == "1.1"


def test_internal_client_maps_timeout_and_upstream_errors(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.internal_ai_client.httpx.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.TimeoutException("timeout")),
    )
    with pytest.raises(AiUpstreamError) as timeout:
        InternalAiClient("https://ai.internal", "t" * 32).query({})
    assert timeout.value.code == "timeout"

    monkeypatch.setattr(
        "app.infrastructure.internal_ai_client.httpx.post",
        lambda *_args, **_kwargs: httpx.Response(503, json={"error": "unavailable"}),
    )
    with pytest.raises(AiUpstreamError) as unavailable:
        InternalAiClient("https://ai.internal", "t" * 32).query({})
    assert unavailable.value.code == "upstream_unavailable"
