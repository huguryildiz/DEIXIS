"""Library view and adding a Library work to another research (D40, D41). Records are SYNTHETIC."""

from fastapi.testclient import TestClient

from deixis.storage.db import new_id, now, transaction
from test_api_flow import app_for, create, session


def seed_work(store, rid):
    """One work with a metadata-only published record and a preprint whose abstract is stored."""
    published = store.create_upload_source("SYNTHETIC packet size study")
    work_id = store.source(published)["work_id"]
    preprint = new_id("srv")
    with transaction(store.conn):
        store.conn.execute("UPDATE source_versions SET doi = '10.1/syn', venue = 'Synthetic J', year = 2021 WHERE id = ?", (published,))
        store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                           " VALUES (?, ?, 'SYNTHETIC packet size study', 'provider', 'submittedVersion', ?)", (preprint, work_id, now()))
        store._insert_passage(preprint, None, "abstract", None, None, "provider", None, None, "Packets of 128 bytes.")
    for svid in (published, preprint):
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    return work_id, published, preprint


def test_adding_a_library_work_includes_its_deepest_version_once(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        origin, target = create(client, source_scope="attached"), create(client, source_scope="attached")
        store = app.state.store
        work_id, published, preprint = seed_work(store, origin)

        response = client.post(f"/api/researches/{target}/library-sources", json={"work_id": work_id})
        assert response.status_code == 201, response.text
        body = response.json()
        # The preprint's stored abstract outranks the richer but text-less published record.
        assert (body["source_version_id"], body["access_level"]) == (preprint, "abstract")
        assert store.is_active_member(target, preprint) and not store.is_active_member(target, published)
        row = store.conn.execute("SELECT m.added_by, s.state, s.origin FROM corpus_memberships m JOIN selections s"
                                 " USING (research_id, source_version_id) WHERE m.research_id = ?", (target,)).fetchone()
        assert tuple(row) == ("library", "included", "user")
        entry = next(e for e in body["library"]["entries"] if e["work_id"] == work_id)
        assert {r["id"] for r in entry["researches"]} == {origin, target}

        again = client.post(f"/api/researches/{target}/library-sources", json={"work_id": work_id})
        assert again.status_code == 409
        assert client.post(f"/api/researches/{target}/library-sources", json={"work_id": "wrk_missing"}).status_code == 404
        assert client.post("/api/researches/res_missing/library-sources", json={"work_id": work_id}).status_code == 404
        assert raw.post(f"/api/researches/{target}/library-sources", json={"work_id": work_id},
                        headers={"x-deixis-csrf": "wrong"}).status_code == 403


from fastapi.testclient import TestClient

from deixis.storage import db
from helpers import make_pdf
from test_api_flow import app_for, create, session


def upload(client, rid, name, text):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf([text]), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def entry(client, work_id):
    return next((e for e in client.get("/api/library").json()["entries"] if e["work_id"] == work_id), None)


def test_research_purge_keeps_saved_items_and_their_files_but_removes_unsaved_ones(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        kept = upload(client, rid, "kept.pdf", "SYNTHETIC saved schedule study.")
        dropped = upload(client, rid, "dropped.pdf", "SYNTHETIC unsaved schedule study.")
        assert client.post("/api/library/items", json={"source_version_ids": [kept]}).status_code == 201
        kept_path = tmp_path / "data" / "papers" / store.conn.execute(
            "SELECT storage_path FROM source_assets WHERE source_version_id = ?", (kept,)).fetchone()[0]
        dropped_path = tmp_path / "data" / "papers" / store.conn.execute(
            "SELECT storage_path FROM source_assets WHERE source_version_id = ?", (dropped,)).fetchone()[0]

        assert client.delete(f"/api/researches/{rid}").status_code == 200  # to Trash
        # In Trash the research's works leave the Library, the saved one stays.
        assert [e["versions"][0]["source_version_id"] for e in client.get("/api/library").json()["entries"]] == [kept]
        assert client.delete(f"/api/trash/{rid}").json()["deleted"] is True

        assert store.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (dropped,)).fetchone() is None
        assert not dropped_path.exists()
        assert store.conn.execute("SELECT 1 FROM library_items WHERE source_version_id = ?", (kept,)).fetchone()
        assert kept_path.exists() and store.passages_for(kept)
        saved = entry(client, store.source(kept)["work_id"])
        assert saved["researches"] == [] and saved["access_level"] == "pdf_available"


from deixis.storage import db
from deixis.workflow.run.views import library_view
from test_lineage_store import make_library


def decide(lib, rid, svid, stage, outcome, superseded=False):
    lib.conn.execute(
        "INSERT INTO stage_decisions (id, research_id, source_version_id, stage, outcome, reason_code, decided_by, next_step,"
        " scope_revision, superseded_at, created_at) VALUES (?, ?, ?, ?, ?, 'SYNTHETIC', 'code', 'none', 1, ?, 'now')",
        (db.new_id("sdc"), rid, svid, stage, outcome, "then" if superseded else None))


def test_library_marks_relevance_per_research_from_screening_and_how_the_source_came(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    try:
        found = lib.store.create_research("SYNTHETIC search?", "academic", "quick", [], "fake", "fake-model", "en")
        for letter in ("a", "b", "c", "d", "z"):
            lib.store.add_to_corpus(found, lib.ids[letter], "search")
        decide(lib, found, lib.ids["a"], "fulltext", "include")
        decide(lib, found, lib.ids["b"], "abstract", "candidate")
        decide(lib, found, lib.ids["c"], "abstract", "candidate")
        decide(lib, found, lib.ids["c"], "fulltext", "criterion_not_met")  # read in full and set aside
        decide(lib, found, lib.ids["d"], "abstract", "out_of_scope")
        decide(lib, found, lib.ids["z"], "fulltext", "include", superseded=True)  # an old decision no longer counts

        relevant = {e["work_id"]: set(e["relevant_research_ids"]) for e in library_view(lib.store)["entries"]}
        # Every source of the first research was uploaded by the user, so each is relevant there.
        assert relevant == {"wrk_a": {lib.rid, found}, "wrk_b": {lib.rid, found}, "wrk_c": {lib.rid},
                            "wrk_d": {lib.rid}, "wrk_z": {lib.rid}}

        lib.store.remove_sources(found, [lib.ids["a"]], "SYNTHETIC removal")
        entry = next(e for e in library_view(lib.store)["entries"] if e["work_id"] == "wrk_a")
        assert entry["relevant_research_ids"] == [lib.rid]  # a removed source is relevant to no research it left
    finally:
        lib.conn.close()
