"""UI parity S20: the migration that adds the `screen_more` run kind rebuilds `runs`. Old rows, every earlier run kind,
the dependents' foreign keys and the three triggers that read `runs` survive it. SYNTHETIC rows on a temporary library.
"""

import shutil
import sqlite3

import pytest

from deixis.storage import db

KINDS = ("discovery", "answer", "answer_review", "table_columns", "table_fill", "cell_recheck", "table_column_recheck",
         "research_title", "pdf_collection", "pdf_ocr", "report", "fulltext_fetch", "fulltext_adjudication",
         "lineage_links", "claim_decomposition", "kill_search", "review", "watch_check")


def test_the_screen_more_migration_keeps_every_run_kind_row_and_run_guard(tmp_path, monkeypatch):
    real = db.MIGRATIONS_DIR
    rebuild = next(p for p in real.glob("*.sql") if p.name.endswith("_screen_more.sql"))
    number = int(rebuild.name.split("_", 1)[0])
    older = tmp_path / "older"
    older.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < number:
            shutil.copy(path, older / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_old', 'SYNTHETIC', 'now', 'now')")
    for n, kind in enumerate(KINDS):  # one finished run of every kind the library already knows
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, usage_json,"
                     " target_json, idempotency_key, version, created_at, updated_at) VALUES (?, 'res_old', 1, ?,"
                     " 'completed', 'extraction', '{\"max_model_calls\": 2}', '{\"model_calls\": 1}', '{\"t\": 1}', ?, 3,"
                     " 'then', 'later')", (f"run_{n:02d}", kind, f"key-{n}"))
    conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_old', 'run_00', 'k', 'model:x', 'succeeded')")
    before = [tuple(row) for row in conn.execute("SELECT * FROM runs ORDER BY id")]
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE runs SET kind = 'screen_more' WHERE id = 'run_00'")

    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    assert number in db.migrate(conn)
    assert [tuple(row) for row in conn.execute("SELECT * FROM runs ORDER BY id")] == before  # every row, unchanged
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                 " updated_at) VALUES ('run_new', 'res_old', 1, 'screen_more', 'queued', 'screening', '{}', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE runs SET idempotency_key = 'key-1' WHERE id = 'run_new'")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE runs SET kind = 'invented' WHERE id = 'run_new'")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE runs SET stage = 'invented' WHERE id = 'run_new'")

    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND sql LIKE '%runs%'")}
    assert {"kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard"} <= triggers
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'runs_status'").fetchone() is not None
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT run_id FROM run_steps WHERE id = 'stp_old'").fetchone()[0] == "run_00"  # dependents kept
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_x', 'run_missing', 'k', 'x', 'pending')")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                     " updated_at) VALUES ('run_x', 'res_missing', 1, 'screen_more', 'queued', 'screening', '{}', 'now', 'now')")
    # The run guards still read the rebuilt table: a screen_more run is not a review run nor a watch check's run.
    with pytest.raises(sqlite3.IntegrityError, match="owner review requires a review run"):
        conn.execute("INSERT INTO owner_reviews (id, research_id, snapshot_id, run_id, focus, requested_connection, created_at)"
                     " VALUES ('rev_x', 'res_old', 'snap_x', 'run_new', 'source_support', 'fake', 'now')")
    with pytest.raises(sqlite3.IntegrityError, match="watch check requires its research watch and run"):
        conn.execute("INSERT INTO watch_checks (id, watch_id, research_id, run_id, trigger, period_start, requested_to,"
                     " config_json, state_version, created_at) VALUES ('wck_x', 'wat_x', 'res_old', 'run_new', 'manual',"
                     " 'now', 'now', '{}', 1, 'now')")
    with pytest.raises(sqlite3.IntegrityError, match="kill-search run kind or research mismatch"):
        conn.execute("INSERT INTO kill_searches (id, candidate_version_id, run_id, query_block_json, rendered_queries_json,"
                     " skipped_terms_json, selection_json, outcome, created_at) VALUES ('kls_x', 'cv_x', 'run_new', '{}',"
                     " '[]', '[]', '{}', 'running', 'now')")
    conn.close()
