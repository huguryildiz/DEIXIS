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
    "cited_by_count": 17,
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
    assert record.cited_by_count == 17 and "cited_by_count" in seen["url"]
    assert [(o.version_label, o.pdf_url) for o in record.other_versions] == [("acceptedVersion", "https://example.org/a.pdf")]
    assert "search.title_abstract_keywords=molecular" in seen["url"]
    assert "SECRET-KEY-VALUE" not in seen["url"]
    assert "SECRET-KEY-VALUE" not in outcome.request_description
    assert seen["auth"] == "Bearer SECRET-KEY-VALUE"
    assert outcome.access_mode == "api_key" and outcome.rate_limit["x-ratelimit-remaining"] == "990"


def test_zero_results_is_distinct_from_failure():
    outcome = run(lambda r: httpx.Response(200, json={"meta": {"count": 0}, "results": []}))
    assert outcome.status == "zero_results" and outcome.delivery_class is None


def test_connect_error_is_before_send_and_read_timeout_is_unknown():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    assert (run(refuse).status, run(refuse).delivery_class) == ("failed", "before_send")
    assert (run(slow).status, run(slow).delivery_class) == ("timeout", "after_send_unknown")


def test_a_chain_read_asks_for_the_keywords_and_keeps_their_display_names():
    """The chain gate reads OpenAlex's own keywords, so a chain request asks for the field and the record
    carries the names; a keyword without a display name is skipped, and a search read asks for no keyword."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        keyworded = WORK | {"keywords": [{"id": "https://openalex.org/keywords/depth-based-routing",
                                          "display_name": "depth-based routing", "score": 0.99},
                                         {"id": "https://openalex.org/keywords/nameless", "score": 0.4}]}
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [keyworded]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openalex.works_by_ids(client, ["W123"])

    outcome = asyncio.run(go())
    assert f"{openalex.KEYWORDS_FIELD}," in openalex.CHAIN_SELECT + "," and "keywords" in seen["url"]
    assert outcome.records[0].index_keywords == ["depth-based routing"]
    # The author's own keywords stay a different thing and are never filled from the classifier's.
    assert outcome.records[0].author_keywords == []

    # A search asks for the keywords too: `search.title_abstract_keywords` matches them, but the planner names its
    # terms from the values, so they have to come back. A record without keywords still reads as none.
    searched = {}

    def search_handler(request):
        searched["select"] = request.url.params.get("select")
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK]})

    search_only = run(search_handler)
    assert "keywords" in searched["select"]
    assert search_only.records[0].index_keywords == []
