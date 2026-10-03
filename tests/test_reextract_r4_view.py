"""R4 read projections; HTTP assertions precede any import of the new module."""

import shutil

import pytest

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow import text_retry
from deixis.workflow.store import Store
from tests.reextract_r2a_helpers import PUBLIC_RETRY_FIELDS, api_library, body, counts, head, seed, url


def projected(lib):
    response = lib.client.get(f"/api/researches/{lib.rid}")
    assert response.status_code == 200
    asset = next(s for s in response.json()["sources"] if s["source_version_id"] == lib.svid)["access"]["assets"][0]
    assert "text_recovery" in asset  # V1 red on 03422d7: public behavior, not a missing import.
    assert "sha256" not in asset and "storage_path" not in asset
    return asset["text_recovery"]


def test_pre_0066_research_view_loads_with_null_recovery_for_every_asset(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations-0065"
    migrations.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) < 66:
            shutil.copy(path, migrations / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)

    def forbidden(*args, **kwargs):
        raise AssertionError("A historical research view called the recovery projection")

    monkeypatch.setattr("deixis.workflow.recovery_view.text_recovery", forbidden)
    with api_library(tmp_path, raise_errors=True) as lib:
        assert not lib.store._extraction_has_recovery_metadata
        assert lib.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 65
        assert lib.conn.execute("SELECT name FROM sqlite_master WHERE name IN"
                                " ('asset_recovery_operations', 'asset_file_observations')").fetchall() == []
        other = seed(lib.store, lib.settings, status="partial", version="synthetic-older-profile")
        lib.store.add_to_corpus(lib.rid, other.svid, "user_upload")
        response = lib.client.get(f"/api/researches/{lib.rid}")
        assert response.status_code == 200
        assets = [asset for source in response.json()["sources"] for asset in source["access"]["assets"]]
        assert {asset["id"] for asset in assets} == {lib.aid, other.aid}
        assert all("text_recovery" in asset and asset["text_recovery"] is None for asset in assets)
        assert next(asset for asset in assets if asset["id"] == other.aid)["current_extraction"] is False


@pytest.mark.parametrize("status,reason,checked", [
    ("failed", None, True), ("partial", None, True), ("no_text", None, True),
    ("succeeded", "already_current", False), ("pending", "pending", False),
])
def test_v1_source_capability_matches_get_without_file_io_red_on_old(tmp_path, status, reason, checked):
    with api_library(tmp_path, status) as lib:
        before = counts(lib.store), lib.conn.total_changes
        view = projected(lib)
        capability = lib.client.get(url(lib, "text-retry")).json()
        assert view == capability | {"file_checked": False}
        assert capability["reason"] == reason and capability["file_checked"] is checked
        assert capability["can_retry_text"] == (reason is None)
        assert (counts(lib.store), lib.conn.total_changes) == before


def test_v1_running_and_active_run_blockers_are_db_only(tmp_path):
    with api_library(tmp_path) as lib:
        operation = lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid,
            idempotency_key="r4_running", request_fingerprint="synthetic", research_id=lib.rid)
        assert projected(lib)["reason"] == "operation_running"
        assert lib.client.get(url(lib, "text-retry")).json()["file_checked"] is False
        lib.store.interrupt_text_retry(operation["operation_id"], "process_ended")
        lib.store.create_run(lib.rid, "answer", {}, "r4_active_run")
        assert projected(lib)["reason"] == "run_active"
        capability = lib.client.get(url(lib, "text-retry")).json()
        assert capability["reason"] == "run_active" and capability["file_checked"] is False


def test_v1_missing_file_and_no_current_head(tmp_path):
    with api_library(tmp_path) as lib:
        lib.path.unlink()
        assert projected(lib)["can_retry_text"] is True
        capability = lib.client.get(url(lib, "text-retry")).json()
        assert capability["reason"] == "file_missing" and capability["file_checked"] is True
        lib.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ?", (lib.aid,))
        assert projected(lib)["reason"] == "no_current_extraction"
        capability = lib.client.get(url(lib, "text-retry")).json()
        assert capability["reason"] == "no_current_extraction" and capability["file_checked"] is False


def test_summary_and_history_never_flush_or_precheck(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        def forbidden(*args, **kwargs):
            raise AssertionError("A read projection tried to flush or inspect a file")
        monkeypatch.setattr(Store, "flush_text_retry_interruptions", forbidden)
        monkeypatch.setattr(text_retry, "precheck", forbidden)
        before = counts(lib.store), lib.conn.total_changes
        assert projected(lib)["file_checked"] is False
        assert lib.client.get(url(lib, "recovery-history")).status_code == 200
        assert (counts(lib.store), lib.conn.total_changes) == before


def test_capability_reads_current_head_without_loading_passage_manifest(tmp_path, monkeypatch):
    with api_library(tmp_path, "partial") as lib:
        def forbidden(*args, **kwargs):
            raise AssertionError("A capability projection loaded the retry baseline's passage manifest")
        monkeypatch.setattr(Store, "_retry_baseline", forbidden)
        before = counts(lib.store), lib.conn.total_changes
        summary = projected(lib)
        response = lib.client.get(url(lib, "text-retry"))
        assert response.status_code == 200
        assert summary == response.json() | {"file_checked": False}
        assert summary["current_extraction_id"] == lib.eid
        assert summary["can_retry_text"] is True
        assert (counts(lib.store), lib.conn.total_changes) == before


def test_v2_password_hidden_in_capability_but_post_still_accepts_guard(tmp_path):
    with api_library(tmp_path) as lib:
        svid = lib.store.create_upload_source("SYNTHETIC known password diagnosis")
        lib.store.add_to_corpus(lib.rid, svid, "user_upload")
        aid = lib.store.add_asset_with_pages(svid, lib.sha, len(lib.data), lib.path.name, "user_upload", None,
            "synthetic.pdf", pdf.Extraction(status="failed", error=pdf.ERROR_PASSWORD), pdf.EXTRACTION_VERSION, pdf.chunk_page)
        route = f"/api/researches/{lib.rid}/sources/{svid}/assets/{aid}"
        capability = lib.client.get(route + "/text-retry").json()
        assert capability["reason"] == "password_protected"  # V2 red on old: old GET offers it.
        assert not capability["can_retry_text"] and not capability["file_checked"]
        view = lib.client.get(f"/api/researches/{lib.rid}").json()
        assert next(s for s in view["sources"] if s["source_version_id"] == svid)["access"]["assets"][0]["text_recovery"] == capability
        response = lib.client.post(route + "/extractions", json=body(lib, "r4_password_post", head(lib.store, aid)["id"]))
        assert response.status_code == 200
        assert response.json()["recovery"]["outcome"] == "promoted"  # Same write path parses these whole, unlocked fixture bytes.


def test_v3_history_is_closed_bounded_ordered_and_read_only_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        for i in range(21):
            op = lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid,
                idempotency_key=f"r4_history_{i:02}", request_fingerprint=f"synthetic-{i}", research_id=lib.rid)
            if i == 0:
                lib.store.interrupt_text_retry(op["operation_id"], "process_ended")
            else:
                obs = lib.store.record_text_retry_input(op["operation_id"], storage_path=lib.path.name,
                    expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
                    observed_byte_size=len(lib.data), integrity="verified")
                lib.store.complete_text_retry(op["operation_id"], pdf.Extraction(status="failed", error=pdf.ERROR_UNREADABLE),
                                              pdf.chunk_page, input_observation_id=obs)
            restore = lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
            lib.store.complete_file_restore(restore["id"], "file_reused")
        before = counts(lib.store), lib.conn.total_changes
        response = lib.client.get(url(lib, "recovery-history"))
        assert response.status_code == 200  # V3 red on old: 404.
        history = response.json()
        assert set(history) == {"text_retries", "file_restores", "text_retries_truncated", "file_restores_truncated"}
        assert history["text_retries_truncated"] is history["file_restores_truncated"] is True
        assert len(history["text_retries"]) == len(history["file_restores"]) == 20
        candidate_fields = {"extraction_id", "extraction_version", "extractor_profile", "status", "error", "page_count", "outcome", "decision_code", "diagnostic_only"}
        retry_ids = [r[0] for r in lib.conn.execute("SELECT id FROM asset_recovery_operations WHERE kind='text_retry' ORDER BY created_at DESC, id DESC LIMIT 20")]
        restore_ids = [r[0] for r in lib.conn.execute("SELECT id FROM asset_recovery_operations WHERE kind='file_restore' ORDER BY created_at DESC, id DESC LIMIT 20")]
        assert [item["operation"]["operation_id"] for item in history["text_retries"]] == retry_ids
        assert [item["operation_id"] for item in history["file_restores"]] == restore_ids
        for item in history["text_retries"]:
            assert set(item) == {"operation", "candidate"}
            assert set(item["operation"]) == PUBLIC_RETRY_FIELDS
            assert item["operation"] == lib.store.text_retry_view(item["operation"]["operation_id"])
            if item["candidate"] is not None:
                assert set(item["candidate"]) == candidate_fields
        for item in history["file_restores"]:
            assert item == lib.store.file_restore_view(item["operation_id"])
        assert (counts(lib.store), lib.conn.total_changes) == before


def test_v3_null_candidate_shared_hash_and_access_guards(tmp_path):
    with api_library(tmp_path) as lib:
        op = lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key="r4_null_candidate",
                                         request_fingerprint="synthetic", research_id=lib.rid)
        lib.store.interrupt_text_retry(op["operation_id"], "process_ended")
        response = lib.client.get(url(lib, "recovery-history"))
        assert response.status_code == 200
        assert response.json()["text_retries"][0]["candidate"] is None
        assert not response.json()["text_retries_truncated"]
        foreign = lib.store.create_research("SYNTHETIC foreign", "attached", "quick", [], "fake", "fake", None)
        assert lib.client.get(url(lib, "recovery-history").replace(lib.rid, foreign)).status_code == 404
        other = seed(lib.store, lib.settings)
        assert lib.client.get(url(lib, "recovery-history").replace(lib.svid, other.svid)).status_code == 404
        restore = lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        lib.store.complete_file_restore(restore["id"], "file_reused")
        assert lib.client.get(url(other, "recovery-history")).json()["file_restores"][0]["operation_id"] == restore["id"]
        lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        assert lib.client.get(url(lib, "recovery-history")).status_code == 404


def test_v6_busy_equation_step_output_is_public_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        run = lib.store.create_run(lib.rid, "answer", {}, "r4_equations")
        step = lib.store.step(run["id"], "equations:synthetic", "read_equations")
        output = {"asset_id": lib.aid, "outcome": "file_busy", "state": "pending", "pages": []}
        lib.store.finish_step(step["id"], "succeeded", output=output)
        view = lib.client.get(f"/api/researches/{lib.rid}").json()
        rendered = next(r for r in view["runs"] if r["id"] == run["id"])
        assert next(s for s in rendered["steps"] if s["id"] == step["id"])["output"] == output
