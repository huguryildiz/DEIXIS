"""OpenAlex's retraction flag (D27): stored per source version, never cleared by an unknown read, shown per work and
sent to answer steps only for a flagged work. Records are SYNTHETIC."""

import shutil
from dataclasses import replace

from fastapi.testclient import TestClient

from deixis.domain import contracts
from deixis.providers import openalex
from deixis.storage import db
from deixis.storage.db import new_id, now, transaction
from deixis.workflow import views
from deixis.workflow.store import Store
from test_api_flow import app_for, create, session

WORK = {
    "id": "https://openalex.org/W900", "doi": "https://doi.org/10.1/retracted", "display_name": "SYNTHETIC retracted study",
    "publication_year": 2020, "type": "article", "authorships": [{"author": {"display_name": "A. Author"}}],
    "primary_location": {"version": "publishedVersion", "source": {"display_name": "Synthetic J"}},
    "abstract_inverted_index": {"Packets": [0], "flow.": [1]}, "cited_by_count": 3,
}


def flag(store, svid):
    return tuple(store.conn.execute("SELECT is_retracted, is_retracted_at FROM source_versions WHERE id = ?", (svid,)).fetchone())


def test_the_migration_adds_unknown_flags_to_earlier_versions(tmp_path, monkeypatch):
    real = db.MIGRATIONS_DIR
    older = tmp_path / "older"
    older.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 10:
            shutil.copy(path, older / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    svid = store.create_upload_source("SYNTHETIC older record")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    assert 10 in db.migrate(store.conn)
    assert flag(store, svid) == (None, None)


def test_only_an_explicit_answer_replaces_the_stored_flag(tmp_path):
    store = Store(db.connect(tmp_path / "library.sqlite"))
    db.migrate(store.conn)
    record = openalex._record({**WORK, "is_retracted": True})
    svid, created = store.upsert_provider_source("openalex", record, None)
    assert created and flag(store, svid)[0] == 1 and flag(store, svid)[1] is not None
    # A later read with no boolean (another provider, or OpenAlex without the field) leaves it as it was.
    store.upsert_provider_source("openalex", replace(record, is_retracted=None), None)
    store.upsert_provider_source("crossref", replace(record, provider_record_id="10.1/retracted", is_retracted=None), None)
    assert flag(store, svid)[0] == 1
    store.upsert_provider_source("openalex", replace(record, is_retracted=False), None)
    assert flag(store, svid)[0] == 0
    unknown, _ = store.upsert_provider_source("openalex", openalex._record({**WORK, "id": "W901", "doi": None}), None)
    assert flag(store, unknown) == (None, None)


def test_views_and_step_inputs_carry_the_flag_per_work(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        flagged, _ = store.upsert_provider_source("openalex", openalex._record({**WORK, "is_retracted": True}), None)
        work_id = store.source(flagged)["work_id"]
        # An unflagged preprint of the same work: the work is still retracted.
        preprint = new_id("srv")
        with transaction(store.conn):
            store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at, is_retracted)"
                               " VALUES (?, ?, 'SYNTHETIC retracted study', 'provider', 'submittedVersion', ?, 0)",
                               (preprint, work_id, now()))
        sound, _ = store.upsert_provider_source("openalex", openalex._record(
            {**WORK, "id": "W902", "doi": "10.1/sound", "display_name": "SYNTHETIC sound study", "is_retracted": False}), None)
        other = store.create_upload_source("SYNTHETIC uploaded study")
        for svid in (flagged, preprint, sound, other):
            store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")

        rows = {s["source_version_id"]: s["is_retracted"] for s in views.research_view(store, rid)["sources"]}
        assert rows == {flagged: True, preprint: False, sound: False, other: None}
        library = {e["work_id"]: e["is_retracted"] for e in client.get("/api/library").json()["entries"]}
        assert library[work_id] is True and library[store.source(sound)["work_id"]] is False
        assert library[store.source(other)["work_id"]] is None
        work = client.get(f"/api/library/works/{work_id}").json()
        assert work["is_retracted"] is True and {v["is_retracted"] for v in work["versions"]} == {True, False}
        abstract = next(p for p in store.passages_for(flagged) if p["kind"] == "abstract")
        assert views.passage_view(store, rid, abstract["id"])["source"]["is_retracted"] is True

        flow = app.state.worker.flow
        run = {"id": new_id("run"), "research_id": rid, "scope_revision": 1,
               "budget": {"max_model_calls": 1, "max_provider_requests": 0}}
        payload = flow._step_input(run, store.scope(rid), new_id("stp"), "grounded_answer", [],
                                   [flagged, preprint, sound, other], [abstract], [], ("fake", "fake-model", None))
        assert contracts.check_step_input(payload) == []
        marked = {s["source_id"]: s.get("is_retracted") for s in payload["sources"]}
        assert marked == {flagged: True, preprint: True, sound: None, other: None}
        # An unflagged source object has exactly the fields it had before D27.
        assert all(set(s) == {"source_id", "work_id", "title", "year", "version_label", "access_level"}
                   for s in payload["sources"] if s["source_id"] in (sound, other))
        # The version rows carry the work's flag too, so the preprint is marked in the UI.
        works = {s["source_version_id"]: s["work_is_retracted"] for s in views.research_view(store, rid)["sources"]}
        assert works == {flagged: True, preprint: True, sound: False, other: None}


def test_a_flagged_version_outside_every_research_marks_the_work_everywhere_alike(tmp_path):
    """Library views and the StepInput read the work's flag from every stored version, shown or not (D27)."""
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        shown = store.create_upload_source("SYNTHETIC preprint of a retracted study")
        work_id = store.source(shown)["work_id"]
        with transaction(store.conn):
            store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at, is_retracted)"
                               " VALUES (?, ?, 'SYNTHETIC retracted study', 'provider', 'publishedVersion', ?, 1)",
                               (new_id("srv"), work_id, now()))
        store.add_to_corpus(rid, shown, "user_upload", selection_state="included", selection_origin="user")
        entry = next(e for e in client.get("/api/library").json()["entries"] if e["work_id"] == work_id)
        assert entry["is_retracted"] is True and len(entry["versions"]) == 1
        assert client.get(f"/api/library/works/{work_id}").json()["is_retracted"] is True
        row = next(s for s in views.research_view(store, rid)["sources"] if s["source_version_id"] == shown)
        assert row["is_retracted"] is None and row["work_is_retracted"] is True
        run = {"id": new_id("run"), "research_id": rid, "scope_revision": 1,
               "budget": {"max_model_calls": 1, "max_provider_requests": 0}}
        payload = app.state.worker.flow._step_input(run, store.scope(rid), new_id("stp"), "grounded_answer", [], [shown],
                                                   [], [], ("fake", "fake-model", None))
        assert payload["sources"][0]["is_retracted"] is True


def test_0010_still_applies_to_a_library_that_already_ran_0011(tmp_path, monkeypatch):
    """Migrations apply by version number, not in arrival order: a library that ran 0011 (P2, D31) before 0010 reached
    main gets 0010 on its next start. 0011 adds new tables and 0010 adds columns to source_versions, so the order
    between them does not matter."""
    real = db.MIGRATIONS_DIR
    copies = tmp_path / "migrations"
    copies.mkdir()
    for path in real.glob("*.sql"):
        if not path.name.startswith("0010_"):
            shutil.copy(path, copies / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", copies)
    conn = db.connect(tmp_path / "library.sqlite")
    applied = db.migrate(conn)
    assert 11 in applied and 10 not in applied
    shutil.copy(next(real.glob("0010_*.sql")), copies)
    assert db.migrate(conn) == [10]
    assert {row[1] for row in conn.execute("PRAGMA table_info(source_versions)")} >= {"is_retracted", "is_retracted_at"}
    assert conn.execute("SELECT COUNT(*) FROM provider_requests").fetchone()[0] == 0
