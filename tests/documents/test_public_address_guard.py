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
             "http://" + "a" * 64 + ".example/x.pdf"]


def never_called(request):
    raise AssertionError(f"request sent to {request.url}")


@pytest.mark.parametrize("url", MALFORMED)
def test_a_malformed_url_is_a_blocked_url_result_not_an_exception(url):
    # The real resolver: the empty and too-long labels fail in its IDNA encoding, before any lookup.
    client = httpx.AsyncClient(transport=httpx.MockTransport(never_called))
    result = asyncio.run(fetch.fetch_pdf(url, client))
    assert (result.status, result.final_url) == ("blocked_url", url)
    assert result.error.startswith("not a valid URL")


@pytest.mark.parametrize("location", MALFORMED)
def test_a_malformed_redirect_location_is_a_blocked_url_result(monkeypatch, location):
    resolve = fetch._resolve

    async def first_host_public(host, port):
        return ["93.184.216.34"] if host == "papers.example" else await resolve(host, port)

    monkeypatch.setattr(fetch, "_resolve", first_host_public)
    sent = []

    def handler(request):
        sent.append(request.url)
        return httpx.Response(302, headers={"location": location})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(fetch.fetch_pdf("https://papers.example/a.pdf", client))
    if location in ("https://papers.example:abc/x.pdf", "https://[::1/x.pdf", "http://[not-an-ip]/x.pdf"):
        # httpx reads the Location header itself and refuses these before `fetch` sees the response.
        assert (result.status, result.error) == ("failed", "RemoteProtocolError")
    else:
        assert result.status == "blocked_url" and result.error.startswith("not a valid URL")
    assert len(sent) == 1  # the malformed hop was never requested
