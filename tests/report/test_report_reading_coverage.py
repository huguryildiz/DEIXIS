"""How much of each included source's text the full-text screening showed, in the report (audit item 3).

SYNTHETIC records, the fake adapter and hand-written reading decisions only. Passing shows the counts and sentences
follow the recorded coverage, not that any model read a paper.
"""

import asyncio
import copy
import json
from dataclasses import replace

import pytest

from deixis.domain import contracts
from deixis.storage.db import dumps
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.report import assembly, review_methodology, sections
from deixis.workflow.report.snapshot import build_snapshot, reading_counts
from test_report_flow import PASSAGE, _add_pdf, report_flow


SOME = {"parts_shown": 12, "parts_total": 40, "pages_shown": 7, "pages_with_text": 14, "pdf_pages": 15,
        "all_parts_shown": False}
ALL = {"parts_shown": 9, "parts_total": 9, "pages_shown": 5, "pages_with_text": 5, "pdf_pages": 6,
       "all_parts_shown": True}


@pytest.fixture
def state(tmp_path):
    value = report_flow(tmp_path)
    value[0].deps.settings = replace(value[0].deps.settings, port=8805)
    yield value
    value[1].conn.close()


def side_step(store, run, key, kind):
    """A step of a finished run beside the report run (only one run may be active)."""
    status = store.run(run["id"])["status"]
    store.update_run(run["id"], status="paused")
    other = store.create_run(run["research_id"], "discovery", {}, None)
    store.update_run(run["id"], status=status)
    step = store.step(other["id"], key, kind)
    store.update_run(other["id"], status="completed")
    return step


def reading(store, run, sid, coverage, code="all_parts_verified"):
    """A decision written from a `model:fulltext_adjudication` step, as `_close_adjudication` writes it."""
    step = side_step(store, run, f"fulltext_adjudication:{sid}:2", "model:fulltext_adjudication")
    return DecisionStore(store).record(run["research_id"], sid, code, step_id=step["id"], read_coverage=coverage)


def source(store, rid, title, *, work_of=None):
    sid = store.create_upload_source(title)
    store._insert_passage(sid, None, "abstract", None, None, "synthetic", None, None, PASSAGE)
    store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
    if work_of is not None:
        work = store.source(work_of)["work_id"]
        store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work, sid))
    return sid


def test_reading_counts_by_included_version(state):
    _, store, _, _, run, _, _ = state
    rid = run["research_id"]
    whole, some, unrecorded, none = (source(store, rid, f"SYNTHETIC {name}") for name in ("all", "some", "unrecorded", "none"))
    reading(store, run, whole, ALL)
    reading(store, run, some, SOME)
    # A person's later decision closes the reading's row; the parts it showed stay shown.
    DecisionStore(store).record(rid, some, "human_criterion_not_met")
    reading(store, run, unrecorded, None)
    # A code decision with no reading step (identity unconfirmed) is not a reading.
    no_step = side_step(store, run, "adjudication_plan", "code:adjudication_plan")
    DecisionStore(store).record(rid, none, "pdf_identity_unconfirmed", step_id=no_step["id"])
    other = source(store, rid, "SYNTHETIC other version", work_of=whole)
    assert reading_counts(store, rid, [whole, some, unrecorded, none, other]) == {
        "all_parts": 2, "some_parts": 1, "unrecorded": 1, "none": 1, "other_version": 1}
    # Two included versions of one work, each read: each keeps its own reading.
    reading(store, run, other, SOME)
    assert reading_counts(store, rid, [whole, other]) == {
        "all_parts": 1, "some_parts": 1, "unrecorded": 0, "none": 0, "other_version": 0}


def test_snapshot_has_no_reading_without_a_recorded_screening(state):
    _, store, _, _, run, _, _ = state
    rid = run["research_id"]
    assert "reading" not in build_snapshot(store, rid, run["target"]["table_id"])
    # Once the research has a reading, an included source without one is disclosed as `none`.
    excluded = store.create_upload_source("SYNTHETIC read but not included")
    store.add_to_corpus(rid, excluded, "user_upload", selection_state="excluded", selection_origin="user")
    reading(store, run, excluded, SOME, code="criterion_absent")
    assert build_snapshot(store, rid, run["target"]["table_id"])["reading"] == {
        "all_parts": 0, "some_parts": 0, "unrecorded": 0, "none": 1, "other_version": 0}


@pytest.mark.parametrize("language", ["en", "tr"])
def test_methodology_and_limitations_say_how_much_was_shown_and_assembly_holds_them(state, language):
    flow, store, reports, adapter, run, scope, report = state
    rid = run["research_id"]
    store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report))
    reading(store, run, store.included_sources(rid)[0], SOME)
    asyncio.run(sections.run_report(flow, run, scope))
    frozen = reports.snapshot(report)
    assert frozen["reading"] == {"all_parts": 0, "some_parts": 1, "unrecorded": 0, "none": 0, "other_version": 0}
    sentence = review_methodology.reading_sentence(frozen["reading"], 1, language)
    expected = ("some of the parts of 1" if language == "en" else "1 tanesinde bir kısmı gösterildi")
    assert expected in sentence
    ii, viii = reports.section(report, "II"), reports.section(report, "VIII")
    assert sentence in ii["draft"]["text"] and ii["validation"]["numbers"]["reading"] == frozen["reading"]
    items = viii["validation"]["numbers"]["items"]
    assert len(items) == 6 and items[1]["key"] == "open_access_bias_note" and items[1]["text"].endswith(sentence)
    assert sentence in viii["draft"]["text"]
    # The VIII model input keeps its contract: no new key or item.
    viii_input = next(si for si in adapter.calls if si["task_type"] == "report_section"
                      and si["report_target"]["section_id"] == "VIII")
    assert contracts.check_step_input(viii_input) == []
    assert assembly.run_assembly_checks(store, reports, report) == []

    def tamper(section_id, change):
        section = reports.section(report, section_id)
        validation = copy.deepcopy(section["validation"])
        draft = copy.deepcopy(section["draft"])
        change(validation["numbers"], draft)
        store.conn.execute("UPDATE report_sections SET validation_json = ?, draft_json = ? WHERE id = ?",
                           (dumps(validation), dumps(draft), section["id"]))
        found = {(i["rule"], i["section_id"]) for i in assembly.run_assembly_checks(store, reports, report)}
        store.conn.execute("UPDATE report_sections SET validation_json = ?, draft_json = ? WHERE id = ?",
                           (dumps(section["validation"]), dumps(section["draft"]), section["id"]))
        return found

    def ii_counts(numbers, draft):
        numbers["reading"] = numbers["reading"] | {"all_parts": 1, "some_parts": 0}

    def viii_sentence(numbers, draft):
        # Items and text changed together, so the text-drift check alone would pass.
        numbers["items"][1]["text"] = numbers["items"][1]["text"].replace(sentence, "")
        draft["text"] = review_methodology.render_limitations(numbers, language)

    def ii_text(numbers, draft):
        draft["text"] = draft["text"].replace(sentence, "")

    assert ("corpus_count_mismatch", "II") in tamper("II", ii_counts)
    assert ("corpus_count_mismatch", "II") in tamper("II", ii_text)
    assert ("corpus_count_mismatch", "VIII") in tamper("VIII", viii_sentence)


def test_report_section_access_names_what_was_sent(state):
    """A source whose PDF text is stored but whose abstract alone was sent is labelled `abstract` (audit item 3)."""
    flow, store, reports, adapter, run, scope, report = state
    asyncio.run(sections.run_report(flow, run, scope))
    sid = store.included_sources(run["research_id"])[0]
    _add_pdf(store, sid, ["SYNTHETIC page text of the source."])
    abstract = next(p for p in store.passages_for(sid) if p["kind"] == "abstract")
    payload = flow._step_input(run, scope, "stp_synthetic", "report_section", [], [sid], [abstract], [],
                               ("fake", "fake-model", None),
                               report_target={"report_id": report, "section_id": "IV", "cells": []})
    assert {s["source_id"]: s["access_level"] for s in payload["sources"]} == {sid: "abstract"}
    cell = {"cell_id": "cel_synthetic", "column_id": "col_synthetic", "source_version_id": sid,
            "reading_depth": "selected_sections", "evidence": []}
    payload = flow._step_input(run, scope, "stp_synthetic", "report_section", [], [sid], [], [],
                               ("fake", "fake-model", None),
                               report_target={"report_id": report, "section_id": "IV", "cells": [cell]})
    assert payload["sources"][0]["access_level"] == "pdf_available"
    payload = flow._step_input(run, scope, "stp_synthetic", "report_section", [], [sid], [], [],
                               ("fake", "fake-model", None),
                               report_target={"report_id": report, "section_id": "IV", "cells": []})
    assert payload["sources"][0]["access_level"] == "metadata"
    # Other steps keep the library's view of the source.
    payload = flow._step_input(run, scope, "stp_synthetic", "answer_review", [], [sid], [abstract], [],
                               ("fake", "fake-model", None))
    assert payload["sources"][0]["access_level"] == "pdf_available"
    assert json.loads(json.dumps(payload))  # still plain JSON


def test_vii_access_counts_the_basis_records_in_its_validation_context(state):
    """VII receives a gap's basis pages and cells inside `validation_context`; they count as sent."""
    flow, store, reports, adapter, run, scope, report = state
    asyncio.run(sections.run_report(flow, run, scope))
    sid = store.included_sources(run["research_id"])[0]
    _add_pdf(store, sid, ["SYNTHETIC basis page of the source."])
    page = next(p for p in store.passages_for(sid) if p["kind"] == "pdf_page")
    context = {"basis_passages": [{"passage_id": page["id"], "source_id": sid, "locator": {"kind": "pdf_page"}}],
               "basis_cells": []}
    payload = flow._step_input(run, scope, "stp_synthetic", "report_section", [], [sid], [], [],
                               ("fake", "fake-model", None),
                               report_target={"report_id": report, "section_id": "VII", "cells": [],
                                              "validation_context": context})
    assert payload["sources"][0]["access_level"] == "pdf_available"
    context = {"basis_passages": [], "basis_cells": [{"cell_id": "cel_basis", "column_id": "col_basis",
                                                      "source_version_id": sid, "reading_depth": "abstract"}]}
    payload = flow._step_input(run, scope, "stp_synthetic", "report_section", [], [sid], [], [],
                               ("fake", "fake-model", None),
                               report_target={"report_id": report, "section_id": "VII", "cells": [],
                                              "validation_context": context})
    assert payload["sources"][0]["access_level"] == "abstract"
