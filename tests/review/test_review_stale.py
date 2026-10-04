"""Each stale reason names a concrete dependency change on synthetic records."""

import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from deixis.storage import db
from deixis.workflow.review.snapshot import build_snapshot
from deixis.workflow.review.stale import REASONS, stale_reasons, claim_text_changed
from deixis.workflow.review.store import NotFound
from tests.review_helpers import report_with_sections, review_lib, snapshot, make_answer
from tests.report.test_report_claim_links import edit


def codes(lib, saved):
    return {r["code"] for r in stale_reasons(lib["reader"], saved)}


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_no_change_has_no_reason_or_not_checked(review_lib, kind):
    saved = snapshot(review_lib, kind)
    assert stale_reasons(review_lib["reader"], saved) == []


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_scope_revised(review_lib, kind):
    lib = review_lib; saved = snapshot(lib, kind)
    lib["store"].revise_scope(lib["rid"], lib["store"].research(lib["rid"])["version"], "SYNTHETIC new scope", None)
    assert "scope_revised" in codes(lib, saved)


def test_newer_answer(review_lib):
    lib = review_lib; saved = snapshot(lib, "answer"); aid = make_answer(lib)
    assert "newer_answer" in codes(lib, saved)
    assert next(r for r in stale_reasons(lib["reader"], saved) if r["code"] == "newer_answer")["answer_id"] == aid


def test_sources_added(review_lib):
    lib = review_lib; saved = snapshot(lib, "answer")
    source = lib["store"].create_upload_source("SYNTHETIC extra")
    lib["store"].add_to_corpus(lib["rid"], source, "user_upload", selection_state="included", selection_origin="user")
    assert "sources_added" in codes(lib, saved)


def test_sources_removed(review_lib):
    lib = review_lib; saved = snapshot(lib, "answer")
    lib["conn"].execute("UPDATE selections SET state = 'excluded' WHERE research_id = ?", (lib["rid"],))
    assert "sources_removed" in codes(lib, saved)


@pytest.mark.parametrize("field", ["stamp", "revision"])
def test_selection_changed_with_same_included_set(review_lib, field):
    lib = review_lib; saved = snapshot(lib, "answer")
    if field == "stamp": lib["conn"].execute("UPDATE selections SET updated_at = '2099' WHERE research_id = ?", (lib["rid"],))
    else: lib["conn"].execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (lib["rid"],))
    assert "selection_changed" in codes(lib, saved)
    assert not {"sources_added", "sources_removed"} & codes(lib, saved)


def test_newer_report_version(review_lib):
    lib = review_lib; saved = snapshot(lib)
    run = lib["store"].create_run(lib["rid"], "report", {}, None)
    report = lib["reports"].create_report(lib["rid"], run["id"], 1, "en")
    lib["reports"].create_section(report, "III", 3)
    lib["conn"].execute("UPDATE report_sections SET status = 'valid' WHERE report_id = ?", (report,))
    lib["reports"].finalize(report, "valid")
    assert "newer_report_version" in codes(lib, saved)


def test_report_version_changed_after_draft_finalizes_without_a_newer_report(report_with_sections):
    from deixis.workflow.review.reader import ReviewReader
    from deixis.workflow.review.store import ReviewStore
    from tests.report.test_report_edit_check import finish
    lib = report_with_sections; lib["rid"] = finish(lib, status="draft")
    lib["reader"] = ReviewReader(lib["store"], lib["reports"])
    lib["reviews"] = ReviewStore(lib["store"].conn)
    saved = snapshot(lib)
    assert saved["markers"]["report_version"] is None
    lib["reports"].finalize(lib["report_id"], "valid")
    assert codes(lib, saved) == {"report_version_changed"}


def test_claim_edited_names_claim_and_acknowledgement_cannot_clear_it(review_lib):
    lib = review_lib; saved = snapshot(lib); edit(lib, text="SYNTHETIC human change")
    reasons = stale_reasons(lib["reader"], saved)
    assert next(r for r in reasons if r["code"] == "claim_edited")["claim_ref"] == "III.1"
    lib["conn"].execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (lib["cell_id"],))
    keys = [c["key"] for c in lib["reports"].evidence_changes(lib["report_id"])["sections"]["III"]["open"]]
    assert keys
    lib["reports"].acknowledge_changes(lib["rid"], lib["report_id"], "III", keys)
    assert "claim_edited" in codes(lib, saved)


def test_claim_removed(review_lib):
    lib = review_lib; saved = snapshot(lib)
    lib["conn"].execute("DELETE FROM report_citation_links WHERE claim_id IN (SELECT id FROM report_claims WHERE claim_key = 'III.1')")
    lib["conn"].execute("DELETE FROM report_claims WHERE claim_key = 'III.1'")
    assert next(r for r in stale_reasons(lib["reader"], saved) if r["code"] == "claim_removed")["claim_ref"] == "III.1"


def test_cell_changed(review_lib):
    lib = review_lib; saved = snapshot(lib)
    lib["conn"].execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (lib["cell_id"],))
    assert next(r for r in stale_reasons(lib["reader"], saved) if r["code"] == "cell_changed")["cell_id"] == lib["cell_id"]


def test_rows_added(review_lib):
    lib = review_lib; saved = snapshot(lib)
    source = lib["store"].create_upload_source("SYNTHETIC additional row")
    lib["store"].add_to_corpus(lib["rid"], source, "user_upload", selection_state="included", selection_origin="user")
    lib["conn"].execute("INSERT INTO table_rows (table_id, source_version_id, added_by, created_at) VALUES (?, ?, 'user', 'now')", (saved["content"]["table_id"], source))
    assert "rows_added" in codes(lib, saved)


def test_rows_removed(review_lib):
    lib = review_lib; saved = snapshot(lib)
    lib["conn"].execute("UPDATE table_rows SET removed_at = '2099' WHERE source_version_id = ?", (lib["source_id"],))
    assert "rows_removed" in codes(lib, saved)


def test_column_revised(review_lib):
    lib = review_lib; saved = snapshot(lib)
    lib["conn"].execute("UPDATE table_columns SET current_revision = current_revision + 1")
    assert "column_revised" in codes(lib, saved)


def test_older_targets_use_latest_at_snapshot_baseline(review_lib):
    lib = review_lib; make_answer(lib)
    saved_answer = snapshot(lib, "answer")
    assert "newer_answer" not in codes(lib, saved_answer)
    run = lib["store"].create_run(lib["rid"], "report", {}, None)
    newer = lib["reports"].create_report(lib["rid"], run["id"], 1, "en")
    lib["reports"].create_section(newer, "III", 3)
    lib["conn"].execute("UPDATE report_sections SET status = 'valid' WHERE report_id = ?", (newer,))
    lib["reports"].finalize(newer, "valid")
    assert "newer_report_version" not in codes(lib, snapshot(lib))


def test_frozen_cell_and_live_marker_are_distinct(review_lib):
    lib = review_lib
    old_revision = lib["conn"].execute("SELECT current_revision_id FROM evidence_cells WHERE id = ?", (lib["cell_id"],)).fetchone()[0]
    lib["conn"].execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (lib["cell_id"],))
    saved = snapshot(lib)
    assert saved["content"]["cells"][0]["cell_revision_id"] == old_revision
    assert saved["markers"]["cells"][lib["cell_id"]] is None
    assert "cell_changed" not in codes(lib, saved)


@pytest.mark.parametrize("reason", ["passage_changed", "asset_changed", "extraction_changed", "evidence_missing", "pdf_replaced", "pdf_removed", "text_superseded"])
@pytest.mark.parametrize("kind", ["answer", "report"])
def test_each_evidence_reason_is_bound_to_its_target_with_stub_reader(review_lib, monkeypatch, reason, kind):
    # Passages are immutable. The stub simulates dependency loss/recreation without weakening a trigger.
    lib = review_lib; reader = lib["reader"]; pid = lib["section_passage"]
    original = reader.evidence_dependency
    def baseline(id_):
        dep = original(id_)
        if id_ == pid:
            dep.update(asset_id="ast_SYNTHASSET01", dependency_asset_id="ast_SYNTHASSET01", asset_sha256="a" * 64,
                       extraction_version="v1", passage_extraction_id="ext_SYNTHORIGINAL", current_extraction_id_at_snapshot="ext_SYNTHCURRENT", evidence_status="current")
        return dep
    monkeypatch.setattr(reader, "evidence_dependency", baseline)
    monkeypatch.setattr(reader, "evidence_exists", lambda asset_id, extraction_id: True)
    saved = snapshot(lib, kind)
    assert stale_reasons(reader, saved) == []
    def changed(id_):
        dep = baseline(id_)
        if id_ != pid: return dep
        if reason == "evidence_missing": return None
        if reason == "passage_changed": dep["text"] += " SYNTHETIC changed words."
        if reason == "asset_changed": dep["asset_sha256"] = "b" * 64
        if reason == "extraction_changed": dep["current_extraction_id_at_snapshot"] = "ext_SYNTHNEXT"
        if reason in {"pdf_replaced", "pdf_removed", "text_superseded"}: dep["evidence_status"] = reason
        return dep
    monkeypatch.setattr(reader, "evidence_dependency", changed)
    assert codes(lib, saved) == {reason}
    row = next(r for r in stale_reasons(reader, saved) if r["code"] == reason)
    assert row["passage_id"] == pid and row["targets"]
    assert row["target_ref"]["kind"] in {"claim", "cell", "whole"}


def asset_evidence(lib):
    from deixis.documents.pdf import Extraction, PageText
    from deixis.documents.pdf import chunk_page as chunks
    from tests.helpers import make_pdf
    data = make_pdf(["SYNTHETIC pdf evidence."])
    sha = hashlib.sha256(data).hexdigest()
    asset = lib["store"].add_asset_with_pages(lib["source_id"], sha, len(data), "SYNTHETIC.pdf", "user_upload", None, "SYNTHETIC.pdf",
        Extraction("succeeded", 1, [PageText(1, None, "SYNTHETIC pdf evidence.")]), "synthetic-v1", chunks)
    pid = next(p["id"] for p in lib["store"].passages_for(lib["source_id"]) if p["asset_id"] == asset)
    lib["conn"].execute("INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, id, ?, ?, ?, 'SYNTHETIC pdf evidence', 'exact' FROM report_claims WHERE claim_key = 'III.1'",
        (db.new_id("rln"), pid, lib["source_id"], lib["report_input_id"]))
    return asset, pid, data, sha


def test_superseded_extraction_keeps_own_and_current_ids_distinct(review_lib):
    from deixis.documents.pdf import Extraction, PageText
    from deixis.documents.pdf import chunk_page as chunks
    lib = review_lib; asset, pid, _, _ = asset_evidence(lib)
    extraction = Extraction("succeeded", 1, [PageText(1, None, "SYNTHETIC replacement evidence.")])
    lib["store"].reextract_asset(asset, extraction, "synthetic-v2", chunks)
    saved = snapshot(lib)
    manifest = next(e for e in saved["content"]["evidence_manifest"] if e["passage_id"] == pid)
    assert manifest["passage_extraction_id"] != manifest["current_extraction_id_at_snapshot"]
    assert manifest["evidence_status"] == "text_superseded"
    assert not {"extraction_changed", "evidence_missing", "text_superseded"} & codes(lib, saved)
    lib["store"].reextract_asset(asset, extraction, "synthetic-v3", chunks)
    assert "extraction_changed" in codes(lib, saved)


def test_abstract_has_no_asset_reasons_and_replaced_before_snapshot_is_not_new(review_lib):
    lib = review_lib; asset, _, _, _ = asset_evidence(lib)
    lib["conn"].execute("UPDATE source_assets SET removed_at = 'now', removal_reason = 'replaced' WHERE id = ?", (asset,))
    saved = snapshot(lib)
    assert "pdf_replaced" not in codes(lib, saved)
    abstract = next(e for e in saved["content"]["evidence_manifest"] if e["passage_id"] == lib["abstract_passage"])
    assert all(abstract[k] is None for k in ("asset_id", "asset_sha256", "passage_extraction_id", "current_extraction_id_at_snapshot"))


@pytest.mark.parametrize("missing", ["asset", "extraction"])
def test_original_asset_or_extraction_missing_names_its_target(review_lib, monkeypatch, missing):
    lib = review_lib; asset, pid, _, _ = asset_evidence(lib); saved = snapshot(lib)
    original = lib["reader"].evidence_exists
    manifest = next(e for e in saved["content"]["evidence_manifest"] if e["passage_id"] == pid)
    # SQLite prevents deleting referenced rows. A stub exercises read-time loss
    # without disabling foreign keys or weakening production triggers.
    def exists(asset_id, extraction_id):
        if (missing == "asset" and asset_id == asset or
                missing == "extraction" and extraction_id == manifest["passage_extraction_id"]):
            return False
        return original(asset_id, extraction_id)
    monkeypatch.setattr(lib["reader"], "evidence_exists", exists)
    reason = next(r for r in stale_reasons(lib["reader"], saved) if r["code"] == "evidence_missing")
    assert reason["passage_id"] == pid and reason["targets"] == [{"kind": "claim", "ref": "III.1"}]


def test_snapshot_content_and_markers_share_one_reserved_read_transaction(review_lib, tmp_path, monkeypatch):
    lib = review_lib; other = db.connect(tmp_path / "library.sqlite")
    other.execute("PRAGMA busy_timeout = 1")
    original = lib["reader"].latest_answer
    traces = []; lib["conn"].set_trace_callback(traces.append)
    def between(rid):
        assert lib["conn"].in_transaction
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (rid,))
        return original(rid)
    monkeypatch.setattr(lib["reader"], "latest_answer", between)
    try:
        content, markers = build_snapshot(lib["reader"], lib["rid"], "answer", lib["answer_id"])
        assert content["scope_revision"] == markers["scope_revision"] == 1
        assert sum(s == "BEGIN IMMEDIATE" for s in traces) == 1
        assert sum(s == "COMMIT" for s in traces) == 1
    finally: other.close(); lib["conn"].set_trace_callback(None)


def test_model_skill_and_provider_metadata_do_not_add_reasons(review_lib, monkeypatch):
    from deixis.domain import skill
    lib = review_lib; saved = snapshot(lib)
    monkeypatch.setattr(skill, "package_hash", lambda: "sha256:" + "e" * 64)
    lib["conn"].execute("UPDATE source_versions SET title = 'SYNTHETIC new provider title', landing_url = 'https://synthetic.invalid'")
    from tests.review_helpers import step_payload
    payload = step_payload(lib, saved, model={"connection": "fake", "requested_model": "SYNTHETIC-other-model"})
    assert lib["store"].step_input_payload(payload["step_input_id"])["model"]["requested_model"] == "SYNTHETIC-other-model"
    assert stale_reasons(lib["reader"], saved) == []


def test_trashed_targets_are_explicit(review_lib):
    lib = review_lib; saved = snapshot(lib)
    lib["store"].trash_research(lib["rid"])
    with pytest.raises(NotFound): stale_reasons(lib["reader"], saved)


def test_claim_text_changed_is_effective_text_only():
    assert not claim_text_changed({"text": "same"}, {"text": "same", "current_revision_id": None})
    assert claim_text_changed({"text": "old"}, {"text": "old", "current_revision_id": "rev", "revision_text": "new"})
    assert claim_text_changed("old", None)


def test_every_declared_reason_has_a_named_test():
    from pathlib import Path
    text = Path(__file__).read_text()
    text += Path(__file__).with_name("test_review_candidate_stale.py").read_text()
    assert len(REASONS) == len(set(REASONS))
    for reason in REASONS:
        assert f"def test_{reason}" in text or f'"{reason}"' in text.split('def test_each_evidence_reason')[0]
