"""Evidence identity and provider boundaries for a prepared NASA PDF."""

import hashlib
import json
from pathlib import Path

import pytest

from pyrogravity_ai.ingestion.loader import LoadedDocument, PageText
from pyrogravity_ai.ingestion.plan import IngestionPlanError, prepare_ingestion
from pyrogravity_ai.schemas.source import SourceRecord


class FakeEmbedder:
    def __init__(self, model_name: str = "embed-v5.0-fast", vectors=None) -> None:
        self.model_name = model_name
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return self.vectors if self.vectors is not None else [
            [float(index + 1)] + [0.0] * 1023 for index in range(len(texts))
        ]


def _source(sha256: str) -> SourceRecord:
    manifest = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    values = json.loads(manifest.read_text(encoding="utf-8"))
    values["expected_document_sha256"] = sha256
    return SourceRecord.model_validate(values)


def _document(text: str = "microgravity combustion evidence " * 12) -> LoadedDocument:
    payload = text.encode("utf-8")
    return LoadedDocument(
        sha256=hashlib.sha256(payload).hexdigest(),
        pages=(PageText(1, text), PageText(2, "NASA droplet results " * 9)),
        size_bytes=len(payload),
    )


def test_plan_preserves_offsets_and_has_stable_content_identity() -> None:
    document = _document()
    source = _source(document.sha256)
    embedder = FakeEmbedder()

    first = prepare_ingestion(source, document, embedder, max_words=10, overlap_words=2)
    second = prepare_ingestion(source, document, FakeEmbedder(), max_words=10, overlap_words=2)

    assert first.chunk_count > 2
    assert first.plan_hash == second.plan_hash
    assert first.config_hash == second.config_hash
    assert embedder.calls == [[chunk.text for chunk in first.chunks]]
    assert all(
        chunk.text == document.pages[chunk.page_number - 1].text[chunk.char_start:chunk.char_end]
        for chunk in first.chunks
    )
    assert len(first.embeddings) == first.chunk_count
    assert all(len(vector) == 1024 for vector in first.embeddings)


def test_model_or_chunking_change_requires_a_new_plan_identity() -> None:
    document = _document()
    source = _source(document.sha256)
    baseline = prepare_ingestion(source, document, FakeEmbedder(), max_words=12, overlap_words=2)
    other_model = prepare_ingestion(
        source, document, FakeEmbedder("embed-v5.0"), max_words=12, overlap_words=2
    )
    other_chunking = prepare_ingestion(source, document, FakeEmbedder(), max_words=10, overlap_words=2)

    assert baseline.config_hash != other_model.config_hash
    assert baseline.plan_hash != other_model.plan_hash
    assert baseline.config_hash != other_chunking.config_hash
    assert baseline.plan_hash != other_chunking.plan_hash


def test_changed_pdf_is_rejected_before_any_provider_call() -> None:
    document = _document()
    embedder = FakeEmbedder()
    with pytest.raises(IngestionPlanError, match="PDF hash"):
        prepare_ingestion(_source("0" * 64), document, embedder)
    assert embedder.calls == []


@pytest.mark.parametrize("vectors", [
    [],
    [[1.0, 2.0]],
    [[float("nan")] + [0.0] * 1023],
    [[0.0] * 1024],
])
def test_invalid_embeddings_cannot_enter_a_plan(vectors) -> None:
    document = _document("one short page")
    document = LoadedDocument(document.sha256, document.pages[:1], document.size_bytes)
    with pytest.raises(IngestionPlanError, match="Embedding"):
        prepare_ingestion(_source(document.sha256), document, FakeEmbedder(vectors=vectors))
