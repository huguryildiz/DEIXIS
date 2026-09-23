"""Provider queries compiled from a search plan's concept vocabulary (D44, D64).

The model names the concepts and the providers; this module writes every query string. In the legacy strategy each
paired query requires one full core synonym AND one term of another concept family. Every
query passes `query_rules.query_issues` and the 300-character limit before it is returned; terms are trimmed from the
end of a group until it does. With a core depth, OpenAlex first gets the core group alone, read deeper than the other
queries: a model-free probe found most known works beyond a query's first 25 results (docs/product/search-recall-depth-2026-09-17.md).
The opt-in compact OpenAlex strategy keeps the deep core query but replaces each paired OpenAlex query with a short
core-phrase plus family-word probe. It was measured on reused controls only; the legacy strategy remains default.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers import query_rules
from deixis.providers.registry import CONNECTORS, search_providers

VERSION = "deixis.query_compiler.v2"
COMPACT_VERSION = "deixis.query_compiler.v3.compact_openalex_v1"
BLOCKS_VERSION = "deixis.query_compiler.v4.blocks"  # the sw workflow's code vocabulary, compiled block by block
BLOCK_ORDER = ("setting", "task")  # the two blocks that gate a search; the query keeps them in this order
STRATEGIES = ("legacy", "compact_openalex_v1")
MAX_QUERY_CHARS = 300
# At most six terms in all keep a two-group query within OpenAlex's five operators; the core keeps up to two of them
# when its family has more alternatives than fit.
MAX_TERMS = 1 + query_rules.OPENALEX_MAX_OPERATORS
CORE_TERMS = 2
PLAIN_PROVIDERS = ("semantic_scholar", "crossref")
BOOLEAN_OPERATORS = ("AND", "OR", "NOT", "ANDNOT")
COMPACT_STOPWORDS = {"a", "an", "and", "are", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with"}
ROLE_NAMES = {"mechanism": "mechanism", "method": "method", "outcome": "outcome", "context": "context",
              "adjacent_field": "adjacent field"}


def _searchable(providers: list[str], workflow: str | None = None, *, routed: bool = True) -> list[str]:
    """The given providers a query may go to, once each and in the order they arrived.

    A connector that is only asked about a record whose DOI is already known is dropped here rather than by each
    caller, so no caller names a provider and a research whose scope still holds one compiles no query for it (D87).
    An sw vocabulary also leaves out a connector that only a legacy research searches (D91).
    """
    return search_providers(list(dict.fromkeys(providers)), workflow, routed=routed)


def _terms(concept: dict[str, Any]) -> list[str]:
    """The concept's synonyms, without the characters query syntax reads and without repeats.

    The label is display text in the research language and is never searched; synonyms are the search terms, written
    in the literature's language.
    """
    terms: dict[str, str] = {}
    for text in concept["synonyms"]:
        term = " ".join(re.sub(r'["()\[\]]', " ", text).split())
        if term and term.upper() not in BOOLEAN_OPERATORS:
            terms.setdefault(term.lower(), term)
    return list(terms.values())


def quoted(term: str) -> str:
    return term if re.fullmatch(r"\w+", term) else f'"{term}"'


def _group(operands: list[str]) -> str:
    return operands[0] if len(operands) == 1 else "(" + " OR ".join(operands) + ")"


def _render(provider: str, core: list[str], family: list[str], endpoint: str | None = None) -> str:
    if endpoint == "bulk":  # Semantic Scholar's bulk syntax (D93): `|` inside a block, `+` between blocks
        return " + ".join(quoted(group[0]) if len(group) == 1 else "(" + " | ".join(quoted(t) for t in group) + ")"
                          for group in (core, family) if group)
    if provider in PLAIN_PROVIDERS:  # plain words: the first core term, then the first family term
        def words(text: str, seen: set[str]) -> list[str]:
            kept: dict[str, str] = {}
            for word in text.split():
                if word not in BOOLEAN_OPERATORS and word.lower() not in seen:
                    kept.setdefault(word.lower(), word)
            return list(kept.values())

        core_words = words(core[0], set())
        family_words = words(family[0], {w.lower() for w in core_words}) if family else []
        # A long core term leaves room for at least one family word, so the word cap never drops a block whole
        # (review of 13g, 2026-09-23).
        cap = query_rules.MAX_PLAIN_WORDS
        family_words = family_words[: max(1, cap - len(core_words))] if family_words else []
        return " ".join(core_words[: cap - len(family_words)] + family_words)
    if provider == "serpapi":  # Google Scholar reads no parentheses, so only the first core term stands before the OR chain
        return " ".join([quoted(core[0]), *([" OR ".join(quoted(t) for t in family)] if family else [])])
    operand = {"arxiv": lambda t: f"abs:{quoted(t)}", "pubmed": lambda t: f"{quoted(t)}[Title/Abstract]"}.get(provider, quoted)
    text = " AND ".join(_group([operand(t) for t in group]) for group in (core, family) if group)
    return f"TITLE-ABS-KEY({text})" if provider == "scopus" else text


def _fit(provider: str, core: list[str], family: list[str]) -> str | None:
    """The query with as many leading terms of each group as the provider's rules allow, or None."""
    n_family = min(len(family), MAX_TERMS - min(len(core), CORE_TERMS))
    n_core = min(len(core), MAX_TERMS - n_family)
    while True:
        text = _render(provider, core[:n_core], family[:n_family])
        if len(text) <= MAX_QUERY_CHARS and not query_rules.query_issues(provider, text):
            return text
        if n_family > 1:
            n_family -= 1
        elif n_core > 1:
            n_core -= 1
        else:
            return None


def _compact_openalex(core_term: str, family_term: str) -> str | None:
    """Two required parts: a short core phrase and one family word, within the checked OpenAlex shape."""
    def words(term: str) -> list[str]:
        return [word for word in re.findall(r"\w+", term) if word.lower() not in COMPACT_STOPWORDS]

    anchor = words(core_term)[-2:]
    family = next((word for word in reversed(words(family_term)) if word.casefold() not in
                   {part.casefold() for part in anchor}), None)
    if not anchor or not family:
        return None
    head = quoted(" ".join(anchor))
    query = f"{head} {family}"
    return query if len(query) <= MAX_QUERY_CHARS and not query_rules.query_issues("openalex", query) else None


def _rendered(provider: str, kept: list[list[str]], endpoint: str | None = None) -> list[int]:
    """How many leading terms of each block `_render` really wrote: a plain-word query takes the first term of each
    block, and SerpApi the first term of the first block (second review of 13g, 2026-09-23). A bulk query writes them
    all."""
    if provider in PLAIN_PROVIDERS and endpoint is None:
        return [min(len(group), 1) for group in kept]
    if provider == "serpapi":
        return [min(len(group), 1) if position == 0 else len(group) for position, group in enumerate(kept)]
    return [len(group) for group in kept]


def _fit_blocks(provider: str, groups: list[list[str]], endpoint: str | None = None) -> tuple[str, list[str]] | None:
    """One query holding as many leading terms of each block as the provider's rules allow, with what was dropped.

    A term goes from the end of the block that still holds the most terms, the last such block on a tie, and every
    block keeps at least one term: a block that lost all of its terms would widen the query into another question
    (SW2.7). Taking from the last block first cut a long task block to one term while the setting block kept five
    (D90).
    """
    counts = [len(group) for group in groups]
    while True:
        kept = [group[:count] for group, count in zip(groups, counts)]
        text = _render(provider, kept[0], kept[1] if len(kept) > 1 else [], endpoint)
        if len(text) <= MAX_QUERY_CHARS and not query_rules.query_issues(provider, text, endpoint):
            used = _rendered(provider, kept, endpoint)
            return text, [term for group, count in zip(groups, used) for term in group[count:]]
        if max(counts) <= 1:
            return None
        counts[max(range(len(counts)), key=lambda position: (counts[position], position))] -= 1


def compile_block_queries(vocabulary: dict[str, Any], enabled_providers: list[str], limit: int, *,
                          routed: bool = True) -> list[dict[str, Any]]:
    """One query per provider from the code vocabulary's blocks: OR inside a block, AND between blocks (SW2.7).

    Only terms of the setting and task blocks are read. Claim words, exclusion words and outcome terms are not in
    `terms`, so no query can hold one. The returned dictionaries carry the keys `compile_queries` returns, so the
    search step reads them unchanged, plus the terms a provider's limits left out. A connector whose sw queries go to
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


def _round_robin(families: int, providers: int) -> list[tuple[int, int]]:
    """Every (family, provider) pair once: each next query takes the next family and the next provider it has not had."""
    order: list[tuple[int, int]] = []
    cursor = 0
    while len(order) < families * providers:
        for family in range(families):
            free = [p for p in range(providers) if (family, p) not in order]
            if free:
                provider = min(free, key=lambda p: (p - cursor) % providers)
                order.append((family, provider))
                cursor = provider + 1
    return order


def compile_queries(plan: dict[str, Any], enabled_providers: list[str], limit: int, core_depth: int = 0,
                    strategy: str = "legacy") -> list[dict[str, Any]]:
    """Queries for a SearchPlan v2 with exactly one core concept, in search order, at most `limit`.

    Families are the non-core concepts with at least one synonym; `adjacent_field` concepts are used only when there is no other family, because
    they name another field's words for the idea rather than a condition to pair with the core. Family terms that repeat
    a core term are dropped; with no family left, each query is the core group alone. SerpApi gets at most one query.
    A `core_depth` puts an OpenAlex query for the core group alone first, marked to read that many results; it counts
    against `limit` like any other query.
    `compact_openalex_v1` changes only paired OpenAlex queries and is opt-in; it does not widen provider scope.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown query compiler strategy: {strategy}")
    core = next(c for c in plan["concepts"] if c["role"] == "core")
    core_terms = _terms(core)
    if not core_terms:
        return []
    others = [c for c in plan["concepts"] if c["role"] != "core"]
    known = {t.lower() for t in core_terms}
    families = [(c, terms) for c in ([c for c in others if c["role"] != "adjacent_field"] or others)
                if (terms := [t for t in _terms(c) if t.lower() not in known])]
    families = families or [(None, [])]
    enabled = set(_searchable(enabled_providers))
    providers = [p for p in dict.fromkeys(plan["providers"]) if p in enabled]
    queries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if core_depth and limit > 0 and "openalex" in providers and (text := _fit("openalex", core_terms, [])):
        seen.add(("openalex", text))
        queries.append({"provider_id": "openalex", "query_text": text, "results": core_depth,
                        "rationale": f'Core "{core["label"]}" alone, read to {core_depth} results'})
    for f, p in _round_robin(len(families), len(providers)):
        if len(queries) >= limit:
            break
        (concept, terms), provider = families[f], providers[p]
        if provider == "serpapi" and any(q["provider_id"] == "serpapi" for q in queries):
            continue
        text = (_compact_openalex(core_terms[f % len(core_terms)], terms[0])
                if strategy == "compact_openalex_v1" and provider == "openalex" and terms else None)
        if text is None:
            text = _fit(provider, core_terms, terms)
        if text is None or (provider, text) in seen:
            continue
        seen.add((provider, text))
        rationale = (f'Core "{core["label"]}" with the {ROLE_NAMES[concept["role"]]} family "{concept["label"]}"' if concept
                     else f'Core "{core["label"]}" alone')
        if strategy == "compact_openalex_v1" and provider == "openalex" and terms and text != _fit(provider, core_terms, terms):
            rationale += "; compact title-and-abstract probe"
        queries.append({"provider_id": provider, "query_text": text, "rationale": rationale})
    return queries
