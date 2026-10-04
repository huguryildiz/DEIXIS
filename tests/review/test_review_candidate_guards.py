"""SYNTHETIC candidate reviews under unchanged real Worker/API write guards."""

import sqlite3
import time

import pytest

from tests.fakes import FakeAdapter
from tests.review.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, candidate_body, candidate_response
from tests.review.review_helpers import all_rows
from tests.review.review_run_helpers import review_api, start, terminal, control
from tests.review.test_review_lifecycle_guards import permitted, hashes, WRITE_ACTIONS

CANDIDATE_TABLES = {"research_candidates", "candidate_versions", "claim_elements", "kill_searches",
    "kill_search_queries", "kill_search_query_records", "kill_search_hits", "claim_matrix_cells",
    "claim_matrix_evidence", "candidate_status_overrides"}


@pytest.mark.parametrize("case", ["normal", "internal_error", "invalid_output", "cancelled"])
def test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables(candidate_lib, tmp_path, case):
    def respond(si):
        if case == "internal_error": raise RuntimeError("SYNTHETIC internal failure")
        return "SYNTHETIC invalid JSON" if case == "invalid_output" else candidate_response(si)
    adapter = FakeAdapter(responder=respond, delay=.2 if case == "cancelled" else 0)
    with review_api(candidate_lib, tmp_path, adapter=adapter, start_worker=True) as api:
        denied, writes = [], []
        def guard(action, table, column, database, trigger):
            if action in WRITE_ACTIONS:
                writes.append((action, table, column))
                if not permitted(action, table, column, api.conn):
                    denied.append((action, table, column)); return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        def begin():
            rows = all_rows(api.conn); before = hashes(api.conn)
            assert CANDIDATE_TABLES <= before.keys()
            assert all(rows[t] for t in CANDIDATE_TABLES)
            controls = {t: rows[t] for t in ("researches", "worker_owner")}
            api.conn.set_authorizer(guard)
            return before, controls
        before, controls = api.client.portal.call(begin)
        try:
            opened, _, _ = start(api, candidate_body(candidate_lib))
            if case == "cancelled":
                deadline = time.monotonic() + 10
                while not adapter.calls and time.monotonic() < deadline: time.sleep(.005)
                assert adapter.calls
                control(api, opened["run"]["id"], "cancel")
            card = terminal(api, opened["review"]["id"])
            deadline = time.monotonic() + 10
            while api.app.state.worker.current_run_id and time.monotonic() < deadline: time.sleep(.005)
            assert api.app.state.worker.current_run_id is None
            assert not denied, denied
            assert api.client.portal.call(hashes, api.conn) == before
            assert card["state"] == {"normal": "completed", "internal_error": "failed", "invalid_output": "failed", "cancelled": "cancelled"}[case]
            if case == "normal": assert len(card["findings"]) == 2
            if case == "invalid_output": assert len(adapter.calls) == 2 and len(card["not_reviewed"]) == 2
            assert any(t == "worker_owner" and c == "heartbeat_at" for _, t, c in writes)
            after = api.client.portal.call(all_rows, api.conn)
            for table, field in (("researches", "updated_at"), ("worker_owner", "heartbeat_at")):
                columns = [r[1] for r in api.conn.execute(f'PRAGMA table_info("{table}")')]
                index = columns.index(field)
                strip = lambda rows: [r[:index] + r[index + 1:] for r in rows]
                assert strip(controls[table]) == strip(after[table])
        finally:
            api.client.portal.call(api.conn.set_authorizer, None)
