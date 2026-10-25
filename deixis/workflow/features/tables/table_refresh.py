"""D52: evidence table cells a model or the system read from the abstract or metadata are read again once PDF text
of their source arrives.

A sweep, like `late_revision.advance`: it does nothing while a run of the research is queued, running or paused, or
while a background PDF fetch of the research is still out, so the PDFs of one fetch round are read in one run. It
queues at most one `table_fill` run per table, marked `auto_refresh`. Its idempotency key names the planned cells and
the newest PDF text of each source, so a repeated sweep never queues a second run; a cell an automatic re-read already
planned since its newest PDF text (one that failed, paused, or gave no answer for it) is not planned again until new PDF
text arrives.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from deixis.storage.db import dumps, transaction
from deixis.workflow.features.tables.tables import DUE_SQL, TableStore

log = logging.getLogger("deixis.table_refresh")
BUSY = ("queued", "running", "pause_requested", "paused")


def _busy(store: Any, rid: str) -> bool:
    return bool(store.conn.execute(
        f"SELECT 1 FROM runs WHERE research_id = ? AND status IN ({', '.join('?' * len(BUSY))}) LIMIT 1", (rid, *BUSY)
    ).fetchone() or store.conn.execute(
        "SELECT 1 FROM fast_path_background_fetches WHERE research_id = ? AND status IN ('queued', 'running') LIMIT 1", (rid,)
    ).fetchone())


def _key(store: Any, scope_revision: int, plan: dict[str, Any]) -> str:
    marks = []
    for source in plan["sources"]:
        newest = store.conn.execute(
            "SELECT MAX(p.created_at) FROM passages p JOIN source_assets a ON a.id = p.asset_id"
            " WHERE p.source_version_id = ? AND a.removed_at IS NULL", (source["source_version_id"],)).fetchone()[0]
        marks.append([source["source_version_id"], sorted(source["column_ids"]), newest])
    return hashlib.sha256(dumps([scope_revision, sorted(marks)]).encode()).hexdigest()[:32]


def advance(store: Any, rid: str | None = None) -> list[dict[str, Any]]:
    """Queue the automatic re-reads that are due; returns the runs it queued."""
    # A first pass in one query, run about once a second by an idle worker: tables holding a due cell (DUE_SQL, the
    # same rule the refresh plan applies). An idle library finds none. The plan then applies the remaining rules
    # (active rows and columns, sources in the research, at most MAX_FILL_SOURCES sources per run).
    candidates = store.conn.execute(
        "SELECT DISTINCT et.research_id, et.id FROM evidence_tables et JOIN researches rs ON rs.id = et.research_id"
        " JOIN evidence_cells c ON c.table_id = et.id JOIN cell_revisions r ON r.id = c.current_revision_id"
        f" WHERE et.trashed_at IS NULL AND rs.trashed_at IS NULL AND {DUE_SQL.format(cell='c', revision='r')}"
        + (" AND et.research_id = ?" if rid else "")
        + " ORDER BY et.created_at", (rid,) if rid else ()).fetchall()
    tables, queued = TableStore(store), []
    for research_id, table_id in candidates:
        try:
            with transaction(store.conn):
                if _busy(store, research_id):
                    continue
                plan = tables.fill_plan(research_id, table_id, refresh=True)
                if not plan["sources"]:
                    continue
                scope_revision = store.research(research_id)["current_scope_revision"]
                version = store.conn.execute("SELECT version FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()[0]
                key = f"table_refresh:{table_id}:{_key(store, scope_revision, plan)}"
                queued.append(tables.request_fill(research_id, table_id, None, False, version, key, refresh=True))
        except Exception:  # noqa: BLE001 - one table must not hold up the worker or the other tables
            log.exception("queueing the automatic re-read of table %s failed", table_id)
    return queued
