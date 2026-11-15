"""Draft v1.1 wire contracts; v1.0 remains in contracts.py unchanged."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"
DATA_REF = r"^[a-zA-Z][a-zA-Z0-9:_-]{0,299}$"
TRIAL_CODE = r"^PSI-[0-9]+:[a-zA-Z0-9_-]+:[1-9][0-9]*$"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DatasetRef(WireModel):
    ref_id: str = Field(pattern=IDENTIFIER)
    psi_code: str = Field(pattern=r"^PSI-[0-9]+$")
    table_name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    relative_path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256)
    source_id: str = Field(min_length=1, max_length=120)
    source_title: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl
    database_dataset_id: int | None = Field(default=None, ge=1)

    @field_validator("relative_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "\\" in value or ":" in value or ".." in value.split("/"):
            raise ValueError("relative_path must be a safe POSIX relative path")
        return value


class CellRef(WireModel):
    dataset_ref_id: str = Field(pattern=IDENTIFIER)
    source_record: int = Field(ge=1)
    column_ordinal: int = Field(ge=1)


class MeasurementDatum(WireModel):
    kind: Literal["measurement"] = "measurement"
    datum_id: str = Field(pattern=IDENTIFIER)
    dataset_ref_id: str = Field(pattern=IDENTIFIER)
    trial_code: str = Field(pattern=TRIAL_CODE)
    source_record: int = Field(ge=1)
    column_ordinal: int = Field(ge=1)
    source_header: str = Field(min_length=1, max_length=200)
    variable_code: str = Field(min_length=1, max_length=100)
    value: str
    raw_value: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=80)
    interpretation_status: Literal["exact"] = "exact"
    validation_status: Literal["validated"] = "validated"
    anomalies: list[str] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def finite_decimal(cls, value: str) -> str:
        try:
            if not Decimal(value).is_finite():
                raise ValueError("value must be finite")
        except InvalidOperation as error:
            raise ValueError("value must be a decimal string") from error
        return value


class DerivedDatum(WireModel):
    kind: Literal["derived"] = "derived"
    datum_id: str = Field(pattern=IDENTIFIER)
    dataset_ref_ids: list[str] = Field(min_length=1)
    variable_code: str = Field(min_length=1, max_length=100)
    value: str
    unit: str = Field(min_length=1, max_length=80)
    validation_status: Literal["validated"] = "validated"
    method: str = Field(min_length=1, max_length=120)
    method_version: str = Field(min_length=1, max_length=80)
    sample_count: int = Field(ge=1)
    group: str | None = Field(default=None, max_length=120)
    cohort: str | None = Field(default=None, max_length=120)
    applied_filters: dict[str, str] = Field(default_factory=dict)
    input_cells: list[CellRef] = Field(default_factory=list)
    input_set_sha256: str | None = Field(default=None, pattern=SHA256)

    _finite_decimal = field_validator("value")(MeasurementDatum.finite_decimal.__func__)

    @model_validator(mode="after")
    def lineage(self) -> DerivedDatum:
        if len(self.dataset_ref_ids) != len(set(self.dataset_ref_ids)):
            raise ValueError("duplicate dataset reference")
        if not self.input_cells and self.input_set_sha256 is None:
            raise ValueError("derived datum requires cell refs or an input set hash")
        if self.method == "delta" and (len(self.input_cells) != 2 or self.sample_count != 1):
            raise ValueError("delta requires two cells and one paired observation")
        return self


ScientificDatum = Annotated[MeasurementDatum | DerivedDatum, Field(discriminator="kind")]


class ScientificResult(WireModel):
    schema_version: Literal["1.1"] = "1.1"
    result_id: str = Field(pattern=IDENTIFIER)
    data_version: str = Field(pattern=SHA256)
    analysis_id: Literal["bass-ii", "flex", "flame-design", "cfi-g", "spice"]
    status: Literal["ok", "partial", "insufficient_evidence"]
    source: Literal["parquet", "postgres"]
    datasets: list[DatasetRef]
    data: list[ScientificDatum]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_references(self) -> ScientificResult:
        datasets = {item.ref_id: item for item in self.datasets}
        if len(datasets) != len(self.datasets) or len({d.datum_id for d in self.data}) != len(self.data):
            raise ValueError("duplicate dataset or datum ID")
        for datum in self.data:
            refs = [datum.dataset_ref_id] if isinstance(datum, MeasurementDatum) else datum.dataset_ref_ids
            if any(ref not in datasets for ref in refs):
                raise ValueError("datum references unknown dataset")
            if isinstance(datum, MeasurementDatum):
                dataset = datasets[datum.dataset_ref_id]
                if datum.trial_code != f"{dataset.psi_code}:{dataset.table_name}:{datum.source_record}":
                    raise ValueError("trial_code does not match dataset and source_record")
            elif any(cell.dataset_ref_id not in refs for cell in datum.input_cells):
                raise ValueError("input cell references a dataset outside the derived value")
        if (self.status == "insufficient_evidence") != (not self.data):
            raise ValueError("insufficient_evidence must have no data; other states require data")
        return self


class ChartRef(WireModel):
    data_ref: str = Field(pattern=DATA_REF)
    label: str = Field(min_length=1, max_length=120)
    variable: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=80)
    trial_codes: list[str] = Field(default_factory=list)

    @field_validator("trial_codes")
    @classmethod
    def valid_trial_codes(cls, values: list[str]) -> list[str]:
        import re
        if len(values) != len(set(values)) or any(re.fullmatch(TRIAL_CODE, value) is None for value in values):
            raise ValueError("invalid or duplicate trial_code")
        return values


class AiQueryRequest(WireModel):
    schema_version: Literal["1.1"] = "1.1"
    request_id: UUID
    question: str = Field(min_length=3, max_length=2000)
    language: Literal["es", "en"] = "es"
    analysis_id: Literal["bass-ii", "flex", "flame-design", "cfi-g", "spice"] | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    experiment_ids: list[str] = Field(default_factory=list, max_length=5)
    variables: list[str] = Field(default_factory=list)
    chart_preference: Literal["none", "auto", "required"] = "auto"
    query_type: Literal["exact_value", "concept", "comparison", "summary", "mixed"] | None = None
    scientific_results: list[ScientificResult] = Field(default_factory=list)
    chart_refs: list[ChartRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_scope(self) -> AiQueryRequest:
        if self.filters and self.analysis_id != "bass-ii":
            raise ValueError("only bass-ii accepts input filters")
        if any(key not in {"pi", "material"} for key in self.filters):
            raise ValueError("unsupported input filter")
        if len(self.experiment_ids) != len(set(self.experiment_ids)):
            raise ValueError("duplicate experiment_id")
        if not self.experiment_ids and (self.scientific_results or self.chart_refs):
            raise ValueError("no scientific context without selected trials")
        if len({ref.data_ref for ref in self.chart_refs}) != len(self.chart_refs):
            raise ValueError("duplicate chart data_ref")
        if self.chart_preference == "none" and self.chart_refs:
            raise ValueError("chart_refs supplied while charts are disabled")
        selected = set(self.experiment_ids)
        if any(isinstance(datum, MeasurementDatum) and datum.trial_code not in selected
               for result in self.scientific_results for datum in result.data):
            raise ValueError("scientific context includes an unselected trial")
        if any(code not in selected for ref in self.chart_refs for code in ref.trial_codes):
            raise ValueError("chart_ref includes an unselected trial")
        return self


class Citation(WireModel):
    document_id: UUID
    document_sha256: str = Field(pattern=SHA256)
    page_number: int = Field(ge=1)
    passage_id: UUID
    passage_sha256: str = Field(pattern=SHA256)
    quote: str = Field(min_length=1, max_length=1500)
    source_id: str = Field(min_length=1, max_length=120)


class DocumentEvidence(WireModel):
    kind: Literal["document"] = "document"
    evidence_id: str = Field(pattern=IDENTIFIER)
    citation: Citation


class ScientificEvidence(WireModel):
    kind: Literal["scientific"] = "scientific"
    evidence_id: str = Field(pattern=IDENTIFIER)
    result_id: str = Field(pattern=IDENTIFIER)
    datum_id: str = Field(pattern=IDENTIFIER)


Evidence = Annotated[DocumentEvidence | ScientificEvidence, Field(discriminator="kind")]


class Claim(WireModel):
    claim_id: str = Field(pattern=IDENTIFIER)
    kind: Literal["numeric", "conceptual"]
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)


class ChartSpec(WireModel):
    chart_id: str = Field(pattern=IDENTIFIER)
    type: Literal["bar", "line", "scatter", "histogram", "box", "heatmap"]
    title: str = Field(min_length=1, max_length=200)
    data_ref: str = Field(pattern=DATA_REF)
    x_field: str = Field(pattern=IDENTIFIER)
    y_field: str = Field(pattern=IDENTIFIER)
    y_unit: str = Field(min_length=1, max_length=80)


class AiResponse(WireModel):
    schema_version: Literal["1.1"] = "1.1"
    request_id: UUID
    status: Literal["supported", "partially_supported", "insufficient_evidence"]
    intent: Literal["scientific_analysis", "document_question", "combined", "unknown"]
    answer: str = Field(min_length=1, max_length=10000)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    visualizations: list[ChartSpec] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def grounded(self) -> AiResponse:
        by_id = {item.evidence_id: item for item in self.evidence}
        ids = set(by_id)
        if len(ids) != len(self.evidence) or any(ref not in ids for claim in self.claims for ref in claim.evidence_ids):
            raise ValueError("duplicate or missing evidence ID")
        if self.status != "insufficient_evidence" and not self.claims:
            raise ValueError("supported response requires claims")
        if any(claim.kind == "numeric" and not any(isinstance(by_id[ref], ScientificEvidence)
               for ref in claim.evidence_ids) for claim in self.claims):
            raise ValueError("numeric claim requires scientific evidence")
        if self.status == "insufficient_evidence" and (self.claims or self.evidence or self.visualizations):
            raise ValueError("insufficient evidence cannot assert claims or charts")
        return self


class ErrorDetail(WireModel):
    code: Literal["invalid_request", "unauthorized", "forbidden", "rate_limited", "upstream_unavailable", "timeout", "internal_error"]
    message: str = Field(min_length=1, max_length=300)
    retryable: bool


class ErrorEnvelope(WireModel):
    schema_version: Literal["1.1"] = "1.1"
    request_id: UUID | None = None
    error: ErrorDetail


def validate_response_against_request(request: AiQueryRequest, response: AiResponse) -> None:
    """Cross-message checks that JSON Schema alone cannot express."""
    if response.request_id != request.request_id:
        raise ValueError("response request_id differs")
    allowed_refs = {ref.data_ref: ref for ref in request.chart_refs}
    for chart in response.visualizations:
        ref = allowed_refs.get(chart.data_ref)
        if ref is None or request.chart_preference == "none" or chart.y_unit != ref.unit or chart.y_field != ref.variable:
            raise ValueError("chart uses an unauthorized or mismatched data_ref")
    allowed_data = {(result.result_id, datum.datum_id) for result in request.scientific_results for datum in result.data}
    for item in response.evidence:
        if isinstance(item, ScientificEvidence) and (item.result_id, item.datum_id) not in allowed_data:
            raise ValueError("scientific evidence was not supplied by backend")
    if not request.experiment_ids and any(isinstance(item, ScientificEvidence) for item in response.evidence):
        raise ValueError("scientific evidence without selected trials")
