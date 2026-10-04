"""P5 slice 4 (D51) sub-step 3: a `pdf_ocr` run reads a PDF's scanned pages one step per page, without a model call.

Tesseract is replaced by a fake page reader, and pages are SYNTHETIC. Passing shows which pages are read, that a page read
once is not read again when the run resumes, and when the OCR extraction is written; it says nothing about OCR accuracy.
"""

import threading

from fastapi.testclient import TestClient

from deixis.documents import ocr
from helpers import make_scanned_pdf
from test_api_flow import app_for, create, session, wait_run

READY = {"available": True, "version": "5.5.2", "languages": ["eng"], "missing_languages": ["tur"], "reason": "no tur"}


def fake_reader(monkeypatch, fail_once=(), gate=None):
    calls = []

    def read_page(path, page, langs, timeout=ocr.TIMEOUT_SECONDS):
        if gate is not None:
            gate.wait(10)
        calls.append(page)
        if page in fail_once and calls.count(page) == 1:
            return ocr.OcrPage(page, "failed", error="OCR timed out")
        return ocr.OcrPage(page, "succeeded", f"SYNTHETIC OCR text of page {page}.")

    monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: READY)
    monkeypatch.setattr(ocr, "read_page", read_page)
    return calls


def upload(client, rid, pages):
    before = {s["source_version_id"] for s in client.get(f"/api/researches/{rid}").json()["sources"]}
    view = client.post(f"/api/researches/{rid}/uploads", files={"file": ("scan.pdf", make_scanned_pdf(pages), "application/pdf")}).json()
    source = next(s for s in view["sources"] if s["source_version_id"] not in before)
    return source["source_version_id"], source["access"]["assets"][0]["id"]


def ocr_url(rid, svid, aid):
    return f"/api/researches/{rid}/sources/{svid}/assets/{aid}/ocr"


SCAN = [("text", "SYNTHETIC text layer page."), ("scan", "SYNTHETIC scanned page."), ("blank", None), ("scan", "SYNTHETIC second scan.")]


def test_a_pdf_ocr_run_reads_each_scanned_page_once_and_stores_the_ocr_extraction(tmp_path, monkeypatch):
    calls = fake_reader(monkeypatch)
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)

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
    calls = fake_reader(monkeypatch, fail_once=(4,))
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)
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


def test_the_ocr_action_checks_the_tool_the_source_the_file_and_other_runs(tmp_path, monkeypatch):
    gate = threading.Event()
    fake_reader(monkeypatch, gate=gate)
    with TestClient(app_for(tmp_path)) as raw:
        assert raw.post("/api/researches/r/sources/s/assets/a/ocr").status_code == 403  # no CSRF token
        client = session(raw)
        rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)
        text_svid, text_aid = upload(client, rid, [("text", "SYNTHETIC page with a text layer.")])

        assert client.post(ocr_url(rid, svid, "ast_missing")).status_code == 404
        assert client.post(ocr_url(rid, text_svid, aid)).status_code == 404  # the file of another source
        every_page = client.post(ocr_url(rid, text_svid, text_aid))
        assert every_page.status_code == 422 and "every page" in every_page.json()["detail"]

        monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: {
            "available": False, "version": None, "languages": [], "missing_languages": ["eng", "tur"],
            "reason": "Tesseract is not installed. Install it with: brew install tesseract tesseract-lang"})
        missing = client.post(ocr_url(rid, svid, aid))
        assert missing.status_code == 422 and "brew install tesseract tesseract-lang" in missing.json()["detail"]
        monkeypatch.setattr(ocr, "tesseract_status", lambda langs=ocr.LANGUAGES: READY)

        run = client.post(ocr_url(rid, svid, aid)).json()
        assert client.post(ocr_url(rid, svid, aid)).status_code == 409  # a run of this research is active
        gate.set()
        wait_run(client, rid, run["id"])

        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        assert client.post(ocr_url(rid, svid, aid)).status_code == 404  # removed from the research


def test_the_tool_status_and_each_pdf_s_ocr_state_are_shown_for_the_interface(tmp_path, monkeypatch):
    fake_reader(monkeypatch)
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        assert client.get("/api/ocr").json() == READY
        rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)

        def state():
            source = next(s for s in client.get(f"/api/researches/{rid}").json()["sources"] if s["source_version_id"] == svid)
            return source["has_ocr_text"], source["access"]["assets"][0]["ocr"]

        assert state() == (False, {"pages_without_text": 3, "ocr_pages": 0, "last_read": None})
        wait_run(client, rid, client.post(ocr_url(rid, svid, aid)).json()["id"])
        has_ocr, after = state()
        assert has_ocr and (after["pages_without_text"], after["ocr_pages"]) == (1, 2)
        assert {k: after["last_read"][k] for k in ("outcome", "version", "languages", "pages_with_text", "blank_pages", "failed_pages")} \
            == {"outcome": "current", "version": "5.5.2", "languages": ["eng"], "pages_with_text": 2, "blank_pages": 1, "failed_pages": []}
