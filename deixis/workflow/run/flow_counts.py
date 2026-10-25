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
from deixis.workflow.screen import queue
from deixis.workflow.read import waiting
from deixis.workflow.search.chaining import QUERY_PREFIX as CHAIN_PREFIX
from deixis.workflow.search.probes import NOT_A_READING

# In the order the flow block lists them: the person's decisions, then the machine's, then what is still open.
BUCKETS = ("confirmed", "person_not_met", "person_excluded", "look_again", "included", "not_met", "queued",
           "person_unsure", "waiting_for_pdf", "abstract_by_choice", "not_read_yet", "candidate_not_fetched", "abstract_open",
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
    other reason to be off the list (no stored retrieval plan) is `other`, with its reason code. A work the person went
    on without a PDF for (D46) would be on the list; it is `abstract_by_choice`, read from its abstract."""
    works, listed = waiting.for_context(ctx)
    if work_id in listed:
        return "waiting_for_pdf"
    if work_id in waiting.skipped_in_context(ctx):
        return "abstract_by_choice"
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


# A follow-up search (D92) is a run of its own under the same question revision. "The search" is the research's
# `discovery` runs; follow-up searches are counted apart and never added to the first search's numbers.
FOLLOWUP_KIND = "followup_search"
FOLLOWUP_FOUND = "followup_search:found"
FOLLOWUP_SUMMARY = "followup_search:summary"
FOLLOWUP_SEND_PREFIX = "followup_search:search:"
# The search funnel's model readings: proposals of these runs (a follow-up search's screening is in its own block).
SEARCH_SCREENING_KINDS = ("discovery", "screen_more")
# A request status in a follow-up search summary that says the request never left DEIXIS.
NOT_SENT = ("not_sent", "pending", "cancelled", "skipped")
# A work found by a follow-up search over all its versions: one held before wins over removed, removed over new (R2.6).
FOLLOWUP_STATE_ORDER = ("already_here", "removed_before", "new")


def followup_runs(conn: Any, research_id: str, revision: int | None = None,
                  statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """The research's follow-up search runs, oldest first, each with its frozen `found` and `summary` step outputs
    (None while that step has not succeeded). Nothing is recounted: these are the counts the run stored."""
    sql = ("SELECT id, scope_revision, status, created_at, updated_at, json_extract(target_json, '$.turn_id') AS turn_id"
           " FROM runs WHERE research_id = ? AND kind = ?")
    args: list[Any] = [research_id, FOLLOWUP_KIND]
    if revision is not None:
        sql += " AND scope_revision = ?"
        args.append(revision)
    if statuses is not None:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += statuses
    runs = [dict(row) for row in conn.execute(sql + " ORDER BY created_at, rowid", args)]
    steps: dict[tuple[str, str], Any] = {}
    if runs:
        ids = [run["id"] for run in runs]
        for row in conn.execute(
                f"SELECT run_id, operation_key, output_json FROM run_steps WHERE run_id IN ({','.join('?' * len(ids))})"
                " AND operation_key IN (?, ?) AND status = 'succeeded' AND output_json IS NOT NULL",
                (*ids, FOLLOWUP_FOUND, FOLLOWUP_SUMMARY)):
            steps[(row["run_id"], row["operation_key"])] = json.loads(row["output_json"])
    from deixis.workflow.search import followup_search

    # A run that stopped before its found step (cancelled or failed after some admissions) is read from those
    # admissions, marked `found_partial`: its records are in the research and must not count as the first search's.
    return [{"run_id": run["id"], "turn_id": run["turn_id"], "scope_revision": run["scope_revision"],
             "status": run["status"], "created_at": run["created_at"],
             "completed_at": run["updated_at"] if run["status"] == "completed" else None,
             "found": steps.get((run["id"], FOLLOWUP_FOUND)) or followup_search.found_from(conn, research_id, run["id"]),
             "found_partial": (run["id"], FOLLOWUP_FOUND) not in steps,
             "summary": steps.get((run["id"], FOLLOWUP_SUMMARY))}
            for run in runs]


def followup_brief(run: dict[str, Any]) -> dict[str, Any]:
    """What a stored snapshot keeps of one completed follow-up search: its date, requests sent and new works."""
    requests = (run["summary"] or {}).get("requests")
    found = (run["found"] or {}).get("counts") or {}
    return {"run_id": run["run_id"], "turn_id": run["turn_id"], "created_at": run["created_at"],
            "completed_at": run["completed_at"],
            "requests": len(requests) if requests is not None else None,
            # The summary says per request whether it may have reached the provider (D92); a refusal closed before
            # sending (a spent OpenAlex budget, a missing key) was not sent.
            "requests_sent": sum(1 for r in requests if r.get("sent", r.get("status") not in NOT_SENT)) if requests is not None else None,
            "records": found.get("records"), "new_works": found.get("new")}


def followup_block(conn: Any, research_id: str, revision: int) -> list[dict[str, Any]]:
    """The follow-up searches of this question revision, each from its own frozen steps; a value a run has not
    written yet (no found or summary step) is None, never zero."""
    block = []
    for run in followup_runs(conn, research_id, revision):
        found = (run["found"] or {}).get("counts") or {}
        summary = (run["summary"] or {}).get("counts") or {}

        def value(key: str) -> Any:
            return found[key] if key in found else summary.get(key)
        block.append({"run_id": run["run_id"], "turn_id": run["turn_id"], "created_at": run["created_at"],
                      "status": run["status"], "records": value("records"), "new": value("new"),
                      "already_here": value("already_here"), "removed_before": value("removed_before"),
                      "code_decided": summary.get("code_decided"), "sent_to_model": summary.get("sent_to_model"),
                      "model_result": summary.get("model_result"), "candidates": summary.get("candidates")})
    return block


def followup_only_works(conn: Any, research_id: str, revision: int, work_of: dict[str, str],
                        discovery_found: set[str]) -> set[str]:
    """Works a follow-up search of this revision brought as new (its frozen found step) that no discovery search hit:
    the first search's funnel leaves them out. A version id maps to the work it belongs to now (`work_of`)."""
    brought: set[str] = set()
    for run in followup_runs(conn, research_id, revision):
        for work in (run["found"] or {}).get("works") or []:
            if work.get("state") == "new":
                brought |= {work_of[svid] for svid in work.get("versions") or [] if svid in work_of}
    return brought - discovery_found


def funnel(ctx: Any, flow: dict[str, Any], boxes: dict[str, Any]) -> dict[str, Any]:
    """The search step's funnel of the current revision (D233), one pool of works from the unique works down.

    `retrieved` is the rows the keyword searches returned; `chained` is the works only citation chaining found, so
    the keyword searches brought `unique - chained` works and every later stage is a subset of `unique`. None of the
    counts is "found" or "relevant". `abstracts_read` counts works a model read, not the ones queued. `candidates` are
    works with a current, not stale abstract-stage decision `candidate`, whatever a person or the full text did with them
    afterwards. `included` is the works whose head record's selection is included, the same count the lists show.

    Follow-up searches (D92) are not this search: `unique` and `candidates` leave out the works only a follow-up
    search brought (`followup_only` in the boxes), and `unique_in_research` is every work of the revision. `included`
    stays research-wide, as the lists count it."""
    box = {row["key"]: row["count"] for row in boxes["boxes"]}
    heads = ctx.facts["heads"]
    followup_only = set(boxes.get("followup_only_works") or ())
    pool = [work_id for work_id in heads if work_id not in followup_only]
    candidates = sum(1 for work_id in pool if passed_abstract(ctx, work_id))
    included = sum(1 for work_id, head in heads.items() if (ctx.selections.get(head) or {}).get("state") == "included")
    return {"retrieved": box["rows_returned"], "chained": len(ctx.chained & set(heads)),
            "unique": box["works"] - len(followup_only & set(heads)),
            "abstracts_read": box["abstract_read_by_model"], "candidates": candidates, "included": included,
            "unique_in_research": box["works"]}


def passed_abstract(ctx: Any, work_id: str) -> bool:
    """Whether the work has a current, not stale abstract-stage decision `candidate` (the funnel's `candidates`)."""
    return any(d["stage"] == "abstract" and d["outcome"] == "candidate" and not ctx.decisions.is_stale(d, ctx.facts["stale_key"])
               for d in ctx.facts["decisions"].get(work_id, []))


def machine_screening(ctx: Any, work_id: str) -> dict[str, Any]:
    """What code and the model runs decided about a work, for the Sources list's "Model proposal" column (UI parity S13).

    The work's outcome by `work_outcome`'s own rules with the person's decisions taken out: a person's choice is the
    selection, shown beside this. So two versions at opposite fresh full-text decisions stay `versions_disagree`, a
    read person's file answers for the work, a stale code decision gives way to the abstract stage, and the version
    named is the one `work_outcome` names. Only current machine decisions are merged: `work_outcome` keeps an abstract
    decision made under an earlier question or criterion (the selection rules rely on that), but this column shows what
    stands for the current one, and `stale` says that earlier decisions were left out. `passed_abstract` is the funnel's
    rule, so the list and the funnel count the same works. `stage` is None when nothing current was decided."""
    facts = ctx.facts
    machine = [d for d in facts["decisions"].get(work_id, []) if d["decided_by"] != "human"]
    current = [d for d in machine if not ctx.decisions.is_stale(d, facts["stale_key"])]
    stale = len(current) < len(machine)
    machine = current
    chosen = ctx.decisions.work_outcome(ctx.rid, work_id, {**facts, "decisions": {work_id: machine}}) or {}
    code = chosen.get("reason_code")
    # Where the reason table sends the work next: `waiting_for_pdf` and `reading_queue` say the full text was not read.
    step = "human_queue" if code == queue.VERSIONS_DISAGREE else REASON_CODES[code].next_step if code in REASON_CODES else None
    # What the reading behind the chosen full-text decision showed the model, from that decision's own row (audit item 3).
    row = next((d for d in reversed(machine) if chosen.get("stage") == "fulltext" and d["stage"] == "fulltext"
                and d["source_version_id"] == chosen.get("source_version_id") and d["reason_code"] == code), None)
    coverage = json.loads(row["read_coverage"]) if row is not None and row.get("read_coverage") else None
    return {"stage": chosen.get("stage"), "outcome": chosen.get("outcome"), "reason_code": code,
            "decided_by": chosen.get("decided_by"), "source_version_id": chosen.get("source_version_id"),
            "next_step": step, "stale": stale, "passed_abstract": passed_abstract(ctx, work_id),
            "read_coverage": coverage}


def flow_boxes(ctx: Any, flow: dict[str, Any]) -> dict[str, Any]:
    """PRISMA 2020-style boxes for the current revision, each marked incomplete; they are counts, not a diagram."""
    store, rid, revision = ctx.store, ctx.rid, ctx.revision
    conn = store.conn
    buckets = flow["buckets"]
    # The search is the research's discovery runs; a follow-up search (D92) is counted in its own block below.
    searches = [dict(row) for row in conn.execute(
        "SELECT sr.id, sr.status, sr.result_count, sr.query_text FROM search_runs sr JOIN runs r ON r.id = sr.run_id"
        " WHERE sr.research_id = ? AND sr.scope_revision = ? AND r.kind = 'discovery'", (rid, revision))]
    keyword = [s for s in searches if not s["query_text"].startswith(CHAIN_PREFIX)]
    chain = [s for s in searches if s["query_text"].startswith(CHAIN_PREFIX)]
    work_of = {row[0]: row[1] for row in conn.execute(
        "SELECT v.id, v.work_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,))}
    hit_searches: set[str] = set()
    found: set[str] = set()
    for row in conn.execute("SELECT h.source_version_id, h.search_run_id FROM candidate_hits h"
                            " JOIN search_runs sr ON sr.id = h.search_run_id JOIN runs r ON r.id = sr.run_id"
                            " WHERE h.research_id = ? AND h.scope_revision = ? AND r.kind = 'discovery'", (rid, revision)):
        hit_searches.add(row[1])
        if row[0] in work_of:
            found.add(work_of[row[0]])
    # A search that returned records and kept no hit row is from before D93: the works it found were not counted.
    counted = not any(s["result_count"] and s["status"] == "completed" and s["id"] not in hit_searches
                      for s in searches)
    abstract_read = {work_of[row[0]] for row in conn.execute(
        "SELECT DISTINCT p.source_version_id FROM model_proposals p JOIN run_steps s ON s.id = p.step_id"
        " JOIN runs r ON r.id = s.run_id WHERE p.research_id = ? AND p.stage = 'abstract' AND r.scope_revision = ?"
        f" AND r.kind IN ({','.join('?' * len(SEARCH_SCREENING_KINDS))})",
        (rid, revision, *SEARCH_SCREENING_KINDS)) if row[0] in work_of}
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
        # A work the person went on without (D46) is still one whose full text was not retrieved.
        ("fulltext_not_retrieved", buckets["waiting_for_pdf"] + buckets["abstract_by_choice"]),
        ("fulltext_read", read),
        ("not_met", flow["five"]["not_met"]),
        ("queued", buckets["queued"]),
        ("included", flow["five"]["included"]),
    ]
    return {"flow_status": FLOW_STATUS, "revision": revision,
            "boxes": [{"key": key, "count": count, "flow_status": FLOW_STATUS} for key, count in rows],
            # Each follow-up search of the revision from its own frozen steps (D92), apart from the boxes above.
            "followup_searches": followup_block(conn, rid, revision),
            # Works only a follow-up search brought: the funnel leaves them out of the first search's numbers.
            "followup_only_works": sorted(followup_only_works(conn, rid, revision, work_of, found))}
