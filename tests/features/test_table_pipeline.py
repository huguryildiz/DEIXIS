"""The study table follows a valid answer as a chain of the usual runs; synthetic model output, so this shows workflow, not quality."""

import dataclasses
import json
import time
from collections import Counter

from fastapi.testclient import TestClient

from deixis.api.app import create_app
from fakes import envelope
from test_api_flow import fake_fetch, openalex_client, session, create, app_for, sw_settings
from test_report_api import upload_and_include
from test_report_flow import COLUMN, FUTURE_WORK_COLUMN, LIMITATIONS_COLUMN, ReportAdapter


class PipelineAdapter(ReportAdapter):
    """Proposes three columns."""

    def _response(self, step_input):
        if step_input["task_type"] == "table_columns":
            return json.dumps(envelope(step_input, "deixis.table_column_proposal.v1") | {
                "columns": [{**column, "rationale": "fake rationale"} for column in (COLUMN, LIMITATIONS_COLUMN, FUTURE_WORK_COLUMN)],
                "notes": "",
            })
        return super()._response(step_input)


def events(store, type_):
    return [json.loads(r[0]) for r in store.conn.execute("SELECT payload_json FROM events WHERE type = ? ORDER BY id", (type_,))]


def wait_for_event(store, type_, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if found := events(store, type_):
            return found[0]
        time.sleep(0.1)
    raise AssertionError(f"no {type_} event")


def kinds(store):
    return [r[0] for r in store.conn.execute("SELECT kind FROM runs ORDER BY created_at, rowid")]


def auto_app(tmp_path, adapter):
    settings = dataclasses.replace(sw_settings(tmp_path), study_table="auto")
    return create_app(settings, adapters={"fake": adapter}, http_client=openalex_client(200), fetcher=fake_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def test_chain_builds_and_fills_the_table_and_queues_no_report(tmp_path):
    adapter = PipelineAdapter()
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        url = f"/api/researches/{research_id}/study-table"

        started = client.post(url, headers={"Idempotency-Key": "k"})
        replay = client.post(url, headers={"Idempotency-Key": "k"})
        assert started.status_code == 202 and replay.json()["id"] == started.json()["id"]

        ready = wait_for_event(store, "study_table_ready")
        time.sleep(0.3)

        assert ready["stale_cells"] == 0 and ready["sources_beyond_limit"] is False
        assert kinds(store) == ["table_columns", "table_fill"]
        table_id = client.get(f"/api/researches/{research_id}/tables").json()[0]["id"]
        table = client.get(f"/api/researches/{research_id}/tables/{table_id}").json()
        assert [c["accepted_by"] for c in table["columns"]] == ["automatic"] * 3
        assert [c["origin"] for c in table["columns"]] == ["model_suggestion"] * 3
        assert table["counts"]["empty"] == 0
        accepted = events(store, "study_table_columns_accepted")
        assert len(accepted) == 1 and accepted[0]["accepted_by"] == "automatic" and accepted[0]["reviewed_by_person"] is False
        summary = client.get(f"/api/researches/{research_id}/tables").json()[0]
        assert summary["access"]["pdf_available"] == 1 and summary["auto_columns"] == 3
        calls = Counter(call["task_type"] for call in adapter.calls)
        assert calls["table_columns"] == 1 and calls["cell_extraction"] == 1


def test_a_valid_answer_starts_the_chain_once_and_a_replay_does_not_repeat_it(tmp_path):
    from deixis.workflow import report_pipeline
    with TestClient(auto_app(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)

        assert client.post(f"/api/researches/{research_id}/runs", json={"kind": "answer"}).status_code in (200, 201, 202)
        wait_for_event(store, "study_table_ready")
        answer_run = store.run(store.conn.execute("SELECT id FROM runs WHERE kind = 'answer'").fetchone()[0])

        report_pipeline.after_answer(store, answer_run)

        assert kinds(store).count("table_columns") == 1 and "report" not in kinds(store)
        assert store.conn.execute("SELECT COUNT(*) FROM evidence_tables").fetchone()[0] == 1


def test_without_the_setting_an_answer_starts_nothing(tmp_path):
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        run = client.post(f"/api/researches/{research_id}/runs", json={"kind": "answer"}).json()
        deadline = time.time() + 20
        while time.time() < deadline and client.get(f"/api/researches/{research_id}").json()["runs"][0]["status"] not in ("completed", "failed"):
            time.sleep(0.1)
        assert kinds(raw.app.state.store) == ["answer"] and run["kind"] == "answer"


