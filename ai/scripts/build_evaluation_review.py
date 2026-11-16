"""Build a human review packet from the pinned NASA PDF and candidate keys."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyrogravity_ai.ingestion.chunker import chunk_document
from pyrogravity_ai.ingestion.loader import InvalidDocumentError, download_pdf, load_pdf
from pyrogravity_ai.retrieval.evaluation import (
    build_review_packet,
    load_evaluation_set,
)
from pyrogravity_ai.schemas.source import load_source


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Preparar revisión humana de casos de recuperación")
    parser.add_argument("--check", action="store_true", help="comprobar que la ficha está actualizada")
    parser.add_argument("--force", action="store_true", help="regenerar la ficha si cambian los casos")
    args = parser.parse_args()
    if args.check and args.force:
        parser.error("--check y --force no se pueden combinar")

    ai_dir = Path(__file__).resolve().parents[1]
    source = load_source(ai_dir / "sources" / "ntrs_20130014061.json")
    candidates = load_evaluation_set(ai_dir / "evaluations" / "ntrs_20130014061_candidates.json")
    if candidates.source_id != source.source_id:
        print("La fuente de los casos no coincide con el manifiesto.", file=sys.stderr)
        return 1
    try:
        pdf_path = download_pdf(source, ai_dir / ".cache")
        document = load_pdf(pdf_path)
        packet = build_review_packet(
            candidates,
            document,
            chunk_document(document),
            source_title=source.title,
            source_url=str(source.catalog_url),
        )
    except (InvalidDocumentError, ValueError) as exc:
        print(f"No se pudo preparar la revisión: {exc}", file=sys.stderr)
        return 1

    output = ai_dir / "evaluations" / "ntrs_20130014061_review.md"
    if output.exists() and output.read_text(encoding="utf-8") != packet and not args.force:
        print("La ficha existente difiere; revísala antes de reemplazarla.", file=sys.stderr)
        return 1
    if not output.exists() and args.check:
        print("La ficha de revisión no existe.", file=sys.stderr)
        return 1
    if not args.check:
        output.write_text(packet, encoding="utf-8")
    print(f"Ficha {'comprobada' if args.check else 'preparada'}: "
          f"{output.relative_to(ai_dir)} ({len(candidates.cases)} casos candidatos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
