"""Offline driver evidence: fake records and MockTransport, no live/model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess

import httpx
import pytest

from test_p6_measure_lineage import finished, G, db_path  # noqa: F401
from test_lineage_flow import factory, lib  # noqa: F401

from scripts.p9_owed import l9_run as l9


@pytest.fixture(autouse=True)
def isolated_test_root(tmp_path, monkeypatch):
    # The safety guard still checks confinement, symlinks and nlink; synthetic
    # tests use pytest's temporary root in place of the measurement worktree.
    monkeypatch.setattr(l9.k6, "ROOT", tmp_path)


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run(status="completed", cause=None, kind="discovery", pause=None):
    return {"id": "r1", "research_id": "res1", "status": status, "kind": kind,
            "pause_reason": pause, "created_at": 1000, "budget": {"max_model_calls": 10},
            "usage": {"model_calls": 0}}


def reading(status="completed", cause=None, sessions=None):
    return {"sessions": sessions or [], "runs": [run(status)], "steps": [
        {"id": "st1", "run_id": "r1", "status": "failed", "error_code": "model_failed", "error_json": json.dumps(cause)}
    ] if cause is not None else []}


class FakeAPI:
    def __init__(self, states=None):
        self.states = states or [run()]
        self.posts, self.gets = [], []
        self.table = {"table": {"id": "t1", "version": 1}, "rows": [{"source_version_id": f"s{i}", "work_id": f"w{i}"} for i in range(6)],
                      "removed_rows": [], "columns": []}
        self.view = {"status": {"pdf_text_rows": 6, "nodes_complete": 4}}
        self.preview = {"selected": [{"to": "s1", "candidate_count": 2}, {"to": "s2", "candidate_count": 1}],
                        "counts": {"candidates": 3}, "preview_fingerprint": "a" * 64, "max_model_calls": 6, "retry_failed": False}

    def get(self, path):
        self.gets.append(path)
        if path.endswith("/lineage/plan"):
            return deepcopy(self.preview)
        if path.endswith("/lineage"):
            return deepcopy(self.view)
        if path.endswith("/t1"):
            return deepcopy(self.table)
        if path.endswith("/queue"):
            return {"rows": getattr(self, "queue", [])}
        current = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"runs": [deepcopy(current)]}

    def post(self, path, body, key):
        self.posts.append((path, deepcopy(body), key))
        if path == "/api/researches":
            return {"research": {"id": "res1"}, "scope": {"search_workflow": "sw"}}
        if path.endswith("/tables"):
            return deepcopy(self.table)
        if path.endswith("/lineage/columns"):
            from deixis.workflow.tables import LINEAGE_ROLE_COLUMNS
            self.table["columns"] = [{"lineage_role": role, "name": name, "instruction": text, "answer_format": "text"}
                                     for role, (name, text) in LINEAGE_ROLE_COLUMNS.items()]
            self.table["table"]["version"] += 1
            return deepcopy(self.table)
        return run()


def driver(tmp_path, api=None, data=None):
    clock = Clock()
    d = l9.Driver(api or FakeAPI(), tmp_path, tmp_path / "library.sqlite", clock=clock, sleep=clock.sleep,
                  read=lambda _: deepcopy(data or reading()))
    d.state.update(baseline=[], preparation_started_at=1000)
    d.state["attempts"] = [{"research_id": "res1", "table_id": "t1", "discovery_complete": True,
                             "rows": [f"s{i}" for i in range(6)], "included": [{"source_version_id": f"s{i}"} for i in range(6)],
                             "rows_table_sha256": "rows-hash", "K1": {"pass": True, "pdf_text_rows": 6}}]
    d.save()
    return d


def k0(d):
    return {"K0": "no_overlap_detected", "status": "checked", "required_inventories": list(l9.independence.REQUIRED_INVENTORIES),
            "researches": [{"research_id": "res1", "included_works": [
                {"head_source_version_id": sid, "matches": [], "independence_unverified": False} for sid in d.current()["rows"]]}]}


@pytest.mark.parametrize("base", ["http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765", "http://example.org:8873", "http://127.0.0.1:8872"])
def test_refuse_base(tmp_path, base):
    with pytest.raises(l9.Refused):
        l9.API(base, tmp_path, transport=httpx.MockTransport(lambda r: pytest.fail("request forbidden")))


def test_api_ledger_csrf_guard_and_uncertain_delivery(tmp_path):
    events = []
    def transport(request):
        events.append(request.url.path)
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"csrf_token": "PRIVATE"})
        assert events[-2] == "guard"
        assert request.headers["x-deixis-csrf"] == "PRIVATE"
        assert request.headers["Origin"] == "http://127.0.0.1:8873"
        raise httpx.ReadTimeout("uncertain")
    api = l9.API("http://127.0.0.1:8873", tmp_path, transport=httpx.MockTransport(transport), port_guard=lambda _: events.append("guard"))
    with pytest.raises(l9.Refused):
        api.post("/api/researches", {"question": "Q"}, "key")
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["request", "response", "request", "error"]
    assert rows[-2]["body"] == {"question": "Q"}
    assert "PRIVATE" not in (tmp_path / "ledger.jsonl").read_text()
    assert events.count("/api/researches") == 1
    api.close()


@pytest.mark.parametrize("returncode,stdout,stderr,free", [(1, "", "", True), (0, "p12\n", "", False), (1, "", "error", False)])
def test_lsof_json(tmp_path, returncode, stdout, stderr, free):
    runner = lambda *a, **k: subprocess.CompletedProcess(a[0], returncode, stdout, stderr)
    if free:
        l9.port_check(tmp_path, runner)
    else:
        with pytest.raises(l9.Refused):
            l9.port_check(tmp_path, runner)
    assert json.loads((tmp_path / "port-checks.jsonl").read_text())["free"] is free


def test_timeout_only_resume_after_600_seconds(tmp_path):
    api = FakeAPI([run("paused"), run("paused"), run()])
    d = driver(tmp_path, api, reading("paused", "client_timeout"))
    assert d.poll(run("paused"), "discovery")["status"] == "completed"
    assert d.clock() == 1600
    assert [p[0] for p in api.posts] == ["/api/runs/r1/resume"]
    assert d.state["run_records"]["r1"]["timeout_resumes"] == 1


@pytest.mark.parametrize("cause", ["bad schema", ["client_timeout", "quota"], ["client_timeout", "bad schema"], "model mismatch", "quota", "serverOverloaded", None])
def test_no_resume_other_mixed_unknown(tmp_path, cause):
    api = FakeAPI([run("paused")])
    d = driver(tmp_path, api, reading("paused", cause))
    with pytest.raises(l9.Refused):
        d.poll(run("paused"), "discovery")
    assert not api.posts


def test_second_timeout_stops(tmp_path):
    api = FakeAPI([run("paused")])
    d = driver(tmp_path, api, reading("paused", "client_timeout"))
    with pytest.raises(l9.Refused):
        d.poll(run("paused"), "discovery")
    assert len(api.posts) == 1
    assert api.posts[0][0].endswith("/resume")


@pytest.mark.parametrize("status", ["paused", "pause_requested", "failed", "completed", "cancelled"])
def test_never_cancel_paused_or_terminal(tmp_path, status):
    api = FakeAPI([run(status)])
    d = driver(tmp_path, api)
    assert not d.safe_cancel("r1")
    assert not api.posts


def test_cancel_fresh_second_read_changes_to_paused(tmp_path):
    api = FakeAPI([run("running"), run("paused")])
    assert not driver(tmp_path, api).safe_cancel("r1")
    assert not api.posts
    assert len(api.gets) == 2


def session(i):
    return {"id": f"ms{i}", "connection": "codex", "requested_model": "gpt-5.6-luna", "resolved_model": "gpt-5.6-luna",
            "tool_item_types_json": "[]", "status": "completed"}


def test_session_cap_stops_and_cancels_active_once(tmp_path):
    api = FakeAPI([run("running")])
    d = driver(tmp_path, api, reading("running", sessions=[session(i) for i in range(60)]))
    with pytest.raises(l9.Refused, match="cap"):
        d.poll(run("running"), "fill")
    assert [p[0] for p in api.posts] == ["/api/runs/r1/cancel"]
    assert d.state["new_sessions"] == 60


def test_preparation_combined_cap_not_reset(tmp_path):
    api = FakeAPI([run("paused")])
    d = driver(tmp_path, api, reading("paused", sessions=[session(i) for i in range(180)]))
    with pytest.raises(l9.Refused, match="cap"):
        d.poll(run("paused"), "discovery")
    assert not api.posts


def test_model_or_tool_violation(tmp_path):
    s = session(1)
    s["tool_item_types_json"] = '["exec"]'
    d = driver(tmp_path, data=reading(sessions=[s]))
    with pytest.raises(l9.Refused, match="tool violation"):
        d.observe()


def test_k1_mismatch_no_columns_fill(tmp_path, monkeypatch):
    api = FakeAPI()
    api.view["status"]["pdf_text_rows"] = 5
    d = driver(tmp_path, api)
    del d.current()["table_id"]
    monkeypatch.setattr(l9.k6, "safe_db", lambda p: p)
    monkeypatch.setattr(l9.KIT, "selected_rows", lambda *a: {"rows": [f"s{i}" for i in range(6)], "included_works": []})
    with pytest.raises(l9.Refused, match="K1"):
        d.rows()
    assert [p[0] for p in api.posts] == ["/api/researches/res1/tables"]
    with pytest.raises(l9.Refused):
        d.columns_fill(tmp_path / "absent")
    assert d.state["closed"]
    assert l9.load(tmp_path / "outcome.json")["reason"] == "korpus koşulu karşılanmadı"


@pytest.mark.parametrize("nodes,pairs,later,passed2,passed3", [(4, [2, 1], ["s1", "s2"], True, True),
    (3, [2, 1], ["s1", "s2"], False, True), (4, [3], ["s1"], True, False), (4, [1, 1], ["s1", "s2"], True, False)])
def test_gate_evaluation(tmp_path, nodes, pairs, later, passed2, passed3):
    d = driver(tmp_path)
    api = d.api
    api.view["status"]["nodes_complete"] = nodes
    api.preview["selected"] = [{"to": sid, "candidate_count": n} for sid, n in zip(later, pairs)]
    api.preview["counts"]["candidates"] = sum(pairs)
    gates = l9.evaluate_gates(k0(d), d.current(), api.view, api.preview, api.table)
    assert gates["K0"]["pass"]
    assert gates["K2"]["pass"] is passed2
    assert gates["K3"]["pass"] is passed3


def test_k3_distinct_works_not_versions(tmp_path):
    d = driver(tmp_path)
    d.api.table["rows"][2]["work_id"] = "w1"
    assert not l9.evaluate_gates(k0(d), d.current(), d.api.view, d.api.preview, d.api.table)["K3"]["pass"]


def test_k0_missing_inventory_and_scope_mismatch(tmp_path):
    d = driver(tmp_path)
    record = k0(d)
    record["required_inventories"].pop()
    assert not l9.evaluate_gates(record, d.current(), d.api.view, d.api.preview, d.api.table)["K0"]["pass"]
    record = k0(d)
    record["researches"][0]["included_works"].pop()
    assert not l9.evaluate_gates(record, d.current(), d.api.view, d.api.preview, d.api.table)["K0"]["pass"]


def test_gate_failed_no_lineage(tmp_path):
    d = driver(tmp_path)
    l9.write(tmp_path / "gates.json", {"gates": {"K0": {"pass": False}}})
    assert d.lineage("nonexistent", "hash") is None
    assert not d.api.posts


def test_columns_verbatim_rows_retained_and_l2_fields(tmp_path):
    d = driver(tmp_path)
    path = tmp_path / "k0.json"
    l9.write(path, k0(d))
    gates = d.columns_fill(path)
    assert [c["instruction"] for c in d.api.table["columns"]] == [c["instruction"] for c in l9.load(l9.L1)["columns"]]
    assert [p[0] for p in d.api.posts] == [d.tp() + "/lineage/columns", d.tp() + "/fill"]
    assert gates["rows"] == [f"s{i}" for i in range(6)]
    assert gates["counts"] == d.api.preview["counts"]
    assert gates["preview_fingerprint"] == "a" * 64
    assert gates["table_response_hashes"]["filled"] == l9.digest(d.api.table)
    assert d.current()["preparation_complete"]


def test_no_manual_rows(tmp_path):
    d = driver(tmp_path)
    d.api.table["rows"].reverse()
    with pytest.raises(l9.Refused, match="rows"):
        d.columns_fill("absent")
    assert not d.api.posts


def test_bad_l2_hash_blocks_post(tmp_path):
    d = driver(tmp_path)
    path = tmp_path / "k0.json"
    l9.write(path, k0(d))
    d.columns_fill(path)
    l2 = tmp_path / "l2.json"
    l9.write(l2, l9.load(tmp_path / "gates.json"))
    before = len(d.api.posts)
    with pytest.raises(l9.Refused, match="Ek L2"):
        d.lineage(l2, "b" * 64)
    assert len(d.api.posts) == before


def test_second_attempt_blocked_after_complete_or_gate_failure(tmp_path):
    d = driver(tmp_path)
    d.current()["preparation_complete"] = True
    with pytest.raises(l9.Refused, match="second attempt"):
        d.discover(new_attempt=True)
    assert not d.api.posts


def test_discover_exact_fields_and_unchanged_approval(tmp_path):
    api = FakeAPI([run("paused", pause="protocol_approval_needed"), run()])
    clock = Clock()
    d = l9.Driver(api, tmp_path, "unused", clock=clock, sleep=clock.sleep, read=lambda _: {"sessions": [], "runs": [], "steps": []})
    d.discover()
    body = api.posts[0][1]
    assert body["question"] == l9.load(l9.L1)["question"]
    assert body["effort"] == "standard" and body["language_hint"] == "en"
    assert [body[k] for k in ("model_connection", "requested_model", "reasoning_effort")] == l9.MODEL
    assert api.posts[-1][1] == {}
    rec = d.state["run_records"]["r1"]["protocol_approved"]
    assert rec["unchanged"] and rec["approver"] == "executor model" and rec["product_approved_by"] == "user"


def make_queue_db(tmp_path, count):
    db = tmp_path / "library.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE passages(id TEXT, source_version_id TEXT, kind TEXT, text TEXT)")
        conn.executemany("INSERT INTO passages VALUES(?,?,?,?)", [(f"p{i}", f"s{i}", "abstract", "stored diffusion text") for i in range(count)])
    return db


def queue_driver(tmp_path, count=31):
    d = driver(tmp_path)
    d.db = make_queue_db(tmp_path, count)
    del d.current()["table_id"]
    d.api.queue = [{"source_version_id": f"s{i}", "work_id": f"w{i:02}", "title": f"Diffusion {i:02}", "row_token": f"tok{i}"} for i in range(count)]
    return d


def queue_runner(command, **kwargs):
    assert command[:7] == ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "medium", "--tools"]
    packet = json.loads(kwargs["input"].split("\n", 1)[1])
    assert len(packet["works"]) <= 30
    return subprocess.CompletedProcess(command, 0, json.dumps({"modelUsage": {"claude-opus-5-5": {}}, "result": json.dumps({"decisions": []})}), "")


def test_queue_30_works_once_per_attempt_two_total_person_remark(tmp_path):
    d = queue_driver(tmp_path)
    d.queue_pass(queue_runner)
    assert d.state["queue_requests"][0]["works"] == 30
    assert 'label is wrong' in d.state["queue_requests"][0]["person_label_remark"]
    with pytest.raises(l9.Refused, match="one request"):
        d.queue_pass(queue_runner)
    d.current()["research_id"] = "res2"
    d.queue_pass(queue_runner)
    d.current()["research_id"] = "res3"
    with pytest.raises(l9.Refused, match="two total"):
        d.queue_pass(queue_runner)
    assert len(d.state["queue_requests"]) == 2
    assert 'label is wrong' in (tmp_path / "queue-pass/ledger.jsonl").read_text()


def test_queue_product_decision_note_and_no_text_inclusion(tmp_path):
    d = queue_driver(tmp_path, 1)
    def answer(command, **kwargs):
        decision = {"source_version_id": "s0", "decision": "include", "reason": "stored task matches", "reading_depth": "abstract"}
        return subprocess.CompletedProcess(command, 0, json.dumps({"modelUsage": {"claude-opus-5-5": {}}, "result": json.dumps({"decisions": [decision]})}), "")
    d.queue_pass(answer)
    assert d.api.posts[0][0] == "/api/researches/res1/queue/s0/decision"
    assert d.api.posts[0][1]["row_token"] == "tok0"
    assert "claude-opus-5-5 medium; abstract" in d.api.posts[0][1]["note"]


def test_queue_mismatch_no_decisions_no_retry(tmp_path):
    d = queue_driver(tmp_path, 1)
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '{"modelUsage":{"other":{}},"result":"{}"}', "")
    with pytest.raises(l9.Refused, match="identity"):
        d.queue_pass(bad)
    assert not d.api.posts
    with pytest.raises(l9.Refused):
        d.queue_pass(queue_runner)


def test_quota_needs_explicit_notice_and_same_run(tmp_path):
    api = FakeAPI([run("paused"), run("paused"), run()])
    d = driver(tmp_path, api, reading("paused", "rate_limit"))
    notice = tmp_path / "return.json"
    l9.write(notice, {"run_id": "r1", "instruction": "bağlantı döndü", "at": 1000})
    assert d.poll(run("paused"), "lineage", returned=notice)["status"] == "completed"
    assert [p[0] for p in api.posts] == ["/api/runs/r1/resume"]
    assert d.state["run_records"]["r1"]["quota_resumes"] == 1


def test_session_ro_census(tmp_path):
    db = tmp_path / "library.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE model_sessions(id TEXT)")
        conn.execute("CREATE TABLE runs(id TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE run_steps(id TEXT)")
    before = db.read_bytes()
    assert l9.census(db) == {"sessions": [], "runs": [], "steps": []}
    assert db.read_bytes() == before


def test_quota_wait_excluded_but_counters_not_reset(tmp_path):
    api = FakeAPI([run("paused")])
    d = driver(tmp_path, api, reading("paused", "quota"))
    with pytest.raises(l9.Refused, match="coordinator"):
        d.poll(run("paused"), "fill")
    d.clock.now += 18000
    notice = tmp_path / "return.json"
    l9.write(notice, {"run_id": "r1", "instruction": "bağlantı döndü", "at": d.clock()})
    api.states = [run("paused"), run("paused"), run()]
    d.poll(run("paused"), "fill", returned=notice)
    assert d.state["excluded_wait_seconds"] == 18000
    assert d.state["run_records"]["r1"]["excluded_wait_seconds"] == 18000
    assert d.state["run_records"]["r1"]["baseline"] == 0
    assert d.state["preparation_started_at"] == 1000


@pytest.mark.parametrize("stage,limit", [("discovery", 3), ("lineage", 2)])
def test_quota_resume_limits(tmp_path, stage, limit):
    d = driver(tmp_path, FakeAPI([run("paused")]), reading("paused", "quota"))
    d.state["run_records"]["r1"] = {"stage": stage, "requested_at": 1000, "baseline": 0,
        "timeout_resumes": 0, "quota_resumes": limit, "excluded_wait_seconds": 0}
    with pytest.raises(l9.Refused, match="rights exhausted"):
        d.poll(run("paused"), stage)
    assert not d.api.posts


def test_timeout_wait_counts_toward_fill_clock(tmp_path):
    d = driver(tmp_path, FakeAPI([run("paused")]), reading("paused", "client_timeout"))
    d.state["run_records"]["r1"] = {"stage": "fill", "requested_at": -2100, "baseline": 0,
        "timeout_resumes": 0, "quota_resumes": 0, "excluded_wait_seconds": 0}
    with pytest.raises(l9.Refused, match="timeout wait"):
        d.poll(run("paused"), "fill")
    assert not d.api.posts
    assert d.clock() >= 1500


def test_started_sessions_prevent_resume(tmp_path):
    s = session(1)
    s["status"] = "started"
    d = driver(tmp_path, FakeAPI([run("paused")]), reading("paused", "client_timeout", [s]))
    d.clock.now += 3600
    with pytest.raises(l9.Refused, match="cap"):
        d.poll(run("paused"), "fill")
    assert not d.api.posts


def test_lineage_max_model_calls_stops(tmp_path):
    r = run("running")
    r["usage"]["model_calls"] = 10
    d = driver(tmp_path, FakeAPI([r]), reading("running"))
    with pytest.raises(l9.Refused, match="product cap"):
        d.poll(r, "lineage")
    assert d.api.posts[0][0].endswith("/cancel")


def test_gate_failure_after_completed_fill_blocks_second_attempt(tmp_path):
    d = driver(tmp_path)
    d.api.view["status"]["nodes_complete"] = 3
    path = tmp_path / "k0.json"
    l9.write(path, k0(d))
    gates = d.columns_fill(path)
    assert not gates["gates"]["K2"]["pass"]
    assert d.current()["preparation_complete"]
    with pytest.raises(l9.Refused, match="closed"):
        d.discover(new_attempt=True)


def test_second_incomplete_attempt_preserves_counters_and_records(tmp_path):
    d = driver(tmp_path)
    d.current()["incomplete"] = True
    old = deepcopy(d.current())
    baseline = d.state["baseline"][:]
    start = d.state["preparation_started_at"]
    d.api.states = [run("paused", pause="protocol_approval_needed"), run()]
    d.discover(new_attempt=True)
    assert len(d.state["attempts"]) == 2
    assert d.state["attempts"][0] == old
    assert d.state["baseline"] == baseline
    assert d.state["preparation_started_at"] == start
    with pytest.raises(l9.Refused, match="two preparation"):
        d.discover(new_attempt=True)


def test_lineage_pass_uses_l2_fingerprint_and_kit_snapshot(tmp_path, monkeypatch):
    d = driver(tmp_path)
    path = tmp_path / "k0.json"
    l9.write(path, k0(d))
    d.columns_fill(path)
    l2 = tmp_path / "l2.json"
    l9.write(l2, l9.load(tmp_path / "gates.json"))
    d.api.base = "http://127.0.0.1:8873"
    guards, snapshots = [], []
    d.api.guard = lambda out: guards.append(out)
    monkeypatch.setattr(l9, "reader_snapshot", lambda *args, **kwargs: snapshots.append(args))
    d.lineage(l2, l9.file_hash(l2))
    assert d.api.posts[-1][0].endswith("/lineage/runs")
    assert d.api.posts[-1][1] == {"preview_fingerprint": "a" * 64}
    assert snapshots[0][4] == l9.load(l9.L1)["G"]
    assert snapshots[0][2] == "r1"
    assert guards == [tmp_path]
    assert l9.load(tmp_path / "snapshot-closure.json")["observed_seconds"] == 120
    assert d.state["closed"]


def test_changed_preview_before_lineage_no_post(tmp_path):
    d = driver(tmp_path)
    path = tmp_path / "k0.json"
    l9.write(path, k0(d))
    d.columns_fill(path)
    l2 = tmp_path / "l2.json"
    l9.write(l2, l9.load(tmp_path / "gates.json"))
    d.api.preview["preview_fingerprint"] = "b" * 64
    before = len(d.api.posts)
    with pytest.raises(l9.Refused, match="changed"):
        d.lineage(l2, l9.file_hash(l2))
    assert len(d.api.posts) == before


def test_queue_no_stored_text_no_include(tmp_path):
    d = queue_driver(tmp_path, 1)
    with sqlite3.connect(d.db) as conn:
        conn.execute("DELETE FROM passages")
    def answer(command, **kwargs):
        decisions = [{"source_version_id": "s0", "decision": "include", "reason": "looks relevant", "reading_depth": "abstract"}]
        return subprocess.CompletedProcess(command, 0, json.dumps({"modelUsage": {"claude-opus-5-5": {}}, "result": json.dumps({"decisions": decisions})}), "")
    with pytest.raises(l9.Refused, match="textless"):
        d.queue_pass(answer)
    assert not d.api.posts


def test_queue_timeout_consumes_request(tmp_path):
    d = queue_driver(tmp_path, 1)
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 1800
        d.clock.now += 1800
        raise subprocess.TimeoutExpired(command, 1800)
    with pytest.raises(l9.Refused):
        d.queue_pass(timeout)
    assert d.state["queue_requests"][0]["elapsed_seconds"] == 1800
    assert not d.api.posts


def test_auto_fulltext_runs_observed_no_synthetic_start(tmp_path):
    d = driver(tmp_path)
    r = run()
    r.update(id="r2", kind="fulltext_adjudication")
    d.read = lambda _: {"sessions": [], "steps": [], "runs": [r]}
    d.api.states = [r]
    d.automatic_preparation()
    assert d.current()["automatic_preparation_complete"]
    assert d.state["run_records"]["r2"]["completed_at"] == 1000
    assert not d.api.posts


def test_8765_guard_failure_blocks_post(tmp_path):
    calls = []
    def transport(req):
        calls.append(req.method)
        return httpx.Response(200, json={"csrf_token": "hidden"})
    def guard(out):
        raise l9.Refused("port occupied")
    api = l9.API("http://127.0.0.1:8873", tmp_path, transport=httpx.MockTransport(transport), port_guard=guard)
    with pytest.raises(l9.Refused, match="port occupied"):
        api.post("/api/researches", {}, "key")
    assert calls == ["GET"]
    api.close()


def test_snapshot_real_synthetic_store_and_score(finished):
    library, run_record, out, view_path, _ = finished
    attempt = {"research_id": library.rid, "table_id": library.tid}
    before = l9.file_hash(db_path(library))
    l9.reader_snapshot(db_path(library), attempt, run_record["id"], l9.load(view_path), G, out,
                       {"attempts": [attempt], "run_records": {}})
    snapshot = l9.load(out / "snapshot.json")
    key = l9.load(out / "key.json")
    assert l9.file_hash(db_path(library)) == before
    assert snapshot["R14"]["value"] == 1 and snapshot["R14"]["denominator"] == 2
    assert snapshot["sample_size"] == 1 and snapshot["seed"] == 20261001
    assert "SYNTHETIC" in (out / "reader.md").read_text()
    answers = {"links": {i: {"support": "supports", "chronology_only": False} for i in key["links"]},
               "mentions": {i: "body" for i in key["mentions"]}}
    assert l9.KIT.score(snapshot, key, answers)["R12"]["denominator"] == 1


def test_snapshot_stopped_never_scores_partial_links(finished):
    library, run_record, out, view_path, _ = finished
    library.store.update_run(run_record["id"], status="paused", pause_reason="model_call_failed")
    library.conn.execute("PRAGMA wal_checkpoint(FULL)")
    attempt = {"research_id": library.rid, "table_id": library.tid}
    l9.reader_snapshot(db_path(library), attempt, run_record["id"], l9.load(view_path), G, out,
                       {"attempts": [attempt], "run_records": {}}, stopped="client_timeout twice")
    results = l9.load(out / "results.json")
    assert all(results[r]["status"] == "not_measurable" for r in ("R12", "R13", "R14", "R15"))
    assert not (out / "reader.md").exists()


def test_snapshot_refuses_unaccounted_paused_work(finished):
    library, run_record, out, view_path, _ = finished
    other = library.store.create_run(library.rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    library.store.update_run(other["id"], status="paused")
    library.conn.execute("PRAGMA wal_checkpoint(FULL)")
    attempt = {"research_id": library.rid, "table_id": library.tid}
    with pytest.raises(l9.Refused, match="snapshot ineligible"):
        l9.reader_snapshot(db_path(library), attempt, run_record["id"], l9.load(view_path), G, out,
                           {"attempts": [attempt], "run_records": {}})


def test_snapshot_preserves_identified_failed_prior_attempt(finished):
    library, run_record, out, view_path, _ = finished
    prior_id = library.store.create_research("SYNTHETIC previous attempt", "academic", "standard", [], "fake", "fake-model", "en")
    prior = library.store.create_run(prior_id, "discovery", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    library.store.update_run(prior["id"], status="paused", pause_reason="model_call_failed")
    library.conn.execute("PRAGMA wal_checkpoint(FULL)")
    attempt = {"research_id": library.rid, "table_id": library.tid}
    state = {"attempts": [{"research_id": prior_id, "incomplete": True}, attempt],
             "run_records": {prior["id"]: {"stop_reason": "second client_timeout"}}}
    l9.reader_snapshot(db_path(library), attempt, run_record["id"], l9.load(view_path), G, out, state)
    assert library.store.run(prior["id"])["status"] == "paused"
    checks = l9.load(out / "snapshot.json")["structure"]["intervention_audit"]
    assert checks["non_terminal_runs"] == 1
    assert checks["preserved_stopped_prior_runs"][0]["id"] == prior["id"]


def test_status_read_only_state_and_no_posts(tmp_path, monkeypatch, capsys):
    d = driver(tmp_path)
    before = l9.file_hash(tmp_path / "state.json")
    d.api.close = lambda: None
    class StatusAPI:
        def __new__(cls, *args):
            return d.api
    monkeypatch.setattr(l9, "API", StatusAPI)
    monkeypatch.setattr(l9, "census", lambda _: reading())
    assert l9.main(["status", "--out", str(tmp_path), "--db", str(d.db)]) == 0
    assert l9.file_hash(tmp_path / "state.json") == before
    assert not d.api.posts
    assert json.loads(capsys.readouterr().out)["state"]["attempts"][0]["research_id"] == "res1"
