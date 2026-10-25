"""The answer thread's view of the candidates written from one answer (D98): counts read from stored rows only.

Nothing here derives a status of its own; the computed status is `CandidateStore.search_status`, and the person's
decision stays beside it with the card version it was made for.
"""
from __future__ import annotations

import json

from deixis.domain.rules import step_model
from deixis.workflow.features.candidates.candidates_run import decompose_budget
from deixis.workflow.features.candidates.candidates_status import SUPPORT_RELATIONS
from deixis.workflow.features.candidates.candidates_store import CandidateStore
from deixis.workflow.run.store import NotFound, Store

TOP_WORKS = 3


def _run_view(run: dict | None) -> dict | None:
    return {key: run[key] for key in ("id", "kind", "status", "pause_reason")} if run else None


def _reading(cs: CandidateStore, search: dict, hits: list[dict]) -> dict:
    """What the model was given for the works it assessed: abstracts, stored PDF passages and metadata-only works,
    from the stored assessment plan. Kill search never gives full text."""
    assessed = {h["source_version_id"] for h in hits if h["kept"] and h["assessment_state"] == "assessed"}
    plan = cs.store.existing_step(search["run_id"], "kill_search_plan")
    entries = {e["source_version_id"]: e for e in ((plan or {}).get("output") or {}).get("hits", [])} if plan else {}
    ids = [p["passage_id"] for svid in assessed for p in entries.get(svid, {}).get("passages", [])]
    kinds = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        kinds.update({row["id"]: row["kind"] for row in cs.conn.execute(
            f"SELECT id, kind FROM passages WHERE id IN ({','.join('?' * len(chunk))})", chunk)})
    abstracts = sum(any(kinds.get(p["passage_id"]) == "abstract" for p in entries.get(svid, {}).get("passages", []))
                    for svid in assessed)
    pages = sum(kinds.get(pid) == "pdf_page" for pid in ids)
    depths = {depth: sum(h["reading_depth"] == depth for h in hits if h["source_version_id"] in assessed)
              for depth in ("abstract", "stored_passages", "metadata_only")}
    return {"assessed_works": len(assessed), "abstracts": abstracts, "stored_passages": pages,
            "depths": depths, "full_text": 0, "planned": bool(plan)}


def _top_works(cs: CandidateStore, search: dict, version: dict, hits: list[dict]) -> list[dict]:
    cells = cs.cells(search["id"])
    elements = {e["id"]: e for e in version["elements"]}
    by_source: dict[str, list[dict]] = {}
    for cell in cells:
        by_source.setdefault(cell["source_version_id"], []).append(cell)
    chosen = [h for h in hits if h["kept"] and h["assessment_state"] == "assessed" and h["work_relevance"] in ("related", "uncertain")]

    def support(hit):
        return sum(c["relation"] in SUPPORT_RELATIONS for c in by_source.get(hit["source_version_id"], []))
    chosen.sort(key=lambda h: (not h["states_whole_claim"], -support(h), h["rank_key"]))
    works = []
    for hit in chosen[:TOP_WORKS]:
        source = cs.store.source(hit["source_version_id"])
        own = sorted(by_source.get(hit["source_version_id"], []), key=lambda c: elements[c["element_id"]]["position"])
        works.append({"source_version_id": hit["source_version_id"], "rank": hit["rank_key"],
                      "title": source["title"], "year": source["year"], "version_label": source["version_label"],
                      "work_relevance": hit["work_relevance"], "states_whole_claim": bool(hit["states_whole_claim"]),
                      "reading_depth": hit["reading_depth"],
                      "elements": [{"element_id": c["element_id"], "position": elements[c["element_id"]]["position"],
                                    "kind": elements[c["element_id"]]["kind"], "text": elements[c["element_id"]]["text"],
                                    "relation": c["relation"], "condition_alignment": c["condition_alignment"]} for c in own]})
    return works


def search_view(cs: CandidateStore, search: dict, version: dict, current_version: int) -> dict:
    queries = cs.queries(search["id"])
    hits = cs.hits(search["id"])
    kept = [h for h in hits if h["kept"]]
    cells = cs.cells(search["id"])
    supported = {c["source_version_id"] for c in cells if c["relation"] in SUPPORT_RELATIONS}
    element_ids = {e["id"] for e in version["elements"]}
    whole = 0
    for hit in kept:
        own = [c for c in cells if c["source_version_id"] == hit["source_version_id"]]
        if (hit["assessment_state"] == "assessed" and hit["states_whole_claim"] and element_ids
                and {c["element_id"] for c in own} == element_ids
                and all(c["relation"] == "explicit_support" and c["condition_alignment"] == "aligned" for c in own)):
            whole += 1
    recorded = bool(search["hits_recorded"])
    execution = {
        "queries_planned": len(json.loads(search["rendered_queries_json"])),
        "queries_recorded": len(queries),
        "queries_succeeded": sum(q["status"] == "succeeded" for q in queries),
        "queries_failed": sum(q["status"] == "failed" for q in queries),
        "queries_outcome_unknown": sum(q["status"] == "outcome_unknown" for q in queries),
        "records_returned": sum(q["record_count"] for q in queries),
        "hits_recorded": recorded,
        # Counts of the merge, null until the merge is stored: found is every record the queries returned, unique the
        # distinct works among them, kept the works sent on to assessment and cut the unique works left after them.
        "found": search["found"] if recorded else None,
        "duplicates": search["duplicates"] if recorded else None,
        "unique": search["found"] - search["duplicates"] if recorded else None,
        "kept": search["kept"] if recorded else None,
        "rank_cut": search["rank_cut"] if recorded else None,
        "assessed": sum(h["assessment_state"] == "assessed" for h in kept),
        "insufficient_access": sum(h["assessment_state"] == "insufficient_access" for h in kept),
        "not_assessed_budget": sum(h["assessment_state"] == "not_assessed_budget" for h in kept),
        "pending": sum(h["assessment_state"] == "pending" for h in kept),
        "works_with_support": len(supported & {h["source_version_id"] for h in kept if h["assessment_state"] == "assessed"}),
        "works_stating_whole_claim": whole,
    }
    return {"kill_search_id": search["id"], "run_id": search["run_id"], "version": version["version"],
            "is_current_version": version["version"] == current_version, "outcome": search["outcome"],
            "created_at": search["created_at"], "status": cs.search_status(search["id"]), "execution": execution,
            "reading": _reading(cs, search, hits), "top_works": _top_works(cs, search, version, hits)}


def answer_candidates(store: Store, research_id: str, answer_id: str) -> dict:
    research = store.research(research_id)
    if not store.conn.execute("SELECT 1 FROM answers WHERE id = ? AND research_id = ?", (answer_id, research_id)).fetchone():
        raise NotFound(answer_id)
    cs = CandidateStore(store)
    scope = store.scope(research_id, research["current_scope_revision"])
    connection, model, effort = step_model(scope, "claim_decomposition")
    rows = []
    for link in cs.answer_links(research_id, answer_id):
        candidate_id = link["candidate_id"]
        versions = cs.versions(candidate_id)
        for version in versions:
            for search in cs.searches(version["id"]):
                cs.sync_search_outcome(search["run_id"])
        candidate = cs.candidate(candidate_id)
        current = next((v for v in versions if v["version"] == candidate["current_version"]), None)
        latest = None
        for version in sorted(versions, key=lambda v: -v["version"]):
            searches = cs.searches(version["id"])
            if searches:
                latest = (searches[-1], version)
                break
        decision = None
        for version in sorted(versions, key=lambda v: -v["version"]):
            decisions = cs.overrides(version["id"])
            if decisions:
                decision = decisions[-1] | {"version": version["version"]}
                break
        runs = cs.runs(candidate_id, limit=5)
        live = next((r for r in runs if r["status"] in ("queued", "running", "pause_requested", "paused")), None)
        rows.append({
            "candidate_id": candidate_id, "aspect_index": link["aspect_index"], "created_at": link["created_at"],
            "context": json.loads(candidate["origin_provenance_json"]), "origin_text": candidate["origin_text"],
            "trashed_at": candidate["trashed_at"], "current_version": candidate["current_version"],
            "claim_statement": current["claim_statement"] if current else None,
            "current_version_searched": bool(current and cs.searches(current["id"])),
            "search": search_view(cs, latest[0], latest[1], candidate["current_version"]) if latest else None,
            "owner": decision, "run": _run_view(live), "latest_run": _run_view(runs[0] if runs else None),
        })
    return {"answer_id": answer_id, "candidates": rows,
            "decompose": {"connection": connection, "model": model, "reasoning_effort": effort, **decompose_budget()}}
