"""Recovered-head targeting and real synthetic tool execution; no live service or network."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.documents import pdf, ocr, math_reader
from deixis.storage import db
from deixis.workflow import equations, recovery
from deixis.workflow.store import Store
from tests.reextract.test_reextract_r1_store import lib, setup, extraction, chunk, head, complete, reserve, observe, cited_answer
from tests.documents.test_ocr_run import fake_reader, upload, ocr_url, SCAN, READY
from tests.app.test_api_flow import app_for, create, session, wait_run
from tests.documents.test_equations import FakeReader, stored_pdf
from tests.documents.test_arxiv_source_route import library, service, read, FakeFetch


@pytest.mark.parametrize("head_version,base,ocr_part", [
    ("B", "", ""),
    ("B+ocr-tesseract-5-eng-v1", "", "+ocr-tesseract-5-eng-v1"),
    ("B+reextract-rop_X", "+reextract-rop_X", ""),
    ("B+reextract-rop_X+ocr-tesseract-5-eng-v1", "+reextract-rop_X", "+ocr-tesseract-5-eng-v1"),
    ("B+reextract-rop_X+ocr-tesseract-5-eng-v1+marker-old", "+reextract-rop_X", "+ocr-tesseract-5-eng-v1"),
])
def test_marker_and_source_targeting_preserves_token_ocr_and_plain_literals(monkeypatch, head_version, base, ocr_part):
    monkeypatch.setattr(pdf, "EXTRACTION_VERSION", "B")
    monkeypatch.setattr(math_reader, "MATH_VERSION", "marker-1.10.1-math-v2")
    assert equations.target_version(head_version) == "B" + base + ocr_part + "+marker-1.10.1-math-v2"
    assert equations.source_target_version(head_version) == "B" + base + ocr_part + "+arxiv-latex-v1"


def test_t10_rejected_plain_ocr_does_not_block_actual_recovery_occurrence(tmp_path, monkeypatch):
    calls = fake_reader(monkeypatch)
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw); rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)
        store = app.state.store
        old_target = ocr.target_version(pdf.EXTRACTION_VERSION, READY["version"], READY["languages"])
        empty = pdf.Extraction("failed", 4, error="SYNTHETIC OCR failure")
        store.reextract_asset(aid, empty, old_target, pdf.chunk_page)
        # Guard paired with the recovered-head assertion: plain-head repeat is still 409.
        assert client.post(ocr_url(rid, svid, aid)).status_code == 409
        baseline = dict(store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone())
        operation = store.reserve_text_retry(aid, expected_extraction_id=baseline["id"], idempotency_key="recovery", request_fingerprint="recovery")
        asset = store.asset(aid)
        observation = store.add_file_observation(kind="extraction_input", storage_path=asset["storage_path"],
            expected_sha256=asset["sha256"], expected_byte_size=asset["byte_size"],
            observed_sha256=asset["sha256"], observed_byte_size=asset["byte_size"], integrity="verified", operation_id=operation["id"])
        candidate = pdf.Extraction("partial", 4, [pdf.PageText(1, None, "SYNTHETIC revised text layer page.")])
        result = store.complete_text_retry(operation["id"], candidate, pdf.chunk_page, input_observation_id=observation)
        recovered = result["extraction_id"]
        started = client.post(ocr_url(rid, svid, aid))
        assert started.status_code == 202, started.text
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed" and sorted(calls) == [2, 4]
        target = recovery.text_base(store.asset(aid)["extraction_version"]) + old_target.removeprefix(pdf.EXTRACTION_VERSION)
        row = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (aid, target)).fetchone()
        assert row["outcome"] == "current" and row["extractor_profile"] == old_target
        assert row["baseline_extraction_id"] == recovered
        assert client.post(ocr_url(rid, svid, aid)).status_code == 409
def test_password_diagnosis_ocr_refuses_before_tool_check(tmp_path, monkeypatch):
    from deixis.config import Settings
    from deixis.api.app import create_app
    def forbidden(*args, **kwargs): raise AssertionError("Tesseract was checked for a password diagnosis")
    app = create_app(Settings(data_dir=tmp_path / "data"), start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw); store = app.state.store
        rid = store.create_research("SYNTHETIC?", "attached", "quick", [], "fake", "fake", None)
        svid = store.create_upload_source("SYNTHETIC locked")
        store.add_to_corpus(rid, svid, "user_upload")
        aid = store.add_asset_with_pages(svid, "1" * 64, 10, "synthetic.pdf", "user_upload", None, None,
                                        extraction("no_text", 0, ()), pdf.EXTRACTION_VERSION, chunk)
        ns = SimpleNamespace(store=store, conn=store.conn, aid=aid, svid=svid, rid=rid, sha="1" * 64, size=10)
        complete(ns, extraction("failed", 0, (), pdf.ERROR_PASSWORD))
        monkeypatch.setattr(ocr, "tesseract_status", forbidden)
        response = client.post(ocr_url(rid, svid, aid))
        assert response.status_code == 422
        assert response.json()["detail"] == "This PDF requires a password; OCR cannot read it"


def test_ocr_merge_malformed_recovery_token_is_not_reported_as_changed_pages(lib, tmp_path, monkeypatch):
    from deixis.workflow.flow import ResearchFlow

    fake_reader(monkeypatch)
    monkeypatch.setattr(pdf, "extract_pdf", lambda path: extraction())
    flow = ResearchFlow(SimpleNamespace(store=lib.store, settings=SimpleNamespace(papers_dir=tmp_path)))
    run = lib.store.create_run(lib.rid, "pdf_ocr", {}, None,
        target={"asset_id": lib.aid, "source_version_id": lib.svid, "languages": ["eng"]})
    real_asset = lib.store.asset
    def malformed_asset(asset_id):
        return real_asset(asset_id) | {"extraction_version": pdf.EXTRACTION_VERSION + "+reextract-rop-X"}
    monkeypatch.setattr(lib.store, "asset", malformed_asset)
    def forbidden_merge(*args, **kwargs):
        raise AssertionError("OCR merge received a malformed recovery identity")
    monkeypatch.setattr(ocr, "merge", forbidden_merge)
    with pytest.raises(ValueError, match="Malformed recovery token"):
        asyncio.run(flow._pdf_ocr(run))
    step = lib.store.existing_step(run["id"], "ocr:merge")
    assert step["error_code"] is None and step["status"] == "running"
    assert lib.store.run(run["id"])["pause_reason"] != "ocr_pages_changed"


@pytest.mark.parametrize("lost", [False, True])
def test_ocr_run_preserves_or_rejects_shifted_coverage(tmp_path, monkeypatch, lost):
    fake_reader(monkeypatch)
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw); rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)
        store = app.state.store
        # This stored synthetic baseline has 2 text pages in a 4-page PDF.
        base = extraction("partial", 4, (1, 2) if lost else (1, 4))
        store.reextract_asset(aid, base, "synthetic-baseline-v1", chunk)
        old = dict(store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone())
        real = pdf.extract_pdf
        def reparse(path, **kw):
            parsed = real(path, **kw)
            # Two output text pages after OCR, with page 2 lost in the shifted case.
            parsed.pages = [pdf.PageText(1, None, "SYNTHETIC page 1.")]
            parsed.image_pages = [4]
            return parsed
        monkeypatch.setattr(pdf, "extract_pdf", reparse)
        started = client.post(ocr_url(rid, svid, aid)); assert started.status_code == 202
        _, run = wait_run(client, rid, started.json()["id"]); assert run["status"] == "completed"
        target = ocr.target_version(pdf.EXTRACTION_VERSION, READY["version"], READY["languages"])
        row = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (aid, target)).fetchone()
        assert row["decision_code"] == ("text_page_lost" if lost else "upgraded")
        assert row["outcome"] == ("rejected" if lost else "current")
        assert row["baseline_extraction_id"] == old["id"]
        if lost: assert store.asset(aid)["extraction_version"] == old["extraction_version"]


@pytest.mark.parametrize("lost", [False, True])
def test_marker_execution_preserves_or_rejects_shifted_coverage(tmp_path, monkeypatch, lost):
    store, svid, aid, papers = stored_pdf(tmp_path, ["SYNTHETIC first.", "SYNTHETIC second.", ""])
    old = dict(store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone())
    real = pdf.extract_pdf
    def reparse(path, **kw):
        parsed = real(path, **kw)
        if lost: parsed.pages = [p for p in parsed.pages if p.physical_page != 1]
        return parsed
    monkeypatch.setattr(pdf, "extract_pdf", reparse)
    monkeypatch.setattr(math_reader, "math_pages", lambda path: [2] if lost else [1])
    monkeypatch.setattr(math_reader, "table_pages", lambda path: [])
    svc = equations.EquationService(store, FakeReader(), papers)
    asyncio.run(svc.read_asset(aid))
    row = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (aid, equations.target_version())).fetchone()
    assert row["decision_code"] == ("text_page_lost" if lost else "upgraded")
    assert row["outcome"] == ("rejected" if lost else "current")
    assert row["baseline_extraction_id"] == old["id"]
    if lost: assert store.asset(aid)["extraction_version"] == old["extraction_version"]
    store.conn.close()


@pytest.mark.parametrize("lost", [False, True])
def test_source_execution_preserves_or_rejects_shifted_coverage(tmp_path, monkeypatch, lost):
    store, svid, aid, papers = library(tmp_path)
    baseline = pdf.extract_pdf(papers / "paper.pdf")
    old = dict(store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone())
    real = pdf.extract_pdf
    def reparse(path, **kw):
        parsed = real(path, **kw)
        if kw.get("placements") and lost:
            # Same number of text pages, but page 2 disappears and page 3 appears.
            parsed.pages = [p for p in parsed.pages if p.physical_page == 1] + [pdf.PageText(3, None, "SYNTHETIC shifted.")]
        return parsed
    monkeypatch.setattr(pdf, "extract_pdf", reparse)
    svc = service(store, papers, tmp_path, fetcher=FakeFetch())
    read(svc, aid)
    target = equations.source_target_version(pdf.EXTRACTION_VERSION)
    row = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (aid, target)).fetchone()
    assert row["decision_code"] == ("text_page_lost" if lost else "upgraded")
    assert row["outcome"] == ("rejected" if lost else "current")
    assert row["baseline_extraction_id"] == old["id"]
    if lost: assert store.asset(aid)["extraction_version"] == old["extraction_version"]
    store.conn.close()


def test_next_asset_selects_recovered_head_despite_old_marker_and_does_not_repeat(lib, tmp_path):
    svc = equations.EquationService(lib.store, FakeReader(), tmp_path)
    old_target = equations.target_version()
    svc._record_without_passages(lib.store.asset(lib.aid), old_target, equations.NO_MATH, 1)
    assert svc.next_asset() is None
    result = complete(lib)
    version = head(lib)["extraction_version"]
    assert svc.next_asset() == lib.aid
    marker = extraction(pages=(1, 2, 3)); marker.math = {}
    target = equations.target_version(version)
    lib.store.reextract_asset(lib.aid, marker, target, chunk)
    assert svc.next_asset() is None
    assert head(lib)["baseline_extraction_id"] == result["extraction_id"]


def test_ocr_repeat_after_marker_in_same_recovery_lineage_keeps_existing_policy(lib):
    complete(lib); base = recovery.text_base(head(lib)["extraction_version"])
    target = ocr.target_version(base, READY["version"], READY["languages"])
    lib.store.reextract_asset(lib.aid, extraction("failed", 0, (), "failure"), target, chunk)
    marker = extraction(pages=(1, 2, 3)); marker.math = {}
    lib.store.reextract_asset(lib.aid, marker, equations.target_version(head(lib)["extraction_version"]), chunk)
    assert ocr.target_version(recovery.text_base(head(lib)["extraction_version"]), READY["version"], READY["languages"]) == target
    assert lib.conn.execute("SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (lib.aid, target)).fetchone()


def test_forget_failure_never_deletes_recovery_occurrence(lib, tmp_path):
    rejected = complete(lib, extraction("failed", 0, (), "failure"))
    svc = equations.EquationService(lib.store, FakeReader(), tmp_path)
    svc._forget_failure(lib.aid, lib.conn.execute("SELECT extraction_version FROM asset_extractions WHERE id = ?", (rejected["extraction_id"],)).fetchone()[0])
    assert lib.conn.execute("SELECT 1 FROM asset_extractions WHERE id = ?", (rejected["extraction_id"],)).fetchone()


@pytest.mark.parametrize("route", ["marker", "source"])
def test_equation_passageless_insert_duplicate_remains_no_op(lib, tmp_path, route):
    svc = equations.EquationService(lib.store, FakeReader(), tmp_path)
    target = equations.target_version() if route == "marker" else equations.source_target_version(None)
    def record():
        if route == "marker": svc._record_without_passages(lib.store.asset(lib.aid), target, equations.NO_MATH, 1)
        else: svc._record_source_rejection(lib.store.asset(lib.aid), target, equations.NOTHING_PLACED, None)
    record()
    before = [tuple(r) for r in lib.conn.execute("SELECT * FROM asset_extractions")]
    record()
    assert [tuple(r) for r in lib.conn.execute("SELECT * FROM asset_extractions")] == before
    row = lib.conn.execute("SELECT * FROM asset_extractions WHERE extraction_version = ?", (target,)).fetchone()
    assert row["extractor_profile"] == target and row["baseline_extraction_id"] == head(lib)["id"]


def test_source_guard_duplicate_insert_remains_no_op(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    original = store.reextract_asset
    def twice(asset_id, candidate, version, chunker, **kwargs):
        guard = kwargs["guard"]
        def double_guard(conn):
            first = guard(conn)
            assert guard(conn) == first
            return first
        return original(asset_id, candidate, version, chunker, **(kwargs | {"guard": double_guard}))
    monkeypatch.setattr(store, "reextract_asset", twice)
    def changed_record():
        store.conn.execute("UPDATE source_versions SET version_label = 'publishedVersion' WHERE id = ?", (svid,))
    svc = service(store, papers, tmp_path, fetcher=FakeFetch(before=changed_record))
    state = read(svc, aid)
    assert state["outcome"] == equations.RECORD_VERSION_CHANGED
    rows = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                              (aid, equations.source_target_version(None))).fetchall()
    assert len(rows) == 1 and rows[0]["rejection_reason"] == equations.RECORD_VERSION_CHANGED
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION
    store.conn.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_arxiv_withdrawal_restores_recorded_baseline_or_legacy_latest_red_on_old(tmp_path, monkeypatch, legacy):
    store, svid, aid, papers = library(tmp_path)
    baseline = store.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'current'").fetchone()[0]
    # Deterministic timestamps at insertion, with an unrelated superseded competitor
    # newer than the true predecessor. No immutable extraction is updated.
    import deixis.workflow.store as module
    monkeypatch.setattr(module, "now", lambda: "2098")
    competitor = store._write_extraction(svid, aid, pdf.extract_pdf(papers / "paper.pdf"), "competitor-v1", pdf.chunk_page, "superseded")
    monkeypatch.setattr(module, "now", lambda: "2099")
    target = equations.source_target_version(None)
    with db.transaction(store.conn):
        store.conn.execute("UPDATE asset_extractions SET outcome = 'superseded' WHERE id = ?", (baseline,))
        source = store._write_extraction(svid, aid, pdf.extract_pdf(papers / "paper.pdf"), target, pdf.chunk_page,
                                         "current", baseline_extraction_id=None if legacy else baseline)
        store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?", (target, aid))
        store.conn.execute("INSERT INTO asset_arxiv_versions (asset_id, eligibility, arxiv_key, version_from, record_label, checked_at)"
            " VALUES (?, 'eligible', '2101.00001v2', 'url', 'arXiv v2', 'now')", (aid,))
    old_query_choice = store.conn.execute(
        "SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'superseded' AND created_at <= '2099'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (aid,)).fetchone()[0]
    assert old_query_choice == competitor
    # A stored changed label makes the known version ineligible, using the real withdrawal call.
    store.conn.execute("UPDATE source_versions SET version_label = 'publishedVersion' WHERE id = ?", (svid,))
    store._recheck_arxiv_eligibility(svid)
    restored = store.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'current'").fetchone()[0]
    assert restored == (competitor if legacy else baseline)
    store.conn.close()


@pytest.mark.parametrize("result_kind", ["promoted", "rejected", "no_change", "refused"])
def test_b1_snapshot_retains_content_and_reports_only_promoted_extraction_staleness(lib, result_kind):
    from deixis.workflow.report.store import ReportStore
    from deixis.workflow.review.reader import ReviewReader
    from deixis.workflow.review.snapshot import build_snapshot
    from deixis.workflow.review.store import ReviewStore
    from deixis.workflow.review.stale import stale_reasons
    pid = lib.store.passages_for(lib.svid)[0]["id"]
    answer = cited_answer(lib, pid)
    reader = ReviewReader(lib.store, ReportStore(lib.store)); reviews = ReviewStore(lib.conn)
    content, markers = build_snapshot(reader, lib.rid, "answer", answer)
    snapshot = reviews.snapshot(reviews.add_snapshot(content, markers))
    if result_kind == "refused":
        operation = reserve(lib)
        lib.store.complete_text_retry(operation["id"], extraction(), chunk, input_observation_id=None)
    else:
        candidate = extraction("failed", 0, (), "failure") if result_kind == "rejected" else extraction(pages=(1, 2)) if result_kind == "no_change" else extraction(pages=(1, 2, 3))
        result = complete(lib, candidate)
        assert result["outcome"] == result_kind
    reasons = stale_reasons(reader, snapshot)
    codes = {r["code"] for r in reasons}
    assert codes == ({"extraction_changed", "text_superseded"} if result_kind == "promoted" else set())
    assert reviews.snapshot(snapshot["id"]) == snapshot
    if reasons:
        assert all(r["passage_id"] == pid and r["targets"] for r in reasons)
    if result_kind == "promoted":
        new_pid = lib.store.passages_for(lib.svid)[0]["id"]
        lib.conn.execute("UPDATE evidence_links SET passage_id = ? WHERE passage_id = ?", (new_pid, pid))
        next_content, _ = build_snapshot(reader, lib.rid, "answer", answer)
        entry = next(e for e in next_content["evidence_manifest"] if e["passage_id"] == new_pid)
        assert entry["passage_extraction_id"] == result["extraction_id"]
        assert entry["current_extraction_id_at_snapshot"] == result["extraction_id"]
