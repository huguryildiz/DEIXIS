"""P5 evidence table model steps: EvidenceCellDraft and TableColumnProposal checks, fill and recheck runs, their API.

Model outputs come from the test-only FakeAdapter or hand-written SYNTHETIC drafts. Passing these tests shows the contract
checks, allowlists, storage and run behavior hold in code; it says nothing about how well a model fills cells.
"""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.tables import InvalidTableInput, TableStore
from fakes import FakeAdapter, valid_response
from test_api_flow import app_for, create, session, wait_run
from test_contracts import STEP_INPUTS
from test_evidence_tables import PACKET_SIZE, upload

SOURCE = "srv_SYNA1pub01"


# ---- contract checks ------------------------------------------------------------------------
def cell_step_input():
    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    si.update(task_type="cell_extraction", output_schema_versions=["deixis.evidence_cell_draft.v1"],
              skill_files=["SKILL.md", "references/evidence-table.md"])
    si["sources"] = [s for s in si["sources"] if s["source_id"] == SOURCE]
    si["passages"] = [p for p in si["passages"] if p["source_id"] == SOURCE]
    si["allowlist"] = {"candidate_ids": [], "source_ids": [SOURCE], "passage_ids": [p["passage_id"] for p in si["passages"]]}
    column = {"revision": 1, "options": None, "allow_multiple": False, "unit_hint": None}
    si["extraction_target"] = {"table_id": "tbl_SYNTHA0001", "source_id": SOURCE, "passage_scope": {"given": 2, "available": 2, "all_pages_given": True},
                               "columns": [
        column | {"column_id": "col_SYNMETHOD1", "name": "Method", "instruction": "Name the optimization method.", "answer_format": "text"},
        column | {"column_id": "col_SYNCLASS01", "name": "Program class", "instruction": "Which program class is used?", "answer_format": "choice",
                  "options": [{"id": "o1", "label": "MILP"}, {"id": "o2", "label": "Heuristic"}]},
        column | {"column_id": "col_SYNBUDGET1", "name": "Molecule budget", "instruction": "Report the molecule budget per frame.",
                  "answer_format": "number_unit", "unit_hint": "molecules"},
        column | {"column_id": "col_SYNMEASUR1", "name": "Measured", "instruction": "Are results measured in a laboratory?", "answer_format": "yes_no"},
    ]}
    return si


def cell_draft(si):
    envelope = {"schema_version": "deixis.evidence_cell_draft.v1"} | {k: si[k] for k in contracts.ENVELOPE_FIELDS}
    return envelope | {"cells": [
        {"column_id": "col_SYNMETHOD1", "state": "value", "value": {"text": "Mixed-integer linear program with binary release variables"},
         "note": None, "evidence": [{"passage_id": "psg_SYNA1abs01", "quote": "We formulate release-time scheduling as a mixed-integer linear program"}]},
        {"column_id": "col_SYNCLASS01", "state": "value", "value": {"option_ids": ["o1"]}, "note": None,
         "evidence": [{"passage_id": "psg_SYNA1abs01", "quote": "a mixed-integer linear program with binary release variables"}]},
        {"column_id": "col_SYNBUDGET1", "state": "unknown", "value": None, "note": "A budget is named without a number.",
         "evidence": [{"passage_id": "psg_SYNA1pg003", "quote": "subject to a total molecule budget per frame"}]},
        {"column_id": "col_SYNMEASUR1", "state": "not_found_in_inspected_scope", "value": None, "note": None, "evidence": []},
    ]}


def test_a_valid_cell_draft_passes_and_links_carry_the_passage_words():
    si = cell_step_input()
    assert contracts.check_step_input(si) == []
    draft = cell_draft(si)
    report = contracts.validate_model_output(si, draft)
    assert report.ok, [vars(i) for i in report.issues]
    link = contracts.cell_links(si, draft["cells"][2])[0]
    assert link == {"passage_id": "psg_SYNA1pg003", "source_version_id": SOURCE,
                    "anchor_text": "subject to a total molecule budget per frame", "anchor_match": "exact"}


def other_version_passage(cell):
    cell["evidence"] = [{"passage_id": "psg_SYNA3pg002", "quote": "Relay positions are chosen by a heuristic"}]


@pytest.mark.parametrize("change, codes", [
    (lambda d: d["cells"].pop(3), ["column_without_answer"]),
    (lambda d: d["cells"].append(copy.deepcopy(d["cells"][0])), ["duplicate_column_answer"]),
    (lambda d: d["cells"][0].update(column_id="col_SYNUNKNOWN"), ["column_without_answer", "unknown_column_id"]),
    (lambda d: other_version_passage(d["cells"][0]), ["unknown_passage_id"]),
    (lambda d: d["cells"][1].update(value={"option_ids": ["o9"]}), ["invalid_cell_value"]),
    (lambda d: d["cells"][1].update(value={"option_ids": ["o1", "o2"]}), ["invalid_cell_value"]),
    (lambda d: d["cells"][2].update(state="value", value={"text": "a budget"}), ["invalid_cell_value"]),
    (lambda d: d["cells"][0].update(value=None), ["invalid_cell_value"]),
    (lambda d: d["cells"][3].update(value={"answer": "yes"}), ["invalid_cell_value"]),
    (lambda d: d["cells"][0].update(value={"text": "x" * 501}), ["schema_invalid"]),
    (lambda d: d["cells"][3].update(value={"answer": "unclear"}), ["schema_invalid"]),
    (lambda d: d["cells"][0]["evidence"][0].update(quote="SYNTHETIC. This sentence is not in the passage."), ["anchor_not_in_passage"]),
    (lambda d: d["cells"][0].update(evidence=[]), ["value_without_evidence"]),
    (lambda d: d["cells"][2].update(evidence=[]), ["unknown_without_evidence"]),
    (lambda d: d["cells"][3].update(evidence=copy.deepcopy(d["cells"][0]["evidence"])), ["evidence_for_not_found"]),
    (lambda d: d["cells"][3].update(state="not_applicable"), ["not_applicable_without_note"]),
    (lambda d: d["cells"][2].update(note="The budget is set on page 3."), ["locator_in_note"]),
    (lambda d: d["cells"][0]["evidence"].append(copy.deepcopy(d["cells"][0]["evidence"][0])), ["duplicate_evidence_quote"]),
])
def test_cell_draft_checks(change, codes):
    si = cell_step_input()
    draft = cell_draft(si)
    change(draft)
    assert contracts.validate_model_output(si, draft).codes() == codes


def test_a_cell_may_quote_one_passage_more_than_once_but_not_repeat_a_quote():
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][0]["evidence"].append({"passage_id": "psg_SYNA1abs01", "quote": "an inter-symbol interference constraint"})
    report = contracts.validate_model_output(si, draft)
    assert report.ok, [vars(i) for i in report.issues]
    assert [(link["passage_id"], link["anchor_text"]) for link in contracts.cell_links(si, draft["cells"][0])] == [
        ("psg_SYNA1abs01", "We formulate release-time scheduling as a mixed-integer linear program"),
        ("psg_SYNA1abs01", "an inter-symbol interference constraint"),
    ]

    # A second quote that locates the same words of the passage adds no evidence.
    same_words = cell_draft(si)
    same_words["cells"][0]["evidence"].append({"passage_id": "psg_SYNA1abs01", "quote": "we formulate release-time  scheduling as a mixed-integer linear program"})
    assert contracts.validate_model_output(si, same_words).codes() == ["duplicate_evidence_quote"]


def test_a_quote_that_is_in_another_given_passage_of_the_source_names_that_passage_but_is_not_moved():
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][0]["evidence"] = [{"passage_id": "psg_SYNA1abs01", "quote": "subject to a total molecule budget per frame"}]
    (issue,) = contracts.validate_model_output(si, draft).issues
    assert issue.code == "anchor_not_in_passage" and "psg_SYNA1pg003" in issue.message
    assert draft["cells"][0]["evidence"][0]["passage_id"] == "psg_SYNA1abs01"
    assert contracts.cell_links(si, draft["cells"][0])[0]["anchor_text"] is None

    nowhere = cell_draft(si)
    nowhere["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC. This sentence is not in any passage."
    (issue,) = contracts.validate_model_output(si, nowhere).issues
    assert issue.code == "anchor_not_in_passage" and "psg_SYNA1pg003" not in issue.message


@pytest.mark.parametrize("state", ["not_reported", "inaccessible", "not_verified"])
def test_a_model_cannot_write_a_person_or_system_state(state):
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][3]["state"] = state
    report = contracts.validate_model_output(si, draft)
    # The value rule may trip on the same cell and is then reported with the schema error, so one repair sees both.
    assert report.issues[0].code == "schema_invalid" and report.issues[0].path == "/cells/3/state"
    assert set(report.codes()) <= {"schema_invalid", "invalid_cell_value"}


def test_cell_steps_show_short_handles_that_map_back_to_records():
    si = cell_step_input()
    shown = contracts.with_citation_handles(si)
    assert [c["column_id"] for c in shown["extraction_target"]["columns"]] == [f"col_C{n:07d}" for n in range(1, 5)]
    assert shown["extraction_target"]["source_id"] == "srv_S0000001" and contracts.check_step_input(shown) == []

    draft = cell_draft(si)
    handles = contracts.citation_handles(si)
    for cell in draft["cells"]:
        cell["column_id"] = handles[cell["column_id"]]
        for item in cell["evidence"]:
            item["passage_id"] = handles[item["passage_id"]]
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert contracts.validate_model_output(si, resolved).ok
    assert resolved["cells"][2]["column_id"] == "col_SYNBUDGET1" and resolved["cells"][2]["evidence"][0]["passage_id"] == "psg_SYNA1pg003"


def test_a_cell_step_input_reads_one_source_only():
    si = cell_step_input()
    other = next(s for s in STEP_INPUTS["A_answer"]["sources"] if s["source_id"] == "srv_SYNA3pre01")
    passage = next(p for p in STEP_INPUTS["A_answer"]["passages"] if p["source_id"] == "srv_SYNA3pre01")
    si["sources"].append(other)
    si["passages"].append(passage)
    si["allowlist"]["source_ids"].append(other["source_id"])
    si["allowlist"]["passage_ids"].append(passage["passage_id"])
    assert {i.code for i in contracts.check_step_input(si)} == {"extraction_source_mismatch", "passage_outside_extraction_source"}

    too_many = cell_step_input()
    too_many["extraction_target"]["columns"] *= 3
    assert [i.code for i in contracts.check_step_input(too_many)] == ["extraction_column_count"]
    untargeted = cell_step_input()
    del untargeted["extraction_target"]
    assert [i.code for i in contracts.check_step_input(untargeted)] == ["extraction_target_mismatch"]


def test_an_invalid_output_keeps_only_well_formed_answers_for_storage():
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC. Not in the passage."  # kept; shown as invalid
    draft["cells"][1]["value"] = {"option_ids": ["o9"]}  # no storable value
    draft["cells"][2]["evidence"].append({"passage_id": "psg_SYNA3pg002", "quote": "Relay positions are chosen by a heuristic"})
    draft["cells"][3]["state"] = "not_reported"  # a person's state
    kept = contracts.storable_cells(si, json.dumps(draft))
    assert [c["column_id"] for c in kept] == ["col_SYNMETHOD1", "col_SYNBUDGET1"]
    assert [e["passage_id"] for e in kept[1]["evidence"]] == ["psg_SYNA1pg003"]
    assert contracts.cell_links(si, kept[0])[0]["anchor_text"] is None
    assert contracts.storable_cells(si, "not json") == []


def test_column_proposal_checks():
    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    si.update(task_type="table_columns", output_schema_versions=["deixis.table_column_proposal.v1"])
    si["extraction_target"] = {"table_id": "tbl_SYNTHA0001", "source_id": None, "passage_scope": None,
                               "columns": cell_step_input()["extraction_target"]["columns"][:1]}
    assert contracts.check_step_input(si) == []
    envelope = {"schema_version": "deixis.table_column_proposal.v1"} | {k: si[k] for k in contracts.ENVELOPE_FIELDS}
    column = {"name": "Objective", "instruction": "What does the model minimize or maximize?", "answer_format": "choice",
              "options": [{"label": "Error probability"}, {"label": "Energy"}], "allow_multiple": True, "unit_hint": None,
              "rationale": "The question asks for objectives."}
    assert contracts.validate_model_output(si, envelope | {"columns": [column], "notes": ""}).ok
    renamed = column | {"name": " method"}
    assert contracts.validate_model_output(si, envelope | {"columns": [column, column, renamed], "notes": ""}).codes() == ["duplicate_column_name"]
    unit_on_yes_no = column | {"answer_format": "yes_no", "options": None, "allow_multiple": False, "unit_hint": "s"}
    assert contracts.validate_model_output(si, envelope | {"columns": [unit_on_yes_no], "notes": ""}).codes() == ["invalid_column_definition"]


# ---- fill and recheck runs ----------------------------------------------------------------------
def add_pdf(store, svid, pages, sha):
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=len(pages),
                                 pages=[SimpleNamespace(physical_page=n, printed_label=None, text=text) for n, text in enumerate(pages, 1)])
    return store.add_asset_with_pages(svid, sha, 10, f"{sha}.pdf", "user_upload", None, "p.pdf", extraction, "test-v1",
                                      lambda text: [(0, len(text), text)])


def library(path, responder=valid_response):
    """A research with a published PDF, a preprint of the same work with only an abstract, and a source without text."""
    conn = db.connect(path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    published = store.create_upload_source("A SYNTHETIC packet size study")
    preprint = new_id("srv")
    with transaction(conn):
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at) VALUES (?, ?, ?, 'provider', 'submittedVersion', ?)",
                     (preprint, store.source(published)["work_id"], "B SYNTHETIC packet size preprint", now()))
        store._insert_passage(preprint, None, "abstract", None, None, "provider", None, None, "SYNTHETIC preprint: packets of 64 bytes were evaluated.")
    add_pdf(store, published, ["SYNTHETIC page one: packets of 128 bytes minimize energy per bit.", "SYNTHETIC page two: a relay forwards each packet once."], "1" * 64)
    no_text = store.create_upload_source("C SYNTHETIC scanned report")
    for svid in (published, preprint, no_text):
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    tid = tables.create_table(rid, "Packets", None, None, None)
    cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=path / "data", port=8765), store, {"fake": adapter}, skill.load_skill_package(), None))
    return SimpleNamespace(conn=conn, store=store, tables=tables, rid=rid, published=published, preprint=preprint, no_text=no_text,
                           tid=tid, cid=cid, adapter=adapter, flow=flow)


def execute(lib, run):
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def table_version(lib):
    return lib.tables.table_view(lib.rid, lib.tid)["table"]["version"]


def fill(lib, **options):
    return lib.tables.request_fill(lib.rid, lib.tid, options.get("column_ids"), options.get("include_stale", False), table_version(lib), None)


def recheck(lib, svid, version):
    return lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, svid, version, None)


def cell(lib, svid, cid=None):
    return lib.tables.cell_view(lib.rid, lib.tid, cid or lib.cid, svid)


def stored_inputs(lib, run_id):
    return [json.loads(r[0]) for r in lib.conn.execute("SELECT payload_json FROM step_inputs WHERE run_id = ? ORDER BY created_at", (run_id,))]


def passage_ids(lib, svid):
    return {p["id"] for p in lib.store.passages_for(svid)}


def test_fill_links_each_cell_to_its_own_source_version_and_skips_the_model_without_text(tmp_path):
    lib = library(tmp_path)
    run = fill(lib)
    assert run["kind"] == "table_fill" and run["stage"] == "extraction" and run["budget"]["max_model_calls"] == 4
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2  # the source without text had no model call

    published, preprint, no_text = cell(lib, lib.published), cell(lib, lib.preprint), cell(lib, lib.no_text)
    assert published["current"]["kind"] == "model_fill" and published["current"]["value"] == {"number": 128, "unit": "byte", "as_stated": None}
    assert published["current"]["reading_depth"] == "selected_sections" and published["current"]["model"]["resolved_model"] == "fake-model"
    assert {e["passage_id"] for e in published["current"]["evidence"]} <= passage_ids(lib, lib.published)
    assert published["current"]["evidence"][0]["anchor_match"] == "exact"
    assert preprint["current"]["reading_depth"] == "abstract"
    assert {e["passage_id"] for e in preprint["current"]["evidence"]} <= passage_ids(lib, lib.preprint)
    assert (no_text["current"]["kind"], no_text["current"]["state"], no_text["current"]["author"]) == ("system_fill", "inaccessible", "system")

    for payload in stored_inputs(lib, run["id"]):
        target = payload["extraction_target"]
        assert {p["source_id"] for p in payload["passages"]} == {target["source_id"]} and payload["human_corrections"] == []
        assert set(payload["allowlist"]["passage_ids"]) == passage_ids(lib, target["source_id"])
    scopes = {p["extraction_target"]["source_id"]: p["extraction_target"]["passage_scope"] for p in stored_inputs(lib, run["id"])}
    assert scopes[lib.published] == {"given": 2, "available": 2, "all_pages_given": True}
    assert scopes[lib.preprint] == {"given": 1, "available": 1, "all_pages_given": False}
    with pytest.raises(InvalidTableInput):
        fill(lib)  # nothing is left to fill


def test_a_resumed_fill_or_recheck_does_not_add_revisions_or_calls(tmp_path):
    lib = library(tmp_path)
    run = fill(lib)
    execute(lib, run)
    revisions = lib.conn.execute("SELECT COUNT(*) FROM cell_revisions").fetchone()[0]
    assert execute(lib, run)["status"] == "completed"  # e.g. resumed after a restart that came after the last write
    assert lib.conn.execute("SELECT COUNT(*) FROM cell_revisions").fetchone()[0] == revisions and len(lib.adapter.calls) == 2

    checked = recheck(lib, lib.published, 1)
    execute(lib, checked)
    execute(lib, checked)
    assert [r["kind"] for r in cell(lib, lib.published)["revisions"]] == ["model_fill", "model_proposal"] and len(lib.adapter.calls) == 3


def nine_columns(lib):
    for n in range(8):
        lib.tables.add_column(lib.rid, lib.tid, {"name": f"Field {n}", "instruction": "Report the field as stated.", "answer_format": "text",
                                                 "options": None, "allow_multiple": False, "unit_hint": None}, table_version(lib), None)


def test_a_source_answers_at_most_eight_columns_per_call_and_a_spent_budget_pauses_the_fill(tmp_path):
    lib = library(tmp_path / "full")
    nine_columns(lib)
    run = fill(lib)
    assert run["budget"]["max_model_calls"] == 8
    assert execute(lib, run)["status"] == "completed"
    assert [len(call["extraction_target"]["columns"]) for call in lib.adapter.calls] == [8, 1, 8, 1]

    lib = library(tmp_path / "budget")
    nine_columns(lib)
    run = fill(lib)
    lib.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(run["budget"] | {"max_model_calls": 1}), run["id"]))
    stopped = execute(lib, run)
    assert (stopped["status"], stopped["pause_reason"]) == ("paused", "budget_exhausted")
    view = lib.tables.table_view(lib.rid, lib.tid)
    assert sum(c["current"] is not None for c in view["cells"] if c["source_version_id"] == lib.published) == 8
    assert view["fill_estimate"]["sources"] == 3  # the cells left empty can be filled again


def test_a_fill_reads_at_most_25_sources(tmp_path):
    lib = library(tmp_path)
    rid = lib.store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    for n in range(26):
        svid = lib.store.create_upload_source(f"SYNTHETIC source {n:02d}")
        with transaction(lib.conn):
            lib.store._insert_passage(svid, None, "abstract", None, None, "user", None, None, f"SYNTHETIC abstract {n}: packets of {n} bytes.")
        lib.store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    tid = lib.tables.create_table(rid, "Many", None, None, None)
    lib.tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    plan = lib.tables.fill_plan(rid, tid)
    assert (len(plan["sources"]), plan["sources_beyond_limit"], plan["model_calls"], plan["max_model_calls"]) == (25, 1, 25, 50)


def test_a_stale_fill_only_proposes(tmp_path):
    lib = library(tmp_path)
    execute(lib, fill(lib))
    column = lib.tables.table_view(lib.rid, lib.tid)["columns"][0]
    lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"instruction": "Report the largest packet size."}, None, column["version"])
    with pytest.raises(InvalidTableInput):
        fill(lib)
    execute(lib, fill(lib, include_stale=True))
    view = cell(lib, lib.published)
    assert view["current"]["kind"] == "model_fill" and view["pending_proposal"]["column_revision"] == 2
    assert "stale_column" in view["flags"] and cell(lib, lib.no_text)["pending_proposal"] is None


def test_t09m_a_recheck_does_not_show_the_model_the_human_value_and_waits_as_a_proposal(tmp_path):
    lib = library(tmp_path)
    human = lib.tables.edit_cell(lib.rid, lib.tid, lib.cid, lib.published, "not_verified", {"number": 987654.321, "unit": "HUMANUNIT"},
                                 "HUMAN-NOTE-SENTINEL", None, 0, None)
    run = recheck(lib, lib.published, 1)
    assert run["target"] == {"table_id": lib.tid, "column_id": lib.cid, "source_version_id": lib.published, "cell_version": 1}
    assert execute(lib, run)["status"] == "completed"
    view = cell(lib, lib.published)
    assert view["current"]["id"] == human and view["pending_proposal"]["output_status"] == "structurally_valid" and view["flags"] == []
    (row,) = lib.conn.execute("SELECT payload_json, user_message FROM step_inputs WHERE run_id = ?", (run["id"],)).fetchall()
    for text in (row["payload_json"], row["user_message"]):
        assert not any(word in text for word in ("987654", "HUMANUNIT", "HUMAN-NOTE-SENTINEL"))
    assert json.loads(row["payload_json"])["human_corrections"] == []


def test_recheck_reads_only_this_source_versions_retained_passages(tmp_path):
    def cite_the_preprint(si):
        draft = json.loads(valid_response(si))
        draft["cells"][0]["evidence"] = [{"passage_id": preprint_abstract, "quote": "packets of 64 bytes were evaluated"}]
        return json.dumps(draft)

    lib = library(tmp_path, cite_the_preprint)
    preprint_abstract = next(iter(passage_ids(lib, lib.preprint)))
    # One PDF is in use at a time (D45): the fixture's file is withdrawn, a wrong file added and withdrawn, then the pages added again.
    (first,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    lib.store.remove_asset(lib.rid, lib.published, first)
    withdrawn = add_pdf(lib.store, lib.published, ["SYNTHETIC withdrawn page: packets of 512 bytes."], "2" * 64)
    lib.store.remove_asset(lib.rid, lib.published, withdrawn)
    add_pdf(lib.store, lib.published, ["SYNTHETIC page one: packets of 128 bytes minimize energy per bit.", "SYNTHETIC page two: a relay forwards each packet once."], "3" * 64)
    run = recheck(lib, lib.published, 0)
    assert execute(lib, run)["status"] == "completed"
    (payload,) = stored_inputs(lib, run["id"])[:1]
    assert set(payload["allowlist"]["passage_ids"]) == passage_ids(lib, lib.published) and len(payload["passages"]) == 2
    assert preprint_abstract not in payload["allowlist"]["passage_ids"]

    # The model cited the preprint of the same work twice: rejected, kept as an invalid proposal without that evidence.
    assert len(lib.adapter.calls) == 2
    step = lib.conn.execute("SELECT status, error_code, error_json FROM run_steps WHERE run_id = ? AND operation_key = 'cell_recheck'",
                            (run["id"],)).fetchone()
    assert (step["status"], step["error_code"]) == ("failed", "invalid_model_output") and "unknown_passage_id" in step["error_json"]
    view = cell(lib, lib.published)
    assert view["current"] is None and view["pending_proposal"]["evidence"] == [] and "proposal_invalid" in view["flags"]
    with pytest.raises(InvalidTableInput):
        lib.tables.decide_proposal(lib.rid, lib.tid, lib.cid, lib.published, view["pending_proposal"]["id"], True, view["version"], None)


def test_a_repair_message_names_passages_and_columns_by_the_handles_the_model_saw(tmp_path):
    attempts = []

    def wrong_passage_first(si):
        draft = json.loads(valid_response(si))
        if not attempts:  # quote page two under page one's handle
            draft["cells"][0]["evidence"] = [{"passage_id": si["passages"][0]["passage_id"], "quote": si["passages"][1]["text"]}]
        attempts.append(si["step_input_id"])
        return json.dumps(draft)

    lib = library(tmp_path, wrong_passage_first)
    run = recheck(lib, lib.published, 0)
    assert execute(lib, run)["status"] == "completed" and len(attempts) == 2
    (repair,) = lib.conn.execute("SELECT user_message FROM step_inputs WHERE run_id = ? AND attempt = 1", (run["id"],)).fetchone()
    issues = json.loads(repair.split("not in the allowlist.\n", 1)[1])
    assert [i["code"] for i in issues] == ["anchor_not_in_passage"]
    assert issues[0]["message"].startswith("col_C0000001:psg_P0000001:") and "psg_P0000002" in issues[0]["message"]
    assert not any(record in repair for record in passage_ids(lib, lib.published) | {lib.cid, lib.published})
    assert cell(lib, lib.published)["pending_proposal"]["output_status"] == "structurally_valid"


def test_a_recheck_without_any_storable_answer_fails_the_run(tmp_path):
    lib = library(tmp_path, lambda si: "not json")
    stopped = execute(lib, recheck(lib, lib.published, 0))
    assert (stopped["status"], stopped["pause_reason"]) == ("failed", "invalid_model_output")
    assert cell(lib, lib.published)["revisions"] == []


# ---- API ------------------------------------------------------------------------------------------
def table_url(rid, tid):
    return f"/api/researches/{rid}/tables/{tid}"


def test_fill_and_column_suggestion_api(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload(client, rid, "a.pdf", "SYNTHETIC packets of 128 bytes minimize energy per bit.")
        tid = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()["table"]["id"]
        view = client.post(f"{table_url(rid, tid)}/columns", json=PACKET_SIZE | {"expected_version": 1}).json()
        assert view["fill_estimate"] == {"sources": 1, "sources_without_text": 0, "sources_beyond_limit": 0, "model_calls": 1, "max_model_calls": 2}
        version = view["table"]["version"]

        assert client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version - 1}).status_code == 409
        assert client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version, "column_ids": ["col_missing000000"]}).status_code == 422
        started = client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version}, headers={"Idempotency-Key": "f1"})
        assert started.status_code == 202, started.text
        replay = client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version}, headers={"Idempotency-Key": "f1"})
        assert replay.json()["id"] == started.json()["id"]
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed" and run["target"]["sources"][0]["column_ids"] == [view["columns"][0]["id"]]
        filled = client.get(table_url(rid, tid)).json()
        assert filled["cells"][0]["current"]["kind"] == "model_fill" and filled["cells"][0]["current"]["evidence"][0]["anchor_match"] == "exact"
        assert client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version}).status_code == 422

        suggested = client.post(f"{table_url(rid, tid)}/column-suggestions", headers={"Idempotency-Key": "s1"})
        assert suggested.status_code == 202
        _, run = wait_run(client, rid, suggested.json()["id"])
        assert run["status"] == "completed"
        suggestions = client.get(table_url(rid, tid)).json()["column_suggestions"]
        assert [c["name"] for c in suggestions["columns"]] == ["SYNTHETIC method"]
        assert len(client.get(table_url(rid, tid)).json()["columns"]) == 1  # nothing is added by itself
        spec = {k: suggestions["columns"][0][k] for k in ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")}
        body = spec | {"expected_version": version, "suggestion_step_id": "stp_notASuggestion00"}
        assert client.post(f"{table_url(rid, tid)}/columns", json=body).status_code == 422
        added = client.post(f"{table_url(rid, tid)}/columns", json=body | {"suggestion_step_id": suggestions["step_id"]})
        assert added.status_code == 201 and [c["origin"] for c in added.json()["columns"]] == ["user", "model_suggestion"]


def fill_three_sources(tmp_path, responder):
    """A research with three uploaded PDFs, a one-column table and its fill run started; the responder sees each call."""
    holder = {}
    adapter = FakeAdapter(lambda si: responder(holder, si))
    holder["app"] = app = app_for(tmp_path, adapter)
    return app, adapter, holder


def start_fill(client):
    rid = create(client, source_scope="attached")
    for name, text in (("a.pdf", "SYNTHETIC packets of 128 bytes."), ("b.pdf", "SYNTHETIC packets of 64 bytes."), ("c.pdf", "SYNTHETIC packets of 32 bytes.")):
        upload(client, rid, name, text)
    tid = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()["table"]["id"]
    version = client.post(f"{table_url(rid, tid)}/columns", json=PACKET_SIZE | {"expected_version": 1}).json()["table"]["version"]
    started = client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": version})
    assert started.status_code == 202, started.text
    return rid, tid, started.json()["id"]


def filled_cells(client, rid, tid):
    return [c for c in client.get(table_url(rid, tid)).json()["cells"] if c["current"]]


def test_cancel_during_a_fill_keeps_written_values_and_drops_the_call_in_progress(tmp_path):
    # The Evidence tab's cancel confirmation says: values already written stay, the run cannot be resumed, empty cells can be filled again.
    def responder(holder, si):
        if si["task_type"] == "cell_extraction":
            holder["calls"] = holder.get("calls", 0) + 1
            if holder["calls"] == 2:
                holder["app"].state.store.update_run(si["run_id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
        return valid_response(si)

    app, adapter, _ = fill_three_sources(tmp_path, responder)
    with TestClient(app) as raw:
        client = session(raw)
        rid, tid, run_id = start_fill(client)
        _, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("cancelled", "user_cancelled")
        assert len(adapter.calls) == 2
        assert [c["current"]["kind"] for c in filled_cells(client, rid, tid)] == ["model_fill"]  # the second call's answer is not written
        steps = [s for s in run["steps"] if s["kind"] == "model:cell_extraction"]
        assert [s["status"] for s in steps] == ["succeeded", "succeeded"]  # it stays recorded under the run
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 409

        view = client.get(table_url(rid, tid)).json()
        assert view["fill_estimate"]["sources"] == 2
        again = client.post(f"{table_url(rid, tid)}/fill", json={"expected_version": view["table"]["version"]})
        _, rerun = wait_run(client, rid, again.json()["id"])
        assert rerun["status"] == "completed" and len(filled_cells(client, rid, tid)) == 3


def test_pause_during_a_fill_writes_the_call_result_only_after_resume(tmp_path):
    def responder(holder, si):
        if si["task_type"] == "cell_extraction" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested", pause_reason="user_requested")
        return valid_response(si)

    app, adapter, _ = fill_three_sources(tmp_path, responder)
    with TestClient(app) as raw:
        client = session(raw)
        rid, tid, run_id = start_fill(client)
        _, run = wait_run(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
        assert filled_cells(client, rid, tid) == [] and len(adapter.calls) == 1
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed" and len(filled_cells(client, rid, tid)) == 3
        assert len(adapter.calls) == 3  # the paused call's recorded answer is used; the model is not asked again


def test_t09g_j_recheck_requests(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        for name, text in (("a.pdf", "SYNTHETIC packets of 128 bytes."), ("b.pdf", "SYNTHETIC packets of 64 bytes."), ("c.pdf", "SYNTHETIC packets of 32 bytes.")):
            upload(client, rid, name, text)
        tid = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()["table"]["id"]
        view = client.post(f"{table_url(rid, tid)}/columns", json=PACKET_SIZE | {"expected_version": 1}).json()
        rows, cid = {r["title"]: r["source_version_id"] for r in view["rows"]}, view["columns"][0]["id"]
        url = lambda title: f"{table_url(rid, tid)}/cells/{cid}/{rows[title]}/recheck"  # noqa: E731

        first = client.post(url("a"), json={"expected_version": 0}, headers={"Idempotency-Key": "r1"})
        assert first.status_code == 202, first.text
        assert client.post(url("a"), json={"expected_version": 0}, headers={"Idempotency-Key": "r1"}).json()["id"] == first.json()["id"]
        _, run = wait_run(client, rid, first.json()["id"])
        assert run["status"] == "completed"
        assert client.get(url("a").removesuffix("/recheck")).json()["pending_proposal"]["kind"] == "model_proposal"
        assert client.post(url("a"), json={"expected_version": 5}).status_code == 409
        assert client.post(url("a"), json={"expected_version": 0}, headers={"x-deixis-csrf": "wrong"}).status_code == 403

        conn = app.state.store.conn
        asset = conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (rows["b"],)).fetchone()[0]
        assert client.delete(f"/api/researches/{rid}/sources/{rows['b']}/assets/{asset}").status_code == 200
        assert client.post(url("b"), json={"expected_version": 0}).status_code == 422  # no text left to read
        table = client.get(table_url(rid, tid)).json()["table"]
        assert client.delete(f"{table_url(rid, tid)}/rows/{rows['a']}", params={"expected_version": table["version"]}).status_code == 200
        assert client.post(url("a"), json={"expected_version": 0}).status_code == 422  # the row left the table

        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_ACTIVE00000001', ?, 1, 'answer', 'running', 'answer', '{}', ?, ?)", (rid, now(), now()))
        assert client.post(url("c"), json={"expected_version": 0}).status_code == 409
        conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = 'run_ACTIVE00000001'")


def test_t09k_a_recheck_interrupted_by_a_restart_resumes_into_one_proposal(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload(client, rid, "a.pdf", "SYNTHETIC packets of 128 bytes minimize energy per bit.")
        tid = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()["table"]["id"]
        view = client.post(f"{table_url(rid, tid)}/columns", json=PACKET_SIZE | {"expected_version": 1}).json()
        cid, svid = view["columns"][0]["id"], view["rows"][0]["source_version_id"]
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    run = TableStore(Store(conn)).request_recheck(rid, tid, cid, svid, 0, None)
    conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))
    conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES (?, ?, 'cell_recheck', 'model:cell_extraction', 'running', 1)",
                 (new_id("stp"), run["id"]))
    conn.close()

    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        assert client.get("/api/health").json()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 0}
        stored = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run["id"])
        assert (stored["status"], stored["pause_reason"], stored["steps"][0]["status"]) == ("paused", "backend_restarted", "outcome_unknown")
        client.post(f"/api/runs/{run['id']}/resume")
        _, resumed = wait_run(client, rid, run["id"])
        assert resumed["status"] == "completed"
        revisions = client.get(f"{table_url(rid, tid)}/cells/{cid}/{svid}").json()["revisions"]
        assert [(r["kind"], r["output_status"], r["decision"]) for r in revisions] == [("model_proposal", "structurally_valid", "pending")]
