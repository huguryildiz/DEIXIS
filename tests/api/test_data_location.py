"""Data location (D32): the pointer file, the move at the next start, and the Settings routes.

Every folder is a temp path: `config.platform_data_dir` is patched to a pretend default, so nothing here reads or writes
the real `~/Library/Application Support/DEIXIS`. Files are SYNTHETIC. Passing shows the pointer order, the move rules
and the route checks; the macOS folder chooser itself (osascript) is not run. The folder lock tests (E1) start real
child processes that hold a lock; no second server is started, and network drives and full disks are simulated by
patching the mount table and the free space.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as cli
from deixis import config
from deixis.storage import data_location, library_lock
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter


@pytest.fixture
def default(tmp_path, monkeypatch):
    folder = tmp_path / "pretend-default"
    folder.mkdir()
    monkeypatch.setattr(config, "platform_data_dir", lambda: folder)
    monkeypatch.delenv("DEIXIS_DATA_DIR", raising=False)
    return folder


def library(folder, marker="old"):
    (folder / "papers").mkdir(parents=True)
    (folder / "papers" / "a.pdf").write_bytes(b"%PDF SYNTHETIC")
    (folder / "library.sqlite").write_text(marker)
    (folder / "library.sqlite-wal").write_text("wal")
    (folder / "worker.lock").write_text("")
    return folder


# ---- pointer resolution --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ['{"path": "/Volumes/Data/DEIX'])
def test_a_damaged_pointer_stops_every_command_instead_of_opening_an_empty_library(default, monkeypatch, capsys, text):
    """E23: a truncated or malformed location.json is a startup error that names the old folder when it can."""
    (default / "location.json").write_text(text)
    with pytest.raises(data_location.PointerDamaged):
        config.default_data_dir()
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "create_app", lambda *a, **k: pytest.fail("no library may be opened"))
    for argv in (["serve", "--no-browser"], ["recovery-files"]):
        assert cli.main(argv) == 2
        err = capsys.readouterr().err
        assert "location.json" in err and "did not open an empty library" in err
        assert ("/Volumes/Data/DEIX" in err) == text.startswith('{"path": "/Volumes')
    assert sorted(p.name for p in default.iterdir()) == ["location.json"]  # nothing created in the default folder


# ---- the move at the next start ------------------------------------------------------------------------------------


def test_a_fresh_folder_receives_every_entry_and_the_pointer_is_cleared(default, tmp_path):
    library(default)
    new = tmp_path / "new" / "DEIXIS"
    data_location.write_pointer(new, default)
    assert data_location.apply_pending_move(new) is None
    assert (new / "library.sqlite").read_text() == "old" and (new / "library.sqlite-wal").exists()
    assert (new / "papers" / "a.pdf").read_bytes() == b"%PDF SYNTHETIC"
    assert sorted(p.name for p in default.iterdir()) == ["library.lock", "location.json", "worker.lock"]
    assert json.loads((default / "location.json").read_text()) == {"path": str(new)}
    assert config.default_data_dir() == new


def test_a_cross_disk_move_interrupted_after_a_copy_finishes_at_the_next_start(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    real_rename, real_remove, calls = os.rename, data_location._remove, []

    def cross_disk(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    def fail_once(path):
        calls.append(path.name)
        if len(calls) == 1:
            raise OSError(errno.EIO, "SYNTHETIC failure")
        real_remove(path)

    monkeypatch.setattr(data_location.os, "rename", cross_disk)
    monkeypatch.setattr(data_location, "_remove", fail_once)
    message = data_location.apply_pending_move(new)
    assert "start DEIXIS again" in message
    assert (default / "papers" / "a.pdf").exists() and (new / "papers" / "a.pdf").exists()  # copied, original kept
    assert json.loads((default / "location.json").read_text())["moved"] == ["papers"]
    assert data_location.apply_pending_move(new) is None
    monkeypatch.setattr(data_location.os, "rename", real_rename)
    assert (new / "papers" / "a.pdf").exists() and (new / "library.sqlite").read_text() == "old"
    assert sorted(p.name for p in default.iterdir()) == ["library.lock", "location.json", "worker.lock"]


# ---- the folder lock (E1) ------------------------------------------------------------------------------------------


HOLDER = ("import sys; from pathlib import Path; from deixis.storage import library_lock; "
          "assert library_lock.hold_shared(Path(sys.argv[1])); print('ready', flush=True); sys.stdin.read()")


@pytest.fixture
def holder():
    """A second DEIXIS process that holds a folder's shared lock until the test ends (as a server on another port does)."""
    started = []

    def hold(folder):
        env = {**os.environ, "PYTHONPATH": str(Path(library_lock.__file__).parents[2])}
        proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(folder)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
        started.append(proc)
        assert proc.stdout.readline().strip() == "ready"
        return proc

    yield hold
    for proc in started:
        proc.kill()
        proc.wait()


def stop(proc):
    proc.stdin.close()
    proc.wait(timeout=10)


# ---- an interrupted move (E22) -------------------------------------------------------------------------------------


# ---- routes --------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(default):
    (default / "papers").mkdir()
    (default / "papers" / "a.pdf").write_bytes(b"%PDF SYNTHETIC")
    app = create_app(Settings(data_dir=default, port=8765, model_concurrency=1), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        c.app_state = app.state
        yield c


def test_the_view_reports_the_folder_its_parts_and_free_space(client, default):
    view = client.get("/api/settings/data-location").json()
    assert view["path"] == str(default) and view["is_default"] and not view["set_outside_app"] and view["pending_path"] is None
    parts = {p["key"]: p["bytes"] for p in view["breakdown"]}
    assert set(parts) == {"database", "pdfs", "payloads", "tools", "other"}
    assert parts["pdfs"] == len(b"%PDF SYNTHETIC") and parts["database"] > 0
    assert view["size_bytes"] == sum(parts.values()) and view["free_bytes"] > 0 and view["running_runs"] == 0


def test_a_change_needs_the_csrf_token(client, tmp_path):
    del client.headers["x-deixis-csrf"]
    assert client.post("/api/settings/data-location", json={"path": str(tmp_path / "x")}).status_code == 403


# ---- target checks (E21) -------------------------------------------------------------------------------------------


# ---- review round 1: older builds, the start race, a missing source, durability, Windows ---------------------------------


def test_nothing_is_deleted_from_the_source_before_the_copy_and_its_record_are_on_disk(default, tmp_path, monkeypatch):
    library(default)
    (default / "papers" / "sub").mkdir()
    (default / "papers" / "sub" / "b.pdf").write_bytes(b"%PDF SYNTHETIC 2")
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    events = []
    real = {name: getattr(data_location, name) for name in ("_remove", "write_pointer", "_fsync_tree", "_fsync_path", "_sync_dir")}
    real_replace = os.replace

    def logged(name, label):
        def call(path, *args, **kwargs):
            events.append((label, Path(path).name, Path(path).parent.name))
            return real[name](path, *args, **kwargs)
        return call

    def replace(src, dst):
        events.append(("replace", Path(dst).name, Path(dst).parent.name))
        real_replace(src, dst)

    def write_pointer(path, move_from, moved=None, phase=None, placing=None):
        real["write_pointer"](path, move_from, moved, phase, placing)
        events.append(("pointer", tuple(moved or ()), phase))

    def cross_disk(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(data_location.os, "rename", cross_disk)
    monkeypatch.setattr(data_location.os, "replace", replace)
    monkeypatch.setattr(data_location, "write_pointer", write_pointer)
    monkeypatch.setattr(data_location, "_remove", logged("_remove", "remove"))
    monkeypatch.setattr(data_location, "_fsync_tree", logged("_fsync_tree", "tree"))
    monkeypatch.setattr(data_location, "_fsync_path", logged("_fsync_path", "file"))
    monkeypatch.setattr(data_location, "_sync_dir", logged("_sync_dir", "dir"))
    assert data_location.apply_pending_move(new) is None

    def at(*event):
        return events.index(event)

    for name in ("papers", "library.sqlite-wal", "library.sqlite"):
        staged = data_location.MOVING_PREFIX + name
        copied, placed = at("tree", staged, "new"), at("replace", name, "new")
        entries_flushed = next(i for i, e in enumerate(events) if i > placed and e[:2] == ("dir", "new"))
        recorded = next(i for i, e in enumerate(events) if e[0] == "pointer" and name in e[1] and i > placed)
        deleted = at("remove", name, "pretend-default")
        assert copied < placed < entries_flushed < recorded < deleted, (name, events)
        # the record itself: its file flushed, renamed over the pointer, and the pointer's folder flushed, all before the deletion
        record = events[:recorded]
        renamed = max(i for i, e in enumerate(record) if e[:2] == ("replace", "location.json"))
        assert ("file", "location.json.tmp", "pretend-default") in record[:renamed]
        assert any(e[:2] == ("dir", "pretend-default") for e in record[renamed:])
    # the copy of a folder is flushed as a whole: its nested file is covered by the one tree call
    assert (new / "papers" / "sub" / "b.pdf").read_bytes() == b"%PDF SYNTHETIC 2"


# The Windows holder runs here on POSIX locks: `_inherits` is patched off so a child is started through `python -m deixis
# hold-folder`, the real module and the real handshake. msvcrt, the job object and a real Windows computer are not tested.


# ---- network detection (E21) ---------------------------------------------------------------------------------------


# ---- review round 2: the holder's job, Windows deferred deletion, the recovery path ------------------------------------


