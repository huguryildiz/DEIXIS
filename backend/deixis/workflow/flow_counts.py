"""Where every work of an `sw` research stands in the flow, and PRISMA 2020-style boxes (slice 20, decisions 1–2).

Nothing here is stored. Each read puts every work of the current revision in exactly one bucket: the person's own
decision first, by D101's single precedence rule (`probes.probe_set`), then the work's outcome (`work_outcome`, the
same context the queue and the probe set read) by stage, reason code and the reason table's next step. The buckets
sum to the works; a sum that does not is a bug, not a number to show.

The boxes resemble PRISMA 2020's flow boxes and are marked `incomplete_no_human_screening`: code and model runs did
the screening, and a person looked only at the queue and the audit sample. They are not added up and no diagram is
drawn from them. `abstract_not_read` is "not excluded, not read", never a negative.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from deixis.domain.reason_codes import REASON_CODES
from deixis.workflow import queue, waiting
from deixis.workflow.chaining import QUERY_PREFIX as CHAIN_PREFIX
from deixis.workflow.probes import NOT_A_READING

# In the order the flow block lists them: the person's decisions, then the machine's, then what is still open.
BUCKETS = ("confirmed", "person_not_met", "person_excluded", "look_again", "included", "not_met", "queued",
           "person_unsure", "waiting_for_pdf", "not_read_yet", "candidate_not_fetched", "abstract_open",
           "abstract_not_read", "survey", "out_of_scope_model", "out_of_scope_code", "not_screened", "other")
ABSTRACT_OPEN = ("no_abstract", "abstract_not_found", "runs_agree_unresolved")
ABSTRACT_NOT_READ = ("abstract_not_read", "abstract_not_proposed")
FLOW_STATUS = "incomplete_no_human_screening"


def work_buckets(ctx: Any, probe: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    """Each work of the revision with its bucket and the reason code behind it (None for a person's probe)."""
    found: dict[str, tuple[str, str | None]] = {}
    for work_id in sorted(ctx.facts["heads"]):
        found[work_id] = _bucket(ctx, probe, work_id)
    return found


def _bucket(ctx: Any, probe: dict[str, Any], work_id: str) -> tuple[str, str | None]:
    if work_id in probe["verified"]:
        return "confirmed", None
    if work_id in probe["negatives"]:
        return ("person_not_met" if probe["negatives"][work_id] == "criterion_not_met" else "person_excluded"), None
    if work_id in probe["look_again"]:
        return "look_again", None
    outcome = ctx.outcome(work_id)
    if not outcome:
        return "not_screened", None
    code, stage, by = outcome["reason_code"], outcome["stage"], outcome["decided_by"]
    if stage == "fulltext":
        if by == "human":
            # A person's decision the probe set does not hold: gone stale (the queue asks again, as D96 counts it),
            # "not sure", "the PDF is wrong", or an include / not-met whose selection the person later set to pending.
            state = queue._classify(ctx, work_id)
            if state is not None and state["state"] == queue.LOOK_AGAIN:
                return "look_again", code
            if code == "human_not_sure":
                return "person_unsure", code
            if code == "human_pdf_wrong":
                return _waiting_bucket(ctx, work_id), code
            return "other", code
        if outcome["outcome"] == "include" and by == "model_agreement":
            return "included", code
        if outcome["outcome"] == "criterion_not_met" and by == "model_agreement":
            return "not_met", code
        step = "human_queue" if code == queue.VERSIONS_DISAGREE else REASON_CODES[code].next_step
        if step == "human_queue":
            # Only a row D96 shows: a selection the person set from the list keeps the work out of the queue.
            state = queue._classify(ctx, work_id)
            return ("queued" if state is not None and state["state"] == "open" else "other"), code
        if step == "waiting_for_pdf":
            return _waiting_bucket(ctx, work_id), code
        if step == "reading_queue":
            return "not_read_yet", code
        return "other", code
    if outcome["outcome"] == "candidate":
        return "candidate_not_fetched", code
    if outcome["outcome"] == "out_of_scope":
        return ("out_of_scope_model" if by == "model_agreement" else "out_of_scope_code"), code
    if code in ABSTRACT_NOT_READ:
        return "abstract_not_read", code
    if code == "survey_title_word":
        return "survey", code
    if code in ABSTRACT_OPEN:
        return "abstract_open", code
    return "other", code


def _waiting_bucket(ctx: Any, work_id: str) -> str:
    """A work whose code says "waiting for a PDF" is in that bucket only when D99's waiting list holds it (one rule,
    `fulltext.waits_for_pdf`). When another version already has PDF text the work is off that list, and here it is
    "text in hand, not read yet" (`not_read_yet`): the text is there and nothing has read it for the criterion. Any
    other reason to be off the list (no stored retrieval plan) is `other`, with its reason code."""
    works, listed = waiting.for_context(ctx)
    if work_id in listed:
        return "waiting_for_pdf"
    work = works.get(work_id)
    return "not_read_yet" if work and any(version.get("has_text") for version in work["versions"]) else "other"


def flow_counts(ctx: Any, probe: dict[str, Any]) -> dict[str, Any]:
    """Decision 1's buckets, the SW11.12 five, the stale person decisions an answer still reads, and the queue's
    reasons, from one queue context and its probe set."""
    placed = work_buckets(ctx, probe)
    counts = Counter(bucket for bucket, _ in placed.values())
    buckets = {name: counts.get(name, 0) for name in BUCKETS}
    if sum(buckets.values()) != len(ctx.facts["heads"]):
        raise AssertionError("every work of the revision is in exactly one flow bucket")
    other = Counter(code or "none" for bucket, code in placed.values() if bucket == "other")
    # A stale person decision whose work is still included: the answer reads it (D96 left this to slice 20).
    in_answer = sum(1 for work_id, (bucket, _) in placed.items() if bucket == "look_again"
                    and (ctx.selections.get(ctx.facts["heads"][work_id]) or {}).get("state") == "included")
    _, scan, _ = queue._scan(ctx)
    return {
        "works": len(placed),
        "buckets": buckets,
        "other_reasons": dict(sorted(other.items())),
        "five": {"included": buckets["included"] + buckets["confirmed"],
                 "included_by_agreement": buckets["included"], "confirmed": buckets["confirmed"],
                 "not_met": buckets["not_met"] + buckets["person_not_met"],
                 "waiting_for_pdf": buckets["waiting_for_pdf"], "queued": buckets["queued"],
                 "not_read": buckets["not_read_yet"] + buckets["candidate_not_fetched"],
                 "not_read_in_reading": buckets["not_read_yet"],
                 "not_read_not_tried": buckets["candidate_not_fetched"]},
        "look_again_in_answer": in_answer,
        "queue_by_reason": scan["by_reason"],
    }


def flow_boxes(ctx: Any, flow: dict[str, Any]) -> dict[str, Any]:
    """PRISMA 2020-style boxes for the current revision, each marked incomplete; they are counts, not a diagram."""
    store, rid, revision = ctx.store, ctx.rid, ctx.revision
    conn = store.conn
    buckets = flow["buckets"]
    searches = [dict(row) for row in conn.execute(
        "SELECT id, status, result_count, query_text FROM search_runs WHERE research_id = ? AND scope_revision = ?",
        (rid, revision))]
    keyword = [s for s in searches if not s["query_text"].startswith(CHAIN_PREFIX)]
    chain = [s for s in searches if s["query_text"].startswith(CHAIN_PREFIX)]
    work_of = {row[0]: row[1] for row in conn.execute(
        "SELECT v.id, v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,))}
    hit_searches: set[str] = set()
    found: set[str] = set()
    for row in conn.execute("SELECT source_version_id, search_run_id FROM candidate_hits"
                            " WHERE research_id = ? AND scope_revision = ?", (rid, revision)):
        hit_searches.add(row[1])
        if row[0] in work_of:
            found.add(work_of[row[0]])
    # A search that returned records and kept no hit row is from before D93: the works it found were not counted.
    counted = not any(s["result_count"] and s["status"] == "completed" and s["id"] not in hit_searches
                      for s in searches)
    abstract_read = {work_of[row[0]] for row in conn.execute(
        "SELECT DISTINCT p.source_version_id FROM model_proposals p JOIN run_steps s ON s.id = p.step_id"
        " JOIN runs r ON r.id = s.run_id WHERE p.research_id = ? AND p.stage = 'abstract' AND r.scope_revision = ?",
        (rid, revision)) if row[0] in work_of}
    sought: set[str] = set()
    for row in conn.execute(
            "SELECT s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND r.scope_revision = ? AND s.operation_key = 'fulltext_plan' AND s.status = 'succeeded'"
            " AND s.output_json IS NOT NULL", (rid, revision)):
        sought |= {work_of[svid] for svid in json.loads(row[0]).get("works") or [] if svid in work_of}
    read = sum(1 for work_id in ctx.facts["heads"] if any(
        d["stage"] == "fulltext" and d["reason_code"] not in NOT_A_READING
        and not ctx.decisions.is_stale(d, ctx.facts["stale_key"]) for d in ctx.facts["decisions"].get(work_id, [])))
    rows = [
        ("rows_returned", sum(s["result_count"] or 0 for s in keyword)),
        ("chain_rows_returned", sum(s["result_count"] or 0 for s in chain)),  # no citation request is 0 rows
        # D93's hit rows; a revision searched before them was not counted, which is not zero.
        ("works_found_by_search", len(found) if counted else None),
        ("works", flow["works"]),
        ("abstract_read_by_model", len(abstract_read)),
        ("out_of_scope_model", buckets["out_of_scope_model"]),
        ("out_of_scope_code", buckets["out_of_scope_code"]),
        ("fulltext_sought", len(sought)),
        ("fulltext_not_retrieved", buckets["waiting_for_pdf"]),
        ("fulltext_read", read),
        ("not_met", flow["five"]["not_met"]),
        ("queued", buckets["queued"]),
        ("included", flow["five"]["included"]),
    ]
    return {"flow_status": FLOW_STATUS, "revision": revision,
            "boxes": [{"key": key, "count": count, "flow_status": FLOW_STATUS} for key, count in rows]}
