"""Inherit source-owned IEEE author keywords in one isolated OpenAlex query round."""

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

PROTOCOL = previous.ROOT / "docs/methods/quantum-author-keyword-lane-2026-09-18.md"
IEEE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def source_rows(run_dir: Path) -> tuple[bytes, list[dict[str, Any]]]:
    return cited.input_rows(run_dir)


def ieee_seeds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, eligible = cited.select_seeds(rows)
    selected = [row for row in eligible if (row.get("doi") or "").startswith("10.1109/")][:3]
    if len(selected) != 3:
        raise ValueError("fewer than three eligible IEEE DOI seeds")
    return selected


def terms_from_field(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [term for item in value for term in terms_from_field(item)]
    if isinstance(value, dict):
        if "terms" in value:
            return terms_from_field(value["terms"])
        if isinstance(value.get("term"), str):
            return [value["term"]]
    return []


def select_terms(metadata: list[dict[str, Any]], used: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: dict[str, set[str]] = defaultdict(set)
    ranks = {item["doi"]: index for index, item in enumerate(metadata)}
    rejected = []
    for item in metadata:
        for raw in item["author_terms"]:
            try:
                term = earlier.safe_term(raw)
                if len(term.split()) > 5 or term in cited.GENERIC or term in used or term == "entanglement":
                    raise ValueError("generic_or_already_searched")
            except ValueError as exc:
                rejected.append({"term": raw, "source_doi": item["doi"], "reason": str(exc)[:60]})
                continue
            found[term].add(item["doi"])
    ranking = sorted(found, key=lambda term: (-len(found[term]), -len(term.split()),
                                               min(ranks[doi] for doi in found[term]), term))
    selected = [{"term": term, "source_dois": sorted(found[term]),
                 "provenance": "ieee_author_terms"} for term in ranking[:4]]
    if len(selected) < 2 or len({doi for item in selected for doi in item["source_dois"]}) < 2:
        raise ValueError("insufficient source-owned author keywords from two papers")
    return selected, rejected


def compile_query(selected: list[dict[str, Any]]) -> str:
    query = "entanglement AND " + earlier.render(
        [{"term": item["term"], "provenance": item["provenance"]} for item in selected])
    if query_rules.query_issues("openalex", query) or len(query) > 300:
        raise ValueError("invalid inherited-keyword query")
    return query


async def prepare(args: argparse.Namespace) -> None:
    previous.empty_output(args.plan_dir)
    rows_raw, rows = source_rows(args.source_run)
    seeds = ieee_seeds(rows)
    selected_seeds = [{"doi": item["doi"], "openalex_id": item["openalex_id"],
                       "title": item["title"], "cited_by_count": item["cited_by_count"]} for item in seeds]
    previous.write_json(args.plan_dir / "seed-selection.json",
                        {"source_rows_sha256": previous.sha(rows_raw), "selected": selected_seeds,
                         "rule": "top three IEEE DOI records after the frozen topic and genre gate"})
    key = os.environ.get("IEEE_API_KEY")
    if not key:
        raise RuntimeError("IEEE_API_KEY unavailable")
    metadata = []
    calls = []
    async with httpx.AsyncClient(headers={"Accept": "application/json",
                                         "User-Agent": "DEIXIS isolated keyword inheritance/2026-09-18"},
                                 trust_env=False) as client:
        for index, seed in enumerate(selected_seeds):
            if index:
                await asyncio.sleep(1.05)
            code = None
            article = None
            error_type = None
            try:
                response = await client.get(IEEE_URL, params={"doi": seed["doi"], "format": "json",
                                                              "apikey": key}, timeout=25)
                code = response.status_code
                if code == 200:
                    payload = response.json()
                    articles = payload.get("articles") or []
                    article = next((a for a in articles if previous.normalize_doi(a.get("doi")) == seed["doi"]), None)
                    if article is None:
                        error_type = "doi_not_in_provider_response"
                else:
                    error_type = "http_status"
            except (httpx.HTTPError, ValueError) as exc:
                error_type = type(exc).__name__
            calls.append({"doi": seed["doi"], "http_status": code,
                          "status": "completed" if article is not None else "failed",
                          "error_type": error_type})
            if article is not None:
                metadata.append({"doi": seed["doi"], "article_number": str(article.get("article_number") or ""),
                                 "title": article.get("title"),
                                 "author_terms": terms_from_field(article.get("author_terms")),
                                 "ieee_terms_present": bool(terms_from_field(article.get("ieee_terms"))),
                                 "index_terms_present": bool(terms_from_field(article.get("index_terms")))})
    previous.write_json(args.plan_dir / "ieee-metadata-ledger.json", {"calls": calls, "metadata": metadata})
    if len(metadata) != 3:
        previous.write_json(args.plan_dir / "prepare-failure.json",
                            {"status": "failed_before_openalex_search", "reason": "ieee_metadata_incomplete",
                             "completed_metadata_calls": len(metadata), "at": previous.now()})
        raise RuntimeError("IEEE metadata incomplete; no provider substitution")
    try:
        selected, rejected = select_terms(metadata, cited.existing_terms())
    except ValueError as exc:
        previous.write_json(args.plan_dir / "prepare-failure.json",
                            {"status": "failed_before_openalex_search", "reason": str(exc),
                             "completed_metadata_calls": len(metadata), "at": previous.now()})
        raise
    query = compile_query(selected)
    plan = {"question": previous.QUESTION, "source_run": str(args.source_run.resolve()),
            "source_rows_sha256": previous.sha(rows_raw),
            "protocol_sha256": previous.sha(PROTOCOL.read_bytes()),
            "script_sha256": previous.sha(Path(__file__).read_bytes()),
            "selected_seeds": selected_seeds, "ieee_metadata_calls": calls,
            "ieee_metadata": metadata, "selected_terms": selected, "rejected_terms": rejected,
            "query_text": query, "provider": "openalex", "search_field": "search.title_and_abstract",
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
    seeds = ieee_seeds(base_rows)
    selected, rejected = select_terms(plan["ieee_metadata"], cited.existing_terms())
    expected_seeds = [{"doi": item["doi"], "openalex_id": item["openalex_id"],
                       "title": item["title"], "cited_by_count": item["cited_by_count"]} for item in seeds]
    if (plan.get("question") != previous.QUESTION or plan.get("source_rows_sha256") != previous.sha(rows_raw)
            or plan.get("protocol_sha256") != previous.sha(PROTOCOL.read_bytes())
            or plan.get("script_sha256") != previous.sha(Path(__file__).read_bytes())
            or plan.get("selected_seeds") != expected_seeds or plan.get("selected_terms") != selected
            or plan.get("rejected_terms") != rejected or plan.get("query_text") != compile_query(selected)
            or plan.get("per_page") != 100 or plan.get("pages") != 2
            or plan.get("logical_requests") != 2):
        raise ValueError("plan no longer matches the frozen inherited-keyword experiment")
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
        async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS isolated author keywords/2026-09-18",
                                             "Accept": "application/json"}, trust_env=False) as client:
            ledger = previous.OpenAlexLedger(args.output_dir, client)
            for page in (1, 2):
                name = f"author_keywords_p{page}"
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
        lines = ["# Isolated inherited author-keyword round", "",
                 f"- Status: `{ledger_data['status']}`; wall clock: {ledger_data['wall_clock_seconds']} s.",
                 f"- OpenAlex calls: {len(ledger_data['calls'])}; complete: "
                 f"{sum(call['status'] == 'completed' for call in ledger_data['calls'])}.",
                 f"- Returned rows: {len(rows)}; exact identities: {len(unique)}; "
                 f"incremental to C: {ledger_data['incremental_to_c_exact_identities']}.",
                 "- No second keyword round, PDF, graph, human screening, or inclusion was performed.", "",
                 f"Frozen query: `{plan['query_text']}`", "",
                 "Author keywords are source metadata. They do not by themselves establish relevance."]
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
        if not args.env_file or not args.env_file.is_file():
            parser.error("prepare needs the selected env file")
        load_dotenv(args.env_file)
        asyncio.run(prepare(args))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
