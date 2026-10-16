"""Audit F4: a link is fetched only when every address its host resolves to is global."""

import asyncio

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
