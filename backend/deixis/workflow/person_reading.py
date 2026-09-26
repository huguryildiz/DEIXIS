"""A file a person added for a work of an `sw` research, and the reading it asks for (slice 18b).

When a person attaches a file to a version, the version gets the code the file asks for (`not_read_yet`, or
`text_unreadable` when it has no text layer), noted with the file (`person_pdf:<asset>`), and — when the work may be
read — a reading request (`person_pdf_requests`). The request is the only thing that puts a work at the front of the
reading order. It moves `waiting` → `planned` → `read` or `unread`, each step written with what caused it: the attach,
the frozen plan, the reading decision, or the run that ended without one. A person's retry is the only way an
`unread` request is asked again.

Nothing here replaces or removes a file (D45, D50 stay as they are), nothing withdraws a person's decision, and
nothing is read without a trace: a request whose question revision or criterion changed is stale and is left as it
was, never rewritten.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.reason_codes import reason
from deixis.storage.db import new_id, now, transaction
from deixis.workflow import fulltext
from deixis.workflow.decisions import PERSON_PDF_NOTE, DecisionStore
from deixis.workflow.store import ACTIVE_RUN_STATUSES, Store

# What a person's attach led to (the confirmation says which, and the "Your files" section keeps it).
REQUESTED = "requested"            # a code and a waiting request: the model reads the file next
MODEL_OFF = "model_off"            # a code, no request: reading is off or no criterion is frozen
UNREADABLE = "unreadable"          # `text_unreadable`, no request: the work stays on the waiting list
DECISION_STANDS = "decision_stands"  # the person's own decision stands: no code, no request
NOT_ELIGIBLE = "not_eligible"      # the work is not one the reading takes: no code, no request

# Why an `unread` request was not read.
RUN_CANCELLED, RUN_FAILED, NO_DECISION, FILE_CHANGED = "run_cancelled", "run_failed", "no_decision", "file_changed"


def note_for(asset_id: str) -> str:
    return f"{PERSON_PDF_NOTE}{asset_id}"


def attach_outcome(work: dict[str, Any], svid: str, has_text: bool, reading_on: bool) -> str:
    """What attaching a person's file to `svid` leads to, from the work as the reading plan reads it (decisions 1–4).

    Tested as if the request were already written (the fifth review round): a person's `human_pdf_wrong` on another
    version does not hold the work back once this file asks to be read, while every other decision of theirs —
    including a `human_pdf_wrong` on this very version, and a selection they set to anything but included — stands.
    """
    asked = dict(work, versions=[dict(version, person={"status": "waiting"}) if version["id"] == svid else version
                                 for version in work["versions"]])
    selection = work.get("selection") or {}
    if fulltext.decided_by_human(asked, "fulltext", reading=True) or (selection.get("origin") == "user"
                                                         and selection.get("state") != "included"):
        return DECISION_STANDS
    if fulltext.group_of(asked, reading=True) is None:
        return NOT_ELIGIBLE
    if not has_text:
        return UNREADABLE
    return REQUESTED if reading_on else MODEL_OFF


# ---- the request's states ------------------------------------------------------------------------------------------

def _event(store: Store, research_id: str, status: str, ids: list[str], run_id: str | None = None, **extra: Any) -> None:
    if ids:
        store._event(research_id, "person_pdf_request", {"status": status, "request_ids": ids, **extra}, run_id)


def insert_request(store: Store, research_id: str, svid: str, asset_id: str) -> str:
    """A waiting request for this file; the caller holds the attach's transaction."""
    revision, criterion_hash = store.criterion_key(research_id)
    rid, ts = new_id("ppr"), now()
    store.conn.execute(
        "INSERT INTO person_pdf_requests (id, research_id, source_version_id, asset_id, scope_revision, criterion_hash,"
        " status, attempt, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'waiting', 0, ?, ?)",
        (rid, research_id, svid, asset_id, revision, criterion_hash, ts, ts))
    _event(store, research_id, "waiting", [rid], source_version_id=svid, asset_id=asset_id)
    return rid


def live_waiting(store: Store, research_id: str) -> list[dict[str, Any]]:
    """The research's live `waiting` requests, oldest file first."""
    rows = [request for request in store.person_files(research_id).values() if request["status"] == "waiting"]
    return sorted(rows, key=lambda r: (r["asset_at"], r["asset_id"]))


def plan_requests(store: Store, run: dict[str, Any], plan: dict[str, Any]) -> None:
    """Mark `planned` the waiting requests whose file this plan reads, with the run and the digest it froze.

    The caller holds the transaction the plan is written in. A request past the limit stays `waiting`: the run that
    ends without it leaves it to the next one (decision 5)."""
    ids: list[str] = []
    for item in plan["works"]:
        if not item.get("asset_id"):
            continue
        for row in store.conn.execute(
                "SELECT id FROM person_pdf_requests WHERE research_id = ? AND source_version_id = ? AND asset_id = ?"
                " AND status = 'waiting' AND scope_revision = ? AND criterion_hash IS ?",
                (run["research_id"], item["read_version"], item["asset_id"], plan["scope_revision"],
                 plan["criterion_hash"])):
            store.conn.execute("UPDATE person_pdf_requests SET status = 'planned', run_id = ?, page_digest = ?,"
                               " updated_at = ? WHERE id = ?", (run["id"], item["page_digest"], now(), row["id"]))
            ids.append(row["id"])
    _event(store, run["research_id"], "planned", ids, run["id"])


def mark_read(store: Store, run: dict[str, Any], item: dict[str, Any], plan: dict[str, Any], decision_id: str) -> None:
    """The reading decision on this file was written: its request, whichever run planned it, is `read`.

    Only when the plan the decision rests on names this file, its page digest, the request's question revision and
    its criterion digest (fourth review round, 2); otherwise the request is left as it is. The caller holds the
    transaction the decision is written in."""
    if not item.get("asset_id") or "criterion_hash" not in plan:
        return
    ids = [row["id"] for row in store.conn.execute(
        "SELECT id FROM person_pdf_requests WHERE research_id = ? AND source_version_id = ? AND asset_id = ?"
        " AND status != 'read' AND scope_revision = ? AND criterion_hash IS ?",
        (run["research_id"], item["read_version"], item["asset_id"], plan["scope_revision"], plan["criterion_hash"]))]
    for request_id in ids:
        store.conn.execute("UPDATE person_pdf_requests SET status = 'read', run_id = ?, page_digest = ?,"
                           " decision_id = ?, unread_reason = NULL, updated_at = ? WHERE id = ?",
                           (run["id"], item["page_digest"], decision_id, now(), request_id))
    _event(store, run["research_id"], "read", ids, run["id"])


def close_run(store: Store, run_id: str, ended: bool = False) -> int:
    """The requests a run held and did not read become `unread` once that run has ended, with why (decision 5).

    A run holds the requests its plan made `planned`. A reading run whose plan was not frozen yet also holds every
    live `waiting` request: its plan would have taken them first. Those are closed only by the write that ends the
    run (`ended`, which `Store.update_run` passes in the same transaction), never by a later call, so a file added
    after that write stays waiting. A file added after a plan froze was never the run's and stays `waiting` too. A
    paused run keeps its requests: it can still be resumed. Idempotent for the planned ones."""
    run = store.run(run_id)
    if run["status"] not in ("completed", "failed", "cancelled"):
        return 0
    # A stale request is left as it was: the question it was asked under is gone.
    revision, criterion_hash = store.criterion_key(run["research_id"])
    why_run = (RUN_CANCELLED if run["status"] == "cancelled" else RUN_FAILED if run["status"] == "failed"
               else NO_DECISION)
    rows = store.conn.execute("SELECT id, source_version_id, asset_id, page_digest FROM person_pdf_requests"
                              " WHERE run_id = ? AND status = 'planned' AND scope_revision = ? AND criterion_hash IS ?",
                              (run_id, revision, criterion_hash)).fetchall()
    before_plan: list[dict[str, Any]] = []
    if ended and run["kind"] == "fulltext_adjudication" and run["scope_revision"] == revision:
        plan = store.existing_step(run_id, "adjudication_plan")
        if plan is None or plan["status"] != "succeeded":
            before_plan = live_waiting(store, run["research_id"])
    with transaction(store.conn):
        for row in rows:
            in_use = store.conn.execute("SELECT 1 FROM source_assets WHERE id = ? AND source_version_id = ?"
                                        " AND removed_at IS NULL", (row["asset_id"], row["source_version_id"])).fetchone()
            why = FILE_CHANGED if not in_use or store.asset_page_digest(row["asset_id"]) != row["page_digest"] else why_run
            store.conn.execute("UPDATE person_pdf_requests SET status = 'unread', unread_reason = ?, updated_at = ?"
                               " WHERE id = ?", (why, now(), row["id"]))
        _event(store, run["research_id"], "unread", [row["id"] for row in rows], run_id)
        unread_waiting(store, run["research_id"], before_plan, why_run, run_id)
    return len(rows) + len(before_plan)


def unread_waiting(store: Store, research_id: str, requests: list[dict[str, Any]], why: str,
                   run_id: str | None = None) -> None:
    """These waiting requests will not be read by the run that was to read them; the caller holds the transaction."""
    for request in requests:
        store.conn.execute("UPDATE person_pdf_requests SET status = 'unread', unread_reason = ?, run_id = COALESCE(?, run_id),"
                           " updated_at = ? WHERE id = ? AND status = 'waiting'", (why, run_id, now(), request["id"]))
    _event(store, research_id, "unread", [r["id"] for r in requests], run_id)


def changed_since_read(request: dict[str, Any]) -> bool:
    """A `read` request whose file's pages are no longer those it was read as (a new extraction, decision 6)."""
    return request["status"] == "read" and not request["holds"]


def retry(store: Store, research_id: str, request_id: str) -> dict[str, Any]:
    """A person asks for a file to be read again: the request waits again and its attempt is counted, so the queue
    opens a new run for the same file (decision 6). Only for a live request that is `unread`, or `read` from pages the
    file no longer has; refused otherwise."""
    request = next((r for r in store.person_files(research_id).values() if r["id"] == request_id), None)
    if request is None or not (request["status"] == "unread" or changed_since_read(request)):
        raise RetryRefused("This file is not waiting for another reading")
    with transaction(store.conn):
        store.conn.execute("UPDATE person_pdf_requests SET status = 'waiting', attempt = attempt + 1, run_id = NULL,"
                           " unread_reason = NULL, updated_at = ? WHERE id = ? AND status IN ('unread', 'read')",
                           (now(), request_id))
        _event(store, research_id, "waiting", [request_id], retry=True)
    return request


class RetryRefused(Exception):
    """A retry the request's state does not allow; the API answers 409."""


# ---- the "Your files" section (decision 9) --------------------------------------------------------------------------

def _verified_quotes(store: Store, svid: str, step_id: str | None) -> list[dict[str, Any]]:
    """The quotes code verified in the reading that wrote this decision, with their pages; none when it has no step."""
    if not step_id:
        return []
    seen: set[tuple[str, str]] = set()
    quotes = []
    for row in store.conn.execute(
            "SELECT criterion_part, quote, quote_page, quote_passage_id FROM model_proposals WHERE source_version_id = ?"
            " AND stage = 'fulltext' AND quote_verified = 1 AND step_id IN"
            " (SELECT id FROM run_steps WHERE run_id = (SELECT run_id FROM run_steps WHERE id = ?))"
            " ORDER BY run_no, criterion_part", (svid, step_id)):
        key = (row["criterion_part"], row["quote"])
        if key in seen:
            continue
        seen.add(key)
        quotes.append({"part": row["criterion_part"], "quote": row["quote"], "page": row["quote_page"],
                       "rendition": store.passage_rendition(row["quote_passage_id"])})
    return quotes


def files_view(store: Store, research_id: str, reading_on: bool) -> dict[str, Any]:
    """The works a person added a file to, each with what became of it, read from what is stored (decision 9).

    A file is listed while it is in use on a bibliographic record of the research and has text; a file with no text
    is on the waiting list instead (`text_unreadable`). Nothing is written.
    """
    decisions = DecisionStore(store)
    facts = decisions.facts(research_id)
    stale_key = facts["stale_key"]
    person = store.person_files(research_id)
    selections = {row["source_version_id"]: dict(row) for row in store.conn.execute(
        "SELECT source_version_id, state, origin FROM selections WHERE research_id = ?", (research_id,))}
    runs = [dict(row) for row in store.conn.execute(
        "SELECT id, kind, status, pause_reason FROM runs WHERE research_id = ? ORDER BY created_at", (research_id,))]
    active = [run for run in runs if run["status"] in ACTIVE_RUN_STATUSES]
    reading_now = _reading_now(store, research_id, active)
    rows = []
    for asset in store.conn.execute(
            "SELECT a.id, a.source_version_id, a.original_filename, a.retrieved_at, v.work_id, v.version_label"
            " FROM source_assets a JOIN source_versions v ON v.id = a.source_version_id AND v.origin != 'user_upload'"
            " JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ? AND m.removed_at IS NULL"
            " WHERE a.origin = 'user_upload' AND a.removed_at IS NULL ORDER BY a.retrieved_at, a.id", (research_id,)):
        svid, work_id = asset["source_version_id"], asset["work_id"]
        head = facts["heads"].get(work_id)
        if head is None or not store.has_pdf_text(svid):
            continue
        request = person.get(svid) if (person.get(svid) or {}).get("asset_id") == asset["id"] else None
        decision = decisions.current(research_id, svid, "fulltext")
        if decision is not None and decisions.is_stale(decision, stale_key) and decision["decided_by"] != "human":
            decision = None
        outcome = decisions.work_outcome(research_id, work_id, facts)
        selection = selections.get(head) or {}
        row = {"work_id": work_id, "head": head, "source_version_id": svid, "asset_id": asset["id"],
               "title": store.source(head)["title"], "version_label": asset["version_label"],
               "filename": asset["original_filename"], "added_at": asset["retrieved_at"],
               "request_id": request["id"] if request else None, "attempt": request["attempt"] if request else 0,
               "unread_reason": request["unread_reason"] if request else None,
               "reason_code": decision["reason_code"] if decision else None, "quotes": [], "after_run": False,
               "decided_code": None}
        # A `human_pdf_wrong` about another version's file does not stand over this one (decision 3).
        own = outcome.get("decided_by") == "human" and not (outcome.get("reason_code") == "human_pdf_wrong"
                                                           and outcome.get("source_version_id") != svid)
        if own or (selection.get("origin") == "user" and selection.get("state") != "included"):
            row |= {"state": "decision_stands",
                    "decided_code": outcome.get("reason_code") if own
                    else f"selection_{selection.get('state')}"}
        elif request is not None and request["status"] == "unread":
            row["state"] = "unread"
        elif (request is not None and changed_since_read(request)) or (
                request is None and decision is not None
                and store.decision_read_file(decision) not in (None, (asset["id"], store.asset_page_digest(asset["id"])))):
            # The file's pages are not those the reading quoted: nothing it found is shown as verified (decision 6).
            row["state"] = "changed"
        elif request is not None and request["status"] in ("waiting", "planned"):
            reading = request["status"] == "planned" and work_id in reading_now
            row |= {"state": "reading" if reading else "waiting",
                    "after_run": not reading and any(run["id"] != request["run_id"] for run in active)}
        elif decision is not None and decision["reason_code"] == "all_parts_verified":
            row |= {"state": "included", "quotes": _verified_quotes(store, svid, decision["step_id"])}
        elif decision is not None and decision["reason_code"] == "criterion_absent":
            row["state"] = "criterion_not_met"
        elif decision is not None and reason(decision["reason_code"]).next_step == "human_queue":
            row["state"] = "your_decision"
        elif decision is not None and decision["reason_code"] == "not_read_yet":
            row |= {"state": "waiting" if reading_on else "model_off", "after_run": reading_on and bool(active)}
        else:
            row["state"] = "not_eligible"
        rows.append(row)
    waiting = any(row["state"] == "waiting" for row in rows)
    paused = next((run for run in reversed(runs) if run["status"] == "paused"), None)
    return {"rows": rows, "reading_on": reading_on,
            # A paused run holds the reading back: the view offers to resume or cancel it, never a new run (decision 5).
            "paused_run": paused if waiting and paused is not None else None}


def _reading_now(store: Store, research_id: str, active: list[dict[str, Any]]) -> set[str]:
    """The works a reading step is being sent for right now, by `work_id` (the "model is reading" state)."""
    heads = []
    for run in active:
        if run["kind"] != "fulltext_adjudication":
            continue
        for row in store.conn.execute("SELECT operation_key FROM run_steps WHERE run_id = ? AND status = 'running'"
                                      " AND kind = 'model:fulltext_adjudication'", (run["id"],)):
            heads.append(row[0].removeprefix("fulltext_adjudication:").rpartition(":")[0])
    return set(store.work_ids(heads).values()) if heads else set()
