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


def test_a_change_is_recorded_for_the_next_start_and_can_be_cancelled(client, default, tmp_path):
    target = tmp_path / "elsewhere"
    assert client.post("/api/settings/data-location", json={"path": str(target), "check": True}).json() == {"path": str(target), "has_library": False, "sync_service": None}
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
