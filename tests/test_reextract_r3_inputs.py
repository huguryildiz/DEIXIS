"""S6/S7 private parser inputs across every attachment and ordinary upgrade."""

import asyncio
import hashlib
import shutil
import threading
from dataclasses import replace

import pytest

from deixis.documents import acquisition, pdf
from deixis.storage import db
from deixis.workflow.store import Store
from tests.helpers import make_pdf
from tests.reextract_r2a_helpers import api_library, child_lock, head, store_library, url
from tests.reextract_r2b_helpers import source
from tests.test_reextract_r2b_writers import call_writer, configure
from tests.reextract_r3_helpers import no_external_calls
from tests.review_helpers import all_rows


WRITERS = ["upload_new", "upload_existing", "waiting", "zotero_import", "zotero_pdfs", "acquisition", "confirmed", "run_fetch", "replace"]


def initial(lib, monkeypatch, writer, svid, record):
    base = f"/api/researches/{lib.rid}"
    if writer in ("upload_new", "upload_existing"):
        route = base + ("/uploads" if writer == "upload_new" else f"/sources/{svid}/uploads")
        return lib.client.post(route, files={"file": ("initial.pdf", lib.data, "application/pdf")})
    if writer == "replace":
        return lib.client.put(url(lib).removesuffix("/extractions"), files={"file": ("initial.pdf", lib.data, "application/pdf")})
    if writer == "acquisition":
        return asyncio.run(acquisition._attach_pdf(lib.store, svid, lib.data, lib.settings.papers_dir,
            "download", "https://example.org/synthetic.pdf", research_id=lib.rid, recovery_dir=lib.settings.recovery_dir))
    if writer == "run_fetch":
        configure(lib, monkeypatch)
        run = lib.store.create_run(lib.rid, "pdf_collection", {}, None)
        lib.store.update_run(run["id"], status="running")
        asyncio.run(lib.app.state.worker.flow._fetch_pdf(lib.store.run(run["id"]), lib.store.source(svid)))
        return dict(lib.conn.execute("SELECT * FROM run_steps WHERE run_id = ?", (run["id"],)).fetchone())
    return call_writer(lib, monkeypatch, writer, lib.rid, svid, record)


def new_input(lib):
    lib.data = make_pdf(["SYNTHETIC new initial relays input"])
    lib.sha = hashlib.sha256(lib.data).hexdigest()
    lib.path = lib.settings.papers_dir / (lib.sha + ".pdf")


def input_row(lib):
    return lib.conn.execute("SELECT e.*, a.sha256, a.byte_size FROM asset_extractions e JOIN source_assets a ON a.id = e.asset_id"
                            " WHERE a.sha256 = ? AND e.outcome = 'current'", (lib.sha,)).fetchone()


@pytest.mark.parametrize("writer", WRITERS)
def test_s6_initial_verified_input_red_on_old(tmp_path, monkeypatch, writer):
    with api_library(tmp_path, raise_errors=True) as lib:
        new_input(lib)
        svid, record = source(lib)
        calls, real = [], pdf.extract_pdf
        def parse(path):
            calls.append(path)
            return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        result = initial(lib, monkeypatch, writer, svid, record)
        row = input_row(lib)
        assert row is not None and row["input_observation_id"] is not None, str(result)
        obs = dict(lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (row["input_observation_id"],)).fetchone())
        assert (obs["kind"], obs["operation_id"], obs["integrity"], obs["observed_sha256"], obs["observed_byte_size"]) == (
            "extraction_input", None, "verified", row["sha256"], row["byte_size"])
        assert len(calls) == 1 and calls[0].parent == lib.settings.recovery_dir / "tmp"
        assert calls[0] != lib.path and not calls[0].exists()
        assert not list((lib.settings.recovery_dir / "tmp").glob("*.pdf"))
        assert not lib.conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("damage", ["same_size", "missing"])
def test_s6_changed_initial_input_new_contract(tmp_path, monkeypatch, writer, damage):
    """Paired with S6; outside edits after placement must never reach the parser."""
    from deixis.workflow import text_retry
    with api_library(tmp_path, raise_errors=True) as lib:
        new_input(lib)
        svid, record = source(lib)
        real = text_retry.observe_copy
        def observe(papers, name, sha, size, private):
            path = papers / name
            if damage == "missing":
                path.unlink()
            else:
                path.write_bytes(b"x" * size)
            return real(papers, name, sha, size, private)
        monkeypatch.setattr(text_retry, "observe_copy", observe)
        def forbidden(*args, **kwargs):
            raise AssertionError("Unverified initial input reached parser")
        monkeypatch.setattr(pdf, "extract_pdf", forbidden)
        result = initial(lib, monkeypatch, writer, svid, record)
        row = input_row(lib)
        assert row["status"] == "failed" and row["page_count"] == 0 and row["error"] == text_retry.INPUT_CHANGED
        obs = lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (row["input_observation_id"],)).fetchone()
        assert obs["integrity"] == ("missing" if damage == "missing" else "mismatch")
        if writer.startswith("zotero"):
            field = "zotero_import" if writer == "zotero_import" else "zotero_pdfs"
            assert result.json()[field]["notes"][0]["note"].startswith("PDF input not verified:")
        assert not list((lib.settings.recovery_dir / "tmp").glob("*.pdf"))


@pytest.mark.parametrize("writer", WRITERS)
def test_s6_busy_verified_initial_read_new_contract(tmp_path, monkeypatch, writer):
    """Paired with S6: whole-file placement fast path, then a busy verified read."""
    from deixis.workflow import text_retry
    monkeypatch.setattr("deixis.workflow.file_restore.WRITER_LOCK_WAIT_SECONDS", 0.03)
    with api_library(tmp_path, raise_errors=True) as lib:
        new_input(lib)
        lib.path.write_bytes(lib.data)
        svid, record = source(lib)
        with child_lock(lib):
            if writer == "acquisition":
                with pytest.raises(text_retry.FileBusy):
                    initial(lib, monkeypatch, writer, svid, record)
            else:
                result = initial(lib, monkeypatch, writer, svid, record)
                if writer.startswith("zotero"):
                    field = "zotero_import" if writer == "zotero_import" else "zotero_pdfs"
                    assert result.json()[field]["notes"][0]["note"].startswith("PDF not added:")
                elif writer == "run_fetch":
                    assert result["status"] == "failed" and result["error_code"] == "fetch_file_busy"
                else:
                    assert result.status_code == 409 and result.json()["code"] == "file_busy"
            assert input_row(lib) is None
        assert lib.path.read_bytes() == lib.data


@pytest.mark.parametrize("legacy", ["nonhex", "pre0066"])
def test_s6_legacy_reads_and_occurrence_nulls_new_contract(tmp_path, monkeypatch, legacy):
    """Paired with S6 and S4's unchanged dependency oracle; private-read legacy branches."""
    from deixis.workflow import text_retry
    from deixis.workflow.views import passage_view
    with store_library(tmp_path, "partial") as lib:
        if legacy == "pre0066":
            lib.conn.close()
            # A separate historical synthetic library, not a downgrade of stored rows.
            migrations = tmp_path / "migrations"
            migrations.mkdir()
            for path in db.MIGRATIONS_DIR.glob("*.sql"):
                if int(path.name.split("_")[0]) <= 65:
                    shutil.copyfile(path, migrations / path.name)
            monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
            conn = db.connect(tmp_path / "historical.sqlite")
            db.migrate(conn)
            lib.conn = conn
            lib.store = Store(conn)
        sha = "sha-synthetic" if legacy == "nonhex" else lib.sha
        calls = []
        extraction = pdf.Extraction("partial", 1, [pdf.PageText(1, None, "SYNTHETIC historical text")])
        def parse(path):
            calls.append(path)
            return extraction
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        read = asyncio.run(text_retry.read_verified(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
            storage_path=lib.path.name, sha256=sha, byte_size=len(lib.data), lock=True))
        assert read.observation is None and calls == [lib.path]
        if legacy == "pre0066":
            rid = lib.store.create_research("SYNTHETIC historical", "attached", "quick", [], "fake", "fake", None)
            svid = lib.store.create_upload_source("SYNTHETIC historical")
            lib.store.add_to_corpus(rid, svid, "user_upload")
            aid = lib.store.add_asset_with_pages(svid, sha, len(lib.data), lib.path.name, "user_upload", None, None,
                read.extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
            value = passage_view(lib.store, rid, lib.store.passages_for(svid)[0]["id"])["occurrence"]
            assert value["extractor_profile"] is None and value["input"] is None and value["latest_file_restore"] is None
            assert value["input_relation"] == "input_not_recorded" and not value["file_restored_after"]
            conn.close()


def test_s7_torn_upgrade_red_on_old(tmp_path, monkeypatch):
    with api_library(tmp_path, "partial", version="legacy-profile", raise_errors=True) as lib:
        lib.path.write_bytes(b"x" * len(lib.data))
        before = all_rows(lib.conn)
        calls = []
        real = pdf.extract_pdf
        def parse(path):
            calls.append(path)
            return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        refused = lib.client.post(url(lib))
        assert refused.status_code == 409 and refused.json()["code"] == "input_not_verified"
        assert not calls and all_rows(lib.conn) == before
        lib.path.write_bytes(lib.data)
        response = lib.client.post(url(lib))
        assert response.status_code == 200
        observation = head(lib.store, lib.aid)["input_observation_id"]
        assert observation and lib.conn.execute("SELECT integrity FROM asset_file_observations WHERE id = ?", (observation,)).fetchone()[0] == "verified"
        assert len(calls) == 1 and calls[0].parent == lib.settings.recovery_dir / "tmp" and not calls[0].exists()


def test_s7_cli_upgrade_continues_and_dry_run_new_contract(tmp_path, monkeypatch, capsys):
    """Paired with S7; CLI outcome and observation writes follow the same verified read."""
    from deixis.__main__ import reextract
    from tests.reextract_r2a_helpers import seed
    with api_library(tmp_path, "partial", version="legacy-profile", raise_errors=True) as lib:
        other = seed(lib.store, lib.settings, "partial", version="legacy-profile", data=make_pdf(["SYNTHETIC whole second input"]))
        before = all_rows(lib.conn)
        assert reextract(lib.settings, True) == 0
        assert all_rows(lib.conn) == before
        capsys.readouterr()
        lib.path.write_bytes(b"x" * len(lib.data))
        assert reextract(lib.settings, False) == 0
        output = capsys.readouterr().out
        assert "input_not_verified" in output and other.aid in output
        assert head(lib.store, lib.aid)["input_observation_id"] is None
        assert head(lib.store, other.aid)["input_observation_id"] is not None


@pytest.mark.parametrize("writer", ["zotero_import", "zotero_pdfs"])
def test_s6_two_item_zotero_keeps_failed_asset_and_continues_new_contract(tmp_path, monkeypatch, writer):
    """Paired with S6: O1 is a recorded failed attachment, not an aborted import."""
    from deixis.providers import zotero
    from deixis.workflow import text_retry
    with api_library(tmp_path, raise_errors=True) as lib:
        new_input(lib)
        first_svid, record = source(lib)
        second_record = replace(record, provider_record_id="R3-second", doi="10.1/r3-second", title="SYNTHETIC second import item")
        second_svid, _ = lib.store.upsert_provider_source("openalex", second_record, None)
        lib.store.add_to_corpus(lib.rid, second_svid, "search", selection_state="included", selection_origin="user")
        second_data = make_pdf(["SYNTHETIC verified second import input"])
        items = [zotero.ZoteroItem(record, "PDFA1234", "first.pdf"), zotero.ZoteroItem(second_record, "PDFB1234", "second.pdf")]
        async def collection(*args):
            return items, []
        async def find(http, library, doi, title):
            return items[0] if doi == record.doi else items[1]
        async def data(http, library, key, fetcher):
            return lib.data if key == items[0].pdf_key else second_data
        monkeypatch.setattr(zotero, "collection_items", collection)
        monkeypatch.setattr(zotero, "find_pdf", find)
        monkeypatch.setattr(zotero, "pdf_bytes", data)
        original_observe = text_retry.observe_copy
        original_parse = pdf.extract_pdf
        calls = []
        def observe(papers, name, sha, size, private):
            if sha == lib.sha:
                (papers / name).write_bytes(b"x" * size)
            return original_observe(papers, name, sha, size, private)
        def parse(path):
            calls.append(path)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(second_data).hexdigest()
            return original_parse(path)
        monkeypatch.setattr(text_retry, "observe_copy", observe)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        route = f"/api/researches/{lib.rid}/" + ("zotero-imports" if writer == "zotero_import" else "zotero-pdfs")
        response = lib.client.post(route, json={"source": "local", **({"collection_key": "SYN12345"} if writer == "zotero_import" else {})})
        assert response.status_code in (200, 201), response.text
        field = "zotero_import" if writer == "zotero_import" else "zotero_pdfs"
        assert response.json()[field]["pdfs_added" if writer == "zotero_import" else "added"] == 2
        assert response.json()[field]["notes"][0]["note"].startswith("PDF input not verified:")
        rows = {r["sha256"]: dict(r) for r in lib.conn.execute("SELECT a.sha256, e.status, o.integrity FROM source_assets a"
            " JOIN asset_extractions e ON e.asset_id = a.id JOIN asset_file_observations o ON o.id = e.input_observation_id")}
        assert rows[lib.sha]["status"] == "failed" and rows[lib.sha]["integrity"] == "mismatch"
        assert rows[hashlib.sha256(second_data).hexdigest()]["integrity"] == "verified"
        assert len(calls) == 1 and not calls[0].exists()


def test_s6_cancelled_parser_drains_before_unlock_new_contract(tmp_path, monkeypatch):
    """Paired with S6: cancelling a read cannot unlock bytes still used by its parser."""
    from deixis.workflow import text_retry
    with api_library(tmp_path, raise_errors=True) as lib:
        entered, release = threading.Event(), threading.Event()
        real = pdf.extract_pdf
        def parse(path):
            entered.set()
            assert release.wait(5)
            return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        before = all_rows(lib.conn)
        async def cancel():
            task = asyncio.create_task(text_retry.read_verified(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                storage_path=lib.path.name, sha256=lib.sha, byte_size=len(lib.data), lock=True))
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0.03)
            assert not task.done() and text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        try:
            asyncio.run(cancel())
        finally:
            release.set()
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
        assert not list((lib.settings.recovery_dir / "tmp").glob("*.pdf"))
        assert all_rows(lib.conn) == before


@pytest.mark.parametrize("parser_error", [False, True])
def test_s6_cleanup_failure_preserves_result_or_error_new_contract(tmp_path, monkeypatch, caplog, parser_error):
    """Paired with S6: private-copy cleanup logs a failure without replacing the parser result."""
    from pathlib import Path
    from deixis.workflow import text_retry
    with api_library(tmp_path, raise_errors=True) as lib:
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.parent == lib.settings.recovery_dir / "tmp":
                raise OSError("SYNTHETIC private cleanup failure")
            return original(path, *args, **kwargs)
        if parser_error:
            def parse(path):
                raise RuntimeError("SYNTHETIC parser failure")
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        monkeypatch.setattr(Path, "unlink", unlink)
        def read():
            return asyncio.run(text_retry.read_verified(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                storage_path=lib.path.name, sha256=lib.sha, byte_size=len(lib.data), lock=True))
        if parser_error:
            with pytest.raises(RuntimeError, match="SYNTHETIC parser failure"):
                read()
        else:
            assert read().observation["integrity"] == "verified"
        assert "Could not remove a verified extraction input copy" in caplog.text
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)
