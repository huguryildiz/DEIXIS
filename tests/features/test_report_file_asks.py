"""Which works the person is asked for a file for, after the automatic routes have had their turn (P10d).

SYNTHETIC records, no model and no network. Passing shows the list is bounded by the depth's own allowance, that a
request rests on one work's own open cell rather than on an empty axis, and that an answered request hands nothing
back; it says nothing about whether a file the person adds improves a report.
"""

from deixis.storage import db
from deixis.storage.db import dumps, new_id, now
from deixis.workflow.features.report import report_coverage as coverage
from deixis.workflow.features.report import report_file_asks as file_asks
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.run import fast_path
from deixis.workflow.features.tables.tables import TableStore
from deixis.workflow.run.store import Store
from deixis.workflow.run.views import file_asks_view

COLUMN_A, COLUMN_B = "col_aaaaaaaa", "col_bbbbbbbb"
PLAN = {"axes": [{"axis_id": "AX1", "label": "SYNTHETIC delay bound", "column_id": COLUMN_A},
                 {"axis_id": "AX2", "label": "SYNTHETIC energy cost", "column_id": COLUMN_B}],
        "research_questions": [{"rq_id": "RQ1", "text": "SYNTHETIC"}]}


def _add_asset(store, asset_id, svid, sha, filename):
    """A file on that record's own row, as the library stores one."""
    store.conn.execute(
        "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
        " retrieved_at, origin, extraction_status) VALUES (?, ?, ?, 10, 'application/pdf', ?, ?, 'user_upload',"
        " 'succeeded')", (asset_id, svid, sha, filename, now()))


def cell(column, source, state="value", depth="abstract", evidence=(("psg_1", "SYNTHETIC quote"),)):
    return {"cell_id": f"cel_{column}_{source}", "column_id": column, "source_version_id": source, "state": state,
            "value": {"text": "SYNTHETIC value"} if state == "value" else None, "reading_depth": depth,
            "evidence": [{"passage_id": pid, "quote": quote} for pid, quote in evidence]}


class Library:
    """A research with sources, a frozen report snapshot and plan, and the runs those rest on."""

    def __init__(self, tmp_path, effort="standard"):
        conn = db.connect(tmp_path / "library.sqlite")
        db.migrate(conn)
        self.store = Store(conn)
        self.research_id = self.store.create_research(
            "How do SYNTHETIC underwater routing protocols bound delay?", "academic", effort, [], "fake", "fake-model", "en")
        # The discovery run that froze the depth, and its ledger: the allowance belongs to that run's policy.
        budget = fast_path.freeze_budget({"max_model_calls": 10, "max_provider_requests": 10}, effort)
        # `create_run` writes the run's own fast-path ledger, which is where the allowance is read back from.
        self.discovery = self.store.create_run(self.research_id, "discovery", {"fast_path": budget}, None)
        self.store.update_run(self.discovery["id"], status="completed")
        self.report_run = self.store.create_run(self.research_id, "report", {"max_model_calls": 10}, None)
        self.reports = ReportStore(self.store)
        self.report_id = self.reports.create_report(self.research_id, self.report_run["id"], 1, "en")
        self.table_id = TableStore(self.store).create_table(self.research_id, "SYNTHETIC evidence", None, None, None)
        self.sources = {}

    def source(self, key, *, file=False, settled=True):
        """One record of its own work in the research; `file` gives it a PDF, `settled` ends its routes."""
        svid = self.store.create_upload_source(f"SYNTHETIC study {key}")
        self.store.add_to_corpus(self.research_id, svid, "user_upload", selection_state="included",
                                 selection_origin="user")
        self.store._insert_passage(svid, None, "abstract", None, None, "synthetic_fixture", None, None,
                                   f"SYNTHETIC abstract of {key}.")
        work_id = self.store.source(svid)["work_id"]
        if file:
            asset_id = new_id("ast")
            _add_asset(self.store, asset_id, svid, f"sha{key}", f"{key}.pdf")
            self.store._insert_passage(svid, asset_id, "pdf_page", 1, 1, "synthetic_fixture", None, None,
                                       f"SYNTHETIC page of {key}.")
        if settled:
            # The retrieval answered for this work: the one outcome that means the automatic routes had their turn.
            step = self.store.step(self.discovery["id"], f"fulltext_work:{work_id}", "code:fulltext_work")
            self.store.finish_step(step["id"], "succeeded", None)
        self.sources[key] = svid
        return svid

    def freeze(self, cells, plan=PLAN, failed=()):
        """Store the report's own snapshot and plan, the two frozen things the request rests on."""
        snapshot = {"columns": [{"column_id": COLUMN_A, "name": "SYNTHETIC delay"},
                                {"column_id": COLUMN_B, "name": "SYNTHETIC energy"}],
                    "rows": [{"source_version_id": svid} for svid in self.sources.values()],
                    "failed_rows": [{"source_version_id": svid} for svid in failed],
                    "cells": cells}
        self.store.conn.execute(
            "INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at)"
            " VALUES (?, ?, 1, ?, ?)", (self.report_id, self.table_id, dumps(snapshot), now()))
        self.reports.set_plan(self.report_id, plan)
        return snapshot

    def asks(self):
        return [row["work_id"] for row in file_asks.asks(self.store, self.research_id)]


def test_the_open_sub_questions_of_one_row_are_read_from_the_same_record_the_coverage_counts():
    """One pure reading of the plan against the snapshot feeds both surfaces: the coverage counts it by
    sub-question and the request list reads it by row."""
    snapshot = {"columns": [{"column_id": COLUMN_A, "name": "SYNTHETIC delay"},
                            {"column_id": COLUMN_B, "name": "SYNTHETIC energy"}],
                "rows": [{"source_version_id": f"srv_{n}"} for n in (1, 2, 3)],
                "failed_rows": [{"source_version_id": "srv_3"}],
                "cells": [cell(COLUMN_A, "srv_1"),
                          cell(COLUMN_B, "srv_1", state="inaccessible", evidence=()),
                          cell(COLUMN_A, "srv_2", state="not_verified", evidence=()),
                          cell(COLUMN_B, "srv_3", state="unknown", evidence=())]}
    open_rows = coverage.open_axes_by_row(snapshot, PLAN)
    # A row whose own cells failed is not evidence, so it is not listed at all.
    assert set(open_rows) == {"srv_1", "srv_2"}
    assert [axis["axis_id"] for axis in open_rows["srv_1"]] == ["AX2"]
    assert open_rows["srv_1"][0]["state"] == "inaccessible"
    assert [axis["axis_id"] for axis in open_rows["srv_2"]] == ["AX1"]
    # The sub-question record still counts what it counted before the reading was shared.
    record = coverage.coverage(snapshot, PLAN)
    first, second = record["sub_questions"]
    assert (first["rows"], first["rows_answered"]) == (2, 1) and first["states"] == {"not_verified": 1}
    assert (second["rows"], second["rows_answered"]) == (1, 0) and second["states"] == {"inaccessible": 1}


def test_a_work_whose_own_cell_is_open_and_whose_routes_ended_without_a_file_is_asked_for(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    opened = file_asks.advance(held.store, held.research_id)
    assert [row["source_version_id"] for row in opened] == [asked]
    row = file_asks.asks(held.store, held.research_id)[0]
    # The request says which sub-question stays open on that work's own row, and under which rule it was made.
    assert [axis["axis_id"] for axis in row["axes"]] == ["AX1"]
    assert row["axes"][0]["label"] == "SYNTHETIC delay bound" and row["axes"][0]["state"] == "inaccessible"
    assert (row["rule"], row["run_id"], row["answered_at"]) == (file_asks.RULE, held.discovery["id"], None)
    # Asked once: running the decision again writes nothing, whichever of its two inputs arrived last.
    assert file_asks.advance(held.store, held.research_id) == []
    assert held.asks() == [held.store.source(asked)["work_id"]]


def test_a_work_that_already_holds_a_file_is_not_asked_for_another(tmp_path):
    held = Library(tmp_path)
    readable = held.source("A", file=True)
    held.freeze([cell(COLUMN_A, readable, state="not_found_in_inspected_scope", depth="full_text", evidence=())])
    assert file_asks.advance(held.store, held.research_id) == []


def test_a_work_whose_automatic_routes_have_not_answered_is_not_asked_for(tmp_path):
    held = Library(tmp_path)
    pending = held.source("A", settled=False)
    held.freeze([cell(COLUMN_A, pending, state="inaccessible", evidence=())])
    assert file_asks.advance(held.store, held.research_id) == []
    work_id = held.store.source(pending)["work_id"]
    # A retrieval the daily budget deferred, or one no route answered, is recorded as failed: nothing was settled,
    # so the person is not asked in its place.
    for cause in ("quota_deferred", "fetch_not_settled", "fulltext_work_failed"):
        step = held.store.step(held.discovery["id"], f"fulltext_work:{work_id}", "code:fulltext_work")
        held.store.finish_step(step["id"], "failed", None, error_code=cause)
        assert file_asks.advance(held.store, held.research_id) == [], cause
    # Once the retrieval itself answers — with a file or without one — the same decision asks for it.
    held.store.conn.execute("UPDATE run_steps SET status = 'succeeded', error_code = NULL WHERE operation_key = ?",
                            (f"fulltext_work:{work_id}",))
    assert [row["source_version_id"] for row in file_asks.advance(held.store, held.research_id)] == [pending]


def test_nothing_is_asked_while_a_background_fetch_of_the_research_is_still_out(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    held.store.conn.execute(
        "INSERT INTO fast_path_background_fetches (id, ledger_run_id, run_id, research_id, scope_revision, work_id,"
        " head, position, origin, status, queued_at) VALUES (?, ?, ?, ?, 1, 'wrk_other', 'srv_other', 0,"
        " 'in_flight', 'running', ?)",
        (new_id("bfetch"), held.discovery["id"], held.discovery["id"], held.research_id, now()))
    assert file_asks.advance(held.store, held.research_id) == []
    held.store.conn.execute("UPDATE fast_path_background_fetches SET status = 'succeeded'")
    assert len(file_asks.advance(held.store, held.research_id)) == 1


def test_a_sub_question_that_does_not_apply_to_the_work_asks_for_nothing(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="not_applicable", evidence=())])
    assert file_asks.advance(held.store, held.research_id) == []


def test_the_depth_bounds_how_many_works_are_asked_for_and_quick_asks_for_none(tmp_path):
    held = Library(tmp_path)
    sources = [held.source(key) for key in "ABCD"]
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=()) for svid in sources])
    # Standard asks for three of the four, in the evidence gap's own order (the plan's sub-questions, then the rows).
    assert [row["source_version_id"] for row in file_asks.advance(held.store, held.research_id)] == sources[:3]
    assert file_asks.advance(held.store, held.research_id) == []

    quick = Library(tmp_path / "quick", effort="quick")
    asked = quick.source("A")
    quick.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    assert file_asks.advance(quick.store, quick.research_id) == []
    assert fast_path.MODES["quick"].file_asks == 0


def test_the_allowance_is_spent_by_the_asking_and_an_answered_request_hands_nothing_back(tmp_path):
    held = Library(tmp_path)
    first, second, third, fourth = (held.source(key) for key in "ABCD")
    held.freeze([cell(COLUMN_A, svid, state="inaccessible", evidence=()) for svid in (first, second, third, fourth)])
    file_asks.advance(held.store, held.research_id)
    # The file the first request asked for arrives: its row closes and says so, and keeps its place in the list.
    asset_id = new_id("ast")
    _add_asset(held.store, asset_id, first, "shaA2", "A2.pdf")
    held.store._insert_passage(first, asset_id, "pdf_page", 1, 1, "synthetic_fixture", None, None, "SYNTHETIC page.")
    assert file_asks.advance(held.store, held.research_id) == []
    rows = file_asks.asks(held.store, held.research_id)
    assert [row["source_version_id"] for row in rows] == [first, second, third]
    assert rows[0]["outcome"] == "file_added" and rows[0]["answered_at"]
    assert [row["outcome"] for row in rows[1:]] == [None, None]
    # The fourth work is never asked for: the three asks spent the depth's whole allowance.
    assert fourth not in [row["source_version_id"] for row in rows]


def test_a_research_whose_depth_was_frozen_before_the_rule_asks_for_nothing(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    budget = held.store.run(held.discovery["id"])["budget"]
    policy = {key: value for key, value in budget["fast_path"].items()
              if key not in ("file_ask_rule", "file_asks")}
    held.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?",
                            (dumps({"fast_path": policy}), held.discovery["id"]))
    assert file_asks.allowance(held.store, held.discovery["id"]) is None
    assert file_asks.advance(held.store, held.research_id) == []


def test_the_screen_reads_the_list_with_its_bound_and_the_record_of_each_work(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="not_verified", evidence=())])
    file_asks.advance(held.store, held.research_id)
    view = file_asks_view(held.store, held.research_id)
    assert (view["rule"], view["limit"], view["used"]) == (file_asks.RULE, 3, 1)
    shown = view["asks"][0]
    assert shown["source_version_id"] == asked and shown["title"] == "SYNTHETIC study A"
    assert [axis["label"] for axis in shown["axes"]] == ["SYNTHETIC delay bound"]
    assert shown["answered_at"] is None
    # A research nobody asked anything of still states the bound its depth sets, and an empty list.
    other = Library(tmp_path / "other")
    assert file_asks_view(other.store, other.research_id) == {"rule": file_asks.RULE, "limit": 3, "used": 0,
                                                             "asks": []}
    # The bound is the depth now in force, not the one the last request was made under.
    budget = held.store.run(held.discovery["id"])["budget"]
    policy = budget["fast_path"] | {"file_asks": 5}
    held.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?",
                            (dumps({"fast_path": policy}), held.discovery["id"]))
    assert file_asks_view(held.store, held.research_id)["limit"] == 5


def test_a_report_without_a_frozen_plan_asks_for_nothing(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())], plan={"axes": []})
    assert file_asks.advance(held.store, held.research_id) == []
    held.store.conn.execute("UPDATE reports SET plan_json = NULL WHERE id = ?", (held.report_id,))
    assert file_asks.advance(held.store, held.research_id) == []


def test_one_work_is_asked_once_however_many_of_its_versions_the_table_holds(tmp_path):
    held = Library(tmp_path)
    preprint = held.source("A")
    # A second record of the same work, as a sibling version row is opened: both rows leave a cell open.
    work_id = held.store.source(preprint)["work_id"]
    journal = held.store.create_upload_source("SYNTHETIC study A, journal copy")
    held.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work_id, journal))
    held.store.add_to_corpus(held.research_id, journal, "user_upload", selection_state="included",
                             selection_origin="user")
    held.sources["A2"] = journal
    held.freeze([cell(COLUMN_B, journal, state="inaccessible", evidence=()),
                 cell(COLUMN_A, preprint, state="inaccessible", evidence=())])
    opened = file_asks.advance(held.store, held.research_id)
    # Asked once, on the row whose own cell opens the earlier sub-question of the plan.
    assert [row["source_version_id"] for row in opened] == [preprint]
    assert [row["work_id"] for row in file_asks.asks(held.store, held.research_id)] == [work_id]


def test_a_report_of_an_older_scope_asks_for_nothing_and_a_newer_unplanned_one_makes_the_list_wait(tmp_path):
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    # The person changed the question after that report, and the new discovery froze the depth again: the older
    # report's sub-questions are not the ones to ask about any more.
    held.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (held.research_id,))
    budget = held.store.run(held.discovery["id"])["budget"]
    held.store.update_run(held.report_run["id"], status="completed")
    again = held.store.create_run(held.research_id, "discovery", budget, None)
    held.store.update_run(again["id"], status="completed")
    assert file_asks.advance(held.store, held.research_id) == []
    # A newer report of the current scope that has not frozen its plan yet makes the list wait rather than ask from
    # the plan it is replacing: an allowance spent cannot be handed back.
    held.store.conn.execute("UPDATE reports SET scope_revision = 2 WHERE id = ?", (held.report_id,))
    later_run = held.store.create_run(held.research_id, "report", {"max_model_calls": 10}, None)
    later = held.reports.create_report(held.research_id, later_run["id"], 2, "en")
    assert file_asks.advance(held.store, held.research_id) == []
    # With its own plan frozen on the same evidence, the newest report asks.
    held.store.conn.execute(
        "INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at)"
        " SELECT ?, table_id, table_revision, snapshot_json, ? FROM report_snapshot WHERE report_id = ?",
        (later, now(), held.report_id))
    held.reports.set_plan(later, PLAN)
    opened = file_asks.advance(held.store, held.research_id)
    assert [row["source_version_id"] for row in opened] == [asked]
    # The request records the newer report and the depth run now in force, so what it was asked from is readable.
    assert (opened[0]["report_id"], opened[0]["run_id"], opened[0]["scope_revision"]) == (later, again["id"], 2)


def test_a_source_that_has_left_the_research_is_not_asked_for(tmp_path):
    held = Library(tmp_path)
    gone = held.source("A")
    held.freeze([cell(COLUMN_A, gone, state="inaccessible", evidence=())])
    held.store.conn.execute("UPDATE corpus_memberships SET removed_at = ? WHERE source_version_id = ?",
                            (now(), gone))
    # The upload route refuses a file for a source the research no longer holds, so asking for one asks for nothing.
    assert file_asks.advance(held.store, held.research_id) == []


def test_a_withdrawn_file_leaves_the_work_without_one(tmp_path):
    held = Library(tmp_path)
    withdrawn = held.source("A", file=True)
    held.freeze([cell(COLUMN_A, withdrawn, state="inaccessible", evidence=())])
    assert file_asks.advance(held.store, held.research_id) == []
    # The file was taken off the record, so the work holds none again and the request opens.
    held.store.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'wrong_file'"
                            " WHERE source_version_id = ?", (now(), withdrawn))
    assert [row["source_version_id"] for row in file_asks.advance(held.store, held.research_id)] == [withdrawn]


def test_a_file_nobody_could_read_the_text_of_still_answers_the_request(tmp_path):
    """What was asked for is a file. Whether its text can be read is the reading path's question, and a version row
    holds one file at a time, so this list never asks for a second file for the same work."""
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    assert len(file_asks.advance(held.store, held.research_id)) == 1
    # A file with no readable page at all: the request is answered, and nothing asks the person for another.
    _add_asset(held.store, new_id("ast"), asked, "shaNoText", "A-no-text.pdf")
    assert file_asks.advance(held.store, held.research_id) == []
    row = file_asks.asks(held.store, held.research_id)[0]
    assert (row["outcome"], bool(row["answered_at"])) == ("file_added", True)


def test_an_answered_request_closes_even_while_no_new_one_may_be_opened(tmp_path):
    """Closing rests on the file alone: a question the person has since changed, or a report whose plan is not
    frozen yet, stops new requests and must not leave an answered one standing open."""
    held = Library(tmp_path)
    asked = held.source("A")
    held.freeze([cell(COLUMN_A, asked, state="inaccessible", evidence=())])
    assert len(file_asks.advance(held.store, held.research_id)) == 1
    held.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (held.research_id,))
    _add_asset(held.store, new_id("ast"), asked, "shaA3", "A3.pdf")
    assert file_asks.advance(held.store, held.research_id) == []
    row = file_asks.asks(held.store, held.research_id)[0]
    assert (row["outcome"], bool(row["answered_at"])) == ("file_added", True)
