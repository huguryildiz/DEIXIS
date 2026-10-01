"""SYNTHETIC K1 storage tests; no retrieval, model calls or quote verification."""
from dataclasses import replace
import itertools
import json
import sqlite3
from types import SimpleNamespace

import pytest

from deixis.domain.contracts import GAP_KINDS
from deixis.domain.rules import RevisionConflict
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import links
from deixis.workflow.candidates.hits import merge_and_cut
from deixis.workflow.candidates.store import CandidateStore, CANDIDATE_TABLES, InvalidCandidateInput
from deixis.workflow.store import NotFound
from test_lineage_store import make_library as lineage_library

TEXT = "SYNTHETIC: A bounded scheduling mechanism reduces packet delay."
QUOTE = "SYNTHETIC unlocated quote, stored as supplied"


def make_library(path):
    lib = lineage_library(path)
    lib.candidate_store = CandidateStore(lib.store)
    lib.report = db.new_id("rpt")
    lib.conn.execute(
        "INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at)"
        " VALUES (?, ?, ?, 1, 'draft', 'now', 'now')", (lib.report, lib.rid, lib.run))
    lib.gaps = {}
    for kind in GAP_KINDS:
        id_ = db.new_id("gap")
        lib.conn.execute(
            "INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'now')",
            (id_, lib.report, id_, kind, TEXT, db.dumps({"basis_cell_ids": ["cel_missing"],
             "basis_passage_ids": [lib.passages["a"], "pas_missing"], "basis_claim_keys": ["claim_missing"]}),
             db.dumps({"SYNTHETIC": True})))
        lib.gaps[kind] = id_
    return lib


@pytest.fixture
def lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def state(lib, tables=CANDIDATE_TABLES):
    return {t: sorted((tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")), key=repr) for t in tables}


def owner(lib, **changes):
    return lib.candidate_store.open_from_owner_text(lib.rid, TEXT, **changes)


def version(lib, candidate=None, **changes):
    candidate = candidate or owner(lib)
    research_id = changes.pop("research_id", lib.rid)
    values = dict(claim_statement=TEXT, conditions=["SYNTHETIC bounded traffic"],
                  elements=[{"text": "SYNTHETIC scheduling", "kind": "mechanism"},
                            {"text": "SYNTHETIC packet delay", "kind": "outcome"}],
                  nearest_simple_explanation=None, critical_assumption="SYNTHETIC load",
                  validation_plan="SYNTHETIC check supplied evidence", origin="human_edit", step_input_id=None,
                  expected_version=lib.candidate_store.candidate(candidate["id"])["current_version"])
    return lib.candidate_store.add_version(research_id, candidate["id"], **(values | changes))


def run(lib, kind="kill_search", research_id=None, candidate_id=None, status="completed"):
    id_ = db.new_id("run")
    lib.conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, target_json, created_at, updated_at)"
        " VALUES (?, ?, 1, ?, ?, 'candidate', '{}', ?, 'now', 'now')",
        (id_, research_id or lib.rid, kind, status, db.dumps({"candidate_id": candidate_id})))
    return id_


def start(lib, v=None, **changes):
    v = v or version(lib)
    values = dict(query_block={"setting": ["SYNTHETIC network"], "task": ["scheduling"]},
                  rendered_queries=[], skipped_terms=[], selection={"model": "SYNTHETIC"})
    return lib.candidate_store.start_kill_search(lib.rid, v["id"], run(lib, candidate_id=v["candidate_id"]), **(values | changes))


def provider_record(id_="SYNTHETIC-fresh", abstract=TEXT, **changes):
    return ProviderRecord(**(dict(provider_record_id=id_, title=f"SYNTHETIC source {id_}", authors=[], year=None,
        venue=None, publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=None, abstract=abstract, abstract_origin="provider", identifiers={}, raw={}) | changes))


def query(lib, s, records=None, position=1, **changes):
    return lib.candidate_store.record_query(s["id"], **(dict(position=position, provider="openalex", query_text="SYNTHETIC",
                                status="succeeded", records=records if records is not None else [provider_record()]) | changes))


def with_hits(lib, v=None, records=None, **query_changes):
    s = start(lib, v)
    records = query(lib, s, records=records, **query_changes)
    lib.candidate_store.record_hits(s["id"], merge_and_cut([records]), {r["source_version_id"]: "abstract" for r in records})
    return s, records


def step_input(lib, s):
    step = lib.store.step(s["run_id"], db.new_id("op"), "model:SYNTHETIC")
    id_ = db.new_id("sti")
    lib.store.insert_step_input(step["id"], lib.rid, s["run_id"], 0,
        {"step_input_id": id_, "task_type": "SYNTHETIC", "scope_revision": 1,
         "skill_package_hash": "sha256:SYNTHETIC"}, "base", "developer", "SYNTHETIC", {})
    return id_


def assessment(lib, s, relevance="related", whole=False, passage_id=None, **changes):
    elements = lib.candidate_store.version(s["candidate_version_id"])["elements"]
    relation = {"related": "explicit_support", "unrelated": "no_match_in_supplied_text", "uncertain": "uncertain"}[relevance]
    quote = {"evidence_kind": "passage" if passage_id else "abstract", "passage_id": passage_id, "quote": QUOTE}
    cells = [{"element_id": e["id"], "relation": relation,
              "condition_alignment": "aligned" if relevance == "related" else None,
              "quotes": [quote] if relevance == "related" else []} for e in elements]
    return dict(assessment_state="assessed", work_relevance=relevance, states_whole_claim=whole, note="SYNTHETIC note",
                step_input_id=step_input(lib, s), cells=cells, whole_claim_quotes=[quote] if whole else []) | changes


def publish(lib, s, records, **changes):
    return lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **assessment(lib, s, **changes))


def raw_insert(lib, table, row):
    lib.conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def another_research(lib):
    return lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake-model", "en")


@pytest.mark.parametrize("kind", GAP_KINDS)
def test_each_gap_kind_is_snapshotted_replayed_and_survives_gap_deletion(lib, kind):
    c = lib.candidate_store.open_from_gap(lib.rid, lib.report, lib.gaps[kind])
    assert c["gap_kind"] == kind and c["origin_text"] == TEXT
    gap = lib.conn.execute("SELECT * FROM report_gaps WHERE id = ?", (lib.gaps[kind],)).fetchone()
    assert c["origin_basis_json"] == gap["basis_json"] and c["origin_provenance_json"] == gap["provenance_json"]
    view = json.loads(c["origin_basis_view_json"])
    assert view["basis_passage_ids"][0] == {"id": lib.passages["a"], "text": lib.store.passage(lib.passages["a"])["text"],
                                           "source_version_id": lib.ids["a"]}
    assert view["basis_cell_ids"] == [{"id": "cel_missing", "missing": True}]
    assert view["basis_claim_keys"] == [{"id": "claim_missing", "missing": True}]
    before = state(lib)
    assert lib.candidate_store.open_from_gap(lib.rid, lib.report, lib.gaps[kind]) == c
    assert state(lib) == before
    lib.conn.execute("DELETE FROM report_gaps WHERE id = ?", (lib.gaps[kind],))
    assert lib.candidate_store.candidate(c["id"]) == c


def test_gap_view_resolves_current_cell_and_human_claim_text_and_missing_ids(lib):
    lib.conn.execute("INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES ('col_basis', ?, 0, 'user', 'now')", (lib.tid,))
    lib.conn.execute("INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at)"
                     " VALUES ('cel_basis', ?, 'col_basis', ?, 'now', 'now')", (lib.tid, lib.ids["a"]))
    lib.conn.execute("INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, value_json, created_at)"
                     " VALUES ('crv_basis', 'cel_basis', 'human_edit', 'human', 1, 'not_verified', ?, 'now')", (db.dumps({"text": "SYNTHETIC cell"}),))
    lib.conn.execute("UPDATE evidence_cells SET current_revision_id = 'crv_basis' WHERE id = 'cel_basis'")
    lib.conn.execute("INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
                     " VALUES ('sec_basis', ?, 'IV', 'draft', 1, 'now', 'now')", (lib.report,))
    lib.conn.execute("INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type)"
                     " VALUES ('claim_basis', 'sec_basis', 'SYNTHETIC_key', 1, 1, 'SYNTHETIC old', 'analyst_inference')")
    lib.conn.execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at)"
                     " VALUES ('rcr_basis', 'claim_basis', 'human_edit', 'SYNTHETIC edited', 'now')")
    lib.conn.execute("UPDATE report_claims SET current_revision_id = 'rcr_basis' WHERE id = 'claim_basis'")
    gap = next(iter(lib.gaps.values()))
    lib.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE id = ?",
                     (db.dumps({"basis_cell_ids": ["cel_basis"], "basis_claim_keys": ["SYNTHETIC_key"]}), gap))
    view = json.loads(lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)["origin_basis_view_json"])
    assert view["basis_cell_ids"] == [{"id": "cel_basis", "text": "SYNTHETIC cell"}]
    assert view["basis_claim_keys"] == [{"id": "SYNTHETIC_key", "text": "SYNTHETIC edited"}]


def test_rewritten_gap_creates_another_candidate_and_marks_old_origin_changed(lib):
    gap = next(iter(lib.gaps.values()))
    old = lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)
    lib.conn.execute("UPDATE report_gaps SET text = 'SYNTHETIC rewritten' WHERE id = ?", (gap,))
    new = lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)
    assert new["id"] != old["id"] and new["origin_fingerprint"] != old["origin_fingerprint"]
    assert lib.candidate_store.candidate(old["id"])["origin_changed"] is True
    assert new["origin_changed"] is False


def test_wrong_research_report_and_unknown_gap_kind_are_refused(lib):
    gap = next(iter(lib.gaps.values()))
    for rid, report in ((another_research(lib), lib.report), (lib.rid, "rpt_missing")):
        with pytest.raises(NotFound):
            lib.candidate_store.open_from_gap(rid, report, gap)
    lib.conn.execute("UPDATE report_gaps SET kind = 'SYNTHETIC_unknown' WHERE id = ?", (gap,))
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)


def test_owner_text_replay_rejects_key_reuse_and_invalid_lengths(lib):
    c = owner(lib, idempotency_key="SYNTHETIC-key")
    assert owner(lib, idempotency_key="SYNTHETIC-key") == c
    assert all(c[k] is None for k in ("origin_report_id", "origin_gap_row_id", "gap_kind", "origin_fingerprint"))
    for rid, text in ((lib.rid, "SYNTHETIC changed"), (another_research(lib), TEXT)):
        with pytest.raises(InvalidCandidateInput):
            lib.candidate_store.open_from_owner_text(rid, text, "SYNTHETIC-key")
    for text in (" ", "x" * 2001):
        with pytest.raises(InvalidCandidateInput):
            lib.candidate_store.open_from_owner_text(lib.rid, text)


def test_version_replay_precedes_stale_check_and_rejects_changed_or_foreign_content(lib):
    c = owner(lib)
    one = version(lib, c, idempotency_key="SYNTHETIC-version")
    two = version(lib, c)
    assert [v["version"] for v in lib.candidate_store.versions(c["id"])] == [1, 2]
    assert [e["position"] for e in one["elements"]] == [1, 2]
    assert version(lib, c, expected_version=0, idempotency_key="SYNTHETIC-version") == one
    assert lib.candidate_store.candidate(c["id"])["current_version"] == two["version"]
    with pytest.raises(RevisionConflict):
        version(lib, c, expected_version=0)
    for candidate, changes in ((c, {"claim_statement": "SYNTHETIC changed"}), (owner(lib), {})):
        with pytest.raises(InvalidCandidateInput):
            version(lib, candidate, idempotency_key="SYNTHETIC-version", **changes)
    with pytest.raises(NotFound):
        version(lib, c, research_id=another_research(lib))


@pytest.mark.parametrize("changes", [
    {"elements": [{"text": TEXT, "kind": "mechanism"}]},
    {"elements": [{"text": TEXT, "kind": "mechanism"}] * 7},
    {"claim_statement": " "}, {"conditions": [" "]},
    {"origin": "model_decomposition"}, {"step_input_id": "sti_missing"},
])
def test_invalid_version_shapes_store_nothing(lib, changes):
    c = owner(lib)
    before = state(lib)
    with pytest.raises(InvalidCandidateInput):
        version(lib, c, **changes)
    assert state(lib) == before


def test_model_decomposition_needs_a_stored_step_input_and_keeps_it_on_the_version(lib):
    c = owner(lib)
    s = start(lib)
    sti = step_input(lib, s)
    v = version(lib, c, origin="model_decomposition", step_input_id=sti)
    assert v["origin"] == "model_decomposition" and v["step_input_id"] == sti
    before = state(lib)
    with pytest.raises(InvalidCandidateInput, match="missing"):
        version(lib, c, origin="model_decomposition", step_input_id="sti_missing")
    assert state(lib) == before


def test_ambiguous_report_level_claim_key_is_recorded_missing_in_gap_basis_view(lib):
    for n, section_id in enumerate(("III", "IV")):
        lib.conn.execute("INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
                         " VALUES (?, ?, ?, 'draft', ?, 'now', 'now')", (f"sec_{n}", lib.report, section_id, n))
        lib.conn.execute("INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type)"
                         " VALUES (?, ?, 'SYNTHETIC_key', 1, 1, 'SYNTHETIC ambiguous', 'analyst_inference')",
                         (f"claim_{n}", f"sec_{n}"))
    gap = next(iter(lib.gaps.values()))
    lib.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE id = ?",
                     (db.dumps({"basis_claim_keys": ["SYNTHETIC_key"]}), gap))
    c = lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)
    assert json.loads(c["origin_basis_view_json"])["basis_claim_keys"] == [{"id": "SYNTHETIC_key", "missing": True}]


def test_candidate_changes_emit_exactly_one_event_and_replays_emit_none(lib):
    def event_count():
        return lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'candidate_changed'").fetchone()[0]
    before = event_count()
    c = owner(lib, idempotency_key="SYNTHETIC-event-key")
    assert event_count() == before + 1
    owner(lib, idempotency_key="SYNTHETIC-event-key")
    assert event_count() == before + 1
    v = version(lib, c, idempotency_key="SYNTHETIC-event-version")
    assert event_count() == before + 2
    version(lib, c, idempotency_key="SYNTHETIC-event-version", expected_version=0)
    assert event_count() == before + 2
    s, records = with_hits(lib, v)
    assert event_count() == before + 5  # start, query, merge.
    a = assessment(lib, s)
    lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a)
    assert event_count() == before + 6
    lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a)
    assert event_count() == before + 6
    event = dict(lib.conn.execute("SELECT * FROM events WHERE type = 'candidate_changed' ORDER BY id DESC LIMIT 1").fetchone())
    assert json.loads(event["payload_json"]) == {"candidate_id": c["id"], "change": "assessment_published"}


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
@pytest.mark.parametrize("status", ["queued", "running", "pause_requested"])
def test_candidate_trash_and_restore_refuse_active_targeted_runs(lib, kind, status):
    c = owner(lib)
    id_ = run(lib, kind, candidate_id=c["id"], status=status)
    with pytest.raises(RevisionConflict):
        lib.candidate_store.trash_candidate(lib.rid, c["id"])
    with pytest.raises(RevisionConflict):
        lib.candidate_store.restore_candidate(lib.rid, c["id"])
    lib.conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (id_,))
    lib.candidate_store.trash_candidate(lib.rid, c["id"])
    with pytest.raises(InvalidCandidateInput):
        version(lib, c)
    lib.candidate_store.restore_candidate(lib.rid, c["id"])
    version(lib, c)


def test_candidate_trash_and_restore_leave_versions_searches_and_evidence_identical(lib):
    v = version(lib)
    s, records = with_hits(lib, v)
    publish(lib, s, records, whole=True)
    lib.candidate_store.record_owner_decision(lib.rid, v["id"], "open", "SYNTHETIC reason")
    before = state(lib, CANDIDATE_TABLES[1:])
    lib.candidate_store.trash_candidate(lib.rid, v["candidate_id"])
    assert lib.candidate_store.candidates(lib.rid) == []
    assert len(lib.candidate_store.candidates(lib.rid, True)) == 1
    lib.candidate_store.restore_candidate(lib.rid, v["candidate_id"])
    assert state(lib, CANDIDATE_TABLES[1:]) == before


def test_start_replay_checks_every_frozen_field_and_permits_old_versions(lib):
    c = owner(lib)
    v = version(lib, c)
    version(lib, c)
    s = start(lib, v)
    values = {k: json.loads(s[k + "_json"]) for k in ("query_block", "rendered_queries", "skipped_terms", "selection")}
    assert lib.candidate_store.start_kill_search(lib.rid, v["id"], s["run_id"], **values) == s
    for field in values:
        with pytest.raises(InvalidCandidateInput):
            lib.candidate_store.start_kill_search(lib.rid, v["id"], s["run_id"], **(values | {field: {"changed": True}}))
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.start_kill_search(lib.rid, version(lib, c)["id"], s["run_id"], **values)
    for id_ in (run(lib, "answer"), run(lib, research_id=another_research(lib))):
        with pytest.raises(InvalidCandidateInput):
            lib.candidate_store.start_kill_search(lib.rid, v["id"], id_, **values)


def test_record_query_replay_uses_persisted_order_without_upsert_and_checks_record_content(lib, monkeypatch):
    s = start(lib)
    records = [provider_record("SYNTHETIC-a"), provider_record("SYNTHETIC-b")]
    out = query(lib, s, records)
    query(lib, s, records=[], position=2, status="failed", error_code="SYNTHETIC")
    query(lib, s, records=[], position=3, status="outcome_unknown")
    before = state(lib)
    monkeypatch.setattr(lib.store, "upsert_provider_source", lambda *a: pytest.fail("replay upserted a source"))
    assert query(lib, s, records) == out
    assert lib.candidate_store.query_records(s["id"]) == [out]
    assert state(lib) == before
    for changed in (list(reversed(records)), [replace(records[0], abstract="SYNTHETIC changed"), records[1]]):
        with pytest.raises(InvalidCandidateInput):
            query(lib, s, changed)
    for field, value in (("query_text", "SYNTHETIC changed"), ("provider", "crossref"), ("raw_payload_path", "changed.json"),
                         ("payload_sha256", "changed"), ("error_code", "changed"), ("status", "failed"), ("step_id", "missing")):
        with pytest.raises(InvalidCandidateInput):
            query(lib, s, [] if field == "status" else records, **{field: value})
    assert state(lib) == before


def test_failed_unknown_queries_cannot_have_records_and_merge_cannot_be_repeated_even_when_empty(lib):
    s = start(lib)
    for status in ("failed", "outcome_unknown"):
        with pytest.raises(InvalidCandidateInput):
            query(lib, s, status=status)
    query(lib, s, [])
    lib.candidate_store.record_hits(s["id"], merge_and_cut([[]]), {})
    with pytest.raises(RevisionConflict):
        lib.candidate_store.record_hits(s["id"], merge_and_cut([[]]), {})


@pytest.mark.parametrize("state_", ["running", "paused"])
def test_completed_without_merge_is_refused_when_a_succeeded_query_returned_records(lib, state_):
    s = start(lib)
    records = query(lib, s)
    lib.candidate_store.set_kill_search_state(s["id"], state_)
    before = state(lib, (*CANDIDATE_TABLES, "events"))
    with pytest.raises(RevisionConflict, match="merge"):
        lib.candidate_store.finish_kill_search(s["id"], "completed")
    assert state(lib, (*CANDIDATE_TABLES, "events")) == before
    lib.candidate_store.record_hits(s["id"], merge_and_cut([records]),
                                    {r["source_version_id"]: "abstract" for r in records})
    assert lib.candidate_store.finish_kill_search(s["id"], "completed")["outcome"] == "completed"


@pytest.mark.parametrize("record_empty_merge", [False, True])
def test_zero_result_completed_is_open_with_or_without_an_empty_record_hits_call(lib, record_empty_merge):
    s = start(lib)
    query(lib, s, [])
    if record_empty_merge:
        lib.candidate_store.record_hits(s["id"], merge_and_cut([[]]), {})
    completed = lib.candidate_store.finish_kill_search(s["id"], "completed")
    assert completed["found"] == completed["kept"] == 0
    assert completed["hits_recorded"] == int(record_empty_merge)
    result = lib.candidate_store.candidate_status(s["candidate_version_id"])["computed"]
    assert (result["status"], result["reason"]) == ("open", "no_match_in_assessed_subset")
    assert result["warnings"] == []


@pytest.mark.parametrize("outcome", ["failed", "stopped"])
@pytest.mark.parametrize("state_", ["running", "paused"])
def test_failed_and_stopped_can_finish_without_merge_even_with_query_records(lib, outcome, state_):
    s = start(lib)
    query(lib, s)
    lib.candidate_store.set_kill_search_state(s["id"], state_)
    assert lib.candidate_store.finish_kill_search(s["id"], outcome)["outcome"] == outcome


def test_hand_made_completed_row_with_query_records_and_no_merge_reads_unclassified(lib):
    v = version(lib)
    search_id = db.new_id("kls")
    # Import an inconsistent historical shape with every FK, CHECK and trigger enabled.
    raw_insert(lib, "kill_searches", dict(id=search_id, candidate_version_id=v["id"], run_id=run(lib),
               query_block_json="{}", rendered_queries_json="[]", skipped_terms_json="[]", selection_json="{}",
               outcome="completed", created_at="now"))
    raw_insert(lib, "kill_search_queries", dict(kill_search_id=search_id, position=1, status="succeeded",
               provider="openalex", query_text="SYNTHETIC", record_count=1, records_sha256="SYNTHETIC"))
    raw_insert(lib, "kill_search_query_records", dict(kill_search_id=search_id, position=1, rank=1,
               provider="openalex", source_version_id=lib.ids["a"], work_id=lib.store.source(lib.ids["a"])["work_id"]))
    stored = lib.candidate_store.kill_search(search_id)
    assert stored["hits_recorded"] == stored["found"] == stored["kept"] == 0
    assert not lib.candidate_store.hits(search_id)
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    result = lib.candidate_store.candidate_status(v["id"])["computed"]
    assert (result["status"], result["reason"]) == ("undecided", "unclassified")
    assert result["warnings"] == ["merge_missing"]


def test_record_hits_requires_all_depths_and_exact_persisted_merge_counts(lib):
    s = start(lib)
    records = query(lib, s, [provider_record(f"SYNTHETIC-{n}") for n in range(11)])
    merged = merge_and_cut([records])
    before = state(lib)
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.record_hits(s["id"], merged, {})
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.record_hits(s["id"], merged | {"found": 20}, {r["source_version_id"]: "abstract" for r in records})
    assert state(lib) == before
    lib.candidate_store.record_hits(s["id"], merged, {r["source_version_id"]: "stored_passages" for r in records})
    search = lib.candidate_store.kill_search(s["id"])
    assert (search["found"], search["kept"], search["rank_cut"], search["duplicates"]) == (11, 8, 3, 0)
    assert [h["rank_key"] for h in lib.candidate_store.hits(s["id"])] == list(range(1, 12))
    assert all(h["assessment_state"] == "pending" for h in lib.candidate_store.hits(s["id"])[:8])
    assert all(h["assessment_state"] is None for h in lib.candidate_store.hits(s["id"])[8:])


@pytest.mark.parametrize("relevance", ["related", "unrelated", "uncertain"])
def test_assessed_publication_enforces_relevance_and_keeps_raw_unlocated_quotes(lib, relevance):
    s, records = with_hits(lib)
    result = publish(lib, s, records, relevance=relevance)
    assert result["assessment_state"] == "assessed" and result["work_relevance"] == relevance
    assert len(lib.candidate_store.cells(s["id"])) == 2
    if relevance == "related":
        assert all(e["quote"] == QUOTE for e in lib.candidate_store.evidence(s["id"]))


@pytest.mark.parametrize("state_", ["insufficient_access", "not_assessed_budget"])
def test_unread_publication_has_no_assessment_fields_or_cells(lib, state_):
    s, records = with_hits(lib)
    result = lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], assessment_state=state_)
    assert result["assessment_state"] == state_ and result["step_input_id"] is None and not result["cells"]


@pytest.mark.parametrize("shape", ["missing", "duplicate", "extra", "unrelated_support", "related_no_support",
    "uncertain_no_uncertain", "alignment_missing", "no_match_alignment", "support_without_quote",
    "whole_without_quote", "whole_unrelated", "quote_without_whole", "missing_step", "wrong_source_passage",
    "unread_with_fields"])
def test_every_invalid_publication_shape_stores_nothing(lib, shape):
    s, records = with_hits(lib)
    a = assessment(lib, s)
    if shape == "missing":
        a["cells"].pop()
    elif shape == "duplicate":
        a["cells"][1] = a["cells"][0]
    elif shape == "extra":
        a["cells"].append(a["cells"][0] | {"element_id": "ele_extra"})
    elif shape == "unrelated_support":
        a["work_relevance"] = "unrelated"
    elif shape in ("related_no_support", "no_match_alignment", "whole_unrelated"):
        a["cells"] = [c | {"relation": "no_match_in_supplied_text", "condition_alignment": None, "quotes": []} for c in a["cells"]]
        if shape == "no_match_alignment":
            a["cells"][0]["condition_alignment"] = "aligned"
        if shape == "whole_unrelated":
            a.update(work_relevance="unrelated", states_whole_claim=True,
                     whole_claim_quotes=[{"evidence_kind": "abstract", "passage_id": None, "quote": QUOTE}])
    elif shape == "uncertain_no_uncertain":
        a["work_relevance"] = "uncertain"
    elif shape == "alignment_missing":
        a["cells"][0]["condition_alignment"] = None
    elif shape == "support_without_quote":
        a["cells"][0]["quotes"] = []
    elif shape == "whole_without_quote":
        a["states_whole_claim"] = True
    elif shape == "quote_without_whole":
        a["whole_claim_quotes"] = [{"evidence_kind": "abstract", "passage_id": None, "quote": QUOTE}]
    elif shape == "missing_step":
        a["step_input_id"] = None
    elif shape == "wrong_source_passage":
        a["cells"][0]["quotes"] = [{"evidence_kind": "passage", "passage_id": lib.passages["b"], "quote": QUOTE}]
    else:
        a["assessment_state"] = "insufficient_access"
    before = state(lib)
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a)
    assert state(lib) == before


def test_identical_publication_replays_but_changed_publication_conflicts(lib):
    s, records = with_hits(lib)
    a = assessment(lib, s, whole=True)
    first = lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a)
    before = state(lib)
    assert lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a) == first
    with pytest.raises(RevisionConflict):
        lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **(a | {"note": "SYNTHETIC changed"}))
    assert state(lib) == before


def test_last_evidence_failure_rolls_back_inside_caught_outer_transaction(lib, monkeypatch):
    s, records = with_hits(lib)
    a = assessment(lib, s, whole=True)
    original = lib.candidate_store._insert
    def fail_last(table, row):
        if table == "claim_matrix_evidence" and row["element_id"] is None:
            raise sqlite3.IntegrityError("SYNTHETIC last evidence failure")
        original(table, row)
    monkeypatch.setattr(lib.candidate_store, "_insert", fail_last)
    before = state(lib)
    with db.transaction(lib.conn):
        with pytest.raises(sqlite3.IntegrityError, match="last evidence"):
            lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a)
        lib.conn.execute("INSERT INTO works (id, created_at) VALUES ('wrk_outer', 'now')")
    assert state(lib) == before
    assert lib.conn.execute("SELECT 1 FROM works WHERE id = 'wrk_outer'").fetchone()


@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
def test_terminal_search_refuses_late_query_hits_and_publication_without_any_row_change(lib, outcome):
    s, records = with_hits(lib)
    a = assessment(lib, s)
    lib.candidate_store.set_kill_search_state(s["id"], "paused")
    lib.candidate_store.set_kill_search_state(s["id"], "running")
    lib.candidate_store.finish_kill_search(s["id"], outcome)
    before = state(lib)
    lib.candidate_store.finish_kill_search(s["id"], outcome)
    for action in (
        lambda: query(lib, s),
        lambda: lib.candidate_store.record_hits(s["id"], merge_and_cut([records]), {}),
        lambda: lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], **a),
        lambda: lib.candidate_store.set_kill_search_state(s["id"], "running"),
        lambda: lib.candidate_store.finish_kill_search(s["id"], next(o for o in ("completed", "failed", "stopped") if o != outcome)),
    ):
        with pytest.raises(RevisionConflict):
            action()
    assert state(lib) == before


def test_fresh_source_complete_search_changes_no_protected_corpus_selection_or_reading_rows(lib, monkeypatch):
    v = version(lib)
    for name in ("record_search", "add_search_run", "add_to_corpus", "_corpus_changed"):
        monkeypatch.setattr(lib.store, name, lambda *a, **k: pytest.fail("Forbidden corpus call"))
    monkeypatch.setattr(links, "link_records", lambda *a, **k: pytest.fail("Forbidden linking call"))
    protected = ("corpus_memberships", "candidates", "candidate_hits", "search_runs", "selections",
                 "selection_history", "record_links", "suspected_duplicates")
    before = state(lib, protected)
    research_before = tuple(lib.conn.execute("SELECT selection_revision, updated_at FROM researches WHERE id = ?", (lib.rid,)).fetchone())
    reading_before = state(lib, ("asset_arxiv_versions", "asset_extractions", "source_assets"))
    events_before = [tuple(r) for r in lib.conn.execute("SELECT * FROM events WHERE type <> 'candidate_changed'")]
    original = lib.store.upsert_provider_source
    calls = []
    def upsert(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(lib.store, "upsert_provider_source", upsert)
    s, records = with_hits(lib, v)
    publish(lib, s, records, whole=True)
    lib.candidate_store.finish_kill_search(s["id"], "completed")
    assert len(calls) == 1
    assert state(lib, protected) == before
    assert state(lib, ("asset_arxiv_versions", "asset_extractions", "source_assets")) == reading_before
    assert [tuple(r) for r in lib.conn.execute("SELECT * FROM events WHERE type <> 'candidate_changed'")] == events_before
    assert tuple(lib.conn.execute("SELECT selection_revision, updated_at FROM researches WHERE id = ?", (lib.rid,)).fetchone()) == research_before


@pytest.mark.parametrize("expected", ["not_run", "closed", "narrowed", "undecided", "open"])
def test_candidate_status_uses_stored_rows_for_each_status_and_owner_never_decides_it(lib, expected):
    v = version(lib)
    if expected != "not_run":
        s, records = with_hits(lib, v)
        if expected == "undecided":
            lib.candidate_store.publish_assessment(s["id"], records[0]["source_version_id"], assessment_state="insufficient_access")
        else:
            publish(lib, s, records, relevance="unrelated" if expected == "open" else "related", whole=expected == "closed")
        if expected != "closed":  # Partial running search can already close.
            lib.candidate_store.finish_kill_search(s["id"], "completed")
    before = lib.candidate_store.candidate_status(v["id"])
    assert before["computed"]["status"] == expected
    for status_ in ("closed", "open"):
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], status_, "SYNTHETIC owner reason")
    after = lib.candidate_store.candidate_status(v["id"])
    assert after["computed"] == before["computed"] and after["owner"]["status"] == "open"
    assert len(lib.candidate_store.overrides(v["id"])) == 2
    with pytest.raises(InvalidCandidateInput):
        lib.candidate_store.record_owner_decision(lib.rid, v["id"], "open", " ")


def test_latest_failed_search_hides_older_completed_status_and_versions_never_share_results(lib, monkeypatch):
    monkeypatch.setattr("deixis.workflow.candidates.store.now", lambda: "2026-10-01T00:00:00.000+00:00")
    c = owner(lib)
    v = version(lib, c)
    s, records = with_hits(lib, v)
    publish(lib, s, records, whole=True)
    lib.candidate_store.finish_kill_search(s["id"], "completed")
    later = start(lib, v)
    assert later["created_at"] > s["created_at"]
    lib.candidate_store.finish_kill_search(later["id"], "failed")
    status_ = lib.candidate_store.candidate_status(v["id"])
    assert status_["computed"]["reason"] == "search_incomplete" and status_["previous"]["status"] == "closed"
    v2 = version(lib, c)
    assert lib.candidate_store.candidate_status(v2["id"])["computed"]["status"] == "not_run"


def guard_library(lib):
    s, records = with_hits(lib)
    publish(lib, s, records, whole=True)
    lib.candidate_store.record_owner_decision(lib.rid, s["candidate_version_id"], "closed", "SYNTHETIC reason")
    return s, records


@pytest.mark.parametrize("table", CANDIDATE_TABLES)
@pytest.mark.parametrize("clause", ["replace", "upsert", "explicit_id", "ignore"])
def test_every_candidate_table_refuses_conflicting_inserts_before_conflict_handling(lib, table, clause):
    guard_library(lib)
    row = dict(lib.conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    if table == "research_candidates":
        row["current_version"] = 0
    columns = ", ".join(row)
    values = ", ".join("?" * len(row))
    before = state(lib)
    statement = {
        "replace": f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({values})",
        "ignore": f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({values})",
        "upsert": f"INSERT INTO {table} ({columns}) VALUES ({values}) ON CONFLICT DO UPDATE SET {next(iter(row))} = excluded.{next(iter(row))}",
        "explicit_id": f"INSERT INTO {table} ({columns}) VALUES ({values})",
    }[clause]
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        lib.conn.execute(statement, tuple(row.values()))
    assert state(lib) == before
    with pytest.raises(sqlite3.OperationalError, match="rowid"):
        lib.conn.execute(f"SELECT rowid FROM {table}")


@pytest.mark.parametrize("table", ["research_candidates", "candidate_versions", "claim_elements", "kill_searches", "claim_matrix_cells"])
def test_secondary_unique_key_conflict_cannot_replace_a_different_id(lib, table):
    guard_library(lib)
    row = dict(lib.conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    if table == "research_candidates":
        lib.conn.execute("UPDATE report_gaps SET text = 'SYNTHETIC secondary' WHERE id = ?", (next(iter(lib.gaps.values())),))
        row = lib.candidate_store.open_from_gap(lib.rid, lib.report, next(iter(lib.gaps.values())))
        row.pop("origin_changed")
    row["id"] = db.new_id("SYNTHETIC")
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        raw_insert(lib, table, row)


APPEND_ONLY = ("candidate_versions", "claim_elements", "claim_matrix_cells", "claim_matrix_evidence",
               "candidate_status_overrides", "kill_search_queries", "kill_search_query_records")


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_append_only_rows_refuse_even_noop_updates(lib, table):
    guard_library(lib)
    col = lib.conn.execute(f"PRAGMA table_info({table})").fetchone()["name"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lib.conn.execute(f"UPDATE {table} SET {col} = {col}")


@pytest.mark.parametrize("table", CANDIDATE_TABLES)
def test_delete_guard_requires_owning_research_authorization_and_rejects_table_authorization(lib, table):
    guard_library(lib)
    lib.conn.execute("INSERT INTO table_purge_authorizations VALUES (?)", (lib.tid,))
    with pytest.raises(sqlite3.IntegrityError, match="research purge authorization"):
        lib.conn.execute(f"DELETE FROM {table}")
    lib.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (another_research(lib),))
    with pytest.raises(sqlite3.IntegrityError, match="research purge authorization"):
        lib.conn.execute(f"DELETE FROM {table}")


def test_owning_research_authorization_allows_the_entire_tree_delete_in_dependency_order(lib):
    from deixis.workflow.candidates.store import purge_candidates
    guard_library(lib)
    lib.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (lib.rid,))
    purge_candidates(lib.conn, lib.rid)
    assert all(not rows for rows in state(lib).values())
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def check_base(lib, table):
    s, records = guard_library(lib)
    row = dict(lib.conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    if "id" in row:
        row["id"] = db.new_id("SYNTHETIC")
    if table == "research_candidates":
        row["current_version"] = 0
    elif table == "candidate_versions":
        row["version"] = 2
    elif table == "claim_elements":
        row["position"] = 3
    elif table == "kill_searches":
        row["run_id"] = run(lib)
    elif table == "kill_search_queries":
        row["position"] = 2
    elif table == "kill_search_query_records":
        row["rank"] = 2
    elif table == "kill_search_hits":
        row["source_version_id"] = lib.ids["a"]
    elif table == "claim_matrix_cells":
        h = dict(lib.candidate_store.hits(s["id"])[0], source_version_id=lib.ids["a"])
        raw_insert(lib, "kill_search_hits", h)
        row["source_version_id"] = lib.ids["a"]
    return row


@pytest.mark.parametrize("table,changes", [
    ("research_candidates", {"origin": "report_gap"}),
    ("research_candidates", {"origin": "owner_text", "origin_gap_row_id": "SYNTHETIC"}),
    ("research_candidates", {"origin": "owner_text", "origin_report_id": "SYNTHETIC"}),
    ("research_candidates", {"origin": "owner_text", "gap_kind": "SYNTHETIC"}),
    ("research_candidates", {"origin": "owner_text", "origin_fingerprint": "SYNTHETIC"}),
    ("research_candidates", {"origin": "unknown"}),
    ("candidate_versions", {"origin": "model_decomposition", "step_input_id": None}),
    ("candidate_versions", {"origin": "human_edit", "step_input_id": "SYNTHETIC"}),
    ("candidate_versions", {"origin": "unknown"}), ("candidate_versions", {"claim_statement": " "}),
    ("candidate_versions", {"version": 0}),
    ("claim_elements", {"position": 0}), ("claim_elements", {"kind": "unknown"}), ("claim_elements", {"text": " "}),
    ("kill_searches", {"outcome": "unknown"}), ("kill_searches", {"found": -1}),
    ("kill_searches", {"kept": 9}), ("kill_searches", {"kept": -1}),
    ("kill_searches", {"rank_cut": -1}), ("kill_searches", {"duplicates": -1}),
    ("kill_search_queries", {"status": "unknown"}), ("kill_search_queries", {"record_count": -1}),
    ("kill_search_queries", {"status": "failed", "record_count": 1}),
    ("kill_search_query_records", {"rank": 0}),
    ("kill_search_hits", {"kept": 2}), ("kill_search_hits", {"rank_key": 0}),
    ("kill_search_hits", {"kept": 0}), ("kill_search_hits", {"cut_reason": "rank_cut"}),
    ("kill_search_hits", {"reading_depth": None}), ("kill_search_hits", {"reading_depth": "unknown"}),
    ("kill_search_hits", {"assessment_state": None}), ("kill_search_hits", {"assessment_state": "unknown"}),
    ("kill_search_hits", {"work_relevance": None}), ("kill_search_hits", {"work_relevance": "unknown"}),
    ("kill_search_hits", {"states_whole_claim": None}), ("kill_search_hits", {"states_whole_claim": 2}),
    ("kill_search_hits", {"step_input_id": None}), ("kill_search_hits", {"assessment_state": "pending"}),
    ("claim_matrix_cells", {"relation": "unknown"}), ("claim_matrix_cells", {"condition_alignment": None}),
    ("claim_matrix_cells", {"condition_alignment": "unknown"}),
    ("claim_matrix_cells", {"relation": "no_match_in_supplied_text", "condition_alignment": "aligned"}),
    ("claim_matrix_evidence", {"evidence_kind": "unknown"}), ("claim_matrix_evidence", {"quote": " "}),
    ("claim_matrix_evidence", {"evidence_kind": "passage", "passage_id": None}),
    ("claim_matrix_evidence", {"evidence_kind": "abstract", "passage_id": "SYNTHETIC"}),
    ("candidate_status_overrides", {"status": "unknown"}), ("candidate_status_overrides", {"reason": " "}),
])
def test_sql_checks_refuse_inconsistent_candidate_shapes(lib, table, changes):
    row = check_base(lib, table)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        raw_insert(lib, table, row | changes)


@pytest.mark.parametrize("state_", [None, "pending", "insufficient_access", "not_assessed_budget"])
@pytest.mark.parametrize("fields", [fields for count in range(1, 5) for fields in itertools.combinations(
    ("work_relevance", "states_whole_claim", "note", "step_input_id"), count)])
def test_sql_cut_and_each_non_assessed_state_refuse_every_stray_assessment_field_combination(lib, state_, fields):
    s, _ = with_hits(lib)
    values = {"work_relevance": "related", "states_whole_claim": 0,
              "note": "SYNTHETIC", "step_input_id": step_input(lib, s)}
    base = dict(lib.candidate_store.hits(s["id"])[0], source_version_id=lib.ids["a"], assessment_state=state_)
    if state_ is None:
        base.update(kept=0, cut_reason="rank_cut", reading_depth=None)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        raw_insert(lib, "kill_search_hits", base | {field: values[field] for field in fields})
    raw_insert(lib, "kill_search_hits", base)
    stored = next(h for h in lib.candidate_store.hits(s["id"]) if h["source_version_id"] == lib.ids["a"])
    assert all(stored[field] is None for field in values)


def test_sql_search_run_guard_rejects_other_kind_or_research_and_freezes_columns(lib):
    s = start(lib)
    row = dict(s, id=db.new_id("kls"))
    for id_ in (run(lib, "answer"), run(lib, research_id=another_research(lib))):
        with pytest.raises(sqlite3.IntegrityError, match="mismatch"):
            raw_insert(lib, "kill_searches", row | {"run_id": id_})
    for col in ("id", "candidate_version_id", "run_id", "query_block_json", "rendered_queries_json",
                "skipped_terms_json", "selection_json", "created_at"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            lib.conn.execute(f"UPDATE kill_searches SET {col} = ? WHERE id = ?", ("SYNTHETIC changed", s["id"]))
    lib.candidate_store.set_kill_search_state(s["id"], "paused")
    lib.candidate_store.finish_kill_search(s["id"], "stopped")
    for col, value in (("outcome", "running"), ("outcome", "failed"), ("found", 1), ("kept", 1), ("rank_cut", 1), ("duplicates", 1)):
        with pytest.raises(sqlite3.IntegrityError, match="terminal|frozen"):
            lib.conn.execute(f"UPDATE kill_searches SET {col} = ? WHERE id = ?", (value, s["id"]))


def test_sql_hit_assessment_moves_once_and_identity_is_frozen(lib):
    s, records = with_hits(lib)
    sti = step_input(lib, s)
    for col in ("source_version_id", "kill_search_id", "work_id", "rank_key", "kept", "cut_reason", "reading_depth"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            lib.conn.execute(f"UPDATE kill_search_hits SET {col} = ?, assessment_state = 'assessed',"
                             " work_relevance = 'unrelated', states_whole_claim = 0, step_input_id = ?", ("SYNTHETIC", sti))
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute("UPDATE kill_search_hits SET note = 'SYNTHETIC'")
    publish(lib, s, records)
    for col in ("note", "assessment_state", "work_relevance"):
        with pytest.raises(sqlite3.IntegrityError, match="once"):
            lib.conn.execute(f"UPDATE kill_search_hits SET {col} = {col}")


def test_candidate_identity_and_pointer_need_next_existing_own_version(lib):
    c = owner(lib)
    for col in ("id", "research_id", "origin", "origin_report_id", "origin_gap_row_id", "gap_kind", "origin_text",
                "origin_basis_json", "origin_basis_view_json", "origin_provenance_json", "origin_fingerprint", "idempotency_key", "created_at"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            lib.conn.execute(f"UPDATE research_candidates SET {col} = ? WHERE id = ?", ("SYNTHETIC", c["id"]))
    for value in (1, 2, -1):
        with pytest.raises(sqlite3.IntegrityError):
            lib.conn.execute("UPDATE research_candidates SET current_version = ? WHERE id = ?", (value, c["id"]))
    foreign = version(lib)
    with pytest.raises(sqlite3.IntegrityError):
        lib.conn.execute("UPDATE research_candidates SET current_version = 1 WHERE id = ?", (c["id"],))
    one = version(lib, c)
    for value in (0, 1, 3):
        with pytest.raises(sqlite3.IntegrityError):
            lib.conn.execute("UPDATE research_candidates SET current_version = ? WHERE id = ?", (value, c["id"]))
    clone = dict(c, id=db.new_id("rcd"), current_version=1)
    clone.pop("origin_changed")
    with pytest.raises(sqlite3.IntegrityError, match="version zero"):
        raw_insert(lib, "research_candidates", clone)
    assert foreign["candidate_id"] != one["candidate_id"]


def test_cell_integrity_rejects_foreign_version_and_not_kept_or_not_assessed_source(lib):
    s, records = with_hits(lib)
    e = lib.candidate_store.version(s["candidate_version_id"])["elements"][0]["id"]
    base = dict(id=db.new_id("cmx"), kill_search_id=s["id"], element_id=e,
                source_version_id=records[0]["source_version_id"], relation="uncertain", condition_alignment=None)
    with pytest.raises(sqlite3.IntegrityError, match="kept assessed"):
        raw_insert(lib, "claim_matrix_cells", base)
    publish(lib, s, records)
    foreign = version(lib)["elements"][0]["id"]
    for changes in ({"element_id": foreign}, {"source_version_id": lib.ids["b"]}):
        with pytest.raises(sqlite3.IntegrityError, match="kept assessed"):
            raw_insert(lib, "claim_matrix_cells", base | changes)
    cut = dict(lib.candidate_store.hits(s["id"])[0], source_version_id=lib.ids["b"], kept=0,
               cut_reason="rank_cut", reading_depth=None, assessment_state=None,
               work_relevance=None, states_whole_claim=None, note=None, step_input_id=None)
    raw_insert(lib, "kill_search_hits", cut)
    with pytest.raises(sqlite3.IntegrityError, match="kept assessed"):
        raw_insert(lib, "claim_matrix_cells", base | {"source_version_id": lib.ids["b"]})


def test_evidence_integrity_rejects_cell_scope_mismatch_wrong_passage_and_unstated_whole_claim(lib):
    s, records = with_hits(lib)
    publish(lib, s, records)
    cell = lib.candidate_store.cells(s["id"])[0]
    base = dict(id=db.new_id("cmx"), kill_search_id=s["id"], source_version_id=records[0]["source_version_id"],
                element_id=cell["element_id"], matrix_cell_id=cell["id"], evidence_kind="abstract", passage_id=None, quote=QUOTE)
    for changes in ({"kill_search_id": start(lib)["id"]}, {"source_version_id": lib.ids["b"]},
                    {"element_id": "ele_other"}, {"element_id": None, "matrix_cell_id": None},
                    {"evidence_kind": "passage", "passage_id": lib.passages["b"]}):
        with pytest.raises(sqlite3.IntegrityError, match="scope or passage"):
            raw_insert(lib, "claim_matrix_evidence", base | changes)
    for changes in ({"element_id": None}, {"matrix_cell_id": None}):
        with pytest.raises(sqlite3.IntegrityError):
            raw_insert(lib, "claim_matrix_evidence", base | changes)
    other_s, other_records = with_hits(lib, records=[provider_record("SYNTHETIC-other-whole")])
    publish(lib, other_s, other_records, whole=True)
    raw_insert(lib, "claim_matrix_evidence", base | {"kill_search_id": other_s["id"],
               "source_version_id": other_records[0]["source_version_id"], "element_id": None, "matrix_cell_id": None})


def kill_search_for_other_research(lib, rid, records=None, payload=None, write_hits=True):
    other = SimpleNamespace(**vars(lib))
    other.rid = rid
    v = version(other)
    s = start(other, v)
    result = query(other, s, records=records, raw_payload_path=payload)
    if write_hits:
        other.candidate_store.record_hits(s["id"], merge_and_cut([result]), {r["source_version_id"]: "abstract" for r in result})
    return other, s, result


def test_purge_research_removes_candidate_tree_before_runs_steps_and_passages_and_keeps_other_research_hits(lib):
    s, records = with_hits(lib)
    publish(lib, s, records, whole=True)
    lib.candidate_store.record_owner_decision(lib.rid, s["candidate_version_id"], "closed", "SYNTHETIC")
    other, _, shared = kill_search_for_other_research(lib, another_research(lib))
    assert shared[0]["source_version_id"] == records[0]["source_version_id"]
    extra = query(lib, start(lib), [provider_record("SYNTHETIC-hit-only")])
    # Interrupted before hits: query-record ownership is enough to find this orphan.
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (records[0]["source_version_id"],)).fetchone()
    assert not lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (extra[0]["source_version_id"],)).fetchone()
    assert {c["research_id"] for c in lib.candidate_store.candidates(other.rid)} == {other.rid}
    assert not lib.conn.execute("SELECT 1 FROM runs WHERE research_id = ?", (lib.rid,)).fetchone()
    assert not lib.conn.execute("SELECT 1 FROM step_inputs WHERE research_id = ?", (lib.rid,)).fetchone()
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_interruption_after_record_query_before_record_hits_still_purges_its_sources(lib):
    s = start(lib)
    records = query(lib, s)
    assert not lib.candidate_store.hits(s["id"])
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert all(not rows for rows in state(lib).values())
    assert not lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (records[0]["source_version_id"],)).fetchone()


def test_purge_research_removes_hit_only_sources_and_returns_only_unreferenced_query_payloads(lib):
    s, records = with_hits(lib, raw_payload_path="SYNTHETIC-exclusive.json")
    publish(lib, s, records)
    lib.store.trash_research(lib.rid)
    _, payloads = lib.store.purge_research(lib.rid)
    assert payloads == ["SYNTHETIC-exclusive.json"]
    assert all(not rows for rows in state(lib).values())
    assert not lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (records[0]["source_version_id"],)).fetchone()
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def search_payload_reference(lib, rid, payload):
    id_ = run(lib, "discovery", research_id=rid)
    step = lib.store.step(id_, db.new_id("op"), "provider:SYNTHETIC")
    raw_insert(lib, "search_runs", dict(id=db.new_id("srn"), research_id=rid, run_id=id_, step_id=step["id"],
               provider="openalex", query_text="SYNTHETIC", request_description="SYNTHETIC", access_mode="public",
               status="zero_results", result_count=0, page_limit=20, raw_payload_path=payload, retrieved_at="now"))


def test_purge_research_keeps_payload_named_by_another_research_search_run(lib):
    s = start(lib)
    query(lib, s, [], status="failed", raw_payload_path="SYNTHETIC-shared.json")
    search_payload_reference(lib, another_research(lib), "SYNTHETIC-shared.json")
    lib.store.trash_research(lib.rid)
    assert lib.store.purge_research(lib.rid)[1] == []


def test_purge_sources_keeps_payload_file_named_by_live_kill_search_query_of_other_research(lib, tmp_path):
    payload = tmp_path / "SYNTHETIC-shared.json"
    payload.write_text("SYNTHETIC payload")
    lib.conn.execute("UPDATE source_versions SET provider_payload_path = ? WHERE id = ?", (payload.name, lib.ids["a"]))
    other, s, _ = kill_search_for_other_research(lib, another_research(lib), records=[], payload=payload.name)
    before = state(lib)
    lib.conn.execute("DELETE FROM table_rows WHERE source_version_id = ?", (lib.ids["a"],))
    lib.store.remove_sources(lib.rid, [lib.ids["a"]], "SYNTHETIC removed")
    _, _, orphan_payloads = lib.store.purge_sources(lib.rid, [lib.ids["a"]])
    for name in orphan_payloads:
        (tmp_path / name).unlink()
    assert orphan_payloads == [] and payload.is_file()
    assert state(lib) == before and other.candidate_store.queries(s["id"])[0]["raw_payload_path"] == payload.name


def test_payload_only_named_by_surviving_abstract_passage_is_retained_and_backed_up(lib, tmp_path):
    from deixis.config import Settings
    from deixis.storage.backup import _referenced_files, create_backup
    settings = Settings(data_dir=tmp_path)
    settings.payloads_dir.mkdir()
    payload = settings.payloads_dir / "SYNTHETIC-abstract-only.json"
    payload.write_text("SYNTHETIC payload")
    # Existing upload source has no abstract: upsert fills it without a provider_payload_path.
    svid = lib.ids["a"]
    lib.conn.execute("DELETE FROM passages_fts WHERE rowid IN (SELECT rowid FROM passages WHERE source_version_id = ?)", (svid,))
    lib.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (svid,))
    lib.conn.execute("INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                     " VALUES (?, 'openalex', 'SYNTHETIC-existing', 'openalex', 'now')", (svid,))
    rid = another_research(lib)
    other, s, _ = kill_search_for_other_research(lib, rid, [provider_record("SYNTHETIC-existing")], payload.name, write_hits=False)
    assert lib.conn.execute("SELECT provider_payload_path FROM source_versions WHERE id = ?", (svid,)).fetchone()[0] is None
    other.store.trash_research(rid)
    _, orphan_payloads = other.store.purge_research(rid)
    assert orphan_payloads == []
    assert payload.name in _referenced_files(lib.conn)["provider-payloads"]
    assert not lib.conn.execute("SELECT 1 FROM kill_search_queries WHERE raw_payload_path = ?", (payload.name,)).fetchone()
    backup = create_backup(settings, tmp_path / "backups")
    assert (backup / "provider-payloads" / payload.name).read_text() == "SYNTHETIC payload"
    # The source-purge filter independently protects a passage-owned reference too.
    lib.conn.execute("UPDATE source_versions SET provider_payload_path = ? WHERE id = ?", (payload.name, lib.ids["b"]))
    lib.conn.execute("DELETE FROM table_rows WHERE source_version_id = ?", (lib.ids["b"],))
    lib.store.remove_sources(lib.rid, [lib.ids["b"]], "SYNTHETIC removal")
    assert lib.store.purge_sources(lib.rid, [lib.ids["b"]])[2] == []


@pytest.mark.parametrize("last_purge", ["research", "sources"])
def test_two_step_purge_keeps_abstract_payload_after_b_then_removes_it_after_a_and_never_collects_pdf_chars(tmp_path, last_purge):
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.config import Settings
    from fakes import FakeAdapter
    from test_api_flow import create, session

    settings = Settings(data_dir=tmp_path / "api-data")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid_a = create(client, source_scope="attached", question="SYNTHETIC research A?")
        rid_b = create(client, source_scope="attached", question="SYNTHETIC research B?")
        store = app.state.store
        svid, _ = store.upsert_provider_source("openalex", provider_record(abstract=None), None)
        store.add_to_corpus(rid_a, svid, "search")
        settings.payloads_dir.mkdir(exist_ok=True)
        payload = settings.payloads_dir / "SYNTHETIC-abstract-only.json"
        payload.write_text("SYNTHETIC payload")
        local = SimpleNamespace(conn=store.conn, store=store, rid=rid_b, candidate_store=CandidateStore(store))
        s = start(local)
        records = query(local, s, raw_payload_path=payload.name)
        assert records[0]["source_version_id"] == svid
        assert store.source(svid)["provider_payload_path"] is None
        abstract = next(p for p in store.passages_for(svid) if p["kind"] == "abstract")
        assert abstract["payload_ref"] == payload.name
        # A sentinel file proves a PDF character range never enters the file-cleanup list.
        chars = settings.payloads_dir / "chars:0-50"
        chars.write_text("SYNTHETIC sentinel, not a PDF payload")
        asset_id = db.new_id("ast")
        store.conn.execute(
            "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
            " retrieved_at, origin, extraction_status) VALUES (?, ?, 'SYNTHETIC', 1, 'application/pdf',"
            " 'SYNTHETIC.pdf', 'now', 'user_upload', 'succeeded')", (asset_id, svid))
        pdf_passage = store._insert_passage(svid, asset_id, "pdf_page", 1, None, None,
                                           chars.name, "SYNTHETIC", "SYNTHETIC PDF page")
        store.trash_research(rid_b)
        response = client.delete(f"/api/trash/{rid_b}")
        assert response.status_code == 200, response.text
        assert response.json()["files_not_removed"] == []
        assert payload.is_file() and chars.is_file()
        assert not store.conn.execute("SELECT 1 FROM kill_search_queries WHERE raw_payload_path = ?", (payload.name,)).fetchone()
        assert not store.conn.execute("SELECT 1 FROM source_versions WHERE provider_payload_path = ?", (payload.name,)).fetchone()
        assert store.passage(abstract["id"])["payload_ref"] == payload.name
        if last_purge == "research":
            store.trash_research(rid_a)
            response = client.delete(f"/api/trash/{rid_a}")
        else:
            store.remove_sources(rid_a, [svid], "SYNTHETIC removal")
            response = client.post(f"/api/researches/{rid_a}/sources/purge", json={"source_version_ids": [svid]})
        assert response.status_code == 200, response.text
        assert response.json()["files_not_removed"] == []
        assert not payload.exists()
        assert chars.is_file()
        assert not store.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (svid,)).fetchone()
        assert not store.conn.execute("SELECT 1 FROM passages WHERE id IN (?, ?)", (abstract["id"], pdf_passage)).fetchone()
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_purge_sources_keeps_query_only_and_hit_only_sources_without_deleting_candidate_rows(lib):
    other, s, records = kill_search_for_other_research(lib, another_research(lib), write_hits=False)
    svid = records[0]["source_version_id"]
    lib.store.add_to_corpus(lib.rid, svid, "search")
    lib.store.remove_sources(lib.rid, [svid], "SYNTHETIC removed")
    before = state(lib)
    assert lib.store.cited_source_versions([svid]) == set()
    assert lib.store.purge_sources(lib.rid, [svid])[0] == [svid]
    assert state(lib) == before
    assert lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (svid,)).fetchone()
    # Hit-only lower-level record proves the hit branch independently of query-record ownership.
    raw_insert(lib, "kill_search_hits", dict(kill_search_id=s["id"], source_version_id=lib.ids["b"],
               work_id=lib.store.source(lib.ids["b"])["work_id"], rank_key=1, kept=1,
               reading_depth="abstract", assessment_state="pending"))
    lib.conn.execute("DELETE FROM table_rows WHERE source_version_id = ?", (lib.ids["b"],))
    lib.store.remove_sources(lib.rid, [lib.ids["b"]], "SYNTHETIC removed")
    before = state(lib)
    assert lib.store.purge_sources(lib.rid, [lib.ids["b"]])[0] == [lib.ids["b"]]
    assert state(lib) == before
    assert lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (lib.ids["b"],)).fetchone()


def test_cited_source_versions_sees_assessment_cells_and_quotes_but_not_pending_hits(lib):
    s, records = with_hits(lib)
    svid = records[0]["source_version_id"]
    assert lib.store.cited_source_versions([svid]) == set()
    publish(lib, s, records, relevance="unrelated")
    assert not lib.candidate_store.evidence(s["id"])
    assert lib.store.cited_source_versions([svid]) == {svid}  # Isolate the cell branch.
    # Whole-claim evidence also protects a source; the integrity rule ties it to the same assessed hit.
    s2, records2 = with_hits(lib, records=[provider_record("SYNTHETIC-second")])
    publish(lib, s2, records2, whole=True)
    assert lib.store.cited_source_versions([records2[0]["source_version_id"]]) == {records2[0]["source_version_id"]}


def test_research_trash_and_restore_leave_every_candidate_table_row_identical(lib):
    guard_library(lib)
    before = state(lib)
    lib.store.trash_research(lib.rid)
    assert state(lib) == before
    lib.store.restore_research(lib.rid)
    assert state(lib) == before


def attach_asset(lib, svid):
    id_ = db.new_id("ast")
    raw_insert(lib, "source_assets", dict(id=id_, source_version_id=svid, sha256="a" * 64, byte_size=10,
               media_type="application/pdf", storage_path="SYNTHETIC.pdf", retrieved_at="now",
               origin="user_upload", extraction_status="succeeded"))
    passage = lib.store._insert_passage(svid, id_, "pdf_page", 1, None, "pdf_extraction", "chars:0-120", None, TEXT)
    return id_, passage


def test_research_cites_asset_and_asset_impact_count_only_candidate_passage_quotes(lib):
    s, records = with_hits(lib)
    asset, passage = attach_asset(lib, records[0]["source_version_id"])
    publish(lib, s, records, whole=True, passage_id=passage)
    assert lib.store.research_cites_asset(lib.rid, asset)
    assert not lib.store.research_cites_asset(another_research(lib), asset)
    assert lib.store.asset_impact(asset)["candidate_quotes"] == 3
    assert lib.store.asset_impact(asset)["quotes"] == lib.store.asset_impact(asset)["cells"] == 0


def test_existing_pdf_remove_and_replace_routes_preserve_candidate_only_citation_access(lib, tmp_path):
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.config import Settings
    from fakes import FakeAdapter
    from helpers import make_pdf
    from test_api_flow import create, session
    app = create_app(Settings(data_dir=tmp_path / "api-data"), adapters={"fake": FakeAdapter()}, start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("SYNTHETIC.pdf", make_pdf([TEXT]), "application/pdf")})
        assert response.status_code == 201, response.text
        store = app.state.store
        asset = dict(store.conn.execute("SELECT * FROM source_assets").fetchone())
        passage = next(p for p in store.passages_for(asset["source_version_id"]) if p["asset_id"] == asset["id"])
        local = SimpleNamespace(conn=store.conn, store=store, rid=rid, candidate_store=CandidateStore(store))
        s, records = with_hits(local, records=[provider_record("SYNTHETIC-api")])
        # Query source and uploaded source are distinct; use a kept hit for the uploaded source.
        raw_insert(local, "kill_search_hits", dict(kill_search_id=s["id"], source_version_id=asset["source_version_id"],
                   work_id=store.source(asset["source_version_id"])["work_id"], rank_key=2, kept=1,
                   reading_depth="stored_passages", assessment_state="pending"))
        local.candidate_store.publish_assessment(s["id"], asset["source_version_id"], **assessment(local, s, passage_id=passage["id"]))
        assert not store.conn.execute("SELECT * FROM evidence_links").fetchall()
        assert not store.conn.execute("SELECT * FROM cell_evidence_links").fetchall()
        assert store.research_cites_asset(rid, asset["id"])
        base = f"/api/researches/{rid}/sources/{asset['source_version_id']}/assets/{asset['id']}"
        assert client.delete(base).status_code == 200
        assert client.get(f"/api/researches/{rid}/assets/{asset['id']}").status_code == 404
        assert store.research_cites_asset(rid, asset["id"])
        assert client.post(base + "/restore").status_code == 200
        replacement = client.put(base, files={"file": ("SYNTHETIC-new.pdf", make_pdf(["SYNTHETIC replacement"]), "application/pdf")})
        assert replacement.status_code == 200, replacement.text
        assert client.get(f"/api/researches/{rid}/assets/{asset['id']}").status_code == 200
        assert store.research_cites_asset(rid, asset["id"])


@pytest.mark.parametrize("value,options,text", [
    ({"text": "SYNTHETIC text"}, None, "SYNTHETIC text"),
    ({"number": 8, "unit": "SYNTHETIC unit", "as_stated": None}, None, "8 SYNTHETIC unit"),
    ({"answer": "yes"}, None, "yes"),
    ({"option_ids": ["o1", "missing"]}, db.dumps([{"id": "o1", "label": "SYNTHETIC option"}]), "SYNTHETIC option, missing"),
    (None, None, ""),
])
def test_gap_snapshot_formats_stored_cell_values_without_a_view_model(value, options, text):
    assert CandidateStore._cell_text(value, options) == text


@pytest.mark.parametrize("held_by", ["kill_search_query_records", "kill_search_hits"])
def test_purge_research_shared_source_check_independently_respects_queries_and_hits(lib, held_by):
    s, records = with_hits(lib)
    rid = another_research(lib)
    other, other_search, _ = kill_search_for_other_research(lib, rid)
    removed_table = "kill_search_hits" if held_by == "kill_search_query_records" else "kill_search_query_records"
    lib.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (rid,))
    lib.conn.execute(f"DELETE FROM {removed_table} WHERE kill_search_id = ?", (other_search["id"],))
    lib.conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (rid,))
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (records[0]["source_version_id"],)).fetchone()
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_purge_retains_shared_library_sibling_versions_and_their_payload_as_the_documented_limit(lib):
    from deixis.providers.common import OtherVersion
    from deixis.storage.backup import _referenced_files
    s = start(lib)
    record = provider_record(other_versions=[OtherVersion("SYNTHETIC-other", "https://synthetic.invalid/file", None, None)])
    primary = query(lib, s, [record], raw_payload_path="SYNTHETIC-sibling.json")[0]["source_version_id"]
    sibling = lib.store.other_version_ids("openalex", record)[0]
    lib.store.trash_research(lib.rid)
    assert lib.store.purge_research(lib.rid)[1] == []
    assert not lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (primary,)).fetchone()
    assert lib.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (sibling,)).fetchone()
    assert "SYNTHETIC-sibling.json" in _referenced_files(lib.conn)["provider-payloads"]
