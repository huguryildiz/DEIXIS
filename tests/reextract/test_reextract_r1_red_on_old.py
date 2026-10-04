"""Behavioral defect assertions that execute on c3048f4 using only its existing APIs."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from deixis.documents import pdf, ocr
from deixis.storage import db
from deixis.workflow import equations
from deixis.workflow.store import Store
from tests.documents.test_ocr_run import fake_reader, upload, ocr_url, SCAN, READY
from tests.app.test_api_flow import app_for, create, session, wait_run
from tests.documents.test_arxiv_source_route import library


def chunks(text):
    return [(0, len(text), text)] if text else []


def text(pages, count=3):
    return pdf.Extraction("partial", count, [pdf.PageText(p, str(p), f"SYNTHETIC page {p}.") for p in pages])


def test_ordinary_shifted_pages_are_rejected_red_on_old(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    store = Store(conn); svid = store.create_upload_source("SYNTHETIC")
    aid = store.add_asset_with_pages(svid, "1" * 64, 10, "synthetic.pdf", "user_upload", None, None,
                                     text((1, 2)), pdf.EXTRACTION_VERSION, chunks)
    result = store.reextract_asset(aid, text((2, 3)), "distinct-v1", chunks)
    assert result["outcome"] == "rejected"
    assert result["decision_code"] == "text_page_lost"
    assert store.asset(aid)["extraction_version"] == pdf.EXTRACTION_VERSION
    conn.close()


def test_recovered_label_ocr_request_is_202_red_on_old(tmp_path, monkeypatch):
    # A synthetic recovered label is seeded through the pre-existing ordinary
    # Store API. The HTTP assertion requires no proposed recovery function.
    fake_reader(monkeypatch)
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw); rid = create(client, source_scope="attached")
        svid, aid = upload(client, rid, SCAN)
        store = app.state.store
        plain_target = ocr.target_version(pdf.EXTRACTION_VERSION, READY["version"], READY["languages"])
        store.reextract_asset(aid, pdf.Extraction("failed", 4, error="SYNTHETIC failure"), plain_target, chunks)
        assert client.post(ocr_url(rid, svid, aid)).status_code == 409
        version = pdf.EXTRACTION_VERSION + "+reextract-rop_SYNTHETIC"
        store.reextract_asset(aid, text((1,), 4), version, chunks)
        started = client.post(ocr_url(rid, svid, aid))
        assert started.status_code == 202, started.text
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed"
        assert store.asset(aid)["extraction_version"] == version + plain_target.removeprefix(pdf.EXTRACTION_VERSION)


def test_arxiv_withdrawal_restores_exact_predecessor_red_on_old(tmp_path, monkeypatch):
    store, svid, aid, papers = library(tmp_path)
    baseline = store.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'current'").fetchone()[0]
    import deixis.workflow.store as module
    monkeypatch.setattr(module, "now", lambda: "2098")
    base = pdf.extract_pdf(papers / "paper.pdf")
    with db.transaction(store.conn):
        store._write_extraction(svid, aid, base, "competitor-v1", pdf.chunk_page, "superseded")
    competitor = store.conn.execute("SELECT id FROM asset_extractions WHERE extraction_version = 'competitor-v1'").fetchone()[0]
    monkeypatch.setattr(module, "now", lambda: "2099")
    target = equations.source_target_version(None)
    assert store.reextract_asset(aid, base, target, pdf.chunk_page)["outcome"] == "current"
    old_query_choice = store.conn.execute(
        "SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'superseded' AND created_at <= '2099'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (aid,)).fetchone()[0]
    assert old_query_choice == competitor
    store.conn.execute("INSERT INTO asset_arxiv_versions (asset_id, eligibility, arxiv_key, version_from, record_label, checked_at)"
        " VALUES (?, 'eligible', '2101.00001v2', 'url', 'arXiv v2', 'now')", (aid,))
    store.conn.execute("UPDATE source_versions SET version_label = 'publishedVersion' WHERE id = ?", (svid,))
    store._recheck_arxiv_eligibility(svid)
    restored = store.conn.execute("SELECT id FROM asset_extractions WHERE outcome = 'current'").fetchone()[0]
    assert restored == baseline
    store.conn.close()
