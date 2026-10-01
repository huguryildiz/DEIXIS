"""Dependency manifest and persisted results for model-free working-text checks."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deixis.domain import contracts


CHECKER_VERSION = "edit-check-1"
NOT_CHECKED = ["semantic_support", "numbers_written_as_words", "passages"]
ABSENT = {"absent": True}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: str | None) -> str | dict:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else dict(ABSENT)


def fingerprint(dependencies: dict) -> str:
    return hashlib.sha256(canonical(dependencies).encode("utf-8")).hexdigest()


def manifest(store, reports, report_id: str) -> dict:
    """Cover the inputs read by current checks, including missing records and section ownership.

    Selected section inputs follow assembly._section_payload's latest-row rule;
    equation links may also read older inputs by id. Both dependencies are recorded.
    """
    from deixis.workflow.report.assembly import _claims

    conn = store.conn
    report = reports.report(report_id)
    snapshot = conn.execute("SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()
    sections = []
    for section in conn.execute("SELECT * FROM report_sections WHERE report_id = ? ORDER BY ordinal, created_at",
                                (report_id,)):
        selected = conn.execute("SELECT rowid AS row_id, id, payload_json FROM step_inputs WHERE step_id = ?"
                                " ORDER BY rowid DESC LIMIT 1", (section["step_id"],)).fetchone()
        sections.append({key: section[key] for key in ("id", "section_id", "ordinal", "step_id", "word_count")} | {
            "draft_digest": _digest(section["draft_json"]),
            "validation_digest": _digest(section["validation_json"]),
            "selected_step_input": {"row_id": selected["row_id"], "id": selected["id"],
                                    "payload_digest": _digest(selected["payload_json"])} if selected else dict(ABSENT),
        })
    claims = []
    passage_ids = set()
    for claim in _claims(store, report_id, current=True):
        claims.append({key: claim[key] for key in (
            "id", "report_section_id", "section_id", "claim_key", "ordinal", "paragraph", "support_type",
            "table_ref", "equation_ref", "axis_id", "count_json", "equation_origin_json", "current_revision_id",
        )} | {"text_digest": _digest(claim["text"]), "refs": [dict(row) for row in conn.execute(
            "SELECT * FROM report_claim_refs WHERE claim_id = ? ORDER BY ref_kind, ref_value", (claim["id"],))]})
        try:
            origin = json.loads(claim["equation_origin_json"] or "null")
        except ValueError:
            origin = None
        if isinstance(origin, dict) and isinstance(origin.get("passage_id"), str):
            passage_ids.add(origin["passage_id"])
    links = reports.effective_links(report_id)
    passage_ids.update(link["passage_id"] for link in links if link["passage_id"] is not None)
    gaps = [dict(row) for row in conn.execute("SELECT id, gap_id, kind, text, basis_json, provenance_json"
                                            " FROM report_gaps WHERE report_id = ? ORDER BY gap_id, id",
                                            (report_id,))]
    for gap in gaps:
        try:
            basis = json.loads(gap["basis_json"])
        except ValueError:
            basis = None
        if isinstance(basis, dict) and isinstance(basis.get("basis_passage_ids"), list):
            passage_ids.update(pid for pid in basis["basis_passage_ids"] if isinstance(pid, str))
    passages = []
    for passage_id in sorted(passage_ids):
        row = conn.execute("SELECT id, source_version_id, kind, text_source, text FROM passages WHERE id = ?",
                           (passage_id,)).fetchone()
        passages.append({"id": passage_id, **ABSENT} if row is None else {
            key: row[key] for key in ("id", "source_version_id", "kind", "text_source")
        } | {"text_digest": _digest(row["text"])})
    inputs = []
    for input_id in sorted({link["step_input_id"] for link in links}):
        row = conn.execute("SELECT step_id, payload_json FROM step_inputs WHERE id = ?", (input_id,)).fetchone()
        inputs.append({"id": input_id, **ABSENT} if row is None else {
            "id": input_id, "step_id": row["step_id"], "payload_digest": _digest(row["payload_json"]),
        })
    sources = []
    for source_id in sorted({link["source_version_id"] for link in links}):
        row = conn.execute("SELECT v.title, w.source_key FROM source_versions v LEFT JOIN works w ON w.id = v.work_id"
                           " WHERE v.id = ?", (source_id,)).fetchone()
        sources.append({"id": source_id, **ABSENT} if row is None else {"id": source_id, **dict(row)})
    latest_repairs = {}
    for row in conn.execute("SELECT id, section_id, sentence_id, before, after, outcome FROM report_phrase_repairs"
                            " WHERE report_id = ? ORDER BY rowid", (report_id,)):
        latest_repairs[(row["section_id"], row["sentence_id"])] = dict(row)
    return {
        "checker_version": CHECKER_VERSION,
        "report": {"language": report["language"], "plan": report["plan"],
                   "scope_language_fallback": store.scope(report["research_id"], report["scope_revision"]).get("language_hint")},
        "snapshot_digest": _digest(snapshot["snapshot_json"]) if snapshot else dict(ABSENT),
        "sections": sections, "claims": claims, "effective_links": links,
        "passages": passages, "link_step_inputs": inputs, "sources": sources, "gaps": gaps,
        "phrase_repairs": [latest_repairs[key] for key in sorted(latest_repairs)],
        "phrasebank_digest": _digest(contracts._phrasebank_text()),
    }


def shape_result(items: list[dict], skipped: list[dict], rules_run: list[str], edited_claims: int) -> dict:
    # Several rules can encounter the same malformed record; report it once.
    unique = {canonical(item): item for item in items}
    items = sorted(({**item, "severity": "warning" if item["detail"].startswith("WARNING:") else "error"}
                    for item in unique.values()), key=lambda item: (item["section_id"], item["rule"], item["detail"]))
    skipped = sorted(skipped, key=lambda item: (item["section_id"], item["claim_key"], item["rule"], item["reason"]))
    return {
        "version": 1, "checker_version": CHECKER_VERSION, "items": items, "rules_run": rules_run, "skipped": skipped,
        "counts": {"errors": sum(item["severity"] == "error" for item in items),
                   "warnings": sum(item["severity"] == "warning" for item in items),
                   "skipped": len(skipped), "edited_claims": edited_claims}, "not_checked": list(NOT_CHECKED),
    }


def record(row) -> dict:
    return {key: row[key] for key in ("id", "report_id", "checker_version", "input_fingerprint", "created_at")} | {
        "result": json.loads(row["result_json"]),
    }


def state(store, reports, report_id: str) -> dict | None:
    latest = store.conn.execute("SELECT * FROM report_edit_checks WHERE report_id = ? ORDER BY rowid DESC LIMIT 1",
                                (report_id,)).fetchone()
    if latest is None:
        return None
    present = fingerprint(manifest(store, reports, report_id))
    row = store.conn.execute("SELECT * FROM report_edit_checks WHERE report_id = ? AND input_fingerprint = ?",
                             (report_id, present)).fetchone()
    current = row is not None
    row = row if current else latest
    result = json.loads(row["result_json"])
    return {key: row[key] for key in ("id", "created_at", "checker_version")} | {
        "current": current, **result["counts"], "items": result["items"], "skipped_rules": result["skipped"],
        "rules_run": result["rules_run"], "not_checked": result["not_checked"],
    }
