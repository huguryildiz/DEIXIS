"""SYNTHETIC builders for the arXiv source route's tests (slice 22, D104), and their network guard.

Everything here is made up: a PDF built with PyMuPDF whose display equations are lines of plain letters with a number at
the right margin, and an arXiv-like source archive built in memory with `tarfile`/`gzip`. Passing tests built on them shows
the route's workflow and rules, not how well matching works on real papers.
"""

from __future__ import annotations

import gzip
import io
import ipaddress
import socket
import tarfile

import httpx
import pymupdf
import pytest

STAMP = "arXiv:2101.00001v2 [cs.IT] 5 Jan 2021"
PROSE = [
    "SYNTHETIC. We study a simple model of signal detection in which the receiver counts",
    "the particles that arrive within each interval and compares that count with a threshold",
    "chosen in advance. The quantities below are defined once and then used throughout.",
]
# Display equations as the text layer prints them (letters only; symbol fonts would be masked) and as the source writes them.
EQUATIONS = [
    ("P a b = c d", r"P_{a b} = c_{d} \label{eq:first}"),
    ("Q m n = r s t", r"Q_{m} n = r \frac{s}{t}"),
    ("W x y = z u v w", r"W_{x} = \mathcal{Y} z + \mathrm{uvw}"),
]
SOURCE_PREAMBLE = r"""\documentclass{article}
\usepackage{amsmath}
\newcommand{\half}{\frac{1}{2}}
\begin{document}
"""


def page_with_equations(doc: pymupdf.Document, equations: list[tuple[str, str]], first_number: int = 1, stamp: str | None = None,
                        prose: list[str] | None = None, between: list[str] | None = None) -> None:
    """One page: prose, then each equation line with its number at the right margin, with a prose line between them."""
    page = doc.new_page(width=612, height=792)
    y = 90
    for line in prose or PROSE:
        page.insert_text((72, y), line, fontsize=10, fontname="helv")
        y += 14
    for k, (printed, _) in enumerate(equations):
        y += 24
        page.insert_text((200, y), printed, fontsize=10, fontname="helv")
        page.insert_text((520, y), f"({first_number + k})", fontsize=10, fontname="helv")
        y += 24
        for line in (between or ["where the symbols are those of the model defined in the section above."]):
            page.insert_text((72, y), line, fontsize=10, fontname="helv")
            y += 14
    if stamp:
        page.insert_text((30, 600), stamp, fontsize=9, fontname="helv", rotate=90)


def make_arxiv_pdf(pages: list[list[tuple[str, str]]] | None = None, stamp: str | None = STAMP) -> bytes:
    doc = pymupdf.open()
    number = 1
    for index, equations in enumerate(pages if pages is not None else [EQUATIONS]):
        page_with_equations(doc, equations, number, stamp if index == 0 else None)
        number += len(equations)
    return doc.tobytes()


def source_tex(equations: list[tuple[str, str]] | None = None, extra: str = "") -> str:
    body = "\n".join(f"Text before.\n\\begin{{equation}}\n{latex}\n\\end{{equation}}\nText after." for _, latex in (equations or EQUATIONS))
    return SOURCE_PREAMBLE + extra + body + "\n\\end{document}\n"


def make_tar(files: dict[str, str | bytes], gz: bool = True, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    return gzip.compress(raw.getvalue()) if gz else raw.getvalue()


def source_archive(equations: list[tuple[str, str]] | None = None, extra: str = "") -> bytes:
    return make_tar({"main.tex": source_tex(equations, extra)})


def _loopback(host: str | None) -> bool:
    if host in ("localhost", "testserver", "testclient"):
        return True
    try:
        return ipaddress.ip_address((host or "").strip("[]")).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fails the test on any httpx request not served by a mock transport and on any socket.connect off loopback."""
    real_connect = socket.socket.connect

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
            raise AssertionError(f"network access in a test: connect to {address!r}")
        return real_connect(self, address)

    async def async_request(self, request):
        raise AssertionError(f"network access in a test: {request.method} {request.url}")

    def sync_request(self, request):
        raise AssertionError(f"network access in a test: {request.method} {request.url}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_request)


# ---- fetching against a local server (loopback only) --------------------------------------------------------------------
REAL_ASYNC_REQUEST = httpx.AsyncHTTPTransport.handle_async_request


class LoopbackTransport(httpx.AsyncHTTPTransport):
    """A real transport that refuses every host but loopback, for the tests that need server-side arrival times."""

    async def handle_async_request(self, request):
        if not _loopback(request.url.host):
            raise AssertionError(f"network access in a test: {request.url}")
        return await REAL_ASYNC_REQUEST(self, request)


def install_socket_guard() -> None:
    """The no_network guard for a child process started by a test (no pytest fixture runs there)."""
    real_connect = socket.socket.connect

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
            raise AssertionError(f"network access in a test: connect to {address!r}")
        return real_connect(self, address)

    socket.socket.connect = connect


def point_at_local_server(port: int) -> None:
    """The route's address and the public-address check pointed at a local SYNTHETIC server (the host name is kept)."""
    from deixis.documents import arxiv_source, fetch

    async def public(url):
        return "127.0.0.1"

    fetch.check_public_url = public
    arxiv_source.E_PRINT_URL = f"http://arxiv.test:{port}/e-print/{{key}}"


def fetch_child(db_path: str, data_dir: str, port: int, key: str, results, clock_offset: float = 0.0) -> None:
    """A second DEIXIS process fetching one version from the local server through the product's own path."""
    import asyncio
    import time
    from pathlib import Path

    from deixis.documents import arxiv_source
    from deixis.storage import db
    from deixis.workflow.store import Store

    install_socket_guard()
    point_at_local_server(port)
    arxiv_source.clock = lambda: time.time() + clock_offset
    store = Store(db.connect(Path(db_path)))
    sources = arxiv_source.SourceStore(store, Path(data_dir), client=httpx.AsyncClient(transport=LoopbackTransport()))
    row = asyncio.run(sources.ensure(key))
    results.put((key, dict(row) if row else None, time.time()))
