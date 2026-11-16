"""Download a pinned NASA PDF and extract text with original page numbers."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pyrogravity_ai.schemas.source import SourceRecord


MAX_PDF_BYTES = 20 * 1024 * 1024
EXTRACTION_VERSION = "pypdf-7.0.0-header-v1"
LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
})


class InvalidDocumentError(ValueError):
    """The PDF cannot safely be used as an indexed source."""


@dataclass(frozen=True)
class PageText:
    number: int  # Original PDF page number, starting at 1.
    text: str


@dataclass(frozen=True)
class LoadedDocument:
    sha256: str
    pages: tuple[PageText, ...]
    size_bytes: int
    extraction_version: str = EXTRACTION_VERSION


def _remove_repeated_headers(pages: tuple[PageText, ...]) -> tuple[PageText, ...]:
    """Drop only identical first lines repeated across most pages."""
    first_lines = [page.text.splitlines()[0].strip() for page in pages if page.text]
    if len(pages) < 3 or len(first_lines) < 3:
        return pages
    line, count = Counter(first_lines).most_common(1)[0]
    if len(line) < 20 or count < 3 or count * 2 < len(pages):
        return pages
    cleaned = []
    for page in pages:
        head, separator, rest = page.text.partition("\n")
        text = rest.strip() if separator and head.strip() == line else page.text
        cleaned.append(PageText(number=page.number, text=text))
    return tuple(cleaned)


def _validate_pdf_bytes(data: bytes, expected_sha256: str | None = None) -> str:
    if len(data) > MAX_PDF_BYTES:
        raise InvalidDocumentError("PDF exceeds the 20 MB ingestion limit")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocumentError("File is not a PDF")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise InvalidDocumentError("PDF hash differs from the reviewed source manifest")
    return digest


def download_pdf(
    source: SourceRecord,
    cache_dir: Path,
    *,
    client: Any | None = None,
) -> Path:
    """Fetch only the pinned NASA artifact; refuse changed publisher bytes."""
    if source.catalog_status != "catalog_verified":
        raise InvalidDocumentError("Source catalog has not been verified")
    if source.document_url.scheme != "https" or source.document_url.host != "ntrs.nasa.gov":
        raise InvalidDocumentError("Document URL must be an official HTTPS NASA NTRS URL")

    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{source.ntrs_id}.pdf"
    if target.exists():
        if target.stat().st_size > MAX_PDF_BYTES:
            raise InvalidDocumentError("PDF exceeds the 20 MB ingestion limit")
        _validate_pdf_bytes(target.read_bytes(), source.expected_document_sha256)
        return target

    owns_client = client is None
    active_client = client if client is not None else httpx.Client(timeout=60, follow_redirects=False)
    try:
        with active_client.stream("GET", str(source.document_url)) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length is not None and int(length) > MAX_PDF_BYTES:
                raise InvalidDocumentError("PDF exceeds the 20 MB ingestion limit")
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > MAX_PDF_BYTES:
                    raise InvalidDocumentError("PDF exceeds the 20 MB ingestion limit")
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, InvalidDocumentError):
            raise
        raise InvalidDocumentError("NASA PDF download failed") from None
    finally:
        if owns_client:
            active_client.close()

    _validate_pdf_bytes(data, source.expected_document_sha256)
    temporary = cache_dir / f".{source.ntrs_id}.pdf.tmp"
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


def load_pdf(path: Path) -> LoadedDocument:
    """Extract selectable text; keep page numbers even if a page is blank."""
    if path.stat().st_size > MAX_PDF_BYTES:
        raise InvalidDocumentError("PDF exceeds the 20 MB ingestion limit")
    data = path.read_bytes()
    digest = _validate_pdf_bytes(data)
    try:
        document = PdfReader(BytesIO(data), strict=True)
        if document.is_encrypted:
            raise InvalidDocumentError("Encrypted PDF cannot be indexed")
        pages = tuple(
            PageText(number=index + 1, text=(page.extract_text() or "").translate(LIGATURES).strip())
            for index, page in enumerate(document.pages)
        )
    except (PdfReadError, ValueError, OSError):
        raise InvalidDocumentError("PDF text extraction failed") from None
    pages = _remove_repeated_headers(pages)
    if not any(page.text for page in pages):
        raise InvalidDocumentError("PDF contains no extractable text")
    return LoadedDocument(sha256=digest, pages=pages, size_bytes=len(data))
