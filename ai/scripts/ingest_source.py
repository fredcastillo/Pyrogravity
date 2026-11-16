"""Prepare a pinned NASA document and optionally persist one exact plan."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

from pyrogravity_ai.config import ConfigurationError, Settings
from pyrogravity_ai.database.ingestion_repository import IngestionPersistenceError, persist_ingestion
from pyrogravity_ai.ingestion.loader import InvalidDocumentError, download_pdf, load_pdf
from pyrogravity_ai.ingestion.plan import IngestionPlanError, prepare_ingestion
from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingClient, CohereEmbeddingResponseError
from pyrogravity_ai.schemas.source import load_source

AI_DIR = Path(__file__).resolve().parents[1]


def _ingest_url() -> str:
    values = {key: value for key, value in dotenv_values(AI_DIR / ".env").items() if value is not None}
    values.update(os.environ)
    url = values.get("AI_INGEST_DATABASE_URL", "").strip()
    if not url.startswith(("postgresql://", "postgres://")):
        raise ConfigurationError("AI_INGEST_DATABASE_URL is required for writes")
    try:
        conninfo_to_dict(url)
    except (psycopg.Error, ValueError):
        raise ConfigurationError("Invalid AI_INGEST_DATABASE_URL") from None
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=AI_DIR / "sources" / "ntrs_20130014061.json")
    parser.add_argument("--apply", action="store_true", help="Write the exact prepared plan")
    parser.add_argument("--expect-plan-hash", help="Required with --apply; copy from a dry run")
    args = parser.parse_args(argv)
    if args.apply and (not args.expect_plan_hash or len(args.expect_plan_hash) != 64):
        parser.error("--apply requires --expect-plan-hash from a dry run")
    try:
        settings = Settings.from_environment()
        source = load_source(args.source)
        document = load_pdf(download_pdf(source, AI_DIR / ".cache"))
        plan = prepare_ingestion(source, document, CohereEmbeddingClient(settings))
        if args.expect_plan_hash and plan.plan_hash != args.expect_plan_hash:
            raise IngestionPlanError("Prepared plan differs from the approved hash")
        print(f"source_id: {source.source_id}")
        print(f"document_sha256: {document.sha256}")
        print(f"chunks: {plan.chunk_count}")
        print(f"config_hash: {plan.config_hash}")
        print(f"plan_hash: {plan.plan_hash}")
        if not args.apply:
            print("database_writes: none")
            return 0
        url = _ingest_url()
        parameters = conninfo_to_dict(url)
        sslmode = parameters.get("sslmode")
        if sslmode not in {"verify-ca", "verify-full"}:
            sslmode = "require"
        with psycopg.connect(url, connect_timeout=10, sslmode=sslmode,
                             options="-c statement_timeout=30000", prepare_threshold=None) as connection:
            result = persist_ingestion(plan, connection)
        print(f"document_id: {result.document_id}")
        print(f"chunks_created: {result.chunks_created}")
        print(f"embeddings_created: {result.embeddings_created}")
        return 0
    except (ConfigurationError, InvalidDocumentError, IngestionPlanError,
            CohereServiceError, CohereEmbeddingResponseError, IngestionPersistenceError,
            psycopg.Error, OSError, ValueError):
        print("Ingestion failed; no database details or credentials are shown.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
