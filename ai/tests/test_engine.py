"""Grounding checks for the isolated AI engine."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from pyrogravity_ai.core.engine import (
    AiEngine,
    CohereEvidenceSelector,
    CohereIntentClassifier,
    EvidenceError,
    route,
)
from pyrogravity_ai.retrieval.postgres import PassageHit
from pyrogravity_ai.schemas.contracts_v11 import AiQueryRequest

EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "v1_1" / "AiQueryRequest.example.json"


def request(**changes: object) -> AiQueryRequest:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload.update(changes)
    return AiQueryRequest.model_validate(payload)


def passage(text: str = "Flames in microgravity can be spherical.") -> PassageHit:
    return PassageHit(
        passage_id=UUID("21e21011-946a-4f8c-97d7-ff947329ba53"),
        document_id=UUID("a0a61f5d-a563-4805-994b-c9eca2619afb"),
        document_sha256="b" * 64,
        page_number=3,
        passage_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        passage_text=text,
        extraction_version="test-v1",
        source_id="nasa:test",
        source_title="Test source",
        source_url="https://ntrs.nasa.gov/citations/test",
        score=1.0,
    )


class FakeRetriever:
    def __init__(self, hits: tuple[PassageHit, ...] = ()) -> None:
        self.hits = hits
        self.calls = 0

    def retrieve(self, question: str, *, limit: int, source_ids: tuple[str, ...] = ()) -> tuple[PassageHit, ...]:
        self.calls += 1
        self.lookup = (question, source_ids)
        assert 1 <= limit <= 8 and question
        return tuple(hit for hit in self.hits if not source_ids or hit.source_id in source_ids)


class FakeSelector:
    def __init__(self, kinds: tuple[str, ...] = ("numeric", "conceptual")) -> None:
        self.kinds = kinds

    def select(self, question: str, candidates: tuple) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in candidates if item.kind in self.kinds)[:4]


def test_numeric_answer_uses_only_supplied_datum_and_authorized_chart() -> None:
    retriever = FakeRetriever()
    result = AiEngine(retriever, FakeSelector()).answer(request())
    assert retriever.calls == 0
    assert result.status == "supported"
    assert result.intent == "scientific_analysis"
    assert result.claims[0].kind == "numeric"
    assert "12.5 s" in result.answer
    assert result.evidence[0].datum_id == "datum_1"
    assert [chart.data_ref for chart in result.visualizations] == ["analysis:flex:synthetic_1"]
    assert "Ejemplo sintético" in result.limitations[0]


def test_document_answer_quotes_retrieved_text_exactly() -> None:
    hit = passage()
    retriever = FakeRetriever((hit,))
    query = request(question="Explica la forma de la llama", query_type="concept",
                    experiment_ids=[], scientific_results=[], chart_refs=[])
    result = AiEngine(retriever, FakeSelector()).answer(query)
    assert result.status == "supported" and result.intent == "document_question"
    assert result.claims[0].text == hit.passage_text
    assert result.evidence[0].citation.quote in hit.passage_text
    assert result.visualizations == []


def test_combined_answer_is_partial_when_only_one_evidence_type_exists() -> None:
    query = request(question="Explica el valor registrado", query_type="mixed")
    response = AiEngine(FakeRetriever(), FakeSelector()).answer(query)
    assert response.status == "partially_supported"
    assert all(claim.kind == "numeric" for claim in response.claims)
    assert any("Falta evidencia" in item for item in response.limitations)


@pytest.mark.parametrize("question", [
    "BASS-II", "Estudio BASS-II", "¿Qué investigó BASS-II?", "¿Qué investigo BASS-II?",
    "¿Qué es el estudio BASS-II?", "Investigación BASS-II", "Háblame sobre BASS-II.",
    "  ¿QUÉ SE INVESTIGÓ EN BASS–II?  ", "PSI-25", "Burning and Suppression of Solids - II",
])
def test_document_shorthand_scopes_retrieval_and_preserves_citation(question: str) -> None:
    hit = replace(passage("Objectives of the solid-fuel experiment"), source_id="ntrs:20160000593")
    retriever = FakeRetriever((passage(), hit))
    query = request(question=question, query_type=None, experiment_ids=[], scientific_results=[], chart_refs=[])
    result = AiEngine(retriever, FakeSelector()).answer(query)
    assert retriever.lookup == (
        "What were the main objectives of the BASS-II investigation?", ("ntrs:20160000593",),
    )
    assert result.status == "supported"
    assert [item.citation.source_id for item in result.evidence] == ["ntrs:20160000593"]


@pytest.mark.parametrize(("question", "expected"), [
    ("Resultados de BASS-II", "main findings and conclusions"),
    ("¿Qué descubrieron en BASS-II?", "main findings and conclusions"),
    ("Metodología de BASS-II", "apparatus and procedures"),
    ("¿Cómo hicieron la investigación BASS-II?", "apparatus and procedures"),
    ("Fuentes de BASS-II", "publication documents"),
    ("¿De dónde salen los datos de BASS-II?", "publication documents"),
    ("¿Quién realizó el estudio BASS-II?", "named authors or institutions"),
])
def test_document_intent_uses_requested_facet(question: str, expected: str) -> None:
    retriever = FakeRetriever()
    query = request(question=question, query_type=None, experiment_ids=[], scientific_results=[], chart_refs=[])
    AiEngine(retriever, FakeSelector()).answer(query)
    assert expected in retriever.lookup[0]
    assert retriever.lookup[1] == ("ntrs:20160000593",)


def test_specific_premise_is_preserved_and_other_sources_cannot_answer() -> None:
    question = "Explica el resultado de los ensayos de combustión de antimateria de BASS-II."
    retriever = FakeRetriever((replace(passage(), source_id="ntrs:20130014061"),))
    query = request(question=question, query_type=None, experiment_ids=[], scientific_results=[], chart_refs=[])
    result = AiEngine(retriever, FakeSelector()).answer(query)
    assert retriever.lookup == (question, ("ntrs:20160000593",))
    assert result.status == "insufficient_evidence"
    assert not result.evidence


def test_ambiguous_document_question_asks_for_study() -> None:
    retriever = FakeRetriever((passage(),))
    query = request(question="¿Qué investigaron?", query_type=None, experiment_ids=[],
                    scientific_results=[], chart_refs=[])
    result = AiEngine(retriever, FakeSelector()).answer(query)
    assert retriever.calls == 0
    assert result.status == "insufficient_evidence"
    assert "nombre o código" in result.answer


def test_numeric_question_without_selected_trials_abstains() -> None:
    query = request(experiment_ids=[], scientific_results=[], chart_refs=[])
    response = AiEngine(FakeRetriever((passage(),)), FakeSelector()).answer(query)
    assert response.status == "insufficient_evidence"
    assert response.claims == [] and response.evidence == []


def test_documentary_question_with_numeric_vocabulary_uses_reviewed_passages() -> None:
    query = request(question="Explícame por qué se estudia la presión", query_type=None,
                    experiment_ids=[], scientific_results=[], chart_refs=[])
    result = AiEngine(FakeRetriever((passage(),)), FakeSelector()).answer(query)
    assert result.intent == "document_question"
    assert result.status == "supported"


def test_exact_row_without_scientific_context_still_abstains() -> None:
    query = request(question="Explícame el valor exacto de presión en la fila 4", query_type=None,
                    experiment_ids=[], scientific_results=[], chart_refs=[])
    retriever = FakeRetriever((passage(),))
    result = AiEngine(retriever, FakeSelector()).answer(query)
    assert result.status == "insufficient_evidence"
    assert retriever.calls == 0


def test_unknown_intent_can_still_retrieve_evidence_about_microgravity() -> None:
    class UnknownIntent:
        def classify(self, question, *, scientific_available):
            return "unknown"

    query = request(question="Llamas en microgravedad", query_type=None,
                    experiment_ids=[], scientific_results=[], chart_refs=[])
    result = AiEngine(FakeRetriever((passage(),)), FakeSelector(), classifier=UnknownIntent()).answer(query)
    assert result.intent == "document_question"
    assert result.status == "supported"


def test_passage_hash_mismatch_fails_closed() -> None:
    hit = passage()
    altered = copy.copy(hit)
    object.__setattr__(altered, "passage_text", "altered")
    query = request(question="Explica la llama", query_type="concept",
                    experiment_ids=[], scientific_results=[], chart_refs=[])
    with pytest.raises(EvidenceError, match="hash mismatch"):
        AiEngine(FakeRetriever((altered,)), FakeSelector()).answer(query)


def test_unauthorized_model_choice_fails_closed() -> None:
    class MaliciousSelector:
        def select(self, question: str, candidates: tuple) -> tuple[str, ...]:
            return ("doc_invented",)

    with pytest.raises(EvidenceError, match="invalid evidence"):
        AiEngine(FakeRetriever(), MaliciousSelector()).answer(request())


def test_cohere_selection_requires_exact_json_shape() -> None:
    class TextClient:
        def __init__(self, output: str) -> None:
            self.output = output

        def generate(self, prompt: str) -> str:
            assert "untrusted data" in prompt
            return self.output

    selector = CohereEvidenceSelector(TextClient('{"selected_ids":[]}'))
    assert selector.select("question", ()) == ()
    assert CohereEvidenceSelector(TextClient('```json\n{"selected_ids":[]}\n```')).select("q", ()) == ()
    with pytest.raises(EvidenceError, match="shape"):
        CohereEvidenceSelector(TextClient('{"selected_ids":[],"answer":"fake"}')).select("q", ())


def test_rules_first_and_classifier_for_ambiguous_question() -> None:
    class TextClient:
        def generate(self, prompt: str) -> str:
            return "document_question"

    query = request(question="¿Qué sucede aquí?", query_type=None)
    assert route(query, CohereIntentClassifier(TextClient())) == "document_question"
    assert route(request(query_type="exact_value"), CohereIntentClassifier(TextClient())) == "scientific_analysis"
