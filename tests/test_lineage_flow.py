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
from deixis.models import prompt
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.lineage import run as lineage
from deixis.workflow.lineage.store import LineageStore
from deixis.workflow.worker import Worker
from fakes import FakeAdapter, valid_response
from test_lineage_plan import attach, candidate, fill, make_env


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.flow.RATE_LIMIT_BACKOFF_SECONDS", 0)
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


@pytest.mark.parametrize("verdict", ["no_relation", "insufficient_evidence"])
def test_no_relation_with_a_present_edge_publishes_no_link(lib, verdict):
    frm, to = lib.ids["a"], lib.ids["b"]
    lib.conn.execute("INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                     " VALUES (?, 'openalex', 'W1', 'synthetic', 'now')", (frm,))
    lib.conn.execute("UPDATE source_versions SET references_read = 1 WHERE id = ?", (to,))
    lib.conn.execute("INSERT INTO record_references (source_version_id, referenced_id) VALUES (?, 'W1')", (to,))

    def respond(si):
        result = json.loads(valid_response(si))
        assert si["lineage_target"]["candidates"][0]["edge_state"] == "present"
        result["decisions"][0].update(decision=verdict, relation=None, what_changed=None, support_type=None, evidence=[])
        return json.dumps(result)

    lib.adapter.responder = respond
    run = queue(lib)
    assert execute(lib, run)["status"] == "completed"
    assert lib.lineage.active_links(lib.tid) == []
    assert revisions(lib)[0]["decision"] == verdict


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


def test_whitespace_explanation_is_repaired_before_both_decisions_publish(factory):
    lib = factory(mentions=(0, 2))

    def respond(si):
        answer = json.loads(all_links(si))
        assert len(answer["decisions"]) == 2
        if len(lib.adapter.calls) == 1:
            answer["decisions"][0]["what_changed"] = "   "
        return json.dumps(answer)

    lib.adapter.responder = respond
    run = queue(lib)
    result = execute(lib, run)
    assert result["status"] == "completed" and result["pause_reason"] != "lineage_publication_failed"
    assert len(lib.adapter.calls) == 2
    sessions = lib.conn.execute("SELECT validation_json, step_input_id FROM model_sessions ORDER BY rowid").fetchall()
    assert "what_changed_empty" in sessions[0]["validation_json"]
    repair = lib.conn.execute("SELECT user_message FROM step_inputs WHERE id = ?", (sessions[1]["step_input_id"],)).fetchone()[0]
    assert "non-whitespace" in repair
    links = lib.lineage.active_links(lib.tid)
    assert len(links) == len(revisions(lib)) == 2
    assert all(lib.lineage._current(link)["what_changed"] == "SYNTHETIC change" for link in links)
    assert publication(lib, run)["counts"]["accepted"] == 2
    assert publication(lib, run)["step_failed"] == []


def test_nine_candidates_are_two_calls(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    run = queue(lib)
    execute(lib, run)
    assert len(lib.adapter.calls) == 2
    assert [len(si["lineage_target"]["candidates"]) for si in lib.adapter.calls] == [8, 1]
    assert len(publication(lib, run)["published"]) == 9


@pytest.mark.parametrize("path", ["first", "repair", "rate_limit", "outcome_unknown"])
def test_each_send_checks_the_budget(lib, path):
    run = queue(lib)
    limit = 0 if path == "first" else 1
    run["budget"]["max_model_calls"] = limit
    lib.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (db.dumps(run["budget"]), run["id"]))
    if path == "repair":
        lib.adapter.responder = invalid
    elif path == "rate_limit":
        lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC HTTP 429")
    elif path == "outcome_unknown":
        step = lib.store.step(run["id"], run["target"]["chunks"][0]["key"], "model:lineage_links")
        lib.store.start_step(step["id"])
        lib.worker.recover()
        lib.conn.execute("UPDATE runs SET usage_json = '{\"model_calls\":1}' WHERE id = ?", (run["id"],))
        lib.store.update_run(run["id"], status="running")
    state = execute(lib, lib.store.run(run["id"]))
    assert state["status"] == "paused" and state["pause_reason"] == "budget_exhausted"
    assert state["usage"].get("model_calls", 0) <= limit
    assert len(lib.adapter.calls) == (1 if path in ("repair", "rate_limit") else 0)
    assert publication(lib, run) is None and revisions(lib) == []


def test_budget_exhaustion_pauses_and_invents_no_relation(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    run = queue(lib)
    lib.conn.execute("UPDATE runs SET budget_json = '{\"max_model_calls\":1,\"max_provider_requests\":0}' WHERE id = ?", (run["id"],))
    state = execute(lib, lib.store.run(run["id"]))
    assert state["pause_reason"] == "budget_exhausted" and revisions(lib) == []
    assert publication(lib, run) is None


def test_resume_after_budget_pause_makes_no_progress_and_keeps_the_counter(lib):
    lib.adapter.responder = invalid
    run = queue(lib)
    lib.conn.execute("UPDATE runs SET budget_json = '{\"max_model_calls\":1,\"max_provider_requests\":0}' WHERE id = ?", (run["id"],))
    execute(lib, lib.store.run(run["id"]))
    state = resume(lib, run)
    assert state["pause_reason"] == "budget_exhausted" and state["usage"]["model_calls"] == 1
    assert len(lib.adapter.calls) == 1 and revisions(lib) == []
    output = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"]
    assert output["step_input_id"] == lib.adapter.calls[0]["step_input_id"]
    assert output["send_record"]["pairs"][0]["pair_fp"] == run["target"]["selected"][0]["candidates"][0]["pair_fp"]


def test_message_too_large_is_terminal_and_sends_nothing(lib, monkeypatch):
    run = queue(lib)
    original = prompt.step_message
    monkeypatch.setattr(prompt, "step_message", lambda si: original(si) + "x" * 48_000)
    assert execute(lib, run)["status"] == "completed"
    assert lib.adapter.calls == [] and revisions(lib) == []
    assert publication(lib, run)["step_failed"][0]["reason"] == "message_too_large"


def test_repair_message_over_48000_is_not_sent(lib, monkeypatch):
    lib.adapter.responder = invalid
    run = queue(lib)
    original = prompt.repair_message
    monkeypatch.setattr(prompt, "repair_message", lambda *args: original(*args) + "x" * 48_000)
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 1
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    assert step["error_code"] == "message_too_large" and "anchor_not_in_passage" in step["error_json"]
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 1
    assert lib.conn.execute("SELECT validation_json FROM model_sessions").fetchone()[0]


def test_invalid_after_one_repair_is_step_failed_and_others_still_publish(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    lib.adapter.responder = lambda si: invalid(si) if len(si["lineage_target"]["candidates"]) == 8 else valid_response(si)
    run = queue(lib)
    execute(lib, run)
    record = publication(lib, run)
    assert len(record["step_failed"]) == 1 and len(record["failed_pairs"]) == 8
    assert len(record["published"]) == 1 and len(revisions(lib)) == 1


def test_default_tasks_do_not_see_the_new_hooks(lib):
    run = lib.store.create_run(lib.rid, "research_title", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    lib.store.update_run(run["id"], status="running")
    execute(lib, run)
    step = lib.store.existing_step(run["id"], "research_title")
    assert lib.store.run(run["id"])["status"] == "completed"
    assert step and "send_record" not in step["output"] and len(lib.adapter.calls) == 1


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


def test_cancel_between_repair_and_resend_sends_nothing_more(lib):
    run = queue(lib)
    lib.adapter.responder = invalid
    lib.adapter.before = lambda si: lib.store.update_run(run["id"], status="cancelled")
    execute(lib, run)
    assert len(lib.adapter.calls) == 1 and revisions(lib) == []
    assert lib.conn.execute("SELECT validation_json FROM model_sessions").fetchone()[0]


def test_pause_requested_at_the_barrier_does_not_complete_the_run(lib, monkeypatch):
    run = queue(lib)
    original = lib.flow._send_through_limiter

    async def barrier(*args):
        result = await original(*args)
        lib.store.update_run(run["id"], status="pause_requested")
        return result

    monkeypatch.setattr(lib.flow, "_send_through_limiter", barrier)
    assert execute(lib, run)["status"] == "paused"
    assert publication(lib, run) is None and revisions(lib) == []


def test_new_scope_revision_cancels_and_nothing_is_published(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: scope_edit(lib)
    state = execute(lib, run)
    assert state["status"] == "cancelled" and state["pause_reason"] == "scope_revised"
    assert revisions(lib) == [] and publication(lib, run) is None


def test_outcome_unknown_resend_uses_budget_and_does_not_double_publish(lib):
    run = queue(lib)
    lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC unknown delivery", delivery_class="after_send_unknown")
    assert execute(lib, run)["status"] == "paused"
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    assert step["status"] == "outcome_unknown" and revisions(lib) == []
    lib.adapter.fail = None
    assert resume(lib, run)["status"] == "completed"
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 2 and len(revisions(lib)) == 1
    execute(lib, run)
    assert len(revisions(lib)) == 1 and len(lib.adapter.calls) == 2


def test_late_result_after_pause_is_not_applied(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: lib.store.update_run(run["id"], status="paused", pause_reason="SYNTHETIC pause")
    assert execute(lib, run)["status"] == "paused"
    assert revisions(lib) == []
    assert lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["status"] == "succeeded"


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
    assert len(lib.adapter.calls) == 1 and len(revisions(lib)) == 1


def test_crash_after_publication_does_not_publish_twice_or_call_the_model(lib):
    run = queue(lib)
    execute(lib, run)
    before = revisions(lib)
    # The publication transaction committed; the completion write was lost.
    lib.store.update_run(run["id"], status="running")
    assert lib.worker.recover()["runs"] == 1
    assert resume(lib, run)["status"] == "completed"
    assert revisions(lib) == before and len(lib.adapter.calls) == 1


def test_publication_order_is_fixed_when_calls_finish_out_of_order(factory, monkeypatch):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    lib.flow.deps.limiter = ModelCallLimiter(3)
    run = queue(lib)
    finishes, applied = [], []
    original_call = lib.adapter.run_step
    original_apply = LineageStore.apply_model_proposal

    async def reverse(*args):
        from fakes import parse_step_input
        si = parse_step_input(args[2])
        size = len(si["lineage_target"]["candidates"])
        await asyncio.sleep(0.03 if size == 8 else 0)
        result = await original_call(*args)
        finishes.append(size)
        return result

    def record(self, **kw):
        assert self.conn.in_transaction
        applied.append((kw["to_svid"], kw["from_svid"]))
        return original_apply(self, **kw)

    monkeypatch.setattr(lib.adapter, "run_step", reverse)
    monkeypatch.setattr(LineageStore, "apply_model_proposal", record)
    execute(lib, run)
    assert finishes == [1, 8]
    assert applied == sorted(applied) and len(applied) == 9
    assert [(p["to"], p["from"]) for p in publication(lib, run)["published"]] == applied


@pytest.mark.parametrize("location", ["proposal", "publication_record"])
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


@pytest.mark.parametrize("change,code", [("exclude", "endpoint_not_included"), ("extraction", "stale_input"),
                                         ("instruction", "stale_input"), ("human", "superseded_by_human")])
def test_stored_success_is_kept_and_judged_while_unsuccessful_steps_are_resent_with_the_current_input(factory, change, code):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    run = queue(lib)
    lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC unavailable") if len(lib.adapter.calls) == 2 else None
    assert execute(lib, run)["status"] == "paused"
    first = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"]
    if change == "exclude":
        selection_edit(lib, "b")
    elif change == "extraction":
        reextract(lib, text="SYNTHETIC: " + " ".join(f"Author{i:03d} ({2000+i})" for i in range(10) if i != 1))
    elif change == "instruction":
        instruction_edit(lib)
    else:
        human_add(lib)
    lib.adapter.fail = None
    assert resume(lib, run)["status"] == "completed"
    published = publication(lib, run)["published"]
    assert any(p["rejection_code"] == code for p in published)
    assert lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"] == first
    assert len([r for r in revisions(lib) if r["step_input_id"] == first["step_input_id"]]) == 8
    if change in ("exclude", "extraction"):
        assert len(lib.adapter.calls) == 2
        record = publication(lib, run)
        assert record["skipped"] and record["targets"][0]["outcome"] == "incomplete"
        if change == "extraction":
            next_plan = lib.planner.build_plan(lib.rid, lib.tid)
            assert next_plan["chunks"][0]["shown_passage_ids"] != run["target"]["chunks"][0]["shown_passage_ids"]
    else:
        assert len(lib.adapter.calls) == 3
        if change == "instruction":
            assert lib.adapter.calls[-1]["lineage_target"]["to"]["cells"][0]["instruction"] == "SYNTHETIC edited instruction"


def test_end_excluded_in_flight_is_recorded_endpoint_not_included(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: selection_edit(lib)
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "endpoint_not_included"
    assert next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert lib.lineage.active_links(lib.tid) == []


def test_human_decision_in_flight_is_recorded_superseded_by_human(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: human_add(lib)
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "superseded_by_human"
    assert next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert lib.lineage._current(lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"]))["author"] == "human"


@pytest.mark.parametrize("edit", [instruction_edit, lambda lib: fill(lib)])
def test_cell_or_instruction_change_in_flight_is_recorded_stale_input(lib, edit):
    run = queue(lib)
    lib.adapter.before = lambda si: edit(lib)
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "stale_input"
    assert next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert lib.lineage.active_links(lib.tid) == []


def test_pdf_extraction_change_in_flight_is_recorded_stale_input(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: reextract(lib, allow_run_id=run["id"])
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "stale_input"
    assert revisions(lib)[0]["decision"] == "link"


def test_selection_change_in_flight_is_recorded_stale_input(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: selection_edit(lib, "h")
    execute(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "stale_input"


def test_superseded_cited_passage_shown_through_another_candidate_is_recorded_stale_input(factory):
    lib = factory(n=6, mentions=(0, 2), only_target=True)
    # One candidate's own mention is an abstract; the other brings the PDF into the same chunk.
    abstract = lib.store._insert_passage(lib.ids["b"], None, "abstract", None, None, "synthetic", None, None,
                                         "SYNTHETIC: Author000 (2000) extends a method.")
    reextract(lib, text="SYNTHETIC: Author002 (2002) changes a method.")
    run = queue(lib)
    def respond(si):
        answer = json.loads(all_links(si))
        pdf = next(p for p in si["passages"] if p["locator"]["kind"] == "pdf_page")
        answer["decisions"][0].update(support_type="analyst_inference",
            evidence=[{"passage_id": pdf["passage_id"], "quote": pdf["text"]}])
        return json.dumps(answer)
    lib.adapter.responder = respond
    lib.adapter.before = lambda si: reextract(lib, text="SYNTHETIC: Author002 (2002) newer extraction.", allow_run_id=run["id"])
    execute(lib, run)
    assert abstract in {p["id"] for p in lib.store.passages_for(lib.ids["b"])}
    assert all(p["rejection_code"] == "stale_input" for p in publication(lib, run)["published"])
    assert lib.lineage.active_links(lib.tid) == []


def test_stored_successful_output_is_checked_at_publication_even_after_a_human_decision_on_resume(lib):
    run = queue(lib)
    lib.adapter.before = lambda si: lib.store.update_run(run["id"], status="pause_requested")
    execute(lib, run)
    rev = human_add(lib)
    lib.adapter.before = None
    resume(lib, run)
    assert publication(lib, run)["published"][0]["rejection_code"] == "superseded_by_human"
    assert lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])["current_revision_id"] == rev
    assert len(lib.adapter.calls) == 1


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


def test_incomplete_target_is_retried_with_only_its_missing_pairs(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    first = queue(lib)
    execute(lib, first)
    assert publication(lib, first)["targets"][0]["outcome"] == "incomplete"
    second = queue(lib)
    assert second["target"]["selected"][0]["class"] == "retry"
    assert sum(len(c["from"]) for c in second["target"]["chunks"]) == 3
    execute(lib, second)
    assert len(lib.adapter.calls) == 4 and len(revisions(lib)) == 27
    assert lib.planner.build_plan(lib.rid, lib.tid)["selected"] == []


def test_failed_chunks_do_not_block_the_remaining_pairs_in_later_runs(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    lib.adapter.responder = invalid
    first = queue(lib)
    execute(lib, first)
    assert len(publication(lib, first)["failed_pairs"]) == 24
    lib.adapter.responder = valid_response
    second = queue(lib)
    assert len(second["target"]["failed_unchanged"]) == 24
    assert sum(len(c["from"]) for c in second["target"]["chunks"]) == 3
    execute(lib, second)
    assert lib.planner.build_plan(lib.rid, lib.tid)["selected"] == []
    retry = lib.planner.build_plan(lib.rid, lib.tid, retry_failed=True)
    assert retry["selected"][0]["class"] == "retry"
    assert sum(len(c["from"]) for c in retry["chunks"]) == 24


def test_retry_failed_reopens_carried_failures_after_remaining_pairs_settle(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    lib.adapter.responder = invalid
    first = queue(lib)
    assert execute(lib, first)["status"] == "completed"
    failed = {p["from"] for p in publication(lib, first)["failed_pairs"]}
    assert len(failed) == 24
    remaining = {p["from"] for p in first["target"]["not_sent_budget"] if p["reason"] == "beyond_call_limit"}
    assert len(remaining) == 3 and not failed & remaining

    lib.adapter.responder = valid_response
    second = queue(lib)
    assert {p["from"] for p in second["target"]["failed_unchanged"]} == failed
    assert {frm for c in second["target"]["chunks"] for frm in c["from"]} == remaining
    assert execute(lib, second)["status"] == "completed"
    record = publication(lib, second)
    assert record["failed_pairs"] == [] and record["targets"][0]["outcome"] == "settled"
    assert second["target"]["selected"][0]["target_fp"] == first["target"]["selected"][0]["target_fp"]
    assert lib.planner.preview(lib.rid, lib.tid)["selected"] == []

    third = queue(lib, retry_failed=True)
    assert third["target"]["selected"][0]["class"] == "retry"
    assert third["target"]["failed_unchanged"] == []
    assert {frm for c in third["target"]["chunks"] for frm in c["from"]} == failed
    assert execute(lib, third)["status"] == "completed"
    assert len(publication(lib, third)["published"]) == 24 and len(revisions(lib)) == 27
    assert lib.planner.preview(lib.rid, lib.tid, retry_failed=True)["selected"] == []


@pytest.mark.parametrize("author,change", [("model", "cell"), ("model", "instruction"), ("model", "scope"),
    ("model", "selection"), ("human", "selection"), ("model", "removed"), ("human", "removed"),
    ("model", "replaced"), ("human", "replaced"), ("model", "extraction"), ("human", "extraction")])
def test_stale_edges_leave_the_cycle_graph_by_revision(lib, author, change):
    if author == "model":
        run = queue(lib)
        execute(lib, run)
    else:
        human_add(lib)
    pair = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    original = pair["current_revision_id"]
    if change == "cell":
        fill(lib)
    elif change == "instruction":
        instruction_edit(lib)
    elif change == "scope":
        scope_edit(lib)
    elif change == "selection":
        selection_edit(lib, "h")
    elif change in ("removed", "replaced"):
        lib.store.remove_asset(lib.rid, lib.ids["b"], lib.assets[lib.ids["b"]])
        if change == "replaced":
            attach(lib, lib.ids["b"], "SYNTHETIC replacement Author000 (2000)", "SYNTHETIC-v2")
    else:
        reextract(lib)
    stale = lineage.stale_link_revisions(lib.store, lib.tid)
    assert (stale.get(pair["id"]) == original) == (change != "selection")
    closing = lib.lineage.ensure_link(lib.tid, lib.ids["b"], lib.ids["a"])
    assert lib.lineage._cycle(closing, stale) == (change == "selection")
    assert lib.lineage.link_by_id(pair["id"])["current_revision_id"] == original
    if change == "cell":
        refresh = queue(lib)
        execute(lib, refresh)
        updated = lib.lineage.link_by_id(pair["id"])
        assert updated["current_revision_id"] != original
        # An old stale map never hides a refreshed revision.
        assert lib.lineage._cycle(closing, stale)
        assert lineage.stale_link_revisions(lib.store, lib.tid) == {}


@pytest.mark.parametrize("phase", ["limiter", "health", "backoff"])
@pytest.mark.parametrize("signal", ["pause_requested", "paused", "cancelled", "scope"])
def test_pause_cancel_or_scope_change_during_limiter_wait_health_and_backoff_stops_the_send(lib, monkeypatch, phase, signal):
    run = queue(lib)
    def steer():
        if signal == "scope":
            scope_edit(lib)
        else:
            lib.store.update_run(run["id"], status=signal)

    async def scenario():
        if phase == "health":
            original = lib.adapter.health
            async def health(*args):
                await asyncio.sleep(0)
                steer()
                return await original(*args)
            monkeypatch.setattr(lib.adapter, "health", health)
            await lib.flow.execute(run["id"])
        elif phase == "backoff":
            lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC 429")
            original = asyncio.sleep
            async def sleep(seconds):
                steer()
                await original(0)
            monkeypatch.setattr("deixis.workflow.flow.asyncio.sleep", sleep)
            await lib.flow.execute(run["id"])
        else:
            entered, release = asyncio.Event(), asyncio.Event()
            async def occupy():
                entered.set()
                await release.wait()
            holder = asyncio.create_task(lib.flow.deps.limiter.run("SYNTHETIC occupied slot", occupy))
            await entered.wait()
            task = asyncio.create_task(lib.flow.execute(run["id"]))
            while run["target"]["chunks"][0]["key"] not in lib.flow.deps.limiter._by_key:
                await asyncio.sleep(0)
            steer()
            release.set()
            await asyncio.gather(task, holder)

    asyncio.run(scenario())
    state = lib.store.run(run["id"])
    assert state["status"] == ("cancelled" if signal in ("cancelled", "scope") else "paused")
    assert len(lib.adapter.calls) == (1 if phase == "backoff" else 0)
    assert revisions(lib) == [] and publication(lib, run) is None


def test_rate_limit_retries_are_at_most_two_per_attempt_per_chunk_and_then_pause_as_model_failure(factory):
    lib = factory(n=12, mentions=tuple(i for i in range(10) if i != 1), only_target=True)
    lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC 429")
    run = queue(lib)
    state = execute(lib, run)
    assert state["status"] == "paused" and state["pause_reason"] == "model_call_failed"
    assert len(lib.adapter.calls) == state["usage"]["model_calls"] == 3
    assert len({si["step_input_id"] for si in lib.adapter.calls}) == 1
    assert state["budget"]["max_model_calls"] == 12
    assert lib.store.existing_step(run["id"], run["target"]["chunks"][1]["key"]) is None


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


@pytest.mark.parametrize("status", ["paused", "pause_requested", "cancelled", "scope"])
def test_barrier_stop_leaves_the_run_paused_or_cancelled_never_completed(lib, monkeypatch, status):
    run = queue(lib)
    original = lib.flow._send_through_limiter
    async def barrier(*args):
        result = await original(*args)
        if status == "scope":
            scope_edit(lib)
        else:
            lib.store.update_run(run["id"], status=status)
        return result
    monkeypatch.setattr(lib.flow, "_send_through_limiter", barrier)
    state = execute(lib, run)
    assert state["status"] == ("cancelled" if status in ("cancelled", "scope") else "paused")
    assert publication(lib, run) is None and revisions(lib) == []


@pytest.mark.parametrize("phase", ["health", "repair"])
def test_send_record_comes_from_the_real_payload_not_from_the_job_build(lib, monkeypatch, phase):
    run = queue(lib)
    if phase == "health":
        original = lib.adapter.health
        async def health(*args):
            await asyncio.sleep(0)
            lib.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed during health' WHERE id = ?", (lib.ids["a"],))
            instruction_edit(lib)
            return await original(*args)
        monkeypatch.setattr(lib.adapter, "health", health)
    else:
        def respond(si):
            if len(lib.adapter.calls) == 1:
                instruction_edit(lib)
                return invalid(si)
            return valid_response(si)
        lib.adapter.responder = respond
    execute(lib, run)
    assert publication(lib, run)["published"][0]["disposition"] == "accepted"
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    payload = lib.store.step_input_payload(step["output"]["step_input_id"])
    sent = step["output"]["send_record"]
    assert sent["pairs"][0]["pair_fp"] == lineage.pair_fp(payload, sent["selection_revision"], lib.ids["a"], run["target"]["model"][2])
    assert sent["pairs"][0]["pair_fp"] != run["target"]["selected"][0]["candidates"][0]["pair_fp"]
    assert next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert payload["lineage_target"]["to"]["cells"][0]["instruction"] == "SYNTHETIC edited instruction"
    assert step["operation_key"] == run["target"]["chunks"][0]["key"]


@pytest.mark.parametrize("sent_pdf", [True, False])
def test_shared_source_that_goes_metadata_to_pdf_and_back_is_judged_by_what_was_sent(lib, monkeypatch, sent_pdf):
    # The from-end is abstract-only at planning time; its first PDF moves no revision counter.
    run = queue(lib)
    other_rid = lib.store.create_research("SYNTHETIC shared source?", "attached", "quick", [], "fake", "fake-model", "en")
    lib.store.add_to_corpus(other_rid, lib.ids["a"], "user_upload", selection_state="included", selection_origin="user")
    selection_revision = lib.store.selection_revision(lib.rid)
    assets = []
    original = lib.adapter.health
    async def health(*args):
        aid = attach(lib, lib.ids["a"], "SYNTHETIC from work PDF")
        assets.append(aid)
        if not sent_pdf:
            lib.store.remove_asset(other_rid, lib.ids["a"], aid)
        return await original(*args)
    monkeypatch.setattr(lib.adapter, "health", health)
    def remove(si):
        if sent_pdf:
            lib.store.remove_asset(other_rid, lib.ids["a"], assets[0])
    lib.adapter.before = remove
    execute(lib, run)
    result = publication(lib, run)["published"][0]
    assert result["rejection_code"] == ("stale_input" if sent_pdf else None)
    assert lib.store.selection_revision(lib.rid) == selection_revision
    if sent_pdf:
        target = next(t for t in publication(lib, run)["targets"] if t["to"] == lib.ids["b"])
        assert target["outcome"] == "incomplete"
        for retry_failed in (False, True):
            preview = lib.planner.build_plan(lib.rid, lib.tid, retry_failed)
            selected = next(s for s in preview["selected"] if s["to"] == lib.ids["b"])
            assert selected["class"] == "retry" and selected["target_fp"] == target["target_fp"]
            assert preview["chunks"][0]["from"] == [lib.ids["a"]]


@pytest.mark.parametrize("sent_pdf", [True, False])
def test_failed_shared_source_pdf_round_trip_retries_only_if_sent_input_differs_from_plan(lib, monkeypatch, sent_pdf):
    run = queue(lib)
    other_rid = lib.store.create_research("SYNTHETIC shared source?", "attached", "quick", [], "fake", "fake-model", "en")
    lib.store.add_to_corpus(other_rid, lib.ids["a"], "user_upload", selection_state="included", selection_origin="user")
    selection_revision = lib.store.selection_revision(lib.rid)
    assets = []
    original = lib.adapter.health

    async def health(*args):
        await asyncio.sleep(0)
        if not assets:
            aid = attach(lib, lib.ids["a"], "SYNTHETIC from work PDF")
            assets.append(aid)
            if not sent_pdf:
                lib.store.remove_asset(other_rid, lib.ids["a"], aid)
        return await original(*args)

    monkeypatch.setattr(lib.adapter, "health", health)
    lib.adapter.responder = invalid

    def remove_after_last_send(si):
        if sent_pdf and len(lib.adapter.calls) == 2:
            lib.store.remove_asset(other_rid, lib.ids["a"], assets[0])

    lib.adapter.before = remove_after_last_send
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2 and revisions(lib) == []
    assert lib.store.selection_revision(lib.rid) == selection_revision
    assert all(p["kind"] != "pdf_page" for p in lib.store.passages_for(lib.ids["a"]))
    planned = next(s for s in run["target"]["selected"] if s["to"] == lib.ids["b"])
    record = publication(lib, run)
    assert len(record["failed_pairs"]) == 1
    assert (record["failed_pairs"][0]["pair_fp"] != planned["candidates"][0]["pair_fp"]) == sent_pdf
    target = next(t for t in record["targets"] if t["to"] == lib.ids["b"])
    assert target["target_fp"] == planned["target_fp"]
    assert target["outcome"] == ("incomplete" if sent_pdf else "settled")

    preview = lib.planner.preview(lib.rid, lib.tid)
    if sent_pdf:
        assert preview["selected"][0]["class"] == "retry"
        assert preview["selected"][0]["target_fp"] == planned["target_fp"]
        assert preview["selected"][0]["candidate_count"] == 1 and preview["calls"] == 1
        pending = lib.planner.build_plan(lib.rid, lib.tid)
        assert pending["failed_unchanged"] == [] and pending["chunks"][0]["from"] == [lib.ids["a"]]
        assert pending["selected"][0]["candidates"][0]["pair_fp"] == planned["candidates"][0]["pair_fp"]
    else:
        assert preview["selected"] == [] and preview["calls"] == 0
        assert lib.planner.preview(lib.rid, lib.tid, retry_failed=True)["calls"] == 1


def test_terminal_failure_keeps_the_sent_fingerprint_and_a_plan_with_another_fingerprint_does_not_treat_the_pair_as_known_failed(lib, monkeypatch):
    run = queue(lib)
    original = lib.adapter.health
    async def health(*args):
        instruction_edit(lib)
        return await original(*args)
    monkeypatch.setattr(lib.adapter, "health", health)
    lib.adapter.responder = invalid
    # Lose the completion, then recover; terminal invalid chunks must not be called again.
    execute(lib, run)
    sent = publication(lib, run)["failed_pairs"][0]["pair_fp"]
    planned = run["target"]["selected"][0]["candidates"][0]["pair_fp"]
    assert sent != planned
    lib.store.update_run(run["id"], status="running")
    lib.worker.recover()
    resume(lib, run)
    assert len(lib.adapter.calls) == 2
    fill(lib, text="SYNTHETIC new fingerprint after terminal failure")
    plan = lib.planner.build_plan(lib.rid, lib.tid)
    assert plan["failed_unchanged"] == [] and plan["chunks"]


def test_message_too_large_failure_keeps_a_record(lib, monkeypatch):
    run = queue(lib)
    original = prompt.step_message
    monkeypatch.setattr(prompt, "step_message", lambda si: original(si) + "x" * 48_000)
    execute(lib, run)
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    blocked = step["output"]["blocked_send_record"]["send_record"]
    payload = lib.store.step_input_payload(step["output"]["blocked_step_input_id"])
    assert step["output"]["step_input_id"] is None and "send_record" not in step["output"]
    assert blocked["pairs"][0]["pair_fp"] == lineage.pair_fp(payload, blocked["selection_revision"], lib.ids["a"], run["target"]["model"][2])
    assert blocked["passages"][0]["current"] is True
    assert publication(lib, run)["failed_pairs"] == []
    lib.store.update_run(run["id"], status="running")
    lib.worker.recover()
    resume(lib, run)
    assert len(lib.adapter.calls) == 0


def test_first_message_blocked_by_shared_pdf_remains_pending_after_pdf_removal(lib, monkeypatch):
    _, _, payload = candidate(lib)
    title = lib.store.source(lib.ids["a"])["title"]
    padding = 47_999 - lib.flow.lineage_message_chars(payload)
    assert padding > 0
    lib.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (title + "x" * padding, lib.ids["a"]))
    assert lib.flow.lineage_message_chars(candidate(lib)[2]) == 47_999
    run = queue(lib)
    planned = next(s for s in run["target"]["selected"] if s["to"] == lib.ids["b"])
    other_rid = lib.store.create_research("SYNTHETIC shared source?", "attached", "quick", [], "fake", "fake-model", "en")
    lib.store.add_to_corpus(other_rid, lib.ids["a"], "user_upload", selection_state="included", selection_origin="user")
    selection = lib.store.selection_revision(lib.rid)
    assets = []
    original = lib.adapter.health

    async def health(*args):
        await asyncio.sleep(0)
        assets.append(attach(lib, lib.ids["a"], "SYNTHETIC shared PDF"))
        return await original(*args)

    monkeypatch.setattr(lib.adapter, "health", health)
    assert execute(lib, run)["status"] == "completed"
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    blocked_id = step["output"]["blocked_step_input_id"]
    assert len(lib.conn.execute("SELECT user_message FROM step_inputs WHERE id = ?", (blocked_id,)).fetchone()[0]) == 48_002
    assert lib.adapter.calls == [] and revisions(lib) == []
    assert lib.conn.execute("SELECT COUNT(*) FROM model_sessions").fetchone()[0] == 0
    record = publication(lib, run)
    assert record["failed_pairs"] == []
    assert next(t for t in record["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"

    lib.store.remove_asset(other_rid, lib.ids["a"], assets[0])
    assert lib.store.selection_revision(lib.rid) == selection
    for retry_failed in (False, True):
        preview = lib.planner.preview(lib.rid, lib.tid, retry_failed=retry_failed)
        assert preview["calls"] == 1
        selected = next(s for s in preview["selected"] if s["to"] == lib.ids["b"])
        assert selected["target_fp"] == planned["target_fp"]
        pending = lib.planner.build_plan(lib.rid, lib.tid, retry_failed)
        assert pending["failed_unchanged"] == []
        assert pending["chunks"][0]["from"] == [lib.ids["a"]]
        assert pending["selected"][0]["candidates"][0]["pair_fp"] == planned["candidates"][0]["pair_fp"]


@pytest.mark.parametrize("earlier_sent", [False, True])
def test_crash_before_session_start_then_oversized_resume_uses_only_session_backed_records(lib, monkeypatch, earlier_sent):
    class SyntheticCrash(BaseException):
        pass

    run = queue(lib)
    key = run["target"]["chunks"][0]["key"]
    unsent_ids = []
    original = lib.store.start_model_session

    def crash_before_start(rid, run_id, step_id, step_input_id, *args):
        if len(lib.adapter.calls) == int(earlier_sent):
            unsent_ids.append(step_input_id)
            raise SyntheticCrash
        return original(rid, run_id, step_id, step_input_id, *args)

    def respond(si):
        lib.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed before unsent repair' WHERE id = ?", (lib.ids["a"],))
        return invalid(si)

    lib.adapter.responder = respond
    with monkeypatch.context() as patch:
        patch.setattr(lib.store, "start_model_session", crash_before_start)
        with pytest.raises(SyntheticCrash):
            execute(lib, run)
    assert len(unsent_ids) == 1
    unsent_id = unsent_ids[0]
    assert lib.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE step_input_id = ?", (unsent_id,)).fetchone()[0] == 0
    assert len(lib.adapter.calls) == int(earlier_sent)
    assert lib.worker.recover()["runs"] == 1
    assert lib.store.run(run["id"])["pause_reason"] == "backend_restarted"
    sent_id = lib.adapter.calls[0]["step_input_id"] if earlier_sent else None
    selection = lib.store.selection_revision(lib.rid)
    unsent_fp = lineage.pair_fp(lib.store.step_input_payload(unsent_id), selection, lib.ids["a"], run["target"]["model"][2])
    sent_fp = (lineage.pair_fp(lib.store.step_input_payload(sent_id), selection, lib.ids["a"], run["target"]["model"][2])
               if earlier_sent else None)
    if earlier_sent:
        assert sent_fp != unsent_fp
    lib.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", ("SYNTHETIC oversized resume " + "x" * 48_000, lib.ids["a"]))
    assert resume(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == int(earlier_sent) and revisions(lib) == []
    output = lib.store.existing_step(run["id"], key)["output"]
    assert output["step_input_id"] == sent_id
    record = publication(lib, run)
    assert [p["pair_fp"] for p in record["failed_pairs"]] == ([sent_fp] if earlier_sent else [])
    assert all(p["pair_fp"] != unsent_fp for p in record["failed_pairs"])
    if not earlier_sent:
        assert next(t for t in record["targets"] if t["to"] == lib.ids["b"])["outcome"] == "incomplete"
    assert unsent_id in output["attempt_records"]
    if earlier_sent:
        assert output["attempt_records"][sent_id]["send_record"]["pairs"][0]["pair_fp"] == sent_fp


def test_unknown_repair_recovery_and_oversized_changed_input_keep_only_the_last_sent_fingerprint(lib):
    lib.adapter.responder = invalid
    lib.adapter.fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC repair outcome unknown",
                                  delivery_class="after_send_unknown") if len(lib.adapter.calls) == 2 else None)
    run = queue(lib)
    assert execute(lib, run)["status"] == "paused"
    key = run["target"]["chunks"][0]["key"]
    before = lib.store.existing_step(run["id"], key)
    assert before["status"] == "outcome_unknown"
    sent_id = lib.adapter.calls[-1]["step_input_id"]
    assert before["output"]["step_input_id"] == sent_id
    sent_fp = before["output"]["send_record"]["pairs"][0]["pair_fp"]
    lib.store.update_run(run["id"], status="running")
    assert lib.worker.recover()["runs"] == 1
    assert lib.store.existing_step(run["id"], key)["output"] == before["output"]

    # B fits as a first message; the resumed repair is too large and never sent.
    title = lib.store.source(lib.ids["a"])["title"]
    _, _, payload = candidate(lib)
    padding = 47900 - lib.flow.lineage_message_chars(payload)
    assert padding > 0
    lib.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (title + "x" * padding, lib.ids["a"]))
    _, _, b = candidate(lib)
    assert lib.flow.lineage_message_chars(b) <= 48000
    issues = json.loads(lib.conn.execute("SELECT validation_json FROM model_sessions WHERE validation_json IS NOT NULL").fetchone()[0])["issues"]
    assert len(prompt.repair_message(contracts.with_citation_handles(b), contracts.issues_with_handles(b, issues))) > 48000
    lib.adapter.fail = None
    assert resume(lib, run)["status"] == "completed"
    output = lib.store.existing_step(run["id"], key)["output"]
    assert output["step_input_id"] == sent_id
    blocked = lib.store.step_input_payload(output["blocked_step_input_id"])
    blocked_fp = output["blocked_send_record"]["send_record"]["pairs"][0]["pair_fp"]
    assert blocked_fp == lineage.pair_fp(blocked, output["send_record"]["selection_revision"], lib.ids["a"], run["target"]["model"][2])
    assert blocked_fp != sent_fp
    assert publication(lib, run)["failed_pairs"][0]["pair_fp"] == sent_fp
    preview = lib.planner.build_plan(lib.rid, lib.tid)
    assert preview["failed_unchanged"] == [] and preview["chunks"]
    assert len(lib.adapter.calls) == 2


@pytest.mark.parametrize("failure,reason", [
    (ModelStepResult("failed", error="SYNTHETIC failure"), "model_call_failed"),
    (ModelStepResult("isolation_violation", error="SYNTHETIC tool violation"), "model_isolation_violation"),
    (ModelStepResult("completed", resolved_model="SYNTHETIC wrong model"), "model_mismatch"),
])
def test_model_failure_paths_preserve_the_really_sent_input_and_record(lib, failure, reason):
    run = queue(lib)
    lib.adapter.fail = lambda si: failure
    assert execute(lib, run)["pause_reason"] == reason
    output = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"]
    assert output["step_input_id"] == lib.adapter.calls[0]["step_input_id"]
    assert output["send_record"]["pairs"][0]["pair_fp"] == run["target"]["selected"][0]["candidates"][0]["pair_fp"]
    lib.worker.recover()
    assert lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])["output"] == output


def test_oversized_changed_repair_records_the_last_sent_fingerprint(lib, monkeypatch):
    run = queue(lib)
    def respond(si):
        instruction_edit(lib)
        return invalid(si)
    lib.adapter.responder = respond
    original = prompt.repair_message
    monkeypatch.setattr(prompt, "repair_message", lambda *args: original(*args) + "x" * 48_000)
    execute(lib, run)
    step = lib.store.existing_step(run["id"], run["target"]["chunks"][0]["key"])
    output = step["output"]
    sent = output["send_record"]
    payload = lib.store.step_input_payload(output["step_input_id"])
    blocked = lib.store.step_input_payload(output["blocked_step_input_id"])
    fp = lineage.pair_fp(payload, sent["selection_revision"], lib.ids["a"], run["target"]["model"][2])
    assert fp == publication(lib, run)["failed_pairs"][0]["pair_fp"]
    assert fp != lineage.pair_fp(blocked, sent["selection_revision"], lib.ids["a"], run["target"]["model"][2])
    assert lib.planner.build_plan(lib.rid, lib.tid)["failed_unchanged"] == []
    assert len(lib.adapter.calls) == 1


def test_schema_repair_and_rate_limit_resends_share_the_six_call_ceiling(lib):
    run = queue(lib)
    lib.adapter.fail = lambda si: ModelStepResult("failed", error="SYNTHETIC 429") if len(lib.adapter.calls) % 3 else None
    lib.adapter.responder = invalid
    execute(lib, run)
    assert len(lib.adapter.calls) == lib.store.run(run["id"])["usage"]["model_calls"] == 6
    assert len({si["step_input_id"] for si in lib.adapter.calls}) == 2
    assert len(publication(lib, run)["step_failed"]) == 1


def test_health_wait_superseding_a_shown_passage_skips_without_a_model_send(lib, monkeypatch):
    run = queue(lib)
    original = lib.adapter.health
    async def health(*args):
        reextract(lib, allow_run_id=run["id"])
        return await original(*args)
    monkeypatch.setattr(lib.adapter, "health", health)
    execute(lib, run)
    record = publication(lib, run)
    assert len(record["skipped"]) == 1 and record["skipped"][0]["reason"] == "passage_not_current"
    assert record["targets"][0]["outcome"] == "incomplete"
    assert lib.adapter.calls == [] and revisions(lib) == []


@pytest.mark.parametrize("author", ["model", "human"])
def test_endpoint_exclusion_alone_is_left_to_l4_and_does_not_make_inputs_stale(lib, author):
    if author == "model":
        execute(lib, queue(lib))
    else:
        human_add(lib)
    pair = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    selection_edit(lib)
    assert lineage.stale_link_revisions(lib.store, lib.tid) == {}
    closing = lib.lineage.ensure_link(lib.tid, lib.ids["b"], lib.ids["a"])
    assert not lib.lineage._cycle(closing, {})
    assert lib.lineage.link_by_id(pair["id"])["current_revision_id"] == pair["current_revision_id"]


def test_lineage_run_has_no_provider_request_and_no_other_model_task(lib):
    run = queue(lib)
    state = execute(lib, run)
    assert state["budget"]["max_provider_requests"] == 0
    assert state["usage"].get("provider_requests", 0) == 0 and lib.seen == []
    assert {si["task_type"] for si in lib.adapter.calls} == {"lineage_links"}


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused", "cancelled", "completed", "failed"])
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


@pytest.mark.parametrize("missing", [False, True])
def test_unavailable_table_fails_without_a_call(lib, missing):
    run = queue(lib)
    if missing:
        from deixis.workflow.tables import _delete_tables
        lib.conn.execute("INSERT INTO table_purge_authorizations VALUES (?)", (lib.tid,))
        _delete_tables(lib.conn, "SELECT id FROM evidence_tables WHERE id = ?", (lib.tid,))
    else:
        lib.conn.execute("UPDATE evidence_tables SET trashed_at = 'SYNTHETIC' WHERE id = ?", (lib.tid,))
    assert execute(lib, run)["pause_reason"] == "table_unavailable"
    assert lib.adapter.calls == [] and publication(lib, run) is None
