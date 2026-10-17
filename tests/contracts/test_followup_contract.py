"""The follow-up answer contract (UI parity S22a, F17) with SYNTHETIC fixtures. Passing shows the schema, identifier
scope, anchor and method-package rules hold in code; it does not show that any model follows the method file."""

import json
import shutil
from pathlib import Path

from deixis.domain import contracts, skill
from deixis.paths import SKILL_DIR
from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = {c["name"]: c for c in json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]}


def test_the_followup_contract_is_registered_and_its_step_input_is_valid():
    assert contracts.SCHEMA_FILES["FollowupAnswer"] == "followup-answer.schema.json"
    assert contracts.SCHEMA_VERSIONS["FollowupAnswer"] == "deixis.followup_answer.v5"
    assert contracts.TASK_OUTPUTS["followup_answer"] == ("FollowupAnswer",)
    Draft202012Validator.check_schema(contracts.load_schema("FollowupAnswer"))
    assert contracts.strict_compatibility_issues(contracts.model_output_schema("followup_answer")) == []
    si = STEP_INPUTS["K_followup_answer"]
    assert contracts.check_step_input(si) == []
    # The allowlist must resolve to the records the step input carries, as for every task.
    broken = json.loads(json.dumps(si))
    broken["allowlist"]["passage_ids"].append("psg_SYNA5abs01")
    assert {i.code for i in contracts.check_step_input(broken)} == {"allowlist_without_record"}


def test_handles_shown_to_the_model_resolve_back_and_links_carry_located_anchors():
    si = STEP_INPUTS["K_followup_answer"]
    shown = contracts.with_citation_handles(si)
    assert all(p["passage_id"].startswith("psg_P") for p in shown["passages"])
    handle = shown["passages"][0]["passage_id"]
    draft = json.loads(json.dumps(CASES["followup_valid"]["output"]))
    draft["claims"][0]["passage_ids"] = [handle]
    draft["citation_anchors"][0]["passage_id"] = handle
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    report = contracts.validate_model_output(si, resolved)
    assert report.ok, report.codes()
    (link,) = contracts.derive_evidence_links(si, report.result)
    assert link["passage_id"] == "psg_SYNA1abs01" and link["anchor_match"] == "exact"
    assert link["anchor_text"] in si["passages"][0]["text"]


def test_followup_loads_its_own_method_file_and_moves_the_package_hash(tmp_path):
    assert skill.RUNTIME_FILES["followup_answer"] == ("SKILL.md", "followup.md")
    assert skill.integrity_issues() == []
    package = skill.load_skill_package()
    text = package.runtime_text("followup_answer")
    assert '<method-file path="followup.md">' in text and "references/phrases.md" not in text
    assert "No search was run for this question" in " ".join(text.split())
    copy = tmp_path / "deixis-research"
    shutil.copytree(SKILL_DIR, copy)
    before = skill.package_hash(copy)
    (copy / "followup.md").write_text((copy / "followup.md").read_text() + "\nchanged\n")
    assert skill.package_hash(copy) != before  # editing the follow-up method changes every later StepInput's hash
    provenance = json.loads((SKILL_DIR / "provenance.json").read_text())
    entry = next(e for e in provenance["adaptations"] if e["deixis_file"] == "followup.md")
    for marker in ("S22a", "not upstream text", "followup_answer", "Not measured"):
        assert marker in entry["change"]


def classification_draft(si, records, claims=False):
    """SYNTHETIC: the valid follow-up output with its claims dropped and these work records (D66)."""
    draft = json.loads(json.dumps(CASES["followup_valid"]["output"]))
    if not claims:
        draft["claims"], draft["citation_anchors"] = [], []
    draft["work_classifications"] = records
    return draft


def text_of(si, pid):
    return next(" ".join(p["text"].split()) for p in si["passages"] if p["passage_id"] == pid)


def member(si, group, pid, support="source_stated"):
    return {"group": group, "passage_id": pid, "quote": text_of(si, pid)[:80], "support_type": support}


def test_the_method_groups_a_work_by_its_own_approach_not_by_what_it_compares():
    """D66: the follow-up method file says a work that only compares approaches is not in their groups."""
    text = " ".join((SKILL_DIR / "followup.md").read_text().split())
    assert "only compares or reviews approaches is not in their groups" in text
    assert "write no count or list of works in a claim" in text


def test_work_classifications_answer_a_counting_question_without_claims():
    """D66: a classified work names one source by a passage and puts it in groups with located anchors; a work the
    passages leave open says why; no claim is needed when works are classified."""
    si = STEP_INPUTS["K_followup_answer"]
    records = [
        {"passage_id": "psg_SYNA1abs01", "status": "classified", "memberships": [member(si, "Optimal", "psg_SYNA1pg003")], "note": None},
        {"passage_id": "psg_SYNA3pg002", "status": "classified",
         "memberships": [member(si, "Heuristic", "psg_SYNA3pg002"), member(si, "Optimal", "psg_SYNA3pg002", "analyst_inference")],
         "note": None},
        {"passage_id": "psg_SYNA2abs01", "status": "insufficient_evidence", "memberships": [], "note": "Says nothing about relays."},
    ]
    report = contracts.validate_model_output(si, classification_draft(si, records))
    assert report.ok, report.codes()
    # Handles shown to the model resolve back in records and memberships.
    shown = {p["passage_id"]: h["passage_id"] for p, h in zip(si["passages"], contracts.with_citation_handles(si)["passages"])}
    handled = json.loads(json.dumps(records))
    for r in handled:
        r["passage_id"] = shown[r["passage_id"]]
        for m in r["memberships"]:
            m["passage_id"] = shown[m["passage_id"]]
    resolved = contracts.resolve_citation_handles(si, json.dumps(classification_draft(si, handled)))
    assert resolved["work_classifications"] == records


def test_work_classifications_refuse_what_cannot_be_counted_or_cited():
    si = STEP_INPUTS["K_followup_answer"]

    def codes(records):
        return set(contracts.validate_model_output(si, classification_draft(si, records)).codes())
    a1 = {"passage_id": "psg_SYNA1abs01", "status": "classified", "memberships": [member(si, "Optimal", "psg_SYNA1abs01")], "note": None}
    assert "membership_passage_other_work" in codes([a1 | {"memberships": [member(si, "Optimal", "psg_SYNA2abs01")]}])
    assert "classified_work_without_group" in codes([a1 | {"memberships": []}])
    assert {"unclassified_work_with_group", "unclassified_work_without_note"} <= codes([a1 | {"status": "ambiguous"}])
    assert "duplicate_work_group" in codes([a1 | {"memberships": [member(si, "Optimal", "psg_SYNA1abs01"),
                                                                 member(si, " optimal ", "psg_SYNA1pg003")]}])
    assert "anchor_not_in_passage" in codes([a1 | {"memberships": [member(si, "Optimal", "psg_SYNA1abs01") | {
        "quote": "SYNTHETIC words that no passage holds at all."}]}])
    assert "unknown_passage_id" in codes([a1 | {"passage_id": "psg_SYNA9abs01"}])
    many = [member(si, f"Group {n}", "psg_SYNA1abs01") for n in range(6)]
    seventh = {"passage_id": "psg_SYNA3pg002", "status": "classified", "memberships": [member(si, "Group 6", "psg_SYNA3pg002")], "note": None}
    assert "too_many_work_groups" in codes([a1 | {"memberships": many}, seventh])
    assert "too_many_work_groups" not in codes([a1 | {"memberships": many}])
    assert "empty_work_group" in codes([a1 | {"memberships": [member(si, "   ", "psg_SYNA1abs01")]}])
    # One record per work: two versions of one work are one work, and a membership may quote either version.
    one_work = json.loads(json.dumps(si))
    for source in one_work["sources"]:
        if source["source_id"] == "srv_SYNA3pre01":
            source["work_id"] = next(s["work_id"] for s in si["sources"] if s["source_id"] == "srv_SYNA1pub01")
    a3 = {"passage_id": "psg_SYNA3pg002", "status": "ambiguous", "memberships": [], "note": "SYNTHETIC unclear."}
    merged = contracts.validate_model_output(one_work, classification_draft(one_work, [a1, a3]))
    assert merged.ok and [w.code for w in merged.warnings] == ["work_records_merged"]
    other_version = a1 | {"memberships": [member(si, "Optimal", "psg_SYNA3pg002")]}
    assert contracts.validate_model_output(one_work, classification_draft(one_work, [other_version])).ok
    # An answer with neither a claim nor a classified work is still refused.
    assert "followup_answer_without_claims" in codes([{"passage_id": "psg_SYNA2abs01", "status": "ambiguous",
                                                       "memberships": [], "note": "SYNTHETIC unclear."}])
