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
from deixis.storage.db import new_id, transaction
from deixis.workflow import fast_path, intent, statement_check
from deixis.workflow.decisions import DecisionStore
from fakes import valid_response
from test_abstract_flow import Pool, app_for, client_of
from test_criterion_passage_flow import TOPIC_PAGE, page_source
from test_fast_path_answer import inspected_pdf
from test_statement_check import (ABSTRACT, MODEL, SENTENCE, build, by_source, cutoff, execute, items,
                                  replace_passage, statement_calls, user)

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


# ------------------------------------------------------------------------------------------------ the request

def test_a_wrong_expected_question_revision_is_refused_and_opens_nothing(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    refused("revision_mismatch", request, lib, expected=2)
    assert checks(lib.store, lib.rid) == []
    check = request(lib, expected=1)
    assert (check["revision"], check["scope_revision"]) == (1, 1)


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


# --------------------------------------------------------------------------------------------------- staleness

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


def test_a_pdf_marked_wrong_during_the_check_makes_the_revision_stale(tmp_path):
    lib = build(tmp_path, pdf=True)
    svid, _ = inspected_pdf(lib)
    cutoff(lib)

    def respond(si):
        if si["task_type"] == "statement_check" and not changed:
            changed.append(True)
            DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
        return valid_response(si)
    changed = []
    lib.adapter.responder = respond
    check = request(lib)
    execute(lib, check)
    assert statement_check.check_row(lib.store, check["id"])["stale_reason"] == "person_choice_changed"


def test_a_pdf_page_changed_during_the_check_is_could_not_check_and_the_revision_stale(tmp_path):
    lib = build(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    cutoff(lib)
    check = request(lib)
    pdf_item = by_source(lib, check)[svid]
    page = next(pid for pid in json.loads(pdf_item["plan_json"])["passage_ids"]
                if lib.store.passage(pid)["kind"] == "pdf_page")

    def respond(si):
        if si["task_type"] == "statement_check" and si["statement_check_target"]["item_id"] == pdf_item["id"]:
            replace_passage(lib.store, page, "SYNTHETIC the page as a new extraction reads it.")
        return valid_response(si)
    lib.adapter.responder = respond
    execute(lib, check)
    after = by_source(lib, check)[svid]
    assert after["status"] == "could_not_check" and json.loads(after["error_json"])["code"] == "frozen_input_changed"
    assert statement_check.check_row(lib.store, check["id"])["stale_reason"] == "source_changed"


def test_a_changed_question_makes_the_revision_stale(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    check = request(lib)
    execute(lib, check)
    lib.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
    assert statement_check.view(lib.store, check["id"])["stale_reason"] == "question_changed"


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


# ------------------------------------------------------------------------------------------ the discovery hook

def routed(lib, intent_name="statement"):
    run = copy.deepcopy(lib.store.run(lib.discovery["id"]))
    run["budget"]["fast_path"] = fast_path.with_intent(run["budget"]["fast_path"], intent_name)
    return run


def test_the_discovery_end_hook_fired_twice_opens_one_revision_on_the_settings_model(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    lib.store.set_setting("literature", {"model_connection": "fake", "model": "fake-model", "reasoning_effort": "low"})
    run = routed(lib)
    assert run["budget"]["fast_path"]["auto_answer"] is False
    for _ in range(2):
        with transaction(lib.store.conn):
            statement_check.after_discovery(lib.flow, run)
    (check,) = checks(lib.store, lib.rid)
    cut = lib.store.existing_step(lib.discovery["id"], "fast_path:v1:cutoff")
    assert check["request_id"] == f"statement_check:auto:{lib.rid}:1:{cut['id']}"
    assert json.loads(check["model_json"]) == {"connection": "fake", "model": "fake-model", "reasoning_effort": "low"}
    assert lib.store.run(check["run_id"])["status"] == "queued"
    with transaction(lib.store.conn):
        statement_check.after_discovery(lib.flow, routed(lib, "report"))  # another intent's route: nothing
    assert len(checks(lib.store, lib.rid)) == 1


def test_no_model_in_settings_at_the_auto_start_records_a_refusal_and_starts_nothing(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    with transaction(lib.store.conn):
        statement_check.after_discovery(lib.flow, routed(lib))
    assert checks(lib.store, lib.rid) == [] and runs_of(lib.store, lib.rid, "statement_check") == []
    events = [json.loads(r["payload_json"]) for r in lib.store.conn.execute(
        "SELECT payload_json FROM events WHERE research_id = ? AND type = 'statement_check_skipped'", (lib.rid,))]
    assert events == [{"reason": "no_model"}]


def test_the_claim_note_reaches_the_criterion_search_and_screening_steps_of_a_statement_research(tmp_path):
    lib = build(tmp_path)
    run = routed(lib)
    assert intent.is_statement(lib.store, run)
    assert not intent.is_statement(lib.store, routed(lib, "report"))
    scope = lib.store.scope(lib.rid)
    for task in intent.STATEMENT_NOTE_TASKS:
        assert intent.STATEMENT_NOTE in lib.flow._step_input(run, scope, new_id("stp"), task, [], [], [], [], ("fake", "fake-model", None))[
            "user_steering"], task
    assert intent.STATEMENT_NOTE not in lib.flow._step_input(
        routed(lib, "report"), scope, new_id("stp"), "abstract_screening", [], [], [], [], ("fake", "fake-model", None))["user_steering"]


# ------------------------------------------------------------------------------------------------ attached scope

def attached(lib):
    """The research's scope is its attached files: no discovery runs (the one `build` opened is cancelled)."""
    lib.store.conn.execute("UPDATE scope_revisions SET source_scope = 'attached' WHERE research_id = ?", (lib.rid,))
    lib.store.update_run(lib.discovery["id"], status="cancelled")


def test_an_attached_scope_check_waits_while_a_file_is_extracting_then_freezes_from_the_files(tmp_path):
    lib = build(tmp_path, n=0)
    attached(lib)
    one = page_source(lib.store, lib.rid, "one", [TOPIC_PAGE] * 2, ABSTRACT)
    two = page_source(lib.store, lib.rid, "two", [TOPIC_PAGE], ABSTRACT)
    asset = lib.store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (two,)).fetchone()[0]
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'pending' WHERE id = ?", (asset,))
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    assert (check["discovery_run_id"], json.loads(check["attachment_snapshot_json"])) == (None, {"status": "waiting"})
    run = execute(lib, check)
    assert (run["status"], run["pause_reason"]) == ("paused", "attachments_extracting")
    assert items(lib, check) == [] and statement_calls(lib) == []
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'succeeded' WHERE id = ?", (asset,))
    lib.store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    rows = by_source(lib, check)
    assert set(rows) == {one, two} and {r["status"] for r in rows.values()} == {"done"}
    assert {r["entry"] for r in rows.values()} == {"person_included"}
    snapshot = json.loads(statement_check.check_row(lib.store, check["id"])["attachment_snapshot_json"])
    assert snapshot["status"] == "frozen" and {a["source_version_id"] for a in snapshot["assets"]} == {one, two}
    assert all(a["text_sha256"] and a["extraction_version"] == "test" for a in snapshot["assets"])
    assert lib.store.run(run["id"])["budget"]["max_model_calls"] == 4  # two works, one call and one repair each


def test_an_attached_file_whose_extraction_failed_is_no_text(tmp_path):
    lib = build(tmp_path, n=0)
    attached(lib)
    good = page_source(lib.store, lib.rid, "good", [TOPIC_PAGE], ABSTRACT)
    bad = page_source(lib.store, lib.rid, "bad", [TOPIC_PAGE], None)
    asset = lib.store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (bad,)).fetchone()[0]
    with transaction(lib.store.conn):
        lib.store.conn.execute("DELETE FROM passages WHERE asset_id = ?", (asset,))
        lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'failed' WHERE id = ?", (asset,))
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    execute(lib, check)
    rows = by_source(lib, check)
    assert (rows[bad]["eligibility"], rows[bad]["status"]) == ("listed", "no_text")
    assert rows[good]["status"] == "done"


def test_an_attached_file_replaced_after_the_freeze_makes_the_revision_stale(tmp_path):
    lib = build(tmp_path, n=0)
    attached(lib)
    one = page_source(lib.store, lib.rid, "one", [TOPIC_PAGE], ABSTRACT)
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    execute(lib, check)
    assert statement_check.view(lib.store, check["id"])["currency"] == "current"
    page = next(p["id"] for p in lib.store.passages_for(one) if p["kind"] != "abstract")
    replace_passage(lib.store, page, "SYNTHETIC another reading of the page.")
    assert statement_check.view(lib.store, check["id"])["stale_reason"] == "source_changed"


# ------------------------------------------------------------------------------------------------------ HTTP

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


def test_http_attached_scope_start_repeated_with_the_same_key_opens_one_revision(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([]))
    client = client_of(app)
    try:
        store = app.state.store
        rid = statement_research(client)
        page_source(store, rid, "one", [TOPIC_PAGE], ABSTRACT)
        missing = client.post(f"/api/researches/{rid}/runs", json={"kind": "statement_check"},
                              headers={"Idempotency-Key": "k-0"})
        assert missing.status_code == 422 and checks(store, rid) == []  # the question revision is required
        refused_start = client.post(f"/api/researches/{rid}/runs",
                                    json={"kind": "statement_check", "expected_scope_revision": 1},
                                    headers={"Idempotency-Key": "k-0"})
        assert refused_start.status_code == 409 and refused_start.json()["code"] == "no_model"
        store.set_setting("literature", LITERATURE)
        stale = client.post(f"/api/researches/{rid}/runs", json={"kind": "statement_check", "expected_scope_revision": 2},
                            headers={"Idempotency-Key": "k-1"})
        assert stale.status_code == 409 and stale.json()["code"] == "revision_mismatch"
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "statement_check", "expected_scope_revision": 1},
                            headers={"Idempotency-Key": "k-1"})
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["kind"] == "statement_check" and body["revision"] == 1
        assert wait_run(client, rid, body["id"])["status"] == "completed"
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "statement_check", "expected_scope_revision": 1},
                            headers={"Idempotency-Key": "k-1"}).json()
        assert (again["id"], again["statement_check_id"]) == (body["id"], body["statement_check_id"])
        listed = client.get(f"/api/researches/{rid}/statement-checks").json()
        assert len(listed["checks"]) == 1 and listed["latest_check_id"] == body["statement_check_id"]
        view = client.get(f"/api/statement-checks/{body['statement_check_id']}").json()
        assert view["currency"] == "current" and [i["status"] for i in view["items"]] == ["done"]
        preview = client.get(f"/api/statement-checks/{body['statement_check_id']}/preview").json()
        assert preview["cost"]["model"] == "fake-model" and preview["planned"] == 0
        export = client.get(f"/api/statement-checks/{body['statement_check_id']}/export?format=md")
        assert export.status_code == 200 and "statement-check-" in export.headers["content-disposition"]
        assert client.get("/api/statement-checks/stc_missing").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_http_a_statement_sentence_is_one_sentence_and_a_model_goes_with_its_connection(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([]))
    client = client_of(app)
    try:
        long = client.post("/api/researches", json={"question": "a" * 601, "model_connection": "fake",
                                                     "requested_model": "fake-model", "intent": "statement"})
        assert long.status_code == 422
        rid = statement_research(client)
        no_connection = client.post(f"/api/researches/{rid}/runs", json={"kind": "statement_check", "model": "fake-model"})
        assert no_connection.status_code == 422
        on_discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer", "model": "fake-model",
                                                                        "connection": "fake"})
        assert on_discovery.status_code == 422
    finally:
        client.__exit__(None, None, None)


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


# ------------------------------------------------------------------------------------- Sol's R2 review fixes

def test_a_work_removed_after_an_attached_check_makes_it_stale_in_the_view_and_the_export(tmp_path):
    lib = build(tmp_path, n=0)
    attached(lib)
    one = page_source(lib.store, lib.rid, "one", [TOPIC_PAGE], ABSTRACT)
    page_source(lib.store, lib.rid, "two", [TOPIC_PAGE], ABSTRACT)
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    execute(lib, check)
    assert statement_check.view(lib.store, check["id"])["currency"] == "current"
    lib.store.remove_sources(lib.rid, [one], None)  # the record, its file and passages stay
    view = statement_check.view(lib.store, check["id"])
    assert (view["currency"], view["stale_reason"]) == ("stale", "source_removed")
    assert [i["status"] for i in view["items"]] == ["done", "done"]  # kept, never shown as current
    rows = list(csv.DictReader(io.StringIO(statement_check.export(lib.store, check["id"], "csv"))))
    assert {r["currency"] for r in rows} == {"stale"}


def test_a_work_removed_after_a_discovery_check_makes_it_stale(tmp_path):
    lib = build(tmp_path, n=2)
    cutoff(lib)
    check = request(lib)
    execute(lib, check)
    lib.store.remove_sources(lib.rid, [lib.sources[1]], None)
    assert statement_check.view(lib.store, check["id"])["stale_reason"] == "source_removed"


def test_a_waiting_attached_preview_is_pending_and_then_prices_the_list_the_run_checks(tmp_path):
    lib = build(tmp_path, n=0)
    attached(lib)
    page_source(lib.store, lib.rid, "one", [TOPIC_PAGE], ABSTRACT)
    two = page_source(lib.store, lib.rid, "two", [TOPIC_PAGE], ABSTRACT)
    asset = lib.store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (two,)).fetchone()[0]
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'pending' WHERE id = ?", (asset,))
    check = statement_check.request(lib.flow, lib.rid, "req-1", MODEL)
    pending = statement_check.preview(lib.store, check["id"])
    assert pending["waiting"] is True and pending["planned"] == 0
    assert (pending["cost"]["usd"], pending["cost"]["calls"], pending["cost"]["reason"]) == (
        "unknown", None, "attachments_extracting")
    assert "input_tokens" not in pending["cost"]
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'succeeded' WHERE id = ?", (asset,))
    priced = statement_check.preview(lib.store, check["id"])
    assert priced["waiting"] is False and priced["planned"] == priced["cost"]["pairs"] == 2
    frozen_ids = [i["id"] for i in items(lib, check)]
    assert lib.store.run(check["run_id"])["budget"]["max_model_calls"] == 4
    assert execute(lib, check)["status"] == "completed"
    assert [i["id"] for i in items(lib, check)] == frozen_ids  # the run checked the list the preview priced


def test_the_latest_revision_is_marked_by_number_not_by_currency(tmp_path):
    lib = build(tmp_path, n=2)
    cutoff(lib)
    first = request(lib)
    execute(lib, first)
    second = request(lib, "req-2")
    execute(lib, second)
    listed = statement_check.list_checks(lib.store, lib.rid)
    assert listed["latest_check_id"] == second["id"]
    assert [(c["revision"], c["is_latest"], c["currency"]) for c in listed["checks"]] == [
        (2, True, "current"), (1, False, "current")]
    view = statement_check.view(lib.store, first["id"])
    assert (view["is_latest"], view["latest_check_id"]) == (False, second["id"])
