"""Synthetic review fixtures; no provider, model or live library access."""

import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.workflow.review.reader import ReviewReader
from deixis.workflow.review.snapshot import build_snapshot, review_step_input_parts
from deixis.workflow.review.store import ReviewStore, resolve_finding
from tests.test_report_assembly import report_with_sections
from tests.test_report_edit_check import finish

INPUTS = json.loads((Path(__file__).parent / "fixtures/research/step-inputs.json").read_text())


def si(kind="answer"):
    return copy.deepcopy(INPUTS["R_owner_review_" + kind])


def output(step_input=None):
    step_input = step_input or si()
    return {"schema_version": "deixis.owner_review.v1", **{k: step_input[k] for k in contracts.ENVELOPE_FIELDS},
            "findings": [], "supported_points": [], "context_limits": [], "notes": "SYNTHETIC assessment."}


def finding(step_input=None, **changes):
    step_input = step_input or si()
    return {"finding_handle": "f1", "target_ref": {"kind": "claim", "ref": step_input["allowlist"]["claim_refs"][0]},
            "kind": "overstated", "evidence": [{"passage_handle": step_input["passages"][0]["passage_id"],
                                                   "anchor": step_input["passages"][0]["text"]}],
            "rationale": "SYNTHETIC reason.", "possible_impact": "SYNTHETIC impact.",
            "suggested_fix": "SYNTHETIC suggested text.", "uncertainty": "SYNTHETIC scope limit.", **changes}


def make_answer(lib, status="structurally_valid", text="SYNTHETIC answer claim."):
    store = lib["store"]
    run = store.create_run(lib["rid"], "answer", {}, None)
    step = store.step(run["id"], db.new_id("op"), "model:grounded_answer")
    input_id = db.new_id("sti")
    store.insert_step_input(step["id"], lib["rid"], run["id"], 0,
        {"step_input_id": input_id, "task_type": "grounded_answer", "scope_revision": 1,
         "skill_package_hash": skill.package_hash()}, "base", "developer", "message", {})
    aid = store.save_answer(lib["rid"], run["id"], step["id"], input_id, 1, status,
        {"title": "SYNTHETIC answer", "answer_language": "en", "claims": [{"claim_label": "c1", "section": "Methods",
          "text": text, "support_type": "source_stated"}]}, {},
        [{"claim_label": "c1", "passage_id": lib["section_passage"], "source_id": lib["source_id"],
          "anchor_text": "selected-section evidence", "anchor_match": "exact"}])
    store.update_run(run["id"], status="completed")
    return aid


@pytest.fixture
def review_lib(report_with_sections):
    lib = report_with_sections
    lib["rid"] = finish(lib)
    lib["conn"] = lib["store"].conn
    # Include a frozen cell citation to exercise the full report boundary.
    claim_id = lib["conn"].execute("SELECT id FROM report_claims WHERE claim_key = 'III.1'").fetchone()[0]
    lib["conn"].execute("INSERT INTO report_citation_links (id, claim_id, cell_id, source_version_id, step_input_id, anchor_text, anchor_match)"
                        " VALUES (?, ?, ?, ?, ?, ?, 'exact')",
                        (db.new_id("rln"), claim_id, lib["cell_id"], lib["source_id"], lib["report_input_id"], "selected-section evidence"))
    lib["answer_id"] = make_answer(lib)
    lib["reader"] = ReviewReader(lib["store"], lib["reports"])
    lib["reviews"] = ReviewStore(lib["conn"], lib["reader"])
    return lib


def snapshot(lib, kind="report"):
    target_id = lib[kind + "_id"]
    content, markers = build_snapshot(lib["reader"], lib["rid"], kind, target_id)
    sid = lib["reviews"].add_snapshot(content, markers)
    return lib["reviews"].snapshot(sid)


def review_run(lib, kind="review", research_id=None):
    run_id = db.new_id("run")
    lib["conn"].execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                        " VALUES (?, ?, 1, ?, 'completed', 'claim_check', '{}', ?, ?)",
                        (run_id, research_id or lib["rid"], kind, db.now(), db.now()))
    return run_id


def step_payload(lib, saved, run_id=None, model=None, **parts_args):
    run_id = run_id or review_run(lib)
    step = lib["store"].step(run_id, db.new_id("op"), "model:owner_review")
    payload = si(saved["target_kind"])
    payload.update(step_input_id=db.new_id("sti"), research_id=lib["rid"], run_id=run_id, step_id=step["id"],
                   scope_revision=saved["content"]["scope_revision"], skill_package_hash=skill.package_hash(),
                   question={"text": saved["content"]["scope"]["question"], "language_hint": saved["content"]["scope"]["language"]},
                   user_steering=[saved["content"]["scope"]["steering"]] if saved["content"]["scope"]["steering"] else [])
    parts = review_step_input_parts(saved["id"], saved["content"], focus="source_support", owner_note=None, **parts_args)
    payload.update(parts)
    if model is not None:
        payload["model"] = model
    assert contracts.check_step_input(payload) == []
    lib["store"].insert_step_input(step["id"], lib["rid"], run_id, 0, payload, "base", "developer", "message", contracts.step_output_schema("owner_review"))
    return payload


def stored_review(lib, kind="report"):
    saved = snapshot(lib, kind)
    run_id = review_run(lib)
    review = lib["reviews"].create_review(lib["rid"], saved["id"], run_id, focus="source_support", requested_connection="fake")
    payload = step_payload(lib, saved, run_id)
    resolved = resolve_finding(saved["content"], payload, finding(payload))
    fid = lib["reviews"].add_findings(review["id"], [{"finding": resolved, "step_input_id": payload["step_input_id"]}])[0]
    return saved, review, payload, fid


def rows(conn, table):
    return sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')), key=repr)


def all_rows(conn):
    return {r[0]: rows(conn, r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
