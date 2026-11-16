from pathlib import Path

import pytest
from pydantic import ValidationError


def test_nasa_manifest_has_verifiable_catalog_identity() -> None:
    from pyrogravity_ai.schemas.source import load_source

    path = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    source = load_source(path)

    assert source.source_id == f"ntrs:{source.ntrs_id}"
    assert source.catalog_url.host == "ntrs.nasa.gov"
    assert source.document_url.host == "ntrs.nasa.gov"
    assert source.experiment == "FLEX"
    assert source.doi is None
    assert source.document_version is None
    assert source.catalog_status == "catalog_verified"


def test_mismatched_ntrs_identity_is_rejected() -> None:
    from pyrogravity_ai.schemas.source import SourceRecord

    path = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_id"] = "ntrs:00000000"
    with pytest.raises(ValidationError, match="source_id"):
        SourceRecord.model_validate(payload)
