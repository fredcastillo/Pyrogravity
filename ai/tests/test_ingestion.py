from pathlib import Path
import hashlib
import json
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf_bytes(pages: list[str]) -> bytes:
    """Make a tiny selectable-text PDF without an external fixture or PDF generator."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        lines = []
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.extend((f"({escaped}) Tj", "T*"))
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 12 Tf 14 TL 50 700 Td " + " ".join(lines) + " ET").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_pages_and_chunks_keep_page_and_artifact_provenance(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.chunker import chunk_document
    from pyrogravity_ai.ingestion.loader import load_pdf

    path = tmp_path / "sample.pdf"
    path.write_bytes(_pdf_bytes([
        f"Page {number} " + "microgravity combustion " * 40 for number in (1, 2)
    ]))

    loaded = load_pdf(path)
    chunks = chunk_document(loaded, max_words=35, overlap_words=5)

    assert len(loaded.pages) == 2
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.artifact_sha256 == loaded.sha256 for chunk in chunks)
    assert all(chunk.text_sha256 for chunk in chunks)
    assert all(
        chunk.text == loaded.pages[chunk.page_number - 1].text[chunk.char_start:chunk.char_end]
        for chunk in chunks
    )
    assert all("Page 1" not in chunk.text for chunk in chunks if chunk.page_number == 2)


def test_identical_repeated_headers_are_removed_before_chunking(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.chunker import chunk_document
    from pyrogravity_ai.ingestion.loader import EXTRACTION_VERSION, load_pdf

    header = "Conference paper heading repeated on every page"
    path = tmp_path / "headed.pdf"
    path.write_bytes(_pdf_bytes([f"{header}\nScientific result {number}." for number in (1, 2, 3)]))

    loaded = load_pdf(path)
    chunks = chunk_document(loaded)

    assert loaded.extraction_version == EXTRACTION_VERSION
    assert [page.text for page in loaded.pages] == [
        f"Scientific result {number}." for number in (1, 2, 3)
    ]
    assert all(header not in chunk.text for chunk in chunks)
    assert all(
        chunk.text == loaded.pages[chunk.page_number - 1].text[chunk.char_start:chunk.char_end]
        for chunk in chunks
    )


def test_minority_first_line_is_not_removed(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.loader import load_pdf

    header = "Scientific heading appearing on a minority of pages"
    pages = [f"{header}\nEvidence {number}" for number in (1, 2, 3)]
    pages.extend(f"Unique opening {number}\nEvidence {number}" for number in range(4, 9))
    path = tmp_path / "mixed.pdf"
    path.write_bytes(_pdf_bytes(pages))

    loaded = load_pdf(path)
    assert all(page.text.startswith(header) for page in loaded.pages[:3])


def test_non_pdf_is_rejected(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.loader import InvalidDocumentError, load_pdf

    path = tmp_path / "wrong.pdf"
    path.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(InvalidDocumentError, match="PDF"):
        load_pdf(path)


def test_download_rejects_changed_publisher_bytes(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.loader import InvalidDocumentError, download_pdf
    from pyrogravity_ai.schemas.source import SourceRecord

    manifest = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["expected_document_sha256"] = "0" * 64
    source = SourceRecord.model_validate(payload)

    class FakeResponse:
        headers = {"content-length": "12"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_bytes(self):
            yield b"%PDF-1.7 fake"

        def raise_for_status(self):
            pass

    class FakeClient:
        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    with pytest.raises(InvalidDocumentError, match="hash"):
        download_pdf(source, tmp_path, client=FakeClient())


def test_download_accepts_matching_pdf_and_reuses_verified_cache(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.loader import download_pdf, load_pdf
    from pyrogravity_ai.schemas.source import SourceRecord

    pdf_bytes = _pdf_bytes(["Verified NASA text"])

    manifest = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["expected_document_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    source = SourceRecord.model_validate(payload)

    class FakeResponse:
        headers = {"content-length": str(len(pdf_bytes))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            midpoint = len(pdf_bytes) // 2
            yield pdf_bytes[:midpoint]
            yield pdf_bytes[midpoint:]

    class FakeClient:
        calls = 0

        def stream(self, *_args, **_kwargs):
            self.calls += 1
            return FakeResponse()

    client = FakeClient()
    first_path = download_pdf(source, tmp_path, client=client)
    second_path = download_pdf(source, tmp_path, client=client)

    assert first_path == second_path
    assert client.calls == 1
    assert load_pdf(first_path).pages[0].text == "Verified NASA text"
