"""The model's advice on each term-inflation warning of the approval card (D232, D233: information only).

Every question, term and count here is SYNTHETIC, OpenAlex is mocked and the model is the fake adapter, so passing
shows workflow behavior: when the call is made, what is stored and shown, and that no run waits on it or acts on it. It
says nothing about whether a model advises well; no real model was asked.
"""

import json
from pathlib import Path

from deixis.domain import contracts
from deixis.domain.rules import ADVICE_CALLS, LITERATURE_TASKS, NO_REPAIR_TASKS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES, integrity_issues, load_skill_package
from deixis.models.adapter import ModelStepResult
from fakes import FakeAdapter, envelope, valid_response
from test_search_query import (GATE, WITHOUT_BROAD, WITHOUT_NARROW, OpenAlex, calls, client_for, set_stored, start,
                               step_output, two_setting_terms, wait)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text())["G_term_advice"]
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]
COUNTS = {GATE: 18_369, WITHOUT_BROAD: 535, WITHOUT_NARROW: 17_500}


def waiting_card(client, rid, run_id):
    return next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)["approval"]


def asked(adapter):
    return calls(adapter, "term_advice")


# ---- the contract of one call -------------------------------------------------------------------------------

def test_the_task_is_registered_with_its_schema_its_method_file_and_no_repair():
    assert contracts.TASK_OUTPUTS["term_advice"] == ("TermAdvice",)
    assert contracts.SCHEMA_VERSIONS["TermAdvice"] == "deixis.term_advice.v1"
    assert RUNTIME_FILES["term_advice"] == ("SKILL.md", "references/term-advice.md")
    assert "term_advice" in LITERATURE_TASKS and "term_advice" in NO_REPAIR_TASKS
    assert schema_repairs("term_advice") == 0 and ADVICE_CALLS == 1
    schema = contracts.step_output_schema("term_advice")
    assert set(schema["properties"]["advice"]["items"]["properties"]) == {"phrase", "recommendation", "reason"}
    assert contracts.strict_compatibility_issues(schema) == []


def test_the_method_package_is_intact_and_carries_the_new_file():
    assert integrity_issues() == []
    package = load_skill_package()
    assert "references/term-advice.md" in package.files
    assert "deixis.term_advice.v1" in package.runtime_text("term_advice")


def test_the_fake_adapter_answers_the_task_with_valid_advice():
    assert contracts.check_step_input(STEP_INPUT) == []
    report = contracts.validate_model_output(STEP_INPUT, valid_response(STEP_INPUT))
    assert report.ok, [vars(i) for i in report.issues]
    assert report.output_type == "TermAdvice"


def test_the_fixture_cases_are_judged_as_the_slice_says():
    for case in (c for c in CASES if c["name"].startswith("term_advice")):
        report = contracts.validate_model_output(STEP_INPUT, case["output"])
        assert report.codes() == sorted(case["expect_codes"]), case["name"]
        assert report.ok is case["expect_ok"], case["name"]


def test_the_advice_target_belongs_to_this_task_and_its_allowlist_is_the_warned_phrases():
    without = json.loads(json.dumps(STEP_INPUT))
    del without["advice_target"]
    assert "advice_target_mismatch" in {i.code for i in contracts.check_step_input(without)}
    elsewhere = json.loads(json.dumps(json.loads((FIXTURES / "step-inputs.json").read_text())["A_answer"]))
    elsewhere["advice_target"] = STEP_INPUT["advice_target"]
    assert "advice_target_mismatch" in {i.code for i in contracts.check_step_input(elsewhere)}
    wider = json.loads(json.dumps(STEP_INPUT))
    wider["allowlist"]["phrases"] += ["wind integrated transmission grid"]
    assert "phrase_allowlist_mismatch" in {i.code for i in contracts.check_step_input(wider)}


# ---- the run around it --------------------------------------------------------------------------------------

def test_a_warning_gets_advice_once_and_the_card_shows_it_with_the_model(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="ask")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "protocol_approval_needed")
    (call,) = asked(adapter)
    assert [w["phrase"] for w in call["advice_target"]["warnings"]] == ["broad setting"]
    assert call["allowlist"]["phrases"] == ["broad setting"]
    assert call["advice_target"]["warnings"][0]["matches_without_term"] == 535
    assert [s["operation_key"] for s in run["steps"]].count("term_advice:1") == 1
    card = waiting_card(client, rid, run_id)
    (warning,) = card["warnings"]
    assert warning["advice"]["recommendation"] == "keep" and warning["advice"]["reason"].startswith("SYNTHETIC")
    assert card["advice_model"] == {"connection": "fake", "model": "fake-model"}


def test_a_run_without_a_warning_makes_no_advice_call(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms)
    client = client_for(tmp_path, monkeypatch, OpenAlex({GATE: 600}), adapter, approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed" and asked(adapter) == []


def test_a_failed_call_under_ask_leaves_the_card_without_advice(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms,
                          fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "term_advice" else None)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="ask")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "protocol_approval_needed")
    card = waiting_card(client, rid, run_id)
    assert card["warnings"][0]["advice"] is None and card["advice_model"] is None
    assert step_output(client, run_id, "protocol_approval")["advice"] == {}


def not_warned(si):
    if si["task_type"] != "term_advice":
        return two_setting_terms(si)
    return json.dumps(envelope(si, "deixis.term_advice.v1") | {"advice": [
        {"phrase": "narrow setting", "recommendation": "remove", "reason": "SYNTHETIC: not warned."}]})


def missing(si):
    if si["task_type"] != "term_advice":
        return two_setting_terms(si)
    return json.dumps(envelope(si, "deixis.term_advice.v1") | {"advice": []})


def test_advice_for_a_phrase_that_was_not_warned_is_not_used(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), FakeAdapter(not_warned), approval="ask")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["pause_reason"] == "protocol_approval_needed"
    assert waiting_card(client, rid, run_id)["warnings"][0]["advice"] is None


def test_advice_that_misses_a_warned_phrase_is_not_used_and_warn_goes_on(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), FakeAdapter(missing), approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    stored = step_output(client, run_id, "protocol_approval")
    assert stored["advice"] == {}
    record = stored["approval"]
    assert (record["approved_by"], record["asked"], record["advice_given"]) == ("warn_kept", False, False)
    assert [r["recommendation"] for r in record["advice"]] == [None]


def test_a_resumed_run_returns_the_stored_advice_and_does_not_call_again(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="ask")
    rid, run_id = start(client)
    wait(client, rid, run_id)
    stored = step_output(client, run_id, "protocol_approval")["advice"]
    assert len(asked(adapter)) == 1

    def lose_it(output):
        output.pop("advice"), output.pop("advice_model")
        return output
    set_stored(client, run_id, "protocol_approval", lose_it)
    client.app.state.store.resume_run(run_id)
    client.app.state.worker.wake()
    _, run = wait(client, rid, run_id)
    assert run["pause_reason"] == "protocol_approval_needed"
    assert len(asked(adapter)) == 1  # the model step had succeeded: its stored output answers
    assert step_output(client, run_id, "protocol_approval")["advice"] == stored


def test_a_spent_call_budget_leaves_the_run_going_with_every_term_kept(tmp_path, monkeypatch):
    holder = {}

    class Spending(OpenAlex):
        def __call__(self, request):
            # The last count the approval check asks is the moment the run's calls run out.
            if request.url.params.get("search.title_and_abstract") == WITHOUT_NARROW and "run_id" in holder:
                holder["client"].app.state.store.add_usage(holder["run_id"], "model_calls", 10_000)
            return super().__call__(request)

    adapter = FakeAdapter(two_setting_terms)
    client = client_for(tmp_path, monkeypatch, Spending(COUNTS), adapter, approval="warn")
    holder["client"] = client
    rid = client.post("/api/researches", json={"question": "SYNTHETIC question about two settings and one task",
                                              "model_connection": "fake", "requested_model": "fake-model",
                                              "effort": "quick"}).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    holder["run_id"] = run_id
    _, run = wait(client, rid, run_id)
    assert asked(adapter) == []
    assert run["pause_reason"] != "protocol_approval_needed"
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    record = step_output(client, run_id, "protocol_approval")["approval"]
    assert (record["approved_by"], record["advice_given"], record["term_edits"]) == ("warn_kept", False, 0)


# ---- the advice shown: the run goes on without asking anyone and keeps every term -----------------------------

def removing(si):
    if si["task_type"] != "term_advice":
        return two_setting_terms(si)
    return json.dumps(envelope(si, "deixis.term_advice.v1") | {"advice": [
        {"phrase": w["phrase"], "recommendation": "remove", "reason": "SYNTHETIC: a general word."}
        for w in si["advice_target"]["warnings"]]})


def test_a_remove_recommendation_is_shown_and_not_applied_and_the_run_goes_on(tmp_path, monkeypatch):
    adapter = FakeAdapter(removing)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    stored = step_output(client, run_id, "protocol_approval")
    record = stored["approval"]
    assert (record["approved_by"], record["asked"], record["reason"], record["edited"]) == ("warn_kept", False, "warn_kept", False)
    assert record["term_edits"] == 0 and record["advice_given"] is True
    (row,) = record["advice"]
    assert row == {"phrase": "broad setting", "block": "setting", "recommendation": "remove",
                   "reason": "SYNTHETIC: a general word.", "matches": 18_369, "matches_without_term": 535}
    assert record["advice_model"] == {"connection": "fake", "model": "fake-model"}
    assert [t["phrase"] for t in stored["approved"]["vocabulary"]["terms"] if t["block"] == "setting"] == [
        "narrow setting", "broad setting"]
    card = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)["approval"]
    assert card["status"] == "approved" and card["approved_by"] == "warn_kept" and card["advice_given"] is True
    assert card["advice_applied"][0]["recommendation"] == "remove"
    assert len(asked(adapter)) == 1


def test_a_keep_recommendation_is_recorded_and_changes_nothing(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), FakeAdapter(two_setting_terms), approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    record = step_output(client, run_id, "protocol_approval")["approval"]
    assert record["approved_by"] == "warn_kept" and record["edited"] is False and record["term_edits"] == 0
    assert [r["recommendation"] for r in record["advice"]] == ["keep"]


def test_a_run_whose_advice_failed_goes_on_under_warn_with_every_term_kept(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms, fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "term_advice" else None)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    record = step_output(client, run_id, "protocol_approval")["approval"]
    assert (record["approved_by"], record["asked"], record["advice_given"], record["advice_model"]) == (
        "warn_kept", False, False, None)
    assert record["advice"][0]["recommendation"] is None and record["term_edits"] == 0


def test_a_warn_kept_run_is_not_an_earlier_approval_for_the_next_run(tmp_path, monkeypatch):
    adapter = FakeAdapter(removing)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="warn")
    rid, first = start(client)
    wait(client, rid, first, ("completed", "failed"))
    second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    wait(client, rid, second, ("completed", "failed"))
    assert step_output(client, second, "protocol_approval")["approval"]["approved_by"] == "warn_kept"
    assert len(asked(adapter)) == 2  # the second run asked again; the first run's record was nobody's approval


def test_a_warn_run_resumed_after_failed_advice_asks_nobody_again_and_keeps_every_term(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_setting_terms, fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "term_advice" else None)
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), adapter, approval="warn")
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    before = len(asked(adapter))
    assert before == 1

    def reopen(output):
        for key in ("approved", "approval", "edits", "skipped_edits", "suggestions"):
            output.pop(key, None)
        return output
    set_stored(client, run_id, "protocol_approval", reopen)
    store = client.app.state.store
    store.conn.execute("UPDATE run_steps SET status = 'pending' WHERE run_id = ? AND operation_key = 'protocol_approval'",
                       (run_id,))
    store.conn.execute("UPDATE runs SET status = 'paused', pause_reason = 'protocol_approval_needed' WHERE id = ?", (run_id,))
    store.resume_run(run_id)
    client.app.state.worker.wake()
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    assert len(asked(adapter)) == before  # the failed model step is stored: nothing is asked a second time
    record = step_output(client, run_id, "protocol_approval")["approval"]
    assert (record["approved_by"], record["advice_given"], record["term_edits"]) == ("warn_kept", False, 0)


def test_a_run_recorded_before_d233_as_model_advice_is_shown_as_what_it_did(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, OpenAlex(COUNTS), FakeAdapter(removing), approval="warn")
    rid, run_id = start(client)
    wait(client, rid, run_id, ("completed", "failed"))

    def old(output):
        record = output["approval"]
        record["approved_by"] = record["reason"] = "model_advice"
        record.pop("advice_given")
        record["advice"] = [row | {"applied": True} for row in record["advice"]]
        return output
    set_stored(client, run_id, "protocol_approval", old)
    card = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)["approval"]
    assert card["approved_by"] == "model_advice" and card["advice_given"] is True
    assert card["advice_applied"][0]["recommendation"] == "remove" and card["advice_applied"][0]["applied"] is True
