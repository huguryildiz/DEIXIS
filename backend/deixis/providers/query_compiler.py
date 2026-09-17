"""Provider queries compiled from a search plan's concept vocabulary (D44).

The model names the concepts and the providers; this module writes every query string. Each query requires one term of
the core concept AND one term of one other concept family, so no query can drop the discriminating core term. Every
query passes `query_rules.query_issues` and the 300-character limit before it is returned; terms are trimmed from the
end of a group until it does. With a core depth, OpenAlex first gets the core group alone, read deeper than the other
queries: a model-free probe found most known works beyond a query's first 25 results (docs/product/search-recall-depth-2026-09-17.md).
No recall measurement stands behind these rules: they are a structural guard only.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers import query_rules

VERSION = "deixis.query_compiler.v2"
MAX_QUERY_CHARS = 300
# At most six terms in all keep a two-group query within OpenAlex's five operators; the core keeps up to two of them
# when its family has more alternatives than fit.
MAX_TERMS = 1 + query_rules.OPENALEX_MAX_OPERATORS
CORE_TERMS = 2
PLAIN_PROVIDERS = ("semantic_scholar", "crossref")
BOOLEAN_OPERATORS = ("AND", "OR", "NOT", "ANDNOT")
ROLE_NAMES = {"mechanism": "mechanism", "method": "method", "outcome": "outcome", "context": "context",
              "adjacent_field": "adjacent field"}


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


def _quoted(term: str) -> str:
    return term if re.fullmatch(r"\w+", term) else f'"{term}"'


def _group(operands: list[str]) -> str:
    return operands[0] if len(operands) == 1 else "(" + " OR ".join(operands) + ")"


def _render(provider: str, core: list[str], family: list[str]) -> str:
    if provider in PLAIN_PROVIDERS:  # plain words: the first core term, then the first family term
        words: dict[str, str] = {}
        for word in " ".join([core[0], *family[:1]]).split():
            if word not in BOOLEAN_OPERATORS:
                words.setdefault(word.lower(), word)
        return " ".join(list(words.values())[: query_rules.MAX_PLAIN_WORDS])
    if provider == "serpapi":  # Google Scholar reads no parentheses, so only the first core term stands before the OR chain
        return " ".join([_quoted(core[0]), *([" OR ".join(_quoted(t) for t in family)] if family else [])])
    operand = {"arxiv": lambda t: f"abs:{_quoted(t)}", "pubmed": lambda t: f"{_quoted(t)}[Title/Abstract]"}.get(provider, _quoted)
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


def compile_queries(plan: dict[str, Any], enabled_providers: list[str], limit: int, core_depth: int = 0) -> list[dict[str, Any]]:
    """Queries for a SearchPlan v2 with exactly one core concept, in search order, at most `limit`.

    Families are the non-core concepts with at least one synonym; `adjacent_field` concepts are used only when there is no other family, because
    they name another field's words for the idea rather than a condition to pair with the core. Family terms that repeat
    a core term are dropped; with no family left, each query is the core group alone. SerpApi gets at most one query.
    A `core_depth` puts an OpenAlex query for the core group alone first, marked to read that many results; it counts
    against `limit` like any other query.
    """
    core = next(c for c in plan["concepts"] if c["role"] == "core")
    core_terms = _terms(core)
    if not core_terms:
        return []
    others = [c for c in plan["concepts"] if c["role"] != "core"]
    known = {t.lower() for t in core_terms}
    families = [(c, terms) for c in ([c for c in others if c["role"] != "adjacent_field"] or others)
                if (terms := [t for t in _terms(c) if t.lower() not in known])]
    families = families or [(None, [])]
    providers = [p for p in dict.fromkeys(plan["providers"]) if p in enabled_providers]
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
        text = _fit(provider, core_terms, terms)
        if text is None or (provider, text) in seen:
            continue
        seen.add((provider, text))
        rationale = (f'Core "{core["label"]}" with the {ROLE_NAMES[concept["role"]]} family "{concept["label"]}"' if concept
                     else f'Core "{core["label"]}" alone')
        queries.append({"provider_id": provider, "query_text": text, "rationale": rationale})
    return queries
