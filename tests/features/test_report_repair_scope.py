"""What one report finding may cost the whole report, and which sub-questions the synthesis starts without (P12).

SYNTHETIC records and a fake model. Passing shows the three kinds of finding end differently and that the record of
the sub-questions without evidence is written before the sections; it says nothing about report quality.
"""

import asyncio
import json

import pytest

from deixis.workflow.features.report import report_assembly as assembly, report_coverage as coverage
from deixis.workflow.features.report.report_sections import CLAIMS_WITHOUT_BASIS, COVERAGE_KEY, run_report
from deixis.workflow.run.views import report_view
from test_report_flow import ReportAdapter, report_flow

def cell(column, source="srv_1", state="value", evidence=(("psg_1", "SYNTHETIC quote"),), depth="full_text"):
    return {"cell_id": f"cel_{column}_{source}", "column_id": column, "source_version_id": source,
            "state": state, "value": {"text": "SYNTHETIC value"}, "reading_depth": depth,
            "evidence": [{"passage_id": pid, "quote": quote} for pid, quote in evidence]}


def test_each_sub_question_is_recorded_with_what_answers_it_and_which_have_nothing():
    """A sub-question is answered for a row only by a cell that holds a value with a located quote; everything else
    is counted by what it says, and a sub-question no row answers is named."""
    snapshot = {"columns": [{"column_id": "col_aaaaaaaa", "name": "SYNTHETIC method"},
                            {"column_id": "col_bbbbbbbb", "name": "SYNTHETIC delay"}],
                "rows": [{"source_version_id": f"srv_{n}"} for n in (1, 2, 3, 4)],
                # A row whose own cells failed is not evidence, so its answered cell counts for no sub-question.
                "failed_rows": [{"source_version_id": "srv_4"}],
                "cells": [cell("col_aaaaaaaa", "srv_1"),
                          cell("col_aaaaaaaa", "srv_4"),
                          cell("col_aaaaaaaa", "srv_2", depth="abstract"),
                          # A value nobody located, a reading that looked and found nothing, and a source with no text.
                          cell("col_bbbbbbbb", "srv_1", state="not_verified", evidence=()),
                          cell("col_bbbbbbbb", "srv_2", state="not_found_in_inspected_scope", evidence=()),
                          cell("col_bbbbbbbb", "srv_3", state="inaccessible", evidence=())]}
    plan = {"axes": [{"axis_id": "AX1", "label": "SYNTHETIC method", "column_id": "col_aaaaaaaa"},
                     {"axis_id": "AX2", "label": "SYNTHETIC delay", "column_id": "col_bbbbbbbb"},
                     {"axis_id": "AX3", "label": "SYNTHETIC gone", "column_id": "col_cccccccc"}],
            "research_questions": [{"rq_id": "RQ1", "text": "SYNTHETIC"}]}
    found = coverage.coverage(snapshot, plan)
    assert found["rule"] == coverage.RULE and found["axes"] == 3
    assert found["without_evidence"] == ["AX2", "AX3"]
    first, second, third = found["sub_questions"]
    assert (first["rows"], first["rows_answered"]) == (2, 2)
    assert first["depths"] == {"abstract": 1, "full_text": 1} and first["states"] == {}
    assert second["rows_answered"] == 0 and second["states"] == {
        "not_found_in_inspected_scope": 1, "not_verified": 1, "inaccessible": 1}
    # A sub-question whose column is not in the table at all has nothing to stand on, and the record says why.
    assert third["column_missing"] and third["rows"] == 0


def test_a_value_without_a_located_quote_does_not_answer_its_sub_question():
    snapshot = {"columns": [{"column_id": "col_aaaaaaaa", "name": "SYNTHETIC method"}],
                "rows": [{"source_version_id": "srv_1"}],
                "cells": [cell("col_aaaaaaaa", "srv_1", evidence=())]}
    plan = {"axes": [{"axis_id": "AX1", "label": "SYNTHETIC method", "column_id": "col_aaaaaaaa"}]}
    found = coverage.coverage(snapshot, plan)
    assert found["without_evidence"] == ["AX1"] and found["sub_questions"][0]["rows_answered"] == 0


def test_a_finding_is_sorted_by_what_it_may_cost_the_report():
    """A warning costs nothing, a claim whose citation found no basis costs that claim, and anything else still
    refuses the report. A claim-scoped rule without a named claim is not claim-scoped: it refuses the report."""
    issues = [{"rule": "equation_text_source_warning", "section_id": "IV", "detail": "WARNING: OCR text."},
              {"rule": "anchor_not_in_passage", "section_id": "III", "detail": "ERROR: III.1 …", "claim_key": "III.1"},
              {"rule": "corpus_count_mismatch", "section_id": "IV", "detail": "ERROR: included differs."},
              {"rule": "anchor_not_in_passage", "section_id": "III", "detail": "ERROR: no claim named."}]
    scoped = assembly.repair_scope(issues)
    assert [issue["rule"] for issue in scoped["warnings"]] == ["equation_text_source_warning"]
    assert [issue["claim_key"] for issue in scoped["claims"]] == ["III.1"]
    assert [issue["rule"] for issue in scoped["blocking"]] == ["corpus_count_mismatch", "anchor_not_in_passage"]


class Hooked(ReportAdapter):
    """A fixture model that can check the run's order and change a stored passage between the sections and assembly.

    `conclusion_on` makes the conclusion, the introduction and the abstract rest on that section's claim instead of
    the first one written, so a claim that cites a passage can lose its basis without leaving the conclusion
    unfounded. `watch` is called with each section id as its call goes out.
    """

    def __init__(self, *, conclusion_on=None, watch=None):
        super().__init__()
        self.conclusion_on = conclusion_on
        self.watch = watch
        self.seen = []

    def _response(self, step_input):
        target = step_input.get("report_target") or {}
        section_id = target.get("section_id")
        if step_input["task_type"] == "report_section":
            self.seen.append(section_id)
            if self.watch:
                self.watch(section_id)
        out = super()._response(step_input)
        if self.conclusion_on and section_id in ("I", "IX", "abstract"):
            draft = json.loads(out)
            keys = [item["claim_key"] for item in target.get("prior_summaries") or []
                    if item["section_id"] == self.conclusion_on]
            if draft.get("claims") and keys:
                draft["claims"][0]["body_refs"] = keys[:1]
            return json.dumps(draft)
        return out


def run_with(tmp_path, **kwargs):
    """The report fixture's run, driven by `Hooked` instead of the plain fixture model.

    `before` records, for each section call, whether the sub-question record was already stored.
    """
    flow, store, reports, _adapter, run, scope, report_id = report_flow(tmp_path)
    before = {}

    def watch(section_id):
        before.setdefault(section_id, store.existing_step(run["id"], COVERAGE_KEY) is not None)

    hooked = Hooked(watch=watch, **kwargs)
    flow.deps.adapters["fake"] = hooked
    asyncio.run(run_report(flow, run, scope))
    return flow, store, reports, hooked, store.run(run["id"]), report_id, before


def unlocatable(monkeypatch, claim_key, section_id):
    """Stand in for a claim whose cited evidence no longer holds its quote.

    Today nothing stored can reach that state: a passage's text cannot change, a cited passage cannot be deleted
    while a link points at it, and a cell citation is checked against the report's own frozen snapshot. Both readings
    of the anchors are therefore given the same finding, so the test drives the decision this package adds (which
    claim is set aside, and whether the conclusion still stands) over real stored claims, links and body refs.
    """
    issue = {"rule": "anchor_not_in_passage", "section_id": section_id,
             "detail": f"ERROR: {claim_key} anchor is absent from passage.", "claim_key": claim_key}
    checks, anchors = assembly.run_assembly_checks, assembly._check_anchors
    monkeypatch.setattr(assembly, "run_assembly_checks",
                        lambda store, reports, report_id: checks(store, reports, report_id) + [issue])
    monkeypatch.setattr(assembly, "_check_anchors",
                        lambda store, reports, report_id, **kwargs: anchors(store, reports, report_id, **kwargs)
                        + [issue])
    return issue


def test_the_sub_questions_without_evidence_are_recorded_before_the_sections_are_written(tmp_path):
    flow, store, reports, hooked, run, report_id, before = run_with(tmp_path)
    step = store.existing_step(run["id"], COVERAGE_KEY)
    assert step["status"] == "succeeded"
    record = step["output"]
    assert record["rule"] == coverage.RULE and record["without_evidence"] == []
    assert [axis["axis_id"] for axis in record["sub_questions"]] == ["AX1"]
    assert record["sub_questions"][0]["rows_answered"] == 1
    assert record["research_questions"] == ["RQ1", "RQ2"]
    # It was stored before any section was written, not after the sections it is meant to be read against.
    assert before and all(before.values()), before
    assert hooked.seen[0] in ("III", "IV", "V")
    assert reports.report(report_id)["status"] == "valid"
    del flow


def test_a_claim_whose_quote_is_no_longer_there_is_delivered_with_its_uncertainty_reported(tmp_path, monkeypatch):
    """The claim's citation is read again; it still has no located basis, so the claim is delivered saying so and
    the rest of the report stands, because the conclusion rests on another claim that has one."""
    unlocatable(monkeypatch, "III.1", "III")
    flow, store, reports, _hooked, run, report_id, _before = run_with(tmp_path, conclusion_on="V")
    assert reports.report(report_id)["status"] == "valid"
    assert run["error"] and [issue["claim_key"] for issue in run["error"]] == ["III.1"]
    assert store.conn.execute("SELECT 1 FROM events WHERE run_id = ? AND type = ?",
                              (run["id"], CLAIMS_WITHOUT_BASIS)).fetchone()
    # The report screen reports that one claim's uncertainty, and nothing else changes for the other claims.
    view = report_view(store, run["research_id"], report_id)
    assert view["claims_without_basis"] == [{"section_id": "III", "claim_key": "III.1"}]
    cited = {claim["claim_key"]: claim for section in view["sections"] for claim in section["claims"]
             if claim["evidence"]}
    assert len(cited) > 1 and all(any(link["anchor_match"] for link in claim["evidence"])
                                 for key, claim in cited.items() if key != "III.1")
    # That one claim keeps its citation, and the screen no longer calls any of its anchors located.
    assert not any(link["anchor_match"] for link in cited["III.1"]["evidence"])
    # The conclusion rests on V's claim, which keeps its own located basis.
    assert not assembly.main_answer_missing(store, report_id, without={"III.1"})
    del flow


def test_a_report_whose_conclusion_keeps_no_located_basis_is_not_a_valid_report(tmp_path, monkeypatch):
    """The same claim without a basis, with the conclusion resting on it: the report's main question is unanswered,
    so the report is a draft and its run says why."""
    unlocatable(monkeypatch, "III.1", "III")
    flow, store, reports, _hooked, run, report_id, _before = run_with(tmp_path)
    assert reports.report(report_id)["status"] == "draft"
    rules = [issue["rule"] for issue in run["error"]]
    assert assembly.NO_MAIN_ANSWER in rules and "anchor_not_in_passage" in rules
    assert assembly.main_answer_missing(store, report_id, without={"III.1"})
    # With nothing set aside the conclusion does rest on a located basis, through the claim it names.
    assert not assembly.main_answer_missing(store, report_id)
    del flow


def test_a_claim_the_second_reading_finds_a_basis_for_keeps_it(tmp_path, monkeypatch):
    """A finding the recheck does not reproduce sets no claim aside: the report is delivered as a clean one."""
    issue = {"rule": "anchor_not_in_passage", "section_id": "III",
             "detail": "ERROR: III.1 anchor is absent from passage.", "claim_key": "III.1"}
    checks = assembly.run_assembly_checks
    monkeypatch.setattr(assembly, "run_assembly_checks",
                        lambda store, reports, report_id: checks(store, reports, report_id) + [issue])
    _flow, store, reports, _hooked, run, report_id, _before = run_with(tmp_path)
    assert reports.report(report_id)["status"] == "valid" and run["error"] is None
    assert store.conn.execute("SELECT 1 FROM events WHERE run_id = ? AND type = 'report_finalized'",
                              (run["id"],)).fetchone()
    assert report_view(store, run["research_id"], report_id)["claims_without_basis"] == []


@pytest.mark.parametrize("rule,detail,status", [
    ("equation_text_source_warning", "WARNING: SYNTHETIC OCR text.", "valid"),
    ("corpus_count_mismatch", "ERROR: SYNTHETIC included differs.", "draft"),
])
def test_a_warning_leaves_the_report_valid_and_a_report_wide_error_still_refuses_it(tmp_path, monkeypatch, rule,
                                                                                   detail, status):
    original = assembly.run_assembly_checks

    def checks(store, reports, report_id):
        return original(store, reports, report_id) + [{"rule": rule, "section_id": "IV", "detail": detail}]

    monkeypatch.setattr(assembly, "run_assembly_checks", checks)
    _flow, store, reports, _hooked, run, report_id, _before = run_with(tmp_path)
    assert reports.report(report_id)["status"] == status
    assert store.conn.execute(
        "SELECT 1 FROM events WHERE run_id = ? AND type = ?",
        (run["id"], "report_assembly_failed" if status == "draft" else "report_finalized")).fetchone()


def test_two_claims_that_name_each_other_are_supported_through_what_one_of_them_reaches(tmp_path):
    """Support is spread over the body refs until nothing more can be reached, so a claim in a cycle is supported
    when any claim of that cycle reaches a located citation, whatever order the claims are read in."""
    _flow, store, _reports, _hooked, run, report_id, _before = run_with(tmp_path, conclusion_on="V")
    ids = {row["claim_key"]: row["id"] for row in store.conn.execute(
        "SELECT c.id, c.claim_key FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ?", (report_id,))}
    # The introduction and the conclusion now name each other; only the conclusion also names V's cited claim.
    store.conn.execute("DELETE FROM report_claim_refs WHERE claim_id = ?", (ids["I.1"],))
    store.conn.execute("INSERT INTO report_claim_refs (claim_id, ref_kind, ref_value) VALUES (?, ?, ?)",
                       (ids["I.1"], "body_ref", "IX.1"))
    supported = assembly.located_claims(store, report_id)
    assert {"I.1", "IX.1", "V.1"} <= supported
    # Set V's claim aside and the cycle has nothing left to stand on.
    without = assembly.located_claims(store, report_id, without={"V.1"})
    assert not {"I.1", "IX.1", "V.1"} & without
