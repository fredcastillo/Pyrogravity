"""Public browser-facing AI contract (v1.1).

This contract deliberately stays separate from Johan's internal AI contract.
The private provider is not enabled, so no internal v1.1 mapper is claimed here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PUBLIC_CONTRACT_VERSION = "public-1.1"


class PublicAiQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=500)
    language: Literal["es", "en"]
    experiment_ids: list[str] = Field(default_factory=list, max_length=5)
    variables: list[str] = Field(default_factory=list)
    chart_preference: Literal["line", "bar", "scatter"] | None = None


class PublicClaim(BaseModel):
    id: str
    text: str
    citation_ids: list[str]


class PublicMeasurement(BaseModel):
    variable: str
    value: float | str
    unit: str
    provenance: Literal["live", "cache", "demo", "degraded"]


class PublicCitation(BaseModel):
    id: str
    kind: Literal["document", "scientific"]
    title: str
    url: str
    page: int | None
    snippet: str
    source: str
    measurement: PublicMeasurement | None = None


class PublicChartPoint(BaseModel):
    x: float | str
    y: float


class PublicChartSeries(BaseModel):
    id: str
    label: str
    unit: str | None
    validated: Literal[True]
    points: list[PublicChartPoint]


class PublicChart(BaseModel):
    id: str
    type: Literal["bar", "line", "scatter"]
    title: str
    x_label: str
    y_label: str
    provenance: Literal["live", "cache", "demo", "degraded"]
    data_ref: str | None
    series: list[PublicChartSeries]
    limitations: list[str]


class PublicAiResponse(BaseModel):
    schema_version: Literal[PUBLIC_CONTRACT_VERSION] = PUBLIC_CONTRACT_VERSION
    id: str
    status: Literal["supported", "partially_supported", "insufficient_evidence"]
    answer: str
    claims: list[PublicClaim]
    citations: list[PublicCitation]
    limitations: list[str]
    charts: list[PublicChart]
    provenance: Literal["live", "cache", "demo", "degraded"]
