"""A candidate answer key cannot silently become an accepted benchmark."""

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from pyrogravity_ai.ingestion.chunker import chunk_document
from pyrogravity_ai.ingestion.loader import LoadedDocument, PageText
from pyrogravity_ai.retrieval.evaluation import (
    EvaluationCase,
    EvaluationSet,
    evaluate_retrieval,
    load_evaluation_set,
    verify_candidate_evidence,
)
from pyrogravity_ai.retrieval.postgres import PassageHit


def _hit(digest: str, rank: int) -> PassageHit:
    return PassageHit(
        UUID(int=rank), UUID(int=100), "a" * 64, 1, digest, "evidence",
        "extract-v1", "ntrs:20130014061", "NASA", "https://ntrs.nasa.gov", 0.5,
    )


def test_metrics_count_hits_rank_and_abstention_separately() -> None:
    cases = EvaluationSet(document_sha256="a" * 64, extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="answerable-hit", question="first question", language="en",
                       expected_passage_sha256=["b" * 64], review_status="reviewed"),
        EvaluationCase(case_id="answerable-miss", question="second question", language="en",
                       expected_passage_sha256=["c" * 64], review_status="reviewed"),
        EvaluationCase(case_id="abstain", question="third question", language="es",
                       review_status="reviewed"),
    ])
    answers = {
        "first question": [_hit("a" * 64, 1), _hit("b" * 64, 2)],
        "second question": [_hit("d" * 64, 3)],
        "third question": [],
    }
    report = evaluate_retrieval(cases, lambda question, k: answers[question], k=2)
    assert report.cases == 3
    assert report.hit_rate_at_k == 0.5
    assert report.mean_reciprocal_rank_at_k == 0.25
    assert report.abstention_accuracy == 1.0


def test_candidate_set_is_blocked_from_reported_metrics() -> None:
    path = Path(__file__).resolve().parents[1] / "evaluations" / "ntrs_20130014061_candidates.json"
    candidates = load_evaluation_set(path)
    assert len(candidates.cases) == 5
    with pytest.raises(ValueError, match="human review"):
        evaluate_retrieval(candidates, lambda question, k: ())


def test_candidate_evidence_must_match_current_extraction() -> None:
    text = "Methanol combustion in microgravity"
    document = LoadedDocument("a" * 64, (PageText(1, text),), len(text), "extract-v1")
    chunks = chunk_document(document)
    digest = hashlib.sha256(text.encode()).hexdigest()
    candidates = EvaluationSet(document_sha256=document.sha256, extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="q1", question="What burned?", language="en",
                       expected_passage_sha256=[digest], expected_excerpt="Methanol combustion")
    ])
    verify_candidate_evidence(candidates, document, chunks)
    candidates.cases[0].expected_excerpt = "unrelated observation"
    with pytest.raises(ValueError, match="excerpt"):
        verify_candidate_evidence(candidates, document, chunks)


def test_metrics_reject_hits_from_a_different_document_version() -> None:
    cases = EvaluationSet(document_sha256="a" * 64, extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="q1", question="What burned?", language="en",
                       expected_passage_sha256=["b" * 64], review_status="reviewed")
    ])
    wrong_version = replace(_hit("b" * 64, 1), document_sha256="c" * 64)
    with pytest.raises(ValueError, match="different corpus version"):
        evaluate_retrieval(cases, lambda question, k: [wrong_version])
