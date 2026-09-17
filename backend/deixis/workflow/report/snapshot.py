"""Read the evidence table into a value-only report snapshot."""

from __future__ import annotations

import json
from typing import Any

from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore


def build_snapshot(store: Store, research_id: str, table_id: str) -> dict[str, Any]:
    """Copy current source, column, cell and quote records; this function does not write."""
    tables = TableStore(store)
    table = tables._table(research_id, table_id)
    columns = tables.target_columns(research_id, table_id)
    included = store.included_sources(research_id)
    included_set = set(included)
    source_ids = [source_id for source_id in tables.active_rows(table_id) if source_id in included_set]
    column_ids = {column["id"] for column in columns}
    cells = []
    for row in store.conn.execute(
        "SELECT c.id AS cell_id, c.column_id, c.source_version_id, r.id AS cell_revision_id,"
        " r.state, r.value_json, r.reading_depth FROM evidence_cells c"
        " JOIN cell_revisions r ON r.id = c.current_revision_id WHERE c.table_id = ?", (table_id,),
    ):
        if row["source_version_id"] not in source_ids or row["column_id"] not in column_ids:
            continue
        evidence = [{"passage_id": link["passage_id"], "quote": link["anchor_text"]} for link in store.conn.execute(
            "SELECT passage_id, anchor_text FROM cell_evidence_links WHERE cell_revision_id = ? ORDER BY rowid",
            (row["cell_revision_id"],),
        )]
        cells.append({"cell_id": row["cell_id"], "cell_revision_id": row["cell_revision_id"],
                      "column_id": row["column_id"], "source_version_id": row["source_version_id"],
                      "state": row["state"], "value": json.loads(row["value_json"]) if row["value_json"] else None,
                      "reading_depth": row["reading_depth"], "evidence": evidence})
    row_order = {source_id: index for index, source_id in enumerate(source_ids)}
    column_order = {column["id"]: index for index, column in enumerate(columns)}
    cells.sort(key=lambda cell: (row_order[cell["source_version_id"]], column_order[cell["column_id"]]))
    depth_order = {"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}
    rows = []
    for source_id in source_ids:
        source = store.conn.execute("SELECT version_label FROM source_versions WHERE id = ?", (source_id,)).fetchone()
        depths = [cell["reading_depth"] for cell in cells if cell["source_version_id"] == source_id and cell["reading_depth"]]
        rows.append({"source_version_id": source_id, "version_label": source["version_label"],
                     "reading_depth": max(depths, key=depth_order.__getitem__) if depths else None})

    revision = store.research(research_id)["current_scope_revision"]
    found = store.conn.execute(
        "SELECT COALESCE(SUM(s.result_count), 0) FROM search_runs s JOIN runs r ON r.id = s.run_id"
        " WHERE s.research_id = ? AND COALESCE(s.scope_revision, r.scope_revision) = ?"
        " AND s.status IN ('completed', 'zero_results')", (research_id, revision),
    ).fetchone()[0]
    unique = store.conn.execute(
        "SELECT COUNT(DISTINCT v.work_id) FROM source_versions v WHERE v.id IN ("
        " SELECT c.source_version_id FROM candidates c WHERE c.research_id = ? AND c.scope_revision = ?"
        " UNION SELECT m.source_version_id FROM corpus_memberships m"
        " WHERE m.research_id = ? AND m.removed_at IS NULL)",
        (research_id, revision, research_id),
    ).fetchone()[0]
    screened = store.conn.execute(
        "SELECT COUNT(DISTINCT json_extract(candidate.value, '$.candidate_id')) FROM step_inputs i,"
        " json_each(i.payload_json, '$.candidates') candidate"
        " WHERE i.research_id = ? AND i.scope_revision = ? AND i.task_type = 'screening'",
        (research_id, revision),
    ).fetchone()[0]
    return {
        "table_revision": table["version"],
        "columns": [{"column_id": column["id"], "revision": column["current_revision"], "name": column["name"],
                     "instruction": column["instruction"], "answer_format": column["answer_format"]} for column in columns],
        "rows": rows,
        "cells": cells,
        "corpus": {"found": found, "unique": unique, "screened": screened, "included": len(included),
                   "full_text": sum(store.has_pdf_text(source_id) for source_id in included)},
    }
