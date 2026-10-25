"""UI parity S17, F10 (Sol round 1): run kinds that freeze a model at their request (prior-art search, lineage links)
send their later calls to a model a person chose since, without editing the frozen record. SYNTHETIC records and the
fake adapter; this shows which model each call asks for, not model quality.
"""

import json

import pytest

from test_candidate_flow import lib as candidate_lib  # noqa: F401  (pytest fixture)
from test_candidate_flow import edit_version, execute as run_candidate, search
from test_lineage_flow import factory  # noqa: F401  (fixtures used by name)


def change(lib, model, effort=None):
    return lib.store.change_role_model(lib.rid, "answer", "fake", model, effort, lib.store.research(lib.rid)["version"])


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


