"""Provider queries compiled from the concept blocks of a vocabulary (SW2.7).

This module writes every query string: OR inside a block, AND between blocks. Every query passes
`query_rules.query_issues` and the 300-character limit before it is returned; terms are trimmed from the end of the
longest block until it does. The SearchPlan v2 compiler was removed in the clean start (slice 3a).
"""

from __future__ import annotations

import re
from typing import Any

from deixis.providers import query_rules
from deixis.providers.registry import CONNECTORS, resolve_query_syntax, search_providers

BLOCKS_VERSION = "deixis.query_compiler.v4.blocks"  # the fast path's code vocabulary, compiled block by block
BLOCK_ORDER = ("setting", "task")  # the two blocks that gate a search; the query keeps them in this order
MAX_QUERY_CHARS = 300
PLAIN_PROVIDERS = tuple(pid for pid, connector in CONNECTORS.items()
                        if connector.query_syntax is not None and connector.query_syntax.kind == "plain")


def _searchable(providers: list[str], *, broad: bool = False) -> list[str]:
    """The given providers a query may go to, once each and in the order they arrived.

    A connector that is only asked about a record whose DOI is already known is dropped here rather than by each
    caller, so no caller names a provider and a research whose scope still holds one compiles no query for it.
    `broad` also admits a connector searched only as a depth's second independent index; a caller that is not
    compiling a discovery run's own first-round queries leaves it alone.
    """
    return search_providers(list(dict.fromkeys(providers)), broad=broad)


def quoted(term: str) -> str:
    return term if re.fullmatch(r"\w+", term) else f'"{term}"'


# Quoted phrase forms are driven by the stored vocabulary, including for later searches of an older research.
PHRASE_FORMS_RULE = "phrase_number_v1"
# OpenAlex does not fold singular and plural inside a quoted phrase; only its queries get the other form.
PHRASE_FORM_PROVIDERS = ("openalex",)
# Words that look plural and are not, or whose number the rule cannot tell: no form is made for them.
NOT_PLURAL = frozenset({
    "series", "species", "analysis", "basis", "thesis", "physics", "mathematics", "news", "lens", "bias", "focus",
    "corpus", "status", "apparatus", "always"})
# Words that are not counted: no plural is made for them (a plural in the plan is still turned to its singular).
NOT_COUNTED = frozenset({
    "data", "information", "health", "learning", "knowledge", "software", "hardware", "research", "evidence",
    "equipment", "feedback", "internet", "traffic", "energy", "noise", "security", "privacy", "access", "performance",
    "behaviour", "behavior"})


def _plural(word: str) -> str:
    """The plural of a singular word by the fixed rule: consonant + y -> ies; s, x, z, ch, sh -> es; else s."""
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def _other_number(word: str) -> str | None:
    """The other number form of one word, or None where the rule is unsure."""
    lower = word.lower()
    # Short words, words with a digit, acronyms and the fixed list are left alone.
    if len(word) < 4 or any(ch.isdigit() for ch in word) or word.isupper() or lower in NOT_PLURAL:
        return None
    # Singular-looking endings the rule cannot toggle safely.
    if lower.endswith(("ss", "us", "is")):
        return None
    if lower.endswith("ies") and len(word) - 3 < 3:
        return None
    if not lower.endswith("s"):
        # Gerunds and words that are not counted take no plural.
        if lower.endswith("ing") or lower in NOT_COUNTED:
            return None
        return _plural(word)
    # Plural to singular: ies -> y; ches, shes, xes, zes, sses -> drop es; any other s -> drop the s alone.
    if lower.endswith("ies"):
        singular = word[:-3] + "y"
    elif lower.endswith(("ches", "shes", "xes", "zes", "sses")):
        singular = word[:-2]
    else:
        singular = word[:-1]
    # A singular the plural rule does not turn back into the word is not trusted.
    return singular if _plural(singular) == word else None


def number_variant(phrase: str) -> str | None:
    """The phrase with its head word in the other number, or None.

    Only a phrase of two or more words that is written quoted gets one. The head word is the word before the first
    " of " when the phrase holds one (`mixture of experts` -> `mixtures of experts`), else the last word. The phrase
    is read as it was spelled, so a head word in capitals (an acronym) gets none; a caller that has only lower-cased
    text has lost that and passes none.
    """
    words = phrase.split(" ")
    if len(phrase.split()) < 2 or quoted(phrase) == phrase:
        return None
    # The word before the first " of ", or the last word.
    head = next((index - 1 for index, word in enumerate(words) if index > 0 and word == "of"), len(words) - 1)
    other = _other_number(words[head])
    if other is None:
        return None
    return " ".join(words[:head] + [other] + words[head + 1:])


def phrase_forms_on(vocabulary: dict[str, Any]) -> bool:
    """Whether this vocabulary was frozen under the rule that searches the other number form."""
    return (vocabulary.get("phrase_forms") or {}).get("rule") == PHRASE_FORMS_RULE


def variants_of(vocabulary: dict[str, Any]) -> dict[str, str | None] | None:
    """The other number form of each term, as the plan stored it from the terms' own spelling, or None for a
    vocabulary frozen without the forms rule."""
    return dict((vocabulary.get("phrase_forms") or {}).get("variants") or {}) if phrase_forms_on(vocabulary) else None


def _limit_reason(text: str, issues: list[str]) -> str:
    """Why a form did not fit: the length cap, the operator cap, or another of the provider's query rules."""
    if len(text) > MAX_QUERY_CHARS:
        return "length_cap"
    return "operator_cap" if any("operators" in issue for issue in issues) else "query_rules"


def fit_with_forms(provider: str, groups: list[list[str]], endpoint: str | None = None,
                   *, variants: dict[str, str | None] | None = None
                   ) -> tuple[str, list[int], list[dict[str, Any]] | None] | None:
    """The fitted query, the plan terms written from each block and, under the forms rule, what was done per term.

    The plan's own terms are fitted first, exactly as `fit_block_counts` fits them. Only then is each written term's
    other number form (`variants`, read from the plan's own spelling) placed right after it, in the plan's term
    order, while the query still passes the provider's limits; a form that does not fit is left out, so a form never
    takes a plan term's place. A term `variants` does not name gets no form. Without `variants`, or for a provider
    that folds number itself, the record is None and the text is the one `fit_block_counts` gives.
    """
    fitted = fit_block_counts(provider, groups, endpoint)
    if fitted is None:
        return None
    text, used = fitted
    if variants is None or provider not in PHRASE_FORM_PROVIDERS:
        return text, used, None
    declaration = resolve_query_syntax(provider, endpoint)
    # The blocks as written so far: the plan's fitted terms, to which forms are added.
    written = [list(group[:count]) for group, count in zip(groups, used)]
    # Every plan term, written or not, so a form equal to one is never added twice.
    seen = {term.casefold() for group in groups for term in group}
    record: list[dict[str, Any]] = []
    for position, (group, count) in enumerate(zip(groups, used)):
        for index, term in enumerate(group):
            variant = variants.get(term)
            # Only a quoted phrase of two or more words is recorded; a single word is not a candidate.
            if len(term.split()) < 2 or quoted(term) == term:
                continue
            row = {"phrase": term, "variant": variant, "searched": False}
            if variant is None:
                record.append(row | {"left_out": "no_variant"})
                continue
            if variant.casefold() in seen:
                record.append(row | {"left_out": "in_plan"})
                continue
            if index >= count:
                record.append(row | {"left_out": "term_not_written"})
                continue
            # The form goes right after its own term, so the block reads term, form, next term.
            trial = [list(block) for block in written]
            trial[position].insert(trial[position].index(term) + 1, variant)
            candidate = _render(provider, trial[0], trial[1] if len(trial) > 1 else [], endpoint)
            issues = declaration.query_issues(candidate)
            if len(candidate) <= MAX_QUERY_CHARS and not issues:
                written, text = trial, candidate
                seen.add(variant.casefold())
                record.append(row | {"searched": True, "left_out": None})
            else:
                record.append(row | {"left_out": _limit_reason(candidate, issues)})
    return text, used, record


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
.
    """
    if len(groups) > query_rules.RENDERED_BLOCKS:
        # A third mandatory concept is refused here rather than dropped in silence: `render` writes two blocks, so a
        # query compiled from three would search for less than the plan asked and still report the third as written.
        # The third concept is searched with its own focused query instead.
        return None
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


def compile_block_queries(vocabulary: dict[str, Any], enabled_providers: list[str], limit: int,
                          *, broad: bool = False) -> list[dict[str, Any]]:
    """One query per provider from the code vocabulary's blocks: OR inside a block, AND between blocks (SW2.7).

    Only terms of the setting and task blocks are read. Claim words, exclusion words and outcome terms are not in
    `terms`, so no query can hold one. Each returned dictionary names the provider, the query text and its rationale,
    plus the terms a provider's limits left out. A connector whose queries go to
    another endpoint (Semantic Scholar's bulk search) gets a query in that endpoint's syntax, which names the
    endpoint and its sort.
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
    # A vocabulary frozen under the forms rule also searches the other number form of its quoted phrases.
    variants = variants_of(vocabulary)
    queries: list[dict[str, Any]] = []
    for provider in _searchable(enabled_providers, broad=broad):
        if len(queries) >= limit:
            break
        extra = CONNECTORS[provider].sw_query
        if variants is None:
            if (fitted := _fit_blocks(provider, groups, extra.get("endpoint"))) is None:
                continue
            text, dropped = fitted
            queries.append({"provider_id": provider, "query_text": text, "rationale": rationale,
                            "dropped_terms": dropped, **extra})
            continue
        if (formed := fit_with_forms(provider, groups, extra.get("endpoint"), variants=variants)) is None:
            continue
        text, used, record = formed
        dropped = [term for group, count in zip(groups, used) for term in group[count:]]
        # The query records, per quoted phrase, the form it searched or why it left the form out.
        queries.append({"provider_id": provider, "query_text": text, "rationale": rationale, "dropped_terms": dropped,
                        **({"phrase_forms": {"rule": PHRASE_FORMS_RULE, "terms": record}} if record is not None
                           else {}), **extra})
    return queries
