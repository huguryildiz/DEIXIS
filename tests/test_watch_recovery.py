"""Transaction failures and interruptions never publish an unfinished check."""

import asyncio
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import httpx
import pytest

from deixis.providers import common
from deixis.storage import db
from deixis.workflow.watch import run as watch_run
from deixis.workflow.watch import check as policy
from deixis.workflow.watch.store import WatchStore
from tests.watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, page, work, rows, add_included


class Crash(BaseException):
    pass


@pytest.mark.parametrize("failure", ["inside", "commit"])
def test_completion_rolls_back_on_exception_or_commit_failure_worker_can_fail(api, monkeypatch, failure):
    first = create(api); turn(api)
    baseline = api.watches.watch(api.rid, first["watch_id"])["baseline_json"]
    seen_before = rows(api.conn, ["watch_seen", "watch_seen_alias", "watch_items"])
    api.state.payload = page(work("NEW"))
    second = now_check(api, first["watch_id"])
    if failure == "inside":
        original = WatchStore._announce
        def fail(self, *args):
            original(self, *args)
            raise RuntimeError("SYNTHETIC completion failed after announcement writes")
        monkeypatch.setattr(WatchStore, "_announce", fail)
    else:
        class FailCommit:
            def __init__(self, conn):
                self.conn, self.failed = conn, False
            def __getattr__(self, name):
                return getattr(self.conn, name)
            def execute(self, sql, args=()):
                if sql == "COMMIT" and not self.failed and self.conn.execute(
                    "SELECT 1 FROM run_steps WHERE run_id=? AND operation_key='watch_complete' AND status='succeeded'", (second["run_id"],)).fetchone():
                    self.failed = True
                    raise sqlite3.OperationalError("SYNTHETIC COMMIT failed")
                return self.conn.execute(sql, args)
        monkeypatch.setattr(api.store, "conn", FailCommit(api.conn))
    turn(api)
    assert api.store.run(second["run_id"])["status"] == "failed"
    assert api.store.run(second["run_id"])["pause_reason"] == "internal_error"
    assert rows(api.conn, ["watch_seen", "watch_seen_alias", "watch_items"]) == seen_before
    assert api.watches.watch(api.rid, first["watch_id"])["baseline_json"] == baseline
    assert api.watches.check(api.rid, second["check_id"])["completed_at"] is None
    assert api.store.existing_step(second["run_id"], "watch_complete") is None
    assert not api.conn.in_transaction
    assert api.client.post(f"/api/runs/{second['run_id']}/resume").status_code == 409


def test_recovery_after_reads_before_completion_resumes_once_without_send(api, monkeypatch):
    first = create(api); turn(api)
    api.state.payload = page(work("NEW"))
    second = now_check(api, first["watch_id"])
    original = WatchStore.complete_check
    def crash(*args, **kwargs):
        raise Crash("SYNTHETIC process interruption after reads")
    monkeypatch.setattr(WatchStore, "complete_check", crash)
    with pytest.raises(Crash): turn(api)
    assert not api.watches.items(api.rid)
    assert api.store.run(second["run_id"])["status"] == "running"
    sent = len(api.sent); usage = api.store.run(second["run_id"])["usage"]
    api.app.state.worker.recover()
    assert read(api, second)["state"] == "paused" and read(api, second)["pause_reason"] == "backend_restarted"
    monkeypatch.setattr(WatchStore, "complete_check", original)
    control(api, second, "resume"); turn(api)
    assert read(api, second)["state"] == "succeeded" and len(api.watches.items(api.rid)) == 1
    assert len(api.sent) == sent and api.store.run(second["run_id"])["usage"] == usage
    before = rows(api.conn)
    api.client.portal.call(api.app.state.worker.flow.execute, second["run_id"])
    assert rows(api.conn) == before and len(api.sent) == sent


def test_payload_file_write_failure_publishes_no_read_or_succeeded_page(api, monkeypatch):
    command = create(api)
    original = Path.write_bytes
    def fail(path, content):
        if path.parent == api.settings.payloads_dir:
            raise OSError("SYNTHETIC payload write refused")
        return original(path, content)
    monkeypatch.setattr(Path, "write_bytes", fail)
    turn(api)
    assert read(api, command)["state"] == "failed"
    assert not api.watches.reads(api.watches.check(api.rid, command["check_id"]))
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 0
    assert api.store.existing_step(command["run_id"], "watch:0:page:1")["status"] == "running"


def test_resumed_check_refuses_changed_adapter_before_using_stored_cursor(api, monkeypatch):
    from dataclasses import replace
    from deixis.providers import registry
    api.state.payload = page(work(), cursor="next")
    command = create(api)
    original = WatchStore.record_read
    def crash(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise Crash("SYNTHETIC interruption after first cursor page")
    monkeypatch.setattr(WatchStore, "record_read", crash)
    with pytest.raises(Crash): turn(api)
    api.app.state.worker.recover()
    monkeypatch.setattr(WatchStore, "record_read", original)
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(registry.CONNECTORS["openalex"], adapter_revision=4))
    control(api, command, "resume"); turn(api)
    assert read(api, command)["failure_reason"] == "adapter_revision_changed"
    assert len(api.sent) == 1 and api.store.run(command["run_id"])["usage"]["provider_requests"] == 1
    assert not api.conn.execute("SELECT 1 FROM watch_seen").fetchone()
    assert not api.watches.items(api.rid)


@pytest.mark.parametrize("change,reason", [("disable", "watch_disabled"), ("scope", "scope_revised"),
    ("protocol", "watch_protocol_changed"), ("trash", "research_unavailable"), ("state_version", "watch_state_changed")])
def test_live_state_change_while_last_request_held_publishes_nothing(api, change, reason):
    command = create(api)
    entered = threading.Event(); release = threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.001)
        return httpx.Response(200, json=page(work("NEW")))
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        if change == "disable":
            response = api.client.post(api.url + f"/{command['watch_id']}/disable", json={"expected_state_version": 1},
                headers={"Idempotency-Key": "held-disable"})
            assert response.status_code == 200
        elif change == "scope":
            api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC revised", None)
        elif change == "protocol":
            api.store.freeze_protocol(api.rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "changed"}]}, "SYNTHETIC changed")
        elif change == "trash":
            # The ordinary trash route correctly refuses active work; a committed external revision is simulated.
            api.conn.execute("UPDATE researches SET trashed_at=? WHERE id=?", (db.now(), api.rid))
        else:
            api.conn.execute("UPDATE watches SET state_version=state_version+1 WHERE id=?", (command["watch_id"],))
    finally:
        release.set()
    future.result(5)
    result = api.store.run(command["run_id"])
    assert result["status"] == ("failed" if change == "state_version" else "cancelled") and result["pause_reason"] == reason
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 0
    assert api.conn.execute("SELECT count(*) FROM watch_items").fetchone()[0] == 0
    assert api.conn.execute("SELECT count(*) FROM watch_reads").fetchone()[0] == 1
    assert api.conn.execute("SELECT completed_at FROM watch_checks").fetchone()[0] is None


def test_citing_watch_ignores_protocol_revision_on_research_that_has_protocol(api):
    add_included(api, "SEED")
    command = create(api, "citing_works")
    def revise(request):
        api.store.freeze_protocol(api.rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "changed"}]}, "SYNTHETIC changed")
        return httpx.Response(200, json=page(work("NEW")))
    api.state.handler = revise
    turn(api)
    assert read(api, command)["state"] == "succeeded"
    assert api.watches.watch(api.rid, command["watch_id"])["protocol_record_id"] is None


@pytest.mark.parametrize("change", ["disable", "scope", "pause", "cancel", "protocol"])
def test_gate_refuses_next_internal_rate_limit_send_after_held_change(api, monkeypatch, change):
    command = create(api)
    entered = threading.Event(); release = threading.Event()
    async def held(request):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.001)
        return httpx.Response(429, headers={"retry-after": "0"})
    api.state.handler = held
    future = api.client.portal.start_task_soon(api.app.state.worker._turn)
    assert entered.wait(5)
    try:
        if change == "disable":
            api.watches.disable(api.rid, command["watch_id"], {"expected_state_version": 1}, "rate-disable")
        elif change == "scope":
            api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC changed", None)
        elif change == "protocol":
            api.store.freeze_protocol(api.rid, 1, {"compiled_queries": []}, "SYNTHETIC changed")
        else:
            control(api, command, change)
    finally:
        release.set()
    future.result(5)
    run = api.store.run(command["run_id"])
    assert len(api.sent) == run["usage"]["provider_requests"] == 1
    assert run["status"] == ("paused" if change == "pause" else "cancelled")
    assert not api.watches.items(api.rid)
    assert api.watches.reads(api.watches.check(api.rid, command["check_id"]))[0]["status"] in ("stopped", "watch_disabled", "watch_protocol_changed")


def test_internal_rate_limit_resend_budget_gate_even_when_adapter_hint_ignored(api, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    original = common.send
    async def ignore_hint(*args, **kwargs):
        kwargs["max_rate_limit_retries"] = 2
        return await original(*args, **kwargs)
    monkeypatch.setattr(registry_openalex(), "send", ignore_hint)
    api.state.status = 429
    command = create(api); turn(api)
    assert len(api.sent) == api.store.run(command["run_id"])["usage"]["provider_requests"] == 1
    assert "budget_deferred" in read(api, command)["partial_reasons"]


def registry_openalex():
    from deixis.providers import openalex
    return openalex


def test_deadline_between_two_internal_sends_and_resume_keeps_deadline(api, monkeypatch):
    command = create(api)
    frozen = api.store.run(command["run_id"])["target"]["deadline_at"]
    clock = ["2026-01-01T00:00:00+00:00"]
    monkeypatch.setattr(watch_run, "now", lambda: clock[0])
    def first(request):
        clock[0] = "2099-01-01T00:00:00+00:00"
        return httpx.Response(429, headers={"retry-after": "0"})
    api.state.handler = first
    turn(api)
    assert len(api.sent) == 1 and "deadline_deferred" in read(api, command)["partial_reasons"]
    assert api.store.run(command["run_id"])["target"]["deadline_at"] == frozen


def test_crash_between_pubmed_internal_sends_keeps_actual_reservation_and_unknown_page(tmp_path, monkeypatch):
    from deixis.providers import pubmed
    original = pubmed.send
    async def between(client, url, *args, **kwargs):
        if url == pubmed.FETCH_URL:
            raise Crash("SYNTHETIC interruption between ESearch and EFetch")
        return await original(client, url, *args, **kwargs)
    monkeypatch.setattr(pubmed, "send", between)
    with watch_api(tmp_path, queries=[{"provider_id": "pubmed", "query_text": "SYNTHETIC"}]) as api:
        api.state.handler = lambda request: httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["17"]}})
        command = create(api)
        with pytest.raises(Crash): turn(api)
        assert api.store.run(command["run_id"])["usage"]["provider_requests"] == len(api.sent) == 1
        api.app.state.worker.recover()
        assert read(api, command)["state"] == "paused" and read(api, command)["outcome_unknown"]
        assert api.client.post(api.url + f"/{command['watch_id']}/checks", json={"expected_state_version": 1},
            headers={"Idempotency-Key": "unknown-new"}).json()["code"] == "check_paused"
        control(api, command, "resume"); turn(api)
        assert len(api.sent) == 1 and read(api, command)["state"] == "failed"
        assert "outcome_unknown" in read(api, command)["partial_reasons"]
        assert api.store.run(command["run_id"])["usage"]["provider_requests"] == 1


def test_paused_resume_past_deadline_sends_nothing_and_keeps_usage(api, monkeypatch):
    command = create(api)
    frozen = api.store.run(command["run_id"])["target"]["deadline_at"]
    def pause(request):
        api.store.update_run(command["run_id"], status="pause_requested")
        return httpx.Response(200, json=page(work(), cursor="remaining"))
    api.state.handler = pause
    turn(api)
    assert read(api, command)["state"] == "paused"
    usage = api.store.run(command["run_id"])["usage"]
    monkeypatch.setattr(watch_run, "now", lambda: "2099-01-01T00:00:00+00:00")
    control(api, command, "resume"); turn(api)
    assert len(api.sent) == 1 and api.store.run(command["run_id"])["usage"] == usage
    assert api.store.run(command["run_id"])["target"]["deadline_at"] == frozen
    assert "deadline_deferred" in read(api, command)["partial_reasons"]


def test_pause_during_last_page_completes_and_does_not_claim_more_work(api):
    command = create(api)
    def pause(request):
        api.store.update_run(command["run_id"], status="pause_requested")
        return httpx.Response(200, json=page(work()))
    api.state.handler = pause
    turn(api)
    assert read(api, command)["state"] == "succeeded" and len(api.sent) == 1


def test_run_states_through_pause_resume_cancel_recovery_and_worker_error(api):
    command = create(api)
    assert read(api, command)["state"] == "queued"
    api.store.update_run(command["run_id"], status="running")
    assert read(api, command)["state"] == "running"
    control(api, command, "pause")
    assert read(api, command)["state"] == "pause_requested"
    api.client.portal.call(api.app.state.worker.flow.execute, command["run_id"])
    assert read(api, command)["state"] == "paused"
    control(api, command, "resume")
    assert read(api, command)["state"] == "queued"
    turn(api)
    assert read(api, command)["state"] == "succeeded"
    second = now_check(api, command["watch_id"])
    control(api, second, "cancel")
    assert read(api, second)["state"] == "cancelled"
