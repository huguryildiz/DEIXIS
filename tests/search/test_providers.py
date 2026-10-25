"""Scholarly provider adapters against mocked HTTP: one test matrix per connection. Live access is checked separately."""

import asyncio
import json

import httpx
import pytest

from deixis.providers import arxiv, biorxiv, common, core, crossref, ieee_xplore, openalex, pubmed, scopus, semantic_scholar, serpapi
from deixis.providers.registry import CONNECTORS

SECRET = "SECRET-KEY-VALUE"
DOI = "10.1109/SYNTH.2021.1"

ARXIV_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>7</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v2</id>
    <title>SYNTHETIC release
      scheduling</title>
    <summary>We schedule release times.</summary>
    <published>2021-01-02T00:00:00Z</published>
    <link href="https://arxiv.org/abs/2101.00001v2" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2101.00001v2" rel="related" type="application/pdf" title="pdf"/>
    <arxiv:doi>10.1109/SYNTH.2021.1</arxiv:doi>
    <author><name>A. Author</name></author>
  </entry>
</feed>"""
EMPTY_FEED = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><opensearch:totalResults>0</opensearch:totalResults></feed>'
PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article>
<Journal><JournalIssue><Volume>12</Volume><Issue>3</Issue><PubDate><MedlineDate>2021 Spring</MedlineDate></PubDate></JournalIssue><Title>Synthetic Transactions</Title></Journal>
<ArticleTitle>SYNTHETIC <i>release</i> scheduling</ArticleTitle>
<Pagination><MedlinePgn>10-19</MedlinePgn></Pagination>
<Abstract><AbstractText Label="BACKGROUND">We schedule release times.</AbstractText><AbstractText Label="RESULTS">It works.</AbstractText></Abstract>
<AuthorList><Author><ForeName>A.</ForeName><LastName>Author</LastName></Author><Author><CollectiveName>Synthetic Group</CollectiveName></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article>
<MeshHeadingList><MeshHeading><DescriptorName UI="D001">Indexer Heading</DescriptorName></MeshHeading></MeshHeadingList>
<KeywordList Owner="NOTNLM"><Keyword MajorTopicYN="N">release scheduling</Keyword><Keyword>  molecular channel  </Keyword>
<Keyword>release scheduling</Keyword><Keyword> </Keyword></KeywordList>
<KeywordList><Keyword>Indexer Keyword</Keyword></KeywordList>
</MedlineCitation><PubmedData><PublicationStatus>ppublish</PublicationStatus><ArticleIdList>
<ArticleId IdType="pubmed">12345678</ArticleId><ArticleId IdType="doi">10.1109/SYNTH.2021.1</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

SUCCESS = {
    "openalex": {"meta": {"count": 3}, "results": [{"id": "https://openalex.org/W1", "doi": f"https://doi.org/{DOI}", "display_name": "SYNTHETIC"}]},
    "semantic_scholar": {"total": 3, "data": [{
        "paperId": "s2abc", "externalIds": {"DOI": DOI, "ArXiv": "2101.00001", "CorpusId": 9}, "title": "SYNTHETIC release scheduling",
        "abstract": "We schedule release times.", "year": 2021, "venue": "Synthetic Transactions", "publicationTypes": ["JournalArticle"],
        "authors": [{"name": "A. Author"}], "url": "https://www.semanticscholar.org/paper/s2abc"}]},
    "crossref": {"status": "ok", "message": {"total-results": 3, "items": [{
        "DOI": DOI, "title": ["SYNTHETIC <i>release</i> scheduling"], "author": [{"given": "A.", "family": "Author"}],
        "issued": {"date-parts": [[2021, 3]]}, "container-title": ["Synthetic Transactions"], "type": "journal-article",
        "abstract": "<jats:title>Abstract</jats:title><jats:p>We schedule release&amp;times.</jats:p>", "URL": f"https://doi.org/{DOI}"}]}},
    "pubmed": {"esearchresult": {"count": "3", "retmax": "1", "idlist": ["12345678"]}},
    "ieee_xplore": {"total_records": 3, "articles": [{
        "article_number": "123", "doi": DOI, "title": "SYNTHETIC <inline-formula>release</inline-formula> scheduling",
        "authors": {"authors": [{"full_name": "A. Author"}]}, "publication_year": 2021, "publication_title": "Synthetic Transactions",
        "content_type": "Journals", "abstract": "We schedule release times.", "html_url": "https://ieeexplore.ieee.org/document/123/",
        "index_terms": {"author_terms": {"terms": ["release scheduling", "  molecular channel  ", "release scheduling", " "]},
                        "ieee_terms": {"terms": ["Indexer Term"]}},
        "pdf_url": "https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=123", "access_type": "LOCKED"}]},
    "scopus": {"search-results": {"opensearch:totalResults": "3", "entry": [{
        "dc:identifier": "SCOPUS_ID:555", "eid": "2-s2.0-555", "dc:title": "SYNTHETIC release scheduling", "dc:creator": "Author A.",
        "prism:publicationName": "Synthetic Transactions", "prism:coverDate": "2021-01-01", "prism:doi": DOI.upper(),
        "subtypeDescription": "Article", "citedby-count": "4", "link": [{"@ref": "scopus", "@href": "https://www.scopus.com/record/555"}]}]}},
    "core": {"totalHits": 3, "limit": 5, "offset": 0, "results": [{
        "id": 777, "doi": DOI, "title": "SYNTHETIC release\n scheduling", "authors": [{"name": "A. Author"}], "yearPublished": 2021,
        "journals": [{"title": "Synthetic Transactions", "identifiers": []}], "documentType": "research article",
        "abstract": "We schedule release times.", "downloadUrl": "https://core.ac.uk/download/555.pdf", "fullText": "SYNTHETIC full text",
        "links": [{"type": "download", "url": "https://core.ac.uk/download/555.pdf"}, {"type": "display", "url": "https://core.ac.uk/works/777"}]}]},
    "serpapi": {"search_metadata": {"json_endpoint": "https://serpapi.com/searches/x.json"}, "search_parameters": {"q": "x"},
                "search_information": {"total_results": 128}, "organic_results": [{
                    "result_id": "r1", "title": "SYNTHETIC release scheduling", "link": f"https://doi.org/{DOI}", "snippet": "… an excerpt …",
                    "publication_info": {"summary": "A Author, B Author - Synthetic Transactions, 2021 - ieeexplore.ieee.org",
                                         "authors": [{"name": "A Author"}, {"name": "B Author"}]}}]},
}
ZERO = {
    "openalex": {"meta": {"count": 0}, "results": []},
    "semantic_scholar": {"total": 0, "offset": 0},
    "crossref": {"message": {"total-results": 0, "items": []}},
    "pubmed": {"esearchresult": {"count": "0", "retmax": "0", "idlist": []}},
    "ieee_xplore": {"total_records": 0, "total_searched": 7408387},
    "scopus": {"search-results": {"opensearch:totalResults": "0", "entry": [{"@_fa": "true", "error": "Result set was empty"}]}},
    "core": {"totalHits": 0, "limit": 5, "offset": 0, "results": []},
    "serpapi": {"search_metadata": {"status": "Success"}, "error": "Google hasn't returned any results for this query."},
}
SUCCESS["biorxiv"], ZERO["biorxiv"] = SUCCESS["openalex"], ZERO["openalex"]
KEYED = {"ieee_xplore", "scopus", "core", "serpapi"}
SEARCH = {"openalex": openalex.search_works, "semantic_scholar": semantic_scholar.search, "crossref": crossref.search,
          "arxiv": arxiv.search, "biorxiv": biorxiv.search, "pubmed": pubmed.search,
          "ieee_xplore": ieee_xplore.search, "scopus": scopus.search,
          "core": core.search, "serpapi": serpapi.search}
ALL = list(SEARCH)


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    sleeps = []

    async def instant(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(common.asyncio, "sleep", instant)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)
    monkeypatch.setattr(arxiv, "MIN_INTERVAL_SECONDS", 0.0)
    return sleeps


def ok_response(provider, zero=False, request=None):
    if provider == "arxiv":
        return httpx.Response(200, text=EMPTY_FEED if zero else ARXIV_FEED)
    if provider == "pubmed" and request is not None and request.url.path.endswith("/efetch.fcgi"):
        return httpx.Response(200, text=PUBMED_XML)
    return httpx.Response(200, json=(ZERO if zero else SUCCESS)[provider])


def run(provider, handler, key=None, limit=5, cursor=None):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await SEARCH[provider](client, "synthetic query", limit, key, "contact@example.org", cursor=cursor)
    return asyncio.run(go()), seen


def key_for(provider):
    return SECRET if provider in KEYED else None


def test_crossref_record_strips_jats_and_filters_types():
    outcome, seen = run("crossref", lambda r: ok_response("crossref"))
    record = outcome.records[0]
    assert record.title == "SYNTHETIC release scheduling" and record.abstract == "We schedule release&times."
    assert (record.authors, record.year, record.version_label) == (["A. Author"], 2021, "publishedVersion")
    assert record.provider_record_id == DOI.lower() and record.abstract_origin == crossref.ABSTRACT_ORIGIN
    params = seen[0].url.params
    assert params["query"] == "synthetic query" and params["mailto"] == "contact@example.org" and "posted-content" in params["filter"]


# ---- the reference count, asked for only on an sw read (slice 05) --------------------------


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar", "crossref"])
def test_zero_results_is_distinct_from_failure(provider):
    outcome, _ = run(provider, lambda r: ok_response(provider, zero=True, request=r), key=key_for(provider))
    assert (outcome.status, outcome.delivery_class, outcome.records) == ("zero_results", None, [])


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar", "crossref"])
def test_short_rate_limit_is_retried_and_counted(provider, no_waits):
    attempts = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        if attempts == 2:
            return httpx.Response(429, headers={"retry-after": "2"})
        return ok_response(provider, request=request)
    outcome, seen = run(provider, handler, key=key_for(provider))
    assert (outcome.status, outcome.retries, len(seen)) == ("completed", 2, 4 if provider == "pubmed" else 3)
    assert no_waits[-2:] == [15.0 if provider in ("semantic_scholar", "arxiv") else 3.0, 2.0]


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar", "crossref"])
def test_long_rate_limit_is_not_retried(provider):
    outcome, seen = run(provider, lambda r: httpx.Response(429, headers={"retry-after": "60"}), key=key_for(provider))
    assert (outcome.status, outcome.delivery_class, len(seen)) == ("rate_limited", "rejected_not_executed", 1)
    assert outcome.rate_limit["retry-after"] == "60"


@pytest.mark.parametrize("provider", ["openalex"])
def test_auth_errors_are_classified_and_redacted(provider):
    key = key_for(provider) or (SECRET if provider in ("openalex", "biorxiv", "semantic_scholar") else None)
    outcome, _ = run(provider, lambda r: httpx.Response(401, text=f"bad key {key}"), key=key)
    assert outcome.status == ("entitlement_missing" if key else "auth_required")
    if key:
        assert SECRET not in (outcome.error or "") and SECRET not in outcome.request_description


@pytest.mark.parametrize("provider", ["semantic_scholar"])
def test_rejected_unknown_parse_and_network_outcomes(provider):
    key = key_for(provider)

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    assert (run(provider, lambda r: httpx.Response(400, text="bad query"), key=key)[0].delivery_class) == "rejected_not_executed"
    assert (run(provider, lambda r: httpx.Response(503), key=key)[0].delivery_class) == "after_send_unknown"
    assert run(provider, lambda r: httpx.Response(200, text="<html>"), key=key)[0].status == "parse_error"
    assert (run(provider, refuse, key=key)[0].status, run(provider, refuse, key=key)[0].delivery_class) == ("failed", "before_send")
    assert (run(provider, slow, key=key)[0].status, run(provider, slow, key=key)[0].delivery_class) == ("timeout", "after_send_unknown")


@pytest.mark.parametrize("provider", ["scopus"])
@pytest.mark.parametrize("key", [None])
def test_key_required_search_without_a_key_sends_no_request(provider, key, monkeypatch):
    monkeypatch.delenv(CONNECTORS[provider].key_env, raising=False)

    def unexpected_request(request):
        pytest.fail("a key-required search sent a request without a key")

    outcome, seen = run(provider, unexpected_request, key=key)
    assert seen == []
    assert (outcome.status, outcome.delivery_class, outcome.access_mode) == (
        "not_configured", "before_send", CONNECTORS[provider].access_mode())
    assert "access=not_configured" in outcome.request_description
    assert outcome.records == [] and outcome.raw_payload is None and outcome.http_status is None
    assert outcome.retries == 0


# ---- paging (slice 04c) -------------------------------------------------------------
# Per provider: the paging mode, the request parameter a page carries, and the value that parameter holds when the
# read continues at record 200. Verified against each provider's own documentation; see the module docstrings.
PAGING = {
    "openalex": ("cursor", "cursor", "IlsxNzA5MjUyNjAwMDAwLCAn"),
    "biorxiv": ("cursor", "cursor", "IlsxNzA5MjUyNjAwMDAwLCAn"),
    "crossref": ("offset", "offset", "200"),
    "semantic_scholar": ("offset", "offset", "200"),
    "arxiv": ("offset", "start", "200"),
    "pubmed": ("offset", "retstart", "200"),
    "ieee_xplore": ("offset", "start_record", "201"),  # 1-based
    "scopus": ("offset", "start", "200"),
    "core": ("offset", "offset", "200"),
    "serpapi": ("single_page", None, None),
}
# What an unpaged request sends today for a parameter the paged read reuses; nothing else may appear.
# Providers whose next cursor is read from the response rather than counted from the offset.
OPENALEX_NEXT = "IlsxNzA5MjUyNjAwMDAwLCAn"


def paged_response(provider, next_cursor=OPENALEX_NEXT, request=None):
    """A first-page answer that says another page follows."""
    if provider in ("openalex", "biorxiv"):
        payload = json.loads(json.dumps(SUCCESS["openalex"]))
        payload["meta"]["next_cursor"] = next_cursor
        return httpx.Response(200, json=payload)
    if provider == "semantic_scholar":
        return httpx.Response(200, json=SUCCESS["semantic_scholar"] | {"next": 1})
    return ok_response(provider, request=request)


def params_of(seen):
    return seen[0].url.params


@pytest.mark.parametrize("provider", ["openalex"])
def test_a_later_page_carries_the_cursor_the_previous_page_gave(provider):
    mode, key, sent = PAGING[provider]
    cursor = OPENALEX_NEXT if mode == "cursor" else "200"
    _, seen = run(provider, lambda r: paged_response(provider, request=r), key=key_for(provider), limit=1, cursor=cursor)
    assert params_of(seen)[key] == sent


@pytest.mark.parametrize("provider", ["scopus"])
def test_a_paged_request_keeps_the_key_out_of_its_description(provider):
    outcome, _ = run(provider, lambda r: ok_response(provider, request=r), key=SECRET, limit=1, cursor=common.FIRST_PAGE)
    assert SECRET not in outcome.request_description


# ---- the reference list, asked for only on an sw read (slice 07) ---------------------------


