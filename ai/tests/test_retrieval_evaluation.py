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
    EvaluationEnvironmentError,
    EvaluationSet,
    combine_engine_evaluations,
    combine_retrieval_evaluations,
    evaluate_engine,
    build_review_packet,
    compare_retrievers,
    evaluate_active_kb,
    evaluate_retrieval,
    load_evaluation_set,
    verify_active_evaluation_source,
    verify_candidate_evidence,
)
from pyrogravity_ai.retrieval.postgres import PassageHit
from pyrogravity_ai.schemas.contracts_v11 import AiResponse, Claim, Citation, DocumentEvidence


def _hit(digest: str, rank: int) -> PassageHit:
    return PassageHit(
        UUID(int=rank), UUID(int=100), "a" * 64, 1, digest, "evidence",
        "extract-v1", "ntrs:20130014061", "NASA", "https://ntrs.nasa.gov", 0.5,
    )


def _engine_response(status: str, digest: str | None, case_index: int) -> AiResponse:
    evidence = []
    claims = []
    if digest is not None:
        evidence_id = f"doc_{case_index}"
        evidence.append(DocumentEvidence(
            evidence_id=evidence_id,
            citation=Citation(
                document_id=UUID(int=100), document_sha256="a" * 64,
                page_number=1, passage_id=UUID(int=case_index + 1),
                passage_sha256=digest, quote="Literal evidence", source_id="nasa:test",
            ),
        ))
        claims.append(Claim(
            claim_id=f"claim_{case_index}", kind="conceptual", text="Literal evidence",
            evidence_ids=[evidence_id],
        ))
    return AiResponse(
        request_id=UUID(int=case_index + 10), status=status,
        intent="document_question", answer="Answer" if claims else "Insufficient evidence",
        claims=claims, evidence=evidence,
    )


def test_metrics_count_hits_rank_and_abstention_separately() -> None:
    cases = EvaluationSet(source_id="ntrs:20130014061", document_sha256="a" * 64,
                          extraction_version="extract-v1", cases=[
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


def test_approved_set_can_be_scored_but_unreviewed_copy_is_blocked() -> None:
    path = Path(__file__).resolve().parents[1] / "evaluations" / "ntrs_20130014061_candidates.json"
    approved = load_evaluation_set(path)
    assert len(approved.cases) == 5
    assert all(case.review_status == "reviewed" for case in approved.cases)
    unreviewed = approved.model_copy(deep=True)
    unreviewed.cases[0].review_status = "candidate"
    with pytest.raises(ValueError, match="human review"):
        evaluate_retrieval(unreviewed, lambda question, k: ())
    with pytest.raises(ValueError, match="human review"):
        evaluate_active_kb(unreviewed, None, None, "a" * 64)


def test_candidate_evidence_must_match_current_extraction() -> None:
    text = "Methanol combustion in microgravity"
    document = LoadedDocument("a" * 64, (PageText(1, text),), len(text), "extract-v1")
    chunks = chunk_document(document)
    digest = hashlib.sha256(text.encode()).hexdigest()
    candidates = EvaluationSet(source_id="ntrs:20130014061", document_sha256=document.sha256,
                               extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="q1", question="What burned?", language="en",
                       expected_passage_sha256=[digest], expected_excerpt="Methanol combustion")
    ])
    verify_candidate_evidence(candidates, document, chunks)
    candidates.cases[0].expected_excerpt = "unrelated observation"
    with pytest.raises(ValueError, match="excerpt"):
        verify_candidate_evidence(candidates, document, chunks)


def test_review_packet_locates_unique_passage_without_approving_it() -> None:
    text = "Methanol combustion in microgravity"
    document = LoadedDocument("a" * 64, (PageText(1, text),), len(text), "extract-v1")
    chunks = chunk_document(document)
    digest = hashlib.sha256(text.encode()).hexdigest()
    candidates = EvaluationSet(source_id="ntrs:20130014061", document_sha256=document.sha256,
                               extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="q1", question="What burned?", language="en",
                       expected_passage_sha256=[digest], expected_excerpt="Methanol combustion"),
        EvaluationCase(case_id="q2", question="What is the pressure?", language="en"),
    ])
    packet = build_review_packet(candidates, document, chunks,
                                 source_title="NASA paper", source_url="https://ntrs.nasa.gov")
    assert "Página PDF: 1; fragmento: 0" in packet
    assert digest in packet
    assert "ningún pasaje" in packet
    assert packet.count("Estado actual: `candidate`") == 2
    assert all(case.review_status == "candidate" for case in candidates.cases)
    with pytest.raises(ValueError, match="ambiguous"):
        verify_candidate_evidence(candidates, document, chunks + chunks)


def test_metrics_count_other_documents_as_distractors() -> None:
    cases = EvaluationSet(source_id="ntrs:20130014061", document_sha256="a" * 64,
                          extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="q1", question="What burned?", language="en",
                       expected_passage_sha256=["b" * 64], review_status="reviewed")
    ])
    wrong_version = replace(_hit("b" * 64, 1), document_sha256="c" * 64)
    report = evaluate_retrieval(cases, lambda question, k: [wrong_version, _hit("b" * 64, 2)])
    assert report.hit_rate_at_k == 1.0
    assert report.mean_reciprocal_rank_at_k == 0.5


def test_strategy_comparison_exposes_language_gaps_and_abstention() -> None:
    cases = EvaluationSet(source_id="ntrs:20130014061", document_sha256="a" * 64,
                          extraction_version="extract-v1", cases=[
        EvaluationCase(case_id="english", question="English question", language="en",
                       expected_passage_sha256=["b" * 64], review_status="reviewed"),
        EvaluationCase(case_id="spanish", question="Spanish question", language="es",
                       expected_passage_sha256=["c" * 64], review_status="reviewed"),
        EvaluationCase(case_id="unsupported", question="Unknown question", language="en",
                       review_status="reviewed"),
    ])
    text_hits = {"English question": [_hit("b" * 64, 1)],
                 "Spanish question": [], "Unknown question": [_hit("d" * 64, 2)]}
    vector_hits = {"English question": [],
                   "Spanish question": [_hit("c" * 64, 3)], "Unknown question": []}
    result = compare_retrievers(cases, {
        "text": lambda question, k: text_hits[question],
        "vector": lambda question, k: vector_hits[question],
    })
    assert result["text"].metrics.hit_rate_at_k == 0.5
    assert result["vector"].metrics.abstention_accuracy == 1.0
    assert result["text"].cases[1].first_expected_rank is None
    assert result["vector"].cases[1].first_expected_rank == 1
    assert not result["text"].cases[2].abstained
    unreviewed = load_evaluation_set(
        Path(__file__).resolve().parents[1] / "evaluations" / "ntrs_20130014061_candidates.json"
    ).model_copy(deep=True)
    unreviewed.cases[0].review_status = "candidate"
    with pytest.raises(ValueError, match="human review"):
        compare_retrievers(unreviewed, {"text": lambda question, k: ()})


def test_full_engine_evaluation_scores_expected_evidence_and_negative_abstention() -> None:
    cases = EvaluationSet(
        source_id="nasa:test", document_sha256="a" * 64, extraction_version="test-v1",
        cases=[
            EvaluationCase(case_id="positive", question="Answerable question", language="en",
                           expected_passage_sha256=["b" * 64], review_status="reviewed"),
            EvaluationCase(case_id="negative-abstain", question="Unsupported question", language="es",
                           review_status="reviewed"),
            EvaluationCase(case_id="negative-guess", question="Another unsupported question", language="en",
                           review_status="reviewed"),
        ],
    )
    responses = {
        "positive": _engine_response("supported", "b" * 64, 1),
        "negative-abstain": _engine_response("insufficient_evidence", None, 2),
        "negative-guess": _engine_response("supported", "c" * 64, 3),
    }
    report = evaluate_engine(cases, lambda case: responses[case.case_id])
    assert report.cases == 3
    assert report.correct_rate == pytest.approx(2 / 3)
    assert report.answerable_evidence_rate == 1.0
    assert report.negative_abstention_accuracy == 0.5
    assert report.false_support_rate == 0.5
    assert [outcome.correct for outcome in report.outcomes] == [True, True, False]


def test_multi_document_engine_metrics_are_pooled_by_case_and_keep_source_identity() -> None:
    def make_set(source_id: str, positive_id: str, negative_id: str) -> EvaluationSet:
        return EvaluationSet(
            source_id=source_id, document_sha256="a" * 64, extraction_version="test-v1",
            cases=[
                EvaluationCase(case_id=positive_id, question=f"Question {positive_id}", language="en",
                               expected_passage_sha256=["b" * 64], review_status="reviewed"),
                EvaluationCase(case_id=negative_id, question=f"Question {negative_id}", language="es",
                               review_status="reviewed"),
            ],
        )

    def response(source_id: str, status: str, digest: str | None, index: int) -> AiResponse:
        result = _engine_response(status, digest, index)
        if digest:
            evidence = result.evidence[0]
            citation = evidence.citation.model_copy(update={"source_id": source_id})
            result = result.model_copy(update={"evidence": [evidence.model_copy(update={"citation": citation})]})
        return result

    first = make_set("ntrs:one", "positive-one", "negative-one")
    second = make_set("ntrs:two", "positive-two", "negative-two")
    first_report = evaluate_engine(first, lambda case: response(
        first.source_id,
        "supported" if case.case_id == "positive-one" else "insufficient_evidence",
        "b" * 64 if case.case_id == "positive-one" else None,
        41 if case.case_id == "positive-one" else 42,
    ))
    second_report = evaluate_engine(second, lambda case: response(
        second.source_id,
        "insufficient_evidence" if case.case_id == "positive-two" else "supported",
        None if case.case_id == "positive-two" else "c" * 64,
        43 if case.case_id == "positive-two" else 44,
    ))

    combined = combine_engine_evaluations([
        (first.source_id, first_report), (second.source_id, second_report),
    ])
    assert combined.cases == 4
    assert combined.correct_rate == pytest.approx(0.5)
    assert combined.answerable_evidence_rate == pytest.approx(0.5)
    assert combined.negative_abstention_accuracy == pytest.approx(0.5)
    assert combined.false_support_rate == pytest.approx(0.5)
    assert combined.outcomes[0].case_id == "ntrs:one/positive-one"
    assert combined.outcomes[2].case_id == "ntrs:two/positive-two"


def test_multi_document_retrieval_metrics_use_pooled_denominators() -> None:
    first = EvaluationSet(
        source_id="ntrs:one", document_sha256="a" * 64, extraction_version="test-v1",
        cases=[
            EvaluationCase(case_id="positive-one", question="Find passage one", language="en",
                           expected_passage_sha256=["b" * 64], review_status="reviewed"),
            EvaluationCase(case_id="negative-one", question="No answer one", language="es",
                           review_status="reviewed"),
        ],
    )
    second = EvaluationSet(
        source_id="ntrs:two", document_sha256="c" * 64, extraction_version="test-v2",
        cases=[
            EvaluationCase(case_id="positive-two", question="Find passage two", language="en",
                           expected_passage_sha256=["e" * 64], review_status="reviewed"),
            EvaluationCase(case_id="negative-two", question="No answer two", language="es",
                           review_status="reviewed"),
        ],
    )
    first_hit = replace(_hit("b" * 64, 1), source_id="ntrs:one", extraction_version="test-v1")
    second_hit = replace(_hit("e" * 64, 2), document_sha256="c" * 64,
                         extraction_version="test-v2", source_id="ntrs:two")
    first_results = compare_retrievers(first, {
        "text": lambda question, _k: (
            [_hit("d" * 64, 3), first_hit] if question == "Find passage one"
            else [_hit("d" * 64, 3)]
        )
    })
    second_results = compare_retrievers(second, {
        "text": lambda question, _k: ([second_hit] if question == "Find passage two" else [])
    })

    combined = combine_retrieval_evaluations([
        (first, first_results), (second, second_results),
    ])
    report = combined["text"]
    assert report.metrics.cases == 4
    assert report.metrics.hit_rate_at_k == 1.0
    assert report.metrics.mean_reciprocal_rank_at_k == pytest.approx(0.75)
    assert report.metrics.abstention_accuracy == pytest.approx(0.5)
    assert report.cases[0].case_id == "ntrs:one/positive-one"
    assert report.cases[2].case_id == "ntrs:two/positive-two"


def test_full_engine_evaluation_requires_human_review() -> None:
    cases = EvaluationSet(
        source_id="nasa:test", document_sha256="a" * 64, extraction_version="test-v1",
        cases=[EvaluationCase(case_id="draft", question="Draft question", language="en")],
    )
    with pytest.raises(ValueError, match="human review"):
        evaluate_engine(cases, lambda _case: _engine_response("insufficient_evidence", None, 1))


def test_full_engine_evaluation_requires_expected_source_identity() -> None:
    cases = EvaluationSet(
        source_id="nasa:test", document_sha256="a" * 64, extraction_version="test-v1",
        cases=[EvaluationCase(case_id="positive", question="Answerable question", language="en",
                              expected_passage_sha256=["b" * 64], review_status="reviewed")],
    )
    response = _engine_response("supported", "b" * 64, 1)
    original = response.evidence[0]
    forged_source = original.citation.model_copy(update={"source_id": "nasa:other"})
    forged_evidence = original.model_copy(update={"citation": forged_source})
    response = response.model_copy(update={"evidence": [forged_evidence]})
    report = evaluate_engine(cases, lambda _case: response)
    assert report.answerable_evidence_rate == 0.0
    assert report.outcomes[0].correct is False


def test_engine_evaluation_requires_the_approved_source_in_active_generation() -> None:
    cases = EvaluationSet(
        source_id="nasa:test", document_sha256="a" * 64, extraction_version="test-v1",
        cases=[EvaluationCase(case_id="q1", question="Answerable question", language="en",
                              expected_passage_sha256=["b" * 64], review_status="reviewed")],
    )

    class ReadOnlyConnection:
        def execute(self, query, params=None):
            if "FROM pg_roles" in query:
                return _Row((False, False))
            if "FROM pg_class" in query:
                return _Row((False,))
            if "FROM ai.kb_active" in query:
                assert params == ("nasa:test",)
                return _Row((UUID(int=200), UUID(int=100), "a" * 64,
                             "test-v1", "c" * 64, "c" * 64))
            if "SELECT content_sha256" in query:
                assert params == (UUID(int=100),)
                return _Rows([("b" * 64,)])
            raise AssertionError("unexpected SQL")

    assert verify_active_evaluation_source(cases, ReadOnlyConnection()) == str(UUID(int=200))

    class WrongVersionConnection(ReadOnlyConnection):
        def execute(self, query, params=None):
            if "FROM ai.kb_active" in query:
                return _Row((UUID(int=200), UUID(int=100), "d" * 64,
                             "test-v1", "c" * 64, "c" * 64))
            return super().execute(query, params)

    with pytest.raises(EvaluationEnvironmentError, match="does not match"):
        verify_active_evaluation_source(cases, WrongVersionConnection())


class _Row:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows
