"""What completing OpenAlex with Semantic Scholar changed, read from stored rows alone.

The design asks for three arms compared at the same total record, time and reranker budget: OpenAlex alone, OpenAlex
with a conditional snippet search, and OpenAlex with a snippet search on every question. Each run freezes the arm it
was queued with, so this tool groups the runs by their question, depth and total record budget, takes the latest
completed `off` run of that group as the reference, and reports for every other arm the works **added to** and **dropped from** the first fifty of the frozen
list, the share of questions whose condition fired, and the time the runs took.

It also keeps the two older operations apart, which the design asks for by name: how many abstracts the batch lookup
of works with a known DOI added, and how many records the bulk query brought. Those are not this arm and are never
counted as its contribution.

It reads stored rows only: no model call, no provider request, no judgement of whether the works added are better.
A work entering the first fifty is a change in the list, not evidence that the answer improved; that needs the
answer-quality measurement, which is not in here.

Usage:
    uv run python scripts/benchmark/completion_arms.py <library.sqlite3> [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

TOP = 50  # the window the design reports added and dropped works in
RELEVANCE_KEY = "search:fast:s2_relevance"
SNIPPET_PREFIX = "search:fast:s2_snippet:"
BULK_KEY = "search:fast:s2_bulk"
ARMS = ("off", "conditional", "always")


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _ms(start: str, end: str) -> int:
    """Milliseconds between two stored timestamps, parsed rather than computed in SQL (see delivery_time.py)."""
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(0, delta // timedelta(milliseconds=1))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One row per discovery run, with the arm it froze and what that arm did.

    A run whose policy names no completion block is the `off` arm: the absence of the key is that arm, so runs from
    before the rule are the reference the others are compared against rather than being left out.
    """
    out = []
    for row in _rows(conn, "SELECT r.id, r.research_id, r.scope_revision, r.status, r.budget_json, r.created_at,"
                           " s.question FROM runs r JOIN scope_revisions s ON s.research_id = r.research_id"
                           " AND s.revision = r.scope_revision WHERE r.kind = 'discovery' ORDER BY r.created_at"):
        policy = (json.loads(row["budget_json"] or "{}").get("fast_path") or {})
        block = policy.get("completion") or {}
        record = {
            "run_id": row["id"], "research_id": row["research_id"], "revision": row["scope_revision"],
            "question": row["question"], "status": row["status"], "created_at": row["created_at"],
            "effort": policy.get("mode"), "arm": block.get("arm", "off"),
            "records_reserved": block.get("records", 0), "snippet_requests": block.get("snippet_requests", 0),
            "keyword_cap": policy.get("keyword_record_cap"),
        }
        record |= requests_of(conn, row["id"])
        record |= aside(conn, row["id"])
        record["top"] = top_works(conn, row["id"])
        record["elapsed_ms"] = elapsed_of(conn, row["id"])
        out.append(record)
    return out


def requests_of(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """What each request of the arm came to: triggered, sent, or not sent with the recorded reason.

    "Triggered" and "sent" are counted apart on purpose: a condition that fired and then found no record budget or no
    time left is a different result from one that never fired, and reporting only what was sent would hide it.
    """
    relevance: dict[str, Any] = {"state": None, "sent": False, "reason": None, "records": 0, "request_status": None}
    snippets: list[dict[str, Any]] = []
    for row in _rows(conn, "SELECT s.operation_key, s.status, s.error_code, s.output_json,"
                           " sr.status AS request_status, sr.result_count FROM run_steps s"
                           " LEFT JOIN search_runs sr ON sr.step_id = s.id"
                           " WHERE s.run_id = ? AND (s.operation_key = ? OR s.operation_key LIKE ?)"
                           " ORDER BY s.operation_key", run_id, RELEVANCE_KEY, SNIPPET_PREFIX + "%"):
        output = json.loads(row["output_json"] or "{}")
        # A request that reached the provider and was refused was still sent: the search run it recorded says so,
        # while the step's own status would count it with the requests that never went out.
        sent = row["request_status"] is not None
        entry = {"sent": sent, "request_status": row["request_status"],
                 "reason": None if sent else (row["error_code"] or output.get("stop_reason")),
                 "records": (row["result_count"] or 0) if sent else 0}
        if row["operation_key"] == RELEVANCE_KEY:
            observed = output.get("openalex") or {}
            relevance = entry | {"state": observed.get("state"), "failures": observed.get("failures") or {}}
        else:
            gate = output.get("gate") or {}
            snippets.append(entry | {"covered": gate.get("covered"), "concept": (output.get("focused") or {}).get("term"),
                                     "snippets": output.get("snippets") or 0,
                                     "works_linked": output.get("snippet_works") or 0,
                                     "works_unlinked": output.get("snippet_works_unlinked") or 0})
    return {
        "fallback": relevance,
        "snippet_steps": snippets,
        # The condition fired when the gate found the part of the question unmet; a step whose gate was never reached
        # records None and is neither.
        "snippet_triggered": sum(1 for s in snippets if s["covered"] is False),
        "snippet_sent": sum(1 for s in snippets if s["sent"]),
        "snippet_unsent_reasons": sorted({s["reason"] for s in snippets if not s["sent"] and s["reason"]}),
        "arm_records": relevance["records"] + sum(s["records"] for s in snippets),
    }


def aside(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """The two operations the design wants kept apart from this arm: the batch abstract lookup of works whose DOI is
    known, and the bulk query. Neither is the completion arm and neither is counted as its contribution."""
    added = 0
    asked = 0
    for row in _rows(conn, "SELECT output_json FROM run_steps WHERE run_id = ?"
                           " AND operation_key LIKE 'record_lookup:semantic_scholar:%'", run_id):
        output = json.loads(row["output_json"] or "{}")
        added += output.get("abstracts_filled") or 0
        asked += output.get("asked") or 0
    bulk = _rows(conn, "SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?", run_id, BULK_KEY)
    bulk_records = json.loads(bulk[0]["output_json"] or "{}").get("result_count") or 0 if bulk else 0
    return {"abstract_lookup": {"asked": asked, "abstracts_added": added}, "bulk_records": bulk_records}


def top_works(conn: sqlite3.Connection, run_id: str, top: int = TOP) -> list[str]:
    """The works at the head of the list this run froze, best first, by work rather than by record: the same work
    found as a preprint in one run and as the published version in another is one work in both."""
    rows = _rows(conn, "SELECT v.work_id FROM record_signal_ranks k JOIN run_steps s ON s.id = k.ranking_step_id"
                       " JOIN source_versions v ON v.id = k.source_version_id"
                       " WHERE s.run_id = ? AND k.signal = 'inspection' ORDER BY k.rank", run_id)
    works: list[str] = []
    for row in rows:
        if row["work_id"] not in works:
            works.append(row["work_id"])
        if len(works) == top:
            break
    return works


def elapsed_of(conn: sqlite3.Connection, run_id: str) -> int | None:
    """How long this run took from the question's submission to its last stage interval, or None where nothing is
    recorded. It is the run's own span, not the delivery time to a recorded answer; `delivery_time.py` reports that."""
    row = _rows(conn, "SELECT l.started_at, MAX(COALESCE(i.closed_at, i.last_checkpoint_at)) AS last"
                      " FROM fast_path_ledgers l LEFT JOIN fast_path_intervals i ON i.run_id = l.ledger_run_id"
                      " WHERE l.ledger_run_id = ?", run_id)
    if not row or row[0]["started_at"] is None or row[0]["last"] is None:
        return None
    return _ms(row[0]["started_at"], row[0]["last"])


def _key(record: dict[str, Any]) -> tuple[Any, ...]:
    """What makes two runs comparable: the same question, the same depth and the same total record budget.

    The arm's reservation comes off the keyword cap, so the two added together are the depth's own total; a run read
    at another depth, or under another cap, answers a different question of the design and is not a reference.
    """
    return (record["question"], record["effort"],
            (record["keyword_cap"] or 0) + (record["records_reserved"] or 0))


def comparison(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per comparable group and arm, the works this arm's first fifty added over the `off` arm's and the ones it
    dropped, and the runs that had no reference to compare against.

    Only a **completed** run is read on either side: a paused or failed run froze part of a list, and comparing it
    with a whole one would report the interruption as a loss. A group with no completed `off` run of the same depth
    and budget is not compared at all; it is returned in the second list with the reason, so the reading can never
    look as if every question had a reference.
    """
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(_key(record), []).append(record)
    out, skipped = [], []
    for key, group in sorted(groups.items(), key=lambda item: str(item[0])):
        question, effort, budget = key
        # The latest completed OpenAlex-alone run of the group is the reference; how many there were is reported, so
        # a group with several can be read as such instead of silently taking the first.
        references = [r for r in group if r["arm"] == "off" and r["status"] == "completed"]
        reference = references[-1] if references else None
        base = set(reference["top"]) if reference else None
        for record in group:
            if record["arm"] == "off":
                continue
            row = {"question": question, "effort": effort, "record_budget": budget, "arm": record["arm"],
                   "run_id": record["run_id"], "snippet_triggered": record["snippet_triggered"],
                   "snippet_sent": record["snippet_sent"], "fallback_sent": record["fallback"]["sent"],
                   "arm_records": record["arm_records"], "elapsed_ms": record["elapsed_ms"],
                   "reference_run_id": reference["run_id"] if reference else None,
                   "references_available": len(references)}
            if record["status"] != "completed":
                skipped.append(row | {"reason": "run_" + str(record["status"])})
                continue
            if base is None:
                skipped.append(row | {"reason": "no_completed_off_run"})
                continue
            top = set(record["top"])
            out.append(row | {"added": sorted(top - base), "dropped": sorted(base - top)})
    return out, skipped


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def summary(records: list[dict[str, Any]], pairs: list[dict[str, Any]],
            skipped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One block per arm: how many runs, what fired, what was sent, what the list gained and lost, and the time."""
    out: dict[str, Any] = {"arms": {}, "aside": {"abstracts_added": sum(r["abstract_lookup"]["abstracts_added"] for r in records),
                                                  "lookups_asked": sum(r["abstract_lookup"]["asked"] for r in records),
                                                  "bulk_records": sum(r["bulk_records"] for r in records)}}
    for arm in ARMS:
        group = [r for r in records if r["arm"] == arm]
        if not group:
            continue
        compared = [p for p in pairs if p["arm"] == arm]
        unmatched = [p for p in (skipped or []) if p["arm"] == arm]
        times = [r["elapsed_ms"] for r in group if r["elapsed_ms"] is not None]
        triggered = sum(1 for r in group
                        if r["snippet_triggered"] or r["snippet_sent"] or r["fallback"]["sent"])
        out["arms"][arm] = {
            "runs": len(group),
            "questions_compared": len(compared),
            # Named, not dropped: a reading that hides what it could not compare invites a conclusion it cannot carry.
            "questions_not_compared": len(unmatched),
            "not_compared_reasons": _tally(p["reason"] for p in unmatched),
            "questions_triggered": triggered,
            "snippet_requests_sent": sum(r["snippet_sent"] for r in group),
            "snippet_unsent_reasons": sorted({reason for r in group for reason in r["snippet_unsent_reasons"]}),
            "fallbacks_sent": sum(1 for r in group if r["fallback"]["sent"]),
            "openalex_states": _tally(r["fallback"]["state"] for r in group),
            "records_from_the_arm": sum(r["arm_records"] for r in group),
            "passages_found": sum(s["snippets"] for r in group for s in r["snippet_steps"]),
            "passages_without_a_record": sum(s["works_unlinked"] for r in group for s in r["snippet_steps"]),
            "added_to_the_first_50": sum(len(p["added"]) for p in compared) or 0,
            "dropped_from_the_first_50": sum(len(p["dropped"]) for p in compared) or 0,
            "median_ms": int(statistics.median(times)) if times else None,
            "p95_ms": _p95(times),
        }
    return out


def _tally(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _print(report: dict[str, Any]) -> None:
    aside_counts = report["aside"]
    print(f"Read at {_now()}")
    print(f"Kept apart: the batch abstract lookup asked for {aside_counts['lookups_asked']} works and added"
          f" {aside_counts['abstracts_added']} abstracts; the bulk query brought {aside_counts['bulk_records']} records."
          " Neither is this arm.")
    if not report["arms"]:
        print("No discovery run in this library.")
        return
    for arm, block in report["arms"].items():
        print(f"\n{arm}: {block['runs']} runs, {block['questions_triggered']} of them with a request of the arm sent"
              f" or its condition fired")
        print(f"  requests: {block['fallbacks_sent']} fallback, {block['snippet_requests_sent']} snippet"
              f" ({block['records_from_the_arm']} records, {block['passages_found']} passages,"
              f" {block['passages_without_a_record']} of them with no record)")
        if block["snippet_unsent_reasons"]:
            print(f"  snippet requests not sent because: {', '.join(block['snippet_unsent_reasons'])}")
        if block["openalex_states"]:
            print(f"  what OpenAlex came to: {block['openalex_states']}")
        if arm != "off":
            print(f"  against the completed OpenAlex-alone run of the same question, depth and record budget"
                  f" ({block['questions_compared']} questions): {block['added_to_the_first_50']} works added to the"
                  f" first {TOP}, {block['dropped_from_the_first_50']} dropped")
            if block["questions_not_compared"]:
                print(f"  {block['questions_not_compared']} runs had no reference to compare against:"
                      f" {block['not_compared_reasons']}")
        print(f"  run span: median {block['median_ms']} ms, p95 {block['p95_ms']} ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library")
    parser.add_argument("--json", action="store_true", help="print the whole reading as JSON")
    args = parser.parse_args(argv)
    conn = sqlite3.connect(f"file:{args.library}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        records = runs(conn)
        pairs, skipped = comparison(records)
        report = summary(records, pairs, skipped)
    finally:
        conn.close()
    if args.json:
        print(json.dumps({"runs": records, "questions": pairs, "not_compared": skipped, "summary": report},
                         indent=1, sort_keys=True))
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
