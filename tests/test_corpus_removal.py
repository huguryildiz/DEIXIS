"""P5 slice 3 (D50): a source removed from a research leaves its lists and new work, while its evidence keeps opening.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows which stored rows each view and model input
reads after a removal; it says nothing about answer or cell quality.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.store import NotASource
from deixis.workflow.views import library_view, passage_view, research_view
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_evidence_tables import PACKET_SIZE
from test_source_versions import library_at
from test_table_extraction import cell, execute, fill, library


def mark_removed(store, rid, *svids):
    """Step 1 writes the removal directly; Store.remove_sources comes in step 2."""
    with db.transaction(store.conn):
        store.conn.executemany("UPDATE corpus_memberships SET removed_at = ? WHERE research_id = ? AND source_version_id = ?",
                               [(db.now(), rid, svid) for svid in svids])


def upload(client, rid, name, text):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf([text]), "application/pdf")})
    assert response.status_code == 201, response.text
    return next(s for s in response.json()["sources"] if s["access"]["assets"] and s["access"]["assets"][0]["original_filename"] == name)


# ---- migration 29 ---------------------------------------------------------------------------
def test_migration_on_a_library_written_at_28_keeps_memberships_and_guards_evidence_deletes(tmp_path, monkeypatch):
    conn, store = library_at(tmp_path, monkeypatch, 28)
    rid = store.create_research("SYNTHETIC question", "attached", "quick", [], "fake", "fake-model", None)
    svids = [store.create_upload_source(f"SYNTHETIC source {n}") for n in range(3)]
    with db.transaction(conn):  # rows as code at 28 wrote them
        for svid in svids:
            conn.execute("INSERT INTO corpus_memberships (research_id, source_version_id, added_by, created_at) VALUES (?, ?, 'user_upload', ?)",
                         (rid, svid, db.now()))
    assert 29 in db.migrate(conn)
    rows = conn.execute("SELECT removed_at, removal_note FROM corpus_memberships WHERE research_id = ?", (rid,)).fetchall()
    assert [tuple(r) for r in rows] == [(None, None)] * 3
    assert conn.execute("SELECT COUNT(*) FROM table_purge_authorizations").fetchone()[0] == 0
    triggers = dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN"
                                 " ('column_revisions_no_delete', 'cell_revisions_no_delete', 'cell_evidence_links_no_delete')").fetchall())
    assert len(triggers) == 3 and all("table_purge_authorizations" in sql and "research_purge_authorizations" in sql for sql in triggers.values())


def test_a_table_purge_authorization_opens_the_delete_triggers_for_that_table_only(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    other = lib.tables.create_table(lib.rid, "Other", None, None, None)
    lib.tables.add_column(lib.rid, other, PACKET_SIZE, 1, None)
    lib.tables.edit_cell(lib.rid, other, lib.tables._columns(other)[0]["id"], lib.no_text, "unknown", None, None, None, 0, None)
    conn = lib.conn
    revisions = "SELECT r.id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE c.table_id = ?"
    with db.transaction(conn):
        conn.execute("INSERT INTO table_purge_authorizations VALUES (?)", (lib.tid,))
        conn.execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE table_id = ?", (lib.tid,))
        conn.execute(f"DELETE FROM cell_evidence_links WHERE cell_revision_id IN ({revisions})", (lib.tid,))
        conn.execute(f"DELETE FROM cell_revisions WHERE id IN ({revisions})", (lib.tid,))
        conn.execute("DELETE FROM column_revisions WHERE column_id IN (SELECT id FROM table_columns WHERE table_id = ?)", (lib.tid,))
    assert conn.execute(f"SELECT COUNT(*) FROM ({revisions})", (lib.tid,)).fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"DELETE FROM cell_revisions WHERE id IN ({revisions})", (other,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM column_revisions WHERE column_id IN (SELECT id FROM table_columns WHERE table_id = ?)", (other,))


def test_a_research_purge_still_deletes_its_tables(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert lib.conn.execute("SELECT COUNT(*) FROM cell_revisions").fetchone()[0] == 0


# ---- active and past membership -------------------------------------------------------------
def test_a_removed_work_leaves_lists_answers_pdf_collection_and_fills_but_its_cells_and_passages_still_open(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    store, tables = lib.store, lib.tables
    passage = next(p for p in store.passages_for(lib.published) if p["kind"] == "pdf_page")
    evidence = cell(lib, lib.published)["current"]

    mark_removed(store, lib.rid, lib.published, lib.preprint)
    assert store.is_active_member(lib.rid, lib.no_text) and not store.is_active_member(lib.rid, lib.published)
    assert store.was_member(lib.rid, lib.published) and not store.was_member(lib.rid, "srv_missing")
    assert set(store.included_sources(lib.rid)) == {lib.no_text}
    assert store.included_works(lib.rid) == [lib.no_text]  # the answer and PDF collection read included works
    assert lib.published not in store.work_heads(lib.rid).values()
    assert store.work_versions(lib.rid, lib.no_text) == []

    column = tables.add_column(lib.rid, lib.tid, PACKET_SIZE | {"name": "Second size"}, tables.table_view(lib.rid, lib.tid)["table"]["version"], None)
    planned = {s["source_version_id"] for s in tables.fill_plan(lib.rid, lib.tid, [column])["sources"]}
    assert planned == {lib.no_text}
    view = tables.table_view(lib.rid, lib.tid)
    assert {r["source_version_id"] for r in view["rows"]} == {lib.no_text} and view["removed_rows"] == []
    assert tables.tables(lib.rid)[0]["rows"] == 1
    assert lib.published not in {c["source_version_id"] for c in view["cells"]}
    assert cell(lib, lib.published)["current"] == evidence  # the cell and its evidence are kept and still open

    assert lib.published not in {s["source_version_id"] for s in research_view(store, lib.rid)["sources"]}
    assert passage_view(store, lib.rid, passage["id"]) is not None
    entry = next(e for e in library_view(store)["entries"] if e["work_id"] == store.source(lib.published)["work_id"])
    assert entry["researches"] == []  # the library record stays; it is in no project group
    assert {s["source_version_id"] for s in store.quick_search("SYNTHETIC")["sources"]} == {lib.no_text}


def test_a_removed_source_is_not_given_to_the_answer_and_its_quote_and_cited_pdf_still_open(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        cited = upload(client, rid, "cited.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        quote = view["answers"][0]["claims"][0]["evidence"][0]
        assert quote["source_version_id"] == cited["source_version_id"] and quote["removed_from_research"] is False
        assert client.get(f"/api/researches/{rid}/passages/{quote['passage_id']}").json()["removed_from_research"] is False
        uncited = upload(client, rid, "uncited.pdf", "SYNTHETIC second molecule release report.")

        mark_removed(store, rid, cited["source_version_id"], uncited["source_version_id"])
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).status_code == 422
        passage = client.get(f"/api/researches/{rid}/passages/{quote['passage_id']}")
        assert passage.status_code == 200 and passage.json()["removed_from_research"] is True  # the quote and passage say so (D50)
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["claims"][0]["evidence"][0]["removed_from_research"] is True
        assert client.get(f"/api/researches/{rid}/assets/{cited['access']['assets'][0]['id']}").status_code == 200
        assert client.get(f"/api/researches/{rid}/assets/{uncited['access']['assets'][0]['id']}").status_code == 404
        assert client.get("/api/search", params={"q": "cited"}).json()["sources"] == []

        with db.transaction(store.conn):
            store.conn.execute("UPDATE corpus_memberships SET removed_at = NULL WHERE source_version_id = ?", (uncited["source_version_id"],))
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        assert view["answers"][0]["inputs_given"]["source_ids"] == [uncited["source_version_id"]]


# ---- removing and restoring (T15) -----------------------------------------------------------
def search_found_again(store, rid, svid):
    """A later discovery search that returns the removed source's record again."""
    with db.transaction(store.conn):
        run = store.conn.execute("SELECT id FROM runs WHERE research_id = ? LIMIT 1", (rid,)).fetchone()
    run_id = run["id"] if run else store.create_run(rid, "discovery", {"max_model_calls": 0, "max_provider_requests": 1}, None)["id"]
    step = store.step(run_id, "search:again", "search")
    srid = store.add_search_run(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex",
                                query_text="SYNTHETIC", request_description="SYNTHETIC", access_mode="open", status="completed",
                                result_count=1, page_limit=1)
    store.add_to_corpus(rid, svid, "search", srid, 0, scope_revision=1)
    with db.transaction(store.conn):
        store.conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (run_id,))


def removed(store, rid):
    return {r[0] for r in store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL", (rid,))}


def test_removing_a_work_head_removes_its_versions_and_restoring_brings_back_rows_and_selection(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    store, tables = lib.store, lib.tables
    revision = store.selection_revision(lib.rid)
    cells_before = tables.table_view(lib.rid, lib.tid)["cells"]

    assert store.remove_sources(lib.rid, [lib.preprint], None) == [lib.preprint]  # not the head: removed alone
    assert removed(store, lib.rid) == {lib.preprint} and store.selection_revision(lib.rid) == revision + 1
    assert store.restore_sources(lib.rid, [lib.preprint]) == [lib.preprint]
    assert removed(store, lib.rid) == set() and store.selection_revision(lib.rid) == revision + 2

    assert set(store.remove_sources(lib.rid, [lib.published], "wrong upload")) == {lib.published, lib.preprint}
    assert store.selection_revision(lib.rid) == revision + 3
    note = store.conn.execute("SELECT removal_note FROM corpus_memberships WHERE source_version_id = ?", (lib.published,)).fetchone()[0]
    assert note == "wrong upload"
    assert {r["source_version_id"] for r in tables.table_view(lib.rid, lib.tid)["rows"]} == {lib.no_text}
    assert {s["source_version_id"] for s in tables.fill_plan(lib.rid, lib.tid, include_stale=True)["sources"]} <= {lib.no_text}
    assert store.remove_sources(lib.rid, [lib.published], None) == []  # already removed
    events = [e["type"] for e in store.events_after(lib.rid, 0)]
    assert events.count("source_removed") == 2 and events.count("source_restored") == 1

    assert set(store.restore_sources(lib.rid, [lib.preprint])) == {lib.published, lib.preprint}  # the work comes back whole
    assert store.selection_revision(lib.rid) == revision + 4
    assert tables.table_view(lib.rid, lib.tid)["cells"] == cells_before
    assert set(store.included_works(lib.rid)) == {lib.published, lib.no_text}


def test_removal_is_refused_for_a_non_member_and_during_a_run(tmp_path):
    lib = library(tmp_path)
    with pytest.raises(NotASource):
        lib.store.remove_sources(lib.rid, [lib.published, "srv_missing"], None)
    with pytest.raises(NotASource):
        lib.store.restore_sources(lib.rid, ["srv_missing"])
    assert removed(lib.store, lib.rid) == set()
    run = fill(lib)
    with pytest.raises(RevisionConflict):
        lib.store.remove_sources(lib.rid, [lib.published], None)
    lib.store.update_run(run["id"], status="cancelled")
    lib.store.remove_sources(lib.rid, [lib.no_text], None)
    lib.store.create_run(lib.rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    with pytest.raises(RevisionConflict):
        lib.store.restore_sources(lib.rid, [lib.no_text])


def test_a_later_search_leaves_a_removed_source_removed_and_counts_it(tmp_path):
    lib = library(tmp_path)
    store = lib.store
    store.remove_sources(lib.rid, [lib.published], None)
    counts = research_view(store, lib.rid)["counts"]
    assert (counts["removed"], counts["removed_found_again"]) == (1, 0)

    search_found_again(store, lib.rid, lib.published)
    assert removed(store, lib.rid) == {lib.published, lib.preprint}
    assert store.conn.execute("SELECT 1 FROM candidates WHERE research_id = ? AND source_version_id = ?", (lib.rid, lib.published)).fetchone()
    view = research_view(store, lib.rid)
    assert lib.published not in {s["source_version_id"] for s in view["sources"]}
    assert (view["counts"]["removed"], view["counts"]["removed_found_again"]) == (1, 1)

    other = store.create_upload_source("SYNTHETIC packet size accepted manuscript")
    with db.transaction(store.conn):  # a new version of the removed work, found by that search
        store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (store.source(lib.published)["work_id"], other))
    store.add_to_corpus(lib.rid, other, "search", candidate=False)
    assert other in removed(store, lib.rid)

    store.restore_sources(lib.rid, [lib.published])
    assert removed(store, lib.rid) == {other}  # it was not removed together with the work
    assert research_view(store, lib.rid)["counts"]["removed_found_again"] == 1


def test_remove_and_restore_api_and_shared_files(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        a = create(client, source_scope="attached")
        source = upload(client, a, "shared.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        svid, asset = source["source_version_id"], source["access"]["assets"][0]["id"]
        b = create(client, question="SYNTHETIC research B", source_scope="attached")
        assert upload(client, b, "shared.pdf", "SYNTHETIC uploaded molecule schedule notes.")["source_version_id"] == svid
        path = tmp_path / "data" / "papers" / store.asset(asset)["storage_path"]
        fingerprint = lambda: (store.asset(asset)["sha256"], [p["id"] for p in store.passages_for(svid)], path.read_bytes())  # noqa: E731
        before = fingerprint()

        url = f"/api/researches/{a}/sources"
        assert raw.request("DELETE", url, json={"source_version_ids": [svid]}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        assert client.request("DELETE", url, json={"source_version_ids": ["srv_missing"]}).status_code == 422
        response = client.request("DELETE", url, json={"source_version_ids": [svid], "note": "SYNTHETIC wrong file"})
        assert response.status_code == 200, response.text
        assert response.json()["sources"] == [] and response.json()["counts"]["removed"] == 1
        assert fingerprint() == before
        assert [s["source_version_id"] for s in client.get(f"/api/researches/{b}").json()["sources"]] == [svid]
        assert client.get(f"/api/researches/{b}/assets/{asset}").status_code == 200
        assert {r["id"] for r in next(e for e in client.get("/api/library").json()["entries"])["researches"]} == {b}

        assert raw.post(f"{url}/restore", json={"source_version_ids": [svid]}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        restored = client.post(f"{url}/restore", json={"source_version_ids": [svid]})
        assert restored.status_code == 200 and [s["source_version_id"] for s in restored.json()["sources"]] == [svid]

        # B removes it, A is deleted permanently: B's removed membership still counts as a use, so the file stays.
        assert client.request("DELETE", f"/api/researches/{b}/sources", json={"source_version_ids": [svid]}).status_code == 200
        assert client.delete(f"/api/researches/{a}").status_code == 200
        assert client.delete(f"/api/trash/{a}").json()["files_not_removed"] == []
        assert path.exists() and fingerprint() == before
        assert client.post(f"/api/researches/{b}/sources/restore", json={"source_version_ids": [svid]}).status_code == 200


def test_adding_one_removed_source_on_purpose_restores_it(tmp_path):
    """A single deliberate add (the same file uploaded again, the work dragged from the Library) brings the source back
    with the versions removed with it; a bulk add (search, Zotero collection) does not."""
    from test_library import seed_work
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        source = upload(client, rid, "notes.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        store.remove_sources(rid, [source["source_version_id"]], None)
        revision = store.selection_revision(rid)
        again = upload(client, rid, "notes.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        assert again["source_version_id"] == source["source_version_id"] and removed(store, rid) == set()
        assert store.selection_revision(rid) == revision + 1
        assert [e["type"] for e in store.events_after(rid, 0)].count("source_restored") == 1

        work_id, published, preprint = seed_work(store, rid)
        store.remove_sources(rid, [published], None)
        response = client.post(f"/api/researches/{rid}/library-sources", json={"work_id": work_id})
        assert response.status_code == 201, response.text
        assert response.json()["source_version_id"] == published and response.json()["restored"] is True
        assert removed(store, rid) == set()
        assert client.post(f"/api/researches/{rid}/library-sources", json={"work_id": work_id}).status_code == 409


# ---- deleting a removed source permanently (D65) ---------------------------------------------
def test_purging_a_removed_source_clears_this_research_and_frees_the_file_once_no_one_else_holds_it(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        a = create(client, source_scope="attached")
        source = upload(client, a, "shared.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        svid, asset = source["source_version_id"], source["access"]["assets"][0]["id"]
        b = create(client, question="SYNTHETIC research B", source_scope="attached")
        assert upload(client, b, "shared.pdf", "SYNTHETIC uploaded molecule schedule notes.")["source_version_id"] == svid
        path = tmp_path / "data" / "papers" / store.asset(asset)["storage_path"]

        purge_a = f"/api/researches/{a}/sources/purge"
        assert raw.post(purge_a, json={"source_version_ids": [svid]}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        assert client.post(purge_a, json={"source_version_ids": [svid]}).json()["deleted"] == []  # an active source is not purged

        assert client.request("DELETE", f"/api/researches/{a}/sources", json={"source_version_ids": [svid]}).status_code == 200
        response = client.post(purge_a, json={"source_version_ids": [svid]})
        assert response.status_code == 200 and response.json() == {"deleted": [svid], "files_not_removed": []}
        assert not store.was_member(a, svid) and client.get("/api/trash").json()["sources"] == []
        assert path.exists() and store.passages_for(svid)  # research B still holds the source, so its record and file stay
        assert [s["source_version_id"] for s in client.get(f"/api/researches/{b}").json()["sources"]] == [svid]
        assert {r["id"] for r in client.get("/api/library").json()["entries"][0]["researches"]} == {b}

        assert client.request("DELETE", f"/api/researches/{b}/sources", json={"source_version_ids": [svid]}).status_code == 200
        assert client.post(f"/api/researches/{b}/sources/purge", json={"source_version_ids": [svid]}).json() == {"deleted": [svid], "files_not_removed": []}
        assert not path.exists() and store.passages_for(svid) == []
        assert client.get("/api/library").json()["entries"] == [] and client.get("/api/trash").json()["sources"] == []
        assert store.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (svid,)).fetchone() is None


def test_a_removed_source_an_answer_quotes_is_kept_and_the_trash_row_says_it_is_cited(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        cited = upload(client, rid, "cited.pdf", "SYNTHETIC uploaded molecule schedule notes.")
        svid = cited["source_version_id"]
        _, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200

        row = next(s for s in client.get("/api/trash").json()["sources"] if s["source_version_id"] == svid)
        assert row["quotes"] > 0 and row["cited"] == 1
        response = client.post(f"/api/researches/{rid}/sources/purge", json={"source_version_ids": [svid]})
        assert response.status_code == 409, response.text
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["claims"][0]["evidence"][0]["source_version_id"] == svid
        assert client.get(f"/api/researches/{rid}/assets/{cited['access']['assets'][0]['id']}").status_code == 200
