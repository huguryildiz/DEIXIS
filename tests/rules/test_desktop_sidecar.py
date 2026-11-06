"""P10 M1: the backend as the packaged app's sidecar.

The frozen entry's `-m` routing, the `serve --desktop` start contract (JSON lines on stdout, saved port, stdin EOF), the
control-token shutdown route and the token kept out of the environment. Run from the repository, not a PyInstaller build
(scripts/p10/sidecar_smoke.py checks the built binary). SYNTHETIC data only.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as cli
from deixis import frozen_entry
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter

REPO = Path(__file__).resolve().parents[2]


def test_the_frozen_entry_runs_only_listed_child_modules_with_the_child_argv(monkeypatch, tmp_path):
    # Every module the app starts as `[sys.executable, "-m", "deixis...."]` is on the list.
    started = {m for path in (REPO / "deixis").rglob("*.py") if path.name != "frozen_entry.py"
               for m in re.findall(r'sys\.executable, "-m", "(deixis\.[\w.]+)"', path.read_text(encoding="utf-8"))}
    assert started and started <= frozen_entry.CHILD_MODULES
    (tmp_path / "argv_probe.py").write_text("import sys\nSEEN.extend(sys.argv)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    seen: list[str] = []
    monkeypatch.setattr("builtins.SEEN", seen, raising=False)
    monkeypatch.setattr(frozen_entry, "CHILD_MODULES", frozenset({"argv_probe"}))
    assert frozen_entry.main(["-m", "argv_probe", "/tmp/SYNTHETIC.pdf", "40000"]) == 0
    assert seen == [str(tmp_path / "argv_probe.py"), "/tmp/SYNTHETIC.pdf", "40000"]  # argv[1] is the first real argument
    seen.clear()
    assert frozen_entry.main(["-m", "deixis.__main__", "serve"]) == frozen_entry.EXIT_REFUSED
    assert seen == []


def test_the_control_token_is_read_once_and_removed_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEIXIS_CONTROL_TOKEN", "SYNTHETIC-control-token")
    seen = {}

    def record(settings, open_browser, dev_hosts, **options):
        seen.update(options, environment_has_token="DEIXIS_CONTROL_TOKEN" in os.environ)
        return 0

    monkeypatch.setattr(cli, "serve", record)
    assert cli.main(["serve", "--desktop"]) == 0
    assert seen["control_token"] == "SYNTHETIC-control-token" and seen["desktop"] is True
    assert not seen["environment_has_token"] and "DEIXIS_CONTROL_TOKEN" not in os.environ


def test_a_saved_port_that_is_taken_is_replaced_by_a_free_one_and_saved(tmp_path):
    settings = Settings(data_dir=tmp_path, port=free_port())
    first = cli.desktop_listener(settings, None)  # no saved port: the configured one, saved
    assert first.getsockname()[1] == settings.port == cli.saved_port(tmp_path)
    first.listen()  # the saved port is now taken by another server
    second = cli.desktop_listener(settings, None)
    try:
        assert second.getsockname()[1] not in (0, settings.port)
        assert cli.saved_port(tmp_path) == second.getsockname()[1]
    finally:
        first.close()
        second.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_a_refused_desktop_start_prints_one_startup_failed_line_with_the_same_sentence(monkeypatch, tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o555)
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(data))
    monkeypatch.setattr(cli, "port_available", lambda host, port: True)  # the default port is the owner's live service
    monkeypatch.setattr(cli, "create_app", lambda *a, **k: pytest.fail("the app was created"))
    try:
        assert cli.main(["serve", "--no-browser"]) == 2
        plain = capsys.readouterr()
        assert cli.main(["serve", "--desktop"]) == 2
        desktop = capsys.readouterr()
    finally:
        data.chmod(0o755)
    assert plain.out == "" and desktop.err == plain.err  # without --desktop nothing changes; the sentence is the same
    event = json.loads(desktop.out)
    assert event == {"event": "startup_failed", "code": "data_dir_unusable", "message": plain.err.strip()}


def shutdown_client(tmp_path, token):
    calls: list[int] = []
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",),
                     control_token=token, start_nonce="SYNTHETIC-nonce" if token else None,
                     request_shutdown=lambda: calls.append(1))
    return app, calls


def test_the_shutdown_route_takes_the_control_token_and_no_csrf_cookie(tmp_path):
    app, calls = shutdown_client(tmp_path, "SYNTHETIC-control-token")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["nonce"] == "SYNTHETIC-nonce"
        assert client.post("/api/internal/shutdown").status_code == 403
        assert client.post("/api/internal/shutdown", headers={"X-Deixis-Control": "wrong"}).status_code == 403
        assert client.put("/api/settings/preferences", json={"theme": "dark"}).status_code == 403  # every other write needs CSRF
        assert calls == []
        response = client.post("/api/internal/shutdown", headers={"X-Deixis-Control": "SYNTHETIC-control-token"})
        assert response.status_code == 202 and calls == [1] and "deixis_csrf" not in client.cookies
    app, calls = shutdown_client(tmp_path / "plain", None)
    with TestClient(app) as client:
        assert "nonce" not in client.get("/api/health").json()
        assert client.post("/api/internal/shutdown", headers={"X-Deixis-Control": "anything"}).status_code == 404
        assert calls == []


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.process
def test_a_desktop_start_reports_listening_after_startup_and_stops_when_stdin_closes(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    port = free_port()
    (data / cli.DESKTOP_PORT_FILE).write_text(json.dumps({"port": port}))  # never the default port, the owner's library
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "DEIXIS_DATA_DIR": str(data), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
           "DEIXIS_CONTROL_TOKEN": "SYNTHETIC-control-token"}
    proc = subprocess.Popen([sys.executable, "-m", "deixis", "serve", "--desktop"], cwd=tmp_path, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        event = json.loads(proc.stdout.readline())
        assert event["event"] == "listening" and event["port"] == port and event["pid"] == proc.pid
        health = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=10)
        assert health.status_code == 200 and health.json()["nonce"] == event["nonce"]  # the lifespan start has passed
        assert (data / "logs" / "backend.log").is_file()
        started = time.monotonic()
        proc.stdin.close()
        assert proc.wait(cli.SHUTDOWN_EXIT_SECONDS + 4) == 0
        assert time.monotonic() - started < cli.SHUTDOWN_EXIT_SECONDS + 4
        assert proc.stdout.read() == ""  # nothing but the one JSON line on stdout
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.process
def test_a_failed_lifespan_start_prints_startup_failed_and_no_listening_line(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / cli.DESKTOP_PORT_FILE).write_text(json.dumps({"port": free_port()}))
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "DEIXIS_DATA_DIR": str(data), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    script = ("from deixis.domain import skill\n"
              "skill.integrity_issues = lambda *a, **k: ['SYNTHETIC broken method file']\n"
              "from deixis.__main__ import main\nraise SystemExit(main(['serve', '--desktop']))\n")
    done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 3  # uvicorn's startup failure code, as without --desktop
    event = json.loads(done.stdout)  # one line, and no `listening` before it
    assert event["event"] == "startup_failed" and event["code"] == "lifespan_failed"
    assert "SYNTHETIC broken method file" in event["message"] and event["message"] in done.stderr


def test_an_unexpected_desktop_start_error_still_gives_one_startup_failed_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEIXIS_FULLTEXT_FETCH", "SYNTHETIC-bad-value")
    monkeypatch.setattr(cli, "EMITTED", [])
    with pytest.raises(ValueError):  # the process ends as without --desktop: the exception, exit 1
        cli.main(["serve", "--desktop"])
    event = json.loads(capsys.readouterr().out)
    assert event == {"event": "startup_failed", "code": "start_error",
                     "message": "ValueError: DEIXIS_FULLTEXT_FETCH must be auto or off"}
