"""Read-only adapter-session attribution; counterfactual packing is not live acceptance."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

try:
    from .replay_ranking import snapshot_path
except ImportError:
    from replay_ranking import snapshot_path

CASES = ("dbr_vbf", "kurt2017", "uwsn_kconn2022", "irs2021")


def seconds(start, finish):
    if isinstance(start, (int, float)) and isinstance(finish, (int, float)):
        return finish - start
    if isinstance(start, (int, float)):
        return datetime.fromisoformat(finish).timestamp() - start
    return (datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds()


def packed_calls(positions, size):
    """Two readings of the same observed candidates, with no new work or decisions."""
    groups = Counter((position - 1) // size for position in positions)
    return 2 * sum((count + 19) // 20 for count in groups.values())


def carried_calls(positions):
    """Ordered twenty-record groups across fetch batches; two readings per group."""
    return 2 * ((len(positions) + 19) // 20)


def collect(directory: Path):
    database = snapshot_path(directory)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    drive = json.loads((directory / "drive.json").read_text())
    rid = drive["research_id"]
    conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    rows = conn.execute(
        "SELECT m.id, m.started_at, m.finished_at, m.status, s.operation_key, i.task_type, i.attempt, i.payload_json"
        " FROM model_sessions m JOIN step_inputs i ON i.id=m.step_input_id JOIN run_steps s ON s.id=m.step_id"
        " JOIN runs r ON r.id=m.run_id WHERE m.research_id=?"
        " AND r.kind IN ('discovery','fulltext_adjudication','answer')", (rid,)).fetchall()
    tasks = defaultdict(lambda: {"calls": 0, "session_seconds": 0, "attempt_gt1": 0})
    for row in rows:
        role = tasks[row["task_type"]]
        role["calls"] += 1
        role["attempt_gt1"] += row["attempt"] > 1
        if row["started_at"] and row["finished_at"]:
            role["session_seconds"] += seconds(row["started_at"], row["finished_at"])
    for role in tasks.values():
        role["session_seconds"] = round(role["session_seconds"], 3)
    steps = [dict(row) for row in conn.execute(
        "SELECT s.* FROM run_steps s JOIN runs r ON r.id=s.run_id WHERE r.research_id=? AND r.kind='discovery'", (rid,))]
    chains = [s for s in steps if s["kind"].startswith("provider_chain:")]
    timed_chains = [s for s in chains if s["started_at"] and s["finished_at"]]
    abstracts = [r for r in rows if r["task_type"] == "abstract_screening"]
    adjudicated_sources = {s["source_id"] for r in rows if r["task_type"] == "fulltext_adjudication"
                           for s in json.loads(r["payload_json"])["sources"]}
    adjudicated_works = {r["work_id"] for r in conn.execute("SELECT id,work_id FROM source_versions")
                        if r["id"] in adjudicated_sources} if adjudicated_sources else set()
    listing_step = next((s for s in steps if s["operation_key"] == "small_batch:v1:list"), None)
    seeds_step = next((s for s in steps if s["operation_key"] == "chain_seeds"), None)
    packing = None
    if listing_step:
        listing = json.loads(listing_step["output_json"])
        positions = {version: item["position"] for item in listing["items"] for version in item["versions"]}
        candidates = {r["id"]: r["source_version_id"] for r in conn.execute(
            "SELECT id, source_version_id FROM candidates WHERE research_id=?", (rid,))}
        sent = {candidates[c["candidate_id"]] for r in abstracts
                for c in json.loads(r["payload_json"])["candidates"]}
        missing = sent - positions.keys()
        if missing:
            raise ValueError("Sent abstract is absent from the frozen list")
        actual_positions = [positions[svid] for svid in sent]
        packing = {"observed_unique_abstracts": len(sent), "calls_at_30": packed_calls(actual_positions, 30),
                   "calls_at_40": packed_calls(actual_positions, 40),
                   "ideal_global_calls": carried_calls(actual_positions),
                   "carried_abstract_calls": carried_calls(actual_positions),
                   "basis": "same observed candidates; changed screening/fetch/model decisions and elapsed time unmeasured"}
    searches = [dict(r) for r in conn.execute(
        "SELECT q.provider,q.query_text,q.status,q.result_count,q.page_number,s.operation_key"
        " FROM search_runs q JOIN run_steps s ON s.id=q.step_id WHERE q.research_id=?"
        " AND (s.operation_key='search:0' OR s.operation_key LIKE 'search:0:page:%'"
        " OR s.operation_key='search:6' OR s.operation_key LIKE 'search:6:page:%')", (rid,))]
    query_input = conn.execute(
        "SELECT id,payload_json FROM step_inputs WHERE research_id=? AND task_type='search_query' ORDER BY created_at LIMIT 1",
        (rid,)).fetchone()
    query_envelope = None
    if query_input:
        payload = json.loads(query_input["payload_json"])
        query_envelope = {"step_input_id": query_input["id"], "budget": payload["budget"],
                          "skill_package_hash": payload["skill_package_hash"],
                          "question_sha256": hashlib.sha256(payload["question"]["text"].encode()).hexdigest()}
    first_abstract = min((r["started_at"] for r in abstracts), default=None)
    allocation = conn.execute(
        "SELECT s.output_json FROM run_steps s JOIN runs r ON r.id=s.run_id"
        " WHERE r.research_id=? AND s.operation_key='small_batch:v1:answer_input'", (rid,)).fetchone()
    conn.close()
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("Original snapshot changed")
    return {"research_id": rid, "snapshot_sha256": before, "unchanged": True, "tasks": dict(tasks),
            "calls": len(rows), "adjudicated_work_count": len(adjudicated_works),
            "elapsed_seconds": seconds(drive["discovery_started"], drive["answer_done"]),
            "chain_step_records": len(chains), "chain_timed_step_records": len(timed_chains),
            "chain_elapsed_seconds": seconds(min(s["started_at"] for s in timed_chains),
                                              max(s["finished_at"] for s in timed_chains)) if timed_chains else 0,
            "first_abstract_seconds": seconds(drive["discovery_started"], first_abstract) if first_abstract else None,
            "preinspection_chain_phase_seconds": seconds(seeds_step["started_at"], listing_step["finished_at"])
            if listing_step and seeds_step else None,
            "packing": packing, "searches": searches, "search_query_envelope": query_envelope,
            "allocation": json.loads(allocation[0]) if allocation else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--new-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = {}
    lines = ["# Adapter sessions: round 2 → small batch", "",
             "Counts are recorded adapter sessions, not provider sends. Session durations may overlap and must not be added to wall time.", ""]
    for case in CASES:
        old, new = collect(args.baseline_root / case), collect(args.new_root / case)
        results[case] = {"baseline": old, "small_batch": new}
        packing = new["packing"]
        if packing:
            abstract = packing["carried_abstract_calls"]
            adjudication = new["tasks"].get("fulltext_adjudication", {}).get("calls", 0)
            other = new["calls"] - new["tasks"].get("abstract_screening", {}).get("calls", 0) - adjudication
            old_adjudication = old["tasks"].get("fulltext_adjudication", {}).get("calls", 0)
            old_non_adjudication = old["calls"] - old_adjudication
            results[case]["carried_projection"] = {
                "abstract": abstract, "adjudication": adjudication, "other": other,
                "total": abstract + adjudication + other,
                "non_adjudication_ratio": (abstract + other) / old_non_adjudication,
                "baseline_adjudication_calls_per_work": old_adjudication / old["adjudicated_work_count"],
                "adjudication_calls_per_work": adjudication / new["adjudicated_work_count"],
                "basis": "same supplied candidates and fixed other sessions; no new run or elapsed-time estimate"}
            lines += [f"Carried projection: abstract {abstract}, adjudication {adjudication}, other {other}, "
                      f"total {abstract + adjudication + other}; non-adjudication ratio "
                      f"{(abstract + other) / old_non_adjudication:.3f}. No live acceptance claim.", ""]
        lines += [f"## {case}", "", "| Task | Calls old → new | Delta | Session seconds old → new |",
                  "|---|---:|---:|---:|"]
        for task in sorted(old["tasks"].keys() | new["tasks"].keys()):
            a, b = old["tasks"].get(task, {}), new["tasks"].get(task, {})
            lines.append(f"| {task} | {a.get('calls',0)} → {b.get('calls',0)} | {b.get('calls',0)-a.get('calls',0):+} | "
                         f"{a.get('session_seconds',0):.1f} → {b.get('session_seconds',0):.1f} |")
        p = new["packing"]
        lines += ["", f"Total {old['calls']} → {new['calls']}; elapsed {old['elapsed_seconds']:.1f} → {new['elapsed_seconds']:.1f} s.",
                  f"Chain step records {old['chain_step_records']} → {new['chain_step_records']} "
                  f"(timed {old['chain_timed_step_records']} → {new['chain_timed_step_records']}); "
                  f"chain span {old['chain_elapsed_seconds']:.1f} → {new['chain_elapsed_seconds']:.1f} s; "
                  f"first abstract {old['first_abstract_seconds']:.1f} → {new['first_abstract_seconds']:.1f} s.",
                  f"Same-candidate packing only: {p['observed_unique_abstracts']} abstracts; at 30: {p['calls_at_30']} calls, at 40: {p['calls_at_40']}, global lower bound: {p['ideal_global_calls']}. No corrected live time or acceptance claim.", ""]
        lines += [f"Serial chain→list phase before any abstract: {new['preinspection_chain_phase_seconds']:.1f} s. "
                  "Overlapping keyword-only reads would change eligibility before this list is frozen; not enabled.", ""]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    args.output.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
