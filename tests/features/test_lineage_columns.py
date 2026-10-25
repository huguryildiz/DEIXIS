"""L1 role boundaries on synthetic temporary libraries; no providers or real models."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from fakes import FakeAdapter
from test_api_flow import create, session


TEXT = {"name": "Synthetic method", "instruction": "Record the stated method.", "answer_format": "text",
        "options": None, "allow_multiple": False, "unit_hint": None}
EXPECTED = {
    "problem": ("Problem addressed", "The problem or question this work takes up, in its own terms, in one or two sentences."),
    "change": ("Established or changed", "What this work states it established, showed or changed relative to earlier work. If the passages make no comparison, say so; do not infer one."),
    "uncertainty": ("Uncertainty left", "An uncertainty, limitation or open question the work itself names as remaining or as future work. Prefer the stated next step when the source separates a limitation from a next step."),
}


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Synthetic question?", "attached", "quick", [], "fake", "fake-model", "en")
    tables = TableStore(store)
    tid = tables.create_table(rid, "Synthetic table", None, None, None)
    yield SimpleNamespace(conn=conn, store=store, tables=tables, rid=rid, tid=tid)
    conn.close()


def version(lib, tid=None):
    return lib.tables._table(lib.rid, tid or lib.tid)["version"]


def add(lib, key=None, tid=None):
    lib.tables.add_development_columns(lib.rid, tid or lib.tid, version(lib, tid), key)


def columns(lib, removed=False, tid=None):
    return lib.tables._columns(tid or lib.tid, include_removed=removed)


def remove(lib, column):
    lib.tables.remove_column(lib.rid, lib.tid, column["id"], column["version"])


def database_state(lib):
    return {table: [tuple(row) for row in lib.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("table_columns", "column_revisions", "evidence_tables", "events")}


def test_add_development_columns_is_idempotent(lib):
    add(lib, "k")
    before = database_state(lib)
    lib.tables.add_development_columns(lib.rid, lib.tid, 1, "k")  # replay before version check
    add(lib, "unused")
    add(lib)
    assert database_state(lib) == before
    other = lib.tables.create_table(lib.rid, "Other", None, None, None)
    add(lib, "k", other)
    assert len(columns(lib, tid=other)) == 3
    fresh = lib.tables.create_table(lib.rid, "Stale", None, None, None)
    lib.tables.add_column(lib.rid, fresh, TEXT, version(lib, fresh), None)
    with pytest.raises(RevisionConflict):
        lib.tables.add_development_columns(lib.rid, fresh, 1, "stale")
    old = columns(lib)[0]
    remove(lib, old)
    before_replay = database_state(lib)
    add(lib, "k")  # removed revisions still spend the original key
    assert database_state(lib) == before_replay
    add(lib, "unused")  # a no-op never spends a key
    assert len(columns(lib)) == 3 and len(columns(lib, removed=True)) == 4
    assert columns(lib)[-1]["lineage_role"] == old["lineage_role"]
    other_rid = lib.store.create_research("Other research?", "attached", "quick", [], "fake", "fake-model", "en")
    other_tid = lib.tables.create_table(other_rid, "Other research table", None, None, None)
    lib.tables.add_development_columns(other_rid, other_tid, 1, "k")
    assert len(lib.tables._columns(other_tid)) == 3


def test_api_add_development_columns(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8805), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        base = f"/api/researches/{rid}/tables"
        table = client.post(base, json={"title": "Synthetic"}).json()
        url = f"{base}/{table['table']['id']}"
        action = url + "/lineage/columns"
        response = client.post(action, json={"expected_version": 1}, headers={"Idempotency-Key": "k"})
        assert response.status_code == 200, response.text
        view = response.json()
        assert [c["lineage_role"] for c in view["columns"]] == list(EXPECTED)
        assert client.post(action, json={"expected_version": 1}, headers={"Idempotency-Key": "k"}).json() == view
        assert client.post(action, json={"expected_version": 1}).status_code == 409
        assert client.post(action, json={"expected_version": 2}, headers={"Idempotency-Key": "x" * 201}).status_code == 422
        column = view["columns"][0]
        refused = client.patch(f"{url}/columns/{column['id']}", json={"expected_version": 1, "answer_format": "yes_no"})
        assert refused.status_code == 422 and "detail" in refused.json()
        assert client.get(url).json() == view
        assert client.delete(f"{url}/columns/{column['id']}?expected_version=1").status_code == 200
        assert client.post(action, json={"expected_version": 2}).status_code == 200
        before = client.get(url).json()
        refused = client.post(f"{url}/columns/{column['id']}/restore", json={"expected_version": 2})
        assert refused.status_code == 422 and "problem" in refused.json()["detail"]
        assert client.get(url).json() == before
        csrf = client.headers.pop("x-deixis-csrf")
        assert client.post(action, json={"expected_version": 3}).status_code == 403
        client.headers["x-deixis-csrf"] = csrf
        assert client.post(base + "/tbl_missing/lineage/columns", json={"expected_version": 1}).status_code == 404
        assert client.delete(url + "?expected_version=3").status_code == 200
        assert client.post(action, json={"expected_version": 3}, headers={"Idempotency-Key": "k"}).status_code == 404
        assert client.get(f"/api/researches/{rid}").json()["runs"] == []
