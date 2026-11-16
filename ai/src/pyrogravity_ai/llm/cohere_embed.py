"""Cohere Embed v2 adapter for the 1024-dimensional AI schema."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal

import cohere
from cohere.core import ApiError
from httpx import HTTPError, TimeoutException

from pyrogravity_ai.config import Settings
from pyrogravity_ai.llm.cohere_client import CohereServiceError


EMBEDDING_DIMENSIONS = 1024


class CohereEmbeddingResponseError(RuntimeError):
    """The provider returned vectors that cannot be stored or compared safely."""


class CohereEmbeddingClient:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else cohere.ClientV2(
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            client_name="pyrogravity-ai",
        )

    @property
    def model_name(self) -> str:
        return self._settings.embed_model

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed exact chunk text, preserving order across provider batches."""
        return self._embed(texts, input_type="search_document")

    def embed_query(self, text: str) -> tuple[float, ...]:
        """Use the query input type required for document search."""
        return self._embed((text,), input_type="search_query")[0]

    def _embed(
        self,
        texts: Sequence[str],
        *,
        input_type: Literal["search_document", "search_query"],
    ) -> tuple[tuple[float, ...], ...]:
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding texts must be nonempty strings")
        if not texts:
            return ()

        vectors: list[tuple[float, ...]] = []
        size = self._settings.embed_batch_size
        for start in range(0, len(texts), size):
            batch = list(texts[start:start + size])
            try:
                response = self._client.embed(
                    model=self._settings.embed_model,
                    texts=batch,
                    input_type=input_type,
                    embedding_types=["float"],
                    output_dimension=EMBEDDING_DIMENSIONS,
                    truncate="NONE",
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

            raw = getattr(getattr(response, "embeddings", None), "float", None)
            if not isinstance(raw, (list, tuple)) or len(raw) != len(batch):
                raise CohereEmbeddingResponseError("Cohere returned an invalid embedding count")
            for values in raw:
                if not isinstance(values, (list, tuple)) or len(values) != EMBEDDING_DIMENSIONS:
                    raise CohereEmbeddingResponseError("Cohere returned an invalid embedding dimension")
                if any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for value in values):
                    raise CohereEmbeddingResponseError("Cohere returned a non-finite embedding")
                if not any(value != 0 for value in values):
                    raise CohereEmbeddingResponseError("Cohere returned a zero embedding")
                vectors.append(tuple(float(value) for value in values))
        return tuple(vectors)
