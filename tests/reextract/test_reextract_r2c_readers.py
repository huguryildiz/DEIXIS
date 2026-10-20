"""R5 reader exclusion red-on-old; cancellation and busy-run contracts; invalid-hash guard (crop and arXiv routes)."""

import asyncio
import hashlib
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from deixis.documents import arxiv_source, equation_regions, pdf
from deixis.workflow import equations, file_restore, text_retry
from deixis.workflow.store import RunInProgress
from tests.reextract.reextract_r2a_helpers import api_library, body, counts, head, seed, store_library, url
from tests.reextract.reextract_r2b_helpers import tear
from tests.documents.test_arxiv_source_route import FakeFetch, arxiv_pdf
from tests.reextract.reextract_r2c_helpers import ROOT, child_lock


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


def crop(lib, monkeypatch):
    """A crop route that can read (the answer model, D113); `equation_regions.detect` is what reads the PDF."""
    service = equations.EquationService(lib.store, lib.settings.papers_dir)
    monkeypatch.setattr(service, "model_ready", lambda: (True, None))
    monkeypatch.setattr(service, "model_revision", lambda: "SYNTHETIC")
    return service


def detected(monkeypatch, found=()):
    calls = []
    def detect(*args, **kwargs): calls.append(args); return list(found)
    monkeypatch.setattr(equation_regions, "detect", detect)
    return calls


def failed_once(lib, service):
    asset = lib.store.asset(lib.aid)
    service._record_crop("model", asset, equations.model_target_version(asset["extraction_version"]), "model_failed",
                         {"reason": "network", "attempts": 1})


def source(lib):
    lib.conn.execute("UPDATE source_versions SET version_label = 'arXiv v2', doi = '10.48550/arXiv.2101.00001' WHERE id = ?", (lib.svid,))
    lib.conn.execute("UPDATE source_assets SET retrieved_from = 'https://arxiv.org/pdf/2101.00001v2' WHERE id = ?", (lib.aid,))
    return equations.EquationService(lib.store, lib.settings.papers_dir, arxiv_mode="auto",
                                    data_dir=lib.settings.data_dir, fetch_file=FakeFetch())


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_r5_crop_busy_does_no_read_or_write_red_on_old(tmp_path, monkeypatch, background, failed):
    with store_library(tmp_path, "succeeded") as lib:
        service = crop(lib, monkeypatch)
        if failed:
            failed_once(lib, service)
        before = counts(lib.store)
        calls = detected(monkeypatch)
        with child_lock(lib):
            state = asyncio.run(service.read_asset(lib.aid, background=background, retry=not background))
        assert calls == []
        assert state["outcome"] == "file_busy" and state["state"] == ("failed" if failed else "pending")
        if failed: assert state["attempts"] == 1
        assert counts(lib.store) == before
        assert asyncio.run(service.read_asset(lib.aid, retry=True))["state"] == "no_candidates" and len(calls) == 1


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
        service = crop(lib, monkeypatch)
        detected(monkeypatch)
        if not valid:
            lib.conn.execute("UPDATE source_assets SET sha256 = 'sha-paper' WHERE id = ?", (lib.aid,))
        calls, real = [], text_retry.file_lock
        def locking(*args): calls.append(args); return real(*args)
        monkeypatch.setattr(text_retry, "file_lock", locking)
        assert asyncio.run(service.read_asset(lib.aid))["state"] == "no_candidates"
        assert len(calls) == int(valid)
        if valid: assert calls[0] == (lib.settings.recovery_dir, lib.sha)
        else: assert not lib.settings.recovery_dir.exists()


@pytest.mark.parametrize("already_cancelled", [False, True])
def test_r5_normal_stop_logs_no_error_guard(tmp_path, monkeypatch, caplog, already_cancelled):
    with store_library(tmp_path, "succeeded") as lib:
        service = crop(lib, monkeypatch)
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
        service = crop(lib, monkeypatch)
        detected(monkeypatch)
        lib.app.state.worker.flow.deps.equations = service
        if failed:
            failed_once(lib, service)
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.update_run(run["id"], status="running")
        with child_lock(lib):
            asyncio.run(lib.app.state.worker.flow._read_equations(lib.store.run(run["id"]), [lib.svid]))
        step = lib.conn.execute("SELECT * FROM run_steps WHERE kind = 'read_equations'").fetchone()
        assert step["status"] == "succeeded" and '"outcome": "file_busy"' in step["output_json"]
        assert lib.store.run(run["id"])["status"] == "running"


def test_r5_background_busy_waits_one_retry_interval_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path, "succeeded") as lib:
        service = crop(lib, monkeypatch)
        calls = detected(monkeypatch)
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
        assert calls == []


@pytest.mark.parametrize("route", ["crop", "arxiv"])
def test_r5_reader_excludes_retry_and_waiting_restore_new_contract(tmp_path, monkeypatch, route):
    with api_library(tmp_path) as lib:
        entered, release = threading.Event(), threading.Event()
        if route == "crop":
            service = crop(lib, monkeypatch)
            def detect(*args, **kwargs):
                entered.set(); assert release.wait(15); return []
            monkeypatch.setattr(equation_regions, "detect", detect)
        else:
            service = source(lib)
            async def ensure(key):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(0.005)
                return {"status": "not_settled"}
            monkeypatch.setattr(service.sources, "ensure", ensure)
        monkeypatch.setattr(file_restore, "WRITER_LOCK_WAIT_SECONDS", 0.05)
        async def scenario():
            task = asyncio.create_task(service.read_asset(lib.aid))
            await thread_entered(entered)
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


def test_r5_crop_cancellation_drains_the_detect_thread_new_contract(tmp_path, monkeypatch):
    with store_library(tmp_path, "succeeded") as lib:
        entered, release = threading.Event(), threading.Event()
        service = crop(lib, monkeypatch)
        def detect(*args, **kwargs): entered.set(); assert release.wait(15); return []
        monkeypatch.setattr(equation_regions, "detect", detect)
        async def scenario():
            task = asyncio.create_task(service.read_asset(lib.aid))
            try:
                await thread_entered(entered)
                task.cancel(); await asyncio.sleep(0.01)
                assert probe(lib) and not task.done()
                task.cancel(); await asyncio.sleep(0.01)
                assert probe(lib) and not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError): await task
                assert not probe(lib)
            finally:
                release.set()
        asyncio.run(scenario())
        assert head(lib.store, lib.aid)["id"] == lib.eid
        assert lib.conn.execute("SELECT count(*) FROM asset_extractions").fetchone()[0] == 1


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
