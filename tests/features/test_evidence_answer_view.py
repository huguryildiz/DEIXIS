"""The evidence an answer rests on is frozen with that answer, and its report is written from the same view.

Synthetic model output throughout, so these show workflow order, not extraction quality.
"""

import json
import time

from fastapi.testclient import TestClient

from deixis.workflow.answer import answer as fast_answer
from deixis.workflow.features.report import report_evidence_view as evidence_view
from deixis.workflow.features.report import report_selection
from test_api_flow import create, include_sources, run_to_end, session, wait_run
from test_study_table_opening import ColumnAdapter, app_for


class FakeConn:
    """Answers the one query the snapshot's naming helper makes, so nothing private has to be patched."""

    def execute(self, sql, params=()):
        assert "FROM source_versions" in sql, sql
        return _Row({"title": "SYNTHETIC title", "source_key": params[0]})


class _Row:
    def __init__(self, values):
        self.values = values

    def fetchone(self):
        return self

    def __getitem__(self, key):
        return self.values[key]


class FakeStore:
    """Enough store for the pure boundary tests: a passage's kind, a source's abstract, and the naming query."""

    def __init__(self, kinds=None, unreadable=()):
        self.conn = FakeConn()
        self.kinds = kinds or {}
        self.unreadable = set(unreadable)

    def passage(self, passage_id):
        if passage_id in self.unreadable:
            raise KeyError(passage_id)
        return {"id": passage_id, "kind": self.kinds.get(passage_id, "abstract")}

    def passages_for(self, source_id):
        return [{"id": f"psg_abstract_of_{source_id}", "kind": "abstract"}]


def built(monkeypatch, store, snapshot, plan):
    """`build` run against a supplied snapshot: what is under test is the boundary this module applies."""
    monkeypatch.setattr(evidence_view, "build_snapshot",
                        lambda _store, _research_id, _table_id: json.loads(json.dumps(snapshot)))
    return evidence_view.build(store, "res_one", "tbl_one", plan, "run_one")


def answer_run_id(store, rid):
    row = store.conn.execute(
        "SELECT run_id FROM answers WHERE research_id = ? AND status = 'structurally_valid'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (rid,)).fetchone()
    return row["run_id"] if row else None


def step_output(store, run_id, key):
    step = store.existing_step(run_id, key)
    return step["output"] if step and step["status"] == "succeeded" else None


def settle(client, rid, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        runs = client.get(f"/api/researches/{rid}").json()["runs"]
        if all(run["status"] in ("completed", "failed", "paused", "cancelled") for run in runs):
            return runs
        time.sleep(0.1)
    raise AssertionError("runs did not settle")


def answered(client, store, rid):
    """A research with a study table, a reading and a valid answer; returns its answer run and frozen view."""
    discovered = run_to_end(client, rid, "discovery")
    include_sources(client, rid, discovered)
    run_to_end(client, rid, "answer")
    settle(client, rid)
    run_id = answer_run_id(store, rid)
    assert run_id is not None
    return run_id, step_output(store, run_id, evidence_view.VIEW_KEY)


def test_the_view_is_frozen_with_the_answer_and_bound_to_the_text_that_answer_read(tmp_path):
    """Every row carries exactly the passages the answer's own input bound for it, and nothing reads live text."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_id, view = answered(client, store, rid)

        assert view is not None and view["bound_to_answer"] is True
        assert view["answer_run_id"] == run_id
        plan = step_output(store, run_id, fast_answer.INPUT)
        assert view["scope_revision"] == plan["scope_revision"]
        # The view is the answer's rows, not the reading's: one row per source the answer kept.
        allowed = evidence_view.allowed_passages(plan)
        assert all("passage_ids" in row for row in view["rows"])
        for row in view["rows"]:
            assert row["passage_ids"] == allowed.get(row["source_version_id"], [])
        # Something was read, or every assertion above would hold on an empty view.
        assert any(row["passage_ids"] for row in view["rows"])


def test_a_row_the_answer_read_from_its_abstract_does_not_give_its_pdf():
    """The route decides, not the richest text the source happens to hold."""
    plan = {"scope_revision": 1, "items": [
        {"source_version_id": "srv_file", "route": "fulltext", "fulltext_ids": ["psg_p1", "psg_p2"],
         "abstract_ids": ["psg_a"]},
        # The source has a PDF, but this answer read its abstract, so that is all the report may read.
        {"source_version_id": "srv_abstract", "route": "abstract", "fulltext_ids": ["psg_p3"],
         "abstract_ids": ["psg_b"]},
        {"source_version_id": "srv_no_text", "route": "abstract", "fulltext_ids": [], "abstract_ids": []},
    ]}
    assert evidence_view.allowed_passages(plan) == {
        "srv_file": ["psg_p1", "psg_p2"], "srv_abstract": ["psg_b"], "srv_no_text": []}


def test_a_cell_quote_outside_its_rows_text_is_not_verified_evidence(monkeypatch):
    """A quote linked past the row's frozen text keeps its value for the person but counts as unverified."""

    snapshot = {
        "rows": [{"source_version_id": "srv_one", "reading_depth": "full_text", "membership": "included"}],
        "columns": [{"column_id": "col_one", "name": "Finding", "revision": 1}],
        "cells": [
            {"cell_id": "cel_in", "column_id": "col_one", "source_version_id": "srv_one", "state": "value",
             "value": {"text": "in bounds"}, "reading_depth": "full_text",
             "evidence": [{"passage_id": "psg_p1", "quote": "SYNTHETIC inside"}]},
            {"cell_id": "cel_out", "column_id": "col_one", "source_version_id": "srv_one", "state": "value",
             "value": {"text": "out of bounds"}, "reading_depth": "full_text",
             "evidence": [{"passage_id": "psg_later", "quote": "SYNTHETIC from a page that arrived later"}]},
        ],
    }
    plan = {"scope_revision": 3, "items": [
        {"source_version_id": "srv_one", "route": "fulltext", "fulltext_ids": ["psg_p1"], "abstract_ids": ["psg_a1"]}]}

    view = built(monkeypatch, FakeStore({"psg_p1": "pdf_page", "psg_later": "pdf_page"}), snapshot, plan)

    kept = next(cell for cell in view["cells"] if cell["cell_id"] == "cel_in")
    lost = next(cell for cell in view["cells"] if cell["cell_id"] == "cel_out")
    assert kept["state"] == "value" and [link["passage_id"] for link in kept["evidence"]] == ["psg_p1"]
    # The value is kept for the person; it is simply no located evidence in this view.
    assert lost["state"] == "not_verified" and lost["evidence"] == [] and lost["value"] == {"text": "out of bounds"}
    assert view["rows"][0]["passage_ids"] == ["psg_p1"]


def test_a_row_bound_to_its_abstract_claims_no_deeper_reading(monkeypatch):
    """A row whose frozen text is only its abstract cannot show a full-text depth, in the row or in its cells."""
    snapshot = {
        "rows": [{"source_version_id": "srv_one", "reading_depth": "full_text", "membership": "abstract_only"}],
        "columns": [{"column_id": "col_one", "name": "Finding", "revision": 1}],
        "cells": [{"cell_id": "cel_one", "column_id": "col_one", "source_version_id": "srv_one", "state": "value",
                   "value": {"text": "from the abstract"}, "reading_depth": "selected_sections",
                   "evidence": [{"passage_id": "psg_a1", "quote": "SYNTHETIC abstract sentence"}]}],
    }
    plan = {"scope_revision": 1, "items": [
        {"source_version_id": "srv_one", "route": "abstract", "fulltext_ids": [], "abstract_ids": ["psg_a1"]}]}

    view = built(monkeypatch, FakeStore(), snapshot, plan)

    assert view["rows"][0]["reading_depth"] == "abstract"
    assert view["cells"][0]["reading_depth"] == "abstract"
    # The quote is inside the row's own text, so it stays located evidence.
    assert view["cells"][0]["state"] == "value"


def test_the_report_is_written_from_the_answers_view_and_reads_only_its_passages(tmp_path):
    """The report's own snapshot is that view, and a row reads exactly the passages frozen for it."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, view = answered(client, store, rid)
        table_id = view["table_id"]

        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": table_id})
        assert started.status_code == 202, started.text
        report_id = started.json()["target"]["report_id"]
        _, report_run = wait_run(client, rid, started.json()["id"])
        assert report_run["status"] in ("completed", "failed"), report_run

        saved = json.loads(store.conn.execute(
            "SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()["snapshot_json"])
        assert saved["bound_to_answer"] is True and saved["answer_run_id"] == view["answer_run_id"]
        assert [row["passage_ids"] for row in saved["rows"]] == [row["passage_ids"] for row in view["rows"]]
        assert [cell["cell_revision_id"] for cell in saved["cells"]] == [cell["cell_revision_id"] for cell in view["cells"]]

        bound = next(row for row in saved["rows"] if row["passage_ids"])
        read = report_selection.row_passages(store, saved, bound["source_version_id"])
        assert [passage["id"] for passage in read] == bound["passage_ids"]


def test_a_report_of_a_research_without_a_view_still_reads_the_live_table(tmp_path):
    """A research whose answer froze no view (its study table is off) keeps the behaviour it had."""
    from deixis.workflow.features.tables.tables import TableStore

    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        run_id, view = answered(client, store, rid)
        assert view is not None
        # A table the app did not open: the answer's view is of another table, so this one is read live.
        other = TableStore(store).create_table(rid, "My own table", [], None, None)

        assert evidence_view.for_research(store, rid, other) is None
        live = evidence_view.readiness(store, rid, other)
        assert "from_answer_view" not in live
        assert evidence_view.readiness(store, rid, view["table_id"])["from_answer_view"] is True


def test_the_views_rows_are_exactly_the_answers_rows(monkeypatch):
    """A table row the answer did not use is named, not counted as evidence; a row it used with none is named too."""
    snapshot = {
        "rows": [{"source_version_id": "srv_used", "reading_depth": "abstract", "membership": "included"},
                 {"source_version_id": "srv_unused", "reading_depth": "full_text", "membership": "included"}],
        "columns": [{"column_id": "col_one", "name": "Finding", "revision": 1, "instruction": "x",
                     "answer_format": "text"}],
        "cells": [
            {"cell_id": "cel_used", "column_id": "col_one", "source_version_id": "srv_used", "state": "value",
             "value": {"text": "kept"}, "reading_depth": "abstract",
             "evidence": [{"passage_id": "psg_a1", "quote": "SYNTHETIC kept"}]},
            {"cell_id": "cel_unused", "column_id": "col_one", "source_version_id": "srv_unused", "state": "value",
             "value": {"text": "dropped"}, "reading_depth": "full_text",
             "evidence": [{"passage_id": "psg_p9", "quote": "SYNTHETIC dropped"}]},
        ],
        "basis": {"sources": 2, "full_text": 1, "abstract_only": 1, "metadata_only": 0, "cells_total": 2,
                  "cells_unverified": 0, "unverified_sources": []},
    }
    plan = {"scope_revision": 1, "items": [
        {"source_version_id": "srv_used", "route": "abstract", "fulltext_ids": [], "abstract_ids": ["psg_a1"]},
        {"source_version_id": "srv_no_table_row", "route": "abstract", "fulltext_ids": [], "abstract_ids": ["psg_a2"]}]}

    view = built(monkeypatch, FakeStore({"psg_p9": "pdf_page"}), snapshot, plan)

    assert [row["source_version_id"] for row in view["rows"]] == ["srv_used"]
    assert [cell["cell_id"] for cell in view["cells"]] == ["cel_used"]
    assert [row["source_version_id"] for row in view["rows_not_in_answer"]] == ["srv_unused"]
    assert view["answer_rows_without_a_table_row"] == ["srv_no_table_row"]
    # The basis note counts what is left, not what the live table held.
    assert view["basis"]["sources"] == 1 and view["basis"]["full_text"] == 0
    assert view["basis"]["cells_total"] == 1


def test_a_passage_that_cannot_be_read_gives_a_row_no_depth(monkeypatch):
    """An unreadable frozen passage counts as no text beyond the abstract, so the row claims none."""
    snapshot = {
        "rows": [{"source_version_id": "srv_one", "reading_depth": "full_text", "membership": "included"}],
        "columns": [{"column_id": "col_one", "name": "Finding", "revision": 1, "instruction": "x",
                     "answer_format": "text"}],
        "cells": [{"cell_id": "cel_one", "column_id": "col_one", "source_version_id": "srv_one", "state": "value",
                   "value": {"text": "x"}, "reading_depth": "full_text",
                   "evidence": [{"passage_id": "psg_gone", "quote": "SYNTHETIC unreadable"}]}],
        "basis": {},
    }
    plan = {"scope_revision": 1, "items": [
        {"source_version_id": "srv_one", "route": "fulltext", "fulltext_ids": ["psg_gone"], "abstract_ids": []}]}

    view = built(monkeypatch, FakeStore(unreadable={"psg_gone"}), snapshot, plan)

    assert view["rows"][0]["reading_depth"] == "abstract"
    assert view["cells"][0]["reading_depth"] == "abstract"
    # The quote is inside the row's frozen text, so the boundary rule leaves it alone.
    assert view["cells"][0]["state"] == "value"
