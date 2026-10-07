"""Store, file and cancellation contracts, paired with T1/T3 and existing R1 rollback guards."""

import asyncio
import errno
import logging
import os
import threading
from pathlib import Path

import pytest

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow.store import Store, RecoveryConflict, RunInProgress
try:
    from deixis.workflow import text_retry
    from deixis.workflow.store import TEXT_RETRY_REFUSALS
except ImportError:
    text_retry = None
    TEXT_RETRY_REFUSALS = ("asset_removed", "no_holding_research", "membership_changed", "asset_replaced",
                          "baseline_changed", "run_active", "input_not_verified", "file_missing", "file_mismatch")
from tests.reextract.reextract_r2a_helpers import store_library, seed, head, protected, counts, sharing, child_lock


def reserve(lib, key="store_request", rid=True):
    return lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key=key,
                                       request_fingerprint=key, research_id=lib.rid if rid else None)


async def execute(lib, key="driver_request"):
    return await text_retry.execute_text_retry(lib.store, lib.settings, asset_id=lib.aid,
        expected_extraction_id=lib.eid, idempotency_key=key, research_id=lib.rid, source_version_id=lib.svid)


def record(lib, op):
    return lib.store.record_text_retry_input(op["id"], storage_path=lib.path.name,
        expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
        observed_byte_size=len(lib.data), integrity="verified")


def test_request_membership_removed_final_transaction_red_on_old(tmp_path):
    # Uses only R1 methods so the behavioral assertion can run unchanged on 2148c32.
    with store_library(tmp_path) as lib:
        sharing(lib)
        op = reserve(lib)
        obs = lib.store.add_file_observation(kind="extraction_input", operation_id=op["id"], storage_path=lib.path.name,
            expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
            observed_byte_size=len(lib.data), integrity="verified")
        lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        before = protected(lib.store)
        result = lib.store.complete_text_retry(op["id"], pdf.extract_pdf(lib.path), pdf.chunk_page, input_observation_id=obs)
        assert result["outcome"] == "refused" and result["reason"] == "membership_changed"
        assert protected(lib.store) == before


def test_same_process_independent_open_probe_does_not_weaken_lock(tmp_path):
    import fcntl
    folder, sha = tmp_path / "recovery", "a" * 64
    assert not text_retry.lock_held(folder, sha) and not folder.exists()
    with text_retry.file_lock(folder, sha):
        assert text_retry.lock_held(folder, sha)
        with (folder / "locks" / (sha + ".lock")).open("rb") as third:
            with pytest.raises(OSError) as exc:
                fcntl.flock(third.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert exc.value.errno in (errno.EAGAIN, errno.EWOULDBLOCK)
        with pytest.raises(text_retry.FileBusy):
            with text_retry.file_lock(folder, sha): pass
    assert not text_retry.lock_held(folder, sha)
    assert (folder / "locks" / (sha + ".lock")).exists()


def test_child_process_probe_and_unrelated_hash_lock(tmp_path):
    with store_library(tmp_path) as lib:
        with child_lock(lib):
            assert text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
            with text_retry.file_lock(lib.settings.recovery_dir, "b" * 64): pass
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def test_probe_propagates_other_oserror(tmp_path, monkeypatch):
    import fcntl
    sha = "a" * 64
    with text_retry.file_lock(tmp_path, sha): pass
    def fail(*args): raise OSError(errno.EIO, "SYNTHETIC read failure")
    monkeypatch.setattr(fcntl, "flock", fail)
    with pytest.raises(OSError) as exc: text_retry.lock_held(tmp_path, sha)
    assert exc.value.errno == errno.EIO


@pytest.mark.parametrize("sha", ["../bad", "A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n"])
def test_invalid_lock_hash_cannot_build_a_path(tmp_path, sha):
    with pytest.raises(ValueError):
        with text_retry.file_lock(tmp_path / "absent", sha): pass
    with pytest.raises(ValueError): text_retry.lock_held(tmp_path / "absent", sha)
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested"])
def test_reservation_refuses_active_run_in_another_holding_research(tmp_path, status):
    with store_library(tmp_path) as lib:
        other = sharing(lib)
        run = lib.store.create_run(other, "answer", {}, None)
        lib.store.update_run(run["id"], status=status)
        before = counts(lib.store)
        with pytest.raises(RunInProgress): reserve(lib)
        assert counts(lib.store) == before


@pytest.mark.parametrize("unrelated_first", [False, True])
def test_live_child_retry_defers_holding_run_and_skips_to_unrelated(tmp_path, unrelated_first):
    with store_library(tmp_path) as lib:
        unrelated = lib.store.create_research("SYNTHETIC unrelated?", "attached", "quick", [], "fake", "fake", None)
        op = reserve(lib)
        if unrelated_first: free = lib.store.create_run(unrelated, "answer", {}, None)
        held = lib.store.create_run(lib.rid, "answer", {}, None)
        if not unrelated_first: free = lib.store.create_run(unrelated, "answer", {}, None)
        with child_lock(lib):
            assert lib.store.next_queued_run()["id"] == free["id"]
            lib.store.update_run(free["id"], status="completed")
            assert lib.store.next_queued_run() is None
        assert lib.store.next_queued_run()["id"] == held["id"]
        assert lib.store.text_retry_view(op["id"])["lifecycle"] == "running"
        lib.store.update_run(held["id"], status="completed")
        with pytest.raises(RecoveryConflict, match="operation_running"): reserve(lib, "new_request")


@pytest.mark.parametrize("failure", ["directory", "permission"])
def test_probe_error_defers_only_holding_research_and_logs_once(tmp_path, monkeypatch, caplog, failure):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        held = lib.store.create_run(lib.rid, "answer", {}, None)
        unrelated = lib.store.create_research("SYNTHETIC unrelated?", "attached", "quick", [], "fake", "fake", None)
        free = lib.store.create_run(unrelated, "answer", {}, None)
        path = lib.settings.recovery_dir / "locks" / (lib.sha + ".lock")
        path.parent.mkdir(parents=True)
        if failure == "directory":
            path.mkdir()
            error_number = errno.EISDIR
        else:
            path.touch()
            error_number = errno.EACCES
        with monkeypatch.context() as patch:
            if failure == "permission":
                original = Path.open
                def denied(entry, *args, **kwargs):
                    if entry == path: raise OSError(errno.EACCES, "SYNTHETIC unreadable lock")
                    return original(entry, *args, **kwargs)
                patch.setattr(Path, "open", denied)
            with pytest.raises(OSError) as exc:
                text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
            assert exc.value.errno == error_number
            with caplog.at_level(logging.WARNING, logger="deixis.workflow.store"):
                assert lib.store.next_queued_run()["id"] == free["id"]
                assert lib.store.next_queued_run()["id"] == free["id"]
                lib.store.update_run(free["id"], status="completed")
                assert lib.store.next_queued_run() is None
            records = [r for r in caplog.records if "Could not probe text retry lock" in r.message]
            assert len(records) == 1
            assert op["id"] in records[0].message and f"errno={error_number}" in records[0].message
            assert lib.store.text_retry_view(op["id"])["lifecycle"] == "running"
        if failure == "directory": path.rmdir()
        assert lib.store.next_queued_run()["id"] == held["id"]


def test_bare_store_defers_running_reservation_and_paused_resume_stays_queued(tmp_path):
    with store_library(tmp_path) as lib:
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.update_run(run["id"], status="paused")
        op = reserve(lib)
        lib.store.resume_run(run["id"])
        lib.store.recovery_dir = None
        assert lib.store.next_queued_run() is None
        lib.store.refuse_text_retry(op["id"], "file_missing")
        assert lib.store.next_queued_run()["id"] == run["id"]


@pytest.mark.parametrize("path", ["create", "resume", "search_retry", "suggestions", "approval", "code_query", "follow_on"])
def test_all_run_creators_and_requeues_succeed_but_wait(path, tmp_path):
    with store_library(tmp_path) as lib:
        store = lib.store
        run = None
        if path not in ("create", "follow_on"):
            run = store.create_run(lib.rid, "discovery" if path == "search_retry" else "answer",
                                   {"inspection": {"policy": "small_batch_fused_v1"}}, None)
            store.update_run(run["id"], status="paused")
            if path in ("suggestions", "approval"):
                store.step(run["id"], "protocol_approval", "protocol_approval", {"suggestion_requests": 0})
            elif path == "code_query": store.step(run["id"], "search_query", "search_query", {"synthetic": True})
            elif path == "search_retry":
                step = store.step(run["id"], "search", "provider_search:openalex")
                store.finish_step(step["id"], "failed")
        op = reserve(lib)
        with text_retry.file_lock(lib.settings.recovery_dir, lib.sha):
            if path in ("create", "follow_on"): result = store.create_run(lib.rid, "answer", {}, None)
            elif path == "resume": result = store.resume_run(run["id"])
            elif path == "search_retry": result = store.queue_failed_search_retry(run["id"])
            elif path == "suggestions": result = store.request_term_suggestions(run["id"])
            elif path == "approval": result = store.submit_approval(run["id"], {})
            else: result = store.choose_code_query(run["id"])
            assert result["status"] == "queued" and store.next_queued_run() is None
        assert store.next_queued_run()["id"] == result["id"]
        assert store.text_retry_view(op["id"])["lifecycle"] == "running"


@pytest.mark.parametrize("reason", TEXT_RETRY_REFUSALS)
def test_refusal_closed_vocabulary_replay_and_no_evidence(tmp_path, reason):
    with store_library(tmp_path) as lib:
        op = reserve(lib); obs = record(lib, op)
        before = protected(lib.store)
        result = lib.store.refuse_text_retry(op["id"], reason)
        assert result["lifecycle"] == "completed" and result["outcome"] == "refused" and result["reason"] == reason
        assert result["input_observation_id"] == obs and result["input_integrity"] == "verified"
        assert protected(lib.store) == before
        snapshot = counts(lib.store)
        assert lib.store.refuse_text_retry(op["id"], reason) == result
        assert counts(lib.store) == snapshot


def test_invalid_endings_and_input_record_are_atomic(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        op = reserve(lib)
        with pytest.raises(ValueError): lib.store.refuse_text_retry(op["id"], "invented")
        with pytest.raises(ValueError): lib.store.interrupt_text_retry(op["id"], "invented")
        result = lib.store.interrupt_text_retry(op["id"], "unexpected_error")
        assert lib.store.interrupt_text_retry(op["id"], "cancelled") == result
        with pytest.raises(RecoveryConflict): lib.store.refuse_text_retry(op["id"], "file_missing")
        with pytest.raises(RecoveryConflict): record(lib, op)
        assert counts(lib.store)["asset_file_observations"] == 0


@pytest.mark.parametrize("phase", ["copy_blocked", "copy_success", "copy_error", "parse"])
def test_cancelled_threads_drain_under_lock_before_cleanup_and_keep_cancellation(tmp_path, monkeypatch, phase):
    with store_library(tmp_path) as lib:
        entered, release = threading.Event(), threading.Event()
        observe, parse = text_retry.observe_copy, pdf.extract_pdf
        def blocked_copy(*args):
            Path(args[-1]).write_bytes(b"SYNTHETIC IN PROGRESS")
            entered.set(); assert release.wait(15)
            if phase == "copy_error": raise RuntimeError("SYNTHETIC drained copy failure")
            return observe(*args)
        def blocked_parse(path):
            entered.set(); assert release.wait(15); return parse(path)
        monkeypatch.setattr(pdf if phase == "parse" else text_retry,
                            "extract_pdf" if phase == "parse" else "observe_copy",
                            blocked_parse if phase == "parse" else blocked_copy)
        async def scenario():
            task = asyncio.create_task(execute(lib))
            for _ in range(1500):
                if entered.is_set(): break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done() and text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
            assert len(list((lib.settings.recovery_dir / "tmp").iterdir())) == 1
            task.cancel()  # a second cancellation must also drain
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
        try: asyncio.run(scenario())
        finally: release.set()
        op = lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone()
        assert op["lifecycle"] == "interrupted" and op["reason"] == "cancelled" and op["outcome"] is None
        assert counts(lib.store)["asset_extractions"] == 1
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert list((lib.settings.recovery_dir / "tmp").iterdir()) == []


@pytest.mark.parametrize("unlink_failure,unlock_failure,parser_failure", [(True, False, False), (False, True, False),
    (True, True, False), (True, False, True), (False, True, True), (True, True, True)])
@pytest.mark.parametrize("cleanup_error", [OSError, RuntimeError])
def test_cleanup_errors_preserve_result_or_original_error_then_sweep(tmp_path, monkeypatch, unlink_failure, unlock_failure, parser_failure, cleanup_error):
    with store_library(tmp_path) as lib:
        unlink, unlock = Path.unlink, text_retry._unlock
        def unlinking(path, *args, **kwargs):
            if unlink_failure and path.parent == lib.settings.recovery_dir / "tmp": raise cleanup_error("SYNTHETIC unlink")
            return unlink(path, *args, **kwargs)
        def unlocking(handle):
            if unlock_failure: raise cleanup_error("SYNTHETIC unlock")
            return unlock(handle)
        monkeypatch.setattr(Path, "unlink", unlinking)
        monkeypatch.setattr(text_retry, "_unlock", unlocking)
        original = RuntimeError("SYNTHETIC original parser exception")
        if parser_failure:
            def fail(path): raise original
            monkeypatch.setattr(pdf, "extract_pdf", fail)
            with pytest.raises(RuntimeError) as exc: asyncio.run(execute(lib))
            assert exc.value is original
        else: assert asyncio.run(execute(lib))["outcome"] == "promoted"
        monkeypatch.setattr(Path, "unlink", unlink)
        monkeypatch.setattr(text_retry, "_unlock", unlock)
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        if unlink_failure: assert list((lib.settings.recovery_dir / "tmp").iterdir())
        text_retry._sweep(lib.settings.recovery_dir)
        assert list((lib.settings.recovery_dir / "tmp").iterdir()) == []


def test_serializer_failure_after_commit_keeps_result_and_replay(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        real = lib.store.complete_text_retry
        serialize = lib.store.text_retry_view
        def complete(*args, **kwargs):
            result = real(*args, **kwargs)
            def fail(oid): raise RuntimeError("SYNTHETIC post-commit serializer")
            monkeypatch.setattr(lib.store, "text_retry_view", fail)
            return result
        monkeypatch.setattr(lib.store, "complete_text_retry", complete)
        with pytest.raises(RuntimeError, match="post-commit"): asyncio.run(execute(lib))
        monkeypatch.setattr(lib.store, "text_retry_view", serialize)
        result = asyncio.run(execute(lib))
        assert result["outcome"] == "promoted" and result["replayed"]
        assert lib.store.pending_text_retry_interruptions == {}


@pytest.mark.parametrize("flush", ["execute", "capability", "queue"])
def test_pending_interruption_flush_keeps_original_error_and_only_ends_running(tmp_path, monkeypatch, flush):
    from tests.reextract.reextract_r2a_helpers import api_library, body, url
    with api_library(tmp_path) as lib:
        interrupt, calls = lib.store.interrupt_text_retry, []
        def ending(*args):
            calls.append(args)
            if len(calls) == 1: raise RuntimeError("SYNTHETIC interruption write failure")
            return interrupt(*args)
        def parser(*args): raise OSError(errno.ENOSPC, "SYNTHETIC original")
        monkeypatch.setattr(lib.store, "interrupt_text_retry", ending)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 507 and response.json()["code"] == "disk_full"
        assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "running"
        assert lib.store.pending_text_retry_interruptions
        if flush == "execute": response = lib.client.post(url(lib), json=body(lib))
        elif flush == "capability": response = lib.client.get(url(lib, "text-retry"))
        else: lib.store.next_queued_run()
        assert lib.conn.execute("SELECT lifecycle FROM asset_recovery_operations").fetchone()[0] == "interrupted"
        assert lib.store.pending_text_retry_interruptions == {}


def test_replay_does_not_sweep_or_touch_orphans_and_sweep_keeps_live_input(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        result = asyncio.run(execute(lib))
        folder = lib.settings.recovery_dir / "tmp"
        orphan = folder / (lib.sha + "-orphan.pdf"); orphan.write_bytes(b"SYNTHETIC orphan")
        def forbidden(*args): raise AssertionError("Replay touched files")
        monkeypatch.setattr(text_retry, "_sweep", forbidden)
        monkeypatch.setattr(text_retry, "precheck", forbidden)
        monkeypatch.setattr(text_retry, "file_lock", forbidden)
        assert asyncio.run(execute(lib)) == result | {"replayed": True}
        assert orphan.exists()


def test_sweep_removes_only_orphans_with_free_hash_lock_and_ignores_unlink_failure(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        folder = lib.settings.recovery_dir / "tmp"; folder.mkdir(parents=True)
        live = folder / (lib.sha + "-live.pdf"); live.write_bytes(b"SYNTHETIC live copy")
        orphan = folder / ("b" * 64 + "-orphan.pdf"); orphan.write_bytes(b"SYNTHETIC orphan")
        blocked = folder / ("c" * 64 + "-blocked.pdf"); blocked.write_bytes(b"SYNTHETIC blocked")
        invalid = folder / "unowned.pdf"; invalid.write_bytes(b"SYNTHETIC unknown file")
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == blocked: raise OSError(errno.EACCES, "SYNTHETIC cleanup denied")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", unlink)
        with child_lock(lib):
            text_retry._sweep(lib.settings.recovery_dir)
            assert live.exists() and blocked.exists() and invalid.exists() and not orphan.exists()
        monkeypatch.setattr(Path, "unlink", original)
        text_retry._sweep(lib.settings.recovery_dir)
        assert not live.exists() and not blocked.exists() and invalid.exists()


def test_copy_and_parser_use_private_permissions_and_no_open_transaction(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        thread_id = threading.get_ident()
        original, parse = text_retry.observe_copy, pdf.extract_pdf
        observed = []
        def copy(*args):
            assert not lib.conn.in_transaction and threading.get_ident() != thread_id
            path = args[-1]
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
            return original(*args)
        def parser(path):
            assert not lib.conn.in_transaction and threading.get_ident() != thread_id
            assert path != lib.path and path.read_bytes() == lib.data
            observed.append(path)
            return parse(path)
        record_input = lib.store.record_text_retry_input
        def record_on_caller(*args, **kwargs):
            assert threading.get_ident() == thread_id
            return record_input(*args, **kwargs)
        monkeypatch.setattr(text_retry, "observe_copy", copy)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        monkeypatch.setattr(lib.store, "record_text_retry_input", record_on_caller)
        assert asyncio.run(execute(lib))["outcome"] == "promoted"
        assert observed and not observed[0].exists()


def test_wrong_size_copy_hashes_whole_file_without_writing_destination(tmp_path):
    import hashlib
    with store_library(tmp_path) as lib:
        target = tmp_path / "copy.pdf"; target.write_bytes(b"SYNTHETIC sentinel")
        data = lib.data + b"SYNTHETIC extra"
        lib.path.write_bytes(data)
        assert text_retry.observe_copy(lib.settings.papers_dir, lib.path.name, lib.sha, len(lib.data), target) == (
            "mismatch", hashlib.sha256(data).hexdigest(), len(data))
        assert target.read_bytes() == b"SYNTHETIC sentinel"


def test_refusal_and_interruption_event_failures_roll_back_and_keep_observation(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        op = reserve(lib); observation = record(lib, op)
        before = counts(lib.store)
        def fail(*args): raise RuntimeError("SYNTHETIC terminal event failure")
        monkeypatch.setattr(lib.store, "_event", fail)
        for end in (lambda: lib.store.refuse_text_retry(op["id"], "file_missing"),
                    lambda: lib.store.interrupt_text_retry(op["id"], "storage_full")):
            with pytest.raises(RuntimeError): end()
            assert counts(lib.store) == before
            view = lib.store.text_retry_view(op["id"])
            assert view["lifecycle"] == "running" and view["input_observation_id"] == observation
