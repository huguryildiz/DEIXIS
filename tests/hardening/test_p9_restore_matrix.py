"""P9 H4: restore matrix. Backup and restore compared over every table and every file; the negative cases of restore;
a restore cut half way; the schema guard for a library written by a newer DEIXIS; what a restored library says about the
model connection. SYNTHETIC records, a test-only FakeAdapter, no network and no real model.

In-process. The real-process counterparts (F03 restore part, F10, a real launcher on a newer library, a restore killed
half way) are in `tests/process/test_p9_restore_process.py`.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deixis import __main__ as deixis_main
from deixis.config import Settings
from deixis.storage import backup as backup_module
from deixis.storage import db
from deixis.storage.backup import BackupError, MANIFEST, create_backup, restore_backup
from p9_restore_compare import compare_states, library_state, sha256_file, tree_snapshot

REPO = Path(__file__).resolve().parents[2]


# ---- small hand-made backups --------------------------------------------------------------------------------------


def make_source_library(folder: Path) -> Path:
    """A migrated library with one research, closed cleanly (no -wal), journal mode DELETE like a real backup."""
    from deixis.workflow.store import Store

    folder.mkdir(parents=True, exist_ok=True)
    conn = db.connect(folder / "library.sqlite")
    db.migrate(conn)
    Store(conn).create_research("SYNTHETIC question", "attached", "quick", [], "fake", "fake-model", "en")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()
    return folder / "library.sqlite"


def write_manifest(folder: Path, files: list[dict], **fields) -> None:
    manifest = {"format": backup_module.FORMAT, "created_at": "SYNTHETIC", "schema_versions": [], "files": files, "not_included": []}
    manifest.update(fields)
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def entry(folder: Path, rel: str) -> dict:
    return {"path": rel, "sha256": sha256_file(folder / rel), "bytes": (folder / rel).stat().st_size}


def hand_backup(tmp: Path, papers: int = 3, payloads: int = 2) -> Path:
    """A complete backup folder made by hand: the database and `papers + payloads` small files, manifest last."""
    folder = tmp / "backup"
    folder.mkdir(parents=True)
    shutil.copyfile(make_source_library(tmp / "source"), folder / "library.sqlite")
    rels = ["library.sqlite"]
    for n in range(papers):
        (folder / "papers").mkdir(exist_ok=True)
        (folder / "papers" / f"SYNTHETIC-{n}.pdf").write_bytes(f"%PDF SYNTHETIC paper {n} ".encode() * 40)
        rels.append(f"papers/SYNTHETIC-{n}.pdf")
    for n in range(payloads):
        (folder / "provider-payloads").mkdir(exist_ok=True)
        (folder / "provider-payloads" / f"SYNTHETIC-{n}.json").write_bytes(json.dumps({"n": n, "text": "SYNTHETIC " * 50}).encode())
        rels.append(f"provider-payloads/SYNTHETIC-{n}.json")
    write_manifest(folder, [entry(folder, r) for r in rels])
    return folder


def manifest_of(folder: Path) -> dict:
    return json.loads((folder / MANIFEST).read_text())


def refused(backup: Path, target: Path, fragment: str) -> None:
    """restore raises BackupError naming `fragment` and leaves the target tree exactly as it was."""
    before = (target.exists(), tree_snapshot(target))
    with pytest.raises(BackupError, match=fragment):
        restore_backup(backup, Settings(data_dir=target, port=8765))
    assert (target.exists(), tree_snapshot(target)) == before, "the failed restore changed the target"


# ---- B01n ---------------------------------------------------------------------------------------------------------


def test_b01n_target_that_already_holds_a_library_is_refused_unchanged(tmp_path):
    backup = hand_backup(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "library.sqlite").write_bytes(b"SYNTHETIC existing library")
    refused(backup, target, "already exists")


@pytest.mark.parametrize("name", ["library.sqlite-wal", "library.sqlite-shm"])
def test_b01n_target_with_only_a_wal_or_shm_is_ambiguous_and_refused_unchanged(tmp_path, name):
    backup = hand_backup(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / name).write_bytes(b"SYNTHETIC leftover")
    refused(backup, target, "already exists")


@pytest.mark.parametrize("which", ["first", "middle"])
def test_b01n_target_file_with_the_same_name_and_a_different_hash_is_refused_before_anything_is_written(tmp_path, which):
    """The middle case fails on code that checks each target file inside the copy loop: earlier files and papers/ exist by then."""
    backup = hand_backup(tmp_path, papers=4, payloads=3)
    names = [e["path"] for e in manifest_of(backup)["files"] if e["path"] != "library.sqlite"]
    clash = names[0] if which == "first" else names[len(names) // 2]
    assert which == "first" or names.index(clash) > 0
    target = tmp_path / "target"
    (target / Path(clash).parent).mkdir(parents=True)
    (target / clash).write_bytes(b"SYNTHETIC a different file")
    refused(backup, target, "different file already exists")


def test_b01n_target_that_already_holds_the_same_file_accepts_it_and_keeps_it(tmp_path):
    backup = hand_backup(tmp_path)
    kept = "papers/SYNTHETIC-1.pdf"
    target = tmp_path / "target"
    (target / "papers").mkdir(parents=True)
    shutil.copyfile(backup / kept, target / kept)
    before = (target / kept).stat()
    result = restore_backup(backup, Settings(data_dir=target, port=8765))
    after = (target / kept).stat()
    assert result["files"] == len(manifest_of(backup)["files"])
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns), "the identical file was rewritten"
    assert compare_states(library_state(backup), library_state(target)) == []


@pytest.mark.parametrize("rel", ["papers/SYNTHETIC-1.pdf", "provider-payloads/SYNTHETIC-0.json", "library.sqlite"])
def test_b01n_backup_file_missing_or_changed_is_refused_unchanged(tmp_path, rel):
    for how in ("missing", "changed"):
        backup = hand_backup(tmp_path / how)
        if how == "missing":
            (backup / rel).unlink()
        else:
            data = bytearray((backup / rel).read_bytes())
            data[len(data) // 2] ^= 1
            (backup / rel).write_bytes(bytes(data))
        refused(backup, tmp_path / how / "target", "missing or changed")


def test_b01n_folder_without_a_manifest_is_refused_unchanged(tmp_path):
    backup = hand_backup(tmp_path)
    (backup / MANIFEST).unlink()
    refused(backup, tmp_path / "target", "not a complete DEIXIS backup")


def test_b01n_manifest_with_a_wrong_format_is_refused_unchanged(tmp_path):
    backup = hand_backup(tmp_path)
    write_manifest(backup, manifest_of(backup)["files"], format="deixis-backup-v0")
    refused(backup, tmp_path / "target", "unsupported backup format")


@pytest.mark.parametrize("bad", ["../x", "papers/a/b.pdf", "/etc/hosts", "other/x.pdf", "papers/..", ""])
def test_b01n_manifest_path_that_escapes_is_refused_unchanged(tmp_path, bad):
    backup = hand_backup(tmp_path)
    files = manifest_of(backup)["files"] + [{"path": bad, "sha256": "0" * 64, "bytes": 1}]
    write_manifest(backup, files)
    refused(backup, tmp_path / "target", "unexpected path in manifest")


def test_b01n_manifest_without_the_database_entry_is_refused_unchanged(tmp_path):
    backup = hand_backup(tmp_path)
    write_manifest(backup, [e for e in manifest_of(backup)["files"] if e["path"] != "library.sqlite"])
    refused(backup, tmp_path / "target", "no library database")


def test_b01n_truncated_manifest_is_refused_unchanged(tmp_path):
    backup = hand_backup(tmp_path)
    text = (backup / MANIFEST).read_text()
    (backup / MANIFEST).write_text(text[: len(text) // 2])
    refused(backup, tmp_path / "target", "not a complete DEIXIS backup")


@pytest.mark.parametrize("shape", ["list", "no_files", "files_not_a_list", "entry_without_path", "entry_without_sha256", "entry_not_an_object"])
def test_b01n_manifest_with_a_wrong_shape_is_a_backup_error_not_a_traceback(tmp_path, shape):
    backup = hand_backup(tmp_path)
    good = manifest_of(backup)
    bad = {"list": [1, 2], "no_files": {"format": good["format"]}, "files_not_a_list": good | {"files": {"a": 1}},
           "entry_without_path": good | {"files": good["files"] + [{"sha256": "0" * 64}]},
           "entry_without_sha256": good | {"files": good["files"] + [{"path": "papers/x.pdf"}]},
           "entry_not_an_object": good | {"files": good["files"] + ["papers/x.pdf"]}}[shape]
    (backup / MANIFEST).write_text(json.dumps(bad))
    refused(backup, tmp_path / "target", "not a complete DEIXIS backup")


# ---- restore atomicity (unit) -------------------------------------------------------------------------------------


class CutCopy:
    """Stands in for `backup.shutil`: the nth `copyfile` writes half the source to its destination and raises KeyboardInterrupt."""

    def __init__(self, nth: int):
        self.nth, self.calls = nth, 0

    def __getattr__(self, name):
        return getattr(shutil, name)

    def copyfile(self, src, dst, **kwargs):
        self.calls += 1
        if self.calls == self.nth:
            data = Path(src).read_bytes()
            Path(dst).write_bytes(data[: len(data) // 2])
            raise KeyboardInterrupt("SYNTHETIC cut")
        return shutil.copyfile(src, dst, **kwargs)


def wrong_files(target: Path, backup: Path) -> list[str]:
    """Files under a final name in papers/ or provider-payloads/ whose hash differs from the manifest."""
    wanted = {e["path"]: e["sha256"] for e in manifest_of(backup)["files"]}
    bad = []
    for sub in ("papers", "provider-payloads"):
        for path in sorted((target / sub).glob("*")) if (target / sub).exists() else []:
            rel = f"{sub}/{path.name}"
            if path.name.startswith(".restoring-") or path.name.endswith(".part"):
                continue
            if wanted.get(rel) != sha256_file(path):
                bad.append(rel)
    return bad


@pytest.mark.parametrize("nth", [1, 3])
def test_a_restore_cut_inside_a_file_copy_leaves_no_half_file_and_can_be_run_again(tmp_path, monkeypatch, nth):
    backup = hand_backup(tmp_path, papers=3, payloads=2)
    target = tmp_path / "target"
    monkeypatch.setattr(backup_module, "shutil", CutCopy(nth))
    with pytest.raises(KeyboardInterrupt):
        restore_backup(backup, Settings(data_dir=target, port=8765))
    monkeypatch.setattr(backup_module, "shutil", shutil)
    assert wrong_files(target, backup) == [], "a half file under a final name"
    assert sorted(p.name for p in target.rglob(".restoring-*")) == [] and sorted(p.name for p in target.rglob("*.part")) == []
    assert not (target / "library.sqlite").exists() and not (target / "library.sqlite.restoring").exists()

    result = restore_backup(backup, Settings(data_dir=target, port=8765))
    assert result["files"] == 6
    assert compare_states(library_state(backup), library_state(target)) == []


def test_a_restore_leftover_part_file_is_removed_by_the_next_restore(tmp_path):
    """A SIGKILL leaves the `.restoring-*.part` file (nothing can remove it); the next restore starts clean, and a download's
    `tmp*.part` in the same folder is not touched."""
    backup = hand_backup(tmp_path)
    target = tmp_path / "target"
    (target / "papers").mkdir(parents=True)
    (target / "provider-payloads").mkdir()
    (target / "papers" / ".restoring-abc.part").write_bytes(b"SYNTHETIC half")
    (target / "provider-payloads" / ".restoring-def.part").write_bytes(b"SYNTHETIC half")
    (target / "papers" / "tmpdownload.part").write_bytes(b"SYNTHETIC a download in progress")
    restore_backup(backup, Settings(data_dir=target, port=8765))
    assert not list(target.rglob(".restoring-*"))
    assert (target / "papers" / "tmpdownload.part").read_bytes() == b"SYNTHETIC a download in progress"


def test_restored_files_get_the_permissions_a_plain_copy_gets(tmp_path):
    import stat

    backup = hand_backup(tmp_path)
    target = tmp_path / "target"
    restore_backup(backup, Settings(data_dir=target, port=8765))
    shutil.copyfile(backup / "papers" / "SYNTHETIC-0.pdf", tmp_path / "plain-copy")
    plain = stat.S_IMODE((tmp_path / "plain-copy").stat().st_mode)
    for rel in ("papers/SYNTHETIC-0.pdf", "provider-payloads/SYNTHETIC-1.json", "library.sqlite"):
        assert stat.S_IMODE((target / rel).stat().st_mode) == plain, rel


def test_a_restored_file_whose_copy_differs_from_the_manifest_is_refused_and_its_temporary_file_removed(tmp_path, monkeypatch):
    """The source passed the hash check, then changed (or the copy was corrupted): the destination is never replaced."""
    backup = hand_backup(tmp_path)
    target = tmp_path / "target"

    class Corrupt(CutCopy):
        def copyfile(self, src, dst, **kwargs):
            self.calls += 1
            shutil.copyfile(src, dst)
            if self.calls == 2:
                with open(dst, "ab") as handle:
                    handle.write(b"X")
            return dst

    monkeypatch.setattr(backup_module, "shutil", Corrupt(0))
    with pytest.raises(BackupError, match="does not match"):
        restore_backup(backup, Settings(data_dir=target, port=8765))
    monkeypatch.setattr(backup_module, "shutil", shutil)
    assert wrong_files(target, backup) == [] and not list(target.rglob(".restoring-*"))
    assert not (target / "library.sqlite").exists()


# ---- B03: a library written by a newer DEIXIS ---------------------------------------------------------------------


def migrated_library(path: Path) -> Path:
    conn = db.connect(path)
    db.migrate(conn)
    conn.close()  # the last connection to close checkpoints and removes the -wal
    return path


def add_versions(path: Path, *versions: int) -> None:
    conn = sqlite3.connect(path)
    for v in versions:
        conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)", (v, f"{v:04d}_future.sql", "SYNTHETIC"))
    conn.commit()
    conn.close()


def folder_names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def file_facts(folder: Path, names=("library.sqlite", "library.sqlite-wal", "library.sqlite-shm")) -> dict:
    return {n: ((folder / n).stat().st_size, sha256_file(folder / n)) if (folder / n).exists() else None for n in names}


PACKAGED_VERSIONS = db.packaged_versions()
LAST = max(PACKAGED_VERSIONS)
UNKNOWN_CASES = {"a_next": ([LAST + 1], [f"{LAST + 1:04d}"]), "b_far": ([9999], ["9999"]),
                 "c_below_range": ([0], ["0000"]),
                 "d_two": ([LAST + 1, 9999], [f"{LAST + 1:04d}", "9999"])}


@pytest.mark.parametrize("case", sorted(UNKNOWN_CASES))
def test_b03_unknown_migration_id_is_refused_and_no_file_changes(tmp_path, case):
    versions, shown = UNKNOWN_CASES[case]
    path = migrated_library(tmp_path / "lib" / "library.sqlite")
    add_versions(path, *versions)
    folder = path.parent
    before_files, before_names = file_facts(folder), folder_names(folder)
    assert "library.sqlite-wal" not in before_names
    for call in (lambda: db.check_schema_known(path), lambda: db.connect(path)):
        with pytest.raises(db.UnknownSchemaError) as caught:
            call()
        assert all(v in str(caught.value) for v in shown), str(caught.value)
        assert "newer DEIXIS" in str(caught.value) and "Nothing was changed" in str(caught.value)
    assert file_facts(folder) == before_files and folder_names(folder) == before_names


def test_b03_library_from_an_older_code_opens_and_migrate_applies_exactly_the_missing_migration(tmp_path, monkeypatch):
    real_dir = db.MIGRATIONS_DIR
    older = tmp_path / "older-migrations"
    older.mkdir()
    for p in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(p.name.split("_", 1)[0]) < LAST:
            shutil.copyfile(p, older / p.name)
    path = tmp_path / "lib" / "library.sqlite"
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    conn = db.connect(path)
    assert db.migrate(conn) == sorted(PACKAGED_VERSIONS - {LAST})
    conn.close()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real_dir)
    assert db.packaged_versions() == PACKAGED_VERSIONS
    db.check_schema_known(path)  # known ids only: nothing to refuse
    conn = db.connect(path)
    try:
        assert db.migrate(conn) == [LAST]
    finally:
        conn.close()


def test_b03_clean_library_nothing_to_refuse_and_missing_or_empty_files_return_at_once(tmp_path):
    db.check_schema_known(tmp_path / "does-not-exist" / "library.sqlite")
    empty = tmp_path / "empty.sqlite"
    empty.write_bytes(b"")
    db.check_schema_known(empty)
    assert empty.stat().st_size == 0 and folder_names(tmp_path) == ["empty.sqlite"]
    bare = tmp_path / "bare" / "library.sqlite"
    bare.parent.mkdir()
    conn = sqlite3.connect(bare)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    db.check_schema_known(bare)  # no schema_migrations table: nothing to compare
    ok = migrated_library(tmp_path / "ok" / "library.sqlite")
    db.check_schema_known(ok)
    assert folder_names(ok.parent) == ["library.sqlite"]


def test_b03_path_with_hash_question_mark_and_space(tmp_path):
    path = migrated_library(tmp_path / "dir #1 ?x y" / "library.sqlite")
    add_versions(path, 9999)
    before_files, before_names = file_facts(path.parent), folder_names(path.parent)
    with pytest.raises(db.UnknownSchemaError, match="9999"):
        db.check_schema_known(path)
    assert file_facts(path.parent) == before_files and folder_names(path.parent) == before_names
    assert folder_names(tmp_path) == ["dir #1 ?x y"], "a stray file was created next to the folder"


def test_b03_corrupt_library_still_raises_a_database_error_not_the_schema_error(tmp_path):
    path = tmp_path / "library.sqlite"
    path.write_bytes(b"SYNTHETIC this is not a database " * 200)
    with pytest.raises(sqlite3.DatabaseError) as caught:
        db.check_schema_known(path)
    assert not isinstance(caught.value, db.UnknownSchemaError)


CHILD = """
import os, sys
sys.path[:0] = [sys.argv[2]]
from pathlib import Path
from deixis.storage import db
conn = db.connect(Path(sys.argv[1]))
conn.execute("PRAGMA wal_autocheckpoint = 0")
conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (9999, '9999_future.sql', 'SYNTHETIC')")
os._exit(0)  # no checkpoint, no close: the committed row lives only in the -wal
"""


def library_with_id_only_in_the_wal(folder: Path) -> Path:
    path = migrated_library(folder / "library.sqlite")
    subprocess.run([sys.executable, "-c", CHILD, str(path), str(REPO / "backend")], check=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(folder), "PYTHONPATH": str(REPO / "backend")})
    assert (folder / "library.sqlite-wal").stat().st_size > 0 and (folder / "library.sqlite-shm").exists()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        in_main = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    assert in_main == PACKAGED_VERSIONS,"the main file alone must not hold the unknown id"
    return path


def test_b03_unknown_id_that_exists_only_in_the_wal_is_refused_and_main_wal_and_shm_are_untouched(tmp_path):
    path = library_with_id_only_in_the_wal(tmp_path / "lib")
    folder = path.parent
    before_files, before_names = file_facts(folder), folder_names(folder)
    assert before_files["library.sqlite-shm"] is not None
    for call in (lambda: db.check_schema_known(path), lambda: db.connect(path)):
        with pytest.raises(db.UnknownSchemaError, match="9999"):
            call()
    assert file_facts(folder) == before_files and folder_names(folder) == before_names
    print("B03 -shm:", before_files["library.sqlite-shm"][0], "bytes, hash unchanged after two refusals")


def test_b03_a_torn_copy_is_tried_again_and_three_torn_copies_say_so(tmp_path, monkeypatch):
    path = library_with_id_only_in_the_wal(tmp_path / "lib")
    real = db._copy_live_files

    def tear(times):
        calls = []

        def torn(source, folder):
            copy = real(source, folder)
            calls.append(1)
            if len(calls) <= times:
                data = copy.read_bytes()
                copy.write_bytes(b"SYNTHETIC torn" + data[100:])
            return copy
        return torn, calls

    torn, calls = tear(1)
    monkeypatch.setattr(db, "_copy_live_files", torn)
    with pytest.raises(db.UnknownSchemaError, match="9999"):
        db.check_schema_known(path)
    assert len(calls) == 2, "one torn copy, then a good one"

    torn, calls = tear(3)
    monkeypatch.setattr(db, "_copy_live_files", torn)
    with pytest.raises(db.SchemaCheckUnreadable, match="try again with DEIXIS stopped"):
        db.check_schema_known(path)
    assert len(calls) == 3


def test_b03_main_file_changing_while_it_is_copied_counts_as_torn(tmp_path, monkeypatch):
    path = library_with_id_only_in_the_wal(tmp_path / "lib")
    real, calls = db._copy_live_files, []

    def moving(source, folder):
        copy = real(source, folder)
        calls.append(1)
        if len(calls) == 1:  # a checkpoint rewrote the main file between our two reads
            os.utime(source, ns=(time.time_ns(), time.time_ns()))
        return copy

    monkeypatch.setattr(db, "_copy_live_files", moving)
    with pytest.raises(db.UnknownSchemaError):
        db.check_schema_known(path)
    assert len(calls) == 2


def test_b03_the_backup_command_still_rescues_a_library_written_by_a_newer_version(tmp_path):
    """Reading such a library to save it is allowed: create_backup does not run the schema check. Done after the hash checks above."""
    path = migrated_library(tmp_path / "data" / "library.sqlite")
    add_versions(path, 9999)
    backup = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "out")
    result = restore_backup(backup, Settings(data_dir=tmp_path / "restored", port=8765))
    assert 9999 in result["schema_versions"]
    with pytest.raises(db.UnknownSchemaError):
        db.connect(tmp_path / "restored" / "library.sqlite")


# ---- the launcher refuses before it binds anything ----------------------------------------------------------------


def settings_for(data: Path, port: int) -> Settings:
    return Settings(data_dir=data, port=port, model_concurrency=1)


def free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeServer:
    instances: list = []

    def __init__(self, config):
        self.config, self.started, self.should_exit = config, True, False
        FakeServer.instances.append(self)

    def run(self):
        pass


@pytest.fixture
def fake_uvicorn(monkeypatch):
    FakeServer.instances = []
    monkeypatch.setattr(deixis_main.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(deixis_main, "watch_shutdown", lambda *a, **k: None)  # its forced exit must never run in a test
    return FakeServer


def test_serve_on_a_library_written_by_a_newer_version_returns_2_without_creating_the_server(tmp_path, monkeypatch, capsys, fake_uvicorn):
    data = tmp_path / "data"
    add_versions(migrated_library(data / "library.sqlite"), 9999)
    monkeypatch.setattr(deixis_main, "create_app", lambda *a, **k: pytest.fail("the app was created"))
    before_files, before_names = file_facts(data), folder_names(data)
    assert deixis_main.serve(settings_for(data, free_port()), False, ()) == 2
    err = capsys.readouterr().err
    assert "newer DEIXIS" in err and "9999" in err and "Traceback" not in err
    assert fake_uvicorn.instances == []
    assert file_facts(data) == before_files and folder_names(data) == before_names


def test_serve_on_an_unreadable_check_returns_2_with_the_message(tmp_path, monkeypatch, capsys, fake_uvicorn):
    data = tmp_path / "data"
    migrated_library(data / "library.sqlite")

    def unreadable(path):
        raise db.SchemaCheckUnreadable("SYNTHETIC could not read; try again with DEIXIS stopped.")

    monkeypatch.setattr(deixis_main, "check_schema_known", unreadable)
    assert deixis_main.serve(settings_for(data, free_port()), False, ()) == 2
    assert "try again with DEIXIS stopped" in capsys.readouterr().err and fake_uvicorn.instances == []


def test_a_failing_copy_of_the_library_is_one_message_not_a_traceback(tmp_path, monkeypatch, capsys, fake_uvicorn):
    path = library_with_id_only_in_the_wal(tmp_path / "data")

    def full_disk(source, folder):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(db, "_copy_live_files", full_disk)
    with pytest.raises(db.SchemaCheckUnreadable, match="No space left on device"):
        db.check_schema_known(path)
    monkeypatch.setattr(deixis_main, "create_app", lambda *a, **k: pytest.fail("the app was created"))
    assert deixis_main.serve(settings_for(path.parent, free_port()), False, ()) == 2
    err = capsys.readouterr().err
    assert "No space left on device" in err and "Traceback" not in err and fake_uvicorn.instances == []


def test_serve_on_a_normal_library_reaches_the_server(tmp_path, fake_uvicorn):
    data = tmp_path / "data"
    migrated_library(data / "library.sqlite")
    assert deixis_main.serve(settings_for(data, free_port()), False, ()) == 0
    assert len(fake_uvicorn.instances) == 1


def test_serve_on_a_new_data_directory_reaches_the_server(tmp_path, fake_uvicorn):
    assert deixis_main.serve(settings_for(tmp_path / "fresh", free_port()), False, ()) == 0
    assert len(fake_uvicorn.instances) == 1


def test_reextract_on_a_library_written_by_a_newer_version_returns_2_and_changes_nothing(tmp_path, capsys):
    data = tmp_path / "data"
    add_versions(migrated_library(data / "library.sqlite"), 9999)
    before_files, before_names = file_facts(data), folder_names(data)
    assert deixis_main.reextract(settings_for(data, 8765), True) == 2
    assert "newer DEIXIS" in capsys.readouterr().err
    assert file_facts(data) == before_files and folder_names(data) == before_names


def test_reextract_on_a_normal_library_still_runs(tmp_path, capsys):
    data = tmp_path / "data"
    migrated_library(data / "library.sqlite")
    assert deixis_main.reextract(settings_for(data, 8765), True) == 0
    assert "0 PDFs" in capsys.readouterr().out


# ---- B01: one rich library, backup while the app runs, restore, compare everything ---------------------------------


@contextmanager
def rich_library(tmp_path: Path):
    """One data directory that reaches as many tables as the existing builders can, composed in this order:
    report with claim links and edit checks (store level), candidates and lineage (store level), then the API flow with
    FakeAdapter (academic discovery, selections, upload, answer, answer review, evidence table, removal, trash)."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from helpers import make_pdf
    from test_api_flow import app_for, create, session, wait_run
    from test_candidate_store import make_library as candidate_library, publish, query, start, version, with_hits
    from test_corpus_removal import search_found_again, upload
    from test_evidence_tables import table_with_edit
    from test_lineage_store import edit as lineage_edit, human, model, remove as lineage_remove
    from test_report_assembly import report_with_sections
    from test_report_claim_links import edit as claim_edit, three_links
    from test_report_edit_check import finish

    settings = Settings(data_dir=tmp_path / "data", port=8765)
    settings.data_dir.mkdir()

    fixture = report_with_sections.__wrapped__(settings.data_dir)
    lib = next(fixture)
    try:
        ids = three_links(lib)
        rid = finish(lib)
        claim_edit(lib, link_ids=ids[:2])
        claim_edit(lib, restore_from="model")
        claim_edit(lib, "abstract.1", link_ids=[])
        lib["reports"].check_edits(rid, lib["report_id"])
    finally:
        with pytest.raises(StopIteration):
            next(fixture)

    settings.payloads_dir.mkdir(exist_ok=True)
    for name in ("SYNTHETIC-query.json", "SYNTHETIC-failed.json"):
        (settings.payloads_dir / name).write_text("SYNTHETIC payload")
    lib = candidate_library(settings.db_path)
    try:
        v = version(lib)
        s, records = with_hits(lib, v, raw_payload_path="SYNTHETIC-query.json")
        publish(lib, s, records, whole=True)
        lib.candidate_store.finish_kill_search(s["id"], "completed")
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], "open", "SYNTHETIC owner reason")
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], "closed", "SYNTHETIC second reason")
        lib.candidate_store.trash_candidate(lib.rid, v["candidate_id"])
        query(lib, start(lib, v), [], status="failed", raw_payload_path="SYNTHETIC-failed.json")
        model(lib)
        lineage_edit(lib)
        lineage_remove(lib)
        human(lib, "c", "d")
    finally:
        lib.conn.close()

    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        assert client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "fake-model"}).status_code == 200
        rid = create(client, source_scope="attached_and_academic", review_mode="custom", review_connection="fake", review_model="fake-model")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        relay = next(s for s in view["sources"] if "relay" in s["title"])
        client.patch(f"/api/researches/{rid}/selections/{relay['source_version_id']}",
                     json={"state": "excluded", "expected_version": relay["selection"]["version"], "reason": "not about scheduling"})
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded notes."]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        wait_run(client, rid, run["id"])
        # an evidence table with a human edit, a removed source that a later search finds again, a trashed research
        table = table_with_edit(client, rid)
        assert client.post("/api/table-templates", json={"research_id": rid, "table_id": table, "name": "SYNTHETIC packets"}).status_code == 201
        gone = upload(client, rid, "gone.pdf", "SYNTHETIC a report taken out of this research.")["source_version_id"]
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [gone], "note": "SYNTHETIC off topic"}).status_code == 200
        search_found_again(store, rid, gone)
        other = create(client, source_scope="attached")
        assert client.delete(f"/api/researches/{other}").status_code == 200
        time.sleep(0.5)  # background answer review and any other idle writes settle
        # Recovery evidence is part of the rich round trip, including retained bytes.
        from tests.reextract.reextract_r2a_helpers import seed
        from tests.reextract.reextract_r2b_helpers import tear, write
        recovery = seed(store, settings, "partial")
        tear(recovery)
        write(recovery)
        yield SimpleNamespace(settings=settings, client=client, app=app, rid=rid, other=other)




# Tables the rich library leaves empty, each with the reason the existing builders do not reach it. A table that is empty
# and not named here fails the test, so a table a later migration adds is noticed; a named table that gained rows fails too.
EMPTY_BECAUSE = {
    "arxiv_sources": "arXiv source reading is off in the test settings",
    "asset_arxiv_versions": "written only by the optional equation reader (Marker), which is not installed",
    "chain_links": "citation chaining is off in the test settings",
    "fast_path_background_fetches": "fast-path reading (D251) is off in the test settings",
    "fast_path_embedding_queue": "fast-path search (D252) is off in the test settings",
    "fast_path_intervals": "fast-path accounting (D250) is off in the test settings",
    "fast_path_ledgers": "fast-path accounting (D250) is off in the test settings",
    "fast_path_late_revisions": "fast-path late revisions (D255) are off in the test settings",
    "fast_path_stages": "fast-path accounting (D250) is off in the test settings",
    "human_selection_links": "written only by human decisions in the screening queue, which this flow does not make",
    "openalex_budget_runs": "written only when OpenAlex's daily budget refuses a PDF lookup; the fake providers never do",
    "owner_review_snapshots": "no review can be started until B2",
    "owner_reviews": "no review can be started until B2",
    "owner_review_findings": "no review can be started until B2",
    "owner_review_decisions": "no review can be started until B2",
    "passage_embeddings": "needs an embedding model; none is configured",
    "pdf_candidates": "written when a PDF fetch is refused and another open copy is looked up; the fake fetcher never refuses",
    "pdf_discovery_runs": "same lookup as pdf_candidates",
    "person_pdf_requests": "written by the 'read it yourself' person-reading flow, not exercised here",
    "record_flags": "written by record lookups (workflow/lookups.py), not run here",
    "record_links": "written by record linking (workflow/links.py), not run here",
    "record_lookups": "written by record lookups, not run here",
    "record_references": "reference lists arrive with citation chaining or lookups, both off",
    "report_stale_acknowledgements": "written only when a person acknowledges stale report changes after an upstream edit",
    "research_purge_authorizations": "a temporary row opened and removed inside the purge transaction",
    "recovery_purge_authorizations": "a temporary row opened and removed inside the recovery purge transaction",
    "scope_english_questions": "written only for a non-English question that gets an English rendering",
    "source_similarities": "written by the semantic ranking step, which needs an embedding model",
    "suspected_duplicates": "written only when two sources look like duplicates of one work",
    "table_purge_authorizations": "a temporary row opened and removed inside the table purge",
    "watches": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_checks": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_reads": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_seen": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_seen_alias": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_items": "the rich library builder starts no follow-up watch (P8 B5 adds no builder)",
    "watch_gaps": "the rich library builder starts no interval watch, so no scheduling gap is recorded",
    "watch_schedule_changes": "the rich library builder changes no follow-up watch schedule",
}


def restored_app(settings: Settings):
    """The restored library opened the way B02 will open a copy: no worker, no adapters that can reach a model, no network."""
    import httpx
    from deixis.api.app import create_app
    from fakes import FakeAdapter
    from test_api_flow import fake_fetch

    def no_network(request):
        raise AssertionError(f"restored app tried to reach {request.url}")

    return create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(no_network)),
                      fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)


def keys_named(value, name: str, found: set | None = None) -> set:
    found = set() if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            if k == name and isinstance(v, str):
                found.add(v)
            keys_named(v, name, found)
    elif isinstance(value, list):
        for item in value:
            keys_named(item, name, found)
    return found


def anchor_pairs(value, found: list | None = None) -> list:
    """(passage_id, anchor_text) of every object in a view that holds both."""
    found = [] if found is None else found
    if isinstance(value, dict):
        if isinstance(value.get("passage_id"), str) and isinstance(value.get("anchor_text"), str):
            found.append((value["passage_id"], value["anchor_text"]))
        for v in value.values():
            anchor_pairs(v, found)
    elif isinstance(value, list):
        for item in value:
            anchor_pairs(item, found)
    return found


def collect_views(client, research_ids: list[str]) -> dict[str, tuple]:
    """GET every read view of every research and the library-wide lists: {path: (status, body)}."""
    views: dict[str, tuple] = {}

    def get(path: str):
        response = client.get(path)
        body = response.json() if "json" in response.headers.get("content-type", "") else hashlib.sha256(response.content).hexdigest()
        views[path] = (response.status_code, body)
        return views[path]

    for path in ("/api/researches", "/api/library", "/api/trash", "/api/table-templates", "/api/settings"):
        get(path)
    for rid in research_ids:
        base = f"/api/researches/{rid}"
        _, research = get(base)
        passages = keys_named(research, "passage_id")
        for suffix in ("/tables", "/reports", "/candidates", "/bibliography", "/audit", "/queue", "/prisma-s"):
            status, body = get(base + suffix)
            if status != 200:
                continue
            if suffix == "/tables":
                for table in body:
                    get(f"{base}/tables/{table['id']}")
                    get(f"{base}/tables/{table['id']}/lineage")
            elif suffix == "/reports":
                for report in body:
                    _, view = get(f"{base}/reports/{report['id']}")
                    get(f"{base}/reports/{report['id']}/gaps")
                    get(f"{base}/reports/{report['id']}/export")
                    # Freshness also names unresolved IDs; they are diagnostics, not openable citations.
                    passages |= keys_named({k: v for k, v in view.items() if k != "passage_freshness"}, "passage_id")
            elif suffix == "/candidates":
                for item in body:
                    get(f"{base}/candidates/{item['id']}")
        for passage in sorted(passages):
            get(f"{base}/passages/{passage}")
    return views


# Fields removed from both sides before the views are compared. The open of a restored library writes none of the stored
# rows that a view shows (the table comparison above is exact); this one field is the export's own clock, set when the
# view is requested and never stored.
ALLOWED_DIFFERENCES = {"generated_at": "the PRISMA-S export stamps the time of the request (workflow/prisma_s.py), not a stored value"}


def strip(value, names):
    if isinstance(value, dict):
        return {k: strip(v, names) for k, v in value.items() if k not in names}
    if isinstance(value, list):
        return [strip(v, names) for v in value]
    return value


def test_b01_backup_while_the_app_runs_restores_every_table_and_file_and_every_view(tmp_path):
    from fastapi.testclient import TestClient

    with rich_library(tmp_path) as built:
        settings, client = built.settings, built.client
        before = library_state(settings.data_dir)
        empty = sorted(name for name, (rows, _) in before["tables"].items() if rows == 0)
        total, with_rows = len(before["tables"]), len(before["tables"]) - len(empty)
        print(f"B01 coverage: tables total {total}, with rows {with_rows}; empty {len(empty)}: {empty}")
        assert sorted(EMPTY_BECAUSE) == empty, "an empty table without a named reason, or a named table that has rows now"
        assert len(before["files"]) >= 7 and any(p.startswith("papers/") for p in before["files"]) and any(p.startswith("provider-payloads/") for p in before["files"])

        ids = [row[0] for row in sqlite3.connect(settings.db_path).execute("SELECT id FROM researches ORDER BY id")]
        assert built.other in ids and len(ids) >= 3
        views_before = collect_views(client, ids)
        assert sum(1 for status, _ in views_before.values() if status == 200) > 40

        backup = create_backup(settings, tmp_path / "backups")  # the original app is still running
        # The running worker stamps `worker_owner.heartbeat_at` about once a second (workflow/worker.py); that one table is
        # left out of the source comparisons. The backup and the restored folder, where no worker runs, are compared exactly.
        heartbeat = ("worker_owner",)
        assert compare_states(before, library_state(settings.data_dir), allow=heartbeat) == [], "the original library moved while it was idle"
        assert compare_states(before, library_state(backup), allow=heartbeat) == [], "the backup differs from the source it was taken from"

        restored = tmp_path / "restored"
        restore_backup(backup, Settings(data_dir=restored / "data", port=8765))

    # before any server opens the restored directory
    data = restored / "data"
    diffs = compare_states(library_state(backup), library_state(data))
    print(f"B01 compared: {len(before['tables'])} tables (rows and canonical digests), {len(before['files'])} files; differences: {diffs}")
    assert diffs == []
    conn = sqlite3.connect(data.joinpath("library.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == sorted(db.packaged_versions())
    finally:
        conn.close()
    assert sorted(p.name for p in data.iterdir()) == ["library.sqlite", "papers", "provider-payloads"]

    with TestClient(restored_app(Settings(data_dir=data, port=8765, model_concurrency=1, protocol_approval="as_proposed",
                                          search_query="code", fulltext_fetch="off", citation_chaining="off"))) as raw:
        views_after = collect_views(raw, ids)
        assert set(views_after) == set(views_before)
        changed = [path for path in views_before
                   if views_before[path][0] != views_after[path][0]
                   or strip(views_before[path][1], ALLOWED_DIFFERENCES) != strip(views_after[path][1], ALLOWED_DIFFERENCES)]
        print(f"B01 views: {len(views_before)} compared, {len(changed)} differ; allow-list: {sorted(ALLOWED_DIFFERENCES)}")
        assert changed == []
        # every citation anchor of the answers and of the report opens in the restored app, as in the original
        def anchors(views, kind):
            found = []
            for path, (status, body) in views.items():
                if status == 200 and (("/reports/" in path and path.count("/") == 5 and not path.endswith(("gaps", "export")))
                                      if kind == "report" else path.startswith("/api/researches/res_") and path.count("/") == 3):
                    base = path.split("/reports/")[0] if kind == "report" else path
                    for pair in anchor_pairs(body):
                        passage = views.get(f"{base}/passages/{pair[0]}")
                        found.append((pair, passage[0], passage[1]["text"].find(pair[1]) >= 0 if passage and passage[0] == 200 else None))
            return sorted(found, key=repr)

        for kind in ("answer", "report"):
            original, again = anchors(views_before, kind), anchors(views_after, kind)
            print(f"B01 {kind} citation anchors: {len(original)} in the original, {len(again)} in the restored app,"
                  f" located in their passage text: {sum(1 for _, _, ok in again if ok)}")
            assert original == again and original, kind
            assert all(status == 200 and ok is True for _, status, ok in again)
        written = compare_states(library_state(backup), library_state(data))
        print("B01 what opening the restored library wrote (tables that differ from the backup):", written)
        assert written == [], "opening a restored library with no worker wrote to it"
        opened = sum(1 for path, (status, _) in views_after.items() if "/passages/" in path and status == 200)
        print("B01 passage views opened in the restored app:", opened)
        assert opened > 0 and all(status == 200 for path, (status, _) in views_after.items() if "/passages/" in path)


# ---- connections after a restore (plan H4 item 5) ------------------------------------------------------------------


def test_a_restored_library_shows_the_model_connection_as_not_ready_and_pauses_its_runs(tmp_path):
    """Credentials are not in a backup. Original: a research on a connection named `gemini` (a FakeAdapter answers under that
    name). Restored: the same research with the real GeminiAdapter and no key, which needs no network to say it is not ready."""
    import httpx
    from fastapi.testclient import TestClient

    from deixis.api.app import create_app
    from deixis.models.gemini import GeminiAdapter
    from fakes import FakeAdapter
    from test_api_flow import create, fake_fetch, openalex_client, session, sw_settings, wait_run

    def app_with(base: Path, adapter):
        return create_app(sw_settings(base), adapters={"gemini": adapter}, http_client=openalex_client(), fetcher=fake_fetch,
                          extra_hosts=("testserver",), trusted_clients=("testclient",))

    with TestClient(app_with(tmp_path, FakeAdapter())) as raw:
        client = session(raw)
        rid = create(client, model_connection="gemini")
        assert client.get("/api/connections").json()["models"]["gemini"]["ready"] is True
        backup = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")
    assert not any("key" in p.name.lower() or "auth" in p.name.lower() for p in backup.rglob("*"))
    restore_backup(backup, Settings(data_dir=tmp_path / "restored" / "data", port=8765))

    with TestClient(app_with(tmp_path / "restored", GeminiAdapter())) as raw:
        client = session(raw)
        status = client.get("/api/connections").json()["models"]["gemini"]
        print("connections finding: GET /api/connections ->", {k: status[k] for k in ("ready", "reason")})
        assert status["ready"] is False and "Add a Gemini API key in Settings" in status["reason"]
        view = client.get(f"/api/researches/{rid}")
        assert view.status_code == 200 and view.json()["research"]["version"] >= 1, "the restored research must open"
        posted = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
        print("connections finding: POST run ->", posted.status_code)
        _, run = wait_run(client, rid, posted.json()["id"], timeout=90)  # 12 s alone; the default 15 s failed under load
        print("connections finding: a run on the restored research ->", run["status"], run["pause_reason"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")
    labels = (REPO / "apps" / "web" / "src" / "labels.ts").read_text()
    assert "model_connection_not_ready: 'The selected model connection is not ready. Nothing was sent to another model.'" in labels


# ---- B02: a backup of a library that the current code has not migrated yet ------------------------------------------

OLD_LAST = 40  # the schema of a library written on 22 September 2026: no kill_search_queries, passages without later columns


def old_library(tmp_path: Path, monkeypatch, with_paper_file: bool = True) -> Settings:
    """A library migrated only up to 0040 with one paper row; its file is in papers/ unless `with_paper_file` is False."""
    real_dir = db.MIGRATIONS_DIR
    older = tmp_path / "older-migrations"
    older.mkdir()
    for p in sorted(real_dir.glob("*.sql")):
        if int(p.name.split("_", 1)[0]) <= OLD_LAST:
            shutil.copyfile(p, older / p.name)
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    settings.data_dir.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    try:
        conn = db.connect(settings.db_path)
        assert db.migrate(conn) == list(range(1, OLD_LAST + 1))
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'kill_search_queries'").fetchone() is None
        data = b"%PDF SYNTHETIC old paper " * 40
        conn.execute("INSERT INTO works (id, created_at) VALUES ('work-old', 'SYNTHETIC')")
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, created_at)"
                     " VALUES ('sv-old', 'work-old', 'SYNTHETIC old paper', 'user_upload', 'SYNTHETIC')")
        conn.execute("INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, retrieved_at,"
                     " origin, extraction_status) VALUES ('asset-old', 'sv-old', ?, ?, 'application/pdf', 'old-paper.pdf', 'SYNTHETIC',"
                     " 'user_upload', 'succeeded')", (hashlib.sha256(data).hexdigest(), len(data)))
        conn.commit()
        conn.close()
    finally:
        monkeypatch.setattr(db, "MIGRATIONS_DIR", real_dir)
    if with_paper_file:
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        (settings.papers_dir / "old-paper.pdf").write_bytes(data)
    return settings


def test_b02_backup_of_a_library_older_than_the_code_lists_its_paper_restores_and_then_migrates(tmp_path, monkeypatch):
    settings = old_library(tmp_path, monkeypatch)
    backup = create_backup(settings, tmp_path / "backups")
    assert "papers/old-paper.pdf" in [e["path"] for e in manifest_of(backup)["files"]]
    assert manifest_of(backup)["schema_versions"] == list(range(1, OLD_LAST + 1))

    restored = Settings(data_dir=tmp_path / "restored", port=8765)
    restore_backup(backup, restored)
    assert compare_states(library_state(settings.data_dir), library_state(restored.data_dir)) == []
    assert sha256_file(restored.papers_dir / "old-paper.pdf") == sha256_file(settings.papers_dir / "old-paper.pdf")

    conn = db.connect(restored.db_path)
    try:
        assert db.migrate(conn) == sorted(v for v in db.packaged_versions() if v > OLD_LAST)
        assert conn.execute("SELECT storage_path FROM source_assets").fetchall()[0][0] == "old-paper.pdf"
    finally:
        conn.close()


def test_b02_a_paper_row_of_an_older_library_whose_file_is_missing_still_fails_the_backup(tmp_path, monkeypatch):
    settings = old_library(tmp_path, monkeypatch, with_paper_file=False)
    with pytest.raises(BackupError, match="referenced file is missing: papers/old-paper.pdf"):
        create_backup(settings, tmp_path / "backups")
    assert not any((tmp_path / "backups").glob("deixis-backup-*"))


def test_b02_a_database_without_source_assets_is_not_checked_for_being_a_library(tmp_path):
    """Pinned as it is, not as a wish: with `source_assets` read as optional (asked for), a database that has only an empty
    `schema_migrations` table backs up as just its database file; backup does not decide what a library is."""
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    settings.data_dir.mkdir()
    conn = sqlite3.connect(settings.db_path)
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    conn.commit()
    conn.close()
    backup = create_backup(settings, tmp_path / "backups")
    assert [e["path"] for e in manifest_of(backup)["files"]] == ["library.sqlite"]
