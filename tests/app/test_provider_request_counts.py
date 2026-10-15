"""A run's OpenAlex and Semantic Scholar request counts (P2, D31): one stored row per provider attempt the run made,
written just before the attempt goes to the HTTP client and settled when it ends, counting only the attempts that went
out, with the refusals among them and the attempts not known whether sent named apart.

Workflow behavior only. Every provider answer here comes from a mocked transport and the records are SYNTHETIC; passing
shows what is stored and counted for those answers, not what the live providers send or how many requests a real run
makes.
"""

import asyncio
import shutil
from types import SimpleNamespace

import httpx
import pytest

from deixis.api import usage_routes
from deixis.documents import acquisition
from deixis.providers import common
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from test_abstract_flow import Pool, app_for, client_of, discover, work

URL = "https://api.openalex.org/works"


class Log:
    """A request log that keeps its rows in memory, as the store keeps them: begun as not known whether sent."""

    def __init__(self):
        self.rows = []

    def begin(self, host, url):
        self.rows.append({"host": host, "url": url, "sends": 0, "refusals": 0, "unknown": 1, "delivery_class": None,
                          "http_status": None, "settled": False})
        return len(self.rows) - 1

    def settle(self, row, facts):
        self.rows[row] |= facts | {"settled": True}


def logged(run, log=None):
    """Run `run()` (a coroutine factory) with a request log set; the rows it holds and the result."""
    log = log or Log()

    async def go():
        token = common.request_log.set(log)
        try:
            return await run()
        finally:
            common.request_log.reset(token)

    result = asyncio.run(go())
    return log.rows, result


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def send(handler, **options):
    return logged(lambda: common.send(client(handler), URL, {"q": "x"}, {}, "GET works", "keyless",
                                      unstated_wait=0, **options))


def counts(row):
    return row["host"], row["sends"], row["refusals"], row["unknown"], row["delivery_class"], row["settled"]


class Hanging(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        await asyncio.sleep(30)


def cancelled_while_out(make):
    """Start `make()` with a request log, cancel it while its request hangs at the transport; the log's rows."""
    log = Log()

    async def go():
        common.request_log.set(log)
        task = asyncio.ensure_future(make())
        while not log.rows:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    return log.rows


def test_an_answered_request_is_one_send_and_no_refusal():
    rows, _ = send(lambda request: httpx.Response(200, json={}))
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 0, 0, None, True)]
    assert rows[0]["url"] == URL and rows[0]["http_status"] == 200


def test_the_row_exists_before_the_client_has_the_request():
    log = Log()
    seen = []

    def handler(request):
        seen.append([counts(row) for row in log.rows])
        return httpx.Response(200, json={})
    logged(lambda: common.send(client(handler), URL, {}, {}, "GET", "keyless"), log)
    assert seen == [[("api.openalex.org", 0, 0, 1, None, False)]]  # not known whether sent until it settles


def test_each_rate_limit_retry_is_a_sent_request_the_provider_refused():
    answers = iter([httpx.Response(429), httpx.Response(429), httpx.Response(200, json={})])
    rows, _ = send(lambda request: next(answers))
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 1, 0, "rejected_not_executed", True)] * 2 + [
        ("api.openalex.org", 1, 0, 0, None, True)]


def test_a_refused_attempt_is_settled_before_the_retry_wait_so_a_stop_during_the_wait_keeps_it():
    log = Log()

    async def go():
        common.request_log.set(log)
        task = asyncio.ensure_future(common.send(client(lambda request: httpx.Response(429)), URL, {}, {}, "GET",
                                                 "keyless", unstated_wait=30, max_retry_wait=60))
        while not (log.rows and log.rows[0]["settled"]):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert [counts(row) for row in log.rows] == [("api.openalex.org", 1, 1, 0, "rejected_not_executed", True)]


def test_an_attempt_cancelled_while_out_is_not_known_whether_sent():
    rows = cancelled_while_out(lambda: common.send(httpx.AsyncClient(transport=Hanging()), URL, {}, {}, "GET",
                                                   "keyless"))
    assert [counts(row) for row in rows] == [("api.openalex.org", 0, 0, 1, "cancelled", True)]


def test_a_spent_daily_budget_is_one_sent_request_refused_without_retry():
    rows, (_, outcome) = send(lambda request: httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0"}))
    assert outcome.delivery_class == "rejected_not_executed"
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 1, 0, "rejected_not_executed", True)]


def test_a_connection_that_never_opened_is_not_a_send():
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)
    rows, _ = send(refuse)
    assert [counts(row) for row in rows] == [("api.openalex.org", 0, 0, 0, "before_send", True)]


def test_a_timeout_waiting_for_a_pooled_connection_is_not_a_send():
    def busy(request):
        raise httpx.PoolTimeout("no connection free", request=request)
    rows, (_, outcome) = send(busy)
    assert outcome.status == "timeout"  # the outcome is as before; only the count reads it as not sent
    assert [counts(row) for row in rows] == [("api.openalex.org", 0, 0, 0, "after_send_unknown", True)]
    rows, found = lookup(busy)
    assert found.status == "timeout" and [(row["sends"], row["unknown"]) for row in rows] == [(0, 0)]


def test_a_stop_while_waiting_at_the_semantic_scholar_pacer_sent_nothing_and_leaves_no_row():
    from deixis.providers.pacing import SEMANTIC_SCHOLAR_PACER
    log, seen = Log(), []

    async def go():
        common.request_log.set(log)
        while not SEMANTIC_SCHOLAR_PACER._lock.acquire(blocking=False):  # another request holds the pacer
            await asyncio.sleep(0.01)
        try:
            task = asyncio.ensure_future(common.send(client(lambda request: seen.append(request) or httpx.Response(200)),
                                                     "https://api.semanticscholar.org/graph/v1/paper", {}, {}, "GET",
                                                     "keyless"))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            SEMANTIC_SCHOLAR_PACER._lock.release()
    asyncio.run(go())
    assert seen == [] and log.rows == []


def test_a_timeout_after_sending_is_a_send_with_an_unknown_outcome():
    def slow(request):
        raise httpx.ReadTimeout("late", request=request)
    rows, _ = send(slow)
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 0, 0, "after_send_unknown", True)]


def test_a_request_stopped_at_its_start_gate_is_no_attempt_and_leaves_no_row():
    class Pacer:
        async def start(self):
            return None

    async def gated():
        token = common.send_blocked.set(lambda: "quota_exhausted")
        try:
            return await common.send(client(lambda request: httpx.Response(200, json={})), URL, {}, {}, "GET works",
                                     "keyless", start_pacer=Pacer())
        finally:
            common.send_blocked.reset(token)
    rows, _ = logged(gated)
    assert rows == []


def test_without_a_request_log_nothing_is_handed_on():
    async def plain():
        return await common.send(client(lambda request: httpx.Response(200, json={})), URL, {}, {}, "GET", "keyless")
    assert common.request_log.get() is None
    asyncio.run(plain())  # nothing to receive the row; must not fail


def test_the_secret_in_a_url_never_reaches_the_row():
    secret = "SYNTHETIC-KEY-123"
    rows, _ = logged(lambda: common.send(client(lambda request: httpx.Response(200, json={})),
                                         f"https://api.semanticscholar.org/{secret}/paper", {}, {}, "GET", "api_key",
                                         secrets=(secret,)))
    assert secret not in rows[0]["url"] and rows[0]["host"] == "api.semanticscholar.org"


# ---- OpenAlex PDF lookups (documents/acquisition.py), which do not go through `send` -------------------------------

def lookup(handler, budget=None):
    return logged(lambda: acquisition.openalex_lookup(client(handler), "10.1/x", None, budget=budget))


@pytest.mark.parametrize("status,refused", [(200, 0), (404, 0), (429, 1), (403, 1), (400, 1), (503, 0)])
def test_a_pdf_lookup_that_got_an_answer_is_one_send_and_a_4xx_other_than_404_is_a_refusal(status, refused):
    rows, _ = lookup(lambda request: httpx.Response(status, json={"doi": "https://doi.org/10.1/x", "locations": []}))
    assert [(row["host"], row["sends"], row["refusals"], row["unknown"], row["http_status"]) for row in rows] == [
        ("api.openalex.org", 1, refused, 0, status)]


def test_a_pdf_lookup_whose_connection_never_opened_is_not_sent():
    def refuse(request):
        raise httpx.ConnectTimeout("no route", request=request)
    rows, found = lookup(refuse)
    assert found.status == "timeout"  # unchanged by the count
    assert [(row["sends"], row["refusals"], row["unknown"]) for row in rows] == [(0, 0, 0)]


def test_a_pdf_lookup_cancelled_while_out_is_not_known_whether_sent():
    rows = cancelled_while_out(lambda: acquisition.openalex_lookup(httpx.AsyncClient(transport=Hanging()), "10.1/x", None))
    assert [(row["sends"], row["unknown"], row["delivery_class"]) for row in rows] == [(0, 1, "cancelled")]


def test_a_pdf_lookup_the_spent_budget_skips_makes_no_request_and_no_row():
    budget = acquisition.OpenAlexBudget()
    budget.reset_at = "2999-01-01T00:00:00+00:00"
    seen = []
    rows, found = lookup(lambda request: seen.append(request) or httpx.Response(200, json={}), budget)
    assert found.error_code == acquisition.QUOTA_EXHAUSTED and seen == [] and rows == []


# ---- the run's count: stored rows, per provider ---------------------------------------------------------------------

def library(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    return store


def a_run(store):
    rid = store.create_research("SYNTHETIC request count question", "academic", "quick", ["openalex"], "fake",
                                "fake-model", None)
    return store.create_run(rid, "discovery", {}, None)["id"]


def stored(store, run_id, host, sends=0, refusals=0, unknown=0, settle=True):
    row = store.begin_provider_request(run_id, host, f"https://{host}/x")
    if settle:
        store.settle_provider_request(run_id, row, {"sends": sends, "refusals": refusals, "unknown": unknown,
                                            "delivery_class": None, "http_status": 200})
    return row


def test_the_count_sums_sends_refusals_and_unknowns_per_provider_and_leaves_other_hosts_out(tmp_path):
    store = library(tmp_path)
    run_id = a_run(store)
    stored(store, run_id, "api.openalex.org", sends=1)
    stored(store, run_id, "api.openalex.org", sends=1, refusals=1)
    stored(store, run_id, "api.openalex.org", sends=1, refusals=1)
    stored(store, run_id, "api.openalex.org")  # failed before sending
    stored(store, run_id, "api.openalex.org", unknown=1)  # cancelled while out
    stored(store, run_id, "api.crossref.org", sends=1)
    answer = usage_routes.requests(store.provider_request_counts(run_id))
    assert answer == {"recorded": True, "providers": [
        {"provider": "openalex", "sent": 3, "refused": 2, "unknown": 1},
        {"provider": "semantic_scholar", "sent": 0, "refused": 0, "unknown": 0}]}


def test_an_attempt_out_when_the_process_stopped_stays_not_known_and_recovery_says_why(tmp_path):
    """The crash case needs no run state: the row was written before the client had the request and never settled.
    Recovery leaves it not known whether sent and names the reason; a settled row is left alone."""
    store = library(tmp_path)
    run_id = a_run(store)
    store.update_run(run_id, status="cancelled")  # the person cancelled while the request was still out
    stored(store, run_id, "api.openalex.org", sends=1)
    out = stored(store, run_id, "api.openalex.org", settle=False)
    assert store.provider_request_counts(run_id)["api.openalex.org"] == {"sent": 1, "refused": 0, "unknown": 1}
    Worker.recover(SimpleNamespace(store=store))  # the next start; uses nothing but the store
    row = store.conn.execute("SELECT * FROM provider_requests WHERE id = ?", (out,)).fetchone()
    assert (row["unknown"], row["sends"], row["delivery_class"]) == (1, 0, "backend_stopped") and row["settled_at"]
    assert store.provider_request_counts(run_id)["api.openalex.org"] == {"sent": 1, "refused": 0, "unknown": 1}


def test_a_run_older_than_the_record_has_no_figures_not_zero(tmp_path, monkeypatch):
    """The migration marks every run that existed before it; their requests were never stored, so the count is not
    known. A run made after the migration is counted from its first request."""
    before = tmp_path / "before"
    before.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0011":
            shutil.copy(path, before / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", before)
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    old = a_run(store)
    store.update_run(old, status="cancelled")
    monkeypatch.undo()
    db.migrate(store.conn)
    new = a_run(store)
    assert usage_routes.requests(store.provider_request_counts(old)) == {"recorded": False, "providers": None}
    assert usage_routes.requests(store.provider_request_counts(new))["providers"][0] == {
        "provider": "openalex", "sent": 0, "refused": 0, "unknown": 0}


def test_a_request_begun_after_its_run_was_deleted_stores_nothing(tmp_path):
    store = library(tmp_path)
    assert store.begin_provider_request("run_gone", "api.openalex.org", URL) is None
    store.settle_provider_request("run_gone", None, {})
    assert store.conn.execute("SELECT COUNT(*) FROM provider_requests").fetchone()[0] == 0


def test_an_attempt_settling_after_its_research_was_deleted_never_touches_a_newer_run_s_row(tmp_path):
    """Delete the research while its attempt is out, start a new run that stores an attempt, then let the old one
    settle: ids are never reused and the settle is bound to its own run, so the new row keeps its own facts."""
    store = library(tmp_path)
    old = a_run(store)
    store.update_run(old, status="completed")
    out = stored(store, old, "api.openalex.org", settle=False)
    rid = store.run(old)["research_id"]
    store.trash_research(rid)
    store.purge_research(rid)
    new = a_run(store)
    fresh = stored(store, new, "api.openalex.org", settle=False)
    assert fresh != out
    old_log = store.request_log(old)
    old_log.settle(out, {"sends": 1, "refusals": 1, "unknown": 0, "delivery_class": "rejected_not_executed",
                         "http_status": 429})
    old_log.settle(fresh, {"sends": 1, "refusals": 1, "unknown": 0, "delivery_class": "rejected_not_executed",
                           "http_status": 429})  # even when handed the newer row's id
    assert store.provider_request_counts(new)["api.openalex.org"] == {"sent": 0, "refused": 0, "unknown": 1}


def test_a_late_settle_does_not_reopen_a_row_recovery_closed(tmp_path):
    store = library(tmp_path)
    run_id = a_run(store)
    out = stored(store, run_id, "api.openalex.org", settle=False)
    Worker.recover(SimpleNamespace(store=store))
    store.request_log(run_id).settle(out, {"sends": 1, "refusals": 0, "unknown": 0, "delivery_class": None,
                                           "http_status": 200})
    row = store.conn.execute("SELECT unknown, delivery_class FROM provider_requests WHERE id = ?", (out,)).fetchone()
    assert tuple(row) == (1, "backend_stopped")


def test_a_discovery_run_counts_every_request_the_providers_received(tmp_path, monkeypatch):
    """End to end: the mocked transport is the providers' side. Every OpenAlex and Semantic Scholar request it received
    from the run is counted once, and the Semantic Scholar 404s (the mock serves only OpenAlex) are refusals."""
    received = {"api.openalex.org": 0, "api.semanticscholar.org": 0}
    pool = Pool([work(n) for n in range(4)])

    def handler(request):
        if request.url.host in received:
            received[request.url.host] += 1
        return pool(request)

    app = app_for(tmp_path, monkeypatch, handler)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="detailed")
        usage = client.get(f"/api/usage?period=run&run_id={run_id}").json()
        unsettled = app.state.store.conn.execute(
            "SELECT COUNT(*) FROM provider_requests WHERE run_id = ? AND settled_at IS NULL", (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and unsettled == 0
    assert received["api.openalex.org"] > 0 and received["api.semanticscholar.org"] > 0
    assert usage["requests"] == {"recorded": True, "providers": [
        {"provider": "openalex", "sent": received["api.openalex.org"], "refused": 0, "unknown": 0},
        {"provider": "semantic_scholar", "sent": received["api.semanticscholar.org"],
         "refused": received["api.semanticscholar.org"], "unknown": 0}]}
