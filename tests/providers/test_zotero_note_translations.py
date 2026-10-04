"""Every note the Zotero routes return is an English template the UI translates (R5, D208)."""

import ast
import re
from pathlib import Path

from deixis.workflow import text_retry

REPO = Path(__file__).resolve().parents[2]


def _turkish_keys() -> set[str]:
    source = (REPO / "apps" / "web" / "src" / "i18n.ts").read_text()
    return set(re.findall(r"^  '((?:[^'\\]|\\.)*)':", source, re.M))


def _note_templates() -> set[str]:
    found = {"PDF input not verified: " + text_retry.INPUT_CHANGED}
    app = ast.parse((REPO / "backend" / "deixis" / "api" / "app.py").read_text())
    zotero = ast.parse((REPO / "backend" / "deixis" / "providers" / "zotero.py").read_text())
    for node in ast.walk(app):
        if isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "note" for k in node.keys):
            value = node.values[[k.value if isinstance(k, ast.Constant) else None for k in node.keys].index("note")]
            if isinstance(value, ast.Constant):
                found.add(value.value)
            assert not isinstance(value, ast.JoinedStr), "a note is a template with vars, not an f-string"
    for node in ast.walk(zotero):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "pdf_problem" for t in node.targets):
            found |= {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str) and " " in c.value}
            assert not any(isinstance(c, ast.JoinedStr) for c in ast.walk(node.value))
    return found


def test_every_zotero_note_template_has_a_turkish_entry():
    templates = _note_templates()
    assert "PDF not added: {reason}" in templates and "its PDF attachment has no file ({mode})" in templates
    assert templates - _turkish_keys() == set()
