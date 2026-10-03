"""Checks runnable against the untouched B1 code as well as B2 (see implementation report)."""

import inspect
import json

import pytest

from deixis.domain import contracts, skill
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow import flow as flow_module
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.report.store import ReportStore
from tests.fakes import FakeAdapter
from tests.review_helpers import report_with_sections, review_lib, stored_review, snapshot, review_run, step_payload, all_rows
from tests.review_run_helpers import review_api, body


def test_review_stage_is_claim_check_not_extraction(review_lib):
    run = review_lib["store"].create_run(review_lib["rid"], "review", {}, None)
    assert run["stage"] == "claim_check"


@pytest.mark.parametrize("kind", ["invented_kind", "table_columns"])
def test_unknown_kind_fails_without_table_dispatch_and_real_table_kind_still_dispatches(review_lib, tmp_path, monkeypatch, kind):
    with review_api(review_lib, tmp_path) as api:
        run = api.store.create_run(api.rid, "table_columns", {}, None)
        api.store.update_run(run["id"], status="running")
        original = api.store.run
        monkeypatch.setattr(api.store, "run", lambda rid: original(rid) | {"kind": kind})
        calls = []
        async def table(*args):
            calls.append(True)
        monkeypatch.setattr(api.app.state.worker.flow, "_table_columns", table)
        api.client.portal.call(api.app.state.worker.flow._execute_run, run["id"])
        if kind == "invented_kind":
            assert calls == []
            assert original(run["id"])["status"] == "failed" and original(run["id"])["pause_reason"] == "unknown_run_kind"
        else:
            assert calls == [True] and original(run["id"])["status"] == "completed"


def test_add_findings_refuses_a_plain_dict_before_any_insert(review_lib):
    saved, review, payload, fid = stored_review(review_lib)
    before = all_rows(review_lib["conn"])
    with pytest.raises(TypeError):
        review_lib["reviews"].add_findings(review["id"], [{"finding": {"target_ref": {"kind": "whole", "ref": None}}, "step_input_id": payload["step_input_id"]}])
    assert all_rows(review_lib["conn"]) == before


def test_full_request_limit_refuses_a_message_that_alone_fits(review_lib, tmp_path, monkeypatch):
    saved = snapshot(review_lib)
    with review_api(review_lib, tmp_path) as api:
        run = api.store.create_run(api.rid, "review", {"max_model_calls": 6, "max_provider_requests": 0}, None)
        api.store.update_run(run["id"], status="running")
        # A B1 full contract fixture supplies a builder independently of run.py.
        from tests.review_helpers import si
        from deixis.workflow.review.snapshot import review_step_input_parts
        payload = si("report")
        payload.update(review_step_input_parts(saved["id"], saved["content"], focus="source_support", owner_note=None))
        payload.update(research_id=api.rid, run_id=run["id"], skill_package_hash=skill.package_hash())
        limit = max(len(prompt.step_message(payload)), len(prompt.step_message(contracts.with_citation_handles(payload)))) + 100
        def builder(step_id):
            return payload | {"step_id": step_id, "step_input_id": db.new_id("sti")}
        flow = api.app.state.worker.flow
        if "max_request_chars" in inspect.signature(flow._model_step).parameters:
            bounds = {"step_input_builder": builder, "max_request_chars": limit}
        else:
            # Exercise B1's actual message-only check instead of failing merely
            # because the new keywords do not exist on the baseline.
            monkeypatch.setattr(flow, "_step_input", lambda *args, **kwargs: builder(args[2]))
            bounds = {"max_message_chars": limit}
        result = api.client.portal.call(lambda: flow._model_step(
            api.store.run(run["id"]), api.store.scope(api.rid), "owner_review:1", "owner_review", model=("fake", "review-model", None),
            **bounds))
        row = api.conn.execute("SELECT * FROM step_inputs WHERE run_id = ?", (run["id"],)).fetchone()
        measured = len(row["base_instructions"]) + len(row["developer_instructions"]) + len(row["user_message"]) + len(
            json.dumps(json.loads(row["output_schema_json"]), separators=(",", ":"), ensure_ascii=False))
        assert len(row["user_message"]) < limit < measured
        assert not api.adapter.calls, f"message-only check sent {len(api.adapter.calls)} oversized complete requests"
        assert result["message_too_large"] and result["request_chars"] == measured
        assert api.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE run_id = ?", (run["id"],)).fetchone()[0] == 0


def test_resend_loop_without_owner_gate_uses_three_sessions_under_ceiling_one(review_lib, tmp_path, monkeypatch):
    """Diagnostic control: B2's guard is necessary; the shared loop is unchanged."""
    from tests.review_helpers import si
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    with review_api(review_lib, tmp_path) as api:
        run = api.store.create_run(api.rid, "review", {"max_model_calls": 1, "max_provider_requests": 0}, None)
        step = api.store.step(run["id"], "owner_review:1", "model:owner_review")
        payload = si("report") | {"step_input_id": db.new_id("sti"), "research_id": api.rid, "run_id": run["id"], "step_id": step["id"]}
        api.store.insert_step_input(step["id"], api.rid, run["id"], 0, payload, "base", "developer", "message", {})
        api.adapter.fail = lambda si: ModelStepResult("failed", error="429 SYNTHETIC rate limit")
        api.client.portal.call(lambda: api.app.state.worker.flow._call_adapter(run["id"], api.rid, step["id"],
            payload["step_input_id"], "fake", "review-model", api.adapter, "base", "developer",
            prompt.step_message(payload), {}, None, ModelCallLimiter(1), resend=None))
        assert len(api.adapter.calls) == api.store.run(run["id"])["usage"]["model_calls"] == 3


@pytest.mark.parametrize("route", ["preview", "start", "list", "read", "decisions", "apply"])
def test_new_review_route_is_registered_and_answers_its_contract(review_lib, tmp_path, route):
    saved, review, payload, fid = stored_review(review_lib)
    review_lib["conn"].execute("UPDATE runs SET target_json = ? WHERE id = ?", (json.dumps({"plan": {"groups": []}}), review["run_id"]))
    with review_api(review_lib, tmp_path) as api:
        headers = {"Idempotency-Key": "SYNTHETIC-command"}
        if route == "preview":
            response = api.client.post(api.url + "/preview", json=body(api))
        elif route == "start":
            shown = api.client.post(api.url + "/preview", json=body(api))
            hashes = {k: shown.json()[k] for k in ("snapshot_sha256", "preview_fingerprint")} if shown.status_code == 200 else {"snapshot_sha256": "0" * 64, "preview_fingerprint": "0" * 64}
            response = api.client.post(api.url, json=body(api) | hashes, headers=headers)
        elif route == "list":
            response = api.client.get(api.url, params={"target_kind": "report", "target_id": api.report_id})
        elif route == "read":
            response = api.client.get(f"{api.url}/{review['id']}")
        elif route == "decisions":
            response = api.client.post(f"{api.url}/{review['id']}/findings/{fid}/decisions", json={"decision": "deferred", "reason": None, "expected_ordinal": 0}, headers=headers)
        else:
            card = api.client.get(f"{api.url}/{review['id']}")
            fingerprint = card.json()["findings"][0]["dependency_fingerprint"] if card.status_code == 200 else "0" * 64
            claim = api.conn.execute("SELECT version FROM report_claims WHERE id = ?", (saved["content"]["claims"][0]["claim_id"],)).fetchone()
            response = api.client.post(f"{api.url}/{review['id']}/findings/{fid}/apply", json={"text": "SYNTHETIC new edit", "link_ids": None, "note": None,
                "expected_version": claim[0], "dependency_fingerprint": fingerprint}, headers=headers)
        assert response.status_code == (202 if route == "start" else 200), response.text


@pytest.mark.parametrize("route", ["trash", "source"])
def test_unreadable_snapshot_purge_is_409_not_500(review_lib, tmp_path, route):
    saved = snapshot(review_lib)
    conn = review_lib["conn"]
    trigger = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'owner_review_snapshots_no_update'").fetchone()[0]
    conn.execute("DROP TRIGGER owner_review_snapshots_no_update")
    conn.execute("UPDATE owner_review_snapshots SET content_json = 'corrupt' WHERE id = ?", (saved["id"],))
    conn.execute(trigger)
    with review_api(review_lib, tmp_path) as api:
        if route == "trash":
            api.store.trash_research(api.rid)
        else:
            sid = api.store.create_upload_source("SYNTHETIC unused")
            api.store.add_to_corpus(api.rid, sid, "user_upload")
            api.conn.execute("UPDATE corpus_memberships SET removed_at = 'now' WHERE source_version_id = ?", (sid,))
        before = all_rows(api.conn)
        response = api.client.delete(f"/api/trash/{api.rid}") if route == "trash" else api.client.post(
            f"/api/researches/{api.rid}/sources/purge", json={"source_version_ids": [sid]})
        assert response.status_code == 409 and response.json()["code"] == "snapshot_dependency_unreadable", response.text
        assert all_rows(api.conn) == before
