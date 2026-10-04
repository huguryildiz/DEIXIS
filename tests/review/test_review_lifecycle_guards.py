"""All-table separation across real API and Worker lifecycles, using scripted models."""

import hashlib
import sqlite3
import time

import pytest

from deixis.storage import db
from deixis.workflow import person_reading
from tests.fakes import FakeAdapter
from tests.review.review_helpers import report_with_sections, review_lib, all_rows
from tests.review.review_run_helpers import review_api, start, read, control, terminal, two_groups, finding_response

ALLOWED = {"runs", "run_steps", "step_inputs", "model_sessions", "events",
           "owner_review_snapshots", "owner_reviews", "owner_review_findings", "owner_review_decisions", "sqlite_sequence"}
WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}


def permitted(action, table, column, conn):
    if table in ALLOWED:
        return True
    if action == sqlite3.SQLITE_UPDATE and (table, column) in {("researches", "updated_at"), ("worker_owner", "heartbeat_at")}:
        return True
    return False


def hashes(conn):
    return {table: hashlib.sha256(repr(rows).encode()).hexdigest() for table, rows in all_rows(conn).items()
            if table not in ALLOWED | {"researches", "worker_owner"}}


@pytest.mark.parametrize("case", ["normal", "internal_error", "invalid_output", "cancelled"])
def test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes(review_lib, tmp_path, monkeypatch, case):
    def respond(si):
        if case == "internal_error":
            raise RuntimeError("SYNTHETIC adapter failure")
        return "invalid JSON" if case == "invalid_output" else finding_response(si)
    adapter = FakeAdapter(responder=respond, delay=.15 if case == "cancelled" else 0)
    with review_api(review_lib, tmp_path, adapter=adapter, start_worker=True) as api:
        two_groups(api, monkeypatch)
        if case == "normal":
            # An unrepresentable third claim is announced rather than shortened.
            section = api.lib["section_ids"]["III"]
            api.conn.execute("INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type)"
                " VALUES (?, ?, 'III.2', 2, 1, ?, 'analyst_inference')", (db.new_id("rcl"), section, "x" * 4001))
        denied, writes = [], []
        def guard(action, table, column, database, trigger):
            if action in WRITE_ACTIONS:
                writes.append((action, table, column))
                if not permitted(action, table, column, api.conn):
                    denied.append((action, table, column))
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def begin():
            assert "AUTOINCREMENT" in api.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'events'").fetchone()[0]
            before = hashes(api.conn)
            controls = {t: all_rows(api.conn)[t] for t in ("researches", "worker_owner")}
            api.conn.set_authorizer(guard)
            return before, controls
        before, controls = api.client.portal.call(begin)
        try:
            opened, _, _ = start(api)
            if case == "cancelled":
                stop = time.monotonic() + 10
                while not adapter.calls and time.monotonic() < stop:
                    time.sleep(.005)
                assert adapter.calls
                control(api, opened["run"]["id"], "cancel")
            card = terminal(api, opened["review"]["id"])
            # Cancel answers immediately; let the outstanding scripted call and
            # Worker's run-end callback drain before comparing all rows.
            stop = time.monotonic() + 10
            while api.app.state.worker.current_run_id and time.monotonic() < stop:
                time.sleep(.005)
            assert api.app.state.worker.current_run_id is None
            assert not denied, denied
            assert api.client.portal.call(hashes, api.conn) == before
            assert card["state"] == {"normal": "partial", "internal_error": "failed", "invalid_output": "failed", "cancelled": "cancelled"}[case]
            if case == "normal":
                assert len(card["groups"]) == len(card["findings"]) == 2
                assert "claim_text_too_long" in {r["reason"] for r in card["not_reviewed"]}
                assert {r["claim_ref"] for r in card["not_reviewed"]} == {"III.2"}
            if case == "internal_error":
                assert card["failure_reason"] == "internal_error"
            if case == "invalid_output":
                assert card["failure_reason"] == "nothing_reviewed"
                assert len(adapter.calls) == 4 and not card["findings"]
            assert any(t == "worker_owner" and c == "heartbeat_at" for _, t, c in writes)
            # The two narrowly allowed mutable tables retain all other columns.
            after = api.client.portal.call(all_rows, api.conn)
            for table, field in (("researches", "updated_at"), ("worker_owner", "heartbeat_at")):
                columns = [r[1] for r in api.conn.execute(f'PRAGMA table_info("{table}")')]
                index = columns.index(field)
                strip = lambda rows: [r[:index] + r[index + 1:] for r in rows]
                assert strip(controls[table]) == strip(after[table])
        finally:
            api.client.portal.call(api.conn.set_authorizer, None)


def waiting_file(api):
    scope = api.store.scope(api.rid)
    api.store.freeze_protocol(api.rid, scope["revision"], {"question": scope["question"], "steering": scope["steering"],
        "inclusion_criterion": "SYNTHETIC methods are studied", "criterion_parts": [], "cue_phrases": [], "exclusion_title_words": []})
    asset = db.new_id("ast")
    api.conn.execute("INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, retrieved_at,"
        " origin, extraction_status, extraction_version, page_count) VALUES (?, ?, ?, 1, 'application/pdf', 'synthetic.pdf', ?,"
        " 'user_upload', 'succeeded', 'synthetic', 1)", (asset, api.lib["source_id"], "0" * 64, db.now()))
    api.store._insert_passage(api.lib["source_id"], asset, "pdf_page", 1, None, None, None, "synthetic", "SYNTHETIC waiting page")
    person_reading.insert_request(api.store, api.rid, api.lib["source_id"], asset)


def test_cancel_with_waiting_person_file_matches_nonreview_run_end_followup(review_lib, tmp_path):
    outcomes = []
    for kind in ("review", "table_columns"):
        with review_api(review_lib, tmp_path) as api:
            if kind == "review":
                opened, _, _ = start(api)
                run_id = opened["run"]["id"]
            else:
                run_id = api.store.create_run(api.rid, kind, {}, None)["id"]
            waiting_file(api)
            writes = []
            def observe(action, table, column, database, trigger):
                if action in WRITE_ACTIONS:
                    writes.append((action, table, column))
                return sqlite3.SQLITE_OK
            api.conn.set_authorizer(observe)
            try:
                control(api, run_id, "cancel")
                api.client.portal.call(api.app.state.worker._run_ended, run_id)
                queued = api.conn.execute("SELECT kind, status FROM runs WHERE status = 'queued'").fetchall()
                assert [tuple(r) for r in queued] == [("fulltext_adjudication", "queued")]
                outside = {w for w in writes if not permitted(*w, api.conn)}
                assert {t for _, t, _ in outside} <= {"person_pdf_requests"}
                outcomes.append((outside, [tuple(r) for r in queued], [r[0] for r in api.conn.execute("SELECT status FROM person_pdf_requests")]))
            finally:
                api.conn.set_authorizer(None)
    assert outcomes[0] == outcomes[1]
