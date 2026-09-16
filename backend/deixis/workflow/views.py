"""Read models returned by the API. Every value comes from stored records."""

from __future__ import annotations

import json
from typing import Any

from deixis.documents import embeddings
from deixis.domain.rules import effective_reviewer, result_applicability
from deixis.workflow.store import Store


# What the transcript reports from a search plan; the rest of the stored output stays out of the view.
PLAN_FIELDS = ("question_interpretation", "search_rationale", "scope_boundaries", "concepts")


def _json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _model_outputs(store: Store, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [json.loads(r["output_json"]) for r in store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND kind = ? AND status = 'succeeded' AND output_json IS NOT NULL"
        " ORDER BY rowid", (run_id, kind),
    )]


def research_view(store: Store, research_id: str) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    scope = store.scope(research_id)

    runs = []
    for row in conn.execute("SELECT id FROM runs WHERE research_id = ? ORDER BY created_at DESC LIMIT 10", (research_id,)):
        run = store.run(row["id"])
        run["steps"] = store.run_steps(run["id"])
        output = next((o for o in _model_outputs(store, run["id"], "model:search_plan") if o.get("output_type") == "SearchPlan"), None)
        # A v1 plan holds the queries the model wrote; a v2 plan's queries were compiled from its concepts and stored beside it (D44).
        run["plan"] = ({k: output["result"][k] for k in PLAN_FIELDS}
                       | {"queries": output["result"].get("queries", output.get("queries", []))}) if output else None
        # Screening runs in batches; the notes of the batches read as one paragraph.
        run["screening_notes"] = " ".join(
            note for o in _model_outputs(store, run["id"], "model:screening") if (note := (o.get("result") or {}).get("notes", "").strip())
        )
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
                 "reading_depth": "abstract" if e["kind"] == "abstract" else "selected_sections", "title": e["title"],
                 "version_label": e["version_label"], "anchor_text": e["anchor_text"]}
                for e in conn.execute(
                    "SELECT l.passage_id, l.source_version_id, l.anchor_text, p.kind, p.physical_page, p.printed_label, s.title, s.version_label FROM evidence_links l"
                    " JOIN passages p ON p.id = l.passage_id JOIN source_versions s ON s.id = l.source_version_id"
                    " WHERE l.claim_id = ? ORDER BY l.rowid", (c["id"],)
                )
            ]
            if not answers:
                cited_sources.update(e["source_version_id"] for e in evidence)
            claims.append({"id": c["id"], "label": c["label"], "section": c["section"], "text": c["text"], "support_type": c["support_type"],
                           "semantic_review": c["semantic_review"], "evidence": evidence})
        session = conn.execute(
            "SELECT connection, requested_model, resolved_model, token_usage_json FROM model_sessions WHERE step_input_id = ?",
            (a["step_input_id"],),
        ).fetchone() if a["step_input_id"] else None
        review = _review_view(store, a["id"])
        verdicts = {r["claim_label"]: {"verdict": r["verdict"], "reason": r["reason"]} for r in (review or {}).get("reviews", [])}
        for claim in claims:
            claim["review"] = verdicts.get(claim["label"])
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
            "review": review,
        })
    duplicates = store.suspected_duplicates(research_id)
    # Similarity from the chosen semantic search model only; with semantic search off, no source has one (D30).
    provider, model = embeddings.chosen(store.setting("semantic_search"))
    similarity_model = embeddings.Embedder(provider, model).stored_model if provider != "off" and model else None
    sources = []
    for row in conn.execute(
        "SELECT m.added_by, s.*, sel.state, sel.origin AS selection_origin, sel.version AS selection_version, sel.proposal,"
        " sel.proposal_reason, sel.proposal_basis, sel.user_reason, c.id AS candidate_id, c.rank, c.scope_revision AS found_in_revision,"
        " (SELECT ss.similarity FROM source_similarities ss WHERE ss.research_id = m.research_id AND ss.source_version_id = m.source_version_id"
        "  AND ss.scope_revision = c.scope_revision AND ss.model = ?) AS similarity"
        " FROM corpus_memberships m JOIN source_versions s ON s.id = m.source_version_id"
        " JOIN selections sel ON sel.research_id = m.research_id AND sel.source_version_id = m.source_version_id"
        " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
        " WHERE m.research_id = ? ORDER BY m.created_at, c.rank", (similarity_model, research_id)
    ):
        svid = row["id"]
        assets = [dict(r) for r in conn.execute(
            "SELECT id, extraction_status, page_count, origin, byte_size, original_filename FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL", (svid,)
        )]
        abstract = conn.execute(
            "SELECT id, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract' LIMIT 1", (svid,)
        ).fetchone()
        # The link's latest attempt in any research: a refused link is not requested again (see Store.pdf_link_refusal).
        fetch = conn.execute(
            "SELECT status, error_code, json_extract(error_json, '$.http_status') AS http_status FROM run_steps"
            " WHERE operation_key = ? ORDER BY started_at DESC LIMIT 1", (f"fetch:{svid}",)
        ).fetchone()
        other_copy = conn.execute(
            "SELECT s.status, s.error_code FROM run_steps s JOIN runs r ON r.id = s.run_id"
            " WHERE r.research_id = ? AND s.operation_key = ? ORDER BY s.started_at DESC LIMIT 1", (research_id, f"other_copy:{svid}")
        ).fetchone()
        pdf_candidates = [{k: r[k] for k in (
            "id", "provider", "candidate_url", "landing_url", "version_label", "license", "identity_status",
            "version_status", "access_status", "http_status", "error_code", "final_url", "discovered_at", "attempted_at"
        )} for r in conn.execute(
            "SELECT * FROM pdf_candidates WHERE source_version_id = ? ORDER BY discovered_at, rowid", (svid,)
        )]
        sources.append({
            "source_version_id": svid, "work_id": row["work_id"], "title": row["title"], "authors": json.loads(row["authors_json"]),
            "year": row["year"], "venue": row["venue"], "volume": row["volume"], "issue": row["issue"],
            "pages": row["pages"], "doi": row["doi"], "landing_url": row["landing_url"],
            "version_label": row["version_label"], "publication_type": row["publication_type"], "origin": row["origin"],
            "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
            "added_by": row["added_by"], "rank": row["rank"], "similarity": row["similarity"],
            # "other_version": another version of a found record (e.g. its submitted manuscript), stored separately.
            "version_role": "other_version" if row["added_by"] == "search" and row["candidate_id"] is None else "record",
            # A search result keeps the question revision it was found for; attached files belong to no revision.
            "found_in_revision": row["found_in_revision"],
            "applicability": "current" if row["found_in_revision"] is None
            else result_applicability(row["found_in_revision"], research["current_scope_revision"]),
            "access": {"abstract_passage_id": abstract["id"] if abstract else None,
                       "abstract_origin": abstract["abstract_origin"] if abstract else None,
                       "oa_pdf_url": row["oa_pdf_url"], "oa_pdf_version": row["oa_pdf_version"], "assets": assets,
                       "fetch": dict(fetch) if fetch else None, "other_copy": dict(other_copy) if other_copy else None,
                       "pdf_candidates": pdf_candidates,
                       "pdf_discoveries": store.pdf_discoveries(research_id, svid)},
            "selection": {"state": row["state"], "origin": row["selection_origin"], "version": row["selection_version"],
                          "proposal": row["proposal"], "proposal_reason": row["proposal_reason"],
                          "proposal_basis": row["proposal_basis"], "user_reason": row["user_reason"]},
            "cited_in_latest_answer": svid in cited_sources,
            # Providers whose records map to this source version (one DOI from several providers is one source).
            "provider_records": [r[0] for r in conn.execute(
                "SELECT DISTINCT provider FROM identifier_mappings WHERE source_version_id = ? AND scheme = provider ORDER BY provider", (svid,)
            )],
            # Possibly the same publication as another source (same title, or a preprint naming its DOI); never merged.
            "suspected_duplicates": duplicates.get(svid, []),
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
    reviewer = effective_reviewer(scope, store.setting("reviewer"))
    return {"research": research, "scope": scope, "runs": runs, "search_runs": search_runs, "sources": sources,
            "answers": answers, "counts": counts, "last_event_id": last_event,
            # The reviewer the next answer would get: the research's own setting, else the app-wide default.
            "reviewer": {"mode": scope["review_mode"], "connection": reviewer[0] if reviewer else None, "model": reviewer[1] if reviewer else None,
                         "reasoning_effort": reviewer[2] if reviewer else None}}


# Reading depth of one stored source version. A PDF text layer, an abstract and bare metadata are
# different evidence levels (AGENTS.md), so the library names the level instead of a generic badge.
_HAS_PDF_TEXT = ("EXISTS (SELECT 1 FROM passages p JOIN source_assets a ON a.id = p.asset_id"
                 " WHERE p.source_version_id = v.id AND a.removed_at IS NULL)")
_HAS_ABSTRACT = "EXISTS (SELECT 1 FROM passages p WHERE p.source_version_id = v.id AND p.kind = 'abstract')"
_ACCESS_ORDER = ["metadata", "abstract", "pdf_available"]


def _access_level(has_pdf_text: int, has_abstract: int) -> str:
    return "pdf_available" if has_pdf_text else "abstract" if has_abstract else "metadata"


# Rank one version of a work as the representative shown in the library table: richer bibliographic
# records first, so a bare preprint never hides the published version's metadata.
def _library_representative_score(row: dict[str, Any]) -> tuple[int, ...]:
    return (
        1 if row["cited_by_count"] is not None else 0,
        1 if row["authors"] else 0,
        1 if row["year"] is not None else 0,
        1 if row["venue"] else 0,
        1 if row["doi"] else 0,
        1 if row["version_label"] else 0,
        1 if row["publication_type"] else 0,
    )


def library_view(store: Store) -> dict[str, Any]:
    """Every work (publication) in any non-trashed research, with its versions and the researches it belongs to."""
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.volume, v.issue,"
        " v.pages, v.publication_type, v.doi, v.landing_url, v.version_label, v.cited_by_count, v.cited_by_count_at,"
        " v.created_at AS source_created_at, r.id AS research_id, r.title AS research_title, r.updated_at AS research_updated_at,"
        f" {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " JOIN researches r ON r.id = m.research_id WHERE r.trashed_at IS NULL"
        " ORDER BY v.created_at DESC, r.updated_at DESC"
    ).fetchall()

    works: dict[str, dict[str, Any]] = {}
    for row in rows:
        work = works.setdefault(row["work_id"], {"versions": {}, "researches": {}})
        svid = row["source_version_id"]
        if svid not in work["versions"]:
            work["versions"][svid] = {
                "source_version_id": svid, "title": row["title"], "version_label": row["version_label"], "year": row["year"],
                "venue": row["venue"], "doi": row["doi"], "authors": json.loads(row["authors_json"]),
                "publication_type": row["publication_type"], "landing_url": row["landing_url"],
                "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
                "source_created_at": row["source_created_at"],
                "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
            }
        rid = row["research_id"]
        if rid not in work["researches"]:
            work["researches"][rid] = {"id": rid, "title": row["research_title"], "updated_at": row["research_updated_at"]}

    entries = []
    for work_id, work in works.items():
        versions = list(work["versions"].values())
        versions.sort(key=lambda v: (v["source_created_at"] is None, v["source_created_at"] or ""), reverse=True)
        representative = max(versions, key=_library_representative_score)
        researches = sorted(work["researches"].values(), key=lambda r: r["updated_at"] or "", reverse=True)
        entries.append({
            "work_id": work_id,
            "title": representative["title"],
            "authors": representative["authors"],
            "year": representative["year"], "venue": representative["venue"],
            "publication_type": representative["publication_type"], "doi": representative["doi"],
            "landing_url": representative["landing_url"],
            "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
            "cited_by_count_at": representative["cited_by_count_at"],
            "versions": [{"source_version_id": v["source_version_id"], "version_label": v["version_label"],
                          "year": v["year"], "venue": v["venue"], "access_level": v["access_level"]} for v in versions],
            # The best reading depth any stored version of this work reaches; the panel lists each version separately.
            "access_level": max((v["access_level"] for v in versions), key=_ACCESS_ORDER.index),
            "researches": researches,
            "first_research_id": researches[0]["id"] if researches else None,
            "newest_source_at": max(v["source_created_at"] or "" for v in versions),
        })

    # Most recently added works first; within a tie, newest active research first.
    entries.sort(key=lambda e: (e["newest_source_at"], e["first_research_id"] or ""), reverse=True)
    # Every active research, including ones with no source yet, so each can be a group and a drop target.
    researches = [dict(r) for r in conn.execute(
        "SELECT id, title, updated_at FROM researches WHERE trashed_at IS NULL ORDER BY updated_at DESC"
    )]
    return {
        "entries": entries,
        "researches": researches,
        "counts": {"works": len(entries), "versions": sum(len(e["versions"]) for e in entries),
                   "researches": len({r["id"] for e in entries for r in e["researches"]})},
    }


def library_version_to_add(work: dict[str, Any]) -> dict[str, Any]:
    """The one version of a work that joins a research when the user adds the work from the Library.

    The deepest stored reading comes first, so a paywalled published record never replaces a preprint whose
    text DEIXIS holds; among equals, the richer bibliographic record. Other versions stay out: they are
    different evidence, not copies.
    """
    return max(work["versions"], key=lambda v: (_ACCESS_ORDER.index(v["access_level"]), _library_representative_score(v)))


def library_work_view(store: Store, work_id: str) -> dict[str, Any] | None:
    """One work in reading depth: every stored version with its access level, abstract and PDF asset.

    Versions stay separate. A preprint and a published version are different evidence, so the panel
    never merges their abstracts or files into one record.
    """
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.doi,"
        " v.landing_url, v.version_label, v.publication_type, v.cited_by_count, v.cited_by_count_at,"
        f" v.created_at AS source_created_at, {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM source_versions v WHERE v.work_id = ?"
        " AND EXISTS (SELECT 1 FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
        "  WHERE m.source_version_id = v.id AND r.trashed_at IS NULL)"
        " ORDER BY v.created_at DESC", (work_id,)
    ).fetchall()
    if not rows:
        return None

    versions, researches = [], {}
    for row in rows:
        svid = row["source_version_id"]
        abstract = conn.execute(
            "SELECT text, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract'"
            " ORDER BY created_at DESC LIMIT 1", (svid,)
        ).fetchone()
        asset = conn.execute(
            "SELECT id, page_count, original_filename, extraction_status FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL ORDER BY retrieved_at DESC LIMIT 1", (svid,)
        ).fetchone()
        members = conn.execute(
            "SELECT r.id, r.title, r.updated_at FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
            " WHERE m.source_version_id = ? AND r.trashed_at IS NULL ORDER BY r.updated_at DESC", (svid,)
        ).fetchall()
        for member in members:
            researches.setdefault(member["id"], {"id": member["id"], "title": member["title"],
                                                 "updated_at": member["updated_at"]})
        versions.append({
            "source_version_id": svid, "version_label": row["version_label"], "year": row["year"],
            "venue": row["venue"], "doi": row["doi"], "landing_url": row["landing_url"],
            "publication_type": row["publication_type"], "authors": json.loads(row["authors_json"]),
            "cited_by_count": row["cited_by_count"], "added_at": row["source_created_at"],
            "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
            "abstract": abstract["text"] if abstract else None,
            "abstract_origin": abstract["abstract_origin"] if abstract else None,
            # The PDF opens through a research that holds this version; the asset route is research-scoped.
            "asset": {"id": asset["id"], "page_count": asset["page_count"],
                      "original_filename": asset["original_filename"],
                      "extraction_status": asset["extraction_status"]} if asset else None,
            "research_id": members[0]["id"] if members else None,
        })

    titles = {row["source_version_id"]: row["title"] for row in rows}
    representative = max(versions, key=_library_representative_score)
    return {
        "work_id": work_id, "title": titles[representative["source_version_id"]], "authors": representative["authors"],
        "year": representative["year"], "venue": representative["venue"], "doi": representative["doi"],
        "landing_url": representative["landing_url"], "publication_type": representative["publication_type"],
        "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
        "versions": versions,
        "researches": sorted(researches.values(), key=lambda r: r["updated_at"] or "", reverse=True),
    }


def _review_view(store: Store, answer_id: str) -> dict[str, Any] | None:
    review = store.answer_review(answer_id)
    if review is None:
        return None
    session = store.conn.execute(
        "SELECT connection, requested_model, resolved_model FROM model_sessions WHERE step_id = ? ORDER BY started_at DESC LIMIT 1",
        (review["step_id"],),
    ).fetchone() if review["step_id"] else None
    completed = review["status"] == "completed"
    return {"status": review["status"], "failure_reason": review["failure_reason"], "created_at": review["created_at"],
            "reviews": review["review"]["reviews"] if completed else [], "notes": review["review"]["notes"] if completed else "",
            "issues": (review["review"] or {}).get("issues", []) if not completed else [],
            "model": dict(session) if session else None}


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
        "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin",
                                            "cited_by_count", "cited_by_count_at")},
    }
