"""Run the frozen algae-question DEIXIS retrieval comparison in an ignored directory."""

from __future__ import annotations

import asyncio, hashlib, json, os, shutil, subprocess, time
from pathlib import Path

import httpx

from deixis.config import load_settings
from deixis.models.adapter import CodexAdapter
from deixis.providers.common import normalize_doi
from deixis.providers.query_compiler import compile_queries
from deixis.providers.registry import CONNECTORS, available_providers

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local/elicit-consensus-deixis-comparison-2026-09-17-v2"
PROTOCOL = ROOT / "docs/product/elicit-consensus-deixis-comparison-2026-09-17.md"
CASES = ROOT / "scripts/elicit_consensus_deixis_comparison_cases_2026-09-17.json"
MODEL, EFFORT = "gpt-5.6-luna", "medium"
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "question_interpretation": {"type": "string"}, "concepts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "properties": {
            "label": {"type": "string"}, "role": {"type": "string", "enum": ["core", "mechanism", "method", "outcome", "context", "adjacent_field"]},
            "synonyms": {"type": "array", "items": {"type": "string"}}}, "required": ["label", "role", "synonyms"]}},
    "rationale": {"type": "string"}}, "required": ["question_interpretation", "concepts", "rationale"]}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

def score(records: list, controls: list[dict]) -> dict:
    dois = {r.doi for r in records if r.doi}
    hits = [{"doi": normalize_doi(c["doi"]), "title": c["title"]}
            for c in controls if normalize_doi(c["doi"]) in dois]
    return {"control_total": len(controls), "control_hits": hits,
            "unique_doi_count": len(dois), "returned_record_count": len(records)}

async def main() -> None:
    if DEST.exists():
        raise SystemExit(f"Refusing to overwrite {DEST}")
    DEST.mkdir(parents=True, mode=0o700)
    data = json.loads(CASES.read_text())
    providers = available_providers()
    write(DEST / "manifest.json", {"protocol_sha256": sha(PROTOCOL), "cases_sha256": sha(CASES),
        "runner_sha256": sha(Path(__file__)), "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": MODEL, "effort": EFFORT, "providers": providers})
    auth_source = ROOT / ".local/depth-measure-2026-09-17/data-deep/codex-home/auth.json"
    if not auth_source.is_file():
        raise SystemExit("Isolated Codex authentication unavailable")
    home = DEST / "codex-home"; home.mkdir(mode=0o700); shutil.copyfile(auth_source, home / "auth.json"); os.chmod(home / "auth.json", 0o600)
    empty = DEST / "empty-workspace"; empty.mkdir()
    adapter = CodexAdapter(home, empty, turn_timeout=300)
    try:
        health = await adapter.health(); write(DEST / "model-health.json", {k: v for k, v in health.items() if k != "models"})
        if not health.get("ready"): raise RuntimeError(health.get("reason", "model unavailable"))
        q = data["question"]
        result = await adapter.run_step("You propose DEIXIS search vocabulary only. No tools or search.",
            "Return only the structured SearchPlan. Use one core concept and 2-5 separate families. Do not claim exhaustive coverage.",
            json.dumps({"question": q}, ensure_ascii=False), SCHEMA, MODEL, EFFORT)
        write(DEST / "plan-model.json", {"requested_model": MODEL, "requested_effort": EFFORT,
            "resolved_model": result.resolved_model, "status": result.status, "tool_item_types": result.tool_item_types,
            "token_usage": result.token_usage, "error": result.error, "raw_text": result.raw_text})
        if result.status != "completed" or result.resolved_model != MODEL or result.tool_item_types:
            raise RuntimeError("requested model identity/status/isolation check failed")
        plan = json.loads(result.raw_text)
        if sum(c.get("role") == "core" for c in plan.get("concepts", [])) != 1: raise RuntimeError("invalid core count")
        plan["providers"] = providers
        compiled = compile_queries(plan, providers, 8, core_depth=100)
        write(DEST / "compiled.json", compiled)
        settings = load_settings(); records = []; by_provider = {}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for i, query in enumerate(compiled, 1):
                pid = query["provider_id"]; connector = CONNECTORS[pid]; limit = query.get("results", 25)
                started = time.monotonic(); outcome = await connector.search(client, query["query_text"], limit, connector.api_key(), settings.contact_email)
                payload_hash = None
                if outcome.raw_payload is not None:
                    payload = DEST / f"Q{i}-{pid}-provider.json"; write(payload, outcome.raw_payload); payload_hash = sha(payload)
                write(DEST / f"Q{i}-{pid}-search.json", {"provider": pid, "query": query["query_text"], "requested_limit": limit,
                    "status": outcome.status, "http_status": outcome.http_status, "returned": len(outcome.records),
                    "provider_total": outcome.provider_total, "retries": outcome.retries, "error": outcome.error,
                    "payload_sha256": payload_hash, "elapsed_seconds": round(time.monotonic() - started, 2)})
                records.extend(outcome.records); by_provider.setdefault(pid, []).extend(outcome.records)
        controls = data["controls"]
        write(DEST / "score.json", {"all": score(records, controls), "by_provider": {p: score(rs, controls) for p, rs in by_provider.items()},
            "total_records_before_dedup": len(records), "deduped_records": len({r.doi or r.provider_record_id for r in records})})
    finally:
        await adapter.close()

if __name__ == "__main__": asyncio.run(main())
