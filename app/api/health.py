from fastapi import APIRouter, Depends
from app.core.settings import Settings, get_settings

router = APIRouter()


@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {
        "api": "ok",
        "supabase": "demo" if settings.demo_mode else "configured",
        "ai_engine": "demo" if settings.demo_mode else "configured",
        "retriever": "demo" if settings.demo_mode else "configured",
        "mode": "demo" if settings.demo_mode else "real",
    }
