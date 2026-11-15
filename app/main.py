from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.errors import RequestIdMiddleware, api_error_handler, ApiError
from app.core.settings import get_settings
from app.api.health import router as health_router
from app.api.ai import router as ai_router, analyses_router
from app.api.science import router as science_router

app = FastAPI(title="Flame in Freefall API", version="0.1.0")
settings = get_settings()

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(health_router)
app.include_router(ai_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(science_router, prefix="/api/v1")
