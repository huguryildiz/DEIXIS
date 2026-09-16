"""Page-level PDF text extraction in a bounded subprocess.

PyMuPDF extracts embedded text only: scanned pages yield no text (no OCR), and
equations/tables may still be garbled. Ligatures come out as plain letters. The
original page stays the reference. Passages extracted earlier with pypdf keep their
own `extraction_version`; they are not re-extracted.

From `chunks-v2` the IEEE Xplore download notice stamped on every page ("Authorized licensed
use limited to: ... Restrictions apply.") is removed from page text before chunking (D43).
Passages stored by `chunks-v1` keep the notice; nothing is re-extracted.

The child process is limited in time, pages, total extracted text and memory. The memory
limit is a watchdog on the child's peak resident size: it stops the child shortly after the
limit is crossed rather than preventing the allocation. There is no memory limit on Windows yet.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

EXTRACTION_VERSION = f"pymupdf-{pymupdf.__version__}-chunks-v2"
# MuPDF's default text flags without TEXT_PRESERVE_LIGATURES, so "ﬁ" is extracted as "fi".
TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
MAX_PAGES = 400
MAX_TEXT_CHARS = 3_000_000
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
MEMORY_EXIT_CODE = 3
TIMEOUT_SECONDS = 90
CHUNK_CHARS = 1400
# A licensing stamp added by the download site, not text of the publication. Only the whole notice matches, and each gap
# is bounded, so body text next to it is kept.
DOWNLOAD_NOTICE = re.compile(
    r"Authorized licensed use limited to:.{0,200}?Downloaded on.{0,80}?from IEEE Xplore\.\s*Restrictions apply\.[ \t]*\n?", re.S
)


@dataclass
class PageText:
    physical_page: int
    printed_label: str | None
    text: str


@dataclass
class Extraction:
    status: str  # succeeded, partial, no_text, failed
    page_count: int = 0
    pages: list[PageText] = field(default_factory=list)
    error: str | None = None


def _extract_in_process(path: str, max_chars: int) -> dict:
    with pymupdf.open(path, filetype="pdf") as doc:
        if not doc.is_pdf:  # MuPDF opens other bytes as a one-page document instead of raising
            raise ValueError("not a PDF")
        pages, failed, chars = [], 0, 0
        total = doc.page_count
        truncated = total > MAX_PAGES
        for index in range(min(total, MAX_PAGES)):
            if chars >= max_chars:
                truncated = True
                break
            try:
                page = doc[index]
                text = page.get_text("text", flags=TEXT_FLAGS)
                label = page.get_label() or None
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                failed += 1
                continue
            if len(text) > max_chars - chars:
                text, truncated = text[: max_chars - chars], True
            chars += len(text)
            pages.append({"physical_page": index + 1, "printed_label": label if label != str(index + 1) else None, "text": text})
    return {"page_count": total, "pages": pages, "failed_pages": failed, "truncated": truncated}


def _watch_memory(limit: int) -> None:
    try:
        import resource
    except ImportError:  # Windows
        return
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss is bytes on macOS, kilobytes on Linux

    def watch() -> None:
        while resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale <= limit:
            time.sleep(0.05)
        sys.stderr.write("memory limit exceeded\n")
        sys.stderr.flush()
        os._exit(MEMORY_EXIT_CODE)

    threading.Thread(target=watch, daemon=True).start()


def extract_pdf(path: Path, max_chars: int = MAX_TEXT_CHARS, max_memory: int = MAX_MEMORY_BYTES) -> Extraction:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deixis.documents.pdf", str(path), str(max_chars), str(max_memory)],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        )
    except subprocess.TimeoutExpired:
        return Extraction("failed", error="extraction timed out")
    if completed.returncode == MEMORY_EXIT_CODE:
        return Extraction("failed", error="extraction exceeded the memory limit")
    if completed.returncode != 0:
        return Extraction("failed", error=completed.stderr.decode(errors="replace")[-400:])
    raw = json.loads(completed.stdout)
    pages = [PageText(p["physical_page"], p["printed_label"], text) for p in raw["pages"] if (text := remove_download_notices(p["text"])).strip()]
    if not pages:
        return Extraction("no_text", page_count=raw["page_count"])
    status = "partial" if raw["failed_pages"] or raw["truncated"] or len(pages) < raw["page_count"] else "succeeded"
    return Extraction(status, page_count=raw["page_count"], pages=pages)


def remove_download_notices(text: str) -> str:
    return DOWNLOAD_NOTICE.sub("", text)


def chunk_page(text: str, limit: int = CHUNK_CHARS) -> list[tuple[int, int, str]]:
    """Split page text into (start, end, text) chunks on paragraph or sentence boundaries."""
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    chunks, start = [], 0
    while start < len(normalized):
        end = min(start + limit, len(normalized))
        if end < len(normalized):
            window = normalized[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > limit // 3:
                end = start + cut + 1
        piece = normalized[start:end].strip()
        if piece:
            chunks.append((start, end, piece))
        start = end
    return chunks


if __name__ == "__main__":
    # A malformed file must not flood the parent with MuPDF messages.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    _watch_memory(int(sys.argv[3]))
    try:
        result = _extract_in_process(sys.argv[1], int(sys.argv[2]))
    except MemoryError:
        sys.exit(MEMORY_EXIT_CODE)
    json.dump(result, sys.stdout)
