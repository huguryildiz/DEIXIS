"""Scripted model sessions, stop gates and interrupted-write recovery."""

import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from deixis.domain import contracts
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow import flow as flow_module
from deixis.workflow.review import run as reviews
from deixis.workflow.review.store import ReviewStore, resolve_finding
from tests.fakes import FakeAdapter, valid_response
from tests.review.review_helpers import report_with_sections, review_lib
from tests.review.review_run_helpers import review_api, body, start, read, turn, control, two_groups, finding_response


class Crash(BaseException):
    """Interrupt outside Worker's ordinary exception-to-failed path."""


@pytest.fixture
def api(review_lib, tmp_path):
    with review_api(review_lib, tmp_path) as api:
        yield api


def session_count(api, run_id):
    return api.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE run_id = ?", (run_id,)).fetchone()[0]


def transport_schema_saving(enforces_schema):
    canonical = contracts.step_output_schema("owner_review")
    wire = contracts.model_output_schema("owner_review")
    if enforces_schema:
        render = lambda schema: json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
    else:
        render = lambda schema: prompt.schema_appendix("owner_review", schema)
    return len(render(canonical)) - len(render(wire))


@pytest.mark.parametrize("schema_mode", [True, False])
def test_preview_figure_conservatively_bounds_first_send_full_size_in_both_modes(api, schema_mode):
    api.adapter.enforces_schema = schema_mode
    opened, _, shown = start(api)
    turn(api)
    row = api.conn.execute("SELECT * FROM step_inputs WHERE run_id = ?", (opened["run"]["id"],)).fetchone()
    size = reviews.request_chars(row["base_instructions"], row["developer_instructions"], row["user_message"], json.loads(row["output_schema_json"]), schema_mode)
    # D198 deliberately retains the larger canonical schema for the preview estimate.
    saving = transport_schema_saving(schema_mode)
    assert saving > 0 and size + saving == shown["characters_to_be_sent"]
    assert json.loads(row["payload_json"])["review_input"]["owner_note"] is None


@pytest.mark.parametrize("schema_mode", [True, False])
@pytest.mark.parametrize("repair", [False, True])
def test_full_request_and_repair_size_refused_before_session_start(api, monkeypatch, schema_mode, repair):
    api.adapter.enforces_schema = schema_mode
    opened, _, shown = start(api)
    flow = api.app.state.worker.flow
    run_id = opened["run"]["id"]
    original = flow._model_step
    limit = shown["characters_to_be_sent"] - transport_schema_saving(schema_mode) + (100 if repair else -1)
    if repair:
        api.adapter.responder = lambda si: json.dumps({"notes": "x" * 30000})

    async def smaller_limit(*args, **kwargs):
        return await original(*args, **(kwargs | {"max_request_chars": limit}))
    monkeypatch.setattr(flow, "_model_step", smaller_limit)
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "failed" and card["failure_reason"] == "nothing_reviewed"
    reason = "repair_message_too_large" if repair else "message_too_large"
    assert {r["reason"] for r in card["not_reviewed"]} == {reason}
    assert session_count(api, run_id) == len(api.adapter.calls) == (1 if repair else 0)
    rows = api.conn.execute("SELECT * FROM step_inputs WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    blocked = rows[-1]
    measured = reviews.request_chars(blocked["base_instructions"], blocked["developer_instructions"], blocked["user_message"], json.loads(blocked["output_schema_json"]), schema_mode)
    assert measured > limit and len(rows) == (2 if repair else 1)
    if not repair:
        assert len(blocked["user_message"]) < limit
    assert all(r["request_chars"] == measured and r["step_input_id"] == blocked["id"] for r in card["not_reviewed"])


def test_rate_limit_resend_rechecks_used_budget_and_starts_no_second_session(api, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    opened, _, _ = start(api)
    api.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps({"max_model_calls": 1, "max_provider_requests": 0}), opened["run"]["id"]))
    api.adapter.fail = lambda si: ModelStepResult("failed", error="429 SYNTHETIC rate limit")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "paused" and card["pause_reason"] == "budget_exhausted"
    assert session_count(api, opened["run"]["id"]) == len(api.adapter.calls) == 1
    assert api.store.run(opened["run"]["id"])["usage"]["model_calls"] == 1


def test_rate_limit_resend_refused_after_deadline(api, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    opened, _, _ = start(api)
    deadline = opened["run"]["target"]["deadline_at"]
    def limited(si):
        monkeypatch.setattr(flow_module, "now", lambda: deadline)
        return ModelStepResult("failed", error="429 SYNTHETIC rate limit")
    api.adapter.fail = limited
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "failed" and card["failure_reason"] == "nothing_reviewed"
    assert {r["reason"] for r in card["not_reviewed"]} == {"deadline_passed"}
    assert session_count(api, opened["run"]["id"]) == len(api.adapter.calls) == 1


def test_resume_past_deadline_sends_nothing_and_keeps_deadline(api, monkeypatch):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    control(api, run_id, "pause")
    deadline = opened["run"]["target"]["deadline_at"]
    assert datetime.fromisoformat(deadline) - datetime.fromisoformat(opened["run"]["created_at"]) < timedelta(hours=24, seconds=1)
    monkeypatch.setattr(flow_module, "now", lambda: deadline)
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "failed"
    assert len(card["not_reviewed"]) == 2 and {r["reason"] for r in card["not_reviewed"]} == {"deadline_passed"}
    assert not api.adapter.calls and session_count(api, run_id) == 0
    assert api.store.run(run_id)["target"]["deadline_at"] == deadline


@pytest.mark.parametrize("resume_after", ["normal", "deadline", "package"])
def test_crash_after_success_before_findings_recovers_once_before_send_gate(api, monkeypatch, resume_after):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    add = ReviewStore.add_group_findings
    def crash(*args, **kwargs):
        raise Crash("SYNTHETIC before findings")
    monkeypatch.setattr(ReviewStore, "add_group_findings", crash)
    with pytest.raises(Crash):
        turn(api)
    assert len(api.adapter.calls) == 1
    assert not ReviewStore(api.conn).findings(opened["review"]["id"])
    api.client.portal.call(api.app.state.worker.recover)
    assert read(api, opened["review"]["id"])["state"] == "paused"
    assert api.store.run(run_id)["usage"]["model_calls"] == session_count(api, run_id) == 1
    monkeypatch.setattr(ReviewStore, "add_group_findings", add)
    if resume_after == "deadline":
        monkeypatch.setattr(flow_module, "now", lambda: opened["run"]["target"]["deadline_at"])
    elif resume_after == "package":
        flow = api.app.state.worker.flow
        flow.deps.package = replace(flow.deps.package, package_hash="sha256:" + "0" * 64)
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert len(card["findings"]) == (2 if resume_after == "normal" else 1)
    assert len(api.adapter.calls) == (2 if resume_after == "normal" else 1)
    assert api.store.run(run_id)["usage"]["model_calls"] == session_count(api, run_id) == len(api.adapter.calls)
    assert card["state"] == {"normal": "completed", "deadline": "partial", "package": "failed"}[resume_after]
    if resume_after == "package":
        assert card["failure_reason"] == "skill_package_changed"
    if resume_after == "deadline":
        assert {r["reason"] for r in card["not_reviewed"]} == {"deadline_passed"}


def test_package_change_between_groups_keeps_first_findings_and_fails(api, monkeypatch):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    flow = api.app.state.worker.flow
    add = ReviewStore.add_group_findings
    def added(*args, **kwargs):
        result = add(*args, **kwargs)
        flow.deps.package = replace(flow.deps.package, package_hash="sha256:" + "0" * 64)
        return result
    monkeypatch.setattr(ReviewStore, "add_group_findings", added)
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "failed" and card["failure_reason"] == "skill_package_changed"
    assert len(card["findings"]) == len(api.adapter.calls) == 1


def test_failed_validation_group_and_successful_final_group_yield_partial_coverage(api, monkeypatch):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    def responder(si):
        if si["review_input"]["group_index"] == 1:
            return "invalid JSON"
        api.store.update_run(run_id, status="pause_requested")
        return finding_response(si)
    api.adapter.responder = responder
    turn(api)
    # The final group succeeds with no unfinished work left to pause.
    card = read(api, opened["review"]["id"])
    assert card["state"] == "partial"
    assert len(api.adapter.calls) == 3
    assert len(card["not_reviewed"]) == 1


def test_invalid_group_then_second_group_pause_resume_keeps_failed_group(api, monkeypatch):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    api.adapter.responder = lambda si: "invalid JSON" if si["review_input"]["group_index"] == 1 else finding_response(si)
    health = api.adapter.health
    async def pause_health(*args, **kwargs):
        if len(api.adapter.calls) == 2:
            api.store.update_run(run_id, status="pause_requested")
        return await health(*args, **kwargs)
    monkeypatch.setattr(api.adapter, "health", pause_health)
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "paused"
    assert len(api.adapter.calls) == 2
    monkeypatch.setattr(api.adapter, "health", health)
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "partial" and len(card["not_reviewed"]) == 1
    assert [c["review_input"]["group_index"] for c in api.adapter.calls] == [1, 1, 2]
    assert len(card["findings"]) == 1


def test_crash_between_validation_and_repair_resumes_only_one_repair(api, monkeypatch):
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    api.adapter.responder = lambda si: "invalid JSON"
    store = api.store
    finish = store.finish_model_session
    def after_validation(*args, **kwargs):
        finish(*args, **kwargs)
        if kwargs.get("validation_json"):
            raise Crash("SYNTHETIC after validation")
    monkeypatch.setattr(store, "finish_model_session", after_validation)
    with pytest.raises(Crash):
        turn(api)
    api.client.portal.call(api.app.state.worker.recover)
    monkeypatch.setattr(store, "finish_model_session", finish)
    api.adapter.responder = finding_response
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "completed" and len(api.adapter.calls) == 2
    rows = api.conn.execute("SELECT attempt, user_message FROM step_inputs WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    assert [r["attempt"] for r in rows] == [0, 1]
    assert "previous output" in rows[1]["user_message"]


def test_outcome_unknown_waits_for_user_resume_and_usage_is_not_reset(api):
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    api.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC uncertain delivery", delivery_class="after_send_unknown")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "paused" and card["outcome_unknown"]
    api.client.portal.call(api.app.state.worker.recover)
    turn(api)
    assert len(api.adapter.calls) == session_count(api, run_id) == 1
    api.adapter.fail = None
    control(api, run_id, "resume")
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "completed"
    assert len(api.adapter.calls) == session_count(api, run_id) == api.store.run(run_id)["usage"]["model_calls"] == 2


@pytest.mark.parametrize("stop", [None, "pause", "cancel"])
def test_scope_revision_mid_call_uses_snapshot_revision_and_honors_stop(api, monkeypatch, stop):
    two_groups(api, monkeypatch)
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    def before(si):
        if len(api.adapter.calls) == 1:
            api.store.revise_scope(api.rid, api.store.research(api.rid)["version"], "SYNTHETIC revised question?", None)
            if stop:
                api.store.update_run(run_id, status="pause_requested" if stop == "pause" else "cancelled")
    api.adapter.before = before
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == {None: "completed", "pause": "paused", "cancel": "cancelled"}[stop]
    assert {si["scope_revision"] for si in api.adapter.calls} == {1}
    assert "scope_revised" in {r["code"] for r in card["stale_reasons"]}
    assert len(api.adapter.calls) == (2 if stop is None else 1)


@pytest.mark.parametrize("problem,reason", [("mismatch", "model_mismatch"), ("isolation", "model_isolation_violation"), ("failed", "model_call_failed")])
def test_unusable_model_calls_pause_without_findings_and_resume_same_model(api, problem, reason):
    opened, _, _ = start(api)
    if problem == "mismatch":
        api.adapter.resolved_model = "different-model"
    elif problem == "isolation":
        api.adapter.fail = lambda si: ModelStepResult("isolation_violation", tool_item_types=["tool"])
    else:
        api.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC failed call")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "paused" and card["pause_reason"] == reason and not card["findings"]
    api.adapter.fail = api.adapter.resolved_model = None
    control(api, opened["run"]["id"], "resume")
    turn(api)
    assert read(api, opened["review"]["id"])["state"] == "completed"
    assert {model for task, model, effort in api.adapter.sent} == {"review-model"}


def test_plain_dict_findings_are_refused(api):
    opened, _, _ = start(api)
    with pytest.raises(TypeError, match="resolve_finding"):
        ReviewStore(api.conn).add_findings(opened["review"]["id"], [{"finding": {}, "step_input_id": "sti_fake"}])


@pytest.mark.parametrize("interrupt", ["before", "second_insert"])
def test_group_insert_transaction_rolls_back_and_resume_writes_exactly_once(api, monkeypatch, interrupt):
    opened, _, _ = start(api)
    run_id = opened["run"]["id"]
    def two_findings(si):
        output = json.loads(finding_response(si))
        output["findings"].append(copy.deepcopy(output["findings"][0]) | {"finding_handle": "f2"})
        return json.dumps(output)
    api.adapter.responder = two_findings
    insert = ReviewStore.add_findings
    def crash(self, review_id, rows):
        if interrupt == "second_insert":
            insert(self, review_id, rows[:1])
        raise Crash("SYNTHETIC interrupted group inserts")
    monkeypatch.setattr(ReviewStore, "add_findings", crash)
    with pytest.raises(Crash):
        turn(api)
    assert not ReviewStore(api.conn).findings(opened["review"]["id"])
    api.client.portal.call(api.app.state.worker.recover)
    monkeypatch.setattr(ReviewStore, "add_findings", insert)
    control(api, run_id, "resume")
    turn(api)
    card = read(api, opened["review"]["id"])
    assert len(card["findings"]) == 2 and len(api.adapter.calls) == 1
    sid = card["models_that_answered"][0]["step_input_id"]
    saved = ReviewStore(api.conn).snapshot(card["snapshot"]["id"])
    payload = api.store.step_input_payload(sid)
    result = api.store.existing_step(run_id, "owner_review:1")["output"]["result"]
    assert ReviewStore(api.conn).add_group_findings(card["id"], sid, [resolve_finding(saved["content"], payload, f) for f in result["findings"]]) == []
    assert len(ReviewStore(api.conn).findings(card["id"])) == 2


def test_zero_findings_valid_group_is_idempotent_noop(api):
    api.adapter.responder = valid_response
    opened, _, _ = start(api)
    turn(api)
    card = read(api, opened["review"]["id"])
    assert card["state"] == "completed" and card["findings"] == []
    sid = card["models_that_answered"][0]["step_input_id"]
    assert ReviewStore(api.conn).add_group_findings(card["id"], sid, []) == []
    assert ReviewStore(api.conn).add_group_findings(card["id"], sid, []) == []
