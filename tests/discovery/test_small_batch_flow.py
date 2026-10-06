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


def app_for(tmp_path, monkeypatch, n=60, *, pdf=False, flag="on", adapter=None, model_works=False,
            transport=None, fetch="auto", reading="auto", start_worker=True, **settings):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    records = [work(i, title=ON_TOPIC if not model_works else "SYNTHETIC irrigation scheduling field crop",
                    pdf_url=f"https://example.org/w{i}.pdf" if pdf else None) for i in range(n)]
    fetcher = SlowFetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                           for i in range(n)} if pdf else {}, delay=0.002)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8877, search_query="code",
                              protocol_approval="as_proposed", fulltext_fetch=fetch,
                              fulltext_adjudication=reading, small_batch_inspection=flag, **settings),
                     adapters={"fake": adapter or FakeAdapter(valid_response)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport or Transport(records))),
                     fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=start_worker)
    return app, fetcher


@pytest.mark.parametrize("n,expected,minimum", [(29, [29], False), (49, [30, 19], False),
                                             (50, [30, 20], True), (59, [30, 29], True), (60, [30, 30], True)])
def test_batch_runs_and_counts(tmp_path, monkeypatch, n, expected, minimum):
    app, fetcher = app_for(tmp_path, monkeypatch, n)
    with client_of(app) as client:
        rid, run_id, view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        plans = [s["output"] for s in steps if s["kind"] == "code:small_batch_plan"]
        assert [len(p["work_ids"]) for p in plans] == expected
        listing = output(app.state.store, run_id, small_batch.LIST_KEY)
        assert listing["automatic_order"] == small_batch.replay(listing["manifest"])["fused"]
        progress = run["inspection_progress"]
        assert progress["minimum_reached"] is minimum
        assert progress["counts"] == {"processed": n, "fulltext_adjudicated": 0,
                                      "included": 0, "blocked": 0, "pending": 0}
        assert all(i["reason_code"] == "no_fulltext" for i in progress["items"])
        assert len([r for r in view["runs"] if r["kind"] == "discovery"]) == 1
        assert not [r for r in view["runs"] if r["kind"] in ("fulltext_fetch", "fulltext_adjudication")]
        assert not fetcher.calls


def test_read_limit_and_whole_pipeline_budget_are_shared(tmp_path, monkeypatch):
    app, fetcher = app_for(tmp_path, monkeypatch, 60, pdf=True)
    with client_of(app) as client:
        rid, run_id, view, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        store = app.state.store
        assert len(fetcher.calls) == 60
        reading = [s["output"] for s in small_batch.steps(store, run_id) if s["kind"] == "code:adjudication_plan"]
        assert [len(p["works"]) for p in reading] == [30, 20]
        assert run["usage"]["model_calls"] <= run["budget"]["max_model_calls"]
        assert run["inspection_progress"]["counts"]["blocked"] >= 10
        assert sum(len(p["works"]) for p in reading) == run["budget"]["inspection"]["read_limit"]


def test_model_abstracts_use_20_plus_10_twice_before_next_batch(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        stages = [s["output"] for s in steps if s["operation_key"].endswith(":abstract_stage")]
        assert [[len(b) for b in stage["batches"]] for stage in stages] == [[20, 10], [20, 10]]
        assert len([s for s in steps if s["kind"] == "model:abstract_screening"]) == 8


def test_abstract_exclusions_count_without_pdf_calls(tmp_path, monkeypatch):
    app, fetcher = app_for(tmp_path, monkeypatch, 60, model_works=True,
                           adapter=FakeAdapter(responder("out_of_scope")))
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert run["inspection_progress"]["counts"]["processed"] == 60
        assert not work_steps(app.state.store, run_id)
        assert not fetcher.calls


def test_flag_off_has_old_steps_and_no_inspection_policy(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 4, flag="off")
    with client_of(app) as client:
        _, run_id, _, run = discover(client)
        assert "inspection" not in run["budget"]
        assert "inspection_progress" not in run
        assert output(app.state.store, run_id, small_batch.LIST_KEY) is None
        assert output(app.state.store, run_id, "abstract_stage")


def test_default_flag_off_and_invalid_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEIXIS_SMALL_BATCH_INSPECTION", raising=False)
    assert Settings(data_dir=tmp_path).small_batch_inspection == "off"
    assert load_settings().small_batch_inspection == "off"
    monkeypatch.setenv("DEIXIS_SMALL_BATCH_INSPECTION", "yes")
    with pytest.raises(ValueError, match="DEIXIS_SMALL_BATCH_INSPECTION"):
        load_settings()


def test_abstract_budget_defers_tail_in_one_step_without_more_batch_scans(tmp_path, monkeypatch):
    original = small_batch.freeze_budget

    def limited(*args):
        budget = original(*args)
        budget["inspection"]["abstract_limit"] = 30
        return budget

    monkeypatch.setattr(small_batch, "freeze_budget", limited)
    app, _ = app_for(tmp_path, monkeypatch, 90, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        assert sum(s["kind"] == "code:small_batch_plan" for s in steps) == 1
        deferred = [s for s in steps if s["kind"] == "code:small_batch_deferred"]
        assert len(deferred) == 1 and len(deferred[0]["output"]["items"]) == 60
        assert sum(i["blocker"] == "budget_deferred" for i in run["inspection_progress"]["items"]) == 60


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


def test_total_model_budget_defers_new_batches_even_with_abstract_room(tmp_path, monkeypatch):
    original = small_batch.save_code

    def exhaust(flow, run, key, kind, build):
        result = original(flow, run, key, kind, build)
        if kind == "code:small_batch_close":
            flow.store.conn.execute("UPDATE runs SET usage_json = ? WHERE id = ?",
                                    (json.dumps({"model_calls": run["budget"]["max_model_calls"]}), run["id"]))
        return result

    monkeypatch.setattr(small_batch, "save_code", exhaust)
    app, _ = app_for(tmp_path, monkeypatch, 90)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        assert sum(s["kind"] == "code:small_batch_plan" for s in steps) == 1
        assert len(output(app.state.store, run_id, "small_batch:v1:deferred")["items"]) == 60


@pytest.mark.parametrize("flag", ["on", "off"])
def test_answer_api_freezes_discovery_policy_and_uses_that_input(tmp_path, monkeypatch, flag):
    from test_fetch_overlap_flow import wait

    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, 4, flag=flag, adapter=adapter)
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client, effort="standard")
        assert discovery["status"] == "completed", discovery
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, settled = wait(client, rid, answer["id"])
        assert settled["status"] == "completed", settled
        stored = app.state.store.run(answer["id"])
        assert small_batch.enabled(stored["budget"]) is (flag == "on")
        allocation = output(app.state.store, answer["id"], "small_batch:v1:answer_input")
        if flag == "on":
            assert stored["budget"]["inspection"]["list_run_id"] == discovery_id
            listing = output(app.state.store, discovery_id, small_batch.LIST_KEY)
            sent = next(c for c in adapter.calls if c["task_type"] == "grounded_answer")
            assert len(allocation["passage_ids"]) == 4
            assert [i["work_id"] for i in allocation["items"]] == [i["work_id"] for i in listing["items"]]
            assert len(sent["passages"]) == 4
        else:
            assert allocation is None


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


def test_chain_retrieval_finishes_before_model_abstracts_and_deduplicates_works(tmp_path, monkeypatch):
    from test_chaining_flow import OpenAlex, work as chain_work

    transport = OpenAlex([chain_work(i, references=[101]) for i in range(16)],
                         citing={"W0": [chain_work(101), chain_work(0)]}, by_id={"W101": chain_work(101)})
    seen = []

    def before(si):
        if si["task_type"] == "abstract_screening":
            assert transport.chain
            seen.append(len(transport.chain))

    app, _ = app_for(tmp_path, monkeypatch, 16, transport=transport,
                     citation_chaining="auto", adapter=FakeAdapter(valid_response, before=before))
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        listing = output(app.state.store, run_id, small_batch.LIST_KEY)
        assert len(listing["items"]) == len({i["work_id"] for i in listing["items"]}) == 17
        assert seen and set(seen) == {len(transport.chain)}
        assert not output(app.state.store, run_id, "chain_abstract_stage")
        assert len(output(app.state.store, run_id, "chain_seeds")["seeds"]) == 15


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


def test_code_candidates_fetch_before_abstract_models_finish_with_four_in_flight(tmp_path, monkeypatch):
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
        assert maximum <= 4 and active == 0
        assert len(fetcher.calls) == len(set(fetcher.calls)) == 30
