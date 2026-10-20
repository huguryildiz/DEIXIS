"""Character helpers shared by the equation routes, and the label of PDFs Marker read before it was removed (D113).

Marker, the optional local equation reader of D52, is gone: display equations are now read by the answer model from page
crops (`workflow/equations.py`). A PDF whose current text is an earlier Marker reading keeps it (D45); `MATH_VERSION` is
the suffix that names such a reading, and `text_source = 'marker'` stays on its passages.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# The suffix of an extraction Marker 1.10.2 read (D52, D54). Nothing writes it any more; it only names earlier readings.
MATH_VERSION = "marker-1.10.2-math-v2"
# A table caption opening a line: "TABLE 1 | …" (Frontiers), "TABLE I" (IEEE), "Table 2. …" (Elsevier, Springer). A sentence
# that starts with "Table 1 shows" does not match.
TABLE_CAPTION = re.compile(r"^(?:TABLE|Table)\s+(?:[IVXL]+|[A-Z]?\d{1,3})\s*(?:$|[.:|—–-])", re.M)

GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
         "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
         "varpi": "π", "rho": "ρ", "varrho": "ρ", "sigma": "σ", "varsigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
         "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
         "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "ell": "ℓ"}
SAME_CHARACTER = {"µ": "μ", "∆": "Δ", "ǫ": "ε", "ϵ": "ε", "ϑ": "θ", "ϕ": "φ", "ϱ": "ρ", "ϖ": "π"}


def _character(c: str) -> str:
    c = unicodedata.normalize("NFKC", c)
    return SAME_CHARACTER.get(c, c)


def _letters(text: str) -> Counter:
    return Counter(c for c in map(_character, text) if c.isalnum())


def latex_letters(latex: str) -> Counter:
    """The letters and digits a LaTeX expression prints: command names, environment names and \\tag numbers removed,
    Greek commands turned into their letters."""
    latex = re.sub(r"\\(begin|end)\{[^}]*\}|\\tag\*?\{[^}]*\}|\\operatorname\*?", " ", latex)
    latex = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK.get(m.group(1), " "), latex)
    return _letters(latex)
