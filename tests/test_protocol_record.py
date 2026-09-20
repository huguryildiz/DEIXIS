"""The frozen protocol record of a research, and the audit digests of what a step sent and received (SW14).

Fixture records are SYNTHETIC: these tests show workflow behavior, not model quality or live provider access.
"""

import json
import sqlite3

import pytest

from deixis.config import Settings, load_settings
from deixis.domain.canonical import sha256_hex
from deixis.storage import db
from deixis.workflow.store import Store


def store_for(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def test_the_protocol_migration_adds_the_record_table_and_the_hash_columns(tmp_path):
    store = store_for(tmp_path)
    columns = lambda table: {row[1] for row in store.conn.execute(f"PRAGMA table_info({table})")}
    assert columns("protocol_records") >= {"id", "research_id", "scope_revision", "protocol_revision", "reason",
                                           "body_json", "body_sha256", "created_at"}
    assert "search_workflow" in columns("scope_revisions")
    assert "protocol_hash" in columns("run_steps")
    assert "payload_sha256" in columns("step_inputs")
    assert "output_sha256" in columns("model_sessions")
    assert "payload_sha256" in columns("search_runs")


def test_a_frozen_protocol_record_can_be_neither_changed_nor_removed(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1"})
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE protocol_records SET reason = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("DELETE FROM protocol_records")


def test_an_unknown_search_workflow_setting_is_refused(monkeypatch):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "bogus")
    with pytest.raises(ValueError):
        load_settings()


def test_the_default_search_workflow_is_legacy():
    assert Settings(data_dir=None).search_workflow == "legacy"


def test_the_workflow_a_research_was_opened_with_survives_a_scope_revision(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None,
                                search_workflow="sw")
    assert store.scope(rid)["search_workflow"] == "sw"
    revision = store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC question, narrowed", None)
    assert store.scope(rid, revision)["search_workflow"] == "sw"
    other = store.create_research("SYNTHETIC other", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    assert store.scope(other)["search_workflow"] == "legacy"


def test_a_second_freeze_of_the_same_body_keeps_one_record_and_a_changed_body_needs_a_reason(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    first = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": ["keyword_search"]})
    again = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": ["keyword_search"]})
    assert (again["id"], again["protocol_revision"]) == (first["id"], 1)
    assert first["hash"] == sha256_hex(first["body"])
    with pytest.raises(ValueError):
        store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": []})
    changed = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": []}, reason="vocabulary approved")
    assert changed["protocol_revision"] == 2
    assert store.current_protocol(rid, 1)["hash"] == changed["hash"]
    row = store.conn.execute("SELECT body_json, body_sha256 FROM protocol_records WHERE id = ?", (changed["id"],)).fetchone()
    assert row["body_sha256"] == sha256_hex(json.loads(row["body_json"]))


def test_build_protocol_is_repeatable_and_reads_its_thresholds_from_their_definitions():
    from deixis.documents.pdf import CHUNK_CHARS
    from deixis.domain.rules import SCREENING_BATCH
    from deixis.workflow import flow, protocol

    scope = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
             "seed_mode": "question_only", "search_workflow": "sw", "providers": ["openalex", "crossref"],
             "model_connection": "fake", "requested_model": "fake-model", "reasoning_effort": None,
             "literature_model": None, "review_mode": "off"}
    plan = {"concepts": [{"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel"]}]}
    queries = [{"provider_id": "openalex", "query_text": "diffusion channel", "results": 25}]
    settings = Settings(data_dir=None)
    body = protocol.build_protocol(scope, {"max_candidates": 20}, plan, queries, "pkg_hash", settings)
    assert sha256_hex(body) == sha256_hex(protocol.build_protocol(scope, {"max_candidates": 20}, plan, queries, "pkg_hash", settings))
    assert body["schema"] == protocol.PROTOCOL_SCHEMA and body["search_workflow"] == "sw"
    assert body["thresholds"]["screening_batch"] == SCREENING_BATCH
    assert body["thresholds"]["chunk_chars"] == CHUNK_CHARS
    assert body["thresholds"]["rrf_k"] == flow.RRF_K
    assert body["thresholds"]["max_passages_per_source"] == flow.MAX_PASSAGES_PER_SOURCE
    assert body["thresholds"]["pdf_pages_per_source"] == flow.PDF_PAGES_PER_SOURCE
    assert body["thresholds"]["max_abstract_chars"] == flow.MAX_ABSTRACT_CHARS
    assert body["thresholds"]["formulation_score_threshold"] == flow.FORMULATION_SCORE_THRESHOLD
    assert body["providers"] == ["crossref", "openalex"] and body["arms"] == ["keyword_search"]
    assert body["compiled_queries"] == [{"provider_id": "openalex", "query_text": "diffusion channel", "results": 25}]
    assert body["vocabulary"] == plan["concepts"] and body["inclusion_criterion"] is None
    assert protocol.build_protocol(scope, {}, None, [], "pkg_hash", settings)["vocabulary"] is None


def test_a_discovery_run_freezes_one_protocol_before_its_first_search_and_stamps_the_later_steps(tmp_path, monkeypatch):
    from fakes import FakeAdapter
    from test_provider_flow import discover, routed, two_provider_plan

    view, run = discover(tmp_path, monkeypatch, routed, FakeAdapter(two_provider_plan))
    assert run["status"] == "completed", run
    store = store_for(tmp_path / "data")
    rows = store.conn.execute("SELECT * FROM protocol_records").fetchall()
    assert len(rows) == 1 and rows[0]["protocol_revision"] == 1 and rows[0]["reason"] is None
    assert rows[0]["body_sha256"] == sha256_hex(json.loads(rows[0]["body_json"]))
    assert json.loads(rows[0]["body_json"])["compiled_queries"]

    keys = [s["operation_key"] for s in run["steps"]]
    assert keys.index("protocol") < min(i for i, k in enumerate(keys) if k.startswith("search:"))
    assert run["protocol_hash"] == rows[0]["body_sha256"]
    hashes = {r["operation_key"]: r["protocol_hash"] for r in store.conn.execute(
        "SELECT operation_key, protocol_hash FROM run_steps WHERE run_id = ?", (run["id"],))}
    assert hashes["search_plan"] is None and hashes["protocol"] is None
    stamped = [k for k in hashes if k.startswith("search:") or k.startswith("screening")]
    assert stamped and all(hashes[k] == rows[0]["body_sha256"] for k in stamped)


def test_a_paused_and_resumed_run_keeps_the_protocol_it_froze(tmp_path, monkeypatch):
    import httpx

    from fakes import FakeAdapter
    from test_provider_flow import discover, routed, two_provider_plan

    down = {"openalex": True}

    def handler(request):
        if request.url.host == "api.crossref.org" or down["openalex"]:
            return httpx.Response(503)
        return routed(request)

    view, run = discover(tmp_path, monkeypatch, handler, FakeAdapter(two_provider_plan),
                         before_resume=lambda store, run_id: down.update(openalex=False))
    assert run["status"] == "completed", run
    store = store_for(tmp_path / "data")
    assert store.conn.execute("SELECT COUNT(*) FROM protocol_records").fetchone()[0] == 1


def test_a_model_step_stores_the_digest_of_what_it_sent_and_what_came_back(tmp_path, monkeypatch):
    from fakes import FakeAdapter
    from test_provider_flow import discover, routed, two_provider_plan

    view, run = discover(tmp_path, monkeypatch, routed, FakeAdapter(two_provider_plan))
    assert run["status"] == "completed", run
    store = store_for(tmp_path / "data")
    inputs = store.conn.execute("SELECT payload_json, payload_sha256 FROM step_inputs").fetchall()
    assert inputs and all(r["payload_sha256"] == sha256_hex(json.loads(r["payload_json"])) for r in inputs)
    sessions = store.conn.execute(
        "SELECT raw_output, output_sha256 FROM model_sessions WHERE raw_output IS NOT NULL").fetchall()
    assert sessions
    for row in sessions:
        assert row["output_sha256"] == "json:" + sha256_hex(json.loads(row["raw_output"]))


def test_an_output_that_is_not_json_is_digested_as_text(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    run = store.create_run(rid, "discovery", {}, None)
    step = store.step(run["id"], "search_plan", "model:search_plan")
    store.insert_step_input(step["id"], rid, run["id"], 0,
                            {"step_input_id": "sti_x", "task_type": "search_plan", "scope_revision": 1,
                             "skill_package_hash": "pkg"}, "base", "dev", "msg", {})
    session_id = store.start_model_session(rid, run["id"], step["id"], "sti_x", "fake", "fake-model")
    store.finish_model_session(session_id, status="completed", raw_output="not json at all")
    digest = store.conn.execute("SELECT output_sha256 FROM model_sessions WHERE id = ?", (session_id,)).fetchone()[0]
    assert digest == "text:" + sha256_hex("not json at all")
    assert store.conn.execute("SELECT payload_sha256 FROM step_inputs WHERE id = 'sti_x'").fetchone()[0] == sha256_hex(
        {"step_input_id": "sti_x", "task_type": "search_plan", "scope_revision": 1, "skill_package_hash": "pkg"})


def test_a_provider_search_stores_the_digest_of_the_payload_it_kept(tmp_path, monkeypatch):
    from fakes import FakeAdapter
    from test_provider_flow import discover, routed, two_provider_plan

    view, run = discover(tmp_path, monkeypatch, routed, FakeAdapter(two_provider_plan))
    assert run["status"] == "completed", run
    store = store_for(tmp_path / "data")
    rows = store.conn.execute("SELECT raw_payload_path, payload_sha256 FROM search_runs").fetchall()
    assert rows and all(r["raw_payload_path"] for r in rows)
    payloads = Settings(data_dir=tmp_path / "data").payloads_dir
    for row in rows:
        stored = json.loads((payloads / row["raw_payload_path"]).read_text(encoding="utf-8"))
        assert row["payload_sha256"] == sha256_hex(stored)


def test_a_later_discovery_run_with_another_plan_opens_a_new_protocol_revision(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from deixis.api.app import create_app
    from deixis.providers.registry import CONNECTORS
    from fakes import FakeAdapter
    from test_provider_flow import no_fetch, routed, two_provider_plan, wait

    plans = []

    def changing_plan(si):
        text = two_provider_plan(si)
        if si["task_type"] != "search_plan":
            return text
        plans.append(si["step_input_id"])
        output = json.loads(text)
        if len(plans) > 1:
            output["search_plan"]["concepts"][0]["synonyms"] = ["diffusion channel", "molecular link"]
        return json.dumps(output)

    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter(changing_plan)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(routed)), fetcher=no_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        body = {"question": "How is diffusion channel scheduling optimized?", "model_connection": "fake",
                "requested_model": "fake-model", "effort": "quick"}
        rid = client.post("/api/researches", json=body).json()["research"]["id"]
        runs = []
        for _ in range(2):
            run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
            _, run = wait(client, rid, run_id)
            assert run["status"] == "completed", run
            runs.append(run)
        rows = app.state.store.conn.execute(
            "SELECT protocol_revision, reason, body_sha256 FROM protocol_records ORDER BY protocol_revision").fetchall()
        assert [(r["protocol_revision"], r["reason"]) for r in rows] == [(1, None), (2, "later_discovery_run")]
        first_search = app.state.store.conn.execute(
            "SELECT protocol_hash FROM run_steps WHERE run_id = ? AND operation_key = 'search:0'", (runs[0]["id"],)).fetchone()
        second_search = app.state.store.conn.execute(
            "SELECT protocol_hash FROM run_steps WHERE run_id = ? AND operation_key = 'search:0'", (runs[1]["id"],)).fetchone()
        view = client.get(f"/api/researches/{rid}").json()
        shown = {r["id"]: r["protocol_hash"] for r in view["runs"]}
        assert (shown[runs[0]["id"]], shown[runs[1]["id"]]) == (rows[0]["body_sha256"], rows[1]["body_sha256"])
        # Steps keep the protocol they ran under; the later run does not rewrite the earlier run's hash.
        assert (first_search["protocol_hash"], second_search["protocol_hash"]) == (rows[0]["body_sha256"], rows[1]["body_sha256"])
