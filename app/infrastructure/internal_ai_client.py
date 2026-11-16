"""HTTP client for Johan's private v1.1 service; constructed only when enabled."""

from __future__ import annotations

import json
from functools import lru_cache
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


@lru_cache
def _lambda_client():
    import boto3
    from botocore.config import Config

    return boto3.client("lambda", config=Config(
        connect_timeout=3, read_timeout=24, retries={"total_max_attempts": 1},
    ))


class LambdaInternalAiClient:
    """Invoke the private AI function over the AWS HTTPS API using the backend role."""

    def __init__(self, function_arn: str):
        self.function_arn = function_arn

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

        try:
            invocation = _lambda_client().invoke(
                FunctionName=self.function_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps({"operation": "query", "request": payload}).encode(),
            )
            with invocation["Payload"] as body:
                result = json.load(body)
        except ReadTimeoutError as error:
            raise AiUpstreamError("timeout", retryable=True) from error
        except (BotoCoreError, ClientError) as error:
            raise AiUpstreamError("upstream_unavailable", retryable=True) from error
        except (KeyError, ValueError) as error:
            raise AiUpstreamError("invalid_response") from error
        if invocation.get("FunctionError") or not isinstance(result, dict):
            raise AiUpstreamError("upstream_unavailable", retryable=True)
        if result.get("status") == 504:
            raise AiUpstreamError("timeout", retryable=True)
        if result.get("status") != 200:
            raise AiUpstreamError("upstream_unavailable", retryable=True)
        response = result.get("response")
        if not isinstance(response, dict):
            raise AiUpstreamError("invalid_response")
        return response
