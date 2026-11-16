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
    evaluate_active_kb,
    load_evaluation_set,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Comparar recuperación sobre casos revisados")
    parser.add_argument("--cases", type=Path, required=True, help="JSON con review_status=reviewed")
    parser.add_argument("--config-hash", required=True, help="SHA-256 de la configuración activa")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    try:
        evaluation_set = load_evaluation_set(args.cases)
        if any(case.review_status != "reviewed" for case in evaluation_set.cases):
            print("Evaluación no disponible: los casos siguen como candidatos.", file=sys.stderr)
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
            results = evaluate_active_kb(
                evaluation_set, connection, CohereEmbeddingClient(model_settings),
                args.config_hash, k=args.k,
            )
    except (OSError, json.JSONDecodeError, ValueError, psycopg.Error,
            DatabaseConfigurationError, ConfigurationError,
            EvaluationEnvironmentError, CohereServiceError,
            CohereEmbeddingResponseError) as exc:
        print(f"Evaluación no disponible: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(json.dumps({name: asdict(result) for name, result in results.items()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
