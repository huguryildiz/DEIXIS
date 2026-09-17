"""Reading equations before an answer (D52): the stored extraction, its states and the answer run's wait.

A fake reader stands in for Marker and returns SYNTHETIC LaTeX; passing these tests shows the workflow, not reading quality.
"""

import asyncio
import os
import sys
import time
from datetime import timedelta

from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import math_reader, ocr, pdf
from deixis.storage import db
from deixis.workflow import equations
from deixis.workflow.store import Store
from fakes import FakeAdapter
from helpers import make_pdf, make_scanned_pdf
from test_api_flow import create, fake_fetch, openalex_client, session, wait_run


class FakeReader:
    def __init__(self, fail=False):
        self.fail, self.calls, self.lock = fail, [], asyncio.Lock()

    def available(self):
        return True

    async def read(self, path, pages):
        self.calls.append((path.name, pages))
        if self.fail:
            raise RuntimeError("SYNTHETIC reader failure")
        return math_reader.Reading({p: f"SYNTHETIC model page {p + 1}\n\n$$x_{{i}} \\le c \\tag{{{p + 1}}}$$" for p in pages},
                                   {p: [{"bbox": [0, 0, 612, 792], "latex": "x_{i} \\le c"}] for p in pages})

    async def close(self):
        pass


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


def test_math_pages_are_read_into_a_new_extraction_and_other_pages_keep_their_text(tmp_path, monkeypatch):
    store, svid, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC introduction text.", "SYNTHETIC garbled x i c ( 1 )"])
    old = {p["physical_page"]: p["id"] for p in store.passages_for(svid)}
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [1])
    reader = FakeReader()
    service = equations.EquationService(store, reader, papers)
    assert service.next_asset() == aid and equations.equation_state(store, aid)["state"] == "pending"

    assert asyncio.run(service.read_asset(aid)) == {"state": "read", "to_check": [], "equations_to_check": 0}
    assert reader.calls == [("paper.pdf", [1])]
    passages = {p["physical_page"]: p for p in store.passages_for(svid)}
    assert passages[1]["text"] == "SYNTHETIC introduction text." and passages[1]["text_source"] == "text_layer"
    assert passages[2]["text"].startswith("SYNTHETIC model page 2") and passages[2]["text_source"] == "marker"
    assert passages[2]["id"] != old[2] and store.conn.execute("SELECT 1 FROM passages WHERE id = ?", (old[2],)).fetchone()
    assert store.asset(aid)["extraction_version"] == equations.target_version() and service.next_asset() is None
    math = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone()[0]
    assert '"selected_pages": [2]' in math
    assert asyncio.run(service.read_asset(aid))["state"] == "read" and len(reader.calls) == 1  # never read twice


def test_a_pdf_without_math_pages_and_a_failed_read_are_recorded_once(tmp_path, monkeypatch):
    store, svid, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC prose only."])
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [])
    reader = FakeReader()
    service = equations.EquationService(store, reader, papers)
    assert asyncio.run(service.read_asset(aid))["state"] == "no_math" and reader.calls == []
    assert service.next_asset() is None and store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION

    store2, _, aid2, papers2 = stored_pdf(tmp_path / "second", ["SYNTHETIC formula page."])
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    failed = asyncio.run(equations.EquationService(store2, FakeReader(fail=True), papers2).read_asset(aid2))
    assert failed["state"] == "failed" and "SYNTHETIC reader failure" in failed["reason"] and failed["attempts"] == 1
    assert [p["text_source"] for p in store2.passages_for(store2.asset(aid2)["source_version_id"])] == ["text_layer"]


def run_answer(tmp_path, monkeypatch, reader):
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)  # only the answer run reads here
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    original = equations.EquationService.__init__

    def init(self, store, _reader, papers_dir):
        original(self, store, reader, papers_dir)

    monkeypatch.setattr(equations.EquationService, "__init__", init)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=openalex_client(200), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    return app


def test_an_answer_waits_for_the_equations_of_the_pdfs_it_reads(tmp_path, monkeypatch):
    reader = FakeReader()
    app = run_answer(tmp_path, monkeypatch, reader)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC x i c"]), "application/pdf")})
        asset = upload.json()["sources"][0]["access"]["assets"][0]
        assert asset["equations"]["state"] == "pending"
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        keys = [s["operation_key"] for s in run["steps"]]
        assert keys.index(f"equations:{asset['id']}") < keys.index("grounded_answer")
        source = next(s for s in view["sources"] if s["access"]["assets"])
        assert source["access"]["assets"][0]["equations"]["state"] == "read" and source["access"]["assets"][0]["current_extraction"]
        payload = app.state.store.step_input_payload(app.state.store.step(run_id, "grounded_answer", "model:grounded_answer")["output"]["step_input_id"])
        assert any("\\le c" in p["text"] and p["text_source"] == "marker" for p in payload["passages"])


def test_a_failed_equation_read_pauses_the_answer_and_resuming_uses_the_text_layer(tmp_path, monkeypatch):
    reader = FakeReader(fail=True)
    app = run_answer(tmp_path, monkeypatch, reader)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC x i c"]), "application/pdf")})
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "equations_failed"), run
        client.post(f"/api/runs/{run_id}/resume")
        _, run = wait_run(client, rid, run_id, statuses=("completed", "failed"))
        assert run["status"] == "completed" and len(reader.calls) == 1


def test_a_failed_read_is_tried_again_later_up_to_three_attempts_and_on_request(tmp_path, monkeypatch):
    store, svid, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC formula page."])
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    reader = FakeReader(fail=True)
    service = equations.EquationService(store, reader, papers)
    assert asyncio.run(service.read_asset(aid))["attempts"] == 1
    assert service.next_asset() is None  # too soon after the failed attempt
    monkeypatch.setattr(equations, "RETRY_AFTER", timedelta(seconds=-1))
    assert service.next_asset() == aid
    assert asyncio.run(service.read_asset(aid))["attempts"] == 2 and asyncio.run(service.read_asset(aid))["attempts"] == 3
    assert service.next_asset() is None and asyncio.run(service.read_asset(aid))["attempts"] == 3 and len(reader.calls) == 3
    assert store.conn.execute("SELECT COUNT(*) FROM asset_extractions WHERE asset_id = ?", (aid,)).fetchone()[0] == 2  # one failure row

    reader.fail = False
    assert asyncio.run(service.read_asset(aid, retry=True))["state"] == "read" and len(reader.calls) == 4


def test_a_pdf_with_ocr_pages_keeps_them_and_marker_reads_every_ocr_page(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC scanned paper")
    papers = tmp_path / "papers"
    papers.mkdir()
    path = papers / "scan.pdf"
    path.write_bytes(make_scanned_pdf([("text", "SYNTHETIC text layer page."), ("scan", "prose"), ("scan", "formulas"), ("scan", "more")]))
    base = pdf.extract_pdf(path)
    aid = store.add_asset_with_pages(svid, "sha-scan", 10, "scan.pdf", "user_upload", None, "scan.pdf", base, pdf.EXTRACTION_VERSION, pdf.chunk_page)
    read = ocr.merge(base, [ocr.OcrPage(2, "succeeded", "SYNTHETIC OCR prose about relays."),
                            ocr.OcrPage(3, "succeeded", "SYNTHETIC OCR sin r(2IWt - n)")], ("eng",))  # page 4 found no text
    store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [])
    reader = FakeReader()
    service = equations.EquationService(store, reader, papers)
    assert service.next_asset() == aid

    assert asyncio.run(service.read_asset(aid))["state"] == "read" and reader.calls == [("scan.pdf", [1, 2])]
    assert store.asset(aid)["extraction_version"] == read.extraction_version + "+" + math_reader.MATH_VERSION
    passages = {p["physical_page"]: p for p in store.passages_for(svid)}
    assert [passages[n]["text_source"] for n in (1, 2, 3)] == ["text_layer", "marker", "marker"] and 4 not in passages


def test_a_table_fill_waits_for_the_equations_of_the_pdfs_it_reads(tmp_path):
    from test_table_extraction import execute, fill, library

    lib = library(tmp_path)
    order = []

    class Service:
        def available(self):
            return True

        async def read_asset(self, asset_id, run_id=None):
            order.append(("equations", asset_id, len(lib.adapter.calls)))
            return {"state": "read"}

    lib.flow.deps.equations = Service()
    run = fill(lib)
    assert execute(lib, run)["status"] == "completed"
    asset = lib.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (lib.published,)).fetchone()[0]
    assert order == [("equations", asset, 0)]  # before any cell's model call
    assert lib.store.step(run["id"], f"equations:{asset}", "read_equations")["status"] == "succeeded"


def test_the_equation_reader_is_installed_from_settings_and_a_failed_read_is_read_again_on_request(tmp_path, monkeypatch):
    fake_uv = tmp_path / "bin" / "uv"
    fake_uv.parent.mkdir()
    # venv makes the environment's python; pip install prints a line.
    fake_uv.write_text(f"#!/bin/sh\nif [ \"$1\" = venv ]; then mkdir -p \"$5/bin\" && ln -sf {sys.executable} \"$5/bin/python\"; else echo installed marker; fi\n")
    fake_uv.chmod(0o755)
    runner = tmp_path / "runner.py"
    runner.write_text("import os, sys\nos.makedirs(os.environ['MODEL_CACHE_DIR'], exist_ok=True)\n"
                      "open(os.path.join(os.environ['MODEL_CACHE_DIR'], 'weights.bin'), 'w').write('SYNTHETIC')\nprint('models ready')\n")
    monkeypatch.setattr(math_reader, "RUNNER", runner)
    monkeypatch.setenv("PATH", f"{fake_uv.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=openalex_client(200), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        status = client.get("/api/equation-reader").json()
        assert (status["installed"], status["job"], status["install"]["available"]) == (False, None, True)
        assert client.post("/api/equation-reader/install").status_code == 202
        for _ in range(100):
            status = client.get("/api/equation-reader").json()
            if status["job"]["status"] != "running":
                break
            time.sleep(0.05)
        assert status["job"]["status"] == "succeeded", status["job"]
        assert status["installed"] and status["models_downloaded"] and "models ready" in status["job"]["output"]
        assert client.post("/api/equation-reader/install").status_code == 409

        service = app.state.equations
        reader = FakeReader(fail=True)
        service.reader.read = reader.read
        rid = create(client, source_scope="attached")
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC x i c"]), "application/pdf")})
        source = upload.json()["sources"][0]
        asset = source["access"]["assets"][0]
        path = f"/api/researches/{rid}/sources/{source['source_version_id']}/assets/{asset['id']}/equations"
        assert client.post(path).status_code == 409  # not failed yet
        client.portal.call(service.read_asset, asset["id"])
        assert client.get(f"/api/researches/{rid}").json()["sources"][0]["access"]["assets"][0]["equations"]["state"] == "failed"
        assert any(e["type"] == "equations_failed" for e in client.get(f"/api/researches/{rid}/events").json())
        reader.fail = False
        assert client.post(path).status_code == 202
        for _ in range(100):
            state = client.get(f"/api/researches/{rid}").json()["sources"][0]["access"]["assets"][0]["equations"]["state"]
            if state == "read":
                break
            time.sleep(0.05)
        assert state == "read"

        assert client.delete("/api/equation-reader").json()["installed"] is False


class SlowReader(FakeReader):
    """A read that lasts until the reader is closed, as when a run stops the Marker process."""

    def __init__(self):
        super().__init__()
        self.closed = None

    async def read(self, path, pages):
        if not self.calls:
            self.calls.append((path.name, pages))
            self.closed = asyncio.Event()
            await self.closed.wait()
            raise RuntimeError("the equation reader stopped")
        return await super().read(path, pages)

    async def close(self):
        if self.closed:
            self.closed.set()


def test_a_run_stops_a_background_read_which_stays_pending(tmp_path, monkeypatch):
    store, _, background_aid, papers = stored_pdf(tmp_path, ["SYNTHETIC formula page."])
    svid = store.create_upload_source("SYNTHETIC second paper")
    (papers / "second.pdf").write_bytes(make_pdf(["SYNTHETIC second formula page."]))
    run_aid = store.add_asset_with_pages(svid, "sha-second", 10, "second.pdf", "user_upload", None, "second.pdf",
                                         pdf.extract_pdf(papers / "second.pdf"), pdf.EXTRACTION_VERSION, pdf.chunk_page)
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    reader = SlowReader()
    service = equations.EquationService(store, reader, papers)

    async def scenario():
        background = asyncio.create_task(service.read_asset(background_aid, background=True))
        while not reader.calls:
            await asyncio.sleep(0)
        first = await service.read_asset(run_aid)
        return first, await background

    first, stopped = asyncio.run(scenario())
    assert first["state"] == "read" and stopped["state"] == "pending"
    assert equations.equation_state(store, background_aid)["state"] == "pending" and service.next_asset() == background_aid
