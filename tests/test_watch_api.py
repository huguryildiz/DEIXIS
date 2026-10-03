"""Routes, idempotency, atomic commands, lifecycle separation, backup and purge."""

import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import threading

import httpx
import pytest

from deixis.config import Settings
from deixis.providers import registry
from deixis.storage import backup, db
from deixis.workflow.watch.store import WatchRefusal, WatchStore, TABLES
from tests.watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, page, work, rows, hashes, add_included


def version_body(api, wid):
    return {"expected_state_version": api.watches.watch(api.rid, wid)["state_version"]}


def post(api, path, body, key="SYNTHETIC-command"):
    return api.client.post(path, json=body, headers={"Idempotency-Key": key})


def test_every_watch_route_has_a_coroutine_endpoint(api):
    routes = [route for route in api.app.routes
              if getattr(getattr(route, "endpoint", None), "__module__", None) == "deixis.api.watch_routes"]
    assert len(routes) == 9
    assert all(inspect.iscoroutinefunction(route.endpoint) for route in routes)


def test_create_check_and_dismiss_store_calls_use_the_app_event_loop_thread(api, monkeypatch):
    async def loop_thread():
        return threading.get_ident()
    expected_thread = api.client.portal.call(loop_thread)
    observed = []
    def wrap(name):
        original = getattr(WatchStore, name)
        def called(*args, **kwargs):
            observed.append((name, threading.get_ident()))
            return original(*args, **kwargs)
        monkeypatch.setattr(WatchStore, name, called)
    for name in ("create", "check_now", "dismiss"):
        wrap(name)
    api.state.payload = page()
    first = create(api); turn(api)
    api.state.payload = page(work("NEW"))
    now_check(api, first["watch_id"]); turn(api)
    item = api.watches.items(api.rid)[0]
    response = post(api, f"/api/researches/{api.rid}/watch-items/{item['id']}/dismiss",
                    {"expected_status": "new", "reason": "SYNTHETIC reason"})
    assert response.status_code == 200, response.text
    assert observed == [(name, expected_thread) for name in ("create", "check_now", "dismiss")]


def test_watch_query_and_citing_pages_inherit_the_app_client_headers_like_discovery(tmp_path):
    headers = {"User-Agent": "SYNTHETIC-DEIXIS-watch-header-regression", "X-Synthetic-Client": "app-default"}
    with watch_api(tmp_path, headers=headers) as api:
        flow = api.app.state.worker.flow
        async def discovery_read():
            run = api.store.create_run(api.rid, "discovery", {}, "SYNTHETIC-header-discovery")
            outcome = await flow._send_search(run["id"], registry.CONNECTORS["openalex"],
                                              {"query_text": "SYNTHETIC query"}, 100)
            assert outcome.outcome.status == "completed"
            api.store.update_run(run["id"], status="cancelled")
        api.client.portal.call(discovery_read)
        query = create(api); turn(api)
        assert read(api, query)["state"] == "succeeded"
        add_included(api, "WSEED")
        citing = create(api, "citing_works"); turn(api)
        assert read(api, citing)["state"] == "succeeded"
        assert len(api.sent) == 3
        discovery_request, query_request, citing_request = api.sent
        assert "search.title_and_abstract" in query_request.url.params
        assert citing_request.url.params["filter"] == "cites:WSEED"
        for request in api.sent:
            for name, value in headers.items():
                assert request.headers[name] == value == discovery_request.headers[name]
            assert request.extensions["timeout"] == discovery_request.extensions["timeout"]


def test_preview_read_only_all_tables_and_research_view_run_states(api):
    before = rows(api.conn)
    denied = []
    def guard(action, table, column, database, trigger):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            denied.append((action, table, column)); return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    api.conn.set_authorizer(guard)
    try:
        response = post(api, api.url + "/preview", {"kind": "protocol_queries"})
        assert response.status_code == 200 and not denied and rows(api.conn) == before
        assert response.json()["notice"] == "DEIXIS checks only while it is running."
        assert response.json()["units"][0]["display_name"] == "OpenAlex"
    finally:
        api.conn.set_authorizer(None)
    command = create(api)
    for status in ("queued", "running", "completed"):
        api.store.update_run(command["run_id"], status=status)
        response = api.client.get(f"/api/researches/{api.rid}")
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ["create", "check", "disable", "rebind", "dismiss"])
def test_command_replay_before_expected_revision_after_later_changes_and_changed_content(api, monkeypatch, action):
    key = "SYNTHETIC-content-" + action
    if action == "create":
        body = {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}
        url = api.url
        original = post(api, url, body, key).json()
        turn(api)
        # A later check changes state; disabling changes availability.
        later = now_check(api, original["watch_id"]); turn(api)
        api.watches.disable(api.rid, original["watch_id"], version_body(api, original["watch_id"]), "later-disable")
        changed = body | {"expected_scope_revision": 2}
    else:
        api.state.payload = page()
        first = create(api); turn(api)
        wid = first["watch_id"]
        if action == "dismiss":
            api.state.payload = page(work("NEW"))
            later = now_check(api, wid); turn(api)
            item = api.watches.items(api.rid)[0]
            url = f"/api/researches/{api.rid}/watch-items/{item['id']}/dismiss"
            body = {"expected_status": "new", "reason": "SYNTHETIC reason"}
            changed = body | {"reason": "SYNTHETIC changed reason"}
        else:
            url = api.url + f"/{wid}/" + {"check": "checks", "disable": "disable", "rebind": "rebind"}[action]
            body = version_body(api, wid)
            changed = body | {"expected_state_version": body["expected_state_version"] + 1}
        response = post(api, url, body, key)
        assert response.status_code in (200,201,202), response.text
        original = response.json()
        if action in ("check", "rebind"):
            turn(api)
            api.watches.disable(api.rid, original["watch_id"], version_body(api, original["watch_id"]), "later-disable")
        elif action in ("disable", "dismiss"):
            api.watches.rebind(api.rid, wid, version_body(api, wid), "later-rebind")
    before = rows(api.conn); sent = len(api.sent)
    monkeypatch.setattr(api.app.state.worker, "wake", lambda: pytest.fail("replay woke the worker"))
    replay = post(api, url, body, key)
    assert replay.status_code in (200,201,202), replay.text
    assert replay.json()["replayed"] is True and original["replayed"] is False
    for name in ("watch_id", "check_id", "run_id", "item_id"):
        if name in original:
            assert replay.json()[name] == original[name]
    assert rows(api.conn) == before and len(api.sent) == sent
    if "watch" in replay.json():
        assert replay.json()["watch"]["state_version"] == api.watches.watch(api.rid, original["watch_id"])["state_version"]
    mismatch = post(api, url, changed, key)
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "idempotency_key_reused"


def test_create_replay_keeps_first_ids_when_a_later_check_clock_is_earlier(api, monkeypatch):
    from deixis.workflow.watch import store as watch_store
    body = {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}
    first = post(api, api.url, body, "clock-replay").json(); turn(api)
    assert api.store.run(first["run_id"])["target"]["request_hash"] == api.watches.watch(api.rid, first["watch_id"])["request_hash"]
    monkeypatch.setattr(watch_store, "now", lambda: "2026-01-01T00:00:00+00:00")
    second = now_check(api, first["watch_id"])
    assert second["check_id"] != first["check_id"]
    replay = post(api, api.url, body, "clock-replay").json()
    assert replay["replayed"] and (replay["check_id"], replay["run_id"]) == (first["check_id"], first["run_id"])


def test_queue_transaction_failure_after_create_run_rolls_back_everything(api, monkeypatch):
    original = api.store.create_run
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC after create_run")
    monkeypatch.setattr(api.store, "create_run", fail)
    before = rows(api.conn)
    with pytest.raises(RuntimeError):
        api.watches.create(api.rid, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}, "rollback-create")
    assert rows(api.conn) == before and not api.conn.in_transaction


def test_route_refusals_revision_active_paused_old_scope_and_strict_bodies(api):
    body = {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}
    assert post(api, api.url, body | {"unexpected": True}).status_code == 422
    response = api.client.post(api.url, json=body)
    assert response.status_code == 422
    for key in ("", "x" * 201):
        assert post(api, api.url, body, key).status_code == 422
    assert post(api, api.url, body | {"mode": "interval"}).json()["code"] == "interval_not_built"
    assert post(api, api.url, body | {"expected_scope_revision": 2}).json()["code"] == "scope_changed"
    command = create(api)
    assert post(api, api.url, body | {"kind": "citing_works"}).json()["code"] == "run_active"
    url = api.url + f"/{command['watch_id']}/checks"
    assert post(api, url, {"expected_state_version": 99}).json()["code"] == "watch_changed"
    api.store.update_run(command["run_id"], status="paused", pause_reason="SYNTHETIC")
    assert post(api, url, version_body(api, command["watch_id"])).json()["code"] == "check_paused"
    control(api, command, "cancel")
    api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC revised", None)
    assert post(api, url, version_body(api, command["watch_id"])).json()["code"] == "watch_follows_old_scope"
    listing = api.client.get(api.url).json()
    assert listing[0]["follows_old_scope"] and listing[0]["follows_old_scope_reason"] == "scope_revised"


@pytest.mark.parametrize("legacy", [True, False])
def test_legacy_and_missing_protocol_refused(tmp_path, legacy):
    with watch_api(tmp_path, legacy=legacy) as api:
        if not legacy:
            api.conn.execute("INSERT INTO scope_revisions SELECT " + ",".join(
                "2" if r[1] == "revision" else '"'+r[1]+'"' for r in api.conn.execute("PRAGMA table_info(scope_revisions)")) + " FROM scope_revisions")
            api.conn.execute("UPDATE researches SET current_scope_revision=2")
        response = post(api, api.url, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 2 if not legacy else 1})
        assert response.status_code == (409 if legacy else 422)
        assert response.json().get("code", response.json()["detail"]) == ("legacy_research_read_only" if legacy else "no_protocol")


def test_unknown_trashed_foreign_research_404_and_csrf(api):
    first = create(api); turn(api)
    wrong = api.url.replace(api.rid, "res_unknown")
    assert api.client.get(wrong).status_code == 404
    assert post(api, wrong + "/preview", {"kind": "citing_works"}).status_code == 404
    # Every mutation passes through the existing double-submit middleware.
    assert api.client.post(api.url, json={"kind": "citing_works", "expected_scope_revision": 1},
                           headers={"x-deixis-csrf": "wrong", "Idempotency-Key": "csrf"}).status_code == 403
    api.store.trash_research(api.rid)
    assert api.client.get(api.url).status_code == 404
    assert post(api, api.url + "/preview", {"kind": "citing_works"}).status_code == 404
    assert post(api, api.url + f"/{first['watch_id']}/checks", version_body_raw(first)).status_code == 404


def version_body_raw(command):
    return {"expected_state_version": command["watch"]["state_version"]}


def test_dismiss_wrong_status_and_long_reason_refused(api):
    api.state.payload = page()
    first = create(api); turn(api)
    api.state.payload = page(work("NEW"))
    now_check(api, first["watch_id"]); turn(api)
    item = api.watches.items(api.rid)[0]
    url = f"/api/researches/{api.rid}/watch-items/{item['id']}/dismiss"
    assert post(api, url, {"expected_status": "dismissed"}).json()["code"] == "item_changed"
    assert post(api, url, {"expected_status": "new", "reason": "x"*501}).status_code == 422
    assert post(api, url, {"expected_status": "new"}, "dismiss-first").status_code == 200
    assert post(api, url, {"expected_status": "new"}, "dismiss-other").json()["code"] == "item_changed"


@pytest.mark.parametrize("lifecycle", ["baseline_and_new", "failed", "cancelled"])
def test_real_worker_lifecycle_authorizer_every_other_table_and_view_counts_unchanged(api, lifecycle):
    allowed = {"runs", "run_steps", "events", *TABLES, "researches", "worker_owner", "sqlite_sequence"}
    before_view = api.client.get(f"/api/researches/{api.rid}").json()
    tables = {r[0] for r in api.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    protected = sorted(tables-allowed)
    before = hashes(api.conn, protected)
    narrow = hashes(api.conn, ["researches", "worker_owner"], {"researches": {"updated_at"}, "worker_owner": {"heartbeat_at"}})
    denied = []; writes = []
    def guard(action, table, column, database, trigger):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            writes.append((action, table, column))
            permitted = table in allowed
            if table in ("researches", "worker_owner"):
                permitted = action == sqlite3.SQLITE_UPDATE and column == {"researches": "updated_at", "worker_owner": "heartbeat_at"}[table]
            if not permitted:
                denied.append((action, table, column, trigger)); return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    api.conn.set_authorizer(guard)
    try:
        if lifecycle == "failed":
            api.state.status = 500
        command = create(api)
        if lifecycle == "cancelled":
            control(api, command, "cancel")
            assert read(api, command)["state"] == "cancelled"
        else:
            turn(api)
            if lifecycle == "failed":
                assert read(api, command)["state"] == "failed" and read(api, command)["failure_reason"] == "no_provider_read"
            else:
                assert api.store.run(command["run_id"])["status"] == "completed" and not api.watches.items(api.rid)
                api.state.payload = page(work(), work("NEW"))
                command = now_check(api, command["watch_id"]); turn(api)
                assert api.store.run(command["run_id"])["status"] == "completed" and len(api.watches.items(api.rid)) == 1
            assert read(api, command)["counts"]["added"] == 0
        assert not denied, denied
        assert hashes(api.conn, protected) == before
        assert hashes(api.conn, ["researches", "worker_owner"], {"researches": {"updated_at"}, "worker_owner": {"heartbeat_at"}}) == narrow
        after_view = api.client.get(f"/api/researches/{api.rid}").json()
        count_keys = {k for k in before_view if "count" in k or k in ("counts", "sources", "corpus", "candidates")}
        assert count_keys, before_view.keys()
        assert {k: before_view[k] for k in count_keys} == {k: after_view[k] for k in count_keys}
        assert api.conn.execute("SELECT count(*) FROM person_pdf_requests WHERE status='waiting'").fetchone()[0] == 0
        assert writes and {table for _, table, _ in writes} <= allowed
        assert not any(action == sqlite3.SQLITE_DELETE for action, _, _ in writes)
    finally:
        api.conn.set_authorizer(None)


def two_checks(api):
    first = create(api); turn(api)
    api.state.payload = page(work(), work("NEW"))
    second = now_check(api, first["watch_id"]); turn(api)
    return first, second


def test_backup_restore_six_tables_byte_equal_and_all_payload_hashes(api, tmp_path):
    two_checks(api)
    before = rows(api.conn, TABLES)
    folder = backup.create_backup(api.settings, tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored")
    backup.restore_backup(folder, restored)
    conn = db.connect(restored.db_path)
    try:
        assert rows(conn, TABLES) == before
        for row in conn.execute("SELECT raw_payload_path,payload_file_sha256 FROM watch_reads"):
            assert hashlib.sha256((restored.payloads_dir/row[0]).read_bytes()).hexdigest() == row[1]
    finally:
        conn.close()


@pytest.mark.parametrize("damage", ["corrupt", "missing", "conflict"])
def test_backup_watch_payload_damage_refused(api, tmp_path, damage):
    first, second = two_checks(api)
    reads = api.watches.reads(api.watches.check(api.rid, first["check_id"]))
    filename = reads[0]["raw_payload_path"]
    path = api.settings.payloads_dir / filename
    if damage == "corrupt":
        path.write_bytes(b"SYNTHETIC corrupted")
    elif damage == "missing":
        path.unlink()
    else:
        # Insert a new immutable provenance row with the same file and a conflicting digest.
        check = api.watches.check(api.rid, second["check_id"])
        step = api.store.step(check["run_id"], "SYNTHETIC-conflicting-hash", "watch_read")
        row = dict(api.conn.execute("SELECT * FROM watch_reads WHERE check_id=?", (second["check_id"],)).fetchone())
        row.update(id=db.new_id("wrd"), step_id=step["id"], page_number=99, raw_payload_path=filename, payload_file_sha256="0"*64)
        api.conn.execute(f"INSERT INTO watch_reads ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    with pytest.raises(backup.BackupError, match={"corrupt": "recorded hash", "missing": "missing", "conflict": "conflicting"}[damage]):
        backup.create_backup(api.settings, tmp_path / "refused-backups")


@pytest.mark.parametrize("reference", ["source", "watch"])
def test_purge_removes_six_tables_returns_watch_files_and_keeps_shared_payload(api, tmp_path, reference):
    two_checks(api)
    files = {r[0] for r in api.conn.execute("SELECT raw_payload_path FROM watch_reads")}
    other_rid = api.store.create_research("SYNTHETIC other", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    shared = next(iter(files))
    if reference == "source":
        source = api.store.create_upload_source("SYNTHETIC retained payload")
        api.store.add_to_corpus(other_rid, source, "user_upload", selection_state="included", selection_origin="user")
        api.conn.execute("UPDATE source_versions SET provider_payload_path=? WHERE id=?", (shared, source))
    else:
        api.store.freeze_protocol(other_rid, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC other"}]})
        other = api.watches.create(other_rid, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}, "other-watch")
        step = api.store.step(other["run_id"], "watch:0:page:1", "watch_read")
        row = dict(api.conn.execute("SELECT * FROM watch_reads WHERE raw_payload_path=?", (shared,)).fetchone())
        row.update(id=db.new_id("wrd"), research_id=other_rid, check_id=other["check_id"], step_id=step["id"])
        api.conn.execute(f"INSERT INTO watch_reads ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    api.store.trash_research(api.rid)
    _, payloads = api.store.purge_research(api.rid)
    assert set(payloads) == files-{shared}
    assert all(api.conn.execute(f"SELECT count(*) FROM {table} WHERE research_id=?", (api.rid,)).fetchone()[0] == 0 for table in TABLES)
    if reference == "source":
        assert api.conn.execute("SELECT id FROM source_versions WHERE id=?", (source,)).fetchone()
    else:
        assert api.conn.execute("SELECT raw_payload_path FROM watch_reads WHERE research_id=?", (other_rid,)).fetchone()[0] == shared


def test_rebind_retains_seen_set_and_baselines_current_scope(api):
    first = create(api); turn(api)
    revision = api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC rebound scope", None)
    api.store.freeze_protocol(api.rid, revision, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC rebound"}]})
    before_seen = rows(api.conn, ["watch_seen", "watch_seen_alias"])
    response = post(api, api.url + f"/{first['watch_id']}/rebind", version_body(api, first["watch_id"]), "rebind-new-scope")
    assert response.status_code == 201, response.text
    command = response.json()
    assert command["watch"]["scope_revision"] == revision and command["watch"]["baseline"] == {}
    assert not api.watches.watch(api.rid, first["watch_id"])["enabled"]
    assert rows(api.conn, ["watch_seen", "watch_seen_alias"]) == before_seen
    turn(api)
    assert read(api, command)["state"] == "succeeded" and not api.watches.items(api.rid)
    assert api.sent[-1].url.params["search.title_and_abstract"] == "SYNTHETIC rebound"
