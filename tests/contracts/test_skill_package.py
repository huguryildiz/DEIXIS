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
    assert "provenance.json" not in text
    # D43: the phrasebank left the package; no step loads it.
    assert not (SKILL_DIR / "references/phrases.md").exists()
    assert all("references/phrases.md" not in files for files in skill.RUNTIME_FILES.values())
    review = package.runtime_text("answer_review")
    assert '<method-file path="references/answer-review.md">' in review
    for task in ("cell_extraction", "table_columns"):
        assert '<method-file path="references/evidence-table.md">' in package.runtime_text(task)
    assert '<method-file path="references/evidence-table.md">' not in text


