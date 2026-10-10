"""The study table: a chain of the existing runs that follows a valid answer, queued one after another.

table_columns -> table_fill (one run per 25 sources). It ends with the filled table; a manuscript draft is a separate,
person-started report run. Nothing here is a new evidence or verification path: every step is the run the Evidence tab
starts by hand. The proposed columns join the table without a person reviewing them (`table_columns.accepted_by =
'automatic'`, and an event).
"""

from __future__ import annotations

import math
from typing import Any

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import dumps, transaction
from deixis.workflow.store import Store
from deixis.workflow.tables import MAX_FILL_SOURCES, InvalidTableInput, TableStore

MAX_FILL_ROUNDS = 8  # 200 sources; a larger corpus leaves its last sources unfilled and the report says so
PIPELINE = "study_table"


def after_answer(store: Store, run: dict[str, Any]) -> None:
    """Open the chain once for a completed answer run that produced a structurally valid answer."""
    answer = store.conn.execute("SELECT id, scope_revision FROM answers WHERE run_id = ? AND status = 'structurally_valid'",
                                (run["id"],)).fetchone()
    if answer is None:
        return
    research = store.research(run["research_id"])
    # An answer to an earlier revision of the question opens no table.
    if answer["scope_revision"] != research["current_scope_revision"]:
        return
    try:
        start(store, run["research_id"], f"answer:{answer['id']}")
    except RevisionConflict:
        pass  # nothing included, or another run is active; the person can rebuild the table from the Answer screen's link


def start(store: Store, research_id: str, idempotency_key: str | None) -> dict[str, Any]:
    """Create the table of the included sources and queue the column proposal that opens the chain."""
    tables = TableStore(store)
    base = f"{PIPELINE}:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        included = store.included_sources(research_id)
        if not included:
            raise RevisionConflict("Include at least one source before building the study table")
        table_id = tables.create_table(research_id, "Study table", None, None, f"{base}:table" if base else None)
        run = tables.request_column_suggestions(research_id, table_id, f"{base}:columns" if base else None)
        if not (run["target"] or {}).get("pipeline"):
            rounds = min(MAX_FILL_ROUNDS, math.ceil(len(included) / MAX_FILL_SOURCES))
            run = _mark(store, run, {"id": run["id"], "rounds": rounds, "round": 0, "scope_revision": run["scope_revision"],
                                     "included": len(included)})
    return run


def _mark(store: Store, run: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    return store.update_run(run["id"], target_json=dumps({**(run["target"] or {}), "pipeline": pipeline}))


def continue_after(store: Store, run: dict[str, Any]) -> None:
    """Queue the next run of a chain after a completed run of it; any other run is ignored."""
    pipeline = (run.get("target") or {}).get("pipeline")
    if not isinstance(pipeline, dict) or store.run(run["id"])["status"] != "completed":
        return
    rid, table_id, pid = run["research_id"], run["target"]["table_id"], pipeline["id"]
    tables = TableStore(store)
    if store.research(rid)["current_scope_revision"] != pipeline["scope_revision"]:
        # Columns proposed for an earlier question are never carried into a report of the new one.
        _event(store, run, "study_table_stopped", {"table_id": table_id, "reason": "scope_revised"})
        return
    if run["kind"] == "table_columns":
        if not _accept_columns(store, tables, run, pid):
            return
        _queue_fill(store, tables, run, table_id, pipeline, 1)
    elif run["kind"] == "table_fill":
        if pipeline["round"] < pipeline["rounds"] and _queue_fill(store, tables, run, table_id, pipeline, pipeline["round"] + 1):
            return
        _finish(store, run, table_id, pipeline)


def _event(store: Store, run: dict[str, Any], type_: str, payload: dict[str, Any]) -> None:
    store._event(run["research_id"], type_, payload, run["id"])


def _accept_columns(store: Store, tables: TableStore, run: dict[str, Any], pid: str) -> bool:
    """Add the proposed columns, marked as accepted by the app. False (and a recorded stop) when none could be added."""
    table_id = run["target"]["table_id"]
    suggestion = tables.column_suggestions(table_id)
    added, skipped = 0, []
    with transaction(store.conn):
        if store.conn.execute("SELECT 1 FROM events WHERE run_id = ? AND type = 'study_table_columns_accepted'",
                              (run["id"],)).fetchone():
            return bool(tables._columns(table_id))  # a replayed continue: already accepted and recorded
        if suggestion is not None and suggestion["run_id"] == run["id"]:
            for index, column in enumerate(suggestion["columns"]):
                spec = {k: column.get(k) for k in ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")}
                version = tables._table(run["research_id"], table_id)["version"]
                try:
                    tables.add_column(run["research_id"], table_id, spec, version, f"{PIPELINE}:{pid}:col:{index}",
                                      origin="model_suggestion", suggestion_step_id=suggestion["step_id"], accepted_by="automatic")
                    added += 1
                except InvalidTableInput as exc:
                    skipped.append({"name": column.get("name"), "reason": str(exc)})
        _event(store, run, "study_table_columns_accepted",
               {"table_id": table_id, "accepted_by": "automatic", "reviewed_by_person": False, "added": added, "skipped": skipped})
    if not added:
        _event(store, run, "study_table_stopped", {"table_id": table_id, "reason": "no_columns"})
    return bool(added)


def _queue_fill(store: Store, tables: TableStore, run: dict[str, Any], table_id: str, pipeline: dict[str, Any], round_: int) -> bool:
    rid = run["research_id"]
    """Queue fill round `round_`; False when no cell is left to fill (the caller then goes on to the report)."""
    version = tables._table(rid, table_id)["version"]
    try:
        with transaction(store.conn):
            fill = tables.request_fill(rid, table_id, None, True, version, f"{PIPELINE}:{pipeline['id']}:fill:{round_}")
            _mark(store, fill, {**pipeline, "round": round_})
    except InvalidTableInput:
        if round_ == 1:
            _finish(store, run, table_id, pipeline)
        return False
    return True


def _stale_cells(store: Store, table_id: str) -> int:
    """Cells of active columns whose current value was made under an earlier revision of its column."""
    return store.conn.execute(
        "SELECT COUNT(*) FROM evidence_cells c JOIN cell_revisions r ON r.id = c.current_revision_id"
        " JOIN table_columns k ON k.id = c.column_id WHERE c.table_id = ? AND k.removed_at IS NULL"
        " AND r.column_revision != k.current_revision", (table_id,)).fetchone()[0]


def _finish(store: Store, run: dict[str, Any], table_id: str, pipeline: dict[str, Any]) -> None:
    """The chain ends with a filled table: no report is queued. What it did not reach is recorded, not hidden."""
    stale = _stale_cells(store, table_id)
    beyond = pipeline.get("included", 0) > pipeline.get("rounds", 0) * MAX_FILL_SOURCES
    _event(store, run, "study_table_ready", {"table_id": table_id, "stale_cells": stale, "sources_beyond_limit": beyond})
