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
    ("core_unverified", "include_quote_unverified"),
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


def test_a_human_fulltext_decision_is_not_read(tmp_path, monkeypatch):
    from deixis.workflow import answer as fast_answer, small_batch

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


# ---- a study-protocol title (slice 26, SW26) ----------------------------------------------------------------------

PROTOCOL = "SYNTHETIC irrigation scheduling of an open field crop: a study protocol"


# ---- a criterion with a comparator part (slice 28, D109) ----------------------------------------------------------


# ---- what each reading showed of the extracted text (audit item 3) --------------------------------

def long_pdf(doi, pages):
    return make_pdf([f"SYNTHETIC first page https://doi.org/{doi} irrigation scheduling of a greenhouse crop."]
                    + [f"SYNTHETIC page {n} on irrigation scheduling of a greenhouse crop." for n in range(2, pages + 1)])


def shown_pages(call):
    """The pages a reading call was shown. Passage ids are per-call handles in the input the model sees (D12)."""
    return {p["locator"]["physical_page"] for p in call["passages"]}


# ---- the second call is shown the parts the first did not see (D76) ------------------------------

def split_response(shared_parts=(), unseen_parts=()):
    """Run 1 finds nothing. Run 2 quotes, for each part index in `unseen_parts`, a page run 1 was not shown, and for
    each in `shared_parts`, a page run 1 was shown too; any other part it calls absent. Calls are sequential
    (concurrency 1), so run 1's pages are known when run 2 answers. SYNTHETIC."""
    state = {}

    def respond(si):
        if si["task_type"] != "fulltext_adjudication":
            return valid_response(si)
        by_page = {p["locator"]["physical_page"]: p for p in si["passages"]}
        if si["adjudication_target"]["run"] == 1:
            state["first"] = set(by_page)
            return absent_response(si)
        body = json.loads(absent_response(si))
        unseen = sorted(page for page in by_page if page not in state["first"])
        shared = sorted(page for page in by_page if page in state["first"])
        for index, part in enumerate(body["parts"]):
            pick = unseen[0] if index in unseen_parts else shared[0] if index in shared_parts else None
            if pick is not None:
                part.update(label="present", quote=by_page[pick]["text"][:60], passage_id=by_page[pick]["passage_id"])
        state["picked"] = {"unseen": unseen[0], "shared": shared[0]}
        return json.dumps(body)

    respond.state = state
    return respond


@pytest.mark.parametrize("legacy", [False])
def test_a_reading_paused_after_its_first_call_resumes_under_its_own_rule(tmp_path, monkeypatch, legacy):
    """Paused after call 1 and resumed: the run keeps the rule its budget froze. A legacy run sends the same list
    again and closes with both calls agreeing; a split run sends the other list and closes part by part."""
    if legacy:
        original = adjudication.read_budget
        monkeypatch.setattr(adjudication, "read_budget",
                            lambda effort: {k: v for k, v in original(effort).items() if k != "read_rule"})
    seen, holder = [], {}

    def before(si):
        if si["task_type"] != "fulltext_adjudication":
            return
        seen.append(si["step_input_id"])
        if len(seen) == 1:
            holder["store"].update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                       pause_reason="user_requested")

    responder = disagree_response if legacy else split_response(unseen_parts=(0, 1))
    works = [work(1, pdf_url="https://example.org/w1.pdf")]
    fetcher = Fetcher({"https://example.org/w1.pdf": ok(long_pdf("10.1/oa.1", 15))})
    adapter = FakeAdapter(responder, delay=0.02, before=before)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    client = client_of(app)
    try:
        store = holder["store"] = app.state.store
        rid, _, _, _ = discover(client)
        _, paused = wait_kind(client, rid, "fulltext_adjudication")
        paused_calls = len(adj_calls(adapter))
        client.post(f"/api/runs/{paused['id']}/resume")
        _, reading = wait(client, rid, paused["id"])
        plan = step_output(store, reading["id"], "adjudication_plan")
        read = plan["works"][0]["read_version"]
        calls = sorted(adj_calls(adapter, reading["id"]), key=lambda c: c["adjudication_target"]["run"])
        code = fulltext_code(store, rid, read)
        budget = store.run(reading["id"])["budget"]
    finally:
        client.__exit__(None, None, None)
    shown = [shown_pages(call) for call in calls]
    assert paused["status"] == "paused" and paused_calls == 1 and reading["status"] == "completed"
    assert len(calls) == 2 and budget.get("read_rule") == (None if legacy else "split_v1")
    assert plan.get("read_rule") == budget.get("read_rule")
    if legacy:
        assert shown[0] == shown[1] and code == "fulltext_runs_disagree"
    else:
        assert shown[0] != shown[1] and shown[0] | shown[1] == set(range(1, 16)) and code == "all_parts_verified"
