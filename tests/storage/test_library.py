"""Library view and adding a Library work to another research (D40, D41). Records are SYNTHETIC."""

from fastapi.testclient import TestClient

from deixis.storage.db import new_id, now, transaction
from test_api_flow import app_for, create, session, wait_run


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


def test_library_lists_every_active_research_as_a_group(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        with_source, empty = create(client, source_scope="attached"), create(client, source_scope="attached")
        work_id, _, _ = seed_work(app.state.store, with_source)
        view = client.get("/api/library").json()
        assert {r["id"] for r in view["researches"]} == {with_source, empty}
        assert [e["work_id"] for e in view["entries"]] == [work_id]
        assert view["counts"]["researches"] == 1


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


def test_a_research_title_run_names_an_older_research(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        named, bare = create(client, source_scope="attached"), create(client, source_scope="attached")
        seed_work(app.state.store, named)
        for rid in (named, bare):
            response = client.post(f"/api/researches/{rid}/runs", json={"kind": "research_title"})
            assert response.status_code == 202, response.text
            run = response.json()
            assert (run["kind"], run["stage"], run["budget"]["max_model_calls"]) == ("research_title", "intake", 2)
            view, finished = wait_run(client, rid, run["id"])
            assert finished["status"] == "completed", finished
            # SYNTHETIC: the fake adapter's title; a research without included sources is named from its question alone.
            assert view["research"]["title"] == "Synthetic short research title"
        steps = app.state.store.conn.execute("SELECT kind, status FROM run_steps WHERE run_id = ?", (run["id"],)).fetchall()
        assert [tuple(s) for s in steps] == [("model:research_title", "succeeded")]
