"""P10 W2: child protection on Windows with Job Objects (`deixis/tools/win_job.py`), against real processes.

Each child is started suspended, put in a kill-on-close job of its own and only then resumed; the parent's timeout and
the parent's death end the whole job; a grandchild cannot break away; the job handle is never inherited; a job that
cannot be made leaves a process that never ran. The memory limit is named only from the child's MEMORY_EXIT_CODE, the
job's memory message or its peak; any other crash is "the reader stopped".
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from windows_env import system_env

from deixis.documents import pdf
from deixis.models import cli_process
from deixis.tools import win_job

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects (P10 W2); macOS and Linux bound "
                                "their children with process groups and the resident-size watch, tested elsewhere")

REPO = Path(__file__).resolve().parents[2]
ENV = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO), **system_env()}
MB = 1024 * 1024
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def alive(pid: int) -> bool:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = k.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        return k.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        k.CloseHandle(handle)


def gone_within(pids: list[int], seconds: float) -> float:
    started = time.monotonic()
    while any(alive(p) for p in pids):
        assert time.monotonic() - started < seconds, f"still alive after {seconds} s: {[p for p in pids if alive(p)]}"
        time.sleep(0.05)
    return time.monotonic() - started


def wait_for(path: Path, seconds: float = 30) -> str:
    deadline = time.monotonic() + seconds
    while not (path.exists() and path.read_text(encoding="utf-8").strip()):
        assert time.monotonic() < deadline, f"{path.name} was never written"
        time.sleep(0.05)
    return path.read_text(encoding="utf-8").strip()


def python(code: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(code)]


def with_grandchild(folder: Path, sleep: int = 60) -> list[str]:
    """A child that starts a sleeping grandchild, writes both pids, then sleeps."""
    return python(f"""
        import subprocess, sys, time
        g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({sleep})"])
        open(r"{folder / 'pids'}", "w").write(f"{{__import__('os').getpid()}} {{g.pid}}")
        time.sleep({sleep})
    """)


def test_a_child_that_allocates_past_the_limit_ends_as_a_memory_limit():
    # A plain `python -c` does not catch MemoryError (it exits 1 with a traceback): the job's own report names it.
    done = pdf._run_watched(python("x = bytearray(400 * 1024 * 1024)"), ENV, timeout=60, max_memory=200 * MB)
    assert done.returncode == pdf.MEMORY_EXIT_CODE and b"memory limit exceeded" in done.stderr
    # The extraction children catch MemoryError and exit with MEMORY_EXIT_CODE themselves.
    caught = python(f"""
        import sys
        try:
            x = bytearray(400 * 1024 * 1024)
        except MemoryError:
            sys.exit({pdf.MEMORY_EXIT_CODE})
    """)
    assert pdf._run_watched(caught, ENV, timeout=60, max_memory=200 * MB).returncode == pdf.MEMORY_EXIT_CODE


def test_a_crash_that_is_not_a_memory_limit_is_the_reader_stopping(tmp_path, monkeypatch):
    done = pdf._run_watched(python("import os; os._exit(5)"), ENV, timeout=60, max_memory=200 * MB)
    assert done.returncode == 5  # well under the limit: no memory name for an ordinary crash
    monkeypatch.setattr(win_job, "run", lambda *a, **k: win_job.Finished(0xC0000005, b"", b"access violation", False))
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4\n")
    result = pdf.extract_pdf(tmp_path / "x.pdf")
    assert (result.status, result.error) == ("failed", "the PDF reader stopped (exit code 0xc0000005)")


def test_a_child_past_its_timeout_is_gone_with_its_grandchild(tmp_path):
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        pdf._run_watched(with_grandchild(tmp_path), ENV, timeout=5, max_memory=512 * MB)
    assert time.monotonic() - started < 15
    pids = [int(p) for p in wait_for(tmp_path / "pids").split()]
    gone_within(pids, 2)


def test_killing_the_parent_ends_its_child_and_grandchild_within_two_seconds(tmp_path):
    child = with_grandchild(tmp_path, sleep=120)
    parent = subprocess.Popen(python(f"""
        from deixis.tools import win_job
        win_job.run({child!r}, {ENV!r}, 120, 512 * 1024 * 1024)
    """), env=ENV)
    try:
        pids = [int(p) for p in wait_for(tmp_path / "pids").split()]
        assert all(alive(p) for p in pids)
        parent.kill()  # TerminateProcess: no cleanup code of the parent runs
        parent.wait(10)
        seconds = gone_within(pids, 2)
    finally:
        if parent.poll() is None:
            parent.kill()
    assert seconds < 2


def test_a_grandchild_cannot_break_away_from_the_job(tmp_path):
    # Without JOB_OBJECT_LIMIT_BREAKAWAY_OK the flag either fails (ERROR_ACCESS_DENIED) or, as measured on Windows 11 under
    # an outer job, is ignored: the grandchild is created inside the job. Either way it ends with the job.
    child = python(f"""
        import subprocess, sys, time
        try:
            g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], creationflags={CREATE_BREAKAWAY_FROM_JOB})
            said = str(g.pid)
        except OSError as exc:
            said = f"refused {{exc.winerror}}"
        open(r"{tmp_path / 'said'}", "w").write(said)
        time.sleep(60)
    """)
    with pytest.raises(subprocess.TimeoutExpired):
        pdf._run_watched(child, ENV, timeout=5, max_memory=512 * MB)
    said = wait_for(tmp_path / "said")
    assert said == "refused 5" or gone_within([int(said)], 2) < 2


def test_the_job_handle_is_not_inherited(tmp_path):
    first = subprocess.Popen(python("import time; time.sleep(60)"), env=ENV, creationflags=win_job.CREATION_FLAGS)
    job = win_job.start_in_job(first, 512 * MB)
    try:
        flags = ctypes.c_uint32()
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetHandleInformation.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        assert k.GetHandleInformation(job.handle, ctypes.byref(flags)) and not flags.value & 1  # HANDLE_FLAG_INHERIT
        # A later child created with handle inheritance on cannot use the job's handle value.
        probe = subprocess.run(python(f"""
            import ctypes
            k = ctypes.WinDLL("kernel32")
            k.QueryInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)
            buf = ctypes.create_string_buffer(256)
            print("usable" if k.QueryInformationJobObject({job.handle}, 9, buf, 256, None) else "unusable")
        """), env=ENV, close_fds=False, capture_output=True, text=True, timeout=60)
        assert probe.stdout.strip() == "unusable"
    finally:
        job.terminate()
        job.close()
        first.wait(10)


def test_a_process_that_cannot_join_its_job_is_stopped_unrun(tmp_path, monkeypatch):
    marker = tmp_path / "ran"

    class Refuses:
        def NtResumeProcess(self, handle):  # noqa: N802 - the ntdll name
            return -1

    proc = subprocess.Popen(python(f"open(r'{marker}', 'w').write('ran')"), env=ENV, creationflags=win_job.CREATION_FLAGS)
    monkeypatch.setattr(win_job, "_ntdll", Refuses)
    with pytest.raises(win_job.JobError):
        win_job.start_in_job(proc)
    assert proc.wait(10) == 1 and not marker.exists()


def test_a_cli_and_its_grandchild_end_with_stop_group(tmp_path):
    async def run() -> list[int]:
        proc = await asyncio.create_subprocess_exec(*with_grandchild(tmp_path), env=ENV, **cli_process.spawn_options())
        cli_process.track(proc)
        pids = [int(p) for p in (await asyncio.to_thread(wait_for, tmp_path / "pids")).split()]
        cli_process.stop_group(proc)
        await cli_process.reap(proc)
        return pids

    gone_within(asyncio.run(run()), 2)


def test_a_cli_that_cannot_join_its_job_is_a_local_start_error(tmp_path, monkeypatch):
    from deixis.tools import tool_probe

    class Refuses:
        def NtResumeProcess(self, handle):  # noqa: N802 - the ntdll name
            return -1

    monkeypatch.setattr(win_job, "_ntdll", Refuses)
    marker = tmp_path / "ran"
    found = tool_probe.probe_blocking(python(f"open(r'{marker}', 'w').write('ran')"), env=ENV)
    assert found.error == "failed" and not marker.exists()


def left_behind(folder: Path) -> list[str]:
    """A stand-in for a model CLI: it starts a sleeping grandchild that keeps no pipe of DEIXIS, writes both pids, and
    exits once DEIXIS closes its stdin, leaving the grandchild behind."""
    return python(f"""
        import os, subprocess, sys
        g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(r"{folder / 'pids'}", "w").write(f"{{os.getpid()}} {{g.pid}}")
        sys.stdin.read()
    """)


def test_closing_the_codex_app_server_ends_what_it_started(tmp_path):
    from deixis.models.codex_rpc import CodexAppServer

    async def run() -> list[int]:
        server = CodexAppServer(left_behind(tmp_path), cwd=str(tmp_path), env=ENV)
        await server.start()
        assert cli_process._JOBS.get(server.proc) is not None
        pids = [int(p) for p in (await asyncio.to_thread(wait_for, tmp_path / "pids")).split()]
        assert all(alive(p) for p in pids)
        await server.close()  # stdin closed: the stand-in exits on its own, its grandchild does not
        return pids

    gone_within(asyncio.run(run()), 2)


def claude_stand_in(argv: list[str]):
    """The Claude transport DEIXIS uses on Windows, starting `argv` instead of the CLI's command line."""
    from deixis.models import claude

    class StandIn(claude.JobTransport):
        def _build_command(self) -> list[str]:
            return argv

    return StandIn


def test_closing_the_claude_cli_connection_ends_what_the_cli_started(tmp_path, monkeypatch):
    from claude_agent_sdk import ClaudeAgentOptions

    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")  # the stand-in is no CLI that answers --version
    transport = claude_stand_in(left_behind(tmp_path))(prompt="", options=ClaudeAgentOptions(cli_path=sys.executable,
                                                                                               cwd=tmp_path, env=ENV))

    async def run() -> list[int]:
        await transport.connect()  # the SDK's own spawn, put in a job before the CLI runs
        assert cli_process._JOBS.get(transport._process) is not None
        pids = [int(p) for p in (await asyncio.to_thread(wait_for, tmp_path / "pids")).split()]
        assert all(alive(p) for p in pids)
        await transport.close()
        return pids

    gone_within(asyncio.run(run()), 2)


def test_a_claude_cli_that_cannot_join_its_job_never_runs(tmp_path, monkeypatch):
    from claude_agent_sdk import ClaudeAgentOptions, CLIConnectionError

    from deixis.models import claude

    class Refuses:
        def NtResumeProcess(self, handle):  # noqa: N802 - the ntdll name
            return -1

    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(win_job, "_ntdll", Refuses)
    marker = tmp_path / "ran"
    transport = claude_stand_in(python(f"open(r'{marker}', 'w').write('ran')"))(
        prompt="", options=ClaudeAgentOptions(cli_path=sys.executable, cwd=tmp_path, env=ENV))
    with pytest.raises(CLIConnectionError) as failed:
        asyncio.run(transport.connect())
    assert claude._not_started(failed.value) and not marker.exists()  # nothing was sent


def test_a_pdf_reader_that_cannot_join_its_job_is_a_recorded_failure(tmp_path, monkeypatch):
    class Refuses:
        def NtResumeProcess(self, handle):  # noqa: N802 - the ntdll name
            return -1

    monkeypatch.setattr(win_job, "_ntdll", Refuses)
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4\n")
    result = pdf.extract_pdf(tmp_path / "x.pdf")
    assert (result.status, result.error) == ("failed", "extraction memory limit could not be watched")
