"""One follow-up turn's try at the full text of a work it would otherwise answer from an abstract alone.

A follow-up asks for a detail. When the work that would answer it is in this research on its abstract only, and the
detail is not in that abstract, the abstract cannot answer the question however well it is ranked — so the turn
tries to fetch that work's full text **before** it answers, which is what the design asks for. Nothing else about
the turn changes: the question is still answered from what this research holds, and what the fetch brings in is
held like any other stored passage.

Three bounds keep a chat turn a chat turn. Only a work the person's own selection named, or one the frozen pool
would give this call, is tried. At most `WORKS` of them, in that order. And the whole attempt runs under one
deadline (`SECONDS`): a route still running when it passes is stopped and written down as unsettled, so a slow
publisher cannot hold the person's question open. The numbers are frozen in the turn's own run budget, not in the
research's depth policy: each turn freezes its own waiting, and a turn asked today is not bound by the depth a
discovery run chose months ago.

Three things the bounds do not do, written down rather than implied. A turn the process left half-way through
starts its wait again when it resumes: the person is waiting again, and the works are what the turn freezes, so a
turn that keeps being interrupted still reaches no more than `WORKS` works in all. The deadline stops the turn
from starting another route, and it stops waiting on the one running; it does not kill that route's work, so a file
already being extracted finishes its extraction in the background and its pages are there for a later question.
A file read on another version of the work than the pool gives is kept and read by a later question, not by this
turn, because swapping a version inside a frozen pool would drop the passages the person's own selection points at.
And the works are
what this turn freezes, not the requests: the per-work retrieval walks its own routes under its own limits, so a
turn's cost is "at most two works", never "at most N requests".

The work itself is the same per-work retrieval the main read uses (`flow._claim` / `flow._overlap_work`), recorded
under the same `fulltext_work:{work_id}` key in this turn's run. So the routes, their order and their limits are
that retrieval's own, not this module's, and a work another run already settled is not fetched twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any


log = logging.getLogger("deixis.followup_fulltext")

RULE = "followup_fulltext_v1"
WORKS = 2  # works one turn may try: the person is waiting, and each work is a chain of requests
SECONDS = 30.0  # the whole attempt's deadline, shared by every work it tries
STEP_KEY = "followup:fulltext"
STEP_KIND = "code:followup_fulltext"
# Why a work in the gap was not tried. Kept apart from a try that found nothing.
# How much of what the question asks about an abstract has to name before it counts as able to answer it, and the
# fewest words that may ever stand for "it names it": one shared word is a coincidence, and on a short question a
# single match would otherwise clear the share.
COVERED, COVERED_LEAST = 0.5, 2
# A file the routes read on another version of the work than the pool gives. Its pages are stored and a later
# question reads them; this turn does not, because swapping a version inside a frozen pool would drop the passages
# the person's own selection points at. Counted so the turn can say the file arrived and it did not read it.
OTHER_VERSION = "other_version"


def budget() -> dict[str, Any]:
    """The numbers one follow-up run freezes for this: read back from the run, never from this module."""
    return {"rule": RULE, "fulltext_works": WORKS, "fulltext_seconds": SECONDS}


def frozen(run: dict[str, Any]) -> dict[str, Any] | None:
    """This run's own frozen numbers, or None when it was queued before the rule (then nothing is tried)."""
    held = (run["budget"] or {}).get("followup_fulltext") or {}
    return held if held.get("rule") == RULE else None


def abstract_only(store: Any, pool_sources: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """Each version in the pool whose passages are its abstract alone, with that abstract's text.

    Read from the passages the pool actually holds, not from the record's claims: a version with a file nobody
    could read text from gives the pool its abstract only, and that is what the call would see.
    """
    ids = [pid for pid_list in pool_sources.values() for pid in pid_list]
    if not ids:
        return {}
    rows = [dict(row) for row in store.conn.execute(
        f"SELECT id, source_version_id, kind, text FROM passages WHERE id IN ({', '.join('?' * len(ids))})",
        tuple(ids))]
    held: dict[str, dict[str, Any]] = {}
    for row in rows:
        svid = row["source_version_id"]
        found = held.setdefault(svid, {"source_version_id": svid, "abstract": "", "full_text": False})
        if row["kind"] == "abstract":
            found["abstract"] = row["text"]
        else:
            found["full_text"] = True
    return {svid: found for svid, found in held.items() if not found["full_text"]}


def detail_in_abstract(abstract: str, question_terms: list[str], share: float = COVERED) -> bool:
    """Whether this abstract names enough of what the question asks about to be worth answering from.

    The trigger is the detail, not the depth: a work whose abstract already names what was asked may well answer
    from it, and fetching its full text would spend the turn's one wait on a question already covered.

    No code can read an abstract and say whether a detail is in it. What this counts is how much of what the
    question asks about the abstract names at all: under `share` of its words, the abstract is treated as not
    stating the thing asked for. One shared word proves nothing — two papers on routing share "routing" — which is
    why a single match is not enough. It is a lexical proxy and nothing more: whether the passages answer the
    question is still the model's to say, and this only decides whether to try for better passages first.
    """
    if not question_terms:
        return True  # nothing to look for: the abstract is not shown to be missing anything
    body = abstract.lower()
    # The floor is capped by the question's own length: a one-word question is answered by that one word being
    # there, and asking for two matches would send every such question down the fetch route.
    need = min(len(question_terms), max(COVERED_LEAST, round(len(question_terms) * share)))
    return sum(1 for term in question_terms if term in body) >= need


def candidates(store: Any, turn_id: str, pool_sources: dict[str, list[str]], question_terms: list[str],
               attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The works to try, in order: the person's own selections first, then the pool's own order.

    A selection the person made names the work themselves, so it comes first however the pool is ranked. Every
    candidate is in the pool already, which is what keeps this from becoming a fetch of the whole library.
    """
    missing = abstract_only(store, pool_sources)
    if not missing:
        return []
    works = {row["id"]: row["work_id"] for row in store.conn.execute(
        f"SELECT id, work_id FROM source_versions WHERE id IN ({', '.join('?' * len(missing))})",
        tuple(missing))}
    named: list[str] = []  # the versions the person's selections bind to, in the order they were made
    for item in attachments:
        for binding in item["bindings"]:
            if binding["source_version_id"] in missing and binding["source_version_id"] not in named:
                named.append(binding["source_version_id"])
    ordered = named + [svid for svid in pool_sources if svid in missing and svid not in named]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for svid in ordered:
        work_id = works.get(svid)
        if work_id is None or work_id in seen:
            continue
        # A work the person pointed at is tried whatever its abstract says: pointing at an abstract-only source and
        # asking a question of it is itself the person saying the abstract is not enough. The word count decides
        # only for the works nobody named, where the alternative is fetching the pool.
        if svid not in named and detail_in_abstract(missing[svid]["abstract"], question_terms):
            continue
        seen.add(work_id)
        found.append({"work_id": work_id, "source_version_id": svid, "from_selection": svid in named})
    return found


def tried_before(flow: Any, run_id: str) -> dict[str, dict[str, Any]]:
    """What this run's own per-work steps say it already tried, by work, in the order the works were claimed.

    The record is written once, after every work; a process that stopped between the claims and the record left the
    steps and no record. Reading the steps is what makes a resumed turn whole: it spends no part of the allowance
    twice, and the pages the first attempt did fetch are still named as fetched (`fetched_reads`) instead of being
    counted as works it never reached.
    """
    held: dict[str, dict[str, Any]] = {}
    for row in flow.store.conn.execute(
            "SELECT operation_key, status, error_code, output_json FROM run_steps"
            " WHERE run_id = ? AND kind = 'code:fulltext_work' ORDER BY rowid", (run_id,)):
        output = json.loads(row["output_json"] or "{}")
        work_id = row["operation_key"].split(":", 1)[1]
        if row["status"] == "succeeded":
            held[work_id] = {"outcome": "settled", "reason": output.get("code"),
                             "read_version": output.get("read_version"), "asset_id": output.get("asset_id")}
        else:
            held[work_id] = {"outcome": "not_settled",
                             "reason": row["error_code"] or ("outcome_unknown" if row["status"] in
                                                             ("pending", "running") else row["status"])}
    return held


def fetched_reads(flow: Any, run_id: str) -> dict[str, dict[str, Any]]:
    """Each work this turn's attempt read a file for: the version it was read on and the file it was read from.

    Read from the steps, so the version is the one the routes actually read — which may be another version of the
    same work than the one the pool held — and the pages the pool gives are that file's, never whatever pages the
    version happens to hold.
    """
    return {work_id: {"source_version_id": item["read_version"], "asset_id": item["asset_id"]}
            for work_id, item in tried_before(flow, run_id).items()
            if item["outcome"] == "settled" and item.get("read_version") and item.get("asset_id")}


async def advance(flow: Any, run: dict[str, Any], turn: dict[str, Any], pool_sources: dict[str, list[str]],
                  question_terms: list[str], attachments: list[dict[str, Any]]) -> dict[str, Any]:
    """Try the works this turn may try, under its own deadline; the record of what it did.

    Written as the turn's own code step, so a resumed turn reads what the first attempt did instead of fetching
    again — the allowance is a wait the person already spent.
    """
    store = flow.store
    saved = store.existing_step(run["id"], STEP_KEY)
    if saved and saved["status"] == "succeeded":
        return saved["output"] or {}
    held = frozen(run)
    step = store.step(run["id"], STEP_KEY, STEP_KIND)
    store.start_step(step["id"])
    if held is None:
        # A turn queued before the rule froze no wait of its own, so it waits for nothing and answers from what
        # the research holds, exactly as it did before.
        record = {"rule": None, "tried": [], "not_tried": [], "seconds": None}
        store.finish_step(step["id"], "succeeded", output=record)
        return record
    found = candidates(store, turn["id"], pool_sources, question_terms, attachments)
    limit, seconds = held["fulltext_works"], held["fulltext_seconds"]
    # What a first attempt of this turn already did, read from its own steps: those works are tried, settled or not,
    # and they are what this turn has spent. A work whose page arrived is no longer short of a full text, so it is
    # not in `found` any more — and it still has to be in `tried`, or the turn would both forget the page and hand
    # itself the allowance a second time.
    before = tried_before(flow, run["id"])
    by_work = {work["work_id"]: work for work in found}
    record: dict[str, Any] = {"rule": RULE, "works": limit, "seconds": seconds, "gap": len(found),
                              "resumed": len(before), "tried": [], "not_tried": []}
    for work_id, item in before.items():
        known = by_work.get(work_id, {"work_id": work_id, "source_version_id": item.get("read_version"),
                                      "from_selection": False})
        record["tried"].append(known | item | {"resumed": True})
    deadline = time.monotonic() + seconds
    for work in found:
        if work["work_id"] in before:
            continue
        if len(record["tried"]) >= limit:
            record["not_tried"].append(work | {"reason": "past_limit"})
            continue
        left = deadline - time.monotonic()
        if left <= 0:
            record["not_tried"].append(work | {"reason": "deadline"})
            continue
        record["tried"].append(work | await _one(flow, run, work["work_id"], left))
    store.finish_step(step["id"], "succeeded", output=record)
    return record


async def _one(flow: Any, run: dict[str, Any], work_id: str, seconds: float) -> dict[str, Any]:
    """One work's retrieval, stopped when the turn's wait runs out; what it settled.

    A route cut off mid-request leaves its own step `outcome_unknown` with this turn's reason, which is the state a
    restart already uses for a step nobody settled: a later run may try the work again, and this turn says it did
    not settle it rather than claiming the work has no full text.
    """
    from deixis.workflow.run.flow import RunStopped  # flow builds on most of the workflow; read only when stopping

    store = flow.store
    flow._claim(run["id"], work_id, False, None)
    try:
        await asyncio.wait_for(flow._overlap_work(run, work_id), timeout=seconds)
    except (asyncio.TimeoutError, TimeoutError):
        step = store.existing_step(run["id"], f"fulltext_work:{work_id}")
        if step and step["status"] in ("pending", "running"):
            store.finish_step(step["id"], "outcome_unknown", output=step["output"],
                              error_code="followup_deadline", error={"work_id": work_id})
        return {"outcome": "not_settled", "reason": "deadline"}
    except RunStopped:
        raise  # the run was paused or its question changed: the turn stops here and starts no further route
    except Exception:  # noqa: BLE001 - one work's failure neither fails the turn nor stops the other work
        log.exception("follow-up full-text attempt failed: %s", work_id)
        return {"outcome": "failed", "reason": "fetch_failed"}
    step = store.existing_step(run["id"], f"fulltext_work:{work_id}")
    status = step["status"] if step else None
    if status == "succeeded":
        # The step succeeded, which says the routes answered — with a file or without one. Which version they read
        # and from which file is carried here, because that is the file whose pages the pool may give; whether the
        # pool then gives them is its own decision (`followup.pool`), not a claim made here.
        output = step["output"] or {}
        return {"outcome": "settled", "reason": output.get("code"),
                "read_version": output.get("read_version"), "asset_id": output.get("asset_id")}
    return {"outcome": "not_settled", "reason": (step["error_code"] if step else None) or "no_step"}


def view(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the screen says about the attempt: counts and reasons, never a claim about the work's full text."""
    if not record or not record.get("rule"):
        return None
    tried = record.get("tried") or []
    return {"works": record.get("works"), "seconds": record.get("seconds"), "gap": record.get("gap"),
            "settled": sum(1 for item in tried if item.get("outcome") == "settled"),
            # Settled on another version of the work than the pool gives: read later, not this turn.
            OTHER_VERSION: sum(1 for item in tried if item.get("outcome") == "settled" and item.get("read_version")
                               and item.get("read_version") != item.get("source_version_id")),
            "tried": len(tried),
            "past_limit": sum(1 for item in (record.get("not_tried") or []) if item["reason"] == "past_limit"),
            "deadline": sum(1 for item in tried + (record.get("not_tried") or [])
                            if item.get("reason") == "deadline")}


def stored(store: Any, run_id: str) -> dict[str, Any] | None:
    """This turn's attempt as it was written, for the published turn's scanned scope."""
    step = store.existing_step(run_id, STEP_KEY)
    return (step["output"] or {}) if step and step["status"] == "succeeded" else None
