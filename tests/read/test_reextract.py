"""Re-extraction through the API and CLI (R2-R4): a person asks DEIXIS to read a stored PDF again; the new text is promoted or rejected, old passages and citations stay resolvable, no table row or person's cell is overwritten, and a crashed attempt is reconciled at start and never retried by itself. SYNTHETIC PDFs; no parser tool, provider or model is called."""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from deixis import __main__ as cli
from deixis.config import Settings
from deixis.documents import pdf, acquisition, ocr
from deixis.documents.fetch import FetchResult
from deixis.providers import zotero
from deixis.storage import db, backup, upgrades
from deixis.workflow import text_retry, waiting, equations, file_restore, reconcile
from deixis.workflow.report_export import to_markdown
from deixis.workflow.report_latex import to_latex
from deixis.workflow.review_stale import stale_reasons
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from deixis.workflow.views import research_view, report_view

from reextract_r2c_helpers import child, events, forbid_calls, startup
from reextract_r3_helpers import retry, rich
from review_helpers import all_rows
from reextract_r2a_helpers import store_library, seed, head, protected, counts, sharing, api_library, body, url, PUBLIC_RETRY_FIELDS
from reextract_r2b_helpers import tear, write, receipt, research, retained, source
from tests.support.helpers import make_pdf
from reextract_r3_helpers import no_external_calls  # noqa: F401  (fixtures used by name)
from review_helpers import review_lib  # noqa: F401  (fixtures used by name)
from test_report_assembly import report_with_sections  # noqa: F401  (fixtures used by name)


try:
    from deixis.workflow import text_retry
    from deixis.workflow.store import TEXT_RETRY_REFUSALS
except ImportError:
    text_retry = None
    TEXT_RETRY_REFUSALS = ("asset_removed", "no_holding_research", "membership_changed", "asset_replaced",
                          "baseline_changed", "run_active", "input_not_verified", "file_missing", "file_mismatch")


def reserve(lib, key="store_request", rid=True):
    return lib.store.reserve_text_retry(lib.aid, expected_extraction_id=lib.eid, idempotency_key=key,
                                       request_fingerprint=key, research_id=lib.rid if rid else None)


async def execute(lib, key="driver_request"):
    return await text_retry.execute_text_retry(lib.store, lib.settings, asset_id=lib.aid,
        expected_extraction_id=lib.eid, idempotency_key=key, research_id=lib.rid, source_version_id=lib.svid)


def record(lib, op):
    return lib.store.record_text_retry_input(op["id"], storage_path=lib.path.name,
        expected_sha256=lib.sha, expected_byte_size=len(lib.data), observed_sha256=lib.sha,
        observed_byte_size=len(lib.data), integrity="verified")


try:
    from deixis.workflow import file_restore
except ImportError:
    file_restore = None  # The scheduler reproduction must reach its behavioral assertion on 19d0a48.


@pytest.mark.parametrize("shared", [False])
def test_backup_and_purge_keep_receipt_and_retained_bytes_new_contract(tmp_path, shared):
    """R3 includes retained evidence in backup; only source sharing keeps unpurged receipts."""
    with store_library(tmp_path) as lib:
        tear(lib)
        # Keep S1 held elsewhere while purging the initiating research.
        if shared:
            other = research(lib.store)
            lib.store.add_to_corpus(other, lib.svid, "user_upload")
        result = write(lib)
        saved = lib.store.file_restore_view(result.operation_id)
        path = lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")
        archive = backup.create_backup(lib.settings, tmp_path / "backups")
        assert archive.is_dir()
        assert (archive / "papers" / path.name).read_bytes() == lib.torn
        lib.store.trash_research(lib.rid)
        files, _ = lib.store.purge_research(lib.rid)
        if shared:
            assert lib.store.file_restore_view(result.operation_id) == saved and path.read_bytes() == lib.torn
            assert lib.conn.execute("SELECT count(*) FROM asset_file_observations WHERE operation_id = ?", (result.operation_id,)).fetchone()[0] == 2
            assert path.name not in files
        else:
            assert lib.conn.execute("SELECT count(*) FROM asset_recovery_operations WHERE id = ?", (result.operation_id,)).fetchone()[0] == 0
            assert lib.conn.execute("SELECT count(*) FROM asset_file_observations WHERE operation_id = ?", (result.operation_id,)).fetchone()[0] == 0
            assert path.name in files


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


try:
    from deixis.workflow import text_retry
except ImportError:
    text_retry = None  # T1/T3 must reach their behavioral assertions on the R1 base.


def assert_event_agreement(lib, result):
    row = dict(lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE id = ?", (result["operation_id"],)).fetchone())
    events = lib.conn.execute("SELECT payload_json FROM events WHERE type = 'asset_text_retried'").fetchall()
    fields = ("lifecycle", "outcome", "reason", "decision_code")
    for key in fields:
        assert result[key] == row[key]
    relevant = [json.loads(e[0]) for e in events if json.loads(e[0])["operation_id"] == result["operation_id"]]
    assert len(relevant) == len(lib.store._asset_researches(lib.svid))
    for payload in relevant:
        assert payload == {k: result[k] for k in ("asset_id", "operation_id", *fields, "extraction_version", "baseline_extraction_id")} | {
            "source_version_id": lib.svid}


def test_t1_repaired_failed_same_profile_publishes_new_head_red_on_old(tmp_path):
    with api_library(tmp_path) as lib:
        old = head(lib.store, lib.aid)
        sharing(lib)
        lib.path.write_bytes(lib.data[:len(lib.data) * 4 // 10])
        restored = lib.client.post(f"/api/researches/{lib.rid}/sources/{lib.svid}/uploads",
                                  files={"file": ("synthetic.pdf", lib.data, "application/pdf")})
        assert restored.status_code == 201, restored.text
        assert lib.path.read_bytes() == lib.data and head(lib.store, lib.aid) == old
        response = lib.client.post(url(lib), json=body(lib))
        legacy = response.json().get("reextraction")
        current = head(lib.store, lib.aid)
        assert current["id"] != old["id"] and current["extraction_version"].startswith(pdf.EXTRACTION_VERSION + "+reextract-"), legacy
        assert response.status_code == 200
        result = response.json()["recovery"]
        assert (result["outcome"], result["decision_code"], result["input_integrity"]) == ("promoted", "recovered_text", "verified")
        assert current["extraction_version"] == pdf.EXTRACTION_VERSION + "+reextract-" + result["operation_id"]
        assert current["extractor_profile"] == pdf.EXTRACTION_VERSION
        assert dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE id = ?", (old["id"],)).fetchone()) == old | {"outcome": "superseded"}
        assert {p["physical_page"] for p in lib.store.passages_for(lib.svid)} == {1, 2, 3}
        obs = lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?", (result["input_observation_id"],)).fetchone()
        assert (obs["kind"], obs["observed_sha256"]) == ("extraction_input", lib.sha)
        assert_event_agreement(lib, result)


@pytest.mark.parametrize("change", ["csrf"])
def test_request_authority_refusals_write_no_operation(tmp_path, change):
    with api_library(tmp_path) as lib:
        if change == "csrf": lib.client.headers.pop("x-deixis-csrf")
        elif change == "research": lib.rid = lib.store.create_research("SYNTHETIC absent source?", "attached", "quick", [], "fake", "fake", None)
        elif change == "membership": lib.store.remove_sources(lib.rid, [lib.svid], "SYNTHETIC removed")
        elif change == "foreign": lib.aid = seed(lib.store, lib.settings).aid
        elif change == "removed": lib.store.remove_asset(lib.rid, lib.svid, lib.aid)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == (403 if change == "csrf" else 404)
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("status,reason", [("succeeded", "already_current")])
def test_healthy_and_pending_are_not_retryable(tmp_path, status, reason):
    with api_library(tmp_path, status) as lib:
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 422
        assert response.json()["code"] == "not_retryable" and response.json()["reason"] == reason
        assert lib.client.post(url(lib)).json()["reextraction"]["reason"] == reason
        assert counts(lib.store)["asset_recovery_operations"] == 0


@pytest.mark.parametrize("kind", ["traversal"])
def test_precheck_invalid_paths_write_no_operation(tmp_path, kind):
    with api_library(tmp_path) as lib:
        if kind in ("traversal", "absolute", "separator"):
            lib.conn.execute("UPDATE source_assets SET storage_path = ? WHERE id = ?",
                             ({"traversal": "..pdf", "absolute": str(lib.path), "separator": "a/b.pdf"}[kind], lib.aid))
        else:
            lib.path.unlink()
            if kind == "symlink":
                outside = tmp_path / "outside.pdf"; outside.write_bytes(lib.data); lib.path.symlink_to(outside)
            elif kind == "directory": lib.path.mkdir()
        assert lib.client.post(url(lib), json=body(lib)).status_code == 404
        assert counts(lib.store)["asset_recovery_operations"] == 0


try:
    from deixis.workflow import text_retry
except ImportError:
    text_retry = None  # The unchanged library-wide selection guard also runs on R1.


def invoke(lib, monkeypatch, dry=False):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(lib.settings.data_dir))
    return cli.main(["reextract", "--retry", lib.aid, "--expected-extraction", lib.eid] + (["--dry-run"] if dry else []))


def file_state(folder):
    """Every file and its digest; the empty folder lock every command takes at its start (`library.lock`, E1) is not library data."""
    return {str(p.relative_to(folder)): (p.is_dir(), None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in folder.rglob("*") if p.name != "library.lock"}


def test_cli_retry_promotes_one_failed_asset_and_prints_stored_result(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        assert invoke(lib, monkeypatch) == 0
        printed = capsys.readouterr()
        operation = lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone()
        result = lib.store.text_retry_view(operation["id"])
        assert set(result) == PUBLIC_RETRY_FIELDS
        assert printed.err == ""
        assert printed.out.strip() == f"completed promoted recovered_text {operation['id']} {result['extraction_version']}"
        assert result["input_integrity"] == "verified" and head(lib.store, lib.aid)["id"] != lib.eid
        assert operation["research_id"] is None and operation["idempotency_key"].startswith("cli-")


def test_dry_run_with_a_pending_migration_refuses_without_migrating(tmp_path, monkeypatch, capsys):
    settings = cli.Settings(data_dir=tmp_path)
    conn = db.connect(settings.db_path); db.migrate(conn); conn.close()
    # The code now ships one more upgrade step than the library has applied.
    version = max(db.packaged_versions()) + 1
    step = upgrades.Step(f"{version:04d}_synthetic_pending.sql", False, "CREATE TABLE synthetic_pending (id TEXT PRIMARY KEY);\n")
    monkeypatch.setattr(upgrades, "STEPS", {**upgrades.STEPS, version: step})
    before = file_state(tmp_path)
    assert cli.plan_text_retry(settings, "ast_missing", "ext_missing") == 2
    assert "this library needs a migration" in capsys.readouterr().err
    assert file_state(tmp_path) == before
    check = sqlite3.connect(settings.db_path.as_uri() + "?immutable=1", uri=True)
    assert version not in {r[0] for r in check.execute("SELECT version FROM schema_migrations")}
    check.close()


@pytest.mark.parametrize("dry", [True])
def test_newer_schema_refusal_exit_two(tmp_path, monkeypatch, capsys, dry):
    with store_library(tmp_path) as lib:
        lib.conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (9999, 'SYNTHETIC newer', 'now')")
        before = file_state(lib.settings.data_dir)
        assert invoke(lib, monkeypatch, dry) == 2
        assert capsys.readouterr().err
        assert file_state(lib.settings.data_dir) == before


@pytest.mark.parametrize("route", ["upload"])
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


def test_file_only_restore_never_calls_parser_tools_models_or_http_new_contract(tmp_path, monkeypatch):
    """Paired T2a: a reused source's file repair has no extraction side effect."""
    with api_library(tmp_path) as lib:
        tear(lib)
        def forbidden(*args, **kwargs):
            raise AssertionError("File repair called an extraction, tool or model")
        for module, name in ((pdf, "extract_pdf"), (ocr, "read_page"), (equations.EquationService, "read_asset")):
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


def test_r2_startup_reconciles_text_without_parsing_red_on_old(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        with child(lib, "crash_text"):
            pass
        old = lib.store.text_retry_by_key("crashed_request")
        before, rows = protected(lib.store), counts(lib.store)
        forbid_calls(monkeypatch)
        with startup(lib) as (app, _):
            result = app.state.store.text_retry_view(old["id"])
            assert result["lifecycle"] != "running"
            assert result["reason"] == "process_ended"
            assert app.state.reconciled == {"text_retries": 1, "file_restores": 0, "live": 0}
            assert protected(app.state.store) == before
            after = counts(app.state.store)
            for table in ("asset_extractions", "passages", "asset_recovery_operations", "asset_file_observations"):
                assert after[table] == rows[table]
            assert len(events(app.state.store, "asset_text_retried", old["id"])) == 1


def test_r8_startup_ten_turns_capability_and_queue_never_retry_new_contract(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        reserve(lib)
        lib.store.reserve_file_restore(lib.sha, len(lib.data), caller="upload", research_id=lib.rid)
        before = protected(lib.store), counts(lib.store)
        with monkeypatch.context() as patch:
            forbid_calls(patch)
            with startup(lib) as (app, _):
                assert app.state.reconciled == {"text_retries": 1, "file_restores": 1, "live": 0}
            real_wait = asyncio.wait_for
            async def short(awaitable, timeout): return await real_wait(awaitable, 0.001 if timeout == 1.0 else timeout)
            patch.setattr(asyncio, "wait_for", short)
            async def turns():
                for _ in range(10): await lib.app.state.worker._turn()
            asyncio.run(turns())
            from deixis.workflow import reconcile
            asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
            assert lib.client.get(url(lib, "text-retry")).status_code == 200
            assert lib.store.next_queued_run() is None
            assert protected(lib.store) == before[0]
            after = counts(lib.store)
            for table in ("asset_extractions", "passages", "asset_recovery_operations"):
                assert after[table] == before[1][table]
        assert lib.client.post(url(lib), json=body(lib)).json()["recovery"]["outcome"] == "promoted"


@pytest.mark.parametrize("limit", ["timeout"])
def test_r10_real_parser_limits_through_retry_guard(tmp_path, monkeypatch, limit):
    with api_library(tmp_path) as lib:
        client = lib.client
        if limit == "pages":
            lib = seed(lib.store, lib.settings, data=make_pdf([f"SYNTHETIC text on page {i}." for i in range(1, 402)]))
        real, calls, processes = pdf.extract_pdf, [], []
        if limit == "timeout": monkeypatch.setattr(pdf, "TIMEOUT_SECONDS", 0.000001)
        popen = pdf.subprocess.Popen
        def launch(*args, **kwargs):
            process = popen(*args, **kwargs); processes.append(process); return process
        monkeypatch.setattr(pdf.subprocess, "Popen", launch)
        def parse(*args, **kwargs):
            calls.append((args, kwargs))
            assert len(args) == 1 and kwargs == {} and args[0] != lib.path
            if limit == "memory": return real(args[0], max_memory=1)
            if limit == "chars": return real(args[0], max_chars=15)
            return real(*args)
        monkeypatch.setattr(pdf, "extract_pdf", parse)
        response = client.post(url(lib), json=body(lib, "limit_request"))
        assert response.status_code == 200
        result = response.json()["recovery"]
        assert result["lifecycle"] == "completed" and len(calls) == 1
        candidate = dict(lib.conn.execute("SELECT * FROM asset_extractions WHERE id = ?", (result["extraction_id"],)).fetchone())
        if limit in ("timeout", "memory"):
            assert (result["candidate_status"], result["outcome"], result["decision_code"]) == ("failed", "rejected", "candidate_failed")
            assert candidate["error"] == ("extraction timed out" if limit == "timeout" else "extraction exceeded the memory limit")
            assert head(lib.store, lib.aid)["id"] == lib.eid
        else:
            assert result["outcome"] == "promoted" and result["decision_code"] == "recovered_text"
            if limit == "pages":
                assert result["candidate_status"] == "partial" and result["coverage"]["new_text_pages"] == list(range(1, 401))
                assert candidate["page_count"] == 401
            if limit == "chars":
                assert result["candidate_status"] == "partial"
                assert sum(len(p["text"]) for p in lib.store.passages_for(lib.svid)) <= 15
        for process in processes:
            assert process.returncode is not None
            with pytest.raises(ChildProcessError): os.waitpid(process.pid, os.WNOHANG)
        assert not text_retry.lock_held(lib.settings.recovery_dir, lib.sha)


def protected_rows(conn, before, *, changed_asset=None, changed_head=None):
    after = all_rows(conn)
    columns = {t: [r[1] for r in conn.execute('PRAGMA table_info("' + t + '")')] for t in before}
    append_only = {"asset_recovery_operations", "asset_file_observations", "asset_extractions", "passages", "events"}
    for table, old in before.items():
        if table.startswith("passages_fts"):
            continue  # FTS physical storage is covered by the logical query below.
        if table == "sqlite_sequence":
            previous, current = dict(old), dict(after[table])
            delta = len(after["events"]) - len(before["events"])
            assert current.get("events", 0) - previous.get("events", 0) == delta
            assert {k: v for k, v in previous.items() if k != "events"} == {k: v for k, v in current.items() if k != "events"}
            continue
        if table not in append_only and table != "source_assets":
            assert after[table] == old, table
            continue
        for row in old:
            identity = row[columns[table].index("id")]
            current = next(r for r in after[table] if r[columns[table].index("id")] == identity)
            permitted = ({"outcome"} if table == "asset_extractions" and identity == changed_head else
                         {"extraction_version", "extraction_status", "extraction_error", "page_count"}
                         if table == "source_assets" and identity == changed_asset else set())
            assert all(a == b for name, a, b in zip(columns[table], row, current) if name not in permitted), (table, identity)


def retrieval(lib):
    current = lib.store.passages_for(lib.svid)
    ids = {p["id"] for p in current}
    assert {p["id"] for p in lib.store.search_passages([lib.svid], "SYNTHETIC", 500)} == ids
    assert lib.store.has_pdf_text(lib.svid) is bool(ids)
    assert lib.store.answer_versions(lib.rid)[lib.svid] == lib.svid
    assert {p["extraction_version"] for p in current} <= {head(lib.store, lib.aid)["extraction_version"]}
    rejected = {r[0] for r in lib.conn.execute("SELECT p.id FROM passages p JOIN asset_extractions e"
        " ON e.asset_id = p.asset_id AND e.extraction_version = p.extraction_version WHERE e.outcome = 'rejected'")}
    assert ids.isdisjoint(rejected)
    # The actual lexical inspection ranker takes its rows from current-only Store reads.
    from deixis.domain import skill
    from deixis.workflow.flow import FlowDeps, ResearchFlow
    flow = ResearchFlow(FlowDeps(lib.settings, lib.store, {}, skill.load_skill_package(), None))
    # The mixed-corpus scope exercises ranking rather than the small-PDF shortcut.
    ranked = flow._retrieve(lib.rid, lib.store.scope(lib.rid) | {"source_scope": "academic"}, [lib.svid], 500)
    assert {p["id"] for p in ranked} == ids


@pytest.mark.parametrize("outcome", ["promoted", "rejected"])
def test_s5_every_table_protected_guard(tmp_path, monkeypatch, outcome):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        active = lib
        if outcome == "diagnosis":
            import fitz
            doc = fitz.open(stream=make_pdf(["SYNTHETIC password page"]), filetype="pdf")
            data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
            doc.close()
            active = seed(lib.store, lib.settings, "no_text", data=data)
            lib.store.add_to_corpus(lib.rid, active.svid, "user_upload")
            active.rid = lib.rid
        old_head = head(lib.store, active.aid)
        before = all_rows(lib.conn)
        real = pdf.extract_pdf
        if outcome in ("rejected", "no_change"):
            def parse(path):
                candidate = real(path)
                candidate.status = "partial"
                candidate.pages = [p for p in candidate.pages if p.physical_page != (1 if outcome == "rejected" else 3)]
                return candidate
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        if outcome == "interrupted":
            with child(lib, "text", "parser"):
                pass
            asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
        elif outcome == "file_only":
            tear(lib)
            write(lib)
        else:
            result = retry(active)
            assert result["outcome"] == ("diagnosis_updated" if outcome == "diagnosis" else outcome)
        changed = outcome in ("promoted", "diagnosis")
        protected_rows(lib.conn, before, changed_asset=active.aid if changed else None,
                       changed_head=old_head["id"] if changed else None)
        for saved in lib.snapshots:
            reasons = stale_reasons(lib.rich["reader"], saved)
            for entry in saved["content"]["evidence_manifest"]:
                codes = {r["code"] for r in reasons if r.get("passage_id") == entry["passage_id"]}
                assert codes == ({"extraction_changed", "text_superseded"} if outcome == "promoted" else set())
        assert research_view(lib.store, lib.rid)["answers"][0]["source_text_changed"] is (outcome == "promoted")
        record = lib.conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (lib.rich["cell_id"],)).fetchone()
        cell = TableStore(lib.store).cell_view(lib.rid, record["table_id"], record["column_id"], lib.svid)
        assert ("text_superseded" in cell["flags"]) is (outcome == "promoted")
        retrieval(lib)


@pytest.mark.parametrize("outcome", ["promoted"])
def test_s14_current_only_retrieval_guard(tmp_path, monkeypatch, outcome):
    with store_library(tmp_path, "partial") as lib:
        real = pdf.extract_pdf
        if outcome in ("rejected", "no_change"):
            def parse(path):
                value = real(path)
                value.status = "partial"
                value.pages = [p for p in value.pages if p.physical_page != (1 if outcome == "rejected" else 3)]
                return value
            monkeypatch.setattr(pdf, "extract_pdf", parse)
        if outcome == "diagnosis":
            extra = seed(lib.store, lib.settings, "no_text", data=make_pdf(["SYNTHETIC diagnostic asset"]))
            monkeypatch.setattr(pdf, "extract_pdf", lambda path: pdf.Extraction("failed", error=pdf.ERROR_PASSWORD))
            assert retry(extra)["outcome"] == "diagnosis_updated"
            assert not extra.store.passages_for(extra.svid) and not extra.store.has_pdf_text(extra.svid)
        else:
            assert retry(lib)["outcome"] == outcome
        retrieval(lib)


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


@pytest.mark.parametrize("writer", ["upload_new", "run_fetch"])
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


def test_s1_old_citation_document_red_on_old(tmp_path, monkeypatch):
    with api_library(tmp_path, "partial", raise_errors=True) as lib:
        rich(lib)
        old = lib.store.passages_for(lib.svid)
        real = pdf.extract_pdf
        def changed(path):
            result = real(path)
            for page in result.pages:
                page.text = "SYNTHETIC relays with replacement wording on this page."
            return result
        monkeypatch.setattr(pdf, "extract_pdf", changed)
        response = lib.client.post(url(lib), json=body(lib))
        text_url = f"/api/researches/{lib.rid}/assets/{lib.aid}/text"
        historic = lib.client.get(text_url, params={"extraction_id": lib.eid}).json()
        assert [(p["id"], p["text"]) for p in historic["passages"]] == [(p["id"], p["text"]) for p in old]
        assert response.status_code == 200 and response.json()["recovery"]["outcome"] == "promoted"
        assert historic["occurrence"]["outcome"] == "superseded"
        current = lib.client.get(text_url).json()
        assert current["occurrence"]["extraction_id"] == head(lib.store, lib.aid)["id"]
        link = lib.conn.execute("SELECT * FROM evidence_links WHERE passage_id = ?", (lib.pid,)).fetchone()
        returned = next(p for p in historic["passages"] if p["id"] == link["passage_id"])
        assert link["anchor_text"] in returned["text"]
        assert all(link["anchor_text"] not in p["text"] for p in current["passages"] if p["physical_page"] == returned["physical_page"])
        # Rejected occurrences and another asset's occurrence never become a document view.
        candidate = changed(lib.path)
        candidate.pages = []
        lib.store.reextract_asset(lib.aid, candidate, "synthetic-rejected", pdf.chunk_page)
        rejected = lib.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'rejected'").fetchone()[0]
        foreign = seed(lib.store, lib.settings, data=make_pdf(["SYNTHETIC foreign PDF"]))
        for eid in (rejected, foreign.eid, "missing"):
            refused = lib.client.get(text_url, params={"extraction_id": eid})
            assert refused.status_code == 404 and refused.json()["detail"] == "Extraction is not part of this asset"
        replacement = make_pdf(["SYNTHETIC different replacement PDF"])
        replaced = lib.client.put(url(lib).removesuffix("/extractions"), files={"file": ("replace.pdf", replacement, "application/pdf")})
        assert replaced.status_code == 200, replaced.text
        assert lib.client.get(text_url, params={"extraction_id": lib.eid}).json()["passages"] == historic["passages"]
        assert lib.client.get(text_url).status_code == 404


def exports(lib, language="en"):
    view = report_view(lib.store, lib.rid, lib.report_id) | {"language": language}
    corpus = lib.rich["reports"].snapshot(lib.report_id)["corpus"]
    sources = [lib.store.source(r["source_version_id"]) | {"source_version_id": r["source_version_id"], "arxiv_id": None} for r in view["references"]]
    bundle = to_latex(view, title="SYNTHETIC R3", corpus=corpus, bib_sources=sources)
    return view, to_markdown(view, title="SYNTHETIC R3", corpus=corpus), bundle.tex


def test_s3_report_freshness_red_on_old(tmp_path):
    with store_library(tmp_path, "partial") as lib:
        rich(lib)
        before_changes = json.dumps(lib.rich["reports"].evidence_changes(lib.report_id), sort_keys=True)
        before_rows = all_rows(lib.conn)
        baseline = exports(lib)
        baseline_rows_unchanged = all_rows(lib.conn) == before_rows
        baseline_bytes_unchanged = exports(lib)[1:] == baseline[1:]
        retry(lib)
        before_rows = all_rows(lib.conn)
        view, markdown, latex = exports(lib)
        assert "Passage freshness compared:" in markdown
        assert baseline_rows_unchanged and baseline_bytes_unchanged
        freshness = view["passage_freshness"]
        assert freshness["compared"] == "passage_identity" and freshness["semantic_support"] == "not_checked"
        assert len(freshness["affected"]) == 1 and not freshness["unresolved"]
        item = freshness["affected"][0]
        assert item["passage_id"] == lib.pid and item["evidence_status"] == "text_superseded"
        assert item["passage_extraction_id"] == lib.eid and item["current_extraction_id"] != lib.eid
        assert {u["kind"] for u in item["used_by"]} == {"citation", "restorable_citation", "snapshot_cell", "gap_basis", "section_input", "equation_origin"}
        assert item["used_by"] == sorted(item["used_by"], key=lambda u: (u["kind"], u["ref"]))
        assert json.dumps(lib.rich["reports"].evidence_changes(lib.report_id), sort_keys=True) == before_changes
        assert view["evidence_changes"]["not_checked"] == ["passages"]
        assert "Passage freshness compared:" in latex
        assert "Pasaj güncelliği karşılaştırıldı:" in exports(lib, "tr")[1]
        assert all_rows(lib.conn) == before_rows
        lib.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE id = ?", (json.dumps({"basis_passage_ids": ["missing"]}), lib.gap_id))
        unresolved = report_view(lib.store, lib.rid, lib.report_id)["passage_freshness"]["unresolved"]
        assert unresolved == [{"passage_id": "missing", "reason": "passage_missing", "used_by": [{"kind": "gap_basis", "ref": lib.gap_id}]}]


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
