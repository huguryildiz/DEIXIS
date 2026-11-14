"""A person's undo of an automatic record merge through the local API."""

from fastapi.testclient import TestClient

from deixis.storage.db import transaction
from deixis.workflow.run import links
from test_api_flow import app_for, session
from test_record_links import joined_preprint, link_between, record, research, search


def test_record_link_undo_separates_and_prevents_the_next_merge(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid, run_id = research(store)
        published, preprint = joined_preprint(store, rid, run_id)
        link = link_between(store, rid, published, preprint)
        # A research in the trash that holds the same work is left alone and does not block the undo.
        trashed, trashed_run = research(store)
        search(store, trashed, trashed_run, 0, "openalex", [record("W1")])
        store.conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (trashed_run,))
        store.trash_research(trashed)
        path = f"/api/researches/{rid}/record-links/{link['id']}/undo"
        before = {r["source_version_id"]: dict(r) for r in store.conn.execute(
            "SELECT * FROM selections WHERE research_id = ?", (rid,))}
        runs_before = store.conn.execute("SELECT COUNT(*) FROM runs WHERE research_id = ?", (rid,)).fetchone()[0]

        # The research view gives source details both records and the merge's stored reason.
        view = client.get(f"/api/researches/{rid}").json()
        pair = next(s["record_links"][0] for s in view["sources"] if s["source_version_id"] == published)
        assert pair["id"] == link["id"] and pair["rule"] == "preprint_names_published_doi"
        assert {r["source_version_id"] for r in pair["records"]} == {published, preprint}
        assert all(r["title"] and r["version_label"] and r["doi"] for r in pair["records"])

        assert client.post(path, json={}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        assert client.post(path, json={}, headers={"origin": "https://untrusted.example"}).status_code == 403
        assert client.post(path, json={}, headers={"host": "untrusted.example"}).status_code == 403
        result = client.post(path, json={"note": "SYNTHETIC wrong match"})
        assert result.status_code == 200, result.text
        assert result.json()["closed_reason"] == "undone"
        assert store.source(published)["work_id"] != store.source(preprint)["work_id"]
        assert store.conn.execute("SELECT COUNT(*) FROM runs WHERE research_id = ?", (rid,)).fetchone()[0] == runs_before
        assert store.conn.execute("SELECT closed_note FROM record_links WHERE id = ?", (link["id"],)).fetchone()[0] == "SYNTHETIC wrong match"
        event = store.conn.execute("SELECT type, payload_json FROM events WHERE research_id = ? ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        assert event["type"] == "record_link_undone" and link["id"] in event["payload_json"]
        assert {r["source_version_id"]: dict(r) for r in store.conn.execute(
            "SELECT * FROM selections WHERE research_id = ?", (rid,))} == before

        after = client.get(f"/api/researches/{rid}").json()
        closed = next(s["record_links"][0] for s in after["sources"] if s["source_version_id"] == published)
        assert closed["closed_reason"] == "undone"
        refused = client.post(path)
        assert refused.status_code == 409 and "already closed" in refused.json()["detail"]
        with transaction(store.conn):
            links.link_records(store, rid, [preprint])
        assert store.source(published)["work_id"] != store.source(preprint)["work_id"]
        assert link_between(store, rid, published, preprint) is None
