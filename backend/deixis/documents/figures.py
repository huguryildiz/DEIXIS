"""Figure regions found on PDF pages, so the plain-text view can show a picture of each figure (D58).

A figure is found from its caption: a text block that opens with "Fig. 3.", "Figure 3:", "FIGURE 3 |" or "Fig. 3 Title".
Its region is the images and vector drawings next to the caption (above it, else below it) that overlap the caption's
column, grown to take in the small type set around them (axis labels, legends). The picture is rendered from the PDF page;
nothing is stored and the passage text is unchanged. A figure with no graphics next to its caption, one split across
pages, or a caption worded differently is not found.

An algorithm box is found the same way, from an "Algorithm 5 Title" caption set between two rules (the algorithm and
algorithm2e ruled style); its region runs from the rule above the caption to the next rule below the one under it. Its
picture carries the symbols (accents, primes, subscripts) that the text layer and Marker read as loose characters.

Finding and rendering run in a bounded child process (`pdf_child`), not in the server. A picture is rendered at 160 dpi,
lowered so it holds at most `MAX_PIXELS` pixels: a figure drawn across a 5000 pt page took 655 MB at 160 dpi.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pymupdf

from deixis.documents import pdf_child

ALGORITHM = re.compile(r"^Algorithm\s+(\d{1,3})\b")
RULE_GAP = 6  # the largest distance, in points, between an algorithm caption and the rules around it
CAPTION = re.compile(r"^(?:Fig\.|FIG\.|Figure|FIGURE)\s*(\d{1,3})\s*(?:[.:|—–]|\s(?=[A-Z(]))")
MIN_AREA = 900  # square points; smaller graphics are rules, bullets or logos
GAP = 60  # the largest distance, in points, between a caption and its graphics
REACH = 16  # small type this close to the graphics belongs to the figure
MAX_PAGES = 400
MAX_PIXELS = 4_000_000  # as the equation crops (`equation_regions.MAX_PIXELS`); a letter page at 160 dpi has 2.4 million
# Text lines only: without this, get_text("dict") encodes every picture on the page as a PNG it never uses.
DICT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


def _body_size(page: pymupdf.Page) -> float:
    sizes: dict[float, int] = {}
    for block in page.get_text("dict", flags=DICT_FLAGS)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                key = round(span["size"], 1)
                sizes[key] = sizes.get(key, 0) + len(span["text"].strip())
    return max(sizes, key=sizes.get) if sizes else 0.0


def _is_prose(block: dict, body: float) -> bool:
    """A paragraph of body text: several lines set at the body size."""
    lines = block.get("lines", [])
    sizes = [span["size"] for line in lines for span in line["spans"] if span["text"].strip()]
    return len(lines) >= 2 and bool(sizes) and sum(sizes) / len(sizes) >= body * 0.95


def _grow(page: pymupdf.Page, region: pymupdf.Rect, captions: list[pymupdf.Rect], body: float) -> pymupdf.Rect:
    """Take in text inside the region and small type just around it; paragraphs and captions stay out."""
    blocks = [b for b in page.get_text("dict", flags=DICT_FLAGS)["blocks"]
              if not any(pymupdf.Rect(b["bbox"]).intersects(c) for c in captions) and not _is_prose(b, body)]
    for _ in range(2):
        reach = region + (-REACH, -REACH, REACH, REACH)
        for block in blocks:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    box = pymupdf.Rect(span["bbox"])
                    if not span["text"].strip() or box.is_empty:
                        continue
                    inside = region.contains(box) or (box & region).get_area() >= 0.5 * box.get_area()
                    if inside or (reach.intersects(box) and span["size"] < body * 0.95):
                        region |= box
    return region


def find_figures(path: Path) -> list[dict]:
    """[{"page": 1-based, "label": "3", "bbox": [x0, y0, x1, y1]}] in page order; one entry per figure label."""
    return pdf_child.run("find_figures", str(path))


def _find_figures(path: str) -> list[dict]:
    found, seen = [], set()
    with pymupdf.open(path, filetype="pdf") as doc:
        for index in range(min(doc.page_count, MAX_PAGES)):
            page = doc[index]
            captions = [(pymupdf.Rect(b[:4]), m.group(1)) for b in page.get_text("blocks")
                        if b[6] == 0 and (m := CAPTION.match(b[4].strip()))]
            if not captions:
                continue
            graphics = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
            try:
                graphics += list(page.cluster_drawings())
            except Exception:  # noqa: BLE001 - a page whose drawings cannot be read still offers its images
                pass
            graphics = [g & page.rect for g in graphics if (g & page.rect).get_area() >= MIN_AREA]
            body = _body_size(page)
            barriers = [pymupdf.Rect(b["bbox"]) for b in page.get_text("dict", flags=DICT_FLAGS)["blocks"] if _is_prose(b, body)]
            barriers += [c for c, _ in captions]

            def clear(a: float, b: float, x0: float, x1: float) -> bool:
                """No caption or paragraph lies between heights a and b in this column."""
                return not any(r.x0 < x1 and r.x1 > x0 and r.y0 >= a - 2 and r.y1 <= b + 2 for r in barriers)

            for caption, label in captions:
                if label in seen:
                    continue
                column = [g for g in graphics if g.x0 < caption.x1 and g.x1 > caption.x0]
                above = [g for g in column if g.y1 <= caption.y0 + 4 and caption.y0 - g.y1 < GAP and clear(g.y1, caption.y0, caption.x0, caption.x1)]
                below = [g for g in column if g.y0 >= caption.y1 - 4 and g.y0 - caption.y1 < GAP and clear(caption.y1, g.y0, caption.x0, caption.x1)]
                if above:  # graphics above the caption: the stack of graphics up to the next caption or paragraph
                    region = pymupdf.Rect(max(above, key=lambda g: g.y1))
                    for g in sorted(column, key=lambda g: -g.y1):
                        if g.y1 <= caption.y0 + 4 and g.y1 >= region.y0 - GAP and clear(g.y1, region.y0, region.x0, region.x1):
                            region |= g
                elif below:
                    region = pymupdf.Rect(min(below, key=lambda g: g.y0))
                    for g in sorted(column, key=lambda g: g.y0):
                        if g.y0 >= caption.y1 - 4 and g.y0 <= region.y1 + GAP and clear(region.y1, g.y0, region.x0, region.x1):
                            region |= g
                else:
                    continue
                region = _grow(page, region, [c for c, _ in captions], body) & page.rect
                seen.add(label)
                found.append({"page": index + 1, "label": label, "bbox": [round(v, 1) for v in region]})
    return found


def find_algorithms(path: Path) -> list[dict]:
    """[{"page": 1-based, "label": "algorithm-5", "bbox": [...]}] for each ruled algorithm box, in page order."""
    return pdf_child.run("find_algorithms", str(path))


def _find_algorithms(path: str) -> list[dict]:
    found, seen = [], set()
    with pymupdf.open(path, filetype="pdf") as doc:
        for index in range(min(doc.page_count, MAX_PAGES)):
            page = doc[index]
            captions = [(pymupdf.Rect(b[:4]), m.group(1)) for b in page.get_text("blocks")
                        if b[6] == 0 and (m := ALGORITHM.match(b[4].strip()))]
            if not captions:
                continue
            try:
                drawings = page.get_drawings()
            except Exception:  # noqa: BLE001 - a page whose drawings cannot be read has no ruled boxes
                continue
            rules = [d["rect"] for d in drawings if d["rect"].height < 3 and d["rect"].width >= 60]
            for caption, label in captions:
                column = sorted((r for r in rules if r.x0 < caption.x1 and r.x1 > caption.x0), key=lambda r: r.y0)
                top = [r for r in column if 0 <= caption.y0 - r.y1 <= RULE_GAP]
                under = [r for r in column if 0 <= r.y0 - caption.y1 <= RULE_GAP]
                if label in seen or not top or not under:
                    continue  # running text that opens with "Algorithm 5 …" has no rules around it
                bottom = next((r for r in column if r.y0 > under[0].y1 + 4), None)
                if bottom is None:
                    continue
                # Rules are often zero-height rectangles, which Rect union skips as empty: the corners are taken directly.
                region = pymupdf.Rect(min(top[-1].x0, bottom.x0, caption.x0), top[-1].y0,
                                      max(top[-1].x1, bottom.x1, caption.x1), bottom.y1) & page.rect
                seen.add(label)
                found.append({"page": index + 1, "label": f"algorithm-{label}", "bbox": [round(v, 1) for v in region]})
    return found


def render_figure(path: Path, page: int, bbox: list[float], dpi: int = 160) -> bytes:
    return pdf_child.run("render_figure", str(path), page, list(bbox), dpi)


def _render_figure(path: str, page: int, bbox: list[float], dpi: int) -> bytes:
    with pymupdf.open(path, filetype="pdf") as doc:
        clip = pymupdf.Rect(bbox) + (-4, -4, 4, 4)
        clip &= doc[page - 1].rect
        return doc[page - 1].get_pixmap(clip=clip, dpi=_figure_dpi(clip, dpi)).tobytes("png")


def _pixels(clip: pymupdf.Rect, dpi: int) -> int:
    box = (clip * pymupdf.Matrix(dpi / 72, dpi / 72)).irect  # the pixmap MuPDF makes for this clip
    return box.width * box.height


def _figure_dpi(clip: pymupdf.Rect, dpi: int) -> int:
    """`dpi`, lowered until the picture of `clip` has at most MAX_PIXELS pixels; ValueError when even 1 dpi has more."""
    dpi = max(1, min(dpi, int(math.sqrt(MAX_PIXELS / max(1e-6, clip.width * clip.height)) * 72)))
    while dpi > 1 and _pixels(clip, dpi) > MAX_PIXELS:  # MuPDF rounds the pixmap outward to whole pixels
        dpi -= 1
    if _pixels(clip, dpi) > MAX_PIXELS:
        raise ValueError("figure too large to render")
    return dpi
