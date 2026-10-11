"""The works of a discovery's frozen ranking that were never screened, and the run that screens the next of them
(UI parity S20, F12 and F13).

A discovery screens the first N works of its frozen list (`small_batch:v1:list`); everything below that line is found
but not read. `unscreened` lists those works in the list's order. `request` queues a `screen_more` run for the next
`SIZE` of them that have an abstract to read, and `execute` runs the discovery's own abstract stage over exactly those
works: code first, then two model runs per batch of `ABSTRACT_BATCH`, each batch closed by `abstract_stage.combine`.
Nothing is included here (SW1.2): a work the two runs agree on becomes an abstract-stage candidate, and only a person
or a full-text reading includes it.

A work counts as screened once a person decided it, or it holds a current (not stale) decision at the full-text stage
or an abstract-stage decision other than "not read" (`abstract_stage.UNREAD_CODES`). The list's position and the
embedding similarity it was frozen with are prioritization signals (AGENTS.md), never relevance or quality.
"""

from __future__ import annotations

from typing import Any

from deixis.domain import canonical
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_RUNS
from deixis.storage.db import now, transaction
from deixis.workflow import abstract_stage, small_batch
from deixis.workflow.decisions import DecisionStore

KIND = "screen_more"
POLICY = "screen_more_v1"
SIZE = 40
MAX_PAGE = 100
SUMMARY_KEY = "screen_more:summary"
BATCH_KEY = "screen_more"
SIGNALS_NOTE = ("Rank is the work's place in the discovery's frozen list and similarity the embedding score that list "
                "was ranked with; both are prioritization signals, not relevance or quality verdicts.")


class NothingToScreen(Exception):
    """No completed discovery list to read from, or no work of it left that can be screened (the API answers 422)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def frozen_list(store: Any, rid: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(discovery run, its frozen list) of the latest completed discovery of the current question revision."""
    revision = store.research(rid)["current_scope_revision"]
    for row in store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
            " AND status = 'completed' ORDER BY created_at DESC, id DESC", (rid, revision)):
        step = store.existing_step(row["id"], small_batch.LIST_KEY)
        if step is not None and step["status"] == "succeeded":
            return store.run(row["id"]), step["output"]
    return None


def _screened_works(store: Any, rid: str) -> tuple[set[str], dict[str, str]]:
    """The works a person, code or a model already screened, and every work's current head."""
    decisions = DecisionStore(store)
    facts = decisions.facts(rid)
    screened: set[str] = set()
    for work_id, rows in facts["decisions"].items():
        for decision in rows:
            if decision["decided_by"] == "human":
                screened.add(work_id)  # the person's decision stands, stale or not, and is never asked about again
                break
            if decisions.is_stale(decision, facts["stale_key"]):
                continue
            if decision["stage"] == "fulltext" or decision["reason_code"] not in abstract_stage.UNREAD_CODES:
                screened.add(work_id)
                break
    screened |= {row[0] for row in store.conn.execute(
        "SELECT v.work_id FROM selections s JOIN source_versions v ON v.id = s.source_version_id"
        " WHERE s.research_id = ? AND s.origin = 'user' AND s.state IN ('included', 'excluded')", (rid,))}
    return screened, facts["heads"]


def _works_with_abstract(store: Any, rid: str) -> set[str]:
    """Works with an abstract of their own on any version still in the research: what the model can be shown."""
    return {row[0] for row in store.conn.execute(
        "SELECT DISTINCT v.work_id FROM passages p JOIN source_versions v ON v.id = p.source_version_id"
        " JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ? AND m.removed_at IS NULL"
        " WHERE p.kind = 'abstract' AND length(trim(p.text)) > 0", (rid,))}


def _unscreened(store: Any, rid: str, listing: dict[str, Any]) -> list[dict[str, Any]]:
    """The list's never-screened works, in list order, each with its current head and whether it can be read.

    A work no longer in the research is left out. `screenable` needs an abstract on some version and a head that is
    a search candidate of the current revision: the abstract stage reads nothing else, and this run fetches no
    abstracts (no provider request), so a work without one stays listed but is never planned.
    """
    revision = store.research(rid)["current_scope_revision"]
    screened, heads = _screened_works(store, rid)
    readable = _works_with_abstract(store, rid)
    offered = {c["source_version_id"] for c in store.candidates(rid, revision) if c["origin"] != "user"}
    rows = []
    for item in listing["items"]:
        work_id = item["work_id"]
        head = heads.get(work_id)
        if head is None or work_id in screened:
            continue
        rows.append({"item": item, "head": head, "has_abstract": work_id in readable,
                     "screenable": work_id in readable and head in offered})
    return rows


def unscreened(store: Any, rid: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """F12: the found-but-never-screened works of the frozen list, in its order, one page at a time."""
    store.research(rid)
    found = frozen_list(store, rid)
    if found is None:
        raise NothingToScreen("no_completed_discovery", "This research has no completed search with a ranked list")
    discovery, listing = found
    rows = _unscreened(store, rid, listing)
    similarities = listing["manifest"].get("similarities") or {}
    page = []
    for row in rows[offset:offset + limit]:
        item, head = row["item"], row["head"]
        source = store.source(head)
        page.append({
            "work_id": item["work_id"], "source_version_id": head, "title": source["title"], "year": source["year"],
            "venue": source["venue"], "doi": source["doi"], "authors": source["authors"],
            "has_abstract": row["has_abstract"], "screenable": row["screenable"],
            "signals": {"rank": item["position"], "similarity": similarities.get(item["head"])}})
    return {"research_id": rid, "discovery_run_id": discovery["id"], "scope_revision": discovery["scope_revision"],
            "manifest_hash": listing["manifest_hash"], "list_size": len(listing["items"]),
            "total": len(rows), "screenable": sum(row["screenable"] for row in rows),
            "offset": offset, "limit": limit, "items": page, "signals_note": SIGNALS_NOTE}


def budget(count: int) -> dict[str, Any]:
    """The run's own allowance, frozen with it, and no provider request. The planned reads are one call per batch per
    run; the allowance holds them twice, so a call a crash left with an unknown outcome (it counted when its session
    opened) can be sent again on resume instead of leaving its batch unread. The stage never sends more calls than
    its batches: the room is used only by such resends."""
    reads = abstract_stage.model_calls(count, ABSTRACT_BATCH, ABSTRACT_RUNS)
    return {"max_model_calls": 2 * reads, "max_provider_requests": 0,
            "screen_more": {"policy": POLICY, "size": SIZE, "planned": count, "batch": ABSTRACT_BATCH,
                            "runs": ABSTRACT_RUNS, "reads": reads}}


def request(store: Any, rid: str, idempotency_key: str | None) -> dict[str, Any]:
    """F13: queue a `screen_more` run for the next `SIZE` screenable works of the frozen list, planned here.

    Refused while another run of the research is active (RevisionConflict, 409), and when there is no completed
    discovery list or nothing screenable is left (NothingToScreen, 422). The planned heads are stored in the run's
    target, so a resumed run reads the same works.
    """
    from deixis.domain.rules import RevisionConflict
    from deixis.workflow.store import ACTIVE_RUN_STATUSES

    key = f"{rid}:screen_more:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        store.research(rid)
        if key:
            row = store.conn.execute("SELECT id FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if row is not None:
                return store.run(row["id"])
        active = store.conn.execute(
            f"SELECT id FROM runs WHERE research_id = ? AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
            (rid, *ACTIVE_RUN_STATUSES)).fetchone()
        if active:
            raise RevisionConflict(f"run {active['id']} is still active")
        found = frozen_list(store, rid)
        if found is None:
            raise NothingToScreen("no_completed_discovery", "This research has no completed search with a ranked list")
        discovery, listing = found
        picked = [row for row in _unscreened(store, rid, listing) if row["screenable"]][:SIZE]
        if not picked:
            raise NothingToScreen("nothing_left", "Every work of the ranked list that has an abstract was screened")
        target = {"discovery_run_id": discovery["id"], "manifest_hash": listing["manifest_hash"],
                  "heads": [row["head"] for row in picked], "work_ids": [row["item"]["work_id"] for row in picked],
                  "positions": [row["item"]["position"] for row in picked]}
        return store.create_run(rid, KIND, budget(len(picked)), key, target)


def _candidate_works(store: Any, run_id: str) -> list[str]:
    """Works this run made abstract-stage candidates, whose decision still stands."""
    return sorted({row[0] for row in store.conn.execute(
        "SELECT DISTINCT v.work_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
        " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ? AND d.stage = 'abstract'"
        " AND d.outcome = 'candidate' AND d.superseded_at IS NULL", (run_id,))})


def mark_answer(store: Any, run: dict[str, Any]) -> None:
    """Move the research's selection revision once per new set of candidates this run made, so an answer made before
    them reads as made for an earlier selection (`result_applicability`: `stale_selection`). The next discovery-bound
    answer reads these candidates (`answer_candidates`). Keyed by the set, a replay writes nothing twice."""
    works = _candidate_works(store, run["id"])
    if not works:
        return
    rid = run["research_id"]
    with transaction(store.conn):
        step = store.step(run["id"], f"screen_more:answer_out_of_date:{canonical.sha256_hex(works)[:16]}",
                          "code:screen_more_answer_out_of_date")
        if step["status"] == "succeeded":
            return
        store.start_step(step["id"])
        store.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1, updated_at = ? WHERE id = ?",
                           (now(), rid))
        revision = store.selection_revision(rid)
        store._event(rid, "screen_more_candidates", {"works": works, "selection_revision": revision}, run["id"])
        store.finish_step(step["id"], "succeeded", output={"works": works, "selection_revision": revision})


def answer_candidates(store: Any, rid: str, scope_revision: int) -> dict[str, dict[str, Any]]:
    """Current abstract-stage candidates written by `screen_more` runs of this question revision, by record:
    the decision and its run. Only these extend a discovery-bound answer beyond its read cutoff."""
    decisions = DecisionStore(store)
    key = decisions.staleness_key(rid)
    found = {}
    for row in store.conn.execute(
            "SELECT d.*, s.run_id AS screen_run_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND r.kind = 'screen_more' AND r.scope_revision = ?"
            " AND d.stage = 'abstract' AND d.outcome = 'candidate' AND d.superseded_at IS NULL", (rid, scope_revision)):
        decision = dict(row)
        if not decisions.is_stale(decision, key):
            found[decision["source_version_id"]] = {"decision_id": decision["id"], "run_id": decision["screen_run_id"]}
    return found


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    """Screen the planned works with the discovery's abstract stage, then summarise. Resumable: every model call is a
    step keyed by batch and run, so a finished call returns its stored output and is not sent again."""
    from deixis.workflow import search_query as search_query_rules

    store, run_id, revision = flow.store, run["id"], run["scope_revision"]
    target = run["target"]
    flow._checkpoint(run_id, revision)
    approval = store.existing_step(target["discovery_run_id"], "protocol_approval")
    if approval is None or approval["status"] != "succeeded":
        flow._fail(run_id, "discovery_vocabulary_missing")
    approved = approval["output"]["approved"]
    vocabulary = search_query_rules.settled(approved["vocabulary"], approved["queries"])
    # The discovery's expansion terms, frozen into this run under the key the abstract stage reads them from.
    expansion = (store.existing_step(target["discovery_run_id"], "vocabulary_expansion") or {}).get("output") or {}
    small_batch.save_code(flow, run, "vocabulary_expansion", "code:vocabulary_expansion", lambda: expansion)
    try:
        await flow._abstract_stage(run, scope, vocabulary, order=target["heads"], batch_key=BATCH_KEY,
                                   read_limit=len(target["heads"]))
        flow._checkpoint(run_id, revision)
    finally:
        mark_answer(store, run)
    small_batch.save_code(flow, run, SUMMARY_KEY, "code:screen_more_summary", lambda: summary(store, run))


def summary(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    """What happened to the planned works: the abstract-stage codes this run wrote (counted by record), the works it
    made candidates and the planned works still unscreened (a batch the budget or a stop did not reach)."""
    rid, target = run["research_id"], run["target"]
    planned = set(target["work_ids"])
    screened, _ = _screened_works(store, rid)
    codes: dict[str, int] = {}
    for row in store.conn.execute(
            "SELECT d.reason_code, v.work_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ? AND d.stage = 'abstract'"
            " AND d.superseded_at IS NULL", (run["id"],)):
        if row["work_id"] in planned:
            codes[row["reason_code"]] = codes.get(row["reason_code"], 0) + 1
    return {"planned": len(target["work_ids"]), "reason_codes": dict(sorted(codes.items())),
            "candidates": [w for w in _candidate_works(store, run["id"]) if w in planned],
            "not_screened": [w for w in target["work_ids"] if w not in screened]}
