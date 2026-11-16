"""Cross-module wire examples and scientific integrity boundaries."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pyrogravity_ai.schemas.contracts import AiQueryRequest, AiResponse, ChartSpec, ScientificResult


EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "v1"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.example.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", [AiQueryRequest, ScientificResult, ChartSpec, AiResponse])
def test_versioned_examples_round_trip(model) -> None:
    payload = example(model.__name__)
    assert json.loads(model.model_validate(payload).model_dump_json()) == payload


def test_unknown_fields_and_version_are_rejected() -> None:
    payload = example("AiQueryRequest")
    payload["sql"] = "SELECT * FROM scientific.measurements"
    with pytest.raises(ValidationError):
        AiQueryRequest.model_validate(payload)
    payload.pop("sql")
    payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        AiQueryRequest.model_validate(payload)


def test_filters_follow_current_scientific_catalog_capabilities() -> None:
    payload = example("AiQueryRequest")
    payload["filters"] = {"pi": "example"}
    with pytest.raises(ValidationError):
        AiQueryRequest.model_validate(payload)
    payload["analysis_id"] = "bass-ii"
    assert AiQueryRequest.model_validate(payload).filters == {"pi": "example"}


def test_scientific_datum_requires_real_locator_and_finite_value() -> None:
    payload = example("ScientificResult")
    for change in ({"source_record": None}, {"column_ordinal": None}, {"value": "NaN"},
                   {"validation_status": "provisional"}):
        bad = copy.deepcopy(payload)
        bad["data"][0].update(change)
        with pytest.raises(ValidationError):
            ScientificResult.model_validate(bad)
    payload["data"][0]["dataset_ref_id"] = "missing"
    with pytest.raises(ValidationError):
        ScientificResult.model_validate(payload)


def test_chart_requires_units_and_time_for_line() -> None:
    payload = example("ChartSpec")
    payload["y"]["unit"] = None
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(payload)
    payload = example("ChartSpec")
    payload["type"] = "line"
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(payload)
    payload = example("ChartSpec")
    payload["data_ref"] = "SELECT * FROM scientific.records"
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(payload)


def test_claim_and_chart_must_reference_supplied_evidence() -> None:
    payload = example("AiResponse")
    payload["claims"][0]["evidence_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        AiResponse.model_validate(payload)
    payload = example("AiResponse")
    payload["visualizations"][0]["dataset_ref_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        AiResponse.model_validate(payload)


def test_unavailable_response_cannot_assert_facts_or_show_charts() -> None:
    payload = example("AiResponse")
    payload["status"] = "upstream_unavailable"
    with pytest.raises(ValidationError):
        AiResponse.model_validate(payload)


def test_document_evidence_can_ground_a_claim_without_chart() -> None:
    payload = example("AiResponse")
    payload["intent"] = "document_question"
    payload["evidence"] = [{
        "kind": "document", "evidence_id": "evidence_1", "source_id": "ntrs:20130014061",
        "document_sha256": "a" * 64, "chunk_sha256": "b" * 64,
        "page_number": 5, "source_url": "https://ntrs.nasa.gov/citations/20130014061", "doi": None,
    }]
    payload["visualizations"] = []
    assert AiResponse.model_validate(payload).evidence[0].page_number == 5


def test_derived_scientific_value_requires_method_and_sample_count() -> None:
    payload = example("ScientificResult")
    datum = payload["data"][0]
    datum.update({"kind": "derived", "source_record": None, "column_ordinal": None,
                  "method": "mean", "sample_count": 12})
    assert ScientificResult.model_validate(payload).data[0].kind == "derived"
    datum["sample_count"] = None
    with pytest.raises(ValidationError):
        ScientificResult.model_validate(payload)
