"""SYNTHETIC candidate and evidence changes, compared to snapshot-time tokens."""

import copy

import pytest

from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.review.stale import stale_reasons
from tests.review.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, search, add_version


def test_newer_candidate_version(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib); version = add_version(lib)
    assert stale_reasons(lib["reader"], saved) == [{"code": "newer_candidate_version", "version": version["version"]}]


def test_newer_kill_search(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib); latest = search(lib, outcome="paused")
    assert stale_reasons(lib["reader"], saved) == [{"code": "newer_kill_search", "kill_search_id": latest["id"]}]


@pytest.mark.parametrize("field", ["hit", "cell", "evidence", "count", "outcome"])
def test_kill_search_changed(candidate_lib, monkeypatch, field):
    lib = candidate_lib; saved = snapshot(lib); reader = lib["reader"]
    original, search_read = reader.kill_search_rows, reader.kill_search
    def rows(kid):
        rows = copy.deepcopy(original(kid))
        if field == "hit": rows["hits"][0]["note"] += " SYNTHETIC change"
        if field == "cell": rows["cells"][0]["note"] += " SYNTHETIC change"
        if field == "evidence": rows["evidence"][0]["quote"] += " SYNTHETIC change"
        return rows
    def changed(kid):
        row = search_read(kid)
        if field == "count": row["found"] += 1
        if field == "outcome": row["outcome"] = "failed"
        return row
    monkeypatch.setattr(reader, "kill_search_rows", rows)
    monkeypatch.setattr(reader, "kill_search", changed)
    assert stale_reasons(reader, saved) == [{"code": "kill_search_changed"}]


def test_owner_status_changed(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    CandidateStore(lib["store"]).record_owner_decision(lib["rid"], lib["candidate_version_id"], "undecided", "SYNTHETIC changed reason")
    assert stale_reasons(lib["reader"], saved) == [{"code": "owner_status_changed", "status": "undecided"}]


def test_later_version_override_does_not_change_reviewed_version_owner_token(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib); version = add_version(lib)
    CandidateStore(lib["store"]).record_owner_decision(lib["rid"], version["id"], "undecided", "SYNTHETIC later override")
    assert stale_reasons(lib["reader"], saved) == [{"code": "newer_candidate_version", "version": 2}]


def test_scope_revised_for_candidate(candidate_lib):
    lib = candidate_lib; saved = snapshot(lib)
    lib["store"].revise_scope(lib["rid"], lib["store"].research(lib["rid"])["version"], "SYNTHETIC revised scope", None)
    assert stale_reasons(lib["reader"], saved) == [{"code": "scope_revised"}]


@pytest.mark.parametrize("target", ["element", "source"])
@pytest.mark.parametrize("reason", ["passage_changed", "asset_changed", "extraction_changed", "evidence_missing", "pdf_replaced", "pdf_removed", "text_superseded"])
def test_candidate_evidence_reason_names_element_or_source(candidate_lib, monkeypatch, reason, target):
    lib = candidate_lib; snapshot(lib)  # Reach the old B8 refusal before new reader methods are used.
    reader = lib["reader"]
    content = snapshot(lib)["content"]
    source = content["matrix"][0 if target == "element" else 1]["source_id"]
    passage = next(p for p in content["passages"] if p["source_id"] == source and p["locator"]["kind"] == "pdf_page")
    pid = passage["passage_id"]
    saved = snapshot(lib)
    original = reader.evidence_dependency
    def changed(id_):
        dep = original(id_)
        if id_ != pid: return dep
        if reason == "evidence_missing": return None
        if reason == "passage_changed": dep["text"] += " SYNTHETIC changed"
        if reason == "asset_changed": dep["asset_sha256"] = "b" * 64
        if reason == "extraction_changed": dep["current_extraction_id_at_snapshot"] = "ext_SYNTHNEXT001"
        if reason in {"pdf_replaced", "pdf_removed", "text_superseded"}: dep["evidence_status"] = reason
        return dep
    monkeypatch.setattr(reader, "evidence_dependency", changed)
    expected = {"kind": "candidate_element", "ref": "e1"} if target == "element" else {"kind": "candidate_source", "ref": source}
    rows = stale_reasons(reader, saved)
    assert len(rows) == 1 and rows[0]["code"] == reason
    assert rows[0]["targets"] == [expected] and rows[0]["target_ref"] == expected


def test_candidate_model_package_provider_changes_do_not_make_copy_stale(candidate_lib, monkeypatch):
    from deixis.domain import skill
    lib = candidate_lib; saved = snapshot(lib)
    monkeypatch.setattr(skill, "package_hash", lambda: "sha256:" + "e" * 64)
    lib["conn"].execute("UPDATE source_versions SET title = 'SYNTHETIC metadata update'")
    assert stale_reasons(lib["reader"], saved) == []
