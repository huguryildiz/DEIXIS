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

from deixis.domain.expansion import MAX_PROBED_PHRASES, MIN_DOCUMENT_FREQUENCY, Candidate, stem
from deixis.domain.vocabulary import words
from deixis.domain.vocabulary_words import GENERAL_WORDS
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


def _stems(text: str) -> set[str]:
    return {stem(word) for word in words(text) if word not in GENERAL_WORDS}


def second_round_vocabulary(vocabulary: dict[str, Any], terms: list[str],
                            first_queries: list[dict[str, Any]]) -> dict[str, Any]:
    """The vocabulary the second round's queries are compiled from, and where each accepted phrase went (D90).

    An accepted phrase that shares a word other than a general one with a setting term (a final `s` aside) is a
    setting synonym; every other one is a task addition. The field probe accepts setting synonyms by its nature,
    since they occur with the setting block, and giving them the task block's place searched the setting twice and
    the task not at all. So:

    - with a setting synonym: the synonyms as the setting block AND the first round's task block with the additions;
      the synonyms are cut to as many as the first round's OpenAlex query kept of its own setting block, so the
      fitting does not take the task block's terms to make room for them;
    - with task additions only: the first round's setting block AND the additions alone;
    - with neither: no terms, and no second round.

    Both forms are the arm that only adds: the first round's query is not sent again, so its records are not read a
    second time and what the expansion brought in is counted on its own search rows.
    """
    setting_terms, task_terms = queried_terms(vocabulary, SETTING_BLOCK), queried_terms(vocabulary, TASK_BLOCK)
    setting_words = set().union(*(_stems(term["phrase"]) | _stems(queried_form(term)) for term in setting_terms))
    synonyms = [phrase for phrase in terms if _stems(phrase) & setting_words]
    additions = [phrase for phrase in terms if phrase not in synonyms]
    first = next((query for query in first_queries if query["provider_id"] == "openalex"), None)
    # Without a first-round OpenAlex query to read the width from, the setting block as the vocabulary holds it.
    width = sum(1 for term in setting_terms if first is None or queried_form(term) not in first["dropped_terms"])

    def added(phrase: str, block: str) -> dict[str, Any]:
        return {"phrase": phrase, "block": block, "origin": "data", "root": phrase, "in_query": "phrase",
                "phrase_count": None, "root_count": None, "and_only": False, "dropped": None}

    if synonyms:
        built = ([added(phrase, SETTING_BLOCK) for phrase in synonyms[:max(width, 1)]]
                 + [dict(term) for term in task_terms] + [added(phrase, TASK_BLOCK) for phrase in additions])
    elif additions:
        built = [dict(term) for term in setting_terms] + [added(phrase, TASK_BLOCK) for phrase in additions]
    else:
        built = []
    return {"terms": built, "setting_synonyms": synonyms, "task_additions": additions, "setting_width": width}


def searched_additions(result: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The accepted phrases that really entered a second-round query, by the block they were searched in.

    An accepted phrase is not always searched: setting synonyms are cut to the first round's setting width, and a
    provider's fitting may drop more. What orders records and what the yields count reads this, not the accepted
    list (review of 13g, 2026-09-23). A phrase counts as searched when at least one second-round query kept it.
    """
    second = result.get("second_round") or {}
    if not queries:
        return {SETTING_BLOCK: [], TASK_BLOCK: []}
    synonyms = list(second.get("setting_synonyms") or [])
    width = max(second.get("setting_width") or 0, 1)
    kept = lambda phrase: any(phrase not in (query.get("dropped_terms") or []) for query in queries)
    return {SETTING_BLOCK: [phrase for phrase in synonyms[:width] if kept(phrase)],
            TASK_BLOCK: [phrase for phrase in second.get("task_additions") or [] if kept(phrase)]}


def expansion_blocks(expansion: dict[str, Any] | None,
                     queries: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    """The second round's searched phrases by block.

    An expansion step stored between 13g and its review has the accepted phrases' blocks but not which of them were
    searched: that is read again from its stored queries, counting only the queries that write every term they keep,
    since a plain-word query's list of left-out terms was incomplete then. One stored before 13g had its accepted
    phrases read as task terms, and still has.
    """
    expansion = expansion or {}
    if "searched" in expansion:
        return {SETTING_BLOCK: list(expansion["searched"].get(SETTING_BLOCK) or []),
                TASK_BLOCK: list(expansion["searched"].get(TASK_BLOCK) or [])}
    if "second_round" in expansion and queries is not None:
        from deixis.providers.query_compiler import PLAIN_PROVIDERS

        return searched_additions(expansion, [q for q in queries
                                              if q["provider_id"] not in (*PLAIN_PROVIDERS, "serpapi")])
    return {SETTING_BLOCK: [], TASK_BLOCK: list(expansion.get("terms") or [])}


# ---- what each term brought in ---------------------------------------------------------
def term_rows(terms: list[dict[str, Any]], expansion: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every phrase that entered a query of this research, with the form it entered as."""
    rows = [{"phrase": term["phrase"], "form": queried_form(term), "origin": term["origin"], "block": term["block"]}
            for term in terms if not term["dropped"]]
    return rows + [{"phrase": phrase, "form": phrase, "origin": "data", "block": block}
                   for block, phrases in expansion_blocks(expansion).items() for phrase in phrases]


def count_yields(store: Any, research_id: str, scope_revision: int,
                 rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How many candidate works hold each term, and how many of those the research included.

    Inclusion changes whenever the user decides, so this is derived when it is asked for and never stored as a
    research's own number; the expansion step keeps one dated snapshot of the record counts and nothing else.
    """
    works: dict[str, list[str]] = {}
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
        works.setdefault(row["work_id"], []).append(f" {' '.join(words(text))} ")
        if row["state"] == "included":
            included.add(row["work_id"])
    yields = []
    for row in rows:
        # Matched at word boundaries on the padded text: one substring search a version, where comparing token
        # windows took over a second for a few thousand candidates on the thread the API also answers from.
        form = f" {' '.join(words(row['form']))} "
        holding = {work for work, versions in works.items()
                   if any(form in text for text in versions)} if form.strip() else set()
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


def first_round_records(store: Any, research_id: str, scope_revision: int,
                        only: set[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    """The work heads among this scope revision's candidates, with the text the candidate phrases come from.

    `only` names the (provider, query text) pairs whose records count; a record kept by another query is left out.
    A model-written query's second round reads its own records alone (D92); None reads every first-round record.

    A record that only an expansion arm found is left out. A later discovery run of the same scope reads the same
    pool, and were those records in it, each run would learn from what the last one added and the search would
    drift away from the question. A record the question's own query also found stays.

    Which queries found a record is read from `candidate_hits`, every search that found it (D93): a record is taken
    when any of them is a first-round query `only` allows, and left out only when every one is a second-round query.
    A candidate with no hit row, found before that table existed, is read by the one search its row keeps, as before.
    """
    heads = set(store.work_heads(research_id).values())
    second_round = {(query["provider_id"], query["query_text"])
                    for row in store.conn.execute(
                        "SELECT s.output_json AS output FROM run_steps s JOIN runs r ON r.id = s.run_id"
                        " WHERE r.research_id = ? AND s.operation_key = 'vocabulary_expansion' AND s.status = 'succeeded'",
                        (research_id,))
                    for query in (json.loads(row["output"] or "{}").get("queries") or [])}
    hits: dict[str, set[tuple[str, str]]] = {}
    for row in store.conn.execute(
            "SELECT h.source_version_id AS svid, sr.provider AS provider, sr.query_text AS query_text"
            " FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
            " WHERE h.research_id = ? AND h.scope_revision = ?", (research_id, scope_revision)):
        hits.setdefault(row["svid"], set()).add((row["provider"], row["query_text"]))

    def taken(found: set[tuple[str, str]]) -> bool:
        # A citation chain's request is no first-round query either (D95): a record only the chain found is not read.
        return any(pair not in second_round and not (pair[1] or "").startswith("chain:")
                   and (only is None or pair in only) for pair in found)

    return [{"work_id": row["work_id"], "title": row["title"],
             "author_keywords": json.loads(row["keywords"] or "[]")}
            for row in store.conn.execute(
                "SELECT c.source_version_id AS svid, v.work_id AS work_id, v.title AS title,"
                " v.author_keywords_json AS keywords, sr.provider AS provider, sr.query_text AS query_text"
                " FROM candidates c JOIN source_versions v ON v.id = c.source_version_id"
                " LEFT JOIN search_runs sr ON sr.id = c.search_run_id"
                " WHERE c.research_id = ? AND c.scope_revision = ? ORDER BY c.rank, c.created_at",
                (research_id, scope_revision))
            if row["svid"] in heads and taken(hits.get(row["svid"]) or {(row["provider"], row["query_text"])})]
