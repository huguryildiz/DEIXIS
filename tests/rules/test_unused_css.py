"""Guard against dead CSS: every class a stylesheet in web/src styles is named somewhere in the web source.

A class counts as used when its name appears in web/src or web/e2e, or when a prefix of it is joined to a value at
run time (`is-${state}`, `'gap-' + reason`). shadcn components in components/ui keep their own styles.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def _source() -> str:
    """All TypeScript the stylesheets can be used from: the app and the Playwright specs."""
    files = [*(WEB / "src").rglob("*.ts"), *(WEB / "src").rglob("*.tsx"), *(WEB / "e2e").rglob("*.ts")]
    return "\n".join(path.read_text() for path in files)


def _classes(css: str) -> set[str]:
    """Class names a stylesheet selects, comments and url() values left out."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # comments may name classes
    css = re.sub(r"url\([^)]*\)", "", css)  # file names hold dots
    css = re.sub(r"\{[^{}]*\}", "{}", css)  # declarations hold decimals such as .5em
    return set(re.findall(r"(?<![\w-])\.(-?[_a-zA-Z][\w-]*)", css))


def _names(source: str) -> tuple[set[str], set[str]]:
    """Every word-with-dashes in the source, and every prefix joined to a run-time value there."""
    words = set(re.findall(r"[\w-]+", source))
    # `prefix${...}`, 'prefix' + value, or a template literal that starts with the prefix
    joined = set(re.findall(r"(?<![\w-])([\w-]+-)(?:\$\{|'\s*\+|`)", source))
    return words, joined


def _used(name: str, words: set[str], joined: set[str]) -> bool:
    """The class is named whole, or a prefix of it ending in a dash is joined to a run-time value."""
    if name in words:
        return True
    parts = name.split("-")
    return any("-".join(parts[:i]) + "-" in joined for i in range(1, len(parts)))


def test_every_styled_class_is_used():
    words, joined = _names(_source())
    unused = []
    for sheet in sorted((WEB / "src").rglob("*.css")):
        if "components/ui" in sheet.as_posix():
            continue
        unused += [f"{sheet.relative_to(WEB)}: .{name}" for name in sorted(_classes(sheet.read_text()))
                   if not _used(name, words, joined)]
    assert not unused, "CSS classes no source names (delete the rules):\n" + "\n".join(unused)
