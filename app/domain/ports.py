from typing import Protocol
from app.domain.ai_contract import AiQueryRequest, AiResponse


class AIEngine(Protocol):
    def answer(self, request: AiQueryRequest, context: dict) -> AiResponse: ...


class DocumentRetriever(Protocol):
    def retrieve(self, question: str, k: int = 5) -> list[dict]: ...


class ExperimentReader(Protocol):
    def get(self, experiment_id: str): ...
    def list(self, page_size: int = 100): ...


class MeasurementReader(Protocol):
    def list_by_experiment(self, experiment_id: str, page_size: int = 1000): ...


class StatsReader(Protocol):
    def get_stats(self, experiment_id: str): ...


class AnalysisCache(Protocol):
    def get(self, key: str): ...
    def set(self, key: str, value): ...
