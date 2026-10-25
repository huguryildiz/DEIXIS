"""Reverse citation search, slice R2: request, resume and recheck, the public start, the discovery-end hook, the
attached-scope path and staleness, with a FakeAdapter. Records, PDFs, the cutoff and model answers are SYNTHETIC and
scripted; nothing here calls a real model or the network, so these tests show what the workflow does, not how well any
model answers."""

import copy
import csv
import io
import json
import time
import pytest
from deixis.models.adapter import ModelStepResult
from deixis.workflow import fast_path, intent, statement_check
from fakes import valid_response
from test_abstract_flow import Pool, app_for, client_of
from test_statement_check import ABSTRACT, MODEL, SENTENCE, build, by_source, cutoff, execute, items, statement_calls, user
from deixis.domain import statement
from deixis.workflow import statement_check
from test_statement_check import ABSTRACT, MODEL, build, execute, items
from test_statement_check import answer, build, create, cutoff, execute, items, scripted


LITERATURE = {"model_connection": "fake", "model": "fake-model", "reasoning_effort": None}


def request(lib, request_id="req-1", model=MODEL, expected=None):
    return statement_check.request(lib.flow, lib.rid, request_id, model, expected)


def checks(store, rid):
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM statement_checks WHERE research_id = ? ORDER BY revision", (rid,))]


def runs_of(store, rid, kind):
    return [dict(r) for r in store.conn.execute("SELECT * FROM runs WHERE research_id = ? AND kind = ?", (rid, kind))]


def refused(code, call, *args, **kwargs):
    with pytest.raises(statement_check.Refused) as exc:
        call(*args, **kwargs)
    assert exc.value.code == code


def test_a_second_request_while_a_check_is_active_is_refused_and_the_same_id_returns_its_revision(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    first = request(lib)
    refused("run_active", request, lib, "req-2")
    assert request(lib)["id"] == first["id"]  # the same request id while active: its own revision, no refusal
    assert len(checks(lib.store, lib.rid)) == 1


def test_no_model_named_and_none_in_settings_is_refused(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    refused("no_model", request, lib, model=None)
    lib.store.set_setting("literature", LITERATURE)
    check = request(lib, model=None)
    assert json.loads(check["model_json"]) == {"connection": "fake", "model": "fake-model", "reasoning_effort": None}


def test_the_resume_runs_on_the_stored_model_after_settings_change_and_goes_on_from_the_unchecked_work(tmp_path):
    """A request on the literature model in Settings stores it; Settings then names another model. The run paused
    after its first work resumes on the stored model, sends only the second work, and the preview prices the stored
    model too."""
    failing = {"on": True}

    def fail(si):
        if failing["on"] and si["task_type"] == "statement_check" and si["statement_check_target"]["item_id"] == second["id"]:
            return ModelStepResult("failed", error="SYNTHETIC provider error")
        return None
    lib = build(tmp_path, n=2, fail=fail)
    cutoff(lib)
    lib.store.set_setting("literature", LITERATURE)
    check = request(lib, model=None)
    first, second = items(lib, check)
    lib.store.set_setting("literature", {"model_connection": "fake", "model": "fake-other", "reasoning_effort": "high"})
    run = execute(lib, check)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert [r["status"] for r in items(lib, check)] == ["done", "planned"]
    before = len(statement_calls(lib))
    failing["on"] = False
    lib.store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    resent = statement_calls(lib)[before:]
    assert [si["statement_check_target"]["item_id"] for si in resent] == [second["id"]]
    assert {json.loads(r["model_json"])["requested_model"] for r in items(lib, check)} == {"fake-model"}
    # What the adapter was really sent, every attempt: the stored model and effort, never Settings' new ones.
    assert {(model, effort) for task, model, effort in lib.adapter.sent if task == "statement_check"} == {
        ("fake-model", None)}
    assert len(checks(lib.store, lib.rid)) == 1  # resumed, not a new revision
    preview = statement_check.preview(lib.store, check["id"])
    assert preview["model"]["model"] == preview["cost"]["model"] == "fake-model" and preview["cost"]["pairs"] == 2


def test_two_rechecks_in_a_row_keep_the_cutoff_and_take_the_persons_current_choices(tmp_path):
    lib = build(tmp_path, n=3)
    cutoff(lib)
    first = request(lib)
    execute(lib, first)
    user(lib, lib.sources[1], "excluded")
    assert statement_check.view(lib.store, first["id"])["stale_reason"] == "person_choice_changed"
    second = request(lib, "req-2")
    assert by_source(lib, second)[lib.sources[1]]["eligibility"] == "person_excluded"
    execute(lib, second)
    third = request(lib, "req-3")
    execute(lib, third)
    rows = checks(lib.store, lib.rid)
    assert [r["revision"] for r in rows] == [1, 2, 3]
    assert {r["cutoff_step_id"] for r in rows} == {first["cutoff_step_id"]}
    assert len(runs_of(lib.store, lib.rid, "discovery")) == 1  # no new search
    assert [r["currency"] for r in rows] == ["stale", "current", "current"]
    assert [r["status"] for r in items(lib, third)] == ["done", None, "done"]


def test_a_persons_choice_during_the_check_makes_the_revision_stale_and_its_results_are_kept(tmp_path):
    lib = build(tmp_path, n=2)
    cutoff(lib)

    def respond(si):
        if si["task_type"] == "statement_check" and not changed:
            changed.append(True)
            user(lib, lib.sources[1], "excluded")  # the person excludes a work while the first is being checked
        return valid_response(si)
    changed = []
    lib.adapter.responder = respond
    check = request(lib)
    assert execute(lib, check)["status"] == "completed"
    row = statement_check.check_row(lib.store, check["id"])
    assert (row["currency"], row["stale_reason"]) == ("stale", "person_choice_changed")
    assert [r["status"] for r in items(lib, check)] == ["done", "done"]  # stored, never shown as current
    view = statement_check.view(lib.store, check["id"])
    assert view["currency"] == "stale" and view["stale_reason"] == "person_choice_changed"
    exported = statement_check.export(lib.store, check["id"], "csv")
    assert ",stale" in exported and ",current" not in exported


def test_a_crash_after_the_send_and_before_the_write_is_read_back_and_marked_stale(tmp_path):
    """The step answered, the item was not written, and the person excluded a work meanwhile: the restarted run reads
    the stored answer back without a second send, writes it, and the revision is stale, not current."""
    lib = build(tmp_path, n=2)
    cutoff(lib)
    check = request(lib)
    run = execute(lib, check)
    first = items(lib, check)[0]
    store = lib.store
    with store.conn:
        store.conn.execute(
            "UPDATE statement_check_items SET status = 'planned', result = NULL, output_json = NULL, run_id = NULL,"
            " located_anchors_json = NULL, validation_json = NULL, model_json = NULL, checked_at = NULL WHERE id = ?",
            (first["id"],))
        store.conn.execute("UPDATE statement_checks SET status = 'open' WHERE id = ?", (check["id"],))
        store.conn.execute("UPDATE runs SET status = 'paused', pause_reason = 'backend_restarted' WHERE id = ?",
                           (run["id"],))
    user(lib, lib.sources[1], "excluded")
    calls = len(statement_calls(lib))
    store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    assert len(statement_calls(lib)) == calls
    assert items(lib, check)[0]["status"] == "done"
    assert statement_check.check_row(store, check["id"])["currency"] == "stale"


def routed(lib, intent_name="statement"):
    run = copy.deepcopy(lib.store.run(lib.discovery["id"]))
    run["budget"]["fast_path"] = fast_path.with_intent(run["budget"]["fast_path"], intent_name)
    return run


def attached(lib):
    """The research's scope is its attached files: no discovery runs (the one `build` opened is cancelled)."""
    lib.store.conn.execute("UPDATE scope_revisions SET source_scope = 'attached' WHERE research_id = ?", (lib.rid,))
    lib.store.update_run(lib.discovery["id"], status="cancelled")


def wait_run(client, rid, run_id, statuses=("completed", "failed", "paused")):
    deadline = time.time() + 30
    while time.time() < deadline:
        run = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
        if run["status"] in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError("the run did not settle")


def statement_research(client, scope="attached"):
    response = client.post("/api/researches", json={"question": SENTENCE, "model_connection": "fake",
                                                     "requested_model": "fake-model", "effort": "quick",
                                                     "source_scope": scope, "intent": "statement"})
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def test_http_a_statement_discovery_ends_in_its_check_and_not_in_an_answer(tmp_path, monkeypatch):
    from test_abstract_flow import work
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(3)]))
    client = client_of(app)
    try:
        store = app.state.store
        store.set_setting("literature", LITERATURE)
        rid = statement_research(client, scope="academic")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        assert wait_run(client, rid, run_id)["status"] == "completed"
        assert store.run(run_id)["budget"]["fast_path"]["after_discovery"] == "statement_check"
        (check,) = checks(store, rid)
        assert check["discovery_run_id"] == run_id and check["request_id"].startswith(f"statement_check:auto:{rid}:1:")
        wait_run(client, rid, check["run_id"])
        assert runs_of(store, rid, "answer") == []
        steering = [json.loads(r[0])["user_steering"] for r in store.conn.execute(
            "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.run_id = ? AND s.kind = 'model:abstract_screening'", (run_id,))]
        assert steering and all(intent.STATEMENT_NOTE in s for s in steering)
    finally:
        client.__exit__(None, None, None)


LONG = "a" * (statement.MAX_SENTENCE_CHARS + 1)


def test_the_store_and_a_check_request_refuse_a_sentence_over_the_limit(tmp_path):
    lib = build(tmp_path, n=1)
    research = lib.store.research(lib.rid)
    with pytest.raises(statement.StatementTooLong):
        lib.store.revise_scope(lib.rid, research["version"], LONG, None)
    assert lib.store.research(lib.rid)["current_scope_revision"] == research["current_scope_revision"]
    # A sentence stored before the limit held on every path is refused at the check, never sent.
    lib.store.conn.execute("UPDATE scope_revisions SET question = ? WHERE research_id = ?", (LONG, lib.rid))
    attached(lib)
    with pytest.raises(statement_check.Refused) as refused:
        statement_check.request(lib.flow, lib.rid, "req-long", MODEL)
    assert refused.value.code == "sentence_too_long"
    assert lib.store.conn.execute("SELECT COUNT(*) FROM statement_checks").fetchone()[0] == 0


STATED = {"assessment": "stated"}


PARTLY = {"assessment": "partly"}


NOT_STATED = {"assessment": "not_stated"}


def test_a_stated_part_keeps_a_partial_result_support():
    assert statement.support_class("found_partial", [STATED, PARTLY], 2) == "found_partial"
    assert statement.support_class("found_partial", [STATED, NOT_STATED], 2) == "found_partial"


def test_a_partial_result_with_no_stated_part_is_support_not_shown():
    assert statement.support_class("found_partial", [PARTLY], 2) == "support_not_shown"
    assert statement.support_class("found_partial", [PARTLY, NOT_STATED], 2) == "support_not_shown"
    assert statement.support_class("found_partial", [PARTLY, PARTLY], 2) == "support_not_shown"


FIRST, SECOND = "Supervised exercise lowered cancer related fatigue", "after chemotherapy"


def two_partials():
    """A responder: the first work gets a stated part and a partly part (support); every later work a partly part and a
    not-stated part, no stated one (support not shown). Each quote is a span of the work's SYNTHETIC abstract."""
    seen: list[str] = []

    def respond(si, attempt):
        item = si["statement_check_target"]["item_id"]
        if item not in seen:
            seen.append(item)
        passage = si["passages"][0]
        quote = {"passage_id": passage["passage_id"], "quote": "supervised exercise lowered fatigue"}
        other = {"passage_id": passage["passage_id"], "quote": "in one trial"}
        if seen.index(item) == 0:
            return answer(si, [{"text": FIRST, "assessment": "stated", "evidence": [quote]},
                               {"text": SECOND, "assessment": "partly", "evidence": [other]}])
        return answer(si, [{"text": FIRST, "assessment": "partly", "evidence": [quote]},
                           {"text": SECOND, "assessment": "not_stated", "evidence": []}])
    return scripted(respond)


def checked(tmp_path, n=3):
    lib = build(tmp_path, n=n, responder=two_partials())
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    return lib, check


def test_a_revision_stored_before_r4b_reads_with_rule_1_as_before(tmp_path):
    lib, check = checked(tmp_path)
    lib.store.conn.execute("UPDATE statement_checks SET support_rule_version = 1 WHERE id = ?", (check["id"],))
    view = statement_check.view(lib.store, check["id"])
    assert view["support_rule_version"] == 1
    assert [i["support_class"] for i in view["items"]] == ["found_partial"] * 3
    assert view["counters"]["classes"] == {"found_whole": 0, "found_partial": 3, "support_not_shown": 0,
                                           "not_found_in_given": 0}
    rows = list(csv.DictReader(io.StringIO(statement_check.export(lib.store, check["id"], "csv"))))
    assert {r["support_class"] for r in rows} == {"found_partial"}
