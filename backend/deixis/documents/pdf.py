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
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from deixis.documents import inline_math

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
    text_source: str = "text_layer"  # text_layer, ocr, or marker (a page with mathematics read by Marker, D52)
    # Display equations placed from the authors' arXiv source (D104), as (start, end, number) in the
    # `normalize_page_text` space of `text`; a chunk holding one is labelled `latex_source`.
    latex_blocks: list = field(default_factory=list)


@dataclass
class Extraction:
    status: str  # succeeded, partial, no_text, failed
    page_count: int = 0
    pages: list[PageText] = field(default_factory=list)
    error: str | None = None
    image_pages: list[int] = field(default_factory=list)  # pages without text that hold an image
    blank_pages: list[int] = field(default_factory=list)  # pages without text or image
    ocr: dict | None = None
    math: dict | None = None  # the equation reading merged into this extraction (D52)
    extraction_version: str = EXTRACTION_VERSION
    # Source equations asked to be placed (D104): {"placed": [{page, n, start, end}], "refused": [{page, n, reason}]}.
    placement: dict | None = None


def _blocks(page: pymupdf.Page, textpage: pymupdf.TextPage | None = None) -> list[dict]:
    """Text blocks with their box, horizontal lines and the character-weighted type size.

    Each block also carries, per line, the line's text with symbol-font letters masked (`inline_math.line_text`) and its
    box, for matching source equations to the page (D104); neither enters the page text."""
    blocks = []
    for block in page.get_text("dict", flags=TEXT_FLAGS, textpage=textpage)["blocks"]:
        lines, masked, boxes, weighted, count = [], [], [], 0.0, 0
        for line in block.get("lines", []):
            if abs(line["dir"][1]) > 0.1:  # rotated or vertical: margin stamps such as arXiv's identifier
                continue
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            lines.append(text)
            masked.append(inline_math.line_text([(span["text"], span["font"]) for span in line["spans"]]))
            boxes.append(tuple(line["bbox"]))
            for span in line["spans"]:
                chars = len(span["text"].strip())
                weighted, count = weighted + span["size"] * chars, count + chars
        if lines and count:
            blocks.append({"bbox": block["bbox"], "lines": lines, "size": weighted / count, "chars": count,
                           "masked": masked, "line_boxes": boxes})
    return blocks


def _body_size(layouts: list[tuple]) -> float:
    """The type size that carries most characters in the document, rounded to a quarter point."""
    sizes: dict[float, int] = {}
    for *_, blocks in layouts:
        for block in blocks:
            key = round(block["size"] * 4) / 4
            sizes[key] = sizes.get(key, 0) + block["chars"]
    return max(sizes, key=sizes.get) if sizes else 0.0


def _join_lines(lines: list[str], lower=re.compile(r"[a-z]").fullmatch) -> str:
    """Lines of a block; a word hyphenated at a line end is joined when `lower` accepts the letters around the hyphen.
    The text layer keeps ASCII letters (changing that changes its extraction version); OCR text passes any lowercase letter."""
    text = ""
    for line in (line.strip() for line in lines):
        if len(text) > 1 and text[-1] == "-" and lower(text[-2]) and line and lower(line[0]):
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


def _block_kind(block: dict, height: float, body_size: float) -> str:
    """page_number and running_head blocks are dropped; a heading is compacted; note blocks follow the body."""
    compact = re.sub(r"\s+", " ", _join_lines(block["lines"])).strip()
    small = body_size > 0 and block["size"] < body_size * SMALL_TYPE
    if re.fullmatch(r"\d{1,4}", compact):
        return "page_number"
    if small and block["bbox"][3] < height * TOP_MARGIN:
        return "running_head"
    if len(block["lines"]) <= 2 and len(compact) <= 80 and HEADING.fullmatch(compact):
        return "heading"
    return "note" if small else "body"


def _page_text(blocks: list[dict], height: float, body_size: float, lines: dict[int, list[str]] | None = None) -> str:
    """The page text from its blocks. `lines` gives some blocks other lines (source equations placed, D104); a block's
    kind is always decided from its own lines, so a page without placements is built exactly as before."""
    body, notes = [], []
    for index, block in enumerate(blocks):
        kind = _block_kind(block, height, body_size)
        if kind in ("page_number", "running_head"):
            continue
        text = _join_lines(block["lines"] if lines is None or index not in lines else lines[index])
        if not text:
            continue  # every line of the block was an equation region placed at another block's number line
        if kind == "heading":
            body.append(re.sub(r"\s+", " ", text).strip())
        elif kind == "note":
            notes.append(text)
        else:
            body.append(text)
    return "\n\n".join(_paragraphs(body) + _paragraphs(notes))


def display_block(latex: str, number: str) -> str:
    """A placed source equation in Marker's form (D104)."""
    return f"$$\n{latex}\n$$ ({number})"


def _place(blocks: list[dict], height: float, body_size: float, placements: list[dict]) -> tuple[dict[int, list[str]], list[dict], list[dict]]:
    """Replace each placement's region lines with its display block at the number line. A region with a line in a block
    that never reaches the page text as its own lines (page number, running head, compacted heading) is refused."""
    replaced: dict[int, list[str | None]] = {}
    taken: set[tuple[int, int]] = set()
    placed, refused = [], []
    for item in placements:
        keys = [tuple(k) for k in item["lines"]]
        number = tuple(item["number"])
        valid = all(0 <= b < len(blocks) and 0 <= ln < len(blocks[b]["lines"]) for b, ln in keys) and number in keys
        if not valid or any(_block_kind(blocks[b], height, body_size) in ("page_number", "running_head", "heading") for b, _ in keys):
            refused.append({"n": item["n"], "reason": "not_in_page_text"})
            continue
        if taken & set(keys):
            refused.append({"n": item["n"], "reason": "overlapping_region"})
            continue
        taken |= set(keys)
        for b, ln in keys:
            replaced.setdefault(b, list(blocks[b]["lines"]))[ln] = display_block(item["latex"], item["n"]) if (b, ln) == number else None
        placed.append({"n": item["n"], "block": display_block(item["latex"], item["n"])})
    return {b: [line for line in lines if line is not None] for b, lines in replaced.items()}, placed, refused


def _extract_in_process(path: str, max_chars: int, placements: list[dict] | None = None) -> dict:
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
        by_page: dict[int, list[dict]] = {}
        for item in placements or []:
            by_page.setdefault(item["page"], []).append(item)
        for index, label, height, blocks in layouts:
            if chars >= max_chars:
                truncated = True
                break
            lines, placed, refused = _place(blocks, height, body_size, by_page[index + 1]) if index + 1 in by_page else (None, [], [])
            text = _page_text(blocks, height, body_size, lines)
            if len(text) > max_chars - chars:
                text, truncated = text[: max_chars - chars], True
            chars += len(text)
            # A page whose only text is the download notice is still a scan when it holds an image.
            has_image = not remove_download_notices(text).strip() and bool(doc[index].get_image_info())
            pages.append({"physical_page": index + 1, "printed_label": label if label != str(index + 1) else None, "text": text,
                          "has_image": has_image} | ({"placed": placed, "refused": refused} if index + 1 in by_page else {}))
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


def extract_pdf(path: Path, max_chars: int = MAX_TEXT_CHARS, max_memory: int = MAX_MEMORY_BYTES,
                placements: list[dict] | None = None) -> Extraction:
    """The PDF's text layer. `placements` (D104) are source equations to put in place of their region's lines:
    [{"page", "n", "latex", "number": [block, line], "lines": [[block, line], ...]}] keyed into `_blocks`."""
    argv = [sys.executable, "-m", "deixis.documents.pdf", str(path), str(max_chars), str(max_memory)]
    request = None
    try:
        if placements is not None:
            request = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
            with request:
                json.dump(placements, request)
            argv.append(request.name)
        completed = subprocess.run(
            argv,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        )
    except subprocess.TimeoutExpired:
        return Extraction("failed", error="extraction timed out")
    finally:
        if request is not None:
            Path(request.name).unlink(missing_ok=True)
    if completed.returncode == MEMORY_EXIT_CODE:
        return Extraction("failed", error="extraction exceeded the memory limit")
    if completed.returncode != 0:
        return Extraction("failed", error=completed.stderr.decode(errors="replace")[-400:])
    raw = json.loads(completed.stdout)
    pages, image_pages, blank_pages = [], [], []
    placement = {"placed": [], "refused": []} if placements is not None else None
    for p in raw["pages"]:
        if (text := remove_download_notices(p["text"])).strip():
            page = PageText(p["physical_page"], p["printed_label"], text)
            if placement is not None and ("placed" in p or "refused" in p):
                placement["refused"] += [{"page": page.physical_page} | r for r in p.get("refused", [])]
                for found in _block_offsets(text, p.get("placed", [])):
                    placement["placed" if "start" in found else "refused"].append({"page": page.physical_page} | found)
                page.latex_blocks = [(f["start"], f["end"], f["n"]) for f in placement["placed"] if f["page"] == page.physical_page]
            pages.append(page)
        else:
            (image_pages if p["has_image"] else blank_pages).append(p["physical_page"])
            if placement is not None:
                placement["refused"] += [{"page": p["physical_page"], "n": item["n"], "reason": "not_in_page_text"} for item in p.get("placed", [])]
    if not pages:
        return Extraction("no_text", page_count=raw["page_count"], image_pages=image_pages, blank_pages=blank_pages, placement=placement)
    status = "partial" if raw["failed_pages"] or raw["truncated"] or len(pages) < raw["page_count"] else "succeeded"
    return Extraction(status, page_count=raw["page_count"], pages=pages, image_pages=image_pages, blank_pages=blank_pages,
                      placement=placement)


def _block_offsets(text: str, placed: list[dict]) -> list[dict]:
    """Each placed display block's (start, end) in `normalize_page_text(text)`, the space `chunk_page` cuts and
    `payload_ref` counts in (D104). Each block (run through the same function) must occur exactly once in the page and
    the blocks must not overlap; one that does not is `offsets_unresolved`. Blocks are returned in the page text's order,
    which is not always the order of their number lines (small-type blocks follow the body, D47)."""
    normalized, found = normalize_page_text(text), []
    for item in placed:
        block = normalize_page_text(item["block"])
        start = normalized.find(block)
        if start < 0 or normalized.count(block) != 1:
            found.append({"n": item["n"], "reason": "offsets_unresolved"})
        else:
            found.append({"n": item["n"], "start": start, "end": start + len(block)})
    located = sorted((f for f in found if "start" in f), key=lambda f: f["start"])
    for before, after in zip(located, located[1:]):
        if after["start"] < before["end"]:
            before.pop("start"), before.pop("end")
            before["reason"] = "offsets_unresolved"
    return [f for f in located if "start" in f] + [f for f in found if "start" not in f]


def remove_download_notices(text: str) -> str:
    return DOWNLOAD_NOTICE.sub("", text)


def normalize_page_text(text: str) -> str:
    """The page text chunk offsets count in: runs of spaces and tabs as one space, the ends stripped."""
    return re.sub(r"[ \t]+", " ", text).strip()


DISPLAY_BLOCK = re.compile(r"\$\$\n[^\n]*\n\$\$ \(\d{1,3}[a-z]?\)")


def chunk_page(text: str, limit: int = CHUNK_CHARS, keep_display_math: bool = False) -> list[tuple[int, int, str]]:
    """Split page text into (start, end, text) chunks on paragraph or sentence boundaries.

    With `keep_display_math` (extractions carrying source equations, D104) a chunk never ends inside a placed
    `$$…$$ (n)` block, so each block lies whole in one chunk."""
    normalized = normalize_page_text(text)
    blocks = [(m.start(), m.end()) for m in DISPLAY_BLOCK.finditer(normalized)] if keep_display_math else []
    chunks, start = [], 0
    while start < len(normalized):
        end = min(start + limit, len(normalized))
        if end < len(normalized):
            window = normalized[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > limit // 3:
                end = start + cut + 1
            row = normalized.rfind("\n", start, end - 1) + 1  # a Markdown table row (D54) is cut before it, not inside it
            if normalized.startswith("|", row) and normalized.find("\n", end - 1) != end - 1 and row - start > limit // 3:
                end = row
            for block_start, block_end in blocks:
                if block_start < end < block_end:
                    end = block_start if block_start > start else block_end
                    break
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
        placements = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")) if len(sys.argv) > 4 else None
        result = _extract_in_process(sys.argv[1], int(sys.argv[2]), placements)
    except MemoryError:
        sys.exit(MEMORY_EXIT_CODE)
    json.dump(result, sys.stdout)
