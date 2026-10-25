"""Guard decisions and real startup/lifecycle checks, without MuPDF in the guard."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from deixis.documents import child_guard as cg, pdf, ocr, jats, arxiv_source

BACKEND = str(Path(__file__).resolve().parents[2])
SUPPORTED = pytest.mark.skipif(not pdf._watch_supported(), reason="resident guard supports macOS and Linux")


def wait_for(call, seconds=10):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        value = call()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError("condition not observed before deadline")


def log_rows(path):
    if not path.exists():
        return []
    return [json.loads(row) for row in path.read_text().splitlines() if row]


@pytest.mark.parametrize("parent,rss,want", [(cg.ProcessInfo("parent", 1), 200, "wait"),
                                           (None, 200, "kill")])
def test_guard_decisions(parent, rss, want):
    guard = cg.Guard(10, "child", 20, "parent", 100, 10)
    assert guard.turn(0, lambda pid: cg.ProcessInfo("child", 20) if pid == 10 else parent, lambda _: rss) == (want, None if parent and parent.start == "parent" else rss)


def test_reparented_child_is_orphan_even_when_original_parent_is_alive():
    guard = cg.Guard(10, "child", 20, "parent", 100, 10)
    assert guard.turn(0, lambda pid: cg.ProcessInfo("child", 1) if pid == 10 else cg.ProcessInfo("parent", 1), lambda _: 200)[0] == "kill"


def test_unreadable_orphan_rss_fails_closed_after_bounded_turns():
    guard = cg.Guard(10, "child", 20, "parent", 100, 10)
    read = lambda pid: cg.ProcessInfo("child", 1) if pid == 10 else None
    for _ in range(cg.WATCH_LOST_TURNS - 1):
        assert guard.turn(0, read, lambda _: None)[0] == "wait"
    assert guard.turn(0, read, lambda _: None)[0] == "kill"


def test_final_start_time_check_refuses_pid_reuse():
    sent = []
    guard = cg.Guard(10, "child", 20, "parent", 100, 10)
    assert not guard.signal_once(lambda _: cg.ProcessInfo("replacement", 1), lambda *args: sent.append(args))
    assert sent == []
    assert guard.signal_once(lambda _: cg.ProcessInfo("child", 1), lambda *args: sent.append(args))
    assert sent == [(10, signal.SIGKILL)]


@SUPPORTED
def test_guard_start_failure_exits_before_any_extraction(tmp_path):
    target = tmp_path / "must-not-extract"
    code = ("from deixis.documents import pdf; from pathlib import Path\n"
            "def fail(*a): raise OSError('cannot start guard')\n"
            "pdf.child_guard.start_guard=fail\npdf._watch_memory(10**12)\n"
            f"Path({str(target)!r}).write_text('extracted')")
    if old := os.environ.get("RR_B_OLD_PDF"):
        source = Path(old).read_text()
        function = source[source.index("def _watch_memory("):source.index("\n\nWATCH_INTERVAL_SECONDS")]
        code = "from deixis.documents import pdf\nexec(" + repr(function) + ",pdf.__dict__)\n" + code
    done = subprocess.run([sys.executable, "-c", code], env={"PYTHONPATH": BACKEND}, timeout=15)
    assert done.returncode == cg.GUARD_EXIT_CODE and not target.exists()


@SUPPORTED
def test_guard_readiness_timeout_is_fail_closed_and_reaped(monkeypatch):
    class Fake:
        pid = 9
        killed = waited = False
        def kill(self): self.killed = True
        def wait(self): self.waited = True
    fake = Fake()
    monkeypatch.setattr(cg.subprocess, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(cg.select, "select", lambda *a: ([], [], []))
    with pytest.raises(RuntimeError, match="ready"):
        cg.start_guard(100, 100, (1, "gone"))
    assert fake.killed and fake.waited


@SUPPORTED
@pytest.mark.parametrize("mode", ["normal", "child_sigkill"])
def test_no_guard_remains_after_child_end_and_stdio_is_devnull(tmp_path, mode):
    log = tmp_path / "guard.jsonl"
    code = "from deixis.documents import pdf; import time,os; pdf._watch_memory(10**12); print('ready',flush=True); "
    # Replace Python with a plain shell before SIGABRT so macOS does not open
    # Python.app's crash reporter for this intentional lifecycle test.
    code += {"normal": "time.sleep(.2)",
             "crash": "os.execv('/bin/sh', ['/bin/sh', '-c', 'kill -ABRT $$'])",
             "timeout": "time.sleep(30)", "child_sigkill": "time.sleep(30)"}[mode]
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                            env={"PYTHONPATH": BACKEND, "DEIXIS_CHILD_GUARD_LOG": str(log)})
    try:
        ready = wait_for(lambda: next((r for r in log_rows(log) if r["action"] == "ready"), None))
        assert ready["stdio_devnull"]
        assert proc.stdout.readline().strip() == "ready"
        if mode == "timeout":
            with pytest.raises(subprocess.TimeoutExpired): proc.wait(.1)
            proc.kill()
        if mode == "child_sigkill": proc.kill()
        if mode == "crash":
            assert proc.wait(10) == -signal.SIGABRT
        else:
            proc.wait(10)
        wait_for(lambda: cg.process_info(ready["guard_pid"]) is None)
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait()


@pytest.mark.parametrize("kind", ["pdf"])
def test_guard_failure_is_a_clear_error_in_every_parent_api(tmp_path, monkeypatch, kind):
    fail = subprocess.CompletedProcess([], cg.GUARD_EXIT_CODE, b"", b"")
    monkeypatch.setattr(pdf, "_run_watched", lambda *a: fail)
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: fail)
    if kind == "pdf": assert pdf.extract_pdf(tmp_path / "in.pdf").error == "extraction memory limit could not be watched"
    elif kind == "ocr": assert ocr.read_page(tmp_path / "in.pdf", 1, ["eng"]).error == "OCR memory limit could not be watched"
    else: assert jats.render_pdf(b"<article/>").error == "render memory limit could not be watched"


CHILD = ("import sys, time; sys.path[:0] = [%r]; from deixis.documents import pdf; pdf._watch_memory(10**12); "
         "print('armed', flush=True); time.sleep(30)" % BACKEND)


@pytest.mark.skipif(not hasattr(signal, "alarm"), reason="no SIGALRM on this platform")
def test_child_ends_by_alarm_inside_a_c_call():
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True,
                             env={"DEIXIS_CHILD_LIFETIME_SECONDS": "1", "PYTHONPATH": BACKEND})
    try:
        line: list[str] = []
        reader = threading.Thread(target=lambda: line.append(child.stdout.readline()), daemon=True)
        reader.start()
        reader.join(10)
        assert line, "the child did not print 'armed' within 10 s: it did not start or `_watch_memory` did not return"
        assert line[0].strip() == "armed", line
        armed = time.monotonic()
        code = child.wait(timeout=10)
    finally:
        child.kill()
        child.wait()
    ended = time.monotonic()
    assert code == -signal.SIGALRM
    assert ended - started >= 0.9 and ended - armed <= 6


def test_default_lifetime_is_above_every_parent_clock():
    assert pdf.CHILD_LIFETIME_SECONDS > max(pdf.TIMEOUT_SECONDS, ocr.TIMEOUT_SECONDS, jats.RENDER_TIMEOUT_SECONDS,
                                            arxiv_source.CHILD_TIMEOUT_SECONDS)
