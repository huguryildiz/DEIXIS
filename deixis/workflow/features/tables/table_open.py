"""The study table a discovery run opens before it reads anything.

The design asks for the Evidence table's columns to exist before reading starts, so that a cell can be written as each
paper is read instead of after the first answer. This module is that opening: it creates or adopts the research's study
table and installs the columns that need no model call, and it accepts the columns a model proposed beside them.

Two kinds of column, in this order:

- The **question's own two**, written by code from the question sentence: what the source reports for the question, and
  the condition that finding holds under. They cost nothing and they cannot fail, so the first answer is always built
  with columns in place, whatever happens to the model's proposal.
- The **proposed** ones, which only add to those two. A proposal that fails, or that the table refuses, leaves the two
  standing; no column is ever replaced by a model's.

Nothing here reads a person's decision or writes a cell. The table a person already built by hand is never touched: the
run adopts only a table it or the study-table chain opened for this research, and otherwise opens its own.
"""

from __future__ import annotations

from typing import Any

from deixis.storage.db import transaction
from deixis.workflow.features.tables.tables import InvalidTableInput, TableStore

# The title the app gives its study table. It names the table on screen; it never decides whose table it is.
TITLE = "Study table"
# What the app's own tables carry in their creation key, which is how `chain_table` recognises them.
KEY_PREFIX = "study_table"
# How the question's own columns are named in the table, and the sentence each one asks of a source. The question
# itself is quoted into the instruction, so a source is read against the person's words and not a paraphrase.
QUESTION_COLUMNS = (
    {"name": "Reported finding",
     "instruction": "What this source reports for the research question: {question}"
                    " Give the finding as the source states it, with its number and unit when it states one."},
    {"name": "Condition of the finding",
     "instruction": "The setting or experimental condition the reported finding holds under, as this source states it"
                    " (the scenario, the dataset, the network size, the parameter range). Findings obtained under"
                    " different conditions are not the same finding."},
)
# The two columns are a fixed definition, neither a person's nor a model's suggestion, so they are installed with the
# origin a table's template columns already use.
ORIGIN = "template"


def question_columns(question: str) -> list[dict[str, Any]]:
    """The column specs code writes from the question; no model call, so this list can never come back empty."""
    sentence = " ".join((question or "").split())[:400] or "the research question."
    if not sentence.endswith((".", "?", "!")):
        sentence += "."
    return [{"name": column["name"], "instruction": column["instruction"].format(question=sentence),
             "answer_format": "text", "options": None, "allow_multiple": False, "unit_hint": None}
            for column in QUESTION_COLUMNS]


def chain_table(store: Any, research_id: str) -> str | None:
    """The study table the app itself opened for this research, if it still has one.

    Found by what the app wrote, never by a table's title: the step that opened one names it, and a table the app or
    the study-table chain created carries the key they create it under. A table a person made holds their own columns
    and their own reading, so no automatic writer joins it, whatever they called it.
    """
    opened = store.conn.execute(
        "SELECT json_extract(s.output_json, '$.table_id') AS table_id FROM run_steps s JOIN runs r ON r.id = s.run_id"
        " JOIN evidence_tables et ON et.id = json_extract(s.output_json, '$.table_id')"
        " WHERE r.research_id = ? AND s.kind = 'code:study_table_open' AND s.status = 'succeeded'"
        " AND et.trashed_at IS NULL ORDER BY s.rowid LIMIT 1", (research_id,)).fetchone()
    if opened:
        return opened["table_id"]
    row = store.conn.execute(
        "SELECT id FROM evidence_tables WHERE research_id = ? AND idempotency_key LIKE ? AND follows_included > 0"
        " AND trashed_at IS NULL ORDER BY created_at LIMIT 1", (research_id, f"{research_id}:{KEY_PREFIX}:%")).fetchone()
    return row["id"] if row else None


def open_table(store: Any, research_id: str, question: str, key: str) -> dict[str, Any]:
    """Create or adopt the research's study table and install the question's own columns. Idempotent under `key`.

    A table the chain or an earlier run of this research already opened is adopted as it is, and its missing question
    columns are added; a table that holds them already is returned unchanged. The columns are added one by one, so a
    name the table refuses (a person added a column of that name) skips that one and leaves the rest.
    """
    tables = TableStore(store)
    table_id = chain_table(store, research_id)
    created = table_id is None
    if table_id is None:
        # `rows=None` makes a table that follows the research's sources, so every work read later becomes a row by the
        # ordinary sweep. At this point, before any screening, it has no rows at all.
        table_id = tables.create_table(research_id, TITLE, None, None, f"{key}:table")
    installed, refused = [], []
    names = {column["name"].casefold() for column in tables._columns(table_id)}
    for index, spec in enumerate(question_columns(question)):
        if spec["name"].casefold() in names:
            continue
        try:
            installed.append(tables.add_column(research_id, table_id, spec, tables._table(research_id, table_id)["version"],
                                               f"{key}:col:{index}", origin=ORIGIN))
        except InvalidTableInput as exc:
            refused.append({"name": spec["name"], "reason": str(exc)})
    record = {"table_id": table_id, "created": created, "question_columns": installed,
              "columns": len(tables._columns(table_id))}
    if refused:
        record["refused"] = refused
    store._event(research_id, "study_table_opened", record)
    return record


def accept_proposed(store: Any, research_id: str, table_id: str, run_id: str, key: str) -> dict[str, Any]:
    """Add the columns the run's proposal step wrote, beside the question's own. Returns what was added.

    The proposal only adds: a column whose name is already in the table is skipped, so neither a person's column nor
    one of the question's own is replaced by a model's. Recorded as accepted by the app, as the chain records it.
    """
    tables = TableStore(store)
    suggestion = tables.column_suggestions(table_id)
    added, skipped = [], []
    with transaction(store.conn):
        if store.conn.execute("SELECT 1 FROM events WHERE run_id = ? AND type = 'study_table_columns_accepted'",
                              (run_id,)).fetchone():
            return {"table_id": table_id, "replayed": True}  # a resumed run: already accepted and recorded
        if suggestion is not None and suggestion["run_id"] == run_id:
            names = {column["name"].casefold() for column in tables._columns(table_id)}
            for index, column in enumerate(suggestion["columns"]):
                spec = {field: column.get(field)
                        for field in ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")}
                if str(spec["name"] or "").strip().casefold() in names:
                    skipped.append({"name": spec["name"], "reason": "a column of this name is already in the table"})
                    continue
                try:
                    added.append(tables.add_column(research_id, table_id, spec, tables._table(research_id, table_id)["version"],
                                                   f"{key}:proposed:{index}", origin="model_suggestion",
                                                   suggestion_step_id=suggestion["step_id"], accepted_by="automatic"))
                    names.add(str(spec["name"]).strip().casefold())
                except InvalidTableInput as exc:
                    skipped.append({"name": spec["name"], "reason": str(exc)})
        record = {"table_id": table_id, "accepted_by": "automatic", "reviewed_by_person": False,
                  "added": len(added), "skipped": skipped}
        store._event(research_id, "study_table_columns_accepted", record, run_id)
    return record
