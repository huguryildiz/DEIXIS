"""'Answer now with PDF text': a person's choice to stop reading equations during an answer run.

A fake reader stands in for Marker; passing these tests shows the workflow, not reading quality.
"""

import asyncio
import threading
import time

from fastapi.testclient import TestClient

from helpers import make_pdf
from test_api_flow import create, session, wait_run
from test_equations import FakeReader, run_answer


def upload(client, rid, name):
    client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf([f"SYNTHETIC x i c {name}"]), "application/pdf")})


class GatedReader(FakeReader):
    """Holds its first read until the test has pressed the button."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.gate = threading.Event()

    async def read(self, path, pages):
        if not self.calls:
            self.calls.append((path.name, pages))
            while not self.gate.is_set():
                await asyncio.sleep(0.01)
            self.calls.pop()
        return await super().read(path, pages)


def steps_of(run):
    return {s["operation_key"]: s for s in run["steps"]}


def test_pressing_the_button_mid_way_skips_the_remaining_pdfs_and_the_answer_is_written(tmp_path, monkeypatch):
    reader = GatedReader()
    app = run_answer(tmp_path, monkeypatch, reader)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            upload(client, rid, name)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        deadline = time.time() + 20
        while not reader.calls and time.time() < deadline:
            time.sleep(0.02)
        assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200
        assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 200  # pressed twice: recorded once
        reader.gate.set()
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        steps = steps_of(run)
        assert len(reader.calls) == 1  # the one in flight finished; the others kept their text layer
        assert steps["equations_skipped"]["output"] == {"pdfs_read": 1, "pdfs_skipped": 2}
        assert steps["equations_skip"]["status"] == "succeeded" and "grounded_answer" in steps


def test_without_the_button_every_pdf_is_read_and_no_skip_is_recorded(tmp_path, monkeypatch):
    reader = FakeReader()
    app = run_answer(tmp_path, monkeypatch, reader)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        for name in ("a.pdf", "b.pdf"):
            upload(client, rid, name)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed" and len(reader.calls) == 2
        assert "equations_skipped" not in steps_of(run) and "equations_skip" not in steps_of(run)


def test_a_resumed_run_keeps_the_choice(tmp_path, monkeypatch):
    reader = FakeReader(fail=True)
    app = run_answer(tmp_path, monkeypatch, reader)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        for name in ("a.pdf", "b.pdf"):
            upload(client, rid, name)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "equations_failed")
        assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 409  # paused, not reading
        app.state.store.request_equation_skip(run_id)
        client.post(f"/api/runs/{run_id}/resume")
        _, run = wait_run(client, rid, run_id, statuses=("completed", "failed"))
        assert run["status"] == "completed" and len(reader.calls) == 1
        assert steps_of(run)["equations_skipped"]["output"]["pdfs_skipped"] == 1


def test_the_route_refuses_a_run_that_is_not_reading(tmp_path, monkeypatch):
    app = run_answer(tmp_path, monkeypatch, FakeReader())
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload(client, rid, "a.pdf")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed"
        assert client.post(f"/api/runs/{run_id}/skip-equations").status_code == 409
        assert not app.state.store.equation_skip_requested(run_id)
