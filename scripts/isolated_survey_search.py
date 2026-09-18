"""Run a separate bounded survey-discovery lane for the frozen quantum question."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path

import httpx

import isolated_hybrid_search as previous

from deixis.config import load_dotenv
from deixis.providers import query_rules

PROTOCOL = previous.ROOT / "docs/methods/quantum-auxiliary-search-isolated-2026-09-18.md"
QUERIES = [
    '("entanglement routing" OR "entanglement distribution") AND (survey OR review)',
    '("quantum networks" OR "quantum internet") AND ("routing survey" OR "entanglement survey" OR "literature review")',
    '("quantum repeater" OR "quantum network") AND ("systematic review" OR "comprehensive survey" OR taxonomy)',
]
GENRE_WORDS = re.compile(r"\b(?:survey|review|taxonomy)\b", re.IGNORECASE)


def check_queries() -> None:
    if len(QUERIES) != 3 or len(set(QUERIES)) != 3:
        raise ValueError("survey query budget or uniqueness changed")
    for query in QUERIES:
        if query_rules.query_issues("openalex", query) or len(query) > 300:
            raise ValueError("invalid survey query")


def prepare(args: argparse.Namespace) -> None:
    check_queries()
    previous.empty_output(args.plan_dir)
    plan = {"question": previous.QUESTION, "queries": QUERIES,
            "protocol_sha256": previous.sha(PROTOCOL.read_bytes()),
            "script_sha256": previous.sha(Path(__file__).read_bytes()),
            "provider": "openalex", "search_field": "search.title_and_abstract",
            "per_page": 100, "pages_per_query": 2, "logical_requests": 6,
            "max_returned_slots": 600, "human_approved_terms": False,
            "prepared_at": previous.now()}
    previous.write_json(args.plan_dir / "plan.json", plan)
    print(json.dumps({"status": "prepared", "plan": str(args.plan_dir / "plan.json"),
                      "queries": QUERIES}))


async def run(args: argparse.Namespace) -> None:
    raw = args.plan.read_bytes()
    plan = json.loads(raw)
    check_queries()
    if (plan.get("question") != previous.QUESTION or plan.get("queries") != QUERIES
            or plan.get("protocol_sha256") != previous.sha(PROTOCOL.read_bytes())
            or plan.get("script_sha256") != previous.sha(Path(__file__).read_bytes())
            or plan.get("logical_requests") != 6 or plan.get("per_page") != 100
            or plan.get("pages_per_query") != 2):
        raise ValueError("survey plan no longer matches the frozen experiment")
    previous.empty_output(args.output_dir)
    previous.write_json(args.output_dir / "frozen-plan.json", plan)
    started = time.monotonic()
    rows = []
    ledger_data = {"started_at": previous.now(), "status": "running",
                   "plan_sha256": previous.sha(raw), "provider": "openalex",
                   "real_library_used": False, "live_service_used": False,
                   "human_screening_performed": False, "calls": []}
    ledger = None
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS isolated survey lane/2026-09-18",
                                             "Accept": "application/json"}, trust_env=False) as client:
            ledger = previous.OpenAlexLedger(args.output_dir, client)
            for page in (1, 2):
                for slot, query in enumerate(QUERIES, 1):
                    name = f"survey_q{slot}_p{page}"
                    result = await ledger.get(name, {"search.title_and_abstract": query,
                                                     "per_page": 100, "page": page,
                                                     "select": previous.OA_SELECT + ",type"})
                    rows.extend(previous.record(work, name) | {"provider_type": work.get("type")}
                                for work in result["results"])
        ledger_data["status"] = ("completed" if all(call["status"] == "completed" for call in ledger.calls)
                                 else "partial_provider_failure")
    except Exception as exc:
        ledger_data["status"] = "partial_failure"
        ledger_data["error_type"] = type(exc).__name__
        raise
    finally:
        unique = previous.merge(rows)
        genre = [item for item in unique.values() if GENRE_WORDS.search(item["title"])]
        ledger_data["calls"] = ledger.calls if ledger else []
        ledger_data["returned_rows"] = len(rows)
        ledger_data["exact_identities"] = len(unique)
        ledger_data["doi_identities"] = sum(key.startswith("doi:") for key in unique)
        ledger_data["title_genre_signal_count"] = len(genre)
        ledger_data["screened_by_human"] = 0
        ledger_data["included_studies"] = None
        ledger_data["finished_at"] = previous.now()
        ledger_data["wall_clock_seconds"] = round(time.monotonic() - started, 3)
        previous.write_json(args.output_dir / "records.json", rows)
        previous.write_json(args.output_dir / "title-genre-candidates.json", genre)
        previous.write_json(args.output_dir / "run-ledger.json", ledger_data)
        lines = ["# Isolated survey discovery", "",
                 f"- Status: `{ledger_data['status']}`; wall clock: {ledger_data['wall_clock_seconds']} s.",
                 f"- OpenAlex calls: {len(ledger_data['calls'])}; complete: "
                 f"{sum(call['status'] == 'completed' for call in ledger_data['calls'])}.",
                 f"- Returned rows: {len(rows)}; exact identities: {len(unique)}; DOI identities: "
                 f"{ledger_data['doi_identities']}.",
                 f"- Title survey/review/taxonomy signals: {len(genre)} (provisional, not screened).",
                 "- No PDF, citation graph, human screening, or inclusion was performed.", "",
                 "The already known IEEE survey is a post-run diagnostic, not an independent target."]
        (args.output_dir / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan-dir", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.command == "run" and args.env_file:
        if not args.env_file.is_file():
            parser.error("selected env file does not exist")
        load_dotenv(args.env_file)
    if args.command == "prepare":
        prepare(args)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
