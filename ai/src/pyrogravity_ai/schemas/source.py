"""Immutable catalog metadata and artifact identities for scientific sources."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class SourceRecord(BaseModel):
    source_id: str = Field(pattern=r"^ntrs:[0-9]{11}$")
    ntrs_id: str = Field(pattern=r"^[0-9]{11}$")
    title: str = Field(min_length=8)
    authors: list[str] = Field(min_length=1)
    publisher: str = Field(min_length=2)
    publication_date: date
    catalog_url: HttpUrl
    document_url: HttpUrl
    experiment: str = Field(min_length=2)
    report_numbers: list[str] = Field(default_factory=list)
    doi: str | None = None
    document_version: str | None = None
    expected_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_status: Literal["candidate", "catalog_verified", "rejected"]

    @model_validator(mode="after")
    def source_id_matches_ntrs_id(self) -> SourceRecord:
        if self.source_id != f"ntrs:{self.ntrs_id}":
            raise ValueError("source_id must match ntrs_id")
        return self

    @field_validator("doi")
    @classmethod
    def valid_doi_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("10."):
            raise ValueError("doi must start with 10.")
        return value


def load_source(path: Path) -> SourceRecord:
    """Load one curated source record; JSON is kept as reviewable metadata."""
    return SourceRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
