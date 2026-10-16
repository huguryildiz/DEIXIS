"""Per-cell salvage of a cell extraction output (D68), with SYNTHETIC records and the FakeAdapter only.

A passing test shows how failed answers are kept, retried and stored; it says nothing about how well a model fills cells.
"""

import json

import pytest

from deixis.domain import contracts
from fakes import valid_response
from test_table_extraction import cell, cell_draft, cell_step_input, execute, fill, library, stored_inputs, table_version

BAD_QUOTE = "SYNTHETIC. These words are not in any passage."


def three_columns(lib):
    for name in ("Field A", "Field B"):
        lib.tables.add_column(lib.rid, lib.tid, {"name": name, "instruction": "Report the field as stated.", "answer_format": "text",
                                                 "options": None, "allow_multiple": False, "unit_hint": None}, table_version(lib), None)
    return [c["id"] for c in lib.tables.target_columns(lib.rid, lib.tid)]


def responder(calls, retry_fixes):
    """Field B's quote is wrong in every first call and its repair; a retry fixes it only when `retry_fixes`."""
    def respond(si):
        draft = json.loads(valid_response(si))
        retry = "earlier_issues" in si["extraction_target"]
        calls.append(("retry" if retry else "first", [c["name"] for c in si["extraction_target"]["columns"]]))
        for answer, column in zip(draft["cells"], si["extraction_target"]["columns"]):
            if column["name"] == "Field B" and not (retry and retry_fixes):
                answer["evidence"][0]["quote"] = BAD_QUOTE
        return json.dumps(draft)
    return respond


def published_steps(lib, run_id):
    rows = lib.conn.execute("SELECT operation_key, status, error_code, output_json FROM run_steps WHERE run_id = ?", (run_id,))
    return {r["operation_key"]: dict(r) | {"output": json.loads(r["output_json"]) if r["output_json"] else None}
            for r in rows if lib.published in r["operation_key"]}


@pytest.mark.parametrize("retry_fixes", [True, False])
def test_one_bad_cell_keeps_the_others_and_is_retried_once(tmp_path, retry_fixes):
    calls = []
    lib = library(tmp_path, responder(calls, retry_fixes))
    packet, field_a, field_b = three_columns(lib)
    run = fill(lib)
    assert run["target"]["cell_retry"] is True and run["budget"]["max_model_calls"] == 8  # two batches, four calls each
    assert execute(lib, run)["status"] == "completed"

    # Each source: the call and its repair fail on Field B; one retry asks for Field B alone (and its repair when bad).
    retries = [c for c in calls if c[0] == "retry"]
    assert retries == [("retry", ["Field B"])] * ((1 if retry_fixes else 2) * 2)
    for svid in (lib.published, lib.preprint):
        for cid in (packet, field_a):
            kept = cell(lib, svid, cid)["current"]
            assert (kept["kind"], kept["state"], kept["output_status"]) == ("model_fill", "value", "structurally_valid")
            assert kept["evidence"] and kept["evidence"][0]["anchor_match"] == "exact"
        bad = cell(lib, svid, field_b)["current"]
        if retry_fixes:
            assert (bad["state"], bad["output_status"]) == ("value", "structurally_valid") and bad["evidence"]
        else:
            # Never a verified value: a value without linked evidence, flagged as unverified.
            assert (bad["kind"], bad["state"], bad["output_status"]) == ("model_fill", "not_verified", "unverified_draft")
            assert bad["evidence"] == [] and bad["value"] == {"text": "SYNTHETIC fake value"}

    steps = published_steps(lib, run["id"])
    first, retry = steps[f"cell_extraction:{lib.published}:0"], steps[f"cell_extraction:{lib.published}:0:retry"]
    assert (first["status"], first["error_code"]) == ("failed", "invalid_model_output")
    assert retry["status"] == ("succeeded" if retry_fixes else "failed")
    record = steps[f"cell_salvage:{lib.published}:0"]
    assert record["status"] == "succeeded"
    assert record["output"]["kept"] == [packet, field_a]
    assert record["output"]["dropped"] == [{"column_id": field_b, "codes": ["anchor_not_in_passage"]}]
    assert record["output"]["retry"] == ("valid" if retry_fixes else "failed")
    assert record["output"]["not_verified"] == ([] if retry_fixes else [field_b])

    retry_input = next(p for p in stored_inputs(lib, run["id"]) if p["extraction_target"].get("earlier_issues")
                       and p["extraction_target"]["source_id"] == lib.published)
    assert [c["column_id"] for c in retry_input["extraction_target"]["columns"]] == [field_b]
    (issue,) = retry_input["extraction_target"]["earlier_issues"]
    assert issue["column_id"] == field_b and issue["code"] == "anchor_not_in_passage"
    assert "psg_" not in issue["message"] and contracts.check_step_input(retry_input) == []

    # A resumed run returns every stored step: no call, no revision is added.
    revisions = lib.conn.execute("SELECT COUNT(*) FROM cell_revisions").fetchone()[0]
    sent = len(lib.adapter.calls)
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == sent and lib.conn.execute("SELECT COUNT(*) FROM cell_revisions").fetchone()[0] == revisions


def test_a_fill_planned_before_the_retry_rule_stores_the_bad_cell_as_not_verified_without_a_retry(tmp_path):
    calls = []
    lib = library(tmp_path, responder(calls, retry_fixes=True))
    _, _, field_b = three_columns(lib)
    run = fill(lib)
    # A run frozen before this change: its target has no retry room and its budget no retry calls.
    target = {k: v for k, v in run["target"].items() if k != "cell_retry"}
    lib.conn.execute("UPDATE runs SET target_json = ?, budget_json = ? WHERE id = ?",
                     (json.dumps(target), json.dumps(run["budget"] | {"max_model_calls": 4}), run["id"]))
    assert execute(lib, run)["status"] == "completed"
    assert all(kind == "first" for kind, _ in calls)
    bad = cell(lib, lib.published, field_b)["current"]
    assert (bad["state"], bad["output_status"], bad["evidence"]) == ("not_verified", "unverified_draft", [])
    record = published_steps(lib, run["id"])[f"cell_salvage:{lib.published}:0"]
    assert record["output"]["retry"] == "not_sent"


def test_a_retry_that_fails_as_a_whole_leaves_the_first_value_as_not_verified(tmp_path):
    calls = []
    first_call = responder(calls, retry_fixes=False)
    lib = library(tmp_path, lambda si: "SYNTHETIC not json" if "earlier_issues" in si["extraction_target"] else first_call(si))
    _, _, field_b = three_columns(lib)
    run = fill(lib)
    assert execute(lib, run)["status"] == "completed"
    # The retry was sent and broke as a whole: Field B keeps the first call's value, as it does when no retry is sent.
    bad = cell(lib, lib.published, field_b)["current"]
    assert bad is not None
    assert (bad["kind"], bad["state"], bad["output_status"]) == ("model_fill", "not_verified", "unverified_draft")
    assert bad["evidence"] == [] and bad["value"] == {"text": "SYNTHETIC fake value"}
    record = published_steps(lib, run["id"])[f"cell_salvage:{lib.published}:0"]["output"]
    assert record["retry"] == "failed" and record["retry_step_input_id"]
    assert (record["not_verified"], record["left_empty"]) == ([field_b], [])


def test_a_broken_output_still_fails_as_a_whole(tmp_path):
    lib = library(tmp_path, lambda si: "SYNTHETIC not json")
    run = fill(lib)
    assert execute(lib, run)["status"] == "completed"
    steps = published_steps(lib, run["id"])
    assert not any(key.startswith("cell_salvage:") or key.endswith(":retry") for key in steps)
    assert cell(lib, lib.published)["current"] is None


def test_salvage_splits_only_per_cell_problems():
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][0]["evidence"][0]["quote"] = BAD_QUOTE
    draft["cells"][3]["state"] = "not_applicable"  # without a note
    result = contracts.salvage_cells(si, draft)
    assert [c["column_id"] for c in result["cells"]] == ["col_SYNCLASS01", "col_SYNBUDGET1"]
    assert {k: [i["code"] for i in v] for k, v in result["bad"].items()} == {
        "col_SYNMETHOD1": ["anchor_not_in_passage"], "col_SYNMEASUR1": ["not_applicable_without_note"]}
    assert contracts.salvage_cells(si, cell_draft(si)) is None  # nothing to salvage in a valid output
    twice = cell_draft(si)
    twice["cells"].append(json.loads(json.dumps(twice["cells"][0])))
    assert contracts.salvage_cells(si, twice) is None  # a column answered twice fails the whole output
    broken = cell_draft(si)
    broken["cells"][0]["value"] = {"text": "x" * 501}
    assert contracts.salvage_cells(si, broken) is None  # a schema error fails the whole output
    issues = contracts.earlier_issues(result["bad"])
    assert [(i["column_id"], i["code"]) for i in issues] == [("col_SYNMETHOD1", "anchor_not_in_passage"),
                                                             ("col_SYNMEASUR1", "not_applicable_without_note")]


def test_earlier_issues_belong_to_cell_extraction_and_its_columns():
    si = cell_step_input()
    si["extraction_target"]["earlier_issues"] = [{"column_id": "col_SYNMETHOD1", "code": "anchor_not_in_passage", "message": "m"}]
    assert contracts.check_step_input(si) == []
    si["extraction_target"]["earlier_issues"][0]["column_id"] = "col_SYNOTHER01"
    assert [i.code for i in contracts.check_step_input(si)] == ["earlier_issue_outside_columns"]


def test_a_retry_names_its_columns_by_the_handles_the_model_sees():
    si = cell_step_input()
    si["extraction_target"]["earlier_issues"] = [{"column_id": "col_SYNMETHOD1", "code": "anchor_not_in_passage", "message": "m"}]
    shown = contracts.with_citation_handles(si)
    columns = [c["column_id"] for c in shown["extraction_target"]["columns"]]
    assert shown["extraction_target"]["earlier_issues"][0]["column_id"] == columns[0] != "col_SYNMETHOD1"
    assert si["extraction_target"]["earlier_issues"][0]["column_id"] == "col_SYNMETHOD1"  # the stored input keeps IDs
