"""Audit F2: an answer over attached files whose question is revised during its model call is not published."""

import time

from fastapi.testclient import TestClient

from fakes import FakeAdapter
from test_api_flow import app_for, create, session
from test_report_api import upload_and_include


def test_an_attached_answer_for_an_earlier_question_revision_is_not_published(tmp_path):
    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)

        def revise(step_input):
            if step_input["task_type"] == "grounded_answer" and store.research(research_id)["current_scope_revision"] == 1:
                store.revise_scope(research_id, store.research(research_id)["version"], "A different question entirely?", None)

        adapter.before = revise
        response = client.post(f"/api/researches/{research_id}/runs", json={"kind": "answer"})
        assert response.status_code in (200, 201, 202), response.text
        run_id = store.conn.execute("SELECT id FROM runs WHERE kind = 'answer'").fetchone()[0]
        deadline = time.time() + 30
        while store.run(run_id)["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.1)

        run = store.run(run_id)
        assert run["status"] == "cancelled" and run["pause_reason"] == "scope_revised"
        assert store.conn.execute("SELECT COUNT(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
