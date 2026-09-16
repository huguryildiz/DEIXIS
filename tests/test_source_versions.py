"""P5 slice 2 (D45): one PDF in use per source version, extraction records, and shadowed passages.

Records are SYNTHETIC. Passing these tests shows that storage keeps old passages resolvable while model inputs read only the
file and extraction in use; it says nothing about extraction quality.
"""

import shutil
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.storage import db
from deixis.workflow.store import PdfInUse, Store
from helpers import make_pdf
from test_api_flow import app_for, create, session

REAL_MIGRATIONS = db.MIGRATIONS_DIR


def extraction(pages, status="succeeded"):
    return SimpleNamespace(status=status, error=None, page_count=len(pages),
                           pages=[SimpleNamespace(physical_page=n, printed_label=None, text=text) for n, text in enumerate(pages, 1) if text])


def add_pdf(store, svid, pages, sha, version="test-v1"):
    return store.add_asset_with_pages(svid, sha, 10, f"{sha}.pdf", "user_upload", None, "p.pdf", extraction(pages), version,
                                      lambda text: [(0, len(text), text)])


def library_at(tmp_path, monkeypatch, last):
    old = tmp_path / "migrations"
    old.mkdir()
    for path in REAL_MIGRATIONS.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= last:
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", REAL_MIGRATIONS)
    return conn, Store(conn)


def raw_asset(conn, svid, sha, pages, version):
    """An asset written as code before migration 27 wrote it: no extraction record."""
    aid = db.new_id("ast")
    with db.transaction(conn):
        conn.execute("INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, retrieved_at, origin,"
                     " extraction_status, extraction_version, page_count) VALUES (?, ?, ?, 10, 'application/pdf', ?, ?, 'user_upload', 'succeeded', ?, ?)",
                     (aid, svid, sha, f"{sha}.pdf", db.now(), version, len(pages)))
        for n, text in enumerate(pages, 1):
            if text:
                Store(conn)._insert_passage(svid, aid, "pdf_page", n, None, None, f"chars:0-{len(text)}", version, text)
    return aid


# ---- migration 27 ---------------------------------------------------------------------------
def test_migration_records_the_extraction_each_existing_pdf_has(tmp_path, monkeypatch):
    conn, store = library_at(tmp_path, monkeypatch, 26)
    kept = store.create_upload_source("A SYNTHETIC study")
    removed = store.create_upload_source("B SYNTHETIC study")
    kept_asset = raw_asset(conn, kept, "1" * 64, ["SYNTHETIC page one.", "", "SYNTHETIC page three."], "pypdf-6.18.1-chunks-v1")
    removed_asset = raw_asset(conn, removed, "2" * 64, ["SYNTHETIC wrong file."], "pymupdf-1.28.2-chunks-v1")
    conn.execute("UPDATE source_assets SET removed_at = ? WHERE id = ?", (db.now(), removed_asset))
    passages = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]

    assert 27 in db.migrate(conn)
    rows = {r["asset_id"]: dict(r) for r in conn.execute("SELECT * FROM asset_extractions")}
    assert set(rows) == {kept_asset, removed_asset}
    assert {k: rows[kept_asset][k] for k in ("extraction_version", "status", "page_count", "text_pages", "passage_count", "outcome")} == {
        "extraction_version": "pypdf-6.18.1-chunks-v1", "status": "succeeded", "page_count": 3, "text_pages": 2, "passage_count": 2,
        "outcome": "current"}
    assert rows[removed_asset]["outcome"] == "current"
    assert store.asset(removed_asset)["removal_reason"] is None  # the reason of an earlier removal was not recorded
    assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == passages
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_stops_when_a_source_version_has_two_pdfs_in_use(tmp_path, monkeypatch):
    conn, store = library_at(tmp_path, monkeypatch, 26)
    svid = store.create_upload_source("A SYNTHETIC study")
    raw_asset(conn, svid, "1" * 64, ["SYNTHETIC page one."], "test-v1")
    raw_asset(conn, svid, "2" * 64, ["SYNTHETIC page one."], "test-v1")

    with pytest.raises(sqlite3.IntegrityError):
        db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 26
    assert conn.execute("SELECT COUNT(*) FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()[0] == 2


# ---- storage --------------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def test_a_new_extraction_version_of_the_same_text_is_a_new_passage(store):
    svid = store.create_upload_source("A SYNTHETIC study")
    aid = add_pdf(store, svid, ["SYNTHETIC page one."], "1" * 64, version="test-v1")
    (old,) = store.passages_for(svid)
    with db.transaction(store.conn):
        same = store._insert_passage(svid, aid, "pdf_page", 1, None, None, "chars:0-19", "test-v1", old["text"])
        new = store._insert_passage(svid, aid, "pdf_page", 1, None, None, "chars:0-19", "test-v2", old["text"])
    assert same == old["id"]
    assert new != old["id"] and store.passage(new)["extraction_version"] == "test-v2"
    assert store.passage(old["id"])["extraction_version"] == "test-v1"


def test_adding_a_pdf_records_its_extraction(store):
    svid = store.create_upload_source("A SYNTHETIC study")
    aid = add_pdf(store, svid, ["SYNTHETIC page one.", "", "SYNTHETIC page three."], "1" * 64)
    (row,) = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ?", (aid,)).fetchall()
    assert (row["extraction_version"], row["status"], row["page_count"], row["text_pages"], row["passage_count"], row["outcome"]) == (
        "test-v1", "succeeded", 3, 2, 2, "current")


def test_a_source_version_has_one_pdf_in_use(store):
    svid = store.create_upload_source("A SYNTHETIC study")
    first = add_pdf(store, svid, ["SYNTHETIC page one."], "1" * 64)
    with pytest.raises(PdfInUse):
        add_pdf(store, svid, ["SYNTHETIC page one."], "2" * 64)
    assert [a["id"] for a in store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,))] == [first]

    rid = store.create_research("Question?", "attached", "quick", [], "fake", "fake-model", None)
    store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    store.remove_asset(rid, svid, first)
    assert store.asset(first)["removal_reason"] == "wrong_file"
    add_pdf(store, svid, ["SYNTHETIC right file."], "2" * 64)
    assert [p["text"] for p in store.passages_for(svid)] == ["SYNTHETIC right file."]


def test_passages_of_an_extraction_not_in_use_are_not_given_but_still_resolve(store):
    svid = store.create_upload_source("A SYNTHETIC study")
    with db.transaction(store.conn):
        store._insert_passage(svid, None, "abstract", None, None, "provider", None, None, "SYNTHETIC abstract about relays.")
    aid = add_pdf(store, svid, ["SYNTHETIC relays forward packets."], "1" * 64, version="test-v1")
    with db.transaction(store.conn):
        other = store._insert_passage(svid, aid, "pdf_page", 1, None, None, "chars:0-40", "test-v0", "SYNTHETIC relays drop packets.")

    assert other not in {p["id"] for p in store.passages_for(svid)}
    assert {p["kind"] for p in store.passages_for(svid)} == {"abstract", "pdf_page"}
    assert other not in {p["id"] for p in store.search_passages([svid], '"relays"', 10)}
    assert store.passage(other)["text"] == "SYNTHETIC relays drop packets."


def test_attaching_a_pdf_where_one_is_in_use_answers_409(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        first = make_pdf(["SYNTHETIC molecule notes page"])
        assert client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", first, "application/pdf")}).status_code == 201
        svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?", (rid,)).fetchone()[0]
        url = f"/api/researches/{rid}/sources/{svid}/uploads"
        in_use = lambda: store.conn.execute("SELECT COUNT(*) FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()[0]

        assert client.post(url, files={"file": ("a.pdf", first, "application/pdf")}).status_code == 201  # the same file again changes nothing
        second = client.post(url, files={"file": ("b.pdf", make_pdf(["SYNTHETIC other notes"]), "application/pdf")})
        assert second.status_code == 409 and in_use() == 1

        (asset_id,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()
        client.delete(f"/api/researches/{rid}/sources/{svid}/assets/{asset_id}")
        assert client.post(url, files={"file": ("b.pdf", make_pdf(["SYNTHETIC other notes"]), "application/pdf")}).status_code == 201
        assert in_use() == 1


# ---- re-extraction (D45, D47) ------------------------------------------------------------------
def test_reextraction_becomes_current_and_shadows_the_old_passages(tmp_path):
    from deixis.workflow.store import RunInProgress

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", [], "fake", "fake-model", None)
    svid = store.create_upload_source("SYNTHETIC upload")
    store.add_to_corpus(rid, svid, "user_upload")
    aid = add_pdf(store, svid, ["old page one", "old page two"], "sha-a")
    old_ids = [p["id"] for p in store.passages_for(svid)]
    chunker = lambda text: [(0, len(text), text)]

    assert store.reextract_asset(aid, extraction(["new page one", "new page two"]), "test-v2", chunker, dry_run=True)["outcome"] == "current"
    assert [p["id"] for p in store.passages_for(svid)] == old_ids  # a dry run writes nothing

    report = store.reextract_asset(aid, extraction(["new page one", "new page two"]), "test-v2", chunker)
    assert report["outcome"] == "current" and report["old_version"] == "test-v1"
    assert [p["text"] for p in store.passages_for(svid)] == ["new page one", "new page two"]
    assert all(conn.execute("SELECT 1 FROM passages WHERE id = ?", (pid,)).fetchone() for pid in old_ids)  # still resolvable
    assert store.asset(aid)["extraction_version"] == "test-v2"
    assert store.reextract_asset(aid, extraction(["x", "y"]), "test-v2", chunker)["outcome"] == "unchanged"

    lost = store.reextract_asset(aid, extraction(["only one page", ""]), "test-v3", chunker)
    assert lost["outcome"] == "rejected" and "fewer" in lost["rejection_reason"]
    assert [p["text"] for p in store.passages_for(svid)] == ["new page one", "new page two"]
    assert [r[0] for r in conn.execute("SELECT outcome FROM asset_extractions WHERE asset_id = ? ORDER BY created_at, rowid", (aid,))] == ["superseded", "current", "rejected"]
    assert [e["type"] for e in store.events_after(rid, 0)].count("asset_reextracted") == 2

    run = store.create_run(rid, "discovery", {"max_model_calls": 1, "max_provider_requests": 1, "max_candidates": 1, "max_answer_passages": 1}, None)
    assert run["status"] == "queued"
    with pytest.raises(RunInProgress):
        store.reextract_asset(aid, extraction(["a", "b"]), "test-v4", chunker)
