"""The works of a discovery's frozen ranking that were never screened, and the run that screens the next of them
(UI parity S20, F12 and F13).

A discovery screens the first N works of its frozen list (`small_batch:v1:list`); everything below that line is found
but not read. `unscreened` lists those works in the list's order. `request` queues a `screen_more` run for the next
`SIZE` of them that have an abstract to read, and `execute` runs the discovery's own abstract stage over exactly those
works: code first, then two model runs per batch of `ABSTRACT_BATCH`, each batch closed by `abstract_stage.combine`.
Nothing is included here (SW1.2): a work the two runs agree on becomes an abstract-stage candidate, and only a person
or a full-text reading includes it.

A work counts as screened once a person decided it, or it holds a current (not stale) decision at the full-text stage
or an abstract-stage decision other than "not read" (`NOT_READ_CODES`: the stage's own unread codes, and the lookup's
"no abstract" codes, which say no abstract was there to read, so a version that has one can still be read). The list's position and the
embedding similarity it was frozen with are prioritization signals (AGENTS.md), never relevance or quality.
"""

from __future__ import annotations

import json
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
NOT_READ_CODES = abstract_stage.UNREAD_CODES + ("no_abstract", "abstract_not_found")
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
            if decision["stage"] == "fulltext" or decision["reason_code"] not in NOT_READ_CODES:
                screened.add(work_id)
                break
    screened |= {row[0] for row in store.conn.execute(
        "SELECT v.work_id FROM selections s JOIN source_versions v ON v.id = s.source_version_id"
        " WHERE s.research_id = ? AND s.origin = 'user' AND s.state IN ('included', 'excluded')", (rid,))}
    return screened, facts["heads"]


def _works_with_abstract(store: Any, rid: str) -> dict[str, set[str]]:
    """The versions still in the research with an abstract of their own, by work."""
    found: dict[str, set[str]] = {}
    for row in store.conn.execute(
            "SELECT DISTINCT v.id, v.work_id FROM passages p JOIN source_versions v ON v.id = p.source_version_id"
            " JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ? AND m.removed_at IS NULL"
            " WHERE p.kind = 'abstract' AND length(trim(p.text)) > 0", (rid,)):
        found.setdefault(row["work_id"], set()).add(row["id"])
    return found


def _readable_works(store: Any, rid: str, with_abstract: dict[str, set[str]]) -> set[str]:
    """Works the abstract stage can send to the model, by the stage's own rule: it builds its rows from search
    candidates only (`ResearchFlow._abstract_stage`), and reads a version with an abstract of its own whose current
    abstract decision is not a lookup code (`abstract_stage.reading_version`). An abstract on a version that is not a
    candidate (another version a provider listed) is never sent."""
    candidates = {c["source_version_id"] for c in store.candidates(rid)}
    lookup = {row[0] for row in store.conn.execute(
        "SELECT source_version_id FROM stage_decisions WHERE research_id = ? AND stage = 'abstract'"
        f" AND superseded_at IS NULL AND reason_code IN ({','.join('?' * len(abstract_stage.LOOKUP_CODES))})",
        (rid, *abstract_stage.LOOKUP_CODES))}
    return {work_id for work_id, svids in with_abstract.items() if any(s in candidates and s not in lookup for s in svids)}


def _tried_without_result(store: Any, rid: str, revision: int) -> set[tuple[str, str]]:
    """(work, head) pairs a completed Screen more run of this revision planned and wrote no decision for: the stage
    could not read them, so they are not planned again while the work keeps that head (a run reaches every batch; a
    batch the budget left still writes `abstract_not_read`, and an unusable answer writes `abstract_not_proposed`)."""
    tried: set[tuple[str, str]] = set()
    for run in store.conn.execute("SELECT id, target_json FROM runs WHERE research_id = ? AND kind = 'screen_more'"
                                  " AND scope_revision = ? AND status = 'completed'", (rid, revision)):
        wrote = {row[0] for row in store.conn.execute(
            "SELECT DISTINCT v.work_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ?", (run["id"],))}
        target = json.loads(run["target_json"])
        tried |= {(work_id, head) for work_id, head in zip(target["work_ids"], target["heads"]) if work_id not in wrote}
    return tried


def _unscreened(store: Any, rid: str, listing: dict[str, Any]) -> list[dict[str, Any]]:
    """The list's never-screened works, in list order, each with its current head and whether it can be read.

    A work no longer in the research is left out. `screenable` holds only what the abstract stage will actually send:
    a head that is a search candidate of the current revision (the stage plans by head) and a readable version
    (`_readable_works`), and not a work an earlier completed run already planned without result. This run fetches no
    abstracts (no provider request), so any other work stays listed, with the reason, and is never planned: no run
    plans a work it cannot read, and none can loop on one.
    """
    revision = store.research(rid)["current_scope_revision"]
    screened, heads = _screened_works(store, rid)
    with_abstract = _works_with_abstract(store, rid)
    readable = _readable_works(store, rid, with_abstract)
    tried = _tried_without_result(store, rid, revision)
    offered = {c["source_version_id"] for c in store.candidates(rid, revision) if c["origin"] != "user"}
    rows = []
    for item in listing["items"]:
        work_id = item["work_id"]
        head = heads.get(work_id)
        if head is None or work_id in screened:
            continue
        reason = ("no_abstract" if work_id not in with_abstract else
                  "abstract_not_on_a_searched_version" if work_id not in readable or head not in offered else
                  "screen_more_could_not_read" if (work_id, head) in tried else None)
        rows.append({"item": item, "head": head, "has_abstract": work_id in with_abstract,
                     "screenable": reason is None, "not_screenable_reason": reason})
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
            "not_screenable_reason": row["not_screenable_reason"],
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
    """Works this run's two model reads made abstract-stage candidates, whose decision still stands. A code candidate
    (both gate blocks in the title) read no abstract, so it is not evidence a later answer can take (`answer_admissions`)
    and does not move the selection revision; the person can still include it by hand."""
    return sorted({row[0] for row in store.conn.execute(
        "SELECT DISTINCT v.work_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
        " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ? AND d.stage = 'abstract'"
        " AND d.outcome = 'candidate' AND d.decided_by = 'model_agreement' AND d.superseded_at IS NULL", (run_id,))})


def mark_answer(store: Any, run: dict[str, Any]) -> None:
    """Move the research's selection revision once per new set of candidates this run made, so an answer made before
    them reads as made for an earlier selection (`result_applicability`: `stale_selection`). A new answer the person
    starts may read them (`answer_admissions`). Keyed by the set, a replay or a resent batch writes nothing twice.

    Called inside the transaction that writes a batch's decisions (`ResearchFlow._close_abstract_batch` runs it as the
    run's close hook), so a crash cannot leave candidates stored and the earlier answer still `current`."""
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
    """Current abstract-stage candidates the two model reads of a `screen_more` run of this question revision wrote,
    by record: the decision, its step and its run."""
    decisions = DecisionStore(store)
    key = decisions.staleness_key(rid)
    found = {}
    for row in store.conn.execute(
            "SELECT d.*, s.run_id AS screen_run_id FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND r.kind = 'screen_more' AND r.scope_revision = ?"
            " AND d.stage = 'abstract' AND d.outcome = 'candidate' AND d.decided_by = 'model_agreement'"
            " AND d.superseded_at IS NULL", (rid, scope_revision)):
        decision = dict(row)
        if not decisions.is_stale(decision, key):
            found[decision["source_version_id"]] = {"decision_id": decision["id"], "step_id": decision["step_id"],
                                                    "run_id": decision["screen_run_id"]}
    return found


def answer_admissions(store: Any, rid: str, scope_revision: int) -> dict[str, dict[str, Any]]:
    """The Screen more candidates a new, person-started answer may read beyond the read cutoff, by record (the version
    the two runs read), each with the abstract passages to give; fail-closed.

    A record is left out when its work left the research; when the person's own selection of the work's current head
    is anything but included (the head may have changed since the cutoff: a published version of a screened preprint),
    or the person excluded or set back any version of the work; when the work's outcome is a full-text or abstract
    exclusion or `versions_disagree`; and when the record's stored title, abstract, DOI, year or venue is no longer
    what both model runs were shown (`small_batch.abstract_reusable`), so only the abstract text read then is given.
    """
    from deixis.workflow.flow import MAX_ABSTRACT_CHARS
    from deixis.workflow.ranking import _versions

    found = answer_candidates(store, rid, scope_revision)
    if not found:
        return {}
    decisions = DecisionStore(store)
    facts = decisions.facts(rid)
    heads = facts["heads"]
    work_of = store.work_ids(list(found))
    person: dict[str, dict[str, str]] = {}
    for row in store.conn.execute(
            "SELECT s.source_version_id, s.state, v.work_id FROM selections s JOIN source_versions v"
            " ON v.id = s.source_version_id WHERE s.research_id = ? AND s.origin = 'user'", (rid,)):
        person.setdefault(row["work_id"], {})[row["source_version_id"]] = row["state"]
    candidate_ids = {c["source_version_id"]: c["candidate_id"] for c in store.candidates(rid)}
    versions = _versions(store, rid)
    admitted = {}
    for svid, info in found.items():
        work_id = work_of.get(svid)
        head = heads.get(work_id)
        if head is None or svid not in versions or svid not in candidate_ids:
            continue
        chosen = person.get(work_id, {})
        if head in chosen and chosen[head] != "included":
            continue
        if head not in chosen and any(state != "included" for state in chosen.values()):
            continue
        outcome = decisions.work_outcome(rid, work_id, facts)
        if outcome.get("outcome") in ("criterion_not_met", "out_of_scope") or outcome.get("reason_code") == "versions_disagree":
            continue
        if not small_batch.abstract_reusable(store, {"step_id": info["step_id"]}, candidate_ids[svid], versions[svid],
                                             MAX_ABSTRACT_CHARS):
            continue
        abstract_ids = [row[0] for row in store.conn.execute(
            "SELECT id FROM passages WHERE source_version_id = ? AND kind = 'abstract' ORDER BY rowid LIMIT 1", (svid,))]
        admitted[svid] = info | {"work_id": work_id, "current_head": head, "abstract_ids": abstract_ids}
    return admitted


def admissions_by_work(admitted: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One admitted record per work, the version the runs read: the work's current head when it is one of them, else
    the smallest identifier, so which row came first cannot choose."""
    by_work: dict[str, dict[str, Any]] = {}
    for svid in sorted(admitted):
        info = admitted[svid] | {"source_version_id": svid}
        held = by_work.get(info["work_id"])
        if held is None or (svid == info["current_head"] and held["source_version_id"] != info["current_head"]):
            by_work[info["work_id"]] = info
    return by_work


def answer_view(store: Any, answer_run_id: str | None) -> list[dict[str, Any]]:
    """The works an answer read beyond its read cutoff because a Screen more run made them candidates: abstract-based
    evidence screened after the cutoff, for the answer view to label as such."""
    from deixis.workflow import fast_answer
    from deixis.workflow.late_revision import REVISION_INPUT

    if answer_run_id is None:
        return []
    step = store.existing_step(answer_run_id, REVISION_INPUT) or store.existing_step(answer_run_id, fast_answer.INPUT)
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return []
    return [{"work_id": row["work_id"], "source_version_id": row["source_version_id"],
             "cutoff_source_version_id": row.get("cutoff_source_version_id"),
             "screen_more_run_id": row["screened_after_cutoff"], "evidence_basis": row.get("evidence_basis"),
             "route": row["route"]}
            for row in step["output"].get("items", []) if row.get("screened_after_cutoff")]


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
    heads = target["heads"]
    # Every batch close publishes its decisions and the selection-revision move in one transaction.
    flow._abstract_close_hooks[run_id] = lambda: mark_answer(store, run)
    try:
        await flow._abstract_stage(run, scope, vocabulary, order=heads, batch_key=BATCH_KEY, read_limit=len(heads))
    finally:
        flow._abstract_close_hooks.pop(run_id, None)
    flow._checkpoint(run_id, revision)
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
