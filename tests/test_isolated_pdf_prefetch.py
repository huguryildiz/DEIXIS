"""Network-free checks for the opt-in PDF stage of an isolated search."""

from __future__ import annotations

import asyncio
import json

import pymupdf

from deixis.documents import acquisition, fetch, pdf
from scripts.isolated_pdf_prefetch import run_prefetch, safe_error_code


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Quantum network optimization model and routing constraints.")
    result = document.tobytes()
    document.close()
    return result


def _work(number: int) -> dict[str, str]:
    return {"source_version_id": f"version-{number}", "doi": f"10.1234/work-{number}",
            "title": f"Quantum model {number}", "version_label": "publishedVersion"}


def test_prefetch_requires_a_version_matched_real_pdf_and_preserves_page_text(tmp_path):
    protocol = tmp_path / "protocol.md"
    protocol.write_text("frozen trial\n")
    calls = []

    async def lookup(_client, work):
        if work["source_version_id"] == "version-1":
            candidate = acquisition.Candidate("openalex", "https://example.org/paper.pdf", None,
                                              "publishedVersion", None, "doi_verified", "match")
        else:
            candidate = acquisition.Candidate("openalex", "https://example.org/preprint.pdf", None,
                                              "submittedVersion", None, "doi_verified", "different")
        return acquisition.Lookup("completed", [candidate], 200)

    async def fetch_pdf(url):
        calls.append(url)
        return fetch.FetchResult("ok", data=_pdf_bytes(), final_url=url, http_status=200)

    output = tmp_path / "output"
    report = asyncio.run(run_prefetch([_work(1), _work(2)], output, protocol,
                                      lookups=[("openalex", lookup)], fetcher=fetch_pdf,
                                      max_lookups=1, workers=2))
    good, blocked = report["items"]
    assert calls == ["https://example.org/paper.pdf"]
    assert good["pdf_status"] == "readable_pdf"
    assert good["full_text_assessed"] is False
    assert good["marker_status"] == "pending_not_configured"
    assert good["text_pages"] == 1
    text = json.loads((output / "text" / f"{good['pdf_sha256']}.json").read_text())
    assert text["pages"][0]["physical_page"] == 1
    assert "routing constraints" in text["pages"][0]["text"]
    assert "=== Physical page 1 ===" in (output / "text" / f"{good['pdf_sha256']}.txt").read_text()
    assert blocked["pdf_status"] == "no_eligible_pdf"
    assert blocked["manual_version_candidates"] == 1
    assert blocked["pdf_download_attempts"] == []
    assert blocked["pdf_candidates"][0]["version_status"] == "different"
    assert "preprint.pdf" not in json.dumps(blocked["pdf_candidates"])


def test_prefetch_keeps_failed_lookup_distinct_from_zero_and_caps_selection(tmp_path):
    protocol = tmp_path / "protocol.md"
    protocol.write_text("frozen trial\n")

    async def lookup(_client, _work):
        return acquisition.Lookup("rate_limited", [], 429, "rate_limited")

    async def unexpected_fetch(_url):
        raise AssertionError("no PDF candidate was returned")

    report = asyncio.run(run_prefetch([_work(1), _work(2)], tmp_path / "output", protocol,
                                      max_works=1, lookups=[("openalex", lookup)],
                                      fetcher=unexpected_fetch, max_lookups=1))
    assert report["manifest_selected"] == 1
    assert report["manifest_deferred"] == 1
    assert report["items"][0]["pdf_status"] == "lookup_incomplete"
    assert report["items"][0]["pdf_lookup_attempts"][0]["http_status"] == 429


def test_prefetch_records_a_downloaded_scan_without_claiming_full_text(tmp_path):
    protocol = tmp_path / "protocol.md"
    protocol.write_text("frozen trial\n")
    work = _work(1) | {"direct_pdf_url": "https://example.org/paper.pdf",
                       "direct_pdf_version": "publishedVersion"}

    async def fetch_pdf(url):
        return fetch.FetchResult("ok", data=_pdf_bytes(), final_url=url, http_status=200)

    def no_text(_path):
        return pdf.Extraction("no_text", page_count=1, image_pages=[1])

    report = asyncio.run(run_prefetch([work], tmp_path / "output", protocol, max_lookups=0,
                                      fetcher=fetch_pdf, extractor=no_text))
    item = report["items"][0]
    assert item["pdf_status"] == "pdf_no_text"
    assert item["text_pages"] == 0
    assert item["full_text_assessed"] is False


def test_provider_error_text_is_not_logged():
    assert safe_error_code("Your API key abc123 was rejected") == "provider_message_redacted"
    assert safe_error_code("rate_limited") == "rate_limited"
