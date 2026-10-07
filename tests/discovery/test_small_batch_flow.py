"""Synthetic end-to-end D237 runs with isolated tmp_path data and mocked providers/PDFs."""

import asyncio
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
                              protocol_approval="as_proposed", fulltext_fetch=fetch,
                              fulltext_adjudication=reading, **settings),
                     adapters={"fake": adapter or FakeAdapter(valid_response)},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport or Transport(records))),
                     fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=start_worker)
    return app, fetcher


@pytest.mark.parametrize("n,expected,minimum", [(29, [29], False), (49, [40, 9], False),
                                             (50, [40, 10], True), (59, [40, 19], True), (60, [40, 20], True)])
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
        waiting = client.get(f"/api/researches/{rid}/waiting").json()
        assert waiting["order"] == "small_batch_plan" and waiting["has_plan"]
        assert [row["head"] for row in waiting["rows"]] == listing["order"]
        assert waiting["count"] == view["counts"]["waiting_for_pdf"] == n
        assert view["counts"]["flow"]["five"]["waiting_for_pdf"] == n
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
        assert [len(p["works"]) for p in reading] == [40, 10]
        assert run["usage"]["model_calls"] <= run["budget"]["max_model_calls"]
        assert run["inspection_progress"]["counts"]["blocked"] >= 10
        assert sum(len(p["works"]) for p in reading) == run["budget"]["inspection"]["read_limit"]


def test_model_abstracts_fill_twenty_candidate_calls(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        steps = small_batch.steps(app.state.store, run_id)
        stages = [s["output"] for s in steps if s["operation_key"].endswith(":abstract_stage")]
        assert [[len(b) for b in stage["batches"]] for stage in stages] == [[20, 20], [20]]
        assert len([s for s in steps if s["kind"] == "model:abstract_screening"]) == 6
        assert run["budget"]["inspection"]["runner_version"] == 4
        assert run["budget"]["inspection"]["batch_size"] == 40


def test_abstract_exclusions_count_without_pdf_calls(tmp_path, monkeypatch):
    app, fetcher = app_for(tmp_path, monkeypatch, 60, model_works=True,
                           adapter=FakeAdapter(responder("out_of_scope")))
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert run["inspection_progress"]["counts"]["processed"] == 60
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
        assert len(deferred) == 1 and len(deferred[0]["output"]["items"]) == 50
        assert sum(i["blocker"] == "budget_deferred" for i in run["inspection_progress"]["items"]) == 50


@pytest.mark.parametrize("version", [1, 2])
def test_old_frozen_run_budget_still_executes_thirty_work_plans(tmp_path, monkeypatch, version):
    original = small_batch.freeze_budget

    def legacy(*args):
        budget = original(*args)
        budget["inspection"].update(runner_version=version, batch_size=30)
        return budget

    monkeypatch.setattr(small_batch, "freeze_budget", legacy)
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed"
        stages = [s["output"] for s in small_batch.steps(app.state.store, run_id)
                  if s["operation_key"].endswith(":abstract_stage")]
        assert [[len(b) for b in s["batches"]] for s in stages] == [[20, 10], [20, 10]]


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
        assert len(output(app.state.store, run_id, "small_batch:v1:deferred")["items"]) == 50


@pytest.mark.parametrize("batch_size", [30, 40])
@pytest.mark.parametrize("read_groups", [0, 1])
def test_group_budget_stop_marks_all_unread_closes_step_and_defers_lookahead(tmp_path, monkeypatch, batch_size, read_groups):
    freeze = small_batch.freeze_budget
    prepare = small_batch.prepare_abstract_groups
    abstract = ResearchFlow._abstract_stage

    def budget(*args):
        result = freeze(*args)
        result["inspection"]["batch_size"] = batch_size
        return result

    def spend(flow, run):
        flow.store.conn.execute("UPDATE runs SET usage_json = ? WHERE id = ?",
                                (json.dumps({"model_calls": run["budget"]["max_model_calls"]}), run["id"]))

    def exhaust(flow, run, *args):
        result = prepare(flow, run, *args)
        if read_groups == 0:
            spend(flow, run)
        return result

    async def exhaust_after_group(flow, run, *args, **kwargs):
        await abstract(flow, run, *args, **kwargs)
        spend(flow, run)

    monkeypatch.setattr(small_batch, "freeze_budget", budget)
    monkeypatch.setattr(small_batch, "prepare_abstract_groups", exhaust)
    if read_groups:
        monkeypatch.setattr(ResearchFlow, "_abstract_stage", exhaust_after_group)
    app, fetcher = app_for(tmp_path, monkeypatch, 60, model_works=True, pdf=True,
                           adapter=FakeAdapter(responder("out_of_scope")))
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        store = app.state.store
        records = small_batch.steps(store, run_id)
        groups = next(s["output"]["groups"] for s in records if s["kind"] == "code:small_batch_abstract_groups")
        assert [len(g["sources"]) for g in groups] == [20, 20]
        for group in groups[read_groups:]:
            for svid in group["sources"]:
                row = store.conn.execute("SELECT reason_code FROM stage_decisions WHERE source_version_id = ?"
                                         " AND stage = 'abstract' AND superseded_at IS NULL", (svid,)).fetchone()
                assert row[0] == "abstract_not_read"
        stop = store.existing_step(run_id, f"{groups[read_groups]['key']}:abstract_stage")
        assert stop["status"] == "succeeded"
        assert stop["output"] == {"abstract_not_read": groups[read_groups]["sources"]}
        assert not [s for s in records if s["status"] == "pending"]
        assert sum(s["kind"] == "code:small_batch_plan" for s in records) == 1
        assert len(output(store, run_id, "small_batch:v1:deferred")["items"]) == 60 - batch_size
        if batch_size == 30:
            listing = output(store, run_id, small_batch.LIST_KEY)
            assert store.existing_step(run_id, f"small_batch:v1:{listing['manifest_hash']}:1:abstract_stage")
            assert not [s for s in records if ':1:adjudication_plan' in s['operation_key']]
        assert not fetcher.calls
        assert sum(s["kind"] == "model:abstract_screening" for s in records) == 2 * read_groups


def test_answer_api_freezes_discovery_policy_and_uses_that_input(tmp_path, monkeypatch):
    from test_fetch_overlap_flow import wait

    adapter = FakeAdapter(valid_response)
    app, _ = app_for(tmp_path, monkeypatch, 4, adapter=adapter)
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client, effort="standard")
        assert discovery["status"] == "completed", discovery
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, settled = wait(client, rid, answer["id"])
        assert settled["status"] == "completed", settled
        stored = app.state.store.run(answer["id"])
        assert small_batch.enabled(stored["budget"])
        allocation = output(app.state.store, answer["id"], "small_batch:v1:answer_input")
        assert stored["budget"]["inspection"]["list_run_id"] == discovery_id
        listing = output(app.state.store, discovery_id, small_batch.LIST_KEY)
        sent = next(c for c in adapter.calls if c["task_type"] == "grounded_answer")
        assert len(allocation["passage_ids"]) == 4
        assert [i["work_id"] for i in allocation["items"]] == [i["work_id"] for i in listing["items"]]
        assert len(sent["passages"]) == 4



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


def test_next_batch_abstract_and_fetch_overlap_previous_reading(tmp_path, monkeypatch):
    original_read = ResearchFlow._adjudication_call
    original_prepare = small_batch.execute_batch
    original_fetch = SlowFetcher.__call__
    release = started = None
    reading = next_started = False
    overlap = []
    active_fetch = peak_fetch = 0

    async def read(self, *args, **kwargs):
        nonlocal release, reading
        if release is None:
            release = asyncio.Event()
            reading = True
            started.set()
            try:
                # One real reading holds a model slot while the remaining slots
                # can finish this batch and screen the next one.
                await asyncio.wait_for(release.wait(), 5)
                return await original_read(self, *args, **kwargs)
            finally:
                reading = False
        return await original_read(self, *args, **kwargs)

    async def prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs):
        nonlocal next_started, started
        if plan["number"] == 0:
            started = asyncio.Event()
        if plan["number"] == 1:
            await asyncio.wait_for(started.wait(), 5)
            next_started = True
            assert reading
        return await original_prepare(flow, run, scope, vocabulary, listing, plan, key, **kwargs)

    async def fetch(self, url):
        nonlocal active_fetch, peak_fetch
        active_fetch += 1
        peak_fetch = max(peak_fetch, active_fetch)
        if next_started and reading:
            overlap.append("fetch")
            release.set()
        try:
            return await original_fetch(self, url)
        finally:
            active_fetch -= 1

    def before(si):
        if si["task_type"] == "abstract_screening" and next_started and reading:
            overlap.append("abstract")

    monkeypatch.setattr(ResearchFlow, "_adjudication_call", read)
    monkeypatch.setattr(small_batch, "execute_batch", prepare)
    monkeypatch.setattr(SlowFetcher, "__call__", fetch)
    adapter = FakeAdapter(valid_response, delay=0.002, before=before)
    app, fetcher = app_for(tmp_path, monkeypatch, 60, pdf=True, model_works=True, adapter=adapter)
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="standard")
        assert run["status"] == "completed", run
        assert set(overlap) == {"abstract", "fetch"}
        assert peak_fetch <= 4 and active_fetch == 0
        assert adapter.max_concurrent <= 6
        assert run["usage"]["model_calls"] <= run["budget"]["max_model_calls"]
        records = small_batch.steps(app.state.store, run_id)
        plans = sorted((s for s in records if s["kind"] == "code:small_batch_plan"),
                       key=lambda s: s["output"]["number"])
        assert [s["output"]["number"] for s in plans] == [0, 1]
        closes = [app.state.store.existing_step(run_id, s["operation_key"].removesuffix(":plan") + ":close")
                  for s in plans]
        assert plans[1]["started_at"] < closes[0]["finished_at"] < closes[1]["finished_at"]
        assert len(fetcher.calls) == len(set(fetcher.calls)) == 60
