"""Orchestrate the public request without trusting model-authored data."""

from __future__ import annotations

from typing import Any, Callable

from app.application.public_ai_mapper import (
    MapperValidationError,
    map_internal_response,
    map_public_request,
)
from app.infrastructure.internal_ai_client import AiUpstreamError


class PublicAiOrchestrator:
    def __init__(self, scientific_resolver: Any, internal_client: Any, citation_lookup: Callable):
        self.scientific_resolver = scientific_resolver
        self.internal_client = internal_client
        self.citation_lookup = citation_lookup

    def query(self, public_request: Any):
        results = self.scientific_resolver.resolve(public_request.experiment_ids, public_request.variables)
        try:
            internal_request = map_public_request(public_request, scientific_results=results)
        except (MapperValidationError, ValueError) as error:
            raise PublicAiOrchestrationError("invalid_request", 422, str(error)) from error
        try:
            internal_response = self.internal_client.query(internal_request)
        except AiUpstreamError as error:
            raise PublicAiOrchestrationError(error.code, 504 if error.code == "timeout" else 503) from error
        try:
            mapped = map_internal_response(
                internal_request,
                internal_response,
                provenance="live",
                citation_lookup=self.citation_lookup,
            )
            if public_request.chart_preference:
                for chart in mapped.charts:
                    chart.type = public_request.chart_preference
            return mapped
        except (MapperValidationError, ValueError, KeyError, TypeError) as error:
            raise PublicAiOrchestrationError("AI_UNGROUNDED_RESPONSE", 502) from error
        except RuntimeError:
            raise PublicAiOrchestrationError("upstream_unavailable", 503) from None


class PublicAiOrchestrationError(RuntimeError):
    def __init__(self, code: str, status_code: int, message: str | None = None):
        self.code = code
        self.status_code = status_code
        self.message = message or "La solicitud no pudo completarse de forma segura."
        super().__init__(self.message)
