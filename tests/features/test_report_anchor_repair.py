"""Synthetic P19 checks of repair scope, one-repair bound and unchanged model output."""

import asyncio
import copy
import json

import pytest

from deixis.domain import contracts
from deixis.models import prompt
from deixis.workflow.flow import RunStopped
from deixis.workflow.report_sections import run_report
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
    draft["claims"][0]["passage_ids"] = []  # cell anchors only: an unanchored passage citation is invalid
    draft["claims"][0]["equation_origin"] = None
    return si, draft


def issues(si, draft):
    return [vars(issue) for issue in contracts.validate_model_output(si, draft).issues]


@pytest.mark.parametrize("fix", [False])
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


@pytest.mark.parametrize("kind,code", [("whole_passage", "anchor_not_in_cell_evidence")])
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


@pytest.mark.parametrize("kind", ["other_cell"])
def test_assembly_keeps_rejecting_stored_links_whose_quote_is_not_owned_by_the_cell(tmp_path, kind):
    from deixis.workflow.report_assembly import _check_anchors
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    quote = {"other_cell": "SYNTHETIC other cell result.", "nowhere": BAD_QUOTE, "whole_passage": PASSAGE}[kind]
    if kind == "other_cell":
        frozen = reports.snapshot(report_id)
        frozen["cells"][1]["evidence"][0]["quote"] = quote
        store.conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?", (json.dumps(frozen), report_id))
    store.conn.execute("UPDATE report_citation_links SET anchor_text = ? WHERE cell_id IS NOT NULL", (quote,))
    assert "anchor_not_in_cell_evidence" in {item["rule"] for item in _check_anchors(store, reports, report_id)}
