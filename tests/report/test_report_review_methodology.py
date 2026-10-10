"""Synthetic, code-written Review Methodology section coverage."""

import json

import pytest

from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.report.review_methodology import limitations_core, render_limitations, write_review_methodology
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
    # No fast-path step records the compiled query version this sentence names (slice 3b).
    assert "the compiled query version was not recorded" in section["draft"]["text"]
    numbers = section["validation"]["numbers"]
    assert numbers["corpus"] == snapshot["corpus"]
    assert (numbers["fetch_pdf"], numbers["pdf_other_copy"], numbers["full_text_ratio"]) == (1, 1, 0.5)
    assert "17 found, 11 unique, 9 screened, and 4 included" in section["draft"]["text"]
    assert json.loads(store.conn.execute(
        "SELECT usage_json FROM runs WHERE id = (SELECT run_id FROM reports WHERE id = ?)", (report_id,)
    ).fetchone()[0]).get("model_calls", 0) == 0


@pytest.mark.parametrize("language", ["en", "tr"])
def test_limitations_core_counts_saved_valid_claims_latest_repairs_and_distinct_truncation(lib, language):
    store, reports, report_id, _ = lib
    store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report_id))
    third = reports.create_section(report_id, "III", 3)
    fourth = reports.create_section(report_id, "IV", 4)
    reports.save_section_draft(third, None, "valid", {"claims": []}, {"truncated": [
        {"source_version_id": "srv_SYNTH0001", "record_kind": "passage"},
        {"source_version_id": "srv_SYNTH0001", "record_kind": "cell_missing_evidence"},
    ]}, 1)
    reports.save_section_draft(fourth, None, "draft", {"claims": []}, {"truncated": [
        {"source_version_id": "srv_SYNTH0001", "record_kind": "cell"},
    ]}, 1)
    claim = {"claim_key": "III.1", "text": "SYNTHETIC inference.", "support_type": "analyst_inference",
             "passage_ids": [], "cell_ids": [], "paragraph": 1, "table_ref": None, "equation_ref": None,
             "body_refs": [], "axis_id": None, "count": None, "equation_origin": None, "gap_refs": []}
    reports.save_claims(third, [claim], [])
    reports.save_claims(fourth, [claim | {"claim_key": "IV.1", "support_type": "source_stated"}], [])
    reports.save_phrase_repair(report_id, "III", "III.1#1", "before", "after", "kept")
    reports.save_phrase_repair(report_id, "III", "III.1#1", "before", "after", "reverted_exception")
    reports.save_phrase_repair(report_id, "IV", "IV.1#1", "before", "after", "unframed_exception")

    numbers = limitations_core(store, reports, report_id, {"corpus": {
        "found": 8, "unique": 6, "screened": 5, "included": 4, "full_text": 2}})

    assert numbers["no_full_text_share"] == 0.5
    assert numbers["analyst_inference_share"] == {"analyst_inference": 1, "total": 1, "share": 1.0}
    assert numbers["phrase_repair_exceptions"] == {
        "repaired": 0, "reverted_exception": 1, "unframed_exception": 1}
    assert numbers["truncation"] == {"budget_cut": 2, "missing_evidence": 1, "by_section": {
        "III": {"passage": 1, "cell": 0, "cell_missing_evidence": 1},
        "IV": {"passage": 0, "cell": 1, "cell_missing_evidence": 0}}}
    assert numbers["recall_measurement"] is None
    assert numbers["kill_search_status"] == "not_run"
    assert [item["number"] for item in numbers["items"]] == list(range(1, 8))
    rendered = render_limitations(numbers, language)
    assert all(item["text"] in rendered for item in numbers["items"])
    assert "2" in rendered and "1" in rendered and "50.0%" in rendered


SNAPSHOT = {"corpus": {"found": 17, "unique": 11, "screened": 9, "included": 4, "full_text": 2}}


def chain_steps(store, research_id, *, summary=True):
    """A SYNTHETIC fast chain on the fixture's discovery run: three semantic seeds, one the ranking added, and the
    summary `fast_chain.Round.summary` writes."""
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery'", (research_id,)).fetchone()[0]
    for key, seeds in (("fast_chain:seeds", 3), ("fast_chain:seeds_fallback", 1)):
        store.finish_step(store.step(run_id, key, "code:fast_chain")["id"], "succeeded",
                          output={"seeds": [{"source_version_id": f"sv{i}", "references": ["W1", "W2"]} for i in range(seeds)]})
    if summary:
        store.finish_step(store.step(run_id, "fast_chain:summary", "code:fast_chain")["id"], "succeeded", output={
            "sent": 5, "accepted": 3, "returned": 40, "raw_returned": 44, "admitted_returned": 40, "failed": 1,
            "passed_filter": 12, "late_records": 0, "unknown": 1, "unsent": {"cutoff": 2, "request_budget": 1}})


@pytest.mark.parametrize("language,sentence", [
    ("en", "Citation searching followed the references and the citing works of 4 seed works in OpenAlex: 5 requests "
           "sent (2 did not complete, 3 not sent), 12 returned records kept by the gate-term filter."),
    ("tr", "Atıf taraması 4 tohum eserin referanslarını ve onlara atıf yapan eserleri OpenAlex'te izledi: 5 istek "
           "gönderildi (2 tamamlanmadı, 3 gönderilmedi); dönen kayıtlardan 12 tanesini kapı terimi süzgeci tuttu."),
])
def test_the_method_section_reports_the_fast_chain_from_its_seed_and_summary_steps(lib, language, sentence):
    store, reports, report_id, research_id = lib
    chain_steps(store, research_id)
    store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report_id))
    write_review_methodology(store, reports, report_id, research_id, SNAPSHOT)
    assert sentence in reports.section(report_id, "II")["draft"]["text"]


def test_a_fast_chain_without_its_summary_writes_no_citation_searching_sentence(lib):
    store, reports, report_id, research_id = lib
    chain_steps(store, research_id, summary=False)
    write_review_methodology(store, reports, report_id, research_id, SNAPSHOT)
    assert "Citation searching" not in reports.section(report_id, "II")["draft"]["text"]
