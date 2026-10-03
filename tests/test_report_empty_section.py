"""RF3 synthetic replay and repair behavior; no real-model or evidence-quality claim."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts, phrasebank, skill
from deixis.workflow.flow import RunStopped
from deixis.workflow.report.phrasing import flagged_sentences
from deixis.workflow.report.sections import run_report
from fakes import FakeAdapter, envelope
from test_report_flow import ReportAdapter, _claim, report_flow


REPLAY = json.loads((Path(__file__).parent / "fixtures/research/report-empty-vi-replay.json").read_text())
EMPTY_MESSAGE = (
    "section has no claims or insufficient-evidence entries; write at least one claim supported by the given evidence, "
    "or one insufficient_evidence entry naming the missing material and why; never invent a claim, passage, cell, gap or quote"
)
INSUFFICIENT = {
    "context": "SYNTHETIC VI candidate basis",
    "reason": (
        "These data must be interpreted with caution because SYNTHETIC VI has no supplied limitations cell, "
        "candidate or passage and no comparable V conflict, so no candidate can be supported."
    ),
}


@pytest.mark.parametrize("section_id", ["I", "III", "IV", "V", "VI", "VII", "VIII", "IX", "abstract", "index_terms"])
def test_empty_section_replay_is_a_semantic_issue_in_every_section(section_id):
    si, draft = copy.deepcopy(REPLAY["step_input"]), copy.deepcopy(REPLAY["output"])
    si["report_target"]["section_id"] = draft["section_id"] = section_id
    result = contracts.validate_model_output(si, draft)
    assert not result.ok
    assert [vars(issue) for issue in result.issues] == [
        {"code": "empty_section", "path": "/claims", "message": EMPTY_MESSAGE}
    ]


@pytest.mark.parametrize("content", ["insufficient_evidence", "claim"])
def test_empty_vi_replay_accepts_model_written_content(content):
    draft = copy.deepcopy(REPLAY["output"])
    if content == "insufficient_evidence":
        draft["insufficient_evidence"] = [INSUFFICIENT]
    else:
        draft["claims"] = [_claim("VI") | {
            "support_type": "analyst_inference",
            "text": "These data must be interpreted with caution because SYNTHETIC V summaries use different conditions.",
        }]
    result = contracts.validate_model_output(REPLAY["step_input"], draft)
    assert result.ok
    assert result.issues == []


def test_gap_only_vi_is_still_empty_without_prose_or_insufficiency():
    draft = copy.deepcopy(REPLAY["output"])
    draft["gaps"] = [{
        "gap_id": "gap9", "kind": "conflicting_evidence", "text": "SYNTHETIC candidate only.",
        "basis_claim_keys": ["V.1", "V.2"], "basis_passage_ids": [], "basis_cell_ids": [],
        "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None},
    }]
    result = contracts.validate_model_output(REPLAY["step_input"], draft)
    assert not result.ok
    assert [vars(issue) for issue in result.issues] == [
        {"code": "empty_section", "path": "/claims", "message": EMPTY_MESSAGE}
    ]


class EmptyVIAdapter(FakeAdapter):
    """Keep report_flow's ordinary sections; script VI without indexing missing cells."""

    def __init__(self, *, still_empty):
        super().__init__(responder=self._response)
        self.ordinary = ReportAdapter()
        self.still_empty = still_empty
        self.vi_calls = 0

    def _response(self, si):
        if si["task_type"] == "report_plan":
            plan = json.loads(self.ordinary._response(si))
            plan["limitations_column_id"] = None
            return json.dumps(plan)
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "VI":
            self.vi_calls += 1
            return json.dumps(envelope(si, "deixis.report_section_draft.v2") | {
                "section_id": "VI", "claims": [], "citation_anchors": [], "subsections": [], "gaps": [],
                "insufficient_evidence": [INSUFFICIENT] if self.vi_calls == 2 and not self.still_empty else [],
            })
        return self.ordinary._response(si)


def _vi_sessions(store, run):
    return list(store.conn.execute(
        "SELECT si.attempt, si.payload_json, si.user_message, si.output_schema_json,"
        " m.raw_output, m.validation_json FROM step_inputs si"
        " JOIN model_sessions m ON m.step_input_id = si.id"
        " JOIN run_steps s ON s.id = si.step_id WHERE s.run_id = ? AND s.operation_key = 'report_section:VI'"
        " ORDER BY si.attempt", (run["id"],),
    ))


def _assert_repair_record(store, run, adapter):
    sessions = _vi_sessions(store, run)
    assert len(sessions) == adapter.vi_calls == 2
    assert [row["attempt"] for row in sessions] == [0, 1]
    for row in sessions:
        si = json.loads(row["payload_json"])
        assert si["report_target"]["plan"]["limitations_column_id"] is None
        assert si["report_target"]["cells"] == si["report_target"]["gap_candidates"] == []
        assert si["sources"] == si["passages"] == []
        assert all(si["allowlist"][name] == [] for name in ("cell_ids", "gap_ids", "source_ids", "passage_ids"))
        assert "repair_issues" not in si
        assert json.loads(row["output_schema_json"]) == contracts.model_output_schema("report_section")
    first_validation = json.loads(sessions[0]["validation_json"])
    assert first_validation["ok"] is False
    assert first_validation["issues"] == [{"code": "empty_section", "path": "/claims", "message": EMPTY_MESSAGE}]
    assert '"empty_section"' in sessions[1]["user_message"]
    assert EMPTY_MESSAGE in sessions[1]["user_message"]
    assert not contracts.report_section_anchor_patch_eligible(first_validation["issues"], [])
    return sessions


def _assert_no_vi_claims_gaps_or_anchors(store, reports, report_id):
    section_id = reports.section(report_id, "VI")["id"]
    assert store.conn.execute("SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?", (section_id,)).fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM report_gaps WHERE report_id = ?", (report_id,)).fetchone()[0] == 0
    assert store.conn.execute(
        "SELECT COUNT(*) FROM report_citation_links l JOIN report_claims c ON c.id = l.claim_id"
        " WHERE c.report_section_id = ?", (section_id,),
    ).fetchone()[0] == 0


def test_empty_vi_repairs_once_to_model_written_insufficiency_and_report_is_valid(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    adapter = EmptyVIAdapter(still_empty=False)
    flow.deps.adapters["fake"] = adapter

    asyncio.run(run_report(flow, run, scope))

    sessions = _assert_repair_record(store, run, adapter)
    section = reports.section(report_id, "VI")
    assert section["status"] == "valid"
    assert section["validation"]["issues"] == []
    assert section["draft"]["insufficient_evidence"] == json.loads(sessions[1]["raw_output"])["insufficient_evidence"] == [INSUFFICIENT]
    assert all(section["draft"][name] == [] for name in ("claims", "gaps", "citation_anchors"))
    assert json.loads(sessions[1]["validation_json"])["ok"] is True
    assert reports.report(report_id)["status"] == "valid"
    assert store.run(run["id"])["pause_reason"] is None
    assert not any(call["task_type"] == "report_phrase_repair" and call["report_target"]["section_id"] == "VI" for call in adapter.calls)
    assert flagged_sentences("VI", [INSUFFICIENT], skill.load_skill_package().files[phrasebank.PHRASEBANK], "en") == []
    _assert_no_vi_claims_gaps_or_anchors(store, reports, report_id)


def test_twice_empty_vi_fails_with_full_issues_and_first_pause_reason(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    adapter = EmptyVIAdapter(still_empty=True)
    flow.deps.adapters["fake"] = adapter

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    section = reports.section(report_id, "VI")
    assert section["status"] == "failed"
    sessions = _assert_repair_record(store, run, adapter)
    issues = [{"code": "empty_section", "path": "/claims", "message": EMPTY_MESSAGE}]
    assert section["validation"]["issues"] == issues
    assert json.loads(sessions[1]["validation_json"])["issues"] == issues
    step = store.step(run["id"], "report_section:VI", "model:report_section")
    assert step["status"] == "failed"
    assert step["error_code"] == "invalid_model_output"
    assert json.loads(step["error_json"]) == issues
    stopped = store.run(run["id"])
    assert stopped["status"] == "paused"
    assert stopped["pause_reason"] == "section_failed"
    assert stopped["error"] == {"sections": ["VI"], "reasons": [{"section_id": "VI", "code": "empty_section", "detail": None}]}
    assert section["draft"] is None
    for row in sessions:
        draft = json.loads(row["raw_output"])
        assert all(draft[name] == [] for name in ("claims", "gaps", "citation_anchors", "insufficient_evidence"))
    assert not any(call["task_type"] == "report_phrase_repair" for call in adapter.calls)
    _assert_no_vi_claims_gaps_or_anchors(store, reports, report_id)


def test_loaded_report_instructions_require_content_and_explain_vi_prose():
    text = " ".join(skill.load_skill_package().files["references/report.md"].split())
    for phrase in (
        "A section answer must contain at least one claim or one `insufficient_evidence` entry",
        "The application rejects an answer with neither",
        "write each candidate as a `gaps` entry",
        "`analyst_inference` claims about those candidates, citing the same basis evidence the gap cites",
        "`gap_refs` may name only ids from `report_target.gap_candidates`",
        "minted ids never go into `gap_refs`",
        "allowlisted limitations cells or passages its gap cites",
        "keep the V claim keys in `basis_claim_keys`",
        "only when such records were supplied",
        "write an `insufficient_evidence` entry alongside the gap",
        "no comparable V conflict was given, write no gap and record one `insufficient_evidence` entry",
    ):
        assert phrase in text
    assert "not ordinary prose claims" not in text
