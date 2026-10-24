"""storage/schema.sql and the upgrade steps in storage/upgrades.py (D119) against the migration files they replaced.

A new library made from schema.sql must hold what the old chain 0001 to 0016 made, object for object in the same order;
a library made at any older version by the old files must open, upgrade on its own and keep every row, id and file; a
library at the current version must open without any write. The old files are test fixtures (old_library.py).
Libraries here are SYNTHETIC.
"""

import hashlib
import sqlite3

import pytest

from deixis.config import Settings
from deixis.storage import db, upgrades
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.store import Store
from old_library import FOREIGN_KEYS_OFF, OLD_MIGRATIONS, master, old_files, old_library, steps_through, version_of

CURRENT = db.schema_version()
HISTORICAL = range(1, CURRENT)
PAPER = b"%PDF SYNTHETIC paper kept through the upgrade " * 40

# Rows a library at version 1 can hold: a research with a paused run, a succeeded step and its stored input, and an
# uploaded paper whose file sits in papers/. Every later version keeps these tables.
ROWS = (
    "INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_SYNTHETIC', 'SYNTHETIC research', 'n', 'n')",
    "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
    " VALUES ('run_SYNTHETIC', 'res_SYNTHETIC', 1, 'discovery', 'paused', 'screening', '{}', 'n', 'n')",
    "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt, output_json, started_at, finished_at)"
    " VALUES ('stp_SYNTHETIC', 'run_SYNTHETIC', 'discovery:plan', 'plan', 'succeeded', 1, '{\"queries\": 3}', 'n', 'n')",
    "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision, skill_package_hash,"
    " payload_json, base_instructions, developer_instructions, user_message, output_schema_json, created_at)"
    " VALUES ('sti_SYNTHETIC', 'stp_SYNTHETIC', 'res_SYNTHETIC', 'run_SYNTHETIC', 1, 'plan', 1, 'h', '{}', 'b', 'd', 'u',"
    " '{}', 'n')",
    "INSERT INTO works (id, created_at) VALUES ('wrk_SYNTHETIC', 'n')",
    "INSERT INTO source_versions (id, work_id, title, origin, created_at)"
    " VALUES ('srv_SYNTHETIC', 'wrk_SYNTHETIC', 'SYNTHETIC paper', 'user_upload', 'n')",
)


def rows(conn: sqlite3.Connection, tables) -> dict:
    """Every row of `tables`, read on the columns each had before the upgrade."""
    out = {}
    for table, columns in tables.items():
        names = ", ".join(f'"{c}"' for c in columns)
        out[table] = sorted((tuple(r) for r in conn.execute(f'SELECT {names} FROM "{table}"')), key=repr)  # noqa: S608
    return out


def user_tables(conn: sqlite3.Connection) -> dict:
    """Each table and its columns, without the version record and SQLite's own tables (the full-text index's included)."""
    shadow = {r[1] for r in conn.execute("PRAGMA table_list") if r[2] in ("shadow", "virtual")}
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {n: [r[1] for r in conn.execute(f'PRAGMA table_info("{n}")')] for n in names
            if n not in shadow and n != "schema_migrations"}


def fill(conn: sqlite3.Connection) -> None:
    for statement in ROWS:
        conn.execute(statement)
    conn.execute("INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
                 " retrieved_at, origin, extraction_status) VALUES ('ast_SYNTHETIC', 'srv_SYNTHETIC', ?, ?,"
                 " 'application/pdf', 'SYNTHETIC-paper.pdf', 'n', 'user_upload', 'succeeded')",
                 (hashlib.sha256(PAPER).hexdigest(), len(PAPER)))


def fresh_library(path) -> sqlite3.Connection:
    conn = db.connect(path)
    assert db.migrate(conn) == list(range(1, CURRENT + 1))
    return conn


# ---- schema.sql and the steps -----------------------------------------------------------------------------------

def test_schema_sql_names_the_version_every_step_reaches():
    assert CURRENT == max(db.packaged_versions()) == max(upgrades.STEPS)
    assert db.packaged_versions() == set(range(1, CURRENT + 1))  # one step per version after the baseline


def test_each_step_is_the_old_migration_file_word_for_word():
    """The steps were moved out of 0002 to 0016 unchanged: same name, same SQL, same foreign-key handling."""
    for path in old_files(CURRENT):
        if version_of(path) == 1:
            continue
        step = upgrades.STEPS[version_of(path)]
        assert step.name == path.name
        assert (f"{FOREIGN_KEYS_OFF}\n" if step.foreign_keys_off else "") + step.sql == path.read_text(encoding="utf-8")
    assert sorted(path.name for path in OLD_MIGRATIONS.glob("*.sql")) == [db.BASELINE_NAME] + [
        upgrades.STEPS[v].name for v in range(2, CURRENT + 1)]


def test_a_new_library_from_schema_sql_equals_one_made_by_the_old_files(tmp_path):
    new = fresh_library(tmp_path / "new.sqlite")
    old = old_library(tmp_path / "old.sqlite", CURRENT)
    # Same objects with the same SQL text in the same creation order (the order triggers on one table fire in).
    assert master(new) == master(old)
    assert len(master(new)) > 400
    # Same recorded versions under the same names, and the same rows everywhere else (the full-text index's own).
    record = "SELECT version, name FROM schema_migrations ORDER BY version"
    assert new.execute(record).fetchall() == old.execute(record).fetchall()
    tables = user_tables(new)
    assert rows(new, tables) == rows(old, tables)
    fts = ("passages_fts_data", "passages_fts_idx", "passages_fts_config", "passages_fts_docsize")
    assert [new.execute(f"SELECT * FROM {t}").fetchall() == old.execute(f"SELECT * FROM {t}").fetchall()  # noqa: S608
            for t in fts] == [True] * len(fts)
    for pragma in ("user_version", "application_id", "page_size", "auto_vacuum", "encoding", "journal_mode"):
        assert new.execute(f"PRAGMA {pragma}").fetchone() == old.execute(f"PRAGMA {pragma}").fetchone()


def test_a_new_library_is_made_in_one_transaction(tmp_path, monkeypatch):
    """A failure while making a new library leaves no table behind (the old chain kept the files that had finished)."""
    real = db.SCHEMA.read_text(encoding="utf-8")
    broken = tmp_path / "schema.sql"
    broken.write_text(real + "\nINSERT INTO no_such_table VALUES (1);\n", encoding="utf-8")
    monkeypatch.setattr(db, "SCHEMA", broken)
    path = tmp_path / "library.sqlite"
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed, match="no such table") as caught:
        db.migrate(conn)
    assert caught.value.name == "schema.sql"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name NOT IN ('schema_migrations')").fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    conn.close()


# ---- older libraries --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("version", HISTORICAL)
def test_a_library_at_each_older_version_upgrades_on_open_and_keeps_its_rows(tmp_path, version):
    path = tmp_path / "library.sqlite"
    conn = old_library(path, version)
    fill(conn)
    tables = user_tables(conn)
    before = rows(conn, tables)
    conn.close()

    db.check_schema_known(path)  # an older library is known: nothing to refuse
    conn = db.connect(path)
    assert db.migrate(conn) == list(range(version + 1, CURRENT + 1))
    assert rows(conn, tables) == before  # every row and id kept, read on the columns it had
    fresh = fresh_library(tmp_path / "fresh.sqlite")
    assert master(conn) == master(fresh)
    record = "SELECT version, name FROM schema_migrations ORDER BY version"
    assert conn.execute(record).fetchall() == fresh.execute(record).fetchall()
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.migrate(conn) == []

    # The paused run resumes where it stopped: its succeeded step is found by its key, not opened again.
    store = Store(conn)
    assert store.run("run_SYNTHETIC")["status"] == "paused"
    step = store.step("run_SYNTHETIC", "discovery:plan", "plan")
    assert (step["id"], step["status"], step["output"]) == ("stp_SYNTHETIC", "succeeded", {"queries": 3})
    assert store.research("res_SYNTHETIC")["title"] == "SYNTHETIC research"


def test_a_failing_upgrade_step_is_undone_and_the_library_stays_at_its_version(tmp_path, monkeypatch):
    """Step 9 rebuilds `researches` and `runs` with foreign keys off; made to fail at its end, it leaves the library as it
    was at version 8 and turns foreign keys back on. The next start with the real step upgrades it."""
    path = tmp_path / "library.sqlite"
    conn = old_library(path, 8)
    fill(conn)
    snapshot = master(conn), rows(conn, user_tables(conn))
    conn.close()
    steps = steps_through(CURRENT)
    steps[9] = steps[9]._replace(sql=steps[9].sql + "\nINSERT INTO no_such_table VALUES (1);\n")
    monkeypatch.setattr(upgrades, "STEPS", steps)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed) as caught:
        db.migrate(conn)
    assert caught.value.name == "0009_statement_check.sql" and "no such table" in str(caught.value)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert (master(conn), rows(conn, user_tables(conn))) == snapshot
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == list(range(1, 9))
    monkeypatch.undo()
    assert db.migrate(conn) == list(range(9, CURRENT + 1))
    conn.close()


def test_a_backup_of_an_older_library_restores_and_then_upgrades_with_its_paper(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    settings.data_dir.mkdir()
    conn = old_library(settings.db_path, 5)
    fill(conn)
    tables = user_tables(conn)
    before = rows(conn, tables)
    conn.close()
    settings.papers_dir.mkdir(parents=True, exist_ok=True)
    (settings.papers_dir / "SYNTHETIC-paper.pdf").write_bytes(PAPER)

    backup = create_backup(settings, tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored", port=8765)
    restore_backup(backup, restored)
    conn = db.connect(restored.db_path)
    try:
        assert db.migrate(conn) == list(range(6, CURRENT + 1))
        assert rows(conn, tables) == before
        assert conn.execute("SELECT storage_path FROM source_assets").fetchone()[0] == "SYNTHETIC-paper.pdf"
    finally:
        conn.close()
    assert (restored.papers_dir / "SYNTHETIC-paper.pdf").read_bytes() == PAPER


# ---- the current version --------------------------------------------------------------------------------------

def test_a_library_at_the_current_version_opens_without_any_write(tmp_path):
    path = tmp_path / "library.sqlite"
    conn = fresh_library(path)
    fill(conn)
    conn.close()  # the last connection checkpoints and removes the -wal
    before = path.read_bytes()
    db.check_schema_known(path)
    conn = db.connect(path)
    assert db.migrate(conn) == []
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == CURRENT
    conn.close()
    assert path.read_bytes() == before


def test_a_library_from_a_newer_version_is_refused_before_any_write(tmp_path):
    path = tmp_path / "library.sqlite"
    conn = fresh_library(path)
    conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, 'SYNTHETIC newer', 'n')", (CURRENT + 1,))
    conn.close()
    before = path.read_bytes()
    with pytest.raises(db.UnknownSchemaError, match="newer DEIXIS"):
        db.connect(path)
    assert path.read_bytes() == before
