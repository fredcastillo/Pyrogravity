"""Trial-scoped scientific evidence must not include unrelated measurements."""

import copy
import json
from pathlib import Path

from pyrogravity_ai.core.engine import AiEngine
from pyrogravity_ai.schemas.contracts_v11 import AiQueryRequest, ScientificResult
from pyrogravity_ai.schemas.scientific_canonical import scientific_data_version
from pyrogravity_ai.schemas.scientific_scope import scope_scientific_result


EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "v1_1"


def _payload() -> dict:
    return json.loads((EXAMPLES / "ScientificResult.example.json").read_text(encoding="utf-8"))


def _result_with_two_trials() -> ScientificResult:
    payload = _payload()
    other = dict(payload["data"][0])
    other.update(datum_id="datum_2", trial_code="PSI-69:psi-69_flex:2",
                 source_record=2, value="8.25", raw_value="8.25")
    payload["data"].append(other)
    payload["data_version"] = scientific_data_version(payload)
    return ScientificResult.model_validate(payload)


def test_public_flex_scope_retains_only_the_requested_cell() -> None:
    original = _result_with_two_trials()
    scoped = scope_scientific_result(original, ["PSI-69:psi-69_flex:1"], ["burn_time"])

    assert [datum.datum_id for datum in scoped.data] == ["datum_1"]
    assert scoped.data_version != original.data_version
    assert scoped.datasets == original.datasets
    assert scoped.limitations == original.limitations
    assert len(original.data) == 2
    request = AiQueryRequest.model_validate({
        "request_id": "b3c0e1a5-b79a-40fb-b28d-69c40be37daf",
        "question": "¿Cuál fue el burn_time del ensayo 1?",
        "language": "es",
        "experiment_ids": ["PSI-69:psi-69_flex:1"],
        "variables": ["burn_time"],
        "chart_preference": "auto",
        "scientific_results": [scoped.model_dump(mode="json")],
    })
    assert request.scientific_results[0] == scoped

    class NoDocuments:
        def retrieve(self, question: str, *, limit: int):
            raise AssertionError("a numeric trial query must not retrieve documents")

    class SelectAvailable:
        def select(self, question: str, candidates: tuple):
            return tuple(item.evidence_id for item in candidates)

    answer = AiEngine(NoDocuments(), SelectAvailable()).answer(request)
    assert answer.status == "supported"
    assert len(answer.claims) == 1
    assert "12.5 s" in answer.answer
    assert "8.25" not in answer.answer


def test_scope_with_no_matching_cell_is_insufficient() -> None:
    scoped = scope_scientific_result(
        _result_with_two_trials(), ["PSI-69:psi-69_flex:3"], ["burn_time"]
    )
    assert scoped.status == "insufficient_evidence"
    assert scoped.data == []
    assert scoped.datasets == []


def test_scope_excludes_aggregates_without_trial_lineage() -> None:
    payload = _payload()
    ref = payload["datasets"][0]["ref_id"]
    payload["data"].extend([
        {
            "kind": "derived", "datum_id": "point_delta", "dataset_ref_ids": [ref],
            "variable_code": "delta", "value": "1.5", "unit": "s",
            "validation_status": "validated", "method": "delta", "method_version": "1.0.0",
            "sample_count": 1, "group": None, "cohort": None, "applied_filters": {},
            "input_cells": [
                {"dataset_ref_id": ref, "source_record": 1, "column_ordinal": 14},
                {"dataset_ref_id": ref, "source_record": 1, "column_ordinal": 15},
            ],
            "input_set_sha256": None, "input_set_version": None,
        },
        {
            "kind": "derived", "datum_id": "cohort_median", "dataset_ref_ids": [ref],
            "variable_code": "burn_time", "value": "10", "unit": "s",
            "validation_status": "validated", "method": "median", "method_version": "1.0.0",
            "sample_count": 256, "group": None, "cohort": None, "applied_filters": {},
            "input_cells": [], "input_set_sha256": "a" * 64,
            "input_set_version": "scientific-input-set-c14n-v1",
        },
    ])
    other_trial = copy.deepcopy(payload["data"][1])
    other_trial["datum_id"] = "point_other"
    for cell in other_trial["input_cells"]:
        cell["source_record"] = 2
    payload["data"].append(other_trial)
    payload["data_version"] = scientific_data_version(payload)
    result = ScientificResult.model_validate(payload)
    scoped = scope_scientific_result(result, ["PSI-69:psi-69_flex:1"])
    assert {datum.datum_id for datum in scoped.data} == {"datum_1", "point_delta"}
    assert scoped.data_version == scientific_data_version(scoped.model_dump(mode="json"))
