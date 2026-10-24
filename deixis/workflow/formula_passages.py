"""Bring a full-text source's most formula-dense passage forward when the question asks for formulas.

A full-text source often reaches the answer input with two passages, and both slots go to the pages that match the
topic best: results and evaluation pages. The page where the paper defines its forwarding rule, holding time or energy
model rarely ranks there, so an answer to "what formulas do they use" says the passages hold no formula although the
reading had it. When the question or the criterion asks for formulas, the source keeps its best topic passage first and
its most formula-dense passage second; every other position is unchanged.

The score counts mathematical symbols and defining wording in the stored text. PDF text layers break equations apart
(`α = / p / W + (R−d×cosθ)`), so the score does not try to parse them. An `=` followed by a plain number is a reported
value, not a formula, and is not counted; nor is `μ` before a unit letter (µJ, µs). The trigger reads English only.
A full text written in Greek scores high on every page, so its second slot is close to arbitrary. The constants were
chosen on one research (DBR vs VBF routing, 16 Oct 2026); see the decision log.

Pure: no clock, no randomness, no store.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

ASKS = re.compile(r"(?<!infant )(?<!baby )\bformula(?:s|e)?\b(?![- ](?:milk|feeding|fed|supplementation|use)\b)"
                  r"|\bequations?\b|\bderivations?\b"
                  r"|\b(?:mathematical|closed-form|analytical) expressions?\b"
                  r"|\bhow (?:is|are)\b.{0,60}\b(?:calculated|computed)\b", re.IGNORECASE)
MATH = re.compile(r"=(?!\s*[-−]?\.?\d[\d.,]*(?![\w(]))|[≤≥∑√×·∈∝]|[α-λν-ωΓΔΘΛΣΠΦΨΩ]|μ(?![A-Za-z])"
                  r"|\\(?:frac|sum|sqrt|alpha|beta|delta|theta|tau|cdot)\b")
CUES = re.compile(r"\b(?:defined as|is given by|(?:calculated|computed) (?:as|by)|equations?|formulas?"
                  r"|we (?:define|express))\b", re.IGNORECASE)
CUE_WEIGHT = 3  # one defining phrase counts as much as three symbols
MIN_SCORE = 8  # below this a passage is prose that happens to name a symbol
THRESHOLDS = {"cue_weight": CUE_WEIGHT, "min_score": MIN_SCORE}


def asks_for_formulas(texts: list[str]) -> bool:
    """Whether the question, or a phrase the criterion was approved with, asks for formulas."""
    return any(ASKS.search(text) for text in texts if text)


def score(text: str) -> int:
    text = unicodedata.normalize("NFKC", text)
    return len(MATH.findall(text)) + CUE_WEIGHT * len(CUES.findall(text))


def bring_forward(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`ranked` with its most formula-dense passage moved to the second position.

    Nothing moves when the best topic passage is itself the most formula-dense or no passage reaches `MIN_SCORE`.
    An equal score keeps the higher-ranked passage.
    """
    if len(ranked) < 2:
        return ranked
    best = max(range(len(ranked)), key=lambda i: (score(ranked[i]["text"]), -i))
    if best == 0 or score(ranked[best]["text"]) < MIN_SCORE:
        return ranked
    return [ranked[0], ranked[best], *(p for i, p in enumerate(ranked) if i not in (0, best))]
