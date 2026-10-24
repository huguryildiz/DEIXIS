"""Report passage identity comparison; semantic support is never assessed here."""

from __future__ import annotations

import json

from deixis.workflow.evidence_deps import latest_completed_restore, passage_dependencies
from deixis.workflow.report.store import ReportStore


def passage_freshness(reports: ReportStore, report_id) -> dict:
    conn = reports.conn
    uses: dict[str, set[tuple[str, str]]] = {}
    unreadable: set[tuple[str, str]] = set()

    def record(pid, kind, ref):
        if pid is None:
            return
        if not isinstance(pid, str):
            raise ValueError("passage id is not a string")
        uses.setdefault(pid, set()).add((kind, ref))

    def read(raw, kind, ref, consume):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            consume(value, kind, ref)
        except (ValueError, TypeError, KeyError, RecursionError):
            unreadable.add((kind, ref))

    def list_ids(value, kind, ref):
        if not isinstance(value, list):
            raise ValueError("passage ids are not a list")
        for pid in value:
            record(pid, kind, ref)

    def cells(value, kind, ref):
        if not isinstance(value["cells"], list):
            raise ValueError("cells are not a list")
        for cell in value["cells"]:
            if not isinstance(cell, dict) or not isinstance(cell["cell_id"], str) or not isinstance(cell["evidence"], list):
                raise ValueError("unreadable cell")
            for item in cell["evidence"]:
                if not isinstance(item, dict):
                    raise ValueError("unreadable evidence")
                record(item["passage_id"], kind, cell["cell_id"])

    def basis(value, kind, ref):
        # Older readable bases can omit passage references altogether.
        list_ids(value.get("basis_passage_ids", []), kind, ref)

    def step_input(value, kind, ref):
        passages = value.get("passages", [])
        allowlist = value.get("allowlist", {})
        if not isinstance(passages, list) or not isinstance(allowlist, dict):
            raise ValueError("unreadable model input")
        for item in passages:
            if not isinstance(item, dict):
                raise ValueError("unreadable passage")
            record(item["passage_id"], kind, ref)
        list_ids(allowlist.get("passage_ids", []), kind, ref)

    # These read methods own the effective/restorable citation policy.
    effective = reports.effective_links(report_id)
    removed = reports.removed_links(report_id)
    links = effective + removed
    for kind, rows in (("citation", effective), ("restorable_citation", removed)):
        for link in rows:
            record(link["passage_id"], kind, link["id"])
    for row in conn.execute("SELECT report_id AS id, snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)):
        read(row["snapshot_json"], "snapshot_cell", row["id"], cells)
    for row in conn.execute("SELECT id, basis_json FROM report_gaps WHERE report_id = ?", (report_id,)):
        read(row["basis_json"], "gap_basis", row["id"], basis)
    input_ids = {row["step_input_id"] for row in links}
    for section in conn.execute("SELECT step_id FROM report_sections WHERE report_id = ?", (report_id,)):
        row = conn.execute("SELECT id FROM step_inputs WHERE step_id = ? ORDER BY rowid DESC LIMIT 1",
                           (section["step_id"],)).fetchone()
        if row:
            input_ids.add(row["id"])
    for iid in sorted(input_ids):
        row = conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (iid,)).fetchone()
        if row is None:
            unreadable.add(("section_input", iid))
        else:
            read(row["payload_json"], "section_input", iid, step_input)
    for row in conn.execute(
        "SELECT c.id, c.equation_origin_json FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? AND c.equation_origin_json IS NOT NULL", (report_id,),
    ):
        read(row["equation_origin_json"], "equation_origin", row["id"],
             lambda value, kind, ref: record(value.get("passage_id"), kind, ref))

    def used_by(entries):
        return [{"kind": kind, "ref": ref} for kind, ref in sorted(entries)]

    affected, unresolved, restored = [], [], []
    for pid, dep in sorted(passage_dependencies(conn, sorted(uses)).items()):
        if dep is None:
            unresolved.append({"passage_id": pid, "reason": "passage_missing", "used_by": used_by(uses[pid])})
            continue
        if dep["evidence_status"] != "current":
            affected.append({"passage_id": pid, **{key: dep[key] for key in (
                "source_version_id", "evidence_status", "passage_extraction_id", "current_extraction_id")},
                "used_by": used_by(uses[pid])})
        if dep["passage_extraction_id"]:
            occurrence = conn.execute("SELECT created_at FROM asset_extractions WHERE id = ?",
                                      (dep["passage_extraction_id"],)).fetchone()
            repair = latest_completed_restore(conn, dep["asset_sha256"])
            if repair and repair["finished_at"] > occurrence["created_at"]:
                restored.append(pid)
    if unreadable:
        unresolved.insert(0, {"passage_id": None, "reason": "unreadable_record", "used_by": used_by(unreadable)})
    return {"compared": "passage_identity", "semantic_support": "not_checked", "dependencies": sorted(uses),
            "affected": affected, "unresolved": unresolved, "file_restored_after": restored}
