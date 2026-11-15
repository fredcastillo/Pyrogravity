from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.settings import Settings, get_settings
from app.domain.ai_contract import (
    ApiErrorResponse,
    AiQueryRequest,
    AiResponse,
    ChartData,
)
from app.infrastructure.demo_charts import (
    CHART_ID,
    DEMO_REQUEST_ID,
    load_psi69_chart,
)
from app.infrastructure.demo_factory import DemoInfrastructureFactory


router = APIRouter(prefix="/ai", tags=["ai"])
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])
ERROR_RESPONSES = {
    422: {"model": ApiErrorResponse, "description": "Validation error"},
    502: {"model": ApiErrorResponse, "description": "Ungrounded AI response"},
    503: {"model": ApiErrorResponse, "description": "AI unavailable"},
}


def _run(req, query_type, settings):
    if not settings.demo_mode:
        raise ApiError(
            "AI_UNAVAILABLE",
            "El motor RAG no está conectado.",
            status_code=503,
        )
    request = req.model_copy(update={"query_type": query_type})
    return DemoInfrastructureFactory().ai_engine().answer(request, {})


@router.post("/query", response_model=AiResponse, responses=ERROR_RESPONSES)
def query(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return _run(req, req.query_type, settings)


@router.get(
    "/{request_id}/charts/{chart_id}",
    response_model=ChartData,
    responses={
        404: {
            "model": ApiErrorResponse,
            "description": "Request or chart not found",
        }
    },
)
def get_chart(request_id: str, chart_id: str):
    if request_id != DEMO_REQUEST_ID or chart_id != CHART_ID:
        raise ApiError(
            "CHART_NOT_FOUND",
            "No se encontró el gráfico solicitado.",
            status_code=404,
            details={"request_id": request_id, "chart_id": chart_id},
        )

    chart = load_psi69_chart()
    if chart is None:
        raise ApiError(
            "CHART_NOT_FOUND",
            "No se encontró evidencia fuente válida para el gráfico.",
            status_code=404,
            details={"request_id": request_id, "chart_id": chart_id},
        )
    return chart


@router.post("/analyses/summary", response_model=AiResponse, responses=ERROR_RESPONSES)
@analyses_router.post("/summary", response_model=AiResponse, responses=ERROR_RESPONSES)
def summary(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return _run(req, "summary", settings)


@router.post("/analyses/comparison", response_model=AiResponse, responses=ERROR_RESPONSES)
@analyses_router.post("/comparison", response_model=AiResponse, responses=ERROR_RESPONSES)
def comparison(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return _run(req, "comparison", settings)
