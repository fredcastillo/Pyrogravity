"""Exact PostgreSQL text/vector retrieval with reviewed-source gating."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

import psycopg

from pyrogravity_ai.llm.cohere_embed import EMBEDDING_DIMENSIONS


CONFIG_HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_QUERY_LENGTH = 1000


class RetrievalError(RuntimeError):
    """Retrieval failed without disclosing query or database details."""


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class PassageHit:
    passage_id: UUID
    document_id: UUID
    document_sha256: str
    page_number: int
    passage_sha256: str
    passage_text: str
    extraction_version: str
    source_id: str
    source_title: str
    source_url: str
    score: float


_SELECT = """SELECT c.id, c.document_id, d.sha256, c.page_number,
                    c.content_sha256, c.content, d.extraction_version,
                    s.source_key, s.title, s.canonical_url"""
_JOINS = """FROM ai.document_chunks c
            JOIN ai.documents d ON d.id = c.document_id
            JOIN ai.sources s ON s.id = d.source_id"""
_REVIEWED = "d.review_status = 'reviewed' AND s.catalog_status = 'catalog_verified'"


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
        raise ValueError("limit must be between 1 and 50")
    return value


def _query(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_LENGTH:
        raise ValueError("query must be nonempty and at most 1000 characters")
    return value.strip()


def _hits(rows: list[tuple], *, vector: bool = False) -> tuple[PassageHit, ...]:
    hits = []
    for row in rows:
        if hashlib.sha256(row[5].encode("utf-8")).hexdigest() != row[4]:
            raise RetrievalError("Stored passage hash differs from its text")
        hits.append(PassageHit(
            *row[:10], score=(1.0 - float(row[10])) if vector else float(row[10])
        ))
    return tuple(hits)


def _require_reader(connection: psycopg.Connection) -> None:
    try:
        role = connection.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        owner = connection.execute(
            """SELECT c.relowner = current_user::regrole
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'ai' AND c.relname = 'sources'"""
        ).fetchone()
    except psycopg.Error:
        raise RetrievalError("AI reader role check failed") from None
    if role is None or owner is None or any(role) or owner[0]:
        raise RetrievalError("A dedicated non-owner AI reader role is required")


def search_text(connection: psycopg.Connection, query: str, *, limit: int = 8) -> tuple[PassageHit, ...]:
    """Use the English full-text index as a measured retrieval baseline."""
    question = _query(query)
    count = _limit(limit)
    _require_reader(connection)
    statement = f"""{_SELECT},
        ts_rank_cd(c.content_tsv, plainto_tsquery('english', %s)) AS score
        {_JOINS}
        WHERE {_REVIEWED}
          AND c.content_tsv @@ plainto_tsquery('english', %s)
        ORDER BY score DESC, c.id ASC LIMIT %s"""
    try:
        rows = connection.execute(statement, (question, question, count)).fetchall()
    except psycopg.Error:
        raise RetrievalError("AI text retrieval failed") from None
    return _hits(rows)


def search_vector(
    connection: psycopg.Connection,
    embedding: tuple[float, ...],
    config_hash: str,
    *,
    limit: int = 8,
) -> tuple[PassageHit, ...]:
    """Search only vectors produced by one explicit embedding configuration."""
    count = _limit(limit)
    if not CONFIG_HASH.fullmatch(config_hash):
        raise ValueError("config_hash must be a SHA-256 hex digest")
    if len(embedding) != EMBEDDING_DIMENSIONS or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) for value in embedding
    ) or not any(value != 0 for value in embedding):
        raise ValueError("query embedding must be a finite nonzero vector(1024)")
    _require_reader(connection)
    literal = "[" + ",".join(repr(float(value)) for value in embedding) + "]"
    statement = f"""{_SELECT},
        e.embedding OPERATOR(extensions.<=>) %s::extensions.vector AS distance
        {_JOINS}
        JOIN ai.chunk_embeddings e ON e.chunk_id = c.id
        WHERE {_REVIEWED} AND e.config_hash = %s
        ORDER BY distance ASC, c.id ASC LIMIT %s"""
    try:
        rows = connection.execute(statement, (literal, config_hash, count)).fetchall()
    except psycopg.Error:
        raise RetrievalError("AI vector retrieval failed") from None
    return _hits(rows, vector=True)


def reciprocal_rank_fusion(
    text_hits: tuple[PassageHit, ...],
    vector_hits: tuple[PassageHit, ...],
    *,
    limit: int = 8,
    rank_constant: int = 60,
) -> tuple[PassageHit, ...]:
    """Combine ranked lists; evaluate this against each baseline before adoption."""
    count = _limit(limit)
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    passages: dict[UUID, PassageHit] = {}
    scores: dict[UUID, float] = {}
    for hits in (text_hits, vector_hits):
        for rank, hit in enumerate(hits, start=1):
            existing = passages.get(hit.passage_id)
            if existing is not None and existing != hit and replace(existing, score=hit.score) != hit:
                raise RetrievalError("Conflicting passage metadata in retrieval results")
            passages[hit.passage_id] = hit
            scores[hit.passage_id] = scores.get(hit.passage_id, 0.0) + 1.0 / (rank_constant + rank)
    ordered = sorted(scores, key=lambda passage_id: (-scores[passage_id], str(passage_id)))
    return tuple(replace(passages[passage_id], score=scores[passage_id]) for passage_id in ordered[:count])


def search_hybrid(
    connection: psycopg.Connection,
    query: str,
    embedder: QueryEmbedder,
    config_hash: str,
    *,
    limit: int = 8,
) -> tuple[PassageHit, ...]:
    """Retrieve document evidence from both baselines without generating answers."""
    question = _query(query)
    count = _limit(limit)
    text_hits = search_text(connection, question, limit=count)
    vector_hits = search_vector(connection, embedder.embed_query(question), config_hash, limit=count)
    return reciprocal_rank_fusion(text_hits, vector_hits, limit=count)
