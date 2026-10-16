"""Migration 0014 (D40) rebuilds `passages` to allow `equation_ocr` and adds `mathpix_requests`. From a filled 0013 library:
rowids, the FTS index, references, triggers and indexes survive; a failure inside the migration leaves 0013 working.
SYNTHETIC rows on a temporary library."""

import shutil
import sqlite3

import pytest

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow.store import Store
from helpers import make_pdf

OBJECTS = ("passages_source", "passages_asset", "passages_fts_insert", "passages_no_update", "cell_evidence_same_source",
           "lineage_link_evidence_same_source", "claim_matrix_evidence_integrity")


def library_at_0013(tmp_path, monkeypatch, extra: str | None = None):
    real = db.MIGRATIONS_DIR
    older = tmp_path / "older"
    older.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 14:
            shutil.copy(path, older / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", older)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    svid = store.create_upload_source("SYNTHETIC migration paper")
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf(["SYNTHETIC page one: molecule release schedule minimizes error.", "SYNTHETIC page two: relay placement."]))
    aid = store.add_asset_with_pages(svid, "sha-a", 10, "paper.pdf", "user_upload", None, "paper.pdf", pdf.extract_pdf(path),
                                     pdf.EXTRACTION_VERSION, pdf.chunk_page)
    passage = conn.execute("SELECT id FROM passages WHERE asset_id = ? ORDER BY rowid LIMIT 1", (aid,)).fetchone()[0]
    conn.execute("INSERT INTO passage_embeddings (passage_id, model, dimensions, vector, created_at) VALUES (?, 'm', 1, x'00', 'now')", (passage,))
    if extra is not None:
        source = (real / "0014_mathpix_equations.sql").read_text()
        marker = "DROP TRIGGER cell_evidence_same_source;"
        (tmp_path / "broken").mkdir()
        for path in older.glob("*.sql"):
            shutil.copy(path, tmp_path / "broken" / path.name)
        (tmp_path / "broken" / "0014_mathpix_equations.sql").write_text(source.replace(marker, extra + "\n" + marker))
        monkeypatch.setattr(db, "MIGRATIONS_DIR", tmp_path / "broken")
    else:
        monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    return conn, store, svid, aid, passage


def snapshot(conn):
    return ([tuple(r) for r in conn.execute("SELECT rowid, * FROM passages ORDER BY rowid")],
            {name: conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0] for name in OBJECTS})


def test_the_rebuild_keeps_rows_rowids_fts_references_triggers_and_indexes(tmp_path, monkeypatch):
    conn, store, svid, aid, passage = library_at_0013(tmp_path, monkeypatch)
    rows, objects = snapshot(conn)
    hits = [r[0] for r in conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'relay'")]
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, text, text_sha256, retrieved_at,"
                     " created_at, text_source) VALUES ('psg_x', ?, ?, 'pdf_page', 1, 't', 'h', 'now', 'now', 'equation_ocr')", (svid, aid))
    assert 14 in db.migrate(conn)
    after_rows, after_objects = snapshot(conn)
    assert after_rows == rows and after_objects == objects
    assert [r[0] for r in conn.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'relay'")] == hits and hits
    assert store.passage(passage)["id"] == passage  # an old reference still resolves
    assert conn.execute("SELECT passage_id FROM passage_embeddings").fetchone()[0] == passage
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE passages SET text = 'changed' WHERE id = ?", (passage,))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO passage_embeddings (passage_id, model, dimensions, vector, created_at) VALUES ('psg_missing', 'm', 1, x'00', 'now')")
    conn.execute("INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, payload_ref, extraction_version, text,"
                 " text_sha256, retrieved_at, created_at, text_source) VALUES ('psg_new', ?, ?, 'pdf_page', 1, 'chars:0-5', 'v',"
                 " 'mathpixword', 'h', 'now', 'now', 'equation_ocr')", (svid, aid))
    assert conn.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH 'mathpixword'").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, text, text_sha256, retrieved_at,"
                     " created_at, text_source) VALUES ('psg_y', ?, ?, 'pdf_page', 1, 't', 'h', 'now', 'now', 'invented')", (svid, aid))
    columns = {r[1] for r in conn.execute("PRAGMA table_info(mathpix_requests)")}
    assert {"crop_sha256", "asset_id", "file_sha256", "page", "n", "attempt", "status", "http_status", "request_id", "response_json",
            "credential_revision", "reserved_at", "answered_at"} <= columns
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO mathpix_requests (id, crop_sha256, asset_id, file_sha256, page, n, attempt, status, credential_revision,"
                     " reserved_at) VALUES ('m', 'c', 'a', 'f', 1, '1', 1, 'sent', 'r', 'now')")
    conn.close()


def test_a_failure_inside_the_migration_rolls_back_to_a_working_0013_library(tmp_path, monkeypatch):
    conn, store, svid, aid, passage = library_at_0013(tmp_path, monkeypatch, extra="INSERT INTO no_such_table VALUES (1);")
    rows, objects = snapshot(conn)
    with pytest.raises(db.MigrationFailed, match="no_such_table"):
        db.migrate(conn)
    assert max(r[0] for r in conn.execute("SELECT version FROM schema_migrations")) == 13
    assert snapshot(conn) == (rows, objects)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name IN ('passages_new', 'mathpix_requests')").fetchone() is None
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1 and conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH 'relay'").fetchone()[0] >= 1
    assert store.passage(passage)["id"] == passage
    conn.close()
