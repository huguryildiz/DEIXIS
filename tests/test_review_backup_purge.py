"""Backup hashes and snapshot-only protection through real Store purge transactions."""

import copy
import hashlib
import json

import pytest

from deixis.config import Settings
from deixis.domain.canonical import canonical_json
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.review.store import SnapshotDependencyUnreadable, snapshot_referenced_source_versions
from tests.review_helpers import report_with_sections, review_lib, stored_review, snapshot, make_answer, rows, all_rows
from tests.test_review_store import TABLES
from tests.test_review_stale import asset_evidence


def remove_existing_citation_protection(lib):
    conn = lib["conn"]
    # Use the existing purge authorization for immutable cell evidence; do not drop guards.
    conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (lib["rid"],))
    conn.execute("UPDATE evidence_cells SET current_revision_id = NULL")
    conn.execute("DELETE FROM evidence_links")
    conn.execute("DELETE FROM report_citation_links")
    conn.execute("DELETE FROM cell_evidence_links")
    conn.execute("DELETE FROM cell_revisions")
    conn.execute("DELETE FROM evidence_cells")
    conn.execute("DELETE FROM table_rows")
    conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (lib["rid"],))
    assert all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in
               ("evidence_links", "report_citation_links", "evidence_cells", "table_rows", "lineage_links", "claim_matrix_cells"))


def cleanup(paths, settings):
    # Store returns orphan paths. The API/CLI caller owns physical file deletion.
    for path in paths:
        (settings.papers_dir / path).unlink()


def test_backup_roundtrip_preserves_four_tables_old_pdf_and_both_payload_routes(review_lib, tmp_path):
    from deixis.documents.pdf import Extraction, PageText, chunk_page
    from tests.helpers import make_pdf
    lib = review_lib; settings = Settings(data_dir=tmp_path); settings.papers_dir.mkdir(); settings.payloads_dir.mkdir()
    asset, _, data, sha = asset_evidence(lib)
    (settings.papers_dir / "SYNTHETIC.pdf").write_bytes(data)
    provider_file, abstract_file = "SYNTHETIC-provider.json", "SYNTHETIC-abstract.json"
    (settings.payloads_dir / provider_file).write_text('{"SYNTHETIC":"provider"}')
    (settings.payloads_dir / abstract_file).write_text('{"SYNTHETIC":"abstract"}')
    lib["conn"].execute("UPDATE source_versions SET provider_payload_path = ? WHERE id = ?", (provider_file, lib["source_id"]))
    pid = lib["store"]._insert_passage(lib["source_id"], None, "abstract", None, None, "synthetic", abstract_file, None, "SYNTHETIC payload abstract.")
    lib["conn"].execute("INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, id, ?, ?, ?, 'SYNTHETIC payload abstract', 'exact' FROM report_claims WHERE claim_key = 'III.1'",
        (db.new_id("rln"), pid, lib["source_id"], lib["report_input_id"]))
    saved, review, _, fid = stored_review(lib)
    lib["reviews"].add_decision(fid, "dismissed", "SYNTHETIC owner reason")
    # Keep a snapshot's old asset after the user replaces the PDF.
    lib["conn"].execute("UPDATE source_assets SET removed_at = 'now', removal_reason = 'replaced' WHERE id = ?", (asset,))
    new_data = make_pdf(["SYNTHETIC replacement PDF."]); new_sha = hashlib.sha256(new_data).hexdigest()
    (settings.papers_dir / "SYNTHETIC-replacement.pdf").write_bytes(new_data)
    lib["store"].add_asset_with_pages(lib["source_id"], new_sha, len(new_data), "SYNTHETIC-replacement.pdf", "user_upload", None, None,
        Extraction("succeeded", 1, [PageText(1, None, "SYNTHETIC replacement PDF.")]), "synthetic-v2", chunk_page)
    before = {t: rows(lib["conn"], t) for t in TABLES}
    destination = create_backup(settings, tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored")
    restore_backup(destination, restored)
    conn = db.connect(restored.db_path)
    try:
        assert {t: rows(conn, t) for t in TABLES} == before
        assert hashlib.sha256((restored.papers_dir / "SYNTHETIC.pdf").read_bytes()).hexdigest() == sha
        assert hashlib.sha256((restored.papers_dir / "SYNTHETIC-replacement.pdf").read_bytes()).hexdigest() == new_sha
        for name in (provider_file, abstract_file):
            assert hashlib.sha256((restored.payloads_dir / name).read_bytes()).hexdigest() == hashlib.sha256((settings.payloads_dir / name).read_bytes()).hexdigest()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT content_json FROM owner_review_snapshots WHERE id = ?", (saved["id"],)).fetchone()[0] == saved["content_json"]
    finally: conn.close()


def test_snapshot_is_only_citation_protection_including_trashed_research(review_lib):
    lib = review_lib; saved = snapshot(lib); remove_existing_citation_protection(lib)
    lib["store"].remove_sources(lib["rid"], [lib["source_id"]], "SYNTHETIC removed")
    before = all_rows(lib["conn"])
    with pytest.raises(RevisionConflict): lib["store"].purge_sources(lib["rid"], [lib["source_id"]])
    assert all_rows(lib["conn"]) == before
    assert snapshot_referenced_source_versions(lib["conn"], [lib["source_id"]]) == {lib["source_id"]}
    lib["store"].trash_research(lib["rid"])
    assert snapshot_referenced_source_versions(lib["conn"], [lib["source_id"]]) == {lib["source_id"]}


@pytest.mark.parametrize("case", ["version", "unparsable", "manifest_shape", "sources_shape"])
def test_unreadable_snapshot_stops_purge_without_deleting_any_row(review_lib, case):
    lib = review_lib; saved = snapshot(lib); remove_existing_citation_protection(lib)
    lib["store"].remove_sources(lib["rid"], [lib["source_id"]], "SYNTHETIC removed")
    content = copy.deepcopy(saved["content"])
    if case == "version": content["version"] = 2
    elif case == "manifest_shape": content["evidence_manifest"] = [{"source_version_id": lib["source_id"]}]
    elif case == "sources_shape": content["sources"] = "malformed"
    raw = "{" if case == "unparsable" else canonical_json(content)
    lib["conn"].execute("INSERT INTO owner_review_snapshots VALUES (?, ?, 'answer', ?, ?, ?, '{}', 'now')",
                        (db.new_id("rvs"), lib["rid"], lib["answer_id"], raw, "a" * 64))
    before = all_rows(lib["conn"])
    with pytest.raises(SnapshotDependencyUnreadable): lib["store"].purge_sources(lib["rid"], [lib["source_id"]])
    assert all_rows(lib["conn"]) == before


@pytest.mark.parametrize("without_membership", [False, True])
def test_authorized_research_purge_deletes_review_rows_evidence_and_orphan_file(review_lib, tmp_path, without_membership):
    lib = review_lib; settings = Settings(data_dir=tmp_path); settings.papers_dir.mkdir()
    asset, pid, data, _ = asset_evidence(lib); (settings.papers_dir / "SYNTHETIC.pdf").write_bytes(data)
    _, _, _, fid = stored_review(lib); lib["reviews"].add_decision(fid, "deferred")
    if without_membership:
        remove_existing_citation_protection(lib)
        lib["conn"].execute("DELETE FROM corpus_memberships WHERE research_id = ?", (lib["rid"],))
        lib["conn"].execute("DELETE FROM candidates WHERE research_id = ?", (lib["rid"],))
    lib["store"].trash_research(lib["rid"])
    files, _ = lib["store"].purge_research(lib["rid"])
    assert files == ["SYNTHETIC.pdf"]
    cleanup(files, settings)
    assert not (settings.papers_dir / "SYNTHETIC.pdf").exists()
    assert all(lib["conn"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in TABLES)
    assert lib["conn"].execute("SELECT 1 FROM source_versions WHERE id = ?", (lib["source_id"],)).fetchone() is None
    assert lib["conn"].execute("SELECT 1 FROM passages WHERE id = ?", (pid,)).fetchone() is None
    assert lib["conn"].execute("SELECT 1 FROM source_assets WHERE id = ?", (asset,)).fetchone() is None
    assert lib["conn"].execute("PRAGMA foreign_key_check").fetchall() == []


def test_other_research_snapshot_alone_keeps_old_asset_passages_and_file_then_allows_source_purge(review_lib, tmp_path):
    lib = review_lib; settings = Settings(data_dir=tmp_path); settings.papers_dir.mkdir()
    asset, pid, data, _ = asset_evidence(lib); (settings.papers_dir / "SYNTHETIC.pdf").write_bytes(data)
    lib["conn"].execute("UPDATE source_assets SET removed_at = 'now', removal_reason = 'replaced' WHERE id = ?", (asset,))
    other = lib["store"].create_research("SYNTHETIC snapshot owner", "attached", "quick", [], "fake", None, "en")
    b = dict(lib, rid=other)
    b["answer_id"] = make_answer(b)
    lib["conn"].execute("INSERT INTO evidence_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, c.id, ?, ?, a.step_input_id, 'SYNTHETIC pdf evidence', 'exact' FROM claims c JOIN answers a ON a.id = c.answer_id WHERE a.id = ?",
        (db.new_id("evl"), pid, lib["source_id"], b["answer_id"]))
    saved = snapshot(b, "answer")
    remove_existing_citation_protection(lib)
    assert not lib["conn"].execute("SELECT 1 FROM corpus_memberships WHERE research_id = ?", (other,)).fetchone()
    lib["store"].trash_research(lib["rid"])
    files, _ = lib["store"].purge_research(lib["rid"])
    assert files == []
    assert (settings.papers_dir / "SYNTHETIC.pdf").exists()
    assert lib["store"].passage(pid)["asset_id"] == asset
    assert lib["conn"].execute("PRAGMA foreign_key_check").fetchall() == []
    # A third research holds only a removed membership, so source-level purge can be tested
    # after the snapshot's owner is purged without the source disappearing first.
    third = lib["store"].create_research("SYNTHETIC removed source owner", "attached", "quick", [], "fake", None, "en")
    lib["store"].add_to_corpus(third, lib["source_id"], "user_upload", selection_state="included", selection_origin="user")
    lib["store"].remove_sources(third, [lib["source_id"]], "SYNTHETIC removed")
    with pytest.raises(RevisionConflict): lib["store"].purge_sources(third, [lib["source_id"]])
    lib["store"].trash_research(other); lib["store"].purge_research(other)
    purged, files, _ = lib["store"].purge_sources(third, [lib["source_id"]])
    assert purged == [lib["source_id"]] and files == ["SYNTHETIC.pdf"]
    cleanup(files, settings)
    assert lib["conn"].execute("PRAGMA foreign_key_check").fetchall() == []


def test_snapshot_owner_purge_preserves_other_answer_citation_without_membership(review_lib):
    lib = review_lib
    asset, pid, _, _ = asset_evidence(lib)
    saved = snapshot(lib)
    other = lib["store"].create_research("SYNTHETIC citing owner", "attached", "quick", [], "fake", None, "en")
    b = dict(lib, rid=other); b["answer_id"] = make_answer(b)
    lib["conn"].execute(
        "INSERT INTO evidence_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, c.id, ?, ?, a.step_input_id, 'SYNTHETIC pdf evidence', 'exact' FROM claims c"
        " JOIN answers a ON a.id = c.answer_id WHERE a.id = ?",
        (db.new_id("evl"), pid, lib["source_id"], b["answer_id"]),
    )
    for table in ("corpus_memberships", "candidates"):
        lib["conn"].execute(f"DELETE FROM {table} WHERE research_id = ?", (lib["rid"],))
        assert not lib["conn"].execute(f"SELECT 1 FROM {table} WHERE research_id = ?", (other,)).fetchone()
    lib["store"].trash_research(lib["rid"])
    assert lib["store"].purge_research(lib["rid"]) == ([], [])
    assert not lib["conn"].execute("SELECT 1 FROM owner_review_snapshots WHERE id = ?", (saved["id"],)).fetchone()
    assert lib["store"].passage(pid)["asset_id"] == asset
    assert lib["conn"].execute("SELECT 1 FROM source_versions WHERE id = ?", (lib["source_id"],)).fetchone()
    assert lib["conn"].execute("PRAGMA foreign_key_check").fetchall() == []


def test_research_purge_scans_remaining_snapshots_once_for_all_sources(review_lib, monkeypatch):
    from deixis.workflow.review import store as review_store
    lib = review_lib; snapshot(lib)
    extra = lib["store"].create_upload_source("SYNTHETIC second source")
    lib["store"].add_to_corpus(lib["rid"], extra, "user_upload", selection_state="included", selection_origin="user")
    original = review_store.snapshot_referenced_source_versions
    calls = []
    def scan(conn, svids):
        calls.append(set(svids))
        return original(conn, svids)
    monkeypatch.setattr(review_store, "snapshot_referenced_source_versions", scan)
    lib["store"].trash_research(lib["rid"])
    lib["store"].purge_research(lib["rid"])
    assert calls == [{lib["source_id"], extra}]
