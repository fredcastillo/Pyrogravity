from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ai import router as ai_router, analyses_router
from app.api.health import router as health_router
from app.api.science import router as science_router
from app.core.errors import ApiError, RequestIdMiddleware, api_error_handler
from app.core.settings import get_settings


app = FastAPI(title="Flame in Freefall API", version="0.1.0")
settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


async def validation_error_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "La solicitud no cumple el esquema.",
                "details": {"errors": jsonable_encoder(exc.errors())},
                "request_id": request.state.request_id,
            }
        },
    )


app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Served-From", "X-Request-ID"],
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(health_router)
app.include_router(ai_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(science_router, prefix="/api/v1")
