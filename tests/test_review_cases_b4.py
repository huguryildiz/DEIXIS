"""Synthetic runner checks. No real adapter, model, network or library is used."""
import asyncio
import copy
import json
import socket
from collections import Counter

import pytest

from deixis.domain import contracts
from deixis.domain.skill import load_skill_package
from deixis.models.adapter import ModelStepResult
from scripts.model_behavior import run_review_cases as runner


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("DEIXIS_DATA_DIR", "/tmp/p8b4-data")

    def forbidden(*args, **kwargs):
        raise AssertionError("B4 tests must not reach a network or real adapter")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(runner, "create_adapter", forbidden)


def selected_case(case_id):
    cases, sources = runner.load_cases()
    return next(c for c in cases if c["id"] == case_id), sources


def valid_output(payload):
    output = {"schema_version": "deixis.owner_review.v1",
              **{k: payload[k] for k in contracts.ENVELOPE_FIELDS},
              "findings": [], "supported_points": [], "context_limits": [], "notes": "SYNTHETIC assessment."}
    first = payload["review_input"]["claims"][0]
    if payload["passages"]:
        output["supported_points"] = [{"target_ref": {"kind": "claim", "ref": first["claim_ref"]},
                                       "evidence": [{"passage_handle": payload["passages"][0]["passage_id"],
                                                     "anchor": payload["passages"][0]["text"][:180]}]}]
    for claim in payload["review_input"]["claims"]:
        if claim["claim_ref"] in {"c1", "IV.2"} and not claim["citations"]:
            output["context_limits"].append({"code": "not_enough_context",
                                             "target_ref": {"kind": "claim", "ref": claim["claim_ref"]},
                                             "text": "Cannot check this statement from the supplied call."})
    return output


class ScriptedAdapter:
    connection = "claude"
    enforces_schema = True

    def __init__(self, actions=(), ready=True):
        self.actions = list(actions)
        self.ready = ready
        self.calls = []
        self.health_refresh = []
        self.closed = False
        self.workspace = None

    async def health(self, refresh=False):
        self.health_refresh.append(refresh)
        return {"connection": self.connection, "ready": self.ready, "reason": None if self.ready else "synthetic unready"}

    async def run_step(self, base, developer, message, schema, requested_model, reasoning_effort=None):
        payload = json.loads(message.split("<step-input>\n", 1)[1].split("\n</step-input>", 1)[0])
        self.calls.append({"base": base, "developer": developer, "message": message, "schema": schema,
                           "payload": payload, "model": requested_model, "effort": reasoning_effort})
        action = self.actions.pop(0) if self.actions else "valid"
        if isinstance(action, ModelStepResult):
            return action
        output = valid_output(payload)
        if callable(action):
            action(output, payload)
        elif action == "invalid":
            output.pop("notes")
        elif action == "bad_anchor_sibling":
            output["supported_points"][0]["evidence"][0]["anchor"] = "peak grid import fell by 40%"
            output["context_limits"] = [{"code": "not_enough_context", "text": "SYNTHETIC missing target."}]
        return ModelStepResult("completed", raw_text=json.dumps(output), resolved_model="claude-sonnet-5-5",
                               requested_model_verified=True, token_usage={"input_tokens": 10, "output_tokens": 20})

    async def close(self):
        self.closed = True


def run_fake(tmp_path, fake=None, cases=("RB01",), **kwargs):
    fake = fake or ScriptedAdapter()
    created = []

    def factory(connection, codex_home, workspace):
        created.append(connection)
        fake.workspace = workspace
        return fake

    hashes = runner.freeze_hashes()
    args = {"selected": set(cases), "out_dir": tmp_path / "results",
            "expect_sha256": f"{hashes['cases']},{hashes['expectations']}", "adapter_factory": factory}
    args.update(kwargs)
    code = asyncio.run(runner.main("sonnet", **args))
    paths = sorted((tmp_path / "results").glob("results*.json"))
    result = json.loads(paths[-1].read_text()) if paths else None
    return code, result, fake, created


def test_every_case_builds_and_every_group_input_is_valid():
    cases, sources = runner.load_cases()
    package = load_skill_package()
    assert tuple(c["id"] for c in cases) == runner.CASE_IDS
    for case in cases:
        content = runner.build_content(case, sources)
        assert content["scope"] == {"question": case["question"], "steering": None, "language": "en"}
        assert content[case["target_kind"] + "_id"] == content["target_id"]
        assert all("SYNB4" in c["claim_id"] for c in content["claims"])
        for p in content["passages"]:
            abstract = p["locator"]["kind"] == "abstract"
            assert p["reading_depth"] == ("abstract" if abstract else "selected_sections")
            assert p["abstract_origin"] == ("synthetic_fixture" if abstract else None)
            assert p["text_source"] == (None if abstract else "text_layer")
        for section in content["sections"]:
            assert section["claims"] == [c for c in content["claims"] if c["section_ref"] == section["section_ref"]]
        plan = runner.plan_case(case, content, package, True)
        assert plan["groups"]
        for group in plan["groups"]:
            si = runner.build_payload(case, content, package, group, ("claude", "sonnet", "medium"),
                                      runner.review_budget(len(plan["groups"])), runner.new_id("stp"))
            assert contracts.check_step_input(si) == []
            assert si["budget"]["max_schema_repairs"] == 1
            assert si["model"] == {"connection": "claude", "requested_model": "sonnet"}
            request = runner.build_request(si, package, True)
            assert runner.request_chars(*request, True) <= runner.MAX_REQUEST_CHARS


def test_frozen_claim_counts_and_anchors():
    cases, _ = runner.load_cases()
    assert set(c["id"] for c in cases) == {"RB01", "RB02", "RB03", "RB04", "RB05", "RB06", "PE1", "PE2"}
    plants = [c["plant"] for case in cases if case["id"] in {"PE1", "PE2"} for c in case["claims"] if c["plant"]]
    assert Counter(p["type"] for p in plants) == {"wrong_denominator": 3, "overstated": 3, "support_not_in_passage": 3}
    assert sum(c["plant"] is None for case in cases if case["id"] in {"PE1", "PE2"} for c in case["claims"]) == 15
    not_located = []
    for case in cases:
        texts = {p["passage_id"]: p["text"] for p in case["passages"]}
        for claim in case["claims"]:
            for citation in claim["citations"]:
                pid, cell = citation["passage_id"], citation["cell_id"]
                assert (pid is None) != (cell is None)
                if citation["anchor_text"] is None:
                    assert cell is not None or (case["id"], claim["claim_ref"]) == ("RB06", "IV.1")
                else:
                    assert pid is not None
                    match = contracts.locate_anchor(citation["anchor_text"], texts[pid])
                    if match is None or match.kind not in {"exact", "normalized"}:
                        not_located.append((case["id"], claim["claim_ref"]))
        for cell in case["cells"]:
            for evidence in cell["evidence"]:
                assert contracts.locate_anchor(evidence["quote"], texts[evidence["passage_id"]]).kind in {"exact", "normalized"}
    assert not_located == [("RB04", "III.1")]


def test_rb06_plan_covers_every_other_claim_once():
    case, sources = selected_case("RB06")
    plan = runner.plan_case(case, runner.build_content(case, sources), load_skill_package(), True)
    assert len(plan["groups"]) > 1
    assert {e["claim_ref"] for e in plan["not_reviewed"]} == {"IV.1"}
    assert all(e["reason"] for e in plan["not_reviewed"])
    refs = Counter(ref for g in plan["groups"] for ref in g["claim_refs"])
    assert refs == Counter({c["claim_ref"]: 1 for c in case["claims"] if c["claim_ref"] != "IV.1"})


def test_two_cases_end_to_end_and_recorded_fields(tmp_path):
    code, result, fake, _ = run_fake(tmp_path, cases=("RB02", "RB01"))
    assert code == 0 and result["sends"] == 2 and result["partial"] is False
    assert result["stop_reason"] is None and result["health"]["ready"]
    assert [r["case_id"] for r in result["results"]] == ["RB01", "RB02"]
    assert result["results"][0]["screens"] == {"screen_no_negative_finding_on_c2": True,
                                               "screen_no_peer_review_assertion_phrase": True}
    assert result["results"][1]["screens"] == {"screen_findings_empty": True, "screen_fewer_than_three_findings": True}
    assert fake.health_refresh == [True] and fake.closed and not fake.workspace.exists()
    attempt = result["results"][0]["groups"][0]["attempts"][0]
    assert attempt["attempt"] == "first" and attempt["sent"] and attempt["validation_ok"]
    assert attempt["requested_connection"] == "claude" and attempt["requested_model"] == "sonnet"
    assert attempt["requested_effort"] == "medium" and attempt["requested_model_verified"]
    assert attempt["resolved_model"] == "claude-sonnet-5-5" and attempt["issues"] == []
    assert attempt["token_usage"]["output_tokens"] == 20 and attempt["raw_output"]
    assert attempt["request_chars"] > attempt["message_chars"] > 0
    resolved = attempt["resolved_items"][0]
    assert resolved["item"]["target"]["record_id"].startswith("clm_SYNB4")
    assert resolved["item"]["evidence"][0]["passage_id"].startswith("psg_SYNB4")
    assert result["last_attempted"]["case"] == "RB02"
    assert result["provenance"]["sha256"] == runner.freeze_hashes()
    assert len(result["provenance"]["head"]) == 40 and "status_porcelain" in result["provenance"]
    assert result["call_shape_notes"] and "heuristics" in result["screen_note"]
    assert all(item["judgement"] is None and item["reason"] is None
               for row in result["results"] for item in row["judgement_template"]["items"])


def test_invalid_first_then_valid_repair_has_new_input_same_step(tmp_path):
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter(["invalid", "valid"]))
    assert code == 0 and result["sends"] == 2
    first, repair = result["results"][0]["groups"][0]["attempts"]
    assert first["validation_ok"] is False and repair["validation_ok"] is True
    assert first["issues"][0]["code"] == "schema_invalid"
    assert first["payload"]["step_id"] == repair["payload"]["step_id"]
    assert first["payload"]["step_input_id"] != repair["payload"]["step_input_id"]
    expected = runner.build_request(repair["payload"], load_skill_package(), True, first["issues"])
    assert fake.calls[1]["message"] == expected[2]
    assert result["summary"]["anchors"]["first"]["checked"] == 1
    assert result["summary"]["anchors"]["repair"]["checked"] == 1
    assert result["summary"]["calls"] == {"sends": 2, "repair_sends": 1, "repairs_used": 1,
                                           "failed_sends": 0, "cap": 20}


@pytest.mark.parametrize("failure,reason", [
    (ModelStepResult("completed", raw_text="{}", resolved_model="wrong"), "model_mismatch"),
    (ModelStepResult("completed", raw_text="{}", resolved_model="sonnet", tool_item_types=["shell"]), "tool_items"),
    (ModelStepResult("isolation_violation", error="instruction source", delivery_class="before_send"), "isolation_violation"),
    (ModelStepResult("failed", error="429 rate limit", delivery_class="before_send"), "rate_quota_capacity_limit"),
    (ModelStepResult("failed", error="account quota exhausted"), "rate_quota_capacity_limit"),
    (ModelStepResult("failed", error="overloaded capacity"), "rate_quota_capacity_limit"),
])
def test_global_stops_record_all_unsent_groups_and_cases(tmp_path, failure, reason):
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure]), cases=("RB01", "RB02"))
    assert code == 1 and result["stop_reason"] == reason and result["partial"]
    assert result["sends"] == len(fake.calls) == 1
    assert all(not row["valid"] and row["reason"] == reason for row in result["results"])
    assert result["results"][1]["groups"][0]["attempts"] == []
    assert all(e["reason"] == reason for row in result["results"] for e in row["not_reviewed"])


def test_send_cap_counts_repair_and_records_unsent_cases(tmp_path):
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter(["invalid"]), cases=("RB01", "RB02"), max_sends=1)
    assert code == 1 and result["sends"] == len(fake.calls) == 1
    assert result["stop_reason"] == "send_cap"
    assert [r["reason"] for r in result["results"]] == ["send_cap", "send_cap"]
    assert result["last_attempted"]["attempt"] == "first"


@pytest.mark.parametrize("repair", [False, True])
def test_oversized_complete_request_is_not_sent(tmp_path, monkeypatch, repair):
    original = runner.build_request

    def oversized(payload, package, enforces_schema, repair_issues=None):
        base, developer, message, schema = original(payload, package, enforces_schema, repair_issues)
        if not repair or repair_issues is not None:
            developer += "x" * runner.MAX_REQUEST_CHARS
        return base, developer, message, schema

    monkeypatch.setattr(runner, "build_request", oversized)
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter(["invalid"]))
    assert code == 1 and result["sends"] == len(fake.calls) == int(repair)
    reason = "repair_message_too_large" if repair else "message_too_large"
    assert result["results"][0]["reason"] == reason
    blocked = result["results"][0]["groups"][0]["attempts"][-1]
    assert blocked["sent"] is False and blocked["request_chars"] > runner.MAX_REQUEST_CHARS
    assert result["results"][0]["not_reviewed"][0]["reason"] == reason


def test_resolution_error_invalidates_case_and_records_item(tmp_path, monkeypatch):
    def reject(content, payload, item):
        raise ValueError("SYNTHETIC resolution failure")

    monkeypatch.setattr(runner, "resolve_finding", reject)
    code, result, _, _ = run_fake(tmp_path)
    row = result["results"][0]
    attempt = row["groups"][0]["attempts"][0]
    assert code == 1 and row["reason"] == "resolution_error" and attempt["validation_ok"]
    assert attempt["resolution_errors"] == [{"item_type": "supported_points", "index": 0,
                                               "error": "SYNTHETIC resolution failure"}]
    assert all(value is None for value in row["screens"].values())


def test_unready_health_gate_sends_nothing(tmp_path):
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter(ready=False), cases=("RB01", "RB02"))
    assert code == 1 and result["stop_reason"] == "connection_not_ready"
    assert result["sends"] == 0 and fake.calls == [] and fake.health_refresh == [True]
    assert all(r["reason"] == "connection_not_ready" for r in result["results"])


@pytest.mark.parametrize("final_action", ["valid", "bad_anchor_sibling"])
def test_anchor_audit_survives_malformed_sibling_and_final_invalidity(tmp_path, final_action):
    code, result, _, _ = run_fake(tmp_path, ScriptedAdapter(["bad_anchor_sibling", final_action]), cases=("RB04",))
    row = result["results"][0]
    first = row["groups"][0]["attempts"][0]
    assert first["validation_ok"] is False
    assert not {"review_anchor_not_in_passage", "review_anchor_not_exact"} & {i["code"] for i in first["issues"]}
    assert first["anchor_audit"]["entries"][0]["status"] == "not_located"
    assert row["screens"]["screen_first_attempt_anchors_located"] is False
    assert result["summary"]["anchors"]["first"]["not_located"] == 1
    assert code == (0 if final_action == "valid" else 1)
    assert result["summary"]["anchors"]["repair"]["not_located"] == (0 if final_action == "valid" else 1)


def test_anchor_audit_unchecked_reasons_and_normalized_match():
    payload = {"passages": [{"passage_id": "psg_SYNB4test01", "text": "SYNTHETIC. Alpha beta evidence."}],
               "allowlist": {"passage_ids": ["psg_SYNB4test01"]}}
    audit = runner.anchor_audit(payload, {"findings": [{"evidence": [
        {"passage_handle": "psg_SYNB4test01", "anchor": "ALPHA BETA EVIDENCE"},
        {"passage_handle": "psg_P9999999", "anchor": "Alpha beta evidence"}, {"anchor": "missing passage"},
    ]}], "supported_points": []})
    assert audit["entries"][0]["status"] == "located" and audit["entries"][0]["match_kind"] == "normalized"
    assert [e["reason"] for e in audit["entries"][1:]] == ["passage_not_in_call", "missing_field"]
    assert runner.anchor_audit(payload, "broken JSON")["entries"][0]["reason"] == "unparsable_output"


def test_rb04_zero_checkable_entries_is_null(tmp_path):
    def empty(output, payload):
        output["supported_points"] = []

    code, result, _, _ = run_fake(tmp_path, ScriptedAdapter([empty]), cases=("RB04",))
    assert code == 0 and result["results"][0]["screens"]["screen_first_attempt_anchors_located"] is None
    assert result["summary"]["anchors"]["first"]["checked"] == 0


def test_before_send_retry_counts_cap_and_keeps_attempt_input(tmp_path):
    failure = ModelStepResult("unavailable", error="SYNTHETIC connection refused", delivery_class="before_send")
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure, "valid"]))
    assert code == 0 and result["sends"] == len(fake.calls) == 2
    first, retried = result["results"][0]["groups"][0]["attempts"]
    assert not first["before_send_retry"] and retried["before_send_retry"]
    assert first["payload"] == retried["payload"] and fake.calls[0]["message"] == fake.calls[1]["message"]


def test_second_before_send_failure_is_not_retried_again(tmp_path):
    failure = ModelStepResult("unavailable", error="SYNTHETIC connection refused", delivery_class="before_send")
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure, failure]))
    assert code == 1 and result["sends"] == len(fake.calls) == 2
    assert result["results"][0]["reason"] == "model_call_failed"


def test_unknown_delivery_is_not_resent_and_next_case_runs(tmp_path):
    failure = ModelStepResult("failed", error="SYNTHETIC timeout", delivery_class="after_send_unknown")
    code, result, fake, _ = run_fake(tmp_path, ScriptedAdapter([failure, "valid"]), cases=("RB01", "RB02"))
    assert code == 1 and result["sends"] == len(fake.calls) == 2 and result["stop_reason"] is None
    assert [r["valid"] for r in result["results"]] == [False, True]


@pytest.mark.parametrize("hashes", [None, "wrong,wrong"])
def test_freeze_check_exits_before_adapter_or_directory(tmp_path, hashes):
    code, result, fake, created = run_fake(tmp_path, expect_sha256=hashes)
    assert code == 2 and result is None and created == [] and fake.calls == []
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("cap", [0, 21])
def test_bad_send_cap_exits_before_adapter(tmp_path, cap):
    code, result, _, created = run_fake(tmp_path, max_sends=cap)
    assert code == 2 and result is None and created == []


def test_only_build_creates_no_adapter_or_directory(tmp_path):
    code, result, fake, created = run_fake(tmp_path, cases=("RB01", "RB02"), only_build=True, expect_sha256=None)
    assert code == 0 and result is None and created == [] and fake.calls == []
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("home", [None, "~/Library/Application Support/DEIXIS/codex-home"])
def test_codex_requires_explicit_nonlive_home(tmp_path, home):
    code, result, _, created = run_fake(tmp_path, connection="codex", codex_home=home)
    assert code == 2 and result is None and created == []


def test_planted_summary_and_judgements_stay_unfilled(tmp_path):
    code, result, _, _ = run_fake(tmp_path, cases=("PE1", "PE2"))
    assert code == 0
    assert result["summary"]["denominators"] == {"planted_total": 9, "unplanted_total": 15,
                                                 "planted_eligible": 9, "unplanted_eligible": 15}
    assert result["summary"]["behavior_cases"] == {}
    plants = [p for r in result["results"] for p in r["judgement_template"]["planted_claims"]]
    assert len(plants) == 9 and all(p["found"] is None and p["found_if"] for p in plants)


def test_every_item_type_resolves_and_findings_reach_judgement_template(tmp_path):
    def with_finding(output, payload):
        output["findings"] = [{"finding_handle": "f1", "target_ref": {"kind": "claim", "ref": "c2"},
                               "kind": "overstated", "evidence": [{"passage_handle": payload["passages"][1]["passage_id"],
                                                                     "anchor": payload["passages"][1]["text"][:180]}],
                               "rationale": "SYNTHETIC claim generalizes beyond one house over six weeks.",
                               "possible_impact": "SYNTHETIC scope overstatement.", "suggested_fix": None,
                               "uncertainty": "SYNTHETIC supplied scope only."}]
        output["context_limits"] = [{"code": "only_abstract", "target_ref": {"kind": "whole", "ref": None},
                                     "text": "Some supplied evidence is abstract only."}]

    code, result, _, _ = run_fake(tmp_path, ScriptedAdapter([with_finding]), cases=("PE2",))
    assert code == 0
    row = result["results"][0]
    resolved = row["groups"][0]["attempts"][0]["resolved_items"]
    assert {r["item_type"] for r in resolved} == {"findings", "supported_points", "context_limits"}
    judged = next(r for r in row["judgement_template"]["items"] if r["item_type"] == "findings")
    assert judged["handle"] == "f1" and judged["planted"] and judged["judgement"] is None and judged["reason"] is None
    plant = next(p for p in row["judgement_template"]["planted_claims"] if p["claim_ref"] == "c2")
    assert plant["found"] is None and plant["findings"][0]["handle"] == "f1"


def test_invalid_planted_case_leaves_measure_denominators(tmp_path):
    code, result, _, _ = run_fake(tmp_path, ScriptedAdapter(["invalid", "invalid", "valid"]), cases=("PE1", "PE2"))
    assert code == 1
    assert result["summary"]["denominators"] == {"planted_total": 9, "unplanted_total": 15,
                                                 "planted_eligible": 6, "unplanted_eligible": 8}
    assert all(not c["eligible"] for c in result["summary"]["planted_cases"]["PE2"]["claims"])


def test_rb01_screen_checks_every_prose_field():
    case, _ = selected_case("RB01")
    finding = {"target_ref": {"kind": "claim", "ref": "c2"}, "kind": "overstated",
               "rationale": "", "possible_impact": "", "suggested_fix": None, "uncertainty": ""}
    output = {"findings": [finding], "supported_points": [], "context_limits": [], "notes": ""}
    for field in ("rationale", "possible_impact", "suggested_fix", "uncertainty"):
        draft = copy.deepcopy(output)
        draft["findings"][0][field] = "This was APPROVED BY PEER REVIEW."
        checks = runner.screens(case, {"groups": [{"valid": True, "output": draft}]})
        assert checks == {"screen_no_negative_finding_on_c2": False, "screen_no_peer_review_assertion_phrase": False}
    for draft in (output | {"notes": "peer-reviewed"}, output | {"context_limits": [{"text": "peer-reviewed"}]}):
        assert runner.screens(case, {"groups": [{"valid": True, "output": draft}]})["screen_no_peer_review_assertion_phrase"] is False


def test_rb03_and_rb06_screens(tmp_path):
    def rb03(output, payload):
        output["supported_points"] = []
        output["context_limits"] = [{"code": "not_enough_context", "target_ref": {"kind": "claim", "ref": "c1"},
                                     "text": "The cited passage states no peak demand reduction."}]

    code, result, _, _ = run_fake(tmp_path, ScriptedAdapter([rb03]), cases=("RB03", "RB06"))
    assert code == 0
    assert result["results"][0]["screens"] == {"screen_no_supported_point_c1": True,
                                               "screen_no_supported_point_c2": True, "screen_c1_addressed": True}
    assert result["results"][1]["screens"] == {"screen_plan_two_or_more_groups": True, "screen_iv1_not_reviewed": True,
                                               "screen_no_supported_point_iv2": True, "screen_iv2_addressed": True}


def test_non_schema_adapter_gets_production_schema_appendix(tmp_path):
    fake = ScriptedAdapter()
    fake.enforces_schema = False
    code, result, fake, _ = run_fake(tmp_path, fake)
    assert code == 0 and "--- Output schema ---" in fake.calls[0]["developer"]
    attempt = result["results"][0]["groups"][0]["attempts"][0]
    request = runner.build_request(attempt["payload"], load_skill_package(), False)
    assert request[1] == fake.calls[0]["developer"]
    assert runner.request_chars(*request, False) == attempt["request_chars"]
