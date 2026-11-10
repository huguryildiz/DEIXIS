"""How long a research took to reach its first sourced answer, read from stored rows alone.

The design gives each depth an end-to-end target for the first sourced answer (1, 2 and 5 minutes) and a moment
by which the run must turn to writing it (35 s, 1 min 10 s, 3 min 30 s). Both count on the person's own clock,
from the question's submission, so the queue, the gaps between stages and any pause are inside them.

What this tool measures is the time **to the answer being recorded**, not to it being on the person's screen: the
database holds the moment the answer row was written and nothing times the display. Every rate it reports is
therefore named a rate to the record, and the design's delivery rate needs a measurement taken in the client.

It reads stored rows only: no model call, no provider request, no judgement of whether an answer is good. Whether
each pre-written answer element is actually covered, and whether the cited passage really supports the claim, are
not in here; a located citation anchor says the citation was placed in evidence the step was given, which is a
structural fact and not support.

Usage:
    uv run python scripts/benchmark/delivery_time.py <library.sqlite3> [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# The stages whose end is the handover to answer writing, and the one that follows it.
HANDOVER_STAGE = "read"


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _now() -> str:
    """Now, in the format the library stores."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _ms(start: str, end: str) -> int:
    """Milliseconds between two stored timestamps. Parsed rather than computed with SQLite's `julianday`, whose
    floating point loses a millisecond and would put a run sitting exactly on its target just outside it."""
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(0, delta // timedelta(milliseconds=1))


# A run in one of these states will send nothing more, so whether it met its target is settled. A run still
# running, queued or paused may yet publish an answer, and is left undecided rather than counted as a miss.
TERMINAL = ("completed", "failed", "cancelled")


def ledgers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One row per discovery run that carries a fast-path ledger, with its target, its handover and what it reached.

    A run on a model this computer runs is marked `local`: it keeps no read or answer deadline and no handover, so it
    is reported apart rather than counted against a target it was never given.

    Whether a run met its target is settled for every run that will send nothing more, not only for the ones that
    published: a run that ended with an unverified draft, with no evidence, or with no answer at all gave the person
    no sourced answer inside the target, so it missed it. Counting only the runs that published would report the rate
    among the runs that succeeded, which is not the rate the design asks for.
    """
    out: list[dict[str, Any]] = []
    for row in _rows(conn, "SELECT l.*, r.budget_json, r.status AS discovery_status FROM fast_path_ledgers l"
                           " JOIN runs r ON r.id = l.ledger_run_id ORDER BY l.started_at"):
        policy = (json.loads(row["budget_json"]).get("fast_path") or {})
        target, handover = policy.get("total_ms"), policy.get("handover_ms")
        # When writing actually began: the answer stage opening, not the read stage closing.
        answer_started = conn.execute(
            "SELECT MIN(started_at) FROM fast_path_intervals WHERE ledger_run_id = ? AND stage = 'answer'",
            (row["ledger_run_id"],)).fetchone()[0]
        answer_status = conn.execute("SELECT status FROM runs WHERE id = ?", (row["answer_run_id"],)).fetchone() \
            if row["answer_run_id"] else None
        published = row["answer_published_at"]
        record = {
            "ledger_run_id": row["ledger_run_id"], "research_id": row["research_id"], "mode": row["mode"],
            "local": policy.get("handover") == "none_local_model",
            # A research asking only for papers, a table, a comparison or a check of its own sentence queues no
            # answer of its own (`fast_path.with_intent`). It is held to no delivery target: counting it as a miss
            # would push the rate down by how often those intents are used.
            "no_answer_intended": policy.get("auto_answer") is False,
            "target_ms": target if isinstance(target, int) else None,
            "handover_ms": handover if isinstance(handover, int) else None,
            "answer_outcome": row["answer_outcome"],
            "handover_passed_at": row["handover_passed_at"],
            "to_record_ms": _ms(row["started_at"], published) if published else None,
            "handover_at_ms": _ms(row["started_at"], answer_started) if answer_started else None,
            "anchors": anchors(conn, row["answer_run_id"]) if row["answer_run_id"] else None,
            "stage_ms": {s["stage"]: s["used_ms"] for s in
                         _rows(conn, "SELECT stage, used_ms FROM fast_path_stages WHERE ledger_run_id = ? AND seq > 0"
                                     " ORDER BY seq", row["ledger_run_id"])},
        }
        # Settled once no further answer can arrive: the answer run reached a terminal state, or none was ever
        # queued and discovery itself ended.
        ended = (answer_status["status"] in TERMINAL if answer_status
                 else row["discovery_status"] in TERMINAL)
        # The same rule the run's own view applies: a valid answer recorded inside the target, otherwise a miss once
        # the target has passed or the run has ended without one. A run still working whose target has already gone
        # by cannot meet it with a later answer, so leaving it out would report the rate among the quick ones. This
        # tool reads a library after the fact, so now is the clock the elapsed time is read against.
        if record["no_answer_intended"] or record["local"]:
            # A model this computer runs was given no handover and no deadline on the stages where it works, so it
            # is held to no delivery target either; its times are reported on their own.
            record["on_target_to_record"] = None
        elif record["to_record_ms"] is not None and record["target_ms"]:
            record["on_target_to_record"] = record["to_record_ms"] <= record["target_ms"]
        elif record["target_ms"] and (ended or _ms(row["started_at"], _now()) > record["target_ms"]):
            record["on_target_to_record"] = False
        else:
            record["on_target_to_record"] = None
        record["settled"] = record["on_target_to_record"] is not None
        record["handover_on_target"] = (record["handover_at_ms"] <= record["handover_ms"]
                                        if record["handover_at_ms"] is not None and record["handover_ms"] else None)
        out.append(record)
    return out


def anchors(conn: sqlite3.Connection, answer_run_id: str) -> dict[str, int] | None:
    """How many of a published answer's citations were located in the evidence the step was given. This is a
    structural fact and not support: an anchor says the quoted words were found in a passage the model read, never
    that the passage backs the claim. Whether a claim is actually supported is judged over the passages themselves,
    which is not this tool's work."""
    answer = conn.execute("SELECT id FROM answers WHERE run_id = ? AND status = 'structurally_valid'"
                          " ORDER BY created_at LIMIT 1", (answer_run_id,)).fetchone()
    if answer is None:
        return None
    row = conn.execute(
        "SELECT COUNT(*) AS links, SUM(CASE WHEN e.anchor_match IS NOT NULL THEN 1 ELSE 0 END) AS located"
        " FROM evidence_links e JOIN claims c ON c.id = e.claim_id WHERE c.answer_id = ?", (answer["id"],)).fetchone()
    return {"links": row["links"], "located": row["located"] or 0}


def reports(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The detailed report's own time, measured apart from the first answer: from the request being queued
    (`reports.created_at`) to the report finalizing (`report_finalized`). `reports.updated_at` is not used, because a
    later edit moves it."""
    out: list[dict[str, Any]] = []
    for row in _rows(conn, "SELECT * FROM reports ORDER BY created_at"):
        done = conn.execute(
            "SELECT created_at, payload_json FROM events WHERE type = 'report_finalized' AND research_id = ?"
            " ORDER BY id", (row["research_id"],)).fetchall()
        mine = [(e["created_at"], json.loads(e["payload_json"])) for e in done]
        mine = [(at, p) for at, p in mine if p.get("report_id") == row["id"]]
        # The event that produced the status this report now holds; a draft finalization that a valid one followed is
        # not when this report became ready.
        finalized = next((at for at, p in reversed(mine) if p.get("status") == row["status"]), None)
        out.append({"report_id": row["id"], "research_id": row["research_id"], "status": row["status"],
                    "report_version": row["report_version"],
                    "to_finalized_ms": _ms(row["created_at"], finalized) if finalized else None})
    return out


def _share(values: list[bool | None]) -> dict[str, Any]:
    decided = [v for v in values if v is not None]
    return {"n": len(decided), "met": sum(decided),
            "rate": round(sum(decided) / len(decided), 3) if decided else None}


def summary(rows: list[dict[str, Any]], report_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per mode: how many runs, how many recorded a valid answer, the time to the record, and how the run stood
    against its own target and handover. Local runs are summarized apart, under `local`."""
    def group(group_rows: list[dict[str, Any]]) -> dict[str, Any]:
        latencies = [r["to_record_ms"] for r in group_rows if r["to_record_ms"] is not None]
        handovers = [r["handover_at_ms"] for r in group_rows if r["handover_at_ms"] is not None]
        stages = {}
        for stage in ("plan", "search", "ranking", "read", "answer"):
            used = [r["stage_ms"][stage] for r in group_rows if stage in r["stage_ms"]]
            if used:
                stages[stage] = {"median_ms": int(statistics.median(used)), "worst_ms": max(used)}
        located = [r["anchors"] for r in group_rows if r["anchors"]]
        return {
            "runs": len(group_rows),
            "still_running": sum(1 for r in group_rows if not r["settled"]),
            "missed_during_the_run": sum(1 for r in group_rows if r["handover_passed_at"]),
            "valid_answers": sum(1 for r in group_rows if r["answer_outcome"] == "structurally_valid"),
            "citations": {"links": sum(a["links"] for a in located), "located": sum(a["located"] for a in located)}
            if located else None,
            "target_ms": next((r["target_ms"] for r in group_rows if r["target_ms"]), None),
            "handover_ms": next((r["handover_ms"] for r in group_rows if r["handover_ms"]), None),
            "to_record_median_ms": int(statistics.median(latencies)) if latencies else None,
            "to_record_worst_ms": max(latencies) if latencies else None,
            "on_target_to_record": _share([r["on_target_to_record"] for r in group_rows]),
            "handover_at_median_ms": int(statistics.median(handovers)) if handovers else None,
            "handover_on_target": _share([r["handover_on_target"] for r in group_rows]),
            "stages": stages,
        }

    timed = [r for r in rows if not r["local"] and not r["no_answer_intended"]]
    modes = {mode: group([r for r in timed if r["mode"] == mode]) for mode in sorted({r["mode"] for r in timed})}
    local_rows = [r for r in rows if r["local"] and not r["no_answer_intended"]]
    finalized = [r["to_finalized_ms"] for r in report_rows if r["to_finalized_ms"] is not None]
    return {
        "measured": "to the answer being recorded, not to it being on screen",
        "modes": modes,
        "local": group(local_rows) | {"note": "no read or answer deadline and no handover; not held to a target"}
        if local_rows else None,
        # Researches asking only for papers, a table, a comparison or a sentence check: no answer was queued, so
        # there is no delivery to time.
        "no_answer_intended": sum(1 for r in rows if r["no_answer_intended"]),
        "reports": {"n": len(report_rows), "finalized": len(finalized),
                    "to_finalized_median_ms": int(statistics.median(finalized)) if finalized else None,
                    "to_finalized_worst_ms": max(finalized) if finalized else None},
    }


def _line(label: str, group: dict[str, Any]) -> str:
    target = group["target_ms"]
    rate = group["on_target_to_record"]["rate"]
    return (f"{label:<10} runs {group['runs']:>3}  valid {group['valid_answers']:>3}"
            f"  target {'-' if target is None else f'{target // 1000}s':>5}"
            f"  median {'-' if group['to_record_median_ms'] is None else f'{group['to_record_median_ms'] // 1000}s':>6}"
            f"  worst {'-' if group['to_record_worst_ms'] is None else f'{group['to_record_worst_ms'] // 1000}s':>6}"
            f"  on target {'-' if rate is None else f'{rate:.0%}'} ({group['on_target_to_record']['met']}"
            f"/{group['on_target_to_record']['n']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("library", help="path to a DEIXIS library (sqlite3)")
    parser.add_argument("--json", action="store_true", help="print the whole summary as JSON")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.library}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = summary(ledgers(conn), reports(conn))
    finally:
        conn.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print("Time to the first sourced answer being RECORDED (the display is not timed here).")
    print("The on-target rate counts every run that will send nothing more, a run that never answered included;")
    print("a research that queues no answer of its own is left out of it entirely.")
    for mode, group in result["modes"].items():
        print(_line(mode, group))
    if result["local"]:
        print(_line("local", result["local"]))
    reports_summary = result["reports"]
    median = reports_summary["to_finalized_median_ms"]
    print(f"\nDetailed reports, measured apart: {reports_summary['finalized']}/{reports_summary['n']} finalized"
          f", median {'-' if median is None else f'{median // 1000}s'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
