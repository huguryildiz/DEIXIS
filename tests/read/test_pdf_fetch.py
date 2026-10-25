"""Fetching PDFs from untrusted hosts: only public addresses, malformed links refused, one deadline, extra headers kept on the first https origin; and where the acquisition looks for an open copy. SYNTHETIC hosts, every transport mocked."""

import asyncio
import os
import sys
import time
import httpx
import pytest
from deixis.documents import fetch, pdf
from helpers import make_pdf
from deixis.documents import fetch
import json
from deixis.documents import acquisition
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.run.store import Store
from helpers import make_pdf


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
    while not (pid_file.exists() and pid_file.read_text()):
        assert time.monotonic() < deadline, "the child never wrote its pid"
        time.sleep(0.05)
    return int(pid_file.read_text())


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


