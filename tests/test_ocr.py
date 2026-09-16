"""P5 slice 4 (D51): scanned PDF pages are found, read with the local Tesseract one page at a time, and merged into an
extraction whose pages say where their text came from.

Pages are SYNTHETIC images of typed text. Passing shows which pages are read and how results are recorded; it says nothing
about OCR accuracy on real scans. Tests that run Tesseract are skipped when it is not installed.
"""

import shutil

import pytest

from deixis.documents import ocr, pdf
from helpers import make_scanned_pdf

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
SCANNED = "SYNTHETIC scanned page. The release schedule minimizes the bit error probability with packets of 128 bytes."


def write(tmp_path, pages):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf(pages))
    return path


def test_extraction_names_scanned_and_blank_pages(tmp_path):
    path = write(tmp_path, [("text", "SYNTHETIC text layer page."), ("scan", SCANNED), ("blank", None)])
    result = pdf.extract_pdf(path)
    assert result.status == "partial" and [p.physical_page for p in result.pages] == [1]
    assert (result.image_pages, result.blank_pages) == ([2], [3])
    assert result.pages[0].text_source == "text_layer"

    only_scan = pdf.extract_pdf(write(tmp_path, [("scan", SCANNED)]))
    assert (only_scan.status, only_scan.image_pages, only_scan.blank_pages) == ("no_text", [1], [])


def test_tesseract_status_reports_the_tool_and_the_languages_it_lacks(monkeypatch):
    status = ocr.tesseract_status(("eng", "tur"))
    if shutil.which("tesseract"):
        assert status["available"] and status["version"]
        assert set(status["languages"]) | set(status["missing_languages"]) == {"eng", "tur"}
        assert not set(status["languages"]) & set(status["missing_languages"])
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    missing = ocr.tesseract_status(("eng", "tur"))
    assert (missing["available"], missing["languages"]) == (False, [])
    assert "brew install tesseract tesseract-lang" in missing["reason"]


@needs_tesseract
def test_a_scanned_page_is_read_and_merged_as_ocr_text(tmp_path):
    path = write(tmp_path, [("text", "SYNTHETIC text layer page."), ("scan", SCANNED), ("blank", None)])
    extraction = pdf.extract_pdf(path)
    page = ocr.read_page(path, 2, ["eng"])
    assert page.status == "succeeded" and "bit error probability" in page.text and "128 bytes" in page.text

    merged = ocr.merge(extraction, [page], ["eng"])
    assert [(p.physical_page, p.text_source) for p in merged.pages] == [(1, "text_layer"), (2, "ocr")]
    assert merged.pages[0].text == extraction.pages[0].text  # the text layer page is not read again
    assert merged.status == "partial"  # the blank page still has no text
    assert merged.ocr == {"engine": "tesseract", "version": ocr.tesseract_status(("eng",))["version"], "languages": ["eng"],
                          "pages_read": 1, "pages_with_text": 1, "blank_pages": 1, "failed_pages": []}
    assert merged.extraction_version == f"{pdf.EXTRACTION_VERSION}+ocr-tesseract-{merged.ocr['version']}-eng-v1"


@needs_tesseract
def test_a_page_that_fails_or_finds_nothing_is_recorded_and_changes_no_text(tmp_path):
    path = write(tmp_path, [("scan", SCANNED), ("scan", "")])
    extraction = pdf.extract_pdf(path)
    assert extraction.image_pages == [1, 2]

    timed_out = ocr.read_page(path, 1, ["eng"], timeout=0.001)
    assert (timed_out.status, timed_out.text, timed_out.error) == ("failed", "", "OCR timed out")
    empty = ocr.read_page(path, 2, ["eng"])
    assert (empty.status, empty.text) == ("no_text", "")

    merged = ocr.merge(extraction, [timed_out, empty], ["eng"])
    assert (merged.status, merged.pages) == ("no_text", [])
    assert merged.ocr["failed_pages"] == [1] and merged.ocr["pages_with_text"] == 0
    with pytest.raises(ValueError):  # a page that is not a scanned page of this file is refused
        ocr.merge(extraction, [ocr.OcrPage(physical_page=3, status="succeeded", text="x")], ["eng"])
