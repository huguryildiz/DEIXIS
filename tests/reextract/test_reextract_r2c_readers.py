"""R5 reader exclusion red-on-old; cancellation and busy-run contracts; invalid-hash guard."""

import asyncio
import hashlib
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from deixis.documents import arxiv_source, math_reader, pdf
from deixis.workflow import equations, file_restore, text_retry
from deixis.workflow.store import RunInProgress
from tests.reextract_r2a_helpers import api_library, body, counts, head, seed, store_library, url
from tests.reextract_r2b_helpers import tear
from tests.documents.test_equations import FakeReader
from tests.documents.test_arxiv_source_route import NoMarker, FakeFetch, arxiv_pdf
from tests.reextract_r2c_helpers import ROOT, child_lock


def probe(lib):
    result = subprocess.run([sys.executable, "-c",
        "from pathlib import Path; import sys; from deixis.workflow.text_retry import lock_held; print(lock_held(Path(sys.argv[1]), sys.argv[2]))",
        str(lib.settings.recovery_dir), lib.sha], env=dict(os.environ, PYTHONPATH=str(ROOT / "backend")),
        capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.strip() == "True"


async def thread_entered(event):
    async with asyncio.timeout(15):
        while not event.is_set():
            await asyncio.sleep(0.005)


def marker(lib, monkeypatch, reader=None):
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [0])
    monkeypatch.setattr(math_reader, "table_pages", lambda path: [])
    return equations.EquationService(lib.store, reader or FakeReader(), lib.settings.papers_dir)


def source(lib):
    lib.conn.execute("UPDATE source_versions SET version_label = 'arXiv v2', doi = '10.48550/arXiv.2101.00001' WHERE id = ?", (lib.svid,))
    lib.conn.execute("UPDATE source_assets SET retrieved_from = 'https://arxiv.org/pdf/2101.00001v2' WHERE id = ?", (lib.aid,))
    return equations.EquationService(lib.store, NoMarker(), lib.settings.papers_dir, arxiv_mode="auto",
                                    data_dir=lib.settings.data_dir, fetch_file=FakeFetch())


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_r5_marker_busy_does_no_read_or_write_red_on_old(tmp_path, monkeypatch, background, failed):
    with store_library(tmp_path, "succeeded") as lib:
        service = marker(lib, monkeypatch)
        if failed:
            service._record_without_passages(lib.store.asset(lib.aid), equations.target_version(), "SYNTHETIC failure", 1)
        before = counts(lib.store)
        calls = []
        real = pdf.extract_pdf
        def parser(*args): calls.append(args); return real(*args)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        with child_lock(lib):
            state = asyncio.run(service.read_asset(lib.aid, background=background, retry=not background))
        assert calls == [] and service.reader.calls == []
        assert state["outcome"] == "file_busy" and state["state"] == ("failed" if failed else "pending")
        if failed: assert state["attempts"] == 1
        assert counts(lib.store) == before
        assert asyncio.run(service.read_asset(lib.aid, retry=True))["state"] == "read"


def test_r5_arxiv_busy_does_not_stamp_or_read_red_on_old(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        service = source(lib)
        calls = []
        real = arxiv_source.read_source
        async def read(*args): calls.append(args); return await real(*args)
        monkeypatch.setattr(arxiv_source, "read_source", read)
        with child_lock(lib):
            state = asyncio.run(service.read_asset(lib.aid))
        assert lib.conn.execute("SELECT count(*) FROM asset_arxiv_versions").fetchone()[0] == 0 and calls == []
        assert state["outcome"] == "file_busy"
        asyncio.run(service.read_asset(lib.aid))
        assert lib.conn.execute("SELECT count(*) FROM asset_arxiv_versions").fetchone()[0] == 1
        asyncio.run(service.read_asset(lib.aid))
        assert lib.conn.execute("SELECT count(*) FROM asset_arxiv_versions").fetchone()[0] == 1


@pytest.mark.parametrize("valid", [False, True])
def test_r5_reader_hash_branches_guard(tmp_path, monkeypatch, valid):
    with store_library(tmp_path, "succeeded") as lib:
        service = marker(lib, monkeypatch)
        if not valid:
            lib.conn.execute("UPDATE source_assets SET sha256 = 'sha-paper' WHERE id = ?", (lib.aid,))
        calls, real = [], text_retry.file_lock
        def locking(*args): calls.append(args); return real(*args)
        monkeypatch.setattr(text_retry, "file_lock", locking)
        assert asyncio.run(service.read_asset(lib.aid))["state"] == "read"
        assert len(calls) == int(valid)
        if valid: assert calls[0] == (lib.settings.recovery_dir, lib.sha)
        else: assert not lib.settings.recovery_dir.exists()


@pytest.mark.parametrize("failure", ["reply_error", "run_active"])
def test_r5_completed_marker_request_reuses_child_guard(tmp_path, monkeypatch, failure):
    """Guard of the old shared-process behavior; paired with R5's cancellation contract."""
    with store_library(tmp_path, "succeeded") as lib:
        reader = math_reader.MathReader(math_reader.runtime_paths(lib.settings.data_dir))
        monkeypatch.setattr(reader, "available", lambda: True)
        monkeypatch.setattr(math_reader, "inline_math_marks", lambda *args: ({}, []))
        processes, closes = [], []
        async def start():
            proc = await asyncio.create_subprocess_exec(sys.executable, "-c", """
import json, sys
for index, line in enumerate(sys.stdin):
    request = json.loads(line)
    reply = ({'error': 'SYNTHETIC per-PDF error'} if index == 0 and sys.argv[1] == 'reply_error'
             else {'pages': {str(p): 'SYNTHETIC Marker reply' for p in request['pages']}})
    print(json.dumps(reply), flush=True)
""", failure, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            processes.append(proc)
            reader.process = proc
        monkeypatch.setattr(reader, "_start", start)
        close = reader.close
        async def closing():
            closes.append(reader.process)
            await close()
        monkeypatch.setattr(reader, "close", closing)
        service = marker(lib, monkeypatch, reader)
        reextract = lib.store.reextract_asset
        def refuse(*args, **kwargs):
            raise RunInProgress("SYNTHETIC publication refusal")
        if failure == "run_active":
            monkeypatch.setattr(lib.store, "reextract_asset", refuse)
        async def scenario():
            try:
                if failure == "reply_error":
                    state = await service.read_asset(lib.aid)
                    assert state["state"] == "failed" and "SYNTHETIC per-PDF error" in state["reason"]
                else:
                    with pytest.raises(RunInProgress):
                        await service.read_asset(lib.aid)
                    monkeypatch.setattr(lib.store, "reextract_asset", reextract)
                assert len(processes) == 1 and reader.process is processes[0]
                assert processes[0].returncode is None and closes == [] and not probe(lib)
                assert (await service.read_asset(lib.aid, retry=True))["state"] == "read"
                assert len(processes) == 1 and reader.process is processes[0]
                assert processes[0].returncode is None and closes == []
            finally:
                await service.stop()
            assert processes[0].returncode is not None
            with pytest.raises(ChildProcessError): os.waitpid(processes[0].pid, os.WNOHANG)
        asyncio.run(scenario())


@pytest.mark.parametrize("already_cancelled", [False, True])
def test_r5_normal_stop_logs_no_error_guard(tmp_path, monkeypatch, caplog, already_cancelled):
    with store_library(tmp_path, "succeeded") as lib:
        service = marker(lib, monkeypatch)
        async def scenario():
            service._task = task = asyncio.create_task(asyncio.sleep(30))
            await asyncio.sleep(0)
            if already_cancelled:
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
            await service.stop()
            assert task.cancelled()
        with caplog.at_level(logging.ERROR, logger=equations.log.name):
            asyncio.run(scenario())
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.parametrize("failed", [False, True])
def test_r5_busy_in_run_step_succeeds_without_pause_new_contract(tmp_path, monkeypatch, failed):
    with api_library(tmp_path, "succeeded") as lib:
        service = marker(lib, monkeypatch)
        lib.app.state.worker.flow.deps.equations = service
        if failed:
            service._record_without_passages(lib.store.asset(lib.aid), equations.target_version(), "SYNTHETIC failure", 1)
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.update_run(run["id"], status="running")
        with child_lock(lib):
            asyncio.run(lib.app.state.worker.flow._read_equations(lib.store.run(run["id"]), [lib.svid]))
        step = lib.conn.execute("SELECT * FROM run_steps WHERE kind = 'read_equations'").fetchone()
        assert step["status"] == "succeeded" and '"outcome": "file_busy"' in step["output_json"]
        assert lib.store.run(run["id"])["status"] == "running"


def test_r5_background_busy_waits_one_retry_interval_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path, "succeeded") as lib:
        service = marker(lib, monkeypatch)
        monkeypatch.setattr(equations, "RETRY_SECONDS", 0.06)
        times, real = [], service.read_asset
        async def read(*args, **kwargs):
            times.append(asyncio.get_running_loop().time())
            return await real(*args, **kwargs)
        monkeypatch.setattr(service, "read_asset", read)
        async def scenario():
            with child_lock(lib):
                task = asyncio.create_task(service.run_forever())
                await asyncio.sleep(0.2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
        asyncio.run(scenario())
        assert 2 <= len(times) <= 4
        assert all(b - a >= 0.055 for a, b in zip(times, times[1:]))
        assert service.reader.calls == []


@pytest.mark.parametrize("route", ["marker", "arxiv"])
def test_r5_reader_excludes_retry_and_waiting_restore_new_contract(tmp_path, monkeypatch, route):
    with api_library(tmp_path) as lib:
        entered, release = asyncio.Event(), asyncio.Event()
        if route == "marker":
            class Parked(FakeReader):
                async def read(self, *args):
                    entered.set(); await release.wait(); return await super().read(*args)
            service = marker(lib, monkeypatch, Parked())
        else:
            service = source(lib)
            async def ensure(key):
                entered.set(); await release.wait(); return {"status": "not_settled"}
            monkeypatch.setattr(service.sources, "ensure", ensure)
        monkeypatch.setattr(file_restore, "WRITER_LOCK_WAIT_SECONDS", 0.05)
        async def scenario():
            task = asyncio.create_task(service.read_asset(lib.aid))
            await asyncio.wait_for(entered.wait(), 15)
            try:
                response = lib.client.post(url(lib), json=body(lib, "busy_retry"))
                assert response.status_code == 409 and response.json()["code"] == "file_busy"
                tear(lib)  # Synthetic outside change makes the restore take its writer lock.
                response = lib.client.post(f"/api/researches/{lib.rid}/uploads",
                    files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")})
                assert response.status_code == 409 and response.json()["code"] == "file_busy"
                assert counts(lib.store)["asset_recovery_operations"] == 0
            finally:
                lib.path.write_bytes(lib.data)
                release.set()
            await task
        asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["parser", "inline", "reader"])
def test_r5_marker_cancellation_drains_thread_and_reaps_child_new_contract(tmp_path, monkeypatch, phase):
    with store_library(tmp_path, "succeeded") as lib:
        entered, release = threading.Event(), threading.Event()
        reader = math_reader.MathReader(math_reader.runtime_paths(lib.settings.data_dir))
        monkeypatch.setattr(reader, "available", lambda: True)
        service = marker(lib, monkeypatch, reader)
        processes = []
        real_wait = asyncio.wait_for
        async def shorter(awaitable, timeout):
            return await real_wait(awaitable, 0.03 if timeout == 10 else timeout)
        monkeypatch.setattr(asyncio, "wait_for", shorter)
        if phase == "parser":
            real = pdf.extract_pdf
            def parse(*args): entered.set(); assert release.wait(15); return real(*args)
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        elif phase == "inline":
            def marks(*args): entered.set(); assert release.wait(15); return {}, []
            monkeypatch.setattr(math_reader, "inline_math_marks", marks)
        else:
            async def read(*args):
                entered.set()
                await asyncio.Event().wait()
            monkeypatch.setattr(reader, "read", read)
        async def scenario():
            proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            processes.append(proc); reader.process = proc
            task = asyncio.create_task(service.read_asset(lib.aid))
            try:
                await thread_entered(entered)
                task.cancel(); await asyncio.sleep(0.01)
                assert probe(lib) and not task.done()
                task.cancel()
                if phase != "reader":
                    await asyncio.sleep(0.01)
                    assert probe(lib) and proc.returncode is None
                release.set()
                with pytest.raises(asyncio.CancelledError): await task
                assert not probe(lib)
                if phase == "parser":
                    # No Marker request began; cancellation preserves its idle shared process.
                    assert reader.process is proc and proc.returncode is None
                    await service.stop()
                assert proc.returncode is not None
                with pytest.raises(ChildProcessError): os.waitpid(proc.pid, os.WNOHANG)
            finally:
                release.set()
                if proc.returncode is None: proc.kill()
                await proc.wait()
        asyncio.run(scenario())
        assert head(lib.store, lib.aid)["id"] == lib.eid
        assert lib.conn.execute("SELECT count(*) FROM asset_extractions").fetchone()[0] == 1


def test_r5_preemption_shutdown_and_repeated_cancel_share_one_reaped_close_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path, "succeeded") as lib:
        other = seed(lib.store, lib.settings, "succeeded", data=lib.data + b"\nSYNTHETIC second hash")
        reader = math_reader.MathReader(math_reader.runtime_paths(lib.settings.data_dir))
        monkeypatch.setattr(reader, "available", lambda: True)
        service = marker(lib, monkeypatch, reader)
        entered, gate, killed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        real_wait_for = asyncio.wait_for
        async def short(awaitable, timeout): return await real_wait_for(awaitable, 0.03 if timeout == 10 else timeout)
        monkeypatch.setattr(asyncio, "wait_for", short)
        async def scenario():
            proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            reader.process = proc
            wait, kill = proc.wait, proc.kill
            async def reaped(): await gate.wait(); return await wait()
            def killing(): killed.set(); kill()
            proc.wait, proc.kill = reaped, killing
            async def read(*args):
                entered.set()
                await wait()
                raise RuntimeError("SYNTHETIC preempted reader")
            monkeypatch.setattr(reader, "read", read)
            service._task = background = asyncio.create_task(service.read_asset(lib.aid, background=True))
            foreground = stopping = None
            try:
                await asyncio.wait_for(entered.wait(), 15)
                foreground = asyncio.create_task(service.read_asset(other.aid))
                await asyncio.wait_for(killed.wait(), 15)
                shared = reader._closing[1]
                stopping = asyncio.create_task(service.stop())
                background.cancel(); await asyncio.sleep(0.01); background.cancel()
                assert probe(lib) and not background.done() and not shared.done()
                assert reader._closing[1] is shared
                gate.set()
                await stopping
                await foreground
                assert background.cancelled() and shared.done() and proc.returncode is not None and not probe(lib)
                with pytest.raises(ChildProcessError): os.waitpid(proc.pid, os.WNOHANG)
            finally:
                gate.set()
                if proc.returncode is None: proc.kill()
                await wait()
                for task in (background, foreground, stopping):
                    if task is not None and not task.done(): task.cancel()
                await asyncio.gather(*(t for t in (background, foreground, stopping) if t is not None), return_exceptions=True)
        asyncio.run(scenario())
        assert head(lib.store, lib.aid)["id"] == lib.eid
        assert lib.conn.execute("SELECT count(*) FROM asset_extractions WHERE asset_id = ?", (lib.aid,)).fetchone()[0] == 1


@pytest.mark.parametrize("cancel_at", ["running", "kill", "timeout_cleanup"])
def test_r5_arxiv_cancellation_never_cancels_child_owner_new_contract(tmp_path, monkeypatch, cancel_at):
    with store_library(tmp_path) as lib:
        service = source(lib)
        started, killed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        processes = []
        create = asyncio.create_subprocess_exec
        async def launch(*args, **kwargs):
            proc = await create(*args, **kwargs)
            processes.append(proc)
            wait, kill = proc.wait, proc.kill
            async def reaped():
                await release.wait()
                return await wait()
            def killing(): killed.set(); kill()
            proc.wait, proc.kill = reaped, killing
            started.set()
            return proc
        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        async def read_source(*args):
            result = await arxiv_source.run_child([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.15)
            return {"content": "unreadable", "error": result.failure}
        monkeypatch.setattr(arxiv_source, "read_source", read_source)
        async def scenario():
            task = asyncio.create_task(service.read_asset(lib.aid))
            try:
                await asyncio.wait_for(started.wait(), 15)
                if cancel_at == "timeout_cleanup": await asyncio.wait_for(killed.wait(), 15)
                task.cancel(); await asyncio.sleep(0.01)
                assert probe(lib) and not task.done()
                if cancel_at in ("kill", "timeout_cleanup"):
                    await asyncio.wait_for(killed.wait(), 15)
                    task.cancel(); await asyncio.sleep(0.01)
                    assert probe(lib) and not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError): await task
                assert all(proc.returncode is not None for proc in processes) and not probe(lib)
                for proc in processes:
                    with pytest.raises(ChildProcessError): os.waitpid(proc.pid, os.WNOHANG)
            finally:
                release.set()
                for proc in processes:
                    if proc.returncode is None: proc.kill()
                    await proc.wait()
        asyncio.run(scenario())
        assert lib.conn.execute("SELECT count(*) FROM asset_extractions").fetchone()[0] == 1
        assert head(lib.store, lib.aid)["id"] == lib.eid
