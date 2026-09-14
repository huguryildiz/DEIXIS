import asyncio

import pytest

from deixis.documents import fetch, pdf
from helpers import make_pdf


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
