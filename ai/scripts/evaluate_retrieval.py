"""Evaluate approved cases against one active private Knowledge Base generation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from pyrogravity_ai.config import ConfigurationError, Settings
from pyrogravity_ai.database.connection import (
    DatabaseConfigurationError,
    DatabaseSettings,
)
from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingClient, CohereEmbeddingResponseError
from pyrogravity_ai.retrieval.evaluation import (
    EvaluationEnvironmentError,
    combine_retrieval_evaluations,
    evaluate_active_kb,
    load_evaluation_set,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Comparar recuperación sobre casos revisados")
    parser.add_argument("--cases", type=Path, nargs="+", required=True,
                        help="uno o más JSON revisados, uno por documento NASA")
    parser.add_argument("--config-hash", required=True, help="SHA-256 de la configuración activa")
    parser.add_argument("--k", type=int, default=5)
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
        ai_dir = Path(__file__).resolve().parents[1]
        db_settings = DatabaseSettings.from_environment(env_file=ai_dir / ".env")
        model_settings = Settings.from_environment(env_file=ai_dir / ".env")
        url = db_settings.url.get_secret_value()
        sslmode = conninfo_to_dict(url).get("sslmode", "")
        if sslmode not in {"verify-ca", "verify-full"}:
            sslmode = "require"
        with psycopg.connect(
            url,
            connect_timeout=db_settings.connect_timeout_seconds,
            sslmode=sslmode,
            options="-c default_transaction_read_only=on",
            prepare_threshold=None,
        ) as connection:
            embedder = CohereEmbeddingClient(model_settings)
            source_results = [
                (evaluation_set, evaluate_active_kb(
                    evaluation_set, connection, embedder, args.config_hash, k=args.k,
                ))
                for evaluation_set in evaluation_sets
            ]
            results = combine_retrieval_evaluations(source_results)
    except (OSError, json.JSONDecodeError, ValueError, psycopg.Error,
            DatabaseConfigurationError, ConfigurationError,
            EvaluationEnvironmentError, CohereServiceError,
            CohereEmbeddingResponseError) as exc:
        print(f"Evaluación no disponible: {type(exc).__name__}", file=sys.stderr)
        return 1

    output = {
        "overall": {name: asdict(result) for name, result in results.items()},
        "sources": {
            evaluation_set.source_id: {
                name: asdict(result) for name, result in source_result.items()
            }
            for evaluation_set, source_result in source_results
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
