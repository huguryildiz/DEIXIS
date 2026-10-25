"""P5 slice 3 (D50): a source removed from a research leaves its lists and new work, while its evidence keeps opening.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows which stored rows each view and model input
reads after a removal; it says nothing about answer or cell quality.
"""


import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.store import NotASource
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_evidence_tables import PACKET_SIZE
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


# ---- active and past membership -------------------------------------------------------------
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


# ---- deleting a removed source permanently (D65) ---------------------------------------------
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


import hashlib
import json

from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow import table_rows
from test_api_flow import app_for, create, session
from test_evidence_tables import PACKET_SIZE, table_with_edit

# Every row that says what is trashed or removed, compared whole before the backup and after the restore.
TRASH_ROWS = {
    "corpus_memberships": "SELECT * FROM corpus_memberships ORDER BY research_id, source_version_id",
    "evidence_tables": "SELECT * FROM evidence_tables ORDER BY id",
    "table_columns": "SELECT * FROM table_columns ORDER BY id",
    "table_templates": "SELECT * FROM table_templates ORDER BY id",
    "source_assets": "SELECT * FROM source_assets ORDER BY id",
}


def trash_rows(conn):
    return {name: [tuple(row) for row in conn.execute(sql)] for name, sql in TRASH_ROWS.items()}


def test_backup_keeps_trashed_and_removed_items_and_the_restored_library_brings_them_back(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        base = f"/api/researches/{rid}"

        trashed = table_with_edit(client, rid)
        trashed_view = client.get(f"{base}/tables/{trashed}").json()
        template = client.post("/api/table-templates", json={"research_id": rid, "table_id": trashed, "name": "Packets"}).json()["id"]
        assert client.delete(f"/api/table-templates/{template}").status_code == 200
        assert client.delete(f"{base}/tables/{trashed}", params={"expected_version": trashed_view["table"]["version"]}).status_code == 200

        kept = client.post(f"{base}/tables", json={"title": "Kept"}).json()
        column_view = client.post(f"{base}/tables/{kept['table']['id']}/columns", json=PACKET_SIZE | {"expected_version": kept["table"]["version"]}).json()
        column = column_view["columns"][0]
        assert client.delete(f"{base}/tables/{kept['table']['id']}/columns/{column['id']}", params={"expected_version": column["version"]}).status_code == 200

        gone = upload(client, rid, "gone.pdf", "SYNTHETIC a report taken out of this research.")["source_version_id"]
        assert client.request("DELETE", f"{base}/sources", json={"source_version_ids": [gone], "note": "SYNTHETIC off topic"}).status_code == 200
        search_found_again(store, rid, gone)

        wrong = upload(client, rid, "wrong.pdf", "SYNTHETIC the wrong file for this record.")
        wrong_svid, wrong_asset = wrong["source_version_id"], wrong["access"]["assets"][0]["id"]
        wrong_bytes, wrong_file = client.get(f"{base}/assets/{wrong_asset}").content, store.asset(wrong_asset)["storage_path"]
        assert client.delete(f"{base}/sources/{wrong_svid}/assets/{wrong_asset}").status_code == 200

        membership = store.conn.execute("SELECT removed_at, removal_note, found_again_at FROM corpus_memberships"
                                        " WHERE research_id = ? AND source_version_id = ?", (rid, gone)).fetchone()
        assert membership["removed_at"] and membership["removal_note"] == "SYNTHETIC off topic" and membership["found_again_at"]
        assert store.asset(wrong_asset)["removal_reason"] == "wrong_file"
        # The worker's row sweep (D63) gives "Kept" its row for the later upload; settle it before the backup, as the
        # restored library's first worker turn would.
        table_rows.advance(store, rid)
        rows, trash, view = trash_rows(store.conn), client.get("/api/trash").json(), client.get(base).json()
        assert [t["id"] for t in trash["tables"]] == [trashed] and [s["source_version_id"] for s in trash["sources"]] == [gone]
        assert [t["id"] for t in trash["templates"]] == [template]
        backup = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")  # server still running

    manifest = json.loads((backup / "manifest.json").read_text())
    assert all(hashlib.sha256((backup / f["path"]).read_bytes()).hexdigest() == f["sha256"] for f in manifest["files"])
    assert all((backup / f["path"]).stat().st_size == f["bytes"] for f in manifest["files"])
    papers = {f["path"]: f["sha256"] for f in manifest["files"] if f["path"].startswith("papers/")}
    assert papers[f"papers/{wrong_file}"] == hashlib.sha256(wrong_bytes).hexdigest()  # the withdrawn PDF is in the backup

    restored = tmp_path / "restored"
    restore_backup(backup, Settings(data_dir=restored / "data", port=8765))
    app = app_for(restored)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        assert trash_rows(store.conn) == rows
        assert client.get("/api/trash").json() == trash and client.get(base).json() == view

        back = client.post(f"{base}/tables/{trashed}/restore", json={"expected_version": trashed_view["table"]["version"] + 1})
        assert back.status_code == 200, back.text
        assert back.json()["cells"] == trashed_view["cells"] and back.json()["cells"][0]["current"]["state"] == "not_reported"

        column_back = client.post(f"{base}/tables/{kept['table']['id']}/columns/{column['id']}/restore",
                                  json={"expected_version": column["version"] + 1})
        assert column_back.status_code == 200, column_back.text
        assert [c["id"] for c in column_back.json()["columns"]] == [column["id"]]

        assert client.post(f"/api/table-templates/{template}/restore").status_code == 200
        assert [t["id"] for t in client.get("/api/table-templates").json()] == [template]

        sources = client.post(f"{base}/sources/restore", json={"source_version_ids": [gone]})
        assert sources.status_code == 200, sources.text
        assert gone in {s["source_version_id"] for s in sources.json()["sources"]} and sources.json()["counts"]["removed"] == 0

        pdf = client.post(f"{base}/sources/{wrong_svid}/assets/{wrong_asset}/restore")
        assert pdf.status_code == 200, pdf.text
        assert client.get(f"{base}/assets/{wrong_asset}").content == wrong_bytes

        assert client.get("/api/trash").json() == {"researches": [], "tables": [], "sources": [], "templates": []}
