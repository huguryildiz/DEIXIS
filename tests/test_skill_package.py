"""Package integrity only; these checks do not show behavioral effect on a model."""

import json
import shutil

from deixis.domain import skill
from deixis.paths import SKILL_DIR


def test_package_integrity():
    assert skill.integrity_issues() == []


def test_package_hash_is_stable_and_content_sensitive(tmp_path):
    first = skill.package_hash()
    assert first == skill.package_hash()
    assert first.startswith("sha256:") and len(first) == 71

    copy = tmp_path / "deixis-research"
    shutil.copytree(SKILL_DIR, copy)
    (copy / ".DS_Store").write_bytes(b"ignored")
    assert skill.package_hash(copy) == first
    provenance = copy / "provenance.json"
    provenance.write_text(provenance.read_text().replace("not_done", "not done"))
    assert skill.package_hash(copy) == first  # recording provenance or results must not change the hash they describe
    (copy / "SKILL.md").write_text((copy / "SKILL.md").read_text() + "\nchanged\n")
    assert skill.package_hash(copy) != first


def test_runtime_text_loads_only_declared_files():
    package = skill.load_skill_package()
    text = package.runtime_text("grounded_answer")
    assert '<method-file path="SKILL.md">' in text
    assert '<method-file path="references/source-grounded-answer.md">' in text
    assert f'<method-file path="{skill.PHRASEBANK}">' in text
    assert "provenance.json" not in text
    # The answer and report-section steps carry the phrasebank.
    assert skill.PHRASEBANK not in package.runtime_text("screening")
    assert skill.PHRASEBANK not in package.runtime_text("search_plan")
    review = package.runtime_text("answer_review")
    assert '<method-file path="references/answer-review.md">' in review and skill.PHRASEBANK not in review
    for task in ("cell_extraction", "table_columns"):
        table = package.runtime_text(task)
        assert '<method-file path="references/evidence-table.md">' in table and skill.PHRASEBANK not in table
    assert '<method-file path="references/evidence-table.md">' not in text
    assert f'<method-file path="{skill.PHRASEBANK}">' in package.runtime_text("report_section")
    # The raw file's `tr:` lines never reach the model; a Turkish answer gets the rendered Turkish frames.
    assert "\ntr: " not in text
    assert "literal Turkish renderings" in package.runtime_text("grounded_answer", "tr")


def test_skill_does_not_advertise_unsupported_modes_as_available():
    text = " ".join((SKILL_DIR / "SKILL.md").read_text().split())
    assert "not" in text and "available" in text
    for mode in ("kill-search", "candidate research-question development"):
        assert mode in text


def test_report_task_types_load_the_report_reference_and_pass_integrity():
    from deixis.domain.skill import RUNTIME_FILES, integrity_issues
    for task in ("report_plan", "report_section", "report_phrase_repair", "report_review"):
        assert "references/report.md" in RUNTIME_FILES[task]
    assert integrity_issues() == []


def test_provenance_records_pinned_upstream_without_runtime_dependency():
    provenance = json.loads((SKILL_DIR / "provenance.json").read_text())
    assert provenance["upstream"]["revision"] == "037972d5add41d8a62cff45e09785beebc61bb01"
    assert provenance["runtime_dependency_on_upstream"] is False
    # Behavior runs are recorded per case; provenance must point there and not claim completed validation.
    assert "tests/model_behavior/cases.json" in provenance["behavioral_validation"]
    assert "validated" not in provenance["behavioral_validation"]
    for source in provenance["sources_used"]:
        assert len(source["sha256"]) == 64
