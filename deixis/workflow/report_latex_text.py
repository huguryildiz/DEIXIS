"""Plain text escaping and the closed Unicode symbol table (no math parsing)."""

import unicodedata

# Exact keys (84): ≤≥≠≈≡±∓×÷−·⋅°µμ→←↔⇒⇔∞∈∉⊂⊆∪∩∅∑∏∫√∂∇∀∃¬∧∨∝∼≪≫
# αβγδεζηθικλνξπρστυφχψω ΓΔΘΛΞΠΣΥΦΨΩ ϕϵςϑϰϱϖϝ.
# Greek letters with only KaTeX aliases (e.g. omicron/Alpha) stay unmapped.
# Unicode phi/epsilon glyphs: φ -> varphi, ϕ -> phi, ε -> varepsilon, ϵ -> epsilon.
SYMBOLS: dict[str, str] = {
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "≡": r"\equiv",
    "±": r"\pm", "∓": r"\mp", "×": r"\times", "÷": r"\div", "−": "-",
    "·": r"\cdot", "⋅": r"\cdot", "°": r"{^{\circ}}", "µ": r"\mu", "μ": r"\mu",
    "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow", "∞": r"\infty",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊆": r"\subseteq",
    "∪": r"\cup", "∩": r"\cap", "∅": r"\emptyset", "∑": r"\sum",
    "∏": r"\prod", "∫": r"\int", "√": r"\surd", "∂": r"\partial",
    "∇": r"\nabla", "∀": r"\forall", "∃": r"\exists", "¬": r"\neg",
    "∧": r"\wedge", "∨": r"\vee", "∝": r"\propto", "∼": r"\sim",
    "≪": r"\ll", "≫": r"\gg",
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "ν": r"\nu",
    "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma",
    "τ": r"\tau", "υ": r"\upsilon", "φ": r"\varphi", "χ": r"\chi",
    "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Υ": r"\Upsilon",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
    "ϕ": r"\phi", "ϵ": r"\epsilon", "ς": r"\varsigma", "ϑ": r"\vartheta",
    "ϰ": r"\varkappa", "ϱ": r"\varrho", "ϖ": r"\varpi", "ϝ": r"\digamma",
}

ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
    "&": r"\&", "#": r"\#", "^": r"\textasciicircum{}", "_": r"\_",
    "%": r"\%", "~": r"\textasciitilde{}",
}


def is_unmapped(ch: str) -> bool:
    """The ranges are a reporting policy, not a font-coverage guarantee."""
    code = ord(ch)
    if unicodedata.category(ch) == "Cc" and not ch.isspace():
        return True
    return ch not in SYMBOLS and not (code <= 0x017F or 0x2010 <= code <= 0x2027)


class Unmapped:
    """Document-owned occurrence count and first-seen distinct code points."""

    def __init__(self) -> None:
        self.count = 0
        self._points: dict[int, None] = {}

    def add(self, ch: str) -> None:
        self.count += 1
        self._points.setdefault(ord(ch), None)

    def note(self) -> str | None:
        if not self.count:
            return None
        points = ", ".join(f"U+{point:04X}" for point in list(self._points)[:10])
        return f"Unmapped characters: {self.count} occurrences; first code points: {points}."


def symbol_text(ch: str) -> str:
    return r"\ensuremath{" + SYMBOLS[ch] + "}" if ch in SYMBOLS else ch


def symbol_math(ch: str) -> str:
    return SYMBOLS.get(ch, ch)


def escape_text(text: str, unmapped: Unmapped | None = None) -> str:
    """Escape every saved control sequence; retain boundary whitespace for joining."""
    out: list[str] = []
    i = 0
    whitespace = False
    while i < len(text):
        ch = text[i]
        if ch.isspace() and ch != "\u00a0":
            if not whitespace:
                out.append(" ")
            whitespace = True
            i += 1
            continue
        if unicodedata.category(ch) == "Cc":
            if unmapped is not None:
                unmapped.add(ch)
            i += 1
            continue
        whitespace = False
        if unmapped is not None and is_unmapped(ch):
            unmapped.add(ch)
        if ch == "\\":
            end = i
            while end < len(text) and text[end] == "\\":
                end += 1
            count = end - i
            escaped_dollar = end < len(text) and text[end] == "$" and count % 2 == 1
            out.append(ESCAPES["\\"] * (count - int(escaped_dollar)))
            if escaped_dollar:
                out.append(ESCAPES["$"])
            i = end + int(escaped_dollar)
            continue
        if ch == '"':
            out.append("``" if i == 0 or text[i - 1].isspace() or text[i - 1] in "([{"
                       else "''")
        elif ch == "\u00a0":
            out.append("~")
        elif ch in SYMBOLS:
            out.append(symbol_text(ch))
        else:
            out.append(ESCAPES.get(ch, ch))
        i += 1
    return "".join(out)
