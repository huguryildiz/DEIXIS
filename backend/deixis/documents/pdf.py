"""Page-level PDF text extraction in a bounded subprocess.

pypdf extracts embedded text only: scanned pages yield no text (no OCR), and
equations/tables may be garbled. The original page stays the reference.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pypdf

EXTRACTION_VERSION = f"pypdf-{pypdf.__version__}-chunks-v1"
MAX_PAGES = 400
TIMEOUT_SECONDS = 90
CHUNK_CHARS = 1400


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


def _extract_in_process(path: str) -> dict:
    reader = pypdf.PdfReader(path)
    labels = list(reader.page_labels) if reader.page_labels else []
    pages, failed = [], 0
    total = len(reader.pages)
    for index, page in enumerate(reader.pages[:MAX_PAGES]):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page must not lose the rest
            failed += 1
            continue
        label = labels[index] if index < len(labels) else None
        pages.append({"physical_page": index + 1, "printed_label": label if label != str(index + 1) else None, "text": text})
    return {"page_count": total, "pages": pages, "failed_pages": failed, "truncated": total > MAX_PAGES}


def extract_pdf(path: Path) -> Extraction:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deixis.documents.pdf", str(path)],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        )
    except subprocess.TimeoutExpired:
        return Extraction("failed", error="extraction timed out")
    if completed.returncode != 0:
        return Extraction("failed", error=completed.stderr.decode(errors="replace")[-400:])
    raw = json.loads(completed.stdout)
    pages = [PageText(**p) for p in raw["pages"] if p["text"].strip()]
    if not pages:
        return Extraction("no_text", page_count=raw["page_count"])
    status = "partial" if raw["failed_pages"] or raw["truncated"] or len(pages) < raw["page_count"] else "succeeded"
    return Extraction(status, page_count=raw["page_count"], pages=pages)


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
    json.dump(_extract_in_process(sys.argv[1]), sys.stdout)
