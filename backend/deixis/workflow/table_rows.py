"""D63: a table made from the included sources follows them.

A sweep, run at the same points as `table_refresh.advance`. First, every included source of a following table's
research that was never a row of it gets a row (`added_by = 'included_later'`): a plain insert, done whatever runs are
active, since a running fill keeps the plan it stored and a report keeps the snapshot it saved. A row a person removed is
never added back, and a source excluded later keeps its row; the table marks it as not in the report.

Then the empty cells of those rows are filled by the ordinary fill path: one `table_fill` run per table, marked
`auto_rows` and `included_only`, queued only while no run of the research is queued, running or pause_requested and no
background PDF fetch of it is out. A paused run does not hold it (unlike D52's re-read): `create_run` already lets a
run start beside a paused one. A cell is due when its row is one the app added, its source is still included, its
column existed when the row was added or was accepted by the study-table chain, and no fill of the table planned it
since the row was added; so a fill that failed, paused or was cancelled is not queued again, and a person fills those
cells from the table. An answer that fails only its own checks (a quote not found, say) is asked once more by the
fill and otherwise stored as not verified when it has a value (D68); a call that fails as a whole fills none of its
cells. Neither stops the report.

Every following table gets its own fill: a cell belongs to one table's column (its own instruction and format), and a
report is written from one table, so the same new source is a separate set of questions in each table.

D114: a table made from the research (`follows_included = 2`) also follows the works read from their abstracts only
(`table_sources`). Such a work gets a row when it has never had one in the table, matched by work, so a new head of a
work adds no second row; its cells are due by the same rules as an included source's.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from deixis.storage.db import dumps, now, transaction
from deixis.workflow.store import ACTIVE_RUN_STATUSES
from deixis.workflow.table_sources import FOLLOWS_TABLE_SOURCES, new_abstract_rows, table_sources
from deixis.workflow.tables import InvalidTableInput, TableStore

log = logging.getLogger("deixis.table_rows")

_FOLLOWING = ("FROM evidence_tables et JOIN researches rs ON rs.id = et.research_id"
              " JOIN selections s ON s.research_id = et.research_id AND s.state = 'included'"
              " JOIN corpus_memberships m ON m.research_id = s.research_id AND m.source_version_id = s.source_version_id"
              " AND m.removed_at IS NULL")
_LIVE = "et.follows_included >= 1 AND et.trashed_at IS NULL AND rs.trashed_at IS NULL"
# Included sources of a following table's research that were never rows of it.
NEW_ROWS_SQL = (f"SELECT et.research_id, et.id, s.source_version_id {_FOLLOWING} WHERE {_LIVE}"
                " AND NOT EXISTS (SELECT 1 FROM table_rows t WHERE t.table_id = et.id AND t.source_version_id = s.source_version_id)"
                " ORDER BY et.created_at, s.updated_at, s.source_version_id")
# Tables made from the research (D114): they also follow the works read from their abstracts only.
TABLE_SOURCE_TABLES_SQL = ("SELECT et.research_id, et.id FROM evidence_tables et JOIN researches rs ON rs.id = et.research_id"
                           f" WHERE et.follows_included = {FOLLOWS_TABLE_SOURCES} AND et.trashed_at IS NULL AND rs.trashed_at IS NULL"
                           " ORDER BY et.created_at, et.id")
# Empty cells of rows the app added, in columns that existed when the row was added or that the study-table chain
# accepted, which no fill of the table planned since the row was added. Whether the row's source is still one the table
# follows (included, or for a D114 table read from its abstract only) is checked in Python by `_following`.
DUE_CELLS_SQL = (
    "SELECT et.research_id, et.id, t.source_version_id, k.id FROM evidence_tables et JOIN researches rs ON rs.id = et.research_id"
    " JOIN table_rows t ON t.table_id = et.id AND t.added_by = 'included_later' AND t.removed_at IS NULL"
    " JOIN corpus_memberships m ON m.research_id = et.research_id AND m.source_version_id = t.source_version_id"
    " AND m.removed_at IS NULL"
    " JOIN table_columns k ON k.table_id = et.id AND k.removed_at IS NULL"
    " AND (k.created_at <= t.created_at OR k.accepted_by = 'automatic')"
    f" WHERE {_LIVE}"
    " AND NOT EXISTS (SELECT 1 FROM evidence_cells c WHERE c.column_id = k.id AND c.source_version_id = t.source_version_id"
    " AND c.current_revision_id IS NOT NULL)"
    " AND NOT EXISTS (SELECT 1 FROM runs fr, json_each(fr.target_json, '$.sources') fs WHERE fr.kind = 'table_fill'"
    " AND json_extract(fr.target_json, '$.table_id') = et.id AND fr.created_at >= t.created_at"
    " AND json_extract(fs.value, '$.source_version_id') = t.source_version_id"
    " AND EXISTS (SELECT 1 FROM json_each(fs.value, '$.column_ids') fc WHERE fc.value = k.id))"
    " ORDER BY et.created_at, t.created_at, t.source_version_id, k.position")


def _busy(store: Any, rid: str) -> bool:
    return bool(store.conn.execute(
        f"SELECT 1 FROM runs WHERE research_id = ? AND status IN ({', '.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
        (rid, *ACTIVE_RUN_STATUSES),
    ).fetchone() or store.conn.execute(
        "SELECT 1 FROM fast_path_background_fetches WHERE research_id = ? AND status IN ('queued', 'running') LIMIT 1", (rid,)
    ).fetchone())


def add_rows(store: Any, rid: str | None = None) -> dict[str, list[str]]:
    """Give every following table a row for each included source that was never its row; returns them per table."""
    found: dict[tuple[str, str], list[str]] = {}
    for research_id, table_id, svid in store.conn.execute(
            NEW_ROWS_SQL.replace(" ORDER BY", " AND et.research_id = ? ORDER BY") if rid else NEW_ROWS_SQL, (rid,) if rid else ()):
        found.setdefault((research_id, table_id), []).append(svid)
    for research_id, table_id in store.conn.execute(
            TABLE_SOURCE_TABLES_SQL.replace(" ORDER BY", " AND et.research_id = ? ORDER BY") if rid else TABLE_SOURCE_TABLES_SQL,
            (rid,) if rid else ()).fetchall():
        try:
            for svid in new_abstract_rows(store, research_id, table_id):
                found.setdefault((research_id, table_id), []).append(svid)
        except Exception:  # noqa: BLE001 - one table must not hold up the worker or the other tables
            log.exception("reading the abstract-only works of table %s failed", table_id)
    tables, added = TableStore(store), {}
    for (research_id, table_id), svids in found.items():
        try:
            with transaction(store.conn):
                ts = now()
                inserted = [svid for svid in svids if store.conn.execute(
                    "INSERT INTO table_rows (table_id, source_version_id, added_by, created_at) VALUES (?, ?, 'included_later', ?)"
                    " ON CONFLICT (table_id, source_version_id) DO NOTHING", (table_id, svid, ts)).rowcount]
                if inserted:
                    tables._touch(table_id, bump=True)
                    tables._changed(research_id, table_id, rows_added=len(inserted), added_by="included_later")
                    added[table_id] = inserted
        except Exception:  # noqa: BLE001 - one table must not hold up the worker or the other tables
            log.exception("adding the newly included rows of table %s failed", table_id)
    return added


def advance(store: Any, rid: str | None = None) -> list[dict[str, Any]]:
    """Add the rows, then queue the fills that are due; returns the runs it queued."""
    add_rows(store, rid)
    due: dict[tuple[str, str], dict[str, list[str]]] = {}
    following: dict[str, set[str]] = {}
    for research_id, table_id, svid, column_id in store.conn.execute(
            DUE_CELLS_SQL.replace(" ORDER BY", " AND et.research_id = ? ORDER BY") if rid else DUE_CELLS_SQL, (rid,) if rid else ()).fetchall():
        if table_id not in following:
            following[table_id] = set(table_sources(store, research_id, table_id))
        if svid not in following[table_id]:
            continue
        due.setdefault((research_id, table_id), {}).setdefault(svid, []).append(column_id)
    tables, queued, waiting = TableStore(store), [], set()
    for (research_id, table_id), only in due.items():
        if research_id in waiting:
            continue
        try:
            with transaction(store.conn):
                if _busy(store, research_id):
                    waiting.add(research_id)  # one run at a time per research; the next sweep takes this table
                    continue
                version = store.conn.execute("SELECT version FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()[0]
                digest = hashlib.sha256(dumps(sorted([svid, sorted(cols)] for svid, cols in only.items())).encode()).hexdigest()[:32]
                queued.append(tables.request_fill(research_id, table_id, None, False, version, f"table_rows:{table_id}:{digest}",
                                                  included_only=True, only=only))
                waiting.add(research_id)
        except InvalidTableInput:
            continue  # nothing left to fill once the plan applied its own rules
        except Exception:  # noqa: BLE001 - one table must not hold up the worker or the other tables
            log.exception("queueing the fill of the newly included rows of table %s failed", table_id)
    return queued
