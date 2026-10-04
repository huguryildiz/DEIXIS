"""Guard decisions and real startup/lifecycle checks, without MuPDF in the guard."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from deixis.documents import child_guard as cg, pdf, ocr, jats, arxiv_source

BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
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
                                           (None, 200, "kill"), (None, 50, "wait"),
                                           (cg.ProcessInfo("reused", 1), 200, "kill")])
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


@pytest.mark.parametrize("child,now", [(None, 0), (cg.ProcessInfo("reused", 1), 0), (cg.ProcessInfo("child", 1), 10)])
def test_guard_ends_with_child_or_at_absolute_deadline(child, now):
    assert cg.Guard(10, "child", 20, "parent", 100, 10).turn(now, lambda _: child, lambda _: 200)[0] == "end"


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
def test_early_guard_loss_ends_idle_child_with_distinct_code(tmp_path):
    log = tmp_path / "guard.jsonl"
    code = "from deixis.documents import pdf; import time; pdf._watch_memory(10**12); print('ready',flush=True); time.sleep(30)"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                            env={"PYTHONPATH": BACKEND, "DEIXIS_CHILD_GUARD_LOG": str(log)})
    try:
        ready = wait_for(lambda: next((r for r in log_rows(log) if r["action"] == "ready"), None))
        assert proc.stdout.readline().strip() == "ready"
        os.kill(ready["guard_pid"], signal.SIGKILL)
        assert proc.wait(timeout=10) == cg.GUARD_EXIT_CODE
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


@SUPPORTED
@pytest.mark.parametrize("mode", ["normal", "crash", "timeout", "child_sigkill"])
def test_no_guard_remains_after_child_end_and_stdio_is_devnull(tmp_path, mode):
    log = tmp_path / "guard.jsonl"
    code = "from deixis.documents import pdf; import time,os; pdf._watch_memory(10**12); print('ready',flush=True); "
    code += {"normal": "time.sleep(.2)", "crash": "os.abort()", "timeout": "time.sleep(30)", "child_sigkill": "time.sleep(30)"}[mode]
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
        proc.wait(10)
        wait_for(lambda: cg.process_info(ready["guard_pid"]) is None)
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait()


def test_parent_launchers_pass_their_identity(monkeypatch):
    parent = cg.process_info(os.getpid())
    assert cg.parent_env({"PYTHONPATH": BACKEND})["DEIXIS_PARENT_START"] == parent.start
    assert cg.parent_env({})["DEIXIS_PARENT_PID"] == str(os.getpid())
    monkeypatch.delenv("DEIXIS_PARENT_PID", raising=False)
    monkeypatch.delenv("DEIXIS_PARENT_START", raising=False)
    assert cg.original_parent(1) == (1, "gone")


@SUPPORTED
def test_pdf_launcher_passes_parent_start_time_before_child_work():
    code = "import os,json; print(json.dumps({k:os.environ.get(k) for k in ('DEIXIS_PARENT_PID','DEIXIS_PARENT_START')}))"
    done = pdf._run_watched([sys.executable, "-c", code], {}, 10, 10**12)
    env = json.loads(done.stdout)
    assert env == {"DEIXIS_PARENT_PID": str(os.getpid()), "DEIXIS_PARENT_START": cg.process_info(os.getpid()).start}


@pytest.mark.parametrize("kind", ["pdf", "ocr", "jats"])
def test_guard_failure_is_a_clear_error_in_every_parent_api(tmp_path, monkeypatch, kind):
    fail = subprocess.CompletedProcess([], cg.GUARD_EXIT_CODE, b"", b"")
    monkeypatch.setattr(pdf, "_run_watched", lambda *a: fail)
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: fail)
    if kind == "pdf": assert pdf.extract_pdf(tmp_path / "in.pdf").error == "extraction memory limit could not be watched"
    elif kind == "ocr": assert ocr.read_page(tmp_path / "in.pdf", 1, ["eng"]).error == "OCR memory limit could not be watched"
    else: assert jats.render_pdf(b"<article/>").error == "render memory limit could not be watched"


def test_arxiv_guard_exit_maps_to_watch_loss():
    import asyncio
    result = asyncio.run(arxiv_source.run_child([sys.executable, "-c", "import sys; sys.exit(6)"]))
    assert result.failure == "memory_watch_lost"
