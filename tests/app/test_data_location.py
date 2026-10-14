"""Data location (D32): the pointer file, the move at the next start, and the Settings routes.

Every folder is a temp path: `config.platform_data_dir` is patched to a pretend default, so nothing here reads or writes
the real `~/Library/Application Support/DEIXIS`. Files are SYNTHETIC. Passing shows the pointer order, the move rules
and the route checks; the macOS folder chooser itself (osascript) is not run.
"""

from __future__ import annotations

import errno
import json
import os

import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as cli
from deixis import config, data_location
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


def test_a_damaged_or_relative_pointer_is_ignored(default):
    (default / "location.json").write_text("{not json")
    assert config.default_data_dir() == default
    (default / "location.json").write_text(json.dumps({"path": "relative/folder"}))
    assert config.default_data_dir() == default


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
    assert sorted(p.name for p in default.iterdir()) == ["location.json", "worker.lock"]
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
    assert sorted(p.name for p in default.iterdir()) == ["location.json", "worker.lock"]


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
    assert client.post("/api/settings/data-location", json={"path": str(target), "check": True}).json() == {"path": str(target), "has_library": False}
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

