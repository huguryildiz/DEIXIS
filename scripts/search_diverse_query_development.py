"""Development-only equal-result-budget comparison of diverse S2 queries."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

import search_adaptation_probe as pilot
from deixis.config import load_settings
from deixis.models.adapter import CodexAdapter
from deixis.providers.common import normalize_doi
from deixis.providers.registry import CONNECTORS

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local/search-diverse-query-development-2026-09-17"
BASELINE = ROOT / ".local/search-method-validation-2026-09-17"
PROTOCOL = ROOT / "docs/product/search-diverse-query-development-2026-09-17.md"
CASES = ROOT / "scripts/search_method_validation_cases_2026-09-17.json"
MODEL, EFFORT = "gpt-5.6-luna", "medium"
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"queries": {"type": "array", "items": {"type": "string"}},
                         "rationale": {"type": "string"}},
          "required": ["queries", "rationale"]}
INSTRUCTION = (
    "Generate exactly FOUR distinct short academic search queries for the research question. "
    "Each query must contain 1-5 English words and use plain words only, with no quotes, Boolean syntax, "
    "wildcards or punctuation. Cover different terminology or facets of the question rather than minor "
    "rephrasings. Prefer phrases likely to appear in paper titles or abstracts. Do not name a specific "
    "paper or claim that any result exists. You have no search tools."
)


def baseline_dois(label: str) -> set[str]:
    payload = json.loads((BASELINE / f"{label}-semantic_scholar-provider.json").read_text())
    return {normalize_doi(row.get("externalIds", {}).get("DOI")) for row in payload["data"]
            if row.get("externalIds", {}).get("DOI")}


def hit_list(dois: set[str], gold: list[dict]) -> list[str]:
    return [normalize_doi(g["doi"]) for g in gold if normalize_doi(g["doi"]) in dois]


async def main() -> None:
    if DEST.exists():
        raise SystemExit(f"Refusing to overwrite: {DEST}")
    cases = json.loads(CASES.read_text())
    if len(cases) != 6 or sum(len(case["gold"]) for case in cases) != 12:
        raise RuntimeError("Frozen case set changed")
    DEST.mkdir(parents=True, mode=0o700)
    os.chmod(DEST, 0o700)
    pilot.write_json(DEST / "manifest.json", {
        "protocol_sha256": pilot.sha(PROTOCOL.read_bytes()),
        "cases_sha256": pilot.sha(CASES.read_bytes()),
        "runner_sha256": pilot.sha(Path(__file__).read_bytes()),
        "baseline_manifest_sha256": pilot.sha((BASELINE / "manifest.json").read_bytes()),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": MODEL, "effort": EFFORT, "provider": "semantic_scholar",
    })
    auth_source = ROOT / ".local/depth-measure-2026-09-17/data-deep/codex-home/auth.json"
    home = DEST / "codex-home"
    home.mkdir(mode=0o700)
    shutil.copyfile(auth_source, home / "auth.json")
    os.chmod(home / "auth.json", 0o600)
    settings = load_settings()
    connector = CONNECTORS["semantic_scholar"]
    adapter = CodexAdapter(home, DEST / "empty-workspace", turn_timeout=300)
    try:
        health = await adapter.health()
        pilot.write_json(DEST / "model-health.json", {k: v for k, v in health.items() if k != "models"})
        if not health.get("ready"):
            raise RuntimeError(f"Model unavailable: {health.get('reason')}")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for case in cases:
                label = f"L{case['litsearch_index']}"
                started = time.monotonic()
                result = await adapter.run_step("You propose academic search queries. No tools or search.",
                                                INSTRUCTION, json.dumps({"question": case["query"]}),
                                                SCHEMA, MODEL, EFFORT)
                meta = {"requested_model": MODEL, "requested_effort": EFFORT,
                        "resolved_model": result.resolved_model, "status": result.status,
                        "tool_item_types": result.tool_item_types, "token_usage": result.token_usage,
                        "error": result.error, "raw_text": result.raw_text,
                        "elapsed_seconds": round(time.monotonic() - started, 2)}
                try:
                    if result.status != "completed" or result.resolved_model != MODEL or result.tool_item_types:
                        raise ValueError("Model identity, status or isolation failure")
                    proposal = json.loads(result.raw_text or "")
                    queries = proposal["queries"]
                    if (not isinstance(queries, list) or len(queries) != 4
                            or any(not isinstance(q, str) or not 1 <= len(q.split()) <= 5
                                   or not all(word.replace("-", "").isalpha() for word in q.split()) for q in queries)
                            or len({q.casefold().strip() for q in queries}) != 4):
                        raise ValueError("Invalid query count, words or duplicate")
                    meta["queries"] = queries
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    meta["validation_error"] = str(exc)
                pilot.write_json(DEST / f"{label}-model.json", meta)
                if "queries" not in meta:
                    print(label, "invalid model proposal", flush=True)
                    continue
                gathered = []
                statuses = []
                for i, query in enumerate(meta["queries"], 1):
                    started = time.monotonic()
                    outcome = await connector.search(client, query, 25, connector.api_key(), settings.contact_email)
                    payload_hash = pilot.write_json(DEST / f"{label}-Q{i}-provider.json", outcome.raw_payload) if outcome.raw_payload is not None else None
                    pilot.write_json(DEST / f"{label}-Q{i}-search.json", {
                        "query": query, "requested_limit": 25, "status": outcome.status,
                        "delivery_class": outcome.delivery_class, "access_mode": outcome.access_mode,
                        "http_status": outcome.http_status, "retries": outcome.retries,
                        "returned": len(outcome.records), "provider_total": outcome.provider_total,
                        "rate_limit": outcome.rate_limit, "error": outcome.error,
                        "payload_sha256": payload_hash, "elapsed_seconds": round(time.monotonic() - started, 2)})
                    statuses.append(outcome.status)
                    gathered.extend(outcome.records)
                dois = {r.doi for r in gathered if r.doi}
                first = baseline_dois(label)
                score = {"gold_total": len(case["gold"]), "baseline_hits": hit_list(first, case["gold"]),
                         "diverse_hits": hit_list(dois, case["gold"]),
                         "baseline_unique_dois": len(first), "diverse_unique_dois": len(dois),
                         "diverse_records_returned": len(gathered), "statuses": statuses}
                pilot.write_json(DEST / f"{label}-scores.json", score)
                print(label, "gold", len(score["baseline_hits"]), len(score["diverse_hits"]),
                      "records", len(gathered), "statuses", statuses, flush=True)
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
