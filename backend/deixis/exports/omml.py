"""LaTeX math as Office Math (OMML), so a Word file shows equations Word can edit instead of `$...$` source.

latex2mathml parses the LaTeX into MathML; this module maps the MathML elements it writes onto their OMML twins:
sub- and superscripts, fractions, roots, n-ary operators with their limits (∑ ∏ ∫ … take the following term as their
body), limits under or over an operator (max, min, lim), accents, matrices and case arrays, and plain runs for
identifiers, numbers, operators and text. Anything else is refused: `to_omml` returns None and the caller keeps the
LaTeX as text, so a formula is never dropped or half-converted.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from latex2mathml.converter import convert

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_MML = "{http://www.w3.org/1998/Math/MathML}"
_NARY = frozenset("∑∏∐∫∬∭∮∯∰⋃⋂⋁⋀⨁⨂⨀")
# Word draws an accent from the combining character; MathML carries the spacing one.
_ACCENTS = {"^": "\u0302", "ˆ": "\u0302", "~": "\u0303", "˜": "\u0303", "¯": "\u0305", "‾": "\u0305", "˙": "\u0307",
            "¨": "\u0308", "ˇ": "\u030c", "´": "\u0301", "`": "\u0300", "→": "\u20d7", "⃗": "\u20d7"}
_UPRIGHT = {"normal": "p", "bold": "b", "italic": "i", "bold-italic": "bi"}


class Unsupported(Exception):
    """A MathML element this mapping does not cover."""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _run(text: str, style: str | None = None, normal: bool = False) -> str:
    if not text:
        return ""
    props = "<m:nor/>" if normal else (f'<m:sty m:val="{style}"/>' if style else "")
    return f'<m:r>{f"<m:rPr>{props}</m:rPr>" if props else ""}<m:t xml:space="preserve">{_esc(text)}</m:t></m:r>'


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(_MML)


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).replace(" ", " ")


def _e(content: str) -> str:
    return f"<m:e>{content}</m:e>"


def _nary_base(element: ET.Element) -> str | None:
    """The operator character when `element` is an n-ary operator with limits (∑_{i}^{n})."""
    if _tag(element) in ("msub", "msup", "msubsup", "munder", "mover", "munderover"):
        base = element[0]
        if _tag(base) == "mo" and _text(base).strip() in _NARY:
            return _text(base).strip()
    if _tag(element) == "mo" and _text(element).strip() in _NARY:
        return _text(element).strip()
    return None


def _nary(element: ET.Element, char: str, body: str) -> str:
    kind = _tag(element)
    sub = sup = ""
    if kind in ("msub", "munder"):
        sub = _node(element[1])
    elif kind in ("msup", "mover"):
        sup = _node(element[1])
    elif kind in ("msubsup", "munderover"):
        sub, sup = _node(element[1]), _node(element[2])
    location = "undOvr" if kind.startswith("mu") or char in "∑∏∐⋃⋂⋁⋀⨁⨂⨀" else "subSup"
    props = (f'<m:naryPr><m:chr m:val="{_esc(char)}"/><m:limLoc m:val="{location}"/>'
             f'{"" if sub else "<m:subHide m:val=\"1\"/>"}{"" if sup else "<m:supHide m:val=\"1\"/>"}</m:naryPr>')
    return f"<m:nary>{props}<m:sub>{sub}</m:sub><m:sup>{sup}</m:sup>{_e(body)}</m:nary>"


def _row(children: list[ET.Element]) -> str:
    """A sequence of siblings; an n-ary operator takes the sibling after it as its body."""
    out: list[str] = []
    index = 0
    while index < len(children):
        child = children[index]
        char = _nary_base(child)
        if char is not None:
            body = _node(children[index + 1]) if index + 1 < len(children) else ""
            out.append(_nary(child, char, body))
            index += 2
            continue
        out.append(_node(child))
        index += 1
    return "".join(out)


def _node(element: ET.Element) -> str:
    kind = _tag(element)
    children = list(element)
    if kind in ("math", "mrow", "mstyle", "mpadded", "semantics", "menclose"):
        return _row(children)
    if kind == "mi":
        text = _text(element)
        variant = element.get("mathvariant")
        style = _UPRIGHT.get(variant or "", None) if variant else ("p" if len(text) > 1 else None)
        return _run(text, style)
    if kind == "mn":
        return _run(_text(element))
    if kind == "mo":
        text = _text(element)
        return _run(text, "p" if text.isalpha() else None)
    if kind in ("mtext", "ms"):
        return _run(_text(element), normal=True)
    if kind == "mspace":
        return _run(" ")
    if kind == "mphantom":
        return ""
    if kind == "msub":
        if _tag(children[0]) == "mo" and _text(children[0]).isalpha():  # \max_{x}, \lim_{n}
            return f"<m:limLow>{_e(_node(children[0]))}<m:lim>{_node(children[1])}</m:lim></m:limLow>"
        return f"<m:sSub>{_e(_node(children[0]))}<m:sub>{_node(children[1])}</m:sub></m:sSub>"
    if kind == "msup":
        return f"<m:sSup>{_e(_node(children[0]))}<m:sup>{_node(children[1])}</m:sup></m:sSup>"
    if kind == "msubsup":
        return (f"<m:sSubSup>{_e(_node(children[0]))}<m:sub>{_node(children[1])}</m:sub>"
                f"<m:sup>{_node(children[2])}</m:sup></m:sSubSup>")
    if kind == "mfrac":
        bar = '<m:fPr><m:type m:val="noBar"/></m:fPr>' if element.get("linethickness") in ("0", "0pt", "0em") else ""
        return f"<m:f>{bar}<m:num>{_node(children[0])}</m:num><m:den>{_node(children[1])}</m:den></m:f>"
    if kind == "msqrt":
        return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>{_e(_row(children))}</m:rad>'
    if kind == "mroot":
        return f"<m:rad><m:deg>{_node(children[1])}</m:deg>{_e(_node(children[0]))}</m:rad>"
    if kind == "munder":
        return f"<m:limLow>{_e(_node(children[0]))}<m:lim>{_node(children[1])}</m:lim></m:limLow>"
    if kind == "mover":
        mark = children[1]
        if element.get("accent") == "true" and _tag(mark) == "mo" and len(_text(mark)) == 1:
            char = _ACCENTS.get(_text(mark), _text(mark))
            return f'<m:acc><m:accPr><m:chr m:val="{_esc(char)}"/></m:accPr>{_e(_node(children[0]))}</m:acc>'
        return f"<m:limUpp>{_e(_node(children[0]))}<m:lim>{_node(children[1])}</m:lim></m:limUpp>"
    if kind == "munderover":
        lower = f"<m:limLow>{_e(_node(children[0]))}<m:lim>{_node(children[1])}</m:lim></m:limLow>"
        return f"<m:limUpp>{_e(lower)}<m:lim>{_node(children[2])}</m:lim></m:limUpp>"
    if kind == "mtable":
        rows = [row for row in children if _tag(row) in ("mtr", "mlabeledtr")]
        width = max((len(row) for row in rows), default=1)
        cells = "".join("<m:mr>" + "".join(_e(_row(list(cell))) for cell in row)
                        + _e("") * (width - len(row)) + "</m:mr>" for row in rows)
        return (f'<m:m><m:mPr><m:mcs><m:mc><m:mcPr><m:count m:val="{width}"/><m:mcJc m:val="left"/></m:mcPr></m:mc>'
                f"</m:mcs></m:mPr>{cells}</m:m>")
    raise Unsupported(kind)


@lru_cache(maxsize=1024)
def to_omml(latex: str, display: bool = False) -> str | None:
    """`<m:oMath>` (or `<m:oMathPara>` for display math) for the LaTeX between the dollar signs, or None."""
    try:
        root = ET.fromstring(convert(latex))
        body = _node(root)
    except Exception:  # latex2mathml rejects the input, or the MathML has an element this mapping does not cover
        return None
    # latex2mathml passes a command it does not know through as text ("\\foo"): keep the LaTeX instead.
    if not body or re.search(r"<m:t[^>]*>[^<]*\\", body):
        return None
    math = f"<m:oMath>{body}</m:oMath>"
    return f"<m:oMathPara>{math}</m:oMathPara>" if display else math
