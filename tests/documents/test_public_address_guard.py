"""Audit F4: a link is fetched only when every address its host resolves to is global."""

import asyncio

import httpx
import pytest

from deixis.documents import fetch


def resolving_to(monkeypatch, address):
    async def resolve(host, port):
        return [address]
    monkeypatch.setattr(fetch, "_resolve", resolve)


@pytest.mark.parametrize("address", ["100.64.0.1", "100.127.255.254", "192.0.2.10", "198.18.0.1", "10.0.0.7", "::ffff:100.64.0.1"])
def test_a_non_global_address_is_refused(monkeypatch, address):
    resolving_to(monkeypatch, address)
    with pytest.raises(fetch.BlockedUrl, match="non-public"):
        asyncio.run(fetch.check_public_url("https://papers.example/a.pdf"))


def test_a_global_address_is_returned(monkeypatch):
    resolving_to(monkeypatch, "93.184.216.34")
    assert asyncio.run(fetch.check_public_url("https://papers.example/a.pdf")) == "93.184.216.34"


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


@pytest.mark.parametrize("url", MALFORMED)
def test_a_malformed_url_is_a_blocked_url_result_not_an_exception(monkeypatch, url):
    resolving_public(monkeypatch)
    client = httpx.AsyncClient(transport=httpx.MockTransport(never_called))
    result = asyncio.run(fetch.fetch_pdf(url, client))
    assert (result.status, result.final_url) == ("blocked_url", url)
    assert result.error.startswith("not a valid URL")


@pytest.mark.parametrize("location", MALFORMED)
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


def test_an_internationalized_host_is_fetched_by_its_punycode_name(monkeypatch):
    resolved, seen = [], []
    resolving_public(monkeypatch, resolved)

    def handler(request):
        seen.append((request.url.host, request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 SYNTHETIC")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://B\u00fccher.example/a.pdf", client))
    assert (result.status, result.data) == ("ok", b"%PDF-1.4 SYNTHETIC")
    assert resolved == ["xn--bcher-kva.example"]
    assert seen == [(PUBLIC, "xn--bcher-kva.example", "xn--bcher-kva.example")]


def test_an_unrelated_protocol_error_is_still_failed(monkeypatch):
    resolving_public(monkeypatch)

    def handler(request):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://papers.example/a.pdf", client))
    assert (result.status, result.error) == ("failed", "RemoteProtocolError")


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
    (None, "env@synthetic.example", "DEIXIS/0.1 (local research workspace; mailto:env@synthetic.example)"),
    (None, None, "DEIXIS/0.1 (local research workspace)"),
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
