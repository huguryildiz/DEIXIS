"""T15 (D50): a backup keeps what is in the trash or removed, and the restored library can bring each of them back.

Synthetic library built through the API with the test-only FakeAdapter. Passing shows the stored rows, files and manifest
hashes survive a backup and restore; it says nothing about backups of a real library.
"""

import hashlib
import json

from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage.backup import create_backup, restore_backup
from test_api_flow import app_for, create, session
from test_corpus_removal import search_found_again, upload
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
