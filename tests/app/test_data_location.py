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
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as cli
from deixis import config, data_location, library_lock
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


def test_the_environment_wins_then_the_pointer_then_the_platform_default(default, tmp_path, monkeypatch):
    assert config.default_data_dir() == default
    data_location.write_pointer(tmp_path / "chosen", None)
    assert config.default_data_dir() == tmp_path / "chosen"
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path / "env"))
    assert config.default_data_dir() == tmp_path / "env"


@pytest.mark.parametrize("text", ['{"path": "/Volumes/Data/DEIX', "{not json", json.dumps({"path": "relative/folder"}), ""])
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


def test_choosing_the_platform_default_again_removes_the_pointer(default, tmp_path):
    data_location.write_pointer(tmp_path / "chosen", None)
    data_location.write_pointer(default, None)
    assert not (default / "location.json").exists()


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


def test_a_folder_that_already_has_a_library_is_opened_and_the_old_one_left_untouched(default, tmp_path):
    library(default)
    new = library(tmp_path / "other", marker="theirs")
    data_location.write_pointer(new, default)
    assert data_location.apply_pending_move(new) is None
    assert (new / "library.sqlite").read_text() == "theirs"
    assert (default / "library.sqlite").read_text() == "old" and (default / "papers" / "a.pdf").exists()
    assert json.loads((default / "location.json").read_text()) == {"path": str(new)}


def test_a_name_clash_refuses_and_moves_nothing(default, tmp_path):
    library(default)
    new = tmp_path / "new"
    (new / "papers").mkdir(parents=True)
    data_location.write_pointer(new, default)
    message = data_location.apply_pending_move(new)
    assert "already has papers" in message
    assert (default / "library.sqlite").exists() and "move_from" in json.loads((default / "location.json").read_text())


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


def test_tool_symlinks_and_venv_homes_follow_the_move(default, tmp_path):
    base = default / "tools" / "uv-python"
    base.mkdir(parents=True)
    (default / "tools" / "env" / "bin").mkdir(parents=True)
    (default / "tools" / "env" / "bin" / "python").symlink_to(base / "python3")
    (default / "tools" / "env" / "pyvenv.cfg").write_text(f"home = {base}/bin\n")
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    assert data_location.apply_pending_move(new) is None
    assert os.readlink(new / "tools" / "env" / "bin" / "python") == str(new / "tools" / "uv-python" / "python3")
    assert (new / "tools" / "env" / "pyvenv.cfg").read_text() == f"home = {new}/tools/uv-python/bin\n"


def test_serve_moves_before_it_opens_the_library(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    opened = []
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: opened.append(path) or "stop here")
    assert cli.main(["serve", "--no-browser"]) == 2
    assert opened == [new / "library.sqlite"] and (new / "library.sqlite").read_text() == "old"


# ---- the folder lock (E1) ------------------------------------------------------------------------------------------


HOLDER = ("import sys; from pathlib import Path; from deixis import library_lock; "
          "assert library_lock.hold_shared(Path(sys.argv[1])); print('ready', flush=True); sys.stdin.read()")


@pytest.fixture
def holder():
    """A second DEIXIS process that holds a folder's shared lock until the test ends (as a server on another port does)."""
    started = []

    def hold(folder):
        env = {**os.environ, "PYTHONPATH": str(Path(library_lock.__file__).parents[1])}
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


@pytest.mark.parametrize("busy", ["old", "new"])
def test_a_deixis_on_either_folder_postpones_the_move_and_nothing_moves(default, tmp_path, holder, busy):
    library(default)
    new = tmp_path / "new"
    new.mkdir()
    data_location.write_pointer(new, default)
    other = holder(default if busy == "old" else new)
    result = data_location.apply_pending_move(new)
    assert isinstance(result, data_location.Postponed) and result.busy == (default if busy == "old" else new)
    assert "start DEIXIS again" in result.message()
    assert (default / "library.sqlite").read_text() == "old" and not (new / "library.sqlite").exists()
    assert json.loads((default / "location.json").read_text()) == {"path": str(new), "move_from": str(default)}
    stop(other)
    assert data_location.apply_pending_move(new) is None and (new / "library.sqlite").read_text() == "old"


def test_a_child_that_outlives_its_deixis_keeps_the_folder_busy(default, tmp_path):
    """An install or an equation reading is started with the folder lock (`child_fds`); its DEIXIS letting go is not enough."""
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    assert library_lock.hold_shared(default)
    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE, pass_fds=library_lock.child_fds())
    try:
        library_lock.release(default)
        assert isinstance(data_location.apply_pending_move(new), data_location.Postponed)
    finally:
        child.stdin.close()
        child.wait(timeout=10)
    assert data_location.apply_pending_move(new) is None and (new / "library.sqlite").exists()


def test_serve_opens_the_old_folder_while_the_move_is_postponed(default, tmp_path, holder, monkeypatch, capsys):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    holder(default)
    opened = []
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: opened.append(path) or "stop here")
    assert cli.main(["serve", "--no-browser"]) == 2
    assert opened == [default / "library.sqlite"] and "was not moved" in capsys.readouterr().err
    assert default in library_lock._held  # held before the library is opened
    assert json.loads((default / "location.json").read_text())["move_from"] == str(default)


def test_serve_does_not_open_a_folder_another_process_is_moving(default, tmp_path, monkeypatch, capsys):
    library(default)
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(default))
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: pytest.fail("the library must not be opened"))
    with library_lock.exclusive(default):
        assert cli.main(["serve", "--no-browser"]) == 2
    assert "moving the library" in capsys.readouterr().err


def test_two_moves_asking_in_opposite_orders_never_wait_for_each_other(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    real_try, met, results = library_lock._try, threading.Barrier(2, timeout=5), {}

    def try_then_meet(fd, exclusive):
        got = real_try(fd, exclusive)
        met.wait()  # both hold their first folder before either asks for its second, and neither lets go before both asked
        return got

    def move(name, first, second):
        try:
            with library_lock.exclusive(first, second):
                results[name] = "moved"
        except library_lock.Busy as exc:
            results[name] = exc.folder

    monkeypatch.setattr(library_lock, "_try", try_then_meet)
    threads = [threading.Thread(target=move, args=("ab", a, b)), threading.Thread(target=move, args=("ba", b, a))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert results == {"ab": b, "ba": a}
    monkeypatch.setattr(library_lock, "_try", real_try)
    with library_lock.exclusive(a, b):  # both let go
        pass


# ---- an interrupted move (E22) -------------------------------------------------------------------------------------


class Killed(BaseException):
    """The process stops here (power loss, kill): no handler runs."""


def tool_link(folder):
    (folder / "tools" / "uv-python").mkdir(parents=True)
    (folder / "tools" / "env").mkdir()
    (folder / "tools" / "env" / "python").symlink_to(folder / "tools" / "uv-python" / "python3")


def test_a_stop_between_the_database_move_and_the_relink_is_finished_at_the_next_start(default, tmp_path, monkeypatch):
    library(default)
    tool_link(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    real_rename = os.rename

    def stop_after_database(src, dst):
        real_rename(src, dst)
        if Path(dst).name == "library.sqlite":
            raise Killed

    monkeypatch.setattr(data_location.os, "rename", stop_after_database)
    with pytest.raises(Killed):
        data_location.apply_pending_move(new)
    monkeypatch.setattr(data_location.os, "rename", real_rename)
    assert (new / "library.sqlite").exists() and json.loads((default / "location.json").read_text())["phase"] == "moving"
    assert data_location.apply_pending_move(new) is None
    assert os.readlink(new / "tools" / "env" / "python") == str(new / "tools" / "uv-python" / "python3")
    assert json.loads((default / "location.json").read_text()) == {"path": str(new)}


def test_a_stop_during_the_relink_relinks_at_the_next_start(default, tmp_path, monkeypatch):
    library(default)
    tool_link(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    real_relink = data_location._relink
    monkeypatch.setattr(data_location, "_relink", lambda *a: (_ for _ in ()).throw(Killed()))
    with pytest.raises(Killed):
        data_location.apply_pending_move(new)
    assert json.loads((default / "location.json").read_text())["phase"] == "relinking"
    monkeypatch.setattr(data_location, "_relink", real_relink)
    assert data_location.apply_pending_move(new) is None
    assert os.readlink(new / "tools" / "env" / "python") == str(new / "tools" / "uv-python" / "python3")


def test_a_stop_after_a_copy_takes_its_name_and_before_it_is_recorded_finishes_cleanly(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    real_replace = os.replace

    def cross_disk(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    def stop_after_placing(src, dst):
        real_replace(src, dst)
        if Path(src).name.startswith(data_location.MOVING_PREFIX):
            raise Killed

    monkeypatch.setattr(data_location.os, "rename", cross_disk)
    monkeypatch.setattr(data_location.os, "replace", stop_after_placing)
    with pytest.raises(Killed):
        data_location.apply_pending_move(new)
    pointer = json.loads((default / "location.json").read_text())
    assert pointer["placing"] == "papers" and "moved" not in pointer
    assert (new / "papers" / "a.pdf").exists() and (default / "papers" / "a.pdf").exists()  # in both folders
    monkeypatch.setattr(data_location.os, "replace", real_replace)
    assert data_location.apply_pending_move(new) is None  # no name clash: the record said papers was being placed
    assert (new / "papers" / "a.pdf").exists() and (new / "library.sqlite").read_text() == "old"
    assert sorted(p.name for p in default.iterdir()) == ["library.lock", "location.json", "worker.lock"]


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


def test_a_change_is_recorded_for_the_next_start_and_can_be_cancelled(client, default, tmp_path, monkeypatch):
    monkeypatch.setattr(data_location, "_mounts", lambda: [("/", "apfs")])
    target = tmp_path / "elsewhere"
    assert client.post("/api/settings/data-location", json={"path": str(target), "check": True}).json() == {
        "path": str(target), "has_library": False, "sync_service": None, "network_unchecked": False}
    assert not (default / "location.json").exists()
    view = client.post("/api/settings/data-location", json={"path": str(target)}).json()
    assert view["pending_path"] == str(target) and not view["pending_has_library"]
    assert json.loads((default / "location.json").read_text()) == {"path": str(target), "move_from": str(default)}
    view = client.post("/api/settings/data-location", json={"path": str(default)}).json()
    assert view["pending_path"] is None and not (default / "location.json").exists()


@pytest.mark.parametrize("where", ["inside", "parent", "relative", "file"])
def test_unusable_folders_are_refused(client, default, tmp_path, where):
    (tmp_path / "a-file").write_text("x")
    path = {"inside": str(default / "sub"), "parent": str(tmp_path), "relative": "some/folder", "file": str(tmp_path / "a-file")}[where]
    assert client.post("/api/settings/data-location", json={"path": path}).status_code == 422
    assert not (default / "location.json").exists()


def test_active_runs_and_an_outside_setting_refuse_a_change(client, default, tmp_path, monkeypatch):
    conn = client.app_state.store.conn
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('r1', 'SYNTHETIC', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('u1', 'r1', 1, 'discovery', 'running', 'discovery', '{}', 'now', 'now')")
    conn.commit()
    assert client.get("/api/settings/data-location").json()["running_runs"] == 1
    refused = client.post("/api/settings/data-location", json={"path": str(tmp_path / "x")})
    assert refused.status_code == 409 and "still running" in refused.json()["detail"]
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(default))
    assert client.get("/api/settings/data-location").json()["set_outside_app"] is True
    assert client.post("/api/settings/data-location", json={"path": str(tmp_path / "x")}).status_code == 409
    assert not (default / "location.json").exists()


def test_a_change_needs_the_csrf_token(client, tmp_path):
    del client.headers["x-deixis-csrf"]
    assert client.post("/api/settings/data-location", json={"path": str(tmp_path / "x")}).status_code == 403


def test_the_folder_chooser_is_macos_only(client, monkeypatch):
    monkeypatch.setattr("deixis.api.data_location_routes.sys.platform", "linux")
    assert client.post("/api/settings/data-location/choose").status_code == 501


def test_the_folder_chooser_returns_the_folder_or_nothing_on_cancel(client, monkeypatch):
    from deixis.api import data_location_routes as routes

    monkeypatch.setattr(routes.sys, "platform", "darwin")
    answers = iter([(0, "/Volumes/Data/DEIXIS/\n", ""), (1, "", "execution error: User canceled. (-128)")])

    def fake_run(args, **kwargs):
        code, out, err = next(answers)
        assert args[0] == "osascript"
        return type("Done", (), {"returncode": code, "stdout": out, "stderr": err})()

    monkeypatch.setattr(routes.subprocess, "run", fake_run)
    assert client.post("/api/settings/data-location/choose").json() == {"path": "/Volumes/Data/DEIXIS"}
    assert client.post("/api/settings/data-location/choose").json() == {"path": None}



# ---- target checks (E21) -------------------------------------------------------------------------------------------


def test_a_read_only_target_is_refused_even_when_its_permissions_look_writable(client, default, tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        refused = client.post("/api/settings/data-location", json={"path": str(locked / "DEIXIS"), "check": True})
        assert refused.status_code == 422 and "not writable" in refused.json()["detail"]
        monkeypatch.setattr(data_location.os, "access", lambda *a, **k: True)  # e.g. a read-only mount: only the probe tells
        assert data_location.target_problem(locked, default) == "is not writable"
    finally:
        locked.chmod(0o755)
    assert list(locked.iterdir()) == []  # the probe file is gone


def test_a_target_disk_without_room_for_the_library_is_refused(client, default, tmp_path, monkeypatch):
    monkeypatch.setattr(data_location, "_same_disk", lambda a, b: False)
    monkeypatch.setattr(data_location.shutil, "disk_usage", lambda path: type("U", (), {"free": 1000})())
    refused = client.post("/api/settings/data-location", json={"path": str(tmp_path / "small")})
    assert refused.status_code == 422 and "free; the library needs about" in refused.json()["detail"]
    assert not (default / "location.json").exists()
    monkeypatch.setattr(data_location, "_same_disk", lambda a, b: True)  # a rename on one disk needs no room
    assert client.post("/api/settings/data-location", json={"path": str(tmp_path / "small"), "check": True}).status_code == 200


def test_a_network_drive_is_refused_in_settings_and_at_the_start(client, default, tmp_path, monkeypatch, capsys):
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(data_location, "_mounts", lambda: [("/", "apfs"), (str(share.resolve()), "smbfs")])
    refused = client.post("/api/settings/data-location", json={"path": str(share / "DEIXIS")})
    assert refused.status_code == 422 and "network drive (smbfs)" in refused.json()["detail"]
    assert data_location.network_drive(tmp_path / "local") is None
    data_location.write_pointer(share / "DEIXIS", default)  # recorded before the check existed
    assert "network drive" in data_location.apply_pending_move(share / "DEIXIS")
    assert (default / "papers" / "a.pdf").exists()


def test_windows_network_shares_and_mapped_network_drives_are_network_drives(monkeypatch):
    monkeypatch.setattr(data_location.sys, "platform", "win32")
    monkeypatch.setattr(data_location, "_drive_type", lambda root: 4 if root == "Z:\\" else 3)
    assert data_location.network_drive(Path("\\\\server\\share\\DEIXIS")) == "network share"
    assert data_location.network_drive(Path("Z:\\DEIXIS")) == "mapped network drive"
    assert data_location.network_drive(Path("C:\\Users\\me\\DEIXIS")) is None


def test_a_cloud_sync_folder_is_allowed_with_a_warning(client, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Dropbox").mkdir(parents=True)
    (home / "Library" / "CloudStorage" / "OneDrive-Personal").mkdir(parents=True)
    monkeypatch.setattr(data_location.Path, "home", lambda: home)
    for folder, service in (("Dropbox", "Dropbox"), ("Library/CloudStorage/OneDrive-Personal", "OneDrive"), ("Elsewhere", None)):
        answer = client.post("/api/settings/data-location", json={"path": str(home / folder / "DEIXIS"), "check": True})
        assert answer.status_code == 200 and answer.json()["sync_service"] == service


def test_the_view_says_why_a_move_waits(client, default, tmp_path):
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    client.app_state.move_postponed = {"path": str(new), "busy": str(default)}
    assert client.get("/api/settings/data-location").json()["move_postponed"] == {"path": str(new), "busy": str(default)}
    data_location.write_pointer(default, None)  # cancelled: nothing waits any more
    assert client.get("/api/settings/data-location").json()["move_postponed"] is None


# ---- review round 1: older builds, the start race, a missing source, durability, Windows ---------------------------------


WORKER_ONLY = ("import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); "
               "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('ready', flush=True); sys.stdin.read()")


def old_build(folder):
    """A DEIXIS from before the folder lock: it holds only worker.lock, exclusively, for its whole life."""
    env = {**os.environ, "PYTHONPATH": str(Path(library_lock.__file__).parents[1])}
    proc = subprocess.Popen([sys.executable, "-c", WORKER_ONLY, str(folder / "worker.lock")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, env=env, text=True)
    assert proc.stdout.readline().strip() == "ready"
    return proc


@pytest.mark.parametrize("busy", ["old", "new"])
def test_an_older_build_holding_only_the_worker_lock_blocks_the_move(default, tmp_path, busy):
    library(default)
    new = tmp_path / "new"
    new.mkdir()
    data_location.write_pointer(new, default)
    other = old_build(default if busy == "old" else new)
    try:
        result = data_location.apply_pending_move(new)
        assert isinstance(result, data_location.Postponed) and result.busy == (default if busy == "old" else new)
        assert (default / "library.sqlite").read_text() == "old" and not (new / "library.sqlite").exists()
    finally:
        stop(other)
    assert data_location.apply_pending_move(new) is None and (new / "library.sqlite").read_text() == "old"


def test_a_move_finished_by_another_deixis_between_reading_settings_and_the_lock_reopens_the_new_location(default, tmp_path, monkeypatch):
    """The settings name the old folder; before this DEIXIS holds its lock another one moves the library away."""
    library(default)
    new = tmp_path / "new"
    settings = Settings(data_dir=default)  # what load_settings returned a moment earlier
    real_hold, opened = library_lock.hold_shared, []

    def move_then_hold(folder):
        if folder == default and not opened:
            opened.append("moved")
            data_location.write_pointer(new, default)
            assert data_location.apply_pending_move(new) is None  # the other DEIXIS's whole move
        return real_hold(folder)

    monkeypatch.setattr(library_lock, "hold_shared", move_then_hold)
    seen = []
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: seen.append(path) or "stop here")
    assert cli.serve(settings, False, (), reread_location=True) == 2
    assert seen == [new / "library.sqlite"] and (new / "library.sqlite").read_text() == "old"
    assert default not in library_lock._held and new in library_lock._held  # the lock on the folder it left was let go


def test_a_command_started_just_before_a_move_finishes_uses_the_new_location(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    real_hold = library_lock.hold_shared

    def move_then_hold(folder):
        if folder == default:
            data_location.write_pointer(new, default)
            assert data_location.apply_pending_move(new) is None
        return real_hold(folder)

    monkeypatch.setattr(library_lock, "hold_shared", move_then_hold)
    held = cli.hold_current_folder(Settings(data_dir=default))
    assert isinstance(held, Settings) and held.data_dir == new and default not in library_lock._held


def test_a_pointer_damaged_between_reading_and_locking_stops_the_start(default, tmp_path, monkeypatch, capsys):
    library(default)
    real_hold = library_lock.hold_shared

    def damage_then_hold(folder):
        (default / "location.json").write_text("{not json")
        return real_hold(folder)

    monkeypatch.setattr(library_lock, "hold_shared", damage_then_hold)
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: pytest.fail("the library must not be opened"))
    assert cli.serve(Settings(data_dir=default), False, (), reread_location=True) == 2
    assert "did not open an empty library" in capsys.readouterr().err and not library_lock._held


@pytest.mark.parametrize("phase", ["moving", None])
def test_a_missing_source_stops_the_start_and_names_both_folders(default, tmp_path, monkeypatch, capsys, phase):
    """An unplugged drive must not look like a finished move: no empty library opens and the record stays."""
    unplugged, new = tmp_path / "usb" / "DEIXIS", tmp_path / "new"
    (new / "papers").mkdir(parents=True)  # what the interrupted move had copied so far
    data_location.write_pointer(new, unplugged, [], phase=phase)
    message = data_location.apply_pending_move(new)
    assert isinstance(message, str) and str(unplugged) in message and str(new) in message
    assert json.loads((default / "location.json").read_text())["move_from"] == str(unplugged)
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "create_app", lambda *a, **k: pytest.fail("no library may be opened"))
    assert cli.main(["serve", "--no-browser"]) == 2
    err = capsys.readouterr().err
    assert str(unplugged) in err and str(new) in err and not (new / "library.sqlite").exists()


def test_a_source_that_is_missing_after_the_library_was_found_in_the_target_is_cleared(default, tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "library.sqlite").write_text("kept")
    data_location.write_pointer(new, tmp_path / "gone")
    assert data_location.apply_pending_move(new) is None and not (default / "location.json").read_text().count("move_from")


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


def test_the_helpers_flush_files_and_folders_and_windows_skips_folders(tmp_path, monkeypatch):
    (tmp_path / "t" / "d").mkdir(parents=True)
    (tmp_path / "t" / "a.bin").write_bytes(b"1")
    (tmp_path / "t" / "d" / "b.bin").write_bytes(b"2")
    flushed = []
    real_fsync = os.fsync
    monkeypatch.setattr(data_location.os, "fsync", lambda fd: (flushed.append(os.fstat(fd).st_mode), real_fsync(fd)))
    data_location._fsync_tree(tmp_path / "t")
    import stat
    assert sum(stat.S_ISREG(m) for m in flushed) == 2 and sum(stat.S_ISDIR(m) for m in flushed) == 3  # t, t/d, and t's parent
    flushed.clear()
    monkeypatch.setattr(data_location.sys, "platform", "win32")
    data_location._sync_dir(tmp_path)
    assert flushed == []  # Windows cannot open a folder to flush it
    data_location._fsync_path(tmp_path / "t" / "a.bin")
    assert [stat.S_ISREG(m) for m in flushed] == [True]  # a file is flushed through a writable handle (FlushFileBuffers)


# The Windows holder runs here on POSIX locks: `_inherits` is patched off so a child is started through `python -m deixis
# hold-folder`, the real module and the real handshake. msvcrt, the job object and a real Windows computer are not tested.


@pytest.fixture
def windows_children(monkeypatch):
    monkeypatch.setattr(library_lock, "_inherits", lambda: False)
    return {**os.environ, "PYTHONPATH": str(Path(library_lock.__file__).parents[1])}


def test_a_windows_child_takes_its_own_lock_before_the_parent_goes_on_and_outlives_the_parent(default, tmp_path, windows_children):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    assert library_lock.hold_shared(default)
    marker = tmp_path / "started"
    child = library_lock.guard([sys.executable, "-c", f"import sys; open({str(marker)!r}, 'w').close(); sys.stdin.read()"])
    assert child.kwargs == {} and child.argv[1:4] == ["-m", "deixis", "hold-folder"] and str(default) in child.argv
    process = subprocess.Popen(child.argv, stdin=subprocess.PIPE, env=windows_children)
    try:
        child.wait_ready()
        library_lock.release(default)  # the parent goes away; the holder still has the folder
        assert isinstance(data_location.apply_pending_move(new), data_location.Postponed)
        for _ in range(100):  # the real command starts only after the lock is held
            if marker.exists():
                break
            time.sleep(0.05)
        assert marker.exists()
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        child.done()
    assert process.returncode == 0 and not child._ready.exists()
    assert data_location.apply_pending_move(new) is None and (new / "library.sqlite").exists()


@pytest.fixture
def named_folder(default):
    """The folder counts as held (`guard` names it for the holder) without this test process owning its lock."""
    fd = os.open(os.devnull, os.O_RDONLY)
    library_lock._held[default] = fd
    yield default
    library_lock._held.pop(default, None)
    os.close(fd)


def test_a_windows_child_is_not_started_while_a_move_holds_the_folder(named_folder, tmp_path, windows_children):
    default = named_folder
    library(default)
    marker = tmp_path / "started"
    child = library_lock.guard([sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"])
    with library_lock.exclusive(default):
        process = subprocess.Popen(child.argv, env=windows_children)
        with pytest.raises(library_lock.ChildLockFailed, match="being moved"):
            child.wait_ready()
        assert process.wait(timeout=10) == 3
    child.done()
    assert not marker.exists()


def test_a_windows_child_whose_holder_never_answers_is_reported(named_folder, windows_children):
    child = library_lock.guard(["never-started"])
    with pytest.raises(library_lock.ChildLockFailed, match="did not answer"):
        child.wait_ready(timeout=0.2)
    child.done()


def test_posix_children_inherit_the_descriptor_and_a_command_with_no_folder_held_is_left_alone(default):
    assert library_lock.guard(["x"]).argv == ["x"]
    assert library_lock.hold_shared(default)
    child = library_lock.guard(["x"])
    assert child.argv == ["x"] and child.kwargs == {"pass_fds": library_lock.child_fds()} and child.kwargs["pass_fds"]
    child.wait_ready()


# ---- network detection (E21) ---------------------------------------------------------------------------------------


def test_windows_extended_length_paths_are_classified_by_the_drive_they_name(monkeypatch):
    monkeypatch.setattr(data_location.sys, "platform", "win32")
    roots = []
    monkeypatch.setattr(data_location, "_drive_type", lambda root: roots.append(root) or (4 if root == "Z:\\" else 3))
    assert data_location.network_drive(Path("\\\\?\\E:\\DEIXIS")) is None and roots == ["E:\\"]
    assert data_location.network_drive(Path("\\\\?\\Z:\\DEIXIS")) == "mapped network drive"
    assert data_location.network_drive(Path("\\\\?\\UNC\\server\\share\\DEIXIS")) == "network share"
    assert data_location.network_drive(Path("\\\\.\\E:\\DEIXIS")) is None
    assert data_location.network_drive(Path("\\\\server\\share\\DEIXIS")) == "network share"
    assert not data_location.network_unchecked(Path("\\\\?\\E:\\DEIXIS"))


def test_a_drive_that_cannot_be_examined_is_reported_not_passed_silently(client, tmp_path, monkeypatch):
    monkeypatch.setattr(data_location, "_mounts", lambda: None)
    assert data_location.network_drive(tmp_path / "x") is None and data_location.network_unchecked(tmp_path / "x")
    answer = client.post("/api/settings/data-location", json={"path": str(tmp_path / "x"), "check": True})
    assert answer.status_code == 200 and answer.json()["network_unchecked"] is True
    monkeypatch.setattr(data_location, "_mounts", lambda: [("/", "apfs")])
    assert client.post("/api/settings/data-location", json={"path": str(tmp_path / "x"), "check": True}).json()["network_unchecked"] is False
    monkeypatch.setattr(data_location.sys, "platform", "win32")
    monkeypatch.setattr(data_location, "_drive_type", lambda root: (_ for _ in ()).throw(OSError("no kernel32")))
    assert data_location.network_unchecked(Path("E:\\DEIXIS"))


def test_an_unreadable_mount_table_is_none_not_an_empty_list(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("no mount")

    monkeypatch.setattr(data_location.subprocess, "run", fail)
    monkeypatch.setattr(data_location.sys, "platform", "darwin")
    assert data_location._mounts() is None


# ---- review round 2: the holder's job, Windows deferred deletion, the recovery path ------------------------------------


class FakeChild:
    def __init__(self, log):
        self.log = log

    def wait(self):
        self.log.append("wait")
        return 7


def run_holder(tmp_path, monkeypatch, track):
    """holder_main with a stand-in for the process call; returns (exit status, what the ready file said, event log)."""
    from deixis.models import cli_process

    folder, ready, log = tmp_path / "held", tmp_path / "ready", []
    folder.mkdir(exist_ok=True)
    ready.write_text("")

    def popen(command, **options):
        log.append(("popen", command, options))
        return FakeChild(log)

    def tracked(process, require_job=False):
        log.append(("track", require_job, ready.read_text()))  # what the parent can see while the command is still held
        track(process)

    monkeypatch.setattr(library_lock.subprocess, "Popen", popen)
    monkeypatch.setattr(cli_process, "track", tracked)
    code = library_lock.holder_main([str(ready), str(folder), "--", "the", "command"])
    return code, ready.read_text(), log


def test_the_holder_starts_the_command_suspended_joins_the_job_and_only_then_signals_ready(tmp_path, monkeypatch):
    from deixis.models import cli_process

    code, answer, log = run_holder(tmp_path, monkeypatch, lambda process: None)
    assert (code, answer) == (7, "ready")
    assert [e if isinstance(e, str) else e[0] for e in log] == ["popen", "track", "wait"]
    assert log[0][1] == ["the", "command"] and log[0][2] == cli_process.spawn_options()  # suspended on Windows
    assert log[1][1:] == (True, "")  # the job is required, and "ready" was not said before the command joined it


def test_the_holder_does_not_run_the_command_when_the_job_cannot_be_joined(tmp_path, monkeypatch):
    def refuse(process):
        raise OSError("the process was stopped, not run")

    code, answer, log = run_holder(tmp_path, monkeypatch, refuse)
    assert (code, answer) == (1, "failed") and "wait" not in log
    child = library_lock.Guard.__new__(library_lock.Guard)
    child._ready = tmp_path / "ready"
    with pytest.raises(library_lock.ChildLockFailed, match="could not be tied"):
        child.wait_ready(timeout=0.2)


def test_a_frozen_windows_holder_gets_a_clean_pyinstaller_environment(named_folder, monkeypatch, windows_children):
    monkeypatch.setattr(library_lock.sys, "frozen", True, raising=False)
    child = library_lock.guard(["x"])
    assert child.argv[1] == "hold-folder" and child.env({"A": "1"}) == {"A": "1", "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    child.done()
    monkeypatch.setattr(library_lock.sys, "frozen", False, raising=False)
    plain = library_lock.guard(["x"])
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in plain.env({"A": "1"})
    plain.done()


def cross_disk_and_windows(monkeypatch):
    monkeypatch.setattr(data_location, "_defers_deletion", lambda: True)

    def cross_disk(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(data_location.os, "rename", cross_disk)


def test_on_windows_the_originals_stay_until_a_later_start_has_opened_the_new_library(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    cross_disk_and_windows(monkeypatch)
    assert data_location.apply_pending_move(new) is None
    assert (new / "library.sqlite").read_text() == "old" and (default / "library.sqlite").read_text() == "old"  # both
    pointer = json.loads((default / "location.json").read_text())
    assert pointer["phase"] == "placed_pending_cleanup" and pointer["path"] == str(new) and "opened" not in pointer
    assert config.default_data_dir() == new
    assert data_location.apply_pending_move(new) is None and (default / "papers" / "a.pdf").exists()  # a start in between moves nothing
    assert data_location.finish_cleanup(new) is None  # the first start that opened the new library: it is marked, nothing deleted
    assert json.loads((default / "location.json").read_text())["opened"] is True and (default / "library.sqlite").exists()
    assert data_location.finish_cleanup(new) is None  # the next one deletes the originals
    assert sorted(p.name for p in default.iterdir()) == ["library.lock", "location.json", "worker.lock"]
    assert json.loads((default / "location.json").read_text()) == {"path": str(new)}
    assert (new / "library.sqlite").read_text() == "old" and (new / "papers" / "a.pdf").exists()


def test_a_copy_that_differs_in_size_keeps_the_original_and_says_so(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    cross_disk_and_windows(monkeypatch)
    assert data_location.apply_pending_move(new) is None
    data_location.finish_cleanup(new)
    (new / "library.sqlite").write_text("truncated?")
    message = data_location.finish_cleanup(new)
    assert "library.sqlite" in message and str(default) in message
    assert (default / "library.sqlite").read_text() == "old" and "placed_pending_cleanup" in (default / "location.json").read_text()


def test_the_old_copies_wait_while_another_deixis_uses_the_old_folder(default, tmp_path, monkeypatch, holder):
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    cross_disk_and_windows(monkeypatch)
    data_location.apply_pending_move(new)
    data_location.finish_cleanup(new)
    other = holder(default)
    assert data_location.finish_cleanup(new) is None and (default / "library.sqlite").exists()
    stop(other)
    assert data_location.finish_cleanup(new) is None and not (default / "library.sqlite").exists()


def test_serve_runs_the_cleanup_only_after_the_library_opened(default, tmp_path, monkeypatch):
    new = tmp_path / "new"
    new.mkdir()
    data_location.write_pointer(new, default, ["papers"], phase="placed_pending_cleanup")
    order = []

    class Stop(Exception):
        pass

    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli.db, "open_problem", lambda path: order.append("open") or None)
    monkeypatch.setattr(cli.data_location, "finish_cleanup", lambda path: order.append(("cleanup", path)))
    monkeypatch.setattr(cli, "create_app", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        cli.serve(Settings(data_dir=new), False, ())
    assert order == ["open", ("cleanup", new)]


def test_a_stop_after_a_copy_took_its_name_flushes_the_target_before_the_original_goes(default, tmp_path, monkeypatch):
    """The recovery path deletes an original too: it must flush the copy and its name first, like the first run."""
    library(default)
    new = tmp_path / "new"
    data_location.write_pointer(new, default)
    real_replace, real_rename = os.replace, os.rename

    def cross_disk(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    def stop_after_placing(src, dst):
        real_replace(src, dst)
        if Path(src).name.startswith(data_location.MOVING_PREFIX):
            raise Killed

    monkeypatch.setattr(data_location.os, "rename", cross_disk)
    monkeypatch.setattr(data_location.os, "replace", stop_after_placing)
    with pytest.raises(Killed):
        data_location.apply_pending_move(new)
    monkeypatch.setattr(data_location.os, "replace", real_replace)
    events = []
    for name, label in (("_fsync_tree", "tree"), ("_sync_dir", "dir"), ("_remove", "remove")):
        real = getattr(data_location, name)
        monkeypatch.setattr(data_location, name, lambda path, real=real, label=label: (events.append((label, Path(path).name)), real(path))[1])
    assert data_location.apply_pending_move(new) is None
    tree = events.index(("tree", "papers"))
    assert tree < events.index(("dir", "new"), tree) < events.index(("remove", "papers"))
    assert not (default / "papers").exists() and (new / "papers" / "a.pdf").exists()


def test_a_new_target_folder_and_its_new_parents_are_flushed_into_their_parents(default, tmp_path, monkeypatch):
    library(default)
    new = tmp_path / "a" / "b" / "DEIXIS"
    data_location.write_pointer(new, default)
    synced, real = [], data_location._sync_dir
    monkeypatch.setattr(data_location, "_sync_dir", lambda path: (synced.append(Path(path)), real(path))[1])
    assert data_location.apply_pending_move(new) is None
    first = synced[: synced.index(new) + 1]
    assert tmp_path in first and tmp_path / "a" in first and tmp_path / "a" / "b" in first and new in first


def test_the_first_start_with_no_pointer_and_no_folder_still_works(default, tmp_path, monkeypatch):
    fresh = tmp_path / "fresh" / "DEIXIS"
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(fresh))
    assert data_location.apply_pending_move(fresh) is None and data_location.finish_cleanup(fresh) is None
    seen = []
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "schema_problem", lambda path: seen.append(path) or "stop here")
    assert cli.main(["serve", "--no-browser"]) == 2
    assert seen == [fresh / "library.sqlite"] and fresh in library_lock._held and not (default / "location.json").exists()
