"""T2a/b/c/e/f behavioral red-on-old assertions; API compatibility guards."""

import hashlib

import pytest

from deixis.documents import pdf, math_reader, ocr
from deixis.workflow import equations
from tests.helpers import make_pdf
from tests.reextract.reextract_r2a_helpers import api_library, body, url, head, sharing, child_lock
from tests.reextract.reextract_r2b_helpers import tear, retained, receipt, research


@pytest.mark.parametrize("route", ["upload", "source"])
def test_t2_upload_retains_damaged_bytes_red_on_old(tmp_path, route):
    with api_library(tmp_path) as lib:
        tear(lib)
        path = f"/api/researches/{lib.rid}/" + ("uploads" if route == "upload" else f"sources/{lib.svid}/uploads")
        response = lib.client.post(path, files={"file": ("synthetic.pdf", lib.data, "application/pdf")})
        assert retained(lib), f"Old upload discarded the damaged bytes (HTTP {response.status_code})"
        assert response.status_code == 201, response.text
        view = receipt(lib)
        assert response.json()["file_restore"] == view
        capability = lib.client.get(url(lib, "text-retry"))
        assert capability.json()["can_retry_text"] and capability.json()["latest_file_restore"] == view
        retry = lib.client.post(url(lib), json=body(lib))
        assert retry.status_code == 200 and retry.json()["recovery"]["decision_code"] == "recovered_text"


def test_t2_same_hash_replace_returns_file_only_result_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        tear(lib)
        response = lib.client.put(url(lib, "").rstrip("/"), files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert response.status_code == 200, f"Old Replace PDF repairs then refuses SameFile: {response.text}"
        assert retained(lib)
        assert response.json()["file_restore"] == receipt(lib)
        assert lib.store.asset(lib.aid)["removed_at"] is None
        assert lib.conn.execute("SELECT 1 FROM events WHERE type = 'asset_replaced'").fetchone() is None


@pytest.mark.parametrize("route", ["upload", "source", "replace"])
def test_whole_duplicates_keep_policy_and_mtime_guard(tmp_path, route):
    with api_library(tmp_path) as lib:
        stamp, original = lib.path.stat().st_mtime_ns, head(lib.store, lib.aid)
        if route == "replace":
            response = lib.client.put(url(lib, "").rstrip("/"), files={"file": ("same.pdf", lib.data, "application/pdf")})
        else:
            suffix = "uploads" if route == "upload" else f"sources/{lib.svid}/uploads"
            response = lib.client.post(f"/api/researches/{lib.rid}/{suffix}", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert response.status_code == (422 if route == "replace" else 201)
        assert lib.path.stat().st_mtime_ns == stamp and head(lib.store, lib.aid) == original
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_initial_attachment_records_verified_input_and_no_receipt_guard(tmp_path):
    with api_library(tmp_path) as lib:
        data = make_pdf(["SYNTHETIC fresh initial attachment"])
        sha = hashlib.sha256(data).hexdigest()
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("new.pdf", data, "application/pdf")})
        assert response.status_code == 201
        assert (lib.settings.papers_dir / (sha + ".pdf")).read_bytes() == data
        row = lib.conn.execute("SELECT e.input_observation_id FROM asset_extractions e JOIN source_assets a ON a.id = e.asset_id"
                               " WHERE a.sha256 = ?", (sha,)).fetchone()
        assert row[0] is not None
        assert lib.conn.execute("SELECT integrity FROM asset_file_observations WHERE id = ?", (row[0],)).fetchone()[0] == "verified"
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested"])
@pytest.mark.parametrize("route", ["upload", "source", "replace"])
def test_t2_other_holding_run_refuses_before_mutation_red_on_old(tmp_path, status, route):
    with api_library(tmp_path) as lib:
        tear(lib)
        other = sharing(lib)
        run = lib.store.create_run(other, "answer", {}, None)
        lib.store.update_run(run["id"], status=status)
        if route == "replace":
            response = lib.client.put(url(lib, "").rstrip("/"), files={"file": ("same.pdf", lib.data, "application/pdf")})
        else:
            suffix = "uploads" if route == "upload" else f"sources/{lib.svid}/uploads"
            response = lib.client.post(f"/api/researches/{lib.rid}/{suffix}", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert lib.path.read_bytes() == lib.torn, f"Old writer replaced an active research's file (HTTP {response.status_code})"
        assert response.status_code == 409 and response.json()["code"] == "run_active"
        assert not list(lib.settings.papers_dir.glob("retained-*"))
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_removed_sharer_still_blocks_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        tear(lib)
        lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        destination = research(lib.store)
        response = lib.client.post(f"/api/researches/{destination}/uploads", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert lib.path.read_bytes() == lib.torn, f"Old writer ignored removed sharer (HTTP {response.status_code})"
        assert response.status_code == 409 and response.json()["code"] == "run_active"
        assert lib.store.run(run["id"])["status"] == "queued"


def test_t2_matching_never_places_files_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        tear(lib)
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads/match",
                                   files=[("files", ("same.pdf", lib.data, "application/pdf"))])
        assert lib.path.read_bytes() == lib.torn, f"Old matching placed bytes before confirmation (HTTP {response.status_code})"
        assert response.status_code == 200 and "matches" in response.json()
        fresh = make_pdf(["SYNTHETIC another matching file"])
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads/match",
                                   files=[("files", ("new.pdf", fresh, "application/pdf"))])
        assert response.status_code == 200
        assert not (lib.settings.papers_dir / (hashlib.sha256(fresh).hexdigest() + ".pdf")).exists()
        assert not list(lib.settings.papers_dir.glob("*.partial"))
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_child_lock_refuses_upload_red_on_old(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.file_restore.WRITER_LOCK_WAIT_SECONDS", 0.1)
    with api_library(tmp_path) as lib:
        tear(lib)
        with child_lock(lib):
            response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert lib.path.read_bytes() == lib.torn, "Old upload ignored another process's lock"
        assert response.status_code == 409 and response.json()["code"] == "file_busy"
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0


def test_file_only_restore_never_calls_parser_tools_models_or_http_new_contract(tmp_path, monkeypatch):
    """Paired T2a: a reused source's file repair has no extraction side effect."""
    with api_library(tmp_path) as lib:
        tear(lib)
        def forbidden(*args, **kwargs):
            raise AssertionError("File repair called an extraction, tool or model")
        for module, name in ((pdf, "extract_pdf"), (ocr, "read_page"), (math_reader.MathReader, "read"),
                             (equations.EquationService, "read_asset")):
            monkeypatch.setattr(module, name, forbidden)
        class Adapter:
            async def run_step(self, *args, **kwargs): forbidden()
            async def health(self, *args, **kwargs): forbidden()
            async def close(self): pass
        lib.app.state.adapters["fake"] = Adapter()
        response = lib.client.post(f"/api/researches/{lib.rid}/uploads", files={"file": ("same.pdf", lib.data, "application/pdf")})
        assert response.status_code == 201, response.text
        receipt(lib)
        assert lib.client.get(f"/api/researches/{lib.rid}").status_code == 200
