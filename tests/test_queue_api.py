"""The human queue through the API and inside real `sw` runs (slice 16, D96).

Workflow behavior only. Records are SYNTHETIC and from two fields (greenhouse irrigation, and the pallet loading and
chaining pools the earlier flow tests use), every transport is mocked and the model is scripted. Passing shows that a
person's answer reaches the selection, that the model is not asked about a decided work again — in the abstract read,
the chain read, the fetch plan, the reading plan and a reading run already in flight — and that the endpoints keep to
the `sw` workflow; it says nothing about how a real model or a real person reads a paper.
"""

from deixis.workflow import abstract_stage, adjudication, fulltext
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
