"""Synthetic end-to-end D237 runs with isolated tmp_path data and mocked providers/PDFs."""

import json
from contextlib import contextmanager

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings, load_settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow import small_batch
from deixis.workflow.flow import ResearchFlow
from fakes import FakeAdapter, valid_response
from test_abstract_flow import QUESTION, ON_TOPIC, client_of as opened_client, responder
from test_fetch_overlap_flow import discover, output, SlowFetcher, work_steps
from test_fulltext_flow import Transport, work, named_pdf, ok


@contextmanager
def client_of(app):
    client = opened_client(app)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)


def app_for(tmp_path, monkeypatch, n=60, *, pdf=False, adapter=None, model_works=False,
            transport=None, fetch="auto", reading="auto", search_query="code", start_worker=True, **settings):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    records = [work(i, title=ON_TOPIC if not model_works else "SYNTHETIC irrigation scheduling field crop",
                    pdf_url=f"https://example.org/w{i}.pdf" if pdf else None) for i in range(n)]
    fetcher = SlowFetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                           for i in range(n)} if pdf else {}, delay=0.002)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8877, search_query=search_query,
                              fulltext_fetch=fetch,
                              fulltext_adjudication=reading, **settings),
                     adapters={"fake": adapter or FakeAdapter(valid_response)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport or Transport(records))),
                     fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=start_worker)
    return app, fetcher


@pytest.mark.parametrize("n,window,minimum", [(29, 29, False), (49, 49, False), (50, 50, True), (60, 50, True)])
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


def test_model_abstracts_fill_twenty_candidate_calls(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        stages = [s["output"] for s in steps if s["operation_key"].endswith(":abstract_stage")]
        # The read window's N (standard: 50) works, in calls of at most 20 candidates, each read twice.
        assert [[len(b) for b in stage["batches"]] for stage in stages] == [[20, 20, 10]]
        assert len([s for s in steps if s["kind"] == "model:abstract_screening"]) == 6


def test_abstract_exclusions_count_without_pdf_calls(tmp_path, monkeypatch):
    app, fetcher = app_for(tmp_path, monkeypatch, 60, model_works=True,
                           adapter=FakeAdapter(responder("out_of_scope")))
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        # The read window's N (standard: 50) works are screened out; the list's tail stays pending.
        assert run["inspection_progress"]["counts"]["processed"] == run["budget"]["fast_path"]["N"] == 50
        assert not work_steps(app.state.store, run_id)
        assert not fetcher.calls







def test_legacy_frozen_budget_exposes_only_discovery_allowance():
    budget = small_batch.freeze_budget({"max_model_calls": 40, "fulltext_fetch": {"max_fulltext_works": 100}},
                                      "standard", "auto")
    assert budget["max_model_calls"] == 140
    del budget["inspection"]["discovery_model_calls"]
    assert small_batch.model_call_allowance(budget) == 40
    assert small_batch.model_call_allowance({"max_model_calls": 40}) == 40


@pytest.mark.parametrize("obsolete", ["off", "on", "yes"])
def test_obsolete_flag_cannot_change_product_policy(monkeypatch, tmp_path, obsolete):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEIXIS_SMALL_BATCH_INSPECTION", obsolete)
    assert not hasattr(Settings(data_dir=tmp_path), "small_batch_inspection")
    assert not hasattr(load_settings(), "small_batch_inspection")









def test_unexpected_model_error_does_not_fetch_unscreened_work(tmp_path, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("SYNTHETIC abstract arm failure")

    monkeypatch.setattr(ResearchFlow, "_abstract_stage", broken)
    app, fetcher = app_for(tmp_path, monkeypatch, 30, pdf=True, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "failed", run
        assert not fetcher.calls
        assert not work_steps(app.state.store, run_id)


def test_flagged_answer_without_eligible_work_records_no_evidence(tmp_path, monkeypatch):
    from test_fetch_overlap_flow import wait

    adapter = FakeAdapter(responder("out_of_scope"))
    app, _ = app_for(tmp_path, monkeypatch, 4, model_works=True, adapter=adapter)
    with client_of(app) as client:
        rid, _, _, discovery = discover(client, effort="standard")
        assert discovery["status"] == "completed", discovery
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, settled = wait(client, rid, answer["id"])
        assert settled["status"] == "completed", settled
        assert app.state.store.conn.execute("SELECT status FROM answers WHERE run_id = ?",
                                            (answer["id"],)).fetchone()[0] == "no_evidence"
        assert not any(call["task_type"] == "grounded_answer" for call in adapter.calls)


def test_unverified_fulltext_quotes_remain_human_blockers(tmp_path, monkeypatch):
    def bad_quote(si):
        result = json.loads(valid_response(si))
        if si["task_type"] == "fulltext_adjudication":
            for part in result["parts"]:
                part["quote"] = "SYNTHETIC invented quotation absent from the stored source text."
        return json.dumps(result)

    app, _ = app_for(tmp_path, monkeypatch, 3, pdf=True, adapter=FakeAdapter(bad_quote))
    with client_of(app) as client:
        _, _, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        progress = run["inspection_progress"]
        assert progress["counts"]["included"] == progress["counts"]["processed"] == 0
        assert progress["counts"]["blocked"] == progress["counts"]["fulltext_adjudicated"] == 3
        assert {i["blocker"] for i in progress["items"]} == {"human_pending"}


def test_code_candidates_fetch_before_abstract_models_finish_within_the_fetch_slots(tmp_path, monkeypatch):
    records = [work(i, title=ON_TOPIC if i < 6 else "SYNTHETIC irrigation scheduling field crop",
                    pdf_url=f"https://example.org/w{i}.pdf") for i in range(30)]
    adapter = FakeAdapter(valid_response, delay=0.05)
    app, fetcher = app_for(tmp_path, monkeypatch, 30, pdf=True, transport=Transport(records), adapter=adapter)
    active = maximum = 0
    early = []
    original = SlowFetcher.__call__

    async def tracked(self, url):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        if len(calls) < 4 or adapter.current:
            early.append(url)
        try:
            return await original(self, url)
        finally:
            active -= 1

    monkeypatch.setattr(SlowFetcher, "__call__", tracked)
    with client_of(app) as client:
        _, _, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert early
        assert maximum <= run["budget"]["fast_path"]["fetch_slots"] and active == 0
        # The fast read fetches its frozen K works (standard: 20), each once.
        assert len(fetcher.calls) == len(set(fetcher.calls)) == run["budget"]["fast_path"]["K"]
