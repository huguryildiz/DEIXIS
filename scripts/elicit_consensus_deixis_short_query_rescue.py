"""Run the frozen short-query rescue without touching the DEIXIS library."""

from __future__ import annotations

import asyncio, hashlib, json, os, shutil, subprocess, time
from pathlib import Path

import httpx

from deixis.config import load_settings
from deixis.providers.common import normalize_doi
from deixis.providers.registry import CONNECTORS

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local/elicit-consensus-deixis-short-query-rescue-2026-09-17"
PROTOCOL = ROOT / "docs/product/elicit-consensus-deixis-short-query-rescue-2026-09-17.md"
CASES = ROOT / "scripts/elicit_consensus_deixis_comparison_cases_2026-09-17.json"
QUERIES = ["algae communication", "algal signalling", "molecular communication algae", "algae resource allocation"]

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path: Path, value: object) -> None: path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

def score(records: list, controls: list[dict]) -> dict:
    dois = {r.doi for r in records if r.doi}
    hits = [{"doi": normalize_doi(c["doi"]), "title": c["title"]} for c in controls if normalize_doi(c["doi"]) in dois]
    return {"control_total": len(controls), "control_hits": hits, "unique_doi_count": len(dois), "returned_record_count": len(records)}

async def main() -> None:
    if DEST.exists(): raise SystemExit(f"Refusing to overwrite {DEST}")
    DEST.mkdir(parents=True, mode=0o700)
    data = json.loads(CASES.read_text()); providers = ["openalex", "semantic_scholar"]
    write(DEST / "manifest.json", {"protocol_sha256": sha(PROTOCOL), "cases_sha256": sha(CASES), "runner_sha256": sha(Path(__file__)),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "providers": providers, "queries": QUERIES, "limit": 25})
    settings = load_settings(); all_records = {}; rows = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for provider in providers:
            connector = CONNECTORS[provider]; all_records[provider] = []
            for i, query in enumerate(QUERIES, 1):
                started = time.monotonic(); outcome = await connector.search(client, query, 25, connector.api_key(), settings.contact_email)
                payload_hash = None
                if outcome.raw_payload is not None:
                    payload = DEST / f"{provider}-Q{i}-provider.json"; write(payload, outcome.raw_payload); payload_hash = sha(payload)
                row = {"provider": provider, "query": query, "requested_limit": 25, "status": outcome.status, "http_status": outcome.http_status,
                    "returned": len(outcome.records), "provider_total": outcome.provider_total, "retries": outcome.retries, "error": outcome.error,
                    "payload_sha256": payload_hash, "elapsed_seconds": round(time.monotonic() - started, 2)}
                write(DEST / f"{provider}-Q{i}-search.json", row); rows.append(row); all_records[provider].extend(outcome.records)
    controls = data["controls"]; union = []
    for provider in providers: union.extend(all_records[provider])
    write(DEST / "score.json", {"by_provider": {p: score(rs, controls) for p, rs in all_records.items()},
        "union": score(union, controls), "query_results": rows,
        "total_records_before_dedup": len(union), "deduped_records": len({r.doi or r.provider_record_id for r in union})})

if __name__ == "__main__": asyncio.run(main())
