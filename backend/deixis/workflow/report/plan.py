"""Code-owned additions to a validated model report plan."""

from __future__ import annotations

import copy
import math
from typing import Any


ALLOWED_SUPPORT = {
    "I": ("source_stated", "analyst_inference"),
    "III": ("source_stated",),
    "IV": ("source_stated",),
    "V": ("source_stated", "analyst_inference"),
    "VI": ("analyst_inference",),
    "VII": ("analyst_inference", "source_stated"),
    "VIII": ("source_stated", "analyst_inference"),
    "IX": ("source_stated", "analyst_inference"),
    "abstract": ("source_stated", "analyst_inference"),
    "index_terms": ("source_stated",),
}

DEFAULT_REPORT_WORDS = 5500
_SECTION_WEIGHTS = {
    "I": 7, "III": 14, "IV": 18, "V": 14, "VI": 12,
    "VII": 7, "VIII": 7, "IX": 7, "abstract": 7, "index_terms": 7,
}


def section_budgets(total_words: int, included_count: int) -> dict[str, dict[str, int]]:
    """Allocate the scaled total, with a 1200-word floor, across the fixed report sections."""
    scaled_total = total_words
    if included_count < 10:
        scaled_total = max(1200, int(total_words * included_count / 10))

    exact = {section_id: scaled_total * weight / 100 for section_id, weight in _SECTION_WEIGHTS.items()}
    maxima = {section_id: math.floor(words) for section_id, words in exact.items()}
    remainder = scaled_total - sum(maxima.values())
    for section_id in sorted(exact, key=lambda key: (exact[key] - maxima[key], _SECTION_WEIGHTS[key]), reverse=True)[:remainder]:
        maxima[section_id] += 1
    return {section_id: {"min_words": int(0.6 * maximum), "max_words": maximum, "max_claims": 40}
            for section_id, maximum in maxima.items()}


def freeze_plan(model_plan: dict[str, Any], snapshot: dict[str, Any], included_count: int) -> dict[str, Any]:
    """Replace code-owned plan fields with the frozen corpus, budgets and support rules."""
    frozen = copy.deepcopy(model_plan)
    frozen.update({
        "corpus": copy.deepcopy(snapshot["corpus"]),
        "section_budgets": section_budgets(DEFAULT_REPORT_WORDS, included_count),
        "allowed_support": {section_id: list(values) for section_id, values in ALLOWED_SUPPORT.items()},
    })
    return frozen
