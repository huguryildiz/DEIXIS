"""Guard against dead translations: every English key in the Turkish catalogue is named in the web or backend source.

A key counts as used when it is written as a string literal in web/src or deixis, when its part after `::` is
(`candidate status::Open`), or when it is a stored code with its underscores turned into spaces (`outcome_unknown`
shown as `outcome unknown`). Keys built at run time in another way are listed with their reason in
translation_allowlist.txt.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "web/src/lib/locales/tr.ts"
ALLOWLIST = Path(__file__).with_name("translation_allowlist.txt")
# One quoted JavaScript string at the start of a catalogue line.
QUOTED = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def _unquote(literal: str) -> str:
    """The text of a quoted literal, with its backslash escapes undone."""
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), literal[1:-1])


def _keys() -> list[str]:
    """English keys of the catalogue: a quoted string that opens a line and is followed by a colon."""
    keys = []
    for line in CATALOGUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        match = QUOTED.match(line)
        if match and line[match.end():].lstrip().startswith(":"):
            keys.append(_unquote(match.group(0)))
    return keys


def _quoted_forms(text: str) -> list[str]:
    """How a source file can write this text: in single quotes, double quotes or backticks."""
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n")
    return ["'" + escaped.replace("'", "\\'") + "'", '"' + escaped.replace('"', '\\"') + '"', "`" + escaped + "`"]


def _allowed() -> set[str]:
    """Keys in the allowlist: one per line, comments and blank lines skipped."""
    lines = (line.split(" #", 1)[0].strip() for line in ALLOWLIST.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def test_every_translation_key_is_used():
    files = [*(p for p in (ROOT / "web/src").rglob("*.ts*") if "locales" not in p.parts), *(ROOT / "deixis").rglob("*.py")]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)

    def used(key: str) -> bool:
        for text in (key, key.split("::", 1)[-1]):
            # the key itself, or a stored code whose underscores the UI turns into spaces
            if any(form in source for candidate in (text, text.replace(" ", "_")) for form in _quoted_forms(candidate)):
                return True
        return False

    allowed = _allowed()
    keys = _keys()
    unused = [key for key in keys if not used(key) and key not in allowed]
    assert not unused, "Translation keys no source names (delete them from tr.ts, or allowlist them with the reason):\n" + \
        "\n".join(unused)
    # An allowlisted key that is gone or now written in the source leaves the list.
    stale = sorted(key for key in allowed if key not in keys or used(key))
    assert not stale, "Allowlist entries no longer needed: " + ", ".join(stale)
