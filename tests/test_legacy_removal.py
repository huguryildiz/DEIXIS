"""Stored legacy discovery is readable, but every route that could resume it is closed."""

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow.store import LegacyResearchReadOnly, Store
from deixis.workflow.views import research_view
from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import wait_run


def old_research(store):
    return store.create_research("SYNTHETIC old question", "attached_and_academic", "quick", ["openalex"],
                                 "fake", "fake-model", "en", search_workflow="legacy")


def old_run(store, rid, kind="discovery", status="paused", key=None):
    run_id = f"run_old_{kind}_{status}_{key or 'one'}"
    store.conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, idempotency_key,"
        " created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'discovery', '{}', ?, ?, ?)",
        (run_id, rid, kind, status, key, now(), now()),
    )
    return run_id


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    yield Store(conn)
    conn.close()


def test_stored_legacy_plan_and_screening_notes_remain_readable(store):
    rid = old_research(store)
    run_id = old_run(store, rid, status="completed")
    query = {"provider_id": "openalex", "query_text": '"stored synonym"', "rationale": "SYNTHETIC v1 rationale"}
    plan = {"output_type": "SearchPlan", "result": {
        "schema_version": "deixis.search_plan.v1", "queries": [query],
        "question_interpretation": "old interpretation", "search_rationale": "old rationale",
        "scope_boundaries": ["one provider"],
        "concepts": [{"label": "old concept", "synonyms": ["stored synonym"]}]}}
    for key, kind, output in (("search_plan", "model:search_plan", plan),
                              ("screening", "model:screening", {"result": {"notes": "old screening note"}})):
        step = store.step(run_id, key, kind)
        store.finish_step(step["id"], "succeeded", output=output)
    view = research_view(store, rid)
    assert view["research"]["read_only_reason"] == "legacy_research_read_only"
    assert view["runs"][0]["plan"]["concepts"][0]["synonyms"] == ["stored synonym"]
    assert view["runs"][0]["plan"]["queries"] == [query]
    assert view["runs"][0]["screening_notes"][0]["text"] == "old screening note"
    assert "queue" not in view["counts"]


def test_legacy_answer_uses_stored_plan_concepts(tmp_path, monkeypatch):
    from deixis.workflow.flow import MAX_SMALL_PDF_PAGES

    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data"), adapters={"fake": adapter},
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = old_research(store)
        run_id = old_run(store, rid, status="completed")
        step = store.step(run_id, "search_plan", "model:search_plan")
        store.finish_step(step["id"], "succeeded", output={"output_type": "SearchPlan", "result": {
            "question_interpretation": "old question", "search_rationale": "old rationale", "scope_boundaries": [],
            "concepts": [{"label": "stored anchor phrase", "synonyms": ["prior term"]}]}})
        assert "stored" in app.state.worker.flow._topic_terms(rid, store.scope(rid))
        pages = [f"Unrelated background page {i}." for i in range(MAX_SMALL_PDF_PAGES)]
        pages[-2] = "prior background background background background background background."
        pages[-1] = "stored anchor phrase background background background background."
        pages += ["stored anchor phrase prior term background background."]
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "old.pdf", make_pdf(pages), "application/pdf")})
        assert upload.status_code == 201, upload.text
        searches = []
        original = store.search_passages
        def record_ranking(included, query, limit):
            ranked = original(included, query, limit)
            searches.append((query, [p["physical_page"] for p in ranked]))
            return ranked
        monkeypatch.setattr(store, "search_passages", record_ranking)
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert response.status_code == 202, response.text
        view, run = wait_run(client, rid, response.json()["id"])
        assert run["status"] == "completed" and view["answers"][0]["status"] == "structurally_valid"
        assert not any(step["operation_key"] == "answer_start_snapshot" for step in run["steps"])
        assert not any(step["operation_key"] == "criterion_phrases" for step in run["steps"])
        assert any(call["task_type"] == "grounded_answer" for call in adapter.calls)
        answer_input = next(call for call in adapter.calls if call["task_type"] == "grounded_answer")
        expected_order = [MAX_SMALL_PDF_PAGES + 1, MAX_SMALL_PDF_PAGES, MAX_SMALL_PDF_PAGES - 1]
        assert searches and searches[0][1] == expected_order
        assert '"stored"' in searches[0][0] and '"prior"' in searches[0][0]
        assert [p["locator"]["physical_page"] for p in answer_input["passages"]] == expected_order


def test_store_rejects_scope_edits_and_all_discovery_queue_paths(store):
    rid = old_research(store)
    with pytest.raises(LegacyResearchReadOnly):
        store.revise_scope(rid, store.research(rid)["version"], "changed question", None)
    with pytest.raises(LegacyResearchReadOnly):
        store.set_seed(rid, store.research(rid)["version"], "missing")
    for kind in ("discovery", "fulltext_fetch", "fulltext_adjudication"):
        with pytest.raises(LegacyResearchReadOnly):
            store.create_run(rid, kind, {}, "used-key")
        paused = old_run(store, rid, kind=kind)
        with pytest.raises(LegacyResearchReadOnly):
            store.update_run(paused, status="queued")
        with pytest.raises(LegacyResearchReadOnly):
            store.update_run(paused, status="running")
    completed = old_run(store, rid, status="completed", key="used-key")
    with pytest.raises(LegacyResearchReadOnly):
        store.create_run(rid, "discovery", {}, "used-key")
    with pytest.raises(LegacyResearchReadOnly):
        store.queue_failed_search_retry(completed)
    for path in (store.submit_approval, store.request_term_suggestions, store.choose_code_query):
        with pytest.raises(LegacyResearchReadOnly):
            path(completed, {}) if path == store.submit_approval else path(completed)
    # Answer and auxiliary runs remain available. Each is ended before the next queue operation.
    for kind in ("answer", "pdf_collection", "pdf_ocr", "table_columns", "table_fill", "cell_recheck", "research_title", "report"):
        run = store.create_run(rid, kind, {}, None)
        store.update_run(run["id"], status="running")
        store.update_run(run["id"], status="completed")


def test_legacy_auxiliary_runs_produce_pdf_ocr_table_title_and_report_outputs(tmp_path, monkeypatch):
    from dataclasses import replace
    from deixis.documents.fetch import FetchResult
    from helpers import make_scanned_pdf
    from test_api_flow import app_for, session
    from test_ocr_run import fake_reader, ocr_url
    from test_report_api import create_table, fill_table
    from test_report_flow import CELL_QUOTE, COLUMN, FUTURE_WORK_COLUMN, LIMITATIONS_COLUMN, PASSAGE, ReportAdapter
    from test_search_paging import record, search

    app = app_for(tmp_path, ReportAdapter())
    fetched = []
    async def fetch_pdf(url):
        fetched.append(url)
        return FetchResult("ok", data=make_scanned_pdf([("text", PASSAGE), ("scan", "SYNTHETIC scanned evidence")]),
                           final_url=url, http_status=200)
    # Injected transport and OCR reader never access a provider or installed OCR tool.
    calls = fake_reader(monkeypatch)
    with TestClient(app) as raw:
        app.state.worker.flow.deps.fetch_pdf = fetch_pdf
        client = session(raw)
        store = app.state.store
        rid = old_research(store)
        historic = old_run(store, rid, status="completed")
        source = replace(record(1), title="SYNTHETIC stored evidence", oa_pdf_url="https://example.org/synthetic.pdf",
                         version_label="publishedVersion", oa_pdf_version="publishedVersion")
        search(store, rid, historic, "stored:search", [source])
        svid = research_view(store, rid)["sources"][0]["source_version_id"]
        selection = research_view(store, rid)["sources"][0]["selection"]
        response = client.patch(f"/api/researches/{rid}/selections/{svid}", json={
            "state": "included", "expected_version": selection["version"], "reason": "SYNTHETIC user inclusion"})
        assert response.status_code == 200, response.text
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"})
        assert collection.status_code == 202, collection.text
        view, run = wait_run(client, rid, collection.json()["id"])
        assert run["status"] == "completed" and fetched == [source.oa_pdf_url]
        aid = next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]["id"]
        assert store.passages_for(svid)[0]["text"] == PASSAGE
        started = client.post(ocr_url(rid, svid, aid))
        assert started.status_code == 202, started.text
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed" and calls == [2]
        passages = store.passages_for(svid)
        assert [(p["physical_page"], p["text_source"], p["text"]) for p in passages] == [
            (1, "text_layer", PASSAGE), (2, "ocr", "SYNTHETIC OCR text of page 2.")]
        table = create_table(client, rid, with_columns=False)
        tid = table["table"]["id"]
        suggested = client.post(f"/api/researches/{rid}/tables/{tid}/column-suggestions")
        assert suggested.status_code == 202, suggested.text
        _, run = wait_run(client, rid, suggested.json()["id"])
        assert run["status"] == "completed", run["error"]
        suggested_columns = client.get(f"/api/researches/{rid}/tables/{tid}").json()["column_suggestions"]
        assert suggested_columns["columns"][0]["name"] == "SYNTHETIC method"
        for column in (COLUMN, LIMITATIONS_COLUMN, FUTURE_WORK_COLUMN):
            response = client.post(f"/api/researches/{rid}/tables/{tid}/columns", json={
                **column, "expected_version": table["table"]["version"]})
            assert response.status_code == 201, response.text
            table = response.json()
        fill_table(client, rid, client.get(f"/api/researches/{rid}/tables/{tid}").json())
        from deixis.workflow.tables import TableStore
        cells = TableStore(store).table_view(rid, tid)["cells"]
        assert len(cells) == 3
        assert all(c["current"]["value"] == {"text": "SYNTHETIC fake value"} for c in cells)
        assert all(c["current"]["evidence"][0]["passage_id"] == passages[0]["id"] for c in cells)
        title = client.post(f"/api/researches/{rid}/runs", json={"kind": "research_title"})
        assert title.status_code == 202, title.text
        view, run = wait_run(client, rid, title.json()["id"])
        assert run["status"] == "completed" and view["research"]["title"] == "Synthetic short research title"
        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": tid})
        assert started.status_code == 202, started.text
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed", run
        report = client.get(f"/api/researches/{rid}/reports/{started.json()['target']['report_id']}").json()
        assert report["status"] == "valid" and all(s["draft"] for s in report["sections"])
        links = [e for s in report["sections"] for c in s["claims"] for e in c["evidence"]]
        assert links and all(e["anchor_text"] == CELL_QUOTE for e in links)


def test_api_rejects_each_legacy_discovery_entry_and_keeps_answer_resume(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"), adapters={}, start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = old_research(store)
        paused = old_run(store, rid)
        for kind in ("discovery", "fulltext_fetch", "fulltext_adjudication"):
            response = client.post(f"/api/researches/{rid}/runs", json={"kind": kind})
            assert (response.status_code, response.json()["detail"]) == (409, "legacy_research_read_only")
        routes = [
            ("post", f"/api/runs/{paused}/resume", None),
            ("post", f"/api/runs/{paused}/retry_failed", None),
            ("post", f"/api/runs/{paused}/protocol-approval", {}),
            ("post", f"/api/runs/{paused}/term-suggestions", None),
            ("post", f"/api/runs/{paused}/search-query-choice", None),
            ("post", f"/api/researches/{rid}/seed", {"expected_version": 0, "source_version_id": "srv_missing0"}),
            ("post", f"/api/researches/{rid}/scope", {"expected_version": 0, "question": "changed question"}),
        ]
        for method, path, body in routes:
            response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            assert (response.status_code, response.json()["detail"]) == (409, "legacy_research_read_only"), path
        no_source_answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert no_source_answer.status_code == 422
        assert no_source_answer.json()["detail"] == "Include at least one source before generating an answer"
        answer = old_run(store, rid, kind="answer")
        response = client.post(f"/api/runs/{answer}/resume")
        assert response.status_code == 200 and response.json()["status"] == "queued"


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_recovery_then_cleanup_cancels_legacy_discovery_atomically(store, tmp_path, status):
    rid = old_research(store)
    run_id = old_run(store, rid, status=status)
    old_run(store, rid, kind="answer", status="queued")
    worker = Worker(store, None, tmp_path / "worker.lock")
    worker.recover()
    assert worker.cancel_legacy_discovery() == 1
    assert store.run(run_id)["status"] == "cancelled"
    events = [e for e in store.events_after(rid, 0) if e["run_id"] == run_id and e["type"] == "run_cancelled"]
    assert len(events) == 1 and events[0]["payload"]["reason"] == "legacy_workflow_removed"
    assert store.conn.execute("SELECT status FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchone()[0] == "queued"
    assert worker.cancel_legacy_discovery() == 0


def test_cleanup_rolls_back_status_when_event_cannot_be_written(store, tmp_path):
    rid = old_research(store)
    run_id = old_run(store, rid, status="queued")
    store.conn.execute("CREATE TRIGGER refuse_event BEFORE INSERT ON events WHEN new.payload_json LIKE '%legacy_workflow_removed%'"
                       " BEGIN SELECT RAISE(ABORT, 'event refused'); END")
    worker = Worker(store, None, tmp_path / "worker.lock")
    worker.recover()
    with pytest.raises(Exception, match="event refused"):
        worker.cancel_legacy_discovery()
    assert store.run(run_id)["status"] == "queued"
