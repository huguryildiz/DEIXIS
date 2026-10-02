"""P9 H2: what a child process does when its parent is killed with SIGKILL.

The kill is `os.kill` on the helper parent's one PID (never a group kill: no production child starts its own session,
and a real crash ends one process). A child that is alive after the parent is confirmed dead proves it did not die
with the parent; its end is then its own. Stand-ins, not the real `codex` (that is H10): a stand-in that never reads
its stdin is not tested, because whether the real program ends on stdin EOF is a property of that program.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
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


def test_extraction_child_is_ended_by_its_own_lifetime(harness, tmp_path):
    """The parent's 90 s clock and 1 GiB limit die with it; the child's own alarm is what ends an orphan."""
    from scripts.p9 import memory_probe

    big = tmp_path / "big.pdf"
    memory_probe.build_pdf(big, 60 * 1024 * 1024)
    proc, _ = run_parent(harness, tmp_path, ["pdf", str(big)], {"DEIXIS_CHILD_LIFETIME_SECONDS": "8"})
    child = wait_for(lambda: next((i for i in descendants(proc.pid) if "deixis.documents.pdf" in i.command), None), 20,
                     "the extraction child")
    seen = time.monotonic()
    time.sleep(1.0)
    kill_parent(harness, proc)
    time.sleep(max(0.0, seen + 5.0 - time.monotonic()))
    assert is_same_and_live(child), "the orphan was not alive 5 s after it was first seen (it must not pass by crashing early)"
    time.sleep(max(0.0, seen + 6.0 - time.monotonic()))  # lifetime (8 s) - 2 s
    assert is_same_and_live(child), ("the orphan ended before lifetime - 2 s (6 s after it was first seen): it ended early, "
                                     "and by what means could not be known (alarm, the in-child memory watchdog, or the extraction finishing)")
    wait_gone([child], 8 + 5 - (time.monotonic() - seen), "the orphaned extraction child (lifetime 8 s, limit 13 s after first seen)")
    print(f"child pdf: first seen alive, gone {time.monotonic() - seen:.1f} s later (lifetime 8 s, parent killed at 1 s)")


def test_default_child_lifetime_is_above_every_parent_clock():
    from deixis.documents import arxiv_source, jats, ocr, pdf

    assert pdf.CHILD_LIFETIME_SECONDS == 100
    assert pdf.CHILD_LIFETIME_SECONDS > max(pdf.TIMEOUT_SECONDS, ocr.TIMEOUT_SECONDS, jats.RENDER_TIMEOUT_SECONDS,
                                            arxiv_source.CHILD_TIMEOUT_SECONDS)
