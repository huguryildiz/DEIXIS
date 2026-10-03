"""SIGKILL/restart on test-owned libraries and OS-selected loopback ports."""

import json
from pathlib import Path
import sqlite3
import sys
import time

import httpx
import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from tests.process.p9_harness import (ServerProc, harness, wait_for, wait_run, rows, count, integrity_check, foreign_key_check)
from tests.watch_helpers import page, work

pytestmark = pytest.mark.process
DRIVER = Path(__file__).with_name("watch_driver.py")


class WatchServerProc(ServerProc):
    def start(self, timeout=30):
        self.argv = [sys.executable, str(DRIVER), "--data-dir", str(self.data_dir), "--port", str(self.port)]
        assert Path(self.argv[1]).name == "watch_driver.py"
        self.proc = self.h.popen(self.argv, self.env, self.log_path, start_new_session=True)
        self.started_at = time.monotonic()
        base = f"http://127.0.0.1:{self.port}"
        deadline = self.started_at + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(f"watch server exited {self.proc.returncode}:\n{self.log_text()[-2000:]}")
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200: break
            except httpx.HTTPError:
                time.sleep(.05)
        else:
            pytest.fail(f"watch server not ready after {timeout}s:\n{self.log_text()[-2000:]}")
        self.client = httpx.Client(base_url=base, timeout=10)
        self.client.headers["x-deixis-csrf"] = self.client.get("/api/session").json()["csrf_token"]


def start(harness, data, answers, name, **controls):
    server = WatchServerProc(harness, data, name, {"P9_ANSWERS": str(answers), "P9_TEMP_ROOT": str(harness.tmp), **controls})
    harness.servers.append(server); server.start()
    assert "watch_driver.py" in server.proc.args[1]
    return server


def prepare(harness, tmp_path):
    data = tmp_path / "library"
    conn = db.connect(data / "library.sqlite"); db.migrate(conn)
    main = Store(conn)
    rid = main.create_research("SYNTHETIC process watch", "academic", "standard", ["openalex"], "fake", "fake-model", "en", search_workflow="sw")
    main.freeze_protocol(rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC frozen process query"}]})
    conn.close()
    answers = tmp_path / "answers.json"; answers.write_text(json.dumps(page(work("BASE"))))
    server = start(harness, data, answers, "baseline")
    response = server.client.post(f"/api/researches/{rid}/watches", json={"kind": "protocol_queries", "mode": "interval",
        "interval_days": 1, "catch_up": True, "expected_scope_revision": 1}, headers={"Idempotency-Key": "process-enable"})
    assert response.status_code == 201, response.text
    command = response.json()
    assert wait_run(server.client, rid, command["run_id"], seconds=20)["status"] == "completed"
    assert count(data, "watch_items") == 0
    server.kill9()
    # A direct SQL edit to this killed process's temporary library simulates a computer closed across due times.
    with sqlite3.connect(data / "library.sqlite") as conn:
        conn.execute("UPDATE watches SET next_due_at='2026-01-01T00:00:00+00:00' WHERE id=?", (command["watch_id"],))
    answers.write_text(json.dumps(page(work("BASE"), work("NEW"))))
    return data, rid, command, answers, server


def catchup(data):
    found = rows(data, "SELECT * FROM watch_checks WHERE trigger='catch_up'")
    return dict(found[0]) if found else None


def checked(server, data, rid, state="completed"):
    check = wait_for(lambda: catchup(data), 20, "catch-up queue")
    run = wait_run(server.client, rid, check["run_id"], statuses=(state,), seconds=20)
    assert run["status"] == state
    return check, run


def first_tick(server):
    return wait_for(lambda: next((event for event in server.calls()
        if event["kind"] == "tick" and event["pid"] == server.proc.pid), None), 20, "restarted process first tick")


def safe(servers, data, started, record_property):
    for server in servers:
        server.no_network()
        assert not any(c["kind"] == "model" for c in server.calls())
    assert integrity_check(data) == "ok" and not foreign_key_check(data)
    elapsed = time.monotonic() - started
    record_property("wall_seconds", elapsed)
    print(f"watch process wall_seconds={elapsed:.3f}")


def test_closed_across_due_period_one_catchup_one_item(harness, tmp_path, record_property):  # 14a
    started = time.monotonic()
    data, rid, first, answers, baseline = prepare(harness, tmp_path)
    restarted = start(harness, data, answers, "closed-restart")
    tick = first_tick(restarted)
    assert tick["recorded"] == tick["queued"] == 1
    check, run = checked(restarted, data, rid)
    assert count(data, "watch_checks") == 2 and count(data, "watch_gaps") == 1 and count(data, "watch_items") == 1
    view = restarted.client.get(f"/api/researches/{rid}/watches/{first['watch_id']}/checks/{check['id']}").json()
    assert view["gap"]["missed_periods"] >= 1 and view["schedule"]["gap_id"]
    safe([baseline, restarted], data, started, record_property)


def test_kill_during_catchup_request_recovery_unknown_not_resent_on_resume(harness, tmp_path, record_property):  # 14b
    started = time.monotonic()
    data, rid, first, answers, baseline = prepare(harness, tmp_path)
    held = start(harness, data, answers, "request-held", P9_HOLD_REQUEST="1")
    held.wait_held("request", seconds=20)
    check = catchup(data)
    usage = rows(data, "SELECT usage_json FROM runs WHERE id=?", (check["run_id"],))[0][0]
    assert json.loads(usage)["provider_requests"] == 1
    held.kill9()
    restarted = start(harness, data, answers, "request-restart")
    recovered, run = checked(restarted, data, rid, "paused")
    assert run["pause_reason"] == "backend_restarted" and count(data, "watch_checks") == 2
    assert count(data, "run_steps", "run_id=? AND status='outcome_unknown'", (check["run_id"],)) == 1
    assert count(data, "watch_items") == 0 and run["usage"] == json.loads(usage)
    assert restarted.client.post(f"/api/runs/{check['run_id']}/resume").status_code == 200
    ended = wait_run(restarted.client, rid, check["run_id"], seconds=20)
    assert ended["status"] == "failed" and ended["pause_reason"] == "no_provider_read" and ended["usage"] == json.loads(usage)
    assert not any(c["kind"] == "provider" for c in restarted.calls()) and count(data, "watch_items") == 0
    assert recovered["id"] == check["id"]
    safe([baseline, held, restarted], data, started, record_property)


def test_kill_after_read_before_completion_resume_publishes_once_without_request(harness, tmp_path, record_property):  # 14c
    started = time.monotonic()
    data, rid, first, answers, baseline = prepare(harness, tmp_path)
    ready = tmp_path / "ready"
    held = start(harness, data, answers, "completion-held", P9_HOLD_COMPLETION="1", P9_READY_FILE=str(ready))
    ready.touch()
    held.wait_held("completion", seconds=20)
    check = catchup(data)
    assert count(data, "watch_reads", "check_id=?", (check["id"],)) == 1 and count(data, "watch_items") == 0
    held.kill9()
    restarted = start(harness, data, answers, "completion-restart")
    recovered, run = checked(restarted, data, rid, "paused")
    assert count(data, "watch_items") == 0 and run["pause_reason"] == "backend_restarted"
    response = restarted.client.post(f"/api/runs/{check['run_id']}/resume")
    assert response.status_code == 200, response.text
    assert wait_run(restarted.client, rid, check["run_id"], seconds=20)["status"] == "completed"
    assert not any(c["kind"] == "provider" for c in restarted.calls())
    assert count(data, "watch_items") == 1 and count(data, "watch_checks") == 2 and recovered["id"] == check["id"]
    safe([baseline, held, restarted], data, started, record_property)


def test_further_restart_same_answers_before_next_due_no_duplicate(harness, tmp_path, record_property):  # 14d
    started = time.monotonic()
    data, rid, first, answers, baseline = prepare(harness, tmp_path)
    once = start(harness, data, answers, "first-catchup")
    checked(once, data, rid)
    before = {t: [tuple(r) for r in rows(data, f"SELECT * FROM {t} ORDER BY id")] for t in ("watch_checks", "watch_gaps", "watch_items")}
    once.kill9()
    twice = start(harness, data, answers, "second-restart")
    assert twice.health()["worker"] == "owner"
    tick = first_tick(twice)
    assert tick["recorded"] == tick["queued"] == 0
    assert {t: [tuple(r) for r in rows(data, f"SELECT * FROM {t} ORDER BY id")] for t in before} == before
    assert not any(c["kind"] == "provider" for c in twice.calls())
    safe([baseline, once, twice], data, started, record_property)
