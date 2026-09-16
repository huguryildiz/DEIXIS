"""P5 slice 4 (D51): scanned PDF pages are found, read with the local Tesseract one page at a time, and merged into an
extraction whose pages say where their text came from.

Pages are SYNTHETIC images of typed text. Passing shows which pages are read and how results are recorded; it says nothing
about OCR accuracy on real scans. Tests that run Tesseract are skipped when it is not installed.
"""

import copy
import json
import shutil

import pytest

from deixis.documents import ocr, pdf
from deixis.domain import contracts
from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow import views
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from helpers import make_scanned_pdf

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
SCANNED = "SYNTHETIC scanned page. The release schedule minimizes the bit error probability with packets of 128 bytes."


def write(tmp_path, pages):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scanned_pdf(pages))
    return path


def test_extraction_names_scanned_and_blank_pages(tmp_path):
    path = write(tmp_path, [("text", "SYNTHETIC text layer page."), ("scan", SCANNED), ("blank", None)])
    result = pdf.extract_pdf(path)
    assert result.status == "partial" and [p.physical_page for p in result.pages] == [1]
    assert (result.image_pages, result.blank_pages) == ([2], [3])
    assert result.pages[0].text_source == "text_layer"

    only_scan = pdf.extract_pdf(write(tmp_path, [("scan", SCANNED)]))
    assert (only_scan.status, only_scan.image_pages, only_scan.blank_pages) == ("no_text", [1], [])


def test_tesseract_status_reports_the_tool_and_the_languages_it_lacks(monkeypatch):
    status = ocr.tesseract_status(("eng", "tur"))
    if shutil.which("tesseract"):
        assert status["available"] and status["version"]
        assert set(status["languages"]) | set(status["missing_languages"]) == {"eng", "tur"}
        assert not set(status["languages"]) & set(status["missing_languages"])
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    missing = ocr.tesseract_status(("eng", "tur"))
    assert (missing["available"], missing["languages"]) == (False, [])
    assert "brew install tesseract tesseract-lang" in missing["reason"]


@needs_tesseract
def test_a_scanned_page_is_read_and_merged_as_ocr_text(tmp_path):
    path = write(tmp_path, [("text", "SYNTHETIC text layer page."), ("scan", SCANNED), ("blank", None)])
    extraction = pdf.extract_pdf(path)
    page = ocr.read_page(path, 2, ["eng"])
    assert page.status == "succeeded" and "bit error probability" in page.text and "128 bytes" in page.text

    merged = ocr.merge(extraction, [page], ["eng"])
    assert [(p.physical_page, p.text_source) for p in merged.pages] == [(1, "text_layer"), (2, "ocr")]
    assert merged.pages[0].text == extraction.pages[0].text  # the text layer page is not read again
    assert merged.status == "partial"  # the blank page still has no text
    assert merged.ocr == {"engine": "tesseract", "version": ocr.tesseract_status(("eng",))["version"], "languages": ["eng"],
                          "pages_read": 1, "pages_with_text": 1, "blank_pages": 1, "failed_pages": []}
    assert merged.extraction_version == f"{pdf.EXTRACTION_VERSION}+ocr-tesseract-{merged.ocr['version']}-eng-v1"


@needs_tesseract
def test_a_page_that_fails_or_finds_nothing_is_recorded_and_changes_no_text(tmp_path):
    path = write(tmp_path, [("scan", SCANNED), ("scan", "")])
    extraction = pdf.extract_pdf(path)
    assert extraction.image_pages == [1, 2]

    timed_out = ocr.read_page(path, 1, ["eng"], timeout=0.001)
    assert (timed_out.status, timed_out.text, timed_out.error) == ("failed", "", "OCR timed out")
    empty = ocr.read_page(path, 2, ["eng"])
    assert (empty.status, empty.text) == ("no_text", "")

    merged = ocr.merge(extraction, [timed_out, empty], ["eng"])
    assert (merged.status, merged.pages) == ("no_text", [])
    assert merged.ocr["failed_pages"] == [1] and merged.ocr["pages_with_text"] == 0
    with pytest.raises(ValueError):  # a page that is not a scanned page of this file is refused
        ocr.merge(extraction, [ocr.OcrPage(physical_page=3, status="succeeded", text="x")], ["eng"])


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


def test_an_ocr_extraction_that_found_no_text_is_rejected_and_the_old_text_stays(tmp_path):
    store, rid, svid, aid, base = library_with_scan(tmp_path)
    read = ocr.merge(base, [ocr.OcrPage(2, "failed", error="OCR timed out")], ["eng"])

    report = store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)
    assert report["outcome"] == "rejected" and report["rejection_reason"] == "OCR found no text"
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION
    assert [(p["physical_page"], p["text_source"]) for p in store.passages_for(svid)] == [(1, "text_layer")]
    event = next(e for e in store.events_after(rid, 0) if e["type"] == "asset_ocr_read")
    assert (event["payload"]["outcome"], event["payload"]["failed_pages"]) == ("rejected", [2])


# ---- sub-step 4: OCR in model output checks and views -------------------------------------------
def test_a_claim_with_a_number_resting_only_on_ocr_text_is_a_warning_not_an_issue():
    from test_contracts import STEP_INPUTS
    from test_phrasebank import CASES, anchored

    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    next(p for p in si["passages"] if p["passage_id"] == "psg_SYNA1pg003")["text_source"] = "ocr"
    draft = copy.deepcopy(next(c for c in CASES if c["name"] == "answer_valid")["output"])

    def warned(text, passage_ids):
        draft["claims"][0].update(text=text, passage_ids=passage_ids)
        report = contracts.validate_model_output(si, anchored(draft))
        assert report.ok, [vars(i) for i in report.issues]
        return [w.path for w in report.warnings if w.code == "ocr_numbers_unchecked"]

    assert warned("It has been reported that the budget is 40 molecules per frame.", ["psg_SYNA1pg003"]) == ["/claims/0/text"]
    assert warned(r"It has been reported that $x \le Q$ is required.", ["psg_SYNA1pg003"]) == ["/claims/0/text"]
    assert warned("It has been reported that a molecule budget per frame is imposed.", ["psg_SYNA1pg003"]) == []
    assert warned("It has been reported that the budget is 40 molecules per frame.", ["psg_SYNA1pg003", "psg_SYNA1abs01"]) == []


def test_a_cell_value_with_a_number_resting_only_on_ocr_text_is_a_warning_not_an_issue():
    from test_table_extraction import cell_draft, cell_step_input

    si = cell_step_input()
    next(p for p in si["passages"] if p["passage_id"] == "psg_SYNA1pg003")["text_source"] = "ocr"
    draft = cell_draft(si)
    draft["cells"][2].update(state="value", value={"number": 40, "unit": "molecules", "as_stated": "40 molecules"}, note=None)
    report = contracts.validate_model_output(si, draft)
    assert report.ok, [vars(i) for i in report.issues]
    assert [w.path for w in report.warnings if w.code == "ocr_numbers_unchecked"] == ["/cells/2/value"]


def test_views_say_which_sources_and_cells_rest_on_ocr_text(tmp_path):
    from test_evidence_tables import PACKET_SIZE, VALUE

    store, rid, svid, aid, base = library_with_scan(tmp_path)
    assert next(s for s in views.research_view(store, rid)["sources"] if s["source_version_id"] == svid)["has_ocr_text"] is False
    read = ocr.merge(base, [ocr.OcrPage(2, "succeeded", "SYNTHETIC OCR text: packets of 128 bytes.")], ["eng"])
    store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)
    assert next(s for s in views.research_view(store, rid)["sources"] if s["source_version_id"] == svid)["has_ocr_text"] is True

    passages = {p["physical_page"]: p["id"] for p in store.passages_for(svid)}
    run = store.create_run(rid, "answer", {"max_model_calls": 4}, None)
    step = store.step(run["id"], "cell", "model:cell_extraction")
    sti = new_id("sti")
    store.insert_step_input(step["id"], rid, run["id"], 0, {"step_input_id": sti, "task_type": "cell_extraction", "scope_revision": 1,
                            "skill_package_hash": "sha256:0"}, "base", "developer", "message", {})
    tables = TableStore(store)

    def flags(page, anchor):
        tid = tables.create_table(rid, f"Packets {page}", [svid], None, None)
        cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
        tables.save_model_output(rid, tid, cid, svid, column_revision=1, state="value", value=VALUE, note=None, reading_depth="selected_sections",
                                 output_status="structurally_valid", run_id=run["id"], step_id=step["id"], step_input_id=sti,
                                 links=[{"passage_id": passages[page], "source_version_id": svid, "anchor_text": anchor, "anchor_match": "exact"}],
                                 model_connection="fake", resolved_model="fake-model", scope_revision=1, cell_version_at_request=None, recheck=False)
        cell = tables.cell_view(rid, tid, cid, svid)
        return "ocr_numbers_unchecked" in cell["flags"], [e["text_source"] for e in (cell["pending_proposal"] or cell["current"])["evidence"]]

    assert flags(2, "packets of 128 bytes") == (True, ["ocr"])
    assert flags(1, "SYNTHETIC text layer page") == (False, ["text_layer"])
