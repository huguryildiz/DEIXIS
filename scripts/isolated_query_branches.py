"""Compare a frozen quantum search with question-literal plus model-expanded query branches.

The experiment is isolated from the DEIXIS product workflow and live library.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

import isolated_hybrid_search as previous

from deixis.config import load_dotenv
from deixis.models.gemini import GeminiAdapter
from deixis.providers import query_rules

PROTOCOL = previous.ROOT / "docs/methods/quantum-query-branches-isolated-2026-09-18.md"
QUESTION = previous.QUESTION
ROLES = ("core", "mechanism", "method", "operation", "constraint", "context")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "been", "by", "cite", "compare", "each", "end", "for", "from",
    "full", "have", "in", "is", "it", "of", "or", "paper", "proposed", "state", "supporting",
    "text", "the", "their", "to", "treatment", "verified", "was", "whether", "which", "with",
}
FAMILY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "role": {"type": "string", "enum": list(ROLES)},
        "literal_terms": {"type": "array", "items": {"type": "string"}},
        "expanded_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["role", "literal_terms", "expanded_terms"],
}
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "anchor_literal": {"type": "string"},
        "families": {"type": "array", "items": FAMILY_SCHEMA},
    },
    "required": ["anchor_literal", "families"],
}


def literal_candidates(question: str) -> list[dict[str, Any]]:
    """Return question-owned lexical candidates, without guessing their scientific role."""
    tokens = list(re.finditer(r"[A-Za-z][A-Za-z0-9]*", question))
    found: dict[str, dict[str, Any]] = {}
    for start, token in enumerate(tokens):
        if token.group().casefold() in STOPWORDS:
            continue
        parts = []
        for end in range(start, min(start + 3, len(tokens))):
            current = tokens[end]
            if current.group().casefold() in STOPWORDS:
                break
            if end > start and not re.fullmatch(r"[\s-]+", question[tokens[end - 1].end():current.start()]):
                break
            parts.append(current.group().casefold())
            term = " ".join(parts)
            found.setdefault(term, {"term": term, "source_text": question[token.start():current.end()],
                                    "start": token.start(), "end": current.end()})
    return list(found.values())


def safe_term(text: str) -> str:
    term = " ".join(text.casefold().split())
    if not 2 <= len(term) <= 80 or not re.fullmatch(r"[a-z][a-z0-9]*(?:[ -][a-z0-9]+)*", term):
        raise ValueError("unsafe or empty search term")
    return term


def context_anchor_literal(question: str, literals: list[dict[str, Any]]) -> str:
    first_clause = question.split("?", 1)[0]
    match = re.search(r"\bin\s+([A-Za-z][A-Za-z0-9 -]*)$", first_clause, re.IGNORECASE)
    if not match:
        raise ValueError("question has no explicit in-domain phrase for this experiment")
    phrase = " ".join(match.group(1).casefold().split())
    if phrase not in {item["term"] for item in literals}:
        raise ValueError("domain phrase was not extracted from the question")
    return phrase


def validate_proposal(value: Any, literals: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"anchor_literal", "families"}:
        raise ValueError("unexpected model plan shape")
    allowed = {item["term"] for item in literals}
    anchor = safe_term(value["anchor_literal"])
    if anchor not in allowed or " " in anchor:
        raise ValueError("domain anchor must be a one-word question literal")
    families = value["families"]
    if not isinstance(families, list) or len(families) != len(ROLES):
        raise ValueError("need six distinct concept families")
    checked: dict[str, dict[str, list[str]]] = {}
    for family in families:
        if not isinstance(family, dict) or set(family) != {"role", "literal_terms", "expanded_terms"}:
            raise ValueError("unexpected family shape")
        role = family["role"]
        if role not in ROLES or role in checked:
            raise ValueError("duplicate or invalid concept role")
        literal = family["literal_terms"]
        expanded = family["expanded_terms"]
        if (not isinstance(literal, list) or not isinstance(expanded, list)
                or len(literal) > 5 or len(expanded) > 5):
            raise ValueError("invalid term list")
        exact = [safe_term(term) for term in literal]
        added = [safe_term(term) for term in expanded]
        if any(term not in allowed for term in exact):
            raise ValueError("model claimed a nonliteral term came from the question")
        if any(term in allowed for term in added):
            raise ValueError("model classified a question literal as an expansion")
        if len(set(exact + added)) != len(exact + added):
            raise ValueError("duplicate terms in a family")
        checked[role] = {"literal_terms": exact, "expanded_terms": added}
    if set(checked) != set(ROLES) or anchor not in checked["core"]["literal_terms"]:
        raise ValueError("missing role or core anchor")
    context_anchor = context_anchor_literal(QUESTION, literals)
    if context_anchor not in checked["context"]["literal_terms"]:
        raise ValueError("context family omitted the question's explicit domain phrase")
    if not any(" " in term and anchor in term.split() for term in checked["core"]["literal_terms"]):
        raise ValueError("core needs a multiword question phrase containing the anchor")
    for role in ("core", "method", "operation", "constraint", "context"):
        if not checked[role]["literal_terms"]:
            raise ValueError(f"{role} needs a question literal")
    if not checked["mechanism"]["literal_terms"] and not checked["mechanism"]["expanded_terms"]:
        raise ValueError("mechanism needs a term")
    return {"anchor_literal": anchor, "context_anchor_literal": context_anchor, "families": checked}


def family_terms(family: dict[str, list[str]], literal_limit: int, total_limit: int) -> list[dict[str, str]]:
    selected = ([{"term": term, "provenance": "question_literal"}
                 for term in family["literal_terms"][:literal_limit]] +
                [{"term": term, "provenance": "model_expansion"}
                 for term in family["expanded_terms"]])
    return selected[:total_limit]


def render(terms: list[dict[str, str]]) -> str:
    if not terms:
        raise ValueError("empty query group")
    operands = [f'"{item["term"]}"' if " " in item["term"] or "-" in item["term"] else item["term"]
                for item in terms]
    return operands[0] if len(operands) == 1 else "(" + " OR ".join(operands) + ")"


def compile_branches(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    families = proposal["families"]
    anchor = [{"term": proposal["anchor_literal"], "provenance": "question_literal"}]
    core_literals = [term for term in families["core"]["literal_terms"]
                     if " " in term and proposal["anchor_literal"] in term.split()]
    core = family_terms({"literal_terms": core_literals,
                         "expanded_terms": families["core"]["expanded_terms"]}, 2, 4)
    context = family_terms({"literal_terms": [proposal["context_anchor_literal"]],
                            "expanded_terms": families["context"]["expanded_terms"]}, 1, 2)
    mechanism = family_terms(families["mechanism"], 1, 3)
    method = family_terms(families["method"], 1, 4)
    operation = family_terms(families["operation"], 2, 4)
    constraint = family_terms(families["constraint"], 3, 3)
    specs = [
        ("core", [core]),
        ("context_mechanism", [context, mechanism]),
        ("method", [anchor, method]),
        ("operation", [anchor, operation]),
        ("context_constraint", [context, constraint]),
    ]
    queries = []
    for name, groups in specs:
        query = " AND ".join(render(group) for group in groups)
        issues = query_rules.query_issues("openalex", query)
        if issues or len(query) > 300:
            raise ValueError(f"invalid {name} query: {issues or ['too long']}")
        queries.append({"branch": name, "query_text": query, "groups": groups,
                        "provider_id": "openalex", "search_field": "search.title_and_abstract"})
    if len({item["query_text"] for item in queries}) != 5:
        raise ValueError("compiled branches are not unique")
    return queries


def baseline_queries(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    plan = json.loads(raw)
    if plan.get("question") != QUESTION or len(plan.get("queries") or []) != 5:
        raise ValueError("baseline question or query count differs")
    queries = []
    for index, item in enumerate(plan["queries"], 1):
        if item.get("provider_id") != "openalex" or query_rules.query_issues("openalex", item["query_text"]):
            raise ValueError("invalid frozen baseline query")
        queries.append({"branch": f"frozen_q{index}", "query_text": item["query_text"],
                        "provider_id": "openalex", "search_field": "search.title_and_abstract"})
    return queries, previous.sha(raw)


async def prepare(args: argparse.Namespace) -> None:
    previous.empty_output(args.plan_dir)
    literals = literal_candidates(QUESTION)
    baseline, baseline_sha = baseline_queries(args.baseline_plan)
    prompt = (
        "You are the DEIXIS research agent performing only search-plan vocabulary grouping. "
        "The application has extracted immutable literal candidates from the question. "
        "Choose one single-word domain anchor from those candidates. Return exactly six families: "
        "core, mechanism, method, operation, constraint, context. For each family list selected "
        "literal_terms verbatim from the candidate list and optional expanded_terms absent from that list. "
        "Keep the core anchor and a multiword question phrase containing it in core.literal_terms. "
        f"Put the explicit question-domain phrase '{context_anchor_literal(QUESTION, literals)}' in "
        "context.literal_terms, not mechanism; context is the scientific field, not report variables. "
        "Mechanism means a physical or operational process within that domain. "
        "Keep the original question's method, "
        "operation, constraint, and context vocabulary in those families; use field terms only "
        "as additions. Suggest at most five terms per list. No known-paper title or DOI is supplied. "
        "Do not treat the paper-feature reporting instruction as a search concept. "
        f"Question: {QUESTION}\nLiteral candidates: {json.dumps([x['term'] for x in literals])}"
    )
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            output, model_step = await previous.model_json(
                GeminiAdapter(client), args.model, args.reasoning_effort, prompt, PLAN_SCHEMA)
        proposal = validate_proposal(output, literals)
        hybrid = compile_branches(proposal)
        plan = {"question": QUESTION, "literal_candidates": literals, "model_proposal": output,
                "validated_proposal": proposal, "model_step": model_step,
                "arms": {"a_frozen": baseline, "b_hybrid": hybrid},
                "baseline_plan_sha256": baseline_sha,
                "protocol_sha256": previous.sha(PROTOCOL.read_bytes()),
                "script_sha256": previous.sha(Path(__file__).read_bytes()),
                "prepared_at": previous.now(), "human_approved_terms": False,
                "provider": "openalex", "search_field": "search.title_and_abstract",
                "per_page": 100, "pages_per_query": 2, "logical_requests_per_arm": 10,
                "max_returned_slots_per_arm": 1000}
        previous.write_json(args.plan_dir / "plan.json", plan)
        print(json.dumps({"status": "prepared", "plan": str(args.plan_dir / "plan.json"),
                          "hybrid_queries": [item["query_text"] for item in hybrid]}))
    except Exception as exc:
        previous.write_json(args.plan_dir / "prepare-failure.json",
                            {"status": "failed_before_provider_search", "error_type": type(exc).__name__,
                             "requested_model": args.model, "reasoning_effort": args.reasoning_effort,
                             "at": previous.now()})
        raise


def arm_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unique = previous.merge(rows)
    routes: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        match = re.search(r"_q([1-5])_p[12]$", row["route"])
        key = previous.identity(row)
        if match and key in unique:
            routes[key].add(int(match.group(1)))
    marginal = Counter(next(iter(slots)) for slots in routes.values() if len(slots) == 1)
    return {"returned_rows": len(rows), "exact_identities": len(unique),
            "doi_identities": sum(key.startswith("doi:") for key in unique),
            "title_abstract_identities": sum(bool(row["title"] and row["abstract"]) for row in unique.values()),
            "suspected_same_title_groups": len(previous.suspected_same_title(rows)),
            "marginal_exact_identities_by_query": {str(i): marginal[i] for i in range(1, 6)},
            "screened_by_human": 0, "included_studies": None, "excluded_studies": None}


async def run(args: argparse.Namespace) -> None:
    raw = args.plan.read_bytes()
    plan = json.loads(raw)
    if (plan.get("question") != QUESTION or plan.get("protocol_sha256") != previous.sha(PROTOCOL.read_bytes())
            or plan.get("script_sha256") != previous.sha(Path(__file__).read_bytes())
            or set(plan.get("arms") or {}) != {"a_frozen", "b_hybrid"}
            or any(len(queries) != 5 for queries in plan["arms"].values())):
        raise ValueError("plan no longer matches the frozen experiment")
    literals = literal_candidates(QUESTION)
    if (plan.get("literal_candidates") != literals
            or plan.get("validated_proposal") != validate_proposal(plan["model_proposal"], literals)
            or plan["arms"]["b_hybrid"] != compile_branches(plan["validated_proposal"])):
        raise ValueError("model proposal or compiled branch differs from the frozen plan")
    for query in plan["arms"]["a_frozen"]:
        if query.get("provider_id") != "openalex" or query_rules.query_issues("openalex", query["query_text"]):
            raise ValueError("invalid frozen baseline query")
    previous.empty_output(args.output_dir)
    previous.write_json(args.output_dir / "frozen-plan.json", plan)
    rows: dict[str, list[dict[str, Any]]] = {"a_frozen": [], "b_hybrid": []}
    started = time.monotonic()
    ledger_data: dict[str, Any] = {"started_at": previous.now(), "status": "running",
                                   "plan_sha256": previous.sha(raw), "provider": "openalex",
                                   "search_field": "search.title_and_abstract",
                                   "real_library_used": False, "live_service_used": False,
                                   "human_screening_performed": False, "calls": []}
    ledger = None
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS isolated query branches/2026-09-18",
                                             "Accept": "application/json"}, trust_env=False) as client:
            ledger = previous.OpenAlexLedger(args.output_dir, client)
            for page in (1, 2):
                for slot in range(5):
                    for arm in ("a_frozen", "b_hybrid"):
                        query = plan["arms"][arm][slot]
                        name = f"{arm}_q{slot + 1}_p{page}"
                        result = await ledger.get(name, {"search.title_and_abstract": query["query_text"],
                                                         "per_page": 100, "page": page,
                                                         "select": previous.OA_SELECT})
                        rows[arm].extend(previous.record(work, name) for work in result["results"])
        calls = ledger.calls
        ledger_data["status"] = "completed" if all(call["status"] == "completed" for call in calls) else "partial_provider_failure"
    except Exception as exc:
        ledger_data["status"] = "partial_failure"
        ledger_data["error_type"] = type(exc).__name__
        raise
    finally:
        ledger_data["calls"] = ledger.calls if ledger else []
        for arm, arm_rows in rows.items():
            previous.write_json(args.output_dir / f"{arm}-records.json", arm_rows)
        a_ids = set(previous.merge(rows["a_frozen"]))
        b_ids = set(previous.merge(rows["b_hybrid"]))
        ledger_data["arms"] = {arm: arm_metrics(arm_rows) for arm, arm_rows in rows.items()}
        ledger_data["overlap"] = {"shared_exact_identities": len(a_ids & b_ids),
                                  "a_only_exact_identities": len(a_ids - b_ids),
                                  "b_only_exact_identities": len(b_ids - a_ids)}
        ledger_data["finished_at"] = previous.now()
        ledger_data["wall_clock_seconds"] = round(time.monotonic() - started, 3)
        previous.write_json(args.output_dir / "run-ledger.json", ledger_data)
        lines = ["# Isolated query-branch comparison", "",
                 f"- Status: `{ledger_data['status']}`; wall clock: {ledger_data['wall_clock_seconds']} s.",
                 f"- OpenAlex logical calls: {len(ledger_data['calls'])}; complete: "
                 f"{sum(c['status'] == 'completed' for c in ledger_data['calls'])}.",
                 "- Search field: `search.title_and_abstract`; 10 requests and 1,000 returned-slot cap per arm.",
                 "- No graph, PDF, embedding, human screening, inclusion or exclusion was performed.", "",
                 "| Arm | Returned rows | Exact identities | DOI identities | Title + abstract |", "|---|---:|---:|---:|---:|"]
        for arm, item in ledger_data["arms"].items():
            lines.append(f"| {arm} | {item['returned_rows']} | {item['exact_identities']} | "
                         f"{item['doi_identities']} | {item['title_abstract_identities']} |")
        lines += ["", f"Shared exact identities: {ledger_data['overlap']['shared_exact_identities']}; "
                  f"A-only: {ledger_data['overlap']['a_only_exact_identities']}; "
                  f"B-only: {ledger_data['overlap']['b_only_exact_identities']}.", "",
                  "These are discovery counts, not relevant or included-study counts. "
                  "The question and old misses are development-known; controls must be inspected only in a separate post-run analysis."]
        (args.output_dir / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--baseline-plan", type=Path, required=True)
    prep.add_argument("--model", required=True)
    prep.add_argument("--reasoning-effort", choices=("low", "medium", "high"), required=True)
    prep.add_argument("--plan-dir", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    for command in (prep, execute):
        command.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("selected env file does not exist")
        load_dotenv(args.env_file)
    asyncio.run(prepare(args) if args.command == "prepare" else run(args))


if __name__ == "__main__":
    main()
