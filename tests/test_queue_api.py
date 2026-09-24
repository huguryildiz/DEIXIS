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
from test_adjudication_flow import (adj_calls, app_for, client_of, discover, disagree_response, papers,
                                    step_output, wait, wait_kind)
from test_fulltext_flow import Transport


def queue_of(client, rid):
    return client.get(f"/api/researches/{rid}/queue").json()


def answer(client, rid, row, decision, note=None):
    return client.post(f"/api/researches/{rid}/queue/{row['source_version_id']}/decision",
                       json={"decision": decision, "note": note, "row_token": row["row_token"]})


def reading_run(client, rid):
    """Start one more reading run and wait for it."""
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
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

def test_a_human_decision_keeps_the_work_out_of_the_abstract_read_the_chain_read_the_fetch_plan_and_the_reading_plan(
        tmp_path, monkeypatch):
    # The plans, as pure functions: the same work with and without a person's full-text decision.
    unread = {"id": "srv_a", "has_abstract": True, "code": None, "decision": "abstract_not_read", "decided_by": "code",
              "stale": False}
    for chained in (False, True):  # the keyword read and the chain read plan with the same function
        open_work = {"work_id": "wrk_a", "head": "srv_a", "versions": [dict(unread)], "chained": chained}
        decided = dict(open_work, fulltext_human=True)
        assert abstract_stage.read_plan(["srv_a"], [open_work], 40, 20)["batches"] == [["srv_a"]]
        assert abstract_stage.read_plan(["srv_a"], [decided], 40, 20) == {"batches": [], "not_read": []}
    candidate = {"reason_code": "runs_agree_candidate", "decided_by": "model_agreement", "stale": False}
    human = {"reason_code": "human_not_sure", "decided_by": "human", "stale": False}
    for text in (False, True):
        work = {"work_id": "wrk_b", "head": "srv_b", "selection": {"state": "pending", "origin": "code_rule"},
                "versions": [{"id": "srv_b", "has_text": text, "abstract": candidate, "fulltext": None}]}
        decided = dict(work, versions=[dict(work["versions"][0], fulltext=human)])
        assert fulltext.fetch_plan([work], ["srv_b"], 40)["works" if not text else "already_text"] == ["srv_b"]
        assert fulltext.fetch_plan([decided], ["srv_b"], 40) == {"works": [], "not_reached": [], "already_text": []}
        assert adjudication.read_plan([decided], ["srv_b"], 40) == {"works": [], "not_reached": []}

    # And inside a second discovery run: a keyword record and a chained record the first run left unproposed.
    from test_chaining_flow import OpenAlex, app_for as chain_app, keyword_pool, work as chain_work
    transport = OpenAlex(keyword_pool(), citing={"W1": [chain_work(700), chain_work(701)]})
    adapter = FakeAdapter(responder())
    app = chain_app(tmp_path / "chain", monkeypatch, transport, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        store = app.state.store
        decisions = DecisionStore(store)
        records = records_of(store, rid)
        for key in ("W2", "W3", "W700", "W701"):
            decisions.record(rid, records[key], "abstract_not_proposed")
        for key in ("W2", "W700"):
            decisions.record(rid, records[key], "human_criterion_not_met")
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, second)
        keyword = {svid for batch in step_output(store, second, "abstract_stage")["batches"] for svid in batch}
        chain = {svid for batch in step_output(store, second, "chain_abstract_stage")["batches"] for svid in batch}
        shown = {svid for call in adapter.calls if call.get("run_id") == second
                 and call["task_type"] == "abstract_screening" for svid in sent_records(store, call)}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert records["W3"] in keyword and records["W2"] not in keyword
    assert records["W701"] in chain and records["W700"] not in chain
    assert not {records["W2"], records["W700"]} & shown


def test_a_record_decided_while_a_discovery_run_is_in_flight_is_left_out_of_the_next_abstract_batch(tmp_path, monkeypatch):
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening" or holder.get("done"):
            return
        store = holder["app"].state.store
        run = store.run(si["run_id"])
        later = step_output(store, si["run_id"], "abstract_stage")["batches"][1][0]
        DecisionStore(store).record(run["research_id"], later, "human_include")
        holder.update(done=True, decided=later)

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(25)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        plan = step_output(store, run_id, "abstract_stage")
        sent = [sent_records(store, call) for call in adapter.calls if call["task_type"] == "abstract_screening"]
        decided = holder["decided"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert decided in plan["batches"][1]  # the plan step keeps its list
    assert len(sent) == 4 and all(decided not in batch for batch in sent)
    assert sent[2] == [svid for svid in plan["batches"][1] if svid != decided]
    assert abstract is None  # no decision of that batch was written for the record that left it


def test_a_record_decided_between_the_two_runs_of_a_batch_is_not_sent_again_and_gets_no_abstract_decision(
        tmp_path, monkeypatch):
    """The check once the limiter lets a call through: the second run of the same batch was already generated with
    the record in it, and is sent without it (Sol's review of slice 16)."""
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening" or holder.get("done"):
            return
        store = holder["app"].state.store
        sent = sent_records(store, si)
        DecisionStore(store).record(store.run(si["run_id"])["research_id"], sent[0], "human_include")
        holder.update(done=True, decided=sent[0], first=sent)

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        sent = [sent_records(store, call) for call in adapter.calls if call["task_type"] == "abstract_screening"]
        decided = holder["decided"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        others = {svid: DecisionStore(store).current(rid, svid, "abstract")["reason_code"]
                  for svid in holder["first"] if svid != decided}
        pending = [s["operation_key"] for s in store.run_steps(run_id) if s["status"] == "pending"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert len(sent) == 2 and decided in sent[0] and decided not in sent[1]
    assert sent[1] == [svid for svid in sent[0] if svid != decided]
    assert abstract is None and set(others.values()) == {"runs_agree_candidate"} and pending == []


def test_a_record_left_out_of_one_run_gets_nothing_from_the_batch_even_if_the_decision_is_undone_by_the_close(
        tmp_path, monkeypatch):
    """Decided before the second run, which is sent without it; the decision is undone before the batch closes. Only
    what both runs saw is closed, so the record gets no proposal and no decision. (Removing the record instead cannot
    happen here: sources do not change while a run is active, `RevisionConflict`.)"""
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening":
            return
        store = holder["app"].state.store
        rid = store.run(si["run_id"])["research_id"]
        if not holder.get("decided"):
            sent = sent_records(store, si)
            DecisionStore(store).record(rid, sent[0], "human_include")
            holder.update(decided=sent[0], first=sent)
        else:
            DecisionStore(store).undo_human(rid, holder["decided"], "fulltext")
            holder["undone"] = DecisionStore(store).current(rid, holder["decided"], "fulltext") is None

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        decided = holder["decided"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        proposals = DecisionStore(store).proposals(rid, decided, "abstract")
        others = {DecisionStore(store).current(rid, svid, "abstract")["reason_code"]
                  for svid in holder["first"] if svid != decided}
        pending = [s["operation_key"] for s in store.run_steps(run_id) if s["status"] in ("pending", "running")]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert holder["undone"] and abstract is None and proposals == [] and pending == []
    assert others == {"runs_agree_candidate"}


@pytest.mark.parametrize("then", ["keep", "undo"])
def test_a_batch_emptied_before_its_second_run_makes_one_call_opens_no_step_and_writes_nothing(
        tmp_path, monkeypatch, then):
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening" or holder.get("decided"):
            return
        store = holder["app"].state.store
        rid = store.run(si["run_id"])["research_id"]
        holder["decided"] = sent_records(store, si)[0]
        DecisionStore(store).record(rid, holder["decided"], "human_include")

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(0)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        decided = holder["decided"]
        if then == "undo":
            DecisionStore(store).undo_human(rid, decided, "fulltext")
            assert DecisionStore(store).current(rid, decided, "fulltext") is None
        screening = [s for s in store.run_steps(run_id) if s["kind"] == "model:abstract_screening"]
        calls = [c for c in adapter.calls if c["run_id"] == run_id]
        usage = store.run(run_id)["usage"].get("model_calls", 0)
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        proposals = DecisionStore(store).proposals(rid, decided, "abstract")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert [s["status"] for s in screening] == ["succeeded"]
    assert len([c for c in calls if c["task_type"] == "abstract_screening"]) == 1 and usage == len(calls)
    assert abstract is None and proposals == []


def test_a_decision_taken_while_the_connection_is_checked_stops_the_call_before_its_step_input(tmp_path, monkeypatch):
    """The last check sits after `health()`: a record decided there is not sent, the call is not made or charged,
    and its step is closed as `human_decided` rather than left pending."""
    holder = {}

    def before(si):
        if si["task_type"] == "abstract_screening" and "armed" not in holder:
            store = holder["app"].state.store
            holder.update(armed=sent_records(store, si)[0], rid=store.run(si["run_id"])["research_id"])

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    health = adapter.health

    async def slow_health(refresh=False):
        if holder.get("armed") and not holder.get("decided"):
            DecisionStore(holder["app"].state.store).record(holder["rid"], holder["armed"], "human_include")
            holder["decided"] = holder["armed"]
        return await health(refresh)

    adapter.health = slow_health
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(0)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        decided = holder["decided"]
        screening = {s["operation_key"]: s for s in store.run_steps(run_id) if s["kind"] == "model:abstract_screening"}
        unsent = [store.last_step_input(s["id"]) for s in screening.values() if s["error_code"] == "human_decided"]
        calls = [c for c in adapter.calls if c["run_id"] == run_id]
        usage = store.run(run_id)["usage"].get("model_calls", 0)
        abstract = DecisionStore(store).current(rid, decided, "abstract")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    statuses = sorted((s["status"], s["error_code"]) for s in screening.values())
    # Skipped, not failed: the step is not trouble for the run's view, and a resumed run may open it again.
    assert statuses == [("cancelled", "human_decided"), ("succeeded", None)] and unsent == [None]
    assert len([c for c in calls if c["task_type"] == "abstract_screening"]) == 1 and usage == len(calls)
    assert abstract is None


def test_a_work_decided_while_the_connection_is_checked_for_its_second_reading_call_gets_nothing(
        tmp_path, monkeypatch):
    holder = {}

    def before(si):
        if si["task_type"] == "fulltext_adjudication" and "armed" not in holder:
            holder["armed"] = sent_source(holder["app"].state.store, si)
            holder["rid"] = holder["app"].state.store.run(si["run_id"])["research_id"]

    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, before=before)
    health = adapter.health

    async def slow_health(refresh=False):
        if holder.get("armed") and not holder.get("decided"):
            DecisionStore(holder["app"].state.store).record(holder["rid"], holder["armed"], "human_criterion_not_met")
            holder["decided"] = holder["armed"]
        return await health(refresh)

    adapter.health = slow_health
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        decided = holder["decided"]
        steps = [s for s in store.run_steps(reading["id"]) if s["kind"] == "model:fulltext_adjudication"]
        unsent = [store.last_step_input(s["id"]) for s in steps if s["error_code"] == "human_decided"]
        usage = store.run(reading["id"])["usage"].get("model_calls", 0)
        current = DecisionStore(store).current(rid, decided, "fulltext")
        proposals = DecisionStore(store).proposals(rid, decided, "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed"
    assert sorted((s["status"], s["error_code"]) for s in steps) == [("cancelled", "human_decided"), ("succeeded", None)]
    assert unsent == [None]
    assert usage == 1 and len(adj_calls(adapter, reading["id"])) == 1
    assert current["reason_code"] == "human_criterion_not_met" and proposals == []


def test_a_work_decided_while_a_reading_run_is_in_flight_gets_no_model_call(tmp_path, monkeypatch):
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication" or holder.get("other"):
            return
        store = holder["app"].state.store
        run = store.run(si["run_id"])
        plan = step_output(store, si["run_id"], "adjudication_plan")
        other = next(item["read_version"] for item in plan["works"] if item["read_version"] != sent_source(store, si))
        DecisionStore(store).record(run["research_id"], other, "human_criterion_not_met")
        holder["other"] = other

    works, fetcher = papers(2)
    adapter = FakeAdapter(valid_response, before=before)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        other = holder["other"]
        summary = step_output(store, reading["id"], "adjudication_summary")
        steps = [s["operation_key"] for s in store.run_steps(reading["id"]) if s["kind"] == "model:fulltext_adjudication"]
        usage = store.run(reading["id"])["usage"].get("model_calls", 0)
        current = DecisionStore(store).current(rid, other, "fulltext")
        other_calls = calls_for(store, adapter, reading["id"], other)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed"
    assert other_calls == [] and len(adj_calls(adapter, reading["id"])) == 2
    assert not [key for key in steps if other in key] and usage == 2
    assert summary["human_decided"] == 1 and summary["not_reached"] == 0 and summary["include"] == 1
    assert current["reason_code"] == "human_criterion_not_met"


def test_a_response_that_arrives_after_the_person_decided_writes_no_proposal_and_no_decision(tmp_path, monkeypatch):
    holder = {}

    def before(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] == 2:
            store = holder["app"].state.store
            source = sent_source(store, si)
            DecisionStore(store).record(store.run(si["run_id"])["research_id"], source, "human_include")
            holder["source"] = source

    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, before=before)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        source = holder["source"]
        proposals = store.conn.execute("SELECT COUNT(*) FROM model_proposals WHERE source_version_id = ?"
                                       " AND stage = 'fulltext'", (source,)).fetchone()[0]
        history = [d["reason_code"] for d in DecisionStore(store).history(rid, source) if d["stage"] == "fulltext"]
        steps = [s["status"] for s in store.run_steps(reading["id"]) if s["kind"] == "model:fulltext_adjudication"]
        summary = step_output(store, reading["id"], "adjudication_summary")
    finally:
        client.__exit__(None, None, None)
    assert len(adj_calls(adapter, reading["id"])) == 2 and steps == ["succeeded", "succeeded"]  # the steps stay stored
    assert proposals == 0 and history == ["not_read_yet", "human_include"]
    assert summary["human_decided"] == 1 and summary["not_settled"] == 0 and summary["include"] == 0


# ---- every send after a decision: resends, a real limiter wait, a pause, an undo before the close ------------------

def test_a_record_decided_while_its_abstract_call_waits_in_the_limiter_is_not_sent(tmp_path, monkeypatch):
    """Two calls allowed, one slot held elsewhere: the batch's second run really waits in the limiter while the first
    is out, and a person decides a record in that wait. The second run goes without it and the record gets nothing."""
    holder = {}

    def before(si):
        store = holder["app"].state.store
        limiter = holder["app"].state.worker.flow.deps.limiter
        if si["task_type"] != "abstract_screening":
            if "hold" not in holder:  # an earlier step of the run takes one of the two slots until it is released
                holder["release"] = asyncio.Event()
                holder["hold"] = asyncio.ensure_future(limiter.run("synthetic-hold", holder["release"].wait))
            return
        if "decided" in holder:
            return
        sent = sent_records(store, si)
        # Both slots are taken (the hold and this call) and the batch's other run is already in the limiter.
        holder["waiting"] = (limiter._in_flight == limiter.limit == 2
                             and sum(key.startswith("abstract_screening:") for key in limiter._by_key) == 2)
        DecisionStore(store).record(store.run(si["run_id"])["research_id"], sent[0], "human_include")
        holder.update(decided=sent[0], first=sent)
        holder["release"].set()

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off", concurrency=2)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        sent = [sent_records(store, call) for call in adapter.calls if call["task_type"] == "abstract_screening"]
        decided = holder["decided"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        proposals = DecisionStore(store).proposals(rid, decided, "abstract")
        usage = store.run(run_id)["usage"].get("model_calls", 0)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert holder["waiting"]
    assert len(sent) == 2 and decided in sent[0] and sent[1] == [svid for svid in sent[0] if svid != decided]
    assert abstract is None and proposals == [] and usage == len([c for c in adapter.calls if c["run_id"] == run_id])


def test_a_rate_limited_abstract_call_is_resent_without_a_record_decided_while_it_was_out(tmp_path, monkeypatch):
    """A resend is a new call: it stores its own StepInput without the record a person decided while the first try was
    out, and the record gets nothing from the batch."""
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening" or "decided" in holder:
            return
        store = holder["app"].state.store
        sent = sent_records(store, si)
        DecisionStore(store).record(store.run(si["run_id"])["research_id"], sent[0], "human_include")
        holder.update(decided=sent[0], first=sent)

    def fail(si):
        if si["task_type"] == "abstract_screening" and not holder.get("limited"):
            holder["limited"] = True
            return ModelStepResult("failed", error="429 Too Many Requests")
        return None

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        sent = [sent_records(store, call) for call in adapter.calls if call["task_type"] == "abstract_screening"]
        decided = holder["decided"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        proposals = DecisionStore(store).proposals(rid, decided, "abstract")
        others = {DecisionStore(store).current(rid, svid, "abstract")["reason_code"]
                  for svid in holder["first"] if svid != decided}
        usage = store.run(run_id)["usage"].get("model_calls", 0)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert len(sent) == 3 and decided in sent[0]
    assert sent[1] == sent[2] == [svid for svid in sent[0] if svid != decided]
    assert abstract is None and proposals == [] and others == {"runs_agree_candidate"}
    assert usage == len([c for c in adapter.calls if c["run_id"] == run_id])


@pytest.mark.parametrize("resend", ["rate_limit", "turn_timeout", "schema_repair"])
def test_a_reading_call_is_not_sent_again_for_a_work_decided_while_it_was_out(tmp_path, monkeypatch, resend):
    """The three ways a step sends a second time: after a rate limit, after a turn timeout, and for a schema repair.
    None of them is sent for a work a person decided meanwhile; the step closes unsent and nothing is written."""
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication" or "decided" in holder:
            return
        store = holder["app"].state.store
        holder["decided"] = sent_source(store, si)
        DecisionStore(store).record(store.run(si["run_id"])["research_id"], holder["decided"], "human_criterion_not_met")

    def fail(si):
        if si["task_type"] != "fulltext_adjudication" or holder.get("failed"):
            return None
        holder["failed"] = True
        if resend == "rate_limit":
            return ModelStepResult("failed", error="429 Too Many Requests")
        if resend == "turn_timeout":
            return ModelStepResult("failed", error="client_timeout", delivery_class="after_send_unknown")
        return ModelStepResult("completed", raw_text="{", resolved_model="fake-model")

    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, before=before, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        decided = holder["decided"]
        steps = [(s["status"], s["error_code"]) for s in store.run_steps(reading["id"])
                 if s["kind"] == "model:fulltext_adjudication"]
        usage = store.run(reading["id"])["usage"].get("model_calls", 0)
        current = DecisionStore(store).current(rid, decided, "fulltext")
        proposals = DecisionStore(store).proposals(rid, decided, "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed", reading
    assert len(adj_calls(adapter, reading["id"])) == 1 and usage == 1
    assert steps == [("cancelled", "human_decided")]
    assert current["reason_code"] == "human_criterion_not_met" and proposals == []


def test_a_record_one_run_was_not_sent_gets_nothing_after_a_pause_an_undo_and_a_resume(tmp_path, monkeypatch):
    """The run pauses after both runs of the batch came back and before it closed; the decision is undone while it is
    paused. The resumed run reads both answers back and closes only what both stored StepInputs hold, so the record the
    second run was not sent gets no proposal and no decision (Sol's final check of slice 16, finding 3)."""
    holder = {}

    def before(si):
        if si["task_type"] != "abstract_screening":
            return
        store = holder["app"].state.store
        if "decided" not in holder:
            sent = sent_records(store, si)
            DecisionStore(store).record(store.run(si["run_id"])["research_id"], sent[0], "human_include")
            holder.update(decided=sent[0], first=sent)
        elif "paused" not in holder:
            holder["paused"] = True
            store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                             pause_reason="user_requested")

    from test_abstract_flow import work as abstract_work
    adapter = FakeAdapter(responder(), before=before)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off")
    holder["app"] = app
    client = client_of(app)
    try:
        rid, run_id, _, paused = discover(client)
        store = app.state.store
        decided = holder["decided"]
        closed_before = DecisionStore(store).proposals(rid, holder["first"][1], "abstract")
        DecisionStore(store).undo_human(rid, decided, "fulltext")
        client.post(f"/api/runs/{run_id}/resume")
        _, run = wait(client, rid, run_id)
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        abstract = DecisionStore(store).current(rid, decided, "abstract")
        proposals = DecisionStore(store).proposals(rid, decided, "abstract")
        others = {DecisionStore(store).current(rid, svid, "abstract")["reason_code"]
                  for svid in holder["first"] if svid != decided}
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and closed_before == []  # paused before the batch closed
    assert run["status"] == "completed", run
    assert len(calls) == 2  # the resumed run reads both answers back and sends nothing again
    assert abstract is None and proposals == [] and others == {"runs_agree_candidate"}


def test_a_reading_decision_undone_before_the_close_leaves_the_work_undecided_by_the_run(tmp_path, monkeypatch):
    """Two calls in flight: the work's second call is closed unsent because a person decided it during the connection
    check, and the decision is undone before the first call returns. Nothing is closed from one run: no proposal, no
    decision, and the next reading run reads the work with two calls."""
    holder = {}

    def before(si):
        if si["task_type"] == "fulltext_adjudication" and "armed" not in holder:
            store = holder["app"].state.store
            holder.update(armed=sent_source(store, si), rid=store.run(si["run_id"])["research_id"])

    def respond(si):
        if si["task_type"] == "fulltext_adjudication" and holder.get("decided") and not holder.get("undone"):
            DecisionStore(holder["app"].state.store).undo_human(holder["rid"], holder["decided"], "fulltext")
            holder["undone"] = True
        return valid_response(si)

    works, fetcher = papers(1)
    adapter = FakeAdapter(respond, before=before, delay=0.05)
    health = adapter.health

    async def slow_health(refresh=False):
        if holder.get("armed") and not holder.get("decided"):
            DecisionStore(holder["app"].state.store).record(holder["rid"], holder["armed"], "human_criterion_not_met")
            holder["decided"] = holder["armed"]
        return await health(refresh)

    adapter.health = slow_health
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=2)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        decided = holder["decided"]
        steps = sorted((s["status"], s["error_code"]) for s in store.run_steps(reading["id"])
                       if s["kind"] == "model:fulltext_adjudication")
        current = DecisionStore(store).current(rid, decided, "fulltext")
        proposals = DecisionStore(store).proposals(rid, decided, "fulltext")
        later = reading_run(client, rid)
        later_calls = calls_for(store, adapter, later["id"], decided)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and holder["undone"]
    assert steps == [("cancelled", "human_decided"), ("succeeded", None)]
    assert proposals == [] and current["decided_by"] != "human" and current["reason_code"] == "not_read_yet"
    assert len(later_calls) == 2


def test_a_reading_call_closed_unsent_is_opened_again_and_sent_when_the_run_resumes_after_an_undo(
        tmp_path, monkeypatch):
    """A step closed unsent for a person's decision is a skip, not a failure: the run pauses, the decision is undone,
    and the resumed run sends that call and closes the work from both runs."""
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication":
            return
        store = holder["app"].state.store
        source = sent_source(store, si)
        if "armed" not in holder:
            holder.update(armed=source, rid=store.run(si["run_id"])["research_id"])
        elif source != holder["armed"] and "paused" not in holder:
            holder["paused"] = True
            store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                             pause_reason="user_requested")

    works, fetcher = papers(2)
    adapter = FakeAdapter(valid_response, before=before)
    health = adapter.health

    async def slow_health(refresh=False):
        if holder.get("armed") and not holder.get("decided"):
            DecisionStore(holder["app"].state.store).record(holder["rid"], holder["armed"], "human_criterion_not_met")
            holder["decided"] = holder["armed"]
        return await health(refresh)

    adapter.health = slow_health
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        decided = holder["decided"]
        skipped = [(s["status"], s["error_code"]) for s in store.run_steps(paused["id"])
                   if s["operation_key"] == f"fulltext_adjudication:{decided}:2"]
        DecisionStore(store).undo_human(rid, decided, "fulltext")
        client.post(f"/api/runs/{paused['id']}/resume")
        _, reading = wait(client, rid, paused["id"])
        resent = [(s["status"], s["error_code"]) for s in store.run_steps(reading["id"])
                  if s["operation_key"] == f"fulltext_adjudication:{decided}:2"]
        runs = sorted(call["adjudication_target"]["run"] for call in calls_for(store, adapter, reading["id"], decided))
        current = DecisionStore(store).current(rid, decided, "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and skipped == [("cancelled", "human_decided")]
    assert reading["status"] == "completed" and resent == [("succeeded", None)]
    assert runs == [1, 2]  # the first call is read back, only the skipped one is sent
    assert current["decided_by"] == "model_agreement" and current["reason_code"] != "not_read_yet"


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
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw"),
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
