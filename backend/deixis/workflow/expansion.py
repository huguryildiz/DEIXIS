"""Candidate phrases tried against the field by their record counts, and what each search term brought in (SW2.4).

A phrase the first round repeats may be the field's own term or may be noise: the pool it came from is every record
the first query returned, and most of them are off topic. Two count requests decide. The phrase is used in this
field when the records that hold it together with the setting block are many enough on their own
(`MIN_FIELD_COUNT`) and are a large enough share of every record holding the phrase (`MIN_FIELD_SHARE`). A count
that could not be read is not evidence, so the phrase is refused: unlike the question's own words, a phrase from the
data has nothing but these counts behind it.

The thresholds come from one probe on one topic that learned from *verified* positives
(`.local/quantum-source-comparison-2026-09-18/expand_from_data.py`); the product learns from all candidates of the
first round and has never been measured in that condition (slice 24).

The counts are read once. The step stores them, so a resumed run reuses the numbers of the first run rather than
paying for them again, and the terms a research searched stay the terms its protocol names.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from deixis.domain.expansion import MAX_PROBED_PHRASES, MIN_DOCUMENT_FREQUENCY, Candidate
from deixis.domain.vocabulary import words
from deixis.providers.query_compiler import quoted
from deixis.workflow.vocabulary import GATE_BLOCKS, _or_group

MIN_FIELD_COUNT = 20  # records that hold the phrase together with the setting block
MIN_FIELD_SHARE = 0.2  # and that must be at least this share of all records holding the phrase
MAX_EXPANSION_TERMS = 8  # accepted phrases that enter the second round, in probe order
THRESHOLDS = {
    "min_document_frequency": MIN_DOCUMENT_FREQUENCY,
    "max_probed_phrases": MAX_PROBED_PHRASES,
    "min_field_count": MIN_FIELD_COUNT,
    "min_field_share": MIN_FIELD_SHARE,
    "max_expansion_terms": MAX_EXPANSION_TERMS,
}
SETTING_BLOCK, TASK_BLOCK = GATE_BLOCKS


def queried_terms(vocabulary: dict[str, Any], block: str | None = None) -> list[dict[str, Any]]:
    return [term for term in vocabulary["terms"] if not term["dropped"] and (block is None or term["block"] == block)]


def queried_form(term: dict[str, Any]) -> str:
    """The form of the term that really entered the query: its root word, or the whole phrase."""
    return term["root"] if term["in_query"] == "root" else term["phrase"]


async def expand(vocabulary: dict[str, Any], found: list[Candidate],
                 count: Callable[[str], Awaitable[int | None]]) -> dict[str, Any]:
    """Probe each candidate against the setting block and return the phrases the second round may search with.

    The one rule measured is "probe against the setting block, widen the task block", so a vocabulary that queries
    only one of the two blocks is left alone rather than given a rule nothing measured.
    """
    setting = [queried_form(term) for term in queried_terms(vocabulary, SETTING_BLOCK)]
    if not setting or not queried_terms(vocabulary, TASK_BLOCK):
        return {"skipped": "single_block", "candidates": [], "terms": [], "probes": []}
    group = _or_group([quoted(form) for form in setting])
    probes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    accepted: list[str] = []

    async def probe(query: str) -> int | None:
        value = await count(query)
        probes.append({"query": query, "count": value})
        return value

    for candidate in found:
        row = {"phrase": candidate.phrase, "document_frequency": candidate.document_frequency,
               "sources": list(candidate.sources), "phrase_count": None, "field_count": None, "accepted": False,
               "reason": None}
        rows.append(row)
        if len(accepted) >= MAX_EXPANSION_TERMS:
            # The budget of terms is full; the rest are left unprobed rather than counted and thrown away.
            row["reason"] = "not_probed"
            continue
        row["phrase_count"] = await probe(quoted(candidate.phrase))
        row["field_count"] = await probe(f"{quoted(candidate.phrase)} AND {group}")
        if row["phrase_count"] is None or row["field_count"] is None:
            row["reason"] = "count_unknown"
        elif row["field_count"] < MIN_FIELD_COUNT:
            row["reason"] = "below_field_count"
        elif row["field_count"] < MIN_FIELD_SHARE * row["phrase_count"]:
            row["reason"] = "below_field_share"
        else:
            row["accepted"] = True
            accepted.append(candidate.phrase)
    return {"skipped": None, "candidates": rows, "terms": accepted, "probes": probes}


def second_round_vocabulary(vocabulary: dict[str, Any], terms: list[str]) -> dict[str, Any]:
    """The vocabulary the second round's queries are compiled from: the same setting block, a task block of the
    accepted phrases alone.

    The second round is the arm that only adds: the first round's query is not sent again, so its records are not
    read a second time and what the expansion brought in is counted on its own search rows.
    """
    task = [{"phrase": phrase, "block": TASK_BLOCK, "origin": "data", "root": phrase, "in_query": "phrase",
             "phrase_count": None, "root_count": None, "and_only": False, "dropped": None} for phrase in terms]
    return {"terms": [dict(term) for term in queried_terms(vocabulary, SETTING_BLOCK)] + task}


# ---- what each term brought in ---------------------------------------------------------
def term_rows(terms: list[dict[str, Any]], expansion: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every phrase that entered a query of this research, with the form it entered as."""
    rows = [{"phrase": term["phrase"], "form": queried_form(term), "origin": term["origin"], "block": term["block"]}
            for term in terms if not term["dropped"]]
    return rows + [{"phrase": phrase, "form": phrase, "origin": "data", "block": TASK_BLOCK}
                   for phrase in (expansion or {}).get("terms", [])]


def count_yields(store: Any, research_id: str, scope_revision: int,
                 rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How many candidate works hold each term, and how many of those the research included.

    Inclusion changes whenever the user decides, so this is derived when it is asked for and never stored as a
    research's own number; the expansion step keeps one dated snapshot of the record counts and nothing else.
    """
    works: dict[str, list[list[str]]] = {}
    included: set[str] = set()
    for row in store.conn.execute(
        "SELECT v.work_id AS work_id, v.title AS title, v.author_keywords_json AS keywords, s.state AS state,"
        " (SELECT group_concat(p.text, ' ') FROM passages p WHERE p.source_version_id = v.id AND p.kind = 'abstract')"
        " AS abstract FROM candidates c JOIN source_versions v ON v.id = c.source_version_id"
        " JOIN selections s ON s.research_id = c.research_id AND s.source_version_id = c.source_version_id"
        " WHERE c.research_id = ? AND c.scope_revision = ?", (research_id, scope_revision),
    ):
        text = " ".join(filter(None, [row["title"], row["abstract"], *json.loads(row["keywords"] or "[]")]))
        # A work is one row here however many versions of it were found, as it is one row in the candidate list.
        works.setdefault(row["work_id"], []).append(words(text))
        if row["state"] == "included":
            included.add(row["work_id"])
    yields = []
    for row in rows:
        form = words(row["form"])
        holding = {work for work, versions in works.items()
                   if any(_holds(tokens, form) for tokens in versions)} if form else set()
        yields.append(row | {"records": len(holding), "included": len(holding & included)})
    return yields


def term_yields(store: Any, research_id: str, scope_revision: int) -> list[dict[str, Any]]:
    """The yield of every term this research's frozen protocol names; an empty list when it names none."""
    protocol = store.current_protocol(research_id, scope_revision)
    body = protocol["body"] if protocol else {}
    terms = body.get("vocabulary") if body.get("search_workflow") == "sw" else None
    if not terms or not all("phrase" in term for term in terms):
        return []
    return count_yields(store, research_id, scope_revision, term_rows(terms, body.get("expansion")))


def first_round_records(store: Any, research_id: str, scope_revision: int) -> list[dict[str, Any]]:
    """The work heads among this scope revision's candidates, with the text the candidate phrases come from."""
    heads = set(store.work_heads(research_id).values())
    return [{"work_id": row["work_id"], "title": row["title"],
             "author_keywords": json.loads(row["keywords"] or "[]")}
            for row in store.conn.execute(
                "SELECT c.source_version_id AS svid, v.work_id AS work_id, v.title AS title,"
                " v.author_keywords_json AS keywords FROM candidates c"
                " JOIN source_versions v ON v.id = c.source_version_id"
                " WHERE c.research_id = ? AND c.scope_revision = ? ORDER BY c.rank, c.created_at",
                (research_id, scope_revision))
            if row["svid"] in heads]


def _holds(tokens: list[str], form: list[str]) -> bool:
    return any(tokens[start:start + len(form)] == form for start in range(len(tokens) - len(form) + 1))
