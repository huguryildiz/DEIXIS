"""S8-S13 synthetic backup, authorized purge, and cross-process recovery ownership."""

import asyncio
import copy
import hashlib
import json
import shutil
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain.rules import RevisionConflict
from deixis.storage import backup, db
from deixis.workflow.store import Store
from tests.reextract_r2a_helpers import api_library, child_lock, seed, sharing, store_library
from tests.reextract_r2b_helpers import tear, write
from tests.reextract_r2c_helpers import child, release_child, startup
from tests.reextract_r3_helpers import no_external_calls, retry, rich
from tests.review_helpers import all_rows


HISTORY = ("asset_file_observations", "asset_recovery_operations", "asset_extractions", "passages",
           "owner_review_snapshots", "owner_reviews", "owner_review_findings", "owner_review_decisions")


def history(conn):
    rows = all_rows(conn)
    return {t: rows[t] for t in HISTORY}


def test_s8_backup_retained_roundtrip_red_on_old(tmp_path, monkeypatch):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        unrelated = sharing(lib)
        tear(lib)
        write(lib)
        retry(lib)
        saved = history(lib.conn)
        archive = backup.create_backup(lib.settings, tmp_path / "backups")
        manifest = json.loads((archive / backup.MANIFEST).read_text())
        name = "retained-" + lib.torn_sha + ".bin"
        assert any(f["path"] == "papers/" + name and f["sha256"] == lib.torn_sha for f in manifest["files"])
        restored = Settings(data_dir=tmp_path / "restored")
        backup.restore_backup(archive, restored)
        conn = db.connect(restored.db_path)
        try:
            assert history(conn) == saved
            assert (restored.papers_dir / name).read_bytes() == lib.torn
            assert (restored.papers_dir / lib.path.name).read_bytes() == lib.data
            def forbidden(*args, **kwargs):
                raise AssertionError("Restored startup retried text")
            monkeypatch.setattr("deixis.documents.pdf.extract_pdf", forbidden)
            restored_lib = SimpleNamespace(settings=restored)
            with startup(restored_lib):
                pass
            assert history(conn) == saved
            store = Store(conn)
            store.trash_research(unrelated)
            assert store.purge_research(unrelated) == ([], [])
            assert history(conn) == saved and (restored.papers_dir / name).read_bytes() == lib.torn
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()


@pytest.mark.parametrize("bad", ["contradictory_assets", "retained_identity", "missing_retained", "unreferenced"])
def test_s8_backup_refusals_new_contract(tmp_path, bad):
    """Paired with S8; only observation-owned retained bytes are backup evidence."""
    with store_library(tmp_path) as lib:
        tear(lib)
        write(lib)
        name = "retained-" + lib.torn_sha + ".bin"
        if bad == "contradictory_assets":
            svid = lib.store.create_upload_source("SYNTHETIC contradictory file identity")
            from deixis.documents import pdf
            lib.store.add_asset_with_pages(svid, "b" * 64, len(lib.data), lib.path.name, "user_upload", None, None,
                                          pdf.Extraction("failed"), pdf.EXTRACTION_VERSION, pdf.chunk_page)
        elif bad == "retained_identity":
            lib.store.add_file_observation(kind="before_restore", operation_id=None, storage_path=lib.path.name,
                expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256="b" * 64,
                observed_byte_size=len(lib.torn), integrity="mismatch", retained_filename=name)
        elif bad == "missing_retained":
            (lib.settings.papers_dir / name).unlink()
        else:
            orphan = "retained-" + "c" * 64 + ".bin"
            (lib.settings.papers_dir / orphan).write_bytes(b"SYNTHETIC unreferenced")
            archive = backup.create_backup(lib.settings, tmp_path / "backups")
            assert not (archive / "papers" / orphan).exists()
            assert "recovery (file locks and private temporary copies)" in backup.NOT_INCLUDED
            return
        with pytest.raises(backup.BackupError) as exc:
            backup.create_backup(lib.settings, tmp_path / "backups")
        if bad == "contradictory_assets":
            assert str(exc.value) == "contradictory hashes recorded for papers/" + lib.path.name
        assert not list((tmp_path / "backups").glob("deixis-backup-*"))


@pytest.mark.parametrize("release", [False, True])
def test_s9_backup_busy_or_release_new_contract(tmp_path, monkeypatch, release):
    """Paired with S8; a real child owns the hash lock during backup."""
    monkeypatch.setattr("deixis.workflow.file_restore.WRITER_LOCK_WAIT_SECONDS", 0.3 if release else 0.03)
    with store_library(tmp_path) as lib:
        with child_lock(lib) as process:
            if release:
                timer = threading.Timer(0.08, lambda: (process.stdin.write("release\n"), process.stdin.flush()))
                timer.start()
                archive = backup.create_backup(lib.settings, tmp_path / "backups")
                timer.join()
                assert (archive / "papers" / lib.path.name).read_bytes() == lib.data
            else:
                with pytest.raises(backup.BackupError, match="busy with a file repair, text retry or equation read"):
                    backup.create_backup(lib.settings, tmp_path / "backups")
                assert not list((tmp_path / "backups").glob("deixis-backup-*"))


def test_s9_retention_rename_race_new_contract(tmp_path, monkeypatch):
    """Paired with S8: a parked real restore has durable bytes but no observation yet."""
    with store_library(tmp_path) as lib:
        tear(lib)
        (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
        monkeypatch.setattr("deixis.workflow.file_restore.WRITER_LOCK_WAIT_SECONDS", 0.03)
        with child(lib, "park_restore", "retained", parked=True) as process:
            with pytest.raises(backup.BackupError):
                backup.create_backup(lib.settings, tmp_path / "backups")
            assert not list((tmp_path / "backups").glob("deixis-backup-*"))
            release_child(process)
        archive = backup.create_backup(lib.settings, tmp_path / "backups")
        entries = json.loads((archive / backup.MANIFEST).read_text())["files"]
        assert all(hashlib.sha256((archive / f["path"]).read_bytes()).hexdigest() == f["sha256"] for f in entries)


def test_s9_running_retry_backup_reconciled_new_contract(tmp_path, monkeypatch):
    """Paired with S8; the snapshot's running receipt is reconciled, never replayed."""
    with store_library(tmp_path, "partial") as lib:
        with child(lib, "text", "parser"):
            pass
        archive = backup.create_backup(lib.settings, tmp_path / "backups")
        restored = Settings(data_dir=tmp_path / "restored")
        backup.restore_backup(archive, restored)
        def forbidden(*args, **kwargs):
            raise AssertionError("Startup parsed a backed-up running retry")
        monkeypatch.setattr("deixis.documents.pdf.extract_pdf", forbidden)
        with startup(SimpleNamespace(settings=restored)) as (app, _):
            row = app.state.store.conn.execute("SELECT * FROM asset_recovery_operations").fetchone()
            assert row["lifecycle"] == "interrupted" and row["reason"] == "process_ended"


@pytest.mark.parametrize("source_only", [False, True])
def test_s10_unshared_history_purged_red_on_old(tmp_path, source_only):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        tear(lib)
        write(lib)
        retry(lib)
        name = "retained-" + lib.torn_sha + ".bin"
        if source_only:
            lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removal")
            response = lib.client.post(f"/api/researches/{lib.rid}/sources/purge", json={"source_version_ids": [lib.svid]})
        else:
            lib.store.trash_research(lib.rid)
            response = lib.client.delete(f"/api/trash/{lib.rid}")
        assert lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE expected_sha256 = ?", (lib.sha,)).fetchall() == []
        assert response.status_code == 200, response.text
        assert not lib.conn.execute("SELECT * FROM asset_file_observations WHERE expected_sha256 = ?", (lib.sha,)).fetchall()
        assert not (lib.settings.papers_dir / name).exists() and response.json()["files_not_removed"] == []
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not lib.conn.execute("SELECT * FROM recovery_purge_authorizations").fetchall()


@pytest.mark.parametrize("sharing_kind", ["source", "bytes"])
def test_s10_shared_recovery_history_guard(tmp_path, sharing_kind):
    with store_library(tmp_path, "partial") as lib:
        tear(lib)
        write(lib)
        retry(lib)
        before = history(lib.conn)
        if sharing_kind == "source":
            sharing(lib)
        else:
            other = seed(lib.store, lib.settings, "partial")
            assert other.svid != lib.svid and other.sha == lib.sha
        lib.store.trash_research(lib.rid)
        files, _ = lib.store.purge_research(lib.rid)
        after = history(lib.conn)
        if sharing_kind == "source":
            assert after == before
        else:
            assert not lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE asset_id = ?", (lib.aid,)).fetchall()
            assert lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE kind = 'file_restore'").fetchall()
            assert not lib.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ?", (lib.aid,)).fetchall()
        assert "retained-" + lib.torn_sha + ".bin" not in files
        assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


def frozen_record(lib, kind, raw, owner=None):
    owner = owner or lib.rid
    run = lib.store.create_run(owner, "report" if kind != "input" else "answer", {}, None)
    if kind == "input":
        step = lib.store.step(run["id"], "r3:frozen", "model:grounded_answer")
        lib.store.insert_step_input(step["id"], owner, run["id"], 0,
            {"step_input_id": db.new_id("sti"), "task_type": "grounded_answer", "scope_revision": 1,
             "skill_package_hash": "sha256:synthetic", **(raw if isinstance(raw, dict) else {})},
            "base", "developer", "message", {})
        if not isinstance(raw, dict):
            # Insert unreadable historical JSON directly without rewriting an immutable row.
            row = dict(lib.conn.execute("SELECT * FROM step_inputs WHERE step_id = ?", (step["id"],)).fetchone())
            row.update(id=db.new_id("sti"), attempt=1, payload_json=raw)
            lib.conn.execute("INSERT INTO step_inputs (" + ",".join(row) + ") VALUES (" + ",".join("?" for _ in row) + ")", tuple(row.values()))
    else:
        from deixis.workflow.report.store import ReportStore
        report_id = ReportStore(lib.store).create_report(owner, run["id"], 1, "en")
        encoded = json.dumps(raw) if isinstance(raw, dict) else raw
        if kind == "snapshot":
            from deixis.workflow.tables import TableStore
            table_id = TableStore(lib.store).create_table(owner, "SYNTHETIC frozen table", [], None, None)
            lib.conn.execute("INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at) VALUES (?, ?, 1, ?, ?)", (report_id, table_id, encoded, db.now()))
        else:
            lib.conn.execute("INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json, created_at)"
                             " VALUES (?, ?, 'G1', 'stated_limitation', 'SYNTHETIC gap', ?, '{}', ?)", (db.new_id("rga"), report_id, encoded, db.now()))
    lib.store.update_run(run["id"], status="completed")


@pytest.mark.parametrize("kind", ["input", "snapshot", "basis"])
def test_s10b_frozen_only_protection_red_on_old(tmp_path, kind):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        pid = lib.store.passages_for(lib.svid)[0]["id"]
        raw = {"passages": [{"passage_id": pid}]} if kind == "input" else (
            {"cells": [{"evidence": [{"passage_id": pid}]}]} if kind == "snapshot" else {"basis_passage_ids": [pid]})
        frozen_record(lib, kind, raw)
        lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        # Empty table rows leave the JSON as the sole frozen passage reference.
        assert lib.store.cited_source_versions([lib.svid]) == set()
        before = all_rows(lib.conn)
        response = lib.client.post(f"/api/researches/{lib.rid}/sources/purge", json={"source_version_ids": [lib.svid]})
        assert response.status_code == 409 and lib.conn.execute("SELECT id FROM source_versions WHERE id = ?", (lib.svid,)).fetchone()
        assert all_rows(lib.conn) == before
        other = sharing(lib)
        lib.store.trash_research(other)
        assert lib.store.purge_research(other) == ([], [])
        assert lib.store.passage(pid)["source_version_id"] == lib.svid


@pytest.mark.parametrize("kind", ["input", "snapshot", "basis"])
@pytest.mark.parametrize("raw", ["{", {"passage_id": 2}, {"passage_id": {}}, {"basis_passage_ids": "wrong"}, {"basis_passage_ids": [3]}])
@pytest.mark.parametrize("whole_research", [False, True])
def test_s10b_unreadable_frozen_refuses_new_contract(tmp_path, kind, raw, whole_research):
    """Paired with S10b; unreadable surviving records roll back every application row."""
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        owner = lib.store.create_research("SYNTHETIC frozen owner", "attached", "quick", [], "fake", "fake", None)
        lib.store.add_to_corpus(owner, lib.svid, "user_upload")
        frozen_record(lib, kind, raw, owner)
        if whole_research:
            lib.store.trash_research(lib.rid)
        else:
            lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        before = all_rows(lib.conn)
        response = (lib.client.delete(f"/api/trash/{lib.rid}") if whole_research else
                    lib.client.post(f"/api/researches/{lib.rid}/sources/purge", json={"source_version_ids": [lib.svid]}))
        assert response.status_code == 409 and response.json()["code"] == "frozen_dependency_unreadable"
        assert all_rows(lib.conn) == before


@pytest.mark.parametrize("kind", ["input", "snapshot", "basis"])
@pytest.mark.parametrize("raw", ["{", {"passage_id": 2}, {"passage_id": {}}, {"basis_passage_ids": "wrong"}, {"basis_passage_ids": [3]}])
@pytest.mark.parametrize("whole_research", [False, True])
def test_s10b_unrelated_unreadable_frozen_does_not_block_new_contract(tmp_path, kind, raw, whole_research):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        owner = lib.store.create_research("SYNTHETIC unrelated frozen owner", "attached", "quick", [], "fake", "fake", None)
        frozen_record(lib, kind, raw, owner)
        if whole_research:
            lib.store.trash_research(lib.rid)
        else:
            lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        unrelated = all_rows(lib.conn)
        response = (lib.client.delete(f"/api/trash/{lib.rid}") if whole_research else
                    lib.client.post(f"/api/researches/{lib.rid}/sources/purge", json={"source_version_ids": [lib.svid]}))
        assert response.status_code == 200
        assert not lib.conn.execute("SELECT id FROM source_versions WHERE id = ?", (lib.svid,)).fetchone()
        after = all_rows(lib.conn)
        for table in ("step_inputs", "report_snapshot", "report_gaps", "reports"):
            assert after[table] == unrelated[table]
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


def link_frozen_owner(lib, owner, kind):
    if kind == "removed_corpus":
        lib.store.add_to_corpus(owner, lib.svid, "user_upload")
        lib.store.remove_sources(owner, [lib.svid], "SYNTHETIC removed from linked research")
    elif kind == "candidate":
        lib.conn.execute("INSERT INTO candidates (id, research_id, source_version_id, created_at) VALUES (?, ?, ?, ?)",
                         (db.new_id("can"), owner, lib.svid, db.now()))
    else:
        from deixis.workflow.candidates.store import CandidateStore
        candidates = CandidateStore(lib.store)
        candidate = candidates.open_from_owner_text(owner, "SYNTHETIC scope claim")
        version = candidates.add_version(owner, candidate["id"], claim_statement="SYNTHETIC scope claim",
            conditions=[], elements=[{"text": "SYNTHETIC mechanism", "kind": "mechanism"},
                                     {"text": "SYNTHETIC outcome", "kind": "outcome"}],
            nearest_simple_explanation=None, critical_assumption="SYNTHETIC assumption", validation_plan="SYNTHETIC plan",
            origin="human_edit", step_input_id=None, expected_version=0)
        run = lib.store.create_run(owner, "kill_search", {}, None)
        search = candidates.start_kill_search(owner, version["id"], run["id"], query_block={}, rendered_queries=[],
                                             skipped_terms=[], selection={})
        if kind == "query_record":
            lib.conn.execute("INSERT INTO kill_search_queries (kill_search_id, position, status, provider, query_text,"
                             " record_count, records_sha256) VALUES (?, 1, 'succeeded', 'openalex', 'SYNTHETIC', 1, ?)",
                             (search["id"], "0" * 64))
            lib.conn.execute("INSERT INTO kill_search_query_records (kill_search_id, position, rank, provider, source_version_id)"
                             " VALUES (?, 1, 1, 'openalex', ?)", (search["id"], lib.svid))
        else:
            lib.conn.execute("INSERT INTO kill_search_hits (kill_search_id, source_version_id, rank_key, kept, cut_reason)"
                             " VALUES (?, ?, 1, 0, 'rank_cut')", (search["id"], lib.svid))
        lib.store.update_run(run["id"], status="completed")


@pytest.mark.parametrize("link", ["removed_corpus", "candidate", "query_record", "hit"])
@pytest.mark.parametrize("kind", ["input", "snapshot", "basis"])
@pytest.mark.parametrize("whole_research", [False, True])
def test_s10b_each_link_scopes_unreadable_refusal_new_contract(tmp_path, link, kind, whole_research):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        owner = lib.store.create_research("SYNTHETIC linked frozen owner", "attached", "quick", [], "fake", "fake", None)
        link_frozen_owner(lib, owner, link)
        frozen_record(lib, kind, "{", owner)
        if whole_research:
            lib.store.trash_research(lib.rid)
        else:
            lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        before = all_rows(lib.conn)
        response = (lib.client.delete(f"/api/trash/{lib.rid}") if whole_research else
                    lib.client.post(f"/api/researches/{lib.rid}/sources/purge", json={"source_version_ids": [lib.svid]}))
        assert response.status_code == 409 and response.json()["code"] == "frozen_dependency_unreadable"
        assert all_rows(lib.conn) == before


def test_s10b_nullable_candidate_and_review_inputs_guard(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        frozen_record(lib, "input", {"candidate": {"passage_id": None}, "review": {"passage_id": None}, "passage_ids": []})
        lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        assert lib.store.purge_sources(lib.rid, [lib.svid])[0] == [lib.svid]


@pytest.mark.parametrize("mode,boundary", [("park_text", "parser"), ("park_restore", "retention_copy")])
def test_s11_live_recovery_blocks_purge_red_on_old(tmp_path, mode, boundary):
    with store_library(tmp_path, "partial") as lib:
        if mode == "park_restore":
            tear(lib)
            (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
        with child(lib, mode, boundary, parked=True) as process:
            lib.store.trash_research(lib.rid)
            before = all_rows(lib.conn)
            with pytest.raises(RevisionConflict, match="still running"):
                lib.store.purge_research(lib.rid)
            assert all_rows(lib.conn) == before
            release_child(process)
        lib.store.purge_research(lib.rid)
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("table", ["asset_file_observations", "asset_recovery_operations"])
def test_s12_delete_guard_red_on_old(tmp_path, table):
    with store_library(tmp_path) as lib:
        # No incoming FK: on the old schema DELETE succeeds, so this tests authorization itself.
        lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        lib.store.add_file_observation(kind="extraction_input", storage_path=lib.path.name,
            expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
            observed_byte_size=len(lib.data), integrity="verified")
        row = dict(lib.conn.execute("SELECT * FROM " + table + " LIMIT 1").fetchone())
        with pytest.raises(sqlite3.IntegrityError, match="recovery history requires purge authorization"):
            lib.conn.execute("DELETE FROM " + table + " WHERE id = ?", (row["id"],))
        assert dict(lib.conn.execute("SELECT * FROM " + table + " WHERE id = ?", (row["id"],)).fetchone()) == row
        with pytest.raises(sqlite3.IntegrityError):
            lib.conn.execute("INSERT OR REPLACE INTO " + table + " (" + ",".join(row) + ") VALUES (" + ",".join("?" for _ in row) + ")", tuple(row.values()))
        with db.transaction(lib.conn):
            lib.conn.execute("INSERT INTO recovery_purge_authorizations VALUES (?)", (lib.sha,))
            lib.conn.execute("DELETE FROM asset_file_observations WHERE expected_sha256 = ?", (lib.sha,))
            lib.conn.execute("DELETE FROM asset_recovery_operations WHERE expected_sha256 = ?", (lib.sha,))
            lib.conn.execute("DELETE FROM recovery_purge_authorizations")
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


def test_s12_0068_to_0069_preservation_new_contract(tmp_path, monkeypatch):
    """Paired with S12; only the new table and delete guards are introduced."""
    real = db.MIGRATIONS_DIR
    old = tmp_path / "migrations"
    old.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= 68:
            shutil.copyfile(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        tear(lib)
        write(lib)
        retry(lib)
        before = all_rows(lib.conn)
        objects = list(lib.conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"))
        shutil.copyfile(real / "0069_recovery_purge_authorization.sql", old / "0069_recovery_purge_authorization.sql")
        assert db.migrate(lib.conn) == [69]
        after = all_rows(lib.conn)
        assert all(after[t] == rows for t, rows in before.items() if t != "schema_migrations")
        assert set(map(tuple, objects)) <= set(map(tuple, lib.conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")))
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("state", ["plain", "live_restore", "crashed_restore"])
def test_s13_recovery_files_cli_new_contract(tmp_path, capsys, state):
    """Paired with S10/S10h: listing never deletes, deletion shares the guarded unlink."""
    from deixis.__main__ import recovery_files
    with store_library(tmp_path) as lib:
        tear(lib)
        write(lib)
        referenced = lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")
        orphan = lib.settings.papers_dir / ("retained-" + "a" * 64 + ".bin")
        orphan.write_bytes(b"SYNTHETIC orphan")
        partial = lib.settings.papers_dir / "synthetic.part"
        partial.write_bytes(b"SYNTHETIC staging")
        assert recovery_files(lib.settings, False) == 0 and orphan.exists()
        assert orphan.name in capsys.readouterr().out
        if state != "plain":
            tear(lib)
            (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
            with child(lib, "park_restore" if state == "live_restore" else "restore", "retention_copy", parked=state == "live_restore") as process:
                assert recovery_files(lib.settings, True) == (1 if state == "live_restore" else 0)
                assert orphan.exists() is (state == "live_restore")
                if state == "live_restore":
                    assert "not removed " + orphan.name in capsys.readouterr().out
                    release_child(process)
            if state == "crashed_restore":
                assert lib.conn.execute("SELECT reason FROM asset_recovery_operations ORDER BY created_at DESC LIMIT 1").fetchone()[0] == "process_ended"
        else:
            assert recovery_files(lib.settings, True) == 0 and not orphan.exists()
        assert referenced.exists() and partial.exists()


@pytest.mark.parametrize("protection", ["citation", "snapshot"])
def test_s10_citation_and_snapshot_protection_guard(tmp_path, protection):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        tear(lib)
        write(lib)
        retry(lib)
        owner = lib.store.create_research("SYNTHETIC other evidence owner", "attached", "quick", [], "fake", "fake", None)
        if protection == "snapshot":
            content = copy.deepcopy(lib.snapshots[0]["content"])
            content["research_id"] = owner
            lib.rich["reviews"].add_snapshot(content, lib.snapshots[0]["markers"])
        elif protection == "citation":
            run = lib.store.create_run(owner, "answer", {}, None)
            step = lib.store.step(run["id"], "r3:citation-only", "model:grounded_answer")
            iid = db.new_id("sti")
            lib.store.insert_step_input(step["id"], owner, run["id"], 0,
                {"step_input_id": iid, "task_type": "grounded_answer", "scope_revision": 1,
                 "skill_package_hash": "synthetic", "passages": [], "sources": []}, "base", "developer", "message", {})
            lib.store.save_answer(owner, run["id"], step["id"], iid, 1, "structurally_valid",
                {"title": "SYNTHETIC surviving answer", "answer_language": "en", "claims": [{"claim_label": "c1", "text": "SYNTHETIC surviving citation",
                "section": "Methods", "support_type": "source_stated"}]}, {},
                [{"claim_label": "c1", "passage_id": lib.pid, "source_id": lib.svid,
                  "anchor_text": lib.store.passage(lib.pid)["text"], "anchor_match": "exact"}])
            lib.store.update_run(run["id"], status="completed")
        before = history(lib.conn)
        lib.store.trash_research(lib.rid)
        files, _ = lib.store.purge_research(lib.rid)
        after = history(lib.conn)
        for table in HISTORY[:4]:
            assert after[table] == before[table]
        assert not files
        assert not lib.conn.execute("SELECT * FROM corpus_memberships WHERE source_version_id = ?", (lib.svid,)).fetchall()
        assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


def test_s10_own_snapshot_purge_order_new_contract(tmp_path):
    """Paired with S10 and B1 purge guards: owned reviews go before recovery history."""
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        tear(lib)
        write(lib)
        retry(lib)
        lib.store.trash_research(lib.rid)
        files, _ = lib.store.purge_research(lib.rid)
        for table in HISTORY:
            assert not lib.conn.execute("SELECT * FROM " + table).fetchall()
        assert "retained-" + lib.torn_sha + ".bin" in files
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("case", ["version", "unparsable", "manifest_shape", "sources_shape"])
@pytest.mark.parametrize("source_only", [False, True])
def test_s10_unreadable_owner_snapshot_guard(tmp_path, case, source_only):
    from deixis.workflow.review.store import SnapshotDependencyUnreadable
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        tear(lib)
        write(lib)
        owner = lib.store.create_research("SYNTHETIC snapshot-only owner", "attached", "quick", [], "fake", "fake", None)
        content = copy.deepcopy(lib.snapshots[0]["content"])
        if case == "version":
            content["version"] = 2
        elif case == "manifest_shape":
            content["evidence_manifest"] = [{"source_version_id": lib.svid}]
        elif case == "sources_shape":
            content["sources"] = "wrong shape"
        raw = "{" if case == "unparsable" else json.dumps(content)
        lib.conn.execute("INSERT INTO owner_review_snapshots VALUES (?, ?, 'answer', ?, ?, ?, '{}', 'now')",
            (db.new_id("rvs"), owner, lib.answer_id, raw, "a" * 64))
        if source_only:
            lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removal")
        else:
            lib.store.trash_research(lib.rid)
        before = all_rows(lib.conn)
        with pytest.raises(SnapshotDependencyUnreadable):
            lib.store.purge_sources(lib.rid, [lib.svid]) if source_only else lib.store.purge_research(lib.rid)
        assert all_rows(lib.conn) == before


@pytest.mark.parametrize("owned_by", ["file_restore", "text_retry"])
def test_s10_outside_observation_fk_closure_new_contract(tmp_path, owned_by):
    """Paired with S10: frozen pointers are kept, never cleared to make deletion work."""
    from deixis.documents import pdf
    with store_library(tmp_path, "partial") as lib:
        tear(lib)
        result = write(lib)
        if owned_by == "text_retry":
            operation = retry(lib)
            observation = operation["input_observation_id"]
        else:
            observation = lib.conn.execute("SELECT before_observation_id FROM asset_recovery_operations WHERE id = ?",
                                           (result.operation_id,)).fetchone()[0]
        other_svid = lib.store.create_upload_source("SYNTHETIC outside extraction reference")
        other_rid = lib.store.create_research("SYNTHETIC outside reference owner", "attached", "quick", [], "fake", "fake", None)
        lib.store.add_to_corpus(other_rid, other_svid, "user_upload")
        lib.store.add_asset_with_pages(other_svid, "b" * 64, 0, "synthetic-outside.pdf", "user_upload", None, None,
            pdf.Extraction("failed"), pdf.EXTRACTION_VERSION, pdf.chunk_page, input_observation_id=observation)
        lib.store.trash_research(lib.rid)
        before = all_rows(lib.conn)
        if owned_by == "text_retry":
            with pytest.raises(RevisionConflict, match="still referenced elsewhere"):
                lib.store.purge_research(lib.rid)
            assert all_rows(lib.conn) == before
        else:
            files, _ = lib.store.purge_research(lib.rid)
            assert lib.conn.execute("SELECT id FROM asset_file_observations WHERE id = ?", (observation,)).fetchone()
            assert lib.conn.execute("SELECT id FROM asset_recovery_operations WHERE id = ?", (result.operation_id,)).fetchone()
            assert "retained-" + lib.torn_sha + ".bin" not in files
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


def test_s10_purge_never_reads_extraction_payloads_new_contract(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        tear(lib)
        write(lib)
        retry(lib)
        sharing_source = lib.store.create_upload_source("SYNTHETIC unrelated source")
        from deixis.documents import pdf
        lib.store.add_asset_with_pages(sharing_source, "b" * 64, 0, "unrelated.pdf", "user_upload", None, None,
            pdf.Extraction("failed", math={"SYNTHETIC": "math" * 1000}, ocr={"SYNTHETIC": "ocr" * 1000}),
            pdf.EXTRACTION_VERSION, pdf.chunk_page)
        lib.store.trash_research(lib.rid)

        def forbid_payload_read(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table == "asset_extractions" and column in ("math_json", "ocr_json"):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        lib.conn.set_authorizer(forbid_payload_read)
        try:
            files, _ = lib.store.purge_research(lib.rid)
        finally:
            lib.conn.set_authorizer(None)
        assert "retained-" + lib.torn_sha + ".bin" in files
        assert lib.conn.execute("SELECT id FROM source_versions WHERE id = ?", (sharing_source,)).fetchone()
        assert not lib.conn.execute("SELECT * FROM recovery_purge_authorizations").fetchall()
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("race", ["referenced", "running", "unlink_failure"])
def test_s10h_cross_hash_guarded_unlink_new_contract(tmp_path, monkeypatch, race):
    """Paired with S10: a different hash can take ownership after purge commits."""
    from deixis.workflow import recovery_history
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        tear(lib)
        write(lib)
        name = "retained-" + lib.torn_sha + ".bin"
        real = recovery_history.remove_retained
        def raced(store, papers, filename):
            assert filename == name and not store.conn.in_transaction
            if race != "unlink_failure":
                operation = store.reserve_file_restore("b" * 64, 1, caller="upload", research_id=None)
                if race == "referenced":
                    store.record_file_restore_observation(operation["id"], "before_restore", storage_path="synthetic-other.pdf",
                        expected_sha256="b" * 64, expected_byte_size=1, observed_sha256=lib.torn_sha,
                        observed_byte_size=len(lib.torn), integrity="mismatch", retained_filename=name)
                    store.interrupt_file_restore(operation["id"], "process_ended")
            return real(store, papers, filename)
        monkeypatch.setattr(recovery_history, "remove_retained", raced)
        if race == "unlink_failure":
            from pathlib import Path
            unlink = Path.unlink
            def failing(path, *args, **kwargs):
                if path.name == name:
                    raise OSError("SYNTHETIC retained unlink refused")
                return unlink(path, *args, **kwargs)
            monkeypatch.setattr(Path, "unlink", failing)
        lib.store.trash_research(lib.rid)
        response = lib.client.delete(f"/api/trash/{lib.rid}")
        assert response.status_code == 200 and response.json()["files_not_removed"] == [name]
        assert (lib.settings.papers_dir / name).read_bytes() == lib.torn
        assert not lib.conn.in_transaction and not lib.conn.execute("PRAGMA foreign_key_check").fetchall()
