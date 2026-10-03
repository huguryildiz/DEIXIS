"""P9 H2: what a child process does when its parent is killed with SIGKILL.

The kill is `os.kill` on the helper parent's one PID (never a group kill: no production child starts its own session,
and a real crash ends one process). A child that is alive after the parent is confirmed dead proves it did not die
with the parent; its end is then its own. Stand-ins, not the real `codex` (that is H10): a stand-in that never reads
its stdin is not tested, because whether the real program ends on stdin EOF is a property of that program.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
import json
import os
import signal
import select
import subprocess
import sys
import time

import pytest
from p9_harness import HERE, child_env, descendants, harness, ident_of, is_same_and_live, wait_for, wait_gone  # noqa: F401

pytestmark = pytest.mark.process
PARENT = HERE / "p9_child_parent.py"


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


@pytest.mark.parametrize("mode,limit", [("idle", 3), ("busy:3", 8)])
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


@pytest.mark.parametrize("runner,busy,limit", [("ok", "idle", 3), ("slow:3", "busy", 8)])
def test_embedding_runner_ends_by_itself_and_frees_its_lock(harness, tmp_path, runner, busy, limit):
    data = tmp_path / "embedding-data"
    data.mkdir()
    proc, line = run_parent(harness, tmp_path, ["embedding", busy], {"FAKE_RUNNER": runner, "DEIXIS_DATA_DIR": str(data)})
    child = child_of(proc, line["child_pid"])
    lock = data / "tools" / "embedding-in-use.lock"
    assert lock.exists()
    probe = os.open(lock, os.O_RDWR)
    with pytest.raises(OSError):  # the runner holds the in-use lock while it lives
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    killed = kill_parent(harness, proc)
    if busy == "busy":
        time.sleep(max(0.0, killed + 1.0 - time.monotonic()))
        assert is_same_and_live(child), "positive control: the runner must outlive its parent while it is answering"
    wait_gone([child], limit, f"embedding runner {runner}")
    print(f"child embedding {runner}: gone {time.monotonic() - killed:.2f} s after the kill")
    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free once the runner is gone
    os.close(probe)


@contextmanager
def pdf_case(tmp_path, lifetime="60", guard=True, limit=250 * 1024**2):
    """Native start-time readers and kqueue, independent of ps and without adopting the child."""
    from deixis.documents import child_guard as cg
    from scripts.p9 import memory_probe
    from test_child_guard import wait_for as native_wait, log_rows

    big, ready, gate, log = [tmp_path / name for name in ("big.pdf", "ready.json", "gate", "guard.jsonl")]
    memory_probe.build_pdf(big, 67 * 1024**2)
    env = {"PYTHONPATH": str(HERE.parent.parent / "backend"), "DEIXIS_CHILD_LIFETIME_SECONDS": lifetime,
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


def check_extraction_lifetime(tmp_path, armed):
    with pdf_case(tmp_path, lifetime="8" if armed else "0", guard=False, limit=64 * 1024**3) as case:
        parent, child, identity, gate, _, _, observer, _ = case
        orphan(parent, child, identity)
        gate.touch()
        if armed:
            assert end_signal(observer, 13) == signal.SIGALRM
        else:
            with pytest.raises(AssertionError, match="no child exit"):
                end_signal(observer, 13)
        print(f"lifetime armed={armed}: " + ("observed SIGALRM" if armed else "disabled control remained alive for 13 s"))


@pytest.mark.skipif(sys.platform != "darwin", reason="non-adopting kqueue exit-status evidence requires macOS")
def test_extraction_child_is_ended_by_its_own_lifetime(tmp_path):
    check_extraction_lifetime(tmp_path, True)


@pytest.mark.skipif(sys.platform != "darwin", reason="non-adopting kqueue exit-status evidence requires macOS")
def test_extraction_child_lifetime_disabled_control(tmp_path):
    check_extraction_lifetime(tmp_path, False)


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


@pytest.mark.skipif(sys.platform != "darwin", reason="non-adopting kqueue exit-status evidence requires macOS")
def test_orphan_memory_guard_disabled_control(tmp_path):
    check_orphan_memory(tmp_path, False)


@pytest.mark.skipif(sys.platform != "darwin", reason="real topology and kqueue evidence requires macOS")
def test_orphan_guard_parent_alive_preserves_pdf_memory_failure(tmp_path):
    from deixis.documents import pdf
    from scripts.p9 import memory_probe
    big = tmp_path / "big.pdf"
    memory_probe.build_pdf(big, 67 * 1024**2)
    result = pdf.extract_pdf(big, max_memory=250 * 1024**2)
    assert result == pdf.Extraction("failed", error="extraction exceeded the memory limit")


@pytest.mark.skipif(sys.platform != "darwin", reason="exit-status observation requires macOS kqueue")
def test_lifetime_observer_rejects_normal_completion():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.2)"])
    observer = select.kqueue()
    try:
        observer.control([select.kevent(proc.pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                        fflags=select.KQ_NOTE_EXIT | 0x04000000)], 0, 0)
        with pytest.raises(AssertionError, match="ended without a signal"):
            end_signal(observer, 10)
        assert proc.wait(5) == 0
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait()
        observer.close()


def test_default_child_lifetime_is_above_every_parent_clock():
    from deixis.documents import arxiv_source, jats, ocr, pdf

    assert pdf.CHILD_LIFETIME_SECONDS == 100
    assert pdf.CHILD_LIFETIME_SECONDS > max(pdf.TIMEOUT_SECONDS, ocr.TIMEOUT_SECONDS, jats.RENDER_TIMEOUT_SECONDS,
                                            arxiv_source.CHILD_TIMEOUT_SECONDS)
