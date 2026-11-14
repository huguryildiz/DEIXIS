"""Synthetic end-to-end runs with isolated tmp_path data and mocked providers/PDFs."""

import asyncio
import json
from contextlib import contextmanager

import httpx
import pytest

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search import small_batch
from fakes import FakeAdapter, valid_response
from test_abstract_flow import ON_TOPIC, client_of as opened_client
from overlap_flow_helpers import discover, output, SlowFetcher
from test_fulltext_flow import Transport, work, named_pdf, ok


@contextmanager
def client_of(app):
    client = opened_client(app)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)


def app_for(tmp_path, monkeypatch, n=60, *, pdf=False, adapter=None, model_works=False,
            transport=None, plan_work=None, fetch="auto", reading="auto", start_worker=True, **settings):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    records = [work(i, title=ON_TOPIC if not model_works else "SYNTHETIC irrigation scheduling field crop",
                    pdf_url=f"https://example.org/w{i}.pdf" if pdf else None) for i in range(n)]
    fetcher = SlowFetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                           for i in range(n)} if pdf else {}, delay=0.002)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8877, fulltext_fetch=fetch,
                              fulltext_adjudication=reading, **settings),
                     adapters={"fake": adapter or FakeAdapter(valid_response)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport or Transport(records, plan_work=plan_work))),
                     fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=start_worker)
    return app, fetcher


@pytest.mark.parametrize("n,window,minimum", [(50, 50, True)])
def test_batch_runs_and_counts(tmp_path, monkeypatch, n, window, minimum):
    # One frozen read window of the list's first N (standard: 50) works; the tail stays pending.
    app, fetcher = app_for(tmp_path, monkeypatch, n)
    with client_of(app) as client:
        rid, run_id, view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        plans = [s["output"] for s in steps if s["kind"] == "code:small_batch_plan"]
        assert [len(p["work_ids"]) for p in plans] == [window]
        listing = output(app.state.store, run_id, small_batch.LIST_KEY)
        assert listing["automatic_order"] == small_batch.replay(listing["manifest"])["fused"]
        progress = run["inspection_progress"]
        assert progress["minimum_reached"] is minimum
        assert progress["counts"] == {"processed": window, "fulltext_adjudicated": 0,
                                      "included": 0, "blocked": 0, "pending": n - window}
        assert all(i["reason_code"] == "no_fulltext" for i in progress["items"] if i["processed"])
        waiting = client.get(f"/api/researches/{rid}/waiting").json()
        assert waiting["order"] == "small_batch_plan" and waiting["has_plan"]
        assert [row["head"] for row in waiting["rows"]] == listing["order"][:window]
        assert waiting["count"] == view["counts"]["waiting_for_pdf"] == window
        assert view["counts"]["flow"]["five"]["waiting_for_pdf"] == window
        assert len([r for r in view["runs"] if r["kind"] == "discovery"]) == 1
        assert not [r for r in view["runs"] if r["kind"] in ("fulltext_fetch", "fulltext_adjudication")]
        assert not fetcher.calls


def test_freeze_list_records_v3_maximum_version_counts_and_replays_without_store(tmp_path, monkeypatch):
    freeze = small_batch.freeze_list

    def with_counts(flow, run, scope, vocabulary):
        store = flow.store
        heads = sorted(store.work_heads(run["research_id"]).values())
        store.conn.execute("UPDATE source_versions SET cited_by_count = 0 WHERE id = ?", (heads[0],))
        store.conn.execute("UPDATE source_versions SET cited_by_count = 7 WHERE id = ?", (heads[1],))
        other = store.open_lookup_version(run["research_id"], heads[1], "accepted", "https://example.org/accepted")
        store.conn.execute("UPDATE source_versions SET cited_by_count = 23 WHERE id = ?", (other,))
        listing = freeze(flow, run, scope, vocabulary)
        manifest = listing["manifest"]
        assert "embedding_model" not in manifest and "similarities" not in manifest
        assert manifest["ranking_version"] == 3
        counts = {r["id"]: r["cited_by_count"] for r in manifest["pool"]}
        assert counts == {heads[0]: 0, heads[1]: 23, heads[2]: None}
        store.conn.execute("UPDATE source_versions SET cited_by_count = 999")
        assert small_batch.build_list(manifest) == listing
        assert freeze(flow, run, scope, vocabulary) == listing
        return listing

    monkeypatch.setattr(small_batch, "freeze_list", with_counts)
    app, _ = app_for(tmp_path, monkeypatch, 3, reading="off")
    with client_of(app) as client:
        _, _, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run


# ---- a run frozen under a rule this version no longer carries out ------------------------------------------------

def test_a_run_frozen_under_a_removed_rule_is_named_and_not_carried_out_under_todays():
    """Every frozen rule the code dropped stops its own kind of run, and a current policy passes the gate.

    A stored budget with no allocation version at all is one of those: it was written before the field existed, so
    its answer was laid out by a rule this version no longer has, and running it now would quietly lay it out by
    another one.
    """
    from deixis.workflow.run import fast_path

    def discovery(inspection=None, **fast):
        return {"kind": "discovery", "budget": {
            "fast_path": {"policy": fast_path.POLICY} | fast,
            "inspection": inspection or small_batch.freeze_budget(
                {"max_model_calls": 1, "max_provider_requests": 8}, "standard", "off")["inspection"]}}

    def answer(**inspection):
        return {"kind": "answer", "budget": {"inspection": {"policy": small_batch.POLICY} | inspection}}

    current = fast_path.freeze_budget({}, "standard")
    assert small_batch.removed_rule(discovery(**current)) is None
    assert small_batch.removed_rule(answer(answer_allocation_version=small_batch.ANSWER_ALLOCATION_VERSION)) is None
    # The search method's own runs froze no plan rule at all; a later rule that was itself dropped is named too.
    assert small_batch.removed_rule(discovery(chain_rule=fast_path.CHAIN_RULE)) == "search_method"
    assert small_batch.removed_rule(discovery(**current | {"plan_rule": "SYNTHETIC_older"})) == "plan_rule"
    assert small_batch.removed_rule(discovery(**current | {"chain_rule": "fast_chain_v1"})) == "chain_rule"
    per_depth = {key: value for key, value in current.items() if key != "uniform_search"}
    assert small_batch.removed_rule(discovery(**per_depth)) == "uniform_search"
    assert small_batch.removed_rule(discovery(**per_depth | {"plan_rule": "old"})) == "plan_rule"
    assert small_batch.removed_rule(discovery(**per_depth | {"chain_rule": "fast_chain_v1"})) == "chain_rule"
    assert small_batch.removed_rule(discovery(**current | {"phrase_search": {"rule": "phrase_search_v1"}})) == "phrase_search"
    inspection = small_batch.freeze_budget({"max_model_calls": 1, "max_provider_requests": 8}, "standard", "off")["inspection"]
    assert small_batch.removed_rule(discovery(inspection=inspection | {"rerank": {"version": 5}}, **current)) == "rerank_rule"
    assert small_batch.removed_rule(discovery(inspection=inspection | {"prerank_lookup": {"version": 4}},
                                              **current)) == "prerank_lookup"
    # Shared search needs every current discovery rule, including for a local model.
    for key, reason in (("phrase_forms_rule", "phrase_forms_rule"),
                        ("evidence_minimum", "evidence_minimum"),
                        ("window_word_rule", "window_word_rule"),
                        ("handover_rule", "handover_rule")):
        older = {name: value for name, value in current.items() if name != key}
        assert small_batch.removed_rule(discovery(**older)) == reason
    assert small_batch.removed_rule(discovery(**fast_path.freeze_budget({}, "standard", local_model=True))) is None
    assert small_batch.removed_rule(answer(answer_allocation_version=6)) == "answer_allocation"
    assert small_batch.removed_rule(answer()) == "answer_allocation"
    # A run of another kind, and a budget no fast path froze, are not this gate's business.
    assert small_batch.removed_rule({"kind": "followup_search", "budget": {"fast_path": {}}}) is None
    assert small_batch.removed_rule({"kind": "discovery", "budget": {}}) is None


def test_paused_per_depth_discovery_fails_before_provider_or_model_calls(tmp_path, monkeypatch):
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    from deixis.workflow.run import fast_path

    requests = []
    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, adapter=adapter, start_worker=False,
                     transport=lambda request: requests.append(request) or httpx.Response(500))
    with client_of(app):
        store = app.state.store
        rid = store.create_research("SYNTHETIC stored discovery", "academic", "standard", ["openalex"],
                                    "fake", "fake-model", "en")
        budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["standard"].__dict__, "standard", "off")
        policy = fast_path.freeze_budget(budget, "standard")
        policy.pop("uniform_search")  # a stored per-depth policy with current plan and chain rules
        budget["fast_path"] = policy
        run = store.create_run(rid, "discovery", budget, None)
        store.update_run(run["id"], status="paused", pause_reason="user_requested")
        store.resume_run(run["id"])
        asyncio.run(app.state.worker.flow.execute(run["id"]))
        failed = store.run(run["id"])
        assert failed["status"] == "failed" and failed["pause_reason"] == "search_rules_removed"
        assert failed["error"] == {"rule": "uniform_search"}
        assert requests == [] and adapter.calls == []


def test_completed_per_depth_research_keeps_its_stored_views_and_later_work(tmp_path, monkeypatch):
    from deixis.domain import canonical
    from deixis.workflow.read import background_fetch
    from test_followup_search import search as request_followup, turn_of, wait as wait_followup
    from test_screen_more import settle

    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True, fetch="off", reading="off")
    with client_of(app) as client:
        rid, discovery_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed"
        before = settle(client, rid)
        store = app.state.store
        listing = output(store, discovery_id, small_batch.LIST_KEY)
        assert listing and len(listing["order"]) > 50
        before_run = next(item for item in before["runs"] if item["id"] == discovery_id)

        # Store the shape of a completed Standard run with the former sub-topic and rerank rules.
        budget = store.run(discovery_id)["budget"]
        budget["fast_path"].pop("uniform_search")
        budget["fast_path"]["subtopic_search"] = {"rule": "subtopic_search_v1", "arm": "conditional", "records": 25}
        budget["inspection"]["rerank"]["version"] = 5
        store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(budget), discovery_id))
        listing["manifest"].pop("rerank_merge", None)
        (listing["manifest"].get("preselect") or {}).pop("fused_reserve", None)
        listing["manifest_hash"] = canonical.sha256_hex(listing["manifest"])
        store.conn.execute("UPDATE run_steps SET output_json = ? WHERE run_id = ? AND operation_key = ?",
                           (json.dumps(listing), discovery_id, small_batch.LIST_KEY))
        protocol = store.current_protocol(rid, 1)
        body = protocol["body"]
        plan = body["fast_path_search"]
        assert body["compiled_queries"]
        plan["subtopic"] = {"index": 0, "query": body["compiled_queries"][0], "provider_id": "scopus"}
        body["citation_chaining"]["attempt_limit"] = 23
        stored = store.freeze_protocol(rid, 1, body, reason="SYNTHETIC stored plan")
        store.conn.execute("UPDATE run_steps SET output_json = ? WHERE run_id = ? AND operation_key = 'protocol'",
                           (json.dumps({"protocol_revision": stored["protocol_revision"],
                                        "protocol_hash": stored["hash"]}), discovery_id))

        view = client.get(f"/api/researches/{rid}")
        assert view.status_code == 200, view.text
        shown = view.json()
        old_run = next(item for item in shown["runs"] if item["id"] == discovery_id)
        assert old_run["status"] == "completed" and old_run["error"] is None
        assert old_run["approval"]["chaining"]["attempt_limit"] == 23
        assert old_run["inspection_progress"]["counts"] == before_run["inspection_progress"]["counts"]
        assert shown["answers"] == before["answers"]
        saved_list = output(store, discovery_id, small_batch.LIST_KEY)
        assert saved_list["order"] == listing["order"]
        assert "rerank_merge" not in saved_list["manifest"]
        assert "fused_reserve" not in saved_list["manifest"]["preselect"]
        from deixis.workflow.search import search as fast_search
        assert any(item["arm"] == "subtopic" for item in fast_search.sent_plan(body))

        turn = turn_of(client, rid)
        followup = request_followup(client, rid, turn["id"])
        assert followup.status_code == 202, followup.text
        assert wait_followup(client, rid, followup.json()["search_run_id"])["status"] == "completed"
        settle(client, rid)

        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert answer.status_code == 202, answer.text
        settle(client, rid)
        screen = client.post(f"/api/researches/{rid}/screen-more")
        assert screen.status_code == 202, screen.text
        assert next(item for item in settle(client, rid)["runs"] if item["id"] == screen.json()["id"])["status"] == "completed"

        async def finish_fetch(run, work_id):
            step = store.step(run["id"], f"fulltext_work:{work_id}", "code:fulltext_work")
            store.start_step(step["id"])
            store.finish_step(step["id"], "succeeded", output={"code": "not_read_yet"})

        monkeypatch.setattr(app.state.worker.flow, "_overlap_work", finish_fetch)
        item = listing["items"][0]
        background_fetch.enqueue(store, store.run(discovery_id), item, "not_started")

        async def drain_fetch():
            lane = app.state.worker.flow.background_fetch
            lane.pick()
            await asyncio.gather(*lane.tasks.values())

        client.portal.call(drain_fetch)
        state = store.conn.execute("SELECT status FROM fast_path_background_fetches WHERE run_id = ?",
                                   (discovery_id,)).fetchone()[0]
        assert state == "succeeded"
