from fastapi import APIRouter, Depends, Request

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
from app.domain.public_ai_contract import PublicAiQueryRequest, PublicAiResponse
from app.application.public_ai_orchestrator import PublicAiOrchestrator, PublicAiOrchestrationError
from app.application.scientific_result_resolver import FlexScientificResultResolver, ScientificSelectionError
from app.infrastructure.citation_passage_reader import CitationPassageReader
from app.infrastructure.internal_ai_client import InternalAiClient


router = APIRouter(prefix="/ai", tags=["ai"])
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])
ERROR_RESPONSES = {
    422: {"model": ApiErrorResponse, "description": "Validation error"},
    502: {"model": ApiErrorResponse, "description": "Ungrounded AI response"},
    503: {"model": ApiErrorResponse, "description": "AI unavailable"},
    504: {"model": ApiErrorResponse, "description": "AI upstream timeout"},
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


@router.post(
    "/query",
    response_model=PublicAiResponse,
    responses={
        422: {"model": ApiErrorResponse, "description": "Invalid public request"},
        502: {"model": ApiErrorResponse, "description": "Ungrounded AI response"},
        503: {"model": ApiErrorResponse, "description": "AI provider disabled or unavailable"},
        504: {"model": ApiErrorResponse, "description": "AI upstream timeout"},
    },
    operation_id="public_ai_query_v1_1",
    include_in_schema=True,
)
def public_query(req: PublicAiQueryRequest, request: Request, settings: Settings = Depends(get_settings)):
    """Public v1.1 entrypoint. The upstream path stays off until the reader role is provisioned."""
    # Bryant's request id is the single trace identifier echoed in the error envelope/header.
    request.state.request_id = req.id
    if not settings.ai_provider_enabled and not req.experiment_ids:
        return PublicAiResponse(
            id=req.id,
            status="insufficient_evidence",
            answer="No hay ensayos seleccionados ni pasajes documentales verificados para responder.",
            claims=[],
            citations=[],
            limitations=["Sin ensayos seleccionados, solo se responde con evidencia documental verificada o evidencia insuficiente."],
            charts=[],
            provenance="demo",
        )
    if not settings.ai_provider_enabled:
        raise ApiError(
            "AI_UNAVAILABLE",
            "El proveedor de IA está desactivado hasta completar autenticación y rol lector.",
            status_code=503,
            details={"schema_version": "public-1.1"},
        )
    request.state.served_from = "live"
    orchestrator = PublicAiOrchestrator(
        FlexScientificResultResolver(settings.scientific_data_dir),
        InternalAiClient(str(settings.ai_internal_url), settings.ai_internal_token.get_secret_value()),
        CitationPassageReader(settings.ai_citation_view_database_url.get_secret_value()).get,
    )
    try:
        return orchestrator.query(req)
    except ScientificSelectionError as error:
        status = 404 if error.code == "EXPERIMENT_NOT_FOUND" else 422 if error.code == "VALIDATION_ERROR" else 503
        request.state.served_from = "degraded" if status >= 500 else "live"
        raise ApiError(error.code, str(error), status_code=status, details={}) from None
    except PublicAiOrchestrationError as error:
        request.state.served_from = "degraded" if error.status_code >= 500 else "live"
        code = error.code
        if code == "invalid_request":
            code = "VALIDATION_ERROR"
        elif code in {"upstream_unavailable", "timeout"}:
            code = "AI_UNAVAILABLE"
        raise ApiError(code, error.message, status_code=error.status_code, details={}) from None


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
