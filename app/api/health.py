import psycopg
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.core.settings import Settings, get_settings

router = APIRouter()

@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    database = "demo"
    if not settings.demo_mode:
        try:
            with psycopg.connect(settings.pyrogravity_database_url.get_secret_value(), connect_timeout=5,
                                 options="-c default_transaction_read_only=on -c statement_timeout=5000") as conn:
                conn.execute("SELECT dataset_id FROM scientific.datasets LIMIT 1").fetchone()
            database = "ok"
        except (psycopg.Error, ValueError):
            database = "unavailable"
    return JSONResponse(status_code=503 if database == "unavailable" else 200, content={
        "api": "ok", "scientific_database": database, "ai_engine": "demo" if settings.demo_mode else "not_configured",
        "retriever": "demo" if settings.demo_mode else "not_configured", "mode": "demo" if settings.demo_mode else "real"})
