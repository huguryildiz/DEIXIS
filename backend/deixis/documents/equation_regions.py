"""Numbered display equations on PDF pages with a text layer, the image sent for each, and the checks a reading of that
image must pass before it replaces the page's lines (the Mathpix route, D40).

Detector: a line ending in an equation number `(n)` at its column's right margin (`arxiv_source.number_line`, shared with
the source route). Without a source the equation's lines are found by geometry only: lines that are not prose, in the
same column, within 1.5 body line heights of the region, stopping at a prose line, a heading, a line crossing the column
gutter or 12 lines. A non-prose line just below the region that belongs to no other number leaves the region unclear, and
it is refused. Rotated pages and pages with a table caption are skipped, and so are OCR pages (they have no text layer).

Crop: the union of the region's lines plus 2 pt, with the number cut out of the image. It is refused when any other
text-layer span, a drawing other than a horizontal rule, or an image overlaps it, or when it crosses the column gutter:
only the equation's own lines leave the computer. It is rendered at 200 dpi, lowered (not below 120) to stay within
2,000 px a side and 4 Mpx, and refused above 2 MB as base64.

Gate: necessary checks, not proof. Letters and digits, their script level (raised, lowered, on the line), relation and
operator signs and the number of fraction bars must agree between the reading and the text layer. A wrong reading with
the same multisets passes (swapped subscripts across symbols, a script moved between symbols on one level, grouping).
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf

from deixis.documents import arxiv_source, inline_math, math_reader, pdf, pdf_child

GAP_LINES = 1.5
MAX_REGION_LINES = 12
PAD = 2.0
MARGIN_SHARE = 0.06  # a number line ends within this share of the page width of its column's right edge
DPI, MIN_DPI = 200, 120
MAX_SIDE, MAX_PIXELS = 2000, 4_000_000
MAX_BASE64 = 2 * 1024 * 1024
RULE_HEIGHT = 1.5  # a drawing this thin is a horizontal rule (a fraction bar, a vinculum)
SCRIPT_SIZE = 0.85  # type below this share of the body size is a script when it sits off its line's baseline
SCRIPT_SHIFT = 0.12  # share of the body size a script's baseline sits above or below its line's
MIN_CONFIDENCE = 0.5  # a placement filter on Mathpix's own confidence, not an accuracy threshold
NUMBER_TAIL = re.compile(r"\s*\(\d{1,3}[a-z]?\)\s*$")

# Every sign the gate compares, text-layer character → its class. A math sign (Unicode Sm/So) the table does not know, on
# either side, refuses the region (`unknown_sign`): an unknown sign is never dropped from the comparison (Sol r1).
SIGNS = {"=": "=", "+": "+", "-": "−", "−": "−", "<": "<", ">": ">", "≤": "≤", "⩽": "≤", "≥": "≥", "⩾": "≥", "≠": "≠",
         "±": "±", "∓": "∓", "×": "×", "÷": "÷", "≈": "≈", "≡": "≡", "·": "·", "⋅": "·", "/": "/", "∕": "/",
         "∑": "∑", "∏": "∏", "∐": "∐", "∫": "∫", "∬": "∬", "∭": "∭", "∮": "∮", "⋃": "⋃", "⋂": "⋂", "⨁": "⨁", "⨂": "⨂",
         "⋁": "⋁", "⋀": "⋀", "⨆": "⨆", "√": "√", "∂": "∂", "∇": "∇", "∞": "∞", "∈": "∈", "∉": "∉", "⊂": "⊂", "⊆": "⊆",
         "⊃": "⊃", "⊇": "⊇", "∪": "∪", "∩": "∩", "→": "→", "←": "←", "↔": "↔", "⇒": "⇒", "⇐": "⇐", "⇔": "⇔", "↦": "↦",
         "∀": "∀", "∃": "∃", "¬": "¬", "∧": "∧", "∨": "∨", "⊕": "⊕", "⊗": "⊗", "∘": "∘", "∝": "∝", "∼": "∼", "~": "∼",
         "≃": "≃", "≅": "≅", "≪": "≪", "≫": "≫", "∗": "∗", "*": "∗", "∖": "∖", "⊥": "⊥", "∥": "∥", "≜": "≜", "≔": "≔"}
SIGN_COMMANDS = {"leq": "≤", "le": "≤", "leqslant": "≤", "geq": "≥", "ge": "≥", "geqslant": "≥", "neq": "≠", "ne": "≠",
                 "pm": "±", "mp": "∓", "times": "×", "div": "÷", "approx": "≈", "equiv": "≡", "cdot": "·",
                 "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮", "bigcup": "⋃",
                 "bigcap": "⋂", "bigoplus": "⨁", "bigotimes": "⨂", "bigvee": "⋁", "bigwedge": "⋀", "bigsqcup": "⨆", "sqrt": "√",
                 "partial": "∂", "nabla": "∇", "infty": "∞", "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
                 "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩", "to": "→", "rightarrow": "→", "leftarrow": "←",
                 "gets": "←", "leftrightarrow": "↔", "Rightarrow": "⇒", "implies": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
                 "iff": "⇔", "mapsto": "↦", "forall": "∀", "exists": "∃", "neg": "¬", "lnot": "¬", "wedge": "∧", "land": "∧",
                 "vee": "∨", "lor": "∨", "oplus": "⊕", "otimes": "⊗", "circ": "∘", "propto": "∝", "sim": "∼", "simeq": "≃",
                 "cong": "≅", "ll": "≪", "gg": "≫", "ast": "∗", "setminus": "∖", "perp": "⊥", "parallel": "∥",
                 "triangleq": "≜", "coloneqq": "≔"}
# Signs neither side compares: delimiters and primes, which the text layer and a reading set in too many ways.
UNCOMPARED = {"|", "‖", "∣", "′", "″", "^", "`", "°"}
# Commands that print no compared letter or sign: type faces, accents, spacing, dots and delimiters. Any other command a
# reading uses that is not a letter, operator name, sign or fraction is an unknown sign.
SILENT_COMMANDS = {"mathrm", "mathit", "mathbf", "mathsf", "mathtt", "mathcal", "mathbb", "mathfrak", "mathscr", "boldsymbol",
                   "bm", "text", "textrm", "textit", "textbf", "textsf", "operatorname", "displaystyle", "textstyle",
                   "scriptstyle", "scriptscriptstyle", "quad", "qquad", "hat", "bar", "vec", "dot", "ddot", "tilde",
                   "widetilde", "widehat", "overline", "underline", "check", "breve", "acute", "grave", "mathring", "prime",
                   "ldots", "cdots", "dots", "vdots", "ddots", "dotsc", "dotsb", "dotsm", "langle", "rangle", "lvert", "rvert",
                   "lVert", "rVert", "vert", "Vert", "mid", "lceil", "rceil", "lfloor", "rfloor", "lbrace", "rbrace",
                   "phantom", "hphantom", "vphantom", "mathop", "nolimits", "kern", "mkern", "mspace", "mathstrut", "strut",
                   "boxed", "overset", "underset", "stackrel", "binom", "dbinom", "tbinom", "ell", "hbar", "imath", "jmath",
                   "mathbin", "mathrel", "mathord", "mathpunct", "mathopen", "mathclose", "colon", "space", "enspace",
                   "thinspace", "negthinspace", "medspace", "thickspace"}
LETTER_COMMANDS = {"ell": "ℓ", "hbar": "ℏ", "imath": "ı", "jmath": "ȷ"}
# Operators whose scripts a display sets as limits above or below: their script letters may stand on any level.
LIMIT_OPERATORS = {"sum", "prod", "coprod", "bigcup", "bigcap", "bigoplus", "bigotimes", "bigvee", "bigwedge", "bigsqcup",
                   "underbrace", "overbrace"}
LIMIT_NAMES = {"lim", "liminf", "limsup", "max", "min", "sup", "inf", "argmax", "argmin", "det", "Pr"}
OPERATOR_NAMES = inline_math.WORDS | LIMIT_NAMES | {"sinh", "cosh", "tanh", "coth", "cot", "sec", "csc", "arcsin", "arccos",
                                                    "arctan", "deg", "ker", "gcd", "lg", "hom", "exp", "log"}
FRACTIONS = {"frac", "dfrac", "tfrac", "cfrac", "over"}
DELIMITER_SIZERS = {"left", "right", "middle", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr",
                    "Biggl", "Biggr", "bigm", "Bigm", "biggm", "Biggm"}
# What a sizer may size and still print no compared sign: brackets and bars, which neither side compares. Anything else it
# sizes (`\big/`, `\Big\backslash`, an arrow) is read as the sign it prints (Sol r2).
PURE_DELIMITERS = {"(", ")", "[", "]", "\\{", "\\}", "|", "\\|", ".", "<", ">", "\\langle", "\\rangle", "\\lvert", "\\rvert",
                   "\\lVert", "\\rVert", "\\vert", "\\Vert", "\\lfloor", "\\rfloor", "\\lceil", "\\rceil", "\\lbrace", "\\rbrace",
                   "\\lgroup", "\\rgroup", "\\lbrack", "\\rbrack", "\\mid"}
TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|[^\s]", re.S)
GREEK = math_reader.GREEK


# ---- the detector and the crop -----------------------------------------------------------------------------------------
def _lines(page: pymupdf.Page, body_size: float) -> list[dict[str, Any]]:
    """The page's lines from the extraction's own blocks, keyed (block, line) as `_place` expects."""
    out = []
    height = page.rect.height
    for b, block in enumerate(pdf._blocks(page, spans=True)):
        kind = pdf._block_kind(block, height, body_size)
        for ln, (masked, box, spans) in enumerate(zip(block["masked"], block["line_boxes"], block["line_spans"])):
            out.append({"key": (b, ln), "text": masked.strip(), "box": box, "spans": spans, "kind": kind})
    return out


def _columns(lines: list[dict], width: float) -> tuple[float | None, list[tuple[float, float, float]]]:
    """The gutter (None on a one-column page) and each column as (left, right, right edge of its prose)."""
    prose = [line for line in lines if arxiv_source.is_prose(line["text"])]
    mid = width / 2
    left = [line for line in prose if line["box"][2] <= mid + 4]
    right = [line for line in prose if line["box"][0] >= mid - 4]
    if len(left) >= 3 and len(right) >= 3:
        gutter = (max(line["box"][2] for line in left) + min(line["box"][0] for line in right)) / 2
        return gutter, [(0.0, gutter, max(line["box"][2] for line in left)), (gutter, width, max(line["box"][2] for line in right))]
    edge = max((line["box"][2] for line in prose or lines), default=width)
    return None, [(0.0, width, edge)]


def _column(box: tuple, columns: list[tuple[float, float, float]]) -> int:
    centre = (box[0] + box[2]) / 2
    return next((i for i, (lo, hi, _) in enumerate(columns) if lo <= centre < hi), len(columns) - 1)


def _crosses(box: tuple, gutter: float | None) -> bool:
    return gutter is not None and box[0] < gutter < box[2]


def _overlap(a: tuple, b: tuple) -> float:
    return min(a[3], b[3]) - max(a[1], b[1])


def _touches(a: tuple, b: tuple) -> bool:
    """Boxes that share area or, for a zero-height rule, a stretch of edge."""
    return a[0] < b[2] and a[2] > b[0] and a[1] <= b[3] and a[3] >= b[1]


def _union(boxes: list) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _content_spans(line: dict, cut: tuple | None) -> list[dict]:
    """The line's spans left of the equation number; a span holding text and the number loses the number."""
    if cut is None:
        return line["spans"]
    out = []
    for span in line["spans"]:
        if span["box"][0] >= cut[0] - 0.5:
            continue
        if span["box"][2] > cut[0] + 0.5:
            span = span | {"text": NUMBER_TAIL.sub("", span["text"]), "box": (span["box"][0], span["box"][1], cut[0], span["box"][3])}
        if span["text"].strip():
            out.append(span)
    return out


def _marks(spans_by_line: list[list[dict]], body: float) -> tuple[list[list[str]], Counter]:
    """Each letter and digit with its script level, and the signs, of the text layer's spans."""
    chars, signs = [], Counter()
    for spans in spans_by_line:
        full = [s for s in spans if s["size"] >= SCRIPT_SIZE * body] or spans
        weight = Counter()
        for s in full:
            weight[round(s["y"], 1)] += len(s["text"].strip())
        base = weight.most_common(1)[0][0] if weight else 0.0
        for s in spans:
            level = "base"
            if s["size"] < SCRIPT_SIZE * body:
                if s["y"] < base - SCRIPT_SHIFT * body:
                    level = "raised"
                elif s["y"] > base + SCRIPT_SHIFT * body:
                    level = "lowered"
            masked = bool(inline_math.SYMBOL_FONT.search(s.get("font") or ""))
            for c in s["text"]:
                c = math_reader._character(c)
                if c.isalnum() and not masked:
                    chars.append([c, level])
                elif c in SIGNS:
                    signs[SIGNS[c]] += 1
                elif _math_sign(c):
                    signs["?" + c] += 1  # a sign the table does not know: the gate refuses the region
    return chars, signs


def _math_sign(c: str) -> bool:
    """A character that prints a mathematical sign (Unicode Sm or So) and is not one the gate leaves uncompared."""
    return len(c) == 1 and unicodedata.category(c) in ("Sm", "So") and c not in UNCOMPARED


def _render(page: pymupdf.Page, box: tuple, cut: list, dpi: int) -> bytes:
    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, clip=pymupdf.Rect(box), alpha=False)
    for rect in cut:
        area = (pymupdf.Rect(rect) * matrix).irect & pix.irect
        if not area.is_empty:
            pix.set_rect(area, (255, 255, 255))
    return pix.tobytes("png")


def crop_dpi(box: tuple) -> int | None:
    """The resolution a crop is rendered at, decided from its box before rendering; None when even 120 dpi is too large."""
    width, height = max(1e-6, box[2] - box[0]), max(1e-6, box[3] - box[1])
    dpi = min(DPI, MAX_SIDE * 72 / width, MAX_SIDE * 72 / height, math.sqrt(MAX_PIXELS / (width * height)) * 72)
    return int(dpi) if dpi >= MIN_DPI else None


def render_crop(path: Path, recipe: dict[str, Any]) -> bytes:
    """The crop again from the stored PDF and its recipe (page, box, dpi, cut), in a bounded child; the stored hash says
    whether it is the same."""
    return pdf_child.run("render_crop", str(path), recipe)


def _render_crop(path: str, recipe: dict[str, Any]) -> bytes:
    with pymupdf.open(path, filetype="pdf") as doc:
        return _render(doc[recipe["page"] - 1], tuple(recipe["box"]), recipe["cut"], recipe["dpi"])


def detect(path: Path, skip_pages: set[int] | frozenset = frozenset(), render: bool = True) -> list[dict[str, Any]]:
    """Every numbered display equation found, with its crop or the reason it has none. `render=False` only counts
    (the Settings estimate). It runs in a bounded child (`pdf_child`)."""
    return pdf_child.run("detect", str(path), sorted(skip_pages), render)


def _detect(path: str, skip_pages: list[int], render: bool) -> list[dict[str, Any]]:
    skip_pages = set(skip_pages)
    found: list[dict[str, Any]] = []
    with pymupdf.open(path, filetype="pdf") as doc:
        layouts = []
        for index in range(min(doc.page_count, pdf.MAX_PAGES)):
            page = doc[index]
            layouts.append((index, None, page.rect.height, pdf._blocks(page)))
        body = pdf._body_size(layouts) or 10.0
        for index in range(min(doc.page_count, pdf.MAX_PAGES)):
            page = doc[index]
            if index + 1 in skip_pages or page.rotation or math_reader.TABLE_CAPTION.search(page.get_text()):
                continue
            found += _page_regions(page, index + 1, body, render)
    return found


def _page_regions(page: pymupdf.Page, number: int, body: float, render: bool) -> list[dict[str, Any]]:
    lines = _lines(page, body)
    if not lines:
        return []
    width = page.rect.width
    gutter, columns = _columns(lines, width)
    prose_heights = [line["box"][3] - line["box"][1] for line in lines if arxiv_source.is_prose(line["text"])]
    lh = statistics.median(prose_heights) if prose_heights else body * 1.2
    numbers = {}
    for i, line in enumerate(lines):
        m = arxiv_source.number_line(line["text"])
        if not m or _crosses(line["box"], gutter):
            continue
        col = _column(line["box"], columns)
        lo, hi, edge = columns[col]
        only = arxiv_source.NUMBER_ONLY.match(line["text"]) is not None
        if line["box"][2] < edge - MARGIN_SHARE * width or (only and line["box"][0] < (lo + hi) / 2):
            continue
        numbers[i] = (m.group(1), only, col)
    out, taken = [], set()
    for i, (n, only, col) in numbers.items():
        region = _region(lines, i, only, col, columns, gutter, lh, set(numbers), taken)
        if region is None:
            continue
        taken |= set(region["content"])
        out.append(_candidate(page, number, n, lines, i, only, region, gutter, lh, body, numbers, render))
    return out


def _region(lines, i, only, col, columns, gutter, lh, numbers, taken) -> dict | None:
    number = lines[i]
    in_column = lambda k: _column(lines[k]["box"], columns) == col  # noqa: E731
    if only:
        content = [k for k, line in enumerate(lines) if k != i and k not in taken and k not in numbers and in_column(k)
                   and not _crosses(line["box"], gutter) and not arxiv_source.is_prose(line["text"])
                   and _overlap(line["box"], number["box"]) >= 0.5 * min(line["box"][3] - line["box"][1], number["box"][3] - number["box"][1])]
        if not content:
            return None
    else:
        content = [i]
    while len(content) < MAX_REGION_LINES:
        top = min(lines[k]["box"][1] for k in content)
        bottom = max(lines[k]["box"][3] for k in content)
        band = sorted((k for k, line in enumerate(lines) if k not in content and k != i and line["box"][3] > top - GAP_LINES * lh
                       and line["box"][1] < bottom and (in_column(k) or _crosses(line["box"], gutter))),
                      key=lambda k: -lines[k]["box"][3])
        added, stop = 0, False
        for k in band:
            line = lines[k]
            if (k in taken or k in numbers or _crosses(line["box"], gutter) or arxiv_source.is_prose(line["text"])
                    or line["kind"] == "heading" or pdf.HEADING.fullmatch(line["text"])):
                stop = True
                break
            content.append(k)
            added += 1
            if len(content) >= MAX_REGION_LINES:
                break
        if stop or not added:
            break
    bottom = max(lines[k]["box"][3] for k in content + [i])
    below = [k for k, line in enumerate(lines) if k not in content and k != i and in_column(k)
             and bottom - 0.5 <= line["box"][1] < bottom + GAP_LINES * lh]
    unclear = any(not arxiv_source.is_prose(lines[k]["text"]) and lines[k]["kind"] != "heading" and k not in numbers
                  and not any(_overlap(lines[k]["box"], lines[j]["box"]) > 0 for j in numbers) for k in below)
    return {"content": sorted(content), "unclear": unclear}


def _candidate(page, page_number, n, lines, i, only, region, gutter, lh, body, numbers, render) -> dict[str, Any]:
    number = lines[i]
    if only:
        cut = tuple(number["box"])
    else:
        hits = [r for r in page.search_for(f"({n})", clip=pymupdf.Rect(number["box"]))]
        cut = tuple(max(hits, key=lambda r: r.x1)) if hits else (number["box"][2] - 0.5, number["box"][1], number["box"][2], number["box"][3])
    content = region["content"]
    spans = [_content_spans(lines[k], cut if k == i else None) for k in content]
    boxes = [s["box"] for line in spans for s in line]
    keys = sorted({lines[k]["key"] for k in content} | {number["key"]})
    item: dict[str, Any] = {"page": page_number, "n": n, "number": list(number["key"]), "lines": [list(k) for k in keys],
                            "text_layer": "\n".join("".join(s["text"] for s in line).strip() for line in spans)}
    if not boxes:
        return item | {"refused": "region_unclear"}
    box = _union(boxes)
    box = (box[0] - PAD, box[1] - PAD, box[2] + PAD, box[3] + PAD)
    item["box"] = [round(v, 2) for v in box]
    if region["unclear"]:
        return item | {"refused": "region_unclear"}
    own = {tuple(round(v, 2) for v in s["box"]) for k in set(content) | {i} for s in lines[k]["spans"]}
    if _crosses(box, gutter) or _other_text(page, box, own):
        return item | {"refused": "crop_has_other_text"}
    rules, other = _drawings(page, box)
    if other or any(_touches(tuple(info["bbox"]), box) for info in page.get_image_info()):
        return item | {"refused": "crop_has_other_content"}
    chars, signs = _marks(spans, body)
    item |= {"chars": chars, "signs": dict(signs), "rules": _fraction_rules(rules, boxes, lh)}
    dpi = crop_dpi(box)
    if dpi is None:
        return item | {"refused": "crop_too_large"}
    recipe = {"page": page_number, "box": item["box"], "dpi": dpi, "cut": [[round(v, 2) for v in cut]] if _touches(cut, box) else []}
    item["crop"] = recipe
    if not render:
        return item
    png = _render(page, tuple(item["box"]), recipe["cut"], dpi)
    if len(png) * 4 / 3 > MAX_BASE64:
        return item | {"refused": "crop_too_large"}
    return item | {"png": png, "crop_sha256": hashlib.sha256(png).hexdigest()}


def _other_text(page: pymupdf.Page, box: tuple, own: set) -> bool:
    inner = (box[0] + 0.5, box[1] + 0.5, box[2] - 0.5, box[3] - 0.5)
    for block in page.get_text("dict", flags=pdf.TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() and tuple(round(v, 2) for v in span["bbox"]) not in own and _touches(tuple(span["bbox"]), inner):
                    return True
    return False


def _drawings(page: pymupdf.Page, box: tuple) -> tuple[list[tuple], bool]:
    """Horizontal rules inside the box, and whether any other drawing touches it."""
    rules, other = [], False
    for path in page.get_drawings():
        rect = tuple(path["rect"])
        if not _touches(rect, box):
            continue
        if rect[3] - rect[1] <= RULE_HEIGHT and rect[0] >= box[0] - 0.5 and rect[2] <= box[2] + 0.5:
            rules.append(rect)
        else:
            other = True
    return rules, other


def _fraction_rules(rules: list[tuple], boxes: list[tuple], lh: float) -> int:
    """Rules with the equation's text above and below them: fraction bars."""
    def spans_side(rule, above):
        return any(b[0] < rule[2] and b[2] > rule[0]
                   and (rule[1] - GAP_LINES * lh <= b[3] <= rule[1] + 1 if above else rule[3] - 1 <= b[1] <= rule[3] + GAP_LINES * lh)
                   for b in boxes)
    return sum(1 for rule in rules if spans_side(rule, True) and spans_side(rule, False))


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ---- the gate ----------------------------------------------------------------------------------------------------------
def tidy(latex: str) -> str:
    """One line, numbering commands removed, and `&`/`\\\\` outside an environment wrapped in `aligned`."""
    latex = re.sub(r"\\(nonumber|notag)\b", " ", latex)
    latex = re.sub(r"\s+", " ", latex).strip()
    if ("&" in latex.replace("\\&", "") or "\\\\" in latex) and "\\begin" not in latex:
        latex = f"\\begin{{aligned}}{latex}\\end{{aligned}}"
    return latex


def latex_marks(latex: str) -> dict[str, Any]:
    """What a LaTeX expression prints, by a small brace-aware walk: letters and digits with their script level (`fixed`),
    letters set as an operator's limits, whose level a display decides (`free`), the signs, and the fraction count."""
    latex = re.sub(r"\\begin\{(array|tabular)\}\s*\{[^{}]*\}", " ", latex)
    latex = re.sub(r"\\(begin|end)\{[^{}]*\}|\\(hspace|vspace)\*?\{[^{}]*\}|\\\\\[[^\]]*\]", " ", latex)
    tokens = TOKEN.findall(latex)
    out: dict[str, Any] = {"fixed": Counter(), "free": Counter(), "signs": Counter(), "fractions": 0}

    def emit(c: str, level: str, loose: bool) -> None:
        c = math_reader._character(c)
        if c.isalnum():
            if loose:
                out["free"][c] += 1
            else:
                out["fixed"][(c, level)] += 1
        elif c in SIGNS and c != "~":  # a LaTeX `~` is a space, not a sign
            out["signs"][SIGNS[c]] += 1
        elif _math_sign(c):
            out["signs"]["?" + c] += 1

    def run(i: int, level: str, loose: bool, stop: str) -> int:
        limits = False
        while i < len(tokens) and tokens[i] != stop:
            i, limits = item(i, level, loose, limits)
        return i + 1

    def atom(i: int, level: str, loose: bool) -> int:
        if i >= len(tokens):
            return i
        if tokens[i] == "{":
            return run(i + 1, level, loose, "}")
        return item(i, level, loose, False)[0]

    def item(i: int, level: str, loose: bool, limits: bool) -> tuple[int, bool]:
        token = tokens[i]
        if token in ("^", "_"):
            inner = level if level != "base" else ("raised" if token == "^" else "lowered")
            return atom(i + 1, inner, loose or limits), limits
        if token == "{":
            return run(i + 1, level, loose, "}"), False
        if token.startswith("\\") and len(token) > 1 and token[1].isalpha():
            name = token[1:].rstrip("*")
            if name in GREEK:
                emit(GREEK[name], level, loose)
            elif name in LETTER_COMMANDS:
                emit(LETTER_COMMANDS[name], level, loose)
            elif name in OPERATOR_NAMES:
                for c in name:
                    emit(c, level, loose)
                return i + 1, name in LIMIT_NAMES
            elif name in LIMIT_OPERATORS or name == "limits":
                if name in SIGN_COMMANDS:
                    out["signs"][SIGN_COMMANDS[name]] += 1  # ∑ against ∏ is a different equation (Sol r1)
                return i + 1, True
            elif name in SIGN_COMMANDS and name != "sqrt":
                out["signs"][SIGN_COMMANDS[name]] += 1
            elif name in FRACTIONS:
                out["fractions"] += 1
            elif name in DELIMITER_SIZERS:
                if i + 1 >= len(tokens):
                    out["signs"]["?\\" + name] += 1  # a sizer with nothing to size: refused, not a crash (Sol code r3)
                    return i + 1, False
                if tokens[i + 1] in PURE_DELIMITERS:
                    return i + 2, False  # a sized bracket or bar prints no compared sign
                return item(i + 1, level, loose, False)[0], False  # `\big/`: the sized sign is compared like any other
            elif name == "sqrt":
                out["signs"]["√"] += 1
                if i + 1 < len(tokens) and tokens[i + 1] == "[":
                    return run(i + 2, level, True, "]"), False  # a root's index is set small; its level is not compared
            elif name not in SILENT_COMMANDS:
                out["signs"]["?\\" + name] += 1  # a command the gate cannot compare: the region is refused
            return i + 1, False
        if token.startswith("\\"):
            return i + 1, False  # a control symbol: spacing (`\,` `\;` `\!` `\ `), escaped braces
        if token == "~":
            return i + 1, False  # a tie: a space, not a sign
        emit(token, level, loose)
        return i + 1, False

    i = 0
    while i < len(tokens):
        i = run(i, "base", False, "\0")
    return out


def gate(candidate: dict[str, Any], response: dict[str, Any] | None) -> dict[str, Any]:
    """{"latex", "reason", "checks"}: the LaTeX to place, or the first check it failed (`reason`)."""
    checks: dict[str, bool] = {}
    latex = (response or {}).get("latex_styled")
    if not isinstance(latex, str) or not latex.strip() or "$" in latex or re.search(r"\\(tag|label)\b", latex) \
            or NUMBER_TAIL.search(latex):
        return {"latex": None, "reason": "not_single_equation", "checks": checks}
    latex = tidy(latex)
    confidence = (response or {}).get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < MIN_CONFIDENCE:
        return {"latex": latex, "reason": "low_confidence", "checks": checks}
    checks["katex"] = not arxiv_source.katex_unknown(latex)
    if not checks["katex"]:
        return {"latex": latex, "reason": "katex_unknown", "checks": checks}
    marks = latex_marks(latex)
    text = Counter((math_reader._character(c), level) for c, level in candidate.get("chars", []))
    text_letters = Counter(c for c, _ in text.elements())
    latex_letters = Counter(c for c, _ in marks["fixed"].elements()) + marks["free"]
    checks["letters"] = bool(text_letters) and text_letters == latex_letters
    if not checks["letters"]:
        return {"latex": latex, "reason": "letters_differ", "checks": checks}
    rest = text - marks["fixed"]
    checks["scripts"] = marks["fixed"] <= text and Counter(c for c, _ in rest.elements()) == marks["free"]
    if not checks["scripts"]:
        return {"latex": latex, "reason": "script_differs", "checks": checks}
    signs = Counter(candidate.get("signs", {}))
    checks["known_signs"] = not any(k.startswith("?") for k in (signs + marks["signs"]))
    if not checks["known_signs"]:
        return {"latex": latex, "reason": "unknown_sign", "checks": checks}
    checks["operators"] = signs == marks["signs"]
    if not checks["operators"]:
        return {"latex": latex, "reason": "operators_differ", "checks": checks}
    checks["fractions"] = candidate.get("rules", 0) == marks["fractions"]
    if not checks["fractions"]:
        return {"latex": latex, "reason": "fractions_differ", "checks": checks}
    return {"latex": latex, "reason": None, "checks": checks}
