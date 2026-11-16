from types import SimpleNamespace

import pytest
from cohere.core import ApiError
from httpx import TimeoutException

from pyrogravity_ai.config import Settings
from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.llm.cohere_embed import (
    EMBEDDING_DIMENSIONS,
    CohereEmbeddingClient,
    CohereEmbeddingResponseError,
)


def _settings(batch_size: int = 96) -> Settings:
    return Settings.from_environment(environ={
        "COHERE_API_KEY": "test-secret",
        "COHERE_MODEL": "chosen-chat-model",
        "COHERE_EMBED_MODEL": "embed-v5.0-fast",
        "COHERE_EMBED_BATCH_SIZE": str(batch_size),
    })


def _vector(value: float = 1.0) -> list[float]:
    return [value] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


class FakeEmbedClient:
    def __init__(self, *, vectors=None, error: Exception | None = None) -> None:
        self.vectors = vectors
        self.error = error
        self.calls: list[dict] = []

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        vectors = self.vectors if self.vectors is not None else [_vector() for _ in kwargs["texts"]]
        return SimpleNamespace(embeddings=SimpleNamespace(float=vectors))


def test_document_batches_preserve_order_and_explicit_dimensions() -> None:
    fake = FakeEmbedClient()
    texts = [f"NASA passage {index}" for index in range(5)]
    result = CohereEmbeddingClient(_settings(batch_size=2), client=fake).embed_documents(texts)

    assert len(result) == 5
    assert [call["texts"] for call in fake.calls] == [texts[:2], texts[2:4], texts[4:]]
    assert all(call["input_type"] == "search_document" for call in fake.calls)
    assert all(call["output_dimension"] == 1024 and call["truncate"] == "NONE" for call in fake.calls)
    assert all(call["model"] == "embed-v5.0-fast" and call["embedding_types"] == ["float"] for call in fake.calls)


def test_query_uses_search_query_type() -> None:
    fake = FakeEmbedClient()
    result = CohereEmbeddingClient(_settings(), client=fake).embed_query("Methanol extinction")
    assert len(result) == 1024
    assert fake.calls[0]["input_type"] == "search_query"


def test_empty_documents_skip_provider_and_blank_input_fails() -> None:
    fake = FakeEmbedClient()
    embedder = CohereEmbeddingClient(_settings(), client=fake)
    assert embedder.embed_documents([]) == ()
    with pytest.raises(ValueError, match="nonempty"):
        embedder.embed_documents(["valid", " "])
    with pytest.raises(ValueError, match="nonempty"):
        embedder.embed_query(" ")
    assert fake.calls == []


@pytest.mark.parametrize("vectors,message", [
    ([], "count"),
    ([[1.0, 2.0]], "dimension"),
    ([_vector(float("nan"))], "non-finite"),
    ([_vector(0.0)], "zero"),
])
def test_invalid_provider_vectors_are_rejected(vectors, message: str) -> None:
    with pytest.raises(CohereEmbeddingResponseError, match=message):
        CohereEmbeddingClient(_settings(), client=FakeEmbedClient(vectors=vectors)).embed_query("question")


@pytest.mark.parametrize("error,kind,retryable", [
    (ApiError(status_code=429, body="test-secret"), "rate_limit", True),
    (TimeoutException("test-secret"), "timeout", True),
])
def test_provider_errors_are_classified_without_secret(error, kind: str, retryable: bool) -> None:
    with pytest.raises(CohereServiceError) as captured:
        CohereEmbeddingClient(_settings(), client=FakeEmbedClient(error=error)).embed_query("question")
    assert captured.value.kind == kind
    assert captured.value.retryable is retryable
    assert "test-secret" not in str(captured.value)
