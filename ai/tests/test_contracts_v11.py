"""Interoperability and scientific lineage checks for the v1.1 draft."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pyrogravity_ai.schemas import contracts_v11 as wire
from pyrogravity_ai.schemas.scientific_canonical import (
    dataset_ref_id,
    scientific_data_version,
    scientific_input_set_sha256,
)

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
    first_ref = payload["datasets"][0]["ref_id"]
    second = copy.deepcopy(payload["datasets"][0])
    second.update(sha256="b" * 64)
    second["ref_id"] = dataset_ref_id(second["psi_code"], second["relative_path"], second["sha256"])
    payload["datasets"].append(second)
    payload["data"] = [{
        "kind": "derived", "datum_id": "delta_1", "dataset_ref_ids": [first_ref, second["ref_id"]],
        "variable_code": "co2_delta", "value": "1.5", "unit": "%", "validation_status": "validated",
        "method": "delta", "method_version": "1.0.0", "sample_count": 1,
        "group": "synthetic", "cohort": None, "applied_filters": {},
        "input_cells": [{"dataset_ref_id": first_ref, "source_record": 1, "column_ordinal": 14},
                        {"dataset_ref_id": second["ref_id"], "source_record": 1, "column_ordinal": 15}],
        "input_set_sha256": None,
        "input_set_version": None,
    }]
    payload["data_version"] = scientific_data_version(payload)
    wire.ScientificResult.model_validate(payload)
    payload["data"][0]["input_cells"] = payload["data"][0]["input_cells"][:1]
    with pytest.raises(ValidationError):
        wire.ScientificResult.model_validate(payload)


def test_data_version_is_stable_across_storage_engines_and_order() -> None:
    parquet = example("ScientificResult")
    postgres = copy.deepcopy(parquet)
    postgres["result_id"] = "different_result"
    postgres["source"] = "postgres"
    postgres["datasets"][0]["database_dataset_id"] = 42
    postgres["data"][0]["value"] = "12.5000"
    assert scientific_data_version(postgres) == parquet["data_version"]
    wire.ScientificResult.model_validate(postgres)
    postgres["data"][0]["raw_value"] = "12.50"
    assert scientific_data_version(postgres) != parquet["data_version"]
    with pytest.raises(ValidationError, match="data_version"):
        wire.ScientificResult.model_validate(postgres)


def test_data_version_sorts_datasets_and_data_but_preserves_csv_text() -> None:
    payload = example("ScientificResult")
    second_dataset = copy.deepcopy(payload["datasets"][0])
    second_dataset["sha256"] = "b" * 64
    second_dataset["ref_id"] = dataset_ref_id(
        second_dataset["psi_code"], second_dataset["relative_path"], second_dataset["sha256"]
    )
    payload["datasets"].append(second_dataset)
    second_datum = copy.deepcopy(payload["data"][0])
    second_datum.update(datum_id="datum_2", dataset_ref_id=second_dataset["ref_id"],
                        trial_code="PSI-69:psi-69_flex:2", source_record=2,
                        value="2.00", raw_value=" 2.00 ")
    payload["data"].append(second_datum)
    version = scientific_data_version(payload)
    payload["data_version"] = version
    wire.ScientificResult.model_validate(payload)
    payload["datasets"].reverse()
    payload["data"].reverse()
    assert scientific_data_version(payload) == version
    assert wire.ScientificResult.model_validate(payload).data[0].raw_value == " 2.00 "
    payload["data"][0]["raw_value"] = "2.00"
    assert scientific_data_version(payload) != version


def test_dataset_id_depends_only_on_logical_identity() -> None:
    payload = example("ScientificResult")
    dataset = payload["datasets"][0]
    assert dataset["ref_id"] == dataset_ref_id(
        dataset["psi_code"], dataset["relative_path"], dataset["sha256"]
    )
    dataset["database_dataset_id"] = 7
    wire.ScientificResult.model_validate(payload)
    dataset["ref_id"] = "dataset_7"
    with pytest.raises(ValidationError, match="ref_id must derive"):
        wire.ScientificResult.model_validate(payload)


def test_input_set_hash_preserves_raw_values_and_sorts_cell_identity() -> None:
    dataset = example("ScientificResult")["datasets"][0]
    common = {
        "psi_code": dataset["psi_code"],
        "relative_path": dataset["relative_path"],
        "dataset_sha256": dataset["sha256"],
        "dataset_ref_id": dataset["ref_id"],
        "source_header": "Original header",
        "variable_code": "burn_time",
        "raw_value": " 1.00 ",
        "unit": "s",
        "interpretation_status": "exact",
    }
    first = {**common, "source_record": 1, "column_ordinal": 14, "value": "1.000"}
    second = {**common, "source_record": 2, "column_ordinal": 14,
              "value": "-0.0", "raw_value": " -0.0 "}
    digest = scientific_input_set_sha256([second, first])
    assert digest == scientific_input_set_sha256([
        {**first, "value": "1"}, {**second, "value": "0"}
    ])
    assert digest != scientific_input_set_sha256([{**first, "raw_value": "1.00"}, second])
    with pytest.raises(ValueError, match="duplicate"):
        scientific_input_set_sha256([first, first])


def test_input_set_example_is_an_interoperability_vector() -> None:
    payload = example("ScientificInputSet")
    assert payload["canonicalization_version"] == "scientific-input-set-c14n-v1"
    assert scientific_input_set_sha256(payload["inputs"]) == payload["expected_sha256"]


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
