"""T15 (P4 part): a backup taken while the server runs restores selections, human edits, answers and referenced files.

Synthetic library built through the API with the test-only FakeAdapter; trash/corpus removal is P5.
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage.backup import BackupError, create_backup, restore_backup
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run


def test_backup_restore_preserves_removed_restored_citation_sets_and_all_report_rows(tmp_path):
    from deixis.storage import db
    from deixis.workflow.store import Store
    from deixis.workflow.report.store import ReportStore
    from tests.test_report_assembly import report_with_sections
    from tests.test_report_claim_links import edit, three_links
    from tests.test_report_edit_check import finish
    settings = Settings(data_dir=tmp_path / "claim-links-data")
    settings.data_dir.mkdir()
    fixture = report_with_sections.__wrapped__(settings.data_dir)
    lib = next(fixture)
    try:
        ids = three_links(lib)
        rid = finish(lib)
        edit(lib, link_ids=ids[:2])
        edit(lib, restore_from="model")
        edit(lib, "abstract.1", link_ids=[])
        lib["reports"].check_edits(rid, lib["report_id"])
        db.migrate(lib["store"].conn)
        tables = ("report_claim_revisions", "report_claim_revision_links", "report_citation_links", "report_claims",
                  "reports", "report_sections", "report_claim_refs", "report_gaps", "report_snapshot", "report_edit_checks", "events")
        def rows(conn):
            return {t: sorted((tuple(r) for r in conn.execute(f"SELECT * FROM {t}")), key=repr) for t in tables}
        before = rows(lib["store"].conn)
        effective = lib["reports"].effective_links(lib["report_id"])
        backup = create_backup(settings, tmp_path / "claim-links-backups")
        restored = Settings(data_dir=tmp_path / "claim-links-restored")
        restore_backup(backup, restored)
        conn = db.connect(restored.db_path)
        try:
            db.migrate(conn)
            assert rows(conn) == before
            assert ReportStore(Store(conn)).effective_links(lib["report_id"]) == effective
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


def test_backup_restore_preserves_report_edit_checks_identically_without_models(tmp_path):
    from deixis.storage import db
    from tests.test_report_assembly import report_with_sections
    from tests.test_report_edit_check import finish, check, edit
    settings = Settings(data_dir=tmp_path / "edit-check-data")
    settings.data_dir.mkdir()
    fixture = report_with_sections.__wrapped__(settings.data_dir)
    lib = next(fixture)
    try:
        finish(lib)
        check(lib)
        edit(lib, "A SYNTHETIC human revision.")
        check(lib)
        before = [tuple(row) for row in lib["store"].conn.execute("SELECT * FROM report_edit_checks ORDER BY rowid")]
        backup = create_backup(settings, tmp_path / "edit-check-backups")
        restored = Settings(data_dir=tmp_path / "edit-check-restored")
        restore_backup(backup, restored)
        conn = db.connect(restored.db_path)
        try:
            db.migrate(conn)
            assert [tuple(row) for row in conn.execute("SELECT * FROM report_edit_checks ORDER BY rowid")] == before
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


def test_backup_and_restore_keep_candidates_searches_hits_cells_overrides_and_payload_files_identical(tmp_path):
    from types import SimpleNamespace
    from deixis.storage import db
    from test_candidate_store import make_library, state, version, with_hits, publish, query, start
    settings = Settings(data_dir=tmp_path / "candidate-data")
    lib = make_library(settings.db_path)
    try:
        settings.payloads_dir.mkdir()
        for name in ("SYNTHETIC-query.json", "SYNTHETIC-failed.json"):
            (settings.payloads_dir / name).write_text("SYNTHETIC payload")
        v = version(lib)
        s, records = with_hits(lib, v, raw_payload_path="SYNTHETIC-query.json")
        publish(lib, s, records, whole=True)
        lib.candidate_store.finish_kill_search(s["id"], "completed")
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], "open", "SYNTHETIC owner reason")
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], "closed", "SYNTHETIC second reason")
        lib.candidate_store.trash_candidate(lib.rid, v["candidate_id"])
        # Failed queries retain payloads even with no source records.
        query(lib, start(lib, v), [], status="failed", raw_payload_path="SYNTHETIC-failed.json")
        before = state(lib)
        backup = create_backup(settings, tmp_path / "candidate-backups")
        restored = Settings(data_dir=tmp_path / "candidate-restored")
        restore_backup(backup, restored)
        conn = db.connect(restored.db_path)
        try:
            db.migrate(conn)
            assert state(SimpleNamespace(conn=conn)) == before
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            for name in ("SYNTHETIC-query.json", "SYNTHETIC-failed.json"):
                assert (restored.payloads_dir / name).read_text() == "SYNTHETIC payload"
        finally:
            conn.close()
    finally:
        lib.conn.close()


def test_missing_candidate_query_payload_file_makes_backup_fail(tmp_path):
    from test_candidate_store import make_library, start, query
    settings = Settings(data_dir=tmp_path / "candidate-missing-data")
    lib = make_library(settings.db_path)
    try:
        query(lib, start(lib), [], status="outcome_unknown", raw_payload_path="SYNTHETIC-missing.json")
        with pytest.raises(BackupError, match="referenced file is missing"):
            create_backup(settings, tmp_path / "candidate-missing-backups")
    finally:
        lib.conn.close()


def test_pdf_passage_character_range_is_not_a_provider_payload_file_and_backup_succeeds(tmp_path):
    import hashlib
    from deixis.storage.backup import _referenced_files
    from test_candidate_store import make_library, attach_asset
    settings = Settings(data_dir=tmp_path / "candidate-pdf-data")
    lib = make_library(settings.db_path)
    try:
        asset, _ = attach_asset(lib, lib.ids["a"])
        settings.papers_dir.mkdir()
        pdf = make_pdf(["SYNTHETIC PDF range"])
        (settings.papers_dir / "SYNTHETIC.pdf").write_bytes(pdf)
        lib.conn.execute("UPDATE source_assets SET sha256 = ?, byte_size = ? WHERE id = ?",
                         (hashlib.sha256(pdf).hexdigest(), len(pdf), asset))
        assert "chars:0-120" not in _referenced_files(lib.conn)["provider-payloads"]
        backup = create_backup(settings, tmp_path / "candidate-pdf-backups")
        assert (backup / "papers" / "SYNTHETIC.pdf").read_bytes() == pdf
    finally:
        lib.conn.close()


def test_backup_and_restore_keep_lineage_revisions_evidence_and_human_removals_identical(tmp_path):
    from deixis.storage import db
    from test_lineage_store import make_library, model, edit, remove, human, state

    settings = Settings(data_dir=tmp_path / "lineage-data")
    lib = make_library(settings.db_path)
    try:
        model(lib)
        edit(lib)
        remove(lib)
        human(lib, "c", "d")
        model(lib, "z", "d", decision={"decision": "no_relation", "relation": None, "what_changed": None,
                                       "support_type": None, "evidence": [], "note": "SYNTHETIC negative decision"})
        before = state(lib)
        backup = create_backup(settings, tmp_path / "lineage-backups")
        restored = Settings(data_dir=tmp_path / "lineage-restored")
        restore_backup(backup, restored)
        conn = db.connect(restored.db_path)
        try:
            db.migrate(conn)
            from types import SimpleNamespace
            assert state(SimpleNamespace(conn=conn)) == before
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()
    finally:
        lib.conn.close()


def build_library(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        relay = next(s for s in view["sources"] if "relay" in s["title"])
        client.patch(f"/api/researches/{rid}/selections/{relay['source_version_id']}",
                     json={"state": "excluded", "expected_version": relay["selection"]["version"], "reason": "not about scheduling"})
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded notes."]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        wait_run(client, rid, run["id"])
        backup_dir = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")  # server still running
        view = client.get(f"/api/researches/{rid}").json()
        assets = {a["id"]: client.get(f"/api/researches/{rid}/assets/{a['id']}").content
                  for s in view["sources"] for a in s["access"]["assets"]}
    return rid, view, assets, backup_dir


def test_backup_restores_selections_answers_and_files(tmp_path):
    (tmp_path / "data" / "codex-home").mkdir(parents=True)
    (tmp_path / "data" / "codex-home" / "auth.json").write_text("{\"token\": \"SYNTHETIC\"}")
    rid, before, assets, backup_dir = build_library(tmp_path)

    manifest = json.loads((backup_dir / "manifest.json").read_text())
    paths = {f["path"] for f in manifest["files"]}
    assert "library.sqlite" in paths and any(p.startswith("papers/") for p in paths) and any(p.startswith("provider-payloads/") for p in paths)
    assert not any("codex-home" in str(p) for p in backup_dir.rglob("*"))  # model sign-in data is never copied

    restored = tmp_path / "restored"
    result = restore_backup(backup_dir, Settings(data_dir=restored / "data", port=8765))
    assert result["researches"] == 1

    with TestClient(app_for(restored)) as client:
        after = client.get(f"/api/researches/{rid}").json()
        assert after == before
        relay = next(s for s in after["sources"] if "relay" in s["title"])
        assert relay["selection"]["origin"] == "user" and relay["selection"]["state"] == "excluded"
        evidence = after["answers"][0]["claims"][0]["evidence"][0]
        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}")
        assert passage.status_code == 200 and passage.json()["source"]["id"] == evidence["source_version_id"]
        assert assets and all(client.get(f"/api/researches/{rid}/assets/{aid}").content == data for aid, data in assets.items())


def test_restore_refuses_changed_backup_and_existing_library(tmp_path):
    _, _, _, backup_dir = build_library(tmp_path)

    with pytest.raises(BackupError, match="already exists"):
        restore_backup(backup_dir, Settings(data_dir=tmp_path / "data", port=8765))

    changed = tmp_path / "changed"
    shutil.copytree(backup_dir, changed)
    paper = next((changed / "papers").iterdir())
    paper.write_bytes(paper.read_bytes() + b"%")
    target = Settings(data_dir=tmp_path / "other" / "data", port=8765)
    with pytest.raises(BackupError, match="missing or changed"):
        restore_backup(changed, target)
    assert not target.db_path.exists()


def test_backup_fails_without_leaving_a_partial_folder_when_a_file_is_missing(tmp_path):
    _, _, _, backup_dir = build_library(tmp_path)
    next((tmp_path / "data" / "papers").iterdir()).unlink()
    with pytest.raises(BackupError, match="missing"):
        create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "later")
    assert not (tmp_path / "later").exists() or not any((tmp_path / "later").iterdir())
