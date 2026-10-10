"""D175: restore applicable D119 end-to-end assertions using synthetic sw discovery.

All HTTP is mocked and every model response is scripted. No scientific validity is inferred.
"""

import json

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain.canonical import sha256_hex
from deixis.models.adapter import ModelStepResult
from deixis.providers import query_compiler
from deixis.workflow import lookups
from fakes import FakeAdapter
from test_api_flow import session, sw_settings, wait_run
from test_provider_flow import no_fetch, routed


def app_for(tmp_path, handler, adapter):
    return create_app(sw_settings(tmp_path), adapters={"fake": adapter},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def start(client):
    rid = client.app.state.store.create_research(
        "How does diffusion channel scheduling affect relay energy?", "academic", "quick",
        ["openalex", "biorxiv", "crossref"], "fake", "fake-model", "en")
    response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
    assert response.status_code == 202, response.text
    return rid, response.json()["id"]


def assert_audit(store, settings, rid, run):
    rows = store.conn.execute("SELECT * FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,)).fetchall()
    assert rows and all(row["body_sha256"] == sha256_hex(json.loads(row["body_json"])) for row in rows)
    protocol_hash = run["protocol_hash"]
    assert protocol_hash in [row["body_sha256"] for row in rows]
    keys = [step["operation_key"] for step in run["steps"]]
    assert keys.index("protocol") < min(i for i, key in enumerate(keys) if key.startswith("search:"))
    stamped = store.conn.execute("SELECT operation_key, protocol_hash FROM run_steps WHERE run_id = ?", (run["id"],)).fetchall()
    later = [row for row in stamped if row["operation_key"].startswith(("search:", "abstract:", "ranking"))]
    assert later and all(row["protocol_hash"] == protocol_hash for row in later)
    protocol_step = next(row for row in stamped if row["operation_key"] == "protocol")
    revision = next(i for i, row in enumerate(rows) if row["body_sha256"] == protocol_hash)
    assert protocol_step["protocol_hash"] == (rows[revision - 1]["body_sha256"] if revision else None)
    inputs = store.conn.execute("SELECT payload_json, payload_sha256 FROM step_inputs WHERE run_id = ?", (run["id"],)).fetchall()
    assert inputs and all(row["payload_sha256"] == sha256_hex(json.loads(row["payload_json"])) for row in inputs)
    sessions = store.conn.execute("SELECT raw_output, output_sha256 FROM model_sessions WHERE run_id = ? AND raw_output IS NOT NULL", (run["id"],)).fetchall()
    assert sessions and all(row["output_sha256"] == "json:" + sha256_hex(json.loads(row["raw_output"])) for row in sessions)
    searches = store.conn.execute("SELECT raw_payload_path, payload_sha256 FROM search_runs WHERE run_id = ? AND status = 'completed'", (run["id"],)).fetchall()
    assert searches and all(row["raw_payload_path"] for row in searches)
    for row in searches:
        payload = json.loads((settings.payloads_dir / row["raw_payload_path"]).read_text())
        assert row["payload_sha256"] == sha256_hex(payload)


def test_sw_records_freeze_stamp_digest_merge_and_open_a_later_revision(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, routed, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid, run_id = start(client)
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        store = app.state.store
        assert_audit(store, sw_settings(tmp_path), rid, run)
        rows = store.conn.execute("SELECT * FROM protocol_records WHERE research_id = ?", (rid,)).fetchall()
        assert len(rows) == 1 and (rows[0]["protocol_revision"], rows[0]["reason"]) == (1, None)
        queries = store.step(run_id, "vocabulary", "code:vocabulary")["output"]["queries"]
        assert json.loads(rows[0]["body_json"])["compiled_queries"] == [
            {k: q[k] for k in ("provider_id", "query_text")} for q in queries]
        # The fast path (D252) asks OpenAlex alone: the question to its semantic search, then the OpenAlex keyword
        # query, then the chain. The bioRxiv query stays in the protocol and is dropped from the search plan.
        searched = [s for s in view["search_runs"] if not s["query_text"].startswith("chain:")]
        keyword = [q for q in queries if q["provider_id"] == "openalex"]
        assert [(s["provider"], s["result_count"]) for s in searched] == [("openalex", 1), ("openalex", 1)]
        assert [(s["provider"], s["query_text"]) for s in searched[1:]] == [
            (q["provider_id"], q["query_text"]) for q in keyword]
        plan = json.loads(rows[0]["body_json"])["fast_path_search"]
        assert [(d["query"]["provider_id"], d["reason"]) for d in plan["dropped"]] == [("biorxiv", "openalex_only")]
        assert run["usage"]["provider_requests"] == 2 and view["counts"]["unique"] == 1
        merged = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        assert merged["provider_records"] == ["openalex"]  # the semantic, keyword and chain rows are one source
        assert "crossref" in view["scope"]["providers"] and "crossref" not in [q["provider_id"] for q in queries]
        assert lookups.in_scope(view["scope"], "crossref") is True
        assert adapter.calls and all("crossref" not in call["enabled_providers"] for call in adapter.calls)
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
        assert second.status_code == 202, second.text
        view, later = wait_run(client, rid, second.json()["id"])
        assert later["status"] == "completed", later
        rows = store.conn.execute("SELECT * FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,)).fetchall()
        assert [(r["protocol_revision"], r["reason"]) for r in rows] == [(1, None), (2, "later_discovery_run")]
        shown = {r["id"]: r["protocol_hash"] for r in view["runs"]}
        assert [shown[r["id"]] for r in (run, later)] == [r["body_sha256"] for r in rows]
        assert_audit(store, sw_settings(tmp_path), rid, later)


def test_sw_failed_provider_is_retained_and_retry_reuses_queries_and_protocol(tmp_path, monkeypatch):
    # The fast path searches OpenAlex alone (D252), so its keyword page is the one that fails here.
    attempts = []
    limited = True
    def handler(request):
        params = request.url.params
        if params.get("per_page") == "1" or "search.title_and_abstract" not in params:
            return routed(request)  # count probes, the semantic search and the chain
        attempts.append(params["search.title_and_abstract"])
        if limited:
            return httpx.Response(429, headers={"retry-after": "60"})
        return routed(request)
    adapter = FakeAdapter()
    app = app_for(tmp_path, handler, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid, run_id = start(client)
        view, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("completed", None)
        keyword = lambda view: [(s["provider"], s["status"]) for s in view["search_runs"] if s["query_text"] == attempts[0]]
        assert keyword(view) == [("openalex", "rate_limited")]
        assert [(s["operation_key"], s["status"]) for s in run["steps"] if s["operation_key"].startswith("search:")] == [
            ("search:fast:semantic", "succeeded"), ("search:0", "failed")]
        assert view["counts"]["unique"] == 1
        assert run["budget"]["inspection"]["policy"] == "small_batch_fused_v1"
        assert any(s["operation_key"].startswith("small_batch:v1:")
                   and s["operation_key"].endswith(":abstract_stage") for s in run["steps"])
        store = app.state.store
        frozen = store.current_protocol(rid, 1)
        planning_calls = [call for call in adapter.calls if call["task_type"] in ("vocabulary_labels", "criterion_proposal")]
        def refuse_compile(*args, **kwargs):
            raise AssertionError("Retry must use stored compiled queries")
        monkeypatch.setattr(query_compiler, "compile_block_queries", refuse_compile)
        limited = False
        retry = client.post(f"/api/runs/{run_id}/retry_failed")
        assert retry.status_code == 200, retry.text
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        assert keyword(view) == [("openalex", "rate_limited"), ("openalex", "completed")]
        assert attempts == [attempts[0], attempts[0]]
        assert store.current_protocol(rid, 1) == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == 1
        assert [call for call in adapter.calls if call["task_type"] in ("vocabulary_labels", "criterion_proposal")] == planning_calls


def test_sw_pause_resume_keeps_frozen_protocol_and_does_not_repeat_search(tmp_path, monkeypatch):
    down = True
    def failure(si):
        if down and si["task_type"] == "abstract_screening":
            return ModelStepResult("failed", error="SYNTHETIC paused connection")
    adapter = FakeAdapter(fail=failure)
    app = app_for(tmp_path, routed, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        rid, run_id = start(client)
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "paused", run
        store = app.state.store
        frozen = store.current_protocol(rid, 1)
        searches = view["search_runs"]
        vocabulary = store.step(run_id, "vocabulary", "code:vocabulary")["output"]
        def refuse_compile(*args, **kwargs):
            raise AssertionError("Resume must use stored compiled queries")
        monkeypatch.setattr(query_compiler, "compile_block_queries", refuse_compile)
        down = False
        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        view, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        assert view["search_runs"] == searches
        assert store.step(run_id, "vocabulary", "code:vocabulary")["output"] == vocabulary
        assert store.current_protocol(rid, 1) == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == 1
