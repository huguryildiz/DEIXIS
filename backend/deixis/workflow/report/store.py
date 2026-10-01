"""Synchronous report persistence on the research store's SQLite connection."""

from __future__ import annotations

import json
from typing import Any

from deixis.domain.contracts import _math_span_is_well_formed, _math_spans
from deixis.domain.rules import MAX_SCHEMA_REPAIRS, TEST_EFFORT_BUDGETS, RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.report.snapshot import build_snapshot, included_table_rows
from deixis.workflow.store import NotFound, Store
from deixis.workflow.tables import InvalidTableInput, TableStore

# The smallest model-call ceiling a report run may get, whatever the derived worst case is (owner, 2026-09-18).
REPORT_CALL_FLOOR = 50
DISPLAY_ORDER = ("abstract", "index_terms", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX")


class ReportStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def _event(self, report_id: str, type_: str, **payload: Any) -> None:
        report = self.report(report_id)
        self.store._event(report["research_id"], type_, {"report_id": report_id, **payload}, report["run_id"])

    def request_report(self, research_id: str, table_id: str,
                       idempotency_key: str | None, continue_with_failed: bool = False) -> dict[str, Any]:
        """Queue a report run over one evidence table, refusing a table that is not ready."""
        from deixis.workflow.report.sections import ROUNDS
        from deixis.workflow.tables import report_ready

        key = f"{research_id}:{idempotency_key}" if idempotency_key else None
        with transaction(self.conn):
            existing = self.conn.execute(
                "SELECT id, kind FROM runs WHERE idempotency_key = ?", (key,),
            ).fetchone() if key else None
            if existing:
                if existing["kind"] != "report":
                    raise RevisionConflict("This idempotency key was used for another request")
                return self.store.run(existing["id"])

            scope = self.store.scope(research_id)
            readiness = report_ready(self.store, research_id, table_id, continue_with_failed=continue_with_failed)
            if not self.store.included_sources(research_id) or not readiness["ready"]:
                raise RevisionConflict("Include sources and fill every active evidence-table column before starting a report")

            section_count = sum(map(len, ROUNDS))
            # (Plan + model-written sections + optional research title + one optional phrase repair per section + review)
            # times (initial call + bounded schema repairs per model step).
            # The owner set a floor of 50 on 2026-09-18 so an unforeseen extra call cannot truncate a report.
            max_model_calls = max(REPORT_CALL_FLOOR, (1 + section_count + 1 + section_count + 1) * (1 + MAX_SCHEMA_REPAIRS))
            budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__ | {
                "max_model_calls": max_model_calls,
                "max_provider_requests": 0,
            }
            run = self.store.create_run(research_id, "report", budget, key, {"table_id": table_id})
            report_id = self.create_report(
                research_id, run["id"], run["scope_revision"], scope["language_hint"],
            )
            return self.store.update_run(
                run["id"], target_json=dumps({"table_id": table_id, "report_id": report_id,
                                            **({"continue_with_failed": True} if continue_with_failed else {})}),
            )

    def create_report(self, research_id: str, run_id: str, scope_revision: int, language: str | None) -> str:
        with transaction(self.conn):
            run = self.store.run(run_id)
            if run["research_id"] != research_id or run["scope_revision"] != scope_revision or run["kind"] != "report":
                raise ValueError("A report must belong to a report run of the same research and scope revision")
            existing = self.conn.execute("SELECT id FROM reports WHERE run_id = ?", (run_id,)).fetchone()
            if existing:
                return existing["id"]
            report_id, ts = new_id("rpt"), now()
            self.conn.execute(
                "INSERT INTO reports (id, research_id, run_id, scope_revision, status, language, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'in_progress', ?, ?, ?)",
                (report_id, research_id, run_id, scope_revision, language, ts, ts),
            )
            self._event(report_id, "report_created")
        return report_id

    def report(self, report_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise NotFound(report_id)
        result = dict(row)
        plan_json = result.pop("plan_json")
        result["plan"] = json.loads(plan_json) if plan_json else None
        review_json = result.pop("review_json")
        result["review"] = json.loads(review_json) if review_json else None
        return result

    def save_review(self, report_id: str, record: dict[str, Any]) -> None:
        with transaction(self.conn):
            self.report(report_id)
            self.conn.execute("UPDATE reports SET review_json = ?, updated_at = ? WHERE id = ?",
                              (dumps(record), now(), report_id))
            self._event(report_id, "report_review_saved", status=record["status"])

    def set_plan(self, report_id: str, plan: dict[str, Any]) -> None:
        with transaction(self.conn):
            self.report(report_id)
            self.conn.execute("UPDATE reports SET plan_json = ?, updated_at = ? WHERE id = ?", (dumps(plan), now(), report_id))
            self._event(report_id, "report_plan_saved")

    def save_snapshot(self, report_id: str, table_id: str, continue_with_failed: bool = False) -> dict[str, Any]:
        """Read and insert once in one transaction; later table edits cannot change this report's evidence."""
        with transaction(self.conn):
            report = self.report(report_id)
            existing = self.conn.execute("SELECT table_id, snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()
            if existing:
                if existing["table_id"] != table_id:
                    raise ValueError("This report already has a snapshot of another table")
                return json.loads(existing["snapshot_json"])
            readiness = None
            if continue_with_failed:
                from deixis.workflow.tables import report_ready

                readiness = report_ready(self.store, report["research_id"], table_id, continue_with_failed=True)
                if not readiness["ready"]:
                    raise RevisionConflict("Include sources and fill every active evidence-table column before starting a report")
            snapshot = build_snapshot(self.store, report["research_id"], table_id, readiness)
            self.conn.execute(
                "INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (report_id, table_id, snapshot["table_revision"], dumps(snapshot), now()),
            )
            self._event(report_id, "report_snapshot_saved", table_id=table_id)
        return snapshot

    def snapshot(self, report_id: str) -> dict[str, Any]:
        self.report(report_id)
        row = self.conn.execute("SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise NotFound(f"snapshot for {report_id}")
        return json.loads(row["snapshot_json"])

    def create_section(self, report_id: str, section_id: str, ordinal: int) -> str:
        with transaction(self.conn):
            self.report(report_id)
            existing = self.conn.execute(
                "SELECT id FROM report_sections WHERE report_id = ? AND section_id = ?", (report_id, section_id)
            ).fetchone()
            if existing:
                return existing["id"]
            section_key, ts = new_id("rsc"), now()
            self.conn.execute(
                "INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
                " VALUES (?, ?, ?, 'pending', ?, ?, ?)", (section_key, report_id, section_id, ordinal, ts, ts),
            )
            self._event(report_id, "report_section_created", section_id=section_id)
        return section_key

    def section(self, report_id: str, section_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM report_sections WHERE report_id = ? AND section_id = ?", (report_id, section_id)
        ).fetchone()
        if row is None:
            raise NotFound(f"{report_id}/{section_id}")
        return self._section_dict(row)

    @staticmethod
    def _section_dict(row: Any) -> dict[str, Any]:
        result = dict(row)
        for field in ("draft_json", "validation_json"):
            value = result.pop(field)
            result[field[:-5]] = json.loads(value) if value else None
        return result

    def sections(self, report_id: str) -> list[dict[str, Any]]:
        self.report(report_id)
        return [self._section_dict(row) for row in self.conn.execute(
            "SELECT * FROM report_sections WHERE report_id = ? ORDER BY ordinal, created_at", (report_id,)
        )]

    def save_section_draft(self, report_section_id: str, step_id: str, status: str, draft: dict[str, Any] | None,
                           validation: dict[str, Any], word_count: int | None) -> None:
        with transaction(self.conn):
            row = self.conn.execute("SELECT report_id, section_id FROM report_sections WHERE id = ?", (report_section_id,)).fetchone()
            if row is None:
                raise NotFound(report_section_id)
            self.conn.execute(
                "UPDATE report_sections SET step_id = ?, status = ?, draft_json = ?, validation_json = ?,"
                " word_count = ?, updated_at = ? WHERE id = ?",
                (step_id, status, dumps(draft) if draft is not None else None, dumps(validation), word_count, now(), report_section_id),
            )
            self._event(row["report_id"], "report_section_saved", section_id=row["section_id"], status=status)

    def save_claims(self, report_section_id: str, claims: list[dict[str, Any]],
                    citation_links: list[dict[str, Any]]) -> None:
        with transaction(self.conn):
            section = self.conn.execute("SELECT report_id FROM report_sections WHERE id = ?", (report_section_id,)).fetchone()
            if section is None:
                raise NotFound(report_section_id)
            if self.conn.execute(
                "SELECT 1 FROM report_claim_revisions v JOIN report_claims c ON c.id = v.claim_id"
                " WHERE c.report_section_id = ? LIMIT 1", (report_section_id,),
            ).fetchone():
                raise RevisionConflict("A section with human-edited claims cannot be replaced")
            self.conn.execute(
                "DELETE FROM report_citation_links WHERE claim_id IN"
                " (SELECT id FROM report_claims WHERE report_section_id = ?)", (report_section_id,),
            )
            self.conn.execute(
                "DELETE FROM report_claim_refs WHERE claim_id IN"
                " (SELECT id FROM report_claims WHERE report_section_id = ?)", (report_section_id,),
            )
            self.conn.execute("DELETE FROM report_claims WHERE report_section_id = ?", (report_section_id,))
            claim_ids = {}
            for ordinal, claim in enumerate(claims, 1):
                claim_id = new_id("rcl")
                claim_ids[claim["claim_key"]] = claim_id
                self.conn.execute(
                    "INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type,"
                    " table_ref, equation_ref, axis_id, count_json, equation_origin_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (claim_id, report_section_id, claim["claim_key"], ordinal, claim["paragraph"], claim["text"],
                     claim["support_type"], claim.get("table_ref"), claim.get("equation_ref"), claim.get("axis_id"),
                     dumps(claim["count"]) if claim.get("count") is not None else None,
                     dumps(claim["equation_origin"]) if claim.get("equation_origin") is not None else None),
                )
                for ref_kind, field in (("body_ref", "body_refs"), ("gap_ref", "gap_refs")):
                    self.conn.executemany(
                        "INSERT INTO report_claim_refs (claim_id, ref_kind, ref_value) VALUES (?, ?, ?)",
                        [(claim_id, ref_kind, ref) for ref in claim.get(field, [])],
                    )
            for link in citation_links:
                self.conn.execute(
                    "INSERT INTO report_citation_links (id, claim_id, passage_id, cell_id, source_version_id,"
                    " step_input_id, anchor_text, anchor_match) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("rln"), claim_ids[link["claim_key"]], link.get("passage_id"), link.get("cell_id"),
                     link["source_version_id"], link["step_input_id"], link.get("anchor_text"), link.get("anchor_match")),
                )
            self._event(section["report_id"], "report_claims_saved", section_id=report_section_id)

    def edit_claim(self, research_id: str, report_id: str, claim_id: str, *, text: str | None,
                   restore_from: str | None, note: str | None, expected_version: int,
                   idempotency_key: str | None) -> str:
        """Keep model text and citation links fixed while recording one human revision."""
        key = f"{research_id}:{idempotency_key}" if idempotency_key else None
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT c.*, r.status AS report_status, r.run_id, s.section_id FROM report_claims c"
                " JOIN report_sections s ON s.id = c.report_section_id JOIN reports r ON r.id = s.report_id"
                " WHERE c.id = ? AND s.report_id = ? AND r.research_id = ?",
                (claim_id, report_id, research_id),
            ).fetchone()
            if row is None:
                raise NotFound(claim_id)
            if key:
                replay = self.conn.execute(
                    "SELECT id, claim_id FROM report_claim_revisions WHERE idempotency_key = ?", (key,),
                ).fetchone()
                if replay:
                    if replay["claim_id"] != claim_id:
                        raise RevisionConflict("This idempotency key was used for another claim")
                    return replay["id"]
            run = self.store.run(row["run_id"])
            if row["report_status"] not in ("valid", "draft") or run["status"] not in ("completed", "failed", "cancelled"):
                raise RevisionConflict("A report can be edited once its run has finished")
            check_expected_version(expected_version, row["version"])
            if (text is None) == (restore_from is None):
                raise InvalidTableInput("Give either text or a revision to restore")
            if restore_from is not None:
                if restore_from == "model":
                    new_text = row["text"]
                else:
                    previous = self.conn.execute(
                        "SELECT text FROM report_claim_revisions WHERE id = ? AND claim_id = ?",
                        (restore_from, claim_id),
                    ).fetchone()
                    if previous is None:
                        raise InvalidTableInput("Restore only a revision of this claim")
                    new_text = previous["text"]
            else:
                new_text = text
            new_text = new_text.strip()
            current = self.conn.execute(
                "SELECT text FROM report_claim_revisions WHERE id = ?", (row["current_revision_id"],),
            ).fetchone() if row["current_revision_id"] else None
            if not new_text or new_text == (current["text"] if current else row["text"]):
                raise InvalidTableInput("The edited text must be non-empty and different from the current text")
            warnings = [{"kind": "math_not_well_formed", "detail": span}
                        for span in _math_spans(new_text) if not _math_span_is_well_formed(span)]
            if row["count_json"] is not None:
                warnings.append({"kind": "count_not_rechecked", "detail": "The count was not rechecked after this edit"})
            revision_id = new_id("rcv")
            self.conn.execute(
                "INSERT INTO report_claim_revisions (id, claim_id, kind, restored_from, text, warnings_json, note,"
                " idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (revision_id, claim_id, "human_restore" if restore_from else "human_edit", restore_from,
                 new_text, dumps(warnings), (note or "").strip() or None, key, now()),
            )
            self.conn.execute("UPDATE report_claims SET current_revision_id = ?, version = version + 1 WHERE id = ?",
                              (revision_id, claim_id))
            self.conn.execute("UPDATE reports SET updated_at = ? WHERE id = ?", (now(), report_id))
            self._event(report_id, "report_claim_edited", claim_id=claim_id, revision_id=revision_id,
                        section_id=row["section_id"])
        return revision_id

    def claim_revisions(self, claim_id: str) -> list[dict[str, Any]]:
        revisions = []
        for row in self.conn.execute(
            "SELECT id, claim_id, kind, restored_from, text, warnings_json, note, created_at"
            " FROM report_claim_revisions WHERE claim_id = ? ORDER BY created_at, rowid", (claim_id,),
        ):
            revision = dict(row)
            revision["warnings"] = json.loads(revision.pop("warnings_json"))
            revisions.append(revision)
        return revisions

    def effective_links(self, report_id: str) -> list[dict]:
        """E1 uses all original links; citation selection belongs to E2."""
        return [dict(row) for row in self.conn.execute(
            "SELECT l.*, c.claim_key, s.section_id FROM report_citation_links l"
            " JOIN report_claims c ON c.id = l.claim_id"
            " JOIN report_sections s ON s.id = c.report_section_id"
            " WHERE s.report_id = ? ORDER BY l.rowid", (report_id,),
        )]

    def check_edits(self, research_id: str, report_id: str) -> dict:
        from deixis.workflow.report import assembly, edit_check

        with transaction(self.conn):
            report = self.report(report_id)
            if report["research_id"] != research_id:
                raise NotFound(report_id)
            self.store.research(research_id)  # a trashed research is not found, so nothing is written
            run = self.store.run(report["run_id"])
            if report["status"] not in ("valid", "draft") or run["status"] not in ("completed", "failed", "cancelled"):
                raise RevisionConflict("A report can be checked once its run has finished")
            fingerprint = edit_check.fingerprint(edit_check.manifest(self.store, self, report_id))
            row = self.conn.execute("SELECT * FROM report_edit_checks WHERE report_id = ? AND input_fingerprint = ?",
                                    (report_id, fingerprint)).fetchone()
            if row is not None:
                return edit_check.record(row)
            result = assembly.run_current_checks(self.store, self, report_id)
            check_id = new_id("rec")
            self.conn.execute(
                "INSERT INTO report_edit_checks (id, report_id, checker_version, input_fingerprint, result_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (check_id, report_id, result["checker_version"], fingerprint, edit_check.canonical(result), now()),
            )
            self._event(report_id, "report_edits_checked", check_id=check_id)
            return edit_check.record(self.conn.execute("SELECT * FROM report_edit_checks WHERE id = ?",
                                                       (check_id,)).fetchone())

    def edit_check_state(self, report_id: str) -> dict | None:
        from deixis.workflow.report import edit_check

        with transaction(self.conn):
            return edit_check.state(self.store, self, report_id)

    def evidence_changes(self, report_id: str) -> dict[str, Any]:
        """Compare stored cell and row identities with live records; passage extraction is not measured."""
        report = self.report(report_id)
        sections = [row["section_id"] for row in self.conn.execute(
            "SELECT section_id FROM report_sections WHERE report_id = ?", (report_id,),
        )]
        empty = {section: {"open": [], "acknowledged_count": 0, "unresolved_refs": 0} for section in sections}
        result = {"changed_cells": 0, "removed_sources": 0, "added_sources": 0,
                  "revised_columns": 0, "any": False, "not_checked": ["passages"], "sections": empty}
        saved = self.conn.execute(
            "SELECT table_id, snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,),
        ).fetchone()
        if saved is None:
            return result
        snapshot = json.loads(saved["snapshot_json"])
        table_id = saved["table_id"]
        live_rows = set(included_table_rows(self.store, report["research_id"], table_id))
        frozen_rows = {row["source_version_id"] for row in snapshot["rows"]}
        removed = frozen_rows - live_rows
        result["removed_sources"] = len(removed)
        result["added_sources"] = len(live_rows - frozen_rows)
        stamps = {row["source_version_id"]: row for row in self.conn.execute(
            "SELECT t.source_version_id, t.removed_at AS row_removed_at, m.removed_at AS membership_removed_at,"
            " s.state AS selection_state, s.updated_at AS selection_updated_at FROM table_rows t"
            " LEFT JOIN corpus_memberships m ON m.research_id = ? AND m.source_version_id = t.source_version_id"
            " LEFT JOIN selections s ON s.research_id = ? AND s.source_version_id = t.source_version_id"
            " WHERE t.table_id = ?", (report["research_id"], report["research_id"], table_id),
        )}
        removed_changes = {}
        for source_id in removed:
            record = stamps.get(source_id)
            departure = [] if record is None else [record["row_removed_at"], record["membership_removed_at"],
                record["selection_updated_at"] if record["selection_state"] != "included" else None]
            stamp = max((value for value in departure if value is not None), default="none")
            removed_changes[source_id] = {"key": f"source:{source_id}:{stamp}", "kind": "source_removed",
                                          "source_version_id": source_id}
        live_cells = {row["id"]: row["current_revision_id"] for row in self.conn.execute(
            "SELECT id, current_revision_id FROM evidence_cells WHERE table_id = ?", (table_id,),
        )}
        changed_cells = {}
        for cell in snapshot["cells"]:
            live_revision = live_cells.get(cell["cell_id"])
            if live_revision != cell["cell_revision_id"]:
                changed_cells[cell["cell_id"]] = {
                    "key": f"cell:{cell['cell_id']}:{live_revision or 'none'}", "kind": "cell_changed",
                    "source_version_id": cell["source_version_id"], "cell_id": cell["cell_id"],
                    "column_id": cell["column_id"],
                }
        result["changed_cells"] = len(changed_cells)
        # target_columns checks table visibility; a trashed table still has readable column revisions.
        live_columns = {column["id"]: column["current_revision"] for column in
                        TableStore(self.store)._columns(table_id)}
        result["revised_columns"] = sum(live_columns.get(column["column_id"]) != column["revision"]
                                        for column in snapshot["columns"])
        result["any"] = any(result[field] for field in
                            ("changed_cells", "removed_sources", "added_sources", "revised_columns"))

        claims = [dict(row) for row in self.conn.execute(
            "SELECT c.id, c.claim_key, s.section_id FROM report_claims c"
            " JOIN report_sections s ON s.id = c.report_section_id WHERE s.report_id = ?", (report_id,),
        )]
        by_id = {claim["id"]: claim for claim in claims}
        by_key: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            by_key.setdefault(claim["claim_key"], []).append(claim)
        direct: dict[str, dict[str, dict[str, Any]]] = {claim["id"]: {} for claim in claims}
        for link in self.conn.execute(
            "SELECT l.claim_id, l.cell_id, l.source_version_id FROM report_citation_links l"
            " JOIN report_claims c ON c.id = l.claim_id JOIN report_sections s ON s.id = c.report_section_id"
            " WHERE s.report_id = ?", (report_id,),
        ):
            if change := changed_cells.get(link["cell_id"]):
                direct[link["claim_id"]][change["key"]] = change | {"via": "citation"}
            if change := removed_changes.get(link["source_version_id"]):
                direct[link["claim_id"]][change["key"]] = change | {"via": "citation"}
        section_changes: dict[str, dict[str, dict[str, Any]]] = {section: {} for section in sections}
        for claim in claims:
            section_changes[claim["section_id"]].update(direct[claim["id"]])
        gaps = {row["gap_id"]: json.loads(row["basis_json"]) for row in self.conn.execute(
            "SELECT gap_id, basis_json FROM report_gaps WHERE report_id = ?", (report_id,),
        )}
        frozen_cell_ids = {cell["cell_id"] for cell in snapshot["cells"]}
        for ref in self.conn.execute(
            "SELECT f.claim_id, f.ref_kind, f.ref_value FROM report_claim_refs f"
            " JOIN report_claims c ON c.id = f.claim_id JOIN report_sections s ON s.id = c.report_section_id"
            " WHERE s.report_id = ?", (report_id,),
        ):
            section_id = by_id[ref["claim_id"]]["section_id"]
            target = section_changes[section_id]
            if ref["ref_kind"] == "body_ref":
                matches = [claim for claim in by_key.get(ref["ref_value"], []) if claim["section_id"] != section_id]
                if len(matches) != 1:
                    result["sections"][section_id]["unresolved_refs"] += 1
                    continue
                indirect = direct[matches[0]["id"]].values()
            else:
                basis = gaps.get(ref["ref_value"])
                if basis is None:
                    result["sections"][section_id]["unresolved_refs"] += 1
                    continue
                indirect = []
                for cell_id in basis.get("basis_cell_ids", []):
                    if cell_id not in frozen_cell_ids:
                        result["sections"][section_id]["unresolved_refs"] += 1
                    elif cell_id in changed_cells:
                        indirect.append(changed_cells[cell_id])
                for claim_key in basis.get("basis_claim_keys", []):
                    matches = by_key.get(claim_key, [])
                    if len(matches) != 1:
                        result["sections"][section_id]["unresolved_refs"] += 1
                    else:
                        indirect.extend(direct[matches[0]["id"]].values())
            for change in indirect:
                target.setdefault(change["key"], change | {"via": ref["ref_kind"]})
        acknowledged = {(row["section_id"], row["change_key"]) for row in self.conn.execute(
            "SELECT section_id, change_key FROM report_stale_acknowledgements WHERE report_id = ?", (report_id,),
        )}
        for section_id, changes in section_changes.items():
            result["sections"][section_id]["open"] = [change for key, change in sorted(changes.items())
                                                       if (section_id, key) not in acknowledged]
            result["sections"][section_id]["acknowledged_count"] = sum(
                (section_id, key) in acknowledged for key in changes)
        return result

    def acknowledge_changes(self, research_id: str, report_id: str, section_id: str,
                            change_keys: list[str]) -> int:
        with transaction(self.conn):
            report = self.report(report_id)
            if report["research_id"] != research_id:
                raise NotFound(report_id)
            self.section(report_id, section_id)
            open_keys = {change["key"] for change in self.evidence_changes(report_id)["sections"][section_id]["open"]}
            if not change_keys or not set(change_keys) <= open_keys:
                raise RevisionConflict("The evidence changed again; reload this report")
            inserted = 0
            for key in change_keys:
                inserted += self.conn.execute(
                    "INSERT OR IGNORE INTO report_stale_acknowledgements"
                    " (id, report_id, section_id, change_key, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("rsa"), report_id, section_id, key, now()),
                ).rowcount
            self._event(report_id, "report_changes_acknowledged", section_id=section_id, count=inserted)
            return inserted

    def save_gaps(self, report_id: str, gaps: list[dict[str, Any]]) -> None:
        with transaction(self.conn):
            self.report(report_id)
            saved = False
            for gap in gaps:
                basis = gap.get("basis", {key: gap[key] for key in (
                    "basis_claim_keys", "basis_passage_ids", "basis_cell_ids", "nearest_match") if key in gap})
                cursor = self.conn.execute(
                    "INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json,"
                    " kill_search_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(report_id, gap_id) DO UPDATE SET kind = excluded.kind, text = excluded.text,"
                    " basis_json = excluded.basis_json, provenance_json = excluded.provenance_json,"
                    " kill_search_status = excluded.kill_search_status, created_at = excluded.created_at",
                    (new_id("rgp"), report_id, gap["gap_id"], gap["kind"], gap["text"], dumps(basis),
                     dumps(gap["provenance"]), gap.get("kill_search_status", "not_run"), now()),
                )
                saved = cursor.rowcount > 0 or saved
            if saved:
                self._event(report_id, "report_gaps_saved")

    def save_phrase_repair(self, report_id: str, section_id: str, sentence_id: str, before: str, after: str,
                           outcome: str) -> None:
        with transaction(self.conn):
            self.report(report_id)
            self.conn.execute(
                "INSERT INTO report_phrase_repairs (id, report_id, section_id, sentence_id, before, after, outcome, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("rpr"), report_id, section_id, sentence_id, before, after, outcome, now()),
            )
            self._event(report_id, "report_phrase_repair_saved", section_id=section_id, outcome=outcome)

    def revert_repair(self, report_id: str, section_id: str, sentence_id: str) -> str:
        """Restore one shown claim sentence, provided both stored copies and assembly still agree."""
        from deixis.domain import phrasebank
        from deixis.workflow.report import assembly
        from deixis.workflow.report.phrasing import _location
        from deixis.workflow.report.sections import _word_count

        def errors() -> list[dict[str, Any]]:
            return [issue for issue in assembly.run_assembly_checks(self.store, self, report_id)
                    if not (issue["rule"].endswith("_warning") and issue["detail"].startswith("WARNING:"))]

        class WouldBreakAssembly(Exception):
            pass

        try:
            with transaction(self.conn):
                row = self.conn.execute(
                    "SELECT before, after, outcome FROM report_phrase_repairs"
                    " WHERE report_id = ? AND section_id = ? AND sentence_id = ? ORDER BY rowid DESC LIMIT 1",
                    (report_id, section_id, sentence_id),
                ).fetchone()
                if row is not None and row["outcome"] == "reverted_exception":
                    return "reverted"
                if errors():
                    return "report_has_assembly_errors"
                if row is None or row["outcome"] != "kept":
                    return "not_kept"
                section = self.section(report_id, section_id)
                draft = section["draft"]
                location = _location(draft, sentence_id) if draft is not None else None
                claim_key = sentence_id.split("#", 1)[0]
                claim = self.conn.execute(
                    "SELECT c.id, c.text FROM report_claims c WHERE c.report_section_id = ? AND c.claim_key = ?",
                    (section["id"], claim_key),
                ).fetchone()
                if location is None or claim is None:
                    return "text_changed"
                owner, field, position = location
                draft_sentences = phrasebank.sentences(owner[field])
                claim_sentences = phrasebank.sentences(claim["text"])
                if (position >= len(draft_sentences) or position >= len(claim_sentences)
                        or draft_sentences[position] != row["after"] or claim_sentences[position] != row["after"]
                        or draft_sentences != claim_sentences):
                    return "text_changed"
                def replace_at(text: str, parts: list[str]) -> str:
                    # Find the selected sentence in sequence, preserving every separator and other sentence.
                    cursor = 0
                    for part in parts[:position]:
                        start = text.find(part, cursor)
                        if start < 0:
                            raise ValueError("Stored sentence is not contiguous in its claim")
                        cursor = start + len(part)
                    start = text.find(row["after"], cursor)
                    if start < 0:
                        raise ValueError("Repaired sentence is not contiguous in its claim")
                    return text[:start] + row["before"] + text[start + len(row["after"]):]

                try:
                    restored_draft = replace_at(owner[field], draft_sentences)
                    restored_claim = replace_at(claim["text"], claim_sentences)
                except ValueError:
                    return "text_changed"
                owner[field] = restored_draft
                self.conn.execute("UPDATE report_claims SET text = ? WHERE id = ?",
                                  (restored_claim, claim["id"]))
                self.conn.execute("UPDATE report_sections SET draft_json = ?, word_count = ?, updated_at = ? WHERE id = ?",
                                  (dumps(draft), _word_count(draft), now(), section["id"]))
                self.conn.execute(
                    "INSERT INTO report_phrase_repairs"
                    " (id, report_id, section_id, sentence_id, before, after, outcome, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'reverted_exception', ?)",
                    (new_id("rpr"), report_id, section_id, sentence_id, row["after"], row["before"], now()),
                )
                if errors():
                    raise WouldBreakAssembly
                self._event(report_id, "report_repair_reverted", section_id=section_id, sentence_id=sentence_id)
                return "reverted"
        except WouldBreakAssembly:
            return "would_break_assembly"

    def finalize(self, report_id: str, status: str) -> int | None:
        if status not in ("valid", "draft"):
            raise ValueError("A report may finalize only as valid or draft")
        with transaction(self.conn):
            report = self.report(report_id)
            if report["status"] == "valid":
                if status != "valid":
                    raise ValueError("A valid report cannot be demoted")
                return report["report_version"]
            version = None
            if status == "valid":
                total, invalid = self.conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN status <> 'valid' THEN 1 ELSE 0 END)"
                    " FROM report_sections WHERE report_id = ?", (report_id,),
                ).fetchone()
                if not total or invalid:
                    raise ValueError("All report sections must be valid before finalizing")
                version = self.conn.execute(
                    "SELECT COALESCE(MAX(report_version), 0) + 1 FROM reports WHERE research_id = ?",
                    (report["research_id"],),
                ).fetchone()[0]
            self.conn.execute(
                "UPDATE reports SET status = ?, report_version = ?, updated_at = ? WHERE id = ?",
                (status, version, now(), report_id),
            )
            self._event(report_id, "report_finalized", status=status, report_version=version)
        return version
