"""P5 slice 4 (D51): scanned PDF pages are found, read with the local Tesseract one page at a time, and merged into an
extraction whose pages say where their text came from.

Pages are SYNTHETIC images of typed text. Passing shows which pages are read and how results are recorded; it says nothing
about OCR accuracy on real scans. Tests that run Tesseract are skipped when it is not installed.
"""

from __future__ import annotations
import json
import shutil
import pytest
from deixis.documents import ocr, pdf
from deixis.domain import contracts
from deixis.storage import db
from deixis.workflow.run.store import Store
from helpers import make_scanned_pdf
import sys
import time
import httpx
from fastapi.testclient import TestClient
from deixis.tools import tool_paths
from deixis.api.app import create_app
from deixis.documents import ocr, tool_updates
from test_api_flow import app_for, create, fake_fetch, session, sw_settings, wait_run
from fakes import FakeAdapter


SCANNED = "SYNTHETIC scanned page. The release schedule minimizes the bit error probability with packets of 128 bytes."


def write(tmp_path, pages):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf(pages))
    return path


def test_tesseract_status_reports_the_tool_and_the_languages_it_lacks(monkeypatch):
    status = ocr.tesseract_status(("eng", "tur"))
    if shutil.which("tesseract"):
        assert status["available"] and status["version"]
        assert set(status["languages"]) | set(status["missing_languages"]) == {"eng", "tur"}
        assert not set(status["languages"]) & set(status["missing_languages"])
    monkeypatch.setattr(ocr, "find_tool", lambda name: None)
    missing = ocr.tesseract_status(("eng", "tur"))
    assert (missing["available"], missing["languages"]) == (False, [])
    assert missing["reason"] == "tesseract_missing"


def test_a_tesseract_that_cannot_run_gives_a_code_and_its_own_words_stay_in_the_log(monkeypatch, caplog):
    from deixis.tools.tool_probe import Probe

    async def fails(tesseract):
        return [Probe(1, "", "SYNTHETIC dyld: Library not loaded: /private/path/libtesseract.dylib", "failed"), Probe(0, "tesseract 5.5.2", "")]

    async def hangs(tesseract):
        return [Probe(None, "", "", "not_responding"), Probe(0, "", "")]

    monkeypatch.setattr(ocr, "find_tool", lambda name: "/opt/fake/bin/tesseract")
    monkeypatch.setattr(ocr, "_ask_tesseract", fails)
    with caplog.at_level("WARNING", logger="deixis.documents.ocr"):
        failed = ocr.tesseract_status(("eng", "tur"))
    assert failed["reason"] == "tesseract_failed" and "SYNTHETIC" not in str(failed) and "libtesseract" in caplog.text
    monkeypatch.setattr(ocr, "_ask_tesseract", hangs)
    assert ocr.tesseract_status(("eng", "tur"))["reason"] == "tesseract_not_responding"
    assert set(ocr.REASONS) == {"tesseract_missing", "tesseract_not_responding", "tesseract_failed", "tesseract_languages_missing"}


def library_with_scan(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", [], "fake", "fake-model", None)
    svid = store.create_upload_source("SYNTHETIC scanned paper")
    store.add_to_corpus(rid, svid, "user_upload")
    path = write(tmp_path, [("text", "SYNTHETIC text layer page."), ("scan", SCANNED), ("blank", None)])
    base = pdf.extract_pdf(path)
    aid = store.add_asset_with_pages(svid, "sha-scan", 10, "scan.pdf", "user_upload", None, "scan.pdf", base, pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return store, rid, svid, aid, base


def test_an_ocr_extraction_is_stored_with_its_tool_and_page_counts(tmp_path):
    store, rid, svid, aid, base = library_with_scan(tmp_path)
    read = ocr.merge(base, [ocr.OcrPage(2, "succeeded", "SYNTHETIC OCR text of the scanned page.")], ["eng"])

    report = store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)
    assert report["outcome"] == "current" and store.asset(aid)["extraction_version"] == read.extraction_version
    assert [(p["physical_page"], p["text_source"]) for p in store.passages_for(svid)] == [(1, "text_layer"), (2, "ocr")]
    row = store.conn.execute("SELECT ocr_json, math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone()
    assert (json.loads(row["ocr_json"]), row["math_json"]) == (read.ocr, None)
    events = [e for e in store.events_after(rid, 0) if e["type"] in ("asset_ocr_read", "asset_reextracted")]
    assert [e["type"] for e in events] == ["asset_ocr_read"]
    assert events[0]["payload"].items() >= {"asset_id": aid, "outcome": "current", "extraction_version": read.extraction_version,
                                            "pages_read": 1, "pages_with_text": 1, "blank_pages": 1, "failed_pages": [], "languages": ["eng"]}.items()
    assert store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)["outcome"] == "unchanged"


def test_a_cell_value_with_a_number_resting_only_on_ocr_text_is_a_warning_not_an_issue():
    from test_table_extraction import cell_draft, cell_step_input

    si = cell_step_input()
    next(p for p in si["passages"] if p["passage_id"] == "psg_SYNA1pg003")["text_source"] = "ocr"
    draft = cell_draft(si)
    draft["cells"][2].update(state="value", value={"number": 40, "unit": "molecules", "as_stated": "40 molecules"}, note=None)
    report = contracts.validate_model_output(si, draft)
    assert report.ok, [vars(i) for i in report.issues]
    assert [w.path for w in report.warnings if w.code == "ocr_numbers_unchecked"] == ["/cells/2/value"]


def test_ocr_text_joins_words_hyphenated_at_a_line_or_block_end_in_any_lowercase_letters():
    lines = ["Bölge şefliği bakım memuru mevcuduna gö-", "re ayrımlara ayrılır."]
    assert pdf._join_lines(lines) == "Bölge şefliği bakım memuru mevcuduna gö-\nre ayrımlara ayrılır."  # the text layer is unchanged
    assert ocr._page_text([{"lines": lines}]) == "Bölge şefliği bakım memuru mevcuduna göre ayrımlara ayrılır."
    assert ocr._page_text([{"lines": ["Amerikan orman-"]}, {"lines": ["cısı ormanın korunması"]}, {"lines": ["x-"]}, {"lines": ["Arkansas"]}]) \
        == "Amerikan ormancısı ormanın korunması\n\nx-\n\nArkansas"
    assert ocr.OCR_VERSION == "v2"


def releases(request: httpx.Request) -> httpx.Response:
    if request.url.host == "formulae.brew.sh":
        return httpx.Response(200, json={"versions": {"stable": "5.5.3"}})
    if request.url.path == "/pypi/pymupdf/json":
        return httpx.Response(503)
    return httpx.Response(404)


def client_for(tmp_path):
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(releases)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    return TestClient(app)


def test_versions_compare_by_number_and_ignore_homebrew_revisions():
    assert tool_updates.newer("5.5.10", "5.5.9") is True
    assert tool_updates.newer("5.5.2_1", "5.5.2") is False
    assert tool_updates.newer("1.28.2", "1.28.2") is False
    assert tool_updates.newer(None, "1.0") is None and tool_updates.newer("1.0", None) is None


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake Tesseract is a shell script")


def packaged(monkeypatch, bundle, frozen=True):
    monkeypatch.setattr(tool_paths, "is_frozen", lambda: frozen)
    monkeypatch.setattr(tool_paths, "resource_root", lambda: bundle)


def test_a_computer_without_homebrew_is_sent_to_the_page_its_os_installs_tesseract_from(monkeypatch):
    pages = {}
    for platform in ("darwin", "win32", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        pages[platform] = tool_updates.tesseract_page()
    assert [tool_updates.tesseract_source()["install_manager"]] == [None]  # linux, the last one patched
    monkeypatch.setattr(sys, "platform", "darwin")
    assert tool_updates.tesseract_source() == {"install_url": "https://brew.sh", "install_manager": "brew"}
    assert pages["darwin"] == "https://brew.sh"
    assert "UB-Mannheim/tesseract" in pages["win32"] and "tessdoc" in pages["linux"]
    assert len(set(pages.values())) == 3 and all(p.startswith("https://") for p in pages.values())


# A `pdf_ocr` run reads a PDF's scanned pages one step per page (a fake page reader stands in for Tesseract).

OCR_READY = {"available": True, "version": "5.5.2", "languages": ["eng"], "missing_languages": ["tur"], "reason": "tesseract_languages_missing"}


def fake_ocr_reader(monkeypatch, fail_once=(), gate=None):
    calls = []

    def read_page(path, page, langs, timeout=ocr.TIMEOUT_SECONDS):
        if gate is not None:
            gate.wait(10)
        calls.append(page)
        if page in fail_once and calls.count(page) == 1:
            return ocr.OcrPage(page, "failed", error="OCR timed out")
        return ocr.OcrPage(page, "succeeded", f"SYNTHETIC OCR text of page {page}.")

    monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: OCR_READY)
    monkeypatch.setattr(ocr, "read_page", read_page)
    return calls


def upload_scan(client, rid, pages):
    before = {s["source_version_id"] for s in client.get(f"/api/researches/{rid}").json()["sources"]}
    view = client.post(f"/api/researches/{rid}/uploads", files={"file": ("scan.pdf", make_scanned_pdf(pages), "application/pdf")}).json()
    source = next(s for s in view["sources"] if s["source_version_id"] not in before)
    return source["source_version_id"], source["access"]["assets"][0]["id"]


def ocr_url(rid, svid, aid):
    return f"/api/researches/{rid}/sources/{svid}/assets/{aid}/ocr"


OCR_SCAN = [("text", "SYNTHETIC text layer page."), ("scan", "SYNTHETIC scanned page."), ("blank", None), ("scan", "SYNTHETIC second scan.")]


def test_a_pdf_ocr_run_reads_each_scanned_page_once_and_stores_the_ocr_extraction(tmp_path, monkeypatch):
    calls = fake_ocr_reader(monkeypatch)
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = upload_scan(client, rid, OCR_SCAN)

        started = client.post(ocr_url(rid, svid, aid))
        assert started.status_code == 202, started.text
        run = started.json()
        assert (run["kind"], run["target"]) == ("pdf_ocr", {"asset_id": aid, "source_version_id": svid, "languages": ["eng"]})
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        assert sorted(calls) == [2, 4] and run["usage"].get("model_calls", 0) == 0
        assert [s["operation_key"] for s in run["steps"]] == ["ocr:pages", "ocr:page:2", "ocr:page:4", "ocr:merge"]
        assert run["steps"][0]["output"] == {"page_count": 4, "image_pages": [2, 4], "blank_pages": [3]}

        text = client.get(f"/api/researches/{rid}/assets/{aid}/text").json()
        assert [(p["physical_page"], p["text_source"]) for p in text["passages"]] == [(1, "text_layer"), (2, "ocr"), (4, "ocr")]
        event = next(e for e in client.get(f"/api/researches/{rid}/events").json() if e["type"] == "asset_ocr_read")
        assert (event["payload"]["outcome"], event["payload"]["pages_with_text"], event["payload"]["blank_pages"]) == ("current", 2, 1)

        again = client.post(ocr_url(rid, svid, aid))
        assert again.status_code == 409 and "already" in again.json()["detail"]


def test_a_failed_page_pauses_the_run_before_anything_is_written_and_resume_reads_only_that_page(tmp_path, monkeypatch):
    calls = fake_ocr_reader(monkeypatch, fail_once=(4,))
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = upload_scan(client, rid, OCR_SCAN)
        version = client.get(f"/api/researches/{rid}/assets/{aid}/text").json()["passages"][0]["extraction_version"]

        run = client.post(ocr_url(rid, svid, aid)).json()
        _, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "ocr_pages_failed")
        assert run["error"] == {"failed_pages": [4], "errors": {"4": "OCR timed out"}}
        assert all(p["extraction_version"] == version for p in client.get(f"/api/researches/{rid}/assets/{aid}/text").json()["passages"])

        assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
        _, run = wait_run(client, rid, run["id"], statuses=("completed", "failed", "cancelled"))
        assert run["status"] == "completed", run
        assert sorted(calls) == [2, 4, 4]  # page 2 is not read again
        assert [p["text_source"] for p in client.get(f"/api/researches/{rid}/assets/{aid}/text").json()["passages"]] == ["text_layer", "ocr", "ocr"]
