"""Page-level PDF text extraction in a bounded subprocess.

PyMuPDF extracts embedded text only: scanned pages yield no text, and
equations/tables may still be garbled. Ligatures come out as plain letters. The
original page stays the reference. Passages extracted earlier with pypdf keep their
own `extraction_version`; they are not re-extracted.

From `chunks-v2` the IEEE Xplore download notice stamped on every page ("Authorized licensed
use limited to: ... Restrictions apply.") is removed from page text before chunking (D43).
Passages stored by `chunks-v1` keep the notice; nothing is re-extracted.

From `layout-v1` (D47) page text is built from MuPDF's text blocks instead of the flat page text. Lines that are not
horizontal (the arXiv identifier along the margin), blocks holding only a page number and small-type blocks in the top
margin (running heads) are dropped. Blocks set smaller than the document's body text (author notes, captions, tables,
footnotes) follow the page's body text as their own paragraphs, so a footnote no longer splits a sentence of the column
around it. Section headings become their own paragraph, and a word hyphenated at a line end is joined. From `layout-v2`
a numbered reference entry ("[39] …") is one paragraph even when MuPDF splits its lines into several blocks or puts two
entries in one block. The original page stays the reference; older passages keep their version until the asset is
re-extracted (D45).

A page left without text is named: an image page (a scan, which `ocr.py` can read on request, D51) or a blank page.

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

EXTRACTION_VERSION = f"pymupdf-{pymupdf.__version__}-layout-v2"
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
SMALL_TYPE = 0.87  # blocks below this share of the body size are small type (IEEE: 8 pt notes, 9 pt abstract, 10 pt body)
TOP_MARGIN = 0.07  # share of the page height where running heads sit
# A numbered section heading ("I. INTRODUCTION", "3.2 Results", "A. Model") or an unnumbered standard one.
HEADING = re.compile(r"(?:(?:[IVXL]+|\d+(?:\.\d+)*|[A-H])\.?\s+[A-Z][^.]{1,76}|Abstract|References|Acknowledge?ments?|Appendix)")


@dataclass
class PageText:
    physical_page: int
    printed_label: str | None
    text: str
    text_source: str = "text_layer"  # text_layer or ocr


@dataclass
class Extraction:
    status: str  # succeeded, partial, no_text, failed
    page_count: int = 0
    pages: list[PageText] = field(default_factory=list)
    error: str | None = None
    image_pages: list[int] = field(default_factory=list)  # pages without text that hold an image
    blank_pages: list[int] = field(default_factory=list)  # pages without text or image
    ocr: dict | None = None
    extraction_version: str = EXTRACTION_VERSION


def _blocks(page: pymupdf.Page, textpage: pymupdf.TextPage | None = None) -> list[dict]:
    """Text blocks with their box, horizontal lines and the character-weighted type size."""
    blocks = []
    for block in page.get_text("dict", flags=TEXT_FLAGS, textpage=textpage)["blocks"]:
        lines, weighted, count = [], 0.0, 0
        for line in block.get("lines", []):
            if abs(line["dir"][1]) > 0.1:  # rotated or vertical: margin stamps such as arXiv's identifier
                continue
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            lines.append(text)
            for span in line["spans"]:
                chars = len(span["text"].strip())
                weighted, count = weighted + span["size"] * chars, count + chars
        if lines and count:
            blocks.append({"bbox": block["bbox"], "lines": lines, "size": weighted / count, "chars": count})
    return blocks


def _body_size(layouts: list[tuple]) -> float:
    """The type size that carries most characters in the document, rounded to a quarter point."""
    sizes: dict[float, int] = {}
    for *_, blocks in layouts:
        for block in blocks:
            key = round(block["size"] * 4) / 4
            sizes[key] = sizes.get(key, 0) + block["chars"]
    return max(sizes, key=sizes.get) if sizes else 0.0


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in (line.strip() for line in lines):
        if re.search(r"[a-z]-$", text) and re.match(r"[a-z]", line):
            text = text[:-1] + line  # a word hyphenated at the line end
        else:
            text = f"{text}\n{line}" if text else line
    return text


REFERENCE_ENTRY = re.compile(r"\[\d{1,4}\]\s")


def _paragraphs(texts: list[str]) -> list[str]:
    """Blocks as paragraphs: a numbered reference entry is one paragraph even when MuPDF splits or joins its lines."""
    out: list[str] = []
    for text in texts:
        for part in re.split(r"\n(?=\[\d{1,4}\]\s)", text):
            if out and REFERENCE_ENTRY.match(out[-1]) and not REFERENCE_ENTRY.match(part):
                out[-1] = out[-1][:-1] + part if re.search(r"[a-z]-$", out[-1]) and re.match(r"[a-z]", part) else f"{out[-1]}\n{part}"
            else:
                out.append(part)
    return out


def _page_text(blocks: list[dict], height: float, body_size: float) -> str:
    body, notes = [], []
    for block in blocks:
        text = _join_lines(block["lines"])
        compact = re.sub(r"\s+", " ", text).strip()
        small = body_size > 0 and block["size"] < body_size * SMALL_TYPE
        if re.fullmatch(r"\d{1,4}", compact):
            continue  # a page number
        if small and block["bbox"][3] < height * TOP_MARGIN:
            continue  # a running head
        if len(block["lines"]) <= 2 and len(compact) <= 80 and HEADING.fullmatch(compact):
            body.append(compact)
        elif small:
            notes.append(text)
        else:
            body.append(text)
    return "\n\n".join(_paragraphs(body) + _paragraphs(notes))


def _extract_in_process(path: str, max_chars: int) -> dict:
    with pymupdf.open(path, filetype="pdf") as doc:
        if not doc.is_pdf:  # MuPDF opens other bytes as a one-page document instead of raising
            raise ValueError("not a PDF")
        failed, layouts, seen = 0, [], 0
        total = doc.page_count
        truncated = total > MAX_PAGES
        for index in range(min(total, MAX_PAGES)):
            if seen >= max_chars:
                truncated = True
                break
            try:
                page = doc[index]
                blocks = _blocks(page)
                label = page.get_label() or None
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                failed += 1
                continue
            seen += sum(block["chars"] for block in blocks)
            layouts.append((index, label, page.rect.height, blocks))
        body_size = _body_size(layouts)
        pages, chars = [], 0
        for index, label, height, blocks in layouts:
            if chars >= max_chars:
                truncated = True
                break
            text = _page_text(blocks, height, body_size)
            if len(text) > max_chars - chars:
                text, truncated = text[: max_chars - chars], True
            chars += len(text)
            # A page whose only text is the download notice is still a scan when it holds an image.
            has_image = not remove_download_notices(text).strip() and bool(doc[index].get_image_info())
            pages.append({"physical_page": index + 1, "printed_label": label if label != str(index + 1) else None, "text": text,
                          "has_image": has_image})
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
    pages, image_pages, blank_pages = [], [], []
    for p in raw["pages"]:
        if (text := remove_download_notices(p["text"])).strip():
            pages.append(PageText(p["physical_page"], p["printed_label"], text))
        else:
            (image_pages if p["has_image"] else blank_pages).append(p["physical_page"])
    if not pages:
        return Extraction("no_text", page_count=raw["page_count"], image_pages=image_pages, blank_pages=blank_pages)
    status = "partial" if raw["failed_pages"] or raw["truncated"] or len(pages) < raw["page_count"] else "succeeded"
    return Extraction(status, page_count=raw["page_count"], pages=pages, image_pages=image_pages, blank_pages=blank_pages)


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
