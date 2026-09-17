"""Synthetic, code-written Review Methodology section coverage."""

import json

import pytest

from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.report.review_methodology import write_review_methodology
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    reports = ReportStore(store)
    research_id = store.create_research(
        "Which methods were studied?", "academic", "quick", ["openalex"], "fake", "fake-screening", "en"
    )
    discovery = store.create_run(research_id, "discovery", {"max_model_calls": 4}, None)
    plan = store.step(discovery["id"], "search_plan", "model:search_plan")
    store.finish_step(plan["id"], "succeeded", output={
        "query_compiler": "deixis.query_compiler.v2",
        "queries": [{"provider_id": "openalex", "query_text": "synthetic methods"}],
    })
    search = store.step(discovery["id"], "search:0", "provider_search:openalex")
    store.finish_step(search["id"], "succeeded", output={"status": "completed", "result_count": 7})
    store.add_search_run(
        research_id=research_id, run_id=discovery["id"], step_id=search["id"], scope_revision=1,
        provider="openalex", query_text="synthetic methods", request_description="synthetic request",
        access_mode="keyless", status="completed", delivery_class=None, result_count=7, provider_total=7,
        page_limit=25, error_json=None, raw_payload_path=None,
    )
    screening = store.step(discovery["id"], "screening", "model:screening")
    step_input_id = new_id("sti")
    store.insert_step_input(
        screening["id"], research_id, discovery["id"], 0,
        {"step_input_id": step_input_id, "task_type": "screening", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic", "capabilities": {"supported_tasks": ["screening"]},
         "budget": {"max_model_calls": 4},
         "model": {"connection": "fake", "requested_model": "fake-screening"}},
        "base", "developer", "message", {},
    )
    store.finish_step(screening["id"], "succeeded", output={"result": {"decisions": []}})
    store.update_run(discovery["id"], status="completed")

    acquisition = store.create_run(research_id, "answer", {}, None)
    store.finish_step(store.step(acquisition["id"], "fetch:a", "fetch_pdf")["id"], "succeeded")
    store.finish_step(store.step(acquisition["id"], "other:a", "pdf_other_copy")["id"], "failed")
    store.update_run(acquisition["id"], status="completed")
    report_run = store.create_run(research_id, "report", {}, None)
    report_id = reports.create_report(research_id, report_run["id"], 1, "en")
    yield store, reports, report_id, research_id
    conn.close()


def test_review_methodology_reports_corpus_counts_and_provider_dates_without_a_model_call(lib):
    store, reports, report_id, research_id = lib
    snapshot = {"corpus": {"found": 17, "unique": 11, "screened": 9, "included": 4, "full_text": 2}}

    write_review_methodology(store, reports, report_id, research_id, snapshot)

    section = reports.section(report_id, "II")
    assert section["status"] == "valid" and section["step_id"] is None
    assert str(snapshot["corpus"]["found"]) in section["draft"]["text"]
    assert "synthetic methods" in section["draft"]["text"]
    assert "deixis.query_compiler.v2" in section["draft"]["text"]
    assert json.loads(store.conn.execute(
        "SELECT usage_json FROM runs WHERE id = (SELECT run_id FROM reports WHERE id = ?)", (report_id,)
    ).fetchone()[0]).get("model_calls", 0) == 0
