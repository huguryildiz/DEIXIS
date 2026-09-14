"""Loading and hashing of the application-owned methods/deixis-research package.

Integrity checks here show that the package is complete and referenced files
exist; they say nothing about whether the instructions change model behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from deixis.domain.phrasebank import PHRASEBANK, render
from deixis.paths import SKILL_DIR

# Only the answer step writes report prose, so only it loads the phrasebank.
RUNTIME_FILES = {
    "search_plan": ("SKILL.md", "references/source-grounded-answer.md"),
    "screening": ("SKILL.md", "references/source-grounded-answer.md"),
    "grounded_answer": ("SKILL.md", "references/source-grounded-answer.md", PHRASEBANK),
    "answer_review": ("SKILL.md", "references/answer-review.md"),
}
PROVENANCE_REQUIRED = (
    "package",
    "package_version",
    "upstream",
    "sources_used",
    "adaptations",
    "runtime_dependency_on_upstream",
    "distribution_review",
    "behavioral_validation",
)


@dataclass(frozen=True)
class SkillPackage:
    root: Path
    package_hash: str
    files: dict[str, str]

    def runtime_text(self, task_type: str, language: str = "en") -> str:
        """Method files for one step; the phrasebank is rendered in the language whose frames the answer uses."""
        def body(name: str) -> str:
            return render(self.files[name], language) if name == PHRASEBANK else self.files[name]

        return "\n\n".join(f"<method-file path=\"{name}\">\n{body(name)}\n</method-file>" for name in RUNTIME_FILES[task_type])


def _package_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix in {".md", ".json", ".txt"}
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def package_hash(root: Path = SKILL_DIR) -> str:
    """Hash of the instruction files loaded into model steps.

    Provenance and validation records are excluded, so recording results does not change the hash they describe.
    """
    digest = hashlib.sha256()
    for rel in sorted({name for names in RUNTIME_FILES.values() for name in names}):
        digest.update(f"{rel}\0{hashlib.sha256((root / rel).read_bytes()).hexdigest()}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def load_skill_package(root: Path = SKILL_DIR) -> SkillPackage:
    files = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in _package_files(root)}
    return SkillPackage(root=root, package_hash=package_hash(root), files=files)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def integrity_issues(root: Path = SKILL_DIR) -> list[str]:
    issues: list[str] = []
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        return ["SKILL.md missing"]
    front = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    if front.get("name") != root.name:
        issues.append(f"frontmatter name {front.get('name')!r} != directory {root.name!r}")
    if not front.get("description"):
        issues.append("frontmatter description missing")
    for md in root.rglob("*.md"):
        for target in re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if not (md.parent / target).exists():
                issues.append(f"{md.relative_to(root)} links to missing {target}")
    for names in RUNTIME_FILES.values():
        for name in names:
            if not (root / name).exists():
                issues.append(f"runtime file {name} missing")
    try:
        provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return issues + [f"provenance.json unreadable: {exc}"]
    for key in PROVENANCE_REQUIRED:
        if key not in provenance:
            issues.append(f"provenance.json missing {key}")
    if provenance.get("package") != root.name:
        issues.append("provenance package name mismatch")
    if provenance.get("runtime_dependency_on_upstream") is not False:
        issues.append("upstream must not be a runtime dependency")
    return issues
