"""The Method box under an `sw` answer: how the answer was reached, read from stored rows only.

No model is called and nothing is written. The search part reuses `prisma_s` (`_groups`, `_planned_queries`) so the
box and the PRISMA-S export cannot disagree about which searches ran. Counts stay separate (AGENTS.md): works found,
read at abstract, full text tried, included, given to the model and cited answer different questions. What the stored
rows do not say is returned as `None` or listed in `not_measured`, never filled in.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.workflow import prisma_s, queue
from deixis.workflow.store import Store

# `report_pipeline.start` keys its table `{research}:study_table:answer:{answer}:table` (`TableStore._key`).
STUDY_TABLE_KEY = "{research_id}:study_table:answer:{answer_id}:table"
NOT_MEASURED = (
    "A citation was located in its passage; whether the passage supports the claim was not checked by a person.",
    "Search recall was not measured: works the queries never returned are unknown.",
)


class UnknownAnswer(Exception):
    """No answer of this research has that id; the API answers 404."""


def method_summary(store: Store, research_id: str, answer_id: str) -> dict[str, Any]:
    conn = store.conn
    answer = conn.execute("SELECT * FROM answers WHERE id = ? AND research_id = ?", (answer_id, research_id)).fetchone()
    if answer is None:
        raise UnknownAnswer(answer_id)
    revision = answer["scope_revision"]
    with queue._snapshot(conn):
        return {
            "answer_id": answer_id, "scope_revision": revision,
            "search": _search(store, research_id, revision, answer["created_at"]),
            "selection": _selection(store, research_id, answer, revision),
            "extraction": _extraction(store, research_id, answer_id),
            "limitations": _limitations(store, answer),
            "evidence_base": _evidence_base(store, answer_id),
            "not_measured": list(NOT_MEASURED),
        }


def _protocol(store: Store, research_id: str, revision: int, until: str) -> dict[str, Any] | None:
    """The protocol in force when the answer was written: the latest one stored at or before it."""
    row = store.conn.execute(
        "SELECT id, body_json, body_sha256, created_at FROM protocol_records WHERE research_id = ? AND scope_revision = ?"
        " AND created_at <= ? ORDER BY protocol_revision DESC LIMIT 1", (research_id, revision, until)).fetchone()
    return dict(row) | {"body": json.loads(row["body_json"])} if row else None


def _search(store: Store, research_id: str, revision: int, until: str) -> dict[str, Any]:
    protocol = _protocol(store, research_id, revision, until)
    groups = prisma_s._groups(store, research_id, revision, until)
    planned = ((protocol or {}).get("body") or {}).get("compiled_queries") or []
    keyword = [g for g in groups if g["kind"] == "keyword"]
    chain = [g for g in groups if g["kind"] == "chain"]
    sent = {(g["provider"], g["query_text"]) for g in keyword}
    return {
        "queries": [{"provider": g["provider"], "query": g["query_text"], "records_read": g["rows_returned"],
                     "provider_total": g["provider_total"], "date": g["first_retrieved_at"],
                     "complete": g["ended_complete"], "origin": g["origin"]} for g in keyword],
        "records_read": sum(g["rows_returned"] for g in keyword),
        "planned": len(planned),
        "planned_not_sent": sum((q.get("provider_id"), q.get("query_text")) not in sent for q in planned),
        "chaining": {"ran": bool(chain), "requests": len(chain), "records_read": sum(g["rows_returned"] for g in chain)},
    }


def _selection(store: Store, research_id: str, answer: Any, revision: int) -> dict[str, Any]:
    conn = store.conn
    until = answer["created_at"]
    step = store.existing_step(answer["run_id"], "answer_start_snapshot")
    snapshot = step["output"] if step and step["status"] == "succeeded" and step["output"] else None
    flow = (snapshot or {}).get("flow")
    body = ((_protocol(store, research_id, revision, until) or {}).get("body")) or {}
    approval = body.get("approval") or {}

    def works(sql: str, *args: Any) -> int:
        return conn.execute(sql, (research_id, revision, until, *args)).fetchone()[0]

    # Everything below counts rows stored before this answer, so a later run never changes an earlier answer's box.
    screened = works("SELECT COUNT(DISTINCT v.work_id) FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
                     " WHERE d.research_id = ? AND d.scope_revision = ? AND d.created_at <= ? AND d.stage = 'abstract'")
    proposals = "SELECT COUNT(DISTINCT v.work_id) FROM model_proposals p JOIN run_steps s ON s.id = p.step_id" \
                " JOIN runs r ON r.id = s.run_id JOIN source_versions v ON v.id = p.source_version_id" \
                " WHERE p.research_id = ? AND r.scope_revision = ? AND p.created_at <= ? AND p.stage = ?"
    attempts = conn.execute(
        "SELECT COUNT(DISTINCT s.operation_key) FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND r.scope_revision = ? AND s.operation_key LIKE 'fulltext_work:%' AND s.status IN ('succeeded', 'failed')"
        " AND s.finished_at <= ?", (research_id, revision, until)).fetchone()[0]
    person = works("SELECT COUNT(DISTINCT source_version_id) FROM stage_decisions WHERE research_id = ?"
                   " AND scope_revision = ? AND created_at <= ? AND decided_by = 'human'")
    return {
        "snapshot": flow is not None,
        "works_found": flow["works"] if flow else None,
        "screened": screened,
        "abstract_read": works(proposals, "abstract"),
        "full_text_attempted": attempts,
        "full_text_read": works(proposals, "fulltext"),
        "person_decisions": person,
        "included": flow["five"]["included"] if flow else None,
        "not_met": flow["five"]["not_met"] if flow else None,
        "waiting_for_pdf": flow["five"]["waiting_for_pdf"] if flow else None,
        "not_read": flow["five"]["not_read"] if flow else None,
        "criterion": body.get("inclusion_criterion"),
        "vocabulary_review": {"reviewed_by_person": approval["approved_by"] == "user" if approval.get("approved_by") else None,
                              "approved_by": approval.get("approved_by"), "edited": approval.get("edited")},
    }


def _extraction(store: Store, research_id: str, answer_id: str) -> dict[str, Any]:
    conn = store.conn
    table = conn.execute("SELECT id, trashed_at FROM evidence_tables WHERE idempotency_key = ?",
                         (STUDY_TABLE_KEY.format(research_id=research_id, answer_id=answer_id),)).fetchone()
    if table is None or table["trashed_at"]:
        return {"table": False, "columns": [], "columns_accepted_automatically": 0}
    columns = [dict(row) for row in conn.execute(
        "SELECT r.name, k.accepted_by FROM table_columns k JOIN column_revisions r"
        " ON r.column_id = k.id AND r.revision = k.current_revision WHERE k.table_id = ? AND k.removed_at IS NULL"
        " ORDER BY k.position", (table["id"],))]
    return {"table": True, "columns": [c["name"] for c in columns],
            "columns_accepted_automatically": sum(c["accepted_by"] == "automatic" for c in columns)}


def _limitations(store: Store, answer: Any) -> dict[str, Any]:
    conn = store.conn
    draft = json.loads(answer["draft_json"]) if answer["draft_json"] else {}
    limits = draft.get("limitations") or [] if answer["status"] == "structurally_valid" else []
    given = store.step_input_payload(answer["step_input_id"]) if answer["step_input_id"] else None
    access = None
    if given:
        ids = [p["passage_id"] for p in given.get("passages") or []]
        kinds: dict[str, set[str]] = {s["source_id"]: set() for s in given.get("sources") or []}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for row in conn.execute(f"SELECT source_version_id, kind FROM passages WHERE id IN ({','.join('?' * len(chunk))})",
                                    tuple(chunk)):
                kinds.setdefault(row[0], set()).add(row[1])
        full = sum(1 for k in kinds.values() if k - {"abstract"})
        abstract = sum(1 for k in kinds.values() if k and not (k - {"abstract"}))
        access = {"given": len(kinds), "full_text": full, "abstract_only": abstract,
                  "no_passage": len(kinds) - full - abstract}
    return {"access": access, "answer_limitations": len(limits),
            "access_limitations": sum(1 for item in limits if item.get("kind") == "access")}


def _evidence_base(store: Store, answer_id: str) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT v.work_id, v.year FROM evidence_links l JOIN claims c ON c.id = l.claim_id"
        " JOIN source_versions v ON v.id = l.source_version_id WHERE c.answer_id = ?", (answer_id,)).fetchall()
    works = {r["work_id"] for r in rows}
    years = [r["year"] for r in rows if r["year"] is not None]
    return {"cited_sources": len(works), "year_min": min(years) if years else None,
            "year_max": max(years) if years else None}
