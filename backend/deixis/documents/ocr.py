"""Local OCR of scanned PDF pages with Tesseract through PyMuPDF (D51).

A page is read on request, one page per bounded child process, so a `pdf_ocr` run can store each page as its own step
and not read it again after a restart. Only pages that `pdf.extract_pdf` names as image pages are merged; text layer
pages are never replaced. No file leaves the machine and the PDF is not rewritten.

OCR text is not checked text: Tesseract gives PyMuPDF no word confidence here, superscripts and equations come out
wrong in places, and letters of a language without installed data are misread. "succeeded" only means text was found.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pymupdf

from deixis.documents import pdf

INSTALL_COMMAND = "brew install tesseract tesseract-lang"
LANGUAGES = ("eng", "tur")
DPI = 300
TIMEOUT_SECONDS = 60  # per page; provisional until measured on real scans
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
OCR_VERSION = "v1"


@dataclass
class OcrPage:
    physical_page: int
    status: str  # succeeded, no_text, failed
    text: str = ""
    error: str | None = None
    printed_label: str | None = None


def tesseract_status(langs=LANGUAGES) -> dict:
    """Whether Tesseract is installed, its version, and which of `langs` have data."""
    missing = {"available": False, "version": None, "languages": [], "missing_languages": list(langs)}
    if shutil.which("tesseract") is None:
        return missing | {"reason": f"Tesseract is not installed. Install it with: {INSTALL_COMMAND}"}
    try:
        version = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=10)
        listed = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return missing | {"reason": f"Tesseract could not be run: {exc}"}
    match = re.search(r"tesseract v?(\d+(?:\.\d+)*)", version.stdout + version.stderr)
    installed = set(listed.stdout.split()[1:] if listed.returncode == 0 else [])  # the first line is a header
    languages = [lang for lang in langs if lang in installed]
    absent = [lang for lang in langs if lang not in installed]
    reason = f"Tesseract has no data for {', '.join(absent)}. Install it with: {INSTALL_COMMAND}" if absent else None
    return {"available": bool(match and languages), "version": match.group(1) if match else None, "languages": languages,
            "missing_languages": absent, "reason": reason}


def read_page(path: Path, page: int, langs, timeout: float = TIMEOUT_SECONDS, max_memory: int = MAX_MEMORY_BYTES) -> OcrPage:
    """OCR one physical page (1-based) in a child process limited in time and memory."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deixis.documents.ocr", str(path), str(page), "+".join(langs), str(max_memory)],
            capture_output=True,
            timeout=timeout,
            # PyMuPDF finds the Tesseract data through TESSDATA_PREFIX or by running `tesseract`, so the child needs both.
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}
            | {name: os.environ[name] for name in ("PATH", "TESSDATA_PREFIX") if name in os.environ},
        )
    except subprocess.TimeoutExpired:
        return OcrPage(page, "failed", error="OCR timed out")
    if completed.returncode == pdf.MEMORY_EXIT_CODE:
        return OcrPage(page, "failed", error="OCR exceeded the memory limit")
    if completed.returncode != 0:
        return OcrPage(page, "failed", error=completed.stderr.decode(errors="replace")[-400:])
    raw = json.loads(completed.stdout)
    text = pdf.remove_download_notices(raw["text"]).strip()
    return OcrPage(page, "succeeded" if text else "no_text", text, printed_label=raw["printed_label"])


def merge(extraction: pdf.Extraction, pages: list[OcrPage], langs) -> pdf.Extraction:
    """A new extraction: the text layer pages unchanged plus the OCR text of image pages that were read."""
    numbers = [p.physical_page for p in pages]
    if len(set(numbers)) != len(numbers) or not set(numbers) <= set(extraction.image_pages):
        raise ValueError("OCR pages must be distinct image pages of this extraction")
    version = tesseract_status(langs)["version"]
    read = [pdf.PageText(p.physical_page, p.printed_label, p.text, "ocr") for p in pages if p.status == "succeeded"]
    merged = sorted(extraction.pages + read, key=lambda p: p.physical_page)
    status = "no_text" if not merged else "partial" if len(merged) < extraction.page_count else "succeeded"
    ocr = {"engine": "tesseract", "version": version, "languages": list(langs),
           "pages_read": sum(p.status != "failed" for p in pages), "pages_with_text": len(read),
           "blank_pages": len(extraction.blank_pages), "failed_pages": sorted(p.physical_page for p in pages if p.status == "failed")}
    return replace(extraction, status=status, pages=merged, ocr=ocr,
                   extraction_version=f"{extraction.extraction_version}+ocr-tesseract-{version}-{'+'.join(langs)}-{OCR_VERSION}")


def _read_in_process(path: str, page_number: int, language: str) -> dict:
    with pymupdf.open(path, filetype="pdf") as doc:
        if not doc.is_pdf or not 1 <= page_number <= doc.page_count:
            raise ValueError("not a page of this PDF")
        page = doc[page_number - 1]
        textpage = page.get_textpage_ocr(language=language, dpi=DPI, full=True)
        text = "\n\n".join(pdf._join_lines(block["lines"]) for block in pdf._blocks(page, textpage))
        label = page.get_label() or None
    return {"text": text, "printed_label": label if label != str(page_number) else None}


if __name__ == "__main__":
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    pdf._watch_memory(int(sys.argv[4]))
    try:
        result = _read_in_process(sys.argv[1], int(sys.argv[2]), sys.argv[3])
    except MemoryError:
        sys.exit(pdf.MEMORY_EXIT_CODE)
    json.dump(result, sys.stdout)
