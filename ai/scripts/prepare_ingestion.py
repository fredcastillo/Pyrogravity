"""Prepare and validate a pinned NASA PDF with Cohere, without database writes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyrogravity_ai.config import ConfigurationError, Settings
from pyrogravity_ai.ingestion.loader import InvalidDocumentError, download_pdf, load_pdf
from pyrogravity_ai.ingestion.plan import IngestionPlanError, prepare_ingestion
from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingClient, CohereEmbeddingResponseError
from pyrogravity_ai.schemas.source import load_source


def main() -> int:
    ai_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("ntrs_20130014061.json"),
                        help="source manifest filename inside ai/sources")
    args = parser.parse_args()
    source_path = args.source if args.source.is_absolute() else ai_dir / "sources" / args.source
    try:
        source_path.resolve().relative_to((ai_dir / "sources").resolve())
    except ValueError:
        parser.error("--source must point to a manifest inside ai/sources")
    try:
        settings = Settings.from_environment()
        source = load_source(source_path)
        path = download_pdf(source, ai_dir / ".cache")
        document = load_pdf(path)
        plan = prepare_ingestion(source, document, CohereEmbeddingClient(settings))
    except (ConfigurationError, InvalidDocumentError, IngestionPlanError,
            CohereServiceError, CohereEmbeddingResponseError) as exc:
        print(f"Ingestion preparation failed: {exc}", file=sys.stderr)
        return 1

    print(f"source_id: {source.source_id}")
    print(f"document_sha256: {document.sha256}")
    print(f"extraction_version: {document.extraction_version}")
    print(f"pages: {len(document.pages)}")
    print(f"chunks: {plan.chunk_count}")
    print(f"embedding_model: {plan.model_name}")
    print(f"embedding_dimensions: {len(plan.embeddings[0])}")
    print(f"config_hash: {plan.config_hash}")
    print(f"plan_hash: {plan.plan_hash}")
    print("database_writes: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
