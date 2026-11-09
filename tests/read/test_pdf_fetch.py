"""Fetching PDFs from untrusted hosts: only public addresses, malformed links refused, one deadline, extra headers kept on the first https origin; and where the acquisition looks for an open copy. SYNTHETIC hosts, every transport mocked."""

import asyncio
import hashlib
import os
import sys
import time
import httpx
import pytest
from deixis.documents import fetch, pdf
from helpers import make_pdf
import json
from deixis.documents import acquisition
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.run.store import Store


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8765/api/researches",
    ],
)
def test_private_or_unsafe_urls_are_blocked(url):
    result = asyncio.run(fetch.fetch_pdf(url))
    assert result.status == "blocked_url"


def _child(code: str) -> list[str]:
    return [sys.executable, "-c", code]


PLAIN_ENV = {"PATH": os.environ.get("PATH", "")}


def _wait_for_pid(pid_file) -> int:
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and pid_file.read_text(encoding="utf-8")):
        assert time.monotonic() < deadline, "the child never wrote its pid"
        time.sleep(0.05)
    return int(pid_file.read_text(encoding="utf-8"))


def resolver(*answers):
    calls = []

    async def resolve(host, port):
        calls.append(host)
        return answers[min(len(calls), len(answers)) - 1][host]
    return resolve, calls


def test_fetch_connects_to_the_checked_address_so_a_second_dns_answer_is_not_used(monkeypatch):
    # First answer public, any later answer private (DNS rebinding).
    resolve, calls = resolver({"papers.example": ["93.184.216.34"]}, {"papers.example": ["127.0.0.1"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=make_pdf(["SYNTHETIC"]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf?x=1", client)

    result = asyncio.run(run())
    assert result.status == "ok" and calls == ["papers.example"]
    request = seen[0]
    assert (request.url.host, request.url.path, request.url.query) == ("93.184.216.34", "/a.pdf", b"x=1")
    assert request.headers["host"] == "papers.example" and request.extensions["sni_hostname"] == "papers.example"
    assert result.final_url == "https://papers.example/a.pdf?x=1"


def test_a_pdf_request_asks_for_a_pdf_and_names_the_contact_address(monkeypatch):
    resolve, _ = resolver({"papers.example": ["93.184.216.34"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "owner@example.org")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=make_pdf(["SYNTHETIC"]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": fetch.user_agent()}) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf", client)

    assert asyncio.run(run()).status == "ok"
    assert seen[0].headers["accept"] == fetch.PDF_ACCEPT
    assert seen[0].headers["user-agent"] == "DEIXIS/0.1 (local research workspace; mailto:owner@example.org)"
    monkeypatch.delenv("DEIXIS_CONTACT_EMAIL")
    assert fetch.user_agent() == fetch.USER_AGENT


def test_redirect_to_a_private_address_is_blocked(monkeypatch):
    resolve, _ = resolver({"papers.example": ["93.184.216.34"], "intranet.example": ["10.0.0.7"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)

    def handler(request):
        return httpx.Response(302, headers={"location": "http://intranet.example/secret.pdf"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf", client)

    result = asyncio.run(run())
    assert result.status == "blocked_url" and result.final_url == "http://intranet.example/secret.pdf"


def test_a_pdf_fetch_has_one_deadline_for_the_whole_transfer(monkeypatch):
    resolve, _ = resolver({"papers.example": ["93.184.216.34"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)

    async def trickle():
        yield b"%PDF-1.4 SYNTHETIC"
        while True:  # each chunk arrives inside the per-read timeout; only the whole-fetch deadline ends it
            await asyncio.sleep(0.02)
            yield b" more"

    def handler(request):
        return httpx.Response(200, content=trickle())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf", client, deadline=0.3)

    result = asyncio.run(run())
    assert (result.status, result.error, result.final_url) == ("timeout", "deadline", "https://papers.example/a.pdf")


def resolving_to(monkeypatch, address):
    async def resolve(host, port):
        return [address]
    monkeypatch.setattr(fetch, "_resolve", resolve)


@pytest.mark.parametrize("address", ["100.64.0.1"])
def test_a_non_global_address_is_refused(monkeypatch, address):
    resolving_to(monkeypatch, address)
    with pytest.raises(fetch.BlockedUrl, match="non-public"):
        asyncio.run(fetch.check_public_url("https://papers.example/a.pdf"))


MALFORMED = ["https://papers.example:99999/x.pdf", "https://papers.example:abc/x.pdf", "https://[::1/x.pdf",
             "http://[not-an-ip]/x.pdf", "http://a..b.example/x.pdf", "http://.example/x.pdf",
             "http://" + "a" * 64 + ".example/x.pdf", "https://papers.example/a\x00.pdf", "https://papers.example/a\x7f.pdf",
             "https://papers.example/a.pdf?q=\x00", "https://\u2603.example/x.pdf", "https://xn--zz.example/x.pdf"]


PUBLIC = "93.184.216.34"


def resolving_public(monkeypatch, resolved=None):
    """Every host resolves to a public address, after the IDNA encoding getaddrinfo applies to a str host (where an
    empty or too-long label fails); no lookup leaves the machine."""
    async def resolve(host, port):
        host.encode("idna")
        if resolved is not None:
            resolved.append(host)
        return [PUBLIC]
    monkeypatch.setattr(fetch, "_resolve", resolve)


def never_called(request):
    raise AssertionError(f"request sent to {request.url}")


@pytest.mark.parametrize("url", [MALFORMED[7]])
def test_a_malformed_url_is_a_blocked_url_result_not_an_exception(monkeypatch, url):
    resolving_public(monkeypatch)
    client = httpx.AsyncClient(transport=httpx.MockTransport(never_called))
    result = asyncio.run(fetch.fetch_pdf(url, client))
    assert (result.status, result.final_url) == ("blocked_url", url)
    assert result.error.startswith("not a valid URL")


@pytest.mark.parametrize("location", [MALFORMED[2]])
def test_a_malformed_redirect_location_is_a_blocked_url_result(monkeypatch, location):
    resolving_public(monkeypatch)
    sent = []

    def handler(request):
        sent.append(request.url)
        return httpx.Response(302, headers=[(b"location", location.encode())])  # the bytes a server would send

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://papers.example/a.pdf", client))
    assert result.status == "blocked_url" and result.error.startswith("not a valid URL")
    assert len(sent) == 1  # the malformed hop was never requested


class OwnClient(httpx.AsyncClient):
    """The client `_fetch` opens for itself when none is given, with a mock transport in place of the network."""
    sent: list[httpx.Request] = []

    def __init__(self, **kwargs):
        def handler(request):
            OwnClient.sent.append(request)
            return httpx.Response(403, headers={"content-type": "text/html; charset=utf-8"}, content=b"<html>SYNTHETIC</html>")
        super().__init__(transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.parametrize("email, env, agent", [
    ("me@synthetic.example", None, "DEIXIS/0.1 (local research workspace; mailto:me@synthetic.example)"),
])
def test_the_pdf_fetch_names_the_settings_email_in_its_user_agent(monkeypatch, email, env, agent):
    resolving_public(monkeypatch)
    monkeypatch.setattr(fetch.httpx, "AsyncClient", OwnClient)
    if env:
        monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", env)
    else:
        monkeypatch.delenv("DEIXIS_CONTACT_EMAIL", raising=False)
    OwnClient.sent = []
    result = asyncio.run(fetch.fetch_pdf("https://papers.example/a.pdf", email=email))
    assert [request.headers["user-agent"] for request in OwnClient.sent] == [agent]
    # A refusal keeps its status, the address that refused and the type it answered with (a bot check's HTML page).
    assert (result.status, result.http_status, result.final_url, result.media_type) == (
        "http_error", 403, "https://papers.example/a.pdf", "text/html")


def test_extra_headers_go_to_the_first_host_alone(monkeypatch):
    resolving_public(monkeypatch)
    seen = []

    def handler(request):
        seen.append((request.headers["host"], request.headers.get("x-els-apikey")))
        if request.headers["host"] == "api.publisher.example":
            return httpx.Response(302, headers={"location": "https://cdn.elsewhere.example/a.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 SYNTHETIC")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://api.publisher.example/a?httpAccept=application/pdf", client,
                                         headers={"X-ELS-APIKey": "SYNTHETIC-KEY"}))
    assert result.status == "ok"
    assert seen == [("api.publisher.example", "SYNTHETIC-KEY"), ("cdn.elsewhere.example", None)]


def test_a_key_the_query_string_carries_goes_to_the_first_host_alone_and_is_reported_to_nobody(monkeypatch):
    """A service that takes its key only in the query string (OpenAlex's content host) is sent it for that one
    request. It does not cross a redirect to another host, and the address reported back — which is stored with the
    file — does not carry it."""
    resolving_public(monkeypatch)
    seen = []

    def handler(request):
        seen.append((request.headers["host"], request.url.params.get("api_key")))
        if request.headers["host"] == "content.openalex.example":
            return httpx.Response(302, headers={"location": "https://cdn.elsewhere.example/a.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 SYNTHETIC")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://content.openalex.example/works/W7.pdf", client,
                                         query={"api_key": "SYNTHETIC-KEY"}))
    assert result.status == "ok"
    assert seen == [("content.openalex.example", "SYNTHETIC-KEY"), ("cdn.elsewhere.example", None)]
    assert "api_key" not in (result.final_url or "")


@pytest.mark.parametrize("location", ["http://api.publisher.example/a.pdf", "https://api.publisher.example:8443/a.pdf"])
def test_extra_headers_do_not_follow_a_redirect_to_plain_http_or_another_port(monkeypatch, location):
    resolving_public(monkeypatch)
    seen = []

    def handler(request):
        seen.append((str(request.url.scheme), request.headers.get("x-els-apikey")))
        if not seen[1:]:
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 SYNTHETIC")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://api.publisher.example/a", client, headers={"X-ELS-APIKey": "SYNTHETIC-KEY"}))
    assert result.status == "ok" and [key for _, key in seen] == ["SYNTHETIC-KEY", None]


def run(coro):
    return asyncio.run(coro)


def test_core_requires_key_without_calling_network():
    def handler(request):
        raise AssertionError("CORE must not be called without a key")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.core_lookup(client, "10.1/test", None)

    result = run(check())
    assert (result.status, result.error_code) == ("auth_required", "missing_core_key")


def _candidate(provider, url, version="match", identity="doi_verified"):
    return {"provider": provider, "candidate_url": url, "version_status": version, "identity_status": identity}


def test_the_download_order_comes_from_the_candidate_fields_not_from_who_answered_first():
    rows = [
        _candidate("crossref", "https://c.example/a.pdf"),
        _candidate("unpaywall", "https://u.example/b.pdf", version="different"),
        _candidate("unpaywall", "https://u.example/a.pdf"),
        _candidate("core", "https://core.example/a.pdf"),
        _candidate("openalex", "https://o.example/b.pdf", identity="title_verified"),
        _candidate("openalex", "https://o.example/a.pdf"),
    ]
    wanted = ["https://u.example/a.pdf", "https://u.example/b.pdf", "https://o.example/a.pdf",
              "https://o.example/b.pdf", "https://c.example/a.pdf", "https://core.example/a.pdf"]
    for arrival in (rows, list(reversed(rows)), [rows[i] for i in (3, 0, 5, 2, 4, 1)]):
        assert [c["candidate_url"] for c in acquisition.candidate_order(arrival)] == wanted
    # A provider the order does not name goes last and still sorts by its own fields, never by arrival.
    unknown = [_candidate("web_search", "https://w.example/b.pdf"), _candidate("web_search", "https://w.example/a.pdf")]
    assert [c["candidate_url"] for c in acquisition.candidate_order(unknown)] == [
        "https://w.example/a.pdf", "https://w.example/b.pdf"]
    # A run queued before the rule existed carries none and keeps the order it would have downloaded under.
    assert [c["candidate_url"] for c in acquisition.candidate_order(rows, None)] == [c["candidate_url"] for c in rows]


def test_the_first_provider_of_the_fixed_order_is_downloaded_although_another_answered_first(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord("W1", "Exact synthetic title", [], 2020, "J", "article", "10.1/test",
                            "https://publisher.example/item", None, None, "publishedVersion", None, None, {}, {})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")
    # Crossref's copy is written first (its row arrives first), Unpaywall's second; both are verified matches.
    store.record_pdf_candidates(svid, store.record_pdf_discovery(
        rid, svid, "crossref", "10.1/test", acquisition.Lookup("completed", [acquisition.Candidate(
            "crossref", "https://c.example/a.pdf", None, "publishedVersion", None, "doi_verified", "match")])),
        [acquisition.Candidate("crossref", "https://c.example/a.pdf", None, "publishedVersion", None,
                               "doi_verified", "match")])

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": "10.1/test", "oa_locations": [
                {"url_for_pdf": "https://u.example/a.pdf", "version": "publishedVersion", "host_type": "publisher"}],
                "best_oa_location": None})
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/test", "display_name": record.title,
                                             "locations": []})
        return httpx.Response(200, json={"message": {"DOI": "10.1/test", "link": []}})

    attempts = []

    async def fetcher(url):
        attempts.append(url)
        return FetchResult("ok", data=make_pdf(["SYNTHETIC full text"]), final_url=url, http_status=200)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                        "synthetic@example.org", None, fetcher, web_search=False)

    run(check())
    assert attempts == ["https://u.example/a.pdf"], "the copy that arrived first was downloaded, not the first by rule"
    assert store.has_asset(svid)
    connection.close()


def test_acquisition_records_403_then_downloads_second_verified_location(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(
        provider_record_id="W1", title="Exact synthetic title", authors=[], year=2020, venue="J", publication_type="article",
        doi="10.1/test", landing_url="https://publisher.example/item", oa_pdf_url=None, oa_pdf_version=None,
        version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")

    def handler(request):
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": "10.1/test", "oa_locations": [], "best_oa_location": None})
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/test", "display_name": record.title,
                "locations": [
                    {"pdf_url": "https://blocked.example/a.pdf", "version": "publishedVersion"},
                    {"pdf_url": "https://open.example/a.pdf", "version": "publishedVersion"},
                ]})
        return httpx.Response(200, json={"message": {"DOI": "10.1/test", "link": []}})

    attempts = []
    async def fetcher(url):
        attempts.append(url)
        if "blocked" in url:
            return FetchResult("http_error", final_url=url, http_status=403)
        return FetchResult("ok", data=make_pdf(["SYNTHETIC full text"]), final_url=url, http_status=200)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers", None, None, fetcher)

    result = run(check())
    assert result["pdf_found"] is True and len(attempts) == 2
    candidates = store.pdf_candidates(svid)
    assert [(c["access_status"], c["http_status"]) for c in candidates] == [("http_error", 403), ("downloaded", 200)]
    assert store.has_asset(svid)
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == ["unpaywall", "openalex", "crossref", "core"]
    connection.close()


QUOTA_HEADERS = {"x-ratelimit-remaining-usd": "0", "x-ratelimit-limit-usd": "1", "x-ratelimit-reset": "3600"}


def _openalex_429(headers):
    return httpx.Response(429, headers=headers, json={"message": "rate limit"})


def _store_with_records(tmp_path, count=2):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    workflow_run = store.create_run(rid, "discovery", {"max_model_calls": 0}, None)["id"]
    svids = []
    for number in range(1, count + 1):
        record = ProviderRecord(f"W{number}", f"Synthetic title {number}", [], 2020, "J", "article", f"10.1/test{number}",
                                None, None, None, "publishedVersion", None, None, {}, {})
        svid, _ = store.upsert_provider_source("openalex", record, None)
        store.add_to_corpus(rid, svid, "search")
        svids.append(svid)
    return connection, store, rid, workflow_run, svids


def _budget_events(store, rid):
    return [json.loads(r[0]) for r in store.conn.execute(
        "SELECT payload_json FROM events WHERE research_id = ? AND type = 'openalex_budget_exhausted'", (rid,))]


def _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, budget, *, together=False):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            def one(svid):
                return acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                      "synthetic@example.org", None, core_key="key", web_search=False,
                                                      openalex_budget=budget, workflow_run_id=workflow_run)
            if together:
                await asyncio.gather(*(one(svid) for svid in svids))
            else:
                for svid in svids:
                    await one(svid)

    run(check())


def test_once_openalex_budget_is_exhausted_later_lookups_are_recorded_not_sent_and_counted_in_one_event(tmp_path):
    connection, store, rid, workflow_run, svids = _store_with_records(tmp_path, 3)
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    _acquire_all(store, rid, workflow_run, svids, tmp_path, handler, acquisition.OpenAlexBudget())
    assert len(sent) == 1, "a later record's OpenAlex lookup was sent although the budget was gone"
    rows = [[d for d in store.pdf_discoveries(rid, svid, retry_after=True) if d["provider"] == "openalex"][0]
            for svid in svids]
    assert [(r["status"], r["error_code"], r["http_status"]) for r in rows] == [
        ("rate_limited", "quota_exhausted", 429), ("rate_limited", "quota_exhausted", None),
        ("rate_limited", "quota_exhausted", None)]
    assert len({r["retry_after"] for r in rows}) == 1 and rows[0]["retry_after"]
    # The other routes were still asked for every record.
    assert all({"unpaywall", "crossref", "core"} <= {d["provider"] for d in store.pdf_discoveries(rid, s)} for s in svids)
    assert [(e["run_id"], e["lookups_refused"], e["lookups_skipped"], e["reset_at"]) for e in _budget_events(store, rid)] == [
        (workflow_run, 1, 2, rows[0]["retry_after"])]
    connection.close()


def test_a_second_run_acquiring_at_the_same_time_reads_the_stored_refusal_before_it_sends(tmp_path, monkeypatch):
    """Two runs, two budget memories, one key. The budget is the key's, so the refusal has to be stored before
    another request on it may start; each run's own memory is empty at the moment the other is refused."""
    connection, store, rid, first_run, svids = _store_with_records(tmp_path, 2)
    # Two researches, because one research holds one active run; the key's budget is shared across both.
    other = store.create_research("Another synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    store.add_to_corpus(other, svids[1], "search")
    jobs = [(rid, svids[0], first_run),
            (other, svids[1], store.create_run(other, "discovery", {"max_model_calls": 0}, None)["id"])]
    sent = []

    def handler(request):
        if "api.openalex.org" in request.url.host:
            sent.append(request.url.path)
            return _openalex_429(QUOTA_HEADERS)
        return httpx.Response(404)

    # The window the lock has to cover: the host lock is released when the answer returns, and the refusal is
    # stored a step later. A mocked transport answers with no suspension at all, so the step is put there.
    real_lookup = acquisition.openalex_lookup

    async def answered_then_a_step(*args, **kwargs):
        lookup = await real_lookup(*args, **kwargs)
        await asyncio.sleep(0)
        return lookup

    monkeypatch.setattr(acquisition, "openalex_lookup", answered_then_a_step)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(*(
                acquisition.acquire_for_source(store, research, svid, client, tmp_path / "papers",
                                               "synthetic@example.org", None, core_key="key", web_search=False,
                                               openalex_budget=acquisition.OpenAlexBudget(), workflow_run_id=job)
                for research, svid, job in jobs))

    run(check())
    assert len(sent) == 1, "the other run sent its request in the window before the refusal was stored"
    rows = [[d for d in store.pdf_discoveries(research, svid, retry_after=True) if d["provider"] == "openalex"][0]
            for research, svid, _ in jobs]
    assert sorted(r["http_status"] or 0 for r in rows) == [0, 429]
    assert all(r["error_code"] == "quota_exhausted" for r in rows)
    connection.close()


ELSEVIER_DOI = "10.1016/j.synth.2024.000001"


def _elsevier_record(doi=ELSEVIER_DOI, openaccess="1"):
    return {"full-text-retrieval-response": {"coredata": {
        "prism:doi": doi, "openaccess": openaccess, "openaccessArticle": openaccess == "1",
        "openaccessUserLicense": "http://creativecommons.org/licenses/by/4.0/",
        "link": [{"@href": "https://www.sciencedirect.com/science/article/pii/S0000", "@rel": "scidir"}]}}}


def test_a_refused_elsevier_link_falls_through_to_the_api_copy_fetched_with_the_key(tmp_path, monkeypatch):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(
        provider_record_id="W1", title="Exact synthetic title", authors=[], year=2024, venue="J", publication_type="article",
        doi=ELSEVIER_DOI, landing_url="https://www.sciencedirect.com/science/article/pii/S0000", oa_pdf_url=None,
        oa_pdf_version=None, version_label="publishedVersion", abstract=None, abstract_origin=None, identifiers={}, raw={},
    )
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")

    def handler(request):
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"doi": f"https://doi.org/{ELSEVIER_DOI}", "display_name": record.title,
                "locations": [{"pdf_url": "https://www.sciencedirect.com/science/article/pii/S0000/pdf",
                               "version": "publishedVersion"}]})
        if "api.elsevier.com" in request.url.host:
            return httpx.Response(200, json=_elsevier_record())
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(200, json={"doi": ELSEVIER_DOI, "oa_locations": [], "best_oa_location": None})
        return httpx.Response(200, json={"message": {"DOI": ELSEVIER_DOI, "link": []}})

    plain, keyed = [], []

    async def fetcher(url):
        plain.append(url)
        return FetchResult("http_error", final_url=url, http_status=403, media_type="text/html")

    async def fetch_pdf(url, client=None, deadline=None, *, email=None, headers=None):
        keyed.append((url, email, headers))
        return FetchResult("ok", data=make_pdf(["SYNTHETIC full text"]), final_url=url, http_status=200)

    monkeypatch.setattr(acquisition.fetch, "fetch_pdf", fetch_pdf)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers", "me@synthetic.example",
                                                        None, fetcher, elsevier_key="SYNTHETIC-KEY")

    assert run(check())["pdf_found"] is True and store.has_asset(svid)
    assert plain == ["https://www.sciencedirect.com/science/article/pii/S0000/pdf"]
    api = f"https://api.elsevier.com/content/article/doi/{ELSEVIER_DOI}?httpAccept=application/pdf"
    assert keyed == [(api, "me@synthetic.example", {"X-ELS-APIKey": "SYNTHETIC-KEY"})]
    assert [d["provider"] for d in store.pdf_discoveries(rid, svid)] == ["unpaywall", "openalex", "crossref", "core", "elsevier"]
    assert [(c["provider"], c["access_status"]) for c in store.pdf_candidates(svid)] == [
        ("openalex", "http_error"), ("elsevier", "downloaded")]
    connection.close()




# ---- OpenAlex's own content route ------------------------------------------------------------------------------

CONTENT_DOI = "10.1/content.7"
CONTENT_URL = "https://content.openalex.org/works/W7.pdf"
CONTENT_TEI = "https://content.openalex.org/works/W7.grobid-xml"
CONTENT_TITLE = "Exact synthetic content title"
MANUAL_URL = "https://papers.example/confirmed.pdf"


def _content_library(tmp_path, *, doi=CONTENT_DOI, version_label=None, provider="openalex"):
    """A record OpenAlex answered with (so its work id is stored), with the version label the test needs."""
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(provider_record_id="W7", title=CONTENT_TITLE, authors=["Ada Lovelace"], year=2020,
                            venue="IFIP Networking", publication_type="article", doi=doi, landing_url=None,
                            oa_pdf_url=None, oa_pdf_version=None, version_label=version_label, abstract=None,
                            abstract_origin=None, identifiers={}, raw={})
    svid, _ = store.upsert_provider_source(provider, record, None)
    store.add_to_corpus(rid, svid, "search")
    return connection, store, rid, svid


def _content_handler(content, *, doi=CONTENT_DOI, lookup=None):
    """Answers the DOI lookups with nothing and the content route with `content`; `lookup` replaces the DOI
    lookup's own answer (a timeout, say), so the two OpenAlex requests can be told apart by what they select."""
    def handler(request):
        host = request.url.host
        if host == "api.openalex.org":
            if (request.url.params.get("select") or "").startswith("id,doi"):
                return content(request)
            if lookup is not None:
                return lookup(request)
            return httpx.Response(200, json={"doi": f"https://doi.org/{doi}" if doi else None,
                                             "display_name": CONTENT_TITLE, "locations": []})
        if host == "api.unpaywall.org":
            return httpx.Response(200, json={"doi": doi, "oa_locations": [], "best_oa_location": None})
        if host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"DOI": doi, "link": []}})
        return httpx.Response(200, json={"results": [], "resultList": {"result": []}})
    return handler


def _content_json(*, pdf_url=CONTENT_URL, tei=True, doi=CONTENT_DOI):
    urls = {**({"pdf": pdf_url} if pdf_url else {}), **({"grobid_xml": CONTENT_TEI} if tei else {})}
    return {"id": "https://openalex.org/W7", "doi": f"https://doi.org/{doi}" if doi else None,
            "has_content": {"pdf": bool(pdf_url), "grobid_xml": tei}, "content_urls": urls}


def _acquire_content(store, rid, svid, tmp_path, handler, monkeypatch, *, pages=None, key="SYNTHETIC-KEY"):
    """One acquisition with the content route open; returns (result, the keyed fetches it made)."""
    keyed = []

    async def fetch_pdf(url, client=None, deadline=None, *, email=None, headers=None, query=None):
        keyed.append((url, email, headers, query))
        return FetchResult("ok", data=make_pdf(pages or [f"https://doi.org/{CONTENT_DOI}\nSYNTHETIC full text"]),
                           final_url=url, http_status=200)

    monkeypatch.setattr(acquisition.fetch, "fetch_pdf", fetch_pdf)

    async def nothing(url):
        raise AssertionError("no listed candidate should be fetched in these tests")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                        "synthetic@example.org", None, nothing, web_search=False,
                                                        openalex_key=key)

    return run(check()), keyed


def test_the_content_copy_waits_for_the_person_and_the_key_is_in_no_stored_address(tmp_path, monkeypatch):
    """OpenAlex's own copy is read before anything is published and then waits for the person: its address carries
    no version, so code never attaches it, whatever the record says about versions. The key is sent in the query
    string for that one request and appears in nothing that is kept."""
    connection, store, rid, svid = _content_library(tmp_path)
    found, keyed = _acquire_content(store, rid, svid, tmp_path,
                                    _content_handler(lambda r: httpx.Response(200, json=_content_json())), monkeypatch)
    assert (found["content"], found["pdf_found"], found["has_text"]) == ("attachable", False, False)
    assert not store.has_asset(svid), "a copy whose version nothing settled was attached by code"
    assert keyed == [(CONTENT_URL, "synthetic@example.org", None, {"api_key": "SYNTHETIC-KEY"})]
    row = next(c for c in store.pdf_candidates(svid) if c["provider"] == "openalex_content")
    assert (row["candidate_url"], row["identity_status"], row["version_status"], row["access_status"]) == (
        CONTENT_URL, "doi_verified", "uncertain", "downloaded")
    assert row["error_code"] == "version_unsettled"
    assert "api_key" not in (row["final_url"] or "") and "api_key" not in row["candidate_url"]
    assert [(a["outcome"], a["work_id"], a["reason"]) for a in store.openalex_content_attempts(svid)] == [
        ("attachable", "W7", "match")]
    assert [v["verdict"] for v in store.file_verdicts(svid, CONTENT_URL)] == ["match"]
    connection.close()


def test_the_days_budget_refusing_the_metered_download_is_stored_as_the_keys(tmp_path, monkeypatch):
    """The content download spends the same daily budget as the lookups, so its refusal is the key's: it is stored
    under the key's lock, with the time the budget returns, before any other request can read the budget."""
    connection, store, rid, svid = _content_library(tmp_path)
    budget = acquisition.OpenAlexBudget()

    async def refused(url, client=None, deadline=None, *, email=None, headers=None, query=None):
        return FetchResult("http_error", final_url=url, http_status=429, headers=dict(QUOTA_HEADERS))

    monkeypatch.setattr(acquisition.fetch, "fetch_pdf", refused)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                _content_handler(lambda r: httpx.Response(200, json=_content_json())))) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                        "synthetic@example.org", None, web_search=False,
                                                        openalex_key="SYNTHETIC-KEY", openalex_budget=budget)

    found = run(check())
    assert found["content"] == "quota_exhausted" and not store.has_asset(svid)
    assert budget.exhausted and budget.reset_at is not None
    attempt = store.openalex_content_attempts(svid)[-1]
    assert (attempt["outcome"], attempt["reason"]) == ("quota_exhausted", f"{acquisition.QUOTA_EXHAUSTED}:download")
    rows = [d for d in store.pdf_discoveries(rid, svid) if d["provider"] == "openalex_content"]
    assert [(d["status"], d["error_code"]) for d in rows][-1] == ("rate_limited", acquisition.QUOTA_EXHAUSTED)
    connection.close()


def test_content_served_as_tei_alone_is_a_route_that_exists_and_was_not_read(tmp_path, monkeypatch):
    """The content host serves a TEI XML beside the PDF and the reader here renders JATS. A record whose content is
    TEI alone is written down as that: no file is fetched, no text is claimed, and no route is called exhausted."""
    connection, store, rid, svid = _content_library(tmp_path)
    content = lambda request: httpx.Response(200, json=_content_json(pdf_url=None, tei=True))  # noqa: E731
    found, keyed = _acquire_content(store, rid, svid, tmp_path, _content_handler(content), monkeypatch)
    assert found["content"] == "tei_only" and keyed == [] and not store.has_asset(svid)
    assert [(a["outcome"], a["reason"]) for a in store.openalex_content_attempts(svid)] == [
        ("tei_only", "content_tei_only")]
    content_row = next(d for d in store.pdf_discoveries(rid, svid) if d["provider"] == "openalex_content")
    assert (content_row["status"], content_row["result_count"]) == ("zero_results", 0)
    connection.close()


def test_a_record_without_a_doi_asks_the_content_route_by_its_stored_work_id(tmp_path, monkeypatch):
    """The content route is the one route that needs no DOI: it addresses the work by the id a search stored for
    this record, so a record with no DOI reaches it instead of being left with nothing to ask."""
    connection, store, rid, svid = _content_library(tmp_path, doi=None)
    asked = []

    def content(request):
        asked.append(str(request.url.path))
        return httpx.Response(200, json=_content_json(doi=None))

    # With no DOI on either side, the title page has to name the record itself: its title, its first author and
    # its venue, all three.
    found, keyed = _acquire_content(store, rid, svid, tmp_path, _content_handler(content, doi=None), monkeypatch,
                                    pages=[f"{CONTENT_TITLE}\nAda Lovelace\nIFIP Networking 2020"])
    assert asked == ["/works/W7"] and found["doi_routes"] == "no_doi"
    assert found["content"] == "attachable"
    row = next(c for c in store.pdf_candidates(svid) if c["provider"] == "openalex_content")
    # No provider verified a DOI, because the record has none; what names the file is the file itself, and that
    # verdict is what lets the person confirm the copy.
    assert row["identity_status"] == "unverified" and keyed[0][3] == {"api_key": "SYNTHETIC-KEY"}
    assert store.file_verdicts(svid, CONTENT_URL)[0]["verdict"] == "match"
    connection.close()


def test_the_content_answer_does_not_stand_in_for_the_doi_lookups_own_result(tmp_path, monkeypatch):
    """A content answer is not a lookup answer. The DOI lookup that timed out stays unanswered, so the work is not
    settled as if OpenAlex had answered it."""
    connection, store, rid, svid = _content_library(tmp_path)

    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    handler = _content_handler(lambda r: httpx.Response(200, json=_content_json()), lookup=timeout)
    _acquire_content(store, rid, svid, tmp_path, handler, monkeypatch)
    latest = {d["provider"]: d["status"] for d in store.pdf_discoveries(rid, svid)}
    assert latest["openalex"] == "timeout" and latest["openalex_content"] == "completed"
    connection.close()


def test_a_refused_file_stays_refused_at_the_same_address_although_a_route_answers_again(tmp_path, monkeypatch):
    """The file's own verdict is kept apart from the provider's claim on purpose: a route answering a second time
    writes the candidate's `identity_status` again, and the refusal of the file at that address must survive it."""
    connection, store, rid, svid = _content_library(tmp_path)
    found, _ = _acquire_content(store, rid, svid, tmp_path,
                                _content_handler(lambda r: httpx.Response(200, json=_content_json())), monkeypatch,
                                pages=["Another paper entirely\n10.9/other.1"])
    assert found["content"] == "not_attached" and not store.has_asset(svid)
    assert [(a["outcome"], a["reason"]) for a in store.openalex_content_attempts(svid)] == [
        ("not_attached", "mismatch")]
    assert store.file_refused(svid, CONTENT_URL)["verdict"] == "mismatch"
    # The same address discovered again, now claimed as a title match: the claim is written, the refusal stands.
    again = acquisition.Candidate("openalex_content", CONTENT_URL, None, None, None, "title_verified", "uncertain")
    run_id = store.record_pdf_discovery(rid, svid, "openalex_content", "W7",
                                        acquisition.Lookup("completed", [again], 200))
    rows = store.record_pdf_candidates(svid, run_id, [again], CONTENT_DOI)
    assert next(c for c in rows if c["provider"] == "openalex_content")["identity_status"] == "title_verified"
    assert store.file_refused(svid, CONTENT_URL)["verdict"] == "mismatch"
    connection.close()


# ---- the other version's row and the file's own verdict --------------------------------------------------------

PREPRINT_DOI = "10.48550/arxiv.2101.00001"
PUBLISHED_DOI = "10.1/journal.9"
JOURNAL_URL = "https://pub.example/journal.pdf"
PREPRINT_TITLE = "Exact synthetic preprint title"


def _preprint_with_a_journal_copy(tmp_path):
    """A preprint record that names its published DOI, with a lookup's journal copy listed as another version."""
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(provider_record_id="2101.00001", title=PREPRINT_TITLE, authors=["Ada Lovelace"],
                            year=2021, venue="arXiv", publication_type="preprint", doi=PREPRINT_DOI,
                            landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label="submittedVersion",
                            abstract=None, abstract_origin=None,
                            identifiers={"arxiv": "2101.00001", "published_doi": PUBLISHED_DOI}, raw={})
    svid, _ = store.upsert_provider_source("arxiv", record, None)
    store.add_to_corpus(rid, svid, "search")
    candidate = acquisition.Candidate("unpaywall", JOURNAL_URL, "https://pub.example/a", "publishedVersion", None,
                                      "doi_verified", "different")
    run_id = store.record_pdf_discovery(rid, svid, "unpaywall", PREPRINT_DOI,
                                        acquisition.Lookup("completed", [candidate], 200))
    store.record_pdf_candidates(svid, run_id, [candidate], PREPRINT_DOI)
    return connection, store, rid, svid


def _attach_other(store, rid, svid, tmp_path, pages):
    async def fetcher(url):
        return FetchResult("ok", data=make_pdf(pages), final_url=url, http_status=200)

    return run(acquisition._attach_other_version(store, rid, svid, tmp_path / "papers", fetcher))


def test_the_journal_copys_row_opens_only_once_the_file_names_the_published_doi(tmp_path):
    """A copy a provider called the published version is published on its own row only when the file itself names
    the published DOI this record claims, and the row then says which DOI it is and where that came from."""
    connection, store, rid, svid = _preprint_with_a_journal_copy(tmp_path)
    asset_id, version_id = _attach_other(store, rid, svid, tmp_path,
                                         [f"{PREPRINT_TITLE}\nhttps://doi.org/{PUBLISHED_DOI}\nSYNTHETIC text"])
    assert asset_id and version_id and version_id != svid
    row = store.source(version_id)
    assert (row["doi"], row["version_label"]) == (PUBLISHED_DOI, "publishedVersion")
    assert store.source(svid)["doi"] == PREPRINT_DOI, "the preprint record kept its own DOI"
    opened = [json.loads(r[0]) for r in store.conn.execute(
        "SELECT payload_json FROM events WHERE type = 'lookup_version_opened'")]
    assert opened[0]["doi"] == PUBLISHED_DOI and opened[0]["doi_from"] == "published_doi_in_file"
    assert store.file_verdicts(svid, JOURNAL_URL)[0]["matched_doi"] == PUBLISHED_DOI
    connection.close()


def test_a_journal_copy_that_names_only_the_preprints_doi_is_not_published_as_the_published_version(tmp_path):
    """The provider's declaration is not evidence of a version. Without the published DOI in the file, neither the
    row nor the copy is published, and the candidate carries why instead of being fetched again as if it were new."""
    connection, store, rid, svid = _preprint_with_a_journal_copy(tmp_path)
    assert _attach_other(store, rid, svid, tmp_path,
                         [f"{PREPRINT_TITLE}\nhttps://doi.org/{PREPRINT_DOI}\nSYNTHETIC text"]) == (None, None)
    candidate = store.pdf_candidates(svid)[0]
    assert (candidate["access_status"], candidate["error_code"]) == ("downloaded", "published_doi_unconfirmed")
    assert store.work_versions(rid, svid) == [], "a row was opened for a version nothing confirmed"
    connection.close()


def test_a_copy_of_another_paper_is_not_published_on_a_row_of_this_work(tmp_path):
    """The file is read before anything is published, so a copy of another paper does not become this work's other
    version; the verdict is kept by address, which is what the person's own attach reads later."""
    connection, store, rid, svid = _preprint_with_a_journal_copy(tmp_path)
    assert _attach_other(store, rid, svid, tmp_path, ["Another paper entirely\n10.9/other.1"]) == (None, None)
    assert store.pdf_candidates(svid)[0]["error_code"] == "identity_mismatch"
    assert store.file_refused(svid, JOURNAL_URL)["verdict"] == "mismatch"
    connection.close()


def test_the_person_cannot_attach_a_file_whose_title_page_names_another_paper(tmp_path):
    """The manual attach reads the file it just fetched, not the provider's title claim: the version is the
    person's to confirm, which paper the file is was never theirs to claim. The file that arrives is the one
    judged, so an address that serves the right paper now is not refused for what it served before."""
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.runtime.config import Settings
    from fakes import FakeAdapter

    async def another_paper(url):
        return FetchResult("ok", data=make_pdf(["Another paper entirely\n10.9/other.1"]), final_url=url,
                           http_status=200)

    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, fetcher=another_paper, extra_hosts=("testserver",),
                     trusted_clients=("testclient",))
    with TestClient(app) as client:
        connection = db.connect(settings.db_path)
        store = Store(connection)
        rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
        record = ProviderRecord(provider_record_id="W7", title=CONTENT_TITLE, authors=["Ada Lovelace"], year=2020,
                                venue="IFIP Networking", publication_type="article", doi=CONTENT_DOI, landing_url=None,
                                oa_pdf_url=None, oa_pdf_version=None, version_label=None, abstract=None,
                                abstract_origin=None, identifiers={}, raw={})
        svid, _ = store.upsert_provider_source("openalex", record, None)
        store.add_to_corpus(rid, svid, "search")
        candidate = acquisition.Candidate("openalex", MANUAL_URL, None, None, None, "title_verified", "uncertain")
        run_id = store.record_pdf_discovery(rid, svid, "openalex", CONTENT_DOI,
                                            acquisition.Lookup("completed", [candidate], 200))
        rows = store.record_pdf_candidates(svid, run_id, [candidate], CONTENT_DOI)
        connection.close()

        token = client.get("/api/session").json()["csrf_token"]
        answer = client.post(f"/api/researches/{rid}/sources/{svid}/pdf-candidates/{rows[0]['id']}/attach",
                             headers={"x-deixis-csrf": token})
    assert answer.status_code == 422 and "does not name this record" in answer.json()["detail"]
    store = Store(db.connect(settings.db_path))
    assert not store.has_asset(svid), "a file that names another paper was attached"
    assert store.file_refused(svid, MANUAL_URL)["verdict"] == "mismatch"


def test_a_refused_content_copy_is_not_downloaded_again_with_the_metered_key(tmp_path, monkeypatch):
    """The content download is metered against the key's daily usage, so a file already read at that address and
    refused is not fetched a second time: the attempt says so and nothing is sent."""
    connection, store, rid, svid = _content_library(tmp_path)
    store.record_file_verdict(svid, CONTENT_URL, "synthetic-digest",
                              {"verdict": "mismatch", "fields": [], "dois": [], "page": None})
    found, keyed = _acquire_content(store, rid, svid, tmp_path,
                                    _content_handler(lambda r: httpx.Response(200, json=_content_json())), monkeypatch)
    assert found["content"] == "not_attached" and keyed == []
    assert [(a["outcome"], a["reason"]) for a in store.openalex_content_attempts(svid)] == [
        ("not_attached", "refused_before")]
    connection.close()


def test_a_listed_content_address_on_another_host_is_never_sent_the_key(tmp_path, monkeypatch):
    """The content address comes from a provider's answer and the key is appended to it, so only that one host's
    own address is used: an answer pointing somewhere else falls back to the documented form."""
    connection, store, rid, svid = _content_library(tmp_path)
    elsewhere = _content_json()
    elsewhere["content_urls"]["pdf"] = "https://cdn.elsewhere.example/W7.pdf"
    found, keyed = _acquire_content(store, rid, svid, tmp_path,
                                   _content_handler(lambda r: httpx.Response(200, json=elsewhere)), monkeypatch)
    assert [url for url, *_ in keyed] == [CONTENT_URL]
    assert found["content"] == "attachable"
    connection.close()


def _lookup_library(tmp_path, *, doi="10.1/lookup.3", location=None):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("Synthetic question?", "academic", "quick", ["openalex"], "fake", "m", "en")
    record = ProviderRecord(provider_record_id="W9", title="Exact synthetic lookup title", authors=["Ada Lovelace"],
                            year=2020, venue="IFIP Networking", publication_type="article", doi=doi, landing_url=None,
                            oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion", abstract=None,
                            abstract_origin=None, identifiers={}, raw={})
    svid, _ = store.upsert_provider_source("openalex", record, None)
    store.add_to_corpus(rid, svid, "search")

    def handler(request):
        host = request.url.host
        if host == "api.unpaywall.org":
            return httpx.Response(200, json={"doi": doi, "best_oa_location": None,
                                             "oa_locations": [location] if location else []})
        if host == "api.openalex.org":
            return httpx.Response(200, json={"doi": f"https://doi.org/{doi}", "display_name": record.title,
                                             "locations": []})
        if host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"DOI": doi, "link": []}})
        return httpx.Response(200, json={"results": [], "resultList": {"result": []}})

    return connection, store, rid, svid, handler, doi


def test_each_answers_candidates_keep_the_doi_that_answer_was_asked_for(tmp_path):
    """Another version's row is opened against the candidate's own declared DOI, so every answer's candidates have
    to carry the DOI that answer was asked for — on the path the app itself takes, not only in a test's call."""
    location = {"url_for_pdf": "https://repo.example/a.pdf", "url": "https://repo.example/a", "version": "publishedVersion"}
    connection, store, rid, svid, handler, doi = _lookup_library(tmp_path, location=location)

    async def refused(url):
        return FetchResult("http_error", final_url=url, http_status=403)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                        "synthetic@example.org", None, refused, web_search=False)

    run(check())
    rows = store.pdf_candidates(svid)
    assert rows and all(c["declared_doi"] == doi for c in rows)
    connection.close()


def test_an_address_that_once_served_another_paper_is_read_again_before_its_file_is_kept(tmp_path):
    """A provider calling an address a verified copy of this version does not undo what was read there. The file in
    hand is read first, and the answer is that file's: new content at the same address can still be kept."""
    location = {"url_for_pdf": "https://repo.example/a.pdf", "url": "https://repo.example/a", "version": "publishedVersion"}
    connection, store, rid, svid, handler, doi = _lookup_library(tmp_path, location=location)
    store.record_file_verdict(svid, location["url_for_pdf"], "an-older-file",
                              {"verdict": "mismatch", "fields": [], "dois": [], "page": None})
    pages = [f"https://doi.org/{doi}\nSYNTHETIC full text"]

    async def fetcher(url):
        return FetchResult("ok", data=make_pdf(pages), final_url=url, http_status=200)

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquisition.acquire_for_source(store, rid, svid, client, tmp_path / "papers",
                                                        "synthetic@example.org", None, fetcher, web_search=False)

    assert run(check())["asset_id"] and store.has_asset(svid), "the file in hand named this record and was refused"
    # The same address serving another paper again: nothing is attached and the candidate says why.
    connection2, store2, rid2, svid2, handler2, doi2 = _lookup_library(tmp_path / "second", location=location)
    (tmp_path / "second").mkdir(exist_ok=True)
    store2.record_file_verdict(svid2, location["url_for_pdf"], "an-older-file",
                               {"verdict": "mismatch", "fields": [], "dois": [], "page": None})
    pages = ["Another paper entirely\n10.9/other.1"]

    async def second():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler2)) as client:
            return await acquisition.acquire_for_source(store2, rid2, svid2, client, tmp_path / "papers2",
                                                       "synthetic@example.org", None, fetcher, web_search=False)

    assert run(second())["asset_id"] is None and not store2.has_asset(svid2)
    assert store2.pdf_candidates(svid2)[0]["error_code"] == "identity_mismatch"
    connection.close()
    connection2.close()


@pytest.mark.parametrize("url", [
    "https://content.openalex.org:8443/works/W7.pdf",       # another origin, same host name
    "https://user@content.openalex.org/works/W7.pdf",       # the request would go elsewhere
    "https://content.openalex.org/works/W7.pdf?api_key=x",  # a key already in the address
    "https://content.openalex.org/redirect?to=W7.pdf",      # not the documented path
    "http://content.openalex.org/works/W7.pdf",             # not https
    "https://content.openalex.org.evil.example/works/W7.pdf",
])
def test_the_content_key_is_sent_to_one_address_shape_alone(url):
    """The key is appended to an address a provider's answer gave, so nothing but that one origin and path may be
    sent it: another port is another origin, a user name points the request elsewhere."""
    assert acquisition._is_content_url(url) is False
    assert acquisition._is_content_url(CONTENT_URL) is True


def test_a_verdict_read_before_still_says_which_doi_the_page_carried(tmp_path):
    """The same file met again is the same answer, and that answer has to carry what matched: a copy whose title
    page named the published DOI was verified once and must not be refused the second time by a thinner record."""
    connection, store, rid, svid = _preprint_with_a_journal_copy(tmp_path)
    page = f"{PREPRINT_TITLE}\nhttps://doi.org/{PUBLISHED_DOI}\nSYNTHETIC text"
    first = _attach_other(store, rid, svid, tmp_path, [page])
    assert first[1] and store.source(first[1])["doi"] == PUBLISHED_DOI
    held = store.file_verdict_of(svid, JOURNAL_URL, hashlib.sha256(make_pdf([page])).hexdigest())
    assert (held["verdict"], held["dois"]) == ("match", [PUBLISHED_DOI])
    connection.close()
