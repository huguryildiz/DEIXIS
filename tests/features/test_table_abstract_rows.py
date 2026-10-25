"""D114: works read from their abstracts only join a table made from the research, and its report, with a note.

A work joins when it passed the abstract stage and its full text could not be obtained, nobody decided it, and no
version of it is still being judged or has text beyond its abstract. Records and model outputs are SYNTHETIC (scripted
FakeAdapter); passing shows workflow behavior, not reading quality.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db, upgrades
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.features.tables import table_sources
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.flow import FlowDeps, ResearchFlow
from deixis.workflow.features.report.report_snapshot import included_table_rows
from deixis.workflow.run.store import Store
from deixis.workflow.features.tables.tables import TableStore, report_ready
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

@pytest.mark.parametrize("state", ["excluded"])
def test_a_selection_the_user_set_stands(tmp_path, state):
    lib = make_library(tmp_path)
    svid = abstract_work(lib)
    select(lib, svid, state)
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


# ---- the report -----------------------------------------------------------------------------------------------------

def filled(tmp_path):
    lib = make_library(tmp_path)
    abstract = abstract_work(lib)
    tid = new_table(lib)
    execute(lib, lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None, included_only=True))
    return lib, abstract, tid


# ---- claim marks ----------------------------------------------------------------------------------------------------


# ---- rendering ------------------------------------------------------------------------------------------------------

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
