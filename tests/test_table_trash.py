"""P5 slice 3 (D50): tables, templates and columns in the trash; a single table's permanent deletion; the grouped Trash list.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows what is kept, returned and deleted; it says
nothing about cell quality.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.workflow.store import NotFound
from test_api_flow import app_for, create, session
from test_evidence_tables import PACKET_SIZE, table_with_edit
from test_table_extraction import execute, fill, library, recheck, table_version

TABLE_ROWS = ("evidence_tables", "table_rows", "table_columns", "column_revisions", "evidence_cells", "cell_revisions", "cell_evidence_links")
KEPT = ("passages", "step_inputs", "runs", "run_steps", "source_assets")


def count(conn, name, where="", params=()):
    return conn.execute(f"SELECT COUNT(*) FROM {name} {where}", params).fetchone()[0]


def worked(tmp_path):
    """A filled table with a human edit and a pending proposal."""
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    tables = lib.tables
    lib.tables.edit_cell(lib.rid, lib.tid, lib.cid, lib.no_text, "not_reported", None, "Checked the scan.", None,
                         tables.cell_view(lib.rid, lib.tid, lib.cid, lib.no_text)["version"], None)
    assert execute(lib, recheck(lib, lib.published, tables.cell_view(lib.rid, lib.tid, lib.cid, lib.published)["version"]))["status"] == "completed"
    return lib


def comparable(view):
    return {k: v for k, v in view.items() if k != "table"} | {"title": view["table"]["title"]}


# ---- tables -----------------------------------------------------------------------------------
def test_a_trashed_table_comes_back_with_its_cells_edits_and_proposals(tmp_path):
    lib = worked(tmp_path)
    tables = lib.tables
    before = tables.table_view(lib.rid, lib.tid)
    assert before["counts"]["pending_proposals"] == 1

    tables.trash_table(lib.rid, lib.tid, before["table"]["version"])
    assert tables.tables(lib.rid) == []
    with pytest.raises(NotFound):
        tables.table_view(lib.rid, lib.tid)
    trashed_version = before["table"]["version"] + 1
    with pytest.raises(RevisionConflict):
        tables.restore_table(lib.rid, lib.tid, before["table"]["version"])

    tables.restore_table(lib.rid, lib.tid, trashed_version)
    after = tables.table_view(lib.rid, lib.tid)
    assert comparable(after) == comparable(before) and after["table"]["version"] == trashed_version + 1
    with pytest.raises(NotFound):  # not in the trash
        tables.restore_table(lib.rid, lib.tid, after["table"]["version"])
    events = [e["type"] for e in lib.store.events_after(lib.rid, 0)]
    assert "table_trashed" in events and "table_restored" in events


def test_a_table_run_blocks_trashing_and_a_trashed_research_blocks_restoring(tmp_path):
    lib = library(tmp_path)
    run = fill(lib)
    with pytest.raises(RevisionConflict):
        lib.tables.trash_table(lib.rid, lib.tid, table_version(lib))
    lib.store.update_run(run["id"], status="cancelled")
    version = table_version(lib)
    lib.tables.trash_table(lib.rid, lib.tid, version)
    lib.store.trash_research(lib.rid)
    with pytest.raises(NotFound):
        lib.tables.restore_table(lib.rid, lib.tid, version + 1)
    with pytest.raises(NotFound):  # it goes with its research
        lib.tables.purge_table(lib.tid)


def test_purging_one_table_deletes_only_that_table_and_keeps_passages_step_inputs_and_runs(tmp_path):
    lib = worked(tmp_path)
    tables, conn = lib.tables, lib.conn
    other = tables.create_table(lib.rid, "Other", None, None, None)
    column = tables.add_column(lib.rid, other, PACKET_SIZE, 1, None)
    tables.edit_cell(lib.rid, other, column, lib.no_text, "unknown", None, None, None, 0, None)
    kept = {name: count(conn, name) for name in KEPT}
    other_rows = {name: count(conn, name) for name in TABLE_ROWS}

    with pytest.raises(NotFound):  # not in the trash
        tables.purge_table(lib.tid)
    tables.trash_table(lib.rid, lib.tid, table_version(lib))
    run = lib.store.create_run(lib.rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    with pytest.raises(RevisionConflict):
        tables.purge_table(lib.tid)
    lib.store.update_run(run["id"], status="cancelled")
    kept["runs"] += 1

    result = tables.purge_table(lib.tid)
    assert result["cells"] == 3 and result["human_edits"] == 1
    assert {name: count(conn, name) for name in KEPT} == kept
    assert count(conn, "evidence_tables", "WHERE id = ?", (lib.tid,)) == 0
    assert count(conn, "evidence_cells", "WHERE table_id = ?", (lib.tid,)) == 0
    assert count(conn, "table_columns", "WHERE table_id = ?", (lib.tid,)) == 0
    assert count(conn, "evidence_cells", "WHERE table_id = ?", (other,)) == 1 and count(conn, "table_purge_authorizations") == 0
    assert other_rows["evidence_tables"] - 1 == count(conn, "evidence_tables")
    with pytest.raises(sqlite3.IntegrityError):  # the authorization is gone again
        conn.execute("DELETE FROM cell_revisions WHERE cell_id IN (SELECT id FROM evidence_cells WHERE table_id = ?)", (other,))
    assert "table_purged" in [e["type"] for e in lib.store.events_after(lib.rid, 0)]


# ---- columns and templates --------------------------------------------------------------------
def test_a_removed_column_comes_back_with_its_cells(tmp_path):
    lib = worked(tmp_path)
    tables = lib.tables
    column = next(c for c in tables.table_view(lib.rid, lib.tid)["columns"] if c["id"] == lib.cid)
    cells = [c for c in tables.table_view(lib.rid, lib.tid)["cells"] if c["column_id"] == lib.cid]
    tables.remove_column(lib.rid, lib.tid, lib.cid, column["version"])
    tables.add_column(lib.rid, lib.tid, PACKET_SIZE, table_version(lib), None)  # a new column with the same name

    with pytest.raises(RevisionConflict):
        tables.restore_column(lib.rid, lib.tid, lib.cid, column["version"])
    tables.restore_column(lib.rid, lib.tid, lib.cid, column["version"] + 1)
    view = tables.table_view(lib.rid, lib.tid)
    assert [c["name"] for c in view["columns"]] == ["Packet size", "Packet size"]
    assert [c for c in view["cells"] if c["column_id"] == lib.cid] == cells
    with pytest.raises(NotFound):  # not removed
        tables.restore_column(lib.rid, lib.tid, lib.cid, column["version"] + 2)


def test_a_template_is_restored_or_purged_from_the_trash(tmp_path):
    lib = library(tmp_path)
    tables = lib.tables
    template = tables.create_template(lib.rid, lib.tid, "Packets", None)
    made = tables.create_table(lib.rid, "From template", None, template, None)
    with pytest.raises(NotFound):
        tables.restore_template(template)
    with pytest.raises(NotFound):
        tables.purge_template(template)
    tables.trash_template(template)
    tables.restore_template(template)
    assert [t["id"] for t in tables.templates()] == [template]
    tables.trash_template(template)
    assert tables.purge_template(template) == {"tables_unlinked": 1}
    assert count(lib.conn, "table_templates") == 0
    assert tables.table_view(lib.rid, made)["table"]["template_id"] is None
    assert [c["origin"] for c in tables.table_view(lib.rid, made)["columns"]] == ["template"]


# ---- the Trash list and the API ---------------------------------------------------------------
def test_trash_lists_researches_tables_removed_sources_and_templates_with_what_they_hold(tmp_path):
    lib = worked(tmp_path)
    store, tables = lib.store, lib.tables
    template = tables.create_template(lib.rid, lib.tid, "Packets", None)
    tables.trash_template(template)
    store.remove_sources(lib.rid, [lib.no_text], "SYNTHETIC scan")
    tables.trash_table(lib.rid, lib.tid, table_version(lib))

    trash = store.trash()
    assert trash["researches"] == []
    (table,) = trash["tables"]
    assert (table["id"], table["research_id"], table["research_title"]) == (lib.tid, lib.rid, store.research(lib.rid)["title"])
    assert (table["rows"], table["columns"], table["cells"], table["human_edits"]) == (3, 1, 3, 1)
    (source,) = trash["sources"]
    assert (source["source_version_id"], source["research_id"], source["removal_note"], source["cells"], source["quotes"]) == (
        lib.no_text, lib.rid, "SYNTHETIC scan", 1, 0)
    assert [(t["id"], t["columns"]) for t in trash["templates"]] == [(template, 1)]

    store.trash_research(lib.rid)
    trash = store.trash()
    assert [r["id"] for r in trash["researches"]] == [lib.rid]
    assert trash["tables"] == [] and trash["sources"] == []  # they go and come back with their research


def test_table_template_and_column_trash_api(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        tid = table_with_edit(client, rid)
        base = f"/api/researches/{rid}/tables/{tid}"
        view = client.get(base).json()
        column = view["columns"][0]

        removed = client.delete(f"{base}/columns/{column['id']}", params={"expected_version": column["version"]}).json()
        assert removed["columns"] == []
        wrong = {"x-deixis-csrf": "wrong"}
        assert raw.post(f"{base}/columns/{column['id']}/restore", json={"expected_version": column["version"] + 1}, headers=wrong).status_code == 403
        assert client.post(f"{base}/columns/{column['id']}/restore", json={"expected_version": column["version"]}).status_code == 409
        restored = client.post(f"{base}/columns/{column['id']}/restore", json={"expected_version": column["version"] + 1})
        assert restored.status_code == 200 and restored.json()["cells"] == view["cells"]

        version = client.get(base).json()["table"]["version"]
        assert client.delete(base, params={"expected_version": version}).json() == {"trashed": True}
        assert client.delete(f"/api/trash/tables/{tid}", headers=wrong).status_code == 403
        assert [t["id"] for t in client.get("/api/trash").json()["tables"]] == [tid]
        assert client.post(f"{base}/restore", json={"expected_version": version}).status_code == 409
        back = client.post(f"{base}/restore", json={"expected_version": version + 1})
        assert back.status_code == 200 and back.json()["cells"] == view["cells"]
        assert client.delete(f"/api/trash/tables/{tid}").status_code == 404  # not in the trash

        client.delete(base, params={"expected_version": back.json()["table"]["version"]})
        purged = client.delete(f"/api/trash/tables/{tid}")
        assert purged.status_code == 200 and purged.json() == {"deleted": True, "cells": 1, "human_edits": 1}
        assert client.get("/api/trash").json()["tables"] == []

        other = table_with_edit(client, rid)
        template_id = client.post("/api/table-templates", json={"name": "Packets", "research_id": rid, "table_id": other}).json()["id"]
        assert client.delete(f"/api/table-templates/{template_id}").json() == {"trashed": True}
        assert [t["id"] for t in client.get("/api/trash").json()["templates"]] == [template_id]
        assert client.post(f"/api/table-templates/{template_id}/restore").json() == {"restored": True}
        client.delete(f"/api/table-templates/{template_id}")
        assert client.delete(f"/api/trash/templates/{template_id}").json() == {"deleted": True, "tables_unlinked": 0}
        assert client.delete(f"/api/trash/templates/{template_id}").status_code == 404

        assert client.get("/api/trash").json()["researches"] == []
        assert count(app.state.store.conn, "evidence_tables", "WHERE id = ?", (tid,)) == 0
