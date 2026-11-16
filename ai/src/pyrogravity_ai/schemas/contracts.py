"""Version 1 wire contracts between the backend, AI engine and scientific data."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


SHA256 = r"^[0-9a-f]{64}$"
IDENTIFIER = r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AiQueryRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    question: str = Field(min_length=3, max_length=2000)
    language: Literal["es", "en"] = "es"
    analysis_id: Literal["bass-ii", "flex", "flame-design", "cfi-g", "spice"] | None = None
    filters: dict[str, str | None] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def filters_require_analysis(self) -> AiQueryRequest:
        if self.filters and self.analysis_id is None:
            raise ValueError("filters require analysis_id")
        allowed = {"bass-ii": {"pi", "material"}, "flex": set(), "flame-design": set(),
                   "cfi-g": set(), "spice": set()}
        if self.analysis_id and any(key not in allowed[self.analysis_id] for key in self.filters):
            raise ValueError("unsupported filter for analysis_id")
        if any(not key or not key.isidentifier() or (value is not None and (not value or len(value) > 120))
               for key, value in self.filters.items()):
            raise ValueError("filters contain an invalid name or value")
        return self


class DatasetRef(ContractModel):
    ref_id: str = Field(pattern=IDENTIFIER)
    psi_code: str = Field(pattern=r"^PSI-[0-9]+$")
    relative_path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256)
    nasa_psi_url: HttpUrl
    database_dataset_id: int | None = Field(default=None, ge=1)

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/") or ":" in value:
            raise ValueError("relative_path must be a safe relative POSIX path")
        return value


class ScientificDatum(ContractModel):
    datum_id: str = Field(pattern=IDENTIFIER)
    dataset_ref_id: str = Field(pattern=IDENTIFIER)
    variable_code: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=80)
    validation_status: Literal["validated"]
    kind: Literal["measurement", "derived"]
    source_record: str | None = None
    column_ordinal: int | None = Field(default=None, ge=1)
    method: str | None = Field(default=None, max_length=200)
    sample_count: int | None = Field(default=None, ge=1)

    @field_validator("value")
    @classmethod
    def finite_decimal(cls, value: str) -> str:
        try:
            if not Decimal(value).is_finite():
                raise ValueError("value must be finite")
        except InvalidOperation as error:
            raise ValueError("value must be a decimal string") from error
        return value

    @model_validator(mode="after")
    def provenance_for_kind(self) -> ScientificDatum:
        if self.kind == "measurement" and (not self.source_record or self.column_ordinal is None):
            raise ValueError("measurement requires source_record and column_ordinal")
        if self.kind == "derived" and (not self.method or self.sample_count is None):
            raise ValueError("derived value requires method and sample_count")
        return self


class ScientificResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["ok", "partial", "insufficient_evidence"]
    analysis_id: str = Field(pattern=IDENTIFIER)
    source: Literal["parquet", "postgres"]
    datasets: list[DatasetRef]
    data: list[ScientificDatum]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_exist(self) -> ScientificResult:
        refs = [dataset.ref_id for dataset in self.datasets]
        data_ids = [datum.datum_id for datum in self.data]
        if len(refs) != len(set(refs)) or len(data_ids) != len(set(data_ids)):
            raise ValueError("duplicate dataset or datum ID")
        if any(datum.dataset_ref_id not in refs for datum in self.data):
            raise ValueError("datum references an unknown dataset")
        if self.status == "ok" and not self.data:
            raise ValueError("ok result requires data")
        if self.status == "insufficient_evidence" and self.data:
            raise ValueError("insufficient evidence cannot include data")
        return self


class ChartAxis(ContractModel):
    field: str = Field(pattern=IDENTIFIER)
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["categorical", "numeric", "temporal"]
    unit: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def unit_for_numeric(self) -> ChartAxis:
        if self.kind == "numeric" and not self.unit:
            raise ValueError("numeric axis requires unit")
        return self


class ChartSpec(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    chart_id: str = Field(pattern=IDENTIFIER)
    type: Literal["bar", "line", "scatter", "histogram", "box", "heatmap"]
    title: str = Field(min_length=1, max_length=200)
    data_ref: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9:_-]{0,299}$")
    x: ChartAxis
    y: ChartAxis
    filters: dict[str, str] = Field(default_factory=dict)
    dataset_ref_ids: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_chart(self) -> ChartSpec:
        if self.type == "line" and self.x.kind != "temporal":
            raise ValueError("line chart requires a temporal x axis")
        if len(self.dataset_ref_ids) != len(set(self.dataset_ref_ids)):
            raise ValueError("duplicate dataset reference")
        return self


class DocumentEvidence(ContractModel):
    kind: Literal["document"] = "document"
    evidence_id: str = Field(pattern=IDENTIFIER)
    source_id: str = Field(min_length=1)
    document_sha256: str = Field(pattern=SHA256)
    chunk_sha256: str = Field(pattern=SHA256)
    page_number: int = Field(ge=1)
    source_url: HttpUrl
    doi: str | None = None


class ScientificEvidence(ContractModel):
    kind: Literal["scientific"] = "scientific"
    evidence_id: str = Field(pattern=IDENTIFIER)
    dataset: DatasetRef
    datum: ScientificDatum

    @model_validator(mode="after")
    def matching_dataset(self) -> ScientificEvidence:
        if self.datum.dataset_ref_id != self.dataset.ref_id:
            raise ValueError("datum and dataset reference must match")
        return self


Evidence = Annotated[DocumentEvidence | ScientificEvidence, Field(discriminator="kind")]


class Claim(ContractModel):
    claim_id: str = Field(pattern=IDENTIFIER)
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)


class ResponseMetrics(ContractModel):
    latency_ms: int | None = Field(default=None, ge=0)


class AiResponse(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    status: Literal["supported", "partially_supported", "insufficient_evidence", "invalid_request", "upstream_unavailable"]
    intent: Literal["scientific_analysis", "document_question", "combined", "unknown"]
    answer: str = Field(min_length=1, max_length=10000)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    visualizations: list[ChartSpec] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    metrics: ResponseMetrics = Field(default_factory=ResponseMetrics)

    @model_validator(mode="after")
    def grounded_response(self) -> AiResponse:
        evidence_ids = [item.evidence_id for item in self.evidence]
        claim_ids = [item.claim_id for item in self.claims]
        if len(evidence_ids) != len(set(evidence_ids)) or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate evidence or claim ID")
        if any(eid not in evidence_ids for claim in self.claims for eid in claim.evidence_ids):
            raise ValueError("claim references unknown evidence")
        if self.status == "supported" and not self.claims:
            raise ValueError("supported response requires grounded claims")
        if self.status in {"insufficient_evidence", "invalid_request", "upstream_unavailable"}:
            if self.claims or self.visualizations:
                raise ValueError("unsupported response cannot contain claims or charts")
        chart_ids = [chart.chart_id for chart in self.visualizations]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("duplicate chart ID")
        science_refs = {item.dataset.ref_id for item in self.evidence if isinstance(item, ScientificEvidence)}
        if any(ref not in science_refs for chart in self.visualizations for ref in chart.dataset_ref_ids):
            raise ValueError("chart references a dataset without scientific evidence")
        return self
