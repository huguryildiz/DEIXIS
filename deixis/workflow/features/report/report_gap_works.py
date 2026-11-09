"""The works a report's own open sub-questions point at, for the two things that act on that gap.

One reading, two callers. The open-web search for a work's full text tries to close the gap by itself
(`workflow.read.fulltext_search`), and the file-request list asks the person about what is still open afterwards
(`report_file_asks`). Both need the same answer to the same question — which work's own row leaves a sub-question of
the frozen plan open, with no file and with its automatic retrieval already answered — so neither has a rule of its
own about it, and the order they work in is the same.

The order is the evidence gap's own: the plan's sub-questions in the plan's order, and within one sub-question the
rows in the snapshot's order. It is not the stage's clock and not a row id.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.features.report import report_coverage
from deixis.workflow.features.report.report_coverage import OPEN_STATES
from deixis.workflow.features.report.report_store import ReportStore

# What an open cell has to say for a file to be the thing that would answer it. `not_applicable` is the one open
# state no file settles: the sub-question does not apply to that work, so a file of it would answer nothing.
ASKABLE_STATES = tuple(state for state in OPEN_STATES if state != "not_applicable")
# The step one work's full-text retrieval is recorded under, in the run that read it or in the background round
# after it. A work counts as retrieved only once this step **succeeded**, which is the one outcome that means the
# routes answered — with a file or without one. A failure does not: the step is also recorded as failed when
# OpenAlex's daily budget deferred the work, when a route never answered, and when the retrieval itself broke, and
# in each of those the routes have not had their turn. A cancelled step (the run stopped, the scope moved) is not an
# answer either. The background round's own row is never read, because that row only mirrors this step.
FULLTEXT_STEP = "fulltext_work:"


def retrieval_answered(store: Any, research_id: str, work_id: str) -> bool:
    """Whether this research's automatic full-text retrieval for this work answered, with a file or without one."""
    return bool(store.conn.execute(
        "SELECT 1 FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND s.operation_key = ? AND s.status = 'succeeded' LIMIT 1",
        (research_id, f"{FULLTEXT_STEP}{work_id}"),
    ).fetchone())


def fetches_out(store: Any, research_id: str) -> bool:
    """Whether a background full-text fetch of this research is still queued or running: the routes are not done."""
    return bool(store.conn.execute(
        "SELECT 1 FROM fast_path_background_fetches WHERE research_id = ? AND status IN ('queued', 'running') LIMIT 1",
        (research_id,),
    ).fetchone())


def work_has_file(store: Any, research_id: str, work_id: str) -> bool:
    """Whether any record of this work in this research already holds a file.

    The question is the work's, not the record's: a file on the preprint's row answers the sub-question the journal
    row left open, and a row holds one file at a time (`source_assets_one_in_use`).
    """
    return bool(store.conn.execute(
        "SELECT 1 FROM source_assets a JOIN source_versions v ON v.id = a.source_version_id"
        " JOIN corpus_memberships m ON m.source_version_id = v.id AND m.research_id = ?"
        " WHERE v.work_id = ? AND a.removed_at IS NULL AND m.removed_at IS NULL LIMIT 1",
        (research_id, work_id),
    ).fetchone())


def latest_report(store: Any, research_id: str) -> dict[str, Any] | None:
    """The report whose open sub-questions may be acted on: the newest one of the research's current scope.

    It has to be the newest, and it has to have frozen its plan. A report of an older scope points at nothing,
    because its sub-questions are the ones the person has since changed; and a newer report that has not frozen its
    plan yet makes both callers wait, because acting on the plan it is replacing would spend a budget on a question
    nobody asked any more.
    """
    row = store.conn.execute(
        "SELECT id, run_id, scope_revision, plan_json IS NOT NULL AS planned FROM reports"
        " WHERE research_id = ? AND scope_revision = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (research_id, store.research(research_id)["current_scope_revision"]),
    ).fetchone()
    return dict(row) if row and row["planned"] else None


def depth_run(store: Any, research_id: str, scope_revision: int) -> str | None:
    """The discovery run whose frozen policy is this research's depth, from its own fast-path ledger.

    Both budgets here belong to that run, not to the report run that noticed the gap: a report run's own budget
    carries no depth.
    """
    row = store.conn.execute(
        "SELECT ledger_run_id FROM fast_path_ledgers WHERE research_id = ? AND scope_revision = ?"
        " ORDER BY started_at DESC, ledger_run_id DESC LIMIT 1", (research_id, scope_revision),
    ).fetchone()
    return row[0] if row else None


def frozen_number(store: Any, run_id: str, rule_key: str, rule: str, number_key: str) -> int | None:
    """One number of a run's frozen policy, read only when the policy names the rule it belongs to.

    A run queued before that rule carries neither key, and then the answer is None rather than a default: a budget
    nobody froze is not a budget, and the work it would pay for does not happen.
    """
    policy = store.run(run_id)["budget"].get("fast_path") or {}
    return policy[number_key] if policy.get(rule_key) == rule else None


def gap_works(store: Any, research_id: str) -> dict[str, Any] | None:
    """The report, its depth run and the works whose own row leaves one of its sub-questions open.

    None when there is nothing to act on: no report of the current scope with a frozen plan, or a background
    full-text fetch of the research still out, which means the automatic routes are not done.

    A work is listed once however many of its versions the table holds, on the row whose own cell opens the earliest
    sub-question; a row whose record is gone or has left the research is skipped, since nothing can be fetched for it
    and the person could not upload to it either.
    """
    report = latest_report(store, research_id)
    if report is None or fetches_out(store, research_id):
        return None
    reports = ReportStore(store)
    plan = reports.report(report["id"])["plan"] or {}
    open_rows = report_coverage.open_axes_by_row(reports.snapshot(report["id"]), plan)
    works: dict[str, dict[str, Any]] = {}
    for source_version_id, axes in open_rows.items():
        open_axes = [axis for axis in axes if axis["state"] in ASKABLE_STATES]
        if not open_axes:
            continue
        source = store.conn.execute(
            "SELECT work_id FROM source_versions WHERE id = ?", (source_version_id,)).fetchone()
        if source is None or not store.is_active_member(research_id, source_version_id):
            continue
        work_id = source["work_id"]
        if work_has_file(store, research_id, work_id) or not retrieval_answered(store, research_id, work_id):
            continue
        found = {"order": min(axis["axis_order"] for axis in open_axes), "work_id": work_id,
                 "source_version_id": source_version_id, "axes": open_axes}
        if found["order"] < works.get(work_id, {"order": found["order"] + 1})["order"]:
            works[work_id] = found
    return {"report": report, "depth": depth_run(store, research_id, report["scope_revision"]),
            "works": sorted(works.values(), key=lambda item: item["order"])}
