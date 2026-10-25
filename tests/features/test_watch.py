"""Routes, idempotency, atomic commands, lifecycle separation, backup and purge."""

import hashlib
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from deixis.config import Settings
from deixis.providers import registry
from deixis.storage import backup, db
from deixis.workflow.watch_store import TABLES
from watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, page, work, rows, hashes, add_included


def version_body(api, wid):
    return {"expected_state_version": api.watches.watch(api.rid, wid)["state_version"]}


def post(api, path, body, key="SYNTHETIC-command"):
    return api.client.post(path, json=body, headers={"Idempotency-Key": key})


@pytest.mark.parametrize("action", ["check"])
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


def test_route_refusals_revision_active_paused_old_scope_and_strict_bodies(api):
    body = {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}
    assert post(api, api.url, body | {"unexpected": True}).status_code == 422
    response = api.client.post(api.url, json=body)
    assert response.status_code == 422
    for key in ("", "x" * 201):
        assert post(api, api.url, body, key).status_code == 422
    assert post(api, api.url, body | {"mode": "interval"}).json()["code"] == "schedule_invalid"
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


@pytest.mark.parametrize("lifecycle", ["baseline_and_new"])
def test_real_worker_lifecycle_authorizer_every_other_table_and_view_counts_unchanged(api, lifecycle):
    # provider_requests: the run's own provider requests, stored one row per attempt (D31).
    allowed = {"runs", "run_steps", "events", *TABLES, "researches", "worker_owner", "sqlite_sequence", "provider_requests"}
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


def test_backup_restore_eight_tables_byte_equal_and_all_payload_hashes(api, tmp_path):
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


@pytest.mark.parametrize("reference", ["watch"])
def test_purge_removes_eight_tables_returns_watch_files_and_keeps_shared_payload(api, tmp_path, reference):
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


import json
from dataclasses import replace

import httpx
import pytest

from deixis.providers import common, registry
from deixis.storage import db
from deixis.workflow import watch_check as policy
import test_fast_path_clock
from watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, work, page, add_included

library = test_fast_path_clock.library  # the fast-path test library, a fixture


def test_baseline_and_second_check_announce_only_new_identities(api):
    first = create(api); turn(api)
    assert read(api, first)["state"] == "succeeded"
    assert api.conn.execute("SELECT origin FROM watch_seen").fetchone()[0] == "baseline"
    assert api.watches.items(api.rid) == []
    api.state.payload = page(work(), work("W2"))
    second = now_check(api, first["watch_id"]); turn(api)
    card = read(api, second)
    assert card["state"] == "succeeded" and card["counts"]["new"] == 1 and card["counts"]["already_seen"] == 1
    assert len(api.watches.items(api.rid)) == 1
    assert api.sent[-1].url.params["sort"] == "publication_date:desc"
    assert api.sent[-1].url.params["select"].endswith(",publication_date")
    row = api.watches.reads(api.watches.check(api.rid, second["check_id"]))[0]
    assert "sort=publication_date:desc select+publication_date" in row["request_description"]
    assert json.loads(row["connector_json"])["adapter_revision"] == 3
    assert card["observed"]["units"]["query:0"]["sort_sent"] == "publication_date:desc"


def test_failed_baseline_provider_is_silent_on_first_success(api):
    api.state.status = 500
    first = create(api); turn(api)
    assert read(api, first)["failure_reason"] == "no_provider_read"
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 0
    api.state.status = 200
    second = now_check(api, first["watch_id"]); turn(api)
    assert read(api, second)["counts"]["baseline"] == 1
    assert api.watches.items(api.rid) == []


def test_not_configured_and_not_searchable_units_send_nothing(tmp_path):
    with watch_api(tmp_path, queries=[{"provider_id": "core", "query_text": "SYNTHETIC"},
                                    {"provider_id": "crossref", "query_text": "SYNTHETIC"}]) as api:
        command = create(api); turn(api)
        card = read(api, command)
        assert api.sent == [] and card["state"] == "failed" and card["failure_reason"] == "no_provider_read"
        assert card["provider_status"]["query:0"]["status"] == "not_configured"
        assert card["provider_status"]["query:1"]["status"] == "skipped_not_searchable"


def test_watch_quota_is_stored_and_a_stored_reset_sends_nothing(api):
    """A watch's OpenAlex budget refusal joins `openalex_budget_runs`; while that reset is ahead, no OpenAlex page is sent."""
    api.state.handler = lambda request: httpx.Response(429, json={"error": {"code": "insufficient_quota"}},
        headers={"x-ratelimit-remaining-usd": "0", "x-ratelimit-reset": "3600"})
    first = create(api); turn(api)
    row = api.conn.execute("SELECT run_id, refused FROM openalex_budget_runs").fetchone()
    assert tuple(row) == (first["run_id"], 1) and api.store.openalex_budget_reset() > db.now()
    sent = len(api.sent)
    api.state.handler = None
    second = now_check(api, first["watch_id"]); turn(api)
    assert len(api.sent) == sent
    assert read(api, second)["provider_status"]["query:0"]["status"] == "quota_deferred"


def test_transient_resend_is_budget_gated(api, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    def fail(request):
        raise httpx.ConnectError("SYNTHETIC not sent", request=request)
    api.state.handler = fail
    command = create(api); turn(api)
    assert len(api.sent) == api.store.run(command["run_id"])["usage"]["provider_requests"] == 1
    assert "budget_deferred" in read(api, command)["partial_reasons"]
    assert api.watches.reads(api.watches.check(api.rid, command["check_id"]))[0]["status"] == "deferred_budget"


def test_success_boundary_does_not_move_on_failed_or_deferred_unit(api, monkeypatch):
    first = create(api); turn(api)
    old = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]["success_boundary"]
    last_success = api.watches.watch(api.rid, first["watch_id"])["last_success_at"]
    api.state.status = 500
    second = now_check(api, first["watch_id"]); turn(api)
    baseline = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])
    assert baseline["query:0"]["success_boundary"] == old
    assert read(api, second)["observed"]["units"]["query:0"]["unread_window"] == {"from": old, "to": second["check"]["requested_to"]}
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 0)
    third = now_check(api, first["watch_id"]); turn(api)
    assert json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]["success_boundary"] == old
    assert api.watches.watch(api.rid, first["watch_id"])["last_success_at"] == last_success
    assert read(api, third)["observed"]["units"]["query:0"]["sort_sent"] is None


import json
import sqlite3

import pytest

from deixis.providers import openalex
from deixis.storage import db
from deixis.workflow import watch_check as policy
from watch_helpers import api, watch_offline, create, now_check, turn, read, page, work, record, add_included


def inject(api, command, records):
    # Completion applies already-normalized records exactly as a provider read would supply them.
    # No immutability trigger is relaxed: this creates a new immutable read before completion.
    from deixis.providers.common import SearchOutcome
    check = api.watches.check(api.rid, command["check_id"])
    unit = json.loads(check["config_json"])["units"][0]
    step = api.store.step(command["run_id"], "watch:0:page:1", "watch_read")
    api.store.start_step(step["id"])
    api.watches.record_read(check, unit, 1, step, SearchOutcome("completed", None, "SYNTHETIC injected read", "keyless"),
        records, len(records), 0, {"contract_id": unit["contract_id"], "adapter_revision": unit["adapter_revision"]}, None, None, None)
    turn(api)


def test_doi_arrives_later_no_reannouncement(api):
    first = create(api); turn(api)
    api.state.payload = page(work(doi="https://doi.org/10.1000/late"))
    second = now_check(api, first["watch_id"]); turn(api)
    assert read(api, second)["counts"]["new"] == 0 and not api.watches.items(api.rid)
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 1
    assert api.conn.execute("SELECT alias FROM watch_seen_alias WHERE alias='doi:10.1000/late'").fetchone()


def test_exact_doi_merges_seen_rows_keeps_item_and_dismissal(api):
    api.state.payload = page()
    first = create(api); turn(api)
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "A", doi="10.1000/join"), record("openalex", "B")])
    items = api.watches.items(api.rid)
    oldest = min(items, key=lambda i: (i["created_at"], i["id"]))
    api.watches.dismiss(api.rid, oldest["id"], {"expected_status": "new", "reason": "SYNTHETIC dismissed"}, "dismiss-merge")
    third = now_check(api, first["watch_id"])
    inject(api, third, [record("openalex", "B", doi="10.1000/join")])
    saved = api.watches.items(api.rid, None)
    assert len(saved) == 2 and {i["status"] for i in saved} == {"dismissed", "merged"}
    survivor = api.watches.item(api.rid, oldest["id"])
    assert survivor["status"] == "dismissed" and survivor["dismissed_reason"] == "SYNTHETIC dismissed"
    merged = next(i for i in saved if i["status"] == "merged")
    assert merged["merged_into_item_id"] == oldest["id"]
    assert api.conn.execute("SELECT count(*) FROM watch_seen WHERE merged_into IS NULL").fetchone()[0] == 1
    assert read(api, third)["counts"]["new"] == 0
    # Following the newly added DOI again never revives the dismissed item.
    fourth = now_check(api, first["watch_id"])
    inject(api, fourth, [record("biorxiv", "B", doi="10.1000/join")])
    assert len(api.watches.items(api.rid, None)) == 2 and not api.watches.items(api.rid)


from watch_helpers import api, watch_offline, create, now_check, turn, page, work


def counts(api):
    return {row["id"]: row["followup_new"] for row in api.store.list_researches()}


def test_followup_new_counts_only_this_researchs_new_records_even_when_disabled(api):
    api.state.payload = page()
    command = create(api); turn(api)
    api.state.payload = page(*(work(f"W{i}") for i in range(5)),
                             work("WN", title="Correction: SYNTHETIC paper W0"))
    now_check(api, command["watch_id"]); turn(api)
    items = api.watches.items(api.rid)
    records = [item for item in items if item["kind"] == "new_record"]
    assert len(records) == 5 and len(items) == 6
    assert counts(api)[api.rid] == 5
    api.watches.dismiss(api.rid, records[0]["id"], {"expected_status": "new", "reason": "SYNTHETIC"}, "dismiss-count")
    api.conn.execute("UPDATE watch_items SET status='merged',merged_into_item_id=? WHERE id=?",
                     (records[2]["id"], records[1]["id"]))
    other = api.store.create_research("SYNTHETIC other", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    # The parent trigger requires the check/seen rows to belong to the item's research.
    api.store.freeze_protocol(other, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC other"}]})
    api.state.payload = page()
    second = api.watches.create(other, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}, "other-count")
    turn(api)
    api.state.payload = page(work("WOTHER"))
    api.watches.check_now(other, second["watch_id"],
                          {"expected_state_version": api.watches.watch(other, second["watch_id"])["state_version"]}, "other-check-count")
    turn(api)
    assert counts(api) == {api.rid: 3, other: 1}
    api.watches.disable(api.rid, command["watch_id"],
                        {"expected_state_version": api.watches.watch(api.rid, command["watch_id"])["state_version"]}, "disable-count")
    assert counts(api) == {api.rid: 3, other: 1}


from deixis.workflow.search import sent_plan


def test_a_watch_follows_the_dated_queries_a_fast_plan_sends():
    compiled = [{"provider_id": "openalex", "query_text": "A"}, {"provider_id": "crossref", "query_text": "B"},
                {"provider_id": "semantic_scholar", "query_text": "C", "endpoint": "bulk"}]
    body = {"compiled_queries": compiled, "fast_path_search": {
        "semantic": {"query_text": "S", "query_origin": "question"},
        "seed_semantic": [{"index": 0, "provider_id": "openalex", "query_text": "P", "origin": "seed_text"}],
        "keywords": [{"index": 0}], "s2_bulk": compiled[2], "s2_bulk_index": 2}}
    assert [(q["key"], q["watchable"], q.get("compiled_index")) for q in sent_plan(body)] == [
        ("search:fast:semantic", False, None), ("search:fast:semantic:seed:0", False, None), ("search:0", True, 0),
        ("search:fast:s2_bulk", True, 2)]
    # A body frozen without the plan sends every compiled query under its index.
    assert [q["key"] for q in sent_plan({"compiled_queries": compiled})] == ["search:0", "search:1", "search:2"]


import ast
from pathlib import Path
import re


def test_watch_package_has_no_library_writer_or_sql_mutation():
    root = Path("deixis/workflow")
    forbidden_calls = {"record_search", "add_search_run", "upsert_provider_source", "add_to_corpus", "link_records"}
    library = {"sources", "source_versions", "works", "corpus_memberships", "candidates", "candidate_hits",
               "search_runs", "identifier_mappings", "record_links", "selections", "passages"}
    for path in root.glob("watch_*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls and not node.func.attr.startswith("add_asset"), (path, node.lineno)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for statement in node.value.split(";"):
                    if re.search(r"\b(?:INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER)\b", statement, re.I):
                        assert not any(re.search(r"\b" + t + r"\b", statement, re.I) for t in library), (path, node.lineno, statement)
