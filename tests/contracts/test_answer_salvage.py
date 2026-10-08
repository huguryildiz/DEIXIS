"""Synthetic anchor pruning and FakeAdapter checks; no model or scientific validation."""

import asyncio
import copy
import json

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response
from test_contracts import STEP_INPUTS


def draft_with_defect(si, defect):
    draft = json.loads(valid_response(si))
    first, second = si["passages"][:2]
    anchor = draft["citation_anchors"][0]
    if defect == "duplicate":
        draft["citation_anchors"].append(dict(anchor))
    elif defect == "duplicate_bad_first":
        draft["citation_anchors"].insert(0, dict(anchor, quote="SYNTHETIC quote absent from every passage"))
    elif defect in {"unfindable", "missing", "corrected"}:
        draft["claims"][0]["passage_ids"].append(second["passage_id"])
        draft["claims"].append(dict(draft["claims"][0], claim_label="c2", passage_ids=[second["passage_id"]]))
        if defect in {"unfindable", "corrected"}:
            draft["citation_anchors"].extend([
                dict(anchor, claim_label=label, passage_id=second["passage_id"],
                     quote=second["text"] if defect == "corrected" else
                     "SYNTHETIC quote absent from every passage") for label in ("c1", "c2")])
    elif defect == "uncited":
        draft["citation_anchors"].append(dict(anchor, passage_id=second["passage_id"]))
    elif defect == "unknown_uncited":
        draft["citation_anchors"].append(dict(anchor, passage_id="psg_UNKNOWN0001"))
    elif defect == "mixed":
        draft["citation_anchors"].append(dict(anchor))
        draft["claims"][0]["passage_ids"].append("psg_UNKNOWN0001")
    elif defect == "empty":
        draft["citation_anchors"] = []
    return draft


def run_step(tmp_path, defects):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    sid = store.create_upload_source("SYNTHETIC source")
    pids = [store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, text)
            for text in ("SYNTHETIC first passage about release scheduling.",
                         "SYNTHETIC second passage about a relay budget.")]
    raw_outputs = []

    def responder(si):
        draft = draft_with_defect(si, defects[min(len(raw_outputs), len(defects) - 1)])
        raw_outputs.append(json.dumps(draft))
        return raw_outputs[-1]

    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8872), store,
                                 {"fake": adapter}, skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    result = asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer",
                        "grounded_answer", source_ids=[sid], passage_rows=[store.passage(pid) for pid in pids]))
    return result, store, adapter, raw_outputs, pids


@pytest.mark.parametrize("defect", ["duplicate", "duplicate_bad_first", "uncited"])
def test_lossless_anchor_only_output_is_salvaged_without_a_repair_and_drops_are_recorded(tmp_path, defect):
    result, store, adapter, raw_outputs, pids = run_step(tmp_path, [defect])
    try:
        assert len(adapter.calls) == 1
        assert not result.get("invalid")
        assert [c["claim_label"] for c in result["result"]["claims"]] == ["c1"]
        assert result["result"]["claims"][0]["passage_ids"] == [pids[0]]
        assert len(result["result"]["citation_anchors"]) == 1
        warnings = [w for w in result["warnings"] if w["code"] == "citation_anchor_salvaged"]
        assert warnings and all(w["issue_codes"] and w["claim_label"] for w in warnings)
        assert all(w["passage_id"] in pids or w["dropped"] == "claim" for w in warnings)
        assert all(w["dropped"] == "anchor" for w in warnings)
        session = store.model_session(result["step_input_id"])
        assert session["raw_output"] == raw_outputs[0]
        validation = json.loads(store.conn.execute(
            "SELECT validation_json FROM model_sessions WHERE step_input_id = ?", (result["step_input_id"],)).fetchone()[0])
        assert validation["ok"] and not validation["issues"]
        assert validation["warnings"] == result["warnings"]
        step = store.conn.execute("SELECT s.output_json FROM run_steps s JOIN step_inputs i ON i.step_id = s.id"
                                  " WHERE i.id = ?", (result["step_input_id"],)).fetchone()
        assert json.loads(step[0])["warnings"] == result["warnings"]
        payload = store.conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (result["step_input_id"],)).fetchone()
        assert contracts.validate_model_output(json.loads(payload[0]), result["result"]).ok
    finally:
        store.conn.close()


@pytest.mark.parametrize("defect", ["unfindable", "missing"])
@pytest.mark.parametrize("last", ["corrected", "unfindable", "missing"])
def test_lossy_anchor_salvage_waits_for_repair_and_preserves_corrected_content(tmp_path, defect, last):
    result, store, adapter, raw_outputs, pids = run_step(tmp_path, [defect, last])
    try:
        assert len(adapter.calls) == 2
        assert not result.get("invalid")
        sessions = list(store.conn.execute("SELECT raw_output, validation_json FROM model_sessions ORDER BY rowid"))
        first = json.loads(sessions[0]["validation_json"])
        assert not first["ok"]
        assert {i["code"] for i in first["issues"]} == {
            "anchor_not_in_passage" if defect == "unfindable" else "missing_citation_anchor"}
        assert not any(w["code"] == "citation_anchor_salvaged" for w in first["warnings"])
        assert [s["raw_output"] for s in sessions] == raw_outputs
        warnings = [w for w in result["warnings"] if w["code"] == "citation_anchor_salvaged"]
        if last == "corrected":
            assert not warnings
            assert [c["claim_label"] for c in result["result"]["claims"]] == ["c1", "c2"]
            assert result["result"]["claims"][0]["passage_ids"] == pids
            assert result["result"]["claims"][1]["passage_ids"] == [pids[1]]
        else:
            assert {w["dropped"] for w in warnings} >= {"citation_link", "claim"}
            assert any(w["dropped"] == "claim" and w["claim_label"] == "c2" for w in warnings)
            assert [c["claim_label"] for c in result["result"]["claims"]] == ["c1"]
            assert result["result"]["claims"][0]["passage_ids"] == [pids[0]]
        final = json.loads(sessions[-1]["validation_json"])
        assert final["ok"] and not final["issues"]
        assert final["warnings"] == result["warnings"]
    finally:
        store.conn.close()


@pytest.mark.parametrize("last", ["valid", "duplicate", "unfindable"])
def test_mixed_output_uses_repair_and_final_anchor_only_output_can_be_salvaged(tmp_path, last):
    result, store, adapter, raw_outputs, _ = run_step(tmp_path, ["mixed", last])
    try:
        assert len(adapter.calls) == 2
        assert not result.get("invalid")
        sessions = list(store.conn.execute("SELECT raw_output, validation_json FROM model_sessions ORDER BY rowid"))
        first = json.loads(sessions[0]["validation_json"])
        assert not first["ok"] and not any(w["code"] == "citation_anchor_salvaged" for w in first["warnings"])
        assert "unknown_passage_id" in {i["code"] for i in first["issues"]}
        assert [s["raw_output"] for s in sessions] == raw_outputs
        assert any(w["code"] == "citation_anchor_salvaged" for w in result["warnings"]) == (last != "valid")
    finally:
        store.conn.close()


@pytest.mark.parametrize("defect", ["mixed", "unknown_uncited", "empty"])
def test_non_salvageable_or_empty_answer_keeps_bounded_failure_path(tmp_path, defect):
    result, store, adapter, _, _ = run_step(tmp_path, [defect])
    try:
        assert len(adapter.calls) == 2 and result["invalid"]
        assert all(not any(w["code"] == "citation_anchor_salvaged" for w in json.loads(s[0])["warnings"])
                   for s in store.conn.execute("SELECT validation_json FROM model_sessions"))
    finally:
        store.conn.close()


@pytest.mark.parametrize("defect", ["schema", "envelope", "label", "empty_claim", "duplicate_id", "locator"])
def test_salvage_does_not_mask_other_defects_or_mutate_input(defect):
    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    draft = draft_with_defect(si, "duplicate")
    if defect == "schema":
        draft["extra"] = True
    elif defect == "envelope":
        draft["scope_revision"] += 1
    elif defect == "label":
        draft["citation_anchors"][0]["claim_label"] = "c99"
    elif defect == "empty_claim":
        draft["claims"].append(dict(draft["claims"][0], claim_label="c2", passage_ids=[]))
    elif defect == "duplicate_id":
        draft["claims"][0]["passage_ids"] *= 2
    elif defect == "locator":
        draft["claims"][0]["text"] = "See page 123 for the result."
    before = copy.deepcopy(draft)
    salvaged, warnings = contracts.salvage_answer_draft(si, draft)
    assert not warnings and salvaged == before and draft == before
