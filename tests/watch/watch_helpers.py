"""Isolated SYNTHETIC watch libraries; no model or real transport is permitted."""

import hashlib
import json
import socket
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers import common, registry
from deixis.storage import db
from deixis.workflow.watch.store import WatchStore
from tests.fakes import FakeAdapter
from tests.app.test_api_flow import session


@pytest.fixture(autouse=True)
def watch_offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Watch tests forbid real network, DNS and model calls")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    for connector in registry.CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)


def work(identifier="W1", *, title=None, doi=None, date="2026-09-30", **extra):
    return {"id": "https://openalex.org/" + str(identifier) if isinstance(identifier, (str, int)) else identifier,
        "doi": doi, "display_name": title or "SYNTHETIC paper " + str(identifier), "publication_year": 2026,
        "authorships": [{"author": {"display_name": "SYNTHETIC Ada Smith"}}], "ids": {},
        "publication_date": date, "type": "article", "primary_location": {"landing_page_url": "https://synthetic.invalid/paper"},
        "abstract_inverted_index": {"SYNTHETIC": [0], "evidence": [1]}, **extra}


def page(*records, cursor=None):
    return {"meta": {"count": len(records), "next_cursor": cursor}, "results": list(records)}


@contextmanager
def watch_api(tmp_path, *, queries=None, handler=None, headers=None, start_worker=False):
    sent = []
    state = SimpleNamespace(payload=page(work()), status=200, handler=handler)
    async def serve(request):
        sent.append(request)
        if state.handler:
            response = state.handler(request)
            if hasattr(response, "__await__"):
                response = await response
            return response
        return httpx.Response(state.status, json=state.payload, headers={"retry-after": "0"})
    def no_model(payload):
        raise AssertionError("A watch never calls a model")
    directory = tmp_path / db.new_id("watch")
    settings = Settings(data_dir=directory, port=8879, fulltext_fetch="off", citation_chaining="off")
    http = httpx.AsyncClient(transport=httpx.MockTransport(serve), headers=headers)
    app = create_app(settings, adapters={"fake": FakeAdapter(responder=no_model)}, http_client=http,
                     start_worker=start_worker, trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8879", raise_server_exceptions=True) as client:
        session(client)
        store = app.state.store
        rid = store.create_research("SYNTHETIC follow-up question", "academic", "standard", ["openalex"], "fake",
                                    "fake-model", "en")
        queries = queries if queries is not None else [{"provider_id": "openalex", "query_text": "SYNTHETIC query"}]
        store.freeze_protocol(rid, 1, {"compiled_queries": queries})
        yield SimpleNamespace(client=client, app=app, store=store, conn=store.conn, rid=rid, sent=sent, state=state,
            watches=WatchStore(store), settings=settings, url=f"/api/researches/{rid}/watches")


@pytest.fixture
def api(tmp_path):
    with watch_api(tmp_path) as value:
        yield value


def create(api, kind="protocol_queries", key=None, **extra):
    body = {"kind": kind, "mode": "manual", "expected_scope_revision": api.store.research(api.rid)["current_scope_revision"], **extra}
    response = api.client.post(api.url, json=body, headers={"Idempotency-Key": key or db.new_id("cmd")})
    assert response.status_code == 201, response.text
    return response.json()


def now_check(api, wid, key=None, expected=None):
    version = api.watches.watch(api.rid, wid)["state_version"] if expected is None else expected
    response = api.client.post(api.url + f"/{wid}/checks", json={"expected_state_version": version},
                               headers={"Idempotency-Key": key or db.new_id("cmd")})
    assert response.status_code == 202, response.text
    return response.json()


def turn(api):
    async def guarded():
        try:
            await api.app.state.worker._turn()
        except BaseException as exc:
            if type(exc).__name__ != "Crash":
                raise
            return exc
    result = api.client.portal.call(guarded)
    if isinstance(result, BaseException):
        raise result
    return result


def read(api, command):
    response = api.client.get(api.url + f"/{command['watch_id']}/checks/{command['check_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def control(api, command, action):
    response = api.client.post(f"/api/runs/{command['run_id']}/{action}")
    assert response.status_code == 200, response.text
    return response.json()


def add_included(api, identifier, **changes):
    record = registry.openalex._record(work(identifier, **changes))
    source, _ = api.store.upsert_provider_source("openalex", record, None)
    api.store.add_to_corpus(api.rid, source, "library", selection_state="included", selection_origin="user")
    return source


def record(provider="openalex", identifier="W1", **changes):
    from deixis.workflow.watch.check import normalize_record
    source = asdict(registry.openalex._record(work(identifier)))
    source.update(changes)
    return normalize_record(provider, source, db.now(), source["raw"].get("publication_date") if provider == "openalex" else None)


def rows(conn, tables=None, omit=None):
    tables = tables or [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    result = {}
    for table in tables:
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")') if r[1] not in (omit or {}).get(table, ())]
        selected = ",".join('"' + c + '"' for c in columns)
        result[table] = sorted([tuple(r) for r in conn.execute(f'SELECT {selected} FROM "{table}"')], key=repr)
    return result


def hashes(conn, tables=None, omit=None):
    return {table: hashlib.sha256(json.dumps(records, default=str).encode()).hexdigest()
            for table, records in rows(conn, tables, omit).items()}
