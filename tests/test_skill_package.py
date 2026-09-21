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


def test_fulltext_adjudication_method_text_is_the_slice_text_and_the_hash_changed():
    """The method file is the slice text, unchanged, and loading it moves the package hash (slice 12)."""
    before = "sha256:8f0e6cfb9116b5fba081d5959a45d04d9704b12ff38671f54b0400e540664d47"
    assert skill.package_hash() != before
    assert skill.integrity_issues() == []
    assert skill.RUNTIME_FILES["fulltext_adjudication"] == ("SKILL.md", "references/fulltext-adjudication.md")
    text = (SKILL_DIR / "references/fulltext-adjudication.md").read_text()
    assert text == (
        "You are given one paper's selected passages, one inclusion criterion and its parts. For each part decide whether these passages show that the paper itself contains it. Answer every part exactly once, by its name.\n"
        "`present`: a passage states it. Copy one continuous quote from that passage, character for character, at most 600 characters, and name the passage. Do not join text from two places, do not correct, translate or complete it. An equation may be quoted as it is printed.\n"
        "`absent`: the passages describe what the paper does and this part is not among it. No quote.\n"
        "`unclear`: the passages do not let you tell. No quote. Passages are a selection, not the whole paper: when the part could be elsewhere in the paper, say `unclear`, not `absent`.\n"
        "What the paper cites, surveys or plans as future work is not something the paper contains. Judge only the passages given; use nothing you remember about this paper. Give one sentence of rationale per part. Do not state a confidence.\n"
    )
    loaded = skill.load_skill_package().runtime_text("fulltext_adjudication")
    assert '<method-file path="references/fulltext-adjudication.md">' in loaded
    assert "You are given one paper's selected passages" in loaded
