from pathlib import Path
import hashlib
import json

import pymupdf
import pytest


def test_pdf_pages_and_chunks_keep_page_and_artifact_provenance(tmp_path: Path) -> None:
    from pyrogravity_ai.ingestion.chunker import chunk_document
    from pyrogravity_ai.ingestion.loader import load_pdf

    path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    for number in (1, 2):
        page = document.new_page()
        page.insert_text((50, 70), f"Page {number} " + "microgravity combustion " * 40)
    document.save(path)
    document.close()

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

    document = pymupdf.open()
    document.new_page().insert_text((50, 70), "Verified NASA text")
    pdf_bytes = document.tobytes()
    document.close()

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
