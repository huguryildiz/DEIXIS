"""Scholarly provider adapters against mocked HTTP: one test matrix per connection. Live access is checked separately."""

import asyncio
import json

import httpx
import pytest

from deixis.providers import arxiv, biorxiv, common, core, crossref, ieee_xplore, openalex, pubmed, scopus, semantic_scholar, serpapi
from deixis.providers.registry import CONNECTORS, available_providers

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
</Article></MedlineCitation><PubmedData><PublicationStatus>ppublish</PublicationStatus><ArticleIdList>
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


def test_semantic_scholar_record():
    outcome, seen = run("semantic_scholar", lambda r: ok_response("semantic_scholar"), key=SECRET)
    record = outcome.records[0]
    assert (outcome.status, outcome.provider_total, outcome.access_mode) == ("completed", 3, "api_key")
    assert seen[0].headers["x-api-key"] == SECRET and SECRET not in str(seen[0].url)
    assert (record.provider_record_id, record.doi, record.year, record.venue) == ("s2abc", DOI.lower(), 2021, "Synthetic Transactions")
    assert record.abstract_origin == semantic_scholar.ABSTRACT_ORIGIN and record.oa_pdf_url is None
    assert record.merge_by_doi and record.identifiers["ArXiv"] == "2101.00001"


def test_semantic_scholar_arxiv_only_record_gets_no_doi():
    payload = {"total": 1, "data": [{"paperId": "p", "externalIds": {"ArXiv": "2101.00001"}, "title": "T"}]}
    outcome, _ = run("semantic_scholar", lambda r: httpx.Response(200, json=payload))
    assert outcome.records[0].doi is None and outcome.access_mode == "keyless"


def test_crossref_record_strips_jats_and_filters_types():
    outcome, seen = run("crossref", lambda r: ok_response("crossref"))
    record = outcome.records[0]
    assert record.title == "SYNTHETIC release scheduling" and record.abstract == "We schedule release&times."
    assert (record.authors, record.year, record.version_label) == (["A. Author"], 2021, "publishedVersion")
    assert record.provider_record_id == DOI.lower() and record.abstract_origin == crossref.ABSTRACT_ORIGIN
    params = seen[0].url.params
    assert params["query"] == "synthetic query" and params["mailto"] == "contact@example.org" and "posted-content" in params["filter"]


def test_crossref_posted_content_is_a_submitted_version():
    item = {**SUCCESS["crossref"]["message"]["items"][0], "type": "posted-content"}
    outcome, _ = run("crossref", lambda r: httpx.Response(200, json={"message": {"total-results": 1, "items": [item]}}))
    assert outcome.records[0].version_label == "submittedVersion"


def test_pubmed_record_uses_esearch_then_efetch_and_maps_abstract():
    outcome, seen = run("pubmed", lambda r: ok_response("pubmed", request=r), key=SECRET)
    record = outcome.records[0]
    assert (outcome.status, outcome.provider_total, outcome.access_mode) == ("completed", 3, "api_key")
    assert [request.url.path.rsplit("/", 1)[-1] for request in seen] == ["esearch.fcgi", "efetch.fcgi"]
    assert seen[0].url.params["api_key"] == SECRET and seen[0].url.params["tool"] == "DEIXIS"
    assert seen[0].url.params["sort"] == "relevance" and seen[1].url.params["id"] == "12345678"
    assert SECRET not in outcome.request_description
    assert (record.provider_record_id, record.doi, record.year, record.venue) == (
        "12345678", DOI.lower(), 2021, "Synthetic Transactions")
    assert record.title == "SYNTHETIC release scheduling"
    assert record.authors == ["A. Author", "Synthetic Group"]
    assert record.abstract == "BACKGROUND: We schedule release times.\n\nRESULTS: It works."
    assert record.abstract_origin == pubmed.ABSTRACT_ORIGIN
    assert (record.volume, record.issue, record.pages) == ("12", "3", "10-19")
    assert record.landing_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/" and record.oa_pdf_url is None


def test_arxiv_record_is_one_version_with_its_pdf():
    outcome, seen = run("arxiv", lambda r: ok_response("arxiv"))
    record = outcome.records[0]
    assert (outcome.status, outcome.provider_total) == ("completed", 7)
    assert (record.provider_record_id, record.version_label, record.oa_pdf_version) == ("2101.00001v2", "arXiv v2", "arXiv v2")
    assert record.oa_pdf_url == "https://arxiv.org/pdf/2101.00001v2" and record.title == "SYNTHETIC release scheduling"
    assert record.doi == "10.48550/arxiv.2101.00001" and not record.merge_by_doi
    assert record.identifiers["published_doi"] == DOI.lower()
    assert seen[0].url.params["sortBy"] == "relevance"


def test_biorxiv_searches_openalex_limited_to_the_biorxiv_source():
    outcome, seen = run("biorxiv", lambda r: ok_response("biorxiv"))
    params = seen[0].url
    assert params.host == "api.openalex.org" and params.params["filter"] == "locations.source.id:S4306402567"
    assert "filter=locations.source.id:S4306402567" in outcome.request_description
    assert outcome.records[0].provider_record_id == "W1" and outcome.status == "completed"


def test_ieee_record_redacts_key_and_attaches_no_pdf():
    outcome, seen = run("ieee_xplore", lambda r: ok_response("ieee_xplore"), key=SECRET)
    record = outcome.records[0]
    assert seen[0].url.params["apikey"] == SECRET
    assert SECRET not in outcome.request_description and SECRET not in json.dumps(outcome.raw_payload)
    assert (record.provider_record_id, record.title, record.oa_pdf_url) == ("123", "SYNTHETIC release scheduling", None)
    assert record.abstract_origin == ieee_xplore.ABSTRACT_ORIGIN and record.version_label == "publishedVersion"


def test_ieee_over_quota_403_is_a_rate_limit():
    outcome, _ = run("ieee_xplore", lambda r: httpx.Response(403, headers={"x-error-detail-header": "Account Over Queries Per Day Limit"}), key=SECRET)
    assert (outcome.status, outcome.delivery_class) == ("rate_limited", "rejected_not_executed")


def test_scopus_record_has_no_abstract_and_key_in_header_only():
    outcome, seen = run("scopus", lambda r: ok_response("scopus"), key=SECRET)
    record = outcome.records[0]
    assert seen[0].headers["x-els-apikey"] == SECRET and SECRET not in str(seen[0].url)
    assert (record.provider_record_id, record.doi, record.year, record.abstract) == ("555", DOI.lower(), 2021, None)
    assert record.authors == ["Author A."] and record.landing_url == "https://www.scopus.com/record/555"


@pytest.mark.parametrize("answer, expected", [(200, True), (401, False), (429, None), (500, None), (httpx.ConnectError("down"), None)])
def test_scopus_complete_view_probe_reads_entitlement(answer, expected):
    seen = []

    def handler(request):
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await scopus.complete_view_entitled(client, SECRET)
    assert asyncio.run(go()) is expected
    assert seen[0].url.params["view"] == "COMPLETE" and seen[0].headers["X-ELS-APIKey"] == SECRET and SECRET not in str(seen[0].url)


def test_core_record_attaches_no_pdf_and_drops_full_text():
    outcome, seen = run("core", lambda r: ok_response("core"), key=SECRET)
    record = outcome.records[0]
    assert str(seen[0].url).startswith(core.SEARCH_URL) and seen[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(seen[0].url) and SECRET not in outcome.request_description
    assert (record.provider_record_id, record.title, record.doi, record.year, record.venue) == (
        "777", "SYNTHETIC release scheduling", DOI.lower(), 2021, "Synthetic Transactions")
    assert (record.oa_pdf_url, record.version_label, record.landing_url) == (None, None, "https://core.ac.uk/works/777")
    assert record.abstract_origin == core.ABSTRACT_ORIGIN and record.identifiers == {"core_work_id": "777", "doi": DOI.lower()}
    assert "fullText" not in record.raw and "fullText" not in json.dumps(outcome.raw_payload) and outcome.provider_total == 3


def test_serpapi_record_keeps_snippet_out_of_the_abstract():
    outcome, seen = run("serpapi", lambda r: ok_response("serpapi"), key=SECRET)
    record = outcome.records[0]
    assert seen[0].url.params["engine"] == "google_scholar" and seen[0].url.params["api_key"] == SECRET
    assert (record.abstract, record.abstract_origin, record.oa_pdf_url) == (None, None, None)
    assert (record.authors, record.year, record.venue, record.doi) == (["A Author", "B Author"], 2021, "Synthetic Transactions", DOI.lower())
    assert "search_parameters" not in outcome.raw_payload and outcome.provider_total == 128


def test_serpapi_quota_exhaustion_is_not_retried(no_waits):
    outcome, seen = run("serpapi", lambda r: httpx.Response(429, json={"error": "Your account has run out of searches."}), key=SECRET)
    assert outcome.status == "rate_limited" and len(seen) == 1 and no_waits == []


def test_serpapi_error_payload_is_a_failure_not_zero_results():
    outcome, _ = run("serpapi", lambda r: httpx.Response(200, json={"error": "Unsupported parameter."}), key=SECRET)
    assert (outcome.status, outcome.delivery_class) == ("failed", "rejected_not_executed")


@pytest.mark.parametrize("provider", ALL)
def test_zero_results_is_distinct_from_failure(provider):
    outcome, _ = run(provider, lambda r: ok_response(provider, zero=True, request=r), key=key_for(provider))
    assert (outcome.status, outcome.delivery_class, outcome.records) == ("zero_results", None, [])


@pytest.mark.parametrize("provider", [p for p in ALL if p != "serpapi"])
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


def test_arxiv_rate_limit_without_retry_after_uses_bounded_15_and_30_second_backoff(no_waits):
    outcome, seen = run("arxiv", lambda r: httpx.Response(429))
    assert (outcome.status, outcome.retries, len(seen)) == ("rate_limited", 2, 3)
    assert no_waits[-2:] == [15.0, 30.0]


@pytest.mark.parametrize("provider", ALL)
def test_long_rate_limit_is_not_retried(provider):
    outcome, seen = run(provider, lambda r: httpx.Response(429, headers={"retry-after": "60"}), key=key_for(provider))
    assert (outcome.status, outcome.delivery_class, len(seen)) == ("rate_limited", "rejected_not_executed", 1)
    assert outcome.rate_limit["retry-after"] == "60"


@pytest.mark.parametrize("provider", ALL)
def test_auth_errors_are_classified_and_redacted(provider):
    key = key_for(provider) or (SECRET if provider in ("openalex", "biorxiv", "semantic_scholar") else None)
    outcome, _ = run(provider, lambda r: httpx.Response(401, text=f"bad key {key}"), key=key)
    assert outcome.status == ("entitlement_missing" if key else "auth_required")
    if key:
        assert SECRET not in (outcome.error or "") and SECRET not in outcome.request_description


@pytest.mark.parametrize("provider", ALL)
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


@pytest.mark.parametrize("provider", ALL)
def test_result_limit_is_capped_by_the_provider_maximum(provider):
    _, seen = run(provider, lambda r: ok_response(provider), key=key_for(provider), limit=500)
    params = seen[0].url.params
    sent = next(int(params[k]) for k in ("per_page", "limit", "rows", "max_results", "max_records", "count", "num", "retmax") if k in params)
    assert sent == min(500, CONNECTORS[provider].max_results)


def test_available_providers_follow_configured_keys(monkeypatch):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    assert available_providers() == ["openalex", "semantic_scholar", "crossref", "arxiv", "biorxiv", "pubmed"]
    assert CONNECTORS["scopus"].access_mode() == "not_configured"
    monkeypatch.setenv("IEEE_API_KEY", SECRET)
    assert available_providers()[-1] == "ieee_xplore" and CONNECTORS["ieee_xplore"].access_mode() == "api_key"


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
UNPAGED = {"arxiv": ("start", "0"), "ieee_xplore": ("start_record", "1")}
# Providers whose next cursor is read from the response rather than counted from the offset.
NEXT_IN_RESPONSE = {"openalex", "biorxiv", "semantic_scholar"}
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


@pytest.mark.parametrize("provider", ALL)
def test_a_search_without_a_cursor_sends_the_request_it_sent_before(provider):
    """The legacy path: no paging parameter appears and the provider is not asked for a next cursor."""
    outcome, seen = run(provider, lambda r: ok_response(provider, request=r), key=key_for(provider), limit=1)
    params = params_of(seen)
    key, expected = UNPAGED.get(provider, (PAGING[provider][1], None))
    assert params.get(key) == expected if key else True
    assert "cursor" not in params and outcome.next_cursor is None


@pytest.mark.parametrize("provider", ALL)
def test_the_first_page_is_asked_for_with_the_provider_own_parameter(provider):
    mode, key, _ = PAGING[provider]
    outcome, seen = run(provider, lambda r: paged_response(provider, request=r), key=key_for(provider), limit=1,
                        cursor=common.FIRST_PAGE)
    params = params_of(seen)
    if mode == "cursor":
        assert params["cursor"] == common.FIRST_PAGE
        assert outcome.next_cursor == OPENALEX_NEXT
    elif mode == "offset":
        assert params[key] == ("1" if provider == "ieee_xplore" else "0")
        assert outcome.next_cursor == "1"  # one record read out of a provider total of three
    else:
        assert "start" not in params and outcome.next_cursor is None
    assert SECRET not in (outcome.request_description or "")


@pytest.mark.parametrize("provider", [p for p in ALL if p != "serpapi"])
def test_a_later_page_carries_the_cursor_the_previous_page_gave(provider):
    mode, key, sent = PAGING[provider]
    cursor = OPENALEX_NEXT if mode == "cursor" else "200"
    _, seen = run(provider, lambda r: paged_response(provider, request=r), key=key_for(provider), limit=1, cursor=cursor)
    assert params_of(seen)[key] == sent


@pytest.mark.parametrize("provider", [p for p in ALL if p not in NEXT_IN_RESPONSE and p != "serpapi"])
def test_an_offset_page_that_came_back_short_is_the_last_one(provider):
    """Fewer records than asked for means the provider has no more; nothing further is requested."""
    outcome, _ = run(provider, lambda r: ok_response(provider, request=r), key=key_for(provider), limit=5,
                     cursor=common.FIRST_PAGE)
    assert outcome.next_cursor is None


@pytest.mark.parametrize("provider", ["openalex", "biorxiv"])
def test_openalex_reports_the_end_of_a_cursor_read_as_a_null_cursor(provider):
    outcome, _ = run(provider, lambda r: paged_response(provider, next_cursor=None), key=key_for(provider), limit=1,
                     cursor=common.FIRST_PAGE)
    assert outcome.next_cursor is None


def test_semantic_scholar_without_a_next_field_has_no_further_page():
    outcome, _ = run("semantic_scholar", lambda r: ok_response("semantic_scholar"), limit=1, cursor=common.FIRST_PAGE)
    assert outcome.next_cursor is None


def test_serpapi_reads_one_page_whatever_the_cursor_says():
    outcome, seen = run("serpapi", lambda r: ok_response("serpapi"), key=SECRET, limit=1, cursor="20")
    assert outcome.next_cursor is None and "start" not in params_of(seen)


@pytest.mark.parametrize("provider", [p for p in ALL if PAGING[p][0] == "offset"])
def test_a_cursor_an_offset_provider_never_issued_is_a_code_error(provider):
    with pytest.raises(ValueError):
        run(provider, lambda r: ok_response(provider, request=r), key=key_for(provider), limit=1, cursor="page-2")


@pytest.mark.parametrize("provider", sorted(KEYED))
def test_a_paged_request_keeps_the_key_out_of_its_description(provider):
    outcome, _ = run(provider, lambda r: ok_response(provider, request=r), key=SECRET, limit=1, cursor=common.FIRST_PAGE)
    assert SECRET not in outcome.request_description


def test_the_registry_records_how_each_provider_pages():
    assert {p: CONNECTORS[p].paging for p in ALL} == {p: PAGING[p][0] for p in ALL}
    assert CONNECTORS["semantic_scholar"].max_reachable == 1000
    assert [p for p in ALL if CONNECTORS[p].max_reachable] == ["semantic_scholar"]
    assert CONNECTORS["arxiv"].page_gap == 3.0
    assert [p for p in ALL if CONNECTORS[p].page_gap] == ["arxiv"]
