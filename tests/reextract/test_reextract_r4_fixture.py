"""Synthetic seed/policy compatibility; these are not scientific evidence."""

import hashlib

from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow import recovery
from deixis.workflow.store import Store
from tests.acceptance.fixture_server import seed_reextract


def test_v5_seed_legacy_inputs_and_real_pdf_policy(tmp_path):
    library, originals = tmp_path / "library", tmp_path / "originals"
    seed_reextract(library)
    seed_reextract(library, write_pdfs_dir=originals)
    conn = db.connect(library / "library.sqlite")
    try:
        store = Store(conn)
        research = conn.execute("SELECT * FROM researches").fetchone()
        scope = store.scope(research["id"])
        assert scope["question"] == "SYNTHETIC re-extraction research"
        assert scope["source_scope"] == "attached"
        sources = conn.execute("SELECT m.*, s.state AS selection_state FROM corpus_memberships m JOIN selections s"
                               " ON s.research_id=m.research_id AND s.source_version_id=m.source_version_id"
                               " WHERE m.research_id=? AND m.removed_at IS NULL", (research["id"],)).fetchall()
        assert len(sources) == 3
        by_title = {store.source(s["source_version_id"])["title"]: s for s in sources}
        for number, (title, status, code) in enumerate([
            ("SYNTHETIC failed read", "failed", "recovered_text"),
            ("SYNTHETIC partial legacy read", "partial", "text_updated"),
            ("SYNTHETIC locked PDF", "no_text", "password_diagnosed"),
        ], 1):
            source = by_title[title]
            assert source["selection_state"] == ("included" if number == 2 else "pending")
            asset = conn.execute("SELECT * FROM source_assets WHERE source_version_id=? AND removed_at IS NULL", (source["source_version_id"],)).fetchone()
            baseline = store._retry_baseline(asset["id"])
            assert baseline["status"] == status
            assert baseline["extraction_version"] == pdf.EXTRACTION_VERSION
            assert baseline["input_observation_id"] is None
            stored = library / "papers" / asset["storage_path"]
            assert (hashlib.sha256(stored.read_bytes()).hexdigest() == asset["sha256"]) is (number == 3)
            if number < 3:
                assert hashlib.sha256((originals / f"P{number}.pdf").read_bytes()).hexdigest() == asset["sha256"]
            parsed = pdf.extract_pdf(originals / f"P{number}.pdf" if number < 3 else stored)
            candidate = {"status": parsed.status, "error": parsed.error, "page_count": parsed.page_count,
                         "extractor_profile": pdf.EXTRACTION_VERSION, "manifest": recovery.coverage_manifest(parsed, pdf.chunk_page)}
            decision = recovery.decide(baseline, candidate)
            assert decision.promote and decision.decision_code == code
            assert decision.diagnostic_only is (number == 3)
            if number == 1:
                assert baseline["passage_count"] == 0
                op = conn.execute("SELECT * FROM asset_recovery_operations WHERE asset_id=?", (asset["id"],)).fetchone()
                assert op["lifecycle"] == "interrupted" and op["reason"] == "process_ended"
            elif number == 2:
                assert baseline["page_count"] == 2 and baseline["passage_count"] == 1
                assert "SYNTHETIC earlier reading" in store.passages_for(source["source_version_id"])[0]["text"]
    finally:
        conn.close()
