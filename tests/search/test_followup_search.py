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
from overlap_flow_helpers import discover

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


