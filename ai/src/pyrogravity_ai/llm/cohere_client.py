"""Small Cohere Chat v2 adapter for text generation."""

from __future__ import annotations

from typing import Any

import cohere
from cohere.core import ApiError
from httpx import HTTPError, TimeoutException

from pyrogravity_ai.config import Settings


class CohereServiceError(RuntimeError):
    """A sanitized failure from Cohere or its transport."""

    def __init__(self, kind: str, *, retryable: bool) -> None:
        self.kind = kind
        self.retryable = retryable
        super().__init__(f"Cohere request failed: {kind}")


class CohereResponseError(RuntimeError):
    """Cohere returned no complete text response."""


class CohereTextClient:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else cohere.ClientV2(
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            client_name="pyrogravity-ai",
        )

    def generate(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be blank")

        try:
            result = self._client.chat(
                model=self._settings.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._settings.max_output_tokens,
            )
        except ApiError as exc:
            status = exc.status_code
            if status in (401, 403, 498):
                kind = "authentication"
            elif status == 429:
                kind = "rate_limit"
            elif status is not None and status >= 500:
                kind = "unavailable"
            else:
                kind = "provider_error"
            raise CohereServiceError(kind, retryable=kind in {"rate_limit", "unavailable"}) from None
        except TimeoutException:
            raise CohereServiceError("timeout", retryable=True) from None
        except HTTPError:
            raise CohereServiceError("transport", retryable=True) from None

        if result.finish_reason != "COMPLETE":
            raise CohereResponseError("Cohere returned an incomplete response")
        text = "\n".join(
            part.text for part in (result.message.content or [])
            if part.type == "text" and part.text
        ).strip()
        if not text:
            raise CohereResponseError("Cohere returned no text")
        return text
