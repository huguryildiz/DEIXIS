"""The full-text reading run inside a real `sw` research (slice 12, D85).

Workflow behavior only. Records are SYNTHETIC and from two fields, every transport is mocked and the model is
scripted. Passing shows the run follows the slice, not that a model read a paper.
"""

import json
import time

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow import adjudication
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_abstract_flow import QUESTION, client_of, records_of
from test_fulltext_flow import Fetcher, Transport, named_pdf, ok, work

SETTLED = ("completed", "failed", "paused", "cancelled")


def app_for(tmp_path, monkeypatch, transport, fetcher, *, workflow="sw", fetch="auto", reading="auto",
            adapter=None, concurrency=1):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
                               protocol_approval="as_proposed", fulltext_fetch=fetch, fulltext_adjudication=reading,
                               model_concurrency=concurrency),
                      adapters={"fake": adapter or FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)), fetcher=fetcher,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in SETTLED:
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def discover(client, question=QUESTION, effort="quick"):
    rid = client.post("/api/researches", json={"question": question, "model_connection": "fake",
                                               "requested_model": "fake-model", "effort": effort}).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    view, run = wait(client, rid, run_id)
    return rid, run_id, view, run


def runs_of(client, rid, kind):
    return [r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["kind"] == kind]


def wait_kind(client, rid, kind, index=0):
    deadline = time.time() + 30
    while time.time() < deadline:
        found = sorted(runs_of(client, rid, kind), key=lambda r: r["created_at"])
        if len(found) > index and found[index]["status"] in SETTLED:
            return wait(client, rid, found[index]["id"])
        time.sleep(0.05)
    raise AssertionError(f"no {kind} run settled")


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json, status FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    if row is None or row["output_json"] is None:
        return None
    return json.loads(row["output_json"])


def adj_calls(adapter, run_id=None):
    return [call for call in adapter.calls if call["task_type"] == "fulltext_adjudication"
            and (run_id is None or call["run_id"] == run_id)]


def selection(store, rid, svid):
    row = store.conn.execute("SELECT state, origin FROM selections WHERE research_id = ? AND source_version_id = ?",
                             (rid, svid)).fetchone()
    return (row["state"], row["origin"])


def fulltext_code(store, rid, svid):
    return (DecisionStore(store).current(rid, svid, "fulltext") or {}).get("reason_code")


def patch_selection(client, rid, svid, state):
    view = client.get(f"/api/researches/{rid}").json()
    source = next(s for s in view["sources"] if s["source_version_id"] == svid)
    client.patch(f"/api/researches/{rid}/selections/{svid}",
                 json={"state": state, "expected_version": source["selection"]["version"]})


def budget_of(calls, reads):
    def read_budget(effort):
        return {"max_model_calls": calls, "max_provider_requests": 0, "max_fulltext_reads": reads}
    return read_budget


def papers(n, named=True):
    works = [work(i, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, n + 1)]
    answers = {}
    for i in range(1, n + 1):
        data = named_pdf(f"10.1/oa.{i}") if named else make_pdf(["SYNTHETIC page one of a greenhouse crop."])
        answers[f"https://example.org/w{i}.pdf"] = ok(data)
    return works, Fetcher(answers)


def absent_response(si):
    if si["task_type"] != "fulltext_adjudication":
        return valid_response(si)
    body = json.loads(valid_response(si))
    for part in body["parts"]:
        part["label"] = "absent"
        part["quote"] = ""
        part["passage_id"] = None
    return json.dumps(body)


def disagree_response(si):
    if si["task_type"] != "fulltext_adjudication":
        return valid_response(si)
    if si["adjudication_target"]["run"] == 1:
        return valid_response(si)
    return absent_response(si)


def unverified_response(si):
    if si["task_type"] != "fulltext_adjudication":
        return valid_response(si)
    body = json.loads(valid_response(si))
    for part in body["parts"]:
        part["quote"] = "SYNTHETIC this quote is not on the shown page at all."
    return json.dumps(body)


# ---- the queue ----------------------------------------------------------------------------------

def test_a_completed_retrieval_run_is_followed_by_a_reading_run_that_includes_on_verified_quotes(tmp_path, monkeypatch):
    """auto: the reading run follows the retrieval run, and agreement with every quote on the page includes the work."""
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, fetch = wait_kind(client, rid, "fulltext_fetch")
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        plan = step_output(store, reading["id"], "adjudication_plan")
        summary = step_output(store, reading["id"], "adjudication_summary")
        pages = {row["quote_page"] for row in store.conn.execute(
            "SELECT quote_page FROM model_proposals WHERE research_id = ? AND stage = 'fulltext' AND quote_verified = 1", (rid,))}
        code = fulltext_code(store, rid, plan["works"][0]["read_version"])
        chosen = selection(store, rid, head)
        pending = [row["status"] for row in store.run_steps(reading["id"]) if row["status"] == "pending"]
        before = store.conn.execute("SELECT COUNT(*) FROM run_steps").fetchone()[0]
        client.get(f"/api/researches/{rid}")
        after = store.conn.execute("SELECT COUNT(*) FROM run_steps").fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert fetch["status"] == "completed" and reading["status"] == "completed"
    assert code == "all_parts_verified" and chosen == ("included", "code_rule")
    assert pages == {1}
    assert summary["include"] == 1 and summary["whole_text"] == 1 and summary["model_calls"] == 2
    assert len(adj_calls(adapter, reading["id"])) == 2
    assert pending == [] and before == after


def test_off_legacy_and_a_research_with_no_criterion_queue_no_reading_run(tmp_path, monkeypatch):
    off = app_for(tmp_path / "off", monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]),
                  Fetcher({"https://example.org/w1.pdf": ok(named_pdf("10.1/oa.1"))}), reading="off")
    client = client_of(off)
    try:
        rid, _, _, run = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        none = runs_of(client, rid, "fulltext_adjudication")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and none == []

    legacy = app_for(tmp_path / "legacy", monkeypatch, Transport([work(1)]), Fetcher({}), workflow="legacy")
    client = client_of(legacy)
    try:
        rid, _, _, run = discover(client)
        refused = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"})
        kinds = {r["kind"] for r in client.get(f"/api/researches/{rid}").json()["runs"]}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and "fulltext_adjudication" not in kinds and refused.status_code == 422

    bare = app_for(tmp_path / "bare", monkeypatch, Transport([]), Fetcher({}), reading="auto")
    client = client_of(bare)
    try:
        rid = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                   "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        plan = step_output(bare.state.store, run_id, "adjudication_plan")
        calls = bare.state.store.conn.execute(
            "SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'", (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and plan["reason"] == "no_criterion" and calls == 0


# ---- the rule table, through the run ------------------------------------------------------------

def test_an_unverified_quote_does_not_include(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(unverified_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        code, chosen = fulltext_code(store, rid, head), selection(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed"
    assert code == "include_quote_unverified" and chosen == ("pending", "code_rule")


def test_two_not_met_runs_exclude_and_a_disagreement_stays_pending(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        excluded = (fulltext_code(store, rid, head), selection(store, rid, head))
    finally:
        client.__exit__(None, None, None)
    assert excluded == ("criterion_absent", ("excluded", "code_rule"))

    works, fetcher = papers(1)
    app = app_for(tmp_path / "split", monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(disagree_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        split = (fulltext_code(store, rid, head), selection(store, rid, head))
    finally:
        client.__exit__(None, None, None)
    assert split == ("fulltext_runs_disagree", ("pending", "code_rule"))


def test_a_user_exclusion_is_not_read_and_a_user_inclusion_is_not_overwritten(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        patch_selection(client, rid, head, "excluded")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        plan = step_output(store, run_id, "adjudication_plan")
        excluded = selection(store, rid, head)
        calls = len(adj_calls(app.state.adapters["fake"], run_id))
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and plan["works"] == [] and calls == 0
    assert excluded == ("excluded", "user")

    works, fetcher = papers(1)
    app = app_for(tmp_path / "kept", monkeypatch, Transport(works), fetcher, reading="off",
                  adapter=FakeAdapter(absent_response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        patch_selection(client, rid, head, "included")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        wait(client, rid, run_id)
        kept = selection(store, rid, head)
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(app.state.adapters["fake"], run_id))
    finally:
        client.__exit__(None, None, None)
    assert calls == 2 and code == "criterion_absent" and kept == ("included", "user")


def test_a_human_fulltext_decision_is_not_read(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        DecisionStore(store).record(rid, head, "human_include")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        plan = step_output(store, run_id, "adjudication_plan")
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and plan["works"] == [] and code == "human_include"
    assert adj_calls(adapter, run_id) == []


def test_nothing_is_decided_while_the_model_is_off(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        adapter.ready = False
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "paused" and reading["pause_reason"] == "model_connection_not_ready"
    assert code == "not_read_yet" and adj_calls(adapter, run_id) == []


def test_a_call_that_did_not_answer_is_not_decided_and_resume_makes_only_the_missing_call(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    failed = {"done": False}

    def fail(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] == 2 and not failed["done"]:
            failed["done"] = True
            return ModelStepResult("unavailable", error="synthetic connection")
        return None

    adapter = FakeAdapter(valid_response, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, paused = wait(client, rid, run_id)
        paused_code = fulltext_code(store, rid, head)
        paused_calls = len(adj_calls(adapter, run_id))
        client.post(f"/api/runs/{run_id}/resume")
        _, reading = wait(client, rid, run_id)
        resumed_calls = len(adj_calls(adapter, run_id))
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and paused_code == "not_read_yet" and paused_calls == 2
    assert reading["status"] == "completed" and resumed_calls == paused_calls + 1 and code == "all_parts_verified"


def test_invalid_output_is_not_repeated_and_the_next_run_reads_the_work_with_two_calls(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    phase = {"bad": True}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and phase["bad"] and si["adjudication_target"]["run"] == 2:
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, done = wait(client, rid, first)
        sessions = store.conn.execute(
            "SELECT COUNT(*) FROM model_sessions WHERE run_id = ? AND step_id IN"
            " (SELECT id FROM run_steps WHERE run_id = ? AND operation_key LIKE 'fulltext_adjudication:%:2')",
            (first, first)).fetchone()[0]
        code = fulltext_code(store, rid, head)
        phase["bad"] = False
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, again = wait(client, rid, second)
        second_calls = len(adj_calls(adapter, second))
        settled = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert done["status"] == "completed" and sessions == 2 and code == "not_read_yet"
    assert again["status"] == "completed" and second_calls == 2 and settled == "all_parts_verified"


def test_a_fresh_decision_is_not_reread_until_the_question_is_revised(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_kind(client, rid, "fulltext_adjudication")
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reread = wait(client, rid, again)
        skipped = len(adj_calls(adapter, again))
        research = client.get(f"/api/researches/{rid}").json()["research"]
        client.post(f"/api/researches/{rid}/scope", json={"question": f"{QUESTION} under a SYNTHETIC drip line",
                                                          "expected_version": research["version"]})
        discover_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, discover_id)
        _, revised = wait_kind(client, rid, "fulltext_adjudication", index=2)
        revised_calls = len(adj_calls(adapter, revised["id"]))
    finally:
        client.__exit__(None, None, None)
    assert first["status"] == "completed" and reread["status"] == "completed" and skipped == 0
    assert revised["status"] == "completed" and revised_calls == 2


def test_a_work_past_the_limit_is_not_reached_and_the_next_run_reads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(adjudication, "read_budget", budget_of(2, 1))
    works, fetcher = papers(2)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        summary = step_output(store, first["id"], "adjudication_summary")
        codes = {key: fulltext_code(store, rid, svid) for key, svid in records_of(store, rid).items()}
        monkeypatch.setattr(adjudication, "read_budget", budget_of(4, 2))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, again = wait(client, rid, second)
        later = {key: fulltext_code(store, rid, svid) for key, svid in records_of(store, rid).items()}
        calls = len(adj_calls(adapter, second))
    finally:
        client.__exit__(None, None, None)
    assert first["status"] == "completed" and summary["not_reached"] == 1 and summary["include"] == 1
    assert sorted(codes.values()) == ["all_parts_verified", "not_read_yet"]
    assert again["status"] == "completed" and calls == 2
    assert set(later.values()) == {"all_parts_verified"}


def test_a_paused_run_whose_plan_is_exactly_the_limit_finishes_without_repeating_a_call(tmp_path, monkeypatch):
    """The plan is as long as the limit. A resumed run finishes it and repeats no call; the summary matches."""
    monkeypatch.setattr(adjudication, "read_budget", budget_of(4, 2))
    works, fetcher = papers(2)

    def uninterrupted():
        adapter = FakeAdapter(valid_response)
        app = app_for(tmp_path / "whole", monkeypatch, Transport(works), Fetcher(dict(fetcher.answers)), adapter=adapter)
        client = client_of(app)
        try:
            rid, _, _, _ = discover(client)
            _, reading = wait_kind(client, rid, "fulltext_adjudication")
            summary = step_output(app.state.store, reading["id"], "adjudication_summary")
            calls = len(adj_calls(adapter, reading["id"]))
        finally:
            client.__exit__(None, None, None)
        return summary, calls

    whole, whole_calls = uninterrupted()
    seen = []
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication":
            return
        seen.append(si["step_input_id"])
        if len(seen) == 2:
            holder["store"].update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                       pause_reason="user_requested")

    adapter = FakeAdapter(valid_response, delay=0.02, before=before)
    app = app_for(tmp_path / "paused", monkeypatch, Transport(works), Fetcher(dict(fetcher.answers)), adapter=adapter)
    client = client_of(app)
    try:
        holder["store"] = app.state.store
        rid, _, _, _ = discover(client)
        _, paused = wait_kind(client, rid, "fulltext_adjudication")
        paused_calls = len(adj_calls(adapter))
        client.post(f"/api/runs/{paused['id']}/resume")
        _, reading = wait(client, rid, paused["id"])
        summary = step_output(app.state.store, reading["id"], "adjudication_summary")
        calls = len(adj_calls(adapter, reading["id"]))
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and paused_calls == 2
    assert reading["status"] == "completed" and calls == whole_calls == 4
    assert summary == whole


def test_a_repair_leaves_the_last_work_not_reached_and_no_work_is_half_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(adjudication, "read_budget", budget_of(3, 2))
    works, fetcher = papers(2)
    state = {"bad": True}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and state["bad"] and si["adjudication_target"]["run"] == 1:
            state["bad"] = False
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        summary = step_output(store, reading["id"], "adjudication_summary")
        steps = store.conn.execute(
            "SELECT operation_key, status FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (reading["id"],)).fetchall()
        by_head: dict[str, int] = {}
        for row in steps:
            head, _, _run = row["operation_key"].removeprefix("fulltext_adjudication:").rpartition(":")
            by_head[head] = by_head.get(head, 0) + 1
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and summary["not_reached"] == 1
    assert sorted(by_head.values()) == [2]
    assert summary["model_calls"] == 3

    monkeypatch.setattr(adjudication, "read_budget", budget_of(1, 1))
    works, fetcher = papers(1)
    app = app_for(tmp_path / "short", monkeypatch, Transport(works), fetcher, reading="off")
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, short = wait(client, rid, run_id)
        opened = app.state.store.conn.execute(
            "SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (run_id,)).fetchone()[0]
        summary = step_output(app.state.store, run_id, "adjudication_summary")
    finally:
        client.__exit__(None, None, None)
    assert short["status"] == "completed" and opened == 0 and summary["not_reached"] == 1 and summary["model_calls"] == 0


def test_at_most_the_limiter_limit_calls_are_in_flight(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    peaks = []
    adapter = FakeAdapter(valid_response, delay=0.05)

    def before(si):
        if si["task_type"] == "fulltext_adjudication":
            peaks.append(adapter.current + 1)

    adapter.before = before
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter, concurrency=2)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and peaks and max(peaks) <= 2 and max(peaks) == 2


def test_a_scope_revision_cancels_the_run_and_an_in_flight_response_writes_no_decision(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    holder = {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication" or holder.get("bumped"):
            return
        holder["bumped"] = True
        store = holder["store"]
        research = store.research(si["research_id"])
        scope = store.scope(si["research_id"])
        store.revise_scope(si["research_id"], research["version"],
                           scope["question"] + " under a SYNTHETIC drip line", scope.get("steering"))

    adapter = FakeAdapter(valid_response, delay=0.05, before=before)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter, concurrency=2)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = holder["store"] = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
        proposals = store.conn.execute(
            "SELECT COUNT(*) FROM model_proposals WHERE step_id IN (SELECT id FROM run_steps WHERE run_id = ?)",
            (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "cancelled" and reading["pause_reason"] == "scope_revised"
    assert code == "not_read_yet" and proposals == 0


def test_an_unconfirmed_pdf_is_decided_without_a_call_and_a_user_upload_is_read(tmp_path, monkeypatch):
    works, fetcher = papers(1, named=False)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(adapter, run_id))
        summary = step_output(store, run_id, "adjudication_summary")
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and code == "pdf_identity_unconfirmed" and calls == 0
    assert summary["identity_unconfirmed"] == 1 and summary["model_calls"] == 0

    works, fetcher = papers(1, named=False)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path / "upload", monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        store.conn.execute("UPDATE source_assets SET origin = 'user_upload' WHERE source_version_id = ?", (head,))
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
        calls = len(adj_calls(adapter, run_id))
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and calls == 2 and code == "all_parts_verified"


def test_a_version_that_is_not_a_member_of_this_research_is_not_read(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off")
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_fetch")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        work_id = store.source(head)["work_id"]
        store.conn.execute(
            "INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES (?, ?, ?, 'provider', 't')",
            ("srv_outsider_synthetic", work_id, "SYNTHETIC outsider greenhouse tomato"))
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"}).json()["id"]
        wait(client, rid, run_id)
        plan = step_output(store, run_id, "adjudication_plan")
        versions = store.work_versions(rid, head)
        payload = store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE run_id = ? AND task_type = 'fulltext_adjudication' LIMIT 1",
            (run_id,)).fetchone()
        shown = json.loads(payload["payload_json"])["adjudication_target"]["source_id"]
    finally:
        client.__exit__(None, None, None)
    assert "srv_outsider_synthetic" not in versions
    assert plan["works"][0]["read_version"] == head == shown


def test_discovery_fetch_and_answer_runs_do_not_open_a_reading_step(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="auto")
    client = client_of(app)
    try:
        rid, discovery_id, _, _ = discover(client)
        _, fetch = wait_kind(client, rid, "fulltext_fetch")
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        discovery_kinds = {row["kind"] for row in store.run_steps(discovery_id)}
        fetch_kinds = {row["kind"] for row in store.run_steps(fetch["id"])}
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, answered = wait(client, rid, answer)
        answer_kinds = {row["kind"] for row in store.run_steps(answer)}
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed"
    assert not any("adjudication" in kind for kind in discovery_kinds | fetch_kinds | answer_kinds)
    assert "model:grounded_answer" in answer_kinds and answered["status"] == "completed"


def test_a_repair_the_budget_no_longer_holds_is_skipped_and_the_run_completes(tmp_path, monkeypatch):
    """One work, budget 3, both first calls invalid: the first repair fits, the second does not. The second call is
    closed `invalid_model_output`, the run is `completed` (not `budget_exhausted`), and the work gets no decision."""
    monkeypatch.setattr(adjudication, "read_budget", budget_of(3, 1))
    works, fetcher = papers(1)
    bad = {1, 2}

    def responder(si):
        if si["task_type"] == "fulltext_adjudication" and si["adjudication_target"]["run"] in bad:
            bad.discard(si["adjudication_target"]["run"])
            return "{"
        return valid_response(si)

    adapter = FakeAdapter(responder)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        summary = step_output(store, reading["id"], "adjudication_summary")
        steps = sorted((row["status"], row["error_code"]) for row in store.conn.execute(
            "SELECT status, error_code FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'",
            (reading["id"],)).fetchall())
        heads = [c["source_version_id"] for c in store.candidates(rid)]
        decided = [fulltext_code(store, rid, svid) for svid in heads]
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and reading["pause_reason"] is None
    assert steps == [("failed", "invalid_model_output"), ("succeeded", None)]
    assert summary["model_calls"] == 3
    assert all(code in (None, "not_read_yet") for code in decided)


# ---- a reading call the adapter's turn limit cut off (slice 13e) --------------------------------

def turn_timeout(task, times):
    """The Codex adapter's answer when a turn outlives its limit: `failed`, `client_timeout`, maybe delivered."""
    left = {"n": times}

    def fail(si):
        if si["task_type"] == task and left["n"] and si.get("adjudication_target", {}).get("run", 2) == 2:
            left["n"] -= 1
            return ModelStepResult("failed", error="client_timeout", delivery_class="after_send_unknown")
        return None
    return fail


def test_a_reading_call_cut_off_once_by_the_turn_limit_is_sent_again_and_the_run_completes(tmp_path, monkeypatch):
    """One `client_timeout` does not stop the reading run: the same step is sent once more, as a second attempt."""
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("fulltext_adjudication", 1))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        step = store.conn.execute(
            "SELECT id, status, attempt FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'"
            " AND operation_key LIKE '%:2'", (reading["id"],)).fetchone()
        inputs = [row["attempt"] for row in store.conn.execute(
            "SELECT attempt FROM step_inputs WHERE step_id = ? ORDER BY rowid", (step["id"],))]
        sessions = [row["status"] for row in store.conn.execute(
            "SELECT status FROM model_sessions WHERE step_id = ? ORDER BY rowid", (step["id"],))]
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and reading["pause_reason"] is None
    assert step["status"] == "succeeded" and step["attempt"] == 2
    assert inputs == [0, 1] and len(sessions) == 2
    # Both sends are counted: run 1, and run 2 twice.
    assert reading["usage"]["model_calls"] == 3 and len(adj_calls(adapter, reading["id"])) == 3
    assert code == "all_parts_verified"


def test_a_reading_call_cut_off_twice_pauses_the_run_as_before(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("fulltext_adjudication", 2))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        step = app.state.store.conn.execute(
            "SELECT status, error_code, attempt FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'"
            " AND operation_key LIKE '%:2'", (reading["id"],)).fetchone()
    finally:
        client.__exit__(None, None, None)
    assert (reading["status"], reading["pause_reason"]) == ("paused", "model_call_failed")
    assert (step["status"], step["error_code"], step["attempt"]) == ("outcome_unknown", "model_failed", 2)
    assert len(adj_calls(adapter, reading["id"])) == 3


def test_an_abstract_screening_call_cut_off_once_is_sent_again(tmp_path, monkeypatch):
    """The abstract stage's batch calls are the other place one slow call stopped a whole stage."""
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("abstract_screening", 1))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, discovery = discover(client)
        attempts = sorted(row["attempt"] for row in app.state.store.conn.execute(
            "SELECT attempt FROM run_steps WHERE run_id = ? AND kind = 'model:abstract_screening'", (discovery["id"],)))
    finally:
        client.__exit__(None, None, None)
    assert discovery["status"] == "completed"
    assert attempts[-1] == 2 and attempts.count(2) == 1


def test_a_grounded_answer_cut_off_once_pauses_the_run_as_before(tmp_path, monkeypatch):
    """Outside the two batch stages one call is the whole stage, and the first `client_timeout` stops it."""
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("grounded_answer", 1))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        answer_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, answer = wait(client, rid, answer_id)
        calls = [call for call in adapter.calls if call["task_type"] == "grounded_answer"]
    finally:
        client.__exit__(None, None, None)
    assert (answer["status"], answer["pause_reason"]) == ("paused", "model_call_failed")
    assert len(calls) == 1


def test_a_reading_call_cut_off_with_no_call_left_in_the_budget_is_not_sent_again(tmp_path, monkeypatch):
    """Budget 2 for one work: run 1 and run 2 use it up, run 2 times out. The step stays `outcome_unknown` and the run
    pauses as it did before slice 13e; it is not reopened only to be closed as `budget_exhausted`."""
    monkeypatch.setattr(adjudication, "read_budget", budget_of(2, 1))
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, fail=turn_timeout("fulltext_adjudication", 1))
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        step = app.state.store.conn.execute(
            "SELECT status, error_code, attempt FROM run_steps WHERE run_id = ? AND kind = 'model:fulltext_adjudication'"
            " AND operation_key LIKE '%:2'", (reading["id"],)).fetchone()
    finally:
        client.__exit__(None, None, None)
    assert (reading["status"], reading["pause_reason"]) == ("paused", "model_call_failed")
    assert (step["status"], step["error_code"], step["attempt"]) == ("outcome_unknown", "model_failed", 1)
    assert len(adj_calls(adapter, reading["id"])) == 2
