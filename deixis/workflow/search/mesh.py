"""PubMed's verified MeSH headings, added beside the title and abstract terms the plan already searches.

PubMed indexes its records under NLM's own controlled vocabulary, so a record can be about a question's concept
without carrying the question's words: "heart attack" is indexed as *Myocardial Infarction*. This module turns the
plan's own terms into the headings NCBI maps them to, and writes them into the query as alternatives — never in
place of a term. A heading alone would lose the records NLM has not indexed yet, which is the one warning the
design gives.

Nothing here invents a heading. A heading comes from NCBI twice over: PubMed's own term mapping chose it for that
phrase, and the MeSH database holds it as a descriptor under that very name. Neither says the heading fits the
research question; that is not claimed anywhere.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from deixis.providers import pubmed
from deixis.providers.query_compiler import quoted
from deixis.providers.registry import resolve_query_syntax

RULE = "mesh_expansion_v1"
# Our own bound on the query a page sends, measured on the percent-encoded parameter, not a documented provider
# limit: NCBI advises POST for a long query and this adapter sends GET, so the expansion stops well before a URL
# length any host would refuse.
MAX_SENT_CHARS = 1800


def lookup_text(groups: list[list[str]]) -> str:
    """The text whose mapping is asked for: the plan's own blocks, unquoted.

    Unquoted because a quoted phrase is searched as it stands and gets no mapping at all, which is why the query
    this run sends — every operand quoted and under a field — reports no mapping of its own. The shape stays the
    plan's: alternatives inside a block, blocks joined.
    """
    blocks = [block for block in groups if block]
    return " AND ".join(f"({' OR '.join(block)})" if len(block) > 1 else block[0] for block in blocks)


def heading_candidates(translations: list[dict[str, Any]], terms: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """The heading NCBI mapped each term to, and why a term has none.

    A term is read back by its own text, so a mapping of another phrase is never taken for it. `not_mapped` is a
    term NCBI did not map at all, `not_a_heading` a mapping that searched no heading, and `not_the_whole_phrase`
    one whose headings belong to single words PubMed split the phrase into, or whose phrase mapped to more than
    one heading.
    """
    mapping = {row["from"].strip().casefold(): row["to"] for row in translations}
    found, missing = {}, {}
    for term in terms:
        translated = mapping.get(term.strip().casefold())
        if translated is None:
            missing[term] = "not_mapped"
            continue
        heading = pubmed.mapped_heading(translated)
        if heading is None:
            missing[term] = "not_a_heading" if pubmed.MESH_FIELD not in translated else "not_the_whole_phrase"
            continue
        found[term] = heading
    return found, missing


def _render(provider: str, groups: list[list[str]], headings: dict[str, str]) -> str:
    """The compiled query with a heading written beside every term that has one, in the provider's own syntax."""
    declaration = resolve_query_syntax(provider)

    def operand(term: str) -> str:
        text = f"{declaration.operand_prefix}{quoted(term)}{declaration.operand_suffix}"
        heading = headings.get(term)
        return f'({text} OR "{heading}"{pubmed.MESH_FIELD})' if heading else text

    def block(terms: list[str]) -> str:
        operands = [operand(term) for term in terms]
        return operands[0] if len(operands) == 1 else "(" + " OR ".join(operands) + ")"

    return " AND ".join(block(terms) for terms in groups if terms)


def expanded(provider: str, groups: list[list[str]], headings: dict[str, str],
             max_chars: int = MAX_SENT_CHARS) -> dict[str, Any] | None:
    """The query to send, the headings it carries and the ones the length bound left out; None when it carries none.

    A term is never dropped here: the terms are the ones the compiler already fitted, and only a heading can go.
    A heading goes from the block that holds the most of them, the last such block on a tie, which is how the
    compiler itself takes a term from the longest block. The bound is read on the encoded parameter, because that
    is what the request carries. With no heading left the caller sends the compiled query it already had.
    """
    kept = {term: heading for term, heading in headings.items() if any(term in block for block in groups)}
    dropped: list[str] = []
    while True:
        if not kept:
            return None
        text = _render(provider, groups, kept)
        if len(quote_plus(text)) <= max_chars:
            return {"rule": RULE, "query_text": text,
                    "headings": [{"term": term, "heading": heading} for block in groups for term in block
                                 if term in kept for heading in [kept[term]]],
                    "dropped": dropped}
        counts = [sum(1 for term in block if term in kept) for block in groups]
        position = max(range(len(counts)), key=lambda index: (counts[index], index))
        last = next(term for term in reversed(groups[position]) if term in kept)
        del kept[last]
        dropped.append(last)


def sent_text(query: dict[str, Any]) -> dict[str, Any]:
    """`{"query_text": ...}` where this query carries an expansion, nothing where it does not.

    Read from the plan's own copy of the query, which keeps the expansion whole; the protocol's
    `compiled_queries` list holds a stripped copy of each query and carries none.
    """
    text = ((query.get("mesh") or {}).get("query_text")) if isinstance(query, dict) else None
    return {"query_text": text} if text else {}


def sent_query(query: dict[str, Any]) -> dict[str, Any]:
    """The query a page sends: the expanded text where this query has one, the compiled text otherwise.

    The compiled text stays on the query, because that is what the plan's own records are read back against: the
    words a query carries are told from the compiler's output, and an expanded text would say nothing about them.
    """
    return query | sent_text(query)
