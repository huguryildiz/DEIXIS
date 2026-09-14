"""Read models returned by the API. Every value comes from stored records."""

from __future__ import annotations

import json
from typing import Any

from deixis.domain.rules import result_applicability
from deixis.workflow.store import Store


def _json(value: str | None) -> Any:
    return json.loads(value) if value else None


def research_view(store: Store, research_id: str) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    scope = store.scope(research_id)

    runs = []
    for row in conn.execute("SELECT id FROM runs WHERE research_id = ? ORDER BY created_at DESC LIMIT 10", (research_id,)):
        run = store.run(row["id"])
        run["steps"] = store.run_steps(run["id"])
        runs.append(run)

    search_runs = [
        {**{k: r[k] for k in ("id", "run_id", "scope_revision", "provider", "query_text", "access_mode", "status", "result_count", "provider_total", "page_limit", "retrieved_at")},
         "error": _json(r["error_json"])}
        for r in conn.execute("SELECT * FROM search_runs WHERE research_id = ? ORDER BY retrieved_at", (research_id,))
    ]

    answers = []
    cited_sources: set[str] = set()
    for a in conn.execute("SELECT * FROM answers WHERE research_id = ? ORDER BY created_at DESC LIMIT 10", (research_id,)):
        draft = _json(a["draft_json"])
        claims = []
        for c in conn.execute("SELECT * FROM claims WHERE answer_id = ? ORDER BY ordinal", (a["id"],)):
            evidence = [
                {"passage_id": e["passage_id"], "source_version_id": e["source_version_id"], "kind": e["kind"],
                 "physical_page": e["physical_page"], "printed_label": e["printed_label"],
                 "reading_depth": "abstract" if e["kind"] == "abstract" else "selected_sections", "title": e["title"]}
                for e in conn.execute(
                    "SELECT l.passage_id, l.source_version_id, p.kind, p.physical_page, p.printed_label, s.title FROM evidence_links l"
                    " JOIN passages p ON p.id = l.passage_id JOIN source_versions s ON s.id = l.source_version_id"
                    " WHERE l.claim_id = ? ORDER BY l.rowid", (c["id"],)
                )
            ]
            if not answers:
                cited_sources.update(e["source_version_id"] for e in evidence)
            claims.append({"id": c["id"], "label": c["label"], "text": c["text"], "support_type": c["support_type"],
                           "semantic_review": c["semantic_review"], "evidence": evidence})
        session = conn.execute(
            "SELECT connection, requested_model, resolved_model, token_usage_json FROM model_sessions WHERE step_input_id = ?",
            (a["step_input_id"],),
        ).fetchone() if a["step_input_id"] else None
        given = store.step_input_payload(a["step_input_id"]) if a["step_input_id"] else None
        validation = _json(a["validation_json"]) or {}
        answers.append({
            "id": a["id"], "run_id": a["run_id"], "status": a["status"], "scope_revision": a["scope_revision"],
            "applicability": result_applicability(a["scope_revision"], research["current_scope_revision"],
                                                  a["selection_revision"], research["selection_revision"]),
            "answer_language": a["answer_language"], "created_at": a["created_at"], "claims": claims,
            "limitations": (draft or {}).get("limitations", []) if a["status"] == "structurally_valid" else [],
            "unanswered_aspects": (draft or {}).get("unanswered_aspects", []) if a["status"] == "structurally_valid" else [],
            "capability_notice": (draft or {}).get("capability_notice") if a["status"] == "structurally_valid" else None,
            "clarification": draft if a["status"] == "clarification" else None,
            "unverified_draft": draft if a["status"] == "unverified_draft" else None,
            "validation": validation,
            "model": {"connection": session["connection"], "requested_model": session["requested_model"],
                      "resolved_model": session["resolved_model"], "token_usage": _json(session["token_usage_json"])} if session else None,
            "inputs_given": {"sources": len(given["sources"]), "passages": len(given["passages"]),
                             "source_ids": [s["source_id"] for s in given["sources"]]} if given else None,
        })
    sources = []
    for row in conn.execute(
        "SELECT m.added_by, s.*, sel.state, sel.origin AS selection_origin, sel.version AS selection_version, sel.proposal,"
        " sel.proposal_reason, sel.proposal_basis, sel.user_reason, c.id AS candidate_id, c.rank, c.scope_revision AS found_in_revision"
        " FROM corpus_memberships m JOIN source_versions s ON s.id = m.source_version_id"
        " JOIN selections sel ON sel.research_id = m.research_id AND sel.source_version_id = m.source_version_id"
        " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
        " WHERE m.research_id = ? ORDER BY m.created_at, c.rank", (research_id,)
    ):
        svid = row["id"]
        assets = [dict(r) for r in conn.execute(
            "SELECT id, extraction_status, page_count, origin, byte_size FROM source_assets WHERE source_version_id = ?", (svid,)
        )]
        abstract = conn.execute(
            "SELECT id, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract' LIMIT 1", (svid,)
        ).fetchone()
        fetch = conn.execute(
            "SELECT s.status, s.error_code FROM run_steps s JOIN runs r ON r.id = s.run_id"
            " WHERE r.research_id = ? AND s.operation_key = ? ORDER BY s.started_at DESC LIMIT 1", (research_id, f"fetch:{svid}")
        ).fetchone()
        sources.append({
            "source_version_id": svid, "work_id": row["work_id"], "title": row["title"], "authors": json.loads(row["authors_json"]),
            "year": row["year"], "venue": row["venue"], "doi": row["doi"], "landing_url": row["landing_url"],
            "version_label": row["version_label"], "publication_type": row["publication_type"], "origin": row["origin"],
            "added_by": row["added_by"], "rank": row["rank"],
            # "other_version": another version of a found record (e.g. its submitted manuscript), stored separately.
            "version_role": "other_version" if row["origin"] == "provider" and row["candidate_id"] is None else "record",
            # A search result keeps the question revision it was found for; attached files belong to no revision.
            "found_in_revision": row["found_in_revision"],
            "applicability": "current" if row["found_in_revision"] is None
            else result_applicability(row["found_in_revision"], research["current_scope_revision"]),
            "access": {"abstract_passage_id": abstract["id"] if abstract else None,
                       "abstract_origin": abstract["abstract_origin"] if abstract else None,
                       "oa_pdf_url": row["oa_pdf_url"], "oa_pdf_version": row["oa_pdf_version"], "assets": assets,
                       "fetch": dict(fetch) if fetch else None},
            "selection": {"state": row["state"], "origin": row["selection_origin"], "version": row["selection_version"],
                          "proposal": row["proposal"], "proposal_reason": row["proposal_reason"],
                          "proposal_basis": row["proposal_basis"], "user_reason": row["user_reason"]},
            "cited_in_latest_answer": svid in cited_sources,
        })

    # Other versions follow the record of their work and share its question revision.
    ordered: list[dict[str, Any]] = []
    for record in (s for s in sources if s["version_role"] == "record"):
        ordered.append(record)
        ordered += [s | {"found_in_revision": record["found_in_revision"], "applicability": record["applicability"]}
                    for s in sources if s["version_role"] == "other_version" and s["work_id"] == record["work_id"]]
    placed = {s["source_version_id"] for s in ordered}
    sources = ordered + [s for s in sources if s["source_version_id"] not in placed]

    # Versions of one work are not independent: unique, included, given and cited count works.
    work_of = {s["source_version_id"]: s["work_id"] for s in sources}

    def works(ids: Any) -> int:
        return len({work_of.get(i, i) for i in ids})

    latest_given = next((a["inputs_given"] for a in answers if a["inputs_given"]), None)
    counts = {
        "found": sum(s["result_count"] for s in search_runs),
        "unique": works(work_of),
        "included": works(s["source_version_id"] for s in sources if s["selection"]["state"] == "included"),
        "excluded": sum(s["selection"]["state"] == "excluded" for s in sources),
        "pending": sum(s["selection"]["state"] == "pending" for s in sources),
        "inspected": works(latest_given["source_ids"]) if latest_given else 0,
        "cited": works(cited_sources),
    }
    last_event = conn.execute("SELECT MAX(id) FROM events WHERE research_id = ?", (research_id,)).fetchone()[0] or 0
    return {"research": research, "scope": scope, "runs": runs, "search_runs": search_runs, "sources": sources,
            "answers": answers, "counts": counts, "last_event_id": last_event}


def passage_view(store: Store, research_id: str, passage_id: str) -> dict[str, Any] | None:
    passage = store.passage(passage_id)
    if not store.is_member(research_id, passage["source_version_id"]):
        return None
    source = store.source(passage["source_version_id"])
    return {
        "id": passage["id"], "kind": passage["kind"], "text": passage["text"], "physical_page": passage["physical_page"],
        "printed_label": passage["printed_label"], "abstract_origin": passage["abstract_origin"],
        "extraction_version": passage["extraction_version"], "payload_ref": passage["payload_ref"],
        "reading_depth": "abstract" if passage["kind"] == "abstract" else "selected_sections",
        "asset_id": passage["asset_id"],
        "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin")},
    }
