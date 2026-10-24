"""Upgrade step 7 (0007_answer_thread_candidates.sql, D98) on a library made by 0001 to 0006. Libraries here are
SYNTHETIC."""

import sqlite3

import pytest

from deixis.storage import db, upgrades
from old_library import old_library, steps_through

REBUILT_TRIGGERS = ("candidate_status_overrides_no_delete", "candidate_versions_no_delete", "claim_elements_no_delete",
                    "claim_matrix_cells_no_delete", "claim_matrix_evidence_no_delete", "kill_search_hits_no_delete",
                    "kill_search_queries_no_delete", "kill_search_query_records_no_delete", "kill_searches_no_delete",
                    "kill_searches_run_guard", "research_candidates_empty_pointer", "research_candidates_identity_no_update",
                    "research_candidates_no_conflicting_insert", "research_candidates_no_delete",
                    "research_candidates_publish_guard")
CANDIDATE = ("INSERT INTO research_candidates (id, research_id, origin, origin_text, origin_basis_json, origin_basis_view_json,"
             " origin_provenance_json, created_at) VALUES (?, 'res_1', ?, 'SYNTHETIC claim', '{}', '{}', '{}', 'now')")


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def test_0007_adds_the_answer_thread_origin_keeps_rows_and_triggers_and_matches_a_fresh_library(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    conn = old_library(path, 6)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute(CANDIDATE, ("rcd_SYNTHETIC0001", "owner_text"))
    conn.execute("INSERT INTO candidate_versions (id, candidate_id, version, claim_statement, conditions_json,"
                 " critical_assumption, validation_plan, origin, created_at)"
                 " VALUES ('clv_1', 'rcd_SYNTHETIC0001', 1, 'SYNTHETIC claim', '[]', 'a', 'b', 'human_edit', 'now')")
    conn.execute("UPDATE research_candidates SET current_version = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(CANDIDATE, ("rcd_SYNTHETIC0002", "answer_thread"))
    before = [tuple(r) for r in conn.execute("SELECT * FROM research_candidates")]
    conn.close()

    monkeypatch.setattr(upgrades, "STEPS", steps_through(7))
    conn = db.connect(path)
    assert db.migrate(conn) == [7]
    assert [tuple(r) for r in conn.execute("SELECT * FROM research_candidates")] == before
    conn.execute(CANDIDATE, ("rcd_SYNTHETIC0002", "answer_thread"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(CANDIDATE, ("rcd_SYNTHETIC0003", "no_such_origin"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert triggers >= set(REBUILT_TRIGGERS)
    # The rebuilt guards still act: a version cannot be deleted without the research's purge authorization.
    with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
        conn.execute("DELETE FROM candidate_versions")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert schema(conn) == schema(old_library(tmp_path / "fresh.sqlite", 7))
