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


def test_extraction_drops_the_ieee_xplore_download_notice(tmp_path):
    path = tmp_path / "watermarked.pdf"
    path.write_bytes(make_pdf([
        "SYNTHETIC body line one about packet sizes.\n"
        "Authorized licensed use limited to: SYNTHETIC University. Downloaded on\n"
        "September 15,2026 at 19:38:51 UTC from IEEE Xplore.  Restrictions apply.\n"
        "SYNTHETIC body line two about relays.",
    ]))
    text = pdf.extract_pdf(path).pages[0].text
    assert "Authorized licensed" not in text and "Restrictions apply" not in text and "IEEE Xplore" not in text
    assert "body line one about packet sizes." in text and "body line two about relays." in text
    assert pdf.EXTRACTION_VERSION.endswith("-layout-v2")

    one_line = ("ends here.\nAuthorized licensed use limited to: SYNTHETIC University. Downloaded on September 15,2026 at 19:45:08 UTC"
                " from IEEE Xplore.  Restrictions apply. \nNext")
    assert pdf.remove_download_notices(one_line) == "ends here.\nNext"
    # Only the whole notice is removed; a sentence that mentions licensed use stays.
    mention = "Authorized licensed use limited to: members. The rest of this sentence is body text."
    assert pdf.remove_download_notices(mention) == mention


def test_layout_extraction_moves_small_type_after_the_body_and_drops_page_furniture(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((300, 30), "7", fontsize=7)  # page number
    page.insert_text((72, 40), "SYNTHETIC JOURNAL, VOL. 1, 2026", fontsize=7)  # running head
    page.insert_text((72, 120), "I. INTRODUCTION", fontsize=10)
    page.insert_text((72, 160), "SYNTHETIC body text about diffusion chan-", fontsize=10)
    page.insert_text((72, 172), "nels continues in the first column", fontsize=10)
    page.insert_text((72, 700), "A. Author is with the Department of SYNTHETIC Studies (e-mail: a@example.org).", fontsize=8)
    page.insert_text((320, 160), "and ends in the second column.", fontsize=10)
    page.insert_text((20, 600), "arXiv:2601.00001v1 [cs.NI]", fontsize=16, rotate=90)
    path = tmp_path / "layout.pdf"
    doc.save(path)

    text = pdf.extract_pdf(path).pages[0].text
    paragraphs = [" ".join(p.split()) for p in text.split("\n\n")]
    assert paragraphs[0] == "I. INTRODUCTION"
    assert "diffusion channels continues" in paragraphs[1]  # hyphenated line end joined
    assert paragraphs[-1].startswith("A. Author is with the Department")  # the note follows the body text
    assert "and ends in the second column." in " ".join(paragraphs[1:-1])
    assert "arXiv:2601" not in text and "SYNTHETIC JOURNAL" not in text and "7" not in text.split()


def test_a_numbered_reference_entry_is_one_paragraph():
    split_and_joined = ["[39] M. H. Author, D. J.", "Twitchen, “A SYNTHETIC title,” 2018.\n[40] Y.-A. Chen, J. Zhang,", "K. Chen et al., 2021."]
    assert pdf._paragraphs(split_and_joined) == [
        "[39] M. H. Author, D. J.\nTwitchen, “A SYNTHETIC title,” 2018.", "[40] Y.-A. Chen, J. Zhang,\nK. Chen et al., 2021."]
    assert pdf._paragraphs(["Body paragraph one.", "Body paragraph two."]) == ["Body paragraph one.", "Body paragraph two."]


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
    result = pdf.extract_pdf(path, max_chars=300)  # each line runs past the page edge; only its visible ~99 characters count
    assert result.status == "partial"
    assert sum(len(p.text) for p in result.pages) <= 300 and len(result.pages) < 6


def test_extraction_is_stopped_when_it_exceeds_the_memory_limit(tmp_path):
    # ~70 MB of decoded page content in a file of well under 1 MB.
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
