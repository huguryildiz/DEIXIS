"""SYNTHETIC candidate snapshots, backup file reachability and authorized purge."""

import hashlib
from pathlib import Path

import pytest

from deixis.config import Settings
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.review.store import snapshot_referenced_source_versions
from tests.fakes import FakeAdapter
from tests.helpers import make_pdf
from tests.review.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, candidate_body, candidate_response
from tests.review.review_helpers import rows, all_rows
from tests.review.review_run_helpers import review_api, start, turn, read
from tests.review.test_review_store import TABLES


def test_candidate_snapshot_protects_search_only_sources_and_authorized_purge_orders_rows(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    sid = saved["content"]["matrix"][0]["source_id"]
    assert not lib["conn"].execute("SELECT 1 FROM corpus_memberships WHERE source_version_id=?", (sid,)).fetchone()
    assert sid in snapshot_referenced_source_versions(lib["conn"], [sid])
    third = lib["store"].create_research("SYNTHETIC purge owner", "attached", "quick", [], "fake", None, "en")
    lib["store"].add_to_corpus(third, sid, "user_upload", selection_state="included", selection_origin="user")
    lib["store"].remove_sources(third, [sid], "SYNTHETIC removed")
    before = all_rows(lib["conn"])
    with pytest.raises(RevisionConflict): lib["store"].purge_sources(third, [sid])
    assert all_rows(lib["conn"]) == before
    lib["store"].trash_research(lib["rid"])
    lib["store"].purge_research(lib["rid"])
    assert all(not lib["conn"].execute(f"SELECT 1 FROM {t}").fetchone() for t in TABLES)
    assert not lib["conn"].execute("SELECT 1 FROM research_candidates WHERE research_id=?", (lib["rid"],)).fetchone()
    assert not snapshot_referenced_source_versions(lib["conn"], [sid])
    assert lib["store"].purge_sources(third, [sid])[0] == [sid]
    assert not lib["conn"].execute("PRAGMA foreign_key_check").fetchall()


def test_candidate_review_backup_restores_four_tables_and_snapshot_only_asset_payload_files(candidate_lib, tmp_path):
    with review_api(candidate_lib, tmp_path, adapter=FakeAdapter(responder=candidate_response)) as api:
        opened, _, _ = start(api, candidate_body(candidate_lib)); turn(api)
        detail = read(api, opened["review"]["id"])
        row = detail["findings"][0]
        response = api.client.post(api.url + f"/{detail['id']}/findings/{row['id']}/decisions",
            json=dict(decision="dismissed", reason="SYNTHETIC backup decision", expected_ordinal=0), headers={"Idempotency-Key": "SYNTHETIC-backup"})
        assert response.status_code == 200
        settings = Settings(data_dir=Path(api.conn.execute("PRAGMA database_list").fetchone()[2]).parent)
        settings.papers_dir.mkdir(exist_ok=True); settings.payloads_dir.mkdir(exist_ok=True)
        for asset in api.conn.execute("SELECT * FROM source_assets"):
            data = make_pdf(["SYNTHETIC passage evidence about bounded scheduling and lower delay."])
            assert hashlib.sha256(data).hexdigest() == asset["sha256"]
            (settings.papers_dir / asset["storage_path"]).write_bytes(data)
        sid = detail["snapshot"]["matrix_sources"][0]["source_id"]
        assert not api.conn.execute("SELECT 1 FROM corpus_memberships WHERE source_version_id=?", (sid,)).fetchone()
        provider_file, query_file, abstract_file = "SYNTHETIC-provider.json", "SYNTHETIC-query.json", "SYNTHETIC-abstract.json"
        api.conn.execute("UPDATE source_versions SET provider_payload_path=? WHERE id=?", (provider_file, sid))
        assert api.conn.execute("SELECT raw_payload_path FROM kill_search_queries WHERE kill_search_id=? AND position=1", (detail["snapshot"]["kill_search_id"],)).fetchone()[0] == query_file
        api.store._insert_passage(sid, None, "abstract", None, None, "synthetic", abstract_file, None, "SYNTHETIC later payload text.")
        for name in (provider_file, query_file, abstract_file): (settings.payloads_dir / name).write_text('{"SYNTHETIC":"payload"}')
        before = {t: repr(rows(api.conn, t)).encode() for t in TABLES}
        assert all(rows(api.conn, t) for t in TABLES)
        backup = create_backup(settings, tmp_path / "backups")
        restored = Settings(data_dir=tmp_path / "SYNTHETIC-restored")
        restore_backup(backup, restored)
        conn = db.connect(restored.db_path)
        try:
            assert {t: repr(rows(conn, t)).encode() for t in TABLES} == before
            for asset in api.conn.execute("SELECT * FROM source_assets WHERE source_version_id=?", (sid,)):
                assert hashlib.sha256((restored.papers_dir / asset["storage_path"]).read_bytes()).hexdigest() == asset["sha256"]
            for name in (provider_file, query_file, abstract_file):
                assert (restored.payloads_dir / name).read_bytes() == (settings.payloads_dir / name).read_bytes()
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        finally: conn.close()
        api.store.trash_research(api.rid)
        api.store.purge_research(api.rid)
        assert all(not api.conn.execute(f"SELECT 1 FROM {t}").fetchone() for t in TABLES)
        assert not api.conn.execute("SELECT 1 FROM research_candidates WHERE research_id=?", (api.rid,)).fetchone()
        assert not api.conn.execute("PRAGMA foreign_key_check").fetchall()
