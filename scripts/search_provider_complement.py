"""Read-only Semantic Scholar complement to the frozen compact OpenAlex pilot."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import httpx

import search_adaptation_probe as pilot
from deixis.config import load_settings
from deixis.providers.common import normalize_doi
from deixis.providers.query_compiler import _fit
from deixis.providers.registry import CONNECTORS

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local/search-compact-development-2026-09-17"
DEST = ROOT / ".local/search-provider-complement-2026-09-17"
CASES = ROOT / "scripts/search_method_cases_2026-09-17.json"
PROTOCOL = ROOT / "docs/product/search-provider-complement-development-2026-09-17.md"


def gold_hits(dois: set[str], gold: list[dict]) -> list[str]:
    return [normalize_doi(g["doi"]) for g in gold if normalize_doi(g["doi"]) in dois]


async def main() -> None:
    if DEST.exists():
        raise SystemExit(f"Refusing to overwrite: {DEST}")
    DEST.mkdir(parents=True, mode=0o700)
    os.chmod(DEST, 0o700)
    pilot.write_json(DEST / "manifest.json", {
        "protocol_sha256": pilot.sha(PROTOCOL.read_bytes()),
        "cases_sha256": pilot.sha(CASES.read_bytes()),
        "source_model_outputs": {f"L{c['litsearch_index']}": pilot.sha((SOURCE / f"L{c['litsearch_index']}-model.json").read_bytes())
                                 for c in json.loads(CASES.read_text())},
        "runner_sha256": pilot.sha(Path(__file__).read_bytes()),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "provider": "semantic_scholar",
    })
    settings = load_settings()
    connector = CONNECTORS["semantic_scholar"]
    async with httpx.AsyncClient(timeout=60) as client:
        for case in json.loads(CASES.read_text()):
            label = f"L{case['litsearch_index']}"
            model = json.loads((SOURCE / f"{label}-model.json").read_text())
            proposal = json.loads(model["raw_text"])
            query = _fit("semantic_scholar", proposal["core_terms"], proposal["facet_terms"])
            if not query:
                print(label, "invalid compiled query", flush=True)
                continue
            started = time.monotonic()
            outcome = await connector.search(client, query, 100, connector.api_key(), settings.contact_email)
            payload_hash = pilot.write_json(DEST / f"{label}-provider.json", outcome.raw_payload) if outcome.raw_payload is not None else None
            pilot.write_json(DEST / f"{label}-search.json", {
                "query": query, "requested_limit": 100, "status": outcome.status,
                "delivery_class": outcome.delivery_class, "access_mode": outcome.access_mode,
                "http_status": outcome.http_status, "retries": outcome.retries,
                "returned": len(outcome.records), "provider_total": outcome.provider_total,
                "rate_limit": outcome.rate_limit, "error": outcome.error,
                "payload_sha256": payload_hash, "elapsed_seconds": round(time.monotonic() - started, 2),
            })
            oa = json.loads((SOURCE / f"{label}-first-provider.json").read_text())
            oa_dois = {normalize_doi(w.get("doi")) for w in oa["results"] if w.get("doi")}
            s2_dois = {r.doi for r in outcome.records if r.doi}
            score = {"gold_total": len(case["gold"]), "openalex_hits": gold_hits(oa_dois, case["gold"]),
                     "semantic_scholar_hits": gold_hits(s2_dois, case["gold"]),
                     "union_hits": gold_hits(oa_dois | s2_dois, case["gold"]),
                     "openalex_distinct_dois": len(oa_dois), "semantic_scholar_distinct_dois": len(s2_dois),
                     "union_distinct_dois": len(oa_dois | s2_dois)}
            pilot.write_json(DEST / f"{label}-scores.json", score)
            print(label, outcome.status, len(outcome.records),
                  "gold", len(score["openalex_hits"]), len(score["union_hits"]), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
