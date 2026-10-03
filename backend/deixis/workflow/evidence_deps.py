"""Read-only passage identity dependencies shared by reports and owner reviews."""

from __future__ import annotations

import json

# What became of a passage's file since the passage was stored (D45), over `passages p LEFT JOIN source_assets a`.
EVIDENCE_STATUS_SQL = (
    "CASE WHEN a.id IS NULL THEN 'current'"
    " WHEN a.removed_at IS NOT NULL THEN CASE a.removal_reason WHEN 'replaced' THEN 'pdf_replaced' ELSE 'pdf_removed' END"
    " WHEN p.extraction_version IS NOT a.extraction_version THEN 'text_superseded' ELSE 'current' END"
)

DEPENDENCIES_SQL = (
    "SELECT p.*, a.id AS dependency_asset_id, a.sha256 AS asset_sha256,"
    " a.removed_at, a.removal_reason, a.extraction_version AS asset_extraction_version,"
    " e.id AS passage_extraction_id, e.outcome AS passage_extraction_outcome,"
    " cur.id AS current_extraction_id, " + EVIDENCE_STATUS_SQL + " AS evidence_status"
    " FROM passages p LEFT JOIN source_assets a ON a.id = p.asset_id"
    " LEFT JOIN asset_extractions e ON e.asset_id = p.asset_id AND e.extraction_version = p.extraction_version"
    " LEFT JOIN asset_extractions cur ON cur.asset_id = p.asset_id AND cur.outcome = 'current'"
    " WHERE p.id IN (SELECT value FROM json_each(?))"
)


def passage_dependencies(conn, passage_ids) -> dict[str, dict | None]:
    ids = list(dict.fromkeys(passage_ids))
    result = dict.fromkeys(ids)
    for start in range(0, len(ids), 500):
        for row in conn.execute(DEPENDENCIES_SQL, (json.dumps(ids[start:start + 500]),)):
            result[row["id"]] = dict(row)
    return result


def latest_completed_restore(conn, sha256):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'asset_recovery_operations'").fetchone():
        return None
    row = conn.execute(
        "SELECT id, finished_at FROM asset_recovery_operations WHERE expected_sha256 = ?"
        " AND kind = 'file_restore' AND lifecycle = 'completed' AND outcome = 'file_restored'"
        " ORDER BY finished_at DESC, id DESC LIMIT 1", (sha256,),
    ).fetchone()
    return dict(row) if row else None
