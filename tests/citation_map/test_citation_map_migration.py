"""Migration 0015 rebuilds `runs` to allow the `citation_map` kind and adds `citation_map_resolutions`. From a filled
0014 library: every run row, the rows that point at runs, the triggers and the indexes survive; a failure inside the
migration leaves 0014 working. SYNTHETIC rows on a temporary library."""

import shutil
import sqlite3

import pytest

from deixis.storage import db

KINDS = ("discovery", "answer", "answer_review", "followup_answer", "table_columns", "table_fill", "cell_recheck",
         "table_column_recheck", "screen_more", "research_title", "pdf_collection", "pdf_ocr", "report", "fulltext_fetch",
         "fulltext_adjudication", "lineage_links", "claim_decomposition", "kill_search", "review", "watch_check")
NEW_RUN = ("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
           " VALUES ('run_map', 'res_old', 1, 'citation_map', 'queued', 'synthesis', '{}', 'now', 'now')")


def library_at_0014(tmp_path, monkeypatch, extra: str | None = None):
    real = db.MIGRATIONS_DIR
    older = tmp_path / "older"
    older.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 15:
            shutil.copy(path, older / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_old', 'SYNTHETIC', 'now', 'now')")
    for n, kind in enumerate(KINDS):  # one finished run of every kind the library knows
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, usage_json,"
                     " target_json, idempotency_key, version, created_at, updated_at) VALUES (?, 'res_old', 1, ?,"
                     " 'completed', 'extraction', '{\"max_model_calls\": 2}', '{\"model_calls\": 1}', '{\"t\": 1}', ?, 3,"
                     " 'then', 'later')", (f"run_{n:02d}", kind, f"key-{n}"))
    conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_old', 'run_00', 'k', 'model:x', 'succeeded')")
    conn.execute("INSERT INTO provider_requests (run_id, host, url, started_at) VALUES ('run_00', 'api.openalex.org', 'u', 'now')")
    conn.execute("INSERT INTO events (research_id, run_id, type, payload_json, created_at) VALUES ('res_old', 'run_00', 'run_completed', '{}', 'now')")
    if extra is not None:
        source = (real / "0015_citation_map.sql").read_text()
        marker = "CREATE INDEX runs_status ON runs(status, created_at);"
        broken = tmp_path / "broken"
        broken.mkdir()
        for path in older.glob("*.sql"):
            shutil.copy(path, broken / path.name)
        (broken / "0015_citation_map.sql").write_text(source.replace(marker, marker + "\n" + extra))
        monkeypatch.setattr(db, "MIGRATIONS_DIR", broken)
    else:
        monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    return conn


def snapshot(conn):
    objects = {row[0]: row[1] for row in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('trigger', 'index') AND sql IS NOT NULL")}
    rows = {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("runs", "run_steps", "provider_requests", "provider_requests_unrecorded_runs", "events")}
    return objects, rows


def test_the_rebuild_keeps_rows_references_triggers_and_indexes(tmp_path, monkeypatch):
    conn = library_at_0014(tmp_path, monkeypatch)
    objects, rows = snapshot(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(NEW_RUN)
    assert 15 in db.migrate(conn)
    after_objects, after_rows = snapshot(conn)
    assert after_rows == rows
    assert {name: after_objects[name] for name in objects} == objects  # every trigger and index, same text
    assert set(after_objects) - set(objects) == {"citation_map_resolutions_openalex"}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute(NEW_RUN)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE runs SET kind = 'invented' WHERE id = 'run_map'")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE runs SET idempotency_key = 'key-1' WHERE id = 'run_map'")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES ('stp_x', 'run_missing', 'k', 'x', 'pending')")
    # The run guards still read the rebuilt table: a citation map run is not a review run.
    with pytest.raises(sqlite3.IntegrityError, match="owner review requires a review run"):
        conn.execute("INSERT INTO owner_reviews (id, research_id, snapshot_id, run_id, focus, requested_connection, created_at)"
                     " VALUES ('rev_x', 'res_old', 'snap_x', 'run_map', 'source_support', 'fake', 'now')")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(citation_map_resolutions)")}
    assert columns == {"source_version_id", "method", "status", "openalex_id", "doi", "run_id", "resolved_at"}
    conn.close()


def test_a_failure_inside_the_migration_leaves_0014_working(tmp_path, monkeypatch):
    conn = library_at_0014(tmp_path, monkeypatch, extra="INSERT INTO runs (id) VALUES ('run_broken');")
    before = snapshot(conn)
    runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        db.migrate(conn)
    assert snapshot(conn) == before
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0] == runs_sql
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name IN ('runs_new', 'citation_map_resolutions')").fetchone() is None
    assert conn.execute("SELECT 1 FROM schema_migrations WHERE version = 15").fetchone() is None
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(NEW_RUN)
    conn.close()
