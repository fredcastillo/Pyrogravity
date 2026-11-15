"""Offline retrieval evaluation with explicit human-reviewed answer keys."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from pyrogravity_ai.ingestion.chunker import DocumentChunk
from pyrogravity_ai.ingestion.loader import LoadedDocument
from pyrogravity_ai.retrieval.postgres import PassageHit


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
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_version: str = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)


@dataclass(frozen=True)
class EvaluationReport:
    cases: int
    hit_rate_at_k: float
    mean_reciprocal_rank_at_k: float
    abstention_accuracy: float | None


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
    by_hash = {chunk.text_sha256: chunk for chunk in chunks}
    ids = [case.case_id for case in evaluation_set.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be unique")
    for case in evaluation_set.cases:
        if len(case.expected_passage_sha256) != len(set(case.expected_passage_sha256)):
            raise ValueError("Expected passage hashes must be unique per case")
        if any(digest not in by_hash for digest in case.expected_passage_sha256):
            raise ValueError("Expected passage is absent from current extraction")
        if case.expected_excerpt is not None and not any(
            case.expected_excerpt in by_hash[digest].text
            for digest in case.expected_passage_sha256
        ):
            raise ValueError("Expected excerpt is absent from expected passages")


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
        if any(hit.document_sha256 != evaluation_set.document_sha256
               or hit.extraction_version != evaluation_set.extraction_version
               for hit in results):
            raise ValueError("Retrieval results belong to a different corpus version")
        if not case.expected_passage_sha256:
            abstentions += 1
            abstentions_correct += int(not results)
            continue
        answerable += 1
        expected = set(case.expected_passage_sha256)
        first_rank = next(
            (rank for rank, hit in enumerate(results, 1) if hit.passage_sha256 in expected),
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
