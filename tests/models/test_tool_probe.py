"""Tool version/health probes (A3b, E16): bounded in time and output, decoded safely, never holding up the API."""

import asyncio
import os
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import tool_probe
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import ocr
from deixis.models import cli_process
from deixis.models.adapter import CodexAdapter
from fakes import FakeAdapter

HANGS = "#!/bin/sh\nsleep 600\n"
CP1254 = b"#!/bin/sh\nprintf 'S\\374r\\374m 1.2.3 \\376\\375 \\200\\n'\n"  # "Sürüm" in cp1254 plus bytes invalid in UTF-8


def script(path, body):
    path.write_bytes(body if isinstance(body, bytes) else body.encode())
    path.chmod(0o755)
    return path


def test_a_tool_that_never_answers_is_killed_and_reported_not_responding(tmp_path):
    pid_file = tmp_path / "pid"
    tool = script(tmp_path / "hang", f"#!/bin/sh\nsleep 600 &\necho $! > {pid_file}\nwait\n")
    started = time.monotonic()
    result = asyncio.run(tool_probe.probe([str(tool), "--version"], timeout=1.5))
    assert time.monotonic() - started < 4
    assert (result.error, result.ok, result.returncode) == ("not_responding", False, None)
    # The child it started went with it: the whole process group is killed, not only the launcher.
    assert gone(int(pid_file.read_text()))


def gone(pid):
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_launcher_that_exits_at_once_still_has_its_child_killed(tmp_path):
    """npm-style launcher: it starts the real tool, which does not hold the pipes, and exits with the version."""
    pid_file = tmp_path / "pid"
    tool = script(tmp_path / "launcher", f"#!/bin/sh\nsleep 600 >/dev/null 2>&1 &\necho $! > {pid_file}\necho 1.2.3\n")
    result = asyncio.run(tool_probe.probe([str(tool), "--version"], timeout=3))
    assert result.ok and result.stdout.strip() == "1.2.3"
    assert gone(int(pid_file.read_text()))


class FakeProc:
    pid, returncode = 4242, None

    def kill(self):
        self.returncode = -9


def test_windows_taskkill_fallback_runs_off_the_event_loop(monkeypatch):
    """Without a job object, Windows cleanup is a taskkill child process; it must not hold up the loop."""
    monkeypatch.setattr(cli_process, "WINDOWS", True)
    ran = []
    monkeypatch.setattr(cli_process.subprocess, "run", lambda argv, **kw: (ran.append(argv), time.sleep(1)))

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        task = asyncio.create_task(ticker())
        await cli_process.stop_group_async(FakeProc())
        task.cancel()
        return ticks

    assert asyncio.run(main()) >= 10  # the loop kept running for the second taskkill took
    assert ran == [["taskkill", "/T", "/F", "/PID", "4242"]]


def windows(monkeypatch, **answers):
    """Windows with stand-ins for kernel32 and ntdll that record each call; the real Windows ABI cannot run here."""
    monkeypatch.setattr(cli_process, "WINDOWS", True)
    monkeypatch.setattr(cli_process.subprocess, "run", lambda *a, **k: pytest.fail("taskkill was used despite the job"))
    answers = {"OpenProcess": 9, "CreateJobObjectW": 7, "NtResumeProcess": 0} | answers
    calls = []

    class Library:
        def __getattr__(self, name):
            return lambda *args: calls.append((name, *args)) or answers.get(name, 1)

    monkeypatch.setattr(cli_process, "_kernel32", Library)
    monkeypatch.setattr(cli_process, "_ntdll", Library)
    return calls


def test_windows_cli_starts_suspended_and_joins_a_kill_on_close_job_before_it_runs(monkeypatch):
    calls = windows(monkeypatch)
    flags = cli_process.spawn_options()["creationflags"]
    assert flags & cli_process.CREATE_SUSPENDED and flags & cli_process.CREATE_NEW_PROCESS_GROUP
    proc = FakeProc()
    cli_process.track(proc)
    names = [c[0] for c in calls]
    assert names.index("AssignProcessToJobObject") < names.index("NtResumeProcess")
    assert ("AssignProcessToJobObject", 7, 9) in calls and ("NtResumeProcess", 9) in calls
    limits = next(c for c in calls if c[0] == "SetInformationJobObject")
    assert limits[1:3] == (7, cli_process.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION)
    assert limits[3]._obj.BasicLimitInformation.LimitFlags & cli_process.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert proc.returncode is None  # resumed, not killed
    proc.returncode = 0  # the launcher is gone; what it started is still in the job
    asyncio.run(cli_process.stop_group_async(proc))
    assert calls[-1] == ("TerminateJobObject", 7, 1)


def test_windows_cli_runs_untracked_when_the_job_fails_and_is_killed_when_it_cannot_resume(monkeypatch):
    calls = windows(monkeypatch, AssignProcessToJobObject=0)
    proc = FakeProc()
    cli_process.track(proc)
    assert ("NtResumeProcess", 9) in calls and ("CloseHandle", 7) in calls and proc not in cli_process._JOBS
    assert proc.returncode is None
    windows(monkeypatch, OpenProcess=None)
    stuck = FakeProc()
    cli_process.track(stuck)
    assert stuck.returncode == -9  # left suspended it would hold its caller until the timeout


def test_output_is_decoded_with_replacement_and_bounded(tmp_path):
    odd = asyncio.run(tool_probe.probe([str(script(tmp_path / "odd", CP1254))]))
    assert odd.ok and odd.stdout.startswith("S�r�m 1.2.3 ")
    loud = script(tmp_path / "loud", "#!/bin/sh\nhead -c 1000000 /dev/zero | tr '\\0' 'x'\necho done >&2\n")
    bounded = asyncio.run(tool_probe.probe([str(loud)], timeout=3))
    assert bounded.error is None and len(bounded.stdout) == tool_probe.OUTPUT_LIMIT


def test_a_tool_that_cannot_start_is_reported_failed(tmp_path):
    assert tool_probe.probe_blocking([str(tmp_path / "missing"), "--version"]).error == "failed"


def test_a_hung_codex_does_not_hold_up_the_api_or_the_other_connections(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "codex", HANGS)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setattr(tool_probe, "PROBE_TIMEOUT", 2.0)
    codex = CodexAdapter(tmp_path / "codex-home", tmp_path / "workspace")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"codex": codex, "fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        replies = {}

        def check(name, url):
            started = time.monotonic()
            replies[name] = (client.get(url).json(), time.monotonic() - started)

        slow = threading.Thread(target=check, args=("connections", "/api/connections?refresh=true"))
        slow.start()
        time.sleep(0.3)  # the codex probe is now waiting on the hung CLI
        check("health", "/api/health")
        slow.join(10)
    health, health_seconds = replies["health"]
    assert health["status"] == "ok" and health_seconds < 1  # answered while the codex probe was still waiting
    connections, seconds = replies["connections"]
    assert seconds < 5
    status = connections["models"]["codex"]
    assert (status["installed"], status["ready"], status["reason_code"]) == (True, False, "timeout")
    assert status["reason"] == "Codex CLI is not responding"
    assert connections["models"]["fake"]["ready"] is True  # the other connection's check is not hidden


def test_tesseract_is_asked_twice_at_once_and_undecodable_output_still_reports(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "tesseract", b"#!/bin/sh\nsleep 1\nif [ \"$1\" = --version ]; then printf 'tesseract 5.5.2 \\376\\375\\n'; "
                                  b"else printf 'List of available languages (2):\\neng\\ntur \\377\\n'; fi\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    started = time.monotonic()
    status = ocr.tesseract_status(("eng",))
    assert time.monotonic() - started < 1.8  # both questions are asked side by side, each taking 1 s
    assert (status["available"], status["version"], status["languages"]) == (True, "5.5.2", ["eng"])


def test_a_required_job_that_cannot_be_joined_kills_the_process_without_running_it(monkeypatch):
    """The folder lock holder's command must not run outside the job: no resume, the process is killed, the caller told."""
    calls = windows(monkeypatch, AssignProcessToJobObject=0)
    proc = FakeProc()
    with pytest.raises(OSError, match="stopped, not run"):
        cli_process.track(proc, require_job=True)
    assert not any(c[0] == "NtResumeProcess" for c in calls) and ("CloseHandle", 7) in calls and proc.returncode == -9
    calls = windows(monkeypatch, CreateJobObjectW=None)
    other = FakeProc()
    with pytest.raises(OSError):
        cli_process.track(other, require_job=True)
    assert not any(c[0] == "NtResumeProcess" for c in calls) and other.returncode == -9
    ok = windows(monkeypatch)
    cli_process.track(FakeProc(), require_job=True)
    assert [c[0] for c in ok].index("AssignProcessToJobObject") < [c[0] for c in ok].index("NtResumeProcess")
