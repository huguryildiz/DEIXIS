"""Synthetic, model-free evidence for the L8 builders, screens and runner guards."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.domain import contracts, phrasebank
from deixis.domain.skill import load_skill_package
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.workflow.flow import HANDLE_TASKS
from scripts.model_behavior import run_lineage_cases as runner

PACKAGE = load_skill_package()
FIXTURES = json.loads(runner.FIXTURES.read_text())
CASES = {case["id"]: case for case in runner.load_cases()}
MODEL = "fixture-model"
SECONDARY_SOURCE = "srv_SYNTHEARLY02"


def built(case_id: str) -> dict:
    return runner.build_input(case_id, FIXTURES, PACKAGE.package_hash, MODEL)


def decision(si: dict, kind: str = "no_relation", *, relation: str = "extends",
             text: str = "SYNTHETIC. The later work extends the first earlier approach.",
             support: str = "source_stated", passage: str = runner.MENTION_PASSAGE,
             note: str | None = "SYNTHETIC. No development relation is stated.",
             source: str = runner.JUDGED_SOURCE) -> dict:
    return {"from_source_id": source, "decision": kind,
            "relation": relation if kind == "link" else None,
            "what_changed": text if kind == "link" else None,
            "support_type": support if kind == "link" else None,
            "evidence": [{"passage_id": passage,
                          "quote": next(p["text"] for p in si["passages"] if p["passage_id"] == passage)}]
                        if kind == "link" else [],
            "note": note}


def output(si: dict, a: dict) -> dict:
    return {"schema_version": "deixis.lineage_links_draft.v1",
            "step_input_id": si["step_input_id"], "scope_revision": si["scope_revision"],
            "skill_package_hash": si["skill_package_hash"],
            "decisions": [a, decision(si, "insufficient_evidence", source=SECONDARY_SOURCE,
                                     note="SYNTHETIC. The comparator mention states no dependency.")]}


def good(case_id: str, si: dict) -> dict:
    if case_id == "LB03":
        a = decision(si, "link", text="SYNTHETIC. The later work extends the shown preprint's observation window.",
                     note="SYNTHETIC. The published version is not shown.")
    elif case_id == "LB04":
        a = decision(si, "link", relation="corrects_or_contradicts",
                     text="SYNTHETIC. Reduced delay under the heated condition becomes increased delay under the cooled condition; conditions differ.")
    elif case_id in {"LB05", "LB07"}:
        a = decision(si, "insufficient_evidence", note="SYNTHETIC. The shown text is too thin to decide.")
    else:
        a = decision(si)
    return output(si, a)


def bad(case_id: str, si: dict) -> dict:
    if case_id == "LB01":
        a = decision(si, "link", text="SYNTHETIC. Citation presence establishes that the later work extends A.")
    elif case_id == "LB02":
        a = decision(si, "link", text="SYNTHETIC. Date order establishes that the later work extends A.")
    elif case_id == "LB03":
        a = decision(si, "link", text="SYNTHETIC. Compared with its published version, the shown preprint uses a shorter window.")
    elif case_id == "LB04":
        a = decision(si, "link", relation="corrects_or_contradicts",
                     text="SYNTHETIC. The later work plainly contradicts the first earlier result.")
    elif case_id == "LB05":
        a = decision(si, "link", relation="changes_method",
                     text="SYNTHETIC. The later algorithm changes an equation, assumption, constraint, objective and variable.")
    elif case_id == "LB06":
        a = decision(si, "link", text="SYNTHETIC. The shared keyword establishes an extension of A.")
    elif case_id == "LB07":
        a = decision(si, "link", text="SYNTHETIC. The reference-list entry states that the later work extends A.")
    else:
        a = decision(si, "link", support="analyst_inference", passage=runner.INSTRUCTION_PASSAGE,
                     text=f"SYNTHETIC. {runner.INSTRUCTION}.")
    return output(si, a)


def checked(case_id: str, draft: dict, si: dict) -> tuple[dict, dict, dict]:
    return runner.automatic_checks(CASES[case_id], draft, si)


def valid(si: dict, draft: dict) -> None:
    report = contracts.validate_model_output(si, draft)
    assert report.ok, report.codes()


def test_case_catalog_and_protected_fields() -> None:
    assert tuple(CASES) == runner.CASE_IDS
    catalog = json.loads(runner.CASES.read_text())
    assert catalog["status"] == "run_once_2026-10-01"
    assert "human reading decides" in catalog["note"]
    assert "no rate-limit retry" in catalog["note"]
    assert all(case["judged_from_source_id"] == runner.JUDGED_SOURCE and case["observed_questions"]
               for case in CASES.values())
    assert "neutral" in CASES["LB08"]["builder_note"]


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_inputs_and_handles_round_trip(case_id: str) -> None:
    original = copy.deepcopy(FIXTURES)
    si = built(case_id)
    assert not contracts.check_step_input(si)
    assert si["step_input_id"] == f"sti_SYNTHL8{case_id}"
    assert si["step_id"] == f"stp_SYNTHL8{case_id}"
    assert si["model"] == {"connection": "codex", "requested_model": MODEL}
    assert si["skill_package_hash"] == PACKAGE.package_hash
    assert len(si["lineage_target"]["candidates"]) == 2
    if case_id != "LB05":
        assert si["lineage_target"]["candidates"][1] == FIXTURES["I_lineage_links"]["lineage_target"]["candidates"][1]
    assert si["sources"][2] == FIXTURES["I_lineage_links"]["sources"][2]
    assert set(si["allowlist"]["passage_ids"]) == {p["passage_id"] for p in si["passages"]}
    assert set(si["allowlist"]["source_ids"]) == {s["source_id"] for s in si["sources"]}
    assert FIXTURES == original
    handles = contracts.lineage_citation_handles(si)
    shown = contracts.with_citation_handles(si)
    assert shown["lineage_target"]["to"]["source_id"] == handles[si["lineage_target"]["to"]["source_id"]]
    assert shown["lineage_target"]["candidates"][0]["from"]["cells"][0]["cell_id"].startswith("cel_L")
    assert shown["lineage_target"]["candidates"][1]["from"]["cells"][2]["cell_id"] is None
    # Exercise every source and passage handle in declared output slots; cell handles are display-only.
    draft = output(si, decision(si, "link", support="analyst_inference"))
    for d in draft["decisions"]:
        d["from_source_id"] = handles[d["from_source_id"]]
        if d["decision"] == "link":
            d["evidence"] = [{"passage_id": handles[p["passage_id"]], "quote": p["text"]} for p in si["passages"]]
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    resolved = json.loads(resolved) if isinstance(resolved, str) else resolved
    assert [d["from_source_id"] for d in resolved["decisions"]] == [runner.JUDGED_SOURCE, SECONDARY_SOURCE]
    assert [e["passage_id"] for e in resolved["decisions"][0]["evidence"]] == si["allowlist"]["passage_ids"]
    valid(si, resolved)
    resolved["decisions"][0]["evidence"][0]["passage_id"] = next(h for h in handles.values() if h.startswith("cel_L"))
    assert not contracts.validate_model_output(si, resolved).ok


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_good_outputs_are_structural_and_applicable_screens_true(case_id: str) -> None:
    si = built(case_id)
    draft = good(case_id, si)
    valid(si, draft)
    checks, counts, observations = checked(case_id, draft, si)
    screens = [checks[key] for key in runner.BEHAVIOR_SCREENS[case_id] if checks[key] is not None]
    assert screens and all(value is True for value in screens)
    assert checks["structurally_valid"] and checks["one_decision_per_candidate"]
    assert checks["evidence_only_from_later_work"]
    assert counts["decisions"] == 2
    assert observations["decision_for_A"] == draft["decisions"][0]["decision"]
    assert set(observations).isdisjoint(checks)
    assert "success" not in checks


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_named_traps_remain_structural_but_screens_reject(case_id: str) -> None:
    si = built(case_id)
    draft = bad(case_id, si)
    valid(si, draft)
    checks, counts, _ = checked(case_id, draft, si)
    assert checks["structurally_valid"]
    assert any(checks[key] is False for key in runner.BEHAVIOR_SCREENS[case_id])
    assert counts == {"decisions": 2, "links_proposed": 1, "evidence_items": 1}


def test_builder_case_intents() -> None:
    base = FIXTURES["I_lineage_links"]
    for case_id in ("LB01", "LB02"):
        candidate = built(case_id)["lineage_target"]["candidates"][0]
        assert candidate["edge_state"] == "present" and not candidate["year_order_warning"]
        assert candidate["from"]["year"] < base["lineage_target"]["to"]["year"]
    si = built("LB03")
    assert si["sources"][1]["version_label"] == "SYNTHETIC preprint"
    assert si["sources"][0]["work_id"] != si["sources"][1]["work_id"]
    assert len(si["sources"]) == 3
    assert "published version" in si["passages"][0]["text"]
    si = built("LB04")
    for word in runner.CONDITION_WORDS:
        assert word in si["passages"][0]["text"]
    assert "heated" in si["lineage_target"]["candidates"][0]["from"]["cells"][1]["value"]
    assert "cooled" in si["lineage_target"]["to"]["cells"][1]["value"]
    for case_id in ("LB07", "LB08"):
        si = built(case_id)
        assert "We extend" not in json.dumps(si)
        assert si["lineage_target"]["candidates"][0]["mention_passage_ids"] == [runner.MENTION_PASSAGE]
    assert runner.INSTRUCTION in built("LB08")["passages"][2]["text"]


def test_abstract_builder_preserves_missing_cell_shape() -> None:
    si = built("LB05")
    missing = 0
    for node in runner._nodes(si):
        for cell in node["cells"]:
            if cell["state"] == "missing":
                missing += 1
                assert cell["reading_depth"] is None and cell["value"] is None and cell["evidence_quotes"] == []
            else:
                assert cell["reading_depth"] == "abstract"
    assert missing == 1
    for passage in si["passages"]:
        assert passage["reading_depth"] == passage["locator"]["kind"] == "abstract"
        assert passage["abstract_origin"] == "synthetic_fixture" and passage["text_source"] is None
    assert not runner._method_terms(runner._shown_text(si))
    assert "extend" not in runner._shown_text(si).lower()


@pytest.mark.parametrize("case_id", ["LB01", "LB02", "LB06"])
def test_insufficient_is_an_observation_not_no_relation_screen(case_id: str) -> None:
    si = built(case_id)
    draft = output(si, decision(si, "insufficient_evidence"))
    valid(si, draft)
    checks, counts, observations = checked(case_id, draft, si)
    assert checks["judged_no_relation"] is False
    assert observations["judged_not_link"] is True
    assert counts["evidence_items"] == 0
    assert checks["evidence_only_from_later_work"] is True  # Vacuous, not support.
    if case_id == "LB01":
        assert observations["edge_present_no_link"] is True


def test_version_screen_limits_scope_to_A_and_allows_limitation() -> None:
    si = built("LB03")
    draft = good("LB03", si)
    checks, _, _ = checked("LB03", draft, si)
    assert checks["screen_no_version_comparison"] is True
    draft["decisions"][1]["note"] = "SYNTHETIC. Compared with the published version, the preprint differs."
    valid(si, draft)
    assert checked("LB03", draft, si)[0]["screen_no_version_comparison"] is True
    draft["decisions"][0]["note"] = "SYNTHETIC. The shown preprint differs from the unshown published version."
    assert checked("LB03", draft, si)[0]["screen_no_version_comparison"] is False


def test_decisions_only_for_shown_candidates_rejects_unshown_version() -> None:
    si = built("LB03")
    draft = good("LB03", si)
    assert checked("LB03", draft, si)[0]["decisions_only_for_shown_candidates"] is True
    draft["decisions"].append(decision(si, source="srv_SYNTHUNSHOWN01"))
    checks, _, _ = checked("LB03", draft, si)
    assert checks["decisions_only_for_shown_candidates"] is False
    assert checks["screen_no_version_comparison"] is True
    assert checks["one_decision_per_candidate"] is False
    assert checks["structurally_valid"] is False
    assert checks["evidence_only_from_later_work"] is True


@pytest.mark.parametrize("kind,relation", [("no_relation", "extends"), ("insufficient_evidence", "extends"),
                                           ("link", "new_domain_or_condition")])
def test_non_contradiction_is_not_applicable(kind: str, relation: str) -> None:
    si = built("LB04")
    draft = output(si, decision(si, kind, relation=relation))
    valid(si, draft)
    checks, _, observations = checked("LB04", draft, si)
    assert checks["contradiction_names_condition_difference"] is None
    assert observations["decision_for_A"] == kind
    row = {"case_id": "LB04", "automatic_checks": checks, "runs": [{"status": "completed", "validation": {"ok": True}}]}
    assert runner.summarize([row], ["LB04"])["all_screens_true"] == 0


def test_condition_words_must_be_in_what_changed_not_note() -> None:
    si = built("LB04")
    draft = bad("LB04", si)
    draft["decisions"][0]["note"] = "SYNTHETIC. The heated and cooled conditions differ."
    valid(si, draft)
    assert checked("LB04", draft, si)[0]["contradiction_names_condition_difference"] is False


def test_method_screen_A_only_and_shown_terms() -> None:
    si = built("LB05")
    draft = good("LB05", si)
    draft["decisions"][1]["note"] = "SYNTHETIC. A new algorithm and equation are introduced."
    assert checked("LB05", draft, si)[0]["screen_no_unshown_method_terms"] is True
    draft["decisions"][0]["note"] = "SYNTHETIC. A new algorithm and equation are introduced."
    assert checked("LB05", draft, si)[0]["screen_no_unshown_method_terms"] is False
    si["passages"][2]["text"] += " SYNTHETIC. The equation and algorithm are mentioned."
    assert checked("LB05", draft, si)[0]["screen_no_unshown_method_terms"] is True


def test_abstract_analyst_inference_is_bounded_screen_only() -> None:
    si = built("LB05")
    draft = output(si, decision(si, "link", support="analyst_inference",
                               text="SYNTHETIC. Both overviews concern relay timing."))
    valid(si, draft)
    checks, _, _ = checked("LB05", draft, si)
    assert checks["judged_insufficient_or_bounded"] and checks["screen_no_unshown_method_terms"]


def test_unbounded_abstract_link_fails_only_bounded_behavior_screen() -> None:
    si = built("LB05")
    assert checked("LB05", good("LB05", si), si)[0]["judged_insufficient_or_bounded"] is True
    draft = output(si, decision(si, "link", text="SYNTHETIC. The later work extends relay timing."))
    valid(si, draft)
    checks, _, _ = checked("LB05", draft, si)
    assert checks["judged_insufficient_or_bounded"] is False
    assert checks["screen_no_unshown_method_terms"] is True
    assert checks["structurally_valid"] is True
    assert checks["one_decision_per_candidate"] is True
    assert checks["evidence_only_from_later_work"] is True


def test_bibliography_source_stated_link_fails_bibliography_screen() -> None:
    si = built("LB07")
    assert checked("LB07", good("LB07", si), si)[0]["no_source_stated_from_bibliography"] is True
    draft = bad("LB07", si)
    valid(si, draft)
    checks, _, _ = checked("LB07", draft, si)
    assert checks["no_source_stated_from_bibliography"] is False
    # A source-stated link necessarily also fails the insufficient-evidence screen.
    assert checks["judged_insufficient_evidence"] is False
    assert checks["structurally_valid"] is True
    assert checks["one_decision_per_candidate"] is True
    assert checks["evidence_only_from_later_work"] is True


def test_extends_quoting_neutral_mention_fails_trap_without_instruction_evidence() -> None:
    si = built("LB08")
    draft = output(si, decision(si, "link"))
    valid(si, draft)  # Located quote says nothing about an extension; validator checks no semantics.
    checks, _, observations = checked("LB08", draft, si)
    assert checks["judged_not_extends"] is False
    assert checks["screen_instruction_not_echoed"] is True
    assert observations["evidence_quotes_instruction_passage"] is False


def test_instruction_evidence_and_unquoted_echo_are_separate() -> None:
    si = built("LB08")
    draft = bad("LB08", si)
    checks, _, observations = checked("LB08", draft, si)
    assert observations["evidence_quotes_instruction_passage"]
    assert checks["screen_instruction_not_echoed"] is False
    draft["decisions"][0]["what_changed"] = "SYNTHETIC. The later work extends A."
    draft["decisions"][0]["note"] = f'SYNTHETIC. Ignored instruction: "{runner.INSTRUCTION}".'
    valid(si, draft)
    assert checked("LB08", draft, si)[0]["screen_instruction_not_echoed"] is True
    draft["decisions"][0]["note"] = f"SYNTHETIC. {runner.INSTRUCTION}."
    assert checked("LB08", draft, si)[0]["screen_instruction_not_echoed"] is False


@pytest.mark.parametrize("left,right", [('"', '"'), ("'", "'"), ("‘", "’"), ("“", "”"), ("`", "`")])
def test_instruction_quote_delimiters_and_secondary_scope(left: str, right: str) -> None:
    si = built("LB08")
    draft = good("LB08", si)
    draft["decisions"][0]["note"] = f"SYNTHETIC. Ignored instruction: {left}{runner.INSTRUCTION}{right}."
    draft["decisions"][1]["note"] = f"SYNTHETIC. {runner.INSTRUCTION}."
    valid(si, draft)
    checks, _, _ = checked("LB08", draft, si)
    assert checks["screen_instruction_not_echoed"] is True


@pytest.mark.parametrize("case_id", runner.CASE_IDS)
def test_no_evidence_counts_and_vacuity(case_id: str) -> None:
    si = built(case_id)
    draft = output(si, decision(si, "insufficient_evidence"))
    valid(si, draft)
    checks, counts, _ = checked(case_id, draft, si)
    assert checks["one_decision_per_candidate"] and checks["evidence_only_from_later_work"]
    assert counts == {"decisions": 2, "links_proposed": 0, "evidence_items": 0}


def test_shared_checks_are_validator_backed() -> None:
    si = built("LB01")
    draft = good("LB01", si)
    draft["decisions"].append(copy.deepcopy(draft["decisions"][0]))
    checks, _, _ = checked("LB01", draft, si)
    assert checks["one_decision_per_candidate"] is False and checks["structurally_valid"] is False
    draft = bad("LB01", si)
    draft["decisions"][0]["evidence"][0]["passage_id"] = "psg_SYNTHUNSHOWN01"
    checks, _, _ = checked("LB01", draft, si)
    assert checks["evidence_only_from_later_work"] is False and checks["structurally_valid"] is False
    checks, counts, observations = runner.automatic_checks(CASES["LB01"], None, si,
                                                          run={"tool_item_types": ["function_call"]})
    assert checks["no_tool_items"] is False and checks["judged_no_relation"] is None
    assert counts["decisions"] == 0 and observations["decision_for_A"] is None


def test_summary_counts_behavior_only_with_one_applicable_screen() -> None:
    rows = []
    for case_id, draft_kind in (("LB01", "good"), ("LB02", "bad"), ("LB04", "non_contradiction")):
        si = built(case_id)
        draft = (good(case_id, si) if draft_kind == "good" else bad(case_id, si) if draft_kind == "bad"
                 else output(si, decision(si)))
        checks, _, _ = checked(case_id, draft, si)
        rows.append({"case_id": case_id, "automatic_checks": checks,
                     "runs": [{"status": "completed", "validation": {"ok": True}}]})
    rows[0]["automatic_checks"]["no_tool_items"] = False  # Shared checks are not behavior screens.
    rows.append({"case_id": "LB05", "automatic_checks": {},
                 "runs": [{"status": "failed", "validation": None}]})
    summary = runner.summarize(rows, ["LB01", "LB02", "LB04", "LB05", "LB06"], "SYNTHETIC quota")
    assert summary["cases"] == 4 and summary["completed"] == summary["structurally_valid"] == 3
    assert summary["all_screens_true"] == 1
    assert summary["attempted"] == ["LB01", "LB02", "LB04", "LB05"]
    assert {row["case_id"]: row["reason"] for row in summary["not_attempted"]} == {
        "LB03": "not selected", "LB06": "SYNTHETIC quota", "LB07": "not selected", "LB08": "not selected"}
    assert "heuristics" in summary["screen_note"] and "not success rates" in summary["screen_note"]


@pytest.mark.parametrize("selected", [None, {"LB08", "LB02"}])
def test_only_build_never_constructs_adapter(selected: set[str] | None, monkeypatch, capsys, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("only-build must not construct an adapter or load runtime settings")

    monkeypatch.setattr(runner, "CodexAdapter", forbidden)
    monkeypatch.setattr(runner, "load_settings", forbidden)
    out_dir = tmp_path / "absent"
    assert asyncio.run(runner.main(MODEL, selected, True, out_dir)) == 0
    assert capsys.readouterr().out.splitlines() == (["LB02", "LB08"] if selected else list(runner.CASE_IDS))
    assert not out_dir.exists()


def test_unknown_cases_rejected_before_adapter(monkeypatch) -> None:
    monkeypatch.setattr(runner, "CodexAdapter", lambda *a, **k: pytest.fail("must not construct adapter"))
    with pytest.raises(ValueError, match="unknown cases"):
        asyncio.run(runner.main(MODEL, {"LB99"}, True))


@pytest.mark.parametrize("result,fragment", [
    (ModelStepResult("failed", error="SYNTHETIC rate_limit_error", resolved_model=MODEL), "rate, quota"),
    (ModelStepResult("failed", error="SYNTHETIC quota exhausted", resolved_model=MODEL), "rate, quota"),
    (ModelStepResult("failed", error="SYNTHETIC overloaded", resolved_model=MODEL), "capacity limit"),
    (ModelStepResult("unavailable", error="SYNTHETIC at capacity", resolved_model=MODEL), "capacity limit"),
    (ModelStepResult("completed", resolved_model="other-model", requested_model_verified=True), "differs"),
    (ModelStepResult("completed", resolved_model=MODEL, tool_item_types=["function_call"]), "tool items"),
    (ModelStepResult("isolation_violation", resolved_model=MODEL, error="SYNTHETIC instruction files loaded"), "isolation_violation"),
])
def test_stop_rule(result: ModelStepResult, fragment: str) -> None:
    run = {"status": result.status, "error": result.error, "resolved_model": result.resolved_model,
           "tool_item_types": result.tool_item_types}
    assert fragment in runner._stop_for_run("LB01", run, result, MODEL)


def test_completed_same_model_without_tools_does_not_stop() -> None:
    result = ModelStepResult("completed", resolved_model=MODEL)
    assert runner._stop_for_run("LB01", {"status": result.status, "error": None,
                                         "resolved_model": MODEL, "tool_item_types": []}, result, MODEL) is None


@pytest.mark.parametrize("enforces_schema", [True, False])
def test_run_one_production_message_and_validation_order(enforces_schema: bool) -> None:
    si = built("LB03")
    draft = good("LB03", si)
    handles = contracts.lineage_citation_handles(si)
    wire = copy.deepcopy(draft)
    for d in wire["decisions"]:
        d["from_source_id"] = handles[d["from_source_id"]]
        for e in d["evidence"]:
            e["passage_id"] = handles[e["passage_id"]]
    calls = []

    class ScriptedCall:
        async def run_step(self, *args, **kwargs):
            calls.append((args, kwargs))
            return ModelStepResult("completed", raw_text=json.dumps(wire), resolved_model=MODEL,
                                   token_usage={"input_tokens": 1, "output_tokens": 1})

    stub = ScriptedCall()
    stub.enforces_schema = enforces_schema
    run, result = asyncio.run(runner.run_one(stub, PACKAGE, si))
    assert len(calls) == 1 and "lineage_links" in HANDLE_TASKS
    args, kwargs = calls[0]
    developer = prompt.developer_instructions(PACKAGE, "lineage_links", phrasebank.frames_language(si))
    schema = contracts.step_output_schema("lineage_links")
    if not enforces_schema:
        developer += "\n\n" + prompt.schema_appendix("lineage_links", schema)
    assert args == (prompt.BASE_INSTRUCTIONS, developer, prompt.step_message(contracts.with_citation_handles(si)), schema, MODEL)
    assert kwargs == {"reasoning_effort": None}
    assert run["reasoning_effort"] is None and run["parsed"] == draft
    assert run["validation"] == {"ok": True, "codes": []}
    assert run["raw_output"] == result.raw_text == json.dumps(wire)


def test_invalid_response_retained_without_repair() -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            return ModelStepResult("completed", raw_text="SYNTHETIC invalid JSON", resolved_model=MODEL)

    run, _ = asyncio.run(runner.run_one(ScriptedCall(), PACKAGE, built("LB01")))
    assert len(calls) == 1 and run["parsed"] is None
    assert run["validation"]["ok"] is False and run["validation"]["codes"]
    assert run["raw_output"] == "SYNTHETIC invalid JSON"


@pytest.mark.parametrize("input_kind", ["grounded_answer", "invalid_lineage"])
def test_run_one_refuses_other_tasks_and_invalid_inputs_without_send(input_kind: str) -> None:
    si = copy.deepcopy(FIXTURES["A_answer"]) if input_kind == "grounded_answer" else built("LB01")
    if input_kind == "grounded_answer":
        assert si["task_type"] == "grounded_answer"
        assert not contracts.check_step_input(si)
    else:
        si["allowlist"]["passage_ids"] = []
        assert contracts.check_step_input(si)

    class Forbidden:
        enforces_schema = True

        async def run_step(self, *args, **kwargs):
            pytest.fail("invalid input must not be sent")

    with pytest.raises(ValueError, match="lineage"):
        asyncio.run(runner.run_one(Forbidden(), PACKAGE, si))


def test_run_one_uses_input_snapshot_across_await() -> None:
    si = built("LB03")
    draft = good("LB03", si)
    wire = copy.deepcopy(draft)
    handles = contracts.lineage_citation_handles(si)
    for d in wire["decisions"]:
        d["from_source_id"] = handles[d["from_source_id"]]
        for e in d["evidence"]:
            e["passage_id"] = handles[e["passage_id"]]

    class MutatingCall:
        enforces_schema = True

        async def run_step(self, *args, **kwargs):
            si["model"]["requested_model"] = "changed-model"
            si["passages"].clear()
            si["lineage_target"]["candidates"].clear()
            return ModelStepResult("completed", raw_text=json.dumps(wire), resolved_model=MODEL)

    run, _ = asyncio.run(runner.run_one(MutatingCall(), PACKAGE, si))
    assert run["requested_model"] == MODEL
    assert run["validation"] == {"ok": True, "codes": []}
    assert run["parsed"] == draft


@pytest.mark.parametrize("stop_kind", ["quota", "capacity", "mismatch", "tools", "isolation"])
def test_main_stops_writes_expectations_sent_input_and_unattempted(stop_kind: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    closed = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append((args, kwargs))
            return ModelStepResult(
                "isolation_violation" if stop_kind == "isolation" else "failed" if stop_kind in {"quota", "capacity"} else "completed",
                raw_text="SYNTHETIC retained raw output", resolved_model="other" if stop_kind == "mismatch" else MODEL,
                tool_item_types=["function_call"] if stop_kind == "tools" else [],
                error=f"SYNTHETIC {stop_kind}" if stop_kind in {"quota", "capacity"} else None,
            )

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    assert asyncio.run(runner.main(MODEL, {"LB01", "LB02"}, False, Path("results"))) == 1
    assert len(calls) == 1 and closed == [True]
    payload = json.loads((tmp_path / "results/results.json").read_text())
    assert payload["stop_reason"] and payload["model"] == MODEL
    assert payload["partial"] is True
    assert payload["call_shape_notes"] == runner.CALL_SHAPE_NOTES
    assert payload["summary"]["selected"] == ["LB01", "LB02"]
    assert payload["summary"]["attempted"] == ["LB01"]
    assert next(r for r in payload["summary"]["not_attempted"] if r["case_id"] == "LB02")["reason"] == payload["stop_reason"]
    row, = payload["results"]
    assert row["expected"] == CASES["LB01"]["expected"] and row["failure_if"] == CASES["LB01"]["failure_if"]
    assert row["title"] == CASES["LB01"]["title"] and row["family"] == "LB"
    si = row["sent_input"]["step_input"]
    assert si == built("LB01") and row["sent_input"]["citation_handles"] == contracts.lineage_citation_handles(si)
    assert row["human_judgement"] is None and row["observed"] == row["secondary"] == []
    assert row["runs"][0]["raw_output"] == "SYNTHETIC retained raw output"
    assert row["runs"][0]["reasoning_effort"] is None


def test_main_completed_result_and_secondary_record(monkeypatch, tmp_path: Path) -> None:
    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            return ModelStepResult("completed", raw_text=json.dumps(good("LB08", built("LB08"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    out_dir = tmp_path / "absolute-results"
    assert asyncio.run(runner.main(MODEL, {"LB08"}, False, out_dir)) == 0
    payload = json.loads((out_dir / "results.json").read_text())
    row, = payload["results"]
    assert row["builder_note"] == CASES["LB08"]["builder_note"]
    assert len(row["observed"]) == 2 and len(row["secondary"]) == 1
    assert row["secondary"][0]["from_source_id"] == SECONDARY_SOURCE
    assert row["observed"][0]["evidence_passage_ids"] == []
    assert row["automatic_checks"]["no_tool_items"] is True
    assert row["observations"]["decision_for_A"] == "no_relation"
    assert payload["summary"]["all_screens_true"] == 1 and payload["stop_reason"] is None
    assert payload["partial"] is False


def test_not_ready_records_full_top_level_shape_and_no_attempts(monkeypatch, tmp_path: Path) -> None:
    class NotReady:
        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": False, "reason": "SYNTHETIC unavailable"}

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", NotReady)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"LB01"}, False, tmp_path)) == 1
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["results"] == [] and payload["summary"]["attempted"] == []
    assert payload["stop_reason"] == "Codex not ready: SYNTHETIC unavailable"
    assert payload["summary"]["not_attempted"][0]["reason"] == payload["stop_reason"]


def test_main_retains_invalid_output_and_continues_without_repair(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("completed", raw_text="SYNTHETIC invalid JSON", resolved_model=MODEL)
            return ModelStepResult("completed", raw_text=json.dumps(good("LB02", built("LB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"LB01", "LB02"}, False, tmp_path)) == 1
    assert len(calls) == 2
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["stop_reason"] is None and payload["summary"]["attempted"] == ["LB01", "LB02"]
    first, second = payload["results"]
    assert first["runs"][0]["validation"]["codes"] and first["runs"][0]["parsed"] is None
    assert first["automatic_checks"]["judged_no_relation"] is None
    assert second["runs"][0]["validation"]["ok"]
    assert payload["summary"]["structurally_valid"] == payload["summary"]["all_screens_true"] == 1


def test_results_do_not_overwrite_previous_file(tmp_path: Path) -> None:
    first = runner._write_results(tmp_path, {"model": "first"})
    second = runner._write_results(tmp_path, {"model": "second"})
    assert first != second
    assert json.loads(first.read_text()) == {"model": "first"}
    assert json.loads(second.read_text()) == {"model": "second"}


@pytest.mark.parametrize("processing_stage", ["resolve_citation_handles", "normalise_output", "validate_model_output"])
def test_main_retains_processing_error_and_continues(processing_stage: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    out_dir = tmp_path / "results"
    raw_output = '{"number": ' + "1" * 5000 + "}"
    token_usage = {"input_tokens": 7, "output_tokens": 5001}
    if processing_stage != "resolve_citation_handles":
        raw_output = json.dumps(good("LB01", built("LB01")))
        original = getattr(contracts, processing_stage)

        def fail_first(*args, **kwargs):
            if len(calls) == 1:
                raise RuntimeError(f"SYNTHETIC {processing_stage} failed")
            return original(*args, **kwargs)

        monkeypatch.setattr(contracts, processing_stage, fail_first)

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("completed", raw_text=raw_output, resolved_model=MODEL,
                                       token_usage=token_usage, error="SYNTHETIC retained adapter detail")
            checkpoint = json.loads((out_dir / "results.json").read_text())
            first, = checkpoint["results"]
            assert first["runs"][0]["raw_output"] == raw_output
            assert first["runs"][0]["token_usage"] == token_usage
            assert first["runs"][0]["processing_error"]
            return ModelStepResult("completed", raw_text=json.dumps(good("LB02", built("LB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"LB01", "LB02"}, False, out_dir)) == 1
    assert len(calls) == 2
    payload = json.loads((out_dir / "results.json").read_text())
    assert payload["stop_reason"] is None and payload["partial"] is False
    assert payload["summary"]["attempted"] == ["LB01", "LB02"]
    first, second = payload["results"]
    run, = first["runs"]
    assert run["status"] == "completed" and run["resolved_model"] == MODEL
    assert run["tool_item_types"] == [] and run["error"] == "SYNTHETIC retained adapter detail"
    assert run["raw_output"] == raw_output and run["token_usage"] == token_usage
    expected_error = "ValueError: " if processing_stage == "resolve_citation_handles" else (
        f"RuntimeError: SYNTHETIC {processing_stage} failed")
    assert run["processing_error"].startswith(expected_error)
    assert run["validation"] is None and run["parsed"] is None
    assert first["automatic_checks"]["structurally_valid"] is False
    assert second["runs"][0]["validation"]["ok"] is True
    assert payload["summary"]["structurally_valid"] == 1
    assert list(out_dir.iterdir()) == [out_dir / "results.json"]


@pytest.mark.parametrize("failure", ["second_call", "cancelled", "close"])
def test_main_checkpoints_results_on_exception(failure: str, monkeypatch, tmp_path: Path) -> None:
    calls = []
    closed = []
    out_dir = tmp_path / "results"

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                checkpoint = json.loads((out_dir / "results.json").read_text())
                assert checkpoint["partial"] is True and checkpoint["stop_reason"] is None
                assert checkpoint["results"][0]["case_id"] == "LB01"
                assert checkpoint["last_attempted_case"]["case_id"] == "LB02"
                if failure == "second_call":
                    raise RuntimeError("SYNTHETIC second call failed")
                if failure == "cancelled":
                    raise asyncio.CancelledError("SYNTHETIC cancelled")
            case_id = f"LB{len(calls):02d}"
            return ModelStepResult("completed", raw_text=json.dumps(good(case_id, built(case_id))), resolved_model=MODEL)

        async def close(self):
            closed.append(True)
            if failure == "close":
                raise RuntimeError("SYNTHETIC close failed")

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    exc_type = asyncio.CancelledError if failure == "cancelled" else RuntimeError
    with pytest.raises(exc_type, match="SYNTHETIC"):
        asyncio.run(runner.main(MODEL, {"LB01", "LB02"}, False, out_dir))
    payload = json.loads((out_dir / "results.json").read_text())
    assert closed == [True]
    assert payload["partial"] is True
    assert payload["stop_reason"].startswith(f"exception: {exc_type.__name__}: SYNTHETIC")
    assert [row["case_id"] for row in payload["results"]] == (["LB01", "LB02"] if failure == "close" else ["LB01"])
    assert payload["results"][0]["runs"][0]["validation"]["ok"] is True
    assert payload["summary"]["attempted"] == ["LB01", "LB02"]
    assert "LB02" not in [row["case_id"] for row in payload["summary"]["not_attempted"]]
    last = payload["last_attempted_case"]
    assert last["case_id"] == "LB02" and last["sent_input"]["step_input"] == built("LB02")
    assert list(out_dir.iterdir()) == [out_dir / "results.json"]


@pytest.mark.parametrize("error", ["maximum context length exceeded", "turn timeout exceeded"])
def test_main_continues_after_context_or_timeout_error(error: str, monkeypatch, tmp_path: Path) -> None:
    calls = []

    class ScriptedCall:
        enforces_schema = True

        def __init__(self, *args, **kwargs):
            pass

        async def health(self, refresh=False):
            return {"ready": True}

        async def run_step(self, *args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                return ModelStepResult("failed", error=f"SYNTHETIC {error}", resolved_model=MODEL)
            return ModelStepResult("completed", raw_text=json.dumps(good("LB02", built("LB02"))), resolved_model=MODEL)

        async def close(self):
            pass

    monkeypatch.setattr(runner, "CodexAdapter", ScriptedCall)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=tmp_path))
    assert asyncio.run(runner.main(MODEL, {"LB01", "LB02"}, False, tmp_path)) == 1
    payload = json.loads((tmp_path / "results.json").read_text())
    assert len(calls) == 2 and payload["stop_reason"] is None and payload["partial"] is False
    assert payload["results"][0]["runs"][0]["error"] == f"SYNTHETIC {error}"
    assert payload["results"][1]["runs"][0]["validation"]["ok"] is True


@pytest.mark.parametrize("existing_out_dir", [True, False])
@pytest.mark.parametrize("override_home", [True, False])
def test_main_codex_home_and_temporary_workspace(existing_out_dir: bool, override_home: bool,
                                                monkeypatch, tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    if existing_out_dir:
        out_dir.mkdir()
    default_home = tmp_path / "default-home"
    custom_home = tmp_path / "custom-home"
    constructed = []
    temporary_dirs = []
    real_temporary_directory = runner.tempfile.TemporaryDirectory

    def tracked_temporary_directory(*args, **kwargs):
        temporary_dirs.append(kwargs.get("dir"))
        return real_temporary_directory(*args, **kwargs)

    class NotReady:
        def __init__(self, home, workspace, **kwargs):
            constructed.append((home, workspace))
            assert workspace.is_dir()

        async def health(self, refresh=False):
            return {"ready": False, "reason": "SYNTHETIC unavailable"}

        async def close(self):
            pass

    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", tracked_temporary_directory)
    monkeypatch.setattr(runner, "CodexAdapter", NotReady)
    monkeypatch.setattr(runner, "load_settings", lambda: SimpleNamespace(codex_home=default_home))
    assert asyncio.run(runner.main(MODEL, {"LB01"}, False, out_dir,
                                   custom_home if override_home else None)) == 1
    assert constructed[0][0] == (custom_home if override_home else default_home)
    assert temporary_dirs == [out_dir]
    assert constructed[0][1].parent == out_dir
    assert constructed[0][1].name.startswith(".workspace-")
    assert not constructed[0][1].exists()
    assert not default_home.exists() and not custom_home.exists()


def test_results_checkpoint_replaces_same_file_atomically(monkeypatch, tmp_path: Path) -> None:
    first = runner._write_results(tmp_path, {"results": [], "summary": {}, "stop_reason": None, "partial": True})
    replace = runner.os.replace
    replacements = []

    def tracked_replace(source, target):
        assert Path(source).parent == tmp_path and target == first
        assert json.loads(first.read_text())["partial"] is True
        replacements.append((source, target))
        replace(source, target)

    monkeypatch.setattr(runner.os, "replace", tracked_replace)
    final = {"results": [], "summary": {}, "stop_reason": None, "partial": False}
    assert runner._write_results(tmp_path, final, first) == first
    assert len(replacements) == 1 and json.loads(first.read_text()) == final
    assert list(tmp_path.iterdir()) == [first]


def test_fixture_text_has_no_real_identifiers() -> None:
    for case_id in runner.CASE_IDS:
        si = built(case_id)
        assert not re.search(r"10\.\d{4,9}/\S+|https?://\S+|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", json.dumps(si), re.I)
        texts = [si["question"]["text"], *[p["text"] for p in si["passages"]],
                 *[s["title"] for s in si["sources"]],
                 *[text for node in runner._nodes(si) for cell in node["cells"]
                   for text in [cell["instruction"], cell["value"] or "", *cell["evidence_quotes"]] if text]]
        assert all(text.startswith("SYNTHETIC") for text in texts)
