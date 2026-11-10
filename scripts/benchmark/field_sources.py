"""What each field source really contributed to the runs in a library, read offline.

    uv run python scripts/benchmark/field_sources.py <library.sqlite> [--research RESEARCH_ID] [--json]

Standard and Detailed searches one field source beside OpenAlex: the one whose fields hold the largest share of the
question's records. This reader says, per discovery run, which source that was, the share that chose it, how many
records its reply brought, how many works of the run's corpus it found, and how many of those no other source's
search found anywhere in that run. The last number is the observed contribution of that one request: it is what was
seen in these runs, not a measurement of whether the source helps in general, and nothing here calls it one.

A source that was not searched is listed with the reason its run stored (another source's fields held more of the
question, the depth searches none, no query was compiled, the person left it out). A run frozen before the field
block existed has nothing to report and is skipped.

The library is opened read-only and nothing is written. Pass a copy, never the owner's own library.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from deixis.domain.rules import SOURCE_ROUTES

FIELD_CLASS = 2


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def works_by_provider(conn: sqlite3.Connection, run_id: str) -> dict[str, set[str]]:
    """The works each source's searches found in this run, after the work merge (`candidate_hits` keeps them all)."""
    found: dict[str, set[str]] = {}
    for row in conn.execute(
            "SELECT sr.provider, v.work_id FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
            " JOIN source_versions v ON v.id = h.source_version_id WHERE sr.run_id = ?", (run_id,)):
        found.setdefault(row["provider"], set()).add(row["work_id"])
    return found


def plan_of(conn: sqlite3.Connection, research_id: str, run_id: str) -> dict[str, Any] | None:
    """The search plan this run itself froze, read by the hash its protocol step recorded."""
    step = conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = 'protocol'"
                        " AND status = 'succeeded'", (run_id,)).fetchone()
    digest = (json.loads(step["output_json"] or "{}") or {}).get("protocol_hash") if step else None
    if not digest:
        return None
    row = conn.execute("SELECT body_json FROM protocol_records WHERE research_id = ? AND body_sha256 = ?",
                       (research_id, digest)).fetchone()
    return json.loads(row["body_json"]) if row else None


def run_report(conn: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any] | None:
    body = plan_of(conn, run["research_id"], run["id"])
    plan = (body or {}).get("fast_path_search") or {}
    if "field" not in plan:
        return None
    routing = (body or {}).get("source_routing") or {}
    shares = {row["provider_id"]: row.get("share")
              for row in [*routing.get("chosen", []), *routing.get("left_out", [])]}
    reasons = {row["provider_id"]: row["reason"] for row in routing.get("left_out", [])}
    reasons |= {row["query"]["provider_id"]: row["reason"] for row in plan.get("dropped", [])}
    reasons |= plan.get("field_not_compiled") or {}
    everywhere = works_by_provider(conn, run["id"])
    rows = []
    for spec in plan["field"]:
        provider = spec["query"]["provider_id"]
        replies = conn.execute("SELECT status, result_count FROM search_runs WHERE run_id = ? AND provider = ?"
                               " AND request_class = ?", (run["id"], provider, FIELD_CLASS)).fetchall()
        others = set().union(*(w for p, w in everywhere.items() if p != provider)) if everywhere else set()
        works = everywhere.get(provider, set())
        rows.append({"provider_id": provider, "state": "searched" if replies else "planned",
                     "share": spec.get("share"), "records_allowed": spec["records"],
                     "records": sum(r["result_count"] for r in replies if r["status"] == "completed"),
                     "requests": len(replies), "works": len(works), "only": len(works - others)})
    for provider in SOURCE_ROUTES:
        if provider in {row["provider_id"] for row in rows} or provider not in reasons:
            continue
        rows.append({"provider_id": provider, "state": "not_searched", "share": shares.get(provider),
                     "reason": reasons[provider]})
    return {"run_id": run["id"], "research_id": run["research_id"], "question": run["question"],
            "mode": ((json.loads(run["budget_json"]) or {}).get("fast_path") or {}).get("mode"), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--research", default=None, help="one research's runs only")
    parser.add_argument("--json", action="store_true", help="print the rows as JSON instead of text")
    args = parser.parse_args()
    conn = connect(args.library)
    runs = conn.execute(
        "SELECT r.id, r.research_id, r.budget_json, v.question FROM runs r JOIN scope_revisions v"
        " ON v.research_id = r.research_id AND v.revision = r.scope_revision"
        " WHERE r.kind = 'discovery' ORDER BY r.created_at").fetchall()
    reports = [report for run in runs if (args.research is None or run["research_id"] == args.research)
               and (report := run_report(conn, run)) is not None]
    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))
        return
    if not reports:
        print("No run in this library froze a field-source plan.")
        return
    for report in reports:
        print(f"\n{report['run_id']}  {report['mode'] or '?'}  {(report['question'] or '')[:60]}")
        for row in report["rows"]:
            share = "" if row.get("share") is None else f" share {row['share']:.1%}"
            if row["state"] == "not_searched":
                print(f"  {row['provider_id']:<12} not searched: {row['reason']}{share}")
            else:
                print(f"  {row['provider_id']:<12} {row['state']}{share}, {row['requests']} request(s),"
                      f" {row['records']} records, {row['works']} works, {row['only']} found by no other source")
    print("\nThe last number is what these runs show, not a measurement of the source's worth.")


if __name__ == "__main__":
    main()
