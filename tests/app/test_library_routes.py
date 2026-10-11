"""Library routes (UI parity S19a, F14): CSRF, refusals, bibliography for any set of works and a new research from a
set. Records are SYNTHETIC; nothing here measures provider access or model quality."""

import pytest
from fastapi.testclient import TestClient

from deixis.storage.db import transaction
from helpers import make_pdf
from test_api_flow import app_for, create, session
from test_library import seed_work

MODEL = {"question": "SYNTHETIC: how are packet sizes chosen?", "model_connection": "fake",
         "requested_model": "fake-model", "effort": "quick"}


def pdf_file(name="paper.pdf", text="SYNTHETIC packet study."):
    return {"file": (name, make_pdf([text]), "application/pdf")}


@pytest.mark.parametrize("path, kwargs", [
    ("/api/library/items", {"json": {"source_version_ids": ["srv_x"]}}),
    ("/api/library/uploads", {"files": pdf_file()}),
    ("/api/library/bibliography", {"json": {"work_ids": ["wrk_x"]}}),
    ("/api/library/researches", {"json": MODEL | {"work_ids": ["wrk_x"]}}),
])
def test_every_library_write_needs_the_csrf_token(tmp_path, path, kwargs):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        session(raw)
        assert raw.post(path, headers={"x-deixis-csrf": "wrong"}, **kwargs).status_code == 403
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_save_refuses_unknown_and_empty_sets_and_is_idempotent(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(app.state.store, rid)
        assert client.post("/api/library/items", json={"source_version_ids": []}).status_code == 422
        assert client.post("/api/library/items", json={"source_version_ids": [published, "srv_missing"]}).status_code == 404
        # A refused set saves nothing.
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 0
        assert client.post("/api/library/items", json={"source_version_ids": [preprint]}).json()["saved"] == [preprint]
        again = client.post("/api/library/items", json={"source_version_ids": [preprint, published]}).json()
        assert (again["saved"], again["already_saved"]) == ([published], [preprint])


def test_library_upload_refuses_a_non_pdf_and_reuses_the_same_file(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        refused = client.post("/api/library/uploads", files={"file": ("notes.txt", b"SYNTHETIC plain text", "text/plain")})
        assert refused.status_code == 422 and refused.json()["code"] == "upload_not_pdf"
        first = client.post("/api/library/uploads", files=pdf_file("same.pdf"))
        assert first.status_code == 201, first.text
        second = client.post("/api/library/uploads", files=pdf_file("same-again.pdf"))
        assert second.json()["source_version_id"] == first.json()["source_version_id"]
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 1
        # A file uploaded into a research before is the same record; saving it from the Library marks it uploaded.
        rid = create(client, source_scope="attached")
        held = client.post(f"/api/researches/{rid}/uploads", files=pdf_file("held.pdf", "SYNTHETIC held study."))
        svid = held.json()["uploaded_source_version_id"]
        assert client.post("/api/library/uploads", files=pdf_file("held.pdf", "SYNTHETIC held study.")).json()[
            "source_version_id"] == svid
        assert app.state.store.conn.execute("SELECT origin, metadata_origin FROM library_items WHERE source_version_id = ?",
                                            (svid,)).fetchone()[:] == ("upload", "user_supplied")


def test_bibliography_for_a_set_exports_the_record_each_row_shows(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(store, rid)
        with transaction(store.conn):
            store.conn.execute("UPDATE source_versions SET authors_json = '[\"Ada Synthetic\"]', publication_type = 'article'"
                               " WHERE id = ?", (published,))
            store.conn.execute("INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                               " VALUES (?, 'arxiv', '2101.00001', 'openalex', '2026-10-11T00:00:00Z')", (preprint,))
        only = client.post("/api/library/uploads", files=pdf_file("library_only.pdf")).json()

        assert client.post("/api/library/bibliography", json={"format": "bibtex"}).status_code == 422
        assert client.post("/api/library/bibliography", json={"work_ids": ["wrk_missing"]}).status_code == 404
        assert client.post("/api/library/bibliography", json={"source_version_ids": ["srv_missing"]}).status_code == 404
        assert client.post("/api/library/bibliography", json={"work_ids": [work_id], "format": "csv"}).status_code == 422

        bib = client.post("/api/library/bibliography", json={"work_ids": [work_id, only["work_id"]]})
        assert bib.status_code == 200, bib.text
        assert bib.headers["content-type"].startswith("application/x-bibtex")
        assert bib.headers["content-disposition"] == 'attachment; filename="deixis-library.bib"'
        # The row shows the published record (DOI, venue, year), so that record is exported, not merged with the preprint.
        assert bib.text.count("@") == 2 and "@article{synthetic2021synthetic," in bib.text
        assert "doi = {10.1/syn}" in bib.text and "journal = {Synthetic J}" in bib.text and "2101.00001" not in bib.text
        assert "title = {library only}" in bib.text

        ris = client.post("/api/library/bibliography", json={"format": "ris", "source_version_ids": [preprint, published]})
        assert ris.status_code == 200 and ris.headers["content-disposition"].endswith('deixis-library.ris"')
        records = [r for r in ris.text.split("ER  - ") if r.strip()]
        assert len(records) == 2 and "submitted manuscript" in records[0] and "DO  - 10.1/syn" in records[1]


def test_new_research_from_a_set_holds_those_works_in_attached_scope(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        origin = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(store, origin)
        only = client.post("/api/library/uploads", files=pdf_file("library_only.pdf")).json()
        count = lambda: store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0]

        assert client.post("/api/library/researches", json=MODEL | {"work_ids": []}).status_code == 422
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id], "source_scope": "academic"}).status_code == 422
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id, "wrk_missing"]}).status_code == 404
        # The create route's own checks apply: an unknown model connection is refused before anything is written.
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id], "model_connection": "none"}).status_code == 422
        assert count() == 1

        response = client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id, only["work_id"]], "intent": "table"})
        assert response.status_code == 201, response.text
        view = response.json()
        rid = view["research"]["id"]
        assert count() == 2 and view["scope"]["source_scope"] == "attached" and view["research"]["intent"] == "table"
        # One version per work, the one with the deepest stored reading (the preprint's abstract); versions stay apart.
        assert view["added_source_version_ids"] == [preprint, only["source_version_id"]]
        assert {s["source_version_id"]: s["selection"]["state"] for s in view["sources"]} == {
            preprint: "included", only["source_version_id"]: "included"}
        assert not store.is_active_member(rid, published)
        # A table research gets its study table holding the attached works.
        assert store.conn.execute("SELECT COUNT(*) FROM evidence_tables WHERE research_id = ?", (rid,)).fetchone()[0] == 1


def test_a_zotero_import_saved_to_the_library_stays_user_supplied(tmp_path):
    from test_zotero import COLLECTION, app_for as zotero_app, start, zotero_client
    files = {}
    for key in ("PDFA1234", "LNKD1234", "STND1234"):
        path = tmp_path / f"{key} file.pdf"
        path.write_bytes(make_pdf([f"SYNTHETIC text of {key}"]))
        files[key] = path.as_uri()
    app = zotero_app(tmp_path, zotero_client(files, []))
    with TestClient(app) as client:
        rid = start(client)
        imported = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": COLLECTION})
        assert imported.status_code == 201, imported.text
        svids = [s["source_version_id"] for s in imported.json()["sources"]]
        # The import stores provider records; their fields are still the person's own Zotero entries.
        assert {app.state.store.source(s)["origin"] for s in svids} == {"provider"}
        assert client.post("/api/library/items", json={"source_version_ids": svids}).status_code == 201
        rows = app.state.store.conn.execute("SELECT DISTINCT metadata_origin FROM library_items").fetchall()
        assert [r[0] for r in rows] == ["user_supplied"]


def test_new_research_from_a_set_writes_nothing_when_a_work_goes_during_the_model_check(tmp_path):
    from fakes import FakeAdapter
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        origin = create(client, source_scope="attached")
        work_id, _, _ = seed_work(store, origin)
        health = adapter.health

        async def purge_during_check(refresh=False):
            # A purge that runs while the route awaits the model list.
            if store.conn.execute("SELECT 1 FROM researches WHERE id = ?", (origin,)).fetchone():
                store.trash_research(origin)
                store.purge_research(origin)
            return await health(refresh=refresh)

        adapter.health = purge_during_check
        response = client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id]})
        assert response.status_code == 404, response.text
        assert store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_the_pdf_of_a_saved_item_opens_without_a_research_and_others_do_not(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        saved = client.post("/api/library/uploads", files=pdf_file("saved.pdf", "SYNTHETIC saved copy.")).json()
        asset = client.get(f"/api/library/works/{saved['work_id']}").json()["versions"][0]["asset"]["id"]
        response = client.get(f"/api/library/assets/{asset}")
        assert response.status_code == 200 and response.content.startswith(b"%PDF-")
        assert response.headers["content-type"] == "application/pdf"
        rid = create(client, source_scope="attached")
        held = client.post(f"/api/researches/{rid}/uploads", files=pdf_file("held.pdf", "SYNTHETIC unsaved copy."))
        unsaved = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?",
                                     (held.json()["uploaded_source_version_id"],)).fetchone()[0]
        assert client.get(f"/api/library/assets/{unsaved}").status_code == 404
        assert client.get("/api/library/assets/ast_missing").status_code == 404
