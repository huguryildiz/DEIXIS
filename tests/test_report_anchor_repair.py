"""Synthetic P19 checks of repair scope, one-repair bound and unchanged model output."""

import asyncio
import copy
import json

import pytest

from deixis.domain import contracts, skill
from deixis.models import prompt
from deixis.workflow.flow import RunStopped
from deixis.workflow.report.sections import run_report
from deixis.workflow.views import report_view
from test_report_flow import report_flow, CELL_QUOTE, PASSAGE
from test_report_handles import section


OLD_HASH = "sha256:52775258f530aa6a51513488f2aea37d0b7e609ffebe23d06451fd8ef0ae81ac"
BAD_QUOTE = "SYNTHETIC missing anchor P19 nowhere in stored evidence."


def two_cells():
    si, draft = section()
    cell = si["report_target"]["cells"][0]
    cell["evidence"][0]["quote"] = CELL_QUOTE
    si["passages"][0]["text"] = PASSAGE + " SYNTHETIC second cell reports a different result."
    other = copy.deepcopy(cell)
    other["cell_id"] = "cel_SYNTHCELL0002"
    other["cell_revision_id"] = "crv_SYNTHCELL0002"
    other["evidence"][0]["quote"] = "SYNTHETIC second cell reports a different result."
    si["report_target"]["cells"].append(other)
    si["allowlist"]["cell_ids"].append(other["cell_id"])
    draft["citation_anchors"] = [
        {"claim_key": "IV.1", "passage_id": None, "cell_id": cell["cell_id"], "quote": BAD_QUOTE},
        {"claim_key": "IV.1", "passage_id": None, "cell_id": other["cell_id"], "quote": other["evidence"][0]["quote"]},
    ]
    draft["claims"][0]["cell_ids"].append(other["cell_id"])
    draft["claims"][0]["equation_origin"] = None
    return si, draft


def issues(si, draft):
    return [vars(issue) for issue in contracts.validate_model_output(si, draft).issues]


def test_context_pairs_only_the_failing_anchor_with_its_own_cell_quotes_and_citing_claim():
    si, draft = two_cells()
    before = copy.deepcopy((si, draft))
    context = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    assert context == [{"anchor_index": 0, "claim_key": "IV.1",
                        "cell_id": si["report_target"]["cells"][0]["cell_id"], "quote": BAD_QUOTE,
                        "allowed_quotes": [{"quote_number": 1, "quote": CELL_QUOTE}],
                        "claims": [{"claim_key": "IV.1", "text": draft["claims"][0]["text"],
                                    "anchors": [{"anchor_index": 0, "target": "cell", "failing": True},
                                                {"anchor_index": 1, "target": "cell", "failing": False}]}]}]
    assert si["report_target"]["cells"][1]["evidence"][0]["quote"] not in json.dumps(context)
    assert (si, draft) == before
    assert contracts.check_step_input(si) == []


@pytest.mark.parametrize("code", ["anchor_not_in_passage", "unknown_cell_id", "schema_invalid"])
def test_context_gives_no_specialised_guidance_for_other_issue_codes(code):
    si, draft = two_cells()
    assert contracts.report_section_anchor_repair_context(si, draft, [{"code": code, "path": "/citation_anchors/0/quote"}]) == []


@pytest.mark.parametrize("change", ["other_task", "unknown_cell", "missing_list", "not_dict", "bad_path", "bad_index"])
def test_context_fails_closed_when_the_task_cell_draft_or_issue_path_is_not_eligible(change):
    si, draft = two_cells()
    problem = [{"code": "anchor_not_in_cell_evidence", "path": "/citation_anchors/0/quote"}]
    if change == "other_task":
        si["task_type"] = "grounded_answer"
    elif change == "unknown_cell":
        si["allowlist"]["cell_ids"] = []
    elif change == "missing_list":
        draft["citation_anchors"] = None
    elif change == "not_dict":
        draft = "not a draft"
    elif change == "bad_path":
        problem[0]["path"] = "/claims/0/quote"
    else:
        problem[0]["path"] = "/citation_anchors/999/quote"
    assert contracts.report_section_anchor_repair_context(si, draft, problem) == []


def test_guidance_requires_visible_claim_removal_and_forbids_blind_quote_substitution():
    text = prompt.REPORT_SECTION_ANCHOR_REPAIR_GUIDANCE
    for required in ("SAME cell", "copy the quote exactly", "another cell or a whole passage is not allowed",
                     "a cell anchor is never a whole passage", "found quote does not prove",
                     "insufficient_evidence entry naming its claim_key", "why it was removed",
                     "Never swap in a quote only to pass", "outside the allowlist"):
        assert required in text


def old_repair_message(si, problem):
    return (prompt.step_message(si) + "\n\nA previous output for this StepInput failed validation with these issues. "
            "Return a corrected JSON object; do not add identifiers that are not in the allowlist.\n"
            + json.dumps(problem, ensure_ascii=False, indent=1))


@pytest.mark.parametrize("task", ["grounded_answer", "cell_extraction", "report_section"])
def test_repair_without_anchor_pairs_is_byte_for_byte_the_old_message(task):
    si, _ = two_cells()
    si["task_type"] = task
    problem = [{"code": "schema_invalid", "path": "/", "message": "SYNTHETIC format failure"}]
    assert prompt.repair_message(si, problem) == old_repair_message(si, problem)
    assert prompt.repair_message(si, problem, []) == old_repair_message(si, problem)


@pytest.mark.parametrize("fix", [False, True])
def test_section_gets_exactly_one_targeted_repair_and_keeps_both_raw_outputs_without_code_side_swap(tmp_path, fix):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = adapter.responder
    raw = []

    def response(si):
        draft = json.loads(original(si))
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            if raw:
                draft = {"schema_version": "deixis.report_section_anchor_repair.v1",
                         "step_input_id": si["step_input_id"], "scope_revision": si["scope_revision"],
                         "anchors": [{"anchor_index": 0, "quote_number": 1 if fix else 999}], "claims": []}
            else:
                draft["citation_anchors"][0]["quote"] = BAD_QUOTE
            raw.append(json.dumps(draft))
            return raw[-1]
        return json.dumps(draft)

    adapter.responder = response
    if fix:
        asyncio.run(run_report(flow, run, scope))
        assert reports.section(report_id, "IV")["status"] == "valid"
    else:
        with pytest.raises(RunStopped):
            asyncio.run(run_report(flow, run, scope))
        stopped = store.run(run["id"])
        assert stopped["status"] == "paused" and stopped["pause_reason"] == "section_failed"
        assert stopped["error"]["reasons"][0]["code"] == "anchor_not_in_cell_evidence"
        failed = reports.section(report_id, "IV")
        assert failed["status"] == "failed" and failed["draft"] is None
        assert store.conn.execute("SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?", (failed["id"],)).fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM report_citation_links l JOIN report_claims c ON c.id = l.claim_id WHERE c.report_section_id = ?", (failed["id"],)).fetchone()[0] == 0
        view = report_view(store, run["research_id"], report_id)
        assert next(s for s in view["sections"] if s["section_id"] == "IV")["validation"]["issues"][0]["code"] == "anchor_not_in_cell_evidence"
        assert "error" not in view["run"]  # A section-pause object is not an assembly list.
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert len(raw) == 2
    assert [row[0] for row in store.conn.execute("SELECT raw_output FROM model_sessions WHERE step_id = ? ORDER BY rowid", (step["id"],))] == raw
    rows = list(store.conn.execute("SELECT payload_json, user_message FROM step_inputs WHERE step_id = ? ORDER BY attempt", (step["id"],)))
    assert len(rows) == 2
    payload, message = json.loads(rows[1][0]), rows[1][1]
    assert prompt.REPORT_SECTION_ANCHOR_PATCH_GUIDANCE in message
    pairs = json.loads(message.split("Cell anchor repair pairs:\n")[1].split("\nFor each failing anchor")[0])
    assert pairs[0]["cell_id"].startswith("cel_L")
    assert pairs[0]["allowed_quotes"][0] == {"quote_number": 1, "quote": CELL_QUOTE}
    assert pairs[0]["quote"] == BAD_QUOTE
    for identifier in contracts.report_citation_handles(payload):
        assert identifier not in message


@pytest.mark.parametrize("kind,code", [("other_cell", "anchor_not_in_cell_evidence"),
                                      ("nowhere", "anchor_not_in_cell_evidence"),
                                      ("both_targets", "citation_anchor_target_count"),
                                      ("whole_passage", "anchor_not_in_cell_evidence")])
def test_existing_validator_rejects_wrong_cell_quotes_and_ambiguous_targets_after_guidance(kind, code):
    si, draft = two_cells()
    assert contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    anchor = draft["citation_anchors"][0]
    if kind == "other_cell":
        anchor["quote"] = si["report_target"]["cells"][1]["evidence"][0]["quote"]
    elif kind == "both_targets":
        anchor["quote"] = CELL_QUOTE
        anchor["passage_id"] = si["passages"][0]["passage_id"]
    elif kind == "whole_passage":
        anchor["quote"] = si["passages"][0]["text"]
    assert code in contracts.validate_model_output(si, draft).codes()
    anchor["passage_id"], anchor["quote"] = None, CELL_QUOTE
    assert contracts.validate_model_output(si, draft).ok  # A whole stored cell quote still passes.


def test_p19_method_hash_changed_and_package_integrity_passes():
    assert skill.load_skill_package().package_hash != OLD_HASH
    assert skill.integrity_issues() == []


def test_browser_fixture_bad_anchor_marker_fails_the_same_cell_check_in_both_scripted_calls():
    from acceptance.fixture_server import ScriptedCodex, MODEL
    si, _ = two_cells()
    si["question"]["text"] += " [report-bad-anchor]"
    adapter = ScriptedCodex()
    shown = contracts.with_citation_handles(si)
    message = prompt.step_message(shown)
    schema = contracts.model_output_schema("report_section")
    first_issues = None
    base_draft = None
    for attempt in range(2):
        response = asyncio.run(adapter.run_step("base", "developer", message,
                                               schema, MODEL))
        if attempt:
            patch_validation = contracts.validate_report_section_anchor_patch(si, base_draft, context, response.raw_text)
            assert "anchor_patch_quote_number" in patch_validation.codes()
            assert first_issues[0]["code"] == "anchor_not_in_cell_evidence"
            break
        draft = contracts.resolve_citation_handles(si, response.raw_text)
        validation = contracts.validate_model_output(si, draft)
        assert "anchor_not_in_cell_evidence" in validation.codes()
        cell_anchor = next(a for a in draft["citation_anchors"] if a["cell_id"] is not None)
        assert cell_anchor["quote"] == BAD_QUOTE
        context = contracts.report_section_anchor_repair_context(si, draft, [vars(i) for i in validation.issues])
        first_issues, base_draft = [vars(i) for i in validation.issues], draft
        shown_context = copy.deepcopy(context)
        for pair in shown_context:
            pair["cell_id"] = contracts.report_citation_handles(si)[pair["cell_id"]]
        message = prompt.repair_message(shown, contracts.issues_with_handles(si, first_issues), shown_context, anchor_patch=True)
        schema = contracts.report_section_anchor_patch_schema()


@pytest.mark.parametrize("task", ["grounded_answer", "cell_extraction", "report_section"])
def test_model_step_non_anchor_repairs_keep_the_old_message_byte_for_byte(tmp_path, task):
    from test_report_step_input import report_flow as step_flow, report_target
    from test_report_flow import COLUMN
    flow, store, adapter, run, scope, sid, pid = step_flow(tmp_path)
    adapter.responder = lambda si: json.dumps({"SYNTHETIC_invalid_shape": True})
    target = {"table_id": "tbl_SYNTH0001", "source_id": sid,
              "passage_scope": {"given": 1, "available": 1, "all_pages_given": False},
              "columns": [COLUMN | {"column_id": "col_SYNTH0001", "revision": 1}]}
    output = asyncio.run(flow._model_step(
        run, scope, "synthetic:" + task, task, source_ids=[sid], passage_rows=[store.passage(pid)],
        model=("fake", "fake-model", None),
        extraction_target=target if task == "cell_extraction" else None,
        report_target=report_target(sid, pid) if task == "report_section" else None,
    ))
    assert output["invalid"]
    assert len(adapter.calls) == 2
    rows = list(store.conn.execute("SELECT payload_json, user_message FROM step_inputs ORDER BY rowid"))
    first_payload = json.loads(rows[0][0])
    from fakes import parse_step_input
    shown = parse_step_input(rows[1][1])
    assert shown == contracts.with_citation_handles(json.loads(rows[1][0]))
    stamped, _ = contracts.stamp_package_hash(task, first_payload, {"SYNTHETIC_invalid_shape": True})
    stamped, _ = contracts.stamp_step_input_id(task, first_payload, stamped)  # RF6 (D211)
    problem = issues(first_payload, stamped)
    expected = old_repair_message(shown, contracts.issues_with_handles(first_payload, problem))
    if task == "report_section":
        assert rows[1][1].startswith(expected)
        assert '{"SYNTHETIC_invalid_shape": true}' in rows[1][1]
        assert prompt.REPORT_SECTION_FULL_REPAIR_GUIDANCE in rows[1][1]
    else:
        assert rows[1][1] == expected


@pytest.mark.parametrize("kind,code", [("other_cell", "anchor_not_in_cell_evidence"),
                                      ("nowhere", "anchor_not_in_cell_evidence"),
                                      ("both_targets", "citation_anchor_target_count"),
                                      ("whole_passage", "anchor_not_in_cell_evidence")])
def test_model_repair_cannot_publish_another_cells_quote_or_a_whole_passage(tmp_path, kind, code):
    flow, store, reports, adapter, run, scope, report_id = report_flow(
        tmp_path, cell_quotes=[CELL_QUOTE, "SYNTHETIC other cell result.", CELL_QUOTE])
    original = adapter.responder
    attempts = 0

    def response(si):
        nonlocal attempts
        draft = json.loads(original(si))
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            attempts += 1
            anchor = draft["citation_anchors"][0]
            anchor["quote"] = BAD_QUOTE
            if attempts == 1:
                # Mixed issues select a full-section repair, preserving the original rejection guard.
                draft["section_id"] = "V"
            if attempts == 2:
                if kind == "other_cell":
                    anchor["quote"] = "SYNTHETIC other cell result."
                elif kind == "both_targets":
                    anchor["quote"] = CELL_QUOTE
                    anchor["passage_id"] = si["passages"][0]["passage_id"]
                elif kind == "whole_passage":
                    anchor["quote"] = si["passages"][0]["text"]
        return json.dumps(draft)

    adapter.responder = response
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert attempts == 2
    failed = reports.section(report_id, "IV")
    assert failed["status"] == "failed" and failed["draft"] is None
    assert code in {issue["code"] for issue in failed["validation"]["issues"]}


@pytest.mark.parametrize("kind", ["other_cell", "nowhere", "whole_passage"])
def test_assembly_keeps_rejecting_stored_links_whose_quote_is_not_owned_by_the_cell(tmp_path, kind):
    from deixis.workflow.report.assembly import _check_anchors
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    quote = {"other_cell": "SYNTHETIC other cell result.", "nowhere": BAD_QUOTE, "whole_passage": PASSAGE}[kind]
    if kind == "other_cell":
        frozen = reports.snapshot(report_id)
        frozen["cells"][1]["evidence"][0]["quote"] = quote
        store.conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?", (json.dumps(frozen), report_id))
    store.conn.execute("UPDATE report_citation_links SET anchor_text = ? WHERE cell_id IS NOT NULL", (quote,))
    assert "anchor_not_in_cell_evidence" in {item["rule"] for item in _check_anchors(store, reports, report_id)}
