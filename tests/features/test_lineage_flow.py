"""L5b synthetic integration: real model machinery, stored inputs and publication.

Located synthetic quotes exercise contracts, not scientific support.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain import contracts
from deixis.storage import db
from deixis.workflow.run.concurrency import ModelCallLimiter
from deixis.workflow.features.lineage import lineage_run as lineage
from deixis.workflow.features.lineage.lineage_store import LineageStore
from deixis.workflow.run.worker import Worker
from fakes import FakeAdapter, valid_response
from test_lineage_plan import candidate, fill, make_env


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.run.flow.RATE_LIMIT_BACKOFF_SECONDS", 0)
    libraries = []

    def create(**kw):
        lib = make_env(tmp_path / str(len(libraries)), **kw)
        lib.adapter = FakeAdapter()
        lib.flow.deps.adapters["fake"] = lib.adapter
        lib.worker = Worker(lib.store, lib.flow, tmp_path / "unused.lock")
        libraries.append(lib)
        return lib

    yield create
    for lib in libraries:
        assert lib.seen == []
        asyncio.run(lib.http.aclose())
        lib.conn.close()


@pytest.fixture
def lib(factory):
    return factory()


def queue(lib, **kw):
    plan = lib.planner.build_plan(lib.rid, lib.tid, kw.get("retry_failed", False))
    run = lib.planner.request_run(lib.rid, lib.tid, plan["preview_fingerprint"], **kw)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def execute(lib, run):
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def publication(lib, run):
    step = lib.store.existing_step(run["id"], "lineage_publication")
    return step["output"] if step else None


def resume(lib, run):
    lib.store.update_run(run["id"], status="running", pause_reason=None)
    return execute(lib, lib.store.run(run["id"]))


def revisions(lib):
    return [dict(r) for r in lib.conn.execute("SELECT * FROM lineage_link_revisions ORDER BY created_at, id")]


def invalid(si):
    answer = json.loads(valid_response(si))
    answer["decisions"][0]["evidence"][0]["quote"] = "SYNTHETIC unlocated quote absent from every passage"
    return json.dumps(answer)


def all_links(si):
    answer = json.loads(valid_response(si))
    for decision, candidate in zip(answer["decisions"], si["lineage_target"]["candidates"]):
        passage = next(p for p in si["passages"] if p["passage_id"] == candidate["mention_passage_ids"][0])
        decision.update(decision="link", relation="extends", support_type="source_stated",
                        what_changed="SYNTHETIC change", evidence=[{"passage_id": passage["passage_id"],
                                                                  "quote": passage["text"][:600]}])
    return json.dumps(answer)


def instruction_edit(lib):
    col = lib.tables._columns(lib.tid)[0]
    lib.tables.revise_column(lib.rid, lib.tid, col["id"], {"instruction": "SYNTHETIC edited instruction"}, None, col["version"])


def selection_edit(lib, letter="a"):
    sid = lib.ids[letter]
    version = lib.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                               (lib.rid, sid)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, sid, "excluded", version, "SYNTHETIC user reason")


def scope_edit(lib):
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC revised question?", None)


def reextract(lib, letter="b", text="SYNTHETIC replacement: Author000 (2000)", allow_run_id=None):
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=1,
                                 pages=[SimpleNamespace(physical_page=1, printed_label="1", text=text)])
    return lib.store.reextract_asset(lib.assets[lib.ids[letter]], extraction, db.new_id("synthetic-extraction"),
                                    lambda value: [(0, len(value), value)], allow_run_id=allow_run_id)


def human_add(lib, a="a", b="b", **kw):
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    return lib.lineage.add_link(lib.rid, lib.tid, lib.ids[a], lib.ids[b], "extends", "SYNTHETIC human change",
        "analyst_inference", [{"passage_id": lib.passages[b], "quote": "SYNTHETIC"}], None,
        pair["version"] if pair else 0, None, **kw)


def test_a_run_finds_asks_and_publishes(lib):
    fill(lib)
    run = queue(lib)
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.lineage.active_links(lib.tid)) == 1
    record = publication(lib, run)
    assert record["counts"]["accepted"] == 1 and not record["step_failed"]
    rev = revisions(lib)[0]
    output = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"]
    sent = output["send_record"]["pairs"][0]
    assert json.loads(rev["inputs_json"]) == {"fingerprint": sent["pair_fp"], "inputs": sent["inputs"]}
    payload = lib.store.step_input_payload(output["step_input_id"])
    assert payload["lineage_target"]["to"]["source_id"] == lib.ids["b"]
    assert lib.adapter.calls[0]["lineage_target"]["to"]["source_id"].startswith("srv_S")


def test_cycle_rejection_is_recorded_not_lost(lib):
    human_add(lib, "b", "a")
    run = queue(lib)
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "cycle"
    assert any(r["disposition"] == "rejected" for r in revisions(lib))


def test_invalid_draft_after_one_repair_keeps_raw_output_and_makes_no_revision(lib):
    lib.adapter.responder = invalid
    run = queue(lib)
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2 and revisions(lib) == []
    row = lib.conn.execute("SELECT raw_output, validation_json FROM model_sessions ORDER BY rowid DESC LIMIT 1").fetchone()
    assert "unlocated quote" in row["raw_output"]
    assert "anchor_not_in_passage" in row["validation_json"]
    record = publication(lib, run)
    assert record["step_failed"][0]["reason"] == "invalid_model_output"
    assert len(record["failed_pairs"]) == 1


def test_budget_exhaustion_pauses_and_invents_no_relation(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    run = queue(lib)
    lib.conn.execute("UPDATE runs SET budget_json = '{\"max_model_calls\":1,\"max_provider_requests\":0}' WHERE id = ?", (run["id"],))
    state = execute(lib, lib.store.run(run["id"]))
    assert state["pause_reason"] == "budget_exhausted" and revisions(lib) == []
    assert publication(lib, run) is None


def test_invalid_after_one_repair_is_step_failed_and_others_still_publish(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    lib.adapter.responder = lambda si: invalid(si) if len(si["lineage_target"]["candidates"]) == 8 else valid_response(si)
    run = queue(lib)
    execute(lib, run)
    record = publication(lib, run)
    assert len(record["step_failed"]) == 1 and len(record["failed_pairs"]) == 8
    assert len(record["published"]) == 1 and len(revisions(lib)) == 1


def test_pause_while_calls_in_flight_applies_nothing_and_resume_publishes_from_stored_outputs(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    lib.flow.deps.limiter = ModelCallLimiter(2)
    run = queue(lib)
    lib.adapter.delay = 0.01
    def pause_after_both_sends(si):
        if len(lib.adapter.calls) == 2:
            lib.store.update_run(run["id"], status="pause_requested")
    lib.adapter.before = pause_after_both_sends
    execute(lib, run)
    assert revisions(lib) == [] and publication(lib, run) is None
    assert lib.store.run(run["id"])["status"] == "paused"
    sent = len(lib.adapter.calls)
    successes = lib.conn.execute("SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND status = 'succeeded'", (run["id"],)).fetchone()[0]
    assert successes == sent == 2
    lib.adapter.before = None
    assert resume(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2 and len(publication(lib, run)["published"]) == 9


def test_cancel_never_publishes(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: lib.store.update_run(run["id"], status="cancelled")
    assert execute(lib, run)["status"] == "cancelled"
    assert revisions(lib) == [] and publication(lib, run) is None
    execute(lib, run)
    assert len(lib.adapter.calls) == 1


def test_worker_recover_marks_the_half_sent_run_paused_and_resume_finishes_it(lib):
    run = queue(lib)
    def recover(si):
        state = lib.worker.recover()
        assert state["runs"] == state["steps"] == state["model_sessions"] == 1
    lib.adapter.before = recover
    assert execute(lib, run)["pause_reason"] == "backend_restarted"
    assert publication(lib, run) is None
    lib.adapter.before = None
    assert resume(lib, run)["status"] == "completed"
    # RF6 (D211): the late result of the attempt recovery closed as outcome_unknown is recorded, not used,
    # so the resumed step sends again (before RF6 that late result was stored and reused).
    assert len(lib.adapter.calls) == 2 and len(revisions(lib)) == 1


def test_crash_after_publication_does_not_publish_twice_or_call_the_model(lib):
    run = queue(lib)
    execute(lib, run)
    before = revisions(lib)
    # The publication transaction committed; the completion write was lost.
    lib.store.update_run(run["id"], status="running")
    assert lib.worker.recover()["runs"] == 1
    assert resume(lib, run)["status"] == "completed"
    assert revisions(lib) == before and len(lib.adapter.calls) == 1


@pytest.mark.parametrize("location", ["publication_record"])
def test_publication_is_one_transaction_and_a_failure_rolls_everything_back(factory, monkeypatch, location):
    lib = factory(n=6, mentions=(0, 2, 3), only_target=True)
    run = queue(lib)
    version = lib.tables._table(lib.rid, lib.tid)["version"]
    events = lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'lineage_changed'").fetchone()[0]
    if location == "proposal":
        original = LineageStore.apply_model_proposal
        calls = []
        def fail(self, **kw):
            calls.append(kw)
            result = original(self, **kw)
            if len(calls) == 2:
                raise RuntimeError("SYNTHETIC transaction fault")
            return result
        monkeypatch.setattr(LineageStore, "apply_model_proposal", fail)
    else:
        original = lib.store.finish_step
        def fail(step_id, status, **kw):
            result = original(step_id, status, **kw)
            if kw.get("output", {}).get("published") is not None:
                raise RuntimeError("SYNTHETIC record fault")
            return result
        monkeypatch.setattr(lib.store, "finish_step", fail)
    state = execute(lib, run)
    assert state["status"] == "failed" and state["pause_reason"] == "lineage_publication_failed"
    assert revisions(lib) == [] and publication(lib, run) is None
    assert lib.conn.execute("SELECT COUNT(*) FROM lineage_links").fetchone()[0] == 0
    assert lib.tables._table(lib.rid, lib.tid)["version"] == version
    assert lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'lineage_changed'").fetchone()[0] == events


def test_human_decision_in_flight_is_recorded_superseded_by_human(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: human_add(lib)
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "superseded_by_human"
    assert next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert lib.lineage._current(lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"]))["author"] == "human"


def test_selection_change_in_flight_is_recorded_stale_input(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: selection_edit(lib, "h")
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "stale_input"


def test_human_decision_survives_a_later_model_run(lib):
    human_rev = human_add(lib)
    run = queue(lib)
    assert run["target"]["chunks"] == []
    execute(lib, run)
    assert lib.adapter.calls == [] and len(revisions(lib)) == 1
    assert lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])["current_revision_id"] == human_rev
    assert lib.planner.build_plan(lib.rid, lib.tid)["selected"] == []


def test_second_run_progresses_and_skips_unchanged(factory):
    lib = factory(n=28, all_pdf=True)
    first = queue(lib)
    execute(lib, first)
    assert len(publication(lib, first)["targets"]) == 25
    calls = len(lib.adapter.calls)
    second = queue(lib)
    assert [s["position"] for s in second["target"]["selected"]] == [25, 26, 27]
    execute(lib, second)
    assert len(lib.adapter.calls) == calls
    assert lib.planner.build_plan(lib.rid, lib.tid)["selected"] == []
    instruction_edit(lib)
    assert all(s["class"] == "changed" for s in lib.planner.build_plan(lib.rid, lib.tid)["selected"])


def test_repair_counter_survives_pause_and_restart_between_invalid_answer_and_repair(lib):
    lib.adapter.responder = invalid
    run = queue(lib)
    lib.adapter.before = lambda si: lib.store.update_run(run["id"], status="pause_requested")
    assert execute(lib, run)["status"] == "paused" and len(lib.adapter.calls) == 1
    lib.worker.recover()
    lib.adapter.before = None
    assert resume(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2
    assert len(publication(lib, run)["step_failed"]) == 1 and revisions(lib) == []
    execute(lib, run)
    assert len(lib.adapter.calls) == 2


def test_lineage_run_has_no_provider_request_and_no_other_model_task(lib):
    run = queue(lib)
    state = execute(lib, run)
    assert state["budget"]["max_provider_requests"] == 0
    assert state["usage"].get("provider_requests", 0) == 0 and lib.seen == []
    assert {si["task_type"] for si in lib.adapter.calls} == {"lineage_links"}


@pytest.mark.parametrize("status", ["paused", "failed"])
def test_research_view_with_a_lineage_run_in_each_status_returns_200(lib, status):
    run = queue(lib)
    lib.store.update_run(run["id"], status=status)
    app = create_app(lib.flow.deps.settings, adapters={"fake": lib.adapter}, http_client=lib.http,
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    # Open a second API connection to the same synthetic database, as the real app does.
    settings = lib.flow.deps.settings
    # Settings' data_dir owns its database; backup preserves this test's frozen run and sources.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    destination = db.connect(settings.data_dir / "library.sqlite")
    lib.conn.backup(destination)
    destination.close()
    with TestClient(app) as client:
        app.state.store.update_run(run["id"], status=status)
        assert client.get(f"/api/researches/{lib.rid}").status_code == 200
        assert app.state.store.run(run["id"])["status"] == status
