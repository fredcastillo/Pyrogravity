"""Prepare a reproducible document ingestion without database side effects."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pyrogravity_ai.ingestion.chunker import DocumentChunk, chunk_document
from pyrogravity_ai.ingestion.loader import LoadedDocument
from pyrogravity_ai.llm.cohere_embed import EMBEDDING_DIMENSIONS
from pyrogravity_ai.schemas.source import SourceRecord


PIPELINE_VERSION = "pdf-ingest-v1"


class IngestionPlanError(ValueError):
    """The source, document or embeddings cannot form a trustworthy plan."""


class DocumentEmbedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True)
class PreparedIngestion:
    source: SourceRecord
    document: LoadedDocument
    chunks: tuple[DocumentChunk, ...]
    embeddings: tuple[tuple[float, ...], ...]
    model_name: str
    config_hash: str
    plan_hash: str
    pipeline_version: str = PIPELINE_VERSION

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prepare_ingestion(
    source: SourceRecord,
    document: LoadedDocument,
    embedder: DocumentEmbedder,
    *,
    max_words: int = 180,
    overlap_words: int = 25,
) -> PreparedIngestion:
    """Validate pinned input, preserve chunk order and embed exact chunk text."""
    if source.catalog_status != "catalog_verified":
        raise IngestionPlanError("Source catalog is not verified")
    if source.document_url.scheme != "https" or source.document_url.host != "ntrs.nasa.gov":
        raise IngestionPlanError("Document URL must be an official NASA NTRS URL")
    if document.sha256 != source.expected_document_sha256:
        raise IngestionPlanError("PDF hash differs from the source manifest")
    model_name = embedder.model_name
    if not model_name or model_name != model_name.strip():
        raise IngestionPlanError("Embedding model name is required")

    chunks = chunk_document(document, max_words=max_words, overlap_words=overlap_words)
    if not chunks:
        raise IngestionPlanError("Document contains no indexable text")
    pages = {page.number: page.text for page in document.pages}
    for chunk in chunks:
        page = pages.get(chunk.page_number)
        if (
            page is None
            or chunk.artifact_sha256 != document.sha256
            or page[chunk.char_start:chunk.char_end] != chunk.text
            or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.text_sha256
        ):
            raise IngestionPlanError("Chunk provenance is inconsistent")

    config_hash = _sha256_json({
        "pipeline_version": PIPELINE_VERSION,
        "extraction_version": document.extraction_version,
        "chunking": {"max_words": max_words, "overlap_words": overlap_words},
        "embedding": {
            "model": model_name,
            "input_type": "search_document",
            "embedding_type": "float",
            "dimensions": EMBEDDING_DIMENSIONS,
            "truncate": "NONE",
        },
    })
    plan_hash = _sha256_json({
        "source_id": source.source_id,
        "document_sha256": document.sha256,
        "config_hash": config_hash,
        "chunks": [
            [chunk.page_number, chunk.chunk_index, chunk.char_start, chunk.char_end, chunk.text_sha256]
            for chunk in chunks
        ],
    })

    raw_vectors = embedder.embed_documents([chunk.text for chunk in chunks])
    if len(raw_vectors) != len(chunks):
        raise IngestionPlanError("Embedding count differs from chunk count")
    vectors: list[tuple[float, ...]] = []
    for raw in raw_vectors:
        if len(raw) != EMBEDDING_DIMENSIONS or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in raw
        ) or not any(value != 0 for value in raw):
            raise IngestionPlanError("Embedding is invalid for vector(1024)")
        vectors.append(tuple(float(value) for value in raw))

    return PreparedIngestion(
        source=source,
        document=document,
        chunks=chunks,
        embeddings=tuple(vectors),
        model_name=model_name,
        config_hash=config_hash,
        plan_hash=plan_hash,
    )
