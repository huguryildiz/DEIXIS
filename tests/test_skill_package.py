"""Package integrity only; these checks do not show behavioral effect on a model."""

import json
import shutil

from deixis.domain import skill
from deixis.paths import SKILL_DIR


def test_package_integrity():
    assert skill.integrity_issues() == []


def test_lineage_links_loads_synthesis_md_and_the_hash_moved():
    before = "sha256:cef7c08662f102f5e7dd56f5203ecb142fc28b91eebeddbfb5b3bb0bbad3b6bb"
    assert skill.RUNTIME_FILES["lineage_links"] == ("SKILL.md", "references/synthesis.md")
    package = skill.load_skill_package()
    assert package.package_hash != before
    assert skill.integrity_issues() == []
    assert '<method-file path="references/synthesis.md">' in package.runtime_text("lineage_links")
    text = " ".join((SKILL_DIR / "SKILL.md").read_text().split())
    # These two existing prohibition sentences remain verbatim for answer/report tasks.
    assert ("Literature synthesis across idea chains, candidate research-question development, "
            "claim-specific kill-search, and experiment design or execution are **not available**.") in text
    assert ("That includes proposing research gaps, directions or candidate questions in a `grounded_answer`: "
            "do not offer them as claims, not even as `analyst_inference`; name them in `unanswered_aspects` instead.") in text
    provenance = json.loads((SKILL_DIR / "provenance.json").read_text())
    entry = next(e for e in provenance["adaptations"] if e["deixis_file"] == "references/synthesis.md")
    assert entry["derived_from"] == []
    for marker in ("2026-10-01", "D130", "D133", "Chain of Ideas", "Li and others 2024", "not upstream text"):
        assert marker in entry["change"]
    assert "tests/model_behavior/lineage_cases.json" in provenance["behavioral_validation"]


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
    assert skill.PHRASEBANK not in package.runtime_text("abstract_screening")
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
    """The method file is the slice text (slice 12, with slice 26's reported-result sentence and slice 28's comparator
    line), and loading it moves the package hash."""
    before = "sha256:a633e9c7091ed3338b0a51d3c7bdb99e524678f5cc4bdb60e1049d8b4a68028a"
    assert skill.package_hash() != before
    assert skill.integrity_issues() == []
    assert skill.RUNTIME_FILES["fulltext_adjudication"] == ("SKILL.md", "references/fulltext-adjudication.md")
    text = (SKILL_DIR / "references/fulltext-adjudication.md").read_text()
    assert text == (
        "You are given one paper's selected passages, one inclusion criterion and its parts. For each part decide whether these passages show that the paper itself contains it. Answer every part exactly once, by its name.\n"
        "`present`: a passage states it. Copy one continuous quote from that passage, character for character, at most 600 characters, and name the passage. Do not join text from two places, do not correct, translate or complete it. An equation may be quoted as it is printed.\n"
        "`absent`: the passages describe what the paper does and this part is not among it. No quote.\n"
        "`unclear`: the passages do not let you tell. No quote. Passages are a selection, not the whole paper: when the part could be elsewhere in the paper, say `unclear`, not `absent`.\n"
        "What the paper cites, surveys or plans as future work is not something the paper contains. "
        "A part about a result, an effect or a measured outcome is `present` only when a passage reports that result, or an analysis of it, as a finding of this paper, whatever its source: an experiment or trial, a re-analysis, a review's pooled estimate, a derivation or a simulation. "
        "A result the paper only plans to measure is not reported: a protocol, a trial registration or a design paper that says it will measure an outcome does not contain that result. "
        "Label such a part `absent` when the passages show that no result is reported yet, and `unclear` when they cannot tell. Judge only the passages given; use nothing you remember about this paper. Give one sentence of rationale per part. Do not state a confidence.\n"
        "A part marked `\"role\": \"comparator\"` names what the thing sought must be compared with. "
        "It is `present` only when a passage shows that the comparison group receives what the part names; quote that passage. "
        "Judge the comparison group by everything it receives, not only by what it lacks: a group described only as not receiving the thing sought does not show what it receives. "
        "When the passages show that both groups receive the same added treatment, restriction or prescribed regimen, and that addition makes the comparison group something the part does not name, label the part `absent`: a comparator named as unrestricted or usual X is not met when both groups follow the same restriction of X. "
        "An addition that leaves the comparison group what the part names does not matter: the same Y given to both groups does not change a part that names only X. "
        "With several arms, the part is met when an arm that receives what the part names is compared with an arm that receives the thing sought. "
        "Otherwise, when no passage shows that the comparison group receives what the part names, label the part `unclear`. "
        "A part without that role is read as the lines above say.\n"
    )
    loaded = skill.load_skill_package().runtime_text("fulltext_adjudication")
    assert '<method-file path="references/fulltext-adjudication.md">' in loaded
    assert "You are given one paper's selected passages" in loaded


def test_the_comparator_line_names_no_field_and_the_criterion_rule_names_what_the_comparison_group_receives():
    """Slice 28 (D109): the reading's comparator line carries no field word, and rule 8 of the criterion proposal asks
    the comparator's definition to name what the comparison group receives and forbids widening it."""
    reading = (SKILL_DIR / "references/fulltext-adjudication.md").read_text().splitlines()[-1].lower()
    for word in ("time", "eating", "calori", "weight", "diet", "trial", "placebo"):
        assert word not in reading
    body = " ".join((SKILL_DIR / "references/criterion-proposal.md").read_text().split())
    assert ("The comparator part's `definition` names what the comparison group must receive, in the question's words, "
            "not only that it does not receive the thing sought, and adds no alternative the question does not name "
            "(no \"or a comparable ...\").") in body
    assert ("It says that a comparison group that also receives an addition making it something other than the named "
            "comparator, such as the same restriction the intervention group follows, does not meet it.") in body
    assert ("such as another active treatment, another variant of the same one, or the same added treatment or "
            "restriction as the intervention group.") in body
