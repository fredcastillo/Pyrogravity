"""Interoperability and scientific lineage checks for the v1.1 draft."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pyrogravity_ai.schemas import contracts_v11 as wire

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "v1_1"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.example.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", [wire.AiQueryRequest, wire.ScientificResult, wire.ChartSpec,
                                   wire.AiResponse, wire.Citation, wire.ErrorEnvelope])
def test_examples_match_models_and_exported_schemas(model) -> None:
    payload = example(model.__name__)
    model.model_validate(payload)
    schema = json.loads((EXAMPLES / f"{model.__name__}.schema.json").read_text(encoding="utf-8"))
    assert schema == model.model_json_schema()


def test_backend_context_and_response_match() -> None:
    wire.validate_response_against_request(
        wire.AiQueryRequest.model_validate(example("AiQueryRequest")),
        wire.AiResponse.model_validate(example("AiResponse")),
    )


def test_no_selected_trials_cannot_supply_or_cite_science() -> None:
    payload = example("AiQueryRequest")
    payload["experiment_ids"] = []
    with pytest.raises(ValidationError):
        wire.AiQueryRequest.model_validate(payload)
    payload["scientific_results"] = []
    payload["chart_refs"] = []
    request = wire.AiQueryRequest.model_validate(payload)
    response_payload = example("AiResponse")
    response_payload["visualizations"] = []
    response = wire.AiResponse.model_validate(response_payload)
    with pytest.raises(ValueError, match="scientific evidence"):
        wire.validate_response_against_request(request, response)


def test_measurement_requires_original_locator_and_unit() -> None:
    for change in ({"unit": None}, {"source_record": 0}, {"trial_code": "PSI-69:psi-69_flex:2"},
                   {"value": "NaN"}, {"interpretation_status": "ambiguous"}):
        payload = example("ScientificResult")
        payload["data"][0].update(change)
        with pytest.raises(ValidationError):
            wire.ScientificResult.model_validate(payload)


def test_derived_values_can_use_multiple_datasets_but_require_lineage() -> None:
    payload = example("ScientificResult")
    second = copy.deepcopy(payload["datasets"][0])
    second.update(ref_id="dataset_2", sha256="b" * 64)
    payload["datasets"].append(second)
    payload["data"] = [{
        "kind": "derived", "datum_id": "delta_1", "dataset_ref_ids": ["dataset_1", "dataset_2"],
        "variable_code": "co2_delta", "value": "1.5", "unit": "%", "validation_status": "validated",
        "method": "delta", "method_version": "1", "sample_count": 1,
        "group": "synthetic", "cohort": None, "applied_filters": {},
        "input_cells": [{"dataset_ref_id": "dataset_1", "source_record": 1, "column_ordinal": 14},
                        {"dataset_ref_id": "dataset_2", "source_record": 1, "column_ordinal": 15}],
        "input_set_sha256": None,
    }]
    wire.ScientificResult.model_validate(payload)
    payload["data"][0]["input_cells"] = payload["data"][0]["input_cells"][:1]
    with pytest.raises(ValidationError):
        wire.ScientificResult.model_validate(payload)


def test_response_rejects_unprovided_chart_and_scientific_result() -> None:
    request = wire.AiQueryRequest.model_validate(example("AiQueryRequest"))
    payload = example("AiResponse")
    payload["visualizations"][0]["data_ref"] = "analysis:flex:invented"
    with pytest.raises(ValueError, match="unauthorized"):
        wire.validate_response_against_request(request, wire.AiResponse.model_validate(payload))
    payload = example("AiResponse")
    payload["evidence"][0]["datum_id"] = "invented"
    with pytest.raises(ValueError, match="not supplied"):
        wire.validate_response_against_request(request, wire.AiResponse.model_validate(payload))


def test_no_fallback_state_and_citation_requires_page_and_quote() -> None:
    payload = example("AiResponse")
    payload["status"] = "fallback"
    with pytest.raises(ValidationError):
        wire.AiResponse.model_validate(payload)
    citation = example("Citation")
    citation.pop("page_number")
    with pytest.raises(ValidationError):
        wire.Citation.model_validate(citation)
