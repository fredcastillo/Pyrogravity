"""Ranking and input safety independent of network services."""

from dataclasses import replace
import hashlib
from uuid import UUID

import pytest

from pyrogravity_ai.retrieval.postgres import (
    PassageHit,
    RetrievalError,
    _hits,
    reciprocal_rank_fusion,
    search_text,
    search_vector,
)


def _hit(number: int, score: float = 0.5) -> PassageHit:
    return PassageHit(
        passage_id=UUID(int=number), document_id=UUID(int=100),
        document_sha256="a" * 64, page_number=number,
        passage_sha256="b" * 64, passage_text=f"evidence {number}",
        extraction_version="pypdf-7.0.0-header-v1", source_id="ntrs:20130014061",
        source_title="NASA paper", source_url="https://ntrs.nasa.gov/citations/20130014061",
        score=score,
    )


def test_fusion_rewards_passages_supported_by_both_rankings() -> None:
    result = reciprocal_rank_fusion(
        (_hit(1), _hit(2)), (_hit(2), _hit(3)), limit=3
    )
    assert [hit.page_number for hit in result] == [2, 1, 3]
    assert result[0].score > result[1].score


def test_fusion_rejects_mismatched_metadata_for_same_passage() -> None:
    with pytest.raises(RetrievalError, match="Conflicting passage"):
        reciprocal_rank_fusion((_hit(1),), (replace(_hit(1), document_sha256="c" * 64),))


def test_bad_queries_and_vectors_are_rejected_before_database_access() -> None:
    with pytest.raises(ValueError, match="query"):
        search_text(None, " ")
    with pytest.raises(ValueError, match="limit"):
        search_text(None, "combustion", limit=0)
    with pytest.raises(ValueError, match="config_hash"):
        search_vector(None, (1.0,) + (0.0,) * 1023, "unversioned")
    with pytest.raises(ValueError, match="query embedding"):
        search_vector(None, (0.0,) * 1024, "a" * 64)


def test_retrieval_rejects_passage_whose_stored_hash_does_not_match_text() -> None:
    hit = _hit(1)
    row = (
        hit.passage_id, hit.document_id, hit.document_sha256, hit.page_number,
        "0" * 64, hit.passage_text, hit.extraction_version, hit.source_id,
        hit.source_title, hit.source_url, hit.score,
    )
    assert hashlib.sha256(hit.passage_text.encode()).hexdigest() != row[4]
    with pytest.raises(RetrievalError, match="passage hash"):
        _hits([row])
