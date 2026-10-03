"""Read-only recovery capability and bounded, closed history projections."""

from pathlib import Path

from deixis.documents import pdf
from deixis.workflow import text_retry


def text_recovery(store, asset, source_version_id: str, papers_dir: Path | None) -> dict:
    current = store.conn.execute(
        "SELECT id, status, error, extractor_profile, extraction_version, diagnostic_only"
        " FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
        (asset["id"],)).fetchone()
    latest = store.conn.execute(
        "SELECT id FROM asset_recovery_operations WHERE asset_id = ? AND kind = 'text_retry'"
        " ORDER BY created_at DESC, id DESC LIMIT 1", (asset["id"],)).fetchone()
    reason, file_checked = None, False
    if current is None:
        reason = "no_current_extraction"
    elif current["status"] == "succeeded":
        reason = "already_current"
    elif current["status"] == "pending":
        reason = "pending"
    elif current["status"] == "failed" and current["error"] == pdf.ERROR_PASSWORD:
        reason = "password_protected"
    elif store.conn.execute(
        "SELECT 1 FROM asset_recovery_operations WHERE asset_id = ? AND kind = 'text_retry'"
        " AND lifecycle = 'running'", (asset["id"],)).fetchone():
        reason = "operation_running"
    elif store._asset_run_active(source_version_id):
        reason = "run_active"
    elif papers_dir is not None:
        file_checked = True
        try:
            text_retry.precheck(papers_dir, asset["storage_path"])
        except text_retry.FileMissing:
            reason = "file_missing"
    return {"current_extraction_id": current["id"] if current else None,
            "status": current["status"] if current else asset["extraction_status"],
            "extractor_profile": current["extractor_profile"] if current else None,
            "extraction_version": current["extraction_version"] if current else asset["extraction_version"],
            "diagnostic_only": bool(current["diagnostic_only"]) if current else False,
            "can_retry_text": reason is None, "reason": reason, "file_checked": file_checked,
            "latest_operation": store.text_retry_view(latest["id"]) if latest else None,
            "latest_file_restore": store.latest_file_restore(asset["sha256"])}


def recovery_history(store, asset) -> dict:
    retries = store.conn.execute(
        "SELECT id FROM asset_recovery_operations WHERE asset_id = ? AND kind = 'text_retry'"
        " ORDER BY created_at DESC, id DESC LIMIT 21", (asset["id"],)).fetchall()
    restores = store.conn.execute(
        "SELECT id FROM asset_recovery_operations WHERE expected_sha256 = ? AND kind = 'file_restore'"
        " ORDER BY created_at DESC, id DESC LIMIT 21", (asset["sha256"],)).fetchall()
    entries = []
    for row in retries[:20]:
        candidate = store.conn.execute(
            "SELECT id AS extraction_id, extraction_version, extractor_profile, status, error, page_count,"
            " outcome, decision_code, diagnostic_only FROM asset_extractions WHERE recovery_operation_id = ?",
            (row["id"],)).fetchone()
        details = dict(candidate) if candidate else None
        if details is not None:
            details["diagnostic_only"] = bool(details["diagnostic_only"])
        entries.append({"operation": store.text_retry_view(row["id"]), "candidate": details})
    return {"text_retries": entries, "file_restores": [store.file_restore_view(row["id"]) for row in restores[:20]],
            "text_retries_truncated": len(retries) > 20, "file_restores_truncated": len(restores) > 20}
