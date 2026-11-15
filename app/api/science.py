"""Read-only adapter for the authoritative scientific catalog."""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.settings import Settings, get_settings
from data.src.analysis.scientific_catalog import CatalogError, list_analyses, run_analysis

router = APIRouter(prefix="/analyses", tags=["science"])

@router.get("")
def catalog():
    return list_analyses()

@router.get("/{analysis_id}")
def analysis(analysis_id: str, pi: str | None = Query(default=None, max_length=120),
             material: str | None = Query(default=None, max_length=240),
             settings: Settings = Depends(get_settings)):
    filters = {key: value for key, value in (("pi", pi), ("material", material)) if value is not None}
    try:
        if settings.demo_mode:
            return run_analysis(analysis_id, filters=filters, data_dir=settings.scientific_data_dir)
        with psycopg.connect(settings.pyrogravity_database_url.get_secret_value(), connect_timeout=5,
                             options="-c default_transaction_read_only=on -c statement_timeout=8000") as conn:
            return run_analysis(analysis_id, source="postgres", connection=conn, filters=filters,
                                data_dir=settings.scientific_data_dir)
    except CatalogError as error:
        status = 404 if error.code == "unknown_analysis" else 422 if "filter" in error.code else 503
        raise HTTPException(status, {"code": error.code, "message": str(error)}) from None
    except (psycopg.Error, ValueError):
        raise HTTPException(503, {"code": "scientific_source_unavailable"}) from None
