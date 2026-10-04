"""B02 refuses linked subpaths before SQLite or copyfile can reach a synthetic live library."""

import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from test_p9_restore_matrix import make_source_library
from test_p9_upgrade_check import dirs, uc


@pytest.fixture(autouse=True)
def in_process_port(monkeypatch):
    monkeypatch.setattr(uc, "_free_port", lambda: 8980)  # TestClient never starts a server.


def identity(path):
    try:
        st = path.stat()
        return st.st_dev, st.st_ino
    except FileNotFoundError:
        return None


def protect_live(monkeypatch, live):
    """Record resolved paths and inode identities; block an unsafe old-code call before it can mutate live files."""
    seen = {"sqlite": [], "destinations": []}
    live_ids = {identity(p) for p in live.rglob("*") if p.is_file()}
    real_connect, real_copy = sqlite3.connect, shutil.copyfile

    def record(value, kind):
        raw = str(value)
        if raw == ":memory:":
            seen[kind].append((raw, None, None))
            return
        path = Path(unquote(urlsplit(raw).path) if raw.startswith("file:") else raw)
        resolved, inode = path.resolve(), identity(path)
        seen[kind].append((raw, resolved, inode))
        assert not uc.inside(resolved, live.resolve()) and inode not in live_ids, f"unsafe {kind}: {resolved}"

    def connect(path, *args, **kwargs):
        record(path, "sqlite")
        return real_connect(path, *args, **kwargs)

    def copy(src, dest, *args, **kwargs):
        record(dest, "destinations")
        return real_copy(src, dest, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(shutil, "copyfile", copy)
    return seen


CASES = ["live-copy", "backup", "papers", "source-hardlink", "staging", "restored-hardlink",
         "restored-symlink", "restored-folder", "dangling", "local-hardlink"]


@pytest.mark.parametrize("case", CASES)
def test_linked_work_tree_is_refused_unchanged(dirs, tmp_path, monkeypatch, case):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    live_db = make_source_library(live)
    uc.copy_live(str(live), str(work))
    command = "open-copy" if case.startswith("restored-") else "restore-copy"
    other = tmp_path / "other"
    other.mkdir()
    if command == "open-copy":
        uc.restore_copy(str(work))
    if case == "live-copy":
        shutil.rmtree(work / uc.COPY)
        (work / uc.COPY).symlink_to(live, target_is_directory=True)
    elif case == "backup":
        (work / uc.BACKUP).symlink_to(other, target_is_directory=True)
    elif case == "papers":
        (work / uc.COPY / "papers").symlink_to(other, target_is_directory=True)
    elif case == "source-hardlink":
        target = work / uc.COPY / "library.sqlite"
        target.unlink()
        os.link(live_db, target)
    elif case == "staging":
        (work / uc.RESTORED).mkdir()
        (work / uc.RESTORED / "library.sqlite.restoring").symlink_to(live_db)
    elif case in ("restored-hardlink", "restored-symlink"):
        target = work / uc.RESTORED / "library.sqlite"
        target.unlink()
        os.link(live_db, target) if case.endswith("hardlink") else target.symlink_to(live_db)
    elif case == "restored-folder":
        shutil.copytree(work / uc.RESTORED, other, dirs_exist_ok=True)
        shutil.rmtree(work / uc.RESTORED)
        (work / uc.RESTORED).symlink_to(other, target_is_directory=True)
    elif case == "dangling":
        (work / "dangling").symlink_to(other / "missing")
    else:
        (work / "local").write_text("SYNTHETIC")
        os.link(work / "local", work / "local-link")
    before = uc._tree(live)
    seen = protect_live(monkeypatch, live)
    operation = uc.open_copy if command == "open-copy" else uc.restore_copy
    try:
        expected = "live file identity" if case in ("source-hardlink", "restored-hardlink") else None
        with pytest.raises(uc.Refused, match=expected):
            operation(str(work))
        assert uc.main([command, str(work)]) == 2
    finally:
        assert uc._tree(live) == before
    assert seen["sqlite"] == [] and seen["destinations"] == []


@pytest.mark.parametrize("case", ["live-restored", "existing-library"])
def test_old_refusal_guards_remain(dirs, monkeypatch, case):
    from deixis.storage.backup import BackupError

    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    uc.copy_live(str(live), str(work))
    if case == "live-restored":
        (work / uc.RESTORED).symlink_to(live, target_is_directory=True)
        before = uc._tree(live)
        protect_live(monkeypatch, live)
        with pytest.raises(uc.Refused):
            uc.open_copy(str(work))
        assert uc.main(["open-copy", str(work)]) == 2
    else:
        make_source_library(work / uc.RESTORED)
        before = uc._tree(live)
        protect_live(monkeypatch, live)
        with pytest.raises(BackupError, match="already exists"):
            uc.restore_copy(str(work))
    assert uc._tree(live) == before


@pytest.mark.parametrize("case", ["marker-symlink", "marker-dangling", "marker-hardlink"])
def test_marker_links_are_refused_before_the_marker_is_read(dirs, monkeypatch, case):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    uc.copy_live(str(live), str(work))
    marker = work / uc.MARKER
    text = marker.read_text()
    marker.unlink()
    if case == "marker-hardlink":
        source = live / "synthetic-marker"
        source.write_text(text)
        os.link(source, marker)
    else:
        marker.symlink_to(live / ("missing" if case == "marker-dangling" else "library.sqlite"))
    before = uc._tree(live)
    protect_live(monkeypatch, live)
    real_read_text = Path.read_text

    def read_text(self, *args, **kwargs):
        assert self != marker, "linked marker was read before refusal"
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    try:
        with pytest.raises(uc.Refused, match="link at .p9-upgrade-copy"):
            uc.restore_copy(str(work))
        assert uc.main(["restore-copy", str(work)]) == 2
    finally:
        assert uc._tree(live) == before


@pytest.mark.parametrize("where", ["work", "live", "entry"])
def test_scan_errors_are_refused_without_opening_sqlite(dirs, monkeypatch, where):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    uc.copy_live(str(live), str(work))
    before = uc._tree(live)
    seen = protect_live(monkeypatch, live)
    real_scandir, real_lstat = os.scandir, Path.lstat
    target = work if where == "work" else live

    def scandir(path):
        if Path(path) == target:
            raise OSError(13, "SYNTHETIC scan unavailable")
        return real_scandir(path)

    def lstat(self, *args, **kwargs):
        if self == work / uc.COPY / "library.sqlite":
            raise OSError(13, "SYNTHETIC entry unavailable")
        return real_lstat(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", lstat) if where == "entry" else patch.setattr(os, "scandir", scandir)
        with pytest.raises(uc.Refused, match="could not scan"):
            uc.restore_copy(str(work))
        assert uc.main(["restore-copy", str(work)]) == 2
    assert seen["sqlite"] == [] and seen["destinations"] == []
    assert uc._tree(live) == before


def test_tree_is_checked_again_after_backup(dirs, tmp_path, monkeypatch):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    uc.copy_live(str(live), str(work))
    other = tmp_path / "other"
    other.mkdir()
    before = uc._tree(live)
    protect_live(monkeypatch, live)
    real_backup = uc.create_backup

    def backup(*args):
        result = real_backup(*args)
        (work / uc.RESTORED).mkdir()
        (work / uc.RESTORED / "papers").symlink_to(other, target_is_directory=True)
        return result

    monkeypatch.setattr(uc, "create_backup", backup)
    with pytest.raises(uc.Refused, match="restored/papers"):
        uc.restore_copy(str(work))
    assert uc.main(["restore-copy", str(work)]) == 2
    assert not (work / uc.RESTORED / "library.sqlite").exists()
    assert uc._tree(live) == before


def test_normal_copy_restore_open_still_passes(dirs):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    before = uc._tree(live)
    uc.copy_live(str(live), str(work))
    assert uc.restore_copy(str(work))["researches"] == 1
    result = uc.open_copy(str(work))
    assert result["sql_before"] == result["sql_after"]
    assert result["outbound_requests"] == 0 and result["worker_started"] is False
    assert uc._tree(live) == before
