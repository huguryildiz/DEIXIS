"""SYNTHETIC real API/worker, frozen read models, decisions and bounded repair."""

import json

import pytest

from deixis.workflow.candidates.store import CandidateStore
from tests.fakes import FakeAdapter
from tests.review.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, candidate_body, candidate_response, add_version
from tests.review.review_run_helpers import review_api, start, read, turn, control


def test_candidate_preview_start_read_decide_apply_and_reopen_version_one(candidate_lib, tmp_path):
    lib = candidate_lib
    with review_api(lib, tmp_path, adapter=FakeAdapter(responder=candidate_response, models=["review-model"], efforts=["high"])) as api:
        opened, command, preview = start(api, candidate_body(lib))
        target = api.store.run(opened["run"]["id"])["target"]
        assert target["target_kind"] == "candidate"
        assert target["target_id"] == lib["candidate_version_id"]
        assert preview["element_count"] == 3 and preview["matrix_source_count"] == 2 and preview["claim_count"] == 0
        assert preview["passage_count"] == 4 and preview["total_send_bound"] == 6
        replay = api.client.post(api.url, json=command, headers={"Idempotency-Key": "SYNTHETIC-start"})
        assert replay.json()["review"]["id"] == opened["review"]["id"]
        turn(api); card = read(api, opened["review"]["id"])
        assert card["state"] == "completed" and len(card["findings"]) == 2
        assert card["snapshot"]["candidate_version"] == 1 and len(card["snapshot"]["elements"]) == 3
        assert len(card["snapshot"]["matrix_sources"]) == 2 and len(card["snapshot"]["passages"]) == 4
        row = card["findings"][0]; assert row["finding"]["target"]["text_at_snapshot"].startswith("SYNTHETIC")
        path = api.url + f"/{card['id']}/findings/{row['id']}"
        decision = api.client.post(path + "/decisions", json=dict(decision="accepted", reason=None, expected_ordinal=0), headers={"Idempotency-Key": "SYNTHETIC-accept"})
        assert decision.status_code == 200 and decision.json()["no_change_made"] is True
        applied = api.client.post(path + "/apply", json=dict(text="SYNTHETIC edit", expected_version=1, dependency_fingerprint="0" * 64), headers={"Idempotency-Key": "SYNTHETIC-apply"})
        assert applied.status_code == 422 and applied.json()["code"] == "not_applicable"
        live = dict(lib, store=api.store, conn=api.conn)
        v2 = add_version(live)
        CandidateStore(api.store).record_owner_decision(api.rid, v2["id"], "undecided", "SYNTHETIC later owner")
        reread = read(api, card["id"])
        assert reread["snapshot"] == card["snapshot"]
        assert {r["code"] for r in reread["stale_reasons"]} == {"newer_candidate_version"}
        CandidateStore(api.store).record_owner_decision(api.rid, lib["candidate_version_id"], "undecided", "SYNTHETIC reviewed owner")
        assert {r["code"] for r in read(api, card["id"])["stale_reasons"]} == {"newer_candidate_version", "owner_status_changed"}
        listed = api.client.get(api.url, params=dict(target_kind="candidate", target_id=lib["candidate_version_id"]))
        assert listed.status_code == 200 and len(listed.json()) == 1


@pytest.mark.parametrize("bad", ["passage", "element"])
def test_candidate_unknown_handle_exhausts_bounded_repair_and_records_source_id(candidate_lib, tmp_path, bad):
    def respond(si):
        out = json.loads(candidate_response(si))
        if bad == "passage": out["findings"][0]["evidence"][0]["passage_handle"] = "psg_P0000999"
        else: out["findings"][0]["target_ref"]["ref"] = "e99"
        return json.dumps(out)
    adapter = FakeAdapter(responder=respond)
    with review_api(candidate_lib, tmp_path, adapter=adapter) as api:
        opened, _, _ = start(api, candidate_body(candidate_lib))
        turn(api); card = read(api, opened["review"]["id"])
        assert card["state"] == "failed" and not card["findings"] and len(adapter.calls) == 2
        assert {r["source_id"] for r in card["not_reviewed"]} == {m["source_id"] for m in card["snapshot"]["matrix_sources"]}
        assert {r["reason"] for r in card["not_reviewed"]} == {"invalid_model_output"}
        assert all(r["claim_ref"] is None and r["step_input_id"] for r in card["not_reviewed"])


def test_candidate_empty_source_group_failure_records_null_source(candidate_lib, tmp_path):
    from tests.review.review_candidate_helpers import search
    search(candidate_lib, assessed=False)
    with review_api(candidate_lib, tmp_path, adapter=FakeAdapter(responder=lambda si: "SYNTHETIC invalid")) as api:
        opened, _, _ = start(api, candidate_body(candidate_lib)); turn(api)
        card = read(api, opened["review"]["id"])
        assert len(card["not_reviewed"]) == 1 and card["not_reviewed"][0]["source_id"] is None


def test_candidate_review_blocks_decomposition_and_kill_search_starts(candidate_lib, tmp_path):
    with review_api(candidate_lib, tmp_path, adapter=FakeAdapter(responder=candidate_response)) as api:
        api.conn.execute("UPDATE scope_revisions SET providers_json='[\"openalex\"]' WHERE research_id=?", (api.rid,))
        opened, _, _ = start(api, candidate_body(candidate_lib))
        base = f"/api/researches/{api.rid}/candidates/{candidate_lib['candidate_id']}"
        assert api.client.post(base + "/decompose").status_code == 409
        plan = api.client.get(base + "/kill-search/plan")
        assert plan.status_code == 200, plan.text
        response = api.client.post(base + "/kill-search", json={"preview_fingerprint": plan.json()["preview_fingerprint"]}, headers={"Idempotency-Key": "SYNTHETIC-search"})
        assert response.status_code == 409, response.text
        control(api, opened["run"]["id"], "cancel")


def test_paused_kill_search_run_without_frozen_queries_keeps_completed_search_reviewable(candidate_lib, tmp_path):
    lib = candidate_lib
    with review_api(lib, tmp_path, adapter=FakeAdapter(responder=candidate_response)) as api:
        cs = CandidateStore(api.store)
        run = api.store.create_run(api.rid, "kill_search", {}, None,
            {"candidate_id": lib["candidate_id"], "candidate_version_id": lib["candidate_version_id"]})
        api.store.update_run(run["id"], status="paused")
        assert cs.search_for_run(run["id"]) is None
        opened, _, _ = start(api, candidate_body(lib))
        card = read(api, opened["review"]["id"])
        assert card["snapshot"]["kill_search_id"] == lib["search"]["id"]
