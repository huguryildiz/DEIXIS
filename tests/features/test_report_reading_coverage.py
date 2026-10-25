"""How much of each included source's text the full-text screening showed, in the report (audit item 3).

SYNTHETIC records, the fake adapter and hand-written reading decisions only. Passing shows the counts and sentences
follow the recorded coverage, not that any model read a paper.
"""

import asyncio
import copy
from dataclasses import replace

import pytest

from deixis.domain import contracts
from deixis.storage.db import dumps
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.features.report import report_assembly as assembly, report_review_methodology as review_methodology, report_sections as sections
from test_report_flow import PASSAGE, report_flow


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


@pytest.mark.parametrize("language", ["en"])
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
