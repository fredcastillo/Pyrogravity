"""Limit a validated scientific result to trials authorized by the request."""

from __future__ import annotations

from collections.abc import Collection

from pyrogravity_ai.schemas.contracts_v11 import (
    DerivedDatum,
    MeasurementDatum,
    ScientificResult,
)
from pyrogravity_ai.schemas.scientific_canonical import scientific_data_version


def scope_scientific_result(
    result: ScientificResult,
    experiment_ids: Collection[str],
    variables: Collection[str] = (),
) -> ScientificResult:
    """Return only direct cells and traceable point derivations in the selected scope.

    Aggregate input hashes do not identify individual trials, so aggregates are
    excluded. The new data_version hashes the exact subset sent to the AI service.
    """
    selected_trials = set(experiment_ids)
    selected_variables = set(variables)
    datasets = {item.ref_id: item for item in result.datasets}

    def included(datum: MeasurementDatum | DerivedDatum) -> bool:
        if selected_variables and datum.variable_code not in selected_variables:
            return False
        if isinstance(datum, MeasurementDatum):
            return datum.trial_code in selected_trials
        if datum.sample_count != 1 or not datum.input_cells or datum.input_set_sha256 is not None:
            return False
        if set(datum.dataset_ref_ids) != {cell.dataset_ref_id for cell in datum.input_cells}:
            return False
        return all(
            f"{datasets[cell.dataset_ref_id].psi_code}:"
            f"{datasets[cell.dataset_ref_id].table_name}:{cell.source_record}" in selected_trials
            for cell in datum.input_cells
        )

    selected_data = [datum for datum in result.data if included(datum)]
    used_refs = {
        ref
        for datum in selected_data
        for ref in (
            [datum.dataset_ref_id]
            if isinstance(datum, MeasurementDatum) else datum.dataset_ref_ids
        )
    }
    payload = result.model_dump(mode="json")
    payload["datasets"] = [item for item in payload["datasets"] if item["ref_id"] in used_refs]
    payload["data"] = [datum.model_dump(mode="json") for datum in selected_data]
    payload["status"] = result.status if selected_data else "insufficient_evidence"
    payload["data_version"] = scientific_data_version(payload)
    return ScientificResult.model_validate(payload)
