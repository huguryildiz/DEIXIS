"""Synthetic end-to-end D237 runs with isolated tmp_path data and mocked providers/PDFs."""

import json
from contextlib import contextmanager

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search import small_batch
from fakes import FakeAdapter, valid_response
from test_abstract_flow import ON_TOPIC, client_of as opened_client
from overlap_flow_helpers import discover, output, SlowFetcher
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


@pytest.mark.parametrize("n,window,minimum", [(50, 50, True)])
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
