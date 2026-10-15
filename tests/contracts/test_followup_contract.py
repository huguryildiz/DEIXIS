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
    assert contracts.SCHEMA_VERSIONS["FollowupAnswer"] == "deixis.followup_answer.v1"
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
