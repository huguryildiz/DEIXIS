#!/usr/bin/env python3
"""Measure retrievable, version-verified PDFs for one known-source stratum."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

import httpx

from deixis.config import load_dotenv
from deixis.documents import acquisition
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store


def known_sources(path: Path, stratum: str) -> list[tuple[str, str]]:
    active, result, last = None, [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# stratum:"):
            active = line.split(":", 1)[1].strip()
            last = None
        elif active == stratum and re.fullmatch(r"10\.\S+", line, re.I):
            result.append((line.casefold(), line))
            last = len(result) - 1
        elif active == stratum and last is not None and line.startswith("# ["):
            title = re.sub(r"^#\s*\[\d+\]\s*", "", line).split(" — ", 1)[0].strip()
            title = re.sub(r"\s+\([^()]*,\s*\d{4}\)$", "", title).strip()
            result[last] = (result[last][0], title)
            last = None
    return result


def source_record(doi: str, title: str) -> ProviderRecord:
    return ProviderRecord(
        provider_record_id=doi, title=title, authors=[], year=None, venue=None, publication_type="article", doi=doi,
        landing_url=f"https://doi.org/{doi}", oa_pdf_url=None, oa_pdf_version=None,
        version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )


async def measure(args: argparse.Namespace) -> dict:
    data_dir: Path = args.data_dir
    connection = db.connect(data_dir / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research(
        f"Kurt et al. direct packet-size references: version-verified PDF coverage ({args.stratum})",
        "academic", "quick", ["unpaywall", "openalex", "crossref", "serpapi"], "codex", "gpt-5.6-luna", "en",
    )
    sources = []
    for doi, title in known_sources(args.known_sources, args.stratum):
        svid, _ = store.upsert_provider_source("known_list", source_record(doi, title), None)
        store.add_to_corpus(rid, svid, "search", rank=len(sources), scope_revision=1,
                            selection_state="included", selection_origin="user")
        sources.append((doi, title, svid))

    rows = []
    async with httpx.AsyncClient(headers={"User-Agent": "DEIXIS/0.1 (PDF coverage evaluation)"}) as client:
        for index, (doi, title, svid) in enumerate(sources, 1):
            print(f"[{index}/{len(sources)}] {doi} {title}", flush=True)
            await acquisition.acquire_for_source(
                store, rid, svid, client, data_dir / "papers", os.environ.get("DEIXIS_CONTACT_EMAIL"),
                os.environ.get("SERPAPI_API_KEY"),
            )
            candidates = store.pdf_candidates(svid)
            discoveries = store.pdf_discoveries(rid, svid)
            rows.append({
                "doi": doi, "title": title, "source_version_id": svid, "pdf_found": store.has_asset(svid),
                "discoveries": discoveries,
                "candidates": [{k: c[k] for k in (
                    "provider", "candidate_url", "landing_url", "version_label", "license", "identity_status",
                    "version_status", "access_status", "http_status", "error_code", "final_url",
                )} for c in candidates],
            })
    report = {
        "schema_version": "deixis.pdf_coverage.v1", "research_id": rid, "stratum": args.stratum,
        "known_sources": len(rows), "pdfs_found": sum(row["pdf_found"] for row in rows),
        "sources_with_metadata_candidates": sum(any(c["provider"] != "web_search" for c in row["candidates"]) for row in rows),
        "sources_with_web_candidates": sum(any(c["provider"] == "web_search" for c in row["candidates"]) for row in rows),
        "sources_with_403": sum(any(c["http_status"] == 403 for c in row["candidates"]) for row in rows),
        "sources_with_uncertain_version": sum(any(c["version_status"] == "uncertain" for c in row["candidates"]) for row in rows),
        "sources": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    connection.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("known_sources", type=Path)
    parser.add_argument("--stratum", default="direct-packet-size")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env")
    report = asyncio.run(measure(args))
    print(json.dumps({k: report[k] for k in (
        "research_id", "known_sources", "pdfs_found", "sources_with_metadata_candidates",
        "sources_with_web_candidates", "sources_with_403", "sources_with_uncertain_version",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
