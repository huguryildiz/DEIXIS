"""Provider queries compiled from an sw vocabulary's concept blocks (SW2.7, D90).

This module writes every query string: OR inside a block, AND between blocks. Every query passes
`query_rules.query_issues` and the 300-character limit before it is returned; terms are trimmed from the end of the
longest block until it does. The SearchPlan v2 compiler (D44, D64) was removed in the clean start (slice 3a).
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers.registry import CONNECTORS, resolve_query_syntax, search_providers

BLOCKS_VERSION = "deixis.query_compiler.v4.blocks"  # the sw workflow's code vocabulary, compiled block by block
BLOCK_ORDER = ("setting", "task")  # the two blocks that gate a search; the query keeps them in this order
MAX_QUERY_CHARS = 300
PLAIN_PROVIDERS = tuple(pid for pid, connector in CONNECTORS.items()
                        if connector.query_syntax is not None and connector.query_syntax.kind == "plain")


def _searchable(providers: list[str], workflow: str | None = None, *, routed: bool = True) -> list[str]:
    """The given providers a query may go to, once each and in the order they arrived.

    A connector that is only asked about a record whose DOI is already known is dropped here rather than by each
    caller, so no caller names a provider and a research whose scope still holds one compiles no query for it (D87).
    An sw vocabulary also leaves out a connector that only a legacy research searches (D91).
    """
    return search_providers(list(dict.fromkeys(providers)), workflow, routed=routed)


def quoted(term: str) -> str:
    return term if re.fullmatch(r"\w+", term) else f'"{term}"'


def _render(provider: str, core: list[str], family: list[str], endpoint: str | None = None) -> str:
    return resolve_query_syntax(provider, endpoint).render(core, family, quoted)


def _rendered(provider: str, kept: list[list[str]], endpoint: str | None = None) -> list[int]:
    """How many leading terms of each block `_render` really wrote: a plain-word query takes the first term of each
    block, and SerpApi the first term of the first block (second review of 13g, 2026-09-23). A bulk query writes them
    all."""
    return resolve_query_syntax(provider, endpoint).written_counts(kept)


def _fit_blocks(provider: str, groups: list[list[str]], endpoint: str | None = None) -> tuple[str, list[str]] | None:
    """The fitted text and dropped occurrences, using the shared prefix allocation."""
    fitted = fit_block_counts(provider, groups, endpoint)
    if fitted is None:
        return None
    text, used = fitted
    return text, [term for group, count in zip(groups, used) for term in group[count:]]


def fit_block_counts(provider: str, groups: list[list[str]], endpoint: str | None = None) -> tuple[str, list[int]] | None:
    """One fitted query and the number of leading occurrences written from each block.

    A term goes from the end of the block that still holds the most terms, the last such block on a tie, and every
    block keeps at least one term: a block that lost all of its terms would widen the query into another question
    (SW2.7). Taking from the last block first cut a long task block to one term while the setting block kept five
    (D90).
    """
    declaration = resolve_query_syntax(provider, endpoint)
    counts = [len(group) for group in groups]
    while True:
        kept = [group[:count] for group, count in zip(groups, counts)]
        text = _render(provider, kept[0], kept[1] if len(kept) > 1 else [], endpoint)
        if len(text) <= MAX_QUERY_CHARS and not declaration.query_issues(text):
            used = _rendered(provider, kept, endpoint)
            return text, used
        if max(counts) <= 1:
            return None
        counts[max(range(len(counts)), key=lambda position: (counts[position], position))] -= 1


def compile_block_queries(vocabulary: dict[str, Any], enabled_providers: list[str], limit: int, *,
                          routed: bool = True) -> list[dict[str, Any]]:
    """One query per provider from the code vocabulary's blocks: OR inside a block, AND between blocks (SW2.7).

    Only terms of the setting and task blocks are read. Claim words, exclusion words and outcome terms are not in
    `terms`, so no query can hold one. Each returned dictionary names the provider, the query text and its rationale,
    plus the terms a provider's limits left out. A connector whose sw queries go to
    another endpoint (Semantic Scholar's bulk search, D93) gets a query in that endpoint's syntax, which names the
    endpoint and its sort. `routed` false compiles as before D93, for an sw run from before routing: no endpoint, and
    CORE and SerpApi still searched, so the run keeps the query semantics its card showed.
    """
    groups, names = [], []
    for block in BLOCK_ORDER:
        terms = list(dict.fromkeys(term["root"] if term["in_query"] == "root" else term["phrase"]
                                   for term in vocabulary["terms"] if term["block"] == block and not term["dropped"]))
        if terms:
            groups.append(terms)
            names.append(block)
    if not groups:
        return []
    rationale = "Concept blocks: " + " AND ".join(names)
    queries: list[dict[str, Any]] = []
    for provider in _searchable(enabled_providers, "sw", routed=routed):
        if len(queries) >= limit:
            break
        extra = CONNECTORS[provider].sw_query if routed else {}
        if (fitted := _fit_blocks(provider, groups, extra.get("endpoint"))) is None:
            continue
        text, dropped = fitted
        queries.append({"provider_id": provider, "query_text": text, "rationale": rationale, "dropped_terms": dropped,
                        **extra})
    return queries
