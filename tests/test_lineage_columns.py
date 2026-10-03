"""L1 role boundaries on synthetic temporary libraries; no providers or real models."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.skill import load_skill_package
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.report.snapshot import build_snapshot
from deixis.workflow.store import Store
from deixis.workflow.tables import InvalidTableInput, LINEAGE_ROLE_COLUMNS, TableStore, report_ready
from fakes import FakeAdapter
from test_api_flow import create, session
from test_report_snapshot import _fill


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


def test_add_development_columns_adds_three_text_columns_with_roles(lib):
    lib.tables.add_column(lib.rid, lib.tid, TEXT, version(lib), None)
    before = version(lib)
    events = lib.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    add(lib, "k")
    view = lib.tables.table_view(lib.rid, lib.tid)
    assert LINEAGE_ROLE_COLUMNS == EXPECTED
    assert view["columns"][0]["lineage_role"] is None
    assert [c["position"] for c in view["columns"]] == [0, 1, 2, 3]
    for column, role in zip(view["columns"][1:], EXPECTED, strict=True):
        assert column["lineage_role"] == role
        assert (column["name"], column["instruction"]) == EXPECTED[role]
        assert column["answer_format"] == "text" and column["origin"] == "user"
    assert version(lib) == before + 1
    assert lib.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events + 1
    assert {r[0] for r in lib.conn.execute("SELECT idempotency_key FROM column_revisions WHERE idempotency_key IS NOT NULL")} == {
        f"lineage-columns:{lib.rid}:{lib.tid}:k:{role}" for role in EXPECTED}


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


@pytest.mark.parametrize("action_first", [False, True], ids=["ordinary-first", "action-first"])
@pytest.mark.parametrize("cross_table", [False, True], ids=["same-table", "across-tables"])
def test_add_development_columns_replay_namespace_is_disjoint_from_ordinary_keys(lib, action_first, cross_table):
    ordinary_tid = lib.tables.create_table(lib.rid, "Ordinary", None, None, None) if cross_table else lib.tid
    key = f"lineage-columns:{lib.tid}:k:problem"
    if action_first:
        add(lib, "k")
    cid = lib.tables.add_column(lib.rid, ordinary_tid, TEXT, version(lib, ordinary_tid), key)
    if not action_first:
        add(lib, "k")
    assert len([c for c in columns(lib) if c["lineage_role"]]) == 3
    assert lib.tables._column(ordinary_tid, cid)["lineage_role"] is None
    assert lib.tables.add_column(lib.rid, ordinary_tid, TEXT, 0, key) == cid
    assert lib.conn.execute("SELECT idempotency_key FROM column_revisions WHERE column_id = ?", (cid,)).fetchone()[0] == f"{lib.rid}:{key}"
    before = database_state(lib)
    add(lib, "k")
    assert database_state(lib) == before


def test_add_development_columns_adds_only_missing_roles(lib):
    add(lib)
    old = columns(lib)
    for column in old[1:]:
        remove(lib, column)
    add(lib, "missing")
    active = columns(lib)
    assert [c["lineage_role"] for c in active] == list(EXPECTED)
    assert active[0]["id"] == old[0]["id"]
    assert [c["position"] for c in active] == [0, 3, 4]
    assert len(columns(lib, removed=True)) == 5


def test_add_development_columns_is_atomic(lib, monkeypatch):
    original = lib.tables._insert_column
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-insert failure")
        return original(*args, **kwargs)
    before = database_state(lib)
    monkeypatch.setattr(lib.tables, "_insert_column", fail_second)
    with pytest.raises(RuntimeError, match="second-insert"):
        add(lib, "atomic")
    assert database_state(lib) == before
    monkeypatch.setattr(lib.tables, "_insert_column", original)
    add(lib, "atomic")
    assert len(columns(lib)) == 3


def test_role_survives_rename_move_and_instruction_change(lib):
    sid = lib.store.create_upload_source("Synthetic packet study")
    pid = lib.store._insert_passage(sid, None, "abstract", None, None, "provider", None, None, "The study uses 128-byte packets.")
    lib.store.add_to_corpus(lib.rid, sid, "user_upload", selection_state="included", selection_origin="user")
    lib.tables.add_rows(lib.rid, lib.tid, [sid], version(lib))
    add(lib)
    cid = columns(lib)[0]["id"]
    _fill((lib.store, None, lib.tables, lib.rid, sid, pid, lib.tid, cid))
    lib.tables.revise_column(lib.rid, lib.tid, cid, {}, 2, 1)
    column = lib.tables._column(lib.tid, cid)
    assert column["lineage_role"] == "problem" and column["position"] == 2 and column["current_revision"] == 1
    assert "stale_column" not in lib.tables.cell_view(lib.rid, lib.tid, cid, sid)["flags"]
    for change in ({"name": "Renamed problem"}, {"instruction": "Changed instruction"}):
        lib.tables.revise_column(lib.rid, lib.tid, cid, change, None, column["version"])
        column = lib.tables._column(lib.tid, cid)
        assert column["lineage_role"] == "problem"
        assert "stale_column" in lib.tables.cell_view(lib.rid, lib.tid, cid, sid)["flags"]
    assert column["current_revision"] == 3


@pytest.mark.parametrize("fmt", ["choice", "number_unit", "yes_no"])
def test_role_column_rejects_non_text_format(lib, fmt):
    add(lib)
    column = columns(lib)[0]
    before = database_state(lib)
    with pytest.raises(InvalidTableInput, match="text column"):
        lib.tables.revise_column(lib.rid, lib.tid, column["id"], {"answer_format": fmt}, 2, column["version"])
    assert database_state(lib) == before
    lib.tables.revise_column(lib.rid, lib.tid, column["id"], {"answer_format": "text", "name": "Renamed"}, None, column["version"])
    assert lib.tables._column(lib.tid, column["id"])["lineage_role"] == "problem"


def test_restore_conflicts_with_active_role_column(lib):
    add(lib)
    old = columns(lib)[0]
    remove(lib, old)
    add(lib)
    before = database_state(lib)
    with pytest.raises(InvalidTableInput, match="active column already holds the problem role"):
        lib.tables.restore_column(lib.rid, lib.tid, old["id"], old["version"] + 1)
    assert database_state(lib) == before


def test_restore_without_conflict_works(lib):
    add(lib)
    old = columns(lib)[0]
    remove(lib, old)
    add(lib)
    replacement = next(c for c in columns(lib) if c["lineage_role"] == "problem")
    remove(lib, replacement)
    lib.tables.restore_column(lib.rid, lib.tid, old["id"], old["version"] + 1)
    restored = lib.tables._column(lib.tid, old["id"])
    assert restored["lineage_role"] == "problem" and restored["current_revision"] == 1
    assert len(columns(lib)) == 3


def test_templates_and_user_columns_carry_no_role(lib):
    add(lib)
    template = lib.tables.create_template(lib.rid, lib.tid, "Saved roles as ordinary columns", None)
    specs = json.loads(lib.conn.execute("SELECT columns_json FROM table_templates WHERE id = ?", (template,)).fetchone()[0])
    assert len(specs) == 3 and all("lineage_role" not in spec for spec in specs)
    tid = lib.tables.create_table(lib.rid, "From template", None, template, None)
    assert len(columns(lib, tid=tid)) == 3 and all(c["lineage_role"] is None for c in columns(lib, tid=tid))
    empty = lib.tables.create_table(lib.rid, "Apply template", None, None, None)
    lib.tables.apply_template(lib.rid, empty, template, 1, "apply")
    assert len(columns(lib, tid=empty)) == 3 and all(c["lineage_role"] is None for c in columns(lib, tid=empty))
    cid = lib.tables.add_column(lib.rid, lib.tid, TEXT, version(lib), None)
    assert lib.tables._column(lib.tid, cid)["lineage_role"] is None
    run = lib.store.create_run(lib.rid, "table_columns", {}, None, {"table_id": lib.tid})
    step = lib.store.step(run["id"], "suggestion", "model:table_columns")
    lib.store.finish_step(step["id"], "succeeded")
    suggested = lib.tables.add_column(lib.rid, lib.tid, TEXT, version(lib), None, origin="model_suggestion", suggestion_step_id=step["id"])
    assert lib.tables._column(lib.tid, suggested)["lineage_role"] is None


def test_development_columns_are_ordinary_columns_to_the_report(lib):
    """Record the known §4.2 report interaction, not a defect fix."""
    sid = lib.store.create_upload_source("Synthetic packet study")
    pid = lib.store._insert_passage(sid, None, "abstract", None, None, "provider", None, None, "The study uses 128-byte packets.")
    lib.store.add_to_corpus(lib.rid, sid, "user_upload", selection_state="included", selection_origin="user")
    lib.tables.add_rows(lib.rid, lib.tid, [sid], version(lib))
    cid = lib.tables.add_column(lib.rid, lib.tid, TEXT, version(lib), None)
    _fill((lib.store, None, lib.tables, lib.rid, sid, pid, lib.tid, cid))
    assert report_ready(lib.store, lib.rid, lib.tid)["ready"]
    add(lib)
    role_columns = [c for c in columns(lib) if c["lineage_role"]]
    readiness = report_ready(lib.store, lib.rid, lib.tid)
    assert not readiness["ready"]
    assert readiness["missing"] == [{"source_version_id": sid, "column_id": c["id"]} for c in role_columns]
    snapshot = build_snapshot(lib.store, lib.rid, lib.tid)
    assert [c["column_id"] for c in snapshot["columns"]] == [c["id"] for c in columns(lib)]


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


def test_skill_package_hash_unchanged_by_l1():
    # L1 left the package untouched at its own commit; P8 B1 adds the owner-review method.
    assert load_skill_package().package_hash == "sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff"
