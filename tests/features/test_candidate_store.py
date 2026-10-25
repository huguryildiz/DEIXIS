"""SYNTHETIC K1 storage tests; no retrieval, model calls or quote verification."""
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace

import pytest

from deixis.domain.contracts import GAP_KINDS
from deixis.domain.rules import RevisionConflict
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import links
from deixis.workflow.candidates_hits import merge_and_cut
from deixis.workflow.candidates_store import CandidateStore, CANDIDATE_TABLES, InvalidCandidateInput
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


def test_rewritten_gap_creates_another_candidate_and_marks_old_origin_changed(lib):
    gap = next(iter(lib.gaps.values()))
    old = lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)
    lib.conn.execute("UPDATE report_gaps SET text = 'SYNTHETIC rewritten' WHERE id = ?", (gap,))
    new = lib.candidate_store.open_from_gap(lib.rid, lib.report, gap)
    assert new["id"] != old["id"] and new["origin_fingerprint"] != old["origin_fingerprint"]
    assert lib.candidate_store.candidate(old["id"])["origin_changed"] is True
    assert new["origin_changed"] is False


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


def join(lib, keep, drop):
    with db.transaction(lib.conn):
        lib.store._join_works(keep["work_id"], drop["work_id"])


@pytest.mark.parametrize("shape", ["support_without_quote", "wrong_source_passage"])
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


@pytest.mark.parametrize("outcome", ["stopped"])
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


@pytest.mark.parametrize("expected", ["closed", "open"])
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


def guard_library(lib):
    s, records = with_hits(lib)
    publish(lib, s, records, whole=True)
    lib.candidate_store.record_owner_decision(lib.rid, s["candidate_version_id"], "closed", "SYNTHETIC reason")
    return s, records


@pytest.mark.parametrize("table", ["claim_matrix_evidence"])
@pytest.mark.parametrize("clause", ["replace", "upsert"])
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


@pytest.mark.parametrize("table", ["claim_matrix_evidence"])
def test_append_only_rows_refuse_even_noop_updates(lib, table):
    guard_library(lib)
    col = lib.conn.execute(f"PRAGMA table_info({table})").fetchone()["name"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lib.conn.execute(f"UPDATE {table} SET {col} = {col}")


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


def test_research_trash_and_restore_leave_every_candidate_table_row_identical(lib):
    guard_library(lib)
    before = state(lib)
    lib.store.trash_research(lib.rid)
    assert state(lib) == before
    lib.store.restore_research(lib.rid)
    assert state(lib) == before


