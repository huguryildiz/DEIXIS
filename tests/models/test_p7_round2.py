"""Synthetic native envelopes and run-scoped quota policy; no live error measurement."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from deixis.models.errors import limit_kind
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from test_codex_adapter_paths import codex
from test_p7_error_classification import test_model_limits as check_model_limits


def gemini_error(window):
    return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "message": "Quota exceeded for quota metric 'requests per " + window.lower() + "'",
                      "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                   "violations": [{"quotaId": "GenerateRequestsPer" + window}]}]}}


@pytest.mark.parametrize("connection,body,status,kind", [
    ("codex", {"codexErrorInfo": "usageLimitExceeded", "message": "SYNTHETIC"}, 429, "quota_exhausted"),
    ("claude", {"type": "billing_error", "message": "SYNTHETIC"}, 429, "quota_exhausted"),
    ("deepseek", {"error": {"message": "SYNTHETIC balance failure"}}, 402, "quota_exhausted"),
    ("gemini", gemini_error("Minute"), 429, "rate_limited"),
    ("gemini", gemini_error("Day"), 429, "quota_exhausted"),
])
def test_native_model_envelopes(connection, body, status, kind, monkeypatch, tmp_path, codex):
    # Shapes are grounded in the adapter's inspected fields and recorded decisions; values remain synthetic.
    check_model_limits(connection, body, {}, kind, monkeypatch, tmp_path, codex, http_status=status)


@pytest.mark.parametrize("text,expected", [
    ("Quota exceeded: PerMinute", "rate_limited"),
    ("Quota exceeded: PerSecond", "rate_limited"),
    ("Quota exceeded: per_minute", "rate_limited"),
    ("Quota exceeded: per second", "rate_limited"),
    ("Quota exceeded: PerDay and PerMinute", "quota_exhausted"),
    ("sleeper minute", None),
    ("quota exceeded", "quota_exhausted"),
])
def test_limit_window_precedence(text, expected):
    assert limit_kind(text=text) == expected


@pytest.mark.parametrize("window,expected", [("Minute", "rate_limited"), ("Second", "rate_limited"), ("Day", "quota_exhausted")])
def test_gemini_quota_id_without_window_in_message(window, expected):
    body = gemini_error(window)
    body["error"]["message"] = "Quota exceeded"
    assert limit_kind(body) == expected


@pytest.mark.parametrize("window,expected", [("Minute", "rate_limited"), ("Second", "rate_limited"), ("Day", "quota_exhausted")])
def test_gemini_quota_id_with_scope_suffix(window, expected):
    body = gemini_error(window)
    body["error"]["message"] = "Quota exceeded"
    body["error"]["details"][0]["violations"][0]["quotaId"] += "PerProjectPerModel"
    assert limit_kind(body) == expected


def test_codex_usage_limit_without_http_status():
    assert limit_kind({"codexErrorInfo": "usageLimitExceeded"}) == "quota_exhausted"


def test_provider_503_quota_wording_is_unknown_after_send():
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": "Quota exceeded per day"})))
    _, outcome = asyncio.run(common.send(client, "https://synthetic.invalid", {}, {}, "test", "keyless"))
    assert (outcome.status, outcome.delivery_class, outcome.error_kind) == ("failed", "after_send_unknown", None)


def test_limit_classifier_has_neutral_ownership():
    from deixis.domain.limits import http_limit, limit_kind as neutral
    from deixis.models import adapter, claude, deepseek, gemini
    assert common.limit_kind is neutral
    assert limit_kind is neutral
    assert adapter.limit_kind is neutral and claude.limit_kind is neutral
    assert deepseek.http_limit is http_limit and gemini.http_limit is http_limit
    assert neutral.__module__ == "deixis.domain.limits"


@pytest.fixture
def quota_flow(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "SYNTHETIC daily quota exhausted"})))
    deps = SimpleNamespace(store=store, http=client,
                           settings=SimpleNamespace(contact_email=None, payloads_dir=tmp_path / "payloads"))
    flow = ResearchFlow(deps)
    def new_run():
        rid = store.create_research("SYNTHETIC?", "academic", "standard", ["openalex"], "fake", "m", "en")
        return store.create_run(rid, "discovery", {"max_provider_requests": 10, "inspection": {"policy": "small_batch_fused_v1"}}, None)
    yield flow, new_run
    asyncio.run(client.aclose())
    if deps.http is not client:
        asyncio.run(deps.http.aclose())
    conn.close()


def connector(provider, calls, monkeypatch):
    async def search(http, *args, **kwargs):
        calls.append(provider)
        _, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        return outcome
    source = replace(CONNECTORS[provider], search=search, key_env=None, key_required=False)
    monkeypatch.setitem(CONNECTORS, provider, source)
    return source


def test_exhausted_provider_is_suppressed_only_in_its_run(quota_flow, monkeypatch):
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    first, other = connector("openalex", calls, monkeypatch), connector("crossref", calls, monkeypatch)
    async def exercise():
        await flow._send_search(run["id"], first, {"query_text": "one"}, 3)
        blocked = await flow._send_search(run["id"], first, {"query_text": "two"}, 3)
        assert (blocked.status, blocked.delivery_class, blocked.error_kind) == ("rate_limited", "before_send", "quota_exhausted")
        assert flow.store.run(run["id"])["usage"]["provider_requests"] == 1
        await flow._send_search(run["id"], other, {"query_text": "three"}, 3)
        await flow._send_search(new_run()["id"], first, {"query_text": "four"}, 3)
        restarted = ResearchFlow(flow.deps)
        await restarted._send_search(run["id"], first, {"query_text": "five"}, 3)
    asyncio.run(exercise())
    assert calls == ["openalex", "crossref", "openalex", "openalex"]


def test_execute_resets_quota_guard_on_same_flow(quota_flow, monkeypatch):
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    source = connector("openalex", calls, monkeypatch)

    async def execute_run(run_id):
        await flow._send_search(run_id, source, {"query_text": "one"}, 3)
        await flow._send_search(run_id, source, {"query_text": "two"}, 3)

    monkeypatch.setattr(flow, "_execute_run", execute_run)

    async def exercise():
        await flow.execute(run["id"])
        assert calls == ["openalex"]
        await flow.execute(run["id"])
        assert calls == ["openalex", "openalex"]
        assert flow.store.run(run["id"])["usage"]["provider_requests"] == 2

    asyncio.run(exercise())


def test_search_round_records_suppression_and_retry_sends_again(quota_flow, monkeypatch):
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    queries = [(index, {"provider_id": "openalex", "query_text": text})
               for index, text in enumerate(("one", "two"))]

    async def search(http, query, *args, **kwargs):
        calls.append(query)
        response, outcome = await common.send(http, "https://synthetic.invalid/search", {}, {}, "SYNTHETIC", "keyless")
        return replace(outcome, status="zero_results", delivery_class="answered") if response is not None else outcome

    flow.deps.http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "SYNTHETIC daily quota exhausted"})
        if len(calls) == 1 else httpx.Response(200, json={})))

    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], search=search, key_env=None))

    async def discovery(current, scope):
        await flow._search_round(current, queries, bool(current["budget"].get("retry_failed_searches_only")),
                                 "standard")
        flow.store.update_run(current["id"], event="run_completed", status="completed")

    monkeypatch.setattr(flow, "_discovery", discovery)

    async def exercise():
        await flow.execute(run["id"])
        assert calls == ["one"]
        first = flow.store.existing_step(run["id"], "search:0")
        second = flow.store.existing_step(run["id"], "search:1")
        assert first["status"] == second["status"] == "failed"
        assert second["delivery_class"] == "before_send"
        assert flow._query_requests(run["id"], "search:0") == 1
        assert flow._query_requests(run["id"], "search:1") == 0
        assert flow.store.run(run["id"])["usage"]["provider_requests"] == 1
        flow.store.queue_failed_search_retry(run["id"])
        await flow.execute(run["id"])
        assert calls == ["one", "one", "two"]
        assert flow._query_requests(run["id"], "search:0") == 2
        assert flow._query_requests(run["id"], "search:1") == 1
        assert all(flow.store.existing_step(run["id"], f"search:{index}")["status"] == "succeeded"
                   for index in (0, 1))

    asyncio.run(exercise())


def test_count_probe_obeys_search_quota_guard(quota_flow, monkeypatch):
    from deixis.workflow import flow as module
    flow, new_run = quota_flow
    run = new_run()
    calls = []
    source = connector("openalex", calls, monkeypatch)
    monkeypatch.setitem(module.CONNECTORS, "openalex", source)
    async def count(*args, **kwargs):
        calls.append("count")
        return 7
    monkeypatch.setattr(module.openalex, "count_works", count)
    async def exercise():
        probe = flow._count_probe({"providers": ["openalex"]}, run["id"])
        assert await probe("before") == 7
        await flow._send_search(run["id"], source, {"query_text": "one"}, 3)
        assert await probe("after") is None
        assert await flow._count_probe({"providers": ["openalex"]}, new_run()["id"])("new") == 7
    asyncio.run(exercise())
    assert calls == ["count", "openalex", "count"]


def test_recorded_search_and_pause_preserve_quota_kind(quota_flow):
    flow, new_run = quota_flow
    run = new_run()
    step = flow.store.step(run["id"], "quota-test", "provider_search:openalex")
    outcome = common.SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC", "keyless",
                                   http_status=429, error_kind="quota_exhausted")
    reason, detail = flow._record_search(run, step, {"provider_id": "openalex", "query_text": "one"}, outcome, 3)
    row = flow.store.conn.execute("SELECT error_json FROM search_runs WHERE run_id = ?", (run["id"],)).fetchone()
    assert json.loads(row[0])["error_kind"] == "quota_exhausted"
    assert reason == "provider_quota_exhausted" and detail["error_kind"] == "quota_exhausted"
