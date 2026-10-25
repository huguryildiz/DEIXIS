"""A run's OpenAlex and Semantic Scholar request counts (P2, D31): one stored row per provider attempt the run made,
written just before the attempt goes to the HTTP client and settled when it ends, counting only the attempts that went
out, with the refusals among them and the attempts not known whether sent named apart.

Workflow behavior only. Every provider answer here comes from a mocked transport and the records are SYNTHETIC; passing
shows what is stored and counted for those answers, not what the live providers send or how many requests a real run
makes.
"""

import asyncio

import httpx

from deixis.documents import acquisition
from deixis.providers import common
from deixis.storage import db
from deixis.workflow.store import Store
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


def test_each_rate_limit_retry_is_a_sent_request_the_provider_refused():
    answers = iter([httpx.Response(429), httpx.Response(429), httpx.Response(200, json={})])
    rows, _ = send(lambda request: next(answers))
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 1, 0, "rejected_not_executed", True)] * 2 + [
        ("api.openalex.org", 1, 0, 0, None, True)]


def test_a_timeout_after_sending_is_a_send_with_an_unknown_outcome():
    def slow(request):
        raise httpx.ReadTimeout("late", request=request)
    rows, _ = send(slow)
    assert [counts(row) for row in rows] == [("api.openalex.org", 1, 0, 0, "after_send_unknown", True)]


def test_the_secret_in_a_url_never_reaches_the_row():
    secret = "SYNTHETIC-KEY-123"
    rows, _ = logged(lambda: common.send(client(lambda request: httpx.Response(200, json={})),
                                         f"https://api.semanticscholar.org/{secret}/paper", {}, {}, "GET", "api_key",
                                         secrets=(secret,)))
    assert secret not in rows[0]["url"] and rows[0]["host"] == "api.semanticscholar.org"


# ---- OpenAlex PDF lookups (documents/acquisition.py), which do not go through `send` -------------------------------

def lookup(handler, budget=None):
    return logged(lambda: acquisition.openalex_lookup(client(handler), "10.1/x", None, budget=budget))


# ---- the run's count: stored rows, per provider ---------------------------------------------------------------------

def library(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    return store


def stored(store, run_id, host, sends=0, refusals=0, unknown=0, settle=True):
    row = store.begin_provider_request(run_id, host, f"https://{host}/x")
    if settle:
        store.settle_provider_request(run_id, row, {"sends": sends, "refusals": refusals, "unknown": unknown,
                                            "delivery_class": None, "http_status": 200})
    return row


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
