"""Numbered display equations on PDF pages with a text layer, the image sent for each, and the checks a reading of that
image must pass before it replaces the page's lines (the Mathpix route, D40, and the answer model's, D113).

Detector: a line ending in an equation number `(n)` at its column's right margin (`arxiv_source.number_line`, shared with
the source route), unless the text before the number is a sentence citing it ("The problem in (41)"). Without a source
the equation's lines are found by geometry only: lines that are not prose, in the same column, within 1.5 body line
heights of the region, at most 12. Growth upward stops at prose (also a row of fragments the text layer split around
inline math, read from a paragraph margin), a lead-in ("as follows:", "where κ is given by" at a paragraph margin), a
heading, a line crossing the column gutter, or another equation's line (another number's row, an earlier region); lines
below that stop which start inside the region (a denominator) still join. A lower limit in script type centred under one
of the region's operators (`t=1` under a sum) joins it. A line just above or below the region that is none of these, nor
text at a paragraph margin, leaves the region unclear, and it is refused: the region may miss a part of the equation.
On a single-column page whose prose the text layer split around inline math, the split lines do not make two columns.
Rotated pages and pages with a table caption are skipped, and so are OCR pages (they have no text layer): a caption may
name an unruled table whose rows the finder would take for displays.

Crop: the union of the region's lines plus 2 pt, with the number cut out of the image. Another text-layer span that only
reaches into the 2 pt padding, clear of the equation's own type, is whited out when its line is prose, a number or held
by another equation's region; any other span overlapping the crop, a drawing other than a horizontal rule, an image, or
a crop across the column gutter refuses it: only the equation's own lines leave the computer. It is rendered at 200 dpi,
lowered (not below 120) to stay within 2,000 px a side and 4 Mpx, and refused above 2 MB as base64.

Measured (2026-10-24, model-free, `notes/2026-10-24-equation-finder/frozen.json` against `baseline.json`): on 452
numbered equations of 34 arXiv papers placed by their LaTeX source, crops with exactly the source's lines rose from 185 to
274; crops with other lines fell from 25 to 7 (lines with no letters, which the source placement leaves out). It shows the
regions, not how well a model reads them.

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
CUT_CLEARANCE = 0.75  # pt between a whited-out span and the equation's type: 2 px at 200 dpi, more than the rounding
DOC_MARGIN_LINES = 3  # prose lines in the document that must share a left edge for it to count as a margin
MARGIN_SLACK = 1.5  # pt a line's left edge may sit from a paragraph margin and still start there
TEXT_START = re.compile(r"[A-Za-z]+")
ABBREVIATION = re.compile(r"(?:i\.\s?e|e\.\s?g|viz|cf)\.?\s*[,:]?")
LEAD_IN = re.compile(r"[A-Za-z][A-Za-z\s,.;:'’-]*")
# Words a sentence under a display holds and a display's constraint row does not. Articles and prepositions are not
# among them: they stand in a constraint row too ("The sum of the powers ≤ P").
SENTENCE_CUES = {"we", "is", "are", "was", "be", "if", "which", "that", "where", "then", "thus", "hence", "so", "gives",
                 "give", "yields", "find", "have", "has", "holds", "hold", "since", "let", "it", "this", "these", "when",
                 "can", "will", "follows", "obtain", "get", "see", "note"}
# Words that make a line with no relation sign text ("We also have", "or equivalently,"), never a display's row (D139).
TEXT_CUES = SENTENCE_CUES | {"also", "there", "exists", "exist", "satisfies", "satisfy", "equivalently", "becomes", "denotes",
                             "denote"}
RELATION = re.compile(r"[=<>≤≥≠≈≡∈∉⊂⊆⩽⩾∼≃≅∝]")
DISPLAY_WORD = re.compile(r"(arg)?(min|max|minimi[sz]e|maximi[sz]e)|subject|sup|inf|lim")
LIMIT_RELATION = re.compile(r"[=∈≤≥<>⊂⊆∉]")  # a lower limit names its index: i=1, k∈S, x≥0
FUNCTION_NAME = re.compile(r"(arc)?(sin|cos|tan|cot|sec|csc)h?")

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
    sides = _sides(lines, width)
    if sides is not None:
        gutter, left, right = sides
        # Lines crossing the gutter among the side lines (inline math between two halves of one prose line): one column
        # the text layer split. A full-width title or abstract sits above the two columns, not among their lines.
        top, bottom = min(line["box"][1] for line in left + right), max(line["box"][3] for line in left + right)
        crossing = [line for line in lines if line["box"][0] < gutter < line["box"][2]
                    and top <= (line["box"][1] + line["box"][3]) / 2 <= bottom]
        if len(crossing) < min(len(left), len(right)):
            return gutter, [(0.0, gutter, max(line["box"][2] for line in left)), (gutter, width, max(line["box"][2] for line in right))]
    edge = max((line["box"][2] for line in prose or lines), default=width)
    return None, [(0.0, width, edge)]


def _split_by(content: list[int], lines: list[dict], sides: tuple[float, list[dict], list[dict]]) -> bool:
    gutter = sides[0]
    boxes = [lines[k]["box"] for k in content]
    return any(box[0] < gutter for box in boxes) and any(box[0] >= gutter for box in boxes)


def _sides(lines: list[dict], width: float) -> tuple[float, list[dict], list[dict]] | None:
    """A gutter between prose on either half of the page (three lines each side), and those lines; else None."""
    prose = [line for line in lines if arxiv_source.is_prose(line["text"])]
    mid = width / 2
    left = [line for line in prose if line["box"][2] <= mid + 4]
    right = [line for line in prose if line["box"][0] >= mid - 4]
    if len(left) < 3 or len(right) < 3:
        return None
    return (max(line["box"][2] for line in left) + min(line["box"][0] for line in right)) / 2, left, right


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
        # The document's paragraph margins and indents: left edges that prose lines on its pages share (an indent may
        # start a single paragraph on a page).
        starts = Counter(round(box[0]) for *_, blocks in layouts for block in blocks
                         for text, box in zip(block["masked"], block["line_boxes"]) if arxiv_source.is_prose(text.strip()))
        margins = [x for x, count in starts.items() if count >= DOC_MARGIN_LINES]
        for index in range(min(doc.page_count, pdf.MAX_PAGES)):
            page = doc[index]
            if index + 1 in skip_pages or page.rotation:
                continue
            if math_reader.TABLE_CAPTION.search(page.get_text()):
                continue
            found += _page_regions(page, index + 1, body, render, margins)
    return found


def _page_regions(page: pymupdf.Page, number: int, body: float, render: bool,
                  doc_margins: list[float] = ()) -> list[dict[str, Any]]:
    lines = _lines(page, body)
    if not lines:
        return []
    width = page.rect.width
    gutter, columns = _columns(lines, width)
    sides = _sides(lines, width)
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
        if line["box"][2] < edge - MARGIN_SHARE * width or (only and line["box"][0] < (lo + hi) / 2) or _citation(line["text"][:m.start()]):
            continue
        numbers[i] = (m.group(1), only, col)
    margins = [m + list(doc_margins) for m in _margins(lines, columns)]
    regions, taken, claimed = {}, set(), []
    for i, (n, only, col) in numbers.items():
        region = _region(lines, i, only, col, columns, gutter, lh, set(numbers), taken, margins[col], claimed, body)
        if region is None:
            continue
        # On a page taken for one column with prose on either half, a region with lines starting on either side of where
        # the gutter would be may join two column equations: it is unclear.
        if gutter is None and sides is not None and _split_by(region["content"], lines, sides):
            region["unclear"] = True
        taken |= set(region["content"])
        claimed.append(_union([lines[k]["box"] for k in region["content"] + [i]]))
        regions[i] = region
    # A line another region holds, a number line, or text: what a crop may white out when it only grazes the crop's edge.
    held = {k for region in regions.values() for k in region["content"]} | set(numbers)
    out, text = [], page.get_text("dict", flags=pdf.TEXT_FLAGS)["blocks"]  # read once: every crop checks it
    for i, region in regions.items():
        n, only, col = numbers[i]
        others = (held - set(region["content"]) - {i}) | {k for k, line in enumerate(lines) if arxiv_source.is_prose(line["text"])}
        out.append(_candidate(page, number, n, lines, i, only, region, gutter, lh, body, numbers, render, others, text))
    return out


def _margins(lines: list[dict], columns: list[tuple[float, float, float]]) -> list[list[float]]:
    """Per column, the left edges at least two prose lines share: the paragraph margin and its indents."""
    out = []
    for col in range(len(columns)):
        starts = Counter(round(line["box"][0]) for line in lines
                         if arxiv_source.is_prose(line["text"]) and _column(line["box"], columns) == col)
        out.append([x for x, count in starts.items() if count >= 2])
    return out


def _starts_text(line: dict, margin: list[float], letters: int = 2) -> bool:
    """A line set at a paragraph margin that opens with a word (not an operator name): a line of text, not a display's."""
    m = TEXT_START.match(line["text"])
    return (m is not None and len(m.group(0)) >= letters and m.group(0) not in OPERATOR_NAMES
            and any(abs(line["box"][0] - x) <= MARGIN_SLACK for x in margin))


def _lead_in(line: dict, margin: list[float]) -> bool:
    """The end of the sentence that leads into a display ("as follows:", "and", "where κ is given by", "x ≥ y, we have"):
    a line at a paragraph margin that opens with a word and holds only words and punctuation, or that ends in a colon or
    in a lower-case word (not a function name or a vowelless name; inline math after it is passed over)."""
    text = line["text"]
    if ABBREVIATION.fullmatch(text):  # "i.e.," on a line of its own, wherever it is set (D139)
        return True
    if not any(abs(line["box"][0] - x) <= MARGIN_SLACK for x in margin):
        return False
    # After the word only punctuation, a symbol's name (α′) or a reference (`(59)`).
    last = re.search(r"([A-Za-z]+)(?:[^A-Za-z0-9=<>≤≥+−]|\(\d{1,3}[a-z]?\))*$", text)
    # A word, not a variable's name: lower case, with a vowel (`nv`, `drv` are names), and no function name.
    ends_in_word = (last is not None and last.group(1).islower() and re.search(r"[aeiouy]", last.group(1)) is not None
                    and not _function_name(last.group(1)))
    if _starts_text(line, margin):
        return LEAD_IN.fullmatch(text) is not None or text.endswith((":", ",")) or (ends_in_word and len(last.group(1)) >= 2)
    words = [w for w in re.findall(r"[a-z]{3,}", text) if re.search(r"[aeiouy]", w) and not _function_name(w)]
    if re.search(r"[.;]\s+[A-Z][a-z]{2,}", text):  # a sentence ends and the next begins: "…;0). Then, for any"
        return True
    return text.endswith(":") or (ends_in_word and (re.search(r"[.,;]\s", text) is not None
                                                    or (len(last.group(1)) >= 3 and len(words) >= 2)))


def _row_lead_in(lines: list[dict], k: int, in_column, margin: list[float], sentence: bool = False) -> bool:
    """The line, or the row it sits in read left to right from a paragraph margin, is a lead-in (`_lead_in`): a sentence
    the text layer split around inline math ("that α", "∗ e", "≤ 1 we have"). With `sentence`, only one that reads as a
    sentence (ends in a colon or comma, or holds two words) or carries on the prose line above it: another lone word
    ("minimize" after "as follows:") may be a display's first row, so it stops the growth but leaves the region unclear."""
    row = _row(lines, k, in_column)
    texts = [lines[k]["text"]] + ([" ".join(lines[j]["text"] for j in row)] if len(row) > 1 else [])
    for text, box in zip(texts, [lines[k]["box"], lines[row[0]]["box"]]):
        if _lead_in({"text": text, "box": box}, margin) and (not sentence or _sentence(text) or _continues(lines, k, in_column)):
            return True
    return False


def _at_margin(line: dict, margin: list[float]) -> bool:
    return any(abs(line["box"][0] - x) <= MARGIN_SLACK for x in margin)


def _continues(lines: list[dict], k: int, in_column) -> bool:
    """The prose line just above line k ends without a stop or a colon: k carries on its sentence ("… the receiver
    counts" / "and"). After "as follows:" the next line may open a display ("minimize")."""
    box = lines[k]["box"]
    height = box[3] - box[1]
    above = [j for j, line in enumerate(lines) if j != k and in_column(j) and box[1] - height <= line["box"][3] <= box[1] + 0.5]
    if not above:
        return False
    j = max(above, key=lambda j: lines[j]["box"][3])
    return arxiv_source.is_prose(lines[j]["text"]) and not lines[j]["text"].rstrip().endswith((".", ":", ";", "!", "?"))


def _sentence(text: str) -> bool:
    """Reads as a sentence, not a display's label ("maximize rate"): it does not open with an optimisation word, and it
    ends in a colon or comma or holds two words."""
    words = _words(text)
    return not _display_word(text) and (text.rstrip().endswith((":", ",")) or len(words) >= 2)


def _display_word(text: str) -> bool:
    """Opens with a word that starts or continues an optimisation display at the margin ("minimize", "subject to")."""
    m = TEXT_START.match(text)
    return m is not None and DISPLAY_WORD.fullmatch(m.group(0).lower()) is not None or re.match(r"s\.\s*t\b", text) is not None


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z]{2,}", text) if re.search(r"[aeiouy]", w.lower()) and not _function_name(w)]


def _bare_relation(text: str) -> bool:
    """A line with a relation sign and no word a sentence would hold ("average transmit power ≤ P", "sum of transmit
    powers ≤ P"): it may be a constraint row of the display above even when it reads as words; "It is clear that A = 1"
    and "For D = 4, we find" are sentences."""
    if RELATION.search(text) is None:
        return False
    return not {w.lower() for w in re.findall(r"[A-Za-z]+", text)} & SENTENCE_CUES


def _half_row(a: tuple, b: tuple) -> bool:
    """Two boxes on one row: they overlap vertically by at least half the smaller height."""
    return _overlap(a, b) >= 0.5 * min(a[3] - a[1], b[3] - b[1])


def _text_below(lines: list[dict], k: int, in_column, margin: list[float]) -> bool:
    """A line just below a display is text, not a further row of it: it starts at a paragraph margin with a word
    ("where", "In this case"; with no relation sign: not "average power ≤ P") or is a prose row. The caller still refuses a row opening with an optimisation
    display's word ("minimize", "subject to g(x) ≤ 0")."""
    text = lines[k]["text"]
    cue = _at_margin(lines[k], margin) and bool({w.lower() for w in re.findall(r"[A-Za-z]+", text)} & TEXT_CUES)
    return (_starts_text(lines[k], margin, 3) or cue) and not RELATION.search(text) or _row_prose(lines, k, in_column, margin)


def _cue_word(line: dict, margin: list[float]) -> bool:
    """A lone sentence word at a paragraph margin ("where", "then", "thus"): the end of a lead-in, never a display's row."""
    return _at_margin(line, margin) and re.sub(r"[\s,.:;]", "", line["text"]).lower() in SENTENCE_CUES


def _row_text(lines: list[dict], k: int, in_column) -> str:
    return " ".join(lines[j]["text"] for j in _row(lines, k, in_column))


def _row(lines: list[dict], k: int, in_column) -> list[int]:
    """The column's lines sharing at least half of line k's height, left to right."""
    box = lines[k]["box"]
    return sorted((j for j, line in enumerate(lines) if in_column(j)
                   and _overlap(line["box"], box) >= 0.5 * min(box[3] - box[1], line["box"][3] - line["box"][1])),
                  key=lambda j: lines[j]["box"][0])


def _citation(before: str) -> bool:
    """The text before a line's `(n)` is a sentence that cites the equation ("= x. The problem in (41)"): it ends in a
    word and reads as prose (a full stop before a capital, or two words)."""
    last = re.search(r"([A-Za-z]+)\W*$", before)
    if last is None or not last.group(1).islower() or not re.search(r"[aeiouy]", last.group(1)) or _function_name(last.group(1)):
        return False
    words = [w for w in re.findall(r"[a-z]{3,}", before) if re.search(r"[aeiouy]", w) and not _function_name(w)]
    return re.search(r"[.;]\s+[A-Z]", before) is not None or len(words) >= 2


def _function_name(word: str) -> bool:
    return word in OPERATOR_NAMES or FUNCTION_NAME.fullmatch(word) is not None


def _row_prose(lines: list[dict], k: int, in_column, margin: list[float]) -> bool:
    """The line's row (the column's lines sharing at least half its height), read left to right, starts at a paragraph
    margin and holds prose words: a prose line the text layer split around inline math. Function names are not words."""
    row = _row(lines, k, in_column)
    if len(row) < 2 or not any(abs(lines[row[0]]["box"][0] - x) <= MARGIN_SLACK for x in margin):
        return False
    words = [w for j in row for w in arxiv_source.PROSE_WORD.findall(lines[j]["text"]) if not _function_name(w)]
    return len(words) >= arxiv_source.PROSE_WORDS


def _hanging(lines: list[dict], k: int, content: list[int], body: float, lh: float, in_column) -> bool:
    """A line in script type centred just under a narrow line of the region (an operator such as a sum): that operator's
    lower limit (`t=1` under a sum), which belongs to the display above it. Without a relation sign (`∞`, `N`) and centred
    over a narrow line outside the region too, it is taken for the upper limit of the operator below and left out."""
    line = lines[k]
    box = line["box"]
    if not line["spans"] or any(s["size"] >= SCRIPT_SIZE * body for s in line["spans"]):
        return False
    centre = (box[0] + box[2]) / 2

    def under(j: int) -> bool:  # `k` sits centred under line j
        other = lines[j]["box"]
        return (other[2] - other[0] <= 2 * lh and abs((other[0] + other[2]) / 2 - centre) <= 0.25 * (other[2] - other[0]) + 1.5
                and -0.5 <= box[1] - other[3] <= lh)

    def over(j: int) -> bool:  # `k` sits centred over line j
        other = lines[j]["box"]
        return (other[2] - other[0] <= 2 * lh and abs((other[0] + other[2]) / 2 - centre) <= 0.25 * (other[2] - other[0]) + 1.5
                and -0.5 <= other[1] - box[3] <= lh)

    return any(under(j) for j in content) and (LIMIT_RELATION.search(line["text"]) is not None
                                                or not any(j not in content and j != k and in_column(j) and over(j) for j in range(len(lines))))


def _claimed(line: dict, claimed: list[tuple], numbers: set, lines: list[dict], i: int, in_column) -> bool:
    """The line belongs to another equation: it shares a row with another number line of its column, or lies on an
    earlier region."""
    box = line["box"]
    if any(j != i and in_column(j) and _overlap(lines[j]["box"], box) >= 0.5 * min(box[3] - box[1], lines[j]["box"][3] - lines[j]["box"][1])
           for j in numbers):
        return True
    return any(_touches(box, (c[0], c[1] + 0.5, c[2], c[3] - 0.5)) for c in claimed)


def _region(lines, i, only, col, columns, gutter, lh, numbers, taken, margin=(), claimed=(), body=10.0) -> dict | None:
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
    ceiling = None  # the bottom of a line that ended the growth upward: nothing starting above it joins
    while len(content) < MAX_REGION_LINES:
        top = min(lines[k]["box"][1] for k in content)
        bottom = max(lines[k]["box"][3] for k in content)
        band = sorted((k for k, line in enumerate(lines) if k not in content and k != i and line["box"][3] > top - GAP_LINES * lh
                       and line["box"][1] < bottom and (ceiling is None or line["box"][1] >= ceiling - 0.5)
                       and (in_column(k) or _crosses(line["box"], gutter))),
                      key=lambda k: -lines[k]["box"][3])
        added, raised = 0, False
        for k in band:
            line = lines[k]
            if (k in taken or k in numbers or _crosses(line["box"], gutter) or arxiv_source.is_prose(line["text"])
                    or line["kind"] == "heading" or pdf.HEADING.fullmatch(line["text"]) or _row_lead_in(lines, k, in_column, margin)
                    or _row_prose(lines, k, in_column, margin) or _claimed(line, claimed, numbers, lines, i, in_column)
                    or (_at_margin(line, margin) and _continues(lines, k, in_column))):
                # Lines below it that start inside the region (a denominator under the number's row) may still join.
                ceiling, raised = line["box"][3] if ceiling is None else max(ceiling, line["box"][3]), True
                break
            content.append(k)
            added += 1
            if len(content) >= MAX_REGION_LINES:
                break
        if not added and not raised:
            break
    span = _union([lines[k]["box"] for k in content + [i]])
    content += [k for k, line in enumerate(lines) if k not in content and k != i and k not in taken and k not in numbers
                and span[1] <= line["box"][1] <= span[3] + lh and in_column(k) and _hanging(lines, k, content + [i], body, lh, in_column)]
    # A line on one of the region's rows that holds no word (a limit `τ=0` or `t` left of a sum the growth stopped at) is a
    # part of the display: it joins, and the rows it brings are checked again (D139). A line with a word stays out.
    for _ in range(MAX_REGION_LINES):
        rows = [lines[k]["box"] for k in content + [i]]
        joins = [k for k in range(len(lines)) if k not in content and k != i and in_column(k) and k not in taken
                 and k not in numbers and not _claimed(lines[k], claimed, numbers, lines, i, in_column)
                 and any(_half_row(lines[k]["box"], box) for box in rows) and not _crosses(lines[k]["box"], gutter)
                 and lines[k]["kind"] not in ("heading", "page_number", "running_head") and not _words(lines[k]["text"])]
        if not joins or len(content) + len(joins) > MAX_REGION_LINES:
            break
        content += joins
    # The lines just above the region must be text, a heading or another equation's: anything else may be a part of
    # this equation the growth stopped short of (a line the heading pattern caught, `V Qe(t)`), and the crop would miss it.
    # A row opening with an optimisation word ("maximize average rate", "subject to …") is never taken for text.
    top = min(lines[k]["box"][1] for k in content + [i])
    above = [k for k, line in enumerate(lines) if k not in content and k != i and in_column(k)
             and top - GAP_LINES * lh < line["box"][3] <= top + 0.5]
    unclear_above = any(not (lines[k]["kind"] == "heading" or _cue_word(lines[k], margin) or k in taken or k in numbers
                             or _claimed(lines[k], claimed, numbers, lines, i, in_column)
                             or (arxiv_source.is_prose(lines[k]["text"]) or _row_lead_in(lines, k, in_column, margin, sentence=True)
                                 or _row_prose(lines, k, in_column, margin)) and not _display_word(_row_text(lines, k, in_column)))
                        for k in above)
    bottom = max(lines[k]["box"][3] for k in content + [i])
    below = [k for k, line in enumerate(lines) if k not in content and k != i and in_column(k)
             and bottom - 0.5 <= line["box"][1] < bottom + GAP_LINES * lh]
    unclear = any(not (lines[k]["kind"] == "heading" or k in numbers
                       or any(j != i and in_column(j) and _overlap(lines[k]["box"], lines[j]["box"]) > 0 for j in numbers)
                       or (arxiv_source.is_prose(lines[k]["text"]) or _text_below(lines, k, in_column, margin))
                       and not _display_word(_row_text(lines, k, in_column)) and not _bare_relation(_row_text(lines, k, in_column)))
                  for k in below)
    # A line beside the region on one of its rows (a label left of the display, "maximize average rate  u = v (1)") may be
    # a part of it the growth left out as prose; only another equation's line or a number may stand there.
    rows = [lines[k]["box"] for k in content + [i]]
    beside = any(k not in content and k != i and in_column(k) and k not in taken and k not in numbers
                 and not _claimed(lines[k], claimed, numbers, lines, i, in_column)
                 and any(_half_row(lines[k]["box"], box) for box in rows)
                 for k in range(len(lines)))
    # A line of the region set at the paragraph margin and opening with a word is text ("where u = v", "If x = y"),
    # not a display's name set flush left ("KAB = …"), unless it opens an optimisation display ("minimize").
    text_inside = any(_starts_text(lines[k], margin) and re.match(r"(?=[A-Za-z]*[aeiouyAEIOUY])[A-Z]?[a-z]+\b", lines[k]["text"])
                      and not _display_word(_row_text(lines, k, in_column)) for k in content)
    return {"content": sorted(content), "unclear": unclear or unclear_above or beside or text_inside}


def _candidate(page, page_number, n, lines, i, only, region, gutter, lh, body, numbers, render, others=frozenset(),
               text=None) -> dict[str, Any]:
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
    core = _union(boxes)
    box = (core[0] - PAD, core[1] - PAD, core[2] + PAD, core[3] + PAD)
    item["box"] = [round(v, 2) for v in box]
    if region["unclear"]:
        return item | {"refused": "region_unclear"}
    own = {tuple(round(v, 2) for v in s["box"]) for k in set(content) | {i} for s in lines[k]["spans"]}
    owner = {tuple(round(v, 2) for v in s["box"]): k for k, line in enumerate(lines) for s in line["spans"]}
    grazing = _other_text(page, box, own, text)
    if _crosses(box, gutter) or not all(_cuttable(span, core, owner, others) for span in grazing):
        return item | {"refused": "crop_has_other_text"}
    rules, other = _drawings(page, box)
    images = [tuple(info["bbox"]) for info in page.get_image_info() if _touches(tuple(info["bbox"]), box)]
    # Some PDFs paint a fraction bar as a thin image rather than a drawn rule (D139): an image counts only as a bar, a wide
    # thin one with the equation's type above and below it; any other image refuses the crop.
    bars = [rect for rect in images if _rule(rect, box) and rect[2] - rect[0] >= max(2.0, 4 * (rect[3] - rect[1]))]
    if other or len(bars) < len(images) or _fraction_rules(bars, boxes, lh) < len(bars):
        return item | {"refused": "crop_has_other_content"}
    rules += bars
    # A bar in or just below the crop with the equation's type above it and none below is a fraction whose denominator
    # the region left out (D139).
    below = (box[0], box[1], box[2], box[3] + GAP_LINES * lh)
    near = _drawings(page, below)[0] + [tuple(info["bbox"]) for info in page.get_image_info()
                                        if _touches(tuple(info["bbox"]), below) and _rule(tuple(info["bbox"]), below)]
    held = set(content) | {i}
    between = lambda rule: any(k not in held and line["box"][0] < rule[2] and line["box"][2] > rule[0]  # noqa: E731
                               and core[3] - 0.5 <= line["box"][1] < rule[1] for k, line in enumerate(lines))
    # Type is above or below a rule by its box's middle: a box may cross the rule (a numerator's descent, a radicand).
    over = lambda rule: any(b[0] < rule[2] and b[2] > rule[0] and (b[1] + b[3]) / 2 < rule[1]  # noqa: E731
                            and b[3] >= rule[1] - GAP_LINES * lh for b in boxes)
    under = lambda rule: any(b[0] < rule[2] and b[2] > rule[0] and (b[1] + b[3]) / 2 > rule[3]  # noqa: E731
                             and b[1] <= rule[3] + GAP_LINES * lh for b in boxes)
    if any(over(rule) and not under(rule) and not between(rule) for rule in near):
        return item | {"refused": "region_unclear"}  # (a bar with another line between it and the crop is that line's)
    chars, signs = _marks(spans, body)
    item |= {"chars": chars, "signs": dict(signs), "rules": _fraction_rules(rules, boxes, lh)}
    dpi = crop_dpi(box)
    if dpi is None:
        return item | {"refused": "crop_too_large"}
    cuts = ([cut] if _touches(cut, box) else []) + grazing
    recipe = {"page": page_number, "box": item["box"], "dpi": dpi, "cut": [[round(v, 2) for v in c] for c in cuts]}
    item["crop"] = recipe
    if not render:
        return item
    png = _render(page, tuple(item["box"]), recipe["cut"], dpi)
    if len(png) * 4 / 3 > MAX_BASE64:
        return item | {"refused": "crop_too_large"}
    return item | {"png": png, "crop_sha256": hashlib.sha256(png).hexdigest()}


def _other_text(page: pymupdf.Page, box: tuple, own: set, blocks: list | None = None) -> list[tuple]:
    """The boxes of text-layer spans other than the region's own that overlap the crop, up to its edge."""
    out = []
    for block in blocks if blocks is not None else page.get_text("dict", flags=pdf.TEXT_FLAGS)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() and tuple(round(v, 2) for v in span["bbox"]) not in own and _inside_any(tuple(span["bbox"]), box):
                    out.append(tuple(span["bbox"]))
    return out


def _inside_any(a: tuple, b: tuple) -> bool:
    """Boxes that share area: a span ending on the crop's edge puts no ink in it, one past the edge by any amount may."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _cuttable(span: tuple, core: tuple, owner: dict, others: set) -> bool:
    """Another span may be whited out of the crop only when it lies in the crop's padding, at least `CUT_CLEARANCE` from
    the equation's own type (the white box is rounded out to whole pixels), and belongs to a line another equation holds, a number line or prose. Anything else refuses the crop: it may be
    a part of this equation the region missed."""
    clear = (core[0] - CUT_CLEARANCE, core[1] - CUT_CLEARANCE, core[2] + CUT_CLEARANCE, core[3] + CUT_CLEARANCE)
    return not _touches(span, clear) and owner.get(tuple(round(v, 2) for v in span)) in others


def _rule(rect: tuple, box: tuple) -> bool:
    """A horizontal rule within the box's width (a fraction bar, a vinculum)."""
    return rect[3] - rect[1] <= RULE_HEIGHT and rect[0] >= box[0] - 0.5 and rect[2] <= box[2] + 0.5


def _drawings(page: pymupdf.Page, box: tuple) -> tuple[list[tuple], bool]:
    """Horizontal rules inside the box, and whether any other drawing touches it."""
    rules, other = [], False
    for path in page.get_drawings():
        rect = tuple(path["rect"])
        if not _touches(rect, box):
            continue
        if _rule(rect, box):
            rules.append(rect)
        else:
            other = True
    return rules, other


def _spans_side(rule: tuple, boxes: list[tuple], lh: float, above: bool) -> bool:
    """The equation's text stands right above (or below) the rule."""
    return any(b[0] < rule[2] and b[2] > rule[0]
               and (rule[1] - GAP_LINES * lh <= b[3] <= rule[1] + 1 if above else rule[3] - 1 <= b[1] <= rule[3] + GAP_LINES * lh)
               for b in boxes)


def _fraction_rules(rules: list[tuple], boxes: list[tuple], lh: float) -> int:
    """Rules with the equation's text above and below them: fraction bars."""
    return sum(1 for rule in rules if _spans_side(rule, boxes, lh, True) and _spans_side(rule, boxes, lh, False))


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


def gate(candidate: dict[str, Any], response: dict[str, Any] | None, require_confidence: bool = True) -> dict[str, Any]:
    """{"latex", "reason", "checks"}: the LaTeX to place, or the first check it failed (`reason`). The answer model's
    reading (D113) has no confidence, so its gate skips that one check (`require_confidence=False`)."""
    checks: dict[str, bool] = {}
    latex = (response or {}).get("latex_styled")
    if not isinstance(latex, str) or not latex.strip() or "$" in latex or re.search(r"\\(tag|label)\b", latex) \
            or NUMBER_TAIL.search(latex):
        return {"latex": None, "reason": "not_single_equation", "checks": checks}
    latex = tidy(latex)
    confidence = (response or {}).get("confidence")
    if require_confidence and (not isinstance(confidence, (int, float)) or confidence < MIN_CONFIDENCE):
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
