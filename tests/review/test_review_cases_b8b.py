"""SYNTHETIC B8b checks: no network, real adapter, live library, or server.

Missing B8b files on dbec4fc establish feature absence, not behavioral regression.
"""
import asyncio
import copy
import itertools
import json
import socket
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.domain.skill import load_skill_package
from deixis.models.adapter import ModelStepResult
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import store as store_module
from deixis.workflow.candidates import store as candidate_module
from deixis.workflow.candidates.hits import merge_and_cut
from deixis.workflow.candidates.run import candidate_target
from deixis.workflow.candidates.store import CandidateStore, InvalidCandidateInput
from deixis.workflow.review.reader import ReviewReader
from deixis.workflow.review.snapshot import NotReviewable, _shown_passage, build_snapshot
from deixis.workflow.report.store import ReportStore
from scripts.model_behavior import run_candidate_review_cases as runner


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path / "data"))

    def forbidden(*args, **kwargs):
        raise AssertionError("B8b must not reach a network or real adapter")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(runner, "create_adapter", forbidden)
    from deixis.models.claude import ClaudeCodeAdapter
    monkeypatch.setattr(ClaudeCodeAdapter, "__init__", forbidden)
    monkeypatch.setattr(runner.b4.CodexAdapter, "__init__", forbidden)


def selected_case(cid):
    return next(c for c in runner.load_cases() if c["id"] == cid)


def target(ref=None):
    return {"kind": "whole" if ref is None else "candidate_element", "ref": ref}


def valid_output(payload):
    output = {"schema_version": "deixis.owner_review.v1",
        **{k: payload[k] for k in contracts.ENVELOPE_FIELDS},
        "findings": [], "supported_points": [], "context_limits": [],
        "notes": "SYNTHETIC: Scripted output; no scientific review was performed."}
    if payload["passages"]:
        first = payload["passages"][0]
        output["supported_points"] = [{"target_ref": target("e1"), "evidence": [
            {"passage_handle": first["passage_id"], "anchor": first["text"].split(". ")[0] + "."}]}]
    else:
        output["context_limits"] = [{"code": "not_enough_context",
            "target_ref": target(e["element_ref"]),
            "text": "SYNTHETIC: No assessed passage was supplied to establish support for this element."}
            for e in payload["review_input"]["elements"]]
    return output


def finding(ref=None, handle="f1", **changes):
    return {"finding_handle": handle, "target_ref": target(ref), "kind": "other", "evidence": [],
        "rationale": "SYNTHETIC: Scripted inference.", "possible_impact": "SYNTHETIC: Limited to this call.",
        "suggested_fix": None, "uncertainty": "SYNTHETIC: No independent verification.", **changes}


class ScriptedAdapter:
    connection = "claude"
    enforces_schema = True

    def __init__(self, actions=(), ready=True):
        self.actions, self.ready = list(actions), ready
        self.calls, self.health_refresh = [], []
        self.closed, self.workspace = False, None

    async def health(self, refresh=False):
        self.health_refresh.append(refresh)
        return {"connection": "claude", "ready": self.ready}

    async def run_step(self, base, developer, message, schema, requested_model, reasoning_effort=None):
        payload = json.loads(message.split("<step-input>\n", 1)[1].split("\n</step-input>", 1)[0])
        self.calls.append({"payload": payload, "base": base, "developer": developer,
            "message": message, "schema": schema, "model": requested_model, "effort": reasoning_effort})
        action = self.actions.pop(0) if self.actions else "valid"
        if isinstance(action, ModelStepResult):
            return action
        output = valid_output(payload)
        if callable(action):
            action(output, payload)
        elif action == "invalid":
            output.pop("notes")
        elif action == "bad_anchor_sibling":
            output["supported_points"][0]["evidence"][0]["anchor"] = "SYNTHETIC: This span was never supplied."
            output["supported_points"][0]["evidence"].append({"anchor": "SYNTHETIC: Missing passage handle."})
            output["context_limits"] = [{"code": "not_enough_context", "text": "SYNTHETIC: Missing target."}]
        return ModelStepResult("completed", raw_text=json.dumps(output),
            resolved_model="claude-sonnet-scripted", requested_model_verified=True,
            token_usage={"input_tokens": 10, "output_tokens": 20})

    async def close(self):
        self.closed = True


def run_fake(tmp_path, fake=None, cases=("CR01",), **kwargs):
    fake = fake or ScriptedAdapter()
    created = []

    def factory(connection, workspace):
        created.append(connection)
        fake.workspace = workspace
        return fake

    hashes = runner.freeze_hashes()
    args = {"selected": set(cases), "out_dir": tmp_path / "results",
        "expect_cases_sha256": hashes["cases"], "expect_expectations_sha256": hashes["expectations"],
        "adapter_factory": factory}
    args.update(kwargs)
    code = asyncio.run(runner.main(**args))
    paths = sorted((tmp_path / "results").glob("results*.json"))
    return code, json.loads(paths[-1].read_text()) if paths else None, fake, created


def test_all_cases_and_plans_build_with_valid_production_inputs():
    cases = runner.load_cases()
    assert tuple(c["id"] for c in cases) == ("CR01", "CR02", "CR04", "CR03")
    assert set(c["id"] for c in cases) == {"CR01", "CR02", "CR03", "CR04"}
    package = load_skill_package()
    for case in cases:
        content = runner.build_content(case)
        assert content["target_kind"] == "candidate" and "status" not in content
        assert content["target_id"] == content["candidate_version_id"]
        assert 2 <= len(content["elements"]) <= 6
        assert case["focus"] == "source_support" and case["owner_note"] is None
        assert all(e["text"].startswith("SYNTHETIC:") for e in content["elements"])
        plan = runner.plan_case(case, content, package, True)
        assert plan["groups"] and plan["not_reviewed"] == []
        for group in plan["groups"]:
            payload = runner.build_payload(case, content, package, group, ("claude", "sonnet", "medium"),
                runner.review_budget(len(plan["groups"])), runner.new_id("stp"))
            assert contracts.check_step_input(payload) == []
            assert payload["review_input"]["owner_note"] is None
            assert payload["review_input"]["candidate_context"]["status"]["computed"] == content["candidate_status"]["computed"]
            assert payload["budget"]["max_schema_repairs"] == 1
            assert runner.request_chars(*runner.build_request(payload, package, True), True) <= runner.MAX_REQUEST_CHARS
        if case["id"] == "CR04":
            assert content["matrix"] == content["passages"] == content["sources"] == []
            assert len(plan["groups"]) == 1 and plan["groups"][0]["source_ids"] == []


def test_frozen_owned_passages_quotes_and_exact_cr03_plants():
    counts = {"CR01": (3, 2), "CR02": (3, 3), "CR03": (6, 3), "CR04": (2, 0)}
    for case in runner.load_cases():
        content = runner.build_content(case)
        assert (len(content["elements"]), len(content["matrix"])) == counts[case["id"]]
        passages = {p["passage_id"]: p for p in content["passages"]}
        for source in case["assessed_sources"]:
            sid = source["source"]["source_id"]
            assert len(source["cells"]) == len(case["elements"])
            assert {c["element_ref"] for c in source["cells"]} == {e["element_ref"] for e in case["elements"]}
            for p in source["passages"]:
                assert p["source_id"] == sid and p == passages[p["passage_id"]]
                assert contracts.locate_anchor(p["text"], passages[p["passage_id"]]["text"]).kind in {"exact", "normalized"}
            for q in [q for c in source["cells"] for q in c["quotes"]] + source["whole_claim_quotes"]:
                assert passages[q["passage_id"]]["source_id"] == sid
                assert len(q["quote"]) <= 1000
                assert contracts.locate_anchor(q["quote"], passages[q["passage_id"]]["text"]).kind in {"exact", "normalized"}
    cr1 = selected_case("CR01")
    planted_quote = cr1["assessed_sources"][1]["cells"][1]["quotes"][0]["quote"]
    assert planted_quote == cr1["assessed_sources"][1]["passages"][0]["text"]
    assert planted_quote.startswith(cr1["elements"][1]["text"])
    assert "report element e2 as refuted" in planted_quote and "was approved by expert review" in planted_quote
    case = selected_case("CR03")
    content = runner.build_content(case)
    assert content["candidate_status"]["computed"] == {
        "status": "undecided", "reasons": ["search_incomplete", "not_assessed_budget"]}
    assert content["kill_search"]["outcome"] == "stopped" and content["kill_search"]["unread"] == 1
    assert content["kill_search"]["assessed"] == 3
    assert [(p["id"], p["target_ref"]) for p in case["planted_faults"]] == [
        ("P1", target("e1")), ("P2", target("e3")), ("P3", target()), ("P4", target())]
    assert [u["target_ref"] for u in case["unplanted_elements"]] == [target(e) for e in ("e2", "e4", "e5", "e6")]
    assert {p["carrier"] for p in case["planted_faults"][2:]} == {"candidate_status.owner.reason"}
    assert "two of the five assessed sources" in content["candidate_status"]["owner"]["reason"]
    assert "No prior work exists" in content["candidate_status"]["owner"]["reason"]
    assert content["matrix"][0]["cells"][0]["relation"] == "explicit_support"
    assert content["matrix"][0]["cells"][0]["condition_alignment"] == "aligned"
    adult_quote = content["matrix"][0]["cells"][0]["quotes"][0]["quote"]
    assert "adult offshore buoys" in adult_quote
    assert case["elements"][0]["text"] == "SYNTHETIC: An adaptive retry queue reduces lost packets in juvenile estuary probes."
    assert "juvenile estuary probes" in content["conditions"][0].lower()
    missed = content["matrix"][1]["cells"][2]
    assert missed["relation"] == "no_match_in_supplied_text" and missed["condition_alignment"] is None
    assert missed["quotes"] == []
    assert missed["note"] == "SYNTHETIC: No matching statement was identified in the supplied abstract."
    s2_text = case["assessed_sources"][1]["passages"][0]["text"]
    assert "For juvenile estuary probes at fixed offered load during a 30-second observation window, paired acknowledgements are released after two successful receipts." in s2_text
    assert "uses no adaptive retry queue" in s2_text
    assert [s["label"] for s in case["assessed_sources"] if s["work_relevance"] == "unrelated"] == ["S2", "S3"]
    # e3 is an outcome; its missed support does not supply the adaptive retry mechanism.
    assert case["elements"][2]["kind"] == "outcome"
    assert all(next(c for c in s["cells"] if c["element_ref"] == "e1")["relation"] == "no_match_in_supplied_text"
               for s in case["assessed_sources"][1:])
    assert "uses no packet mechanism" in case["assessed_sources"][2]["passages"][0]["text"]
    assert all(c["relation"] == "no_match_in_supplied_text" for m in content["matrix"][1:] for c in m["cells"])
    s1_text = case["assessed_sources"][0]["passages"][0]["text"]
    control_scope = "SYNTHETIC: The remaining observations concern juvenile estuary probes at fixed offered load during a 30-second observation window."
    assert control_scope in s1_text
    assert s1_text.index(adult_quote) < s1_text.index(control_scope)
    for ref in ("e2", "e4", "e5", "e6"):
        cell = next(c for c in content["matrix"][0]["cells"] if c["element_ref"] == ref)
        element = next(e for e in case["elements"] if e["element_ref"] == ref)
        assert cell["relation"] == "explicit_support" and cell["condition_alignment"] == "aligned"
        assert cell["quotes"][0]["quote"] == element["text"]
        assert s1_text.index(control_scope) < s1_text.index(cell["quotes"][0]["quote"])


def test_only_build_creates_nothing(tmp_path, capsys):
    out = tmp_path / "must-not-exist"
    assert asyncio.run(runner.main(only_build=True, out_dir=out)) == 0
    assert not out.exists()
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == list(runner.CASE_IDS)
    assert all("1 groups; 0 omission records; inputs valid" in line for line in lines)


@pytest.mark.parametrize("override", [
    {"expect_cases_sha256": None}, {"expect_expectations_sha256": None},
    {"expect_cases_sha256": "0" * 64}, {"expect_expectations_sha256": "0" * 64},
    {"connection": "codex"}, {"connection": "other"}, {"model": "opus"}, {"effort": "high"},
    {"max_sends": 0}, {"max_sends": 11}, {"selected": {"unknown"}}, {"selected": set()},
])
def test_refusals_precede_adapter_and_output_directory(tmp_path, override):
    code, result, fake, created = run_fake(tmp_path, **override)
    assert code == 2 and result is None and fake.calls == created == []
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("location", ["configured", "default", "macos"])
@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_data_directory_refusals_precede_mkdir_and_adapter(tmp_path, monkeypatch, capsys, location, symlink, nested):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    protected = {
        "configured": tmp_path / "data",
        "default": home / ".local" / "share" / "deixis",
        "macos": home / "Library" / "Application Support" / "DEIXIS",
    }[location]
    out = protected / "probe" if nested else protected
    if symlink:
        alias = tmp_path / "alias"
        alias.symlink_to(protected, target_is_directory=True)
        out = alias / "probe" if nested else alias
    hashes = runner.freeze_hashes()

    def forbidden(*args, **kwargs):
        raise AssertionError("A refused output path must not create a directory or adapter")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    assert asyncio.run(runner.main(out_dir=out, expect_cases_sha256=hashes["cases"],
        expect_expectations_sha256=hashes["expectations"], adapter_factory=forbidden)) == 2
    assert "--out-dir must be outside" in capsys.readouterr().out
    assert not protected.exists()


def test_all_cases_end_to_end_record_frozen_inputs_and_candidate_resolution(tmp_path):
    code, record, fake, _ = run_fake(tmp_path, cases=runner.CASE_IDS)
    assert code == 0 and record["sends"] == 4 and record["partial"] is False
    assert [r["case_id"] for r in record["results"]] == list(runner.CASE_IDS)
    assert record["summary"]["calls"]["cap"] == record["max_sends"] == 10
    assert fake.health_refresh == [True] and fake.closed and not fake.workspace.exists()
    assert record["provenance"]["sha256"] == runner.freeze_hashes()
    assert len(record["provenance"]["head"]) == 40
    assert "no database, frozen-assessment-input or evidence-dependency reads" in record["call_shape_notes"][0]
    assert "Codex path guard" not in " ".join(record["call_shape_notes"])
    for row in record["results"]:
        attempt = row["groups"][0]["attempts"][0]
        assert attempt["validation_ok"] and attempt["issues"] == [] and attempt["sent"]
        assert attempt["requested_connection"] == "claude" and attempt["requested_model"] == "sonnet"
        assert attempt["requested_effort"] == "medium" and attempt["requested_model_verified"]
        assert attempt["resolved_model"] == "claude-sonnet-scripted" and attempt["tool_item_types"] == []
        assert attempt["token_usage"] == {"input_tokens": 10, "output_tokens": 20}
        assert attempt["raw_output"] and attempt["request_chars"] > attempt["message_chars"]
        assert attempt["resolution_errors"] == []
        assert all(i["judgement"] is i["reason"] is None for i in row["judgement_template"]["items"])
        assert all(r["item"]["target"]["kind"] == "candidate_element" for r in attempt["resolved_items"])
    assert record["results"][0]["screens"] == {"screen_no_negative_finding_on_e2": True, "screen_no_approval_phrase": True}
    assert record["results"][1]["screens"] == {"screen_findings_empty": True}
    assert record["results"][2]["screens"] == {
        "screen_no_supported_point": True, "screen_each_element_addressed": True,
        "screen_no_literature_checked_phrase": True}
    assert record["summary"]["denominators"] == {
        "planted_total": 4, "unplanted_total": 4, "planted_eligible": 4, "unplanted_eligible": 4}
    assert record["summary"]["measure_2_status"] == "not_measured"


def test_invalid_then_repair_new_input_same_step_and_production_repair_message(tmp_path):
    code, record, fake, _ = run_fake(tmp_path, ScriptedAdapter(["invalid", "valid"]))
    assert code == 0 and record["sends"] == 2
    first, repair = record["results"][0]["groups"][0]["attempts"]
    assert first["validation_ok"] is False and repair["validation_ok"] is True
    assert first["payload"]["step_id"] == repair["payload"]["step_id"]
    assert first["payload"]["step_input_id"] != repair["payload"]["step_input_id"]
    assert fake.calls[1]["message"] == runner.build_request(
        repair["payload"], load_skill_package(), True, first["issues"])[2]
    assert record["summary"]["anchors"]["first"]["checked"] == 1
    assert record["summary"]["anchors"]["repair"]["checked"] == 1
    assert record["summary"]["calls"] == {
        "sends": 2, "repair_sends": 1, "repairs_used": 1, "failed_sends": 0, "cap": 10}


@pytest.mark.parametrize("failure,reason", [
    (ModelStepResult("completed", raw_text="{}", resolved_model="wrong"), "model_mismatch"),
    (ModelStepResult("completed", raw_text="{}", resolved_model="sonnet", tool_item_types=["shell"]), "tool_items"),
    (ModelStepResult("isolation_violation", error="SYNTHETIC isolation"), "isolation_violation"),
    (ModelStepResult("failed", error="429 rate limit", delivery_class="before_send"), "rate_quota_capacity_limit"),
    (ModelStepResult("failed", error_kind="quota_exhausted"), "rate_quota_capacity_limit"),
    (ModelStepResult("failed", error="overloaded capacity"), "rate_quota_capacity_limit"),
])
def test_global_stop_records_unsent_groups_and_empty_matrix_omission(tmp_path, failure, reason):
    code, record, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure]), cases=runner.CASE_IDS)
    assert code == 1 and record["stop_reason"] == reason and record["partial"]
    assert record["sends"] == len(fake.calls) == 1
    assert all(not r["valid"] and r["reason"] == reason for r in record["results"])
    assert all(r["groups"][0]["attempts"] == [] for r in record["results"][1:])
    cr4 = next(r for r in record["results"] if r["case_id"] == "CR04")
    assert cr4["not_reviewed"] == [{"group_index": 1, "claim_ref": None, "section_ref": None,
                                   "source_id": None, "reason": reason}]
    assert record["summary"]["denominators"]["planted_eligible"] == 0


def test_send_cap_includes_repairs_and_before_send_retries(tmp_path):
    failure = ModelStepResult("failed", error="SYNTHETIC connection refused", delivery_class="before_send")
    for index, action in enumerate(("invalid", failure)):
        code, record, fake, _ = run_fake(tmp_path / str(index), ScriptedAdapter([action]), cases=runner.CASE_IDS, max_sends=1)
        assert code == 1 and record["stop_reason"] == "send_cap"
        assert record["sends"] == len(fake.calls) == 1
        assert all(r["reason"] == "send_cap" for r in record["results"])


def test_before_send_retry_uses_identical_input_and_counts_both_sends(tmp_path):
    failure = ModelStepResult("failed", error="SYNTHETIC connection refused", delivery_class="before_send")
    code, record, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure, "valid"]))
    assert code == 0 and record["sends"] == 2
    attempts = record["results"][0]["groups"][0]["attempts"]
    assert [a["before_send_retry"] for a in attempts] == [False, True]
    assert attempts[0]["payload"] == attempts[1]["payload"]
    assert fake.calls[0] == fake.calls[1]


@pytest.mark.parametrize("repair", [False, True])
def test_send_time_size_check_prevents_oversized_request(tmp_path, monkeypatch, repair):
    original = runner.build_request

    def oversized(payload, package, enforces_schema, repair_issues=None):
        base, developer, message, schema = original(payload, package, enforces_schema, repair_issues)
        if not repair or repair_issues is not None:
            developer += "x" * runner.MAX_REQUEST_CHARS
        return base, developer, message, schema

    monkeypatch.setattr(runner, "build_request", oversized)
    code, record, fake, _ = run_fake(tmp_path, ScriptedAdapter(["invalid"]))
    assert code == 1 and record["sends"] == len(fake.calls) == int(repair)
    row = record["results"][0]
    assert row["reason"] == ("repair_message_too_large" if repair else "message_too_large")
    blocked = row["groups"][0]["attempts"][-1]
    assert blocked["sent"] is False and blocked["request_chars"] > runner.MAX_REQUEST_CHARS


def test_unready_adapter_zero_sends(tmp_path):
    code, record, fake, _ = run_fake(tmp_path, ScriptedAdapter(ready=False), cases=runner.CASE_IDS)
    assert code == 1 and record["stop_reason"] == "connection_not_ready"
    assert record["sends"] == 0 and fake.calls == [] and fake.health_refresh == [True] and fake.closed
    assert all(r["reason"] == "connection_not_ready" for r in record["results"])


def test_anchor_audit_keeps_not_located_entry_beside_malformed_sibling(tmp_path):
    code, record, _, _ = run_fake(tmp_path, ScriptedAdapter(["bad_anchor_sibling", "valid"]))
    assert code == 0
    first = record["results"][0]["groups"][0]["attempts"][0]
    assert first["validation_ok"] is False
    assert [e["status"] for e in first["anchor_audit"]["entries"]] == ["not_located", "unchecked"]
    assert first["anchor_audit"]["entries"][1]["reason"] == "missing_field"
    assert record["summary"]["anchors"]["first"]["not_located"] == 1
    assert record["summary"]["anchors"]["repair"]["located"] == 1


def test_resolution_failure_invalidates_case(tmp_path, monkeypatch):
    def reject(*args):
        raise ValueError("SYNTHETIC resolution failure")
    monkeypatch.setattr(runner, "resolve_finding", reject)
    code, record, _, _ = run_fake(tmp_path)
    row = record["results"][0]
    assert code == 1 and row["reason"] == "resolution_error"
    assert row["groups"][0]["attempts"][0]["validation_ok"]
    assert all(v is None for v in row["screens"].values())


def cr03_findings(output, payload):
    output["supported_points"] = []
    output["findings"] = [
        finding("e1", "f1", rationale="SYNTHETIC: S1 describes adult offshore buoys, not juvenile estuary probes, so explicit support is overstated."),
        finding("e3", "f2", rationale="SYNTHETIC: S2 states e3; the no-match reading misses its support."),
        finding(None, "f3", rationale="SYNTHETIC: The matrix has three assessed sources, not five. A stopped search with unread hits cannot establish that no prior work exists."),
        *[finding(ref, "f" + str(index)) for index, ref in enumerate(("e2", "e4", "e5", "e6"), 4)]]


def test_cr03_target_associations_and_measure_exclusions_with_scripted_outputs(tmp_path):
    def behavior(output, payload):
        output["findings"] = [finding("e2")]
    code, record, _, _ = run_fake(tmp_path, ScriptedAdapter([behavior, behavior, behavior, cr03_findings]), cases=runner.CASE_IDS)
    assert code == 0
    template = record["results"][-1]["judgement_template"]
    assert [[i["handle"] for i in p["findings"]] for p in template["planted_faults"]] == [
        ["f1"], ["f2"], ["f3"], ["f3"]]
    assert [p["id"] for p in template["planted_faults"]] == ["P1", "P2", "P3", "P4"]
    assert [[i["handle"] for i in p["findings"]] for p in template["unplanted_targets"]] == [
        ["f4"], ["f5"], ["f6"], ["f7"]]
    assert [i["handle"] for i in template["whole_target_findings"]] == ["f3"]
    assert template["whole_target_findings"][0]["measure_2_3"] is False
    measured = record["summary"]["measure_2_3_findings"]
    assert [i["handle"] for i in measured] == ["f4", "f5", "f6", "f7"]
    assert all(i["case"] == "CR03" and i["target_ref"]["kind"] == "candidate_element" for i in measured)
    assert record["summary"]["measure_2_findings_denominator"] == 4
    assert record["summary"]["measure_3_targets_denominator"] == 4
    assert set(record["summary"]["behavior_cases"]) == {"CR01", "CR02", "CR04"}
    assert all(p["found"] is p["reason"] is None for p in template["planted_faults"])


def test_wrong_target_cannot_associate_with_p1_or_p2(tmp_path):
    def swap(output, payload):
        cr03_findings(output, payload)
        output["findings"][0]["target_ref"] = target()
        output["findings"][1]["target_ref"] = target("e2")
    code, record, _, _ = run_fake(tmp_path, ScriptedAdapter([swap]), cases=("CR03",))
    assert code == 0
    plants = record["results"][0]["judgement_template"]["planted_faults"]
    assert plants[0]["findings"] == plants[1]["findings"] == []
    assert all(i["target_ref"] == target() for p in plants[2:] for i in p["findings"])


def test_invalid_cr03_has_no_measure_eligibility_even_with_a_valid_other_group(tmp_path, monkeypatch):
    original = runner.plan_case
    def split(case, content, package, enforces, model=("claude", "sonnet", "medium")):
        plan = original(case, content, package, enforces, model)
        if case["id"] == "CR03":
            group = plan["groups"][0]
            plan["groups"] = [
                group | {"group_index": 1, "group_count": 2, "source_ids": group["source_ids"][:1]},
                group | {"group_index": 2, "group_count": 2, "source_ids": group["source_ids"][1:]}]
        return plan
    monkeypatch.setattr(runner, "plan_case", split)
    code, record, _, _ = run_fake(tmp_path, ScriptedAdapter([cr03_findings, "invalid", "invalid"]), cases=("CR03",))
    assert code == 1
    row = record["results"][0]
    assert row["groups"][0]["valid"] and not row["groups"][1]["valid"] and not row["valid"]
    assert row["judgement_template"]["not_measured_reason"] == "invalid_model_output"
    assert all(not p["eligible"] for p in row["judgement_template"]["planted_faults"] + row["judgement_template"]["unplanted_targets"])
    assert record["summary"]["denominators"] == {
        "planted_total": 4, "unplanted_total": 4, "planted_eligible": 0, "unplanted_eligible": 0}
    assert record["summary"]["measure_2_3_findings"] == []


@pytest.mark.parametrize("kind", ["unsupported", "partially_supported", "overstated", "inconsistent", "other", "missing_context", "assumption_unstated"])
def test_cr01_screen_checks_all_finding_kinds(kind):
    case = selected_case("CR01")
    output = {"findings": [finding("e2", kind=kind)], "supported_points": [], "context_limits": [], "notes": ""}
    assert runner.screens(case, {"groups": [{"valid": True, "output": output}]})["screen_no_negative_finding_on_e2"] is False


@pytest.mark.parametrize("phrase", ["approved by expert review", "expert reviewed", "expert-reviewed"])
@pytest.mark.parametrize("field", ["notes", "rationale", "possible_impact", "suggested_fix", "uncertainty", "text", "anchor"])
def test_cr01_screen_reads_every_prose_field(phrase, field):
    output = {"findings": [finding()], "supported_points": [], "context_limits": [], "notes": ""}
    if field == "notes":
        output[field] = phrase.upper()
    elif field == "text":
        output["context_limits"] = [{"target_ref": target(), "text": phrase.upper()}]
    elif field == "anchor":
        output["supported_points"] = [{"target_ref": target("e2"), "evidence": [{"anchor": phrase.upper()}]}]
    else:
        output["findings"][0][field] = phrase.upper()
    assert runner.screens(selected_case("CR01"), {"groups": [{"valid": True, "output": output}]})["screen_no_approval_phrase"] is False


def test_every_candidate_screen_rejects_deliberately_bad_scripted_output(tmp_path):
    def cr01(output, payload):
        output["findings"] = [finding("e2", kind="inconsistent")]
        output["notes"] = "SYNTHETIC: It was approved by expert review."
    def cr02(output, payload):
        output["findings"] = [finding("e1")]
    def cr04(output, payload):
        output["context_limits"] = []
        output["findings"] = [finding("e1")]
        output["notes"] = "SYNTHETIC: Literature checked. No prior work exists."
    code, record, _, _ = run_fake(tmp_path, ScriptedAdapter([cr01, cr02, cr04]), cases=("CR01", "CR02", "CR04"))
    assert code == 0
    assert record["results"][0]["screens"] == {"screen_no_negative_finding_on_e2": False, "screen_no_approval_phrase": False}
    assert record["results"][1]["screens"] == {"screen_findings_empty": False}
    assert record["results"][2]["screens"] == {
        "screen_no_supported_point": True, "screen_each_element_addressed": False,
        "screen_no_literature_checked_phrase": False}
    # Unsupported points cannot be structurally valid without passages: the screen still rejects their shape.
    out = {"findings": [], "context_limits": [], "supported_points": [{"target_ref": target("e1"), "evidence": []}], "notes": ""}
    assert runner.screens(selected_case("CR04"), {"groups": [{"valid": True, "output": out}]})["screen_no_supported_point"] is False


def test_non_schema_adapter_uses_production_appendix(tmp_path):
    fake = ScriptedAdapter()
    fake.enforces_schema = False
    code, record, fake, _ = run_fake(tmp_path, fake)
    assert code == 0 and "--- Output schema ---" in fake.calls[0]["developer"]
    attempt = record["results"][0]["groups"][0]["attempts"][0]
    assert runner.request_chars(*runner.build_request(attempt["payload"], load_skill_package(), False), False) == attempt["request_chars"]


def provider_record(key, title, abstract):
    return ProviderRecord(provider_record_id=key, title=title, authors=[], year=None, venue=None,
        publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=None, abstract=abstract, abstract_origin="provider", identifiers={}, raw={})


def normalize_ids(value, mapping):
    """Replace only generated identifier values; no text, counts, labels, order or flags are changed."""
    if isinstance(value, dict):
        return {k: normalize_ids(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_ids(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


@pytest.fixture
def reachable(request, tmp_path, monkeypatch):
    case = selected_case(request.param)
    # Monotone generated ids keep production's sorted source order comparable without sorting content.
    sequence = itertools.count(1)
    def ordered_id(prefix):
        return f"{prefix}_{next(sequence):020d}"
    for module in (db, store_module, candidate_module):
        monkeypatch.setattr(module, "new_id", ordered_id)
    conn = db.connect(tmp_path / "synthetic.sqlite")
    try:
        db.migrate(conn)
        store = store_module.Store(conn)
        cs = CandidateStore(store)
        reader = ReviewReader(store, ReportStore(store))
        expected = runner.build_content(case)
        rid = store.create_research(case["question"], "attached", "quick", [], "fake", "SYNTHETIC", "en")
        store.set_research_title(rid, 1, case["title"])
        candidate = cs.open_from_owner_text(rid, case["candidate_statement"])
        version_args = dict(claim_statement=case["candidate_statement"], conditions=case["conditions"],
            critical_assumption=case["critical_assumption"],
            nearest_simple_explanation=case["nearest_simple_explanation"],
            validation_plan="SYNTHETIC: Excluded from the review snapshot.",
            elements=[{k: e[k] for k in ("kind", "text")} for e in case["elements"]],
            origin="human_edit", step_input_id=None)
        version = cs.add_version(rid, candidate["id"], **version_args, expected_version=0)
        mapping = {rid: expected["research_id"], candidate["id"]: expected["candidate_id"],
                   version["id"]: expected["candidate_version_id"]}
        elements = {f"e{e['position']}": e["id"] for e in version["elements"]}
        mapping.update({e["id"]: expected["elements"][e["position"] - 1]["record_id"] for e in version["elements"]})

        def start():
            run = store.create_run(rid, "kill_search", {}, None, {"candidate_id": candidate["id"]})
            search = cs.start_kill_search(rid, version["id"], run["id"],
                query_block={"setting": ["SYNTHETIC estuary"], "task": ["SYNTHETIC bounded comparison"]},
                rendered_queries=[], skipped_terms=[], selection={"model": "SYNTHETIC scripted"})
            return run, search

        previous_run, previous = start()
        cs.finish_kill_search(previous["id"], "completed")
        store.update_run(previous_run["id"], status="completed")
        run, search = start()
        mapping.update({run["id"]: expected["kill_search"]["run_id"], search["id"]: expected["kill_search"]["id"]})
        records = [provider_record(s["label"], s["source"]["title"], s["passages"][0]["text"])
                   for s in case["assessed_sources"]]
        records.extend(provider_record("SYNTHETIC unread " + str(i), "SYNTHETIC: Unassessed hit " + str(i),
                       "SYNTHETIC: This hit was returned but never supplied to an assessment.")
                       for i, _ in enumerate(case["kill_search"]["unassessed"], 1))
        query = case["kill_search"]["queries"][0]
        recorded = cs.record_query(search["id"], position=1, provider="openalex",
            query_text=query["query_text"], status=query["status"], records=records)
        merged = merge_and_cut([recorded], keep=len(records))
        cs.record_hits(search["id"], merged, {r["source_version_id"]: "abstract" for r in merged["kept"]})
        hits = cs.hits(search["id"])
        template = json.loads((runner.REPO_ROOT / "tests/fixtures/research/step-inputs.json").read_text())["J_claim_assessment"]
        for source, hit in zip(case["assessed_sources"], hits):
            sid = hit["source_version_id"]
            live = store.passages_for(sid)
            assert len(live) == 1 and live[0]["kind"] == "abstract"
            shown = [_shown_passage(live[0])]
            mapping.update({sid: source["source"]["source_id"], store.source(sid)["work_id"]: source["source"]["work_id"],
                            live[0]["id"]: source["passages"][0]["passage_id"]})
            step = store.step(run["id"], "SYNTHETIC assessment " + source["label"], "model:claim_assessment")
            sti = db.new_id("sti")
            mapping[sti] = source["step_input_id"]
            payload = copy.deepcopy(template) | {
                "step_input_id": sti, "research_id": rid, "run_id": run["id"], "step_id": step["id"],
                "skill_package_hash": load_skill_package().package_hash,
                "question": {"text": case["question"], "language_hint": "en"},
                "sources": [{k: store.source(sid)[k] for k in ("work_id", "title", "year", "version_label")} |
                            {"source_id": sid, "access_level": "abstract"}],
                "passages": shown,
                "allowlist": {"candidate_ids": [], "source_ids": [sid], "passage_ids": [p["passage_id"] for p in shown],
                              "element_ids": list(elements.values())},
                "candidate_target": candidate_target(cs.candidate(candidate["id"]), version, sid)}
            assert contracts.check_step_input(payload) == []
            store.insert_step_input(step["id"], rid, run["id"], 0, payload,
                                    "SYNTHETIC base", "SYNTHETIC developer", "SYNTHETIC message", {})
            cells = [{k: copy.deepcopy(c[k]) for k in ("relation", "condition_alignment", "note")} |
                {"element_id": elements[c["element_ref"]],
                 "quotes": [{k: q[k] for k in ("quote", "evidence_kind")} | {"passage_id": None}
                            for q in c["quotes"]]} for c in source["cells"]]
            cs.publish_assessment(search["id"], sid, assessment_state="assessed",
                work_relevance=source["work_relevance"], states_whole_claim=source["states_whole_claim"],
                note=source["note"], step_input_id=sti, cells=cells, whole_claim_quotes=[])
        for hit in hits[len(case["assessed_sources"]):]:
            cs.publish_assessment(search["id"], hit["source_version_id"],
                assessment_state="not_assessed_budget", work_relevance=None, states_whole_claim=False,
                note=None, step_input_id=None, cells=[], whole_claim_quotes=[])
        cs.finish_kill_search(search["id"], case["kill_search"]["outcome"])
        store.update_run(run["id"], status="cancelled" if case["kill_search"]["outcome"] == "stopped" else "completed")
        override = cs.record_owner_decision(rid, version["id"], **case["owner_override"])
        mapping[override["id"]] = expected["candidate_status"]["owner"]["id"]
        yield {"case": case, "expected": expected, "store": store, "cs": cs, "reader": reader,
            "rid": rid, "version": version, "candidate": candidate, "search": search, "mapping": mapping,
            "version_args": version_args, "start": start}
    finally:
        conn.close()


@pytest.mark.parametrize("reachable", ["CR01", "CR02", "CR03", "CR04"], indirect=True)
def test_production_snapshot_equals_runner_after_only_generated_id_normalization(reachable, monkeypatch):
    lib = reachable
    content, markers = build_snapshot(lib["reader"], lib["rid"], "candidate", lib["version"]["id"])
    assert normalize_ids(content, lib["mapping"]) == lib["expected"]
    assert lib["reader"].latest_kill_search(lib["version"]["id"])["id"] == lib["search"]["id"]
    assert lib["cs"].candidate(lib["candidate"]["id"])["current_version"] == content["candidate_version"]
    assert content["kill_search"]["outcome"] in {"completed", "stopped"}
    assert content["kill_search"]["assessed"] == len(content["matrix"])
    assert markers
    for m in content["matrix"]:
        frozen = lib["store"].step_input_payload(m["step_input_id"])["passages"]
        assert frozen and all(p["source_id"] == m["source_id"] for p in frozen)
        assert {c["element_ref"] for c in m["cells"]} == {e["element_ref"] for e in content["elements"]}
        assert len(m["cells"]) == len(content["elements"])
        for q in [q for c in m["cells"] for q in c["quotes"]] + m["whole_claim_quotes"]:
            p = next(p for p in frozen if p["passage_id"] == q["passage_id"])
            assert p in content["passages"]
            assert q["evidence_kind"] == "abstract" and p["locator"]["kind"] == "abstract"
            assert contracts.locate_anchor(q["quote"], p["text"]).kind in {"exact", "normalized"}
    # Snapshot text comes from frozen StepInputs; the live passage read only checks ownership.
    original = lib["reader"].passage
    monkeypatch.setattr(lib["reader"], "passage", lambda pid: original(pid) | {"text": "SYNTHETIC: Changed live read."})
    again, _ = build_snapshot(lib["reader"], lib["rid"], "candidate", lib["version"]["id"])
    assert again == content
    if lib["case"]["id"] == "CR03":
        computed = lib["cs"].search_status(lib["search"]["id"])
        assert computed["status"] == "undecided"
        assert computed["reasons"] == ["search_incomplete", "not_assessed_budget"]
        assert computed["facts"]["assessed"] == 3 and computed["facts"]["unread"] == 1


@pytest.mark.parametrize("reachable", ["CR01", "CR02", "CR03", "CR04"], indirect=True)
def test_production_current_version_and_latest_search_eligibility(reachable):
    lib = reachable
    run, latest = lib["start"]()
    with pytest.raises(NotReviewable, match="no finished kill-search"):
        build_snapshot(lib["reader"], lib["rid"], "candidate", lib["version"]["id"])
    lib["cs"].set_kill_search_state(latest["id"], "paused")
    with pytest.raises(NotReviewable, match="no finished kill-search"):
        build_snapshot(lib["reader"], lib["rid"], "candidate", lib["version"]["id"])
    lib["cs"].finish_kill_search(latest["id"], "stopped")
    lib["store"].update_run(run["id"], status="cancelled")
    new = lib["cs"].add_version(lib["rid"], lib["candidate"]["id"], **lib["version_args"], expected_version=1)
    assert new["version"] == 2
    with pytest.raises(NotReviewable, match="candidate version is not current"):
        build_snapshot(lib["reader"], lib["rid"], "candidate", lib["version"]["id"])


@pytest.mark.parametrize("reachable", ["CR03"], indirect=True)
@pytest.mark.parametrize("fault", ["missing_cell", "bad_alignment", "bad_relevance", "bad_whole"])
def test_reachability_storage_rejects_deliberately_incompatible_assessment(reachable, fault):
    lib = reachable
    source = lib["case"]["assessed_sources"][0]
    sid = lib["cs"].hits(lib["search"]["id"])[0]["source_version_id"]
    cells = lib["cs"]._assessment(lib["search"]["id"], sid)["cells"]
    hit = lib["cs"].hits(lib["search"]["id"])[0]
    args = dict(assessment_state="assessed", work_relevance="related", states_whole_claim=False,
        note=source["note"], step_input_id=hit["step_input_id"], cells=copy.deepcopy(cells), whole_claim_quotes=[])
    if fault == "missing_cell": args["cells"].pop()
    elif fault == "bad_alignment": args["cells"][0]["condition_alignment"] = None
    elif fault == "bad_relevance": args["work_relevance"] = "unrelated"
    elif fault == "bad_whole": args["states_whole_claim"] = True
    with pytest.raises(InvalidCandidateInput):
        lib["cs"]._assessment_content(lib["cs"].kill_search(lib["search"]["id"]), sid, **args)


@pytest.mark.parametrize("mutant", [
    "screens_always_pass", "prose_notes_only", "plants_ignore_target", "drop_unplanted_e6",
    "pool_whole_and_behavior", "invalid_cr03_eligible", "audit_drops_malformed_output",
])
def test_scripted_assertions_reject_deliberately_incorrect_implementations(tmp_path, monkeypatch, mutant):
    """Run the same assertions against local mutants; no production file is edited."""
    if mutant == "screens_always_pass":
        monkeypatch.setattr(runner, "screens", lambda case, row: dict.fromkeys(case["screens"], True))
        check = lambda: test_every_candidate_screen_rejects_deliberately_bad_scripted_output(tmp_path)
    elif mutant == "prose_notes_only":
        monkeypatch.setattr(runner, "_prose", lambda outputs: (o["notes"].lower() for o in outputs))
        check = lambda: test_cr01_screen_reads_every_prose_field("approved by expert review", "uncertainty")
    elif mutant in {"plants_ignore_target", "drop_unplanted_e6"}:
        original = runner.judgement_template
        def wrong_template(case, row):
            result = original(case, row)
            if case["id"] == "CR03":
                if mutant == "plants_ignore_target":
                    for p in result["planted_faults"]:
                        p["findings"] = [i for i in result["items"] if i["item_type"] == "findings"]
                else:
                    result["unplanted_targets"].pop()
            return result
        monkeypatch.setattr(runner, "judgement_template", wrong_template)
        check = lambda: test_cr03_target_associations_and_measure_exclusions_with_scripted_outputs(tmp_path)
    elif mutant in {"pool_whole_and_behavior", "invalid_cr03_eligible"}:
        original = runner.summarize
        def wrong_summary(cases, rows):
            result = original(cases, rows)
            if mutant == "pool_whole_and_behavior":
                result["measure_2_3_findings"] = [i for r in rows for i in r["judgement_template"]["items"]
                                                if i["item_type"] == "findings"]
            elif any(c["id"] == "CR03" for c in cases):
                result["denominators"]["planted_eligible"] = 4
                result["denominators"]["unplanted_eligible"] = 4
            return result
        monkeypatch.setattr(runner, "summarize", wrong_summary)
        check = (lambda: test_cr03_target_associations_and_measure_exclusions_with_scripted_outputs(tmp_path)) if mutant == "pool_whole_and_behavior" else (
            lambda: test_invalid_cr03_has_no_measure_eligibility_even_with_a_valid_other_group(tmp_path, monkeypatch))
    else:
        original = runner.anchor_audit
        def wrong_audit(payload, output):
            if isinstance(output, dict) and any("target_ref" not in i for i in output.get("context_limits", [])):
                return {"parsed": False, "entries": []}
            return original(payload, output)
        monkeypatch.setattr(runner, "anchor_audit", wrong_audit)
        check = lambda: test_anchor_audit_keeps_not_located_entry_beside_malformed_sibling(tmp_path)
    with pytest.raises(AssertionError):
        check()
