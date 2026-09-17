"""Evaluate short canonical OpenAlex concept phrases on the used LitSearch cases."""

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
from deixis.providers.query_compiler import _fit
from deixis.providers.registry import CONNECTORS
from search_method_holdout import gold_score

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local/search-compact-development-2026-09-17"
PROTOCOL = ROOT / "docs/product/search-compact-development-2026-09-17.md"
CASES = ROOT / "scripts/search_method_cases_2026-09-17.json"
MODEL = "gpt-5.6-luna"
EFFORT = "medium"
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "core_terms": {"type": "array", "items": {"type": "string"}},
        "facet_terms": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["core_terms", "facet_terms", "rationale"],
}


def valid_terms(value: object, low: int, high: int) -> bool:
    return isinstance(value, list) and low <= len(value) <= high and all(
        isinstance(term, str) and 1 <= len(term.strip().split()) <= 3 and len(term) <= 70
        for term in value)


async def main() -> None:
    if DEST.exists():
        raise SystemExit(f"Refusing to overwrite: {DEST}")
    DEST.mkdir(parents=True, mode=0o700)
    os.chmod(DEST, 0o700)
    pilot.write_json(DEST / "manifest.json", {
        "protocol_sha256": pilot.sha(PROTOCOL.read_bytes()),
        "cases_sha256": pilot.sha(CASES.read_bytes()),
        "runner_sha256": pilot.sha(Path(__file__).read_bytes()),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": MODEL, "effort": EFFORT, "provider": "openalex",
    })
    auth_source = ROOT / ".local/depth-measure-2026-09-17/data-deep/codex-home/auth.json"
    home = DEST / "codex-home"
    home.mkdir(mode=0o700)
    shutil.copyfile(auth_source, home / "auth.json")
    os.chmod(home / "auth.json", 0o600)
    settings = load_settings()
    connector = CONNECTORS["openalex"]
    adapter = CodexAdapter(home, DEST / "empty-workspace", turn_timeout=300)
    try:
        health = await adapter.health()
        pilot.write_json(DEST / "model-health.json", {k: v for k, v in health.items() if k != "models"})
        if not health.get("ready"):
            raise RuntimeError(f"Model unavailable: {health.get('reason')}")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for case in json.loads(CASES.read_text()):
                label = f"L{case['litsearch_index']}"
                instruction = (
                    "Propose search vocabulary for OpenAlex title and abstract, using only the question. "
                    "Give 1-2 short canonical terms for the central established research topic, not a whole "
                    "question or a phrase naming an effect. Give 1-3 short terms for one distinctive facet. "
                    "Every term must be at most THREE words. Prefer common phrases likely to appear verbatim "
                    "in paper titles or abstracts. Do not write query syntax or cite papers."
                )
                started = time.monotonic()
                result = await adapter.run_step("You propose academic search vocabulary. No tools or search.", instruction,
                                                json.dumps({"question": case["query"]}), SCHEMA, MODEL, EFFORT)
                meta = {"label": label, "requested_model": MODEL, "requested_effort": EFFORT,
                        "resolved_model": result.resolved_model, "status": result.status,
                        "tool_item_types": result.tool_item_types, "token_usage": result.token_usage,
                        "error": result.error, "raw_text": result.raw_text,
                        "elapsed_seconds": round(time.monotonic() - started, 2)}
                try:
                    if result.status != "completed" or result.resolved_model != MODEL or result.tool_item_types:
                        raise ValueError("Model identity, status or isolation failure")
                    proposal = json.loads(result.raw_text or "")
                    core, facet = proposal["core_terms"], proposal["facet_terms"]
                    if not valid_terms(core, 1, 2) or not valid_terms(facet, 1, 3):
                        raise ValueError("Terms violate frozen length or count limits")
                    q1, q2 = _fit("openalex", core, []), _fit("openalex", core, facet)
                    if not q1 or not q2 or q1 == q2:
                        raise ValueError("Compiler rejected or duplicated query")
                    meta["first_query"], meta["second_query"] = q1, q2
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    meta["validation_error"] = str(exc)
                pilot.write_json(DEST / f"{label}-model.json", meta)
                if "first_query" not in meta:
                    print(label, "invalid proposal", flush=True)
                    continue
                first = await pilot.search(client, label, "first", q1, 100,
                                           connector.api_key(), settings.contact_email, DEST)
                if first.status not in ("completed", "zero_results"):
                    continue
                second = await pilot.search(client, label, "second", q2, 25,
                                            connector.api_key(), settings.contact_email, DEST)
                if second.status not in ("completed", "zero_results"):
                    continue
                score = {"first": gold_score(first.records, case["gold"]),
                         "combined": gold_score([*first.records, *second.records], case["gold"])}
                pilot.write_json(DEST / f"{label}-scores.json", score)
                print(label, "gold", score["first"]["gold_hit_count"], score["combined"]["gold_hit_count"], flush=True)
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
