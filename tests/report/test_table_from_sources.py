"""P5 slice 3 (D50): a table started from chosen sources takes active members only, included or not (D37).

Records are SYNTHETIC. Passing shows which sources become rows and what is refused; it says nothing about cell quality.
"""

import pytest
from fastapi.testclient import TestClient

from deixis.workflow.tables import InvalidTableInput
from test_api_flow import app_for, create, session
from test_corpus_removal import upload
from test_table_extraction import library


def row_ids(tables, rid, tid):
    return {r["source_version_id"] for r in tables.table_view(rid, tid)["rows"]}


def test_rows_take_active_members_included_or_not_and_refuse_removed_ones(tmp_path):
    lib = library(tmp_path)
    store, tables, conn = lib.store, lib.tables, lib.conn
    excluded = store.create_upload_source("D SYNTHETIC excluded report")
    store.add_to_corpus(lib.rid, excluded, "user_upload", selection_state="excluded", selection_origin="user")
    store.remove_sources(lib.rid, [lib.no_text], "SYNTHETIC scan")
    count = lambda: conn.execute("SELECT COUNT(*) FROM evidence_tables").fetchone()[0]  # noqa: E731
    before = count()

    for rows in ([lib.published, lib.no_text], [lib.published, "srv_missing"]):
        with pytest.raises(InvalidTableInput):
            tables.create_table(lib.rid, "Chosen", rows, None, None)
    assert count() == before  # nothing half-made

    tid = tables.create_table(lib.rid, "Chosen", [lib.published, excluded, lib.published], None, "chosen-1")
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded}
    assert {r[0] for r in conn.execute("SELECT added_by FROM table_rows WHERE table_id = ?", (tid,))} == {"user"}
    assert tables.create_table(lib.rid, "Chosen", [lib.published, excluded], None, "chosen-1") == tid
    assert count() == before + 1

    version = tables.table_view(lib.rid, tid)["table"]["version"]
    with pytest.raises(InvalidTableInput):
        tables.add_rows(lib.rid, tid, [lib.preprint, lib.no_text], version)
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded}
    assert tables.table_view(lib.rid, tid)["table"]["version"] == version
    tables.add_rows(lib.rid, tid, [lib.preprint], version)
    assert row_ids(tables, lib.rid, tid) == {lib.published, excluded, lib.preprint}


def test_table_from_chosen_sources_api(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        kept = upload(client, rid, "kept.pdf", "SYNTHETIC packets of 128 bytes.")
        other = upload(client, rid, "other.pdf", "SYNTHETIC a relay forwards each packet once.")
        gone = upload(client, rid, "gone.pdf", "SYNTHETIC a scanned report.")
        client.patch(f"/api/researches/{rid}/selections/{other['source_version_id']}",
                     json={"state": "excluded", "expected_version": other["selection"]["version"], "reason": "SYNTHETIC off topic"})
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [gone["source_version_id"]]}).status_code == 200

        url = f"/api/researches/{rid}/tables"
        chosen = [kept["source_version_id"], other["source_version_id"]]
        refused = client.post(url, json={"title": "Chosen", "rows": [kept["source_version_id"], gone["source_version_id"]]})
        assert refused.status_code == 422 and gone["source_version_id"] in refused.json()["detail"]
        assert raw.post(url, json={"title": "Chosen", "rows": chosen}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        assert client.get(url).json() == []

        made = client.post(url, json={"title": "Chosen", "rows": chosen}, headers={"idempotency-key": "chosen-1"})
        assert made.status_code == 201, made.text
        table = made.json()
        assert {r["source_version_id"] for r in table["rows"]} == set(chosen)
        again = client.post(url, json={"title": "Chosen", "rows": chosen}, headers={"idempotency-key": "chosen-1"})
        assert again.status_code == 201 and again.json()["table"]["id"] == table["table"]["id"]
        assert len(client.get(url).json()) == 1

        rows = f"{url}/{table['table']['id']}/rows"
        added = client.post(rows, json={"source_version_ids": [gone["source_version_id"]], "expected_version": table["table"]["version"]})
        assert added.status_code == 422
