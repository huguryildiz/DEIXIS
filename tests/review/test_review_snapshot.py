"""Frozen inputs and snapshot size measured on synthetic answer/report records."""

import copy
import json

import pytest

from deixis.domain import contracts
from deixis.domain.canonical import canonical_json, sha256_hex
from deixis.storage import db
from deixis.workflow.review.snapshot import build_snapshot, review_step_input_parts, DuplicateReviewRef, NotReviewable, ReviewInputTooLarge
from deixis.workflow.review.store import NotFound, resolve_finding, applied_matches_suggestion
from tests.review_helpers import report_with_sections, review_lib, snapshot, step_payload, make_answer, finding
from tests.report.test_report_claim_links import edit, claim


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_stored_input_equals_frozen_parts_and_survives_all_live_edits(review_lib, kind):
    lib = review_lib; saved = snapshot(lib, kind); payload = step_payload(lib, saved)
    before = canonical_json(payload)
    parts = review_step_input_parts(saved["id"], saved["content"], focus="source_support", owner_note=None)
    assert {k: payload[k] for k in parts} == parts
    assert contracts.check_step_input(contracts.with_citation_handles(payload)) == []
    stored = lib["store"].step_input_payload(payload["step_input_id"])
    assert canonical_json(stored) == before
    assert len(canonical_json(saved["content"]).encode()) < 12000  # measured fixture, not a product limit
    print(f"SYNTHETIC {kind} snapshot bytes: {len(canonical_json(saved['content']).encode())}")
    edit(lib, text="SYNTHETIC human revision.", link_ids=[])
    make_answer(lib, text="SYNTHETIC later answer.")
    lib["conn"].execute("UPDATE selections SET updated_at = '2099-01-01' WHERE research_id = ?", (lib["rid"],))
    lib["conn"].execute("UPDATE table_columns SET current_revision = current_revision + 1")
    lib["conn"].execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE id = ?", (lib["cell_id"],))
    assert canonical_json(lib["store"].step_input_payload(payload["step_input_id"])) == before
    assert canonical_json(review_step_input_parts(saved["id"], lib["reviews"].snapshot(saved["id"])["content"], focus="source_support", owner_note=None)) == canonical_json(parts)


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_snapshot_hash_is_deterministic_and_changes_with_text(review_lib, kind):
    lib = review_lib; args = (lib["reader"], lib["rid"], kind, lib[kind + "_id"])
    a, _ = build_snapshot(*args); b, _ = build_snapshot(*args)
    assert sha256_hex(a) == sha256_hex(b)
    if kind == "report": edit(lib, text="SYNTHETIC changed.")
    else: lib["conn"].execute("UPDATE claims SET text = 'SYNTHETIC changed.' WHERE answer_id = ?", (lib["answer_id"],))
    c, _ = build_snapshot(*args)
    assert sha256_hex(a) != sha256_hex(c)


def test_effective_human_text_and_removed_citations_are_frozen(review_lib):
    lib = review_lib
    ids = [e["id"] for e in lib["reports"].original_links(claim(lib)["id"])]
    revision = edit(lib, text="SYNTHETIC edited text.", link_ids=ids[:1])
    saved = snapshot(lib)
    current = next(c for c in saved["content"]["claims"] if c["claim_ref"] == "III.1")
    assert current["revision_id"] == revision and current["text_origin"] == "human_edit"
    assert current["text"] == "SYNTHETIC edited text."
    assert [e["link_id"] for e in current["citations"]] == ids[:1]
    assert saved["content"]["cells"] == []
    assert all(s["section_ref"] != "II" for s in saved["content"]["sections"])


def test_duplicate_report_claim_key_stops_before_storage(review_lib):
    lib = review_lib; before = lib["conn"].execute("SELECT COUNT(*) FROM owner_review_snapshots").fetchone()[0]
    lib["conn"].execute("UPDATE report_claims SET claim_key = 'III.1' WHERE claim_key = 'abstract.1'")
    with pytest.raises(DuplicateReviewRef): build_snapshot(lib["reader"], lib["rid"], "report", lib["report_id"])
    assert lib["conn"].execute("SELECT COUNT(*) FROM owner_review_snapshots").fetchone()[0] == before


def test_stored_claim_key_with_nonsection_prefix_survives_snapshot_and_input(review_lib):
    lib = review_lib
    lib["conn"].execute("UPDATE report_claims SET claim_key = 'custom_prefix.123' WHERE claim_key = 'III.1'")
    saved = snapshot(lib)
    payload = step_payload(lib, saved)
    target = next(c for c in payload["review_input"]["claims"] if c["claim_ref"] == "custom_prefix.123")
    assert target["section_ref"] == "III"
    assert "custom_prefix.123" in payload["allowlist"]["claim_refs"]
    assert contracts.check_step_input(contracts.with_citation_handles(payload)) == []


def test_duplicate_answer_label_is_checked_by_builder_with_reader_stub(review_lib, monkeypatch):
    lib = review_lib; original = lib["reader"].answer_claims
    monkeypatch.setattr(lib["reader"], "answer_claims", lambda aid: original(aid) * 2)
    with pytest.raises(DuplicateReviewRef): build_snapshot(lib["reader"], lib["rid"], "answer", lib["answer_id"])
    assert lib["conn"].execute("SELECT COUNT(*) FROM owner_review_snapshots").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["answer", "report"])
@pytest.mark.parametrize("case", ["missing", "other_research", "trash", "not_reviewable"])
def test_snapshot_not_found_and_not_reviewable(review_lib, kind, case):
    lib = review_lib; rid, tid = lib["rid"], lib[kind + "_id"]
    if case == "missing": tid = "missing"
    elif case == "other_research": rid = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", None, "en")
    elif case == "trash": lib["store"].trash_research(rid)
    else:
        if kind == "report": lib["conn"].execute("UPDATE reports SET status = 'in_progress' WHERE id = ?", (tid,))
        else: tid = make_answer(lib, status="unverified_draft")
    with pytest.raises(NotReviewable if case == "not_reviewable" else NotFound):
        build_snapshot(lib["reader"], rid, kind, tid)


def test_review_parts_never_truncate_an_oversized_cell_value(review_lib):
    content = snapshot(review_lib)["content"]
    content["cells"][0]["value"] = {"text": "a" * 4000}
    with pytest.raises(ReviewInputTooLarge, match="4000"):
        review_step_input_parts("rvs_SYNTHSNAP01", content, focus="source_support", owner_note=None)


def test_group_parts_allow_only_selected_claims_and_their_dependencies(review_lib):
    saved = snapshot(review_lib)
    parts = review_step_input_parts(saved["id"], saved["content"], focus="source_support", owner_note=None, group_index=2, group_count=2, claim_refs=["abstract.1"])
    assert parts["allowlist"]["claim_refs"] == ["abstract.1"]
    assert parts["allowlist"]["section_refs"] == ["abstract"]
    assert parts["review_input"]["cells"] == []
    assert parts["allowlist"]["passage_ids"] == [review_lib["abstract_passage"]]
    with pytest.raises(ValueError, match="unknown"):
        review_step_input_parts(saved["id"], saved["content"], focus="source_support", owner_note=None, claim_refs=["III.2"])


def test_resolved_finding_stores_source_owned_words_and_snapshot_target(review_lib):
    lib = review_lib; saved = snapshot(lib); payload = step_payload(lib, saved)
    f = finding(payload, evidence=[{"passage_handle": lib["abstract_passage"], "anchor": "synthetic abstract evidence"}])
    result = resolve_finding(saved["content"], payload, f)
    assert result["target"]["record_id"] == saved["content"]["claims"][0]["claim_id"]
    assert result["target"]["text_at_snapshot"] == saved["content"]["claims"][0]["text"]
    assert result["evidence"][0] == {"passage_id": lib["abstract_passage"], "source_version_id": lib["source_id"],
                                    "anchor_text": "SYNTHETIC abstract evidence", "anchor_match": "normalized"}
    assert applied_matches_suggestion(result, " SYNTHETIC\n suggested text. ")
    assert not applied_matches_suggestion(result, "SYNTHETIC unrelated edit.")
    f["evidence"][0]["passage_handle"] = "psg_UNKNOWN0001"
    with pytest.raises(ValueError): resolve_finding(saved["content"], payload, f)


def test_candidate_snapshot_missing_version_is_not_found(review_lib):
    with pytest.raises(NotFound):
        build_snapshot(review_lib["reader"], review_lib["rid"], "candidate", "candidate")
