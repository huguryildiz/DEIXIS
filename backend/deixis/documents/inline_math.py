"""Checks for inline math read from a line image, used by `marker_runner.py` inside the Marker environment (D52).

It imports nothing, so it runs in Marker's environment and in DEIXIS's tests alike. Marker keeps the PDF text layer and
reads only lines that carry math again from the page image (surya, math mode). A reading is split into prose and
`<math>` segments and aligned with the text layer's letters and digits: prose must match in order (case ignored), and a
math segment must use exactly the text-layer letters between its neighbouring prose, in order, with stacked sub- and
superscripts allowed either way round. A segment that fails keeps the text layer; a prose mismatch rejects the line.
Characters of symbol fonts whose Unicode mapping is broken (`p`/`q` standing for brackets) are masked and never compared.
"""

from __future__ import annotations

import html
import re

MATH_CHARS = set("=≤≥≠≈∼∝±×÷·∑∏∫√∞∂∇∈∉⊂⊆∪∩∀∃→←↔⇒⇔αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩϵϕℓ′″")
MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|CMBSY|MSBM|MSAM|TeX-math|Math|Symbol|MTSY|MTMI|Euclid|rtxmi|txsy|txmi|stix|MT.?Extra", re.I)
SYMBOL_FONT = re.compile(r"TeX-math[ax]|CMEX", re.I)
MASK = "\x00"
# Kept apart from math_reader.GREEK because this module cannot import DEIXIS.
GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
         "theta": "θ", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "varrho": "ρ",
         "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
         "Theta": "Θ", "Lambda": "Λ", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "Upsilon": "Υ", "ell": "ℓ"}
WORDS = {"max", "min", "log", "ln", "exp", "sin", "cos", "tan", "arg", "Pr", "lim", "sup", "inf", "det", "erf", "mod", "dim"}
FOLD = {"ϵ": "ε", "ϕ": "φ", "µ": "μ"}


def _fold(c: str) -> str:
    return FOLD.get(c, c)


def _keep(c: str) -> bool:
    return c.isalnum()


def _letters(text: str) -> str:
    return "".join(_fold(c) for c in text if _keep(c))


def segment_letters(latex: str) -> set[str]:
    """The letters, digits and Greek a LaTeX segment prints in reading order, and the orders with stacked scripts swapped."""
    def strip(x: str) -> str:
        x = re.sub(r"\\(mathbb|mathcal|mathbf|mathrm|text|textrm|operatorname|boldsymbol|bm|pmb|hat|bar|overline|tilde|mathsf|mathit|rm)\b", "", x)
        x = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK.get(m.group(1), m.group(1) if m.group(1) in WORDS else ""), x)
        return _letters(x)
    sub_sup = re.sub(r"_(\{[^{}]*\}|\w)\^(\{[^{}]*\}|\w)", r"^\2_\1", latex)
    sup_sub = re.sub(r"\^(\{[^{}]*\}|\w)_(\{[^{}]*\}|\w)", r"_\2^\1", latex)
    return {strip(latex), strip(sub_sup), strip(sup_sub)}


def is_mathy(text: str, font: str | None, scripted: bool) -> bool:
    return scripted or bool(MATH_FONT.search(font or "")) or any(c in MATH_CHARS for c in text)


def line_text(spans: list[tuple[str, str | None]]) -> str:
    """A line's text-layer text from (text, font) spans, with symbol-font letters masked."""
    return "".join("".join(MASK if SYMBOL_FONT.search(font or "") and c.isalnum() else c for c in text.replace("\n", " "))
                   for text, font in spans)


def parse_reading(text: str) -> list[tuple[str, str]]:
    """A line reading as [("prose", text) | ("math", latex)]."""
    parts, pos = [], 0
    for m in re.finditer(r"<math[^>]*>([\s\S]*?)</math>", text):
        if m.start() > pos:
            parts.append(("prose", text[pos:m.start()]))
        parts.append(("math", html.unescape(m.group(1))))
        pos = m.end()
    parts.append(("prose", text[pos:]))
    return [(kind, re.sub(r"<[^>]+>", "", value) if kind == "prose" else value) for kind, value in parts if value]


def align(parts: list[tuple[str, str]], sources: list[str]):
    """The first text-layer ordering the reading aligns with, as (pieces, accepted, rejected, source), or None. A piece is
    (latex, start, end): the stretch of `source` the accepted segment replaces."""
    for source in sources:
        found = _align(parts, source)
        if found:
            return found + (source,)
    return None


def _align(parts, source):
    letters = [(_fold(c), i) for i, c in enumerate(source) if _keep(c)]
    seq = "".join(c for c, _ in letters)
    pos, pieces, accepted, rejected = 0, [], 0, 0
    for index, (kind, value) in enumerate(parts):
        if kind == "prose":
            prose = _letters(value)
            if not prose:
                continue
            if pos == len(seq):
                break  # the line image reached past the text-layer line; the rest is not used
            have = seq[pos:pos + len(prose)]
            if have.lower() != prose.lower():
                if prose.lower().startswith(have.lower()) and pos + len(have) == len(seq):
                    pos = len(seq)
                    break
                return None
            pos += len(prose)
            continue
        if pos == len(seq):
            break
        # The segment stands for the text-layer letters up to where the next prose begins.
        following = next((_letters(v) for k, v in parts[index + 1:] if k == "prose" and _letters(v)), None)
        if following is None:
            end = len(seq)
        else:
            end = seq.lower().find(following.lower(), pos)
            if end < 0:
                # the next prose may run past the text-layer line: only its part inside the line counts
                cut = next((len(following) - k for k in range(len(following))
                            if len(following) - k >= 3 and seq.lower().endswith(following[:len(following) - k].lower())), 0)
                if not cut:
                    return None
                end = len(seq) - cut
        stretch = seq[pos:end]
        if not stretch:
            continue  # a segment without letters (a lone operator) is not written
        if stretch in segment_letters(value):
            pieces.append((value, letters[pos][1], letters[end - 1][1] + 1))
            accepted += 1
        else:
            rejected += 1
        pos = end
    if pos != len(seq):
        return None
    return pieces, accepted, rejected


def widen(latex: str, source: str, start: int, end: int) -> tuple[int, int]:
    """Extend a replaced stretch over the symbols the LaTeX starts or ends with (brackets, bars), skipping spaces. A masked
    symbol-font character matches any of them."""
    clean = re.sub(r"\\(left|right|big|Big|bigl|bigr)\b|\\[,;:! ]|\\quad", "", latex).replace("\\{", "(").replace("\\}", ")")
    core = [c for c in clean if not c.isspace() and c not in "{}"]
    alnum = [i for i, c in enumerate(core) if c.isalnum()]
    if not alnum:
        return start, end
    for symbol in reversed(core[:alnum[0]]):
        k = start - 1
        while k >= 0 and source[k] == " ":
            k -= 1
        if k < 0 or source[k] not in (symbol, MASK):
            break
        start = k
    for symbol in core[alnum[-1] + 1:]:
        k = end
        while k < len(source) and source[k] == " ":
            k += 1
        if k >= len(source) or source[k] not in (symbol, MASK):
            break
        end = k + 1
    return start, end


def rewrite(reading: str, orderings: list[list[tuple[str, str | None]]]) -> tuple[list[tuple[str, str]], int, int] | None:
    """A line rebuilt from its text layer and the checked math segments of its reading, as ([("text" | "math", value)],
    accepted, rejected), or None when the reading has no math or does not align with any ordering of the line's
    (text, font) spans."""
    parts = parse_reading(reading)
    if not any(kind == "math" for kind, _ in parts):
        return None
    sources = [line_text(spans) for spans in orderings]
    found = align(parts, sources)
    if found is None:
        return None
    pieces, accepted, rejected, source = found
    plain = "".join(text.replace("\n", " ") for text, _ in orderings[sources.index(source)])  # masked letters restored
    out, cursor = [], 0
    for latex, start, end in pieces:
        start, end = widen(latex, source, start, end)
        if start > cursor:
            out.append(("text", plain[cursor:start]))
        out.append(("math", latex))
        cursor = end
    out.append(("text", plain[cursor:]))
    return out, accepted, rejected
