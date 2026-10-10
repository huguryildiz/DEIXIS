"""Semantic Scholar's chain page parser (`semantic_scholar.chain_page`), without a run.

The Semantic Scholar chain arm of discovery (D229) is gone with the clean start (slice 3a): the fast chain asks
OpenAlex only, and its run-level tests went with the arm. These tests keep the provider call that still exists:
paging, parse errors and DOI path encoding, against a mocked transport with SYNTHETIC papers.
"""

import asyncio

import httpx

from test_chaining_flow import IRRIGATION, IRRIGATION_ABSTRACT


def paper(number, title=IRRIGATION, abstract=IRRIGATION_ABSTRACT, doi=None):
    return {"paperId": f"s2p{number}", "externalIds": {"DOI": doi or f"10.2/s2.{number}"},
            "title": f"{title} {number}", "abstract": abstract, "year": 2024, "venue": "SYNTHETIC",
            "publicationTypes": ["JournalArticle"], "authors": [{"name": "A. Author"}],
            "url": f"https://www.semanticscholar.org/paper/s2p{number}"}


def test_chain_page_maps_papers_and_names_the_next_offset():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"offset": 0, "next": 2, "data": [
            {"citingPaper": paper(1)}, {"citingPaper": {"paperId": None}}, {"citingPaper": None}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1/x", "forward", 5000, 0, api_key="SYNTHETIC-KEY")

    outcome = asyncio.run(go())
    request = seen[0]
    assert request.url.path == "/graph/v1/paper/DOI:10.1/x/citations" and request.headers["x-api-key"] == "SYNTHETIC-KEY"
    assert request.url.params["limit"] == "1000" and request.url.params["offset"] == "0"
    assert request.url.params["fields"] == semantic_scholar.FIELDS
    assert [r.provider_record_id for r in outcome.records] == ["s2p1"] and outcome.next_cursor == "2"
    assert outcome.status == "completed" and outcome.access_mode == "api_key"


def _chain_answer(payload, direction="forward", offset=0, doi="10.1/x"):
    from deixis.providers import semantic_scholar

    def handler(request):
        return httpx.Response(200, json=payload)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, doi, direction, 400, offset)

    return asyncio.run(go())


def test_a_malformed_next_offset_is_a_parse_error_not_a_crash():
    outcome = _chain_answer({"next": "bogus", "data": [{"citingPaper": paper(1)}]})
    assert outcome.status == "parse_error" and outcome.next_cursor is None and outcome.records == []


def test_a_non_integer_numeric_next_offset_is_a_parse_error():
    from deixis.providers import semantic_scholar

    for value in (150.5, True, "1e3"):
        assert _chain_answer({"next": value, "data": [{"citingPaper": paper(1)}]}).status == "parse_error", value

    async def overflow():  # 1e309 is not valid JSON to write, so the body is sent as text
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"next": 1e309, "data": []}'))
        async with httpx.AsyncClient(transport=transport) as http:
            return await semantic_scholar.chain_page(http, "10.1/x", "forward", 400, 0)

    assert asyncio.run(overflow()).status == "parse_error"
    assert _chain_answer({"next": "150", "data": [{"citingPaper": paper(1)}]}).next_cursor == "150"


def test_a_truncated_backward_page_states_no_total():
    truncated = _chain_answer({"next": 1000, "data": [{"citedPaper": paper(1)}]}, direction="backward")
    assert truncated.next_cursor is None and truncated.provider_total is None
    whole = _chain_answer({"data": [{"citedPaper": paper(1)}, {"citedPaper": paper(2)}]}, direction="backward")
    assert whole.provider_total == 2


def test_a_repeated_or_falling_next_offset_ends_paging():
    assert _chain_answer({"next": 100, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor is None
    assert _chain_answer({"next": 50, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor is None
    assert _chain_answer({"next": 150, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor == "150"


def test_backward_never_reads_next():
    outcome = _chain_answer({"next": "bogus", "data": [{"citedPaper": paper(1)}]}, direction="backward")
    assert outcome.status == "completed" and outcome.next_cursor is None and len(outcome.records) == 1


def test_a_doi_with_dot_segments_keeps_its_identity_on_the_wire():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1234/a/../b", "forward", 10)

    asyncio.run(go())
    assert seen[0].url.raw_path.split(b"?")[0] == b"/graph/v1/paper/DOI:10.1234%2Fa%2F..%2Fb/citations"


def test_a_doi_with_reserved_characters_is_encoded_as_path_data():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1/a?b#c%d e", "backward", 10)

    asyncio.run(go())
    request = seen[0]
    assert request.url.raw_path.split(b"?")[0] == b"/graph/v1/paper/DOI:10.1%2Fa%3Fb%23c%25d%20e/references"
    assert request.url.fragment == "" and request.url.params["limit"] == "10"
