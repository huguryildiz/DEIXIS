"""Synchronous report persistence on the research store's SQLite connection."""

from __future__ import annotations

import json
from typing import Any

from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.store import NotFound, Store


class ReportStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def _event(self, report_id: str, type_: str, **payload: Any) -> None:
        report = self.report(report_id)
        self.store._event(report["research_id"], type_, {"report_id": report_id, **payload}, report["run_id"])

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
        return result

    def set_plan(self, report_id: str, plan: dict[str, Any]) -> None:
        with transaction(self.conn):
            self.report(report_id)
            self.conn.execute("UPDATE reports SET plan_json = ?, updated_at = ? WHERE id = ?", (dumps(plan), now(), report_id))
            self._event(report_id, "report_plan_saved")

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
            if self.conn.execute("SELECT 1 FROM report_claims WHERE report_section_id = ? LIMIT 1", (report_section_id,)).fetchone():
                raise ValueError("Claims for this section have already been saved")
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

    def save_gaps(self, report_id: str, gaps: list[dict[str, Any]]) -> None:
        with transaction(self.conn):
            self.report(report_id)
            for gap in gaps:
                basis = gap.get("basis", {key: gap[key] for key in (
                    "basis_claim_keys", "basis_passage_ids", "basis_cell_ids", "nearest_match") if key in gap})
                self.conn.execute(
                    "INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json,"
                    " kill_search_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("rgp"), report_id, gap["gap_id"], gap["kind"], gap["text"], dumps(basis),
                     dumps(gap["provenance"]), gap.get("kill_search_status", "not_run"), now()),
                )
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
