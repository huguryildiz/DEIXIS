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


def test_nothing_readable_still_ends_with_every_cell_recorded_as_inaccessible(tmp_path):
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        store.conn.execute("DELETE FROM passages")
        store.conn.commit()
        assert client.post(f"/api/researches/{research_id}/study-table").status_code == 202
        wait_for_event(store, "study_table_ready")
        states = {r[0] for r in store.conn.execute(
            "SELECT r.state FROM evidence_cells c JOIN cell_revisions r ON r.id = c.current_revision_id")}
        assert states == {"inaccessible"} and "report" not in kinds(store)


def test_a_run_paused_in_the_fill_resumes_without_repeating_finished_steps(tmp_path):
    state = {"paused": False}

    def pause_once(step_input):
        if step_input["task_type"] == "cell_extraction" and not state["paused"]:
            state["paused"] = True
            run_id = state["store"].conn.execute("SELECT id FROM runs WHERE kind = 'table_fill'").fetchone()[0]
            state["store"].update_run(run_id, status="pause_requested")

    adapter = PipelineAdapter()
    adapter.before = pause_once
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        state["store"] = store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        client.post(f"/api/researches/{research_id}/study-table", headers={"Idempotency-Key": "p"})

        deadline = time.time() + 20
        fill = None
        while time.time() < deadline and not fill:
            fill = next((r for r in client.get(f"/api/researches/{research_id}").json()["runs"]
                         if r["kind"] == "table_fill" and r["status"] == "paused"), None)
            time.sleep(0.1)
        assert fill is not None
        assert client.post(f"/api/runs/{fill['id']}/resume").status_code == 200
        wait_for_event(store, "study_table_ready")

        calls = Counter(call["task_type"] for call in adapter.calls)
        assert calls["table_columns"] == 1 and calls["cell_extraction"] == 1


def test_refuses_without_an_included_source_and_creates_nothing(tmp_path):
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        assert client.post(f"/api/researches/{research_id}/study-table").status_code == 409
        assert client.get(f"/api/researches/{research_id}/tables").json() == []


def test_a_question_revised_during_the_column_proposal_stops_the_chain(tmp_path):
    adapter = PipelineAdapter()
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        done = {"revised": False}

        def revise(step_input):
            if step_input["task_type"] == "table_columns" and not done["revised"]:
                done["revised"] = True
                store.revise_scope(research_id, store.research(research_id)["version"], "A different question entirely?", None)

        adapter.before = revise
        client.post(f"/api/researches/{research_id}/study-table")
        stopped = wait_for_event(store, "study_table_stopped")
        time.sleep(0.5)
        assert stopped["reason"] == "scope_revised"
        assert kinds(store) == ["table_columns"]
        assert store.conn.execute("SELECT COUNT(*) FROM table_columns").fetchone()[0] == 0


def _finished_chain(client, raw, research_id):
    upload_and_include(client, research_id)
    client.post(f"/api/researches/{research_id}/study-table")
    store = raw.app.state.store
    wait_for_event(store, "study_table_ready")
    return store, store.conn.execute("SELECT id FROM evidence_tables").fetchone()[0]


def test_a_column_edited_after_its_cells_were_filled_is_reported_as_stale(tmp_path):
    from deixis.workflow import report_pipeline
    from deixis.workflow.tables import TableStore
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        store, table_id = _finished_chain(client, raw, research_id)
        tables = TableStore(store)
        column = tables.target_columns(research_id, table_id)[0]
        tables.revise_column(research_id, table_id, column["id"], {"name": "SYNTHETIC renamed"}, None, column["version"])
        run = store.run(store.conn.execute("SELECT id FROM runs WHERE kind = 'table_fill'").fetchone()[0])

        report_pipeline._finish(store, run, table_id, {"id": "again", "included": 1, "rounds": 1})

        assert events(store, "study_table_ready")[-1]["stale_cells"] == 1


def test_sources_beyond_the_fill_limit_are_recorded(tmp_path):
    from deixis.workflow import report_pipeline
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        store, table_id = _finished_chain(client, raw, research_id)
        run = store.run(store.conn.execute("SELECT id FROM runs WHERE kind = 'table_fill'").fetchone()[0])

        report_pipeline._finish(store, run, table_id, {"id": "big", "included": 300, "rounds": 8})

        assert events(store, "study_table_ready")[-1]["sources_beyond_limit"] is True


def test_a_replayed_continue_records_the_acceptance_once(tmp_path):
    from deixis.workflow import report_pipeline
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        store, _ = _finished_chain(client, raw, research_id)
        run = store.run(store.conn.execute("SELECT id FROM runs WHERE kind = 'table_columns'").fetchone()[0])

        report_pipeline.continue_after(store, run)

        assert len(events(store, "study_table_columns_accepted")) == 1
        assert store.conn.execute("SELECT COUNT(*) FROM table_columns").fetchone()[0] == 3


def test_an_answer_to_an_earlier_question_revision_opens_no_table(tmp_path, monkeypatch):
    """Sol r2: a completed answer of revision 1 seen after the question moved to revision 2 queues nothing (D230)."""
    from deixis.workflow import report_pipeline

    class Store:
        conn = None

    calls = []
    monkeypatch.setattr(report_pipeline, "start", lambda *a, **k: calls.append(a))

    class Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)

    class Conn:
        def execute(self, sql, params):
            class R:
                @staticmethod
                def fetchone():
                    return Row(id="ans_1", scope_revision=1)
            return R()

    store = Store()
    store.conn = Conn()
    store.research = lambda rid: {"current_scope_revision": 2}
    store.scope = lambda rid: {"search_workflow": "sw"}
    report_pipeline.after_answer(store, {"id": "run_1", "research_id": "res_1"})
    assert calls == []


def test_view_says_the_study_table_is_coming_while_the_answer_runs(tmp_path):
    """The rail's "after the answer" row: set while an answer is unfinished, no table exists and a source is included."""
    for study_table, expected in (("auto", {"sources": 1}), ("off", None)):
        settings = dataclasses.replace(sw_settings(tmp_path / study_table), study_table=study_table)
        app = create_app(settings, adapters={"fake": PipelineAdapter()}, http_client=openalex_client(200), fetcher=fake_fetch,
                         start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
        with TestClient(app) as raw:
            client = session(raw)
            research_id = create(client, source_scope="attached", effort="quick")
            upload_and_include(client, research_id)
            assert client.get(f"/api/researches/{research_id}").json()["study_table_pending"] is None
            assert client.post(f"/api/researches/{research_id}/runs", json={"kind": "answer"}).status_code == 202
            assert client.get(f"/api/researches/{research_id}").json()["study_table_pending"] == expected
            assert client.post(f"/api/researches/{research_id}/tables", json={"title": "SYNTHETIC table"}).status_code == 201
            assert client.get(f"/api/researches/{research_id}").json()["study_table_pending"] is None



def _crash_continuation(tmp_path, monkeypatch, after_successor):
    """Run the chain with the continuation failing (before or after it queued the next run); the column run's rows."""
    from deixis.workflow import report_pipeline
    real, crashed = report_pipeline.continue_after, []

    def crash(store, run):
        if after_successor:
            real(store, run)
            assert store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'table_fill'").fetchone()[0] == 1
        crashed.append(run["id"])
        raise RuntimeError("injected crash in the continuation")

    monkeypatch.setattr(report_pipeline, "continue_after", crash)
    with TestClient(app_for(tmp_path, PipelineAdapter())) as raw:
        client = session(raw)
        store = raw.app.state.store
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        client.post(f"/api/researches/{research_id}/study-table")
        run_id = store.conn.execute("SELECT id FROM runs WHERE kind = 'table_columns'").fetchone()[0]
        deadline = time.time() + 40
        while store.run(run_id)["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.1)
        run = store.run(run_id)
        completed = store.conn.execute("SELECT COUNT(*) FROM events WHERE run_id = ? AND type = 'run_completed'",
                                       (run_id,)).fetchone()[0]
        return crashed, run, completed, kinds(store)


def test_a_crash_while_queueing_the_next_run_leaves_the_run_unfinished(tmp_path, monkeypatch):
    """Audit F1: the run's completion and the chain's next run are one write, so a failure in between undoes both."""
    crashed, run, completed, run_kinds = _crash_continuation(tmp_path, monkeypatch, after_successor=False)
    assert crashed == [run["id"]]
    assert (run["status"], run["pause_reason"]) == ("failed", "internal_error")
    assert "injected crash in the continuation" in run["error"]["error"]
    assert completed == 0 and run_kinds == ["table_columns"]


def test_a_crash_after_the_next_run_was_queued_undoes_it_with_the_completion(tmp_path, monkeypatch):
    """Sol r1: the successor the continuation wrote is rolled back with the completion, not left half-applied."""
    crashed, run, completed, run_kinds = _crash_continuation(tmp_path, monkeypatch, after_successor=True)
    assert crashed == [run["id"]]
    assert (run["status"], run["pause_reason"]) == ("failed", "internal_error")
    assert completed == 0 and run_kinds == ["table_columns"]
