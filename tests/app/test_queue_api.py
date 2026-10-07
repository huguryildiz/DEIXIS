"""The human queue through the API and inside real `sw` runs (slice 16, D96).

Workflow behavior only. Records are SYNTHETIC and from two fields (greenhouse irrigation, and the pallet loading and
chaining pools the earlier flow tests use), every transport is mocked and the model is scripted. Passing shows that a
person's answer reaches the selection, that the model is not asked about a decided work again — in the abstract read,
the chain read, the fetch plan, the reading plan and a reading run already in flight — and that the endpoints keep to
the `sw` workflow; it says nothing about how a real model or a real person reads a paper.
"""

import asyncio

import pytest

from deixis.models.adapter import ModelStepResult
from deixis.workflow import abstract_stage, adjudication, fulltext
from deixis.workflow import flow as flow_module
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from test_abstract_flow import records_of, responder
from test_adjudication_flow import (absent_response, adj_calls, app_for, client_of, discover, disagree_response,
                                    papers, protocol_paper, step_output, wait, wait_kind, with_a_comparator)
from test_fulltext_flow import Transport


def queue_of(client, rid):
    return client.get(f"/api/researches/{rid}/queue").json()


def answer(client, rid, row, decision, note=None):
    return client.post(f"/api/researches/{rid}/queue/{row['source_version_id']}/decision",
                       json={"decision": decision, "note": note, "row_token": row["row_token"]})


def reading_run(client, rid):
    """Start one more reading run and wait for it."""
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return wait(client, rid, run_id)[1]


def sent_source(store, call):
    """The record a reading call was about. The model is shown a short handle (D12); the stored StepInput keeps the id."""
    return store.step_input_payload(call["step_input_id"])["adjudication_target"]["source_id"]


def sent_records(store, call):
    """The records an abstract batch was sent, read from its stored StepInput."""
    records = {c["candidate_id"]: c["source_version_id"] for c in store.candidates(call["research_id"])}
    return [records[c["candidate_id"]] for c in store.step_input_payload(call["step_input_id"])["candidates"]]


def calls_for(store, adapter, run_id, source):
    return [call for call in adj_calls(adapter, run_id) if sent_source(store, call) == source]


# ---- a person's answer and the selection -------------------------------------------------------------------------

def test_a_human_include_reaches_selections_as_the_users_and_a_later_reading_run_does_not_touch_it(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(disagree_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        row = queue_of(client, rid)["rows"][0]
        decided = answer(client, rid, row, "include", "SYNTHETIC both parts are on page 1.")
        chosen = store.conn.execute("SELECT state, origin FROM selections WHERE research_id = ? AND source_version_id = ?",
                                    (rid, head)).fetchone()
        history = store.conn.execute("SELECT origin, reason FROM selection_history WHERE source_version_id = ?"
                                     " ORDER BY id DESC LIMIT 1", (head,)).fetchone()
        user_chosen = store.answer_order_facts(rid, [head])[head][0]
        later = reading_run(client, rid)
        after = DecisionStore(store).current(rid, row["source_version_id"], "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert row["reason_code"] == "fulltext_runs_disagree" and row["kind"] == "choose_run"
    assert decided.status_code == 200 and decided.json()["row"] is None
    assert decided.json()["selection"]["state"] == "included" and decided.json()["undo_token"]
    assert tuple(chosen) == ("included", "user") and tuple(history) == ("user", "human_include")
    assert user_chosen is True
    assert later["status"] == "completed" and adj_calls(adapter, later["id"]) == []
    assert (after["reason_code"], after["decided_by"], after["note"]) == ("human_include", "human",
                                                                        "SYNTHETIC both parts are on page 1.")


def test_a_protocol_title_row_is_answered_and_undone_through_the_api(tmp_path, monkeypatch):
    """Slice 26: two agreeing runs on a protocol-titled version are a `confirm_results` row with no part asked."""
    works, fetcher = protocol_paper()
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(valid_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        row = queue_of(client, rid)["rows"][0]
        decided = answer(client, rid, row, "include")
        included = DecisionStore(store).current(rid, head, "fulltext")["reason_code"]
        undone = client.post(f"/api/researches/{rid}/queue/{head}/undo", json={"row_token": decided.json()["undo_token"]})
        back = DecisionStore(store).current(rid, head, "fulltext")
        excluded = answer(client, rid, undone.json()["row"], "criterion_not_met")
    finally:
        client.__exit__(None, None, None)
    assert (row["reason_code"], row["kind"], row["question"]) == ("protocol_title", "confirm_results", None)
    assert decided.status_code == 200 and decided.json()["selection"]["state"] == "included"
    assert included == "human_include"
    assert undone.status_code == 200 and undone.json()["row"]["kind"] == "confirm_results"
    # Undo brings the code back as a new row with the restore note, as for every code; the first row keeps its note.
    assert back["reason_code"] == "protocol_title" and back["note"] == "restored after an undone human decision"
    assert excluded.status_code == 200 and excluded.json()["selection"]["state"] == "excluded"


def test_a_withheld_comparator_exclusion_is_answered_and_undone_through_the_api(tmp_path, monkeypatch):
    """Slice 28: two all-negative runs on a comparator criterion are a `confirm_absent` row naming the comparator."""
    with_a_comparator(monkeypatch)
    works, fetcher = protocol_paper(title="SYNTHETIC irrigation scheduling of an open field crop")
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        row = queue_of(client, rid)["rows"][0]
        decided = answer(client, rid, row, "criterion_not_met")
        excluded = DecisionStore(store).current(rid, head, "fulltext")["reason_code"]
        undone = client.post(f"/api/researches/{rid}/queue/{head}/undo", json={"row_token": decided.json()["undo_token"]})
        back = DecisionStore(store).current(rid, head, "fulltext")
        included = answer(client, rid, undone.json()["row"], "include")
    finally:
        client.__exit__(None, None, None)
    assert (row["reason_code"], row["kind"], row["question"]["part"]) == (
        "comparator_exclusion_withheld", "confirm_absent", "measured outcome")
    assert decided.status_code == 200 and decided.json()["selection"]["state"] == "excluded"
    assert excluded == "human_criterion_not_met"
    assert undone.status_code == 200 and undone.json()["row"]["question"]["part"] == "measured outcome"
    assert back["reason_code"] == "comparator_exclusion_withheld"
    assert included.status_code == 200 and included.json()["selection"]["state"] == "included"


def test_research_view_counts_the_queue(tmp_path, monkeypatch):
    works, fetcher = papers(2)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(disagree_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        before = client.get(f"/api/researches/{rid}").json()["counts"]
        answer(client, rid, queue_of(client, rid)["rows"][0], "criterion_not_met")
        after = client.get(f"/api/researches/{rid}").json()["counts"]
    finally:
        client.__exit__(None, None, None)
    assert (before["queue"], before["look_again"]) == (2, 0)
    assert (after["queue"], after["look_again"]) == (1, 0)


def test_queue_endpoints_refuse_legacy_and_mutations_need_the_csrf_header(tmp_path, monkeypatch):
    legacy = app_for(tmp_path / "legacy", monkeypatch, Transport(papers(1)[0]), papers(1)[1], workflow="legacy")
    client = client_of(legacy)
    try:
        rid, _, view, _ = discover(client)
        legacy.state.store.conn.execute("UPDATE scope_revisions SET search_workflow = 'legacy' WHERE research_id = ?", (rid,))
        svid = view["sources"][0]["source_version_id"]
        listed = client.get(f"/api/researches/{rid}/queue")
        row = client.get(f"/api/researches/{rid}/queue/{svid}")
        posted = client.post(f"/api/researches/{rid}/queue/{svid}/decision",
                             json={"decision": "include", "note": None, "row_token": "x"})
        undone = client.post(f"/api/researches/{rid}/queue/{svid}/undo", json={"row_token": "x"})
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
    finally:
        client.__exit__(None, None, None)
    assert [r.status_code for r in (listed, row, posted, undone)] == [422, 422, 422, 422]
    assert "queue" not in counts and "look_again" not in counts  # a legacy view is what it was

    works, fetcher = papers(1)
    app = app_for(tmp_path / "sw", monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(disagree_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        row = queue_of(client, rid)["rows"][0]
        path = f"/api/researches/{rid}/queue/{row['source_version_id']}"
        headers = {"x-deixis-csrf": ""}
        no_csrf = client.post(f"{path}/decision", headers=headers,
                              json={"decision": "include", "note": None, "row_token": row["row_token"]})
        no_csrf_undo = client.post(f"{path}/undo", headers=headers, json={"row_token": row["row_token"]})
        long_note = client.post(f"{path}/decision",
                                json={"decision": "include", "note": "x" * 1001, "row_token": row["row_token"]})
        stale = client.post(f"{path}/decision", json={"decision": "include", "note": None, "row_token": "stale"})
        stranger = client.get(f"/api/researches/{rid}/queue/srv_notasource0000000000")
        still = queue_of(client, rid)["counts"]["open"]
        client.request("DELETE", f"/api/researches/{rid}/sources",
                       json={"source_version_ids": [row["head"]], "note": "SYNTHETIC removed"})
        removed = client.post(f"{path}/decision",
                              json={"decision": "include", "note": None, "row_token": row["row_token"]})
    finally:
        client.__exit__(None, None, None)
    assert no_csrf.status_code == 403 and no_csrf_undo.status_code == 403
    assert long_note.status_code == 422 and stale.status_code == 409 and stranger.status_code == 422
    assert still == 1 and removed.status_code == 409  # once a source, a removed record is a stale row, not unknown


# ---- the model is not asked again --------------------------------------------------------------------------------



















# ---- every send after a decision: resends, a real limiter wait, a pause, an undo before the close ------------------













# ---- the fifth answer --------------------------------------------------------------------------------------------

def test_pdf_confirmed_lets_the_next_reading_run_read_the_work_and_can_be_undone_before_it_does(tmp_path, monkeypatch):
    works, fetcher = papers(1, named=False)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        row = queue_of(client, rid)["rows"][0]
        svid = row["source_version_id"]
        confirmed = answer(client, rid, row, "pdf_confirmed").json()
        events = [e["type"] for e in store.events_after(rid, 0, 10_000)]
        undone = client.post(f"/api/researches/{rid}/queue/{svid}/undo", json={"row_token": confirmed["undo_token"]})
        back = queue_of(client, rid)["rows"]
        again = answer(client, rid, back[0], "pdf_confirmed").json()
        later = reading_run(client, rid)
        code = DecisionStore(store).current(rid, svid, "fulltext")["reason_code"]
        later_calls = calls_for(store, adapter, later["id"], svid)
        refused = client.post(f"/api/researches/{rid}/queue/{svid}/undo",
                              json={"row_token": client.get(f"/api/researches/{rid}/queue/{svid}").json()["undo_token"]})
    finally:
        client.__exit__(None, None, None)
    assert row["kind"] == "confirm_pdf" and adj_calls(adapter, first["id"]) == []
    assert confirmed["row"] is None and confirmed["decision"]["reason_code"] == "not_read_yet"
    assert "pdf_identity_confirmed" in events
    assert undone.status_code == 200 and undone.json()["row"]["kind"] == "confirm_pdf"
    assert [r["source_version_id"] for r in back] == [svid]
    assert again["decision"]["undoable"] is True
    assert len(later_calls) == 2 and code == "all_parts_verified"
    assert refused.status_code == 409  # the confirmed work was read; nothing of the confirmation is left to undo


# ---- what the screen reads (slice 17, D97) ------------------------------------------------------------------------

def quiet_app(tmp_path, monkeypatch):
    """The API over a library the test writes itself, with no worker: rows come from `test_queue.Lib`, not a run."""
    import httpx
    from deixis.api.app import create_app
    from deixis.config import Settings
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765),
                     adapters={"fake": FakeAdapter(valid_response)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    return app, client_of(app)


def test_a_409_names_whether_the_row_changed_or_reading_started(tmp_path, monkeypatch):
    from test_queue import Lib, queued
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Lib(store)
        svid = queued(lib)
        stale = client.post(f"/api/researches/{lib.rid}/queue/{svid}/decision",
                            json={"decision": "include", "note": None, "row_token": "stale"})
        identity = lib.work()
        lib.text(identity, [lib.field["page"]])
        lib.unconfirmed(identity)
        row = next(r for r in queue_of(client, lib.rid)["rows"] if r["source_version_id"] == identity)
        confirmed = answer(client, lib.rid, row, "pdf_confirmed").json()
        # A later reading run froze its plan after the confirmation and opened this work's step.
        run = lib.new_run("fulltext_adjudication")
        plan = store.step(run, "adjudication_plan", "code:adjudication_plan")
        store.finish_step(plan["id"], "succeeded", output={})
        store.step(run, f"fulltext_adjudication:{identity}:1", "model:fulltext_adjudication")
        started = client.post(f"/api/researches/{lib.rid}/queue/{identity}/undo",
                              json={"row_token": confirmed["undo_token"]})
        other = client.post(f"/api/runs/{run}/resume")
    finally:
        client.__exit__(None, None, None)
    assert stale.status_code == 409 and stale.json()["detail"] == {
        "reason": "row_changed", "message": "This row changed since it was shown; read it again"}
    assert started.status_code == 409 and started.json()["detail"]["reason"] == "reading_started"
    assert started.json()["detail"]["message"].startswith("The reading of this PDF has begun")
    assert other.status_code == 409 and isinstance(other.json()["detail"], str)  # other 409s keep one sentence


def test_decided_rows_carry_a_typed_answer_and_no_internal_note(tmp_path, monkeypatch):
    from test_queue import Lib, queued
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        lib = Lib(app.state.store, "irrigation")
        by_answer = {}
        for choice in ("include", "criterion_not_met", "not_sure", "pdf_wrong"):
            svid = queued(lib)
            row = next(r for r in queue_of(client, lib.rid)["rows"] if r["source_version_id"] == svid)
            assert answer(client, lib.rid, row, choice, f"SYNTHETIC note on {choice}").status_code == 200
            by_answer[choice] = svid
        identity = lib.work()
        lib.text(identity, [lib.field["page"]])
        lib.unconfirmed(identity)
        row = next(r for r in queue_of(client, lib.rid)["rows"] if r["source_version_id"] == identity)
        answer(client, lib.rid, row, "pdf_confirmed")
        by_answer["pdf_confirmed"] = identity
        listed = client.get(f"/api/researches/{lib.rid}/queue")
    finally:
        client.__exit__(None, None, None)
    decided = {entry["source_version_id"]: entry for entry in listed.json()["decided"]}
    assert {entry["answer"] for entry in decided.values()} == set(by_answer)
    assert all(decided[svid]["answer"] == choice for choice, svid in by_answer.items())
    assert decided[identity]["reason_code"] == "not_read_yet" and decided[identity]["note"] is None
    assert decided[by_answer["not_sure"]]["note"] == "SYNTHETIC note on not_sure"
    assert "pdf_confirmed:" not in listed.text  # the file the confirmation names is internal


def test_a_source_row_names_a_queue_answer_from_its_stored_link_and_not_from_a_typed_reason(tmp_path, monkeypatch):
    from test_queue import Lib, queued
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Lib(store)
        answered, typed, edited = queued(lib), queued(lib), queued(lib)
        for svid in (answered, edited):
            row = next(r for r in queue_of(client, lib.rid)["rows"] if r["source_version_id"] == svid)
            assert answer(client, lib.rid, row, "include").status_code == 200
        # The same words typed as a reason from the source list are the person's reason, not a queue answer.
        store.set_user_selection(lib.rid, typed, "included", lib.selection_version(typed), "human_include")
        # A list edit after the queue answer makes the selection the person's own again.
        lib.list_edit(edited, "excluded")
        view = client.get(f"/api/researches/{lib.rid}").json()
    finally:
        client.__exit__(None, None, None)
    selections = {source["source_version_id"]: source["selection"] for source in view["sources"]}
    assert selections[answered]["queue_answer"] == "include"
    assert selections[typed]["queue_answer"] is None and selections[typed]["user_reason"] == "human_include"
    assert selections[edited]["queue_answer"] is None


@pytest.mark.parametrize("phase", ["abstract_screening", "fulltext_adjudication"])
@pytest.mark.parametrize("human_code", ["human_include", "human_criterion_not_met", "human_not_sure"])
def test_user_edit_during_small_batch_stops_further_model_reads_and_publication(tmp_path, monkeypatch, human_code, phase):
    holder = {}

    def before(si):
        if si["task_type"] != phase or holder.get("decided"):
            return
        store = holder["app"].state.store
        source = sent_records(store, si)[0] if phase == "abstract_screening" else sent_source(store, si)
        DecisionStore(store).record(si["research_id"], source, human_code)
        holder["decided"] = source

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    if phase == "abstract_screening":
        app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                      adapter=adapter, fetch="off", reading="off", concurrency=1)
    else:
        works, fetcher = papers(1)
        app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        assert (run["status"], run["pause_reason"]) == ("paused", "selection_changed")
        store = app.state.store
        human = DecisionStore(store).current(rid, holder["decided"], "fulltext")
        assert human["reason_code"] == human_code
        assert human["decided_by"] == "human"
        assert len([c for c in adapter.calls if c["task_type"] == phase]) == 1
        assert not store.conn.execute("SELECT 1 FROM model_proposals WHERE research_id = ? AND stage = ?",
                                      (rid, "abstract" if phase == "abstract_screening" else "fulltext")).fetchone()
    finally:
        client.__exit__(None, None, None)
