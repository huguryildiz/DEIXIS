"""Usage reads (parity slice S16): model calls by role and OpenAlex's budget today.

Workflow behavior only. The counts come from model_sessions rows and the budget from rate-limit headers the mocked
transport sent; rows and headers are SYNTHETIC. Passing shows the grouping, the month window and the header reading
behave as the slice says. It says nothing about what OpenAlex really sends today: the USD header names follow the
repo's own tests (tests/documents/test_pdf_acquisition.py), not a live check.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api import usage_routes
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.rules import LITERATURE_TASKS
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


# ---- F8: role grouping ---------------------------------------------------------------------------------------------


def test_every_step_task_maps_to_one_of_the_three_settings_roles():
    for task in LITERATURE_TASKS:
        assert usage_routes.role_of(task) == "literature"
    assert usage_routes.role_of("answer_review") == "reviewer"
    for task in ("grounded_answer", "cell_extraction", "table_columns", "research_title", "report_section", "report_plan",
                 "owner_review", "lineage_links", "claim_assessment", "kill_search_query", "something_new"):
        assert usage_routes.role_of(task) == "answer"
    assert usage_routes.ROLES == ("answer", "literature", "reviewer")


def test_usage_groups_task_types_by_role_in_settings_order_and_shares_sum_to_one():
    result = usage_routes.usage({"grounded_answer": 3, "report_section": 1, "abstract_screening": 4, "search_query": 1,
                                 "fulltext_adjudication": 1, "answer_review": 2})
    assert result["total"] == 12
    assert [(r["role"], r["calls"]) for r in result["roles"]] == [("answer", 4), ("literature", 6), ("reviewer", 2)]
    assert sum(r["share"] for r in result["roles"]) == pytest.approx(1.0)


def test_usage_with_no_data_has_all_three_roles_at_zero_and_no_share():
    result = usage_routes.usage({})
    assert result["total"] == 0
    assert result["roles"] == [{"role": r, "calls": 0, "share": None} for r in ("answer", "literature", "reviewer")]


# ---- F8: month window ----------------------------------------------------------------------------------------------


def test_month_window_is_the_local_calendar_month_as_stored_utc_timestamps():
    istanbul = ZoneInfo("Europe/Istanbul")  # UTC+3 all year
    since, until = usage_routes.month_window(datetime(2026, 10, 11, 12, 0, tzinfo=UTC), istanbul)
    assert (since, until) == ("2026-09-30T21:00:00.000+00:00", "2026-10-31T21:00:00.000+00:00")
    # The last local minute of September is still September, the first of October is October.
    assert usage_routes.month_window(datetime(2026, 9, 30, 20, 59, tzinfo=UTC), istanbul)[0] == "2026-08-31T21:00:00.000+00:00"
    assert usage_routes.month_window(datetime(2026, 9, 30, 21, 0, tzinfo=UTC), istanbul)[0] == since


def test_month_window_rolls_over_the_year_and_follows_daylight_saving():
    new_york = ZoneInfo("America/New_York")
    assert usage_routes.month_window(datetime(2026, 12, 15, tzinfo=UTC), new_york) == (
        "2026-12-01T05:00:00.000+00:00", "2027-01-01T05:00:00.000+00:00")
    # March 2026 starts on standard time and April on daylight time: the month is 743 hours, not 744.
    since, until = usage_routes.month_window(datetime(2026, 3, 15, tzinfo=UTC), new_york)
    assert (since, until) == ("2026-03-01T05:00:00.000+00:00", "2026-04-01T04:00:00.000+00:00")


def test_month_window_without_a_zone_uses_the_machine_zone(monkeypatch):
    import time
    monkeypatch.setenv("TZ", "Europe/Istanbul")
    time.tzset()
    try:
        assert usage_routes.month_window(datetime(2026, 10, 11, tzinfo=UTC)) == (
            "2026-09-30T21:00:00.000+00:00", "2026-10-31T21:00:00.000+00:00")
    finally:
        monkeypatch.undo()
        time.tzset()


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


def test_the_run_route_counts_one_runs_sessions_whatever_their_date(served):
    store, client = served
    rid, run = research(store)
    store.conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (run["id"],))
    other = store.create_run(rid, "answer", {}, None)
    call(store, rid, run, "search_query", datetime(2020, 1, 1, tzinfo=UTC))
    call(store, rid, run, "abstract_screening")
    call(store, rid, other, "grounded_answer")
    body = client.get("/api/usage", params={"period": "run", "run_id": run["id"]}).json()
    assert body["period"] == "run" and body["run_id"] == run["id"] and "since" not in body
    assert body["total"] == 2 and {r["role"]: r["calls"] for r in body["roles"]} == {"answer": 0, "literature": 2, "reviewer": 0}
    assert client.get("/api/usage", params={"period": "run", "run_id": other["id"]}).json()["total"] == 1


def test_the_run_route_refuses_a_missing_or_unknown_run_and_an_unknown_period(served):
    _, client = served
    assert client.get("/api/usage?period=run").status_code == 422
    assert client.get("/api/usage?period=run&run_id=run_nope").status_code == 404
    assert client.get("/api/usage?period=year").status_code == 422


def test_the_month_route_with_no_sessions_is_zero_not_an_error(served):
    _, client = served
    body = client.get("/api/usage?period=month").json()
    assert body["total"] == 0 and all(r["calls"] == 0 and r["share"] is None for r in body["roles"])


# ---- F7: OpenAlex budget today -------------------------------------------------------------------------------------

NOON = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def row(minutes_before, headers=None, *, at=NOON):
    """A stored OpenAlex search row: its time and an error_json whose `rate_limit` is the response headers."""
    payload = {"error": None, "http_status": 200, "rate_limit": headers or {}}
    return usage_routes.iso(at - timedelta(minutes=minutes_before)), json.dumps(payload)


EMPTY = {"provider": "openalex", "unit": None, "remaining": None, "limit": None, "used_fraction": None,
         "reset_at": None, "as_of": None, "source": "last_stored_response"}


def test_a_dollar_budget_with_its_limit_gives_remaining_limit_and_used_fraction_and_the_reset_time():
    headers = {"x-ratelimit-remaining-usd": "0.75", "x-ratelimit-limit-usd": "1", "x-ratelimit-reset": "3600"}
    result = usage_routes.budget([row(10, headers)], NOON)
    assert result == {"provider": "openalex", "unit": "usd", "remaining": 0.75, "limit": 1.0, "used_fraction": 0.25,
                      "reset_at": "2026-10-11T12:50:00.000+00:00", "as_of": "2026-10-11T11:50:00.000+00:00",
                      "source": "last_stored_response"}


def test_a_count_budget_reads_the_plain_limit_headers():
    result = usage_routes.budget([row(1, {"x-ratelimit-remaining": "900", "x-ratelimit-limit": "1000"})], NOON)
    assert (result["unit"], result["remaining"], result["limit"], result["used_fraction"]) == ("credits", 900.0, 1000.0, 0.1)


def test_without_a_limit_header_only_the_remaining_figure_is_given_and_no_denominator_is_invented():
    for headers in ({"x-ratelimit-remaining-usd": "0.42"}, {"x-ratelimit-remaining": "42"},
                    {"x-ratelimit-remaining-usd": "0.42", "x-ratelimit-limit-usd": "n/a"},
                    {"x-ratelimit-remaining-usd": "0.42", "x-ratelimit-limit-usd": "0"}):
        result = usage_routes.budget([row(1, headers)], NOON)
        assert result["remaining"] == 0.42 or result["remaining"] == 42.0
        assert result["limit"] is None and result["used_fraction"] is None


def test_the_two_units_are_never_mixed():
    # A plain limit beside a dollar remainder is not a denominator for the dollars.
    result = usage_routes.budget([row(1, {"x-ratelimit-remaining-usd": "0.5", "x-ratelimit-limit": "1000",
                                          "x-ratelimit-remaining": "900"})], NOON)
    assert (result["unit"], result["remaining"], result["limit"], result["used_fraction"]) == ("usd", 0.5, None, None)


def test_an_exhausted_budget_reads_as_zero_remaining_and_fully_used():
    result = usage_routes.budget([row(1, {"x-ratelimit-remaining-usd": "0", "x-ratelimit-limit-usd": "1"})], NOON)
    assert (result["remaining"], result["used_fraction"]) == (0.0, 1.0)


def test_used_fraction_stays_inside_zero_and_one():
    result = usage_routes.budget([row(1, {"x-ratelimit-remaining": "1200", "x-ratelimit-limit": "1000"})], NOON)
    assert result["used_fraction"] == 0.0


def test_the_newest_row_with_a_figure_wins_and_rows_without_headers_are_skipped():
    rows = [row(1, {}), row(2, {"x-ratelimit-remaining": "junk"}), row(3, {"x-ratelimit-remaining": "800"}),
            row(4, {"x-ratelimit-remaining": "900"})]
    assert usage_routes.budget(rows, NOON)["remaining"] == 800.0


def test_only_headers_since_the_last_daily_reset_count():
    yesterday = row(1, {"x-ratelimit-remaining-usd": "0"}, at=datetime(2026, 10, 10, 23, 59, 59, tzinfo=UTC))
    assert usage_routes.budget([yesterday], NOON) == EMPTY
    midnight = row(0, {"x-ratelimit-remaining": "5"}, at=datetime(2026, 10, 11, tzinfo=UTC))
    assert usage_routes.budget([midnight], NOON)["remaining"] == 5.0


def test_the_reset_falls_back_to_the_next_midnight_utc_when_the_header_is_missing_or_out_of_range():
    for reset in ({}, {"x-ratelimit-reset": "999999"}, {"x-ratelimit-reset": "soon"}, {"x-ratelimit-reset": "-5"}):
        result = usage_routes.budget([row(1, {"x-ratelimit-remaining": "5"} | reset)], NOON)
        assert result["reset_at"] == "2026-10-12T00:00:00.000+00:00"


def test_malformed_rows_and_headers_are_skipped_not_raised():
    rows = [("not a time", "{}"), (usage_routes.iso(NOON), "not json"), (usage_routes.iso(NOON), json.dumps({"rate_limit": "x"})),
            (usage_routes.iso(NOON), None), row(5, {"x-ratelimit-remaining": " 7 "})]
    assert usage_routes.budget(rows, NOON)["remaining"] == 7.0


def test_no_rows_is_an_empty_answer_with_nothing_filled_in():
    assert usage_routes.budget([], NOON) == EMPTY


def test_the_openalex_adapter_keeps_the_dollar_limit_header_with_the_others():
    def handler(request):
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []}, headers={
            "x-ratelimit-limit-usd": "1", "x-ratelimit-remaining-usd": "0.9", "x-ratelimit-reset": "100", "x-unrelated": "no"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openalex.search_works(client, "irrigation", 5)
    assert asyncio.run(go()).rate_limit == {"x-ratelimit-limit-usd": "1", "x-ratelimit-remaining-usd": "0.9",
                                             "x-ratelimit-reset": "100"}


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


def test_many_newer_rows_without_headers_do_not_hide_an_older_usable_one(served):
    store, client = served
    rid, run = research(store)
    now = datetime.now(UTC)
    store_search(store, rid, run, {"x-ratelimit-remaining": "640", "x-ratelimit-limit": "1000"}, at=now - timedelta(minutes=5))
    for n in range(150):  # more than any row cap: newer OpenAlex rows that carry no budget header
        store_search(store, rid, run, {} if n % 2 else {"retry-after": "1"}, at=now - timedelta(seconds=n + 1))
    body = client.get("/api/openalex/budget-today").json()
    assert (body["unit"], body["remaining"], body["limit"], body["source"]) == ("credits", 640.0, 1000.0, "last_stored_response")


# ---- Live read from OpenAlex's /rate-limit (needs a key, costs no credits) ------------------------------------------
# The body follows the shape OpenAlex returned on 15 Oct 2026; the figures here are SYNTHETIC.
LIVE = {"rate_limit": {"daily_budget_usd": 1, "daily_used_usd": 0.25, "daily_remaining_usd": 0.75,
                       "resets_at": "2026-10-16T00:00:00.000Z", "credits_limit": 10000, "credits_remaining": 7500,
                       "prepaid_remaining_usd": 2.5, "onetime_credits_remaining": 25000,
                       "prepaid_expires_at": "Sat Jan 16 2027 11:05:39 GMT+0000 (Coordinated Universal Time)"}}


def live_app(tmp_path, handler):
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, search_query="code", fulltext_fetch="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)), start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    return TestClient(app)


def test_live_answer_gives_dollars_first_and_the_reset_time():
    body = usage_routes.live_budget(LIVE, NOON)
    assert (body["unit"], body["remaining"], body["limit"], body["source"]) == ("usd", 0.75, 1.0, "live")
    assert body["used_fraction"] == pytest.approx(0.25)
    assert body["reset_at"] == "2026-10-16T00:00:00.000+00:00"
    assert (body["prepaid_remaining"], body["prepaid_expires_at"]) == (2.5, "2027-01-16T11:05:39.000+00:00")
    credits = usage_routes.live_budget({"rate_limit": {"credits_limit": 10000, "credits_remaining": 7500}}, NOON)
    assert (credits["unit"], credits["remaining"], credits["limit"]) == ("credits", 7500.0, 10000.0)
    assert (credits["prepaid_remaining"], credits["prepaid_expires_at"]) == (None, None)
    assert usage_routes.live_budget({"error": "x"}, NOON) is None


def test_with_a_key_the_route_reads_openalex_live(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "SYNTHETIC")
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=LIVE)
    with live_app(tmp_path, handler) as client:
        body = client.get("/api/openalex/budget-today").json()
    assert (body["source"], body["remaining"]) == ("live", 0.75)
    assert [(u.host, u.path, u.params["api_key"]) for u in seen] == [("api.openalex.org", "/rate-limit", "SYNTHETIC")]


def test_without_a_key_nothing_is_asked_and_a_failed_read_falls_back_to_the_stored_figure(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(401, json={"error": "Authentication required"})
    with live_app(tmp_path, handler) as client:
        assert client.get("/api/openalex/budget-today").json() == EMPTY
        assert seen == []
        monkeypatch.setenv("OPENALEX_API_KEY", "SYNTHETIC")
        assert client.get("/api/openalex/budget-today").json() == EMPTY
        assert len(seen) == 1


# ---- Model connections: spend this month (paid by key) and subscription limits -------------------------------------

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


def test_codex_windows_are_named_by_length_and_a_missing_window_is_left_out():
    result = {"rateLimits": {"primary": {"usedPercent": 80, "windowDurationMins": 10080, "resetsAt": 1792650762},
                             "secondary": None}}
    from deixis.models import quota
    assert quota.codex_windows(result) == [{"window": "seven_day", "minutes": 10080, "used_fraction": 0.8,
                                           "resets_at": "2026-10-22T06:32:42.000+00:00"}]


def test_codex_windows_reject_malformed_figures():
    from deixis.models import quota
    assert quota.codex_windows({"rateLimits": {"primary": {"usedPercent": True, "windowDurationMins": 300}}}) == []
    assert quota.codex_windows({"rateLimits": None}) == []
    for minutes in (True, 0, -300):
        assert quota.codex_windows({"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": minutes}}}) == []
    assert quota.codex_windows(None) == []


def test_claude_windows_come_from_unified_windows_and_a_missing_utilization_is_left_out():
    from deixis.models import quota
    raw = {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.37, "resetsAt": 1792188600},
                                                   "seven_day": {"resetsAt": 1792342800}}}
    assert quota.claude_windows(raw) == [{"window": "five_hour", "minutes": 300, "used_fraction": 0.37,
                                          "resets_at": "2026-10-16T22:10:00.000+00:00"}]
    assert quota.claude_windows({"status": "allowed"}) == []


def test_the_claude_reading_survives_a_restart(tmp_path):
    from deixis.models import quota
    from deixis.models.claude import ClaudeCodeAdapter
    adapter = ClaudeCodeAdapter(workspace=tmp_path / "claude-workspace")
    assert asyncio.run(adapter.quota()) is None
    adapter._note_quota({"unifiedWindows": {"seven_day": {"utilization": 0.5, "resetsAt": 1792342800}}})
    again = ClaudeCodeAdapter(workspace=tmp_path / "claude-workspace")
    reading = asyncio.run(again.quota())
    assert reading["source"] == "last_call" and [w["window"] for w in reading["windows"]] == ["seven_day"]
    assert quota.load(tmp_path / "missing.json") is None


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
    assert rows["deepseek"]["spend"] == {"estimated_usd": 1.5, "priced_calls": 1, "unpriced_calls": 1}
    assert set(rows) == {"codex", "deepseek"}  # no reviewer model: no reviewer row


def test_month_days_roll_over_the_year():
    assert usage_routes.month_days(datetime(2026, 12, 15, 12, tzinfo=UTC)) == ("2026-12-01", "2027-01-01")


def test_a_malformed_kept_claude_reading_is_unknown_not_a_crash(tmp_path):
    from deixis.models import quota
    path = tmp_path / "claude-quota.json"
    good = {"source": "last_call", "seen_at": "2026-10-17T07:40:00.000+00:00",
            "windows": [{"window": "five_hour", "minutes": 300, "used_fraction": 0.37, "resets_at": None}]}
    for bad in ({"windows": [None]}, {**good, "windows": [{**good["windows"][0], "used_fraction": "0.4"}]},
                {**good, "windows": [{**good["windows"][0], "used_fraction": 1.5}]}, {**good, "windows": []},
                {**good, "windows": [{**good["windows"][0], "used_fraction": None}]},
                {**good, "windows": [{k: v for k, v in good["windows"][0].items() if k != "used_fraction"}]},
                {**good, "seen_at": "0001-01-01T00:00:00+01:00"},
                {**good, "windows": [{**good["windows"][0], "resets_at": "9999-12-31T23:59:59-01:00"}]},
                {**good, "seen_at": "garbage"}, {**good, "seen_at": "2026-10-17T07:40:00"},
                {**good, "windows": [{**good["windows"][0], "resets_at": "garbage"}]},
                {**good, "windows": good["windows"] * 2},
                {**good, "source": "live"}, [good]):
        path.write_text(json.dumps(bad))
        assert quota.load(path) is None, bad
    path.write_text(json.dumps(good))
    assert quota.load(path) == good
    # Any other spelling of a valid moment is rewritten in the one format the page reads.
    path.write_text(json.dumps({**good, "seen_at": "2026-10-17X09:40:00+02:00"}))
    assert quota.load(path)["seen_at"] == "2026-10-17T07:40:00.000+00:00"


def test_nonfinite_or_out_of_range_figures_are_left_out_not_shown_as_0_or_100():
    from deixis.models import quota
    raw = {"unifiedWindows": {"five_hour": {"utilization": float("nan")}, "seven_day": {"utilization": float("inf")}}}
    assert quota.claude_windows(raw) == []
    assert quota.stamp(1e20) is None and quota.stamp(float("inf")) is None
    assert quota.stamp(10**400) is None and quota.fraction(10**400) is None
    assert quota.codex_windows({"rateLimits": {"primary": {"usedPercent": 10**400, "windowDurationMins": 300}}}) == []
    windows = quota.codex_windows({"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": 1e20}}})
    assert windows == [{"window": "five_hour", "minutes": 300, "used_fraction": 0.1, "resets_at": None}]
