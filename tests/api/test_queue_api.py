"""The human queue through the API and inside real `sw` runs (slice 16, D96).

Workflow behavior only. Records are SYNTHETIC and from two fields (greenhouse irrigation, and the pallet loading and
chaining pools the earlier flow tests use), every transport is mocked and the model is scripted. Passing shows that a
person's answer reaches the selection, that the model is not asked about a decided work again — in the abstract read,
the chain read, the fetch plan, the reading plan and a reading run already in flight — and that the endpoints keep to
the `sw` workflow; it says nothing about how a real model or a real person reads a paper.
"""


import pytest

from deixis.workflow.read import fulltext
from deixis.workflow.screen.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from test_abstract_flow import records_of, responder
from test_adjudication_flow import adj_calls, app_for, client_of, discover, disagree_response, papers, wait, wait_kind
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


# ---- the model is not asked again --------------------------------------------------------------------------------


# ---- every send after a decision: resends, a real limiter wait, a pause, an undo before the close ------------------


# ---- the fifth answer --------------------------------------------------------------------------------------------


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


@pytest.mark.parametrize("phase", ["fulltext_adjudication"])
@pytest.mark.parametrize("human_code", ["human_include"])
def test_user_edit_during_small_batch_keeps_the_run_going_without_further_reads_of_that_work(tmp_path, monkeypatch, human_code, phase):
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
        assert (run["status"], run["pause_reason"]) == ("completed", None)
        store = app.state.store
        human = DecisionStore(store).current(rid, holder["decided"], "fulltext")
        assert human["reason_code"] == human_code
        assert human["decided_by"] == "human"
        assert len([c for c in adapter.calls if c["task_type"] == phase]) == 1
        assert not store.conn.execute("SELECT 1 FROM model_proposals WHERE research_id = ? AND stage = ?",
                                      (rid, "abstract" if phase == "abstract_screening" else "fulltext")).fetchone()
    finally:
        client.__exit__(None, None, None)


# ---- one answer to several rows (D110) ----------------------------------------------------------------------------

