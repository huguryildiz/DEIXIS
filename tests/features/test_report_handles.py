"""Synthetic checks of per-step report IDs; no model quality or scientific validity claim."""

import asyncio
import copy
import json

import pytest

from deixis.domain import contracts
from deixis.workflow.features.report.report_sections import run_report
from deixis.workflow.run.flow import RunStopped
from fakes import parse_step_input
from test_contracts import CASES, STEP_INPUTS
from test_report_flow import report_flow


OLD_HASH = "sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee"


def fixture(name):
    return copy.deepcopy(STEP_INPUTS[name])


def output(name):
    return copy.deepcopy(next(case["output"] for case in CASES if case["name"] == name))


def at(data, path, replacement=None, *, set_value=False):
    parts = path.split("/")
    for part in parts[:-1]:
        data = data[int(part)] if isinstance(data, list) else data[part]
    key = int(parts[-1]) if isinstance(data, list) else parts[-1]
    if set_value:
        data[key] = replacement
    return data[key]


def section():
    si, draft = fixture("C_report_section_IV"), output("report_section_valid")
    pid, sid = si["passages"][0]["passage_id"], si["sources"][0]["source_id"]
    cid, col = "cel_SYNTHCELL0001", si["allowlist"]["column_ids"][0]
    si["passages"][0]["text_source"] = "text_layer"
    si["passages"][0]["text"] += " SYNTHETIC source math $$x=1$$."
    si["report_target"]["cells"] = [{
        "cell_id": cid, "cell_revision_id": "crv_SYNTHCELL0001", "column_id": col,
        "source_version_id": sid, "state": "value", "value": {"text": "SYNTHETIC"},
        "reading_depth": "abstract", "evidence": [{"passage_id": pid, "quote": si["passages"][0]["text"]}],
    }]
    si["allowlist"]["cell_ids"] = [cid]
    si["report_target"]["validation_context"] = {"source_ids": si["allowlist"]["source_ids"].copy(),
        "column_ids": si["allowlist"]["column_ids"].copy(),
        "cells": [{name: c[name] for name in ("cell_id", "source_version_id", "column_id", "state", "value", "reading_depth")} for c in si["report_target"]["cells"]],
        "accepted_gaps": [], "basis_cells": [], "basis_passages": []}
    draft["claims"][0] |= {"cell_ids": [cid], "count": {
        "numerator_source_ids": [sid], "denominator_source_ids": [sid], "column_id": col},
        "equation_origin": {"passage_id": pid, "text_source": "text_layer"}}
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": None,
                                       "cell_id": cid, "quote": si["passages"][0]["text"]})
    draft["gaps"] = [{"gap_id": "gap9", "kind": "stated_limitation", "text": "SYNTHETIC candidate.",
                       "basis_claim_keys": [], "basis_passage_ids": [pid], "basis_cell_ids": [cid],
                       "nearest_match": {"status": "found", "source_id": sid, "cell_id": cid}}]
    return si, draft


@pytest.mark.parametrize("path,code", [("citation_anchors/0/passage_id", "unknown_passage_id")])
def test_report_section_refuses_fabricated_id_in_each_output_field(path, code):
    si, draft = section()
    prefix = {"unknown_passage_id": "psg_P", "unknown_cell_id": "cel_L",
              "unknown_source_id": "srv_S", "unknown_column_id": "col_C"}[code]
    bad = prefix + "9999999"
    at(draft, path, bad, set_value=True)
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert at(resolved, path) == bad
    validation = contracts.validate_model_output(si, resolved)
    assert not validation.ok
    assert any(issue.code == code and issue.path == "/" + path for issue in validation.issues)


def test_four_report_tasks_store_real_inputs_and_results_but_messages_and_sessions_keep_handles(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")
    asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "valid"
    tasks = set()
    for row in store.conn.execute("SELECT * FROM step_inputs WHERE run_id = ?", (run["id"],)):
        payload = json.loads(row["payload_json"])
        if payload["task_type"] not in contracts.REPORT_TASKS:
            continue
        tasks.add(payload["task_type"])
        shown = parse_step_input(row["user_message"])
        assert shown == contracts.with_citation_handles(payload)
        for real, handle in contracts.report_citation_handles(payload).items():
            assert real not in row["user_message"]
            assert handle in row["user_message"]
        for field in ("passage_ids", "source_ids", "cell_ids", "column_ids"):
            assert len(shown["allowlist"][field]) == len(payload["allowlist"][field])
        assert all("_P000" not in p["passage_id"] for p in payload["passages"])
        assert all("_L000" not in c["cell_id"] for c in payload["report_target"]["cells"])
        assert shown["report_target"]["report_id"] == payload["report_target"]["report_id"]
        assert [c["cell_revision_id"] for c in shown["report_target"]["cells"]] == [
            c["cell_revision_id"] for c in payload["report_target"]["cells"]]
        session = store.model_session(payload["step_input_id"])
        raw = json.loads(session["raw_output"])
        step = store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (row["step_id"],)).fetchone()
        assert json.loads(step[0])["result"] == contracts.resolve_citation_handles(payload, session["raw_output"])
        if payload["task_type"] in ("report_plan", "report_section") and raw.get("citation_anchors", raw.get("glossary")):
            assert "psg_P0000001" in session["raw_output"] or "cel_L0000001" in session["raw_output"]
    assert tasks == set(contracts.REPORT_TASKS)
    for link in store.conn.execute("SELECT passage_id, cell_id, source_version_id FROM report_citation_links"):
        assert not any(value and ("_P000" in value or "_L000" in value or "_S000" in value) for value in link)


@pytest.mark.parametrize("kind,code", [("cell", "unknown_cell_id")])
def test_report_bad_id_after_one_repair_stops_section_without_salvage_or_dropped_citations(tmp_path, monkeypatch, kind, code):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = adapter.responder
    bad = "psg_P9999999" if kind == "passage" else "cel_L9999999"

    def forbidden_salvage(*args):
        pytest.fail("Reports must never call answer salvage")

    from deixis.workflow.features.report import report_sections as sections
    original_links = sections._citation_links

    def guarded_links(payload, draft):
        assert draft["section_id"] != "IV", "Invalid IV output reached citation link construction"
        return original_links(payload, draft)

    monkeypatch.setattr(contracts, "salvage_answer_draft", forbidden_salvage)
    monkeypatch.setattr(sections, "_citation_links", guarded_links)

    def response(si):
        draft = json.loads(original(si))
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            draft["claims"][0]["passage_ids" if kind == "passage" else "cell_ids"] = [bad]
            draft["citation_anchors"][0] |= {"passage_id": bad if kind == "passage" else None,
                                            "cell_id": bad if kind == "cell" else None}
        return json.dumps(draft)

    adapter.responder = response
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    assert reports.section(report_id, "IV")["status"] == "failed"
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert step["error_code"] == "invalid_model_output"
    assert code in {i["code"] for i in json.loads(step["error_json"])}
    sessions = list(store.conn.execute("SELECT raw_output FROM model_sessions WHERE step_id = ?", (step["id"],)))
    assert len(sessions) == 2
    assert all(json.loads(s[0])["claims"][0]["passage_ids" if kind == "passage" else "cell_ids"] == [bad] for s in sessions)
    assert store.conn.execute("SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?",
                              (reports.section(report_id, "IV")["id"],)).fetchone()[0] == 0
