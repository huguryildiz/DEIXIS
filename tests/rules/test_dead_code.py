"""Guard against dead code: vulture finds no unused function, class, import or module constant outside the tests.

Names reached in a way vulture cannot see (dispatch tables, getattr, stored codes) are listed with their reason in
dead_code_allowlist.txt. FastAPI routes and Pydantic validators are registered by their decorators.
"""

from __future__ import annotations

from pathlib import Path

import vulture

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("dead_code_allowlist.txt")
# Folders scanned; tests count as callers, but their own unused helpers are not reported.
SCANNED = ("deixis", "scripts", "packaging", "tests")
REPORTED = ("deixis", "scripts", "packaging")


def _allowed() -> set[tuple[str, str]]:
    """The (path, name) pairs in the allowlist, comments and blank lines skipped."""
    pairs = set()
    for line in ALLOWLIST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()  # drop the comment part
        if line:
            path, name = line.split()
            pairs.add((path, name))
    return pairs


def _findings() -> list[tuple[str, str, int, str]]:
    """Unused code vulture reports in the shipped folders: (path, name, line, kind)."""
    scan = vulture.Vulture(ignore_decorators=["@app.*", "@field_validator", "@model_validator"])
    scan.scavenge([str(ROOT / folder) for folder in SCANNED])
    found = []
    for item in scan.get_unused_code(min_confidence=60):
        path = Path(item.filename).resolve().relative_to(ROOT)
        if path.parts[0] not in REPORTED:
            continue
        # A variable or attribute counts only at module level: class fields (Pydantic, dataclasses) are read by name.
        if item.typ in ("variable", "attribute"):
            line = (ROOT / path).read_text().splitlines()[item.first_lineno - 1]
            if line[:1].isspace():
                continue
        found.append((path.as_posix(), item.name, item.first_lineno, item.typ))
    return found


def test_no_unused_code_outside_the_allowlist():
    allowed = _allowed()
    found = _findings()
    new = [f"{path}:{line} unused {kind} '{name}'" for path, name, line, kind in found if (path, name) not in allowed]
    assert not new, "Unused code (delete it, or add it to dead_code_allowlist.txt with the reason):\n" + "\n".join(new)
    # An allowlist entry whose code is gone is removed too, so the list never outlives its reason.
    stale = allowed - {(path, name) for path, name, _, _ in found}
    assert not stale, "Allowlist entries no longer reported by vulture: " + ", ".join(f"{p} {n}" for p, n in sorted(stale))
