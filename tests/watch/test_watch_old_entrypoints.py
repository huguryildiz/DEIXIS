"""Regressions reached through pre-B5 entry points, separated from missing interfaces."""

import asyncio
from dataclasses import asdict
import hashlib
import json
import socket

import httpx
import pytest

from deixis.providers import contract, facade, openalex, registry
from deixis.storage import backup, db
from deixis.workflow.store import Store


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Old-entry-point tests forbid network and DNS")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)


@pytest.mark.parametrize("method", ["search", "citing"])
def test_optional_sort_and_publication_date_interface(method):
    requests = []
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                requests.append(request) or httpx.Response(200, json={"results": [], "meta": {"next_cursor": None}}))) as http:
            if method == "search":
                outcome = await openalex.search_works(http, "SYNTHETIC", 100, cursor="*", sort="publication_date:desc", publication_date=True)
            else:
                outcome = await openalex.citing_works(http, "W17", "*", 100, sort="publication_date:desc", publication_date=True)
            assert outcome.status == "zero_results"
            assert outcome.request_description.endswith("sort=publication_date:desc select+publication_date")
    asyncio.run(exercise())
    assert requests[0].url.params["sort"] == "publication_date:desc"
    assert requests[0].url.params["select"].endswith(",publication_date")


@pytest.mark.parametrize("method", ["search", "citing"])
def test_empty_openalex_sort_matches_none_in_request_and_provenance(method):
    requests = []
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                requests.append(request) or httpx.Response(200, json={"results": [], "meta": {}}))) as http:
            outcomes = []
            for sort in (None, ""):
                if method == "search":
                    outcomes.append(await openalex.search_works(http, "SYNTHETIC", 100, cursor="*", sort=sort))
                else:
                    outcomes.append(await openalex.citing_works(http, "W17", "*", 100, sort=sort))
            assert asdict(outcomes[0]) == asdict(outcomes[1])
            assert " sort=" not in outcomes[1].request_description
    asyncio.run(exercise())
    assert len(requests) == 2 and requests[0].url == requests[1].url
    assert all("sort" not in request.url.params for request in requests)


def test_existing_facade_accepts_openalex_sort_and_publication_date():
    sent = []
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                sent.append(request) or httpx.Response(200, json={"results": [], "meta": {}}))) as http:
            outcome = await facade.connectors()["openalex"].search(
                contract.SearchRequest("SYNTHETIC", 100, cursor="*", options={"sort": "publication_date:desc", "publication_date": True}),
                contract.ConnectorContext(http, None, None))
            assert outcome.status == "zero_results"
    asyncio.run(exercise())
    assert len(sent) == 1


def test_existing_openalex_descriptor_is_revision_three_with_only_two_new_options():
    descriptor = facade.connectors()["openalex"].descriptor
    assert descriptor.adapter_revision == 3
    assert {o.name for o in descriptor.endpoints[0].options} == {"references", "reference_count", "sort", "publication_date"}
    assert facade.connectors()["biorxiv"].descriptor.adapter_revision == 2
    assert facade.connectors()["biorxiv"].descriptor.endpoints[0].options == ()


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC watch", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    yield conn, store, rid
    conn.close()


def test_existing_create_run_accepts_watch_check(lib):
    conn, store, rid = lib
    run = store.create_run(rid, "watch_check", {}, "SYNTHETIC-kind")
    assert run["stage"] == "discovery" and run["kind"] == "watch_check"


def seed_watch_payload(lib):
    conn, store, rid = lib
    # 0068 is the only production scaffolding in the old-code backup/purge probe.
    ts = db.now()
    conn.execute("INSERT INTO watches (id,research_id,kind,enabled,scope_revision,created_at) VALUES ('wat_SYNTHETIC',?,'citing_works',1,1,?)", (rid,ts))
    run = store.create_run(rid, "answer", {}, None)
    conn.execute("UPDATE runs SET kind='watch_check' WHERE id=?", (run["id"],))
    conn.execute("INSERT INTO watch_checks (id,watch_id,research_id,run_id,trigger,period_start,requested_to,config_json,state_version,created_at)"
        " VALUES ('wch_SYNTHETIC','wat_SYNTHETIC',?,?,'manual','manual:SYNTHETIC',?,'{}',1,?)", (rid,run["id"],ts,ts))
    step = store.step(run["id"], "watch:0:page:1", "watch_read")
    digest = hashlib.sha256(b"SYNTHETIC payload").hexdigest()
    conn.execute("INSERT INTO watch_reads (id,check_id,research_id,step_id,unit_key,page_number,provider,status,request_description,returned_count,"
        "dropped_count,records_json,raw_payload_path,payload_file_sha256,created_at)"
        " VALUES ('wrd_SYNTHETIC','wch_SYNTHETIC',?,?,'cites:W17',1,'openalex','zero_results','SYNTHETIC',0,0,'[]','SYNTHETIC.json',?,?)", (rid,step["id"],digest,ts))
    store.update_run(run["id"], status="completed")
    return digest


def test_existing_backup_lists_watch_payload_with_file_digest(lib):
    digest = seed_watch_payload(lib)
    assert backup._referenced_files(lib[0])["provider-payloads"]["SYNTHETIC.json"] == digest


def test_existing_purge_research_handles_watch_rows_and_returns_payload(lib):
    seed_watch_payload(lib)
    conn, store, rid = lib
    store.trash_research(rid)
    _, payloads = store.purge_research(rid)
    assert payloads == ["SYNTHETIC.json"]
    assert conn.execute("SELECT count(*) FROM watches").fetchone()[0] == 0


def test_existing_research_view_with_watch_run(lib):
    from deixis.workflow.views import research_view
    conn, store, rid = lib
    run = store.create_run(rid, "watch_check", {}, None)
    assert research_view(store, rid)["research"]["id"] == rid


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/watches/preview", {"kind": "citing_works"}),
    ("POST", "/watches", {"kind": "citing_works", "mode": "manual", "expected_scope_revision": 1}),
    ("GET", "/watches", None),
    ("POST", "/watches/unknown/checks", {"expected_state_version": 1}),
    ("POST", "/watches/unknown/disable", {"expected_state_version": 1}),
    ("POST", "/watches/unknown/rebind", {"expected_state_version": 1}),
    ("GET", "/watches/unknown/checks/unknown", None),
    ("GET", "/watch-items", None),
    ("POST", "/watch-items/unknown/dismiss", {"expected_status": "new"}),
])
def test_watch_route_interface_is_registered(tmp_path, method, path, body):
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.config import Settings
    from tests.fakes import FakeAdapter
    from tests.app.test_api_flow import session
    app = create_app(Settings(data_dir=tmp_path / "route-library"), adapters={"fake": FakeAdapter()},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("No provider call"))),
        start_worker=False, trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        session(client)
        rid = app.state.store.create_research("SYNTHETIC routes", "academic", "standard", ["openalex"], "fake", "fake-model", "en", search_workflow="sw")
        response = client.request(method, f"/api/researches/{rid}" + path, json=body,
            headers={"Idempotency-Key": "route-registration"})
        assert any(route.path == f"/api/researches/{{research_id}}{path.replace('unknown/checks/unknown', '{watch_id}/checks/{check_id}').replace('unknown/dismiss', '{item_id}/dismiss').replace('unknown', '{watch_id}')}"
            and method in getattr(route, "methods", set()) for route in app.routes), response.text
        assert response.status_code != 405
