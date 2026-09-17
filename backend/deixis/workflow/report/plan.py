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
    "VII": 7, "VIII": 7, "IX": 7, "abstract": 7,
}
INDEX_TERMS_MAX_WORDS = 50


def section_budgets(total_words: int, included_count: int) -> dict[str, dict[str, int]]:
    """Allocate the scaled total, with a 1200-word floor, across the fixed report sections."""
    scaled_total = total_words
    if included_count < 10:
        scaled_total = max(1200, int(total_words * included_count / 10))

    # Index terms are a short keyword list, so their ceiling is fixed rather than proportional to prose length.
    prose_total = scaled_total - INDEX_TERMS_MAX_WORDS
    total_weight = sum(_SECTION_WEIGHTS.values())
    exact = {section_id: prose_total * weight / total_weight for section_id, weight in _SECTION_WEIGHTS.items()}
    maxima = {section_id: math.floor(words) for section_id, words in exact.items()}
    remainder = prose_total - sum(maxima.values())
    for section_id in sorted(exact, key=lambda key: (exact[key] - maxima[key], _SECTION_WEIGHTS[key]), reverse=True)[:remainder]:
        maxima[section_id] += 1
    budgets = {section_id: {"min_words": int(0.6 * maximum), "max_words": maximum, "max_claims": 40}
               for section_id, maximum in maxima.items()}
    budgets["index_terms"] = {"min_words": 0, "max_words": INDEX_TERMS_MAX_WORDS, "max_claims": 40}
    return budgets


def freeze_plan(model_plan: dict[str, Any], snapshot: dict[str, Any], included_count: int) -> dict[str, Any]:
    """Replace code-owned plan fields with the frozen corpus, budgets and support rules."""
    frozen = copy.deepcopy(model_plan)
    # Model-response envelope metadata is not part of the code-owned plan stored and reused by section calls.
    for key in ("schema_version", "step_input_id", "scope_revision", "skill_package_hash"):
        frozen.pop(key, None)
    frozen.update({
        "corpus": copy.deepcopy(snapshot["corpus"]),
        "section_budgets": section_budgets(DEFAULT_REPORT_WORDS, included_count),
        "allowed_support": {section_id: list(values) for section_id, values in ALLOWED_SUPPORT.items()},
    })
    return frozen
