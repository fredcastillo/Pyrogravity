"""Offline retrieval evaluation with explicit human-reviewed answer keys."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, Field, field_validator

from pyrogravity_ai.ingestion.chunker import DocumentChunk
from pyrogravity_ai.ingestion.loader import LoadedDocument
from pyrogravity_ai.retrieval.postgres import (
    CONFIG_HASH,
    PassageHit,
    QueryEmbedder,
    RetrievalError,
    _require_reader,
    reciprocal_rank_fusion,
    search_text,
    search_vector,
)


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=5)
    language: Literal["en", "es"]
    expected_passage_sha256: list[str] = Field(default_factory=list)
    expected_excerpt: str | None = None
    review_status: Literal["candidate", "reviewed"] = "candidate"

    @field_validator("expected_passage_sha256")
    @classmethod
    def hashes_are_sha256(cls, value: list[str]) -> list[str]:
        if any(re.fullmatch(r"[0-9a-f]{64}", digest) is None for digest in value):
            raise ValueError("Expected passage hashes must be SHA-256 hex digests")
        return value


class EvaluationSet(BaseModel):
    source_id: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_version: str = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)


@dataclass(frozen=True)
class EvaluationReport:
    cases: int
    hit_rate_at_k: float
    mean_reciprocal_rank_at_k: float
    abstention_accuracy: float | None


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    language: Literal["en", "es"]
    first_expected_rank: int | None
    returned_count: int
    abstained: bool


@dataclass(frozen=True)
class StrategyResult:
    metrics: EvaluationReport
    cases: tuple[CaseOutcome, ...]


class EvaluationEnvironmentError(RuntimeError):
    """The active private corpus cannot be evaluated safely."""


def load_evaluation_set(path: Path) -> EvaluationSet:
    return EvaluationSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def verify_candidate_evidence(
    evaluation_set: EvaluationSet,
    document: LoadedDocument,
    chunks: Sequence[DocumentChunk],
) -> None:
    """Check that proposed answer keys still point to literal current PDF text."""
    if (evaluation_set.document_sha256 != document.sha256
            or evaluation_set.extraction_version != document.extraction_version):
        raise ValueError("Evaluation set targets a different PDF or extraction")
    by_hash: dict[str, list[DocumentChunk]] = {}
    for chunk in chunks:
        by_hash.setdefault(chunk.text_sha256, []).append(chunk)
    ids = [case.case_id for case in evaluation_set.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be unique")
    for case in evaluation_set.cases:
        if len(case.expected_passage_sha256) != len(set(case.expected_passage_sha256)):
            raise ValueError("Expected passage hashes must be unique per case")
        if any(digest not in by_hash for digest in case.expected_passage_sha256):
            raise ValueError("Expected passage is absent from current extraction")
        if any(len(by_hash[digest]) != 1 for digest in case.expected_passage_sha256):
            raise ValueError("Expected passage hash is ambiguous across pages")
        if case.expected_excerpt is not None and not any(
            case.expected_excerpt in by_hash[digest][0].text
            for digest in case.expected_passage_sha256
        ):
            raise ValueError("Expected excerpt is absent from expected passages")


def build_review_packet(
    evaluation_set: EvaluationSet,
    document: LoadedDocument,
    chunks: Sequence[DocumentChunk],
    *,
    source_title: str,
    source_url: str,
) -> str:
    """Prepare a short, reproducible human review aid; never approve cases."""
    verify_candidate_evidence(evaluation_set, document, chunks)
    by_hash = {chunk.text_sha256: chunk for chunk in chunks}
    lines = [
        "# Revisión humana de preguntas de recuperación",
        "",
        "Este documento es una ayuda de revisión, no un benchmark aprobado.",
        f"Fuente: {source_title} — {source_url}",
        f"PDF SHA-256: `{document.sha256}`",
        f"ID de fuente: `{evaluation_set.source_id}`",
        f"Extracción: `{document.extraction_version}`",
        "Compara cada cita con la página del PDF original antes de aprobarla.",
    ]
    for case in evaluation_set.cases:
        lines.extend([
            "",
            f"## {case.case_id}",
            "",
            f"Pregunta ({case.language}): {case.question}",
            f"Estado actual: `{case.review_status}`",
        ])
        if not case.expected_passage_sha256:
            lines.append("Esperado: ningún pasaje de este PDF responde la pregunta.")
        for digest in case.expected_passage_sha256:
            chunk = by_hash[digest]
            excerpt = (case.expected_excerpt if case.expected_excerpt in chunk.text
                       else chunk.text[:120])
            position = chunk.text.find(excerpt)
            start = max(0, position - 80)
            end = min(len(chunk.text), position + len(excerpt) + 80)
            context = " ".join(chunk.text[start:end].split())
            lines.extend([
                f"Página PDF: {chunk.page_number}; fragmento: {chunk.chunk_index}; SHA-256: `{digest}`",
                f"Extracto propuesto: {excerpt}",
                f"Contexto extraído: {context}",
            ])
        lines.extend([
            "- [ ] El texto y la página coinciden con el PDF original.",
            "- [ ] La evidencia responde la pregunta, o confirma que no hay respuesta en este PDF.",
            "Decisión y observaciones del revisor: pendiente.",
        ])
    return "\n".join(lines) + "\n"


def evaluate_retrieval(
    evaluation_set: EvaluationSet,
    retrieve: Callable[[str, int], Sequence[PassageHit]],
    *,
    k: int = 5,
) -> EvaluationReport:
    """Score only approved keys; empty expected lists test abstention."""
    if not 1 <= k <= 50:
        raise ValueError("k must be between 1 and 50")
    if any(case.review_status != "reviewed" for case in evaluation_set.cases):
        raise ValueError("All evaluation cases require human review before scoring")
    if len({case.case_id for case in evaluation_set.cases}) != len(evaluation_set.cases):
        raise ValueError("Evaluation case IDs must be unique")

    answerable = 0
    hits = 0
    reciprocal_rank_sum = 0.0
    abstentions = 0
    abstentions_correct = 0
    for case in evaluation_set.cases:
        results = list(retrieve(case.question, k))[:k]
        if not case.expected_passage_sha256:
            abstentions += 1
            abstentions_correct += int(not results)
            continue
        answerable += 1
        first_rank = next(
            (rank for rank, hit in enumerate(results, 1)
             if _is_expected_hit(evaluation_set, case, hit)),
            None,
        )
        if first_rank is not None:
            hits += 1
            reciprocal_rank_sum += 1.0 / first_rank
    return EvaluationReport(
        cases=len(evaluation_set.cases),
        hit_rate_at_k=hits / answerable if answerable else 0.0,
        mean_reciprocal_rank_at_k=reciprocal_rank_sum / answerable if answerable else 0.0,
        abstention_accuracy=abstentions_correct / abstentions if abstentions else None,
    )


def _is_expected_hit(
    evaluation_set: EvaluationSet, case: EvaluationCase, hit: PassageHit
) -> bool:
    return (
        hit.source_id == evaluation_set.source_id
        and hit.document_sha256 == evaluation_set.document_sha256
        and hit.extraction_version == evaluation_set.extraction_version
        and hit.passage_sha256 in case.expected_passage_sha256
    )


def compare_retrievers(
    evaluation_set: EvaluationSet,
    retrievers: Mapping[str, Callable[[str, int], Sequence[PassageHit]]],
    *,
    k: int = 5,
) -> dict[str, StrategyResult]:
    """Compare the same approved cases, retaining failures hidden by average scores."""
    if not retrievers or any(not name or not name.strip() for name in retrievers):
        raise ValueError("Named retrieval strategies are required")
    comparison: dict[str, StrategyResult] = {}
    for name, retrieve in retrievers.items():
        observed: list[tuple[PassageHit, ...]] = []

        def record(question: str, limit: int) -> tuple[PassageHit, ...]:
            hits = tuple(retrieve(question, limit))
            observed.append(hits[:limit])
            return hits

        metrics = evaluate_retrieval(evaluation_set, record, k=k)
        outcomes = []
        for case, hits in zip(evaluation_set.cases, observed, strict=True):
            first_rank = next(
                (rank for rank, hit in enumerate(hits, 1)
                 if _is_expected_hit(evaluation_set, case, hit)),
                None,
            )
            outcomes.append(CaseOutcome(
                case_id=case.case_id,
                language=case.language,
                first_expected_rank=first_rank,
                returned_count=len(hits),
                abstained=not hits,
            ))
        comparison[name] = StrategyResult(metrics=metrics, cases=tuple(outcomes))
    return comparison


def evaluate_active_kb(
    evaluation_set: EvaluationSet,
    connection: psycopg.Connection,
    embedder: QueryEmbedder,
    config_hash: str,
    *,
    k: int = 5,
) -> dict[str, StrategyResult]:
    """Compare live search baselines only on an approved, matching active corpus."""
    if any(case.review_status != "reviewed" for case in evaluation_set.cases):
        raise ValueError("All evaluation cases require human review before scoring")
    if not 1 <= k <= 50:
        raise ValueError("k must be between 1 and 50")
    if CONFIG_HASH.fullmatch(config_hash) is None:
        raise ValueError("config_hash must be a SHA-256 hex digest")
    _require_reader(connection)
    try:
        row = connection.execute(
            """SELECT d.id, d.sha256, d.extraction_version,
                      d.processing_config_hash, g.config_hash
               FROM ai.kb_active AS a
               JOIN ai.kb_generations AS g ON g.id = a.generation_id
               JOIN ai.kb_generation_documents AS m ON m.generation_id = g.id
               JOIN ai.documents AS d ON d.id = m.document_id
               JOIN ai.sources AS s ON s.id = m.source_id
               WHERE s.source_key = %s""",
            (evaluation_set.source_id,),
        ).fetchone()
        if row is None or row[1:] != (
            evaluation_set.document_sha256,
            evaluation_set.extraction_version,
            config_hash,
            config_hash,
        ):
            raise EvaluationEnvironmentError("Active corpus does not match approved evaluation version")
        hashes = [item[0] for item in connection.execute(
            "SELECT content_sha256 FROM ai.document_chunks WHERE document_id = %s",
            (row[0],),
        ).fetchall()]
    except psycopg.Error:
        raise EvaluationEnvironmentError("Active corpus verification failed") from None
    expected = {digest for case in evaluation_set.cases for digest in case.expected_passage_sha256}
    if any(hashes.count(digest) != 1 for digest in expected):
        raise EvaluationEnvironmentError("Approved passage key is missing or ambiguous in active corpus")

    text_cache: dict[str, tuple[PassageHit, ...]] = {}
    vector_cache: dict[str, tuple[PassageHit, ...]] = {}

    def text_retrieve(question: str, limit: int) -> tuple[PassageHit, ...]:
        if question not in text_cache:
            text_cache[question] = search_text(connection, question, limit=limit)
        return text_cache[question]

    def vector_retrieve(question: str, limit: int) -> tuple[PassageHit, ...]:
        if question not in vector_cache:
            vector_cache[question] = search_vector(
                connection, embedder.embed_query(question), config_hash, limit=limit
            )
        return vector_cache[question]

    try:
        return compare_retrievers(evaluation_set, {
            "text": text_retrieve,
            "vector": vector_retrieve,
            "hybrid_rrf": lambda question, limit: reciprocal_rank_fusion(
                text_retrieve(question, limit), vector_retrieve(question, limit), limit=limit
            ),
        }, k=k)
    except RetrievalError:
        raise EvaluationEnvironmentError("Private corpus retrieval failed") from None
