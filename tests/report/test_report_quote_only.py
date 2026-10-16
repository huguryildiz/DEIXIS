"""SYNTHETIC checks of D58: report sections receive every table cell with its quotes before any page text, and the
report review reads cell quotes in batches. Passing shows workflow behavior, not report or review quality."""

import asyncio
import json

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.storage.db import dumps, new_id
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.report import review
from deixis.workflow.report import sections as report_sections
from deixis.workflow.report.sections import run_report
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from deixis.models.adapter import ModelStepResult
from fakes import scripted_report_review
from test_report_flow import (CELL_QUOTE, COLUMN, FUTURE_WORK_COLUMN, LIMITATIONS_COLUMN, PASSAGE, ReportAdapter,
                              _add_pdf, report_flow)

with open("tests/fixtures/research/step-inputs.json", encoding="utf-8") as source:
    STEP_INPUTS = json.load(source)
with open("tests/fixtures/research/fake-outputs.json", encoding="utf-8") as source:
    SECTION_OUTPUT = next(case["output"] for case in json.load(source)["cases"] if case["name"] == "report_section_valid")
QUOTE_ONLY = "psg_SYNQUOTEONLY01"


def _quote_only_input():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    si["report_target"]["cells"] = [{
        "cell_id": "cel_SYNQUOTE0001", "cell_revision_id": "crv_SYNQUOTE0001", "column_id": "col_SYNTHR0001",
        "source_version_id": si["passages"][0]["source_id"], "state": "value",
        "value": {"text": "SYNTHETIC rate $x^2$"}, "reading_depth": "full_text",
        "evidence": [{"passage_id": QUOTE_ONLY, "quote": "SYNTHETIC stored quote states the rate $x^2$"}]}]
    si["allowlist"]["cell_ids"] = ["cel_SYNQUOTE0001"]
    si["allowlist"]["cell_evidence_passage_ids"] = [QUOTE_ONLY]
    return si


def _cell_draft():
    draft = json.loads(json.dumps(SECTION_OUTPUT))
    draft["claims"][0] |= {"passage_ids": [], "cell_ids": ["cel_SYNQUOTE0001"]}
    draft["citation_anchors"] = [{"claim_key": "IV.1", "passage_id": None, "cell_id": "cel_SYNQUOTE0001",
                                  "quote": "stored quote states the rate"}]
    return draft


def test_a_section_input_may_hold_quote_only_cells_whose_page_is_listed_not_supplied():
    si = _quote_only_input()
    assert QUOTE_ONLY not in si["allowlist"]["passage_ids"]
    assert contracts.check_step_input(si) == []
    assert contracts.check_step_input(contracts.with_citation_handles(si)) == []

    unlisted = json.loads(json.dumps(si))
    del unlisted["allowlist"]["cell_evidence_passage_ids"]
    assert [issue.code for issue in contracts.check_step_input(unlisted)] == ["report_cell_passage_not_allowed"]
    foreign = json.loads(json.dumps(si))
    foreign["allowlist"]["cell_evidence_passage_ids"].append("psg_SYNNOTACELL01")
    assert [issue.code for issue in contracts.check_step_input(foreign)] == ["allowlist_without_record"]


def test_quote_only_page_ids_are_shown_as_handles_and_resolve_to_unknown_passages():
    si = _quote_only_input()
    shown = contracts.with_citation_handles(si)
    handle = contracts.report_citation_handles(si)[QUOTE_ONLY]
    assert QUOTE_ONLY not in json.dumps(shown)
    assert shown["allowlist"]["cell_evidence_passage_ids"] == [handle]
    assert shown["report_target"]["cells"][0]["evidence"][0]["passage_id"] == handle
    assert handle not in shown["allowlist"]["passage_ids"]


def test_a_quote_only_cell_is_cited_by_its_quote_and_its_page_cannot_be_cited():
    si = _quote_only_input()
    assert contracts.validate_model_output(si, _cell_draft()).ok

    draft = _cell_draft()
    draft["claims"][0]["passage_ids"] = [QUOTE_ONLY]
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": QUOTE_ONLY, "cell_id": None,
                                      "quote": "stored quote states the rate"})
    codes = contracts.validate_model_output(si, draft).codes()
    assert "unknown_passage_id" in codes


def test_an_equation_claim_resting_only_on_a_quote_only_cell_is_rejected():
    si = _quote_only_input()
    draft = _cell_draft()
    draft["claims"][0] |= {"text": "It has been reported that the rate is $$x^2$$.",
                           "equation_origin": {"passage_id": QUOTE_ONLY, "text_source": "text_layer"}}
    codes = contracts.validate_model_output(si, draft).codes()
    assert "equation_origin_not_in_input" in codes and "unknown_passage_id" in codes


class WideAdapter(ReportAdapter):
    """VI names every limitation cell as the basis of one stated limitation, so VII receives 31 basis cells."""

    def _response(self, step_input):
        output = json.loads(super()._response(step_input))
        if step_input["task_type"] == "report_section" and step_input["report_target"]["section_id"] == "VI":
            output["gaps"][0]["basis_cell_ids"] = [cell["cell_id"] for cell in step_input["report_target"]["cells"]]
        return json.dumps(output)


def wide_report_flow(tmp_path, rows=31, page_chars=10000):
    """SYNTHETIC rows x 3 table whose every cell cites its row's one long PDF page."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research("How are SYNTHETIC molecular communication systems optimized?",
                                        "attached", "quick", [], "fake", "fake-model", "en")
    pages = []
    for row in range(rows):
        source_id = store.create_upload_source(f"SYNTHETIC molecular communication study {row}")
        _add_pdf(store, source_id, [(PASSAGE + f" SYNTHETIC row {row} filler.").ljust(page_chars, "x")])
        store.add_to_corpus(research_id, source_id, "user_upload", selection_state="included", selection_origin="user")
        pages.append((source_id, store.passages_for(source_id)[0]["id"]))
    tables = TableStore(store)
    table_id = tables.create_table(research_id, "SYNTHETIC evidence", None, None, None)
    column_ids = [tables.add_column(research_id, table_id, column, version, None)
                  for version, column in enumerate((COLUMN, LIMITATIONS_COLUMN, FUTURE_WORK_COLUMN), 1)]
    fill_run = store.create_run(research_id, "answer", {}, None)
    step = store.step(fill_run["id"], "synthetic:cell", "model:cell_extraction")
    step_input_id = new_id("sti")
    store.insert_step_input(step["id"], research_id, fill_run["id"], 0,
                            {"step_input_id": step_input_id, "task_type": "cell_extraction", "scope_revision": 1,
                             "skill_package_hash": "sha256:synthetic"}, "base", "developer", "message", {})
    for row, (source_id, passage_id) in enumerate(pages):
        for column_id in column_ids:
            tables.save_model_output(
                research_id, table_id, column_id, source_id, column_revision=1, state="value",
                value={"text": f"SYNTHETIC bounded formulation {row}"}, note=None, reading_depth="full_text",
                output_status="structurally_valid",
                links=[{"passage_id": passage_id, "source_version_id": source_id, "anchor_text": CELL_QUOTE,
                        "anchor_match": "exact"}],
                run_id=fill_run["id"], step_id=step["id"], step_input_id=step_input_id, model_connection="fake",
                resolved_model="fake-model", scope_revision=1, cell_version_at_request=0, recheck=False)
    store.update_run(fill_run["id"], status="completed")
    run = store.create_run(research_id, "report", {"max_model_calls": 100, "max_provider_requests": 0}, None,
                           {"table_id": table_id})
    reports = ReportStore(store)
    report_id = reports.create_report(research_id, run["id"], 1, "en")
    store.update_run(run["id"], status="running", target_json=dumps({"table_id": table_id, "report_id": report_id}))
    adapter = WideAdapter()
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8765), store, {"fake": adapter},
                                 skill.load_skill_package(), None, limiter=ModelCallLimiter(3)))
    return flow, store, reports, adapter, store.run(run["id"]), store.scope(research_id), report_id


def test_a_31_row_table_reaches_iv_whole_and_vii_validates_over_31_long_basis_pages(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = wide_report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))

    calls = {call["report_target"]["section_id"]: call for call in adapter.calls if call["task_type"] == "report_section"}
    iv = store.step_input_payload(calls["IV"]["step_input_id"])
    assert len(iv["report_target"]["cells"]) == 93
    assert len({cell["source_version_id"] for cell in iv["report_target"]["cells"]}) == 31
    assert iv["allowlist"]["cell_evidence_passage_ids"]
    assert contracts.check_step_input(iv) == []
    # The basis cells' pages total more than the 262,144-character context limit; VII is sent with their quotes.
    vii = store.step_input_payload(calls["VII"]["step_input_id"])["report_target"]["validation_context"]
    assert len(vii["basis_cells"]) == 31 and vii["basis_passages"] == []
    basis_pages = {e["passage_id"] for cell in vii["basis_cells"] for e in cell["evidence"]}
    assert sum(len(store.passage(pid)["text"]) for pid in basis_pages) > 262144
    assert {reports.section(report_id, sid)["status"] for sid in ("IV", "V", "VI", "VII")} == {"valid"}
    assert reports.report(report_id)["status"] == "valid"
    assert "IV" in reports.report(report_id)["review"]["sections_reviewed"]


def _review_ready(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    async def skip_review(*_):
        pass

    monkeypatch.setattr(report_sections, "run_report_review", skip_review)
    asyncio.run(run_report(flow, run, scope))
    monkeypatch.setattr(report_sections, "run_report_review", review.run_report_review)
    return flow, store, reports, adapter, run, scope, report_id


def _inflate(store, reports, report_id, section_id, claims, chars):
    """Replace a section's claims by `claims` copies of its first claim, each with a `chars`-long SYNTHETIC text."""
    section = reports.section(report_id, section_id)
    first = dict(store.conn.execute("SELECT * FROM report_claims WHERE report_section_id = ? ORDER BY ordinal",
                                    (section["id"],)).fetchone())
    links = [dict(row) for row in store.conn.execute("SELECT * FROM report_citation_links WHERE claim_id = ?",
                                                     (first["id"],))]
    for n in range(1, claims):
        claim_id = new_id("rcl")
        store.conn.execute("INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text,"
                           " support_type) VALUES (?, ?, ?, ?, 1, '', ?)",
                           (claim_id, section["id"], f"{section_id}.{n + 1}", first["ordinal"] + n, first["support_type"]))
        for link in links:
            store.conn.execute("INSERT INTO report_citation_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (new_id("rcn"), claim_id, link["passage_id"], link["cell_id"], link["source_version_id"],
                                link["step_input_id"], link["anchor_text"], link["anchor_match"]))
    store.conn.execute("UPDATE report_claims SET text = ? WHERE report_section_id = ?",
                       ("SYNTHETIC " + "w" * chars, section["id"]))


def _review_calls(adapter):
    return [call for call in adapter.calls if call["task_type"] == "report_review"]


def test_cell_cited_claims_are_reviewed_with_the_cells_quotes_not_their_pages(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    (target, passages), = review._input(flow, reports, report_id)[0]
    cell_pages = {e["passage_id"] for cell in target["cells"] for e in cell["evidence"]}
    passage_cited = {c["passage_id"] for s in target["review_sections"] for claim in s["claims"]
                     for c in claim["citations"] if c["passage_id"]}
    assert target["cells"] and all(e["quote"] for cell in target["cells"] for e in cell["evidence"])
    assert {row["id"] for row in passages} == passage_cited
    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))
    payload = store.step_input_payload(reports.report(report_id)["review"]["step_input_id"])
    assert set(payload["allowlist"].get("cell_evidence_passage_ids", [])) == cell_pages - passage_cited
    assert contracts.check_step_input(payload) == []


def test_sections_over_the_review_budget_together_go_to_a_second_batch_and_iv_is_reviewed(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    _inflate(store, reports, report_id, "abstract", 2, 16000)  # about 8k tokens before IV
    _inflate(store, reports, report_id, "IV", 5, 20000)  # about 25k tokens

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    scopes = [call["report_target"]["review_scope"] for call in _review_calls(adapter)]
    assert len(scopes) == 2 and "abstract" in scopes[0] and scopes[1][0] == "IV"
    assert "IV" in saved["sections_reviewed"] and not saved["sections_not_reviewed"]
    assert saved["step_input_ids"] == [call["step_input_id"] for call in _review_calls(adapter)]
    assert store.step(run["id"], "report_review:1", "model:report_review")["status"] == "succeeded"


def test_a_section_larger_than_one_batch_is_split_by_claims(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    _inflate(store, reports, report_id, "IV", 9, 20000)  # about 45k tokens

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    parts = [[claim["claim_key"] for section in call["report_target"]["review_sections"] if section["section_id"] == "IV"
              for claim in section["claims"]] for call in _review_calls(adapter)]
    assert len([part for part in parts if part]) == 2
    assert [key for part in parts for key in part] == [f"IV.{n}" for n in range(1, 10)]
    assert "IV" in saved["sections_reviewed"] and saved["sections_reviewed"].count("IV") == 1
    assert not any(item["reason"] == "input_too_large" for item in saved["sections_not_reviewed"])


def test_only_a_single_claim_larger_than_one_batch_leaves_its_section_out(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    _inflate(store, reports, report_id, "IV", 1, 130000)

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    assert {"section_id": "IV", "reason": "input_too_large"} in saved["sections_not_reviewed"]
    assert "IV" not in saved["sections_reviewed"] and saved["sections_reviewed"]


def test_an_invalid_batch_marks_only_its_sections_and_keeps_the_other_batch_findings(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    _inflate(store, reports, report_id, "abstract", 2, 16000)
    _inflate(store, reports, report_id, "IV", 5, 20000)
    findings = scripted_report_review(adapter.responder, lambda si: [{
        "claim_key": si["report_target"]["review_sections"][0]["claims"][0]["claim_key"], "code": "other",
        "text": "SYNTHETIC flag"}])
    adapter.responder = lambda si: (json.dumps({"SYNTHETIC_broken": True})
                                    if si["task_type"] == "report_review" and "IV" in si["report_target"]["review_scope"]
                                    else findings(si))

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    second = _review_calls(adapter)[-1]["report_target"]["review_scope"]
    assert saved["status"] == "reviewed"
    assert [finding["claim_key"] for finding in saved["findings"]] == ["abstract.1"]
    assert {item["section_id"] for item in saved["sections_not_reviewed"]} == set(second)
    assert {item["reason"] for item in saved["sections_not_reviewed"]} == {"invalid_model_output"}
    assert "abstract" in saved["sections_reviewed"] and not set(second) & set(saved["sections_reviewed"])


def test_a_stored_single_step_review_replays_unchanged(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    first = reports.report(report_id)["review"]
    # A review stored before D58 has no batch count; its one step replays as the whole review.
    store.conn.execute("UPDATE run_steps SET output_json = json_remove(output_json, '$.batch_count')"
                       " WHERE run_id = ? AND operation_key = 'report_review'", (run["id"],))
    store.conn.execute("UPDATE reports SET review_json = NULL WHERE id = ?", (report_id,))

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    assert reports.report(report_id)["review"] == first
    assert len(_review_calls(adapter)) == 1


def test_a_resumed_review_sends_its_stored_batches_and_loses_no_section(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 200)
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    original = store.complete_model_step

    def interrupt_after_batch_zero(session_id, session_fields, step_id, status, **fields):
        original(session_id, session_fields, step_id, status, **fields)
        if step_id == store.step(run["id"], "report_review", "model:report_review")["id"] and status == "succeeded":
            raise RuntimeError("SYNTHETIC interruption after batch 0")

    monkeypatch.setattr(store, "complete_model_step", interrupt_after_batch_zero)
    try:
        asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))
    except RuntimeError:
        pass
    monkeypatch.setattr(store, "complete_model_step", original)
    plan = store.step(run["id"], review.PLAN_KEY, review.PLAN_KIND)["output"]
    assert len(plan["batches"]) > 2
    moved = plan["batches"][1][0]["section_id"]
    # Claims change before the resume: a later batch's section loses its claims, and the budget would now pack anew.
    store.conn.execute("UPDATE report_claims SET report_section_id = ? WHERE report_section_id = ?",
                       (reports.section(report_id, "II")["id"], reports.section(report_id, moved)["id"]))
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 30000)

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    sent = [call["report_target"]["review_scope"] for call in _review_calls(adapter)]
    planned = [[part["section_id"] for part in batch] for batch in plan["batches"]]
    assert sent == [scope_ids for scope_ids in planned if scope_ids != [moved]]
    covered = saved["sections_reviewed"] + [item["section_id"] for item in saved["sections_not_reviewed"]]
    assert sorted(covered) == sorted(s["section_id"] for s in reports.sections(report_id) if s["section_id"] != "II")
    assert {"section_id": moved, "reason": "no_claims"} in saved["sections_not_reviewed"]


def _two_batches_and_an_oversized_section(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _review_ready(tmp_path, monkeypatch)
    _inflate(store, reports, report_id, "abstract", 2, 16000)
    _inflate(store, reports, report_id, "IV", 5, 20000)
    _inflate(store, reports, report_id, "V", 1, 130000)
    return flow, store, reports, adapter, run, scope, report_id


def test_when_every_batch_fails_each_section_keeps_its_own_reason(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _two_batches_and_an_oversized_section(tmp_path, monkeypatch)
    ordinary = adapter.responder
    adapter.responder = lambda si: (json.dumps({"SYNTHETIC_broken": True}) if si["task_type"] == "report_review"
                                    else ordinary(si))
    adapter.fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC unavailable", delivery_class="before_send")
                               if si["task_type"] == "report_review" and "IV" in si["report_target"]["review_scope"]
                               else None)

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    reasons = {item["section_id"]: item["reason"] for item in saved["sections_not_reviewed"]}
    first, second = (store.step_input_payload(review._step_input_id(flow, run["id"], key))["report_target"]["review_scope"]
                     for key in ("report_review", "report_review:1"))
    assert saved["status"] == "not_reviewed" and saved["reason"] == "invalid_model_output"
    assert reasons["V"] == "input_too_large"
    assert {reasons[section_id] for section_id in first} == {"invalid_model_output"}
    assert {reasons[section_id] for section_id in second} == {"model_call_failed"}
    assert len(saved["sections_not_reviewed"]) == len(reasons)
    inputs = [review._step_input_id(flow, run["id"], key) for key in ("report_review", "report_review:1")]
    assert saved["step_input_id"] == inputs[0] and saved["step_input_ids"] == [i for i in inputs if i is not None]


def test_a_failed_first_batch_still_names_its_input_and_every_batch_input_is_listed(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = _two_batches_and_an_oversized_section(tmp_path, monkeypatch)
    ordinary = adapter.responder
    adapter.responder = lambda si: (json.dumps({"SYNTHETIC_broken": True})
                                    if si["task_type"] == "report_review" and "abstract" in si["report_target"]["review_scope"]
                                    else ordinary(si))

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    first, second = (review._step_input_id(flow, run["id"], key) for key in ("report_review", "report_review:1"))
    assert saved["status"] == "reviewed"
    assert saved["step_input_id"] == first and saved["step_input_ids"] == [first, second]
    assert "IV" in saved["sections_reviewed"] and "abstract" not in saved["sections_reviewed"]


def test_vii_loads_gap_named_pages_up_to_the_cap_and_names_the_rest_by_id(tmp_path, monkeypatch):
    flow, store, reports, _, run, _, report_id = report_flow(tmp_path, passage_kind="pdf_page")
    source_id = store.included_sources(run["research_id"])[0]
    page_ids = [page["id"] for page in store.passages_for(source_id)]
    snapshot = reports.save_snapshot(report_id, run["target"]["table_id"])
    reports.save_gaps(report_id, [{"gap_id": "gap1", "kind": "stated_limitation", "text": "SYNTHETIC limitation.",
                                   "basis_claim_keys": [], "basis_passage_ids": page_ids, "basis_cell_ids": [],
                                   "provenance": {"origin": "model", "section_id": "VI", "step_input_id": None}}])
    whole = report_sections._validation_context(flow, report_id, snapshot, "VII")["basis_passages"]
    sizes = [len(json.dumps(page, ensure_ascii=False, sort_keys=True)) for page in whole]
    assert [page["passage_id"] for page in whole] == sorted(page_ids)

    monkeypatch.setattr(report_sections, "MAX_BASIS_PASSAGE_CHARS", sum(sizes))
    assert report_sections._validation_context(flow, report_id, snapshot, "VII")["basis_passages"] == whole
    monkeypatch.setattr(report_sections, "MAX_BASIS_PASSAGE_CHARS", sum(sizes) - 1)
    context = report_sections._validation_context(flow, report_id, snapshot, "VII")
    assert context["basis_passages"] == whole[:1]
    assert context["accepted_gaps"][0]["basis_passage_ids"] == page_ids
