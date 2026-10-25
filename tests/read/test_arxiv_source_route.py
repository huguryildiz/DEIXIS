"""The arXiv source route in the equation service, the answer run and the views (slice 22, D104, decisions 1, 6–8).

A fake fetch serves SYNTHETIC source archives; the clock is fake. The
PDFs and records are SYNTHETIC. Passing shows the route's states, guards and wiring, not matching quality.
"""

import asyncio
import json
import sqlite3
import sys
import pymupdf
import pytest
from arxiv_helpers import page_with_equations, source_archive, EQUATIONS
from deixis.documents import arxiv_source as src
from deixis.documents import fetch, pdf
from deixis.storage import db
from deixis.workflow.read import equations
from deixis.workflow.run.store import Store
from arxiv_helpers import no_network  # noqa: F401  (fixtures used by name)


KEY = "2101.00001v2"


URL = "https://arxiv.org/pdf/2101.00001v2"


LONG = ["and the receiver keeps a running count of every particle it absorbs in the interval of detection used here."] * 8


def arxiv_pdf(pages: int = 2) -> bytes:
    doc = pymupdf.open()
    page_with_equations(doc, EQUATIONS, 1, "arXiv:2101.00001v2 [cs.IT] 5 Jan 2021", between=LONG)
    for _ in range(pages - 1):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 90), "SYNTHETIC. A page of prose with no equation at all, only words about the model.", fontsize=10)
    return doc.tobytes()


class FakeFetch:
    def __init__(self, answer=None, before=None):
        self.calls, self.answer, self.before = [], answer, before

    async def __call__(self, url, media_types, gate=None, client=None, deadline=30.0):
        self.calls.append(url)
        await gate.before()
        try:
            if self.before:
                self.before()
            return self.answer(url) if self.answer else ok(url)
        finally:
            gate.after()


def ok(url, body=None):
    key = url.rsplit("/", 1)[1]
    return fetch.FetchResult("ok", data=body if body is not None else source_archive(), final_url=url, media_type="application/gzip",
                             http_status=200, content_disposition=f'attachment; filename="arXiv-{key}.tar.gz"')


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = [1_800_000_000.0]

    async def fake_sleep(seconds):
        now[0] += seconds
        await asyncio.sleep(0)
    monkeypatch.setattr(src, "clock", lambda: now[0])
    monkeypatch.setattr(src, "sleep", fake_sleep)
    return now


def library(tmp_path, label="arXiv v2", doi="10.48550/arXiv.2101.00001", landing=None, oa=URL, retrieved_from=URL, data=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC arXiv paper")
    conn.execute("UPDATE source_versions SET version_label = ?, doi = ?, landing_url = ?, oa_pdf_url = ? WHERE id = ?",
                 (label, doi, landing, oa, svid))
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    path = papers / "paper.pdf"
    path.write_bytes(data or arxiv_pdf())
    aid = store.add_asset_with_pages(svid, "sha-a", 10, "paper.pdf", "download", retrieved_from, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


def service(store, papers, tmp_path, fetcher=None, mode="auto"):
    svc = equations.EquationService(store, papers)
    svc.configure_arxiv_source(mode, tmp_path / "data", fetch_file=fetcher or FakeFetch())
    return svc


def read(svc, aid, **kw):
    return asyncio.run(svc.read_asset(aid, **kw))


# ---- the route writes a new extraction ----------------------------------------------------------------------------------
def test_an_eligible_pdf_gets_its_numbered_equations_from_the_source(tmp_path):
    store, svid, aid, papers = library(tmp_path)
    fetcher = FakeFetch()
    svc = service(store, papers, tmp_path, fetcher=fetcher)
    assert equations.equation_state(store, aid) == {"state": "pending", "route": "arxiv_source"}
    state = read(svc, aid)
    assert state["state"] == "read" and state["source"]["placed"] == 2 and state["source"]["pages"] == [1]
    assert state["source"]["version"] == 2 and state["source"]["version_from"] == "both" and len(fetcher.calls) == 1
    asset = store.asset(aid)
    assert asset["extraction_version"] == pdf.EXTRACTION_VERSION + "+arxiv-latex-v1"
    page_one = [p for p in store.passages_for(svid) if p["extraction_version"] == asset["extraction_version"] and p["physical_page"] == 1]
    labels = [p["text_source"] for p in page_one]
    assert "latex_source" in labels and "text_layer" in labels  # per chunk, not per page
    assert all("$$" in p["text"] for p in page_one if p["text_source"] == "latex_source")
    assert all("$$" not in p["text"] for p in page_one if p["text_source"] == "text_layer")
    other = [p for p in store.passages_for(svid) if p["extraction_version"] == asset["extraction_version"] and p["physical_page"] == 2]
    assert {p["text_source"] for p in other} == {"text_layer"}
    math = json.loads(store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                         (aid,)).fetchone()[0])
    source = math["source"]
    assert math["engine"] == "arxiv_source" and source["params"] == src.PARAMS and source["arxiv_id"] == "2101.00001"
    assert set(source["placed"][0]) == {"page", "n", "start", "end", "group", "recall", "f1", "window_margin", "paper_margin"}
    assert source["record_label"] == "arXiv v2" and store.source(svid)["version_label"] == "arXiv v2"  # never rewritten
    assert store.conn.execute("SELECT COUNT(*) FROM asset_arxiv_versions WHERE asset_id = ?", (aid,)).fetchone()[0] == 1
    assert read(svc, aid)["state"] == "read" and len(fetcher.calls) == 1


# ---- the last-write guard inside the write's transaction ----------------------------------------------------------------
SECOND = """
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=float(sys.argv[3]), isolation_level=None)
try:
    conn.execute(sys.argv[2])
    print("written")
except sqlite3.OperationalError as exc:
    print(str(exc))
"""


# ---- a record enriched later (enrich_source) -----------------------------------------------------------------------------


# ---- the answer run, the views and the passage payload -------------------------------------------------------------------


