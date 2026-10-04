"""R2a API evidence: T1/T3 are behavioral red-on-old; other cases pair with those or compatibility guards."""

import asyncio
import errno
import hashlib
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from deixis.documents import pdf, ocr, math_reader
from deixis.storage import db
from deixis.workflow import equations
try:
    from deixis.workflow import text_retry
except ImportError:
    text_retry = None  # T1/T3 must reach their behavioral assertions on the R1 base.
from deixis.workflow.store import Store, RecoveryConflict
from tests.reextract.reextract_r2a_helpers import api_library, body, counts, head, protected, seed, sharing, url, child_lock
from tests.reextract.reextract_r2a_helpers import PUBLIC_RETRY_FIELDS


def assert_event_agreement(lib, result):
    row = dict(lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE id = ?", (result["operation_id"],)).fetchone())
    events = lib.conn.execute("SELECT payload_json FROM events WHERE type = 'asset_text_retried'").fetchall()
    fields = ("lifecycle", "outcome", "reason", "decision_code")
    for key in fields:
        assert result[key] == row[key]
    relevant = [json.loads(e[0]) for e in events if json.loads(e[0])["operation_id"] == result["operation_id"]]
    assert len(relevant) == len(lib.store._asset_researches(lib.svid))
    for payload in relevant:
        assert payload == {k: result[k] for k in ("asset_id", "operation_id", *fields, "extraction_version", "baseline_extraction_id")} | {
            "source_version_id": lib.svid}


@pytest.mark.parametrize("lifecycle", ["completed", "interrupted", "running"])
def test_public_retry_fields_are_closed_on_post_replay_and_capability(tmp_path, monkeypatch, lifecycle):
    with api_library(tmp_path, "partial") as lib:
        request = body(lib)
        if lifecycle == "running":
            lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid,
                idempotency_key=request["idempotency_key"], research_id=lib.rid,
                request_fingerprint=text_retry.fingerprint(asset_id=lib.aid, source_version_id=lib.svid,
                    research_id=lib.rid, expected_extraction_id=lib.eid))
        elif lifecycle == "interrupted":
            def fail(*args): raise RuntimeError("SYNTHETIC parser failure")
            monkeypatch.setattr(pdf, "extract_pdf", fail)
            assert lib.client.post(url(lib), json=request).status_code == 500
        response = lib.client.post(url(lib), json=request)
        assert response.status_code == (202 if lifecycle == "running" else 200)
        first = response.json()["recovery"]
        replay_response = lib.client.post(url(lib), json=request)
        assert replay_response.status_code == response.status_code
        replay = replay_response.json()["recovery"]
        latest = lib.client.get(url(lib, "text-retry")).json()["latest_operation"]
        assert set(first) == set(replay) == PUBLIC_RETRY_FIELDS | {"replayed"}
        assert set(latest) == PUBLIC_RETRY_FIELDS
        assert first["lifecycle"] == lifecycle
        assert replay == first | {"replayed": True}
        assert latest == {k: v for k, v in first.items() if k != "replayed"}
        row = lib.store._text_retry_operation(first["operation_id"])
        assert row["kind"] == "text_retry" and row["expected_sha256"] == lib.sha
        for result in (first, replay, latest):
            encoded = json.dumps(result)
            for private_field in ("idempotency_key", "request_fingerprint", "expected_sha256",
                                  "old_coverage_json", "new_coverage_json", "manifest"):
                assert f'"{private_field}"' not in encoded
            assert row["idempotency_key"] not in encoded and row["request_fingerprint"] not in encoded
        if lifecycle == "completed":
            assert first["coverage"] == {"old_text_pages": [1, 2], "new_text_pages": [1, 2, 3], "missing_pages": []}


def test_unknown_recovery_conflict_remains_a_coded_409(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        async def conflict(*args, **kwargs): raise RecoveryConflict("unknown_reason")
        monkeypatch.setattr(text_retry, "execute_text_retry", conflict)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 409
        assert response.json() == {"detail": "This text retry conflicts with the current recovery state.",
                                   "code": "unknown_reason"}
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("phase", ["lock_directory", "parse"])
def test_ordinary_upgrade_disk_full_is_507_and_preserves_head(tmp_path, monkeypatch, phase):
    with api_library(tmp_path, version="older-v1") as lib:
        before = protected(lib.store), counts(lib.store)
        def fail(*args, **kwargs): raise OSError(errno.ENOSPC, "SYNTHETIC full")
        monkeypatch.setattr(text_retry if phase == "lock_directory" else pdf,
                            "_private_dir" if phase == "lock_directory" else "extract_pdf", fail)
        response = lib.client.post(url(lib))
        assert response.status_code == 507 and response.json()["code"] == "disk_full"
        assert (protected(lib.store), counts(lib.store)) == before
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def test_lifespan_configures_recovery_directory_with_separate_statements(tmp_path):
    import ast
    import inspect
    from deixis.api.app import create_app
    tree = ast.parse(inspect.getsource(create_app))
    lifespan = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    store_assignment = next(node for node in lifespan.body if isinstance(node, ast.Assign)
                            and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                            and node.value.func.id == "Store")
    recovery_assignment = next(node for node in lifespan.body if isinstance(node, ast.Assign)
                               and any(isinstance(target, ast.Attribute) and target.attr == "recovery_dir"
                                       for target in node.targets))
    assert store_assignment.end_lineno < recovery_assignment.lineno
    with api_library(tmp_path) as lib:
        assert lib.store.recovery_dir == lib.settings.recovery_dir


def test_t1_repaired_failed_same_profile_publishes_new_head_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        old = head(lib.store, lib.aid)
        sharing(lib)
        lib.path.write_bytes(lib.data[:len(lib.data) * 4 // 10])
        restored = lib.client.post(f"/api/researches/{lib.rid}/sources/{lib.svid}/uploads",
                                  files={"file": ("synthetic.pdf", lib.data, "application/pdf")})
        assert restored.status_code == 201, restored.text
        assert lib.path.read_bytes() == lib.data and head(lib.store, lib.aid) == old
        response = lib.client.post(url(lib), json=body(lib))
        legacy = response.json().get("reextraction")
        current = head(lib.store, lib.aid)
        assert current["id"] != old["id"] and current["extraction_version"].startswith(pdf.EXTRACTION_VERSION + "+reextract-"), legacy
        assert response.status_code == 200
        result = response.json()["recovery"]
        assert (result["outcome"], result["decision_code"], result["input_integrity"]) == ("promoted", "recovered_text", "verified")
        assert current["extraction_version"] == pdf.EXTRACTION_VERSION + "+reextract-" + result["operation_id"]
        assert current["extractor_profile"] == pdf.EXTRACTION_VERSION
        assert dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE id = ?", (old["id"],)).fetchone()) == old | {"outcome": "superseded"}
        assert {p["physical_page"] for p in lib.store.passages_for(lib.svid)} == {1, 2, 3}
        obs = lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (result["input_observation_id"],)).fetchone()
        assert (obs["kind"], obs["observed_sha256"]) == ("extraction_input", lib.sha)
        assert_event_agreement(lib, result)


def test_no_body_same_profile_failed_is_unchanged_guard(tmp_path):
    with api_library(tmp_path) as lib:
        before = counts(lib.store)
        response = lib.client.post(url(lib))
        assert response.status_code == 200 and response.json()["reextraction"]["outcome"] == "unchanged"
        assert counts(lib.store) == before


def test_no_body_failed_retry_available_reason_new_contract(tmp_path):
    with api_library(tmp_path) as lib:
        assert lib.client.post(url(lib), content=b"").json()["reextraction"]["reason"] == "retry_available"


def test_t3_partial_retry_preserves_cited_passages_red_on_old(tmp_path):
    from tests.reextract.test_reextract_r1_store import cited_answer
    with api_library(tmp_path, "partial") as lib:
        old = head(lib.store, lib.aid)
        passages = [dict(r) for r in lib.conn.execute("SELECT * FROM passages WHERE asset_id = ?", (lib.aid,))]
        cited_answer(lib, passages[0]["id"])
        links = [tuple(r) for r in lib.conn.execute("SELECT * FROM evidence_links")]
        response = lib.client.post(url(lib), json=body(lib))
        legacy = response.json().get("reextraction")
        current = head(lib.store, lib.aid)
        assert current["id"] != old["id"] and current["extraction_version"].startswith(pdf.EXTRACTION_VERSION + "+reextract-"), legacy
        assert response.status_code == 200 and response.json()["recovery"]["decision_code"] == "text_updated"
        assert response.json()["recovery"]["outcome"] == "promoted"
        for p in passages:
            assert dict(lib.conn.execute("SELECT * FROM passages WHERE id = ?", (p["id"],)).fetchone()) == p
        retrieved = lib.store.passages_for(lib.svid)
        assert retrieved[0]["text"] == passages[0]["text"] and retrieved[0]["id"] != passages[0]["id"]
        assert {p["extraction_version"] for p in retrieved} == {current["extraction_version"]}
        assert set(lib.store.evidence_statuses([p["id"] for p in passages]).values()) == {"text_superseded"}
        assert lib.store.has_pdf_text(lib.svid)
        assert [tuple(r) for r in lib.conn.execute("SELECT * FROM evidence_links")] == links


@pytest.mark.parametrize("first_kind", ["torn", "parser_failure"])
def test_t6_replays_preserve_each_attempt_without_work(tmp_path, monkeypatch, first_kind):
    with api_library(tmp_path) as lib:
        real = pdf.extract_pdf
        calls = {"copy": 0, "parse": 0}
        observe = text_retry.observe_copy
        def copy(*args):
            calls["copy"] += 1
            return observe(*args)
        def parse(*args):
            calls["parse"] += 1
            return pdf.Extraction("failed", 0, [], error="extraction timed out") if first_kind == "parser_failure" and calls["parse"] == 1 else real(*args)
        monkeypatch.setattr(text_retry, "observe_copy", copy)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        if first_kind == "torn": lib.path.write_bytes(lib.data[:40])
        first = lib.client.post(url(lib), json=body(lib)).json()["recovery"]
        assert first["outcome"] == ("refused" if first_kind == "torn" else "rejected")
        assert (first["reason"] or first["decision_code"]) == ("file_mismatch" if first_kind == "torn" else "candidate_failed")
        lib.path.write_bytes(lib.data)
        second = lib.client.post(url(lib), json=body(lib, "request_0002")).json()["recovery"]
        assert second["outcome"] == "promoted"
        before, work = counts(lib.store), calls.copy()
        for key, saved in (("request_0001", first), ("request_0002", second)):
            assert lib.client.post(url(lib), json=body(lib, key)).json()["recovery"] == saved | {"replayed": True}
        assert counts(lib.store) == before and calls == work
        assert lib.client.post(url(lib), json=body(lib, "request_0002", "different")).json()["code"] == "request_conflict"
        response = lib.client.post(url(lib), json=body(lib, "request_0003"))
        assert response.status_code == 409 and response.json()["code"] == "baseline_changed"


@pytest.mark.parametrize("change", ["csrf", "research", "membership", "foreign", "removed"])
def test_request_authority_refusals_write_no_operation(tmp_path, change):
    with api_library(tmp_path) as lib:
        if change == "csrf": lib.client.headers.pop("x-deixis-csrf")
        elif change == "research": lib.rid = lib.store.create_research("SYNTHETIC absent source?", "attached", "quick", [], "fake", "fake", None)
        elif change == "membership": lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        elif change == "foreign": lib.aid = seed(lib.store, lib.settings).aid
        elif change == "removed": lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == (403 if change == "csrf" else 404)
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("change", ["unknown_mode", "missing", "short_key", "extra", "empty_id", "long_id", "bad_key"])
def test_body_validation_refusals_write_no_operation(tmp_path, change):
    with api_library(tmp_path) as lib:
        request = body(lib)
        if change == "unknown_mode": request["mode"] = "force"
        elif change == "missing": request.pop("expected_current_extraction_id")
        elif change == "short_key": request["idempotency_key"] = "short"
        elif change == "extra": request["force"] = True
        elif change == "empty_id": request["expected_current_extraction_id"] = ""
        elif change == "long_id": request["expected_current_extraction_id"] = "x" * 65
        else: request["idempotency_key"] = "invalid.key"
        assert lib.client.post(url(lib), json=request).status_code == 422
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("status,reason", [("succeeded", "already_current"), ("pending", "pending")])
def test_healthy_and_pending_are_not_retryable(tmp_path, status, reason):
    with api_library(tmp_path, status) as lib:
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 422
        assert response.json()["code"] == "not_retryable" and response.json()["reason"] == reason
        assert lib.client.post(url(lib)).json()["reextraction"]["reason"] == reason
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("kind", ["traversal", "absolute", "separator", "symlink", "directory", "missing"])
def test_precheck_invalid_paths_write_no_operation(tmp_path, kind):
    with api_library(tmp_path) as lib:
        if kind in ("traversal", "absolute", "separator"):
            lib.conn.execute("UPDATE source_assets SET storage_path = ? WHERE id = ?",
                             ({"traversal": "..pdf", "absolute": str(lib.path), "separator": "a/b.pdf"}[kind], lib.aid))
        else:
            lib.path.unlink()
            if kind == "symlink":
                outside = tmp_path / "outside.pdf"; outside.write_bytes(lib.data); lib.path.symlink_to(outside)
            elif kind == "directory": lib.path.mkdir()
        assert lib.client.post(url(lib), json=body(lib)).status_code == 404
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("kind", ["same_size", "larger", "torn"])
def test_mismatch_observes_digest_and_size_without_parsing(tmp_path, monkeypatch, kind):
    with api_library(tmp_path) as lib:
        data = bytearray(lib.data)
        if kind == "same_size": data[50] ^= 1
        elif kind == "larger": data += b"SYNTHETIC EXTRA"
        else: data = data[:40]
        lib.path.write_bytes(data)
        monkeypatch.setattr(pdf, "extract_pdf", lambda *a: pytest.fail("Mismatched input was parsed"))
        result = lib.client.post(url(lib), json=body(lib)).json()["recovery"]
        assert (result["outcome"], result["reason"], result["input_integrity"]) == ("refused", "file_mismatch", "mismatch")
        obs = lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (result["input_observation_id"],)).fetchone()
        assert obs["observed_sha256"] == hashlib.sha256(data).hexdigest() and obs["observed_byte_size"] == len(data)
        assert counts(lib.store)["asset_extractions"] == 1
        assert list((lib.settings.recovery_dir / "tmp").iterdir()) == []


@pytest.mark.parametrize("ordinary", [False, True])
def test_child_file_lock_refuses_retry_and_ordinary_upgrade(tmp_path, ordinary):
    with api_library(tmp_path, version="older-v1" if ordinary else None) as lib, child_lock(lib):
        response = lib.client.post(url(lib), **({} if ordinary else {"json": body(lib)}))
        assert response.status_code == 409 and response.json()["code"] == "file_busy"
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("error,code,status,reason", [
    (OSError(errno.ENOSPC, "SYNTHETIC full"), "disk_full", 507, "storage_full"),
    (RuntimeError("SYNTHETIC parser failure"), None, 500, "unexpected_error"),
    (sqlite3.OperationalError("SYNTHETIC unclassified"), None, 500, "unexpected_error"),
])
def test_interruption_retains_verified_input_and_replays(tmp_path, monkeypatch, error, code, status, reason):
    with api_library(tmp_path) as lib:
        sharing(lib)
        def fail(*args): raise error
        monkeypatch.setattr(pdf, "extract_pdf", fail)
        first = lib.client.post(url(lib), json=body(lib))
        assert first.status_code == status
        if code: assert first.json()["code"] == code
        assert "recovery" not in (first.json() if status != 500 else {})
        replay = lib.client.post(url(lib), json=body(lib))
        assert replay.status_code == 200
        result = replay.json()["recovery"]
        assert (result["lifecycle"], result["outcome"], result["reason"], result["input_integrity"]) == ("interrupted", None, reason, "verified")
        assert lib.client.get(url(lib, "text-retry")).json()["latest_operation"] == {k: v for k, v in result.items() if k != "replayed"}
        assert counts(lib.store)["asset_extractions"] == 1
        assert_event_agreement(lib, result)
        assert list((lib.settings.recovery_dir / "tmp").iterdir()) == []
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


@pytest.mark.parametrize("where", ["before", "copy", "completion_busy"])
def test_storage_failures_keep_original_code(tmp_path, monkeypatch, where):
    with api_library(tmp_path) as lib:
        error = OSError(errno.ENOSPC, "SYNTHETIC full")
        def fail(*args, **kwargs): raise error
        if where == "before": monkeypatch.setattr(text_retry, "_private_dir", fail)
        elif where == "copy": monkeypatch.setattr(text_retry, "observe_copy", fail)
        else:
            error = sqlite3.OperationalError("SYNTHETIC busy"); error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            monkeypatch.setattr(lib.store, "complete_text_retry", fail)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == (503 if where == "completion_busy" else 507)
        assert response.json()["code"] == ("database_busy" if where == "completion_busy" else "disk_full")
        if where == "before": assert counts(lib.store)["asset_recovery_operations"] == 0
        else:
            result = lib.client.post(url(lib), json=body(lib)).json()["recovery"]
            assert result["lifecycle"] == "interrupted"
            assert result["reason"] == ("storage_unavailable" if where == "completion_busy" else "storage_full")
            assert result["input_integrity"] == ("verified" if where == "completion_busy" else None)


@pytest.mark.parametrize("race", ["baseline_changed", "membership_changed", "run_active", "queued"])
def test_final_transaction_races_preserve_competing_state_and_input(tmp_path, monkeypatch, race):
    with api_library(tmp_path) as lib:
        other = sharing(lib)
        real = pdf.extract_pdf
        oracle = {}
        def parse(path):
            candidate = real(path)
            conn = db.connect(lib.settings.db_path)
            store = Store(conn)
            try:
                if race == "baseline_changed":
                    store.reextract_asset(lib.aid, pdf.Extraction("failed", 0, [], error="SYNTHETIC competing failure"),
                                          "competing-v1", pdf.chunk_page)
                elif race == "membership_changed": store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed during parse")
                else:
                    run = store.create_run(other, "answer", {}, None)
                    if race == "run_active": store.update_run(run["id"], status="running")
                oracle.update(protected(store))
            finally: conn.close()
            return candidate
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        result = lib.client.post(url(lib), json=body(lib)).json()["recovery"]
        assert result["input_integrity"] == "verified"
        if race == "queued": assert result["outcome"] == "promoted"
        else:
            assert result["outcome"] == "refused" and result["reason"] == race
            assert protected(lib.store) == oracle
            # Removed membership prevents endpoint replay, so exercise the shared stored serializer directly.
            assert lib.store.text_retry_view(result["operation_id"])["input_integrity"] == "verified"
            replay = asyncio.run(text_retry.execute_text_retry(lib.store, lib.settings, asset_id=lib.aid,
                expected_extraction_id=lib.eid, idempotency_key="request_0001", research_id=lib.rid,
                source_version_id=lib.svid))
            assert replay == result | {"replayed": True}


@pytest.mark.parametrize("swap", ["fifo", "symlink"])
def test_nonregular_swap_between_lstat_and_open_never_blocks(tmp_path, monkeypatch, swap):
    with api_library(tmp_path) as lib:
        original = os.open
        def swapped(path, flags, *args, **kwargs):
            if Path(path) == lib.path:
                lib.path.unlink()
                if swap == "fifo": os.mkfifo(lib.path)
                else: lib.path.symlink_to(tmp_path / "absent.pdf")
            return original(path, flags, *args, **kwargs)
        monkeypatch.setattr(os, "open", swapped)
        response = lib.client.post(url(lib), json=body(lib))
        result = response.json()["recovery"]
        assert result["reason"] == "file_missing" and result["input_integrity"] == "missing"
        assert counts(lib.store)["asset_extractions"] == 1
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert list((lib.settings.recovery_dir / "tmp").iterdir()) == []


def test_inflight_replay_uses_no_lock_copy_or_parser_and_queued_run_waits(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        entered, release = threading.Event(), threading.Event()
        real, calls = pdf.extract_pdf, {"parse": 0, "copy": 0, "lock": 0}
        observe, lock = text_retry.observe_copy, text_retry.file_lock
        def parse(path):
            calls["parse"] += 1; entered.set(); assert release.wait(15); return real(path)
        def copy(*args): calls["copy"] += 1; return observe(*args)
        def locking(*args): calls["lock"] += 1; return lock(*args)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        monkeypatch.setattr(text_retry, "observe_copy", copy)
        monkeypatch.setattr(text_retry, "file_lock", locking)
        with ThreadPoolExecutor() as executor:
            first = executor.submit(lib.client.post, url(lib), json=body(lib))
            try:
                assert entered.wait(15)
                before = counts(lib.store)
                second = lib.client.post(url(lib), json=body(lib))
                assert second.status_code == 202
                assert second.json()["recovery"]["lifecycle"] == "running" and second.json()["recovery"]["replayed"]
                assert calls == {"parse": 1, "copy": 1, "lock": 1} and counts(lib.store) == before
                run = lib.store.create_run(lib.rid, "answer", {}, None)
                assert lib.store.next_queued_run() is None
            finally: release.set()
            assert first.result(15).json()["recovery"]["outcome"] == "promoted"
        assert lib.store.next_queued_run()["id"] == run["id"]


@pytest.mark.parametrize("result_kind", ["promoted", "diagnosis_updated", "rejected", "no_change", "refused", "interrupted"])
def test_responses_events_and_research_view_agree(tmp_path, monkeypatch, result_kind):
    status = "no_text" if result_kind == "diagnosis_updated" else "partial" if result_kind == "no_change" else "failed"
    with api_library(tmp_path, status) as lib:
        sharing(lib)
        if result_kind == "diagnosis_updated": monkeypatch.setattr(pdf, "extract_pdf", lambda p: pdf.Extraction("failed", 0, [], error=pdf.ERROR_PASSWORD))
        elif result_kind == "rejected": monkeypatch.setattr(pdf, "extract_pdf", lambda p: pdf.Extraction("failed", 0, [], error="extraction timed out"))
        elif result_kind == "no_change":
            real = pdf.extract_pdf
            def identical(p):
                candidate = real(p); candidate.status = "partial"; candidate.pages = candidate.pages[:2]; return candidate
            monkeypatch.setattr(pdf, "extract_pdf", identical)
        elif result_kind == "refused": lib.path.write_bytes(b"%PDF-TORN")
        elif result_kind == "interrupted":
            def fail(p): raise RuntimeError("SYNTHETIC parser")
            monkeypatch.setattr(pdf, "extract_pdf", fail)
        response = lib.client.post(url(lib), json=body(lib))
        if result_kind == "interrupted":
            assert response.status_code == 500
            response = lib.client.post(url(lib), json=body(lib))
        result = response.json()["recovery"]
        assert result["outcome"] == (None if result_kind == "interrupted" else result_kind)
        assert_event_agreement(lib, result)
        assert lib.client.get(f"/api/researches/{lib.rid}").status_code == 200
        capability = lib.client.get(url(lib, "text-retry")).json()
        assert capability["latest_operation"] == {k: v for k, v in result.items() if k != "replayed"}


@pytest.mark.parametrize("state,reason", [("failed", None), ("partial", None), ("no_text", None),
    ("succeeded", "already_current"), ("pending", "pending"), ("running", "operation_running"),
    ("crashed", "operation_running"), ("queued", "run_active"), ("missing", "file_missing"),
    ("two_blockers", "operation_running"), ("no_current", "no_current_extraction")])
def test_capability_order_and_read_only_counts(tmp_path, state, reason):
    with api_library(tmp_path, state if state in ("failed", "partial", "no_text", "succeeded", "pending") else "failed") as lib:
        if state in ("running", "crashed", "two_blockers"):
            lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key="capability", request_fingerprint="capability")
        if state in ("queued", "two_blockers"): lib.store.create_run(lib.rid, "answer", {}, None)
        if state == "missing": lib.path.unlink()
        if state == "no_current": lib.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ?", (lib.aid,))
        lib.client.headers.pop("x-deixis-csrf")
        before = counts(lib.store)
        with text_retry.file_lock(lib.settings.recovery_dir, lib.sha) if state == "running" else __import__("contextlib").nullcontext():
            result = lib.client.get(url(lib, "text-retry"))
        assert result.status_code == 200 and result.json()["reason"] == reason
        assert result.json()["can_retry_text"] == (reason is None)
        assert counts(lib.store) == before


def test_retry_calls_only_text_parser_with_tool_model_and_http_fail_on_call(tmp_path, monkeypatch):
    with api_library(tmp_path, "partial") as lib:
        def forbidden(*args, **kwargs): raise AssertionError("Retry invoked a tool or model")
        monkeypatch.setattr(ocr, "read_page", forbidden)
        monkeypatch.setattr(math_reader.MathReader, "read", forbidden)
        monkeypatch.setattr(equations.EquationService, "read_asset", forbidden)
        class ForbiddenAdapter:
            async def run_step(self, *args, **kwargs): forbidden()
            async def health(self, *args, **kwargs): forbidden()
            async def cancel(self, *args, **kwargs): forbidden()
            async def close(self): pass
        lib.app.state.adapters["fake"] = ForbiddenAdapter()
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 200 and response.json()["recovery"]["outcome"] == "promoted"


def test_later_d52_selection_after_partial_retry_is_separate_guard(tmp_path):
    from tests.documents.test_equations import FakeReader
    with api_library(tmp_path, "partial") as lib:
        op = lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid,
            idempotency_key="d52-guard", request_fingerprint="d52-guard")
        obs = lib.store.add_file_observation(kind="extraction_input", operation_id=op["id"], storage_path=lib.path.name,
            expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
            observed_byte_size=len(lib.data), integrity="verified")
        assert lib.store.complete_text_retry(op["id"], pdf.extract_pdf(lib.path), pdf.chunk_page,
                                            input_observation_id=obs)["outcome"] == "promoted"
        assert equations.EquationService(lib.store, FakeReader(), lib.settings.papers_dir).next_asset() == lib.aid


def test_storage_classifier_keeps_unclassified_sqlite_errors_as_code_errors_guard():
    assert db.describe_failure(sqlite3.OperationalError("SYNTHETIC without an error code")) is None
    assert db.describe_failure(OSError(errno.ENOSPC, "SYNTHETIC full"))[0] == "disk_full"


def test_shared_file_assets_exclude_each_other_but_other_hash_proceeds(tmp_path, monkeypatch):
    from tests.helpers import make_pdf
    with api_library(tmp_path) as lib:
        shared = seed(lib.store, lib.settings, version="older-v1", data=lib.data)
        separate = seed(lib.store, lib.settings, data=make_pdf(["SYNTHETIC distinct file."]))
        real, entered, release = pdf.extract_pdf, threading.Event(), threading.Event()
        def parse(path):
            if path.name.startswith(lib.sha):
                entered.set(); assert release.wait(15)
            return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        with ThreadPoolExecutor() as executor:
            first = executor.submit(lib.client.post, url(lib), json=body(lib))
            try:
                assert entered.wait(15)
                for request in ({"json": body(shared, "shared_request")}, {}):
                    response = lib.client.post(url(shared), **request)
                    assert response.status_code == 409 and response.json()["code"] == "file_busy"
                assert lib.conn.execute("SELECT COUNT(*) FROM asset_recovery_operations WHERE asset_id = ?", (shared.aid,)).fetchone()[0] == 0
                assert lib.client.post(url(separate), json=body(separate, "separate_request")).json()["recovery"]["outcome"] == "promoted"
            finally: release.set()
            assert first.result(15).json()["recovery"]["outcome"] == "promoted"


@pytest.mark.parametrize("conflicting", [False, True])
def test_same_key_race_at_lock_replays_inflight_or_reports_request_conflict(tmp_path, monkeypatch, conflicting):
    # Park only the first request's precheck, after its initial key lookup. The second owns the lock and reservation.
    with api_library(tmp_path) as lib:
        parked, proceed, parsing, release = (threading.Event() for _ in range(4))
        check, real = text_retry.precheck, pdf.extract_pdf
        counter, guard = [0], threading.Lock()
        def precheck(*args):
            with guard:
                counter[0] += 1; first = counter[0] == 1
            if first: parked.set(); assert proceed.wait(15)
            return check(*args)
        def parser(path):
            parsing.set(); assert release.wait(15); return real(path)
        monkeypatch.setattr(text_retry, "precheck", precheck)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        first_body = body(lib, eid="ext_conflicting") if conflicting else body(lib)
        def independent_request():
            async def send():
                transport = httpx.ASGITransport(app=lib.app, client=("testclient", 123))
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", cookies=dict(lib.client.cookies),
                    headers={"x-deixis-csrf": lib.token}) as client:
                    return await client.post(url(lib), json=first_body)
            return asyncio.run(send())
        with ThreadPoolExecutor() as executor:
            first = executor.submit(independent_request)
            try:
                assert parked.wait(15)
                second = executor.submit(lib.client.post, url(lib), json=body(lib))
                assert parsing.wait(15)
                proceed.set()
                response = first.result(15)
                assert response.status_code == (409 if conflicting else 202)
                if conflicting: assert response.json()["code"] == "request_conflict"
                else: assert response.json()["recovery"]["replayed"] and response.json()["recovery"]["lifecycle"] == "running"
            finally: proceed.set(); release.set()
            assert second.result(15).json()["recovery"]["outcome"] == "promoted"


def test_ordinary_upgrade_cancellation_holds_lock_until_parser_thread_returns(tmp_path, monkeypatch):
    from starlette.requests import Request
    from starlette.responses import Response
    with api_library(tmp_path, version="older-v1") as lib:
        entered, release = threading.Event(), threading.Event()
        real = pdf.extract_pdf
        def parser(path):
            entered.set(); assert release.wait(15); return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        endpoint = next(route.endpoint for route in lib.app.routes if getattr(route, "path", "") == url(lib).replace(lib.rid, "{research_id}").replace(lib.svid, "{source_version_id}").replace(lib.aid, "{asset_id}"))
        request = Request({"type": "http", "app": lib.app})
        async def scenario():
            task = asyncio.create_task(endpoint(lib.rid, lib.svid, lib.aid, request, Response()))
            for _ in range(1500):
                if entered.is_set(): break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            task.cancel(); await asyncio.sleep(0.02)
            assert text_retry.lock_held(lib.settings.recovery_dir, lib.sha) and not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
        try: asyncio.run(scenario())
        finally: release.set()
        assert head(lib.store, lib.aid)["id"] == lib.eid
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


@pytest.mark.parametrize("locked", [False, True])
def test_second_store_reservation_and_other_research_queued_run_refuse(tmp_path, locked):
    with api_library(tmp_path) as lib:
        second = db.connect(lib.settings.db_path)
        try:
            Store(second).reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key="other-key", request_fingerprint="other")
            with child_lock(lib) if locked else __import__("contextlib").nullcontext():
                response = lib.client.post(url(lib), json=body(lib))
            prior = lib.store.text_retry_by_key("other-key")
            if locked:
                assert response.status_code == 409 and response.json()["code"] == "file_busy"
                assert prior["lifecycle"] == "running"
            else:
                assert response.status_code == 200 and response.json()["recovery"]["outcome"] == "promoted"
                assert (prior["lifecycle"], prior["reason"]) == ("interrupted", "process_ended")
        finally: second.close()
    with api_library(tmp_path / "active") as lib:
        other = sharing(lib)
        lib.store.create_run(other, "answer", {}, None)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 409 and response.json()["code"] == "run_active"
        assert counts(lib.store)["asset_recovery_operations"] == 0


def test_paused_run_allows_retry_then_resumes(tmp_path):
    with api_library(tmp_path) as lib:
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.update_run(run["id"], status="paused")
        assert lib.client.post(url(lib), json=body(lib)).json()["recovery"]["outcome"] == "promoted"
        assert lib.store.resume_run(run["id"])["status"] == "queued"
        assert lib.store.next_queued_run()["id"] == run["id"]
