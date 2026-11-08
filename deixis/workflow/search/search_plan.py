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

from typing import Any

PLAN_RULE = "search_plan_v1"  # the rule each m2 run freezes; the plan's own shape is `deixis.search_plan.v1`
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
