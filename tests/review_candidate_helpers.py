"""SYNTHETIC candidate evidence built through the production stores, without retrieval."""

import copy
import hashlib
import json

import pytest

from deixis.storage import db
from deixis.workflow.candidates.hits import merge_and_cut
from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.review.snapshot import build_snapshot
from tests.review_helpers import report_with_sections, review_lib
from tests.candidates.test_candidate_store import provider_record
from deixis.documents.pdf import Extraction, PageText, chunk_page
from tests.helpers import make_pdf


def add_version(lib, **changes):
    cs = CandidateStore(lib["store"])
    values = dict(claim_statement="SYNTHETIC bounded scheduling reduces delay.",
        conditions=["SYNTHETIC bounded traffic"], critical_assumption="SYNTHETIC stable load",
        nearest_simple_explanation="SYNTHETIC lighter traffic", validation_plan="SYNTHETIC excluded from review",
        elements=[{"kind": kind, "text": "SYNTHETIC " + text} for kind, text in
            (("mechanism", "bounded scheduling"), ("condition", "bounded traffic"), ("outcome", "lower delay"))],
        origin="human_edit", step_input_id=None,
        expected_version=cs.candidate(lib["candidate_id"])["current_version"])
    return cs.add_version(lib["rid"], lib["candidate_id"], **(values | changes))


def search(lib, version_id=None, outcome="completed", *, assessed=True):
    store = lib["store"]
    cs = CandidateStore(store)
    version_id = version_id or lib["candidate_version_id"]
    run = store.create_run(lib["rid"], "kill_search", {}, None, {"candidate_id": lib["candidate_id"]})
    result = cs.start_kill_search(lib["rid"], version_id, run["id"],
        query_block={"setting": ["SYNTHETIC network"], "task": ["SYNTHETIC scheduling"]},
        rendered_queries=[], skipped_terms=[], selection={"model": "SYNTHETIC"})
    records = [provider_record("SYNTHETIC-review-" + str(i), abstract="SYNTHETIC abstract evidence about bounded traffic.") for i in range(3)]
    one = cs.record_query(result["id"], position=1, provider="openalex", query_text="SYNTHETIC first", status="succeeded", records=records, raw_payload_path="SYNTHETIC-query.json")
    two = cs.record_query(result["id"], position=2, provider="openalex", query_text="SYNTHETIC second", status="succeeded", records=[])
    merged = merge_and_cut([one, two], keep=2)
    cs.record_hits(result["id"], merged, {r["source_version_id"]: "stored_passages" for r in merged["kept"]})
    if assessed:
        for i, hit in enumerate(cs.hits(result["id"])):
            if not hit["kept"]:
                continue
            sid = hit["source_version_id"]
            abstract = next(p for p in store.passages_for(sid) if p["kind"] == "abstract")
            text = "SYNTHETIC passage evidence about bounded scheduling and lower delay."
            asset = next((p["asset_id"] for p in store.passages_for(sid) if p["kind"] == "pdf_page"), None)
            if asset is None:
                data = make_pdf([text])
                asset = store.add_asset_with_pages(sid, hashlib.sha256(data).hexdigest(), len(data),
                    "SYNTHETIC-" + sid + ".pdf", "user_upload", None, "SYNTHETIC.pdf",
                    Extraction("succeeded", 1, [PageText(1, None, text)]), "SYNTHETIC-v1", chunk_page)
            pid = next(p["id"] for p in store.passages_for(sid) if p["asset_id"] == asset)
            shown = [{"passage_id": p["id"], "source_id": sid,
                "reading_depth": "abstract" if p["kind"] == "abstract" else "selected_sections",
                "locator": {"kind": p["kind"], "physical_page": p["physical_page"], "printed_label": p["printed_label"]},
                "abstract_origin": p["abstract_origin"], "text_source": None if p["kind"] == "abstract" else "text_layer",
                "text": p["text"]} for p in (abstract, store.passage(pid))]
            step = store.step(run["id"], "SYNTHETIC-assessment-" + str(i), "model:claim_assessment")
            sti = db.new_id("sti")
            store.insert_step_input(step["id"], lib["rid"], run["id"], 0,
                {"step_input_id": sti, "task_type": "claim_assessment", "scope_revision": 1,
                 "skill_package_hash": "sha256:" + "0" * 64, "passages": shown}, "SYNTHETIC base",
                "SYNTHETIC developer", "SYNTHETIC message", {})
            related = i == 0
            quote = {"evidence_kind": "passage", "passage_id": pid, "quote": shown[1]["text"]}
            abstract_quote = {"evidence_kind": "abstract", "passage_id": None, "quote": shown[0]["text"]}
            elements = cs.version(version_id)["elements"]
            cs.publish_assessment(result["id"], sid, assessment_state="assessed", work_relevance="related" if related else "unrelated",
                states_whole_claim=related, note="SYNTHETIC nearest match", step_input_id=sti,
                cells=[{"element_id": e["id"], "relation": "partial_match" if related and j < 2 else "no_match_in_supplied_text",
                    "condition_alignment": "aligned" if related and j < 2 else None, "note": "SYNTHETIC cell",
                    "quotes": ([quote] if j == 0 else [abstract_quote] if j == 1 else []) if related else []}
                       for j, e in enumerate(elements)], whole_claim_quotes=[quote] if related else [])
    if outcome in {"completed", "failed", "stopped"}:
        cs.finish_kill_search(result["id"], outcome)
        store.update_run(run["id"], status="completed" if outcome == "completed" else "failed" if outcome == "failed" else "cancelled")
    elif outcome == "paused":
        cs.set_kill_search_state(result["id"], "paused")
        store.update_run(run["id"], status="paused")
    return cs.kill_search(result["id"])


@pytest.fixture
def candidate_lib(review_lib):
    lib = dict(review_lib)
    lib["rid"] = lib["store"].create_research("SYNTHETIC bounded scheduling question", "attached", "quick", [], "fake", "fake-model", "en")
    cs = CandidateStore(lib["store"])
    candidate = cs.open_from_owner_text(lib["rid"], "SYNTHETIC owner proposal")
    lib["candidate_id"] = candidate["id"]
    lib["candidate_version_id"] = add_version(lib)["id"]
    lib["search"] = search(lib)
    cs.record_owner_decision(lib["rid"], lib["candidate_version_id"], "narrowed", "SYNTHETIC owner reason")
    return lib


def snapshot(lib):
    content, markers = build_snapshot(lib["reader"], lib["rid"], "candidate", lib["candidate_version_id"])
    return lib["reviews"].snapshot(lib["reviews"].add_snapshot(content, markers))


def candidate_body(lib, **changes):
    return dict(target_kind="candidate", target_id=lib["candidate_version_id"], focus="source_support",
        owner_note=None, connection="fake", model="review-model", reasoning_effort="high") | changes


def candidate_context_fixture(value):
    """Explicit context keeps regression tests independent of the old fixture's missing field."""
    return copy.deepcopy(value["review_input"].get("candidate_context") or {
        "candidate_version": 1, "conditions": ["SYNTHETIC condition"], "critical_assumption": "SYNTHETIC assumption",
        "nearest_simple_explanation": None,
        "kill_search": {"outcome": "completed", "found": 1, "kept": 1, "rank_cut": 0, "duplicates": 0,
            "assessed": 1, "unread": 0, "queries_total": 1, "queries_succeeded": 1, "queries_failed": 0, "queries_unknown": 0,
            "reading_depths": {"abstract": 1, "stored_passages": 0, "metadata_only": 0}},
        "status": {"computed": {"status": "undecided", "reasons": ["SYNTHETIC reason"]}, "owner": None},
        "matrix": [{"source_id": value["sources"][0]["source_id"], "reading_depth": "abstract", "work_relevance": "related",
            "states_whole_claim": False, "note": "SYNTHETIC prior reading", "cells": [], "whole_claim_quotes": []}]})


def candidate_response(si):
    from tests.fakes import valid_response
    out = json.loads(valid_response(si))
    context = si["review_input"]["candidate_context"]
    cells = [c for m in context["matrix"] for c in m["cells"] if c["quotes"]]
    target = {"kind": "candidate_element", "ref": cells[0]["element_ref"]} if cells else {"kind": "whole", "ref": None}
    evidence = [{"passage_handle": cells[0]["quotes"][0]["passage_id"], "anchor": cells[0]["quotes"][0]["quote"]}] if cells else []
    out["findings"] = [{"finding_handle": "f1", "target_ref": target,
        "kind": "partially_supported" if cells else "assumption_unstated", "evidence": evidence,
        "rationale": "SYNTHETIC rationale", "possible_impact": "SYNTHETIC impact",
        "suggested_fix": "SYNTHETIC: narrow this element.", "uncertainty": "SYNTHETIC uncertainty"},
        {"finding_handle": "f2", "target_ref": {"kind": "whole", "ref": None}, "kind": "assumption_unstated",
         "evidence": [], "rationale": "SYNTHETIC rationale", "possible_impact": "SYNTHETIC impact",
         "suggested_fix": None, "uncertainty": "SYNTHETIC uncertainty"}]
    return json.dumps(out)
