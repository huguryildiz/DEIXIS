"""Replay frozen hybrid queries against a guarded technical-feature fifth branch."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

import isolated_hybrid_search as previous
import isolated_query_branches as earlier

from deixis.config import load_dotenv
from deixis.providers import query_rules

PROTOCOL = previous.ROOT / "docs/methods/quantum-feature-filter-isolated-2026-09-18.md"
QUESTION = previous.QUESTION
REPORTING_LABELS = ("decision variables", "objectives", "constraints")


def feature_parts(question: str, source: dict[str, Any]) -> dict[str, Any]:
    if question != QUESTION or "? " not in question:
        raise ValueError("unexpected question structure")
    target, reporting = question.split("? ", 1)
    match = re.search(r"\btreatment of (.*?)\. For each\b", reporting, re.IGNORECASE)
    if not match or not all(re.search(rf"\b{re.escape(term)}\b", reporting, re.IGNORECASE)
                            for term in REPORTING_LABELS):
        raise ValueError("comparison facets or reporting labels changed")
    listed = re.sub(r",?\s+and\s+", ", ", match.group(1).casefold())
    features = [part.strip() for part in listed.split(",")]
    literals = {item["term"] for item in source["literal_candidates"]}
    if len(features) != len(set(features)) or any(item not in literals for item in features):
        raise ValueError("technical facet is not a distinct question literal")
    families = source["validated_proposal"]["families"]
    operations = [term for term in features if term in families["operation"]["literal_terms"]]
    technical = [term for term in features if term not in operations and term not in REPORTING_LABELS]
    if len(operations) < 2 or len(technical) < 2:
        raise ValueError("operation and technical facets cannot be separated")
    technical_words = {word for term in technical for word in term.split()}
    expansions = [term for term in families["mechanism"]["expanded_terms"]
                  if set(term.split()) & technical_words and not set(term.split()) & set(REPORTING_LABELS)]
    if not expansions:
        raise ValueError("no domain-linked model expansion")
    return {"research_target": target, "reporting_instruction": reporting,
            "reporting_labels_excluded_from_search": list(REPORTING_LABELS),
            "operation_facets_already_searched": operations,
            "technical_facets": technical, "model_expansion_candidates": expansions}


def guarded_queries(source: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if source.get("question") != QUESTION or source.get("human_approved_terms") is not False:
        raise ValueError("unexpected source plan")
    literals = earlier.literal_candidates(QUESTION)
    if (source.get("literal_candidates") != literals
            or source.get("validated_proposal") != earlier.validate_proposal(source["model_proposal"], literals)
            or source.get("arms", {}).get("b_hybrid") != earlier.compile_branches(source["validated_proposal"])):
        raise ValueError("source model proposal or hybrid queries differ")
    original = source["arms"]["b_hybrid"]
    if len(original) != 5 or original[-1]["branch"] != "context_constraint":
        raise ValueError("unexpected fifth source branch")
    parts = feature_parts(QUESTION, source)
    anchor = source["validated_proposal"]["anchor_literal"]
    if anchor not in {item["term"] for item in literals}:
        raise ValueError("anchor is not question-owned")
    terms = ([{"term": term, "provenance": "question_literal"}
              for term in parts["technical_facets"][:3]] +
             [{"term": parts["model_expansion_candidates"][0], "provenance": "model_expansion"}])
    if len(terms) != 4 or any(item["term"] in REPORTING_LABELS for item in terms):
        raise ValueError("guarded branch lacks specific terms")
    query = anchor + " AND " + earlier.render(terms)
    if query_rules.query_issues("openalex", query) or len(query) > 300:
        raise ValueError("invalid guarded OpenAlex query")
    replacement = {"branch": "technical_features", "query_text": query,
                   "groups": [[{"term": anchor, "provenance": "question_literal"}], terms],
                   "provider_id": "openalex", "search_field": "search.title_and_abstract"}
    arms = {"b_replay": original, "c_feature_guard": original[:4] + [replacement]}
    for queries in arms.values():
        if len(queries) != 5 or len({item["query_text"] for item in queries}) != 5:
            raise ValueError("query budget or uniqueness changed")
    return arms, parts


def prepare(args: argparse.Namespace) -> None:
    previous.empty_output(args.plan_dir)
    raw = args.source_plan.read_bytes()
    source = json.loads(raw)
    arms, parts = guarded_queries(source)
    plan = {"question": QUESTION, "source_plan": str(args.source_plan.resolve()),
            "source_plan_sha256": previous.sha(raw), "protocol_sha256": previous.sha(PROTOCOL.read_bytes()),
            "script_sha256": previous.sha(Path(__file__).read_bytes()),
            "source_model_step": source["model_step"], "human_approved_terms": False,
            "question_parts": parts, "arms": arms, "provider": "openalex",
            "search_field": "search.title_and_abstract", "per_page": 100,
            "pages_per_query": 2, "logical_requests_per_arm": 10,
            "max_returned_slots_per_arm": 1000, "prepared_at": previous.now()}
    previous.write_json(args.plan_dir / "plan.json", plan)
    print(json.dumps({"status": "prepared", "plan": str(args.plan_dir / "plan.json"),
                      "replaced_query": arms["c_feature_guard"][4]["query_text"]}))


async def run(args: argparse.Namespace) -> None:
    raw = args.plan.read_bytes()
    plan = json.loads(raw)
    source_path = Path(plan["source_plan"])
    source_raw = source_path.read_bytes()
    source = json.loads(source_raw)
    arms, parts = guarded_queries(source)
    if (plan.get("question") != QUESTION or plan.get("source_plan_sha256") != previous.sha(source_raw)
            or plan.get("protocol_sha256") != previous.sha(PROTOCOL.read_bytes())
            or plan.get("script_sha256") != previous.sha(Path(__file__).read_bytes())
            or plan.get("arms") != arms or plan.get("question_parts") != parts
            or plan.get("per_page") != 100 or plan.get("pages_per_query") != 2
            or plan.get("logical_requests_per_arm") != 10):
        raise ValueError("plan no longer matches frozen feature-guard experiment")
    previous.empty_output(args.output_dir)
    previous.write_json(args.output_dir / "frozen-plan.json", plan)
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in arms}
    started = time.monotonic()
    ledger_data: dict[str, Any] = {"started_at": previous.now(), "status": "running",
                                   "plan_sha256": previous.sha(raw), "provider": "openalex",
                                   "search_field": "search.title_and_abstract",
                                   "real_library_used": False, "live_service_used": False,
                                   "human_screening_performed": False, "calls": []}
    ledger = None
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS isolated feature guard/2026-09-18",
                                             "Accept": "application/json"}, trust_env=False) as client:
            ledger = previous.OpenAlexLedger(args.output_dir, client)
            for page in (1, 2):
                for slot in range(5):
                    for arm in arms:
                        query = arms[arm][slot]
                        name = f"{arm}_q{slot + 1}_p{page}"
                        result = await ledger.get(name, {"search.title_and_abstract": query["query_text"],
                                                         "per_page": 100, "page": page,
                                                         "select": previous.OA_SELECT})
                        rows[arm].extend(previous.record(work, name) for work in result["results"])
        ledger_data["status"] = ("completed" if all(call["status"] == "completed" for call in ledger.calls)
                                 else "partial_provider_failure")
    except Exception as exc:
        ledger_data["status"] = "partial_failure"
        ledger_data["error_type"] = type(exc).__name__
        raise
    finally:
        ledger_data["calls"] = ledger.calls if ledger else []
        for arm, arm_rows in rows.items():
            previous.write_json(args.output_dir / f"{arm}-records.json", arm_rows)
        identities = {arm: set(previous.merge(arm_rows)) for arm, arm_rows in rows.items()}
        b, c = identities["b_replay"], identities["c_feature_guard"]
        ledger_data["arms"] = {arm: earlier.arm_metrics(arm_rows) for arm, arm_rows in rows.items()}
        ledger_data["overlap"] = {"shared_exact_identities": len(b & c),
                                  "b_only_exact_identities": len(b - c),
                                  "c_only_exact_identities": len(c - b)}
        ledger_data["finished_at"] = previous.now()
        ledger_data["wall_clock_seconds"] = round(time.monotonic() - started, 3)
        previous.write_json(args.output_dir / "run-ledger.json", ledger_data)
        lines = ["# Isolated technical-feature query comparison", "",
                 f"- Status: `{ledger_data['status']}`; wall clock: {ledger_data['wall_clock_seconds']} s.",
                 f"- OpenAlex logical calls: {len(ledger_data['calls'])}; complete: "
                 f"{sum(c['status'] == 'completed' for c in ledger_data['calls'])}.",
                 "- Both arms: 10 requests, at most 1,000 returned slots, title-and-abstract search.",
                 "- The first four queries are identical; only query 5 differs.",
                 "- No graph, PDF, embedding, human screening, inclusion or exclusion was performed.", "",
                 "| Arm | Returned rows | Exact identities | DOI identities | Title + abstract | Marginal q5 identities |",
                 "|---|---:|---:|---:|---:|---:|"]
        for arm, item in ledger_data["arms"].items():
            lines.append(f"| {arm} | {item['returned_rows']} | {item['exact_identities']} | "
                         f"{item['doi_identities']} | {item['title_abstract_identities']} | "
                         f"{item['marginal_exact_identities_by_query']['5']} |")
        lines += ["", f"Shared exact identities: {len(b & c)}; B-only: {len(b - c)}; "
                  f"C-only: {len(c - b)}.", "",
                  "The question and known misses informed this design. These are candidate-discovery counts, "
                  "not relevance or inclusion. Inspect known DOI checks only after freezing this ledger."]
        (args.output_dir / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-plan", type=Path, required=True)
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
