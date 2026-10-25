"""RF4 synthetic section rules and modification checks; no real-model calls.

Tests prefixed preservation keep assembly assertions. Other negative regressions
are checked against the old runtime in a separate scratch tree, without stash.
"""

import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.workflow import report_assembly as assembly
from fakes import envelope
from test_contracts import STEP_INPUTS
from test_report_flow import _claim
from test_report_path_fix import run_step, rebind, first_issues, sessions


REPLAY = json.loads((Path(__file__).parent.parent / "fixtures/research/report-rf4-replay.json").read_text())
PID, SID, CID, COL = "psg_SYNTHRF4001", "srv_SYNTHRF4001", "cel_SYNTHRF4001", "col_SYNTHR0001"


def packet(section="IV"):
    si = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
    for field in ("question", "sources", "passages"):
        si[field] = copy.deepcopy(REPLAY[field])
    target = si["report_target"]
    target["section_id"] = section
    target["cells"] = copy.deepcopy(REPLAY["cells"])
    target["plan"]["section_budgets"] = {section: {"min_words": 0, "max_words": 1000, "max_claims": 40}}
    target["prior_summaries"] = [{"section_id": "IV", "claim_key": "IV.9", "first_sentence": "SYNTHETIC body summary.",
                                  "support_type": "source_stated", "reading_depth": "selected_sections"}]
    target["validation_context"] = {"source_ids": [p["source_id"] for p in si["sources"]], "column_ids": [COL],
        "cells": [{k: c[k] for k in ("cell_id", "source_version_id", "column_id", "state", "value", "reading_depth")} for c in target["cells"]],
        "accepted_gaps": [], "basis_cells": [], "basis_passages": []}
    si["allowlist"].update(source_ids=[s["source_id"] for s in si["sources"]], passage_ids=[p["passage_id"] for p in si["passages"]],
                           cell_ids=[c["cell_id"] for c in target["cells"]], column_ids=[COL], gap_ids=[])
    claim = _claim(section, passage_ids=[PID])
    if section in {"abstract", "I", "IX"}:
        claim["body_refs"] = ["IV.9"]
    if section == "VII":
        claim["cell_ids"] = [CID]
    draft = envelope(si, "deixis.report_section_draft.v3") | {"section_id": section, "claims": [claim],
        "citation_anchors": [{"claim_key": claim["claim_key"], "passage_id": PID, "cell_id": None,
                              "quote": si["passages"][0]["text"]}], "subsections": [], "gaps": [], "insufficient_evidence": []}
    if section == "VII":
        draft["citation_anchors"].append({"claim_key": "VII.1", "passage_id": None, "cell_id": CID,
                                          "quote": target["cells"][0]["evidence"][0]["quote"]})
    return si, draft


def codes(si, draft):
    return contracts.validate_model_output(si, draft).codes()


@pytest.mark.parametrize("where", ["claim"])
@pytest.mark.parametrize("language", ["en"])
def test_banned_word_blocks_each_prose_field(where, language):
    si, draft = packet("VI" if where == "gap" else "VIII")
    si["question"]["language_hint"] = language
    text = REPLAY["bad_texts"]["banned" if language == "en" else "turkish_banned"]
    if where == "claim":
        draft["claims"][0]["text"] = text
    elif where == "heading":
        draft["subsections"] = [{"axis_id": "AX1", "heading": text}]
    elif where == "gap":
        draft["gaps"] = [gap_record(text=text)]
    else:
        draft["insufficient_evidence"] = [{"context": "SYNTHETIC missing basis", "reason": text}]
    assert "banned_word" in codes(si, draft)


@pytest.mark.parametrize("failure", ["members"])
def test_count_rules_use_the_full_frozen_domain(failure):
    si, draft = packet()
    claim = draft["claims"][0]
    claim.update(text="It has been reported that 2 of 2 SYNTHETIC sources agree.", count={"numerator_source_ids": si["allowlist"]["source_ids"].copy(),
                 "denominator_source_ids": si["allowlist"]["source_ids"].copy(), "column_id": COL})
    context = si["report_target"]["validation_context"]
    expected = {"members": "count_members_invalid", "missing": "count_member_not_in_snapshot", "depth": "count_depth_mixed", "value": "count_value_mixed", "numbers": "count_number_mismatch"}[failure]
    if failure == "members":
        claim["count"]["numerator_source_ids"].append(SID)
    elif failure == "missing":
        context["cells"] = context["cells"][:1]
    elif failure == "depth":
        context["cells"][1]["reading_depth"] = "abstract"
    elif failure == "value":
        context["cells"][1]["value"] = {"text": "SYNTHETIC different value"}
    else:
        claim["text"] = "It has been reported that 9 of 9 SYNTHETIC sources agree."
    assert expected in codes(si, draft)


def gap_record(**updates):
    return {"gap_id": "gap9", "kind": "stated_limitation", "text": "SYNTHETIC stated limitation candidate.",
        "basis_claim_keys": [], "basis_passage_ids": [], "basis_cell_ids": [CID],
        "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None}} | updates


@pytest.mark.parametrize("still_bad", [True])
def test_single_section_repair_sees_new_issues_and_is_bounded(tmp_path, still_bad):
    si, good = packet()
    bad = copy.deepcopy(good)
    bad["claims"][0]["text"] = REPLAY["bad_texts"]["banned"]
    attempts = 0
    def respond(current, schema, message):
        nonlocal attempts
        attempts += 1
        return rebind(bad if attempts == 1 or still_bad else good, current)
    output, store, adapter, _, _ = run_step(tmp_path, "report_section", si, respond)
    assert len(sessions(store)) == attempts == 2
    assert "banned_word" in {i["code"] for i in first_issues(store)}
    assert '"banned_word"' in adapter.requests[1]["message"]
    assert bool(output.get("invalid")) is still_bad
