"""Library-owned items (UI parity S19a, F14): the Library view unions saved items with research works, versions stay
separate, and research purge, source purge and backup/restore keep saved items. Records are SYNTHETIC."""

from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.store import Store
from helpers import make_pdf
from test_api_flow import app_for, create, session
from test_library import seed_work


def upload(client, rid, name, text):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf([text]), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def library_upload(client, name, text):
    response = client.post("/api/library/uploads", files={"file": (name, make_pdf([text]), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


def entry(client, work_id):
    return next((e for e in client.get("/api/library").json()["entries"] if e["work_id"] == work_id), None)


def test_saved_versions_stay_separate_and_the_view_unions_library_only_items(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(store, rid)

        response = client.post("/api/library/items", json={"source_version_ids": [published, preprint]})
        assert response.status_code == 201, response.text
        assert response.json()["saved"] == [published, preprint]
        rows = store.conn.execute("SELECT source_version_id, origin, metadata_origin FROM library_items"
                                  " ORDER BY source_version_id").fetchall()
        # Two versions of one work are two saved items; the uploaded record's fields are the person's, the
        # provider record's the provider's.
        assert sorted(tuple(r) for r in rows) == sorted([(published, "saved", "user_supplied"),
                                                         (preprint, "saved", "provider")])
        saved = entry(client, work_id)
        assert saved["saved"] is True and [r["id"] for r in saved["researches"]] == [rid]
        assert {v["source_version_id"]: v["library_item"]["origin"] for v in saved["versions"]} == {
            published: "saved", preprint: "saved"}
        assert len(saved["versions"]) == 2

        only = library_upload(client, "library_only_notes.pdf", "SYNTHETIC notes kept only in the Library.")
        alone = entry(client, only["work_id"])
        assert alone is not None and alone["researches"] == [] and alone["first_research_id"] is None
        assert alone["title"] == "library only notes" and alone["access_level"] == "pdf_available"
        assert alone["versions"][0]["library_item"]["metadata_origin"] == "user_supplied"
        assert alone["representative_source_version_id"] == only["source_version_id"]
        view = client.get("/api/library").json()
        assert view["counts"]["works"] == 2 and view["counts"]["versions"] == 3
        # The work panel opens a version only the Library holds.
        work = client.get(f"/api/library/works/{only['work_id']}")
        assert work.status_code == 200 and work.json()["versions"][0]["library_item"]["origin"] == "upload"
        # An unsaved research work stays unsaved.
        other = create(client, source_scope="attached")
        unsaved = upload(client, other, "unsaved.pdf", "SYNTHETIC unsaved study.")
        unsaved_entry = entry(client, store.source(unsaved)["work_id"])
        assert unsaved_entry["saved"] is False and unsaved_entry["versions"][0]["library_item"] is None


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


def test_purging_a_removed_source_keeps_it_when_it_is_saved(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        svid = upload(client, rid, "saved.pdf", "SYNTHETIC saved and removed study.")
        assert client.post("/api/library/items", json={"source_version_ids": [svid]}).status_code == 201
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        response = client.post(f"/api/researches/{rid}/sources/purge", json={"source_version_ids": [svid]})
        assert response.status_code == 200 and response.json()["deleted"] == [svid]
        assert not store.was_member(rid, svid)  # this research's record of it went
        assert store.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (svid,)).fetchone()
        assert store.passages_for(svid) and entry(client, store.source(svid)["work_id"])["researches"] == []


def test_backup_and_restore_keep_library_items_and_their_files(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        only = library_upload(client, "backup_notes.pdf", "SYNTHETIC notes for the backup check.")
        before_rows = [tuple(r) for r in app.state.store.conn.execute("SELECT * FROM library_items")]
        before = client.get("/api/library").json()
        backup_dir = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")
    assert len(before_rows) == 1

    restored = tmp_path / "restored"
    restore_backup(backup_dir, Settings(data_dir=restored / "data", port=8765))
    conn = db.connect(restored / "data" / "library.sqlite")
    try:
        db.migrate(conn)
        assert [tuple(r) for r in conn.execute("SELECT * FROM library_items")] == before_rows
        storage = conn.execute("SELECT storage_path FROM source_assets WHERE source_version_id = ?",
                               (only["source_version_id"],)).fetchone()[0]
        assert (restored / "data" / "papers" / storage).exists()
        assert Store(conn).passages_for(only["source_version_id"])
    finally:
        conn.close()
    with TestClient(app_for(restored)) as client:
        assert client.get("/api/library").json() == before
