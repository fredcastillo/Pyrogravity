"""Check that the deployed service rejects unauthenticated callers before parsing."""

import secrets

from fastapi.testclient import TestClient

from pyrogravity_ai.service.app import create_app


def test_ai_rejects_missing_and_incorrect_bearer():
    def unexpected_engine():
        raise AssertionError("Authentication must run before the engine")

    token = secrets.token_urlsafe(32)
    with TestClient(create_app(token=token, engine_factory=unexpected_engine)) as service:
        unauthenticated = ({}, {"Authorization": f"Bearer {secrets.token_urlsafe(32)}"})
        for headers in unauthenticated:
            response = service.post("/internal/v1/ai/query", content="invalid json", headers=headers)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "unauthorized"
        authenticated = service.post(
            "/internal/v1/ai/query", content="invalid json", headers={"Authorization": f"Bearer {token}"}
        )
        assert authenticated.status_code == 422
