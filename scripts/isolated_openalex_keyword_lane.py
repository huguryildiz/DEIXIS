"""Run one separate query from OpenAlex-assigned keywords of cited paper seeds."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

import isolated_cited_term_round as cited
import isolated_hybrid_search as previous
import isolated_query_branches as earlier

from deixis.config import load_dotenv
from deixis.providers import query_rules

PROTOCOL = previous.ROOT / "docs/methods/quantum-openalex-keyword-lane-2026-09-18.md"
DOMAIN_WORDS = {"quantum", "network", "networks", "routing", "entanglement", "fidelity", "memory", "optimization"}


def source_rows(run_dir: Path) -> tuple[bytes, list[dict[str, Any]]]:
    return cited.input_rows(run_dir)


def selected_seeds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected, _ = cited.select_seeds(rows)
    return [{"openalex_id": row["openalex_id"], "doi": row["doi"],
             "title": row["title"], "cited_by_count": row["cited_by_count"]} for row in selected]


def select_terms(metadata: list[dict[str, Any]], used: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: dict[str, dict[str, float]] = defaultdict(dict)
    rejected = []
    for work in metadata:
        for item in work["keywords"][:3]:
            raw = item.get("display_name") or ""
            try:
                term = earlier.safe_term(raw)
                score = item.get("score")
                if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                    raise ValueError("invalid provider score")
                if (len(term.split()) > 5 or term in used or term in cited.GENERIC
                        or not set(term.split()) & DOMAIN_WORDS):
                    raise ValueError("generic, previously searched, or outside question domain")
            except ValueError as exc:
                rejected.append({"term": raw, "source_id": work["openalex_id"], "reason": str(exc)[:70]})
                continue
            seen[term][work["openalex_id"]] = float(score)
    ranked = sorted(seen, key=lambda term: (-len(seen[term]),
                                           -sum(seen[term].values()) / len(seen[term]), term))
    selected = [{"term": term, "source_ids": sorted(seen[term]),
                 "mean_keyword_score": round(sum(seen[term].values()) / len(seen[term]), 6),
                 "provenance": "openalex_assigned_keyword"} for term in ranked[:4]]
    if len(selected) < 2 or len({sid for item in selected for sid in item["source_ids"]}) < 2:
        raise ValueError("insufficient distinct OpenAlex-assigned terms from two papers")
    return selected, rejected


def compile_query(selected: list[dict[str, Any]]) -> str:
    query = "entanglement AND " + earlier.render(
        [{"term": item["term"], "provenance": item["provenance"]} for item in selected])
    if query_rules.query_issues("openalex", query) or len(query) > 300:
        raise ValueError("invalid provider-keyword query")
    return query


async def prepare(args: argparse.Namespace) -> None:
    previous.empty_output(args.plan_dir)
    rows_raw, rows = source_rows(args.source_run)
    seeds = selected_seeds(rows)
    previous.write_json(args.plan_dir / "seed-selection.json",
                        {"source_rows_sha256": previous.sha(rows_raw), "selected": seeds,
                         "rule": "top three cited records after frozen title/abstract and non-survey gate"})
    key = os.environ.get("OPENALEX_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    calls = []
    metadata = []
    async with httpx.AsyncClient(headers={"Accept": "application/json",
                                         "User-Agent": "DEIXIS isolated assigned keywords/2026-09-18"},
                                 trust_env=False) as client:
        for seed in seeds:
            code = None
            work = None
            error_type = None
            try:
                response = await client.get(f"{previous.OA_URL}/{seed['openalex_id']}",
                                            params={"select": "id,doi,display_name,keywords"},
                                            headers=headers, timeout=25)
                code = response.status_code
                if code == 200:
                    candidate = response.json()
                    if str(candidate.get("id") or "").rsplit("/", 1)[-1] == seed["openalex_id"]:
                        work = candidate
                    else:
                        error_type = "id_mismatch"
                else:
                    error_type = "http_status"
            except (httpx.HTTPError, ValueError) as exc:
                error_type = type(exc).__name__
            calls.append({"openalex_id": seed["openalex_id"], "http_status": code,
                          "access_mode": "api_key" if key else "keyless",
                          "status": "completed" if work is not None else "failed",
                          "error_type": error_type})
            if work is not None:
                metadata.append({"openalex_id": seed["openalex_id"], "doi": previous.normalize_doi(work.get("doi")),
                                 "title": work.get("display_name"),
                                 "keywords": work.get("keywords") or []})
    previous.write_json(args.plan_dir / "keyword-metadata-ledger.json", {"calls": calls, "metadata": metadata})
    if len(metadata) != 3:
        previous.write_json(args.plan_dir / "prepare-failure.json",
                            {"status": "failed_before_search", "reason": "OpenAlex metadata incomplete",
                             "completed_calls": len(metadata), "at": previous.now()})
        raise RuntimeError("OpenAlex keyword metadata incomplete")
    try:
        selected, rejected = select_terms(metadata, cited.existing_terms())
        query = compile_query(selected)
    except ValueError as exc:
        previous.write_json(args.plan_dir / "prepare-failure.json",
                            {"status": "failed_before_search", "reason": str(exc), "at": previous.now()})
        raise
    plan = {"question": previous.QUESTION, "source_run": str(args.source_run.resolve()),
            "source_rows_sha256": previous.sha(rows_raw),
            "protocol_sha256": previous.sha(PROTOCOL.read_bytes()),
            "script_sha256": previous.sha(Path(__file__).read_bytes()),
            "selected_seeds": seeds, "metadata_calls": calls, "metadata": metadata,
            "selected_terms": selected, "rejected_terms": rejected, "query_text": query,
            "provider": "openalex", "search_field": "search.title_and_abstract",
            "per_page": 100, "pages": 2, "logical_requests": 2, "max_returned_slots": 200,
            "human_approved_terms": False, "prepared_at": previous.now()}
    previous.write_json(args.plan_dir / "plan.json", plan)
    print(json.dumps({"status": "prepared", "plan": str(args.plan_dir / "plan.json"),
                      "query": query, "selected_terms": selected}))


async def run(args: argparse.Namespace) -> None:
    raw = args.plan.read_bytes()
    plan = json.loads(raw)
    source_run = Path(plan["source_run"])
    rows_raw, base_rows = source_rows(source_run)
    selected, rejected = select_terms(plan["metadata"], cited.existing_terms())
    if (plan.get("question") != previous.QUESTION or plan.get("source_rows_sha256") != previous.sha(rows_raw)
            or plan.get("protocol_sha256") != previous.sha(PROTOCOL.read_bytes())
            or plan.get("script_sha256") != previous.sha(Path(__file__).read_bytes())
            or plan.get("selected_seeds") != selected_seeds(base_rows)
            or plan.get("selected_terms") != selected or plan.get("rejected_terms") != rejected
            or plan.get("query_text") != compile_query(selected)
            or plan.get("per_page") != 100 or plan.get("pages") != 2
            or plan.get("logical_requests") != 2):
        raise ValueError("plan no longer matches the frozen assigned-keyword experiment")
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
        async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS isolated assigned keywords/2026-09-18",
                                             "Accept": "application/json"}, trust_env=False) as client:
            ledger = previous.OpenAlexLedger(args.output_dir, client)
            for page in (1, 2):
                name = f"assigned_keywords_p{page}"
                result = await ledger.get(name, {"search.title_and_abstract": plan["query_text"],
                                                 "per_page": 100, "page": page,
                                                 "select": previous.OA_SELECT})
                rows.extend(previous.record(work, name) for work in result["results"])
        ledger_data["status"] = ("completed" if all(call["status"] == "completed" for call in ledger.calls)
                                 else "partial_provider_failure")
    except Exception as exc:
        ledger_data["status"] = "partial_failure"
        ledger_data["error_type"] = type(exc).__name__
        raise
    finally:
        unique = previous.merge(rows)
        baseline = set(previous.merge(base_rows))
        ledger_data["calls"] = ledger.calls if ledger else []
        ledger_data["returned_rows"] = len(rows)
        ledger_data["exact_identities"] = len(unique)
        ledger_data["doi_identities"] = sum(key.startswith("doi:") for key in unique)
        ledger_data["incremental_to_c_exact_identities"] = len(set(unique) - baseline)
        ledger_data["screened_by_human"] = 0
        ledger_data["included_studies"] = None
        ledger_data["finished_at"] = previous.now()
        ledger_data["wall_clock_seconds"] = round(time.monotonic() - started, 3)
        previous.write_json(args.output_dir / "records.json", rows)
        previous.write_json(args.output_dir / "run-ledger.json", ledger_data)
        lines = ["# Isolated OpenAlex-assigned keyword round", "",
                 f"- Status: `{ledger_data['status']}`; wall clock: {ledger_data['wall_clock_seconds']} s.",
                 f"- OpenAlex calls: {len(ledger_data['calls'])}; complete: "
                 f"{sum(call['status'] == 'completed' for call in ledger_data['calls'])}.",
                 f"- Returned rows: {len(rows)}; exact identities: {len(unique)}; "
                 f"incremental to C: {ledger_data['incremental_to_c_exact_identities']}.",
                 "- No second keyword round, PDF, graph, human screening, or inclusion was performed.", "",
                 f"Frozen query: `{plan['query_text']}`", "",
                 "These keywords were assigned by OpenAlex, not supplied by paper authors. "
                 "Discovery counts do not establish relevance."]
        (args.output_dir / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-run", type=Path, required=True)
    prep.add_argument("--plan-dir", type=Path, required=True)
    prep.add_argument("--env-file", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if not args.env_file.is_file():
            parser.error("selected env file does not exist")
        load_dotenv(args.env_file)
        asyncio.run(prepare(args))
    else:
        if args.env_file:
            if not args.env_file.is_file():
                parser.error("selected env file does not exist")
            load_dotenv(args.env_file)
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
