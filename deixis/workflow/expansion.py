"""The terms a research searched with (SW2.4).

The second round of phrases tried against the field by their record counts was removed in the clean start (slice 3a);
runs written before this change still hold an empty `vocabulary_expansion` step, which nothing reads. What stays is
shared by the ranking, the lookups and the protocol: which terms a query searched with and in which form.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.vocabulary import GATE_BLOCKS

_, TASK_BLOCK = GATE_BLOCKS


def queried_terms(vocabulary: dict[str, Any], block: str | None = None) -> list[dict[str, Any]]:
    return [term for term in vocabulary["terms"] if not term["dropped"] and (block is None or term["block"] == block)]


def searched_terms(vocabulary: dict[str, Any], block: str | None = None) -> list[dict[str, Any]]:
    """The terms every first-round query searched with: the vocabulary's own and, where the code's query was searched
    beside a model-written one, the code's too (D92). What orders and closes records reads these; the second round
    reads `queried_terms`, the model's alone."""
    from deixis.workflow.search_query import code_searched  # search_query compiles through query_compiler, not here

    extra = queried_terms(vocabulary["code_query"]["vocabulary"], block) if code_searched(vocabulary) else []
    own = queried_terms(vocabulary, block)
    forms = {queried_form(term) for term in own}
    return own + [term for term in extra if queried_form(term) not in forms]


def queried_form(term: dict[str, Any]) -> str:
    """The form of the term that really entered the query: its root word, or the whole phrase."""
    return term["root"] if term["in_query"] == "root" else term["phrase"]


# ---- what each term brought in ---------------------------------------------------------
def term_rows(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every phrase that entered a query of this research, with the form it entered as."""
    return [{"phrase": term["phrase"], "form": queried_form(term), "origin": term["origin"], "block": term["block"]}
            for term in terms if not term["dropped"]]
