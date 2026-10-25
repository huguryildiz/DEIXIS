"""Usage, budget and activity routes: model sessions and provider headers read from stored rows.

SYNTHETIC sessions and headers written through the store; no model, no live provider. Passing shows the routes count
what is stored and invent no figure; it says nothing about how the page draws them.
"""

import httpx
import json
import pytest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from fastapi.testclient import TestClient

from deixis.api import usage_routes
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers import openalex
from fakes import FakeAdapter


UTC = timezone.utc


@pytest.fixture
def served(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))), start_worker=False,
        extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    try:
        yield app.state.store, client
    finally:
        client.__exit__(None, None, None)


def call(store, rid, run, task_type, started_at=None, n=[0]):
    """One stored model session for `task_type`; `started_at` moves it in time."""
    n[0] += 1
    step = store.step(run["id"], f"{task_type}:{n[0]}", f"model:{task_type}")
    sid = f"sti_{n[0]}"
    store.insert_step_input(step["id"], rid, run["id"], 0, {"step_input_id": sid, "task_type": task_type,
                            "scope_revision": 1, "skill_package_hash": "pkg"}, "b", "d", "m", {})
    session = store.start_model_session(rid, run["id"], step["id"], sid, "fake", "fake-model")
    if started_at is not None:
        store.conn.execute("UPDATE model_sessions SET started_at = ? WHERE id = ?", (usage_routes.iso(started_at), session))
    return session


def research(store):
    rid = store.create_research("SYNTHETIC usage question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    return rid, store.create_run(rid, "discovery", {}, None)


def test_usage_groups_task_types_by_role_in_settings_order_and_shares_sum_to_one():
    result = usage_routes.usage({"grounded_answer": 3, "report_section": 1, "abstract_screening": 4, "search_query": 1,
                                 "fulltext_adjudication": 1, "answer_review": 2})
    assert result["total"] == 12
    assert [(r["role"], r["calls"]) for r in result["roles"]] == [("answer", 4), ("literature", 6), ("reviewer", 2)]
    assert sum(r["share"] for r in result["roles"]) == pytest.approx(1.0)


def test_the_month_route_counts_sessions_inside_the_window_and_none_outside(served):
    store, client = served
    rid, run = research(store)
    since, until = usage_routes.month_window(datetime.now(UTC))
    start, end = datetime.fromisoformat(since), datetime.fromisoformat(until)
    call(store, rid, run, "grounded_answer", start)                                # first instant: counted
    call(store, rid, run, "abstract_screening", start + timedelta(days=3))
    call(store, rid, run, "abstract_screening", start + timedelta(days=4))
    call(store, rid, run, "answer_review", end - timedelta(milliseconds=1))        # last instant: counted
    call(store, rid, run, "grounded_answer", start - timedelta(milliseconds=1))    # last month
    call(store, rid, run, "search_query", end)                                     # next month
    body = client.get("/api/usage?period=month").json()
    assert body["period"] == "month" and (body["since"], body["until"]) == (since, until)
    assert body["total"] == 4
    assert {r["role"]: r["calls"] for r in body["roles"]} == {"answer": 1, "literature": 2, "reviewer": 1}
    assert next(r for r in body["roles"] if r["role"] == "literature")["share"] == 0.5
    assert client.get("/api/usage").json()["total"] == 4  # month is the default


NOON = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def row(minutes_before, headers=None, *, at=NOON):
    """A stored OpenAlex search row: its time and an error_json whose `rate_limit` is the response headers."""
    payload = {"error": None, "http_status": 200, "rate_limit": headers or {}}
    return usage_routes.iso(at - timedelta(minutes=minutes_before)), json.dumps(payload)


EMPTY = {"provider": "openalex", "unit": None, "remaining": None, "limit": None, "used_fraction": None,
         "reset_at": None, "as_of": None, "source": "last_stored_response"}


def test_without_a_limit_header_only_the_remaining_figure_is_given_and_no_denominator_is_invented():
    for headers in ({"x-ratelimit-remaining-usd": "0.42"}, {"x-ratelimit-remaining": "42"},
                    {"x-ratelimit-remaining-usd": "0.42", "x-ratelimit-limit-usd": "n/a"},
                    {"x-ratelimit-remaining-usd": "0.42", "x-ratelimit-limit-usd": "0"}):
        result = usage_routes.budget([row(1, headers)], NOON)
        assert result["remaining"] == 0.42 or result["remaining"] == 42.0
        assert result["limit"] is None and result["used_fraction"] is None


def store_search(store, rid, run, headers, at=None, provider="openalex"):
    step = store.step(run["id"], f"search:{headers}:{at}", "search")
    srid = store.add_search_run(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider=provider,
                                query_text="SYNTHETIC", request_description="SYNTHETIC", access_mode="keyless", status="completed",
                                result_count=0, page_limit=1, error_json=json.dumps({"rate_limit": headers}))
    if at is not None:
        store.conn.execute("UPDATE search_runs SET retrieved_at = ? WHERE id = ?", (usage_routes.iso(at), srid))


def test_the_budget_route_reads_the_newest_stored_openalex_headers_of_today(served):
    store, client = served
    assert client.get("/api/openalex/budget-today").json() == EMPTY
    rid, run = research(store)
    now = datetime.now(UTC)
    store_search(store, rid, run, {"x-ratelimit-remaining-usd": "0.1"}, at=now - timedelta(seconds=30), provider="crossref")
    assert client.get("/api/openalex/budget-today").json() == EMPTY  # another provider's headers are not OpenAlex's
    store_search(store, rid, run, {"x-ratelimit-remaining-usd": "0.9", "x-ratelimit-limit-usd": "1"}, at=now - timedelta(seconds=20))
    store_search(store, rid, run, {"x-ratelimit-remaining-usd": "0.8", "x-ratelimit-limit-usd": "1"}, at=now - timedelta(seconds=10))
    store_search(store, rid, run, {"x-ratelimit-remaining-usd": "0"}, at=now - timedelta(days=2))
    body = client.get("/api/openalex/budget-today").json()
    assert (body["unit"], body["remaining"], body["limit"]) == ("usd", 0.8, 1.0)
    assert body["used_fraction"] == pytest.approx(0.2)


# ---- Live read from OpenAlex's /rate-limit (needs a key, costs no credits) ------------------------------------------
# The body follows the shape OpenAlex returned on 15 Oct 2026; the figures here are SYNTHETIC.


class QuotaAdapter(FakeAdapter):
    def __init__(self, reading):
        super().__init__()
        self.reading = reading

    async def quota(self):
        return self.reading


def ledger(store, session_id, day, connection, cost):
    store.conn.execute("INSERT INTO spend_ledger (session_id, day, connection, model, cost_usd, basis, recorded_at)"
                       " VALUES (?, ?, ?, 'm', ?, ?, '2026-10-01T00:00:00.000+00:00')",
                       (session_id, day, connection, cost, "reported" if cost is not None else "unpriced"))


def test_the_models_route_gives_spend_for_a_paid_key_and_the_limit_for_a_subscription(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    reading = {"source": "live", "seen_at": "2026-10-17T09:00:00.000+00:00",
               "windows": [{"window": "seven_day", "minutes": 10080, "used_fraction": 0.8, "resets_at": None}]}
    app = create_app(settings, adapters={"codex": QuotaAdapter(reading), "deepseek": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))), start_worker=False,
        extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        store = app.state.store
        store.set_setting("answer", {"model_connection": "deepseek", "model": "deepseek-chat", "reasoning_effort": None})
        first, after = usage_routes.month_days(datetime.now(UTC))
        ledger(store, "s1", first, "deepseek", 1.5)
        ledger(store, "s2", first, "deepseek", None)
        ledger(store, "s3", "1999-01-01", "deepseek", 9.0)  # another month: not counted
        body = client.get("/api/usage/models").json()
    rows = {r["connection"]: r for r in body["connections"]}
    assert body["month_start"] == first
    assert rows["codex"] == {"connection": "codex", "kind": "subscription", "roles": ["literature"], "spend": None, "quota": reading}
    assert rows["deepseek"]["kind"] == "api" and rows["deepseek"]["roles"] == ["answer"]
    assert rows["deepseek"]["spend"] == {"estimated_usd": 1.5, "priced_calls": 1, "unpriced_calls": 1, "repriced_calls": 0,
                                       "repriced_price_list": None}
    assert set(rows) == {"codex", "deepseek"}  # no reviewer model: no reviewer row


def test_each_run_reads_its_start_end_and_calls_from_stored_rows(served):  # noqa: F811
    store, client = served
    rid, discovery = research(store)
    call(store, rid, discovery, "abstract_screening")
    call(store, rid, discovery, "abstract_screening")
    store.update_run(discovery["id"], event="run_started", status="running")
    store.update_run(discovery["id"], event="run_paused", status="paused")
    store.update_run(discovery["id"], event="run_resumed", status="queued")
    store.update_run(discovery["id"], event="run_started", status="running")
    store.update_run(discovery["id"], event="run_completed", status="completed")
    events = {row["type"]: row["created_at"] for row in store.conn.execute(
        "SELECT type, created_at FROM events WHERE run_id = ? ORDER BY id", (discovery["id"],))}
    first_start = store.conn.execute("SELECT MIN(created_at) FROM events WHERE run_id = ? AND type = 'run_started'",
                                     (discovery["id"],)).fetchone()[0]
    # A run that was cancelled before the worker took it, and one that is paused.
    never = store.create_run(rid, "pdf_collection", {}, None)
    store.update_run(never["id"], event="run_cancelled", status="cancelled")
    paused = store.create_run(rid, "answer", {}, None)
    store.update_run(paused["id"], event="run_started", status="running")
    store.update_run(paused["id"], event="run_paused", status="paused")

    body = client.get(f"/api/researches/{rid}/activity-runs").json()
    rows = {row["id"]: row for row in body["runs"]}
    assert [row["id"] for row in body["runs"]][-1] == discovery["id"]  # newest first
    done = rows[discovery["id"]]
    assert done["status"] == "completed"
    assert done["started_at"] == first_start  # the first start, not the start after the resume
    assert done["finished_at"] == events["run_completed"]
    assert done["model_calls"] == 2
    assert rows[never["id"]]["started_at"] is None and rows[never["id"]]["finished_at"] == store.conn.execute(
        "SELECT created_at FROM events WHERE run_id = ? AND type = 'run_cancelled'", (never["id"],)).fetchone()[0]
    assert rows[never["id"]]["model_calls"] == 0
    assert rows[paused["id"]]["started_at"] is not None and rows[paused["id"]]["finished_at"] is None
    assert client.get("/api/researches/no-such-research/activity-runs").status_code == 404
