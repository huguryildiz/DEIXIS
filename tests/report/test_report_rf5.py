"""RF5 SYNTHETIC H9c replay and FakeAdapter regressions; no real-model calls."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts, skill
from deixis.workflow.report import sections
from deixis.workflow.report.plan import freeze_plan
from fakes import FakeAdapter, envelope
from test_report_flow import report_flow


REPLAY = json.loads((Path(__file__).parent.parent / "fixtures/research/report-rf5-h9c-replay.json").read_text())


def _abstract_case(tmp_path, monkeypatch, *, draft=None, repairs=None):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    scope["language_hint"] = REPLAY["language_hint"]
    snapshot = reports.save_snapshot(report_id, run["target"]["table_id"])
    plan = freeze_plan({"scope_statement": "SYNTHETIC RF5 replay scope.", "research_questions": [],
        "glossary": [], "axes": [], "limitations_column_id": None, "future_work_column_id": None},
        snapshot, len(snapshot["rows"]))
    plan["section_budgets"]["abstract"] = copy.deepcopy(REPLAY["section_budget"])
    reports.set_plan(report_id, plan)
    summaries = [s | {"first_sentence": "SYNTHETIC omitted body summary."} for s in REPLAY["prior_summaries"]]
    monkeypatch.setattr(sections, "_prior_summaries", lambda *args: summaries)

    def response(si):
        if si["task_type"] == "report_section":
            return json.dumps(copy.deepcopy(draft or REPLAY["draft"]) |
                              envelope(si, "deixis.report_section_draft.v2"), ensure_ascii=False)
        assert si["task_type"] == "report_phrase_repair"
        return json.dumps(envelope(si, "deixis.report_phrase_repair_draft.v1") |
                          {"repairs": copy.deepcopy(REPLAY["repairs"] if repairs is None else repairs)},
                          ensure_ascii=False)

    adapter = FakeAdapter(responder=response)
    flow.deps.adapters["fake"] = adapter
    status = asyncio.run(sections._run_section(flow, run, scope, reports, report_id, plan, snapshot, "abstract"))
    return status, store, reports, adapter, run, report_id


def _assert_rejected_original(case, original, expected):
    status, store, reports, adapter, run, report_id = case
    assert status == "valid"
    section = reports.section(report_id, "abstract")
    assert section["status"] == "valid" and section["validation"]["ok"]
    first, phrase = adapter.calls[:2]
    assert [s["task_type"] for s in adapter.calls] in (
        ["report_section", "report_phrase_repair"],
        ["report_section", "report_phrase_repair", "report_phrase_repair"],
    )
    assert section["draft"] == original | envelope(first, "deixis.report_section_draft.v2")
    stored_claims = list(store.conn.execute("SELECT text FROM report_claims WHERE report_section_id=? ORDER BY ordinal",
                                          (section["id"],)))
    assert [r["text"] for r in stored_claims] == [c["text"] for c in original["claims"]]
    rejection = next(i for i in section["validation"]["issues"] if i["code"] == "phrase_repair_rejected")
    assert expected in rejection["blocking_codes"]
    assert expected not in {i["code"] for i in section["validation"]["issues"]}
    event = store.conn.execute("SELECT payload_json FROM events WHERE type='report_phrase_repair_rejected'").fetchone()
    assert json.loads(event[0])["blocking_codes"] == rejection["blocking_codes"]
    rows = list(store.conn.execute("SELECT before, after, outcome FROM report_phrase_repairs WHERE report_id=?", (report_id,)))
    assert len(rows) == len(phrase["report_target"]["repair_request"]["sentences"])
    assert all(r["outcome"] == "unframed_exception" and r["before"] == r["after"] for r in rows)
    assert store.run(run["id"])["pause_reason"] is None
    return rejection


def test_h9c_synthetic_replay_retains_the_valid_model_abstract_and_records_rejection(tmp_path, monkeypatch):
    case = _abstract_case(tmp_path, monkeypatch)
    rejection = _assert_rejected_original(case, REPLAY["draft"], "own_work_phrase_in_claim")
    assert rejection["issues"] == [{"code": "own_work_phrase_in_claim", "path": "/claims/1/text",
                                   "message": "'Bu çalışma' names this answer's own work, not a cited source"}]
    _, store, _, adapter, _, _ = case
    sessions = list(store.conn.execute("SELECT raw_output, validation_json FROM model_sessions ORDER BY rowid"))
    assert len(sessions) == 2
    first_validation = json.loads(sessions[0]["validation_json"])
    assert first_validation["ok"] and first_validation["issues"] == []
    assert [w["code"] for w in first_validation["warnings"]] == ["sentence_without_phrasebank_frame"] * 4
    assert json.loads(sessions[0]["raw_output"]) == REPLAY["draft"] | envelope(adapter.calls[0], "deixis.report_section_draft.v2")
    assert json.loads(sessions[1]["raw_output"])["repairs"] == REPLAY["repairs"]


@pytest.mark.parametrize("violation,expected", [
    ("own_work", "own_work_phrase_in_claim"),
    ("banned", "banned_word"),
    ("word_budget", "section_word_count_over_budget"),
    ("structure", "unknown_repair_sentence"),
])
def test_fake_adapter_warning_repair_cannot_demote_valid_draft(tmp_path, monkeypatch, violation, expected):
    repairs = copy.deepcopy(REPLAY["repairs"])
    if violation == "own_work":
        repairs[2]["text"] = "Bu çalışma, verilen kapsamı değerlendirmiştir."
    elif violation == "banned":
        repairs[2]["text"] = "Bulgular özgünlük iddiasını göstermektedir."
    elif violation == "word_budget":
        repairs[2]["text"] = "Bulgular " + "k " * 250 + "göstermektedir."
    else:
        repairs[2]["sentence_id"] = "abstract.99#1"
    _assert_rejected_original(_abstract_case(tmp_path, monkeypatch, repairs=repairs), REPLAY["draft"], expected)


def test_valid_phrase_repair_is_kept_without_another_model_call(tmp_path, monkeypatch):
    repairs = copy.deepcopy(REPLAY["repairs"])
    repairs[2]["text"] = "Bulgular, temel amacın enerji maliyetini azaltmak olduğunu göstermektedir."
    status, store, reports, adapter, _, report_id = _abstract_case(tmp_path, monkeypatch, repairs=repairs)
    assert status == "valid" and len(adapter.calls) == 2
    draft = reports.section(report_id, "abstract")["draft"]
    assert contracts.validate_model_output(adapter.calls[0], draft).ok
    assert repairs[2]["text"] in draft["claims"][1]["text"]
    assert not store.conn.execute("SELECT 1 FROM events WHERE type='report_phrase_repair_rejected'").fetchone()


def test_phrase_repair_instruction_preserves_blocking_rules():
    text = skill.load_skill_package().files["references/report.md"].split("## Phrase repair (`report_phrase_repair`)", 1)[1].split("## Report review", 1)[0]
    assert 'own-work phrases such as "this study" or "Bu çalışma", or any blocking-rule violation' in text
    assert "retains the valid original draft" in text
