"""P9 H2: what a child process does when its parent is killed with SIGKILL.

The kill is `os.kill` on the helper parent's one PID (never a group kill: a real crash ends one process; the
built-in models' llama-server is the one child that starts its own session, under a watcher of its parent's pipe). A child that is alive after the parent is confirmed dead proves it did not die
with the parent; its end is then its own. Stand-ins, not the real `codex` (that is H10): a stand-in that never reads
its stdin is not tested, because whether the real program ends on stdin EOF is a property of that program.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import signal
import select
import subprocess
import sys
import time

import pytest
from process_harness import HERE, child_env, descendants, harness, ident_of, is_same_and_live, wait_for, wait_gone  # noqa: F401

pytestmark = pytest.mark.process
PARENT = HERE / "child_parent.py"


def run_parent(harness, tmp_path, args, env):
    """The helper parent with its one JSON line read from a file-backed stdout (no unread pipe)."""
    out = tmp_path / "parent-stdout.jsonl"
    handle = open(out, "wb")
    proc = subprocess.Popen([sys.executable, str(PARENT), *args], env=child_env(harness.home, **env), cwd=harness.cwd,
                            stdout=handle, stderr=subprocess.STDOUT)
    handle.close()
    harness.popens.append(proc)
    harness.track(ident_of(proc.pid))

    def first_line():
        text = out.read_text() if out.exists() else ""
        if proc.poll() is not None and not text:
            pytest.fail(f"the helper parent ended with {proc.returncode} before it printed:\n{text}")
        return json.loads(text.splitlines()[0]) if text.strip() else None

    return proc, wait_for(first_line, 60, "the helper parent's first line")


def kill_parent(harness, proc):
    """SIGKILL to the helper parent's one PID; returns the moment of the kill. The parent is confirmed dead by Popen."""
    harness.record_descendants(proc.pid)
    killed = time.monotonic()
    os.kill(proc.pid, signal.SIGKILL)
    assert proc.wait(timeout=10) == -signal.SIGKILL
    assert proc.poll() is not None  # never `os.kill(pid, 0)`: a dead, unwaited child looks alive to it
    return killed


def child_of(proc, pid):
    (ident,) = [i for i in descendants(proc.pid) if i.pid == pid]
    return ident


@pytest.mark.parametrize("mode,limit", [("idle", 3)])
def test_codex_rpc_child_ends_by_itself(harness, tmp_path, mode, limit):
    proc, line = run_parent(harness, tmp_path, ["codex", mode], {})
    child = child_of(proc, line["child_pid"])
    assert is_same_and_live(child)
    killed = kill_parent(harness, proc)
    if mode.startswith("busy"):
        time.sleep(max(0.0, killed + 1.0 - time.monotonic()))
        assert is_same_and_live(child), "positive control: the child must outlive its parent (it did not read stdin)"
    wait_gone([child], limit, f"codex stand-in {mode}")
    print(f"child codex {mode}: gone {time.monotonic() - killed:.2f} s after the kill")


@contextmanager
def pdf_case(tmp_path, lifetime="60", guard=True, limit=250 * 1024**2):
    """Native start-time readers and kqueue, independent of ps and without adopting the child."""
    from deixis.documents import child_guard as cg
    from scripts.release_checks import memory_probe
    from test_child_guard import wait_for as native_wait, log_rows

    big, ready, gate, log = [tmp_path / name for name in ("big.pdf", "ready.json", "gate", "guard.jsonl")]
    memory_probe.build_pdf(big, 67 * 1024**2)
    env = {"PYTHONPATH": str(HERE.parent.parent), "DEIXIS_CHILD_LIFETIME_SECONDS": lifetime,
           "DEIXIS_CHILD_GUARD_DISABLED": "0" if guard else "1", "DEIXIS_CHILD_GUARD_LOG": str(log),
           "DEIXIS_TEST_MEMORY_LIMIT": str(limit)}
    out = tmp_path / "parent.jsonl"
    child, guard_pid = None, None
    observer = select.kqueue()
    with out.open("wb") as fh:
        parent = subprocess.Popen([sys.executable, str(PARENT), "pdf-gated", str(big), str(ready), str(gate)],
                                  env=env, stdout=fh, stderr=subprocess.STDOUT)
    try:
        line = native_wait(lambda: json.loads(ready.read_text()) if ready.exists() and ready.stat().st_size else None, 30)
        child = line["pid"]
        identity = cg.process_info(child)
        assert identity and identity.ppid == parent.pid == line["parent"]
        rss = cg._resident_bytes(child)
        assert rss is not None and rss < limit, (rss, limit)
        guard_row = native_wait(lambda: next((r for r in log_rows(log) if r["action"] == "ready"), None)) if guard else None
        guard_pid = guard_row["guard_pid"] if guard_row else None
        # NOTE_EXITSTATUS is 0x04000000 in the installed macOS SDK sys/event.h;
        # Python does not expose that constant. It is allowed when the observer can signal the target.
        observer.control([select.kevent(child, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                        fflags=select.KQ_NOTE_EXIT | 0x04000000)], 0, 0)
        yield parent, child, identity, gate, log, out, observer, guard_pid
    finally:
        if parent.poll() is None: parent.kill()
        parent.wait(10)
        if child is not None and (current := cg.process_info(child)) and current.start == identity.start:
            os.kill(child, signal.SIGKILL)
            native_wait(lambda: cg.process_info(child) is None)
        if guard_pid is not None:
            native_wait(lambda: cg.process_info(guard_pid) is None)
        observer.close()


def end_signal(observer, timeout):
    events = observer.control(None, 1, timeout)
    assert events, "no child exit observed"
    event = events[0]
    assert event.fflags & 0x04000000, "kernel did not supply NOTE_EXITSTATUS"
    assert os.WIFSIGNALED(event.data), f"child ended without a signal: wait status {event.data}"
    return os.WTERMSIG(event.data)


def orphan(parent, child, identity):
    from deixis.documents import child_guard as cg
    from test_child_guard import wait_for as native_wait
    parent.kill()
    assert parent.wait(10) == -signal.SIGKILL
    native_wait(lambda: (info := cg.process_info(child)) and info.start == identity.start and info.ppid != parent.pid)


def check_orphan_memory(tmp_path, enabled):
    from deixis.documents import child_guard as cg
    from test_child_guard import wait_for as native_wait, log_rows
    limit = 250 * 1024**2
    with pdf_case(tmp_path, guard=enabled, limit=limit) as case:
        parent, child, identity, gate, log, _, observer, guard_pid = case
        orphan(parent, child, identity)
        gate.touch()
        crossed = native_wait(lambda: rss if (rss := cg._resident_bytes(child)) is not None and rss > limit else None, 15) if not enabled else None
        if enabled:
            action = native_wait(lambda: next((r for r in log_rows(log) if r["action"] == "kill"), None), 15)
            assert action["pid"] == child and action["resident_bytes"] > limit
            assert end_signal(observer, 5) == signal.SIGKILL
            latency = time.monotonic() - action["monotonic"]
            native_wait(lambda: cg.process_info(guard_pid) is None)
            bound = time.monotonic() - action["last_under_at"]
            print(f"orphan memory guard: RSS={action['resident_bytes']} limit={limit}; kill-sample to observed death {latency:.4f}s; last-under to observation upper bound {bound:.4f}s")
        else:
            with pytest.raises(AssertionError, match="no child exit"):
                end_signal(observer, 2)
            assert cg.process_info(child).start == identity.start
            print(f"disabled guard: orphan still alive above limit, RSS={crossed}")


@pytest.mark.skipif(sys.platform != "darwin", reason="non-adopting kqueue exit-status evidence requires macOS")
def test_orphan_memory_guard_stops_gil_holding_pdf_by_sigkill(tmp_path):
    check_orphan_memory(tmp_path, True)


