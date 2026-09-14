"""OpenAlex adapter against mocked HTTP. Live access is checked separately and reported as such."""

import asyncio
import json

import httpx

from deixis.providers import openalex

WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1234/ABC.def",
    "ids": {"openalex": "https://openalex.org/W123", "doi": "https://doi.org/10.1234/ABC.def"},
    "display_name": "SYNTHETIC molecular channel scheduling",
    "publication_year": 2021,
    "type": "article",
    "authorships": [{"author": {"display_name": "A. Author"}}],
    "primary_location": {"landing_page_url": "https://example.org/a", "version": "publishedVersion", "source": {"display_name": "Synthetic Journal"}},
    "best_oa_location": {"pdf_url": "https://example.org/a.pdf", "version": "acceptedVersion"},
    "open_access": {"is_oa": True},
    "abstract_inverted_index": {"We": [0], "schedule": [1], "release": [2], "times.": [3]},
}


def run(handler, **kwargs):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openalex.search_works(client, "molecular scheduling", 5, **kwargs)
    return asyncio.run(go())


def test_success_normalizes_record_and_reconstructs_abstract():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"meta": {"count": 40}, "results": [WORK]}, headers={"x-ratelimit-remaining": "990"})

    outcome = run(handler, api_key="SECRET-KEY-VALUE")
    assert outcome.status == "completed" and outcome.provider_total == 40
    record = outcome.records[0]
    assert record.provider_record_id == "W123"
    assert record.doi == "10.1234/abc.def"
    assert record.abstract == "We schedule release times."
    assert record.abstract_origin == openalex.ABSTRACT_ORIGIN
    assert record.version_label == "publishedVersion" and record.oa_pdf_url.endswith(".pdf")
    assert record.oa_pdf_version == "acceptedVersion"  # kept separate from the primary location's version
    assert [(o.version_label, o.pdf_url) for o in record.other_versions] == [("acceptedVersion", "https://example.org/a.pdf")]
    assert "search.title_and_abstract=molecular" in seen["url"]
    assert "SECRET-KEY-VALUE" not in seen["url"]
    assert "SECRET-KEY-VALUE" not in outcome.request_description
    assert seen["auth"] == "Bearer SECRET-KEY-VALUE"
    assert outcome.access_mode == "api_key" and outcome.rate_limit["x-ratelimit-remaining"] == "990"


def test_zero_results_is_distinct_from_failure():
    outcome = run(lambda r: httpx.Response(200, json={"meta": {"count": 0}, "results": []}))
    assert outcome.status == "zero_results" and outcome.delivery_class is None


def test_rate_limit_is_rejected_not_executed_with_retry_after():
    outcome = run(lambda r: httpx.Response(429, headers={"retry-after": "30"}))
    assert (outcome.status, outcome.delivery_class) == ("rate_limited", "rejected_not_executed")
    assert outcome.rate_limit["retry-after"] == "30"


def test_connect_error_is_before_send_and_read_timeout_is_unknown():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    assert (run(refuse).status, run(refuse).delivery_class) == ("failed", "before_send")
    assert (run(slow).status, run(slow).delivery_class) == ("timeout", "after_send_unknown")


def test_auth_and_parse_errors():
    assert run(lambda r: httpx.Response(403, text="forbidden")).status == "auth_required"
    assert run(lambda r: httpx.Response(403, text="forbidden"), api_key="k").status == "entitlement_missing"
    assert run(lambda r: httpx.Response(200, text="<html>")).status == "parse_error"
    assert run(lambda r: httpx.Response(200, content=json.dumps({"meta": {}}).encode())).status == "parse_error"
