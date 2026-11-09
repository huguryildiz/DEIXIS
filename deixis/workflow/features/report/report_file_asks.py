"""The works this research asks the person for a file for, and nothing else.

A list of its own. The screening queue asks whether to include a record, which is a different question, and before
this nothing in the app asked for a file at all: the report's basis note advised uploading PDFs in general, naming
no work and no open question.

The decision needs two things that never arrive together — a report plan, frozen while the report run writes, and
the automatic routes' own outcome, since the background fetches start after the run that queued them has ended. So
this is one function called from both points and from a person's own upload; whichever arrives last finds the other
already stored, and running it again writes nothing.

What makes a work askable is a reasoned link at the work's own level, not an empty axis: a sub-question the frozen
plan names, this work's own row under it, and that row's own cell left open (`report_coverage.open_axes_by_row`).
An axis no row answered says nothing about which work's file would answer it, and an open cell on a work that
already holds a file is not a missing file. A work is asked only after its own automatic routes settled.

How many works may be asked is the depth's own allowance, frozen in the asking run's policy (`fast_path.MODES`:
none in Quick, three in Standard, five in Deep). It is spent by the asking and over the research's whole life: an
answered ask keeps its row, so a retry, a follow-up or a report revision hands nothing back. A run queued before the
rule names no allowance and asks for nothing. A file the person adds of their own accord asks nothing and writes no
row here, so it costs them nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.features.report import report_coverage
from deixis.workflow.features.report.report_coverage import OPEN_STATES
from deixis.workflow.features.report.report_store import ReportStore

log = logging.getLogger("deixis.report_file_asks")

RULE = "file_ask_v1"
# What an open cell has to say for a file to be the thing that would answer it. `not_applicable` is the one open
# state no file settles: the sub-question does not apply to that work, so asking for its PDF asks for nothing.
ASKABLE_STATES = tuple(state for state in OPEN_STATES if state != "not_applicable")
# The step one work's full-text retrieval is recorded under, in the run that read it or in the background round
# after it. A work is askable only once this step **succeeded**, which is the one outcome that means the routes
# answered — with a file or without one. A failure does not: the step is also recorded as failed when OpenAlex's
# daily budget deferred the work, when a route never answered, and when the retrieval itself broke, and in each of
# those the routes have not had their turn. A cancelled step (the run stopped, the scope moved) is not an answer
# either. Nothing here reads the background round's own row, because that row only mirrors this step.
#
# A route added later has to be counted here too, or the person is asked before it was tried: the recovery search is
# the next slice's work and extends this check with its own per-work outcome.
FULLTEXT_STEP = "fulltext_work:"


def _routes_settled(store: Any, research_id: str, work_id: str) -> bool:
    """Whether this research's automatic full-text retrieval for this work answered, with a file or without one."""
    return bool(store.conn.execute(
        "SELECT 1 FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND s.operation_key = ? AND s.status = 'succeeded' LIMIT 1",
        (research_id, f"{FULLTEXT_STEP}{work_id}"),
    ).fetchone())


def _fetches_out(store: Any, research_id: str) -> bool:
    """Whether a background full-text fetch of this research is still queued or running: the routes are not done."""
    return bool(store.conn.execute(
        "SELECT 1 FROM fast_path_background_fetches WHERE research_id = ? AND status IN ('queued', 'running') LIMIT 1",
        (research_id,),
    ).fetchone())


def _work_has_file(store: Any, research_id: str, work_id: str) -> bool:
    """Whether any record of this work in this research already holds a file.

    The question is the work's, not the record's: a file on the preprint's row answers the sub-question the journal
    row left open. What is asked for is a file, so a file answers it — and a row may hold only one at a time
    (`source_assets_one_in_use`), which is why a work that already has one is not asked for another. Whether the
    text of that file could be read is the reading path's question, and replacing a file nobody could read is the
    person's own action on that record, not a request this list may make.
    """
    return bool(store.conn.execute(
        "SELECT 1 FROM source_assets a JOIN source_versions v ON v.id = a.source_version_id"
        " JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ?"
        " WHERE v.work_id = ? AND a.removed_at IS NULL AND m.removed_at IS NULL LIMIT 1",
        (research_id, work_id),
    ).fetchone())


def _latest_report(store: Any, research_id: str) -> dict[str, Any] | None:
    """The report whose open sub-questions may be asked about: the newest one of the research's current scope.

    It has to be the newest, and it has to have frozen its plan. A report of an older scope asks nothing, because
    its sub-questions are the ones the person has since changed; and a newer report that has not frozen its plan yet
    makes the whole list wait, because asking from the plan it is replacing would spend an allowance that cannot be
    handed back.
    """
    row = store.conn.execute(
        "SELECT id, run_id, scope_revision, plan_json IS NOT NULL AS planned FROM reports"
        " WHERE research_id = ? AND scope_revision = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (research_id, store.research(research_id)["current_scope_revision"]),
    ).fetchone()
    return dict(row) if row and row["planned"] else None


def allowance(store: Any, run_id: str) -> int | None:
    """One run's own allowance, read from its frozen policy; None when it was frozen before the rule.

    The number belongs to the discovery run that chose the depth, not to the report run that noticed the gap: a
    report run's budget carries no depth of its own. The stored request keeps that run, so the screen reads the
    allowance back from the same place however often the research is run again.
    """
    policy = store.run(run_id)["budget"].get("fast_path") or {}
    return policy["file_asks"] if policy.get("file_ask_rule") == RULE else None


def depth_run(store: Any, research_id: str, scope_revision: int) -> str | None:
    """The discovery run whose frozen policy is this research's current depth, from its own fast-path ledger."""
    row = store.conn.execute(
        "SELECT ledger_run_id FROM fast_path_ledgers WHERE research_id = ? AND scope_revision = ?"
        " ORDER BY started_at DESC, ledger_run_id DESC LIMIT 1", (research_id, scope_revision),
    ).fetchone()
    return row[0] if row else None


def asks(store: Any, research_id: str) -> list[dict[str, Any]]:
    """Every file this research has asked the person for, in the order it asked, answered ones included."""
    return [dict(row) | {"axes": json.loads(row["axes_json"])} for row in store.conn.execute(
        "SELECT * FROM person_file_asks WHERE research_id = ? ORDER BY position, rowid", (research_id,),
    )]


def advance(store: Any, research_id: str) -> list[dict[str, Any]]:
    """Open the file requests the open sub-questions justify, close the ones a file answered; the rows it opened.

    One transaction, so a call beside another writes the same list or nothing. The rows it opens are empty on every
    later call: a work is asked once. A failure is logged and asks nothing — the list is for the reader's benefit
    and never stops the run that triggered it.
    """
    try:
        return _advance(store, research_id)
    except Exception:  # noqa: BLE001 - the list never fails the run or the upload that asked for it
        log.exception("file-ask list failed: %s", research_id)
        return []


def _advance(store: Any, research_id: str) -> list[dict[str, Any]]:
    # Whether a new request may be opened rests on a report plan and on a depth; closing one that has been answered
    # rests on neither, so the two are read apart and the closing always runs.
    report = _latest_report(store, research_id)
    depth = depth_run(store, research_id, report["scope_revision"]) if report else None
    limit = allowance(store, depth) if depth else None
    open_rows: dict[str, list[dict[str, Any]]] = {}
    if report is not None and limit is not None:
        reports = ReportStore(store)
        snapshot = reports.snapshot(report["id"])
        plan = reports.report(report["id"])["plan"] or {}
        open_rows = report_coverage.open_axes_by_row(snapshot, plan)
    with transaction(store.conn):
        held = {row["work_id"]: dict(row) for row in store.conn.execute(
            "SELECT work_id, id, answered_at FROM person_file_asks WHERE research_id = ?", (research_id,))}
        # A work whose file has arrived closes its row, whether the person gave it or a later route found it. The
        # row stays: the allowance was spent by the asking, not by the answer.
        for work_id, row in held.items():
            if row["answered_at"] is None and _work_has_file(store, research_id, work_id):
                store.conn.execute(
                    "UPDATE person_file_asks SET answered_at = ?, outcome = 'file_added' WHERE id = ?",
                    (now(), row["id"]))
        if report is None or limit is None or len(held) >= limit or _fetches_out(store, research_id):
            return []
        # The works whose own row leaves a named sub-question open, in the evidence gap's own order: the plan's
        # sub-questions in their order, and within one sub-question the rows in the snapshot's order.
        candidates: dict[str, dict[str, Any]] = {}
        for source_version_id, axes in open_rows.items():
            askable = [axis for axis in axes if axis["state"] in ASKABLE_STATES]
            if not askable:
                continue
            source = store.conn.execute(
                "SELECT work_id FROM source_versions WHERE id = ?", (source_version_id,)).fetchone()
            # A frozen row whose record is gone, or whose record has left the research since: there is nothing to
            # ask for, and the upload route would refuse a file for it anyway.
            if source is None or not store.is_active_member(research_id, source_version_id):
                continue
            work_id = source["work_id"]
            if work_id in held or _work_has_file(store, research_id, work_id):
                continue
            if not _routes_settled(store, research_id, work_id):
                continue
            # One work is asked once however many of its versions the table holds: a file answers the work, and the
            # row kept is the one whose own cell opens the earliest sub-question.
            candidate = {"order": min(axis["axis_order"] for axis in askable), "work_id": work_id,
                         "source_version_id": source_version_id, "axes": askable}
            if candidate["order"] < candidates.get(work_id, {"order": candidate["order"] + 1})["order"]:
                candidates[work_id] = candidate
        opened: list[dict[str, Any]] = []
        for candidate in sorted(candidates.values(), key=lambda item: item["order"])[:limit - len(held)]:
            row = {"id": new_id("pfa"), "research_id": research_id, "work_id": candidate["work_id"],
                   "source_version_id": candidate["source_version_id"], "report_id": report["id"],
                   "run_id": depth, "scope_revision": report["scope_revision"], "rule": RULE,
                   "axes_json": dumps([{key: axis[key] for key in ("axis_id", "label", "column_id", "column_name",
                                                                   "cell_id", "state", "reading_depth")}
                                       for axis in candidate["axes"]]),
                   "position": len(held) + len(opened), "asked_at": now()}
            store.conn.execute(
                f"INSERT INTO person_file_asks ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()))
            store._event(research_id, "person_file_asked",
                         {"work_id": row["work_id"], "source_version_id": row["source_version_id"], "rule": RULE,
                          "axis_ids": [axis["axis_id"] for axis in candidate["axes"]]}, report["run_id"])
            opened.append(row)
        return opened
