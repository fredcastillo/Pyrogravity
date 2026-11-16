"""Evaluate answer selection and abstention against the active reviewed corpus."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

from pyrogravity_ai.config import ConfigurationError
from pyrogravity_ai.database.connection import DatabaseConfigurationError, DatabaseSettings
from pyrogravity_ai.llm.cohere_client import CohereResponseError, CohereServiceError
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingResponseError
from pyrogravity_ai.core.engine import EvidenceError
from pyrogravity_ai.retrieval.evaluation import (
    EvaluationEnvironmentError,
    combine_engine_evaluations,
    evaluate_engine,
    load_evaluation_set,
    verify_active_evaluation_source,
)
from pyrogravity_ai.retrieval.postgres import RetrievalError
from pyrogravity_ai.schemas.contracts_v11 import AiQueryRequest
from pyrogravity_ai.service.app import build_engine


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description="Evaluar selección y abstención del motor AI")
    parser.add_argument("--cases", type=Path, nargs="+", required=True,
                        help="uno o más JSON de casos humanos revisados, uno por documento")
    args = parser.parse_args()

    try:
        evaluation_sets = [load_evaluation_set(path) for path in args.cases]
        if any(any(case.review_status != "reviewed" for case in item.cases)
               for item in evaluation_sets):
            print("Evaluación no disponible: hay casos que siguen como candidatos.", file=sys.stderr)
            return 1
        if len({item.source_id for item in evaluation_sets}) != len(evaluation_sets):
            print("Evaluación no disponible: cada archivo debe representar una fuente distinta.", file=sys.stderr)
            return 1

        database = DatabaseSettings.from_environment()
        url = database.url.get_secret_value()
        sslmode = conninfo_to_dict(url).get("sslmode", "")
        if sslmode not in {"verify-ca", "verify-full"}:
            sslmode = "require"
        with psycopg.connect(
            url,
            connect_timeout=database.connect_timeout_seconds,
            sslmode=sslmode,
            options="-c default_transaction_read_only=on",
            prepare_threshold=None,
        ) as connection:
            generations = {
                item.source_id: verify_active_evaluation_source(item, connection)
                for item in evaluation_sets
            }
            if len(set(generations.values())) != 1:
                raise EvaluationEnvironmentError("Evaluation documents are not in the same active generation")

        engine = build_engine()

        def answer(case):
            request = AiQueryRequest(
                request_id=uuid4(),
                question=case.question,
                language=case.language,
                experiment_ids=[],
                variables=[],
                chart_preference="none",
                query_type="concept",
            )
            return engine.answer(request)

        reports = [(item.source_id, evaluate_engine(item, answer)) for item in evaluation_sets]
        report = combine_engine_evaluations(reports)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        psycopg.Error,
        DatabaseConfigurationError,
        ConfigurationError,
        EvaluationEnvironmentError,
        RetrievalError,
        CohereServiceError,
        CohereResponseError,
        CohereEmbeddingResponseError,
        EvidenceError,
    ) as exc:
        print(f"Evaluación no disponible: {type(exc).__name__}", file=sys.stderr)
        return 1

    result = asdict(report)
    result["generation_id"] = next(iter(generations.values()))
    result["sources"] = {
        source_id: asdict(source_report) for source_id, source_report in reports
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
