"""Whole-phrase term blocks; no backup substitution or provider requests."""
from __future__ import annotations

from itertools import zip_longest

from deixis.providers.query_compiler import compile_block_queries
from deixis.workflow.search.criterion import norm
from deixis.workflow.search.vocabulary import TERM_FIELDS


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
    return compile_block_queries(vocabulary, providers, limit)


def _backup_phrases(groups: list[list[str]], seen: set[str]) -> list[list[str]]:
    kept_groups = []
    for group in groups:
        if not isinstance(group, list) or any(not isinstance(p, str) for p in group):
            raise InvalidTerms("Each backup block must be a list of phrases")
        kept = []
        for text in group:
            phrase = norm(text)
            if phrase and phrase not in seen:
                seen.add(phrase)
                kept.append(phrase)
        kept_groups.append(kept)
    return kept_groups


def compile_alias_queries(setting: list[str], task: list[str], setting_backup: list[str], task_backup: list[str],
                          providers: list[str], limit: int = 6) -> list[dict]:
    """Plan version 3: backups are other names of the block's concepts and are searched, not only recorded.

    Per provider, the main query is the chosen terms fitted exactly as before (`compile_queries`), with each backup
    added after them while the provider's query rules still take every written term. Chosen or backup terms the main
    query cannot hold go to at most one alternative query of that provider: each block's overflow first, then the
    main query's terms of that block as far as the rules allow. Every query of a provider records in `dropped_terms` the terms neither query holds;
    the main query names in `alternative_terms` the ones only the alternative holds. `limit` counts providers.
    """
    from deixis.providers.query_compiler import BLOCK_ORDER, CONNECTORS, _searchable, fit_block_counts

    vocabulary = block_vocabulary(setting, task)
    chosen = [[t["phrase"] for t in vocabulary["terms"] if t["block"] == block] for block in BLOCK_ORDER]
    backups = _backup_phrases([setting_backup, task_backup], {p for group in chosen for p in group})
    interleaved = [(position, term) for pair in zip_longest(*backups)
                   for position, term in enumerate(pair) if term is not None]
    rationale = "Concept blocks: " + " AND ".join(BLOCK_ORDER)
    queries: list[dict] = []
    providers_used = 0
    for provider in _searchable(providers):
        if providers_used >= limit:
            break
        extra = CONNECTORS[provider].sw_query
        endpoint = extra.get("endpoint")
        if (fitted := fit_block_counts(provider, chosen, endpoint)) is None:
            continue
        text, used = fitted
        groups = [group[:count] for group, count in zip(chosen, used)]
        for position, term in interleaved:
            trial = [list(group) for group in groups]
            trial[position].append(term)
            if (more := fit_block_counts(provider, trial, endpoint)) and more[1] == [len(g) for g in trial]:
                groups, text = trial, more[0]
        written = [t for group in groups for t in group]
        overflow = [[t for t in chosen[b] + backups[b] if t not in written] for b in range(len(BLOCK_ORDER))]
        alternative, extra_terms = None, []
        if any(overflow):
            # The overflow leads each block; the main query's terms fill whatever room the provider's rules leave.
            alt_groups = [overflow[b] + groups[b] for b in range(len(BLOCK_ORDER))]
            if (alt := fit_block_counts(provider, alt_groups, endpoint)) and alt[0] != text:
                extra_terms = [t for group, count in zip(alt_groups, alt[1]) for t in group[:count] if t not in written]
                alternative = {"provider_id": provider, "query_text": alt[0], "rationale": rationale + " (other names)",
                               "role": "alternative", **extra}
        dropped = [t for group in overflow for t in group if t not in extra_terms]
        queries.append({"provider_id": provider, "query_text": text, "rationale": rationale, "role": "main",
                        "dropped_terms": dropped, "alternative_terms": extra_terms, **extra})
        if alternative:
            queries.append(alternative | {"dropped_terms": dropped})
        providers_used += 1
    return queries
