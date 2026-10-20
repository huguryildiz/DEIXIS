"""Equation states without Marker (D113): an earlier Marker reading is kept, and a table fill reads equations first.

Marker was removed; nothing here reads equations from a PDF. Passing these tests shows the workflow, not reading quality.
"""

import asyncio
import json

from deixis.documents import math_reader, pdf
from deixis.storage import db
from deixis.workflow import equations
from deixis.workflow.store import Store
from helpers import make_pdf


def stored_pdf(tmp_path, pages):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC paper")
    papers = tmp_path / "papers"
    papers.mkdir()
    path = papers / "paper.pdf"
    path.write_bytes(make_pdf(pages))
    aid = store.add_asset_with_pages(svid, "sha-paper", 10, "paper.pdf", "user_upload", None, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


def marker_reading(store, aid, papers):
    """Store an earlier Marker reading of the PDF's second page, as D52 wrote it."""
    read = pdf.extract_pdf(papers / "paper.pdf")
    read.pages[1].text, read.pages[1].text_source = "SYNTHETIC model page 2\n\n$$x_{i} \\le c \\tag{2}$$", "marker"
    read.math = {"selected_pages": [2], "equations_to_check": [{"page": 2, "latex": "x_{j} \\le c"}]}
    store.reextract_asset(aid, read, equations.target_version(store.asset(aid)["extraction_version"]), pdf.chunk_page)


def test_an_earlier_marker_reading_is_kept_and_never_read_again(tmp_path, monkeypatch):
    store, svid, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC introduction text.", "SYNTHETIC garbled x i c ( 1 )"])
    marker_reading(store, aid, papers)
    version = store.asset(aid)["extraction_version"]
    assert version.endswith("+" + math_reader.MATH_VERSION)
    service = equations.EquationService(store, papers, arxiv_mode="auto")
    read = {"state": "read", "to_check": [2], "equations_to_check": 1, "route": "marker"}
    assert equations.equation_state(store, aid) == read
    assert asyncio.run(service.read_asset(aid)) == read and store.asset(aid)["extraction_version"] == version
    assert service.next_asset() is None and equations.background_read_waiting(store, aid) is None
    assert {p["physical_page"]: p["text_source"] for p in store.passages_for(svid)} == {1: "text_layer", 2: "marker"}
    math = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone()[0]
    assert json.loads(math)["selected_pages"] == [2]

    # D48: after an extractor bump the Marker-read PDF keeps its older text and stays read.
    monkeypatch.setattr(pdf, "EXTRACTION_VERSION", pdf.EXTRACTION_VERSION + "-newer")
    assert equations.target_version(version) != version
    assert equations.equation_state(store, aid) == read and service.next_asset() is None


def test_without_a_route_a_pdf_is_off_and_says_why(tmp_path):
    store, _, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC formula page."])
    assert equations.equation_state(store, aid) == {"state": "off", "reason": "no_reader"}  # no service on the store
    service = equations.EquationService(store, papers)
    off = {"state": "off", "reason": "no_answer_model", "route": "model"}
    assert equations.equation_state(store, aid) == off and asyncio.run(service.read_asset(aid)) == off
    assert not service.crop_active() and service.next_asset() is None
    store.set_setting(equations.MODEL_SWITCH, "off")
    assert equations.equation_state(store, aid)["reason"] == "switch_off"


def test_a_table_fill_waits_for_the_equations_of_the_pdfs_it_reads(tmp_path, monkeypatch):
    from deixis.workflow import flow
    from test_table_extraction import execute, fill, library

    lib = library(tmp_path)
    order = []

    class Service:
        def route_active(self):
            return False

        def crop_active(self):
            return True

        def route_target(self, asset_id):
            return False

        async def read_asset(self, asset_id, run_id=None):
            order.append(("equations", asset_id, len(lib.adapter.calls)))
            return {"state": "read", "route": "model"}

    monkeypatch.setattr(flow, "equation_state", lambda store, asset_id: {"state": "pending", "route": "model"})
    lib.flow.deps.equations = Service()
    run = fill(lib)
    assert execute(lib, run)["status"] == "completed"
    asset = lib.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (lib.published,)).fetchone()[0]
    assert order == [("equations", asset, 0)]  # before any cell's model call
    assert lib.store.step(run["id"], f"equations:{asset}", "read_equations")["status"] == "succeeded"
