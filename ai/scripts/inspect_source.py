"""Download and inspect the first curated NASA document without indexing it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyrogravity_ai.ingestion.chunker import chunk_document
from pyrogravity_ai.ingestion.loader import InvalidDocumentError, download_pdf, load_pdf
from pyrogravity_ai.schemas.source import load_source


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Inspect page-bounded chunks from the first NASA source")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page to preview")
    args = parser.parse_args()

    ai_dir = Path(__file__).resolve().parents[1]
    source = load_source(ai_dir / "sources" / "ntrs_20130014061.json")
    try:
        path = download_pdf(source, ai_dir / ".cache")
        document = load_pdf(path)
    except InvalidDocumentError as exc:
        print(f"Source inspection failed: {exc}")
        return 1

    chunks = chunk_document(document)
    if args.page < 1 or args.page > len(document.pages):
        parser.error(f"--page must be between 1 and {len(document.pages)}")
    print(f"source_id: {source.source_id}")
    print(f"sha256: {document.sha256}")
    print(f"pages: {len(document.pages)}")
    print(f"pages_with_text: {sum(bool(page.text) for page in document.pages)}")
    print(f"replacement_characters: {sum(page.text.count(chr(0xfffd)) for page in document.pages)}")
    print(f"chunks: {len(chunks)}")
    for chunk in (chunk for chunk in chunks if chunk.page_number == args.page):
        preview = " ".join(chunk.text[:180].split())
        print(f"page {chunk.page_number}, chunk {chunk.chunk_index}: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
