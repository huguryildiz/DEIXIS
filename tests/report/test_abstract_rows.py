"""D114: works read from their abstracts only join a table made from the research, and its report, with a note.

A work joins when it passed the abstract stage and its full text could not be obtained, nobody decided it, and no
version of it is still being judged or has text beyond its abstract. Records and model outputs are SYNTHETIC (scripted
FakeAdapter); passing shows workflow behavior, not reading quality.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db, upgrades
from deixis.storage.db import new_id, now, transaction
from deixis.workflow import table_rows, table_sources
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.report import assembly, export_text, selection
from deixis.workflow.report.review_methodology import abstract_rows_sentence
from deixis.workflow.report.snapshot import build_snapshot, countable_row_ids, included_table_rows
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore, report_ready
from fakes import FakeAdapter, valid_response
from test_evidence_tables import PACKET_SIZE
from test_table_extraction import add_pdf

ABSTRACT = "SYNTHETIC abstract: packets of 64 bytes were evaluated."


def make_library(path, responder=valid_response):
    conn = db.connect(path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    included = store.create_upload_source("A SYNTHETIC included study")
    add_pdf(store, included, ["SYNTHETIC page one: packets of 128 bytes minimize energy per bit."], "1" * 64)
    store.add_to_corpus(rid, included, "user_upload", selection_state="included", selection_origin="user")
    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=path / "data", port=8765), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    return SimpleNamespace(conn=conn, store=store, rid=rid, included=included, tables=TableStore(store),
                           decisions=DecisionStore(store), adapter=adapter, flow=flow)


def abstract_work(lib, title="B SYNTHETIC abstract-only study", codes=("runs_agree_candidate", "no_fulltext"),
                  text=ABSTRACT, abstract=True):
    time.sleep(0.003)  # decision and row times have millisecond resolution
    svid = lib.store.create_upload_source(title)
    if abstract:
        lib.store._insert_passage(svid, None, "abstract", None, None, "provider", None, None, text)
    lib.store.add_to_corpus(lib.rid, svid, "user_upload")
    for code in codes:
        lib.decisions.record(lib.rid, svid, code)
    return svid


def other_version(lib, svid, *, abstract=True, title="B SYNTHETIC preprint"):
    other = new_id("srv")
    with transaction(lib.conn):
        lib.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                         " VALUES (?, ?, ?, 'provider', 'submittedVersion', ?)",
                         (other, lib.store.source(svid)["work_id"], title, now()))
        if abstract:
            lib.store._insert_passage(other, None, "abstract", None, None, "provider", None, None, ABSTRACT)
    lib.store.add_to_corpus(lib.rid, other, "search", candidate=False)
    return other


def select(lib, svid, state):
    version = lib.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                               (lib.rid, svid)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, svid, state, version, "SYNTHETIC reason")


def members(lib):
    return set(table_sources.abstract_works(lib.store, lib.rid).values())


def execute(lib, run):
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def new_table(lib):
    tid = lib.tables.create_table(lib.rid, "Packets", None, None, None)
    lib.tables.add_column(lib.rid, tid, PACKET_SIZE, 1, None)
    return tid


def version(lib, tid):
    return lib.tables.table_view(lib.rid, tid)["table"]["version"]


# ---- who is an abstract-only work ---------------------------------------------------------------------------------

@pytest.mark.parametrize("codes", [("runs_agree_candidate", "no_fulltext"), ("blocks_in_title", "text_unreadable"),
                                   ("runs_disagree_kept_as_candidate",)])
def test_a_work_that_passed_the_abstract_stage_without_full_text_is_abstract_only(tmp_path, codes):
    lib = make_library(tmp_path)
    svid = abstract_work(lib, codes=codes)
    assert members(lib) == {svid}


@pytest.mark.parametrize("codes", [
    ("runs_agree_candidate", "criterion_absent"),       # the full text excluded it
    ("runs_agree_out_of_scope",),                        # the abstract stage excluded it
    ("runs_agree_candidate", "not_read_yet"),           # its text waits for reading
    ("runs_agree_candidate", "fulltext_runs_disagree"),  # a person decides it
    ("runs_agree_candidate", "part_without_evidence"),
    ("runs_agree_candidate", "pdf_identity_unconfirmed"),
    ("abstract_not_found", "no_fulltext"),              # never passed the abstract stage
    ("runs_agree_unresolved", "no_fulltext"),
    ("runs_agree_candidate", "human_not_sure"),         # a person's decision
])
def test_works_still_judged_excluded_or_decided_by_a_person_are_not_abstract_only(tmp_path, codes):
    lib = make_library(tmp_path)
    abstract_work(lib, codes=codes)
    assert members(lib) == set()


@pytest.mark.parametrize("state", ["pending", "excluded", "included"])
def test_a_selection_the_user_set_stands(tmp_path, state):
    lib = make_library(tmp_path)
    svid = abstract_work(lib)
    select(lib, svid, state)
    assert members(lib) == set()


def test_another_version_still_being_judged_or_with_text_keeps_the_work_out(tmp_path):
    lib = make_library(tmp_path)
    svid = abstract_work(lib)
    other = other_version(lib, svid)
    assert members(lib) == {svid}
    lib.decisions.record(lib.rid, other, "fulltext_runs_disagree")  # work_outcome would still pick the head's no_fulltext
    assert members(lib) == set()

    lib2 = make_library(tmp_path / "b")
    head = abstract_work(lib2)
    add_pdf(lib2.store, other_version(lib2, head), ["SYNTHETIC preprint page."], "2" * 64)
    assert members(lib2) == set()


def test_a_work_without_any_abstract_is_not_a_row_and_one_with_text_only_on_another_version_uses_that(tmp_path):
    lib = make_library(tmp_path)
    abstract_work(lib, abstract=False)
    assert members(lib) == set()

    lib2 = make_library(tmp_path / "b")
    head = abstract_work(lib2, abstract=False)
    other = other_version(lib2, head)
    # The real answer-version selector (D48) names the head itself here (no version has PDF text); the abstract on the
    # other version still stands for the work (Sol review of b97547a5, finding 3).
    assert lib2.store.answer_versions(lib2.rid)[head] == head
    assert members(lib2) == {other}


def test_a_stale_candidate_after_a_criterion_change_does_not_count(tmp_path):
    lib = make_library(tmp_path)
    abstract_work(lib)
    lib.conn.execute("UPDATE stage_decisions SET scope_revision = scope_revision - 1")
    assert members(lib) == set()


# ---- tables and the D63 sweep ---------------------------------------------------------------------------------------

def test_a_new_table_holds_the_included_and_the_abstract_only_sources_and_marks_them(tmp_path):
    lib = make_library(tmp_path)
    abstract = abstract_work(lib)
    excluded = abstract_work(lib, "C SYNTHETIC excluded", codes=("runs_agree_candidate", "criterion_absent"))
    tid = new_table(lib)
    assert table_sources.follows(lib.store, tid) == table_sources.FOLLOWS_TABLE_SOURCES
    view = lib.tables.table_view(lib.rid, tid)
    rows = {row["source_version_id"]: row for row in view["rows"]}
    assert set(rows) == {lib.included, abstract} and excluded not in rows
    assert rows[abstract]["report_membership"] == "abstract_only" and rows[abstract]["selection_state"] == "pending"
    assert rows[lib.included]["report_membership"] == "included"
    assert report_ready(lib.store, lib.rid, tid)["rows"] == 2

    # A table made before D114 keeps the included sources only.
    old = lib.tables.create_table(lib.rid, "Old", None, None, None)
    lib.conn.execute("UPDATE evidence_tables SET follows_included = 1 WHERE id = ?", (old,))
    assert included_table_rows(lib.store, lib.rid, old) == [lib.included]
    assert table_sources.new_abstract_rows(lib.store, lib.rid, old) == []


def test_the_study_table_starts_from_abstract_only_sources_alone(tmp_path):
    from deixis.workflow import report_pipeline
    lib = make_library(tmp_path)
    select(lib, lib.included, "excluded")
    abstract_work(lib)
    run = report_pipeline.start(lib.store, lib.rid, "synthetic")
    assert run["target"]["pipeline"]["included"] == 1


def test_the_sweep_adds_a_later_abstract_only_work_once_by_work_and_keeps_rows_that_leave(tmp_path):
    lib = make_library(tmp_path)
    tid = new_table(lib)
    late = abstract_work(lib, codes=("runs_agree_candidate",))
    assert table_rows.add_rows(lib.store) == {tid: [late]}
    assert lib.conn.execute("SELECT added_by FROM table_rows WHERE table_id = ? AND source_version_id = ?",
                            (tid, late)).fetchone()[0] == "included_later"
    # A new head of the same work adds no second row; the old row stays the work's row in the report.
    other_version(lib, late, title="B SYNTHETIC published version")
    lib.conn.execute("UPDATE source_versions SET version_label = 'publishedVersion', doi = '10.1/x' WHERE id IN"
                     " (SELECT id FROM source_versions WHERE title = 'B SYNTHETIC published version')")
    lib.decisions.record(lib.rid, late, "no_fulltext")
    assert table_rows.add_rows(lib.store) == {}
    assert table_sources.membership(lib.store, lib.rid, tid).get(late) == "abstract_only"
    # A PDF arrives: the row stays, marked as not in the report.
    add_pdf(lib.store, late, ["SYNTHETIC late page."], "3" * 64)
    lib.decisions.record(lib.rid, late, "not_read_yet")
    rows = {r["source_version_id"]: r for r in lib.tables.table_view(lib.rid, tid)["rows"]}
    assert rows[late]["report_membership"] is None and late not in included_table_rows(lib.store, lib.rid, tid)
    # A reading that includes it brings it back as included.
    lib.decisions.record(lib.rid, late, "all_parts_verified")
    lib.decisions.derive_selection(lib.rid, lib.store.source(late)["work_id"])
    assert table_sources.membership(lib.store, lib.rid, tid).get(late) == "included"


def test_the_fill_skips_a_source_the_person_excluded_meanwhile(tmp_path):
    lib = make_library(tmp_path)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    run = {"research_id": lib.rid, "target": {"included_only": True, "table_id": tid}}
    assert ResearchFlow._left_out(SimpleNamespace(store=lib.store), run, abstract) is False
    select(lib, abstract, "excluded")
    assert ResearchFlow._left_out(SimpleNamespace(store=lib.store), run, abstract) is True


def test_an_abstract_only_row_fills_from_its_abstract_and_quotes_must_be_in_it(tmp_path):
    broken = {}

    def respond(si):
        draft = json.loads(valid_response(si))
        if broken.get("quote") and any(p["text"] == ABSTRACT for p in si["passages"]):
            for answer in draft["cells"]:
                answer["evidence"][0]["quote"] = broken["quote"]
        if broken.get("absent") and any(p["text"] == ABSTRACT for p in si["passages"]):
            for answer in draft["cells"]:
                answer.update(state="not_found_in_inspected_scope", value=None, evidence=[])
        return json.dumps(draft)

    lib = make_library(tmp_path, respond)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    run = lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None, included_only=True)
    assert execute(lib, run)["status"] == "completed"
    cid = lib.tables.target_columns(lib.rid, tid)[0]["id"]
    current = lib.tables.cell_view(lib.rid, tid, cid, abstract)["current"]
    assert current["reading_depth"] == "abstract" and current["state"] == "value"
    assert [e["kind"] for e in current["evidence"]] == ["abstract"]
    assert current["evidence"][0]["anchor_text"] in ABSTRACT

    # A quote from another source's PDF page is not in the abstract: it is never stored as verified evidence.
    broken["quote"] = "SYNTHETIC page one: packets of 128 bytes minimize energy per bit."
    rerun = lib.tables.request_recheck(lib.rid, tid, cid, abstract, lib.tables.cell_view(lib.rid, tid, cid, abstract)["version"], None)
    assert execute(lib, rerun)["status"] == "completed"
    after = lib.tables.cell_view(lib.rid, tid, cid, abstract)
    proposal = after["pending_proposal"]
    assert proposal["output_status"] == "unverified_draft" and all(e["anchor_text"] is None for e in proposal["evidence"])
    assert after["current"]["evidence"][0]["anchor_text"] in ABSTRACT  # the verified value stays as it was

    # A column the abstract does not address is `not_found_in_inspected_scope`, never a guess.
    broken.clear()
    broken["absent"] = True
    lib2_tid = new_table(lib)
    run2 = lib.tables.request_fill(lib.rid, lib2_tid, None, False, version(lib, lib2_tid), None, included_only=True)
    execute(lib, run2)
    cid2 = lib.tables.target_columns(lib.rid, lib2_tid)[0]["id"]
    assert lib.tables.cell_view(lib.rid, lib2_tid, cid2, abstract)["current"]["state"] == "not_found_in_inspected_scope"


def test_known_limit_a_value_the_quote_does_not_entail_passes_the_anchor_check(tmp_path):
    """Anchors confine quotes to the abstract; they do not show the value follows from the quote. A value inventing a
    method detail beside a real abstract sentence is accepted by code: the live sample measures this, tests cannot."""
    def respond(si):
        draft = json.loads(valid_response(si))
        for answer in draft["cells"]:
            answer["value"] = {"number": 64, "unit": "byte", "as_stated": "64 bytes, chosen by a SYNTHETIC genetic algorithm"}
        return json.dumps(draft)

    lib = make_library(tmp_path, respond)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    execute(lib, lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None, included_only=True))
    cid = lib.tables.target_columns(lib.rid, tid)[0]["id"]
    current = lib.tables.cell_view(lib.rid, tid, cid, abstract)["current"]
    assert current["state"] == "value" and current["reading_depth"] == "abstract"


def test_the_sweep_adds_a_work_whose_pdf_was_removed_on_its_next_look(tmp_path):
    """Removing a file changes no other record the sweep's cache key read (Sol review of b97547a5, finding 2)."""
    lib = make_library(tmp_path)
    svid = abstract_work(lib)
    asset = add_pdf(lib.store, svid, ["SYNTHETIC page of a wrong file."], "5" * 64)
    tid = new_table(lib)
    assert table_rows.add_rows(lib.store) == {}
    lib.store.remove_asset(lib.rid, svid, asset)
    assert members(lib) == {svid}
    assert table_rows.add_rows(lib.store) == {tid: [svid]}


# ---- the report -----------------------------------------------------------------------------------------------------

def filled(tmp_path):
    lib = make_library(tmp_path)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    execute(lib, lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None, included_only=True))
    return lib, abstract, tid


def test_the_snapshot_freezes_membership_and_the_abstract_and_counts_take_included_rows_only(tmp_path):
    lib, abstract, tid = filled(tmp_path)
    snap = build_snapshot(lib.store, lib.rid, tid)
    rows = {row["source_version_id"]: row for row in snap["rows"]}
    assert rows[abstract]["membership"] == "abstract_only" and rows[lib.included]["membership"] == "included"
    abstract_passage = lib.store.passages_for(abstract)[0]["id"]
    assert rows[abstract]["passage_ids"] == [abstract_passage] and "passage_ids" not in rows[lib.included]
    assert snap["abstract_rows"] == [abstract] and snap["corpus"]["included"] == 1
    assert [m["source_version_id"] for m in snap["basis"]["abstract_members"]] == [abstract]
    assert countable_row_ids(snap) == [lib.included]

    column = snap["columns"][0]["column_id"]
    context = {"source_ids": countable_row_ids(snap), "column_ids": [column], "cells": selection.usable_cells(snap)}
    two_of_two = {"numerator_source_ids": [abstract], "denominator_source_ids": [abstract], "column_id": column}
    codes = {i.code for i in contracts.report_count_issues("1 of 1 included sources", two_of_two, context)}
    assert "count_member_not_in_snapshot" in codes
    ok = {"numerator_source_ids": [lib.included], "denominator_source_ids": [lib.included], "column_id": column}
    assert "count_member_not_in_snapshot" not in {
        i.code for i in contracts.report_count_issues("1 of 1 included sources", ok, context)}


def test_a_row_filled_from_a_pdf_that_was_then_removed_reports_only_its_abstract(tmp_path):
    """Sol review of b97547a5, finding 1: a cell filled from a PDF keeps that PDF's quote and depth in its revision.
    Once the file is removed the row is abstract-only again; the snapshot keeps its cells inside the frozen abstract."""
    def quote_the_pdf(si):  # the scripted reader quotes the PDF page when it was given one
        if si.get("passages"):
            si = si | {"passages": sorted(si["passages"], key=lambda p: "PDF page" not in p["text"])}
        return valid_response(si)

    lib = make_library(tmp_path, quote_the_pdf)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    asset = add_pdf(lib.store, abstract, ["SYNTHETIC page one: packets of 64 bytes were evaluated on a PDF page."], "6" * 64)
    execute(lib, lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None))
    cid = lib.tables.target_columns(lib.rid, tid)[0]["id"]
    filled_cell = lib.tables.cell_view(lib.rid, tid, cid, abstract)["current"]
    assert filled_cell["reading_depth"] in ("selected_sections", "full_text")
    assert {e["kind"] for e in filled_cell["evidence"]} == {"pdf_page"}
    lib.store.remove_asset(lib.rid, abstract, asset)

    snap = build_snapshot(lib.store, lib.rid, tid)
    row = next(r for r in snap["rows"] if r["source_version_id"] == abstract)
    frozen = set(row["passage_ids"])
    assert row["membership"] == "abstract_only" and row["reading_depth"] in (None, "abstract")
    cells = [c for c in snap["cells"] if c["source_version_id"] == abstract]
    assert cells and all(e["passage_id"] in frozen for c in cells for e in c["evidence"])
    assert all(c["reading_depth"] in (None, "metadata", "abstract") for c in cells)
    assert snap["basis"]["full_text"] == 1 and snap["basis"]["abstract_only"] == 1
    chosen = selection.select_evidence(lib.store, snap, "IV", {"glossary": [], "axes": []}, [])
    assert all(p["id"] in frozen for p in chosen["passages"] if p["source_version_id"] == abstract)
    assert all(e["passage_id"] in frozen for c in chosen["cells"] if c["source_version_id"] == abstract
               for e in c.get("evidence", []))


def test_a_cell_that_lost_a_pdf_link_is_not_verified_even_when_an_abstract_link_survives(tmp_path):
    """Sol review round 2, finding 1: a value quoted from the abstract and a PDF page keeps only the abstract quote
    once the PDF is removed, and that quote need not carry the value. Such a cell is not verified evidence."""
    pdf_text = "SYNTHETIC page one: packets were 128 bytes on a PDF page."

    def quote_both(si):
        draft = json.loads(valid_response(si))
        both = [p for p in si.get("passages", []) if p["text"] in (ABSTRACT, pdf_text)]
        if len(both) == 2:
            for answer in draft["cells"]:
                answer["evidence"] = [{"passage_id": p["passage_id"], "quote": " ".join(p["text"].split())} for p in both]
        return json.dumps(draft)

    lib = make_library(tmp_path, quote_both)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    asset = add_pdf(lib.store, abstract, [pdf_text], "7" * 64)
    execute(lib, lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None))
    cid = lib.tables.target_columns(lib.rid, tid)[0]["id"]
    assert {e["kind"] for e in lib.tables.cell_view(lib.rid, tid, cid, abstract)["current"]["evidence"]} == {"abstract", "pdf_page"}
    lib.store.remove_asset(lib.rid, abstract, asset)

    snap = build_snapshot(lib.store, lib.rid, tid)
    cell = next(c for c in snap["cells"] if c["source_version_id"] == abstract)
    assert cell["state"] == "not_verified" and cell["evidence"] == [] and cell["value"] is not None
    assert cell not in selection.usable_cells(snap)
    assert snap["basis"]["cells_unverified"] == 1
    chosen = selection.select_evidence(lib.store, snap, "IV", {"glossary": [], "axes": []}, [])
    assert all(c["source_version_id"] != abstract for c in chosen["cells"])


def test_an_existing_row_without_an_abstract_does_not_stand_for_an_abstract_only_work(tmp_path):
    """Sol review round 2, finding 2: a table row of a version without an abstract is not the work's abstract-only
    row; the version that holds the abstract is added and stands for it, so the snapshot freezes that abstract."""
    lib = make_library(tmp_path)
    head = abstract_work(lib, abstract=False)
    tid = new_table(lib)
    lib.tables.add_rows(lib.rid, tid, [head], version(lib, tid))  # a person put the bare head in the table
    other = other_version(lib, head)
    assert members(lib) == {other}
    assert table_rows.add_rows(lib.store) == {tid: [other]}
    membership = table_sources.membership(lib.store, lib.rid, tid)
    assert membership.get(other) == "abstract_only" and head not in membership
    rows = {r["source_version_id"]: r for r in build_snapshot(lib.store, lib.rid, tid)["rows"]}
    assert head not in rows and rows[other]["membership"] == "abstract_only" and rows[other]["passage_ids"]


def test_a_pdf_arriving_after_the_snapshot_never_reaches_the_report(tmp_path):
    lib, abstract, tid = filled(tmp_path)
    snap = build_snapshot(lib.store, lib.rid, tid)
    abstract_passage = lib.store.passages_for(abstract)[0]["id"]
    add_pdf(lib.store, abstract, ["SYNTHETIC packets packets packets late page one.",
                                  "SYNTHETIC packets packets packets late page two."], "4" * 64)
    assert [p["id"] for p in selection.row_passages(lib.store, snap, abstract)] == [abstract_passage]
    # The frozen row is ranked within its frozen passages before the limit: two late pages cannot use up the limit.
    hits = lib.store.search_passages([abstract], '"packets"', 2, selection.frozen_passage_ids(snap))
    assert [p["id"] for p in hits] == [abstract_passage]
    plan = {"glossary": [{"term": "packets", "passage_id": abstract_passage}], "axes": []}
    for section_id in ("III", "IV", "V"):
        chosen = selection.select_evidence(lib.store, snap, section_id, plan, [])
        assert all(p["source_version_id"] != abstract or p["id"] == abstract_passage for p in chosen["passages"])
    # A row frozen on nothing extra keeps today's live reading.
    assert selection.row_passages(lib.store, snap, lib.included) == lib.store.passages_for(lib.included)


def test_a_paused_report_resumes_on_the_same_frozen_passages(tmp_path):
    lib, abstract, tid = filled(tmp_path)
    reports = ReportStore(lib.store)
    run = lib.store.create_run(lib.rid, "report", {}, None)
    report_id = reports.create_report(lib.rid, run["id"], 1, "en")
    saved = reports.save_snapshot(report_id, tid)
    add_pdf(lib.store, abstract, ["SYNTHETIC late page."], "5" * 64)
    resumed = reports.snapshot(report_id)  # a resumed report reads the saved snapshot, not a new one
    assert resumed == saved
    assert all(p["kind"] == "abstract" for p in selection.row_passages(lib.store, resumed, abstract))


def test_methodology_names_the_abstract_only_rows_apart_from_the_included_ones():
    assert "not counted as included" in abstract_rows_sentence(2, "en")
    assert "dahil kaynaklara sayılmadı" in abstract_rows_sentence(1, "tr")


# ---- claim marks ----------------------------------------------------------------------------------------------------

def marked_report(tmp_path):
    from test_report_assembly import _claim, report_with_sections
    fixture = report_with_sections.__wrapped__(tmp_path)
    lib = next(fixture)
    store, reports = lib["store"], lib["reports"]
    report_id = lib["report_id"]
    snapshot = reports.snapshot(report_id)
    # A second cell of the same row, read from the abstract: one row with both depths.
    tables = TableStore(store)
    table_id = store.conn.execute("SELECT id FROM evidence_tables WHERE research_id = ?", (lib["store"].conn.execute(
        "SELECT research_id FROM reports WHERE id = ?", (report_id,)).fetchone()[0],)).fetchone()[0]
    research_id = store.conn.execute("SELECT research_id FROM reports WHERE id = ?", (report_id,)).fetchone()[0]
    column_id = tables.add_column(research_id, table_id, {"name": "Setting", "instruction": "Record the setting",
                                                          "answer_format": "text", "options": None,
                                                          "allow_multiple": False, "unit_hint": None},
                                  tables.table_view(research_id, table_id)["table"]["version"], None)
    step = store.conn.execute("SELECT step_id, run_id, step_input_id FROM cell_revisions LIMIT 1").fetchone()
    revision = tables.save_model_output(
        research_id, table_id, column_id, lib["source_id"], column_revision=1, state="value",
        value={"text": "SYNTHETIC setting"}, note=None, reading_depth="abstract", output_status="structurally_valid",
        links=[{"passage_id": lib["abstract_passage"], "source_version_id": lib["source_id"],
                "anchor_text": "abstract evidence", "anchor_match": "exact"}],
        run_id=step["run_id"], step_id=step["step_id"], step_input_id=step["step_input_id"], model_connection="fake",
        resolved_model="fake-model", scope_revision=1, cell_version_at_request=0, recheck=False)
    abstract_cell_id = store.conn.execute("SELECT cell_id FROM cell_revisions WHERE id = ?", (revision,)).fetchone()[0]
    snapshot["cells"].append(snapshot["cells"][0] | {"cell_id": abstract_cell_id, "cell_revision_id": revision,
                                                     "column_id": column_id, "reading_depth": "abstract"})
    store.conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?", (json.dumps(snapshot), report_id))
    lib["abstract_cell_id"] = abstract_cell_id
    reports.save_gaps(report_id, [
        {"gap_id": "gap_abs", "kind": "stated_limitation", "text": "SYNTHETIC gap", "basis_claim_keys": [],
         "basis_passage_ids": [lib["abstract_passage"]], "basis_cell_ids": [], "provenance": {"origin": "model"}},
        {"gap_id": "gap_full", "kind": "stated_limitation", "text": "SYNTHETIC gap two", "basis_claim_keys": [],
         "basis_passage_ids": [lib["section_passage"]], "basis_cell_ids": [], "provenance": {"origin": "model"}},
    ])
    vii = reports.create_section(report_id, "VII", 7)
    ix = reports.create_section(report_id, "IX", 9)
    reports.save_section_draft(vii, lib["report_step_id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 5)
    reports.save_section_draft(ix, lib["report_step_id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 5)
    gap_only = _claim("VII.1", "SYNTHETIC future work.", "analyst_inference") | {"gap_refs": ["gap_abs"]}
    gap_full = _claim("VII.2", "SYNTHETIC other future work.", "analyst_inference") | {"gap_refs": ["gap_full"]}
    reports.save_claims(vii, [gap_only, gap_full], [])
    reports.save_claims(ix, [_claim("IX.1", "SYNTHETIC conclusion.", "analyst_inference", ["VII.1"]),
                             _claim("IX.2", "SYNTHETIC second conclusion.", "analyst_inference", ["VII.2"])], [])
    return fixture, lib


def test_claim_marks_follow_each_claims_own_links_body_refs_and_gap_refs(tmp_path):
    fixture, lib = marked_report(tmp_path)
    try:
        store, reports, report_id = lib["store"], lib["reports"], lib["report_id"]
        marks = assembly.claim_depth_marks(store, reports, report_id)
        by_key = {row["claim_key"]: row["id"] for row in store.conn.execute(
            "SELECT c.claim_key, c.id FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
            " WHERE s.report_id = ?", (report_id,))}
        assert by_key["III.1"] not in marks                    # a full-text section passage
        assert marks[by_key["abstract.1"]] == "mixed"          # its own abstract link, and III.1 by body ref
        assert marks[by_key["VII.1"]] == "abstract"            # supported only by a gap on an abstract basis
        assert marks[by_key["IX.1"]] == "abstract"             # a summary built on it
        assert by_key["VII.2"] not in marks and by_key["IX.2"] not in marks  # a full-text-only gap: no mark
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


def test_a_claim_citing_the_abstract_cell_of_a_row_with_full_text_cells_is_marked(tmp_path):
    from test_report_assembly import _claim
    fixture, lib = marked_report(tmp_path)
    try:
        store, reports, report_id = lib["store"], lib["reports"], lib["report_id"]
        iv = reports.create_section(report_id, "IV", 4)
        reports.save_section_draft(iv, lib["report_step_id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 5)
        link = {"passage_id": None, "source_version_id": lib["source_id"], "step_input_id": lib["report_input_id"],
                "anchor_text": "selected-section evidence", "anchor_match": "exact"}
        reports.save_claims(iv, [_claim("IV.1", "SYNTHETIC abstract value.", "source_stated"),
                                 _claim("IV.2", "SYNTHETIC full value.", "source_stated")],
                            [link | {"claim_key": "IV.1", "cell_id": lib["abstract_cell_id"], "anchor_text": "abstract evidence"},
                             link | {"claim_key": "IV.2", "cell_id": lib["cell_id"]}])
        marks = assembly.claim_depth_marks(store, reports, report_id)
        ids = {row["claim_key"]: row["id"] for row in store.conn.execute("SELECT claim_key, id FROM report_claims")}
        assert marks.get(ids["IV.1"]) == "abstract" and ids["IV.2"] not in marks
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


# ---- rendering ------------------------------------------------------------------------------------------------------

def test_every_output_carries_the_abstract_notes(tmp_path):
    from deixis.exports.report import blocks
    from deixis.workflow.report.export import to_markdown
    from deixis.workflow.report.latex import to_latex
    from deixis.workflow.report.latex_export import read_bib_sources
    from deixis.workflow.views import report_view
    from test_report_export import complete
    store, reports, research_id, report_id = complete(tmp_path)
    view = report_view(store, research_id, report_id)
    assert any(claim["depth_mark"] for section in view["sections"] for claim in section["claims"])
    assert view["references"][0]["abstract_only"] and view["table_i"]["rows"][0]["abstract_only"]
    markdown = to_markdown(view, title="SYNTHETIC", corpus=None)
    assert "(from abstract)" in markdown and "(abstract only)" in markdown and "Read from the abstract only." in markdown
    docx_text = json.dumps([getattr(b, "__dict__", str(b)) for b in blocks(view, title="SYNTHETIC", corpus=None)],
                           default=str, ensure_ascii=False)
    assert "(from abstract)" in docx_text and "Read from the abstract only." in docx_text
    bundle = to_latex(view, title="SYNTHETIC", corpus=None, bib_sources=read_bib_sources(store, view))
    assert "(from abstract)" in bundle.tex and "(abstract only)" in bundle.tex
    assert "read from the abstract only" in bundle.bib
    tr = view | {"language": "tr"}
    assert "(özetten)" in to_markdown(tr, title="SYNTHETIC", corpus=None)


def test_the_basis_note_lists_the_abstract_only_sources_in_both_languages():
    basis = {"sources": 2, "full_text": 1, "abstract_only": 1, "metadata_only": 0, "cells_total": 2, "cells_unverified": 0,
             "unverified_sources": [], "abstract_members": [{"source_version_id": "srv_x", "source_key": "lee21", "title": "T"}]}
    assert "1 source entered the report from its abstract only because no full text was obtained; it is listed below." \
        in export_text.basis_note(basis, False)
    assert "rapora yalnızca özetiyle girdi" in export_text.basis_note(basis, True)
    assert export_text.abstract_member_field(basis["abstract_members"][0], False, str) == "lee21"
    assert export_text.source_cell({"source_key": "lee21", "ref_number": 3, "abstract_only": True}, False, str) == \
        "[3] lee21 (abstract only)"
    assert export_text.claim_depth_mark({"depth_mark": "mixed"}, True) == " (kısmen özetten)"


def test_a_library_with_the_d114_marker_is_refused_by_a_build_without_it(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.close()
    assert 16 in db.packaged_versions()
    assert upgrades.STEPS[16].name == "0016_abstract_rows.sql"
    # The main this lands on knew 0001-0015; a build like that must refuse a library 0016 marked.
    monkeypatch.setattr(db, "packaged_versions", lambda: {v for v in range(1, 16)})
    with pytest.raises(db.UnknownSchemaError):
        db.check_schema_known(tmp_path / "library.sqlite")
