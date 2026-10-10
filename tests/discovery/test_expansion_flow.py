"""Mocked OpenAlex fields and an app factory other discovery tests borrow (slice 04b's packet-size question).

The second-round expansion these helpers were written for is gone with the clean start (slice 3a), and so are its
tests. What stays is the SYNTHETIC transport (`Field`), the dead model adapter and the run helpers, which
tests/discovery/test_{approval,criterion,ranking,suggestion}_flow.py and tests/providers/test_source_routing.py import.
"""

import json
import time
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
# The first round's records repeat "duty cycle", which the question never wrote; the second round's do not.
FIRST_TITLE = "SYNTHETIC duty cycle scheduling in a sensor node"
SECOND_TITLE = "SYNTHETIC duty cycle policy of a relay"
ACCEPTED = "duty cycle"
# The two count requests the field probe sends for the accepted phrase. The setting block entered the query as its
# root words, so the group is the one `build_vocabulary` chose: (energy OR wireless).
PHRASE_PROBE = f'"{ACCEPTED}"'
FIELD_PROBE = f'"{ACCEPTED}" AND (energy OR wireless)'
DEFAULT_COUNT = 8  # below the field probe's threshold, so an unlisted phrase is refused
PAGE = 2  # a small page keeps the fixtures small; real page sizes are checked in tests/providers/test_providers.py


def DeadAdapter():
    """Every model call fails. An expansion and a second round that still run, ran without a model (SW2.3)."""
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def work(number, title):
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/10.1/oa.{number}",
            "display_name": f"{title} {number}", "publication_year": 2024, "type": "article",
            "authorships": [], "abstract_inverted_index": {"We": [0], "measure.": [1]}}


class Field:
    """OpenAlex answering count probes and serving one set of pages per round.

    A query that holds the accepted phrase is the second round's; anything else is the first round's. Every count
    probe and every page request is recorded, so a resumed run can be asked what it sent again.
    """

    def __init__(self, first=4, second=3, counts=None, first_title=FIRST_TITLE, probe_status=200,
                 second_status=200, fail_at=None):
        self.counts = {PHRASE_PROBE: 100, FIELD_PROBE: 40} if counts is None else counts
        self.first = [work(index, first_title) for index in range(first)]
        self.second = [work(100 + index, SECOND_TITLE) for index in range(second)]
        self.probe_status, self.second_status, self.fail_at = probe_status, second_status, fail_at
        self.probes, self.pages = [], []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)  # the other providers are not mocked and fail, which D18 carries on from
        params = request.url.params
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.probes.append(query)
            if self.probe_status != 200:
                return httpx.Response(self.probe_status)
            return httpx.Response(200, json={"meta": {"count": self.counts.get(query, DEFAULT_COUNT)}, "results": []})
        second = ACCEPTED in query
        cursor, size = params.get("cursor"), int(params["per_page"])
        start = 0 if cursor in (None, "*") else int(cursor)
        self.pages.append((query, start))
        if second and self.second_status != 200:
            return httpx.Response(self.second_status)
        if (query, start) == self.fail_at:
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        works = self.second if second else self.first
        end = min(start + size, len(works))
        return httpx.Response(200, json={
            "meta": {"count": len(works), "next_cursor": str(end) if end < len(works) else None},
            "results": works[start:end]})


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
                      adapters={"fake": adapter or DeadAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def discover(client, question=QUESTION, **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def protocols(store, rid):
    return [{"protocol_revision": row["protocol_revision"], "reason": row["reason"],
             "body": json.loads(row["body_json"]), "hash": row["body_sha256"]}
            for row in store.conn.execute(
                "SELECT * FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]
