"""Deterministic page-bounded text fragments for retrieval and citations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from pyrogravity_ai.ingestion.loader import LoadedDocument


@dataclass(frozen=True)
class DocumentChunk:
    artifact_sha256: str
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    text_sha256: str


def chunk_document(
    document: LoadedDocument,
    *,
    max_words: int = 180,
    overlap_words: int = 25,
) -> tuple[DocumentChunk, ...]:
    """Split each page separately so every chunk has an unambiguous page citation."""
    if max_words < 1 or overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("Require max_words > overlap_words >= 0")

    chunks: list[DocumentChunk] = []
    for page in document.pages:
        words = list(re.finditer(r"\S+", page.text))
        start = 0
        index = 0
        while start < len(words):
            end = min(start + max_words, len(words))
            char_start = words[start].start()
            char_end = words[end - 1].end()
            text = page.text[char_start:char_end]
            chunks.append(
                DocumentChunk(
                    artifact_sha256=document.sha256,
                    page_number=page.number,
                    chunk_index=index,
                    char_start=char_start,
                    char_end=char_end,
                    text=text,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
            if end == len(words):
                break
            start = end - overlap_words
            index += 1
    return tuple(chunks)
