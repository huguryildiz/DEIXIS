"""Bounded, opt-in PDF prefetch for isolated literature-search experiments.

The input order is a frozen selection rule's output. This script never chooses works
from Elicit/control labels and never writes to the DEIXIS library. Run it as an
async task alongside later discovery; its output separates PDF retrieval, readable
text, Marker enrichment, and actual human assessment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from deixis.config import load_dotenv  # noqa: E402
from deixis.documents import acquisition, fetch, math_reader, pdf  # noqa: E402
from deixis.providers.common import normalize_doi  # noqa: E402

LookupFn = Callable[[httpx.AsyncClient, dict[str, str]], Awaitable[acquisition.Lookup]]
FetchFn = Callable[[str], Awaitable[fetch.FetchResult]]
ExtractFn = Callable[[Path], pdf.Extraction]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_link(url: str | None) -> dict[str, str] | None:
    if not url:
        return None
    parts = urlsplit(url)
    return {"host": parts.hostname or "", "url_sha256": sha(url.encode())}


def safe_error_code(code: str | None) -> str | None:
    if code is None:
        return None
    if code in {"timeout", "rate_limited", "auth_required", "email_rejected",
                "missing_contact_email", "missing_core_key", "missing_serpapi_key"}:
        return code
    if re.fullmatch(r"http_[0-9]{3}|[A-Za-z]+(?:Error|Exception)", code):
        return code
    return "provider_message_redacted"


def validate_manifest(rows: object) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise ValueError("manifest must be a JSON array")
    seen: set[str] = set()
    works = []
    for position, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"row {position} is not an object")
        source_id = row.get("source_version_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError(f"row {position} needs a unique source_version_id")
        seen.add(source_id)
        doi = normalize_doi(row.get("doi"))
        version = row.get("version_label")
        if not doi or version not in ("publishedVersion", "acceptedVersion", "submittedVersion"):
            raise ValueError(f"row {position} needs a DOI and explicit version_label")
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"row {position} needs a title")
        direct_url = row.get("direct_pdf_url")
        direct_version = row.get("direct_pdf_version")
        if direct_url is not None and (not isinstance(direct_url, str) or not direct_url.startswith(("https://", "http://"))):
            raise ValueError(f"row {position} has an invalid direct_pdf_url")
        works.append({"source_version_id": source_id, "doi": doi, "title": title,
                      "version_label": version, "direct_pdf_url": direct_url,
                      "direct_pdf_version": direct_version, "rank": position})
    return works


def configured_lookups(contact_email: str | None, core_key: str | None,
                       serpapi_key: str | None) -> tuple[list[tuple[str, LookupFn]], list[str]]:
    async def openalex(client: httpx.AsyncClient, work: dict[str, str]) -> acquisition.Lookup:
        return await acquisition.openalex_lookup(client, work["doi"], work["version_label"],
                                                  contact_email=contact_email)

    async def unpaywall(client: httpx.AsyncClient, work: dict[str, str]) -> acquisition.Lookup:
        return await acquisition.unpaywall_lookup(client, work["doi"], work["version_label"], contact_email)

    async def crossref(client: httpx.AsyncClient, work: dict[str, str]) -> acquisition.Lookup:
        return await acquisition.crossref_lookup(client, work["doi"], work["version_label"], contact_email)

    async def core(client: httpx.AsyncClient, work: dict[str, str]) -> acquisition.Lookup:
        return await acquisition.core_lookup(client, work["doi"], core_key)

    async def web(client: httpx.AsyncClient, work: dict[str, str]) -> acquisition.Lookup:
        return await acquisition.web_lookup(client, work["doi"], work["title"], serpapi_key)

    routes: list[tuple[str, LookupFn]] = [("openalex", openalex)]
    unconfigured = []
    if contact_email:
        routes.append(("unpaywall", unpaywall))
    else:
        unconfigured.append("unpaywall")
    routes.append(("crossref", crossref))
    if core_key:
        routes.append(("core", core))
    else:
        unconfigured.append("core")
    if serpapi_key:
        routes.append(("web_search", web))
    else:
        unconfigured.append("web_search")
    return routes, unconfigured


def _text_record(extraction: pdf.Extraction) -> dict[str, Any]:
    return {"extraction_version": extraction.extraction_version, "status": extraction.status,
            "page_count": extraction.page_count, "text_pages": len(extraction.pages),
            "image_pages": extraction.image_pages, "blank_pages": extraction.blank_pages,
            "pages": [{"physical_page": p.physical_page, "printed_label": p.printed_label,
                       "text_source": p.text_source, "text": p.text} for p in extraction.pages]}


async def prefetch_one(work: dict[str, str], output_dir: Path, client: httpx.AsyncClient,
                       lookups: list[tuple[str, LookupFn]], fetcher: FetchFn,
                       extractor: ExtractFn, max_lookups: int, max_downloads: int) -> dict[str, Any]:
    item: dict[str, Any] = {k: work[k] for k in ("source_version_id", "doi", "title", "version_label", "rank")}
    item.update(selection_status="machine_provisional", pdf_status="no_eligible_pdf",
                pdf_lookup_attempts=[], pdf_candidates=[], pdf_download_attempts=[],
                manual_version_candidates=0,
                full_text_assessed=False, pdf_content_identity_checked=False,
                marker_status="not_run", started_at=utc_now())
    tried: set[str] = set()
    incomplete = False

    async def try_candidate(candidate: acquisition.Candidate) -> bool:
        if candidate.url in tried or len(item["pdf_download_attempts"]) >= max_downloads:
            return False
        tried.add(candidate.url)
        result = await fetcher(candidate.url)
        attempt = {"provider": candidate.provider, "url": safe_link(candidate.url),
                   "status": result.status, "http_status": result.http_status,
                   "final_url": safe_link(result.final_url)}
        item["pdf_download_attempts"].append(attempt)
        if result.status != "ok":
            return False
        digest = sha(result.data)
        pdf_dir = output_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        path = pdf_dir / f"{digest}.pdf"
        if not path.exists():
            path.write_bytes(result.data)
        extraction = await asyncio.to_thread(extractor, path)
        item.update(pdf_sha256=digest, pdf_bytes=len(result.data), pdf_path=str(path),
                    pdf_identity_basis=("manifest_asserted" if candidate.provider == "source_metadata"
                                        else "provider_doi_and_version_metadata"),
                    extraction_status=extraction.status, page_count=extraction.page_count,
                    text_pages=len(extraction.pages), image_pages=len(extraction.image_pages),
                    pdf_status=("readable_pdf" if extraction.pages else "pdf_extraction_failed"
                                if extraction.status == "failed" else "pdf_no_text"))
        text_dir = output_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        (text_dir / f"{digest}.json").write_text(json.dumps(_text_record(extraction), ensure_ascii=False) + "\n")
        (text_dir / f"{digest}.txt").write_text("\n\n".join(
            f"=== Physical page {page.physical_page} ===\n{page.text}"
            for page in extraction.pages), encoding="utf-8")
        return True

    direct = work.get("direct_pdf_url")
    if direct:
        item["pdf_candidates"].append({"provider": "source_metadata", "url": safe_link(direct),
                                        "version_label": work.get("direct_pdf_version"),
                                        "identity_status": "manifest_asserted",
                                        "version_status": ("match" if work.get("direct_pdf_version") == work["version_label"]
                                                           else "different_or_unknown")})
        if work.get("direct_pdf_version") == work["version_label"]:
            candidate = acquisition.Candidate("source_metadata", direct, None, work["version_label"],
                                              None, "doi_verified", "match")
            if await try_candidate(candidate):
                item["finished_at"] = utc_now()
                return item
        else:
            item["manual_version_candidates"] += 1

    for name, lookup in lookups[:max_lookups]:
        response = await lookup(client, work)
        item["pdf_lookup_attempts"].append({"provider": name, "status": response.status,
                                            "http_status": response.http_status,
                                            "error_code": safe_error_code(response.error_code),
                                            "other_title_count": response.other_title_count,
                                            "candidate_count": len(response.candidates)})
        if response.status not in ("completed", "zero_results"):
            incomplete = True
        for candidate in response.candidates:
            item["pdf_candidates"].append({"provider": candidate.provider,
                                            "url": safe_link(candidate.url),
                                            "version_label": candidate.version_label,
                                            "identity_status": candidate.identity_status,
                                            "version_status": candidate.version_status})
            if candidate.identity_status != "doi_verified" or candidate.version_status != "match":
                item["manual_version_candidates"] += 1
                continue
            if await try_candidate(candidate):
                item["finished_at"] = utc_now()
                return item
            if len(item["pdf_download_attempts"]) >= max_downloads:
                break
        if len(item["pdf_download_attempts"]) >= max_downloads:
            break
    if incomplete:
        item["pdf_status"] = "lookup_incomplete"
    elif item["pdf_download_attempts"]:
        item["pdf_status"] = "download_failed"
    item["finished_at"] = utc_now()
    return item


async def enrich_marker(item: dict[str, Any], output_dir: Path, reader: math_reader.MathReader) -> None:
    """Read mathematical/table pages after the text layer is already available."""
    if item["pdf_status"] != "readable_pdf":
        return
    path = Path(item["pdf_path"])
    try:
        selected = sorted(set(await asyncio.to_thread(math_reader.math_pages, path)) |
                          set(await asyncio.to_thread(math_reader.table_pages, path)))
        item["marker_selected_pages"] = [p + 1 for p in selected]
        if not selected:
            item["marker_status"] = "no_math_or_table_pages"
            return
        reading = await reader.read(path, selected)
        unchecked = await asyncio.to_thread(math_reader.check_equations, path, reading.equations)
        item["marker_status"] = "completed"
        item["marker_equations_to_check"] = len(unchecked)
        marker_dir = output_dir / "marker"
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{item['pdf_sha256']}.json").write_text(json.dumps(
            {"reader_version": reader.version, "selected_pages": item["marker_selected_pages"],
             "pages": {str(k + 1): v for k, v in reading.pages.items()},
             "equations_to_check": unchecked}, ensure_ascii=False) + "\n")
    except Exception as exc:  # an equation failure does not erase the text layer
        item["marker_status"] = "failed"
        item["marker_error_type"] = type(exc).__name__


async def run_prefetch(works: list[dict[str, str]], output_dir: Path, protocol: Path,
                       *, max_works: int = 20, max_lookups: int = 5, max_downloads: int = 2,
                       workers: int = 2, lookups: list[tuple[str, LookupFn]] | None = None,
                       fetcher: FetchFn = fetch.fetch_pdf, extractor: ExtractFn = pdf.extract_pdf,
                       marker_reader: math_reader.MathReader | None = None,
                       unconfigured: list[str] | None = None) -> dict[str, Any]:
    if not 1 <= max_works <= 20 or not 0 <= max_lookups <= 5 or not 1 <= max_downloads <= 2 or not 1 <= workers <= 2:
        raise ValueError("prefetch caps exceed the isolated trial profile")
    if not protocol.is_file():
        raise ValueError("a frozen protocol file is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    works = validate_manifest(works)
    report: dict[str, Any] = {"started_at": utc_now(), "protocol_sha256": sha(protocol.read_bytes()),
                              "manifest_canonical_sha256": sha(json.dumps(works, sort_keys=True).encode()),
                              "runner_sha256": sha(Path(__file__).read_bytes()),
                              "manifest_selected": min(len(works), max_works),
                              "manifest_deferred": max(0, len(works) - max_works),
                              "caps": {"works": max_works, "lookups_per_work": max_lookups,
                                       "downloads_per_work": max_downloads, "workers": workers},
                              "unconfigured_lookup_routes": unconfigured or [], "items": []}
    semaphore = asyncio.Semaphore(workers)
    if lookups is None:
        lookups, report["unconfigured_lookup_routes"] = configured_lookups(
            os.environ.get("DEIXIS_CONTACT_EMAIL"), os.environ.get("CORE_API_KEY"), os.environ.get("SERPAPI_API_KEY"))
    marker_tasks: list[asyncio.Task] = []
    async with httpx.AsyncClient(trust_env=False, headers={"User-Agent": "DEIXIS isolated PDF prefetch/2026-09-18"}) as client:
        async def one(work: dict[str, str]) -> dict[str, Any]:
            async with semaphore:
                try:
                    item = await prefetch_one(work, output_dir, client, lookups, fetcher, extractor,
                                              max_lookups, max_downloads)
                    if marker_reader is not None and item["pdf_status"] == "readable_pdf":
                        marker_tasks.append(asyncio.create_task(enrich_marker(item, output_dir, marker_reader)))
                    return item
                except Exception as exc:
                    return {"source_version_id": work["source_version_id"], "rank": work["rank"],
                            "pdf_status": "unexpected_failure", "error_type": type(exc).__name__,
                            "full_text_assessed": False, "marker_status": "not_run"}

        report["items"] = await asyncio.gather(*(one(work) for work in works[:max_works]))
    # A caller may start run_prefetch as a task while citation and text search continue.
    # Marker starts as PDFs arrive; its own lock serializes reads without changing text-layer files.
    if marker_reader is not None:
        await asyncio.gather(*marker_tasks)
        await marker_reader.close()
    else:
        for item in report["items"]:
            if item["pdf_status"] == "readable_pdf":
                item["marker_status"] = "pending_not_configured"
    report["finished_at"] = utc_now()
    (output_dir / "pdf-prefetch-ledger.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-works", type=int, default=20)
    parser.add_argument("--max-lookups", type=int, default=5)
    parser.add_argument("--max-downloads", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--env-file", type=Path,
                        help="optional local credential file; values are never written to the ledger")
    parser.add_argument("--marker-tools-root", type=Path)
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("the selected env file does not exist")
        load_dotenv(args.env_file)
    reader = math_reader.MathReader(math_reader.RuntimePaths(args.marker_tools_root)) if args.marker_tools_root else None
    if reader and not reader.available():
        parser.error("the explicitly selected Marker runtime is not installed")
    rows = json.loads(args.manifest.read_text())
    report = asyncio.run(run_prefetch(rows, args.output_dir, args.protocol, max_works=args.max_works,
                                      max_lookups=args.max_lookups, max_downloads=args.max_downloads,
                                      workers=args.workers, marker_reader=reader))
    print(json.dumps({"selected": report["manifest_selected"],
                      "readable_pdfs": sum(x["pdf_status"] == "readable_pdf" for x in report["items"]),
                      "ledger": str(args.output_dir / "pdf-prefetch-ledger.json")}))


if __name__ == "__main__":
    main()
