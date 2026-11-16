"""Authenticated internal API; scientific insufficiency remains an HTTP 200 response."""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pyrogravity_ai.config import Settings
from pyrogravity_ai.core.engine import (
    AiEngine,
    CohereEvidenceSelector,
    CohereIntentClassifier,
    EvidenceError,
)
from pyrogravity_ai.database.connection import DatabaseSettings
from pyrogravity_ai.llm.cohere_client import CohereResponseError, CohereServiceError, CohereTextClient
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingClient, CohereEmbeddingResponseError
from pyrogravity_ai.retrieval.postgres import RetrievalError
from pyrogravity_ai.retrieval.runtime import PostgresPassageRetriever
from pyrogravity_ai.schemas.contracts_v11 import AiQueryRequest, AiResponse, ErrorEnvelope

LOG = logging.getLogger(__name__)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _service_values() -> dict[str, str]:
    values = {key: value for key, value in dotenv_values(ENV_FILE).items() if value is not None}
    values.update(os.environ)
    return values


def build_engine() -> AiEngine:
    """Construct the production engine without using administrator database access."""
    values = _service_values()
    strategy = values.get("AI_RETRIEVAL_STRATEGY", "text")
    settings = Settings.from_environment()
    database = DatabaseSettings.from_environment()
    text = CohereTextClient(settings)
    embedder = CohereEmbeddingClient(settings) if strategy == "hybrid" else None
    retriever = PostgresPassageRetriever(
        database, strategy=strategy, embedder=embedder,
        config_hash=values.get("AI_EMBED_CONFIG_HASH"),
    )
    return AiEngine(retriever, CohereEvidenceSelector(text),
                    classifier=CohereIntentClassifier(text))


def _error(status: int, code: str, message: str, *, retryable: bool = False,
           request_id: UUID | None = None) -> JSONResponse:
    envelope = ErrorEnvelope(request_id=request_id,
                             error={"code": code, "message": message, "retryable": retryable})
    headers = {"X-Request-ID": str(request_id)} if request_id else None
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"), headers=headers)


def create_app(*, engine: AiEngine | None = None, token: str | None = None,
               engine_factory: Callable[[], AiEngine] = build_engine) -> FastAPI:
    """Inject dependencies for tests; require a long private bearer token at runtime."""
    internal_token = token if token is not None else _service_values().get("AI_INTERNAL_TOKEN", "")
    if len(internal_token) < 32:
        raise ValueError("AI_INTERNAL_TOKEN must contain at least 32 characters")
    service = FastAPI(title="Pyrogravity AI internal service", version="1.1", docs_url=None,
                      redoc_url=None, openapi_url=None)

    @service.middleware("http")
    async def require_internal_token(request: Request, call_next):
        started = time.perf_counter()
        if request.url.path == "/internal/v1/ai/query":
            supplied = request.headers.get("authorization", "")
            if not supplied.startswith("Bearer ") or not secrets.compare_digest(
                supplied[7:], internal_token
            ):
                return _error(401, "unauthorized", "Acceso no autorizado.")
        response = await call_next(request)
        if request.url.path == "/internal/v1/ai/query":
            LOG.info("AI query status=%s elapsed_ms=%d", response.status_code,
                     int((time.perf_counter() - started) * 1000))
        return response

    @service.exception_handler(RequestValidationError)
    async def invalid_request(_request, _failure):
        return _error(422, "invalid_request", "La solicitud no cumple el contrato v1.1.")

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @service.post("/internal/v1/ai/query", response_model=AiResponse,
                  responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope},
                             502: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope},
                             504: {"model": ErrorEnvelope}})
    def query(request: AiQueryRequest, response: Response):
        try:
            active_engine = engine if engine is not None else engine_factory()
            result = active_engine.answer(request)
            response.headers["X-Request-ID"] = str(request.request_id)
            return result
        except CohereServiceError as failure:
            if failure.kind == "timeout":
                return _error(504, "timeout", "El proveedor de IA agotó el tiempo de espera.",
                              retryable=True, request_id=request.request_id)
            return _error(503 if failure.retryable else 502, "upstream_unavailable",
                          "El proveedor de IA no está disponible.", retryable=failure.retryable,
                          request_id=request.request_id)
        except (CohereResponseError, CohereEmbeddingResponseError, EvidenceError):
            return _error(502, "upstream_unavailable", "La respuesta del proveedor no pudo validarse.",
                          request_id=request.request_id)
        except RetrievalError:
            return _error(503, "upstream_unavailable", "La base documental no está disponible.",
                          retryable=True, request_id=request.request_id)
        except Exception as failure:
            LOG.error("AI query %s failed: %s", request.request_id, type(failure).__name__)
            return _error(500, "internal_error", "Error interno del servicio de IA.",
                          request_id=request.request_id)

    return service
