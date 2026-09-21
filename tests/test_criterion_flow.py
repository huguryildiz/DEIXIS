"""The criterion proposal inside a discovery run (SW15, slice 06).

What is checked here is workflow behavior: a search that runs with the model down, a criterion that reaches the
protocol before the first provider request, a resumed or repeated run that asks the model nothing twice, and a
`legacy` research that gains none of it. Questions, records and proposals are SYNTHETIC; the criterion they produce
is not a criterion anyone judged.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.domain.canonical import sha256_hex
from deixis.domain.rules import CRITERION_CALLS, TEST_EFFORT_BUDGETS
from deixis.models.adapter import ModelStepResult
from deixis.workflow.criterion import PROPOSAL_RUNS
from deixis.workflow.decisions import CRITERION_FIELDS
from fakes import FakeAdapter, envelope, valid_response
from test_criterion_proposal import three_runs
from test_vocabulary_flow import (CountingOpenAlex, DeadAdapter, KEY_TERMS, app_for, start, store_at, wait)

# SYNTHETIC and from a field no other criterion test uses; the proposals below are about the same question.
EXERCISE = "What is the effect of supervised exercise on cancer related fatigue in adults after chemotherapy?"
RUNS = three_runs()
CRITERION_STEPS = ["criterion"] + [f"criterion_proposal_{i + 1}" for i in range(PROPOSAL_RUNS)]


def proposing(fail_steps=(), invalid_steps=()):
    """A model that answers each criterion call with its own proposal, and fails or breaks the ones named.

    The run number follows the step, not the call, so a schema repair of a broken proposal stays broken instead of
    turning into the next run's answer.
    """
    order = []

    def number(si):
        if si["step_id"] not in order:
            order.append(si["step_id"])
        return order.index(si["step_id"]) % PROPOSAL_RUNS + 1  # a second run of the same research starts over

    def fail(si):
        if si["task_type"] != "criterion_proposal":
            return None
        return ModelStepResult("failed", error="SYNTHETIC criterion call is down") if number(si) in fail_steps else None

    def responder(si):
        if si["task_type"] != "criterion_proposal":
            return valid_response(si)
        body = RUNS[number(si)]
        if number(si) in invalid_steps:
            body = body | {"parts": body["parts"][:1]}  # one part: below the contract's floor, so the run is dropped
        return json.dumps(envelope(si, "deixis.criterion_proposal.v1") | body)

    return FakeAdapter(responder, fail=fail)


def body_of(tmp_path, rid, revision=None):
    store = store_at(tmp_path)
    rows = list(store.conn.execute(
        "SELECT body_json, protocol_revision FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision",
        (rid,)))
    return [json.loads(row["body_json"]) for row in rows] if revision is None else json.loads(
        next(row["body_json"] for row in rows if row["protocol_revision"] == revision))


def criterion_fields(body):
    return {field: body[field] for field in (*CRITERION_FIELDS, "exclusion_title_words")}


def steps_of(run):
    return [s["operation_key"] for s in run["steps"]]


def criterion_calls(adapter):
    return [c for c in adapter.calls if c["task_type"] == "criterion_proposal"]


# ---- the model is unreachable -------------------------------------------------------------------------------

def test_an_sw_discovery_searches_with_no_criterion_while_every_model_call_fails(tmp_path, monkeypatch):
    """The acceptance condition of slices 04a and 04d again: no *required* model call stands before the search."""
    openalex, adapter = CountingOpenAlex(), DeadAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        view, run = wait(client, rid, run_id)
    assert openalex.searches, run
    assert len(criterion_calls(adapter)) == PROPOSAL_RUNS
    statuses = {s["operation_key"]: s["status"] for s in run["steps"] if s["operation_key"].startswith("criterion")}
    assert statuses == {"criterion": "succeeded",
                        **{f"criterion_proposal_{i + 1}": "failed" for i in range(PROPOSAL_RUNS)}}
    # The step succeeded with nothing in it, so a resumed run does not pay for the calls again.
    stored = store_at(tmp_path).latest_step_output(rid, "criterion", 1)
    assert stored["origin"] is None and stored["criterion"] is None
    assert [f["reason"] for f in stored["failures"]] == ["model_call_failed"] * PROPOSAL_RUNS
    body = body_of(tmp_path, rid, 1)
    assert criterion_fields(body) == {"inclusion_criterion": None, "criterion_parts": None, "cue_phrases": None,
                                      "exclusion_title_words": None}
    assert "criterion_origin" not in body
    # The run went on to screening and stopped there, at the first step that needs a model, not before it.
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed"), run


def test_two_failed_proposals_do_not_cancel_the_third_call_and_one_run_builds_nothing(tmp_path, monkeypatch):
    """SW15.2: one valid run is not a criterion. The third call is still sent; skipping it is slice 08's business."""
    openalex, adapter = CountingOpenAlex(), proposing(fail_steps=(1, 2))
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        wait(client, rid, run_id)
    assert len(criterion_calls(adapter)) == PROPOSAL_RUNS
    stored = store_at(tmp_path).latest_step_output(rid, "criterion", 1)
    assert stored["origin"] is None and stored["criterion"] is None
    assert body_of(tmp_path, rid, 1)["inclusion_criterion"] is None


def test_a_proposal_that_breaks_the_contract_is_dropped_and_the_other_two_decide(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), proposing(invalid_steps=(2,))
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        view, run = wait(client, rid, run_id)
    second = next(s for s in run["steps"] if s["operation_key"] == "criterion_proposal_2")
    assert second["status"] == "failed" and second["error_code"] == "invalid_model_output"
    stored = store_at(tmp_path).latest_step_output(rid, "criterion", 1)
    assert stored["criterion"]["runs_ok"] == [1, 3]
    assert [f["reason"] for f in stored["failures"]] == ["invalid_model_output"]


# ---- the model answers ----------------------------------------------------------------------------------------

def run_with_proposals(tmp_path, monkeypatch, question=EXERCISE, **body):
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, question, **body)
        view, run = wait(client, rid, run_id)
    return rid, run, openalex, adapter


def test_three_proposals_reach_the_protocol_before_the_first_provider_request(tmp_path, monkeypatch):
    rid, run, openalex, adapter = run_with_proposals(tmp_path, monkeypatch)
    keys = steps_of(run)
    assert keys[:10] == ["vocabulary", "vocabulary_labels_1", "vocabulary_labels_2", "vocabulary_labels_3",
                         "criterion", "criterion_proposal_1", "criterion_proposal_2", "criterion_proposal_3",
                         "protocol_approval", "protocol"]
    # Every provider search was opened after the protocol step, which already held the criterion.
    searches = [i for i, key in enumerate(keys) if key.startswith("search:")]
    assert searches and min(searches) > keys.index("protocol")
    body = body_of(tmp_path, rid, 1)
    assert body["inclusion_criterion"] == RUNS[1]["criterion"]  # run 1 is the base run of these three proposals
    assert [p["name"] for p in body["criterion_parts"]] == [p["name"] for p in RUNS[1]["parts"]]
    assert "walking programme" in [p["phrase"] for p in body["cue_phrases"]]
    assert body["exclusion_title_words"] == ["editorial", "review"]
    assert body["criterion_origin"]["origin"] == "model" and body["criterion_origin"]["base_run"] == 1
    assert body["criterion_origin"]["runs_ok"] == [1, 2, 3]
    # The known defect's trace: a record only, read by nothing in this slice.
    assert body["criterion_origin"]["sought_term_in_criterion"] is True
    assert body["thresholds"]["criterion"] == {"proposal_runs": 3, "proposal_majority": 2}
    # An sw discovery run is given the three calls on top of its preset, so its room for screening is unchanged.
    presets = {preset.max_model_calls for preset in TEST_EFFORT_BUDGETS.values()}
    assert body["budget"]["max_model_calls"] - CRITERION_CALLS in presets


def test_the_criterion_decides_nothing_and_selects_nothing_in_this_slice(tmp_path, monkeypatch):
    rid, run, openalex, adapter = run_with_proposals(tmp_path, monkeypatch)
    store = store_at(tmp_path)
    criterion_step_ids = {row["id"] for row in store.conn.execute(
        "SELECT s.id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND s.operation_key LIKE 'criterion%'", (rid,))}
    assert criterion_step_ids
    decided_by = {row["step_id"] for row in store.conn.execute(
        "SELECT step_id FROM stage_decisions WHERE research_id = ?", (rid,))}
    assert not (decided_by & criterion_step_ids)
    # Nothing here writes a selection either; the phrases order nothing until slice 11.
    assert not list(store.conn.execute(
        "SELECT 1 FROM selections WHERE research_id = ? AND origin = 'criterion'", (rid,)))


def test_a_resumed_run_proposes_nothing_again(tmp_path, monkeypatch):
    """The search fails on the first pass; resuming retries the search and must not pay for the proposals again."""
    openalex, adapter = CountingOpenAlex(), proposing()
    down = {"now": True}

    def handler(request):
        params = request.url.params
        if down["now"] and not (params.get("per_page") == "1" and params.get("select") == "id"):
            return httpx.Response(503)
        return openalex(request)

    with TestClient(app_for(tmp_path, monkeypatch, handler, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and not openalex.searches
        asked = [c["step_input_id"] for c in criterion_calls(adapter)]
        assert len(asked) == PROPOSAL_RUNS
        down["now"] = False
        client.post(f"/api/runs/{run_id}/resume")
        wait(client, rid, run_id)
    assert openalex.searches
    assert [c["step_input_id"] for c in criterion_calls(adapter)] == asked
    assert body_of(tmp_path, rid, 1)["inclusion_criterion"] == RUNS[1]["criterion"]


def test_a_second_discovery_run_of_the_same_scope_takes_the_frozen_criterion_back(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        wait(client, rid, run_id)
        asked = len(criterion_calls(adapter))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
    assert len(criterion_calls(adapter)) == asked == PROPOSAL_RUNS  # the second run asked nothing
    assert not any(key.startswith("criterion_proposal") for key in steps_of(run))
    stored = store_at(tmp_path).latest_step_output(rid, "criterion", 1)
    assert stored["origin"] == "protocol" and stored["protocol_revision"] == 1
    bodies = body_of(tmp_path, rid)
    assert len(bodies) > 1
    # Byte for byte the same criterion; only the record of where it came from says it was read back.
    assert {sha256_hex(criterion_fields(body)) for body in bodies} == {sha256_hex(criterion_fields(bodies[0]))}
    assert bodies[-1]["criterion_origin"]["origin"] == "protocol"


def test_a_revision_that_keeps_the_question_asks_the_model_nothing(tmp_path, monkeypatch):
    """A revision that changed only the user's key terms must not get the same criterion in other words: that would
    mark every decision taken under the old one stale (SW11.10)."""
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        wait(client, rid, run_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        revised = client.post(f"/api/researches/{rid}/scope",
                              json={"question": EXERCISE, "expected_version": version, "key_terms": KEY_TERMS})
        assert revised.status_code == 200, revised.text
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
    assert len(criterion_calls(adapter)) == PROPOSAL_RUNS
    bodies = body_of(tmp_path, rid)
    assert sha256_hex(criterion_fields(bodies[-1])) == sha256_hex(criterion_fields(bodies[0]))
    assert bodies[-1]["criterion_origin"]["origin"] == "protocol"


def test_a_revision_that_changes_the_question_asks_again(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, EXERCISE)
        wait(client, rid, run_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": EXERCISE + " Only randomised trials.", "expected_version": version})
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
    assert len(criterion_calls(adapter)) == 2 * PROPOSAL_RUNS
    assert store_at(tmp_path).latest_step_output(rid, "criterion", 2)["origin"] == "model"


def test_a_run_that_stops_for_key_terms_asks_for_no_criterion(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), proposing()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "Kablosuz alıcı ağlarında paket boyu enerji tüketimini nasıl etkiler?")
        view, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "key_terms_needed"), run
    assert not criterion_calls(adapter) and not any(key.startswith("criterion") for key in steps_of(run))


# ---- the second arm and the legacy workflow --------------------------------------------------------------------

def test_the_expansion_revision_carries_the_same_criterion(tmp_path, monkeypatch):
    """The easiest mistake in this slice: a second revision without the criterion would make every decision stale."""
    from test_expansion_flow import Field, app_for as expansion_app, client_of, discover, protocols

    app = expansion_app(tmp_path, monkeypatch, Field(), adapter=proposing())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        frozen = protocols(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert [row["reason"] for row in frozen] == [None, "data_expansion"]
    first, second = (row["body"] for row in frozen)
    assert first["inclusion_criterion"] is not None
    assert sha256_hex(criterion_fields(second)) == sha256_hex(criterion_fields(first))
    assert second["criterion_origin"] == first["criterion_origin"]


def test_a_legacy_research_opens_no_criterion_step_and_its_protocol_body_is_what_it_was(tmp_path, monkeypatch):
    from test_provider_flow import routed, two_provider_plan

    adapter = FakeAdapter(two_provider_plan)
    with TestClient(app_for(tmp_path, monkeypatch, routed, adapter, workflow="legacy")) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "How is diffusion channel scheduling optimized?")
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert not any(key.startswith("criterion") for key in steps_of(run))
    assert "criterion_proposal" not in [c["task_type"] for c in adapter.calls]
    body = body_of(tmp_path, rid, 1)
    assert criterion_fields(body) == {"inclusion_criterion": None, "criterion_parts": None, "cue_phrases": None,
                                      "exclusion_title_words": None}
    assert "criterion_origin" not in body and "criterion" not in body["thresholds"]
    # The three calls the criterion adds are given to an sw discovery run alone: a legacy run keeps its preset.
    assert body["budget"]["max_model_calls"] == TEST_EFFORT_BUDGETS[view["scope"]["effort"]].max_model_calls


def test_the_legacy_protocol_body_has_the_digest_it_had_before_this_slice():
    """Pinned from the body `build_protocol` produced at the commit before slice 06 (same arguments, same digest)."""
    from deixis.config import Settings
    from deixis.workflow.protocol import build_protocol
    from determinism_stages import CONCEPTS, SCOPE

    scope = SCOPE | {"providers": ["openalex", "crossref", "arxiv", "pubmed"]}
    body = build_protocol(scope, {"max_candidates": 20}, {"concepts": CONCEPTS},
                          [{"provider_id": "openalex", "query_text": "diffusion channel"}],
                          "SYNTHETIC_package_hash", Settings(data_dir=None))
    assert sha256_hex(body) == "b860f3c8ad392bdc49229c98594b4a15e17797fa19e4dd8d83cfe98259c31833"
