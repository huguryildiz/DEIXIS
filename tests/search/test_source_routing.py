"""Source routing before the first search: one field distribution request, a table of OpenAlex fields, and the
queries compiled for the sources it chooses (slice 14, D93).

Since the clean start (slice 3a) the fast path searches OpenAlex only and drops every other routed query
(`openalex_only`), but routing still runs and is recorded in its step and in the protocol body (`source_routing`,
`compiled_queries`). The tests of cards shown before routing existed (D93) and of their second round were removed with
that old-data compatibility, and the tests of a correction on the approval card with the card itself (slice 3b).

Distributions, questions and records are SYNTHETIC and from more than one field; every transport is mocked. Passing
shows which sources the rule chooses for a given distribution and that the run asks for it once — not that the share
or the table are right for any real question (neither was measured), nor what a real distribution looks like.
"""

from __future__ import annotations


import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow import routing
from deixis.workflow.flow import ResearchFlow
from test_search_query import proposal
from test_vocabulary_flow import DeadAdapter, QUESTION, no_fetch

SCOPE = ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]


def distribution(**counts):
    """A SYNTHETIC field distribution: display name (underscores for spaces) → count; the total is their sum."""
    rows = [{"field": name.replace("_", " "), "key": f"https://openalex.org/fields/{i}", "count": n}
            for i, (name, n) in enumerate(counts.items())]
    return {"total": sum(counts.values()), "fields": rows}


def chosen(record):
    return [row["provider_id"] for row in record["chosen"]]


def reasons(record):
    return {row["provider_id"]: row["reason"] for row in record["left_out"]}


# ---- the rule -----------------------------------------------------------------------------------------------------


def test_a_source_outside_the_scope_or_without_its_key_is_never_chosen(monkeypatch):
    monkeypatch.delenv("IEEE_API_KEY", raising=False)  # another test's credential lookup may have set it
    record = routing.route(["openalex", "semantic_scholar", "arxiv", "ieee_xplore"], "q",
                           distribution(Medicine=90, Computer_Science=10), "read")
    left = reasons(record)
    assert left["pubmed"] == "not_in_scope" and left["biorxiv"] == "not_in_scope"
    assert left["ieee_xplore"] == "not_configured"  # no IEEE key in tests
    # CORE, SerpApi and Scopus are searched by a legacy research only.
    assert left["core"] == left["serpapi"] == left["scopus"] == "not_in_sw_search"
    assert record["providers"] == ["openalex", "semantic_scholar"]


def test_quick_s_three_queries_search_no_domain_source_under_the_routed_order():
    built = proposal()  # a model-written query with the code's beside it (D92)
    _, queries = ResearchFlow._compiled(None, built, ["openalex", "semantic_scholar", "arxiv", "pubmed"],
                                        {"max_provider_requests": 3})
    assert [(q["provider_id"], q["origin"]) for q in queries] == [
        ("openalex", "model"), ("openalex", "code"), ("semantic_scholar", "model")]
    _, eight = ResearchFlow._compiled(None, built, ["openalex", "semantic_scholar", "arxiv", "pubmed"],
                                      {"max_provider_requests": 8})
    assert [q["provider_id"] for q in eight] == ["openalex"] * 2 + ["semantic_scholar"] * 2 + ["arxiv"] * 2 + ["pubmed"] * 2
    assert all(q.get("endpoint") == "bulk" for q in eight if q["provider_id"] == "semantic_scholar")


# ---- through a discovery run --------------------------------------------------------------------------------------


def client_for(tmp_path, monkeypatch, handler):
    """A test client on a fresh app with no source keys set, searching through `handler`."""
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off"),
                     adapters={"fake": DeadAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def start(client, effort="standard"):
    body = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": effort}
    rid = client.post("/api/researches", json=body).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id


def searched(run):
    return sorted({s["kind"].split(":")[1] for s in run["steps"] if s["kind"].startswith("provider_search:")})
