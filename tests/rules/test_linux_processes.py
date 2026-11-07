"""The desktop process layer's Linux parts (P10 L2): the watchdog as child subreaper, identities tied to the boot, and
kills through a pidfd. The shared layer (record, launcher, watchdog) is tested in test_desktop_sidecar.py."""

import errno
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from deixis import desktop_reaper
from deixis.documents import child_guard
from deixis.tools import child_record

pytestmark = [pytest.mark.process,
              pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process layer (subreaper, pidfd, boot id)")]
BACKEND = str(Path(__file__).resolve().parents[2])


def test_an_orphan_that_left_with_setsid_after_the_last_scan_is_adopted_killed_and_reaped(tmp_path):
    # The watchdog as subreaper: a child double-forks a grandchild into its own session and exits, after the last scan.
    # The grandchild is re-parented to the watchdog, not to init; the stop's subtree sweep kills it and reaps it.
    out = tmp_path / "out.json"
    script = textwrap.dedent(f"""
        import json, os, subprocess, sys, time
        sys.path.insert(0, {BACKEND!r})
        from deixis import desktop_reaper
        from deixis.tools import child_record
        assert desktop_reaper.become_subreaper()
        backend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        reaper = desktop_reaper.Reaper(backend.pid, child_record.process_info(backend.pid).start)
        reaper.subreaper = True
        reaper.scan()  # the last scan, before the escape
        middle = subprocess.Popen([sys.executable, "-c",
            "import os, subprocess, sys; subprocess.Popen(['/bin/sleep', '61'], start_new_session=True); "
            "print(os.getpid(), flush=True)"], stdout=subprocess.PIPE, text=True)
        middle.stdout.readline(); middle.wait()
        time.sleep(0.3)
        table = child_record.snapshot()
        orphan = next(pid for pid, (ppid, _g, _s) in table.items() if ppid == os.getpid() and pid != backend.pid)
        orphan_ident = child_record.identity(orphan)
        adopted = table[orphan][0] == os.getpid() and os.getsid(orphan) == orphan
        backend.kill(); backend.wait()
        killed = reaper.stop()
        zombie = os.path.exists(f"/proc/{{orphan}}") and open(f"/proc/{{orphan}}/stat").read().rsplit(")", 1)[1].split()[0]
        json.dump({{"adopted": adopted, "killed": orphan_ident in killed, "alive": child_record.alive(orphan_ident),
                    "zombie": zombie, "backend_code": backend.returncode}}, open({str(out)!r}, "w"))
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(out.read_text())
    assert result["adopted"] and result["killed"] and not result["alive"]
    assert result["zombie"] is False  # reaped by the watchdog, not left as a zombie
    assert result["backend_code"] == -signal.SIGKILL  # the backend's own status stayed with Popen


def test_the_watchdog_refuses_to_start_the_backend_without_the_subreaper(monkeypatch, capsys):
    monkeypatch.setattr(desktop_reaper, "become_subreaper", lambda: False)
    assert desktop_reaper.main([]) == 1
    line = json.loads(capsys.readouterr().out.strip())
    assert line["event"] == "startup_failed" and line["code"] == "process_guard"


def test_an_identity_names_its_boot_and_a_line_from_an_earlier_boot_is_dropped_without_a_signal(tmp_path):
    proc = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    try:
        start = child_record.identity(proc.pid).partition(":")[2]
        assert start.startswith(child_guard.boot_id() + "/")
        ticks = start.partition("/")[2]
        earlier = f"00000000-0000-0000-0000-000000000000/{ticks}"  # same pid and ticks, another boot
        record = child_record.record_path(tmp_path)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"pid": proc.pid, "start": earlier, "pgid": proc.pid, "sid": proc.pid,
                                      "owner": f"1:{earlier}", "kind": "cli"}) + "\n")
        assert child_record.recover(record) == []
        assert child_record.entries(record) == [] and proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_a_kill_goes_through_a_pidfd_and_never_reaches_a_changed_identity(monkeypatch):
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        ident = child_record.identity(proc.pid)
        pid, _, start = ident.partition(":")
        assert not child_guard.signal_identity(int(pid), start + "0", signal.SIGKILL)  # another process now
        assert proc.poll() is None

        def no_descriptor(_pid):
            raise OSError(errno.EMFILE, "Too many open files")
        monkeypatch.setattr(os, "pidfd_open", no_descriptor)
        assert not child_record.kill_identity(ident)  # cannot be sure: not signalled (the sweep tries again)
        assert proc.poll() is None

        def old_kernel(_pid):
            raise OSError(errno.ENOSYS, "Function not implemented")
        monkeypatch.setattr(os, "pidfd_open", old_kernel)
        assert child_record.kill_identity(ident)  # check-then-kill, as on macOS
        assert proc.wait(5) == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_the_pdf_guard_kills_through_the_same_pidfd_rule():
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        info = child_guard.process_info(proc.pid)
        guard = child_guard.Guard(proc.pid, info.start + "0", os.getpid(), "x", 1, time.monotonic() + 60)
        assert not guard.signal_once() and proc.poll() is None
        guard.child_start = info.start
        assert guard.signal_once() and proc.wait(5) == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_the_pdf_guard_tries_again_when_it_could_not_signal_and_kills_once_it_can(monkeypatch, tmp_path):
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        info = child_guard.process_info(proc.pid)
        guard = child_guard.Guard(proc.pid, info.start, os.getpid(), "x", 1, time.monotonic() + 30)
        guard.turn = lambda now: ("kill", 2)
        failures = iter([OSError(errno.EMFILE, "Too many open files")] * 3)
        real = os.pidfd_open

        def flaky(pid):
            error = next(failures, None)
            if error:
                raise error
            return real(pid)
        monkeypatch.setattr(os, "pidfd_open", flaky)
        actions = []
        ready = os.pipe()
        monkeypatch.setattr(sys, "argv", ["guard"] * 7 + [str(ready[1])])
        child_guard.watch(guard, lambda action, rss=None: actions.append(action))
        assert actions[:2] == ["ready", "kill"] and actions.count("signal_failed") == 3
        assert proc.wait(5) == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_a_child_a_scan_missed_is_still_found_because_the_kernel_counts_it(tmp_path):
    # A /proc scan can miss a process that forks and exits while it is read. After the backend is waited for, the
    # watchdog ends only once waitid says it has no child at all; a live one leads to another sweep.
    out = tmp_path / "out.json"
    script = textwrap.dedent(f"""
        import json, os, subprocess, sys
        sys.path.insert(0, {BACKEND!r})
        from deixis import desktop_reaper
        from deixis.tools import child_record
        assert desktop_reaper.become_subreaper()
        backend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        missed = subprocess.Popen(["/bin/sleep", "62"])  # a child every scan below misses at first
        ident = child_record.identity(missed.pid)
        reaper = desktop_reaper.Reaper(backend.pid, child_record.process_info(backend.pid).start)
        reaper.subreaper = True
        blind = [4]
        def snapshot():
            blind[0] -= 1
            table = child_record.snapshot()
            return {{p: v for p, v in table.items() if p != missed.pid}} if blind[0] > 0 else table
        reaper.snapshot = snapshot
        backend.kill(); backend.wait()
        import time
        reaper.stop(time.monotonic() + 10)
        drained = reaper.drain(time.monotonic() + 10)
        json.dump({{"drained": drained, "alive": child_record.alive(ident)}}, open({str(out)!r}, "w"))
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(out.read_text()) == {"drained": True, "alive": False}


def test_a_cancel_kills_the_program_and_the_launcher_empties_its_session_before_it_ends(tmp_path):
    program = ("import subprocess, time; subprocess.Popen(['/bin/sleep', '63']); "
               "subprocess.Popen(['/bin/sleep', '64'], process_group=0); time.sleep(61)")
    argv = child_record.launcher_argv([sys.executable, "-c", program], "cli")  # the record is off here
    launcher = subprocess.Popen(argv, start_new_session=True, env=os.environ | {"PYTHONPATH": BACKEND})
    try:
        leader = child_record.identity(launcher.pid)
        ends = time.monotonic() + 10
        while len(child_record.members(leader)) < 3 and time.monotonic() < ends:
            time.sleep(0.05)
        session = child_record.members(leader)
        assert len(session) == 3
        found = child_record.stop_group(launcher.pid, leader, signal.SIGKILL)
        assert session <= found and leader in found
        assert launcher.wait(15) == -signal.SIGKILL  # it ends as its program did, once its session is empty
        assert not any(child_record.alive(i) for i in session)
    finally:
        if launcher.poll() is None:
            os.killpg(launcher.pid, signal.SIGKILL)
            launcher.wait()


def test_without_a_boot_id_the_watchdog_refuses_and_no_identity_is_read(monkeypatch, capsys):
    monkeypatch.setattr(desktop_reaper, "become_subreaper", lambda: True)
    monkeypatch.setattr(child_guard, "_boot_id", lambda: None)
    assert child_guard.process_info(os.getpid()) is None and child_record.identity(os.getpid()) is None
    assert desktop_reaper.main([]) == 1
    assert json.loads(capsys.readouterr().out.strip())["code"] == "process_guard"


def run_launcher_with(tmp_path, patch: str) -> tuple[int, bool]:
    """session_launcher.main in a fresh process with `patch` applied first; (exit code, whether PROGRAM ran)."""
    marker = tmp_path / "program-ran"
    script = textwrap.dedent(f"""
        import os, signal, sys
        sys.path.insert(0, {BACKEND!r})
        from deixis import session_launcher
        from deixis.tools import child_record
        real_identity = child_record.identity
        {patch}
        sys.exit(session_launcher.main(["-", "-", "cli", "--", "/usr/bin/touch", {str(marker)!r}]))
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    return done.returncode, marker.exists()


def test_a_cancel_that_reaches_the_launcher_before_its_program_starts_means_the_program_never_runs(tmp_path):
    patch = ("def identity(pid):\n"
             "            os.kill(os.getpid(), session_launcher.CANCEL)  # stop_group's cancel, before Popen\n"
             "            return real_identity(pid)\n"
             "        child_record.identity = identity")
    code, ran = run_launcher_with(tmp_path, patch)
    assert (code, ran) == (128 + signal.SIGKILL, False)


def test_a_launcher_whose_own_identity_cannot_be_read_starts_nothing(tmp_path):
    code, ran = run_launcher_with(tmp_path, "child_record.identity = lambda pid: None")
    assert (code, ran) == (125, False)  # RECORD_FAILED
    assert run_launcher_with(tmp_path, "pass") == (0, True)  # the same launch with an identity runs


def test_a_cancel_that_arrives_while_the_launcher_prepares_the_program_still_means_it_never_runs(tmp_path):
    patch = ("real_env = session_launcher.program_env\n"
             "        def program_env():\n"
             "            os.kill(os.getpid(), session_launcher.CANCEL)  # after the identity, before the start\n"
             "            return real_env()\n"
             "        session_launcher.program_env = program_env")
    assert run_launcher_with(tmp_path, patch) == (128 + signal.SIGKILL, False)


def test_a_stop_whose_signals_cannot_be_sent_at_first_tries_again_until_they_are(monkeypatch):
    program = "import subprocess, time; subprocess.Popen(['/bin/sleep', '65']); time.sleep(61)"
    launcher = subprocess.Popen(child_record.launcher_argv([sys.executable, "-c", program], "cli"),
                                start_new_session=True, env=os.environ | {"PYTHONPATH": BACKEND})
    try:
        leader = child_record.identity(launcher.pid)
        ends = time.monotonic() + 10
        while len(child_record.members(leader)) < 2 and time.monotonic() < ends:
            time.sleep(0.05)
        session = child_record.members(leader)
        failures = iter([OSError(errno.EMFILE, "Too many open files")] * 4)  # every member and the cancel fail once
        real = os.pidfd_open

        def flaky(pid):
            error = next(failures, None)
            if error:
                raise error
            return real(pid)
        monkeypatch.setattr(os, "pidfd_open", flaky)
        child_record.stop_group(launcher.pid, leader, signal.SIGKILL)
        assert launcher.wait(15) == -signal.SIGKILL
        assert not any(child_record.alive(i) for i in session)
    finally:
        if launcher.poll() is None:
            os.killpg(launcher.pid, signal.SIGKILL)
            launcher.wait()
