"""Evidence tables: columns, rows and cells with append-only revisions (P5, D37).

A model or the system gives a value only to an empty cell; anything else a model returns waits as a proposal, and only
a user's decision changes the value a cell shows. Human writes carry the cell version their screen showed, so an older
screen cannot overwrite a newer edit. Evidence links resolve to stored passages of the cell's own source version.
"""

from __future__ import annotations

import json
import math
from typing import Any

from deixis.domain.rules import RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.store import NotFound, Store

ANSWER_FORMATS = ("choice", "number_unit", "yes_no", "text")
CELL_STATES = ("value", "unknown", "not_reported", "not_verified", "not_applicable", "inaccessible", "not_found_in_inspected_scope")
VALUE_STATES = ("value", "not_verified")  # the states that carry a value
MAX_TEXT_VALUE = 500
MAX_OPTIONS = 20
MAX_FILL_SOURCES = 25  # sources one fill run reads; the rest stay empty for another fill (D37)
MAX_COLUMNS_PER_CALL = 8  # columns one cell extraction call answers for its source
CALLS_PER_REQUEST = 2  # a model call and its one schema repair


class InvalidTableInput(Exception):
    """A request the table rules refuse; the API answers 422."""


def column_spec(name: str, instruction: str, answer_format: str, options: list[dict[str, Any]] | None,
                allow_multiple: bool, unit_hint: str | None, previous_options: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Normalize a column definition. Options keep their ids across revisions; a new option gets the next free id."""
    if answer_format not in ANSWER_FORMATS:
        raise InvalidTableInput(f"Unknown answer format '{answer_format}'")
    if not name.strip() or not instruction.strip():
        raise InvalidTableInput("A column needs a name and an instruction")
    if answer_format != "choice" and (options or allow_multiple):
        raise InvalidTableInput("Only an options column has options")
    if answer_format != "number_unit" and unit_hint:
        raise InvalidTableInput("Only a number-and-unit column has a unit")
    normalized = None
    if answer_format == "choice":
        if not options or not 2 <= len(options) <= MAX_OPTIONS:
            raise InvalidTableInput(f"An options column needs 2 to {MAX_OPTIONS} options")
        labels = [str(o.get("label") or "").strip() for o in options]
        if not all(labels) or len({label.casefold() for label in labels}) != len(labels):
            raise InvalidTableInput("Options need distinct, non-empty labels")
        known = {o["id"] for o in previous_options or []}
        used = [o.get("id") for o in options if o.get("id")]
        if any(i not in known for i in used) or len(set(used)) != len(used):
            raise InvalidTableInput("An option id must name an existing option of this column once")
        next_number = max([int(i[1:]) for i in known | set(used)] or [0]) + 1
        normalized = []
        for option, label in zip(options, labels):
            option_id = option.get("id")
            if not option_id:
                option_id, next_number = f"o{next_number}", next_number + 1
            normalized.append({"id": option_id, "label": label})
    return {"name": name.strip(), "instruction": instruction.strip(), "answer_format": answer_format, "options": normalized,
            "allow_multiple": bool(allow_multiple) if answer_format == "choice" else False,
            "unit_hint": (unit_hint or "").strip() or None if answer_format == "number_unit" else None}


def check_value(column: dict[str, Any], state: str, value: Any) -> dict[str, Any] | None:
    """The value a cell state carries, checked against the column's answer format. Nothing is converted."""
    if state not in CELL_STATES:
        raise InvalidTableInput(f"Unknown cell state '{state}'")
    if state not in VALUE_STATES:
        if value is not None:
            raise InvalidTableInput(f"A '{state}' cell carries no value")
        return None
    if not isinstance(value, dict):
        raise InvalidTableInput("A value is an object shaped by the column's answer format")
    fmt = column["answer_format"]
    if fmt == "choice":
        ids = value.get("option_ids")
        offered = {o["id"] for o in column["options"] or []}
        if set(value) != {"option_ids"} or not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or not set(ids) <= offered:
            raise InvalidTableInput("A choice value lists option ids of this column")
        if len(ids) > 1 and not column["allow_multiple"]:
            raise InvalidTableInput("This column takes one option")
        return {"option_ids": ids}
    if fmt == "number_unit":
        number, unit, stated = value.get("number"), value.get("unit"), value.get("as_stated")
        if (not set(value) <= {"number", "unit", "as_stated"} or isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number)):
            raise InvalidTableInput("A number value has a finite number, an optional unit and an optional as-stated text")
        if (unit is not None and (not isinstance(unit, str) or not 0 < len(unit.strip()) <= 40)) or (
                stated is not None and (not isinstance(stated, str) or not 0 < len(stated.strip()) <= 200)):
            raise InvalidTableInput("A unit has at most 40 characters and an as-stated text at most 200")
        return {"number": number, "unit": unit.strip() if unit else None, "as_stated": stated.strip() if stated else None}
    if fmt == "yes_no":
        if value != {"answer": "yes"} and value != {"answer": "no"}:
            raise InvalidTableInput("A yes/no value is yes or no; an unclear answer is the 'unknown' state")
        return dict(value)
    text = value.get("text")
    if set(value) != {"text"} or not isinstance(text, str) or not 0 < len(text.strip()) <= MAX_TEXT_VALUE:
        raise InvalidTableInput(f"A text value has 1 to {MAX_TEXT_VALUE} characters")
    return {"text": text.strip()}


class TableStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    # ---- lookups ----------------------------------------------------------------------
    @staticmethod
    def _key(scope: str, idempotency_key: str | None) -> str | None:
        return f"{scope}:{idempotency_key}" if idempotency_key else None

    def _table(self, research_id: str, table_id: str) -> dict[str, Any]:
        self.store.research(research_id)
        row = self.conn.execute(
            "SELECT * FROM evidence_tables WHERE id = ? AND research_id = ? AND trashed_at IS NULL", (table_id, research_id)
        ).fetchone()
        if row is None:
            raise NotFound(table_id)
        return dict(row)

    def _columns(self, table_id: str, include_removed: bool = False) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.*, r.name, r.instruction, r.answer_format, r.options_json, r.allow_multiple, r.unit_hint FROM table_columns c"
            " JOIN column_revisions r ON r.column_id = c.id AND r.revision = c.current_revision"
            f" WHERE c.table_id = ?{'' if include_removed else ' AND c.removed_at IS NULL'} ORDER BY c.position, c.created_at",
            (table_id,),
        ).fetchall()
        columns = []
        for row in rows:
            column = dict(row)
            column["options"] = json.loads(column.pop("options_json")) if column["options_json"] else None
            column["allow_multiple"] = bool(column["allow_multiple"])
            columns.append(column)
        return columns

    def _column(self, table_id: str, column_id: str) -> dict[str, Any]:
        column = next((c for c in self._columns(table_id) if c["id"] == column_id), None)
        if column is None:
            raise NotFound(column_id)
        return column

    def _active_row(self, table_id: str, svid: str) -> None:
        if not self.conn.execute(
            "SELECT 1 FROM table_rows WHERE table_id = ? AND source_version_id = ? AND removed_at IS NULL", (table_id, svid)
        ).fetchone():
            raise InvalidTableInput("This source is not a row of the table")

    def _cell(self, table_id: str, column_id: str, svid: str, create: bool = False) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM evidence_cells WHERE column_id = ? AND source_version_id = ?", (column_id, svid)
        ).fetchone()
        if row is None and create:
            ts = now()
            self.conn.execute(
                "INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("cel"), table_id, column_id, svid, ts, ts),
            )
            return self._cell(table_id, column_id, svid)
        if row is None or row["table_id"] != table_id:
            raise NotFound(f"cell {column_id}/{svid}")
        return dict(row)

    def _revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM cell_revisions WHERE id = ?", (revision_id,)).fetchone()
        return dict(row) if row else None

    def _replayed_revision(self, key: str | None, cell_id: str | None = None) -> str | None:
        if key is None:
            return None
        row = self.conn.execute("SELECT id, cell_id FROM cell_revisions WHERE idempotency_key = ?", (key,)).fetchone()
        if row and cell_id is not None and row["cell_id"] != cell_id:
            raise InvalidTableInput("This idempotency key was used for another cell")
        return row["id"] if row else None

    def _latest_proposal(self, cell_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM cell_revisions WHERE cell_id = ? AND kind = 'model_proposal' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cell_id,),
        ).fetchone()
        return dict(row) if row else None

    def _decision(self, proposal_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT kind FROM cell_revisions WHERE based_on_revision_id = ? AND kind IN ('accept_proposal', 'dismiss_proposal')",
            (proposal_id,),
        ).fetchone()
        return row["kind"] if row else None

    def _touch(self, table_id: str, bump: bool = False) -> None:
        self.conn.execute(f"UPDATE evidence_tables SET updated_at = ?{', version = version + 1' if bump else ''} WHERE id = ?",
                          (now(), table_id))

    def _changed(self, research_id: str, table_id: str, **payload: Any) -> None:
        self.store._event(research_id, "table_changed", {"table_id": table_id, **payload})

    # ---- tables and rows --------------------------------------------------------------
    def create_table(self, research_id: str, title: str, rows: list[str] | None, template_id: str | None,
                     idempotency_key: str | None) -> str:
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            if key and (existing := self.conn.execute("SELECT id FROM evidence_tables WHERE idempotency_key = ?", (key,)).fetchone()):
                return existing["id"]
            self.store.research(research_id)
            template = None
            if template_id:
                template = self.conn.execute(
                    "SELECT * FROM table_templates WHERE id = ? AND trashed_at IS NULL", (template_id,)
                ).fetchone()
                if template is None:
                    raise NotFound(template_id)
            added_by = "included_at_creation" if rows is None else "user"
            svids = self.store.included_sources(research_id) if rows is None else list(dict.fromkeys(rows))
            self._check_members(research_id, svids)
            tid, ts = new_id("tbl"), now()
            self.conn.execute(
                "INSERT INTO evidence_tables (id, research_id, title, template_id, idempotency_key, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)", (tid, research_id, title.strip(), template_id, key, ts, ts),
            )
            self.conn.executemany(
                "INSERT INTO table_rows (table_id, source_version_id, added_by, created_at) VALUES (?, ?, ?, ?)",
                [(tid, svid, added_by, ts) for svid in svids],
            )
            for position, spec in enumerate(json.loads(template["columns_json"]) if template else []):
                self._insert_column(tid, position, column_spec(**spec), "template", None, None)
            self._changed(research_id, tid)
        return tid

    def _check_members(self, research_id: str, svids: list[str]) -> None:
        missing = [svid for svid in svids if not self.store.is_member(research_id, svid)]
        if missing:
            raise InvalidTableInput(f"Not a source of this research: {', '.join(missing)}")

    def rename_table(self, research_id: str, table_id: str, title: str, expected_version: int) -> None:
        with transaction(self.conn):
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            self.conn.execute("UPDATE evidence_tables SET title = ? WHERE id = ?", (title.strip(), table_id))
            self._touch(table_id, bump=True)
            self._changed(research_id, table_id)

    def trash_table(self, research_id: str, table_id: str, expected_version: int) -> None:
        with transaction(self.conn):
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            self.conn.execute("UPDATE evidence_tables SET trashed_at = ?, version = version + 1 WHERE id = ?", (now(), table_id))
            self._changed(research_id, table_id, trashed=True)

    def add_rows(self, research_id: str, table_id: str, svids: list[str], expected_version: int) -> None:
        with transaction(self.conn):
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            svids = list(dict.fromkeys(svids))
            if not svids:
                raise InvalidTableInput("Choose at least one source")
            self._check_members(research_id, svids)
            self.conn.executemany(
                "INSERT INTO table_rows (table_id, source_version_id, added_by, created_at) VALUES (?, ?, 'user', ?)"
                " ON CONFLICT (table_id, source_version_id) DO UPDATE SET removed_at = NULL",
                [(table_id, svid, now()) for svid in svids],
            )
            self._touch(table_id, bump=True)
            self._changed(research_id, table_id)

    def remove_row(self, research_id: str, table_id: str, svid: str, expected_version: int) -> None:
        """Take a source out of the table; its cells and their revisions stay stored."""
        with transaction(self.conn):
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            self._active_row(table_id, svid)
            self.conn.execute("UPDATE table_rows SET removed_at = ? WHERE table_id = ? AND source_version_id = ?", (now(), table_id, svid))
            self._touch(table_id, bump=True)
            self._changed(research_id, table_id)

    # ---- columns ----------------------------------------------------------------------
    def _insert_column(self, table_id: str, position: int, spec: dict[str, Any], origin: str,
                       suggestion_step_id: str | None, key: str | None) -> str:
        cid, ts = new_id("col"), now()
        self.conn.execute(
            "INSERT INTO table_columns (id, table_id, position, origin, suggestion_step_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cid, table_id, position, origin, suggestion_step_id, ts),
        )
        self._insert_column_revision(cid, 1, spec, key)
        return cid

    def _insert_column_revision(self, column_id: str, revision: int, spec: dict[str, Any], key: str | None) -> None:
        self.conn.execute(
            "INSERT INTO column_revisions (column_id, revision, name, instruction, answer_format, options_json, allow_multiple,"
            " unit_hint, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (column_id, revision, spec["name"], spec["instruction"], spec["answer_format"],
             dumps(spec["options"]) if spec["options"] is not None else None, int(spec["allow_multiple"]), spec["unit_hint"], key, now()),
        )

    def add_column(self, research_id: str, table_id: str, spec: dict[str, Any], expected_version: int, idempotency_key: str | None,
                   origin: str = "user", suggestion_step_id: str | None = None) -> str:
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            if key and (existing := self.conn.execute("SELECT column_id FROM column_revisions WHERE idempotency_key = ?", (key,)).fetchone()):
                return existing["column_id"]
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            if origin == "model_suggestion" and not self.conn.execute(
                "SELECT 1 FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE s.id = ? AND s.kind = 'model:table_columns'"
                " AND s.status = 'succeeded' AND r.research_id = ? AND json_extract(r.target_json, '$.table_id') = ?",
                (suggestion_step_id, research_id, table_id),
            ).fetchone():
                raise InvalidTableInput("Not a column suggestion step of this table")
            position = self.conn.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM table_columns WHERE table_id = ?", (table_id,)).fetchone()[0]
            cid = self._insert_column(table_id, position, column_spec(**spec), origin, suggestion_step_id, key)
            self._touch(table_id, bump=True)
            self._changed(research_id, table_id)
        return cid

    def revise_column(self, research_id: str, table_id: str, column_id: str, changes: dict[str, Any], position: int | None,
                      expected_version: int) -> None:
        """Changed fields make a new column revision; values made under the earlier revision stay and read as stale."""
        with transaction(self.conn):
            self._table(research_id, table_id)
            column = self._column(table_id, column_id)
            check_expected_version(expected_version, column["version"])
            current = {k: column[k] for k in ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")}
            fmt = changes.get("answer_format", column["answer_format"])
            # A format change drops the fields the new format has no use for, unless the request sets them.
            dropped = {"options": None, "allow_multiple": False} if fmt != "choice" else {}
            dropped |= {"unit_hint": None} if fmt != "number_unit" else {}
            merged = column_spec(**(current | dropped | changes), previous_options=column["options"])
            if merged != current:
                self._insert_column_revision(column_id, column["current_revision"] + 1, merged, None)
                self.conn.execute("UPDATE table_columns SET current_revision = current_revision + 1 WHERE id = ?", (column_id,))
            if position is not None:
                order = [c["id"] for c in self._columns(table_id) if c["id"] != column_id]
                order.insert(min(max(position, 0), len(order)), column_id)
                self.conn.executemany("UPDATE table_columns SET position = ? WHERE id = ?", list(enumerate(order)))
            self.conn.execute("UPDATE table_columns SET version = version + 1 WHERE id = ?", (column_id,))
            self._touch(table_id)
            self._changed(research_id, table_id)

    def remove_column(self, research_id: str, table_id: str, column_id: str, expected_version: int) -> None:
        with transaction(self.conn):
            self._table(research_id, table_id)
            check_expected_version(expected_version, self._column(table_id, column_id)["version"])
            self.conn.execute("UPDATE table_columns SET removed_at = ?, version = version + 1 WHERE id = ?", (now(), column_id))
            self._touch(table_id)
            self._changed(research_id, table_id)

    # ---- cells ------------------------------------------------------------------------
    def _insert_revision(self, cell: dict[str, Any], key: str | None = None, **fields: Any) -> str:
        rid = new_id("crv")
        row = {"id": rid, "cell_id": cell["id"], **fields, "idempotency_key": key, "created_at": now()}
        if "value_json" in row and row["value_json"] is not None:
            row["value_json"] = dumps(row["value_json"])
        self.conn.execute(f"INSERT INTO cell_revisions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return rid

    def _insert_links(self, revision_id: str, links: list[dict[str, Any]]) -> None:
        self.conn.executemany(
            "INSERT INTO cell_evidence_links (cell_revision_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(revision_id, link["passage_id"], link["source_version_id"], link.get("step_input_id"), link.get("anchor_text"),
              link.get("anchor_match")) for link in links],
        )

    def _links(self, revision_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT passage_id, source_version_id, step_input_id, anchor_text, anchor_match FROM cell_evidence_links"
            " WHERE cell_revision_id = ? ORDER BY rowid", (revision_id,)
        )]

    def _set_current(self, research_id: str, cell: dict[str, Any], revision_id: str | None, kind: str) -> None:
        self.conn.execute(
            f"UPDATE evidence_cells SET {'current_revision_id = ?, ' if revision_id else ''}version = version + 1, updated_at = ? WHERE id = ?",
            (*([revision_id] if revision_id else []), now(), cell["id"]),
        )
        self._touch(cell["table_id"])
        self.store._event(research_id, "cell_revision_saved", {"table_id": cell["table_id"], "column_id": cell["column_id"],
                                                               "source_version_id": cell["source_version_id"], "kind": kind})

    def edit_cell(self, research_id: str, table_id: str, column_id: str, svid: str, state: str, value: Any, note: str | None,
                  keep_evidence_from: str | None, expected_version: int, idempotency_key: str | None) -> str:
        """Record the user's value. A value with linked evidence is 'value'; without, it is 'not_verified'."""
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            self._table(research_id, table_id)
            column = self._column(table_id, column_id)
            self._active_row(table_id, svid)
            cell = self._cell(table_id, column_id, svid, create=True)
            if replayed := self._replayed_revision(key, cell["id"]):
                return replayed
            check_expected_version(expected_version, cell["version"])
            value = check_value(column, state, value)
            links, depth = [], None
            if keep_evidence_from:
                kept = self._revision(keep_evidence_from)
                if kept is None or kept["cell_id"] != cell["id"]:
                    raise InvalidTableInput("Evidence can be kept only from a revision of this cell")
                links, depth = self._links(keep_evidence_from), kept["reading_depth"]
                if not links:
                    raise InvalidTableInput("That revision has no linked evidence")
            if state == "value" and not links:
                raise InvalidTableInput("A value without linked evidence is recorded as not_verified")
            if state == "not_verified" and links:
                raise InvalidTableInput("A value with linked evidence is recorded as value")
            revision_id = self._insert_revision(
                cell, key, kind="human_edit", author="human", based_on_revision_id=keep_evidence_from or cell["current_revision_id"],
                column_revision=column["current_revision"], state=state, value_json=value, note=(note or "").strip() or None,
                reading_depth=depth,
            )
            self._insert_links(revision_id, links)
            self._set_current(research_id, cell, revision_id, "human_edit")
        return revision_id

    def decide_proposal(self, research_id: str, table_id: str, column_id: str, svid: str, proposal_id: str, accept: bool,
                        expected_version: int, idempotency_key: str | None) -> str:
        """Accept (the proposal's value and evidence become the cell's, authored by the user) or dismiss the pending proposal."""
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            self._table(research_id, table_id)
            self._column(table_id, column_id)
            self._active_row(table_id, svid)
            cell = self._cell(table_id, column_id, svid)
            if replayed := self._replayed_revision(key, cell["id"]):
                return replayed
            check_expected_version(expected_version, cell["version"])
            proposal = self._revision(proposal_id)
            if proposal is None or proposal["cell_id"] != cell["id"] or proposal["kind"] != "model_proposal":
                raise NotFound(proposal_id)
            if self._decision(proposal_id):
                raise RevisionConflict("This proposal has already been decided")
            if self._latest_proposal(cell["id"])["id"] != proposal_id:
                raise RevisionConflict("A newer proposal replaced this one")
            if not accept:
                revision_id = self._insert_revision(cell, key, kind="dismiss_proposal", author="human", based_on_revision_id=proposal_id,
                                                    column_revision=proposal["column_revision"])
                self._set_current(research_id, cell, None, "dismiss_proposal")
                return revision_id
            if proposal["output_status"] != "structurally_valid":
                raise InvalidTableInput("A proposal that failed validation cannot be accepted")
            revision_id = self._insert_revision(
                cell, key, kind="accept_proposal", author="human", based_on_revision_id=proposal_id,
                column_revision=proposal["column_revision"], state=proposal["state"],
                value_json=json.loads(proposal["value_json"]) if proposal["value_json"] else None, note=proposal["note"],
                reading_depth=proposal["reading_depth"],
            )
            self._insert_links(revision_id, self._links(proposal_id))
            self._set_current(research_id, cell, revision_id, "accept_proposal")
        return revision_id

    def save_model_output(self, research_id: str, table_id: str, column_id: str, svid: str, *, column_revision: int, state: str,
                          value: Any, note: str | None, reading_depth: str, output_status: str, links: list[dict[str, Any]],
                          run_id: str, step_id: str, step_input_id: str, model_connection: str, resolved_model: str | None,
                          scope_revision: int, cell_version_at_request: int | None, recheck: bool) -> str:
        """A valid fill result for an empty cell becomes its value; every other model result waits as a proposal."""
        with transaction(self.conn):
            cell = self._cell(table_id, column_id, svid, create=True)
            existing = self.conn.execute(
                "SELECT id FROM cell_revisions WHERE cell_id = ? AND step_input_id = ? AND author = 'model'", (cell["id"], step_input_id)
            ).fetchone()
            if existing:
                return existing["id"]  # saved before a restart; a resumed run must not add it twice
            fill = not recheck and cell["current_revision_id"] is None and output_status == "structurally_valid"
            kind = "model_fill" if fill else "model_proposal"
            revision_id = self._insert_revision(
                cell, kind=kind, author="model", column_revision=column_revision, state=state, value_json=value, note=note,
                reading_depth=reading_depth, output_status=output_status, cell_version_at_request=cell_version_at_request,
                scope_revision=scope_revision, run_id=run_id, step_id=step_id, step_input_id=step_input_id,
                model_connection=model_connection, resolved_model=resolved_model,
            )
            self._insert_links(revision_id, [{**link, "step_input_id": step_input_id} for link in links])
            if fill:
                self._set_current(research_id, cell, revision_id, kind)
            else:
                self._touch(table_id)
                self.store._event(research_id, "cell_revision_saved", {"table_id": table_id, "column_id": column_id,
                                                                       "source_version_id": svid, "kind": kind})
        return revision_id

    def save_no_text(self, research_id: str, table_id: str, column_id: str, svid: str, *, column_revision: int, run_id: str,
                     step_id: str, scope_revision: int) -> str | None:
        """A source without any stored text reads as inaccessible, without a model call; only an empty cell takes it."""
        with transaction(self.conn):
            cell = self._cell(table_id, column_id, svid, create=True)
            if cell["current_revision_id"] is not None:
                return None
            revision_id = self._insert_revision(cell, kind="system_fill", author="system", column_revision=column_revision,
                                                state="inaccessible", reading_depth="metadata", scope_revision=scope_revision,
                                                run_id=run_id, step_id=step_id)
            self._set_current(research_id, cell, revision_id, "system_fill")
        return revision_id

    # ---- model work -------------------------------------------------------------------
    def target_columns(self, research_id: str, table_id: str, column_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """The table's active columns in table order; only the named ones when column_ids is given."""
        self._table(research_id, table_id)
        columns = self._columns(table_id)
        if column_ids is None:
            return columns
        if missing := set(column_ids) - {c["id"] for c in columns}:
            raise InvalidTableInput(f"Not a column of this table: {', '.join(sorted(missing))}")
        return [c for c in columns if c["id"] in column_ids]

    def active_rows(self, table_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT t.source_version_id FROM table_rows t JOIN source_versions v ON v.id = t.source_version_id"
            " WHERE t.table_id = ? AND t.removed_at IS NULL ORDER BY t.created_at, v.title", (table_id,)
        )]

    def fill_plan(self, research_id: str, table_id: str, column_ids: list[str] | None = None,
                  include_stale: bool = False) -> dict[str, Any]:
        """The cells a fill would read: empty cells and, with include_stale, values made under an earlier column revision.

        Rows are taken in table order up to MAX_FILL_SOURCES sources. A source without stored text needs no model call.
        """
        columns = self.target_columns(research_id, table_id, column_ids)
        sources, beyond = [], 0
        for svid in self.active_rows(table_id):
            cells = {r["column_id"]: r for r in self.conn.execute(
                "SELECT c.column_id, c.version, r.column_revision FROM evidence_cells c LEFT JOIN cell_revisions r"
                " ON r.id = c.current_revision_id WHERE c.table_id = ? AND c.source_version_id = ?", (table_id, svid)
            )}
            targets = [c["id"] for c in columns if c["id"] not in cells or cells[c["id"]]["column_revision"] is None
                       or (include_stale and cells[c["id"]]["column_revision"] != c["current_revision"])]
            if not targets:
                continue
            if len(sources) == MAX_FILL_SOURCES:
                beyond += 1
                continue
            sources.append({"source_version_id": svid, "column_ids": targets, "has_text": bool(self.store.passages_for(svid)),
                            "cell_versions": {cid: cells[cid]["version"] if cid in cells else 0 for cid in targets}})
        calls = sum(math.ceil(len(s["column_ids"]) / MAX_COLUMNS_PER_CALL) for s in sources if s["has_text"])
        return {"sources": sources, "sources_beyond_limit": beyond, "model_calls": calls, "max_model_calls": CALLS_PER_REQUEST * calls}

    def _replayed_run(self, key: str | None, kind: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id, kind FROM runs WHERE idempotency_key = ?", (key,)).fetchone() if key else None
        if row and row["kind"] != kind:
            raise InvalidTableInput("This idempotency key was used for another request")
        return self.store.run(row["id"]) if row else None

    def request_fill(self, research_id: str, table_id: str, column_ids: list[str] | None, include_stale: bool,
                     expected_version: int, idempotency_key: str | None) -> dict[str, Any]:
        """Queue a fill of the planned cells. The plan is stored with the run, so a resumed run reads the same sources."""
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            if replayed := self._replayed_run(key, "table_fill"):
                return replayed
            check_expected_version(expected_version, self._table(research_id, table_id)["version"])
            plan = self.fill_plan(research_id, table_id, column_ids, include_stale)
            if not plan["sources"]:
                raise InvalidTableInput("No cell of this table needs filling")
            target = {"table_id": table_id, "column_ids": column_ids, "include_stale": include_stale,
                      "sources": [{k: s[k] for k in ("source_version_id", "column_ids", "cell_versions")} for s in plan["sources"]]}
            return self.store.create_run(research_id, "table_fill", {"max_model_calls": plan["max_model_calls"], "max_provider_requests": 0},
                                         key, target)

    def request_recheck(self, research_id: str, table_id: str, column_id: str, svid: str, expected_version: int,
                        idempotency_key: str | None) -> dict[str, Any]:
        """Queue a recheck of one cell; its result waits as a proposal whatever the cell holds (D37)."""
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            if replayed := self._replayed_run(key, "cell_recheck"):
                return replayed
            self._table(research_id, table_id)
            self._column(table_id, column_id)
            self._active_row(table_id, svid)
            cell = self.conn.execute("SELECT version FROM evidence_cells WHERE column_id = ? AND source_version_id = ?",
                                     (column_id, svid)).fetchone()
            version = cell["version"] if cell else 0
            check_expected_version(expected_version, version)
            if not self.store.passages_for(svid):
                raise InvalidTableInput("This source has no stored text to read")
            target = {"table_id": table_id, "column_id": column_id, "source_version_id": svid, "cell_version": version}
            return self.store.create_run(research_id, "cell_recheck", {"max_model_calls": CALLS_PER_REQUEST, "max_provider_requests": 0},
                                         key, target)

    def request_column_suggestions(self, research_id: str, table_id: str, idempotency_key: str | None) -> dict[str, Any]:
        key = self._key(research_id, idempotency_key)
        with transaction(self.conn):
            if replayed := self._replayed_run(key, "table_columns"):
                return replayed
            self._table(research_id, table_id)
            return self.store.create_run(research_id, "table_columns", {"max_model_calls": CALLS_PER_REQUEST, "max_provider_requests": 0},
                                         key, {"table_id": table_id})

    def column_suggestions(self, table_id: str) -> dict[str, Any] | None:
        """The latest suggested columns for this table; a suggestion joins the table only when the user adds it."""
        row = self.conn.execute(
            "SELECT s.id, s.run_id, s.output_json FROM runs r JOIN run_steps s ON s.run_id = r.id WHERE r.kind = 'table_columns'"
            " AND json_extract(r.target_json, '$.table_id') = ? AND s.kind = 'model:table_columns' AND s.status = 'succeeded'"
            " ORDER BY s.finished_at DESC LIMIT 1", (table_id,)
        ).fetchone()
        if row is None:
            return None
        result = json.loads(row["output_json"])["result"]
        return {"run_id": row["run_id"], "step_id": row["id"], "columns": result["columns"], "notes": result["notes"]}

    # ---- templates --------------------------------------------------------------------
    def create_template(self, research_id: str, table_id: str, name: str, idempotency_key: str | None) -> str:
        key = self._key("template", idempotency_key)
        with transaction(self.conn):
            if key and (existing := self.conn.execute("SELECT id FROM table_templates WHERE idempotency_key = ?", (key,)).fetchone()):
                return existing["id"]
            self._table(research_id, table_id)
            columns = [{k: c[k] for k in ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")}
                       for c in self._columns(table_id)]
            if not columns:
                raise InvalidTableInput("A template needs at least one column")
            tpl = new_id("tpl")
            self.conn.execute("INSERT INTO table_templates (id, name, columns_json, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
                              (tpl, name.strip(), dumps(columns), key, now()))
        return tpl

    def templates(self) -> list[dict[str, Any]]:
        return [{"id": r["id"], "name": r["name"], "columns": json.loads(r["columns_json"]), "created_at": r["created_at"]}
                for r in self.conn.execute("SELECT * FROM table_templates WHERE trashed_at IS NULL ORDER BY created_at DESC")]

    def trash_template(self, template_id: str) -> None:
        with transaction(self.conn):
            if not self.conn.execute("UPDATE table_templates SET trashed_at = ? WHERE id = ? AND trashed_at IS NULL",
                                     (now(), template_id)).rowcount:
                raise NotFound(template_id)

    # ---- views ------------------------------------------------------------------------
    def tables(self, research_id: str) -> list[dict[str, Any]]:
        self.store.research(research_id)
        return [dict(r) for r in self.conn.execute(
            "SELECT t.id, t.title, t.version, t.created_at, t.updated_at,"
            " (SELECT COUNT(*) FROM table_rows r WHERE r.table_id = t.id AND r.removed_at IS NULL) AS rows,"
            " (SELECT COUNT(*) FROM table_columns c WHERE c.table_id = t.id AND c.removed_at IS NULL) AS columns"
            " FROM evidence_tables t WHERE t.research_id = ? AND t.trashed_at IS NULL ORDER BY t.created_at", (research_id,)
        )]

    def _revision_view(self, revision: dict[str, Any]) -> dict[str, Any]:
        evidence = [dict(r) | {"asset_removed": bool(r["asset_removed"])} for r in self.conn.execute(
            "SELECT l.passage_id, l.anchor_text, l.anchor_match, p.kind, p.physical_page, p.printed_label, p.asset_id,"
            " a.removed_at IS NOT NULL AS asset_removed FROM cell_evidence_links l JOIN passages p ON p.id = l.passage_id"
            " LEFT JOIN source_assets a ON a.id = p.asset_id WHERE l.cell_revision_id = ? ORDER BY l.rowid", (revision["id"],)
        )]
        return {
            **{k: revision[k] for k in ("id", "kind", "author", "based_on_revision_id", "column_revision", "state", "note",
                                        "reading_depth", "output_status", "cell_version_at_request", "scope_revision", "run_id",
                                        "created_at")},
            "value": json.loads(revision["value_json"]) if revision["value_json"] else None,
            "model": {"connection": revision["model_connection"], "resolved_model": revision["resolved_model"]}
            if revision["author"] == "model" else None,
            "evidence": evidence,
        }

    def _cell_summary(self, cell: dict[str, Any], column: dict[str, Any]) -> dict[str, Any]:
        current = self._revision(cell["current_revision_id"]) if cell["current_revision_id"] else None
        current_view = self._revision_view(current) if current else None
        latest = self._latest_proposal(cell["id"])
        pending = latest if latest and self._decision(latest["id"]) is None else None
        flags = []
        if current_view and current_view["column_revision"] != column["current_revision"]:
            flags.append("stale_column")
        if current_view and any(e["asset_removed"] for e in current_view["evidence"]):
            flags.append("pdf_withdrawn")
        if pending and pending["cell_version_at_request"] is not None and pending["cell_version_at_request"] < cell["version"]:
            flags.append("proposal_before_edit")
        if pending and pending["output_status"] != "structurally_valid":
            flags.append("proposal_invalid")
        return {"cell_id": cell["id"], "column_id": cell["column_id"], "source_version_id": cell["source_version_id"],
                "version": cell["version"], "current": current_view,
                "pending_proposal": self._revision_view(pending) if pending else None, "flags": flags}

    def table_view(self, research_id: str, table_id: str) -> dict[str, Any]:
        table = self._table(research_id, table_id)
        columns = self._columns(table_id)
        rows = []
        for r in self.conn.execute(
            "SELECT t.source_version_id, t.added_by, t.created_at, t.removed_at, v.work_id, v.title, v.authors_json, v.year,"
            " v.version_label, sel.state AS selection_state,"
            " EXISTS (SELECT 1 FROM passages p JOIN source_assets a ON a.id = p.asset_id"
            "  WHERE p.source_version_id = t.source_version_id AND a.removed_at IS NULL) AS has_pdf_text,"
            " EXISTS (SELECT 1 FROM passages p WHERE p.source_version_id = t.source_version_id AND p.kind = 'abstract') AS has_abstract"
            " FROM table_rows t JOIN source_versions v ON v.id = t.source_version_id"
            " LEFT JOIN selections sel ON sel.research_id = ? AND sel.source_version_id = t.source_version_id"
            " WHERE t.table_id = ? ORDER BY t.created_at, v.title", (research_id, table_id)
        ):
            rows.append({"source_version_id": r["source_version_id"], "work_id": r["work_id"], "title": r["title"],
                         "authors": json.loads(r["authors_json"]), "year": r["year"], "version_label": r["version_label"],
                         "selection_state": r["selection_state"], "added_by": r["added_by"], "added_at": r["created_at"],
                         "removed_at": r["removed_at"],
                         "access_level": "pdf_available" if r["has_pdf_text"] else "abstract" if r["has_abstract"] else "metadata"})
        active_rows = {r["source_version_id"] for r in rows if r["removed_at"] is None}
        by_column = {c["id"]: c for c in columns}
        cells = [self._cell_summary(dict(c), by_column[c["column_id"]]) for c in self.conn.execute(
            "SELECT * FROM evidence_cells WHERE table_id = ? ORDER BY created_at", (table_id,)
        ) if c["column_id"] in by_column and c["source_version_id"] in active_rows]
        plan = self.fill_plan(research_id, table_id)
        return {
            "table": {k: table[k] for k in ("id", "research_id", "title", "template_id", "version", "created_at", "updated_at")},
            "columns": [{"id": c["id"], "position": c["position"], "revision": c["current_revision"], "version": c["version"],
                         "origin": c["origin"], **{k: c[k] for k in ("name", "instruction", "answer_format", "options",
                                                                     "allow_multiple", "unit_hint")}} for c in columns],
            "rows": [r for r in rows if r["removed_at"] is None],
            "removed_rows": [r for r in rows if r["removed_at"] is not None],
            "cells": cells,
            "counts": {"rows": len(active_rows), "columns": len(columns),
                       "with_value": sum(c["current"] is not None for c in cells),
                       "empty": len(active_rows) * len(columns) - sum(c["current"] is not None for c in cells),
                       "pending_proposals": sum(c["pending_proposal"] is not None for c in cells)},
            "fill_estimate": {"sources": len(plan["sources"]), "sources_without_text": sum(not s["has_text"] for s in plan["sources"]),
                              **{k: plan[k] for k in ("sources_beyond_limit", "model_calls", "max_model_calls")}},
            "column_suggestions": self.column_suggestions(table_id),
        }

    def cell_view(self, research_id: str, table_id: str, column_id: str, svid: str) -> dict[str, Any]:
        """The cell's summary and its full revision history, oldest first, each with its evidence."""
        self._table(research_id, table_id)
        column = next((c for c in self._columns(table_id, include_removed=True) if c["id"] == column_id), None)
        if column is None:
            raise NotFound(column_id)
        row = self.conn.execute("SELECT 1 FROM table_rows WHERE table_id = ? AND source_version_id = ?", (table_id, svid)).fetchone()
        if row is None:
            raise NotFound(svid)
        found = self.conn.execute("SELECT * FROM evidence_cells WHERE column_id = ? AND source_version_id = ?", (column_id, svid)).fetchone()
        if found is None:
            return {"cell_id": None, "column_id": column_id, "source_version_id": svid, "version": 0, "current": None,
                    "pending_proposal": None, "flags": [], "revisions": []}
        cell = dict(found)
        latest = self._latest_proposal(cell["id"])
        revisions = []
        for r in self.conn.execute("SELECT * FROM cell_revisions WHERE cell_id = ? ORDER BY created_at, rowid", (cell["id"],)):
            view = self._revision_view(dict(r))
            if r["kind"] == "model_proposal":
                decision = self._decision(r["id"])
                view["decision"] = {"accept_proposal": "accepted", "dismiss_proposal": "dismissed"}.get(decision or "") or (
                    "pending" if latest and latest["id"] == r["id"] else "superseded")
            revisions.append(view)
        return self._cell_summary(cell, column) | {"revisions": revisions}


def purge_tables(conn: Any, research_id: str) -> None:
    """Delete a research's tables during permanent deletion; the caller holds the purge authorization."""
    tables = "SELECT id FROM evidence_tables WHERE research_id = ?"
    cells = f"SELECT id FROM evidence_cells WHERE table_id IN ({tables})"
    conn.execute(f"UPDATE evidence_cells SET current_revision_id = NULL WHERE table_id IN ({tables})", (research_id,))
    conn.execute(f"DELETE FROM cell_evidence_links WHERE cell_revision_id IN (SELECT id FROM cell_revisions WHERE cell_id IN ({cells}))",
                 (research_id,))
    conn.execute(f"DELETE FROM cell_revisions WHERE cell_id IN ({cells})", (research_id,))
    conn.execute(f"DELETE FROM evidence_cells WHERE table_id IN ({tables})", (research_id,))
    conn.execute(f"DELETE FROM table_rows WHERE table_id IN ({tables})", (research_id,))
    conn.execute(f"DELETE FROM column_revisions WHERE column_id IN (SELECT id FROM table_columns WHERE table_id IN ({tables}))",
                 (research_id,))
    conn.execute(f"DELETE FROM table_columns WHERE table_id IN ({tables})", (research_id,))
    conn.execute("DELETE FROM evidence_tables WHERE research_id = ?", (research_id,))
