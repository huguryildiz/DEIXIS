"""The search plan a model writes from the first semantic page, and what code does with it (P3).

The design's second step: the model reads the records the question's own request returned — their titles, the
abstracts that page carried and OpenAlex's own index keywords — and answers with the terms of the two blocks, the
evidence each term was read from, and the works the citation chain starts from. Code checks every term's evidence
against the text the step really sent (`domain/contracts.py::_check_search_plan`), compiles the query from the terms
as it does under the `m1` method (`search_query.py`), and starts the chain from the works the plan named rather than
from the provider's own order (`fast_chain.Round.initial`).

Which records the step reads is a fixed rule, so the same stored page gives the same records in the same order: the
places the request itself gave them lead (P6 stores them), and where the page holds more records than one call
reads, the rest are taken at an even stride, so the list's tail is sampled instead of cut off.
"""

from __future__ import annotations

import re
from typing import Any

PLAN_RULE = "search_plan_v1"  # the rule each m2 run freezes; the plan's own shape is `deixis.search_plan.v2`
MAX_RECORDS = 50  # how many records one plan call reads; OpenAlex's semantic search returns at most this many
# How many of a record's keywords one call reads, which is what the step input holds (`index_keywords`): a provider
# that gave a record more of them sends its first MAX_KEYWORDS, in its own order, rather than failing the step.
MAX_KEYWORDS = 20
SEMANTIC_KEY = "search:fast:semantic"


def sample(svids: list[str], limit: int = MAX_RECORDS) -> list[str]:
    """`svids` cut to `limit` by the fixed rule: the first half in their own order, then the rest at an even stride.

    The same list gives the same records in the same order, and a record far down the page can still be read.
    """
    if len(svids) <= limit:
        return list(svids)
    head = limit // 2
    rest, taken = svids[head:], limit - head
    stride = len(rest) / taken
    return svids[:head] + [rest[int(index * stride)] for index in range(taken)]


def page_records(store: Any, run: dict[str, Any], limit: int = MAX_RECORDS) -> list[str]:
    """The records of this run's own question request, in the order the plan step reads them.

    The places come from the hit rows the request wrote (P6), so a record's place is the one the provider gave it in
    that one query. A run whose request wrote nothing — it failed, was cancelled or has not been sent — has none.
    """
    rows = store.conn.execute(
        "SELECT h.source_version_id FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
        " JOIN run_steps s ON s.id = sr.step_id"
        " WHERE s.run_id = ? AND s.operation_key = ? AND h.research_id = ? AND h.scope_revision = ?"
        " ORDER BY h.rank IS NULL, h.rank, h.source_version_id",
        (run["id"], SEMANTIC_KEY, run["research_id"], run["scope_revision"])).fetchall()
    return sample([row[0] for row in rows], limit)


def record_passages(store: Any, svids: list[str], max_chars: int) -> list[dict[str, Any]]:
    """The abstract of each record that has one, in the records' order, each cut to `max_chars`.

    The step sends this text, and the evidence check reads the term's span back from it, so a cut abstract and the
    spans in it agree: a term the model read stands where it says it stands, in the text it was given.
    """
    rows = []
    for svid in svids:
        abstract = next((p for p in store.passages_for(svid) if p["kind"] == "abstract"), None)
        if abstract is not None:
            rows.append(dict(abstract) | {"text": abstract["text"][:max_chars]})
    return rows


def keywords_of(store: Any, svid: str) -> list[str]:
    """The keywords the provider's own classifier gave this record, as the read that brought it stored them.

    A record read before those keywords were kept, or one whose stored value is not a list of strings, has none: the
    plan then rests on the title and the abstract, which every record carries.
    """
    from json import loads

    stored = store.source(svid).get("index_keywords_json")
    if not stored:
        return []
    try:
        keywords = loads(stored)
    except ValueError:
        return []
    if not isinstance(keywords, list):
        return []
    return [keyword for keyword in keywords if isinstance(keyword, str)][:MAX_KEYWORDS]


def named_seeds(store: Any, answer: dict[str, Any], svids: list[str]) -> list[dict[str, Any]]:
    """The works the plan named, as the chain reads them: the record each one stands for and its OpenAlex id.

    The ids are checked against the records the step was given (the contract check refuses any other), so a name here
    always points at a record this research holds. A work whose record carries no OpenAlex id is named with none and
    the chain cannot start from it; nothing else is substituted for it.
    """
    by_work: dict[str, str] = {}
    for svid in svids:
        by_work.setdefault(store.source(svid)["work_id"], svid)
    named = []
    for work in dict.fromkeys(answer.get("seed_work_ids") or []):
        svid = by_work.get(work)
        if svid is None:
            continue
        row = store.conn.execute(
            "SELECT value FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'openalex'"
            " ORDER BY value LIMIT 1", (svid,)).fetchone()
        named.append({"work_id": work, "source_version_id": svid, "openalex_id": row[0] if row else None})
    return named


def unresolved_seeds(rows: list[dict[str, Any]]) -> list[str]:
    """The named works that carry no OpenAlex id, so no provider can be asked for them — a seed PDF whose work was
    never matched, for instance. They are named and counted where the chain records its seeds; nothing is chained
    in their place, because the plan named them and no other record stands for them."""
    return [row["work_id"] for row in rows if not row["openalex_id"]]


def plan_named(store: Any, run: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The works this run's plan named, as the plan step stored them, or None where no plan named any.

    None is what a run of another method, a run whose plan step has not succeeded and a stored plan without named
    works all give: the chain then starts as it did before. An empty list is the plan's own answer that no record
    suits, and the chain starts from nothing (the design: the Boolean results are waited for).
    """
    step = store.existing_step(run["id"], "search_query")
    output = (step or {}).get("output") or {}
    if not step or step["status"] != "succeeded" or "plan_seeds" not in output:
        return None
    return list(output["plan_seeds"])


def plan_seeds(store: Any, run: dict[str, Any]) -> list[str] | None:
    """The OpenAlex ids of the works this run's plan named, in its order, or None where no plan named any.

    A named work with no OpenAlex id is not among them (`unresolved_seeds` names those): no provider can be asked
    for it, and the plan named no other record in its place.
    """
    rows = plan_named(store, run)
    return None if rows is None else [row["openalex_id"] for row in rows if row["openalex_id"]]


FOCUSED_RULE = "focused_query_v1"  # the rule a run freezes for the focused queries it may send
# Why no query was compiled for a concept the plan named: `budget` is the depth's own Boolean plan budget, and
# `unfittable` a provider whose rules cannot hold the concept beside a main term.
LEFT_OUT = ("budget", "unfittable")
# The reason a compiled focused query was not sent, written on its own search step by the search stage.
GAP_ALREADY_MET = "gap_already_met"


# A query that asks for one concept beside another is a Boolean plan of its own and counts against the depth's
# budget. The author queries of a statement research (R5) are a named work's own lookup, not a concept plan.
PLAN_ORIGINS = ("model", "user", "code")


def plans_in_round(queries: list[dict[str, Any]]) -> int:
    """How many distinct Boolean query plans the first round already holds.

    The model's own query is one; the code query searched beside it is another, and it is a different plan of the
    same question, not another rendering of the same one. One plan rendered for several providers stays one plan.
    """
    return len({query["origin"] for query in queries
                if query.get("origin") in PLAN_ORIGINS and query.get("role") != "focused"})


def focused_allowance(budget: dict[str, Any], queries: list[dict[str, Any]] | None = None) -> int:
    """How many focused queries this run may still send inside its depth's Boolean plan budget.

    The budget counts distinct plans, so the plans the first round already holds are subtracted: the model's query
    and, where it is searched, the code query beside it. A depth whose budget the first round already spends sends
    no focused query, and the step records the budget as the reason.

    A run frozen under another method, or before the budget was frozen, has none: the focused query belongs to the
    plan this method writes, and a run that froze no budget for it sends none.
    """
    policy = budget.get("fast_path") or {}
    allowed = policy.get("boolean_plans")
    if not allowed:
        return 0
    return max(0, allowed - (plans_in_round(queries) if queries is not None else 1))


def main_terms(vocabulary: dict[str, Any]) -> list[str]:
    """The queried form of every term the main query's two blocks hold, setting first, each once."""
    from deixis.providers.query_compiler import BLOCK_ORDER

    return list(dict.fromkeys(
        term["root"] if term["in_query"] == "root" else term["phrase"]
        for block in BLOCK_ORDER
        for term in vocabulary["terms"] if term["block"] == block and not term["dropped"]))


def focused_queries(answer: dict[str, Any], vocabulary: dict[str, Any], providers: list[str],
                    allowance: int) -> list[dict[str, Any]]:
    """One query per focused concept the plan named, inside the depth's allowance.

    The query has two blocks: the concept alone, and the main query's terms together. So the main query asks for both
    of its concepts at once and this one asks for the concept beside either of them — the sub-problem the main query's
    AND leaves out. The third concept is searched here rather than as a third block, which no provider's syntax
    writes (`query_rules.RENDERED_BLOCKS`).

    Every returned query says which concept it carries, the gap the plan wrote for it and the terms the provider's
    limits left out. A concept beyond the allowance, and one no provider can fit, are left out and named by
    `focused_record`, so the step says what it sent and what it did not.
    """
    from deixis.providers import query_compiler
    from deixis.providers.registry import CONNECTORS

    entries = list(answer.get("focused") or [])[:max(0, allowance)]
    terms = main_terms(vocabulary)
    if not entries or not terms:
        return []
    queries = []
    for entry in entries:
        blocks = [[entry["term"]], terms]
        for provider in query_compiler._searchable(list(providers)):
            extra = CONNECTORS[provider].sw_query
            fitted = query_compiler.fit_block_counts(provider, blocks, extra.get("endpoint"))
            if fitted is None:
                continue
            text, used = fitted
            queries.append({
                "provider_id": provider, "query_text": text,
                "rationale": f"Focused query: {entry['term']} AND the main query's terms",
                "dropped_terms": [term for group, count in zip(blocks, used) for term in group[count:]],
                "origin": "model", "role": "focused", "focused_rule": FOCUSED_RULE,
                "focused": {"term": entry["term"], "gap": entry["gap"]}, **extra})
    return queries


def focused_record(answer: dict[str, Any], queries: list[dict[str, Any]], allowance: int) -> dict[str, Any]:
    """What the plan step records about the focused queries: the allowance, each concept the plan named, and the
    query compiled for it or the reason none was.

    `left_out` is a compile-time reason only. Whether a compiled query really went to the provider is on that
    query's own search step, which records `gap_already_met` when the main query's records already carried the
    concept, and the stage's own reason when a deadline or the record cap closed it.
    """
    sent: dict[str, dict[str, Any]] = {}
    for query in queries:
        if query.get("role") == "focused":
            # One plan is rendered once per provider; the record keeps the first, which is the first provider the
            # plan names and the one whose query the frozen keyword plan sends.
            sent.setdefault(query["focused"]["term"], query)
    concepts = []
    for position, entry in enumerate(list(answer.get("focused") or [])):
        query = sent.get(entry["term"])
        concepts.append({"term": entry["term"], "gap": entry["gap"],
                         "query_text": query["query_text"] if query else None,
                         "dropped_terms": query["dropped_terms"] if query else [],
                         "left_out": None if query else ("budget" if position >= allowance else "unfittable")})
    return {"rule": FOCUSED_RULE, "allowance": allowance, "concepts": concepts}


def main_query_covers(store: Any, run: dict[str, Any], term: str, indexes: list[int]) -> bool:
    """Whether a record a main Boolean query already found carries this concept in its own text.

    The recorded condition the focused query waits on: a concept the main query's own results already carry is no
    gap, so the second query is not sent and the step says why. Only the title, the abstract and the provider's index
    keywords are read — the same text the plan was written from — and the concept must stand there as its own words,
    not inside a longer one. A main query that found nothing covers nothing, so the focused query goes out: the gap
    is certainly unmet.

    `indexes` are the main query's own pages. A record the code query alone found does not close the gap in the
    main query's results, and a work this concept is merely mentioned in is still counted as carrying it: the check
    reads words, not what a paper is about. That limit is recorded.
    """
    if not indexes:
        return False
    keys = [f"search:{index}" for index in indexes]
    patterns = [f"search:{index}:page:%" for index in indexes]
    clause = " OR ".join(["s.operation_key = ?"] * len(keys) + ["s.operation_key LIKE ?"] * len(patterns))
    rows = store.conn.execute(
        "SELECT DISTINCT h.source_version_id FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
        " JOIN run_steps s ON s.id = sr.step_id"
        f" WHERE s.run_id = ? AND h.research_id = ? AND h.scope_revision = ? AND ({clause})",
        (run["id"], run["research_id"], run["scope_revision"], *keys, *patterns)).fetchall()
    wanted = re.compile(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)")
    for (svid,) in rows:
        source = store.source(svid)
        texts = [source.get("title") or "", *keywords_of(store, svid),
                 *(p["text"] for p in store.passages_for(svid) if p["kind"] == "abstract")]
        if any(wanted.search(text.casefold()) for text in texts):
            return True
    return False


def plan_answer(vocabulary: dict[str, Any]) -> dict[str, Any]:
    """The plan the model wrote, as the vocabulary keeps it, or an empty answer for a vocabulary written otherwise."""
    answer = (vocabulary.get("search_query") or {}).get("answer")
    return answer if isinstance(answer, dict) else {}


def with_focused(vocabulary: dict[str, Any], queries: list[dict[str, Any]], providers: list[str],
                 budget: dict[str, Any]) -> list[dict[str, Any]]:
    """`queries` with the focused queries of the plan that wrote this vocabulary, after the main round.

    Every place that compiles the first round calls this, so a recompile for other providers (`source_routing`)
    keeps the focused queries instead of dropping them. A vocabulary no plan wrote, and a run whose budget allows no
    focused query, get their queries back unchanged.
    """
    allowance = focused_allowance(budget, queries)
    if not allowance:
        return queries
    return queries + focused_queries(plan_answer(vocabulary), vocabulary, providers, allowance)


def main_plan_indexes(specs: list[dict[str, Any]]) -> list[int]:
    """The keyword specs of the main Boolean query: the plan the model wrote, or the person's saved one.

    The code query beside it is a different plan of the same question, and a statement research's author queries are
    a named work's own lookup, so a record only those found leaves the main query's gap open.
    """
    return [spec["index"] for spec in specs
            if spec["query"].get("role") != "focused" and spec["query"].get("origin") in ("model", "user")]
