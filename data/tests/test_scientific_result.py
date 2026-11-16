import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from data.src.analysis.scientific_catalog import CatalogError, list_analyses, run_analysis
from data.src.ingestion.nasa_csv import inspect_nasa_csv
from test_scientific_catalog import dataset_dir, etl_outputs

pytest.importorskip("pyrogravity_ai", reason="ScientificResult needs the published v1.1 contract on PYTHONPATH")
from pyrogravity_ai.schemas import contracts_v11 as wire
from pyrogravity_ai.schemas.scientific_canonical import dataset_ref_id, scientific_input_set_sha256

from data.src.analysis.scientific_result import adapt_catalog_result, run_scientific_result


@pytest.fixture(scope="module")
def schema():
    path = Path(wire.__file__).resolve().parents[3] / "contracts/v1_1/ScientificResult.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", [item["analysis_id"] for item in list_analyses()])
def test_fixture_matches_catalog_nasa_sources_and_official_schema(name, dataset_dir, schema):
    path = Path(__file__).with_name("fixtures") / "scientific_result_v11" / f"{name}.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    catalog = run_analysis(name, data_dir=dataset_dir)
    result = adapt_catalog_result(catalog, data_dir=dataset_dir)
    payload = result.model_dump(mode="json")
    schema.validate(payload)
    assert wire.ScientificResult.model_validate(payload) == result
    assert result == run_scientific_result(name, data_dir=dataset_dir)
    assert result.analysis_id == name and result.status == fixture["status"]
    assert result.data_version == fixture["data_version"]
    assert Counter(datum.kind for datum in result.data) == fixture["counts"]
    assert {dataset.table_name: dataset.sha256 for dataset in result.datasets} == fixture["datasets"]
    assert set(catalog["result"]["warnings"]) <= set(result.warnings)
    assert result.limitations

    datasets = {dataset.ref_id: dataset for dataset in result.datasets}
    sources = {ref: inspect_nasa_csv(dataset_dir / dataset.relative_path) for ref, dataset in datasets.items()}
    for ref, dataset in datasets.items():
        assert dataset.source_id == dataset.psi_code and dataset.database_dataset_id is None
        assert sources[ref].sha256 == dataset.sha256
        assert ref == dataset_ref_id(dataset.psi_code, dataset.relative_path, dataset.sha256)

    cells = {}
    for datum in result.data:
        assert datum.validation_status == "validated" and Decimal(datum.value).is_finite()
        if datum.kind == "measurement":
            source = sources[datum.dataset_ref_id]
            row, ordinal = datum.source_record, datum.column_ordinal
            assert datum.interpretation_status == "exact" and datum.unit
            assert datum.source_header == source.header[ordinal - 1]
            assert datum.raw_value == source.rows[row - 1][ordinal - 1]
            cells[datum.dataset_ref_id, row, ordinal] = datum
        else:
            assert datum.method_version == catalog["result"]["method_version"]
            if datum.method == "delta":
                assert datum.sample_count == 1 and len(datum.input_cells) == 2
                assert datum.input_set_sha256 is None and datum.input_set_version is None
            else:
                assert datum.input_set_sha256 and datum.input_set_version == "scientific-input-set-c14n-v1"
    assert len(cells) == fixture["counts"]["measurement"]
    for delta in (datum for datum in result.data if datum.kind == "derived" and datum.method == "delta"):
        initial, final = (cells[ref.dataset_ref_id, ref.source_record, ref.column_ordinal] for ref in delta.input_cells)
        assert initial.trial_code == final.trial_code
        assert initial.column_ordinal < final.column_ordinal
        assert Decimal(final.value) - Decimal(initial.value) == Decimal(delta.value)

    expected = fixture["aggregate"]
    aggregate, = (datum for datum in result.data if datum.kind == "derived" and
                  (datum.variable_code, datum.group, datum.cohort)
                  == (expected["variable_code"], expected["group"], expected["cohort"]))
    for key in ("value", "unit", "method", "sample_count", "input_set_sha256"):
        assert getattr(aggregate, key) == expected[key]
    ref, = aggregate.dataset_ref_ids
    dataset = datasets[ref]
    assert dataset.table_name == expected["table_name"]
    summary = catalog["result"]
    for key in expected["catalog_path"]:
        summary = summary[key]
    source_records = set(summary["source_records"] if "source_records" in summary
                         else [row["source_record"] for row in summary["pairs"]])
    inputs = [
        {"psi_code": dataset.psi_code, "relative_path": dataset.relative_path, "dataset_sha256": dataset.sha256,
         **datum.model_dump(include={"dataset_ref_id", "source_record", "column_ordinal", "source_header",
                                     "variable_code", "value", "raw_value", "unit", "interpretation_status"})}
        for datum in cells.values()
        if datum.dataset_ref_id == ref and datum.source_record in source_records and datum.variable_code in expected["inputs"]
    ]
    assert len(inputs) == aggregate.sample_count * len(expected["inputs"])
    assert aggregate.input_set_sha256 == scientific_input_set_sha256(inputs)


def test_filters_and_statuses(dataset_dir):
    result = run_scientific_result("bass-ii", filters={"pi": " Olson "}, data_dir=dataset_dir)
    assert result.status == "ok" and result.warnings
    assert all(datum.applied_filters == {"pi": "Olson"} for datum in result.data if datum.kind == "derived")
    empty = run_scientific_result("bass-ii", filters={"pi": "Unmatched"}, data_dir=dataset_dir)
    assert empty.status == "insufficient_evidence" and empty.datasets and not empty.data
    with pytest.raises(CatalogError) as error:
        run_scientific_result("spice", filters={"cohort": "available"}, data_dir=dataset_dir)
    assert error.value.code == "unsupported_filter"


def test_quality_conflict_rejects_row_and_aggregates_using_it(dataset_dir):
    catalog = run_analysis("bass-ii", data_dir=dataset_dir)
    first = catalog["result"]["pairs"][0]
    first["quality_flags"].append("initial_co2_outside_sensor_range")
    result = adapt_catalog_result(catalog, data_dir=dataset_dir)
    assert all(datum.source_record != first["source_record"] for datum in result.data if datum.kind == "measurement")
    assert all(datum.group is not None for datum in result.data if datum.kind == "derived" and datum.method == "median")
    assert any("aggregate lacks its complete validated input set" in warning for warning in result.warnings)


def test_count_mismatch_is_a_technical_error(dataset_dir):
    catalog = run_analysis("flex", data_dir=dataset_dir)
    catalog["result"]["valid_pair_count"] -= 1
    with pytest.raises(CatalogError) as error:
        adapt_catalog_result(catalog, data_dir=dataset_dir)
    assert error.value.code == "inconsistent_result"


def test_cfi_g_keeps_outliers_and_termination_limits(dataset_dir):
    result = run_scientific_result("cfi-g", data_dir=dataset_dir)
    assert any("FT does not establish natural extinction" in item for item in result.limitations)
    assert any("No verified row-level codebook" in item for item in result.limitations)
    anomaly_flags = {flag for datum in result.data if datum.kind == "measurement" for flag in datum.anomalies}
    assert {"duration_outlier", "se_note_mentions_intervention_or_limit"} <= anomaly_flags
    assert any(datum.group == "inverse, termination=SE" for datum in result.data if datum.kind == "derived")


def test_spice_keeps_signed_values_and_distinct_duplicate_policies(dataset_dir):
    result = run_scientific_result("spice", data_dir=dataset_dir)
    assert any("no documented row-level smoke-point indicator" in item for item in result.limitations)
    assert any("conservative cohort excludes every member" in item for item in result.limitations)
    assert any(datum.kind == "measurement" and datum.variable_code == "air_rate_cm_s"
               and Decimal(datum.value) < 0 and "negative_air_rate" in datum.anomalies for datum in result.data)
    assert any(datum.kind == "measurement" and datum.variable_code == "fuel_rate_mg_s"
               and datum.value == "0" and "zero_fuel_rate" in datum.anomalies for datum in result.data)
    medians = {datum.cohort: datum for datum in result.data if datum.kind == "derived"
               and datum.variable_code == "air_rate_cm_s_median" and datum.group is None}
    assert {name: datum.sample_count for name, datum in medians.items()} == {"available": 444, "conservative": 387}
    assert medians["available"].input_set_sha256 != medians["conservative"].input_set_sha256
