"""A follow-up's search for new works (D92). SYNTHETIC OpenAlex records and the fake model: these tests show the
workflow (the click queues one run, the request list is frozen before a send, requests are tagged by the run, the
first search's candidates keep their rank, the found works are split new / already here / removed before, the new
ones are screened and nothing is included, refusals, replay), not whether a model writes good terms or a provider
finds relevant works.
"""

import json
import time

from deixis.workflow import followup_search
from fakes import FakeAdapter, valid_response
from test_fulltext_flow import Transport, work
from test_screen_more import settle
from test_small_batch_flow import app_for, client_of
from test_fetch_overlap_flow import discover

QUESTION = "[new-works] Are there other studies on this that also report energy use?"


class Switch(Transport):
    """OpenAlex answers the discovery with the first set and, once switched, every later search with the second."""

    def __init__(self, first, second):
        super().__init__(first)
        self.second, self.later = second, []

    def switch(self):
        self.works = self.second

    def __call__(self, request):
        if self.works is self.second and request.url.host == "api.openalex.org":
            self.later.append(dict(request.url.params))
        return super().__call__(request)


def wait(client, rid, run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def revision(client, rid):
    return client.get(f"/api/researches/{rid}").json()["scope"]["revision"]


def turn_of(client, rid, question=QUESTION):
    response = client.post(f"/api/researches/{rid}/followup-turns",
                           json={"question": question, "expected_scope_revision": revision(client, rid)})
    assert response.status_code == 202, response.text
    turn = response.json()
    wait(client, rid, turn["run"]["id"])
    return client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()


def search(client, rid, turn_id, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/researches/{rid}/followup-turns/{turn_id}/search", headers=headers,
                       json={"expected_scope_revision": revision(client, rid)})


def setup(tmp_path, monkeypatch, adapter=None):
    first = [work(i) for i in range(30)]
    second = [work(i) for i in range(25, 30)] + [work(100 + i) for i in range(10)]
    transport = Switch(first, second)
    app, _ = app_for(tmp_path, monkeypatch, 30, model_works=True, transport=transport,
                     adapter=adapter or FakeAdapter(valid_response))
    return app, transport


def candidates_of(store, rid):
    return {r["source_version_id"]: (r["rank"], r["search_run_id"]) for r in store.conn.execute(
        "SELECT source_version_id, rank, search_run_id FROM candidates WHERE research_id = ?", (rid,))}


def test_a_click_searches_admits_and_screens_the_new_works_and_includes_nothing(tmp_path, monkeypatch):
    app, transport = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        store = app.state.store
        rid, discovery_id, _, run = discover(client, effort="quick")
        assert run["status"] == "completed", run
        settle(client, rid)
        turn = turn_of(client, rid)
        assert turn["status"] in followup_search.OFFERED_STATUSES
        # The model's flag only sets the emphasis; the click starts the search.
        assert turn["search"]["emphasis"] == "suggested" and turn["search"]["offered"] is True
        assert turn["search"]["runs"] == []
        before = candidates_of(store, rid)
        selection_revision = store.selection_revision(rid)
        included = store.included_works(rid)
        answers = store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0]
        transport.switch()

        response = search(client, rid, turn["id"], key="k1")
        assert response.status_code == 202, response.text
        run_id = response.json()["search_run_id"]
        assert wait(client, rid, run_id)["status"] == "completed"
        settle(client, rid)
        # The same key returns the same run; a second click without one is refused: the turn has searched.
        again = search(client, rid, turn["id"], key="k1")
        assert again.status_code == 202 and again.json()["search_run_id"] == run_id
        refused = search(client, rid, turn["id"])
        assert refused.status_code == 422 and refused.json()["code"] == "searched"

        run = store.run(run_id)
        assert run["kind"] == "followup_search" and run["target"]["turn_id"] == turn["id"]
        # The query step read the context card and the follow-up as its question; no record, no passage.
        (payload,) = [json.loads(r[0]) for r in store.conn.execute(
            "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " WHERE s.run_id = ? AND s.operation_key = ?", (run_id, followup_search.QUERY_KEY))]
        assert payload["task_type"] == "followup_search_query" and payload["question"]["text"] == QUESTION
        assert payload["sources"] == [] and payload["passages"] == []
        card = payload["followup_search_context"]
        assert card["searched_queries"] and card["included_works_total"] == len(card["included_works"])
        # The request list was frozen before any send, and every sent request is a search run of this run.
        plan = store.existing_step(run_id, followup_search.PLAN_KEY)["output"]
        assert plan["requests"][0]["endpoint"] == "semantic" and plan["requests"][0]["query_text"].startswith("[new-works]")
        rows = store.conn.execute("SELECT provider, result_count FROM search_runs WHERE run_id = ?", (run_id,)).fetchall()
        summary = store.existing_step(run_id, followup_search.SUMMARY_KEY)["output"]
        admitted = [r for r in summary["requests"] if r["admitted"]]
        # Only the mocked OpenAlex host answers here (bioRxiv is read through it): each answered request is one search
        # run of this run; the others failed with their reason and wrote no search run.
        assert {r["provider"] for r in rows} <= {"openalex", "biorxiv"} and all(r["result_count"] == 15 for r in rows)
        assert len(rows) == len(admitted) >= 2
        assert all(r["status"] != "succeeded" and r["reason"] for r in summary["requests"] if not r["admitted"])
        # The first search's candidates keep their rank and their search, found again or not.
        after = candidates_of(store, rid)
        assert {svid: after[svid] for svid in before} == before
        found = store.existing_step(run_id, followup_search.FOUND_KEY)["output"]
        assert found["counts"] == {"records": 15 * len(rows), "new": 10, "already_here": 5,
                                   "removed_before": 0}
        new = {w["work_id"] for w in found["works"] if w["state"] == "new"}
        screened = store.existing_step(run_id, followup_search.SCREEN_PLAN_KEY)["output"]
        assert {w["work_id"] for w in screened["planned"]} == new and screened["left_out"] == []
        assert summary["counts"]["screen_planned"] == 10
        assert summary["counts"]["sent_to_model"] + summary["counts"]["code_decided"] >= 10 - summary["counts"]["not_screened"]
        # Nothing is included, the selection did not move, and no answer was started.
        assert store.included_works(rid) == included and store.selection_revision(rid) == selection_revision
        assert store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0] == answers
        view = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["search"]
        assert view["offered"] is False and view["not_offered_reason"] == "searched"
        (shown,) = view["runs"]
        assert shown["status"] == "completed" and shown["summary"]["counts"]["new"] == 10


def test_a_follow_up_about_the_held_works_offers_a_quiet_search_and_a_revised_question_none(tmp_path, monkeypatch):
    app, _ = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        rid, _, _, run = discover(client, effort="quick")
        settle(client, rid)
        turn = turn_of(client, rid, "Which of these works reports the highest delivery ratio?")
        assert turn["search"]["emphasis"] == "quiet" and turn["search"]["offered"] is True
        stale = search(client, rid, turn["id"])
        assert stale.status_code == 202  # quiet is still a search the person may start
        store = app.state.store
        assert wait(client, rid, stale.json()["search_run_id"])["status"] in ("completed", "failed")
        assert store.run(stale.json()["search_run_id"])["kind"] == "followup_search"


def test_an_unknown_turn_or_an_old_revision_is_refused(tmp_path, monkeypatch):
    app, _ = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        rid, _, _, _ = discover(client, effort="quick")
        settle(client, rid)
        assert search(client, rid, "fut_missing").status_code == 404
        turn = turn_of(client, rid)
        wrong = client.post(f"/api/researches/{rid}/followup-turns/{turn['id']}/search",
                            json={"expected_scope_revision": revision(client, rid) + 1})
        assert wrong.status_code == 409


def heads_of(store, rid, numbers):
    """The current heads of the SYNTHETIC works with these OpenAlex numbers."""
    rows = store.conn.execute(
        "SELECT v.id, v.work_id FROM source_versions v JOIN identifier_mappings i ON i.source_version_id = v.id"
        " WHERE i.scheme = 'openalex' AND i.value IN ({})".format(",".join("?" * len(numbers))),
        tuple(f"W{n}" for n in numbers)).fetchall()
    heads = store.work_heads(rid)
    return sorted({heads[r["work_id"]] for r in rows if r["work_id"] in heads})


def test_a_work_the_person_removed_is_found_again_as_removed_and_is_not_screened(tmp_path, monkeypatch):
    app, transport = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        store = app.state.store
        rid, _, _, _ = discover(client, effort="quick")
        settle(client, rid)
        removed = heads_of(store, rid, [25, 26])
        assert len(removed) == 2
        response = client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": removed})
        assert response.status_code == 200, response.text
        turn = turn_of(client, rid)
        transport.switch()
        run_id = search(client, rid, turn["id"]).json()["search_run_id"]
        assert wait(client, rid, run_id)["status"] == "completed"
        settle(client, rid)
        found = store.existing_step(run_id, followup_search.FOUND_KEY)["output"]
        assert found["counts"]["new"] == 10 and found["counts"]["already_here"] == 3
        assert found["counts"]["removed_before"] == 2
        # Found again, a removed work stays removed (D50) and is never screened.
        assert all(store.conn.execute("SELECT removed_at FROM corpus_memberships WHERE research_id = ?"
                                      " AND source_version_id = ?", (rid, svid)).fetchone()[0] for svid in removed)
        planned = store.existing_step(run_id, followup_search.SCREEN_PLAN_KEY)["output"]["planned"]
        assert not {w["head"] for w in planned} & set(removed)


def test_a_spent_openalex_budget_sends_no_openalex_request_and_puts_no_other_provider_in_its_place(tmp_path, monkeypatch):
    app, transport = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        store = app.state.store
        rid, discovery_id, _, _ = discover(client, effort="quick")
        settle(client, rid)
        turn = turn_of(client, rid)
        with store.conn:
            store.note_openalex_budget(rid, discovery_id, "2999-01-01T00:00:00+00:00", skipped=True)
        transport.switch()
        run_id = search(client, rid, turn["id"]).json()["search_run_id"]
        run = wait(client, rid, run_id)
        summary = store.existing_step(run_id, followup_search.SUMMARY_KEY)["output"]
        # bioRxiv is searched through OpenAlex, so the spent budget closes it too; a request closed before sending is
        # not counted as sent.
        openalex = [r for r in summary["requests"] if r["provider_id"] in ("openalex", "biorxiv")]
        assert {r["provider_id"] for r in openalex} >= {"openalex"}
        assert all(r["reason"] == "openalex_budget_exhausted" and not r["admitted"] and not r["sent"] for r in openalex)
        assert store.conn.execute("SELECT COUNT(*) FROM search_runs WHERE run_id = ? AND provider IN ('openalex', 'biorxiv')",
                                  (run_id,)).fetchone()[0] == 0
        assert not any(params for params in transport.later)
        assert run["status"] in ("completed", "failed")


def test_an_invalid_query_fails_the_run_and_the_turn_offers_one_more_attempt(tmp_path, monkeypatch):
    def bad_terms(si):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "followup_search_query":
            draft["setting"] = [{"term": "a AND b", "kind": "topic", "why": "SYNTHETIC operator"}]
        return json.dumps(draft)

    adapter = FakeAdapter(bad_terms)
    app, transport = setup(tmp_path, monkeypatch, adapter)
    with client_of(app) as client:
        store = app.state.store
        rid, _, _, _ = discover(client, effort="quick")
        settle(client, rid)
        turn = turn_of(client, rid)
        transport.switch()
        first = search(client, rid, turn["id"]).json()["search_run_id"]
        run = wait(client, rid, first)
        assert run["status"] == "failed" and store.run(first)["pause_reason"] == "followup_query_invalid"
        # The call and its one repair; nothing was sent to a provider and nothing joined the research.
        assert store.conn.execute("SELECT COUNT(*) FROM search_runs WHERE run_id = ?", (first,)).fetchone()[0] == 0
        assert store.existing_step(first, followup_search.PLAN_KEY) is None
        view = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["search"]
        assert view["offered"] is True and view["attempt"] == 2 and view["runs"][0]["status"] == "failed"
        second = search(client, rid, turn["id"]).json()["search_run_id"]
        assert second != first and wait(client, rid, second)["status"] == "failed"
        refused = search(client, rid, turn["id"])
        assert refused.status_code == 422 and refused.json()["code"] == "attempts_used"


# ---- the run driven step by step ---------------------------------------------------------------------------------

def prepared(tmp_path, monkeypatch, responder=valid_response):
    """A settled discovery and a published turn written by the app, then a flow of the test's own over the same
    library (no worker), with OpenAlex answering the second set. Returns (harness, transport, rid, turn id)."""
    import asyncio  # noqa: F401  (the harness drives the flow with asyncio.run)
    from types import SimpleNamespace
    import httpx
    from deixis.config import Settings
    from deixis.domain import skill
    from deixis.storage import db
    from deixis.workflow.flow import FlowDeps, ResearchFlow
    from deixis.workflow.store import Store
    app, transport = setup(tmp_path, monkeypatch)
    with client_of(app) as client:
        rid, _, _, _ = discover(client, effort="quick")
        settle(client, rid)
        turn = turn_of(client, rid)
    transport.switch()
    store = Store(db.connect(tmp_path / "data" / "library.sqlite"))
    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8877), store, {"fake": adapter},
                                 skill.load_skill_package(), httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    return SimpleNamespace(store=store, flow=flow, adapter=adapter), transport, rid, turn["id"]


def queued(h, rid, turn_id):
    return followup_search.request(h.store, rid, turn_id, h.store.research(rid)["current_scope_revision"], None)


def run_it(h, run_id):
    import asyncio
    h.store.update_run(run_id, status="running")
    asyncio.run(h.flow.execute(run_id))
    return h.store.run(run_id)


def set_target(h, run_id, **fields):
    run = h.store.run(run_id)
    with h.store.conn:
        h.store.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?", (json.dumps(run["target"] | fields), run_id))


def abstract_decisions(h, run_id):
    return h.store.conn.execute(
        "SELECT COUNT(*) FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id WHERE s.run_id = ?",
        (run_id,)).fetchone()[0]


def test_a_changed_criterion_stops_the_run_before_any_call(tmp_path, monkeypatch):
    h, transport, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    set_target(h, run["id"], criterion_hash="SYNTHETIC other criterion")
    sent = len(transport.later)
    run = run_it(h, run["id"])
    assert run["status"] == "failed" and run["pause_reason"] == "criterion_changed"
    assert h.adapter.calls == [] and len(transport.later) == sent


def test_a_criterion_changed_at_a_batch_close_writes_no_decision_and_the_run_stays_failed(tmp_path, monkeypatch):
    h, _, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    set_target(h, run["id"], criterion_hash="SYNTHETIC other criterion")
    # Only the batch close looks: the checkpoint gate is left out so the run reaches its screening.
    monkeypatch.setattr(followup_search, "_criterion_gate", lambda flow, run: None)
    run = run_it(h, run["id"])
    assert run["status"] == "failed" and run["pause_reason"] == "criterion_changed"
    assert h.store.existing_step(run["id"], followup_search.SCREEN_PLAN_KEY)["output"]["planned"]
    assert abstract_decisions(h, run["id"]) == 0
    assert h.store.run(run["id"])["status"] == "failed"


def test_the_query_ceiling_holds_and_its_repair_is_never_sent_past_it(tmp_path, monkeypatch):
    def bad(si):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "followup_search_query":
            draft["task"] = []
        return json.dumps(draft)

    h, _, rid, turn_id = prepared(tmp_path, monkeypatch, bad)
    run = queued(h, rid, turn_id)
    budget = run["budget"] | {"followup_search": run["budget"]["followup_search"] | {"query_calls": 1}}
    with h.store.conn:
        h.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(budget), run["id"]))
    run = run_it(h, run["id"])
    assert run["status"] == "failed" and run["pause_reason"] == "followup_query_budget"
    assert len(h.adapter.calls) == 1 and h.store.run(run["id"])["usage"]["model_calls"] == 1


def test_a_send_whose_delivery_is_unknown_is_never_sent_again(tmp_path, monkeypatch):
    import asyncio
    h, transport, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    step = h.store.step(run["id"], followup_search.search_key(1), "provider_search:openalex")
    h.store.start_step(step["id"])  # the worker died with the request out
    h.store.update_run(run["id"], status="running")
    sent = len(transport.later)
    request_ = {"provider_id": "openalex", "endpoint": "semantic", "query_text": "SYNTHETIC", "limit": 50}
    result = asyncio.run(followup_search._send(h.flow, h.store.run(run["id"]), 1, request_))
    assert result["status"] == "outcome_unknown" and len(transport.later) == sent
    # The step names its frozen request, so the PRISMA-S export reads it without the summary step.
    assert result["output"]["query_text"] == "SYNTHETIC" and result["output"]["endpoint"] == "semantic"


def test_a_pause_between_send_and_admission_admits_the_stored_records_on_resume_without_a_resend(tmp_path, monkeypatch):
    h, transport, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    original = followup_search._send

    async def then_pause(flow, run_, position, request_):
        step = await original(flow, run_, position, request_)
        if position == 1:
            flow.store.update_run(run_["id"], status="pause_requested")
        return step
    monkeypatch.setattr(followup_search, "_send", then_pause)
    run = run_it(h, run["id"])
    assert run["status"] == "paused"
    assert h.store.existing_step(run["id"], followup_search.search_key(1))["status"] == "succeeded"
    assert h.store.existing_step(run["id"], followup_search.admit_key(1)) is None or \
        h.store.existing_step(run["id"], followup_search.admit_key(1))["status"] != "succeeded"
    sent = len(transport.later)
    monkeypatch.setattr(followup_search, "_send", original)
    run = run_it(h, run["id"])
    assert run["status"] == "completed"
    assert h.store.existing_step(run["id"], followup_search.admit_key(1))["status"] == "succeeded"
    plan = h.store.existing_step(run["id"], followup_search.PLAN_KEY)["output"]
    # Only the requests not sent before the pause went out on resume.
    assert len(transport.later) - sent <= len(plan["requests"]) - 1


def test_a_new_version_a_later_link_joins_to_a_removed_work_stays_removed(tmp_path, monkeypatch):
    h, _, rid, turn_id = prepared(tmp_path, monkeypatch)
    removed = heads_of(h.store, rid, [0])
    h.store.remove_sources(rid, removed, "SYNTHETIC off topic")
    run = run_it(h, queued(h, rid, turn_id)["id"])
    assert run["status"] == "completed"
    plan = h.store.existing_step(run["id"], followup_search.PLAN_KEY)["output"]
    created = [svid for p in range(1, len(plan["requests"]) + 1)
               for svid in (h.store.existing_step(run["id"], followup_search.admit_key(p)) or {"output": {}})["output"].get("created_memberships", [])]
    joined = created[0]
    # A record link joins the new version to the work the person removed (as a later admission's links can).
    with h.store.conn:
        h.store.conn.execute("UPDATE source_versions SET work_id = (SELECT work_id FROM source_versions WHERE id = ?) WHERE id = ?",
                             (removed[0], joined))
        followup_search._keep_removed(h.store, run, len(plan["requests"]) + 1, [])
    assert h.store.conn.execute("SELECT removed_at FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?",
                                (rid, joined)).fetchone()[0]
    work = h.store.source(joined)["work_id"]
    assert work not in h.store.work_heads(rid)
    states = {w["work_id"]: w["state"] for w in followup_search._classify(h.store.conn, rid, run["id"])["works"]}
    assert states[work] == "removed_before"


def test_a_run_stopped_after_an_admission_counts_what_it_added_apart_from_the_first_search(tmp_path, monkeypatch):
    from deixis.workflow import flow_counts
    h, _, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    original = followup_search._admit

    def then_cancel(flow, run_, position, request_, sent):
        output = original(flow, run_, position, request_, sent)
        if output.get("created_memberships"):
            flow.store.update_run(run_["id"], status="pause_requested")
        return output
    monkeypatch.setattr(followup_search, "_admit", then_cancel)
    run = run_it(h, run["id"])
    assert run["status"] == "paused" and h.store.existing_step(run["id"], followup_search.FOUND_KEY) is None
    entry = next(r for r in flow_counts.followup_runs(h.store.conn, rid) if r["run_id"] == run["id"])
    assert entry["found_partial"] and entry["found"]["counts"]["new"] > 0
    new = {w["work_id"] for w in entry["found"]["works"] if w["state"] == "new"}
    work_of = h.store.work_ids([v for w in entry["found"]["works"] for v in w["versions"]])
    assert new <= flow_counts.followup_only_works(h.store.conn, rid, run["scope_revision"], work_of, set())
    # Frozen at the admission: a later merge of a held version into a new work does not turn it into a held one.
    held = heads_of(h.store, rid, [1])[0]
    work = sorted(new)[0]
    with h.store.conn:
        h.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work, held))
    assert followup_search._classify(h.store.conn, rid, run["id"])["counts"]["new"] < entry["found"]["counts"]["new"]
    assert followup_search.found_from(h.store.conn, rid, run["id"]) == entry["found"]


def test_a_version_another_run_added_while_this_one_was_paused_is_not_held_before(tmp_path, monkeypatch):
    h, _, rid, turn_id = prepared(tmp_path, monkeypatch)
    run = queued(h, rid, turn_id)
    original = followup_search._admit

    def then_pause(flow, run_, position, request_, sent):
        output = original(flow, run_, position, request_, sent)
        if output.get("created_memberships"):
            flow.store.update_run(run_["id"], status="pause_requested")
        return output
    monkeypatch.setattr(followup_search, "_admit", then_pause)
    run = run_it(h, run["id"])
    assert run["status"] == "paused"
    frozen = followup_search.found_from(h.store.conn, rid, run["id"])
    work = next(w["work_id"] for w in frozen["works"] if w["state"] == "new")
    # While it is paused another run adds a second version of that work to the research (a preprint, say).
    source = dict(h.store.conn.execute("SELECT * FROM source_versions WHERE work_id = ? LIMIT 1", (work,)).fetchone())
    with h.store.conn:
        h.store.conn.execute(f"INSERT INTO source_versions ({', '.join(source)}) VALUES ({', '.join('?' * len(source))})",
                             tuple((source | {"id": "src_SYNTHPREPRINT"}).values()))
        h.store.add_to_corpus(rid, "src_SYNTHPREPRINT", "library", candidate=False)
    monkeypatch.setattr(followup_search, "_admit", original)
    run = run_it(h, run["id"])
    assert run["status"] == "completed"
    found = h.store.existing_step(run["id"], followup_search.FOUND_KEY)["output"]
    assert {w["work_id"]: w["state"] for w in found["works"]}[work] == "new"
