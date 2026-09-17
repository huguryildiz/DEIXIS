"""Read models returned by the API. Every value comes from stored records."""

from __future__ import annotations

import json
from typing import Any

from deixis.documents import embeddings, pdf
from deixis.domain.rules import effective_reviewer, result_applicability
from deixis.workflow.equations import equation_state, equations_to_check
from deixis.workflow.store import EVIDENCE_STATUS_SQL, Store


# What the transcript reports from a search plan; the rest of the stored output stays out of the view.
PLAN_FIELDS = ("question_interpretation", "search_rationale", "scope_boundaries", "concepts")


def _json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _model_outputs(store: Store, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [json.loads(r["output_json"]) for r in store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND kind = ? AND status = 'succeeded' AND output_json IS NOT NULL"
        " ORDER BY rowid", (run_id, kind),
    )]


def ocr_state(store: Store, asset_id: str) -> dict[str, Any]:
    """Pages of the text in use without text (blank pages included), pages read with OCR, and the latest OCR reading (D51)."""
    conn = store.conn
    asset = store.asset(asset_id)
    pages = {r["physical_page"]: r["ocr"] for r in conn.execute(
        "SELECT physical_page, MAX(text_source = 'ocr') AS ocr FROM passages WHERE asset_id = ? AND kind = 'pdf_page'"
        " AND extraction_version IS ? GROUP BY physical_page", (asset_id, asset["extraction_version"]))}
    last = conn.execute(
        "SELECT outcome, rejection_reason, ocr_json, created_at FROM asset_extractions WHERE asset_id = ? AND ocr_json IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (asset_id,)).fetchone()
    return {"pages_without_text": max(0, (asset["page_count"] or 0) - len(pages)), "ocr_pages": sum(1 for o in pages.values() if o),
            "last_read": {"outcome": last["outcome"], "rejection_reason": last["rejection_reason"], "created_at": last["created_at"]}
            | json.loads(last["ocr_json"]) if last else None}


def research_view(store: Store, research_id: str) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    scope = store.scope(research_id)
    seed = scope["seed_snapshot"]
    scope_view = {key: value for key, value in scope.items() if key != "seed_snapshot"}
    scope_view["seed"] = ({key: seed[key] for key in ("source_version_id", "asset_id", "asset_sha256",
                                                      "extraction_version", "title", "title_basis", "page_count", "text_pages")}
                          | {"passage_count": len(seed["passages"])} if seed else None)
    scope_view["seed_status"] = store.seed_status(research_id, scope)

    runs = []
    for row in conn.execute("SELECT id FROM runs WHERE research_id = ? ORDER BY created_at DESC LIMIT 10", (research_id,)):
        run = store.run(row["id"])
        run["steps"] = store.run_steps(run["id"])
        output = next((o for o in _model_outputs(store, run["id"], "model:search_plan") if o.get("output_type") == "SearchPlan"), None)
        # A v1 plan holds the queries the model wrote; a v2 plan's queries were compiled from its concepts and stored beside it (D44).
        run["plan"] = ({k: output["result"][k] for k in PLAN_FIELDS}
                       | {"queries": output["result"].get("queries", output.get("queries", []))}) if output else None
        # Screening runs in batches; each batch's note is its own line, timed by its step.
        run["screening_notes"] = [
            {"step_id": r["id"], "text": note} for r in store.conn.execute(
                "SELECT id, output_json FROM run_steps WHERE run_id = ? AND kind = 'model:screening' AND status = 'succeeded'"
                " AND output_json IS NOT NULL ORDER BY rowid", (run["id"],))
            if (note := (json.loads(r["output_json"]).get("result") or {}).get("notes", "").strip())
        ]
        runs.append(run)

    search_runs = [
        {**{k: r[k] for k in ("id", "run_id", "scope_revision", "provider", "query_text", "access_mode", "status", "result_count", "provider_total", "page_limit", "retrieved_at")},
         "error": _json(r["error_json"])}
        for r in conn.execute("SELECT * FROM search_runs WHERE research_id = ? ORDER BY retrieved_at", (research_id,))
    ]

    answers = []
    cited_sources: set[str] = set()
    # A quote of a source removed from this research still opens; the view names the removal (D50).
    removed = {r[0] for r in conn.execute(
        "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL", (research_id,))}
    for a in conn.execute("SELECT * FROM answers WHERE research_id = ? ORDER BY created_at DESC, rowid DESC", (research_id,)):
        draft = _json(a["draft_json"])
        claims = []
        for c in conn.execute("SELECT * FROM claims WHERE answer_id = ? ORDER BY ordinal", (a["id"],)):
            evidence = [
                {"passage_id": e["passage_id"], "source_version_id": e["source_version_id"], "source_key": e["source_key"], "kind": e["kind"],
                 "physical_page": e["physical_page"], "printed_label": e["printed_label"],
                 "reading_depth": "abstract" if e["kind"] == "abstract" else "selected_sections", "title": e["title"],
                 "version_label": e["version_label"], "anchor_text": e["anchor_text"], "evidence_status": e["evidence_status"],
                 "text_source": e["text_source"], "removed_from_research": e["source_version_id"] in removed}
                for e in conn.execute(
                    "SELECT l.passage_id, l.source_version_id, l.anchor_text, p.kind, p.physical_page, p.printed_label, p.text_source, s.title, s.version_label,"
                    " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
                    f" {EVIDENCE_STATUS_SQL} AS evidence_status FROM evidence_links l"
                    " JOIN passages p ON p.id = l.passage_id JOIN source_versions s ON s.id = l.source_version_id"
                    " LEFT JOIN source_assets a ON a.id = p.asset_id"
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
            # A report keeps the number and title it was saved with; later answers and title changes do not rewrite them.
            "report_version": a["report_version"],
            "report_title": (draft or {}).get("title") if a["status"] == "structurally_valid" else None,
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
            # A file or text extraction this answer read is no longer in use; its quotes still open what was read (D45).
            "source_text_changed": bool(given) and any(
                status != "current" for status in store.evidence_statuses([p["passage_id"] for p in given["passages"]]).values()),
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
        "SELECT m.added_by, m.created_at AS added_at, s.*, sel.state, sel.origin AS selection_origin, sel.version AS selection_version, sel.proposal,"
        " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
        " sel.proposal_reason, sel.proposal_basis, sel.user_reason, c.id AS candidate_id, c.rank, c.scope_revision AS found_in_revision,"
        " (SELECT ss.similarity FROM source_similarities ss WHERE ss.research_id = m.research_id AND ss.source_version_id = m.source_version_id"
        "  AND ss.scope_revision = c.scope_revision AND ss.model = ?) AS similarity"
        " FROM corpus_memberships m JOIN source_versions s ON s.id = m.source_version_id"
        " JOIN selections sel ON sel.research_id = m.research_id AND sel.source_version_id = m.source_version_id"
        " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL ORDER BY m.created_at, c.rank", (similarity_model, research_id)
    ):
        svid = row["id"]
        # The PDF in use, whether its text comes from the current extractor, and a later extraction that was not taken (D45).
        # A math extraction (D52) builds on the current extractor's text; its own "nothing to read" or failed attempts are
        # reported as the PDF's equation state, not as a rejected re-extraction.
        assets = [dict(r) | {"current_extraction": (r["extraction_version"] or "").split("+")[0] == pdf.EXTRACTION_VERSION,
                             "equations": equation_state(store, r["id"]), "ocr": ocr_state(store, r["id"]), "rejected_extraction": dict(rejected) if (rejected := conn.execute(
            "SELECT extraction_version, rejection_reason, created_at FROM asset_extractions WHERE asset_id = ? AND outcome = 'rejected'"
            " AND extraction_version NOT LIKE '%+marker-%' ORDER BY created_at DESC, rowid DESC LIMIT 1", (r["id"],)).fetchone()) else None} for r in conn.execute(
            "SELECT id, extraction_status, extraction_version, page_count, origin, byte_size, original_filename FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL", (svid,)
        )]
        replaced_assets = [dict(r) for r in conn.execute(
            "SELECT id, original_filename, removed_at, replaced_by_asset_id FROM source_assets"
            " WHERE source_version_id = ? AND removal_reason = 'replaced' ORDER BY removed_at DESC", (svid,)
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
            # Web results under another paper's title, stored before those were dropped at lookup, are not shown.
            "SELECT * FROM pdf_candidates WHERE source_version_id = ? AND identity_status != 'unverified'"
            " ORDER BY discovered_at, rowid", (svid,)
        )]
        sources.append({
            "source_version_id": svid, "work_id": row["work_id"], "source_key": row["source_key"], "title": row["title"],
            "authors": json.loads(row["authors_json"]),
            "year": row["year"], "venue": row["venue"], "volume": row["volume"], "issue": row["issue"],
            "pages": row["pages"], "doi": row["doi"], "landing_url": row["landing_url"],
            "version_label": row["version_label"], "publication_type": row["publication_type"], "origin": row["origin"],
            "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
            "added_by": row["added_by"], "added_at": row["added_at"], "rank": row["rank"], "similarity": row["similarity"],
            # Whether an answer can read this version's PDF pages rather than its abstract (D49).
            "has_pdf_text": bool(assets) and store.has_pdf_text(svid),
            # Some of that text was read with OCR from scanned pages and is labelled so (D51).
            "has_ocr_text": bool(assets) and any(p["text_source"] == "ocr" for p in store.passages_for(svid)),
            # "other_version": another version of a found record (e.g. its submitted manuscript), stored separately.
            "version_role": "other_version" if row["added_by"] == "search" and row["candidate_id"] is None else "record",
            # A search result keeps the question revision it was found for; attached files belong to no revision.
            "found_in_revision": row["found_in_revision"],
            "applicability": "current" if row["found_in_revision"] is None
            else result_applicability(row["found_in_revision"], research["current_scope_revision"]),
            "access": {"abstract_passage_id": abstract["id"] if abstract else None,
                       "abstract_origin": abstract["abstract_origin"] if abstract else None,
                       "oa_pdf_url": row["oa_pdf_url"], "oa_pdf_version": row["oa_pdf_version"], "assets": assets, "replaced_assets": replaced_assets,
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

    # A work has one record, its head: a published record, else the first (D46, D48). Another candidate of the same work
    # (a preprint screened before its published record joined the work) is shown as another version of the head.
    heads = store.work_heads(research_id)
    for s in sources:
        if s["version_role"] == "record" and heads.get(s["work_id"]) != s["source_version_id"]:
            s["version_role"] = "other_version"
        # The version whose text an answer reads when it is not the head itself (D48).
        s["answer_reads_version_id"] = None
        if s["version_role"] == "record" and (reads := store.answer_version(research_id, s["source_version_id"])) != s["source_version_id"]:
            s["answer_reads_version_id"] = reads

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
        # A work's selection is its head's; other versions follow it (D48).
        "included": sum(s["selection"]["state"] == "included" for s in sources if s["version_role"] == "record"),
        "excluded": sum(s["selection"]["state"] == "excluded" for s in sources if s["version_role"] == "record"),
        "pending": sum(s["selection"]["state"] == "pending" for s in sources if s["version_role"] == "record"),
        "inspected": works(latest_given["source_ids"]) if latest_given else 0,
        "cited": works(cited_sources),
        # Works the user removed from this research, and those a later search found again; neither is listed (D50).
        **dict(zip(("removed", "removed_found_again"), conn.execute(
            "SELECT COUNT(DISTINCT v.work_id), COUNT(DISTINCT CASE WHEN m.found_again_at IS NOT NULL THEN v.work_id END)"
            " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NOT NULL", (research_id,)).fetchone())),
    }
    last_event = conn.execute("SELECT MAX(id) FROM events WHERE research_id = ?", (research_id,)).fetchone()[0] or 0
    reviewer = effective_reviewer(scope, store.setting("reviewer"))
    return {"research": research, "scope": scope_view, "runs": runs, "search_runs": search_runs, "sources": sources,
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
        " m.removed_at,"
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
        # A source removed from a research stays in the library but not in that research's project group (D50).
        if row["removed_at"] is None and rid not in work["researches"]:
            work["researches"][rid] = {"id": rid, "title": row["research_title"], "updated_at": row["research_updated_at"]}

    entries = []
    for work_id, work in works.items():
        versions = list(work["versions"].values())
        versions.sort(key=lambda v: (v["source_created_at"] is None, v["source_created_at"] or ""), reverse=True)
        representative = max(versions, key=_library_representative_score)
        researches = sorted(work["researches"].values(), key=lambda r: r["updated_at"] or "", reverse=True)
        entries.append({
            "work_id": work_id, "source_key": store.source_key(work_id),
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
            " WHERE m.source_version_id = ? AND m.removed_at IS NULL AND r.trashed_at IS NULL ORDER BY r.updated_at DESC", (svid,)
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
        "work_id": work_id, "source_key": store.source_key(work_id), "title": titles[representative["source_version_id"]],
        "authors": representative["authors"],
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
    if not store.was_member(research_id, passage["source_version_id"]):
        return None
    source = store.source(passage["source_version_id"])
    return {
        "id": passage["id"], "kind": passage["kind"], "text": passage["text"], "physical_page": passage["physical_page"],
        "printed_label": passage["printed_label"], "abstract_origin": passage["abstract_origin"],
        "extraction_version": passage["extraction_version"], "payload_ref": passage["payload_ref"], "text_source": passage["text_source"],
        "equations_to_check": equations_to_check(store, passage["asset_id"], passage["extraction_version"]).get(passage["physical_page"], 0)
        if passage["text_source"] == "marker" else 0,
        "reading_depth": "abstract" if passage["kind"] == "abstract" else "selected_sections",
        "asset_id": passage["asset_id"],
        "evidence_status": store.evidence_statuses([passage_id])[passage_id],
        "removed_from_research": not store.is_active_member(research_id, passage["source_version_id"]),
        "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin",
                                            "cited_by_count", "cited_by_count_at")}
        | {"source_key": store.source_key(source["work_id"])},
    }
