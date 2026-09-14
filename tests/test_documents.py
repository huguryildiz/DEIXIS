import asyncio
import time

import httpx
import pytest

from deixis.documents import fetch, pdf
from helpers import make_compressed_page_pdf, make_pdf


def test_extract_pdf_keeps_physical_pages(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(make_pdf(["SYNTHETIC page one about diffusion channels.", "", "Page three mentions a molecule budget."]))
    result = pdf.extract_pdf(path)
    assert result.page_count == 3
    assert result.status == "partial"  # page two has no text layer
    assert [p.physical_page for p in result.pages] == [1, 3]
    assert "molecule budget" in result.pages[1].text


def test_non_pdf_bytes_fail_extraction(tmp_path):
    path = tmp_path / "not.pdf"
    path.write_bytes(b"<html>not a pdf</html>")
    assert pdf.extract_pdf(path).status == "failed"


def test_chunk_page_respects_limit_and_covers_text():
    text = " ".join(f"Sentence {i} about channel capacity." for i in range(200))
    chunks = pdf.chunk_page(text, limit=300)
    assert all(len(c[2]) <= 300 for c in chunks)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8765/api/researches",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/paper.pdf",
        "http://[::1]/x.pdf",
        "https://user:pw@example.org/x.pdf",
    ],
)
def test_private_or_unsafe_urls_are_blocked(url):
    result = asyncio.run(fetch.fetch_pdf(url))
    assert result.status == "blocked_url"


def test_extraction_stops_at_the_text_limit(tmp_path):
    path = tmp_path / "long.pdf"
    path.write_bytes(make_pdf([f"SYNTHETIC page {i} " + "word " * 40 for i in range(6)]))
    result = pdf.extract_pdf(path, max_chars=500)
    assert result.status == "partial"
    assert sum(len(p.text) for p in result.pages) <= 500 and len(result.pages) < 6


def test_extraction_is_stopped_when_it_exceeds_the_memory_limit(tmp_path):
    # ~70 MB of decoded page content in a file of well under 1 MB (below pypdf's own 75 MB stream limit).
    path = tmp_path / "expands.pdf"
    path.write_bytes(make_compressed_page_pdf(b"BT /F1 11 Tf 72 720 Td (" + b"A" * 70_000_000 + b") Tj ET"))
    assert path.stat().st_size < 1_000_000
    started = time.monotonic()
    result = pdf.extract_pdf(path, max_memory=100 * 1024 * 1024)
    assert (result.status, result.error) == ("failed", "extraction exceeded the memory limit")
    assert time.monotonic() - started < 30


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
