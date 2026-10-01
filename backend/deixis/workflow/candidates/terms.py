"""Whole-phrase term blocks; no backup substitution or provider requests."""
from __future__ import annotations

from deixis.providers.query_compiler import compile_block_queries
from deixis.workflow.criterion import norm
from deixis.workflow.vocabulary import TERM_FIELDS


class InvalidTerms(Exception):
    """A block is empty or the retained vocabulary exceeds six terms."""


def block_vocabulary(setting: list[str], task: list[str]) -> dict:
    terms, seen = [], set()
    for block, phrases in (("setting", setting), ("task", task)):
        if not isinstance(phrases, list) or any(not isinstance(p, str) for p in phrases):
            raise InvalidTerms("Each block must be a list of phrases")
        retained = 0
        for text in phrases:
            phrase = norm(text)
            if not phrase:
                raise InvalidTerms("A phrase must be non-empty")
            if phrase in seen:
                continue
            seen.add(phrase)
            values = {"phrase": phrase, "block": block, "origin": "kill_search", "root": phrase,
                      "in_query": "phrase", "phrase_count": None, "root_count": None,
                      "and_only": False, "dropped": None}
            terms.append({field: values[field] for field in TERM_FIELDS})
            retained += 1
        if not retained:
            raise InvalidTerms("Each block needs at least one distinct phrase")
    if len(terms) > 6:
        raise InvalidTerms("At most six terms in total")
    return {"block_assignment": "kill_search", "terms": terms}


def compile_queries(vocabulary, providers, limit=6):
    return compile_block_queries(vocabulary, providers, limit, routed=True)
