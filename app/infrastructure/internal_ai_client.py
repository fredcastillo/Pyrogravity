"""HTTP client for Johan's private v1.1 service; constructed only when enabled."""

from __future__ import annotations

from typing import Any

import httpx


class AiUpstreamError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class InternalAiClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}/internal/v1/ai/query",
                json=payload,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise AiUpstreamError("timeout", retryable=True) from error
        except httpx.HTTPError as error:
            raise AiUpstreamError("upstream_unavailable", retryable=True) from error
        if response.status_code == 504:
            raise AiUpstreamError("timeout", retryable=True)
        if response.status_code != 200:
            raise AiUpstreamError("upstream_unavailable", retryable=response.status_code >= 500)
        try:
            result = response.json()
        except ValueError as error:
            raise AiUpstreamError("invalid_response") from error
        if not isinstance(result, dict):
            raise AiUpstreamError("invalid_response")
        return result
