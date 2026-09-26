"""Europe PMC's open-access JATS full text drawn as a plain PDF, in a bounded subprocess (SW21, D106).

Europe PMC's own PDF route answers this machine with a Cloudflare check, and the PMC OA service with 404, so the
open-access subset's `fullTextXML` is the one route that returns the text. It is drawn here as a plain PDF (article
title, abstract, section headings and paragraphs, table captions and cell text, figure captions) and then goes through
the same bounded extraction as any downloaded PDF. The references, appendices and MathML markup are left out; the plain
text of a formula stays. The pages of such a file are DEIXIS's pages, not the publisher's: every surface that names a
page of it says "rendered" (`RENDITION_SQL`).

The parent refuses an XML larger than `MAX_XML_BYTES` and any document declaring an entity before anything is parsed.
Parsing and drawing run in a child process limited in time, memory, pages and output size, like `pdf.extract_pdf`.
"""

from __future__ import annotations

import html
import io
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.parsers import expat
from dataclasses import dataclass
from pathlib import Path

MAX_XML_BYTES = 5 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 60
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
MAX_RENDER_PAGES = 200
MAX_RENDER_BYTES = 30 * 1024 * 1024
MEMORY_EXIT_CODE = 3  # the same code `pdf._watch_memory` exits with
PAGES_EXIT_CODE = 4
OUTPUT_EXIT_CODE = 5

FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
FILENAME_SUFFIX = ".europepmc.pdf"
# An asset is a rendition only when all three hold: code downloaded it, from Europe PMC's fullTextXML address, under
# the file name code gives it. A person's upload named `x.europepmc.pdf` is not one. `a` is the `source_assets` row.
RENDITION_SQL = ("(a.origin = 'download'"
                 " AND a.retrieved_from LIKE 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC%/fullTextXML'"
                 " AND a.original_filename LIKE 'PMC%.europepmc.pdf')")


@dataclass(frozen=True)
class Rendition:
    status: str  # ok, jats_too_large, jats_entity_refused, jats_render_timeout, jats_render_memory, jats_render_pages,
    #              jats_render_output_too_large, jats_render_failed
    data: bytes = b""
    error: str | None = None


def filename(pmcid: str) -> str:
    return f"{pmcid}{FILENAME_SUFFIX}"


def is_rendition(origin: str | None, retrieved_from: str | None, original_filename: str | None) -> bool:
    """The Python reading of `RENDITION_SQL`, for a row already in hand."""
    url, name = retrieved_from or "", original_filename or ""
    return (origin == "download" and url.startswith("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC")
            and url.endswith("/fullTextXML") and name.startswith("PMC") and name.endswith(FILENAME_SUFFIX))


def render_pdf(xml: bytes, *, timeout: float = RENDER_TIMEOUT_SECONDS, max_memory: int = MAX_MEMORY_BYTES,
               max_pages: int = MAX_RENDER_PAGES, max_output: int = MAX_RENDER_BYTES,
               max_input: int = MAX_XML_BYTES) -> Rendition:
    """The JATS document drawn as a PDF, or the reason it was not. It never raises for a bad document."""
    if len(xml) > max_input:
        return Rendition("jats_too_large", error=f"{len(xml)} bytes")
    if b"<!ENTITY" in xml:
        return Rendition("jats_entity_refused")
    with tempfile.TemporaryDirectory(prefix="deixis-jats-") as folder:
        source, target = Path(folder) / "in.xml", Path(folder) / "out.pdf"
        source.write_bytes(xml)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "deixis.documents.jats", str(source), str(target), str(max_memory),
                 str(max_pages), str(max_output)],
                capture_output=True, timeout=timeout,
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])})
        except subprocess.TimeoutExpired:
            return Rendition("jats_render_timeout")
        code = completed.returncode
        if code == MEMORY_EXIT_CODE:
            return Rendition("jats_render_memory")
        if code == PAGES_EXIT_CODE:
            return Rendition("jats_render_pages")
        if code == OUTPUT_EXIT_CODE:
            return Rendition("jats_render_output_too_large")
        if code != 0:
            return Rendition("jats_render_failed", error=completed.stderr.decode(errors="replace")[-400:])
        size = target.stat().st_size if target.exists() else 0
        if size > max_output:
            return Rendition("jats_render_output_too_large")
        data = target.read_bytes() if size else b""
        if not data.startswith(b"%PDF-"):
            return Rendition("jats_render_failed", error="no PDF output")
        return Rendition("ok", data=data)


# ---- the child ------------------------------------------------------------------------------------------------------

_SKIP_INLINE = {"fig", "fig-group", "table-wrap", "table-wrap-group", "ref-list", "fn-group", "supplementary-material"}
_PAGE_MARGIN = 54


# A word holding a hyphen is kept on one line: the extractor joins a line ending in "-" to the next (`pdf._join_lines`),
# which would turn "quality-of-life" broken after "of-" into "quality-oflife". A longer token (an address) may still
# break, so that it is never pushed past the page's edge and clipped.
_HYPHENATED = re.compile(r"\S{0,40}-\S{0,40}")


def _esc(text: str) -> str:
    return _HYPHENATED.sub(lambda m: f'<span style="white-space:nowrap">{m.group(0)}</span>'
                           if len(m.group(0)) <= 40 else m.group(0), html.escape(text))


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _text(element: ET.Element) -> str:
    """The element's running text with nested floats left out; a formula keeps its plain text (MathML markup drops)."""
    parts = [element.text or ""]
    for child in element:
        if _name(child) not in _SKIP_INLINE:
            parts.append(_text(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def _floats(element: ET.Element) -> list[ET.Element]:
    """Tables and figures nested anywhere inside a paragraph, in document order."""
    found = []
    for child in element:
        if _name(child) in ("fig", "table-wrap"):
            found.append(child)
        elif _name(child) in ("fig-group", "table-wrap-group") or _name(child) not in _SKIP_INLINE:
            found += _floats(child)
    return found


def _float_html(element: ET.Element) -> list[str]:
    label = next((_text(c) for c in element if _name(c) == "label"), "")
    caption = next((_text(c) for c in element if _name(c) == "caption"), "")
    out = []
    if label or caption:
        out.append(f"<p><b>{_esc(label)}</b> {_esc(caption)}</p>")
    if _name(element) == "table-wrap":
        for row in element.iter():
            if _name(row) == "tr":
                cells = [_text(cell) for cell in row if _name(cell) in ("td", "th")]
                if any(cells):
                    out.append(f"<p>{_esc(' | '.join(cells))}</p>")
        for foot in element.iter():
            if _name(foot) == "table-wrap-foot" and _text(foot):
                out.append(f"<p>{_esc(_text(foot))}</p>")
    return out


def _block_html(element: ET.Element, depth: int) -> list[str]:
    """A section, abstract or body in reading order: headings, paragraphs, lists, formulas and floats."""
    out: list[str] = []
    for child in element:
        name = _name(child)
        if name == "title":
            level = min(depth + 1, 4)
            if (title := _text(child)):
                out.append(f"<h{level}>{_esc(title)}</h{level}>")
        elif name == "sec":
            out += _block_html(child, depth + 1)
        elif name in ("p", "disp-formula", "disp-quote", "statement", "def-list"):
            if (text := _text(child)):
                out.append(f"<p>{_esc(text)}</p>")
            for nested in _floats(child):
                out += _float_html(nested)
        elif name == "list":
            for item in child.iter():
                if _name(item) == "list-item" and (text := _text(item)):
                    out.append(f"<p>• {_esc(text)}</p>")
        elif name in ("fig", "table-wrap"):
            out += _float_html(child)
        elif name in ("fig-group", "table-wrap-group"):
            for nested in _floats(child):
                out += _float_html(nested)
    return out


def _refuse_entity(*_args: object) -> None:
    raise ValueError("entity declaration")


def document_html(xml: bytes) -> str:
    # The parent refused `<!ENTITY` in the bytes; a declaration in another encoding is refused here, by the parser.
    scan = expat.ParserCreate()
    scan.EntityDeclHandler = _refuse_entity
    scan.Parse(xml, True)
    root = ET.fromstring(xml)
    parts: list[str] = []
    title = next((e for e in root.iter() if _name(e) == "article-title"), None)
    if title is not None and (text := _text(title)):
        parts.append(f"<h1>{_esc(text)}</h1>")
    front = next((e for e in root if _name(e) == "front"), None)
    for abstract in (front.iter() if front is not None else []):
        if _name(abstract) != "abstract" or abstract.get("abstract-type") in ("graphical", "teaser"):
            continue
        parts.append("<h2>Abstract</h2>")
        if (loose := _text(abstract)) and not any(_name(c) in ("p", "sec") for c in abstract):
            parts.append(f"<p>{_esc(loose)}</p>")
        parts += _block_html(abstract, 2)
    for section in root:
        if _name(section) == "body":
            parts += _block_html(section, 1)
        elif _name(section) == "floats-group":
            for nested in _floats(section):
                parts += _float_html(nested)
    return "\n".join(parts)


def _render_child(source: Path, target: Path, max_pages: int, max_output: int) -> int:
    import pymupdf

    body = document_html(source.read_bytes())
    story = pymupdf.Story(html=body, user_css="body { font-size: 10.5pt; line-height: 1.35; } h1 { font-size: 16pt; }")
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer, "compress")
    page = pymupdf.paper_rect("a4")
    where = page + (_PAGE_MARGIN, _PAGE_MARGIN, -_PAGE_MARGIN, -_PAGE_MARGIN)
    more, pages = True, 0
    while more:
        if pages >= max_pages:
            return PAGES_EXIT_CODE  # stopped before the page past the limit is placed
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    document = pymupdf.open(stream=buffer.getvalue(), filetype="pdf")
    document.subset_fonts()  # a fallback font for one glyph would otherwise be embedded whole
    data = document.tobytes(garbage=3, deflate=True)
    if len(data) > max_output:
        return OUTPUT_EXIT_CODE
    target.write_bytes(data)
    return 0


if __name__ == "__main__":
    import pymupdf

    from deixis.documents.pdf import _watch_memory

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    _watch_memory(int(sys.argv[3]))
    try:
        sys.exit(_render_child(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[4]), int(sys.argv[5])))
    except MemoryError:
        sys.exit(MEMORY_EXIT_CODE)
