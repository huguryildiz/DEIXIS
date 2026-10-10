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
from deixis.workflow import adjudication, fulltext
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_abstract_flow import QUESTION, client_of, records_of
from test_fulltext_flow import Fetcher, Transport, named_pdf, ok, work

SETTLED = ("completed", "failed", "paused", "cancelled")


def app_for(tmp_path, monkeypatch, transport, fetcher, *, workflow="sw", fetch="auto", reading="auto",
            adapter=None, concurrency=1, overlap=True):
    if not overlap:
        # A discovery run queued before slice 17a: its fetch follows as a retrieval run of its own (decision 3).
        monkeypatch.setattr(fulltext, "overlap_budget", fulltext.fetch_budget)
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch=fetch, fulltext_adjudication=reading,
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
    if kind == "fulltext_adjudication":
        kind = "discovery"
    deadline = time.time() + 30
    while time.time() < deadline:
        found = sorted(runs_of(client, rid, kind), key=lambda r: r["created_at"])
        if len(found) > index and found[index]["status"] in SETTLED:
            return wait(client, rid, found[index]["id"])
        time.sleep(0.05)
    raise AssertionError(f"no {kind} run settled")


def wait_fetch(client, rid):
    """The settled run that holds the fetch: since slice 17a the discovery run itself, before it a retrieval run."""
    discovery = min(runs_of(client, rid, "discovery"), key=lambda r: r["created_at"])
    if (discovery["budget"].get("fulltext_fetch") or {}).get("mode") == "overlap":
        return wait(client, rid, discovery["id"])
    return wait_kind(client, rid, "fulltext_fetch")


def step_output(store, run_id, key):
    from batch_outputs import stage_output
    return stage_output(store, run_id, key)


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
        _, fetch = wait_fetch(client, rid)
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
    assert summary["include"] == 1 and summary["whole_text"] == 1 and len(adj_calls(adapter, reading["id"])) == 2
    assert len(adj_calls(adapter, reading["id"])) == 2
    assert pending == [] and before == after


@pytest.mark.parametrize(("mode", "expected"), [
    ("aspect_missing", "all_parts_verified"),
    ("core_missing", "criterion_absent"),
    ("core_unverified", "include_quote_unverified"),
    ("legacy", "part_without_evidence"),
])
def test_core_gate_and_recorded_source_coverage_through_the_api(tmp_path, monkeypatch, mode, expected):
    """SYNTHETIC model readings exercise persistence and API coverage, not relevance quality."""
    from deixis.workflow.store import Store

    def response(si):
        body = json.loads(valid_response(si))
        if si["task_type"] == "criterion_proposal":
            body["parts"][1]["role"] = "aspect"
        if si["task_type"] == "fulltext_adjudication":
            core, aspect = body["parts"]
            aspect.update(label="absent" if si["adjudication_target"]["run"] == 1 else "unclear",
                          quote="", passage_id=None)
            if mode == "core_missing":
                core.update(label="absent", quote="", passage_id=None)
            elif mode == "core_unverified":
                core["quote"] = "SYNTHETIC this invented quote is absent from the shown page."
        return json.dumps(body)

    if mode == "legacy":
        original = Store.frozen_criterion

        def legacy(self, *args, **kwargs):
            frozen = original(self, *args, **kwargs)
            if frozen:
                frozen["parts"] = [{k: v for k, v in part.items() if k != "role"} for part in frozen["parts"]]
            return frozen

        monkeypatch.setattr(Store, "frozen_criterion", legacy)
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=FakeAdapter(response))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        assert reading["status"] == "completed"
        assert fulltext_code(store, rid, head) == expected
        assert (selection(store, rid, head)[0] == "included") is (mode == "aspect_missing")
        coverage = client.get(f"/api/researches/{rid}/queue/{head}").json()["coverage"]
        assert len(coverage) == 2
        assert [r["parts"][1]["label"] for r in coverage] == ["absent", "unclear"]
        assert all(r["parts"][0]["inclusion_role"] == "core" for r in coverage)
        assert all(r["parts"][1]["inclusion_role"] == ("core" if mode == "legacy" else "aspect")
                   for r in coverage)
        if mode == "aspect_missing":
            assert all(r["parts"][0]["quote_verified"] for r in coverage)
            assert all(r["parts"][0]["anchor_text"] for r in coverage)
            frozen = Store.frozen_criterion

            def revised_roles(self, *args, **kwargs):
                criterion = frozen(self, *args, **kwargs)
                if criterion:
                    criterion["parts"] = [p | {"role": "core"} for p in criterion["parts"]]
                return criterion

            monkeypatch.setattr(Store, "frozen_criterion", revised_roles)
            historical = client.get(f"/api/researches/{rid}/queue/{head}").json()["coverage"]
            assert all(r["parts"][1]["inclusion_role"] == "aspect" for r in historical)
        elif mode == "core_unverified":
            row = client.get(f"/api/researches/{rid}/queue/{head}").json()["row"]
            assert row["question"]["part"] == "method of its own"
    finally:
        client.__exit__(None, None, None)

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




def test_a_human_fulltext_decision_is_not_read(tmp_path, monkeypatch):
    from deixis.workflow import fast_answer, small_batch

    # No automatic answer, so no late revision (D255) reads W1's file before the person decides.
    monkeypatch.setattr(fast_answer, "auto_answer", lambda store, run: None)
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, reading="off", adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_fetch(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        assert fulltext_code(store, rid, head) == "not_read_yet"
        DecisionStore(store).record(rid, head, "human_include")
        # The second discovery reads full text (the fast path reads inside discovery, D251); W1 alone has a file.
        freeze = small_batch.freeze_budget
        monkeypatch.setattr(small_batch, "freeze_budget", lambda budget, effort, reading: freeze(budget, effort, "auto"))
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reading = wait(client, rid, run_id)
        code = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and reading["budget"]["inspection"]["read_limit"] > 0
    assert code == "human_include" and adj_calls(adapter, run_id) == []








def test_a_fresh_decision_is_not_reread_until_the_question_is_revised(tmp_path, monkeypatch):
    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_kind(client, rid, "fulltext_adjudication")
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
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
    # `whole_text` and `model_calls` are run-wide counts taken as each work's read closes; the fast path reads work by
    # work beside the run's other calls (D251), so the sums of those snapshots depend on timing and are left out.
    counts = lambda s: {key: value for key, value in s.items() if key not in ("whole_text", "model_calls")}
    assert counts(summary) == counts(whole)
















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
    assert len(adj_calls(adapter, reading["id"])) == 3
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
        # The fast-path discovery queues the answer run itself (D254); its one grounded-answer call is cut off.
        _, answer = wait_kind(client, rid, "answer")
        calls = [call for call in adapter.calls if call["task_type"] == "grounded_answer"]
    finally:
        client.__exit__(None, None, None)
    assert (answer["status"], answer["pause_reason"]) == ("paused", "model_call_failed")
    assert len(calls) == 1




# ---- a study-protocol title (slice 26, SW26) ----------------------------------------------------------------------

PROTOCOL = "SYNTHETIC irrigation scheduling of an open field crop: a study protocol"


def protocol_paper(title=PROTOCOL):
    """One work whose read version's title names a study protocol; its PDF names its DOI, so identity holds."""
    return [work(1, pdf_url="https://example.org/w1.pdf", title=title)], \
        Fetcher({"https://example.org/w1.pdf": ok(named_pdf("10.1/oa.1"))})


def only_the_result_part(monkeypatch):
    """A criterion whose one part is a result part. The proposal contract asks for two parts or more, so the stored
    criterion is narrowed where the reading plan reads it (Sol r1's single-result-part case)."""
    from deixis.workflow.store import Store
    frozen = Store.frozen_criterion

    def narrowed(self, *args, **kwargs):
        criterion = frozen(self, *args, **kwargs)
        if criterion is None:
            return None
        parts = [part for part in criterion["parts"] if part["name"] == "measured outcome"]
        return {**criterion, "parts": parts,
                "cue_phrases": [p for p in criterion["cue_phrases"] if p.get("part") in (None, "measured outcome")]}
    monkeypatch.setattr(Store, "frozen_criterion", narrowed)


def read_once(tmp_path, monkeypatch, works, fetcher, adapter):
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        decision = DecisionStore(store).current(rid, head, "fulltext")
        plan = step_output(store, reading["id"], "adjudication_plan")
        found = (reading["status"], decision["reason_code"], decision["note"], selection(store, rid, head),
                 len(plan["criterion"]["parts"]))
    finally:
        client.__exit__(None, None, None)
    return found


def test_an_all_present_reading_of_a_protocol_title_goes_to_the_queue_and_is_not_read_again(tmp_path, monkeypatch):
    works, fetcher = protocol_paper()
    adapter = FakeAdapter(valid_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        written = DecisionStore(store).current(rid, head, "fulltext")
        chosen = selection(store, rid, head)
        summary = step_output(store, reading["id"], "adjudication_summary")
        row = client.get(f"/api/researches/{rid}/queue").json()["rows"][0]
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, reread = wait(client, rid, again)
        reread_calls = len(adj_calls(adapter, again))
        DecisionStore(store).record(rid, head, "human_include")
        DecisionStore(store).derive_selection(rid, store.source(head)["work_id"])
        research = client.get(f"/api/researches/{rid}").json()["research"]
        client.post(f"/api/researches/{rid}/scope", json={"question": f"{QUESTION} under a SYNTHETIC drip line",
                                                          "expected_version": research["version"]})
        later = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, later)
        kept = fulltext_code(store, rid, head)
    finally:
        client.__exit__(None, None, None)
    assert reading["status"] == "completed" and len(adj_calls(adapter, reading["id"])) == 2
    assert (written["reason_code"], written["note"]) == ("protocol_title",
                                                         "protocol_title:all_parts_verified:study protocol")
    assert chosen == ("pending", "code_rule") and summary["include"] == 0
    assert (row["reason_code"], row["kind"], row["question"]) == ("protocol_title", "confirm_results", None)
    assert reread["status"] == "completed" and reread_calls == 0
    assert kept == "human_include"


def test_a_plain_title_read_the_same_way_is_still_included(tmp_path, monkeypatch):
    works, fetcher = protocol_paper(title="SYNTHETIC irrigation scheduling of an open field crop: a randomized trial")
    found = read_once(tmp_path, monkeypatch, works, fetcher, FakeAdapter(valid_response))
    assert found == ("completed", "all_parts_verified", None, ("included", "code_rule"), 2)


def test_a_single_result_part_absent_in_both_runs_is_not_excluded_on_a_protocol_title(tmp_path, monkeypatch):
    only_the_result_part(monkeypatch)
    works, fetcher = protocol_paper()
    found = read_once(tmp_path / "protocol", monkeypatch, works, fetcher, FakeAdapter(absent_response))
    assert found == ("completed", "protocol_title", "protocol_title:criterion_absent:study protocol",
                     ("pending", "code_rule"), 1)
    works, fetcher = protocol_paper(title="SYNTHETIC irrigation scheduling of an open field crop")
    found = read_once(tmp_path / "plain", monkeypatch, works, fetcher, FakeAdapter(absent_response))
    assert found == ("completed", "criterion_absent", None, ("excluded", "code_rule"), 1)


def test_every_part_absent_on_a_protocol_title_goes_to_the_queue(tmp_path, monkeypatch):
    works, fetcher = protocol_paper()
    found = read_once(tmp_path, monkeypatch, works, fetcher, FakeAdapter(absent_response))
    assert found == ("completed", "protocol_title", "protocol_title:criterion_absent:study protocol",
                     ("pending", "code_rule"), 2)


# ---- a criterion with a comparator part (slice 28, D109) ----------------------------------------------------------

def with_a_comparator(monkeypatch, part="measured outcome"):
    """The frozen criterion gains a `comparator` question element naming `part`, with the role required (slice 25a
    shape). The fake proposal names no element, so the element is added where the plan and the queue read it."""
    from deixis.workflow.store import Store
    frozen = Store.frozen_criterion

    def with_element(self, *args, **kwargs):
        criterion = frozen(self, *args, **kwargs)
        if criterion is None:
            return None
        return {**criterion, "question_elements": [{"role": "comparator", "words": "SYNTHETIC usual", "part": part}],
                "required_roles": ["comparator"]}
    monkeypatch.setattr(Store, "frozen_criterion", with_element)


def labelled_response(labels):
    """Every reading run labels each part as `labels` says; a `present` part keeps the fake's verified quote."""
    def respond(si):
        if si["task_type"] != "fulltext_adjudication":
            return valid_response(si)
        body = json.loads(valid_response(si))
        for part in body["parts"]:
            label = labels.get(part["part"], "present")
            if label != "present":
                part.update(label=label, quote="", passage_id=None)
        return json.dumps(body)
    return respond


def read_with_targets(tmp_path, monkeypatch, adapter, title=None):
    works, fetcher = protocol_paper(title=title or "SYNTHETIC irrigation scheduling of an open field crop")
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, reading = wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        decision = DecisionStore(store).current(rid, head, "fulltext")
        rows = client.get(f"/api/researches/{rid}/queue").json()["rows"]
        found = {"status": reading["status"], "code": decision["reason_code"], "note": decision["note"],
                 "selection": selection(store, rid, head), "rows": rows,
                 "targets": [call["adjudication_target"]["parts"]
                             for call in adj_calls(adapter, reading["id"])]}
    finally:
        client.__exit__(None, None, None)
    return found


def test_the_reading_marks_the_comparator_part_only_and_a_plain_criterion_is_sent_as_before(tmp_path, monkeypatch):
    plain = read_with_targets(tmp_path / "plain", monkeypatch, FakeAdapter(valid_response))
    with_a_comparator(monkeypatch)
    marked = read_with_targets(tmp_path / "marked", monkeypatch, FakeAdapter(valid_response))
    assert len(plain["targets"]) == len(marked["targets"]) == 2
    for parts in plain["targets"]:
        assert [set(part) for part in parts] == [{"name", "definition", "inclusion_role"}] * 2
        assert all(part["inclusion_role"] == "core" for part in parts)
    for before, after in zip(plain["targets"], marked["targets"]):
        assert after == [before[0], before[1] | {"role": "comparator"}]
    assert plain["code"] == marked["code"] == "all_parts_verified"


def test_the_comparator_absent_and_every_other_part_unclear_is_withheld_not_excluded(tmp_path, monkeypatch):
    with_a_comparator(monkeypatch)
    found = read_with_targets(tmp_path, monkeypatch, FakeAdapter(labelled_response(
        {"method of its own": "unclear", "measured outcome": "absent"})))
    assert (found["status"], found["code"], found["note"], found["selection"]) == (
        "completed", "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:measured outcome",
        ("pending", "code_rule"))
    row = found["rows"][0]
    assert (row["reason_code"], row["kind"], row["question"]["part"]) == (
        "comparator_exclusion_withheld", "confirm_absent", "measured outcome")


def test_another_part_and_the_comparator_absent_in_both_runs_is_withheld_only_on_a_comparator_criterion(
        tmp_path, monkeypatch):
    """Sol r1's case: nothing `present`, another part and the comparator `absent` in both runs."""
    labels = {"method of its own": "absent", "measured outcome": "absent"}
    plain = read_with_targets(tmp_path / "plain", monkeypatch, FakeAdapter(labelled_response(labels)))
    assert (plain["code"], plain["note"], plain["selection"]) == ("criterion_absent", None, ("excluded", "code_rule"))
    with_a_comparator(monkeypatch)
    marked = read_with_targets(tmp_path / "marked", monkeypatch, FakeAdapter(labelled_response(labels)))
    assert (marked["code"], marked["note"], marked["selection"]) == (
        "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:measured outcome",
        ("pending", "code_rule"))


def test_the_comparator_absent_with_the_other_part_present_is_still_a_part_without_evidence(tmp_path, monkeypatch):
    with_a_comparator(monkeypatch)
    found = read_with_targets(tmp_path, monkeypatch, FakeAdapter(labelled_response({"measured outcome": "absent"})))
    assert (found["code"], found["note"], found["selection"]) == ("part_without_evidence", None,
                                                                  ("pending", "code_rule"))
    row = found["rows"][0]
    assert (row["kind"], row["question"]["part"]) == ("confirm_absent", "measured outcome")


def test_an_all_negative_comparator_reading_of_a_protocol_title_is_withheld_for_the_comparator(tmp_path, monkeypatch):
    with_a_comparator(monkeypatch)
    found = read_with_targets(tmp_path, monkeypatch, FakeAdapter(absent_response), title=PROTOCOL)
    assert (found["code"], found["note"], found["selection"]) == (
        "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:measured outcome",
        ("pending", "code_rule"))


def test_a_persons_decision_on_a_comparator_criterion_is_not_overwritten(tmp_path, monkeypatch):
    with_a_comparator(monkeypatch)
    works, fetcher = protocol_paper(title="SYNTHETIC irrigation scheduling of an open field crop")
    adapter = FakeAdapter(absent_response)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_kind(client, rid, "fulltext_adjudication")
        store = app.state.store
        head = records_of(store, rid)["W1"]
        DecisionStore(store).record(rid, head, "human_include")
        DecisionStore(store).derive_selection(rid, store.source(head)["work_id"])
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, again)
        kept = fulltext_code(store, rid, head)
        calls = len(adj_calls(adapter, again))
    finally:
        client.__exit__(None, None, None)
    assert kept == "human_include" and calls == 0


def test_an_element_naming_its_part_in_another_case_still_withholds_the_exclusion(tmp_path, monkeypatch):
    """Sol code r1: an element pointing at "Measured Outcome." for the part "measured outcome" is the same part."""
    with_a_comparator(monkeypatch, part="Measured Outcome.")
    found = read_with_targets(tmp_path, monkeypatch, FakeAdapter(absent_response))
    assert (found["code"], found["note"], found["selection"]) == (
        "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:measured outcome",
        ("pending", "code_rule"))
    assert found["rows"][0]["question"]["part"] == "measured outcome"
    assert all(parts[1].get("role") == "comparator" for parts in found["targets"])
