"""Named read operations over the main library, with no exposed writable store."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from deixis.storage.db import transaction
from .store import NotFound

if TYPE_CHECKING:
    from deixis.workflow.store import Store
    from deixis.workflow.report.store import ReportStore


class ReviewReader:
    def __init__(self, store: Store, reports: ReportStore):
        self._store = store
        self._reports = reports
        self._conn = store.conn

    @contextmanager
    def consistent_read(self):
        # The existing transaction helper reserves the read boundary with BEGIN IMMEDIATE.
        # No data is written; another connection cannot change content between marker reads.
        with transaction(self._conn):
            yield self

    def research(self, research_id):
        return self._store.research(research_id)

    def scope(self, research_id, revision):
        return self._store.scope(research_id, revision)

    def answer(self, answer_id):
        row = self._conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
        if row is None:
            raise NotFound(answer_id)
        return dict(row)

    def latest_answer(self, research_id):
        row = self._conn.execute(
            "SELECT id FROM answers WHERE research_id = ? AND status = 'structurally_valid'"
            " ORDER BY report_version DESC, created_at DESC, id DESC LIMIT 1", (research_id,),
        ).fetchone()
        return row[0] if row else None

    def answer_claims(self, answer_id):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM claims WHERE answer_id = ? ORDER BY ordinal, id", (answer_id,),
        )]

    def answer_links(self, answer_id):
        return [dict(r) for r in self._conn.execute(
            "SELECT e.* FROM evidence_links e JOIN claims c ON c.id = e.claim_id"
            " WHERE c.answer_id = ? ORDER BY c.ordinal, e.rowid", (answer_id,),
        )]

    def report(self, report_id):
        return self._reports.report(report_id)

    def latest_report_version(self, research_id, exclude_report_id=None):
        return self._conn.execute(
            "SELECT MAX(report_version) FROM reports WHERE research_id = ? AND status = 'valid'"
            " AND (? IS NULL OR id <> ?)", (research_id, exclude_report_id, exclude_report_id),
        ).fetchone()[0]

    def report_sections(self, report_id):
        return self._reports.sections(report_id)

    def report_claims(self, report_id):
        return [dict(r) for r in self._conn.execute(
            "SELECT c.*, s.section_id, v.text AS revision_text FROM report_claims c"
            " JOIN report_sections s ON s.id = c.report_section_id"
            " LEFT JOIN report_claim_revisions v ON v.id = c.current_revision_id"
            " WHERE s.report_id = ? ORDER BY s.ordinal, c.ordinal, c.id", (report_id,),
        )]

    def report_links(self, report_id):
        return self._reports.effective_links(report_id)

    def report_claim_revisions(self, claim_id):
        return self._reports.claim_revisions(claim_id)

    def report_original_links(self, claim_id):
        return self._reports.original_links(claim_id)

    def report_snapshot(self, report_id):
        row = self._conn.execute("SELECT * FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise NotFound(f"snapshot for {report_id}")
        return dict(row)

    def source(self, source_id):
        return self._store.source(source_id)

    def source_access(self, source_id):
        if self._store.has_pdf_text(source_id):
            return "pdf_available"
        return "abstract" if self._conn.execute(
            "SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (source_id,),
        ).fetchone() else "metadata"

    def passage(self, passage_id):
        return self._store.passage(passage_id)

    def included_sources(self, research_id):
        return self._store.included_sources(research_id)

    def selection_stamp(self, research_id):
        return self._conn.execute("SELECT MAX(updated_at) FROM selections WHERE research_id = ?", (research_id,)).fetchone()[0]

    def included_rows(self, research_id, table_id):
        # This is report.snapshot.included_table_rows' active-row/included-source boundary.
        included = set(self.included_sources(research_id))
        return [r[0] for r in self._conn.execute(
            "SELECT t.source_version_id FROM table_rows t JOIN source_versions v ON v.id = t.source_version_id"
            " JOIN evidence_tables et ON et.id = t.table_id"
            " WHERE t.table_id = ? AND t.removed_at IS NULL AND EXISTS"
            " (SELECT 1 FROM corpus_memberships m WHERE m.research_id = et.research_id"
            " AND m.source_version_id = t.source_version_id AND m.removed_at IS NULL)"
            " ORDER BY t.created_at, v.title", (table_id,),
        ) if r[0] in included]

    def cells(self, cell_ids):
        return {cid: dict(row) for cid in cell_ids if (row := self._conn.execute(
            "SELECT id, current_revision_id FROM evidence_cells WHERE id = ?", (cid,),
        ).fetchone()) is not None}

    def columns(self, column_ids):
        return {cid: dict(row) for cid in column_ids if (row := self._conn.execute(
            "SELECT id, current_revision FROM table_columns WHERE id = ?", (cid,),
        ).fetchone()) is not None}

    def evidence_dependency(self, passage_id):
        row = self._conn.execute(
            "SELECT p.*, a.id AS dependency_asset_id, a.sha256 AS asset_sha256,"
            " a.removed_at, a.removal_reason, a.extraction_version AS asset_extraction_version,"
            " e.id AS passage_extraction_id, cur.id AS current_extraction_id_at_snapshot"
            " FROM passages p LEFT JOIN source_assets a ON a.id = p.asset_id"
            " LEFT JOIN asset_extractions e ON e.asset_id = p.asset_id AND e.extraction_version = p.extraction_version"
            " LEFT JOIN asset_extractions cur ON cur.asset_id = p.asset_id AND cur.outcome = 'current'"
            " WHERE p.id = ?", (passage_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # EVIDENCE_STATUS_SQL's rule, without importing the writable main store.
        result["evidence_status"] = (
            "current" if result["dependency_asset_id"] is None else
            ("pdf_replaced" if result["removal_reason"] == "replaced" else "pdf_removed") if result["removed_at"] is not None else
            "text_superseded" if result["extraction_version"] != result["asset_extraction_version"] else "current"
        )
        return result

    def evidence_exists(self, asset_id, extraction_id):
        return ((asset_id is None or self._conn.execute("SELECT 1 FROM source_assets WHERE id = ?", (asset_id,)).fetchone() is not None)
                and (extraction_id is None or self._conn.execute("SELECT 1 FROM asset_extractions WHERE id = ?", (extraction_id,)).fetchone() is not None))
