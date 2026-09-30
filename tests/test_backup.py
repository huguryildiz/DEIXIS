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
