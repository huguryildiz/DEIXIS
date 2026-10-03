"""Synthetic R3 evidence libraries; no provider, model or live-data access."""

import asyncio
import json
import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
import pytest

from deixis.storage import db
from deixis.workflow import text_retry
from deixis.workflow.report.store import ReportStore
from deixis.workflow.review.reader import ReviewReader
from deixis.workflow.review.snapshot import build_snapshot
from deixis.workflow.review.store import ReviewStore, resolve_finding
from deixis.workflow.tables import TableStore
from tests.test_report_assembly import COLUMN, _claim
from tests.reextract_r2a_helpers import head
from tests.review_helpers import finding, step_payload, review_run


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    from tests.reextract_r2c_helpers import forbid_calls

    forbid_calls(monkeypatch, parser=False)


def old_dependency(conn, passage_id):
    row = conn.execute(
        "SELECT p.*, a.id AS dependency_asset_id, a.sha256 AS asset_sha256,"
        " a.removed_at, a.removal_reason, a.extraction_version AS asset_extraction_version,"
        " e.id AS passage_extraction_id, cur.id AS current_extraction_id_at_snapshot"
        " FROM passages p LEFT JOIN source_assets a ON a.id = p.asset_id"
        " LEFT JOIN asset_extractions e ON e.asset_id = p.asset_id AND e.extraction_version = p.extraction_version"
        " LEFT JOIN asset_extractions cur ON cur.asset_id = p.asset_id AND cur.outcome = 'current'"
        " WHERE p.id = ?", (passage_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["evidence_status"] = (
        "current" if result["dependency_asset_id"] is None else
        ("pdf_replaced" if result["removal_reason"] == "replaced" else "pdf_removed") if result["removed_at"] is not None else
        "text_superseded" if result["extraction_version"] != result["asset_extraction_version"] else "current"
    )
    return result


def retry(lib, key="r3_retry_key"):
    return asyncio.run(text_retry.execute_text_retry(lib.store, lib.settings, asset_id=lib.aid,
        expected_extraction_id=head(lib.store, lib.aid)["id"], idempotency_key=key,
        research_id=lib.rid, source_version_id=lib.svid))


def rich(lib, *, reviews=True):
    store = lib.store
    pid = store.passages_for(lib.svid)[0]["id"]
    quote = store.passage(pid)["text"]

    def input_for(run, step, task):
        iid = db.new_id("sti")
        store.insert_step_input(step["id"], lib.rid, run["id"], 0,
            {"step_input_id": iid, "task_type": task, "scope_revision": 1, "skill_package_hash": "sha256:synthetic",
             "question": {"text": "SYNTHETIC relays?", "language_hint": "en"},
             "sources": [{"source_id": lib.svid}],
             "passages": [{"passage_id": pid}], "allowlist": {"passage_ids": [pid]}},
             "base", "developer", "message", {})
        return iid

    run = store.create_run(lib.rid, "answer", {}, None)
    step = store.step(run["id"], "r3:answer", "model:grounded_answer")
    iid = input_for(run, step, "grounded_answer")
    answer_id = store.save_answer(lib.rid, run["id"], step["id"], iid, 1, "structurally_valid",
        {"title": "SYNTHETIC answer", "answer_language": "en", "claims": [{"claim_label": "c1", "section": "Methods",
         "text": "SYNTHETIC recorded claim.", "support_type": "source_stated"}]}, {},
        [{"claim_label": "c1", "passage_id": pid, "source_id": lib.svid, "anchor_text": quote, "anchor_match": "exact"}])
    tables = TableStore(store)
    table_id = tables.create_table(lib.rid, "SYNTHETIC R3", None, None, None)
    column_id = tables.add_column(lib.rid, table_id, COLUMN, 1, None)
    revision = tables.save_model_output(lib.rid, table_id, column_id, lib.svid, column_revision=1,
        state="value", value={"text": "SYNTHETIC method"}, note=None, reading_depth="selected_sections",
        output_status="structurally_valid", links=[{"passage_id": pid, "source_version_id": lib.svid,
         "anchor_text": quote, "anchor_match": "exact"}], run_id=run["id"], step_id=step["id"], step_input_id=iid,
        model_connection="fake", resolved_model="fake", scope_revision=1, cell_version_at_request=0, recheck=False)
    cell_id = store.conn.execute("SELECT cell_id FROM cell_revisions WHERE id = ?", (revision,)).fetchone()[0]
    store.update_run(run["id"], status="completed")
    reports = ReportStore(store)
    run = store.create_run(lib.rid, "report", {}, None)
    report_id = reports.create_report(lib.rid, run["id"], 1, "en")
    frozen = reports.save_snapshot(report_id, table_id)
    reports.set_plan(report_id, {"glossary": [], "corpus": frozen["corpus"], "section_budgets": {
        "III": {"min_words": 0, "max_words": 100, "max_claims": 40}},
        "limitations_column_id": column_id, "future_work_column_id": column_id})
    step = store.step(run["id"], "r3:report", "model:report_section")
    iid = input_for(run, step, "report_section")
    section_id = reports.create_section(report_id, "III", 3)
    reports.save_section_draft(section_id, step["id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 10)
    claims = [_claim("III.1", "SYNTHETIC effective claim.", "source_stated"),
              _claim("III.2", "SYNTHETIC restorable claim.", "source_stated")]
    claims[0]["equation_origin"] = {"passage_id": pid}
    reports.save_claims(section_id, claims, [{"claim_key": c["claim_key"], "passage_id": pid,
        "source_version_id": lib.svid, "step_input_id": iid, "anchor_text": quote, "anchor_match": "exact"} for c in claims])
    gap_id = db.new_id("rga")
    store.conn.execute("INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json, created_at)"
        " VALUES (?, ?, 'G1', 'stated_limitation', 'SYNTHETIC gap', ?, '{}', ?)",
        (gap_id, report_id, json.dumps({"basis_passage_ids": [pid], "basis_claim_keys": []}), db.now()))
    store.update_run(run["id"], status="completed")
    reports.finalize(report_id, "valid")
    claim = store.conn.execute("SELECT * FROM report_claims WHERE report_section_id = ? AND claim_key = 'III.2'", (section_id,)).fetchone()
    reports.edit_claim(lib.rid, report_id, claim["id"], text="SYNTHETIC restorable edited claim.", restore_from=None,
                       note=None, expected_version=1, idempotency_key=None, link_ids=[])
    reader = ReviewReader(store, reports)
    review_store = ReviewStore(store.conn, reader)
    mapping = {"store": store, "conn": store.conn, "rid": lib.rid, "source_id": lib.svid, "section_passage": pid,
        "answer_id": answer_id, "report_id": report_id, "reports": reports, "reader": reader, "reviews": review_store,
        "report_input_id": iid, "report_step_id": step["id"], "cell_id": cell_id}
    snapshots = []
    if reviews:
        for kind in ("answer", "report"):
            content, markers = build_snapshot(reader, lib.rid, kind, mapping[kind + "_id"])
            sid = review_store.add_snapshot(content, markers)
            saved = review_store.snapshot(sid)
            run_id = review_run(mapping)
            review = review_store.create_review(lib.rid, sid, run_id, focus="source_support", requested_connection="fake")
            payload = step_payload(mapping, saved, run_id)
            fid = review_store.add_findings(review["id"], [resolve_finding(content, payload, finding(payload))])[0]
            review_store.add_decision(fid, "deferred", "SYNTHETIC review decision")
            snapshots.append(saved)
    lib.rich = mapping
    lib.pid, lib.answer_id, lib.report_id, lib.gap_id = pid, answer_id, report_id, gap_id
    lib.snapshots = snapshots
    return lib


@contextmanager
def verified_child(lib, mode, *, parked=False):
    """Kill or park an actual attachment/CLI upgrade in its private-copy parser."""
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "backend") + os.pathsep + str(root),
               DEIXIS_DATA_DIR=str(lib.settings.data_dir))
    process = subprocess.Popen([sys.executable, "-c",
        "from tests.reextract_r3_helpers import verified_child_main; verified_child_main()",
        mode, lib.svid, str(parked)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 30)
        assert ready, "R3 verified-read child did not reach its parser"
        line = process.stdout.readline().strip()
        assert line == "private-parser", (line, process.poll())
        if not parked:
            out, err = process.communicate(timeout=30)
            assert process.returncode == 137, (out, err)
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def verified_child_main():
    from deixis.config import load_settings
    from deixis.documents import acquisition, pdf
    from deixis.workflow.store import Store
    from tests.reextract_r2c_helpers import forbid_calls

    mode, svid, parked = sys.argv[1:]
    settings = load_settings()
    conn = db.connect(settings.db_path)
    store = Store(conn)
    store.recovery_dir = settings.recovery_dir
    forbid_calls(pytest.MonkeyPatch(), parser=False)
    real = pdf.extract_pdf

    def parser(path):
        assert path.parent == settings.recovery_dir / "tmp"
        print("private-parser", flush=True)
        if parked == "True":
            sys.stdin.readline()
            return real(path)
        os._exit(137)

    pdf.extract_pdf = parser
    if mode == "attachment":
        asset = dict(conn.execute("SELECT * FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone())
        destination = store.create_upload_source("SYNTHETIC killed attachment")
        data = (settings.papers_dir / asset["storage_path"]).read_bytes()
        asyncio.run(acquisition._attach_pdf(store, destination, data, settings.papers_dir, "download", None,
                                           recovery_dir=settings.recovery_dir))
    else:
        from deixis.__main__ import reextract
        reextract(settings, False)
    conn.close()
