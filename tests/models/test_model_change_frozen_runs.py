"""UI parity S17, F10 (Sol round 1): run kinds that freeze a model at their request (prior-art search, lineage links)
send their later calls to a model a person chose since, without editing the frozen record. SYNTHETIC records and the
fake adapter; this shows which model each call asks for, not model quality.
"""

import json

import pytest

from fakes import FakeAdapter  # noqa: F401  (fixtures below build their own)
from test_candidate_flow import lib as candidate_lib  # noqa: F401  (pytest fixture)
from test_candidate_flow import edit_version, execute as run_candidate, search
from test_lineage_flow import factory  # noqa: F401  (pytest fixture)
from test_lineage_flow import execute as run_lineage, publication
from test_lineage_plan import fill


def change(lib, model, effort=None):
    return lib.store.change_role_model(lib.rid, "answer", "fake", model, effort, lib.store.research(lib.rid)["version"])


def models_sent(lib, task):
    return {(model, effort) for sent_task, model, effort in lib.adapter.sent if sent_task == task}


def requested_models(lib, run_id):
    return {r[0] for r in lib.conn.execute("SELECT requested_model FROM model_sessions WHERE run_id = ?", (run_id,))}


# ---- prior-art search (kill_search) ----------------------------------------------------------------
def queued_kill(lib):
    if not lib.candidate_store.candidate(lib.candidate["id"])["current_version"]:
        edit_version(lib, lib.candidate)
    plan = lib.planner.preview(lib.rid, lib.candidate["id"])
    return lib.planner.request_run(lib.rid, lib.candidate["id"], plan["preview_fingerprint"], None)


@pytest.fixture
def kill_lib(candidate_lib):  # noqa: F811
    return candidate_lib


def test_a_queued_prior_art_search_sends_to_the_model_chosen_after_its_request(kill_lib):
    lib = kill_lib
    run = queued_kill(lib)
    frozen = json.loads(json.dumps(run["target"]["model"]))
    assert {m[1] for m in frozen.values()} == {"fake-model"}
    change(lib, "fake-model-2", "high")
    lib.store.update_run(run["id"], status="running")
    assert run_candidate(lib, lib.store.run(run["id"]))["status"] == "completed"
    assert {model for _, model, _ in lib.adapter.sent} == {"fake-model-2"}
    assert {effort for _, _, effort in lib.adapter.sent} == {"high"}
    assert requested_models(lib, run["id"]) == {"fake-model-2"}
    assert lib.store.run(run["id"])["target"]["model"] == frozen  # the frozen plan is never edited
    assert json.loads(search(lib, run)["selection_json"])["model"] == frozen


def test_a_paused_prior_art_search_resumes_on_the_new_model(kill_lib):
    lib = kill_lib
    run = queued_kill(lib)
    lib.store.update_run(run["id"], status="pause_requested", pause_reason="user_requested")
    paused = run_candidate(lib, lib.store.run(run["id"]))  # a model step that fails ends a prior-art search; a pause does not
    assert paused["status"] == "paused" and lib.adapter.sent == []
    change(lib, "fake-model-2")
    lib.store.resume_run(run["id"])
    lib.store.update_run(run["id"], status="running")
    assert run_candidate(lib, lib.store.run(run["id"]))["status"] == "completed"
    assert lib.adapter.sent and {model for _, model, _ in lib.adapter.sent} == {"fake-model-2"}


def test_a_prior_art_search_without_a_change_keeps_its_frozen_model(kill_lib):
    lib = kill_lib
    run = queued_kill(lib)
    lib.conn.execute("UPDATE scope_revisions SET requested_model = 'not-this-one' WHERE research_id = ?", (lib.rid,))
    lib.store.update_run(run["id"], status="running")
    assert run_candidate(lib, lib.store.run(run["id"]))["status"] == "completed"
    assert {model for _, model, _ in lib.adapter.sent} == {"fake-model"}


def test_model_mismatch_still_stops_a_prior_art_search_after_a_change(kill_lib):
    lib = kill_lib
    run = queued_kill(lib)
    change(lib, "fake-model-2")
    lib.adapter.resolved_model = "fake-model"
    lib.store.update_run(run["id"], status="running")
    stopped = run_candidate(lib, lib.store.run(run["id"]))
    assert stopped["pause_reason"] == "model_mismatch"
    assert stopped["error"] == {"requested_model": "fake-model-2", "resolved_model": "fake-model"}


# ---- lineage links ---------------------------------------------------------------------------------
def queued_lineage(lib):
    plan = lib.planner.build_plan(lib.rid, lib.tid, False)
    return lib.planner.request_run(lib.rid, lib.tid, plan["preview_fingerprint"])


def test_a_queued_lineage_run_sends_to_the_new_model_and_its_reuse_key_names_that_model(factory):  # noqa: F811
    lib = factory()
    fill(lib)
    run = queued_lineage(lib)
    assert run["target"]["model"][1] == "fake-model"
    change(lib, "fake-model-2", "high")
    lib.store.update_run(run["id"], status="running")
    assert run_lineage(lib, lib.store.run(run["id"]))["status"] == "completed"
    assert models_sent(lib, "lineage_links") == {("fake-model-2", "high")}
    assert lib.store.run(run["id"])["target"]["model"][1] == "fake-model"  # the frozen plan is never edited
    record = publication(lib, run)
    assert record["counts"]["accepted"] == 1 and not record["step_failed"]
    output = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"]
    assert output["send_record"]["reasoning_effort"] == "high"
    # A later plan computes the reuse key under the model in effect, finds the pair assessed, and sends nothing again.
    again = lib.planner.build_plan(lib.rid, lib.tid, False)
    assert again["chunks"] == []


def test_a_paused_lineage_run_resumes_on_the_new_model(factory):  # noqa: F811
    lib = factory()
    fill(lib)
    run = queued_lineage(lib)
    lib.adapter.ready = False
    lib.store.update_run(run["id"], status="running")
    paused = run_lineage(lib, lib.store.run(run["id"]))
    assert (paused["status"], paused["pause_reason"]) == ("paused", "model_connection_not_ready")
    change(lib, "fake-model-2")
    lib.adapter.ready = True
    lib.store.resume_run(run["id"])
    lib.store.update_run(run["id"], status="running")
    assert run_lineage(lib, lib.store.run(run["id"]))["status"] == "completed"
    assert models_sent(lib, "lineage_links") == {("fake-model-2", None)}
    assert requested_models(lib, run["id"]) == {"fake-model-2"}
    assert publication(lib, run)["counts"]["accepted"] == 1
