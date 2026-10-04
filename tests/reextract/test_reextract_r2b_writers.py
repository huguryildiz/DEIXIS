"""T2d/g red-on-old writer coverage and refusal guards, all fetches/lookups synthetic."""

import asyncio
import json

import pytest

from deixis.documents import acquisition, pdf
from deixis.documents.fetch import FetchResult
from deixis.providers import zotero
from deixis.workflow import waiting
from tests.reextract.reextract_r2a_helpers import api_library, head, child_lock
from tests.reextract.reextract_r2b_helpers import tear, retained, receipt, research, source


def candidate(provider="openalex", status="match"):
    return acquisition.Candidate(provider, "https://example.org/r2b.pdf" if provider != "europepmc" else
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML", None,
        "publishedVersion", None, "doi_verified", status)


def lookups(monkeypatch, chosen):
    async def empty(*args, **kwargs): return acquisition.Lookup("zero_results", [])
    async def found(*args, **kwargs): return acquisition.Lookup("completed", [chosen])
    for name in ("unpaywall_lookup", "openalex_lookup", "crossref_lookup", "core_lookup", "europepmc_lookup", "web_lookup"):
        monkeypatch.setattr(acquisition, name, empty)
    monkeypatch.setattr(acquisition, "europepmc_lookup" if chosen.provider == "europepmc" else "openalex_lookup", found)


def configure(lib, monkeypatch):
    async def fetcher(url): return FetchResult("ok", data=lib.data, final_url=url, http_status=200)
    async def render(*args): return lib.data
    monkeypatch.setattr(acquisition, "_render_candidate", render)
    lib.app.state.fetch_pdf = fetcher
    lib.app.state.worker.flow.deps.fetch_pdf = fetcher
    return fetcher


def call_writer(lib, monkeypatch, writer, destination, svid, record):
    fetcher = configure(lib, monkeypatch)
    prefix = f"/api/researches/{destination}"
    if writer == "waiting":
        work_id = lib.store.source(svid)["work_id"]
        fields = {"work_id": work_id, "source_version_id": svid, "scope_revision": 1, "sha256": lib.sha,
                  "versions_digest": waiting._digest(work_id, waiting._versions(lib.store, destination, svid))}
        return lib.client.post(prefix + "/waiting/uploads", data=fields,
                               files={"file": ("same.pdf", lib.data, "application/pdf")})
    if writer.startswith("zotero"):
        item = zotero.ZoteroItem(record, "PDFA1234", "synthetic.pdf")
        async def items(*args): return [item], []
        async def find(*args): return item
        async def data(*args): return lib.data
        monkeypatch.setattr(zotero, "collection_items", items)
        monkeypatch.setattr(zotero, "find_pdf", find)
        monkeypatch.setattr(zotero, "pdf_bytes", data)
        suffix = "/zotero-imports" if writer == "zotero_import" else "/zotero-pdfs"
        return lib.client.post(prefix + suffix, json={"source": "local", **({"collection_key": "SYN12345"} if writer == "zotero_import" else {})})
    selected = candidate("europepmc" if "rendition" in writer else "openalex",
                         "different" if writer.startswith("other_") else "match")
    lookups(monkeypatch, selected)
    if writer == "discovery" or writer == "rendition":
        return lib.client.post(prefix + f"/sources/{svid}/pdf-discovery")
    if writer == "confirmed":
        selected = candidate(status="uncertain")
    run_id = lib.store.record_pdf_discovery(destination, svid, selected.provider, "SYNTHETIC", acquisition.Lookup("completed", [selected]))
    lib.store.record_pdf_candidates(svid, run_id, [selected])
    if writer == "confirmed":
        cid = lib.store.pdf_candidates(svid)[0]["id"]
        return lib.client.post(prefix + f"/sources/{svid}/pdf-candidates/{cid}/attach")
    if writer.startswith("other_"):
        return asyncio.run(acquisition._attach_other_version(lib.store, destination, svid, lib.settings.papers_dir, fetcher))
    run = lib.store.create_run(destination, "pdf_collection", {}, None)
    lib.store.update_run(run["id"], status="running")
    return asyncio.run(lib.app.state.worker.flow._find_other_copy(lib.store.run(run["id"]), lib.store.source(svid)))


WRITERS = ["waiting", "zotero_import", "zotero_pdfs", "discovery", "rendition", "other_pdf", "other_rendition", "confirmed", "find_other_copy"]


@pytest.mark.parametrize("writer", WRITERS)
def test_t2_every_attachment_retains_shared_damage_red_on_old(tmp_path, monkeypatch, writer):
    with api_library(tmp_path) as lib:
        tear(lib)
        destination = research(lib.store)
        svid, record = source(lib, destination)
        result = call_writer(lib, monkeypatch, writer, destination, svid, record)
        assert retained(lib), f"Old {writer} overwrote shared damaged bytes: {result}"
        if hasattr(result, "status_code"):
            assert result.status_code in (200, 201), result.text
        receipt(lib)
        assert lib.store.latest_file_restore(lib.sha)["outcome"] == "file_restored"
        observation_id = lib.conn.execute("SELECT input_observation_id FROM asset_extractions WHERE asset_id <> ?", (lib.aid,)).fetchone()[0]
        assert observation_id is not None
        assert lib.conn.execute("SELECT integrity FROM asset_file_observations WHERE id = ?", (observation_id,)).fetchone()[0] == "verified"


@pytest.mark.parametrize("writer", WRITERS)
def test_t2_every_attachment_refuses_shared_active_run_red_on_old(tmp_path, monkeypatch, writer):
    with api_library(tmp_path) as lib:
        tear(lib)
        destination = research(lib.store)
        svid, record = source(lib, destination)
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        if writer == "find_other_copy":
            lib.store.add_to_corpus(destination, lib.svid, "user_upload")
        # Direct other-version calls expose the driver's refusal; defer importing the new exception until after
        # the old-compatible no-mutation assertion, so clean-old execution reaches that assertion.
        error = None
        try:
            result = call_writer(lib, monkeypatch, writer, destination, svid, record)
        except Exception as exc:
            error = exc
        assert lib.path.read_bytes() == lib.torn, f"Old {writer} ignored active shared run"
        if writer.startswith("zotero"):
            assert result.status_code in (200, 201)
            field = "zotero_import" if writer == "zotero_import" else "zotero_pdfs"
            assert result.json()[field]["notes"][0]["note"].startswith("PDF not added: ")
        elif writer.startswith("other_"):
            assert error.code == "run_active"
        elif writer == "find_other_copy":
            step = lib.conn.execute("SELECT * FROM run_steps WHERE kind = 'pdf_other_copy'").fetchone()
            assert step["status"] == "failed" and step["error_code"] == "fetch_file_repair_refused"
            assert json.loads(step["error_json"])["code"] == "run_active"
            assert result["asset_id"] is None and not result["pdf_found"]
        else:
            assert result.status_code == 409 and result.json()["code"] == "run_active"
        assert lib.store.run(run["id"])["status"] == "queued"
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0
        assert not list(lib.settings.papers_dir.glob("retained-*"))


@pytest.mark.parametrize("holding", [True, False])
def test_t2_runtime_fetch_own_run_refuses_idle_sharer_restores_red_on_old(tmp_path, monkeypatch, holding):
    with api_library(tmp_path) as lib:
        tear(lib)
        destination = lib.rid if holding else research(lib.store)
        svid, _ = source(lib, destination)
        configure(lib, monkeypatch)
        calls, real = [], pdf.extract_pdf
        def parse(*args):
            calls.append(args)
            return real(*args)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        run = lib.store.create_run(destination, "pdf_collection", {"max_downloads": 20}, None)
        lib.store.update_run(run["id"], status="running")
        asyncio.run(lib.app.state.worker.flow.execute(run["id"]))
        if holding:
            assert lib.path.read_bytes() == lib.torn, "Old run-time fetch overwrote the file its own run holds"
        else:
            assert retained(lib), "Old run-time fetch discarded the idle sharer's damaged bytes"
        assert lib.store.run(run["id"])["status"] == "completed"
        step = lib.conn.execute("SELECT * FROM run_steps WHERE kind = 'fetch_pdf' AND operation_key = ?", (f"fetch:{svid}",)).fetchone()
        if holding:
            assert step["status"] == "failed" and step["error_code"] == "fetch_file_repair_refused"
            assert json.loads(step["error_json"])["code"] == "run_active"
            assert not lib.store.has_asset(svid) and not calls
            assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0
            assert lib.store.pdf_link_refusal(svid, lib.store.source(svid)["oa_pdf_url"]) is None
        else:
            assert step["status"] == "succeeded" and lib.store.has_asset(svid) and len(calls) == 1
            receipt(lib)


@pytest.mark.parametrize("writer", ["run_fetch", "zotero_import", "zotero_pdfs", "find_other_copy"])
def test_child_lock_refuses_fetch_or_zotero_red_on_old(tmp_path, monkeypatch, writer):
    monkeypatch.setattr("deixis.workflow.file_restore.WRITER_LOCK_WAIT_SECONDS", 0.1)
    with api_library(tmp_path) as lib:
        tear(lib)
        destination = research(lib.store)
        svid, record = source(lib, destination)
        configure(lib, monkeypatch)
        with child_lock(lib):
            if writer == "run_fetch":
                run = lib.store.create_run(destination, "pdf_collection", {}, None)
                lib.store.update_run(run["id"], status="running")
                asyncio.run(lib.app.state.worker.flow.execute(run["id"]))
            else:
                result = call_writer(lib, monkeypatch, writer, destination, svid, record)
        assert lib.path.read_bytes() == lib.torn, f"Old {writer} ignored another process's lock"
        if writer.startswith("zotero"):
            field = "zotero_import" if writer == "zotero_import" else "zotero_pdfs"
            assert result.json()[field]["notes"][0]["note"].startswith("PDF not added: ")
        else:
            step = lib.conn.execute("SELECT * FROM run_steps WHERE kind = ?", ("fetch_pdf" if writer == "run_fetch" else "pdf_other_copy",)).fetchone()
            assert step["error_code"] == "fetch_file_busy" and step["status"] == "failed"
        assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations").fetchone()[0] == 0
