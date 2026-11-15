from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    experiment_id: str
    variable: str
    metric: str
    value: Optional[Decimal] = None
    unit: Optional[str] = None
    dataset_id: str
    dataset_version: str
    trial_id: str
    source_row_ref: Optional[int] = None
    source_id: str
    psi_code: Optional[str] = None
    dataset_sha256: Optional[str] = None
    nasa_version: Optional[str] = None
    source_header: Optional[str] = None
    status: Optional[str] = None


class Citation(BaseModel):
    document_id: str
    document_version: str
    passage_id: str
    quote_span: str
    source_id: str


class Claim(BaseModel):
    statement: str
    kind: Literal["numeric", "conceptual"]
    evidence: list[Evidence] = []
    citations: list[Citation] = []


class ChartSeries(BaseModel):
    name: str
    x: list[float]
    y: list[float]
    unit: str


class ChartSpec(BaseModel):
    type: str
    series: list[ChartSeries]
    x_axis: str
    y_axis: str
    x_unit: str
    y_unit: str


class AiQueryRequest(BaseModel):
    query_type: Literal["exact_value", "concept", "comparison", "summary", "mixed"]
    question: Optional[str] = Field(default=None, max_length=500)
    experiment_ids: list[str] = Field(default_factory=list, max_length=5)
    variables: list[str] = Field(default_factory=list)
    want_chart: bool = False
    language: Literal["es", "en"] = "es"


class AiResponse(BaseModel):
    id: str
    status: Literal["ok", "fallback", "insufficient_evidence", "rejected"]
    answer: str
    claims: list[Claim] = []
    chart: Optional[ChartSpec] = None
    limitations: list[str] = []
    confidence: Literal["low", "medium", "high"] = "low"
    model: str
    data_version: str
    corpus_version: str
    degraded_source: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
