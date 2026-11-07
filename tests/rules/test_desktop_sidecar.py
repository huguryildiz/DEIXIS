"""P10 M1 and M2: the backend as the packaged app's sidecar.

The frozen entry's `-m` routing, the `serve --desktop` start contract (JSON lines on stdout, saved port, the control
token as the first stdin line, stdin EOF), the control-token shutdown route and the token kept out of the environment;
the child record and the desktop watchdog (M2). Run from the repository, not a PyInstaller build
(scripts/p10/sidecar_smoke.py and desktop_acceptance.py check the built app). SYNTHETIC data only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as cli
from deixis import desktop_reaper, frozen_entry
from deixis.models import cli_process
from deixis.tools import child_record
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter

REPO = Path(__file__).resolve().parents[2]
# The desktop process layer (child record, watchdog, session launcher) is macOS only; on Windows the shell starts the
# sidecar in a Job Object (W4) and the frozen entry refuses those modules (W3).
MAC_DESKTOP = pytest.mark.skipif(sys.platform == "win32", reason="the desktop sidecar process layer (child record, "
                                 "watchdog, session launcher) is macOS only; Windows owns children with Job Objects "
                                 "(tests/rules/test_windows_jobs.py)")


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


def test_the_frozen_entry_refuses_the_macos_process_layer_on_windows(monkeypatch):
    # P10 W3: on Windows each child's Job Object owns it; the watchdog and the session launcher are not children there.
    monkeypatch.setattr(frozen_entry.sys, "platform", "win32")
    for module in ("deixis.desktop_reaper", "deixis.session_launcher"):
        assert frozen_entry.run_child(module, []) == frozen_entry.EXIT_REFUSED


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


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="root, and any user on Windows (a folder's read-only mode does not stop writes there), can write to it")
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
@MAC_DESKTOP
def test_a_desktop_start_reports_listening_after_startup_and_stops_when_stdin_closes(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    port = free_port()
    (data / cli.DESKTOP_PORT_FILE).write_text(json.dumps({"port": port}))  # never the default port, the owner's library
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "DEIXIS_DATA_DIR": str(data), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
           child_record.ACK_ENV: "1"}  # as the desktop watchdog starts it
    proc = subprocess.Popen([sys.executable, "-m", "deixis", "serve", "--desktop"], cwd=tmp_path, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        proc.stdin.write("SYNTHETIC-stdin-token\n")  # M2: the token is the first stdin line, never in the environment
        proc.stdin.flush()
        announced = json.loads(proc.stdout.readline())  # before the record is on, so before any recorded child
        assert announced == {"event": "child_record", "path": str(data / "run" / "children.jsonl")}
        time.sleep(0.5)
        assert proc.poll() is None and not (data / "run").exists()  # waits for the watchdog's ack
        proc.stdin.write("ack\n")
        proc.stdin.flush()
        event = json.loads(proc.stdout.readline())
        assert event["event"] == "listening" and event["port"] == port and event["pid"] == proc.pid
        assert event["data_dir"] == str(data)
        health = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=10)
        assert health.status_code == 200 and health.json()["nonce"] == event["nonce"]  # the lifespan start has passed
        status = f"http://127.0.0.1:{port}/api/internal/status"
        assert httpx.get(status, timeout=10).status_code == 403
        assert httpx.get(status, headers={"X-Deixis-Control": "SYNTHETIC-stdin-token"}, timeout=10).json() == {
            "running_researches": 0}
        assert (data / "logs" / "backend.log").is_file()
        assert (data / "run" / "children.jsonl").parent.is_dir()  # the child record is on
        started = time.monotonic()
        proc.stdin.close()
        assert proc.wait(cli.SHUTDOWN_EXIT_SECONDS + 4) == 0
        assert time.monotonic() - started < cli.SHUTDOWN_EXIT_SECONDS + 4
        assert proc.stdout.read() == ""  # nothing but the two JSON lines on stdout
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.process
@MAC_DESKTOP
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


def test_the_stdin_token_is_the_first_line_only():
    stream = iter([bytes([b]) for b in b"SYNTHETIC-token\nmore input"])
    assert cli.read_stdin_token(lambda: next(stream, b"")) == "SYNTHETIC-token"
    assert b"".join(stream) == b"more input"  # left for the EOF watch
    assert cli.read_stdin_token(lambda: b"") is None  # EOF first: no token, the shutdown route stays off


def record_on(monkeypatch, tmp_path, owner: str | None = None) -> Path:
    record = child_record.record_path(tmp_path)
    monkeypatch.setenv(child_record.RECORD_ENV, str(record))
    monkeypatch.setenv(child_record.OWNER_ENV, owner or child_record.identity(os.getpid()))
    return record


@pytest.mark.process
@MAC_DESKTOP
def test_a_session_is_recorded_before_its_program_runs_and_emptied_before_its_line_goes(monkeypatch, tmp_path):
    # The program checks the record for its own session, leaves a grandchild in another process group of that session
    # and exits at once (before any watchdog scan could see it). The launcher outlives it and kills the grandchild.
    record = record_on(monkeypatch, tmp_path)
    program = ("import json, os, subprocess, sys\n"
               "from pathlib import Path\n"
               "lines = Path(os.environ['DEIXIS_CHILD_RECORD']).read_text(encoding='utf-8').splitlines()\n"
               "mine = [json.loads(l) for l in lines if json.loads(l)['sid'] == os.getsid(0)]\n"
               "left = subprocess.Popen(['/bin/sleep', '60'], process_group=0)\n"
               "print(json.dumps({'mine': mine, 'left': left.pid}), flush=True)\n")
    done = subprocess.run(cli_process.launch([sys.executable, "-c", program]), capture_output=True, text=True,
                          timeout=20, **cli_process.spawn_options())
    seen = json.loads(done.stdout)
    assert done.returncode == 0, done.stderr
    assert len(seen["mine"]) == 1 and seen["mine"][0]["pid"] == seen["mine"][0]["sid"] == seen["mine"][0]["pgid"]
    assert seen["mine"][0]["kind"] == "cli" and seen["mine"][0]["owner"] == child_record.identity(os.getpid())
    assert child_record.process_info(seen["left"]) is None  # killed before the launcher ended (stdout closed)
    assert child_record.entries(record) == []


@pytest.mark.process
@MAC_DESKTOP
def test_a_program_whose_session_cannot_be_recorded_never_runs(monkeypatch, tmp_path):
    marker = tmp_path / "ran"
    program = [sys.executable, "-c", f"open({str(marker)!r}, 'w')"]
    record_on(monkeypatch, tmp_path, owner=f"{os.getpid()}:0:0")  # the owner is gone (another start time)
    refused = subprocess.run(cli_process.launch(program), capture_output=True, text=True, timeout=20)
    (tmp_path / "file").write_text("")
    monkeypatch.setenv(child_record.RECORD_ENV, str(tmp_path / "file" / "children.jsonl"))  # cannot be written
    monkeypatch.setenv(child_record.OWNER_ENV, child_record.identity(os.getpid()))
    unwritable = subprocess.run(cli_process.launch(program), capture_output=True, text=True, timeout=20)
    assert refused.returncode == unwritable.returncode == 125 and "did not start" in unwritable.stderr
    assert cli_process.refused(unwritable.returncode, unwritable.stderr)  # a local start error: nothing was sent
    assert not cli_process.refused(125, "a program's own exit 125")
    assert not marker.exists() and child_record.entries(child_record.record_path(tmp_path)) == []


def gone(ident: str, seconds: float = 3) -> bool:
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        if not child_record.alive(ident):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.process
@MAC_DESKTOP
def test_the_watchdog_kills_what_a_dead_backend_left_through_live_launchers_and_seen_identities(tmp_path):
    # A stand-in backend (its own process group, as the watchdog starts it) with the record on: a CLI through the
    # session launcher that has put a process in another group of its session, and an unrecorded child in a session
    # of its own that only the scan has seen.
    program = ("import subprocess, time; subprocess.Popen(['/bin/sleep', '63'], process_group=0); time.sleep(61)")
    script = ("import subprocess, sys\nfrom pathlib import Path\nfrom deixis.tools import child_record\n"
              "child_record.configure(Path(sys.argv[1]))\n"
              f"cli = subprocess.Popen(child_record.launcher_argv([sys.executable, '-c', {program!r}], 'cli'),"
              " start_new_session=True)\n"
              "loose = subprocess.Popen(['/bin/sleep', '62'], start_new_session=True)\n"
              "print(cli.pid, loose.pid, flush=True)\nimport time; time.sleep(60)\n")
    backend = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True,
                               process_group=0)
    try:
        launcher_pid, loose_pid = map(int, backend.stdout.readline().split())
        record = child_record.record_path(tmp_path)
        ends = time.monotonic() + 10
        while len(child_record.members(child_record.identity(launcher_pid) or "")) < 2 and time.monotonic() < ends:
            time.sleep(0.05)  # the program and its other-group child have started
        owner = child_record.identity(backend.pid)
        reaper = desktop_reaper.Reaper(backend.pid, owner.partition(":")[2])
        reaper.me = None  # the test process leads no watchdog session; that sweep is not exercised here
        reaper.record = record
        reaper.scan()
        session = child_record.members(child_record.identity(launcher_pid))
        left = session | {child_record.identity(launcher_pid), child_record.identity(loose_pid)}
        assert len(session) == 2 and left <= reaper.known
        assert [e.pid for e in child_record.entries(record)] == [launcher_pid]
        os.kill(backend.pid, signal.SIGKILL)  # the backend dies without cleaning up; its children are orphans now
        backend.wait()
        assert all(child_record.alive(i) for i in left)
        reaper.stop()
        assert all(gone(i) for i in left)
        assert child_record.entries(record) == []
    finally:
        if backend.poll() is None:
            backend.kill()
            backend.wait()


@pytest.mark.process
@MAC_DESKTOP
def test_a_recorded_id_whose_leader_is_another_process_now_is_never_used(tmp_path):
    # A line whose pid now belongs to an unrelated session leader (another start time: the pid was reused), owned by a
    # backend that is gone. Neither recovery nor the watchdog may touch that session or its group.
    other = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & exec sleep 31"], start_new_session=True)
    try:
        time.sleep(0.3)
        record = child_record.record_path(tmp_path)
        record.parent.mkdir(parents=True)
        owner = f"{other.pid}:0:1"
        record.write_text(json.dumps({"pid": other.pid, "start": "0:0", "pgid": other.pid, "sid": other.pid,
                                      "owner": owner, "kind": "cli"}) + "\n")
        unrelated = {child_record.identity(other.pid)} | {
            f"{pid}:{start}" for pid, (_ppid, pgid, start) in child_record.snapshot().items() if pgid == other.pid}
        assert len(unrelated) == 2 and child_record.members(f"{other.pid}:0:0") == set()
        reaper = desktop_reaper.Reaper(other.pid, "0:1")
        reaper.me, reaper.record = None, record
        reaper.scan()
        assert reaper.known == set()
        reaper.stop()
        assert child_record.recover(record) == [] and child_record.entries(record) == []
        assert all(child_record.alive(i) for i in unrelated)
    finally:
        os.killpg(other.pid, signal.SIGKILL)
        other.wait()


def test_the_watchdog_takes_the_record_path_before_any_child_and_answers_it():
    reaper = desktop_reaper.Reaper(os.getpid(), "0:0")
    relay, reply = reaper.on_line(b'{"event": "child_record", "path": "/SYNTHETIC/data/run/children.jsonl"}\n')
    assert (relay, reply) == (False, b"ack\n") and reaper.record == Path("/SYNTHETIC/data/run/children.jsonl")
    assert reaper.on_line(b'{"event": "listening", "port": 1}\n') == (True, None)  # relayed to the shell


@pytest.mark.process
@MAC_DESKTOP
def test_a_group_is_never_signalled_once_its_leader_id_belongs_to_another_process():
    # The leader DEIXIS started has been reaped and its pid now leads an unrelated group (another start time).
    other = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & exec sleep 31"], start_new_session=True)
    try:
        ends = time.monotonic() + 10
        while time.monotonic() < ends and not ("sleep 31" in subprocess.run(
                ["ps", "-o", "command=", "-p", str(other.pid)], capture_output=True, text=True).stdout
                and child_record.members(child_record.identity(other.pid) or "")):
            time.sleep(0.05)  # the shell has started its background sleep and exec'd the other one
        unrelated = {child_record.identity(other.pid)} | child_record.members(child_record.identity(other.pid))
        stale = f"{other.pid}:0:0"

        class Proc:
            pid, returncode = other.pid, 0
        proc = Proc()
        cli_process._LEADERS[proc] = stale
        cli_process.stop_group(proc)
        assert child_record.stop_group(other.pid, stale, signal.SIGKILL) == set()
        assert child_record.stop_group(other.pid, None, signal.SIGKILL) == set()
        assert len(unrelated) == 2 and all(child_record.alive(i) for i in unrelated)
        leader = child_record.identity(other.pid)
        found = child_record.stop_group(other.pid, leader, signal.SIGKILL)  # the real leader
        # Linux leaves the leader (in DEIXIS always a session launcher, which then empties its own session and ends).
        assert found == unrelated and all(gone(i) for i in (unrelated - {leader} if child_record.LINUX else unrelated))
    finally:
        if other.poll() is None:
            # The group may already be gone or hold only the unreaped leader: macOS then answers EPERM.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(other.pid, signal.SIGKILL)
        other.wait()


def backend_with_launcher(tmp_path, program: str) -> subprocess.Popen:
    """A stand-in backend with the record on that starts `program` through the launcher when told (a stdin line)."""
    script = ("import subprocess, sys\nfrom pathlib import Path\nfrom deixis.tools import child_record\n"
              "child_record.configure(Path(sys.argv[1]))\nsys.stdin.readline()\n"
              f"cli = subprocess.Popen(child_record.launcher_argv([sys.executable, '-c', {program!r}], 'cli'),"
              " start_new_session=True)\nprint(cli.pid, flush=True)\nimport time; time.sleep(60)\n")
    backend = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, process_group=0)
    return backend


def start_launcher(backend: subprocess.Popen) -> set[str]:
    """The launcher's session once its program and the program's other-group child run: three identities."""
    backend.stdin.write("go\n")
    backend.stdin.flush()
    launcher = child_record.identity(int(backend.stdout.readline()))
    ends = time.monotonic() + 10
    while len(child_record.members(launcher)) < 2 and time.monotonic() < ends:
        time.sleep(0.05)
    return child_record.members(launcher) | {launcher}


PROGRAM = "import subprocess, time; subprocess.Popen(['/bin/sleep', '63'], process_group=0); time.sleep(61)"


@pytest.mark.process
@MAC_DESKTOP
def test_a_launcher_recorded_after_the_last_scan_is_stopped_and_another_owners_line_kept(tmp_path):
    record = child_record.record_path(tmp_path)
    foreign = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)  # another DEIXIS's recorded session
    backend = backend_with_launcher(tmp_path, PROGRAM)
    try:
        time.sleep(0.5)  # the record is on
        record.write_text(json.dumps({"pid": foreign.pid, "start": child_record.identity(foreign.pid).partition(":")[2],
                                      "pgid": foreign.pid, "sid": foreign.pid, "owner": child_record.identity(os.getpid()),
                                      "kind": "cli"}) + "\n")
        owner = child_record.identity(backend.pid)
        reaper = desktop_reaper.Reaper(backend.pid, owner.partition(":")[2])
        reaper.me, reaper.record = None, record
        reaper.scan()  # the last scan, before the launcher exists
        session = start_launcher(backend)
        assert len(session) == 3 and not session & reaper.known and len(child_record.entries(record)) == 2
        launcher = next(e.ident for e in child_record.entries(record) if e.pid != foreign.pid)
        os.kill(int(launcher.partition(":")[0]), signal.SIGSTOP)  # its own owner watch cannot act: the watchdog must
        os.kill(backend.pid, signal.SIGKILL)
        backend.wait()
        killed = reaper.stop()  # reads the record again once the owner is gone
        assert launcher in killed and all(gone(i) for i in session)
        assert [e.pid for e in child_record.entries(record)] == [foreign.pid] and foreign.poll() is None
    finally:
        for proc in (backend, foreign):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


@pytest.mark.process
@MAC_DESKTOP
def test_a_launcher_whose_owner_dies_empties_its_session_on_its_own(tmp_path):
    record = child_record.record_path(tmp_path)
    backend = backend_with_launcher(tmp_path, PROGRAM)
    try:
        session = start_launcher(backend)
        assert len(session) == 3 and len(child_record.entries(record)) == 1
        os.kill(backend.pid, signal.SIGKILL)  # no watchdog here
        backend.wait()
        assert all(gone(i, 8) for i in session) and child_record.entries(record) == []
    finally:
        if backend.poll() is None:
            backend.kill()
            backend.wait()


def test_the_record_layer_is_off_and_imports_work_without_fcntl():
    code = ("import sys; sys.modules['fcntl'] = None\n"
            "from deixis.models import cli_process\nfrom deixis.tools import child_record\n"
            "assert not child_record.ON and child_record.configure(__import__('pathlib').Path('.')) is None\n"
            "assert cli_process.launch(['prog', 'x']) == ['prog', 'x'] and child_record.recover(None) == []\n"
            "print('ok')")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "ok", done.stderr


@pytest.mark.process
@MAC_DESKTOP
def test_a_known_launchers_late_child_is_killed_before_the_launcher_and_its_line(tmp_path):
    # The last scan sees the launcher and its program; the program then starts a child in another group of the same
    # session just before the backend dies. The launcher is stopped (SIGSTOP), so only the watchdog can clean up.
    flag = tmp_path / "late"
    program = ("import os, subprocess, time\n"
               f"while not os.path.exists({str(flag)!r}): time.sleep(0.02)\n"
               "subprocess.Popen(['/bin/sleep', '64'], process_group=0); time.sleep(61)")
    record = child_record.record_path(tmp_path)
    backend = backend_with_launcher(tmp_path, program)
    try:
        backend.stdin.write("go\n")
        backend.stdin.flush()
        launcher = child_record.identity(int(backend.stdout.readline()))
        ends = time.monotonic() + 10
        while not child_record.members(launcher) and time.monotonic() < ends:
            time.sleep(0.05)
        owner = child_record.identity(backend.pid)
        reaper = desktop_reaper.Reaper(backend.pid, owner.partition(":")[2])
        reaper.me, reaper.record = None, record
        reaper.scan()  # the last scan: launcher and program
        assert launcher in reaper.known and child_record.members(launcher) <= reaper.known
        os.kill(int(launcher.partition(":")[0]), signal.SIGSTOP)
        flag.write_text("")
        ends = time.monotonic() + 10
        while len(child_record.members(launcher)) < 2 and time.monotonic() < ends:
            time.sleep(0.02)
        late = child_record.members(launcher) - reaper.known
        assert len(late) == 1
        os.kill(backend.pid, signal.SIGKILL)
        backend.wait()
        reaper.stop()
        assert all(gone(i) for i in late | {launcher}) and child_record.entries(record) == []
    finally:
        if backend.poll() is None:
            backend.kill()
            backend.wait()


def test_the_desktop_lines_are_ascii_so_a_windows_code_page_never_garbles_a_path(capsys):
    # The shell reads the pipe as UTF-8; Windows writes stdout in the console code page (cp1254 on a Turkish system).
    cli.emit({"event": "listening", "data_dir": "C:\\Users\\Uğur José\\AppData\\Local\\DEIXIS"})
    line = capsys.readouterr().out
    assert line.isascii() and json.loads(line)["data_dir"].endswith("Uğur José\\AppData\\Local\\DEIXIS")
