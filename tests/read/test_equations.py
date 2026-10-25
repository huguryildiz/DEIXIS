"""Reading numbered equations from a PDF: which route reads a PDF and when it is off, finding display regions and cropping them, and the Mathpix request with what it sends. SYNTHETIC PDFs; Mathpix is mocked."""

import asyncio
import json
from deixis.documents import math_reader, pdf
from deixis.storage import db
from deixis.workflow.read import equations
from deixis.workflow.run.store import Store
from helpers import make_pdf
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.config import Settings
from test_api_flow import fake_fetch, openalex_client, session
from deixis.documents import equation_regions as er
from mathpix_helpers import prose, two_equations
from deixis.documents import inline_math, math_reader, pdf
import pytest
from deixis.documents import equation_model, equation_regions, mathpix, pdf
from mathpix_helpers import PAIR, FakeMathpix, prose, two_equations
from test_arxiv_source_route import FakeFetch
from arxiv_helpers import no_network  # noqa: F401  (fixtures used by name)


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
    from deixis.workflow.run import flow
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


def test_the_route_answers_with_the_built_in_connections(tmp_path, monkeypatch):
    """Without injected adapters the app builds its own map; the equation route must use it, not the missing argument."""
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)
    settings = Settings(data_dir=tmp_path / "data", port=8765, arxiv_source="off")
    app = create_app(settings, http_client=openalex_client(200), fetcher=fake_fetch, extra_hosts=("testserver",),
                     trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as raw:
        client = session(raw)
        client.put("/api/settings/answer", json={"model_connection": "anthropic", "model": "claude-sonnet-5-5",
                                                 "reasoning_effort": None})
        response = client.get("/api/equation-model")
        assert response.status_code == 200 and response.json()["reason"] != "connection_unavailable"


def test_the_equations_model_reads_before_the_answer_model_and_must_take_images(tmp_path, monkeypatch):
    """D136: an equations model in Settings is the one asked; with none set, the answer model is; a connection that
    sends no image is refused for it."""
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)
    settings = Settings(data_dir=tmp_path / "data", port=8765, arxiv_source="off")
    app = create_app(settings, http_client=openalex_client(200), fetcher=fake_fetch, extra_hosts=("testserver",),
                     trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        client.put("/api/settings/answer", json={"model_connection": "anthropic", "model": "claude-sonnet-5-5", "reasoning_effort": None})
        assert equation_model.choice(store)["model"] == "claude-sonnet-5-5"  # none set: the answer model reads
        refused = client.put("/api/settings/equations", json={"model_connection": "claude", "model": "sonnet", "reasoning_effort": None})
        assert refused.status_code == 422 and "cannot read images" in refused.json()["detail"]
        assert client.put("/api/settings/equations", json={"model_connection": "anthropic", "model": "claude-haiku-5-5",
                                                           "reasoning_effort": None}).status_code == 200
        assert equation_model.choice(store)["model"] == "claude-haiku-5-5"
        assert client.get("/api/settings").json()["equations"]["model"] == "claude-haiku-5-5"


def detect(tmp_path, doc, name="eq.pdf"):
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return er.detect(path)


def test_a_cut_keeps_clear_of_the_equations_type():
    core = (100.0, 50.0, 200.0, 70.0)
    near = (120.0, 46.0, 130.0, 49.5)  # 0.5 pt from the type: its white box could reach a glyph once rounded to pixels
    assert not er._cuttable(near, core, {near: 7}, others={7})


def test_a_foreign_span_inside_the_crops_outer_edge_counts():
    box = (100.0, 100.0, 200.0, 140.0)
    assert er._inside_any((150.0, 139.8, 160.0, 150.0), box)  # 0.2 pt into the crop: may put ink in it
    assert not er._inside_any((150.0, 140.0, 160.0, 150.0), box)  # ends on the edge


def test_inline_math_keeps_a_segment_only_when_its_letters_match_the_text_layer():
    spans = [("where x", "Times"), ("i", "CMR7"), ("2", "CMR7"), (" is the rate", "Times")]
    # stacked scripts: the text layer has i before 2, the reading writes the superscript first
    assert inline_math.rewrite("where <math>x^{2}_{i}</math> is the rate", [spans]) == (
        [("text", "where "), ("math", "x^{2}_{i}"), ("text", " is the rate")], 1, 0)
    # a changed letter keeps the text layer
    assert inline_math.rewrite("where <math>x_{j}^{2}</math> is the rate", [spans]) == ([("text", "where xi2 is the rate")], 0, 1)
    # prose that does not match the text layer rejects the line; a reading without math changes nothing
    assert inline_math.rewrite("when <math>x_{i}^{2}</math> is the rate", [spans]) is None
    assert inline_math.rewrite("where xi2 is the rate", [spans]) is None
    # of two orderings of the same spans, the one the reading matches is used
    other = [spans[0], spans[2], spans[1], spans[3]]
    assert inline_math.rewrite("where <math>x_{i}^{2}</math> is the rate", [other, spans])[1] == 1
    # the image reached past the line: the prose beyond it is not used
    assert inline_math.rewrite("where <math>x_{i}^{2}</math> is the rate of the next line", [spans])[1] == 1


TARGET = pdf.EXTRACTION_VERSION + "+mathpix-v1"


def library(tmp_path, data=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC paper with numbered equations")
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    path = papers / "paper.pdf"
    path.write_bytes(data or two_equations().tobytes())
    aid = store.add_asset_with_pages(svid, "sha-a", 10, "paper.pdf", "user_upload", None, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, svid, aid, papers


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(mathpix.ENV, PAIR)


def service(store, papers, tmp_path, fake=None, mode="off", switch="on"):
    svc = equations.EquationService(store, papers)
    svc.configure_arxiv_source(mode, tmp_path / "data", fetch_file=FakeFetch())
    svc.configure_mathpix(tmp_path / "data", (fake or FakeMathpix()).client())
    if switch:
        store.set_setting(equations.MATHPIX_SWITCH, switch)
    return svc


def read(svc, aid, **kw):
    return asyncio.run(svc.read_asset(aid, **kw))


def rows(store):
    return [dict(r) for r in store.conn.execute("SELECT * FROM mathpix_requests ORDER BY rowid")]


def test_the_request_carries_the_pair_one_crop_and_the_no_training_flag(tmp_path, on):
    store, _, aid, papers = library(tmp_path)
    fake = FakeMathpix()
    read(service(store, papers, tmp_path, fake), aid)
    request = fake.text_requests()[0]
    assert str(request.url) == mathpix.TEXT_URL and request.method == "POST"
    assert request.headers["app_id"] == "synthetic-app" and request.headers["app_key"] == "synthetic-key-0001"
    body = json.loads(request.content)
    assert set(body) == {"src", "formats", "rm_spaces", "metadata"}
    assert body["src"].startswith("data:image/png;base64,") and body["formats"] == ["latex_styled"] and body["rm_spaces"] is True
    assert body["metadata"] == {"improve_mathpix": False}


# ---- the route table --------------------------------------------------------------------------------------------------------


# ---- the write guard ---------------------------------------------------------------------------------------------------------
