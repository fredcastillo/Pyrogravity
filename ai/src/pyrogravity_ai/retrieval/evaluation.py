"""Offline retrieval evaluation with explicit human-reviewed answer keys."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
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
from pyrogravity_ai.schemas.contracts_v11 import AiResponse


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=5)
    language: Literal["en", "es"]
    expected_passage_sha256: list[str] = Field(default_factory=list)
    expected_excerpt: str | None = None
    review_status: Literal["candidate", "reviewed"] = "candidate"
    reviewed_by: str | None = Field(default=None, min_length=1)
    reviewed_at: date | None = None
    review_notes: str | None = Field(default=None, max_length=1000)

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
    document_reviewed_by: str | None = Field(default=None, min_length=1)
    document_reviewed_at: date | None = None
    document_review_notes: str | None = Field(default=None, max_length=2000)


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


@dataclass(frozen=True)
class EngineCaseOutcome:
    case_id: str
    language: Literal["en", "es"]
    status: str
    answerable: bool
    expected_evidence_selected: bool
    abstained: bool
    correct: bool


@dataclass(frozen=True)
class EngineEvaluationReport:
    cases: int
    correct_rate: float
    answerable_cases: int
    answerable_evidence_rate: float
    unsupported_cases: int
    negative_abstention_accuracy: float | None
    false_support_rate: float | None
    outcomes: tuple[EngineCaseOutcome, ...]


def evaluate_engine(
    evaluation_set: EvaluationSet,
    answer: Callable[[EvaluationCase], AiResponse],
) -> EngineEvaluationReport:
    """Measure end-to-end evidence selection and abstention, not retrieval alone."""
    if any(case.review_status != "reviewed" for case in evaluation_set.cases):
        raise ValueError("All evaluation cases require human review before scoring")
    if len({case.case_id for case in evaluation_set.cases}) != len(evaluation_set.cases):
        raise ValueError("Evaluation case IDs must be unique")

    outcomes: list[EngineCaseOutcome] = []
    answerable = 0
    answerable_with_expected = 0
    unsupported = 0
    true_abstentions = 0
    false_supports = 0
    correct_cases = 0

    for case in evaluation_set.cases:
        response = answer(case)
        expected_selected = any(
            evidence.citation.source_id == evaluation_set.source_id
            and evidence.citation.document_sha256 == evaluation_set.document_sha256
            and evidence.citation.passage_sha256 in case.expected_passage_sha256
            for evidence in response.evidence
            if getattr(evidence, "kind", None) == "document"
        )
        abstained = (
            response.status == "insufficient_evidence"
            and not response.claims
            and not response.evidence
            and not response.visualizations
        )
        if case.expected_passage_sha256:
            answerable += 1
            answerable_with_expected += int(expected_selected)
            correct = expected_selected and response.status != "insufficient_evidence"
        else:
            unsupported += 1
            true_abstentions += int(abstained)
            false_supports += int(not abstained)
            correct = abstained
        correct_cases += int(correct)
        outcomes.append(EngineCaseOutcome(
            case_id=case.case_id,
            language=case.language,
            status=response.status,
            answerable=bool(case.expected_passage_sha256),
            expected_evidence_selected=expected_selected,
            abstained=abstained,
            correct=correct,
        ))

    total = len(evaluation_set.cases)
    return EngineEvaluationReport(
        cases=total,
        correct_rate=correct_cases / total if total else 0.0,
        answerable_cases=answerable,
        answerable_evidence_rate=answerable_with_expected / answerable if answerable else 0.0,
        unsupported_cases=unsupported,
        negative_abstention_accuracy=true_abstentions / unsupported if unsupported else None,
        false_support_rate=false_supports / unsupported if unsupported else None,
        outcomes=tuple(outcomes),
    )


def combine_engine_evaluations(
    reports: Sequence[tuple[str, EngineEvaluationReport]],
) -> EngineEvaluationReport:
    """Pool reviewed per-document engine results without averaging document rates."""
    if not reports or any(not source_id for source_id, _ in reports):
        raise ValueError("At least one named source evaluation is required")
    source_ids = [source_id for source_id, _ in reports]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Evaluation source IDs must be unique")

    outcomes = tuple(
        EngineCaseOutcome(
            case_id=f"{source_id}/{outcome.case_id}",
            language=outcome.language,
            status=outcome.status,
            answerable=outcome.answerable,
            expected_evidence_selected=outcome.expected_evidence_selected,
            abstained=outcome.abstained,
            correct=outcome.correct,
        )
        for source_id, report in reports
        for outcome in report.outcomes
    )
    total = len(outcomes)
    answerable = [outcome for outcome in outcomes if outcome.answerable]
    unsupported = [outcome for outcome in outcomes if not outcome.answerable]
    return EngineEvaluationReport(
        cases=total,
        correct_rate=sum(outcome.correct for outcome in outcomes) / total if total else 0.0,
        answerable_cases=len(answerable),
        answerable_evidence_rate=(
            sum(outcome.expected_evidence_selected for outcome in answerable) / len(answerable)
            if answerable else 0.0
        ),
        unsupported_cases=len(unsupported),
        negative_abstention_accuracy=(
            sum(outcome.abstained for outcome in unsupported) / len(unsupported)
            if unsupported else None
        ),
        false_support_rate=(
            sum(not outcome.abstained for outcome in unsupported) / len(unsupported)
            if unsupported else None
        ),
        outcomes=outcomes,
    )


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


def verify_active_evaluation_source(
    evaluation_set: EvaluationSet,
    connection: psycopg.Connection,
) -> str:
    """Fail closed unless the approved PDF and all answer keys exist in the active KB."""
    _require_reader(connection)
    try:
        row = connection.execute(
            """SELECT g.id, d.id, d.sha256, d.extraction_version,
                      d.processing_config_hash, g.config_hash
               FROM ai.kb_active AS a
               JOIN ai.kb_generations AS g ON g.id = a.generation_id
               JOIN ai.kb_generation_documents AS m ON m.generation_id = g.id
               JOIN ai.documents AS d ON d.id = m.document_id
               JOIN ai.sources AS s ON s.id = m.source_id
               WHERE s.source_key = %s""",
            (evaluation_set.source_id,),
        ).fetchone()
        if row is None or row[2:4] != (
            evaluation_set.document_sha256,
            evaluation_set.extraction_version,
        ) or row[4] != row[5]:
            raise EvaluationEnvironmentError("Active corpus does not match approved evaluation version")
        hashes = [item[0] for item in connection.execute(
            "SELECT content_sha256 FROM ai.document_chunks WHERE document_id = %s",
            (row[1],),
        ).fetchall()]
    except psycopg.Error:
        raise EvaluationEnvironmentError("Active corpus verification failed") from None
    expected = {digest for case in evaluation_set.cases for digest in case.expected_passage_sha256}
    if any(hashes.count(digest) != 1 for digest in expected):
        raise EvaluationEnvironmentError("Approved passage key is missing or ambiguous in active corpus")
    return str(row[0])


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
        (f"Documento revisado por {evaluation_set.document_reviewed_by} el "
         f"{evaluation_set.document_reviewed_at}."
         if evaluation_set.document_reviewed_by and evaluation_set.document_reviewed_at
         else "Este documento es una ayuda de revisión; la aprobación documental está pendiente."),
        f"Fuente: {source_title} — {source_url}",
        f"PDF SHA-256: `{document.sha256}`",
        f"ID de fuente: `{evaluation_set.source_id}`",
        f"Extracción: `{document.extraction_version}`",
        ("Las citas y expectativas se cotejaron con las páginas del PDF original."
         if evaluation_set.document_reviewed_by and evaluation_set.document_reviewed_at
         else "Compara cada cita con la página del PDF original antes de aprobarla."),
    ]
    if evaluation_set.document_review_notes:
        lines.append(f"Notas de revisión documental: {evaluation_set.document_review_notes}")
    for case in evaluation_set.cases:
        lines.extend([
            "",
            f"## {case.case_id}",
            "",
            f"Pregunta ({case.language}): {case.question}",
            f"Estado actual: `{case.review_status}`",
        ])
        if case.reviewed_by and case.reviewed_at:
            lines.append(f"Revisor: {case.reviewed_by}; fecha: {case.reviewed_at}.")
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
        if case.review_status == "reviewed" and case.reviewed_by and case.reviewed_at:
            if case.expected_passage_sha256:
                lines.extend([
                    "- [x] El texto y la página coinciden con el PDF original.",
                    "- [x] La evidencia responde la pregunta.",
                ])
            else:
                lines.extend([
                    "- [x] El SHA-256 del PDF y la identidad de la fuente coinciden con los artefactos revisados.",
                    "- [x] Se confirmó que este PDF no contiene evidencia para la pregunta.",
                ])
            lines.append(f"Decisión y observaciones del revisor: {case.review_notes or 'Aprobado.'}")
        else:
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


def combine_retrieval_evaluations(
    evaluations: Sequence[tuple[EvaluationSet, Mapping[str, StrategyResult]]],
) -> dict[str, StrategyResult]:
    """Pool per-document retrieval metrics using case counts, not rate averages."""
    if not evaluations:
        raise ValueError("At least one document evaluation is required")
    source_ids = [item.source_id for item, _ in evaluations]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Evaluation source IDs must be unique")
    strategy_names = set(evaluations[0][1])
    if not strategy_names or any(set(results) != strategy_names for _, results in evaluations):
        raise ValueError("Each document must report the same named retrieval strategies")

    combined: dict[str, StrategyResult] = {}
    for strategy in sorted(strategy_names):
        rows: list[tuple[EvaluationCase, CaseOutcome, str]] = []
        for evaluation_set, results in evaluations:
            outcomes = results[strategy].cases
            if len(outcomes) != len(evaluation_set.cases):
                raise ValueError("Retrieval outcome count differs from reviewed cases")
            rows.extend((case, outcome, evaluation_set.source_id)
                        for case, outcome in zip(evaluation_set.cases, outcomes, strict=True))

        answerable = [(case, outcome) for case, outcome, _ in rows if case.expected_passage_sha256]
        negative = [(case, outcome) for case, outcome, _ in rows if not case.expected_passage_sha256]
        hits = [outcome for _, outcome in answerable if outcome.first_expected_rank is not None]
        metrics = EvaluationReport(
            cases=len(rows),
            hit_rate_at_k=len(hits) / len(answerable) if answerable else 0.0,
            mean_reciprocal_rank_at_k=(
                sum(1 / outcome.first_expected_rank for outcome in hits
                    if outcome.first_expected_rank is not None) / len(answerable)
                if answerable else 0.0
            ),
            abstention_accuracy=(
                sum(outcome.abstained for _, outcome in negative) / len(negative)
                if negative else None
            ),
        )
        outcomes = tuple(
            CaseOutcome(
                case_id=f"{source_id}/{outcome.case_id}",
                language=outcome.language,
                first_expected_rank=outcome.first_expected_rank,
                returned_count=outcome.returned_count,
                abstained=outcome.abstained,
            )
            for _, outcome, source_id in rows
        )
        combined[strategy] = StrategyResult(metrics=metrics, cases=outcomes)
    return combined


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
