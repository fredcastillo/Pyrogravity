from fastapi import APIRouter, Depends
from app.core.settings import get_settings, Settings
from app.domain.ai_contract import AiQueryRequest, AiResponse
from app.infrastructure.demo_factory import DemoInfrastructureFactory


router = APIRouter(prefix="/ai", tags=["ai"])
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])


def _run(req, qt):
    req.query_type = qt
    return DemoInfrastructureFactory().ai_engine().answer(req, {})


@router.post("/query", response_model=AiResponse)
def query(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return DemoInfrastructureFactory().ai_engine().answer(req, {})


# atajos en ambos prefijos
@router.post("/analyses/summary", response_model=AiResponse)
@analyses_router.post("/summary", response_model=AiResponse)
def summary(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return _run(req, "summary")


@router.post("/analyses/comparison", response_model=AiResponse)
@analyses_router.post("/comparison", response_model=AiResponse)
def comparison(req: AiQueryRequest, settings: Settings = Depends(get_settings)):
    return _run(req, "comparison")
