"""RR-A storage and launcher regressions, synthetic libraries only."""

import sqlite3

import pytest

from deixis import __main__ as launcher
from deixis.config import Settings
from deixis.storage import backup, db
from test_p9_restore_matrix import (
    fake_uvicorn, file_facts, folder_names, hand_backup,
    entry, library_with_id_only_in_the_wal, settings_for, write_manifest,
)


@pytest.mark.parametrize("operation", [db.check_schema_known, db.connect])
def test_symlink_uses_the_real_wal_for_schema_refusal(tmp_path, operation):
    path = library_with_id_only_in_the_wal(tmp_path / "source")
    link = tmp_path / "alias" / "library.sqlite"
    link.parent.mkdir()
    link.symlink_to(path)
    before = file_facts(path.parent), folder_names(path.parent)
    with pytest.raises(db.UnknownSchemaError, match="9999"):
        operation(link)
    assert (file_facts(path.parent), folder_names(path.parent)) == before


@pytest.mark.parametrize("damage", ["text", "integrity"])
def test_staged_database_is_verified_and_removed_on_failure(tmp_path, monkeypatch, damage):
    source = hand_backup(tmp_path, papers=0, payloads=0)
    if damage == "integrity":
        (source / "library.sqlite").write_bytes(b"SYNTHETIC damaged SQLite database" * 100)
        write_manifest(source, [entry(source, "library.sqlite")])
    target = Settings(data_dir=tmp_path / "restored")
    real_copy = backup.shutil.copyfile
    replaced = []
    real_replace = backup.os.replace
    real_connect = sqlite3.connect
    closed = []

    class IntegrityFailure(sqlite3.Connection):
        def close(self):
            super().close()
            closed.append(True)

    def connect(path, *args, **kwargs):
        if damage == "integrity" and str(path).endswith(".restoring"):
            kwargs["factory"] = IntegrityFailure
        return real_connect(path, *args, **kwargs)

    def copy(src, dest, *args, **kwargs):
        result = real_copy(src, dest, *args, **kwargs)
        if str(dest).endswith(".restoring"):
            if damage == "text":
                with sqlite3.connect(dest) as conn:
                    assert conn.execute("UPDATE researches SET title = 'SYNTHETIC changed title'").rowcount == 1
                    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return result

    def replace(src, dest):
        replaced.append((src, dest))
        return real_replace(src, dest)

    monkeypatch.setattr(backup.shutil, "copyfile", copy)
    monkeypatch.setattr(backup.os, "replace", replace)
    monkeypatch.setattr(backup.sqlite3, "connect", connect)
    with pytest.raises((backup.BackupError, sqlite3.DatabaseError)) as caught:
        backup.restore_backup(source, target)
    if damage == "text":
        assert isinstance(caught.value, backup.BackupError)
        assert str(caught.value) == "restored database does not match the manifest"
    else:
        assert closed == [True]
    assert not target.db_path.exists()
    assert not target.db_path.with_name("library.sqlite.restoring").exists()
    assert replaced == []


@pytest.mark.parametrize("error_number", [28, 13])
@pytest.mark.parametrize("operation", ["check", "serve", "reextract"])
def test_temporary_directory_failure_is_a_controlled_refusal(
    tmp_path, monkeypatch, capsys, fake_uvicorn, error_number, operation,
):
    path = library_with_id_only_in_the_wal(tmp_path / "data")
    before = file_facts(path.parent), folder_names(path.parent)

    def fail(*args, **kwargs):
        raise OSError(error_number, "SYNTHETIC temp directory unavailable")

    monkeypatch.setattr(db.tempfile, "TemporaryDirectory", fail)
    monkeypatch.setattr(launcher, "create_app", lambda *a, **k: pytest.fail("app created"))
    monkeypatch.setattr(launcher, "port_available", lambda *a: True)  # FakeServer never binds a socket.
    if operation == "check":
        with pytest.raises(db.SchemaCheckUnreadable, match="free some disk space or fix the permissions"):
            db.check_schema_known(path)
    else:
        settings = settings_for(path.parent, 8980)
        result = launcher.serve(settings, False, ()) if operation == "serve" else launcher.reextract(settings, True)
        assert result == 2
        err = capsys.readouterr().err
        assert len(err.splitlines()) == 1
        assert "free some disk space or fix the permissions" in err and "Traceback" not in err
    assert fake_uvicorn.instances == []
    assert (file_facts(path.parent), folder_names(path.parent)) == before


@pytest.mark.parametrize("which", ["before", "after"])
def test_schema_copy_stat_failure_is_controlled(tmp_path, monkeypatch, which):
    from pathlib import Path

    path = library_with_id_only_in_the_wal(tmp_path / "data")
    before = file_facts(path.parent), folder_names(path.parent)
    real_stat, calls = Path.stat, []

    def stat(self, *args, **kwargs):
        if self == path:
            calls.append(self)
            if len(calls) == (1 if which == "before" else 2):
                raise OSError(13, "SYNTHETIC stat unavailable")
        return real_stat(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        with pytest.raises(db.SchemaCheckUnreadable, match="fix the permissions"):
            db._applied_versions_from_copy(path)
    assert (file_facts(path.parent), folder_names(path.parent)) == before


def test_startup_message_preserves_finished_migrations(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_first.sql").write_text("CREATE TABLE first_table (value BLOB);\n")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    path = tmp_path / "data" / "library.sqlite"
    conn = db.connect(path)
    assert db.migrate(conn) == [1]
    conn.close()
    (migrations / "0002_full.sql").write_text("INSERT INTO first_table VALUES (zeroblob(1000000));\n")
    real_connect = db.connect
    codes = []

    def limited(path):
        conn = real_connect(path)
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count = {pages}")
        return conn

    real_describe = db.describe_failure

    def describe(exc):
        codes.append(exc.sqlite_errorcode)
        return real_describe(exc)

    monkeypatch.setattr(db, "connect", limited)
    monkeypatch.setattr(db, "describe_failure", describe)
    message = db.open_problem(path)
    assert codes == [13]
    assert "did not start" in message and "stays applied" in message
    assert "changed nothing" not in message
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'first_table'").fetchone() == ("first_table",)
