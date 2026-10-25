"""Direct SQLite guard tests and append-only owner decisions on synthetic records."""

import copy
import json
import sqlite3
import pytest
from deixis.storage import db
from deixis.workflow.features.review.review_store import applied_matches_suggestion, resolve_finding, TARGET_KINDS, FOCUSES, DECISIONS
from review_helpers import report_with_sections, review_lib, stored_review, snapshot, review_run, step_payload, rows
from test_report_claim_links import edit, claim
from jsonschema import Draft202012Validator
from deixis.domain import contracts
from fakes import valid_response
from review_helpers import si, output, finding
from deixis.domain.canonical import canonical_json
from deixis.workflow.features.review.review_snapshot import build_snapshot, review_step_input_parts, NotReviewable
from deixis.workflow.features.review.review_store import NotFound, resolve_finding, applied_matches_suggestion
from review_helpers import report_with_sections, review_lib, snapshot, step_payload, make_answer, finding
from review_helpers import report_with_sections, review_lib, stored_review, all_rows
import hashlib
from deixis.config import Settings
from deixis.domain.canonical import canonical_json
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.features.review.review_store import SnapshotDependencyUnreadable
from review_helpers import report_with_sections, review_lib, stored_review, snapshot, make_answer, rows, all_rows
from test_review import asset_evidence
import re
from deixis.workflow.features.review.review_store import TARGET_KINDS, FOCUSES, DECISIONS


TABLES = ("owner_review_snapshots", "owner_reviews", "owner_review_findings", "owner_review_decisions")


def populated(lib):
    saved, review, payload, fid = stored_review(lib)
    lib["reviews"].add_decision(fid, "deferred")
    return saved, review, payload, fid


@pytest.mark.parametrize("blank", [" \t\r\n"])
@pytest.mark.parametrize("field", ["owner_note"])
def test_sql_boundary_refuses_blank_notes_and_dismissal_reasons(review_lib, blank, field):
    lib = review_lib; saved, _, _, fid = stored_review(lib)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        if field == "owner_note":
            run = review_run(lib)
            lib["conn"].execute("INSERT INTO owner_reviews (id, research_id, snapshot_id, run_id, focus, owner_note, requested_connection, created_at)"
                                " VALUES (?, ?, ?, ?, 'source_support', ?, 'fake', 'now')",
                                (db.new_id("orv"), lib["rid"], saved["id"], run, blank))
        else:
            lib["conn"].execute("INSERT INTO owner_review_decisions (id, finding_id, ordinal, decision, reason, applied_ref, created_at) VALUES (?, ?, 1, 'dismissed', ?, NULL, 'now')",
                                (db.new_id("ord"), fid, blank))


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("operation", ["update"])
def test_immutable_rows_and_frozen_review_identity_refuse_mutation(review_lib, table, operation):
    lib = review_lib; populated(lib); before = rows(lib["conn"], table)
    sql = f"DELETE FROM {table}" if operation == "delete" else f"UPDATE {table} SET id = 'changed'"
    with pytest.raises(sqlite3.IntegrityError): lib["conn"].execute(sql)
    assert rows(lib["conn"], table) == before


@pytest.mark.parametrize("decision,reason,applied", [("dismissed", None, None)])
def test_decision_rules(review_lib, decision, reason, applied):
    lib = review_lib; _, _, _, fid = stored_review(lib)
    with pytest.raises(ValueError): lib["reviews"].add_decision(fid, decision, reason, applied)
    assert lib["reviews"].decisions(fid) == []


@pytest.mark.parametrize("case", ["suggestion"])
def test_later_human_revision_is_recorded_without_claiming_editor_origin(review_lib, case):
    lib = review_lib; saved, review, _, fid = stored_review(lib)
    target = saved["content"]["claims"][0]
    request = {"link_ids": []} if case == "citations_only" else {"text": "SYNTHETIC suggested text." if case == "suggestion" else "SYNTHETIC unrelated human text."}
    revision = edit(lib, key=target["claim_ref"], **request)
    decision = lib["reviews"].add_decision(fid, "accepted", applied_ref=revision)
    assert decision["applied_ref"] == revision
    text = lib["conn"].execute("SELECT text FROM report_claim_revisions WHERE id = ?", (revision,)).fetchone()[0]
    assert applied_matches_suggestion(lib["reviews"].findings(review["id"])[0]["finding"], text) == (case == "suggestion")


def codes(step_input, result):
    return {i.code for i in contracts.validate_model_output(step_input, result).issues}


@pytest.mark.parametrize("wire", [True])
def test_owner_review_schema_is_closed_and_strict(wire):
    schema = contracts.step_output_schema("owner_review") if wire else contracts.load_schema("OwnerReview")
    Draft202012Validator.check_schema(schema)
    assert contracts.strict_compatibility_issues(contracts.step_output_schema("owner_review")) == []
    draft = output(); draft["verdict"] = "invented"
    assert "schema_invalid" in codes(si(), draft)


@pytest.mark.parametrize("change,code", [({"evidence": [{"passage_handle": "psg_UNKNOWN0001", "anchor": "SYNTHETIC."}]}, "review_passage_not_allowed"), ({"evidence": [{"passage_handle": "psg_SYNA1abs01", "anchor": "No such words."}]}, "review_anchor_not_in_passage")])
def test_each_semantic_rejection(change, code):
    step = si(); draft = output(step); draft["findings"] = [finding(step, **change)]
    assert code in codes(step, draft)


@pytest.mark.parametrize("array", ["findings"])
def test_one_changed_word_is_fuzzy_and_refused(array):
    step = si(); step["passages"][0]["text"] = "SYNTHETIC: The scheduling mechanism decreases delay under bounded arrivals."
    quote = "SYNTHETIC: The scheduling mechanism increases delay under bounded arrivals."
    assert contracts.locate_anchor(quote, step["passages"][0]["text"]).kind == "fuzzy"
    item = finding(step, evidence=[{"passage_handle": step["passages"][0]["passage_id"], "anchor": quote}])
    if array == "supported_points":
        item = {k: item[k] for k in ("target_ref", "evidence")}
    draft = output(step); draft[array] = [item]
    assert "review_anchor_not_exact" in codes(step, draft)


@pytest.mark.parametrize("array", ["findings"])
@pytest.mark.parametrize("length", [11, 12])
def test_review_anchor_minimum_length(array, length):
    step = si(); draft = output(step)
    item = finding(step, kind="unsupported", evidence=[{
        "passage_handle": step["passages"][0]["passage_id"],
        "anchor": step["passages"][0]["text"][:length],
    }])
    draft[array] = [item if array == "findings" else {k: item[k] for k in ("target_ref", "evidence")}]
    assert ("schema_invalid" in codes(step, draft)) == (length < 12)


@pytest.mark.parametrize("kind", ["unsupported", "other"])
def test_evidence_requirement_per_kind(kind):
    step = si(); draft = output(step); draft["findings"] = [finding(step, kind=kind, evidence=[])]
    assert ("finding_without_evidence" in codes(step, draft)) == (kind in {"unsupported", "partially_supported", "overstated"})


@pytest.mark.parametrize("target_kind", ["answer"])
def test_handles_roundtrip_and_zero_padding(target_kind):
    step = si(target_kind); shown = contracts.with_citation_handles(step)
    assert contracts.check_step_input(shown) == []
    for field in ("claim_refs", "section_refs", "element_refs"):
        assert shown["allowlist"][field] == step["allowlist"][field]
    raw = json.loads(valid_response(shown))
    raw["supported_points"][0]["evidence"][0]["passage_handle"] = "psg_P00000001"
    resolved = contracts.resolve_citation_handles(step, json.dumps(raw))
    assert codes(step, resolved) == set()
    raw["supported_points"][0]["evidence"][0]["passage_handle"] = "srv_S00000001"
    assert "review_passage_not_allowed" in codes(step, contracts.resolve_citation_handles(step, json.dumps(raw)))


@pytest.mark.parametrize("kind", ["answer"])
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


@pytest.mark.parametrize("kind", ["answer"])
@pytest.mark.parametrize("case", ["other_research"])
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


@pytest.mark.parametrize("form", ["UPSERT"])
def test_decision_request_key_refuses_conflicting_insert_replace_upsert_recursive_triggers_off(review_lib, form):
    lib = review_lib
    _, review, payload, fid = stored_review(lib)
    old = lib["reviews"].add_decision(fid, "deferred", idempotency_key="SYNTHETIC-key", request_hash="0" * 64)
    conn = lib["conn"]
    conn.execute("PRAGMA recursive_triggers = OFF")
    before = all_rows(conn)["owner_review_decisions"]
    new = old | {"id": "ord_ANOTHER0001", "ordinal": 2, "decision": "accepted", "reason": "SYNTHETIC different reason", "request_hash": "1" * 64}
    sql = ("INSERT" if form == "UPSERT" else form) + f" INTO owner_review_decisions ({','.join(new)}) VALUES ({','.join('?' for _ in new)})"
    if form == "UPSERT":
        sql += " ON CONFLICT(idempotency_key) DO UPDATE SET id = excluded.id, decision = excluded.decision"
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        conn.execute(sql, tuple(new.values()))
    assert all_rows(conn)["owner_review_decisions"] == before


def remove_existing_citation_protection(lib):
    conn = lib["conn"]
    # Use the existing purge authorization for immutable cell evidence; do not drop guards.
    conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (lib["rid"],))
    conn.execute("UPDATE evidence_cells SET current_revision_id = NULL")
    conn.execute("DELETE FROM evidence_links")
    conn.execute("DELETE FROM report_citation_links")
    conn.execute("DELETE FROM cell_evidence_links")
    conn.execute("DELETE FROM cell_revisions")
    conn.execute("DELETE FROM evidence_cells")
    conn.execute("DELETE FROM table_rows")
    conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (lib["rid"],))
    assert all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in
               ("evidence_links", "report_citation_links", "evidence_cells", "table_rows", "lineage_links", "claim_matrix_cells"))


def cleanup(paths, settings):
    # Store returns orphan paths. The API/CLI caller owns physical file deletion.
    for path in paths:
        (settings.papers_dir / path).unlink()


def test_backup_roundtrip_preserves_four_tables_old_pdf_and_both_payload_routes(review_lib, tmp_path):
    from deixis.documents.pdf import Extraction, PageText, chunk_page
    from helpers import make_pdf
    lib = review_lib; settings = Settings(data_dir=tmp_path); settings.papers_dir.mkdir(); settings.payloads_dir.mkdir()
    asset, _, data, sha = asset_evidence(lib)
    (settings.papers_dir / "SYNTHETIC.pdf").write_bytes(data)
    provider_file, abstract_file = "SYNTHETIC-provider.json", "SYNTHETIC-abstract.json"
    (settings.payloads_dir / provider_file).write_text('{"SYNTHETIC":"provider"}')
    (settings.payloads_dir / abstract_file).write_text('{"SYNTHETIC":"abstract"}')
    lib["conn"].execute("UPDATE source_versions SET provider_payload_path = ? WHERE id = ?", (provider_file, lib["source_id"]))
    pid = lib["store"]._insert_passage(lib["source_id"], None, "abstract", None, None, "synthetic", abstract_file, None, "SYNTHETIC payload abstract.")
    lib["conn"].execute("INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
        " SELECT ?, id, ?, ?, ?, 'SYNTHETIC payload abstract', 'exact' FROM report_claims WHERE claim_key = 'III.1'",
        (db.new_id("rln"), pid, lib["source_id"], lib["report_input_id"]))
    saved, review, _, fid = stored_review(lib)
    lib["reviews"].add_decision(fid, "dismissed", "SYNTHETIC owner reason")
    # Keep a snapshot's old asset after the user replaces the PDF.
    lib["conn"].execute("UPDATE source_assets SET removed_at = 'now', removal_reason = 'replaced' WHERE id = ?", (asset,))
    new_data = make_pdf(["SYNTHETIC replacement PDF."]); new_sha = hashlib.sha256(new_data).hexdigest()
    (settings.papers_dir / "SYNTHETIC-replacement.pdf").write_bytes(new_data)
    lib["store"].add_asset_with_pages(lib["source_id"], new_sha, len(new_data), "SYNTHETIC-replacement.pdf", "user_upload", None, None,
        Extraction("succeeded", 1, [PageText(1, None, "SYNTHETIC replacement PDF.")]), "synthetic-v2", chunk_page)
    before = {t: rows(lib["conn"], t) for t in TABLES}
    destination = create_backup(settings, tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored")
    restore_backup(destination, restored)
    conn = db.connect(restored.db_path)
    try:
        assert {t: rows(conn, t) for t in TABLES} == before
        assert hashlib.sha256((restored.papers_dir / "SYNTHETIC.pdf").read_bytes()).hexdigest() == sha
        assert hashlib.sha256((restored.papers_dir / "SYNTHETIC-replacement.pdf").read_bytes()).hexdigest() == new_sha
        for name in (provider_file, abstract_file):
            assert hashlib.sha256((restored.payloads_dir / name).read_bytes()).hexdigest() == hashlib.sha256((settings.payloads_dir / name).read_bytes()).hexdigest()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT content_json FROM owner_review_snapshots WHERE id = ?", (saved["id"],)).fetchone()[0] == saved["content_json"]
    finally: conn.close()


@pytest.mark.parametrize("case", ["unparsable"])
def test_unreadable_snapshot_stops_purge_without_deleting_any_row(review_lib, case):
    lib = review_lib; saved = snapshot(lib); remove_existing_citation_protection(lib)
    lib["store"].remove_sources(lib["rid"], [lib["source_id"]], "SYNTHETIC removed")
    content = copy.deepcopy(saved["content"])
    if case == "version": content["version"] = 2
    elif case == "manifest_shape": content["evidence_manifest"] = [{"source_version_id": lib["source_id"]}]
    elif case == "sources_shape": content["sources"] = "malformed"
    raw = "{" if case == "unparsable" else canonical_json(content)
    lib["conn"].execute("INSERT INTO owner_review_snapshots VALUES (?, ?, 'answer', ?, ?, ?, '{}', 'now')",
                        (db.new_id("rvs"), lib["rid"], lib["answer_id"], raw, "a" * 64))
    before = all_rows(lib["conn"])
    with pytest.raises(SnapshotDependencyUnreadable): lib["store"].purge_sources(lib["rid"], [lib["source_id"]])
    assert all_rows(lib["conn"]) == before


def test_python_vocabularies_equal_sql_checks(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    try:
        for table, column, values in (("owner_review_snapshots", "target_kind", TARGET_KINDS), ("owner_reviews", "focus", FOCUSES), ("owner_review_decisions", "decision", DECISIONS)):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            assert tuple(re.findall(r"'([^']+)'", re.search(rf'{column} IN \(([^)]+)\)', sql).group(1))) == values
    finally: conn.close()
