"""Status of the supplied, assessed subset; no novelty or scientific-validity verdict."""
from __future__ import annotations

STATUSES = ("not_run", "undecided", "narrowed", "closed", "open")
SUPPORT_RELATIONS = ("explicit_support", "reasoned_inference", "partial_match")


def derive_status(search, queries, hits, cells, element_ids) -> dict:
    kept = [hit for hit in hits if hit["kept"]]
    assessed = [hit for hit in kept if hit["assessment_state"] == "assessed"]
    facts = {key: search[key] if search else 0 for key in ("found", "kept", "rank_cut", "duplicates")}
    facts.update(assessed=len(assessed), unread=facts["rank_cut"] + len(kept) - len(assessed),
                 queries_total=len(queries), queries_succeeded=sum(q["status"] == "succeeded" for q in queries),
                 queries_failed=sum(q["status"] == "failed" for q in queries),
                 queries_unknown=sum(q["status"] == "outcome_unknown" for q in queries),
                 reading_depths={depth: sum(h["reading_depth"] == depth for h in kept)
                                 for depth in ("abstract", "stored_passages", "metadata_only")})

    def result(status, reasons, warnings=()):
        return {"status": status, "reason": reasons[0], "reasons": reasons, "facts": facts, "warnings": list(warnings)}

    if search is None:
        return result("not_run", ["not_searched"])
    if (search["outcome"] == "completed" and search.get("query_record_count", 0) > 0
            and not hits and facts["found"] == 0):
        return result("undecided", ["unclassified"], ["merge_missing"])
    by_source = {h["source_version_id"]: [c for c in cells if c["source_version_id"] == h["source_version_id"]]
                 for h in assessed}
    for hit in assessed:
        own = by_source[hit["source_version_id"]]
        if (element_ids and hit["states_whole_claim"] and hit["whole_claim_evidence_count"] >= 1
                and all(len(matches := [c for c in own if c["element_id"] == element]) == 1
                        and matches[0]["relation"] == "explicit_support"
                        and matches[0]["condition_alignment"] == "aligned" for element in element_ids)):
            return result("closed", ["whole_claim_stated"])
    support = [c for own in by_source.values() for c in own if c["relation"] in SUPPORT_RELATIONS]
    outcome = search["outcome"]
    conditions = (
        ("search_running", outcome == "running"),
        ("search_paused", outcome == "paused"),
        ("search_failed", outcome == "completed" and not facts["queries_succeeded"]),
        ("search_incomplete", outcome in ("failed", "stopped")),
        ("query_outcome_unknown", outcome == "completed" and facts["queries_unknown"] > 0),
        ("insufficient_access", any(h["assessment_state"] == "insufficient_access" for h in kept)),
        ("not_assessed_budget", any(h["assessment_state"] == "not_assessed_budget"
                                   or (h["assessment_state"] == "pending" and outcome not in ("running", "paused")) for h in kept)),
        ("uncertain_relevance", any(h["work_relevance"] == "uncertain" for h in assessed)),
        ("uncertain_cell", any(c["relation"] == "uncertain" for h in assessed if h["work_relevance"] == "related"
                               for c in by_source[h["source_version_id"]])),
        ("unclear_alignment", any(c["condition_alignment"] == "unclear" for c in support)),
    )
    reasons = [code for code, applies in conditions if applies]
    if reasons:
        return result("undecided", reasons)
    if support:
        return result("narrowed", ["partial_overlap"])
    if (outcome == "completed" and facts["queries_succeeded"]
            and ((facts["kept"] > 0 and len(kept) == facts["kept"]
                  and all(h["assessment_state"] == "assessed" and h["work_relevance"] == "unrelated" for h in kept))
                 or (facts["kept"] == 0 and facts["found"] == 0 and not kept))):
        return result("open", ["no_match_in_assessed_subset"])
    return result("undecided", ["unclassified"], ["unmatched_shape:" + outcome + ":"
                  + ",".join(sorted({str(h["assessment_state"]) + "/" + str(h["work_relevance"]) for h in kept}))])
