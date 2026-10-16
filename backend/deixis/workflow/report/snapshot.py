"""Read the evidence table into a value-only report snapshot."""

from __future__ import annotations

import json
from typing import Any

from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore

# The step inputs a report counts as screening: the fast path's `abstract_screening`, and the old `screening` step a
# research made before it. A record both read counts once.
SCREENING_TASKS = ("screening", "abstract_screening")


def included_table_rows(store: Store, research_id: str, table_id: str) -> list[str]:
    """Use the same active-row and included-source boundary for snapshots and later comparisons."""
    included = set(store.included_sources(research_id))
    return [source_id for source_id in TableStore(store).active_rows(table_id) if source_id in included]


def evidence_row_ids(snapshot: dict[str, Any]) -> list[str]:
    """Only completed rows may supply content evidence; older snapshots keep their original boundary."""
    failed = {row["source_version_id"] for row in snapshot.get("failed_rows", [])}
    return [row["source_version_id"] for row in snapshot.get("rows", []) if row["source_version_id"] not in failed]


def reading_counts(store: Store, research_id: str, included: list[str]) -> dict[str, int] | None:
    """How much of each included version's extracted text a two-run full-text reading showed the model (audit item 3).

    A reading decision is a full-text decision written from a `model:fulltext_adjudication` step, superseded or stale
    or not: what was shown does not change when a person decides later or the criterion moves. The newest one on the
    version answers; a version with none takes the newest on another version of its work, and `other_version` counts
    those (a subset of the other three). `none` is not "not read": a reading whose second call failed writes no
    decision, and the answer path can read an attached PDF without any reading here. None when the research holds no
    reading decision at all.
    """
    by_version: dict[str, dict[str, Any]] = {}
    by_work: dict[str, dict[str, Any]] = {}
    for row in store.conn.execute(
        "SELECT d.source_version_id, d.read_coverage, v.work_id FROM stage_decisions d"
        " JOIN run_steps s ON s.id = d.step_id JOIN source_versions v ON v.id = d.source_version_id"
        " WHERE d.research_id = ? AND d.stage = 'fulltext' AND s.kind = 'model:fulltext_adjudication'"
        " ORDER BY d.created_at, d.rowid", (research_id,),
    ):
        by_version[row["source_version_id"]] = dict(row)
        by_work[row["work_id"]] = dict(row)
    if not by_version:
        return None  # no reading in this research at all (attached PDFs only, or no full-text stage)
    counts = {"all_parts": 0, "some_parts": 0, "unrecorded": 0, "none": 0, "other_version": 0}
    for source_id in included:
        reading = by_version.get(source_id)
        if reading is None:
            work = store.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (source_id,)).fetchone()
            reading = by_work.get(work["work_id"]) if work is not None else None
            counts["other_version"] += reading is not None
        if reading is None:
            counts["none"] += 1
        elif not reading["read_coverage"]:
            counts["unrecorded"] += 1
        else:
            counts["all_parts" if json.loads(reading["read_coverage"])["all_parts_shown"] else "some_parts"] += 1
    return counts


def reading_basis(store: Store, rows: list[dict[str, Any]], cells: list[dict[str, Any]],
                  columns: list[dict[str, Any]]) -> dict[str, Any]:
    """What the report's table rests on, for the basis note at the top of the report (D68).

    A row read from PDF text has a cell made from selected PDF passages; any other row was read from its abstract or,
    without one, from its metadata. A cell could not be verified when it holds no finished answer (empty, or a failed
    extraction left it so) or holds a value without linked evidence (`not_verified`); 'inaccessible' cells of a source
    without stored text are counted with the metadata-only rows instead. Rows with such cells are named.
    """
    unverified_states = {None, "not_verified"}
    by_cell = {(c["source_version_id"], c["column_id"]): c for c in cells}
    full_text, abstract_only, metadata_only, named = 0, 0, 0, []
    for row in rows:
        source_id = row["source_version_id"]
        if row["reading_depth"] in ("selected_sections", "full_text"):
            full_text += 1
        elif row["reading_depth"] == "abstract" or (
                row["reading_depth"] is None and any(p["kind"] == "abstract" for p in store.passages_for(source_id))):
            abstract_only += 1
        else:
            metadata_only += 1
        unverified = sum((by_cell.get((source_id, column["column_id"])) or {}).get("state") in unverified_states
                         for column in columns)
        if unverified:
            source = store.conn.execute(
                "SELECT v.title, w.source_key FROM source_versions v JOIN works w ON w.id = v.work_id WHERE v.id = ?",
                (source_id,)).fetchone()
            named.append({"source_version_id": source_id, "source_key": source["source_key"], "title": source["title"],
                          "cells_unverified": unverified, "cells_total": len(columns)})
    return {"sources": len(rows), "full_text": full_text, "abstract_only": abstract_only, "metadata_only": metadata_only,
            "cells_total": len(rows) * len(columns), "cells_unverified": sum(item["cells_unverified"] for item in named),
            "unverified_sources": named}


def build_snapshot(store: Store, research_id: str, table_id: str) -> dict[str, Any]:
    """Copy current source, column, cell and quote records; this function does not write.

    Every included row of the table is evidence, whatever its cells hold: a row whose cells failed is read from its
    abstract or metadata and named in the basis note. Only snapshots saved before this rule carry `failed_rows`.
    """
    tables = TableStore(store)
    table = tables._table(research_id, table_id)
    columns = tables.target_columns(research_id, table_id)
    included = store.included_sources(research_id)
    source_ids = included_table_rows(store, research_id, table_id)
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
        " WHERE i.research_id = ? AND i.scope_revision = ? AND i.task_type IN (?, ?)",
        (research_id, revision, *SCREENING_TASKS),
    ).fetchone()[0]
    result = {
        "table_revision": table["version"],
        "columns": [{"column_id": column["id"], "revision": column["current_revision"], "name": column["name"],
                     "instruction": column["instruction"], "answer_format": column["answer_format"]} for column in columns],
        "rows": rows,
        "cells": cells,
        "corpus": {"found": found, "unique": unique, "screened": screened, "included": len(included),
                   "full_text": sum(store.has_pdf_text(source_id) for source_id in included)},
    }
    # Written whenever the research has a recorded screening reading, even when no included source has one; a research
    # without any (attached PDFs only, or no full-text stage) keeps the snapshot and II/VIII text it had (audit item 3).
    reading = reading_counts(store, research_id, included)
    if reading is not None:
        result["reading"] = reading
    # Rows of the table whose source is not included (excluded or undecided since): not evidence, but recorded, so the
    # report's table boundary is not dropped silently (D63). Written only when there are some.
    states = dict(store.conn.execute("SELECT source_version_id, state FROM selections WHERE research_id = ?", (research_id,)).fetchall())
    left_out = [{"source_version_id": source_id, "selection_state": states.get(source_id)}
                for source_id in tables.active_rows(table_id) if source_id not in source_ids]
    if left_out:
        result["left_out_rows"] = left_out
    result["basis"] = reading_basis(store, rows, cells, result["columns"])
    return result
