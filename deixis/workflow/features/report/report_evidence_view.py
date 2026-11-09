"""The evidence an answer rests on, frozen once when that answer's input is built.

An answer and the report written up from it stand on the same stored evidence. The moment the answer's input is
settled, the run freezes one view of the Evidence table: its rows with how each one came to be in it, the column
revisions, every cell with its content and its located quotes, and, per row, exactly the text this answer bound for
that row — the pages it read when it read the file, its abstract when it read the abstract. A report of that answer is
written from this view, so a full text that arrives afterwards cannot reach the report without reaching the answer.

Four boundaries make the view what it is:

- **Its rows are the answer's rows.** A table row the answer did not use is not evidence here, however the live table
  counts it; it is recorded by name instead of dropped in silence. A row the answer used that the table has none for
  is recorded too.
- **The route, not the richest text.** A row the answer read from its abstract gives its abstract, even when the
  source holds a PDF: the answer did not read that PDF, so the report may not either.
- **A cell cannot reach past its row.** A quote linked to a passage outside the row's frozen text is not evidence
  here; the cell keeps its value for the person and is counted unverified. A row whose frozen text holds nothing
  beyond an abstract claims no deeper reading, in the row or in its cells, and a passage whose own kind cannot be
  read counts as no text beyond the abstract.
- **The basis note counts what is left.** Reading depths, unverified cells and abstract-only rows are counted after
  those narrowings, because the report states them as what it was written from.

What the report reads is the row's whole frozen text, not only the passages that fitted the answer's passage budget: a
write-up may say more about the same stored version than one answer had room for. Evidence that arrives later does not
edit this view; it makes a new answer, a new view, and through it a new report version, and the earlier one stays
readable as it was.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.features.report.report_snapshot import _named, build_snapshot, reading_basis
from deixis.workflow.features.tables.tables import report_ready

VIEW_KEY = "fast_path:v1:evidence_view"
VIEW_KIND = "code:evidence_answer_view"
# Depths a row can only claim when its frozen text holds more than an abstract.
BEYOND_ABSTRACT = ("selected_sections", "full_text")
# The passage kinds that are such text. A passage whose kind cannot be read is not one of them, so a row is never
# given a deeper reading on the strength of text nobody could look at.
BEYOND_ABSTRACT_KINDS = ("pdf_page", "section")


def allowed_passages(answer_input: dict[str, Any]) -> dict[str, list[str]]:
    """Per source version, the text the answer bound for that row: its pages when it read the file, else its abstract.

    Read from the answer's own final rows, so a row the person included after the read cutoff is here and a row the
    answer left out — screened out, over a budget, or excluded since — is not.
    """
    allowed: dict[str, list[str]] = {}
    for row in answer_input.get("items") or []:
        svid = row.get("source_version_id")
        if not svid:
            continue
        ids = row.get("fulltext_ids") if row.get("route") == "fulltext" else row.get("abstract_ids")
        allowed[svid] = list(ids or ())
    return allowed


def build(store: Any, research_id: str, table_id: str, answer_input: dict[str, Any], run_id: str) -> dict[str, Any]:
    """The view to freeze: the table's snapshot, cut to this answer's rows and bound to the text it read."""
    view = build_snapshot(store, research_id, table_id)
    allowed = allowed_passages(answer_input)
    kinds = _passage_kinds(store, {pid for ids in allowed.values() for pid in ids})

    # The rows are the answer's. A table row it did not use is named, not silently dropped; a row the answer used
    # that the table holds none for is named too, so the gap is readable either way.
    table_rows = [row["source_version_id"] for row in view.get("rows") or []]
    not_in_answer = [svid for svid in table_rows if svid not in allowed]
    without_row = [svid for svid in allowed if svid not in table_rows]
    rows = [row for row in view.get("rows") or [] if row["source_version_id"] in allowed]

    bound, shallow = {}, set()
    for row in rows:
        svid = row["source_version_id"]
        ids = allowed.get(svid, [])
        row["passage_ids"] = ids
        bound[svid] = set(ids)
        if not any(kinds.get(pid) in BEYOND_ABSTRACT_KINDS for pid in ids):
            shallow.add(svid)
            if row.get("reading_depth") in BEYOND_ABSTRACT:
                row["reading_depth"] = "abstract"

    cells = []
    for cell in view.get("cells") or []:
        svid = cell["source_version_id"]
        if svid not in allowed:
            continue
        if any(link["passage_id"] not in bound.get(svid, ()) for link in cell.get("evidence") or []):
            if cell["state"] == "value":
                cell["state"] = "not_verified"
            cell["evidence"] = []
        if svid in shallow and cell.get("reading_depth") in BEYOND_ABSTRACT:
            cell["reading_depth"] = "abstract"
        cells.append(cell)

    view["rows"], view["cells"] = rows, cells
    if not_in_answer:
        view["rows_not_in_answer"] = [_named(store, svid) for svid in not_in_answer]
    if without_row:
        view["answer_rows_without_a_table_row"] = sorted(without_row)
    # The basis note states what the report was written from, so it is counted after the narrowing above, not before.
    view["basis"] = reading_basis(store, rows, cells, view["columns"])
    members = [row["source_version_id"] for row in rows if row.get("membership") == "abstract_only"]
    if members:
        view["abstract_rows"] = members
        view["basis"]["abstract_members"] = [_named(store, svid) for svid in members]
    else:
        view.pop("abstract_rows", None)
    # The view names the table and the answer it belongs to, which the snapshot itself does not.
    view["table_id"] = table_id
    view["answer_run_id"] = run_id
    view["scope_revision"] = answer_input.get("scope_revision")
    view["cutoff_at"] = answer_input.get("cutoff_at")
    view["bound_to_answer"] = True
    return view


def _passage_kinds(store: Any, passage_ids: set[str]) -> dict[str, str]:
    """What kind of text each frozen passage is. A passage that cannot be read is left out, so it counts as none."""
    kinds = {}
    for passage_id in passage_ids:
        try:
            kinds[passage_id] = store.passage(passage_id)["kind"]
        except Exception:  # noqa: BLE001 - a passage nobody can read gives a row no depth
            continue
    return kinds


def frozen(store: Any, run_id: str) -> dict[str, Any] | None:
    """The view an answer run froze, or None when it froze none."""
    step = store.existing_step(run_id, VIEW_KEY)
    return step["output"] if step and step["status"] == "succeeded" else None


def for_research(store: Any, research_id: str, table_id: str, scope_revision: int | None = None) -> dict[str, Any] | None:
    """The view the research's latest valid answer of this question rests on, when it is a view of this table.

    This is what a report of that answer is written from. None when the research has no such answer, when the answer
    froze no view (one written before this existed), or when the view is of another table — a report then builds its
    own from the table as it stands.
    """
    revision = scope_revision if scope_revision is not None else store.research(research_id)["current_scope_revision"]
    row = store.conn.execute(
        "SELECT run_id FROM answers WHERE research_id = ? AND status = 'structurally_valid' AND scope_revision = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (research_id, revision)).fetchone()
    if row is None:
        return None
    view = frozen(store, row["run_id"])
    return view if view is not None and view.get("table_id") == table_id else None


def readiness(store: Any, research_id: str, table_id: str, scope_revision: int | None = None) -> dict[str, Any]:
    """Whether a report can be written from this table, read in one place.

    With a frozen view the answer it belongs to settled this: the view's own rows and columns are what the report has,
    and a table that changed since neither refuses a report nor makes one possible. Without a view the live table
    decides, as it always did.
    """
    view = for_research(store, research_id, table_id, scope_revision)
    if view is None:
        return report_ready(store, research_id, table_id)
    rows, columns = view.get("rows") or [], view.get("columns") or []
    return {"ready": bool(rows and columns), "missing": [], "rows": len(rows), "from_answer_view": True}
