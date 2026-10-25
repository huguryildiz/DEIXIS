"""Synthetic syntax and rendering evidence; no scientific or compile claim."""

import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from deixis.documents.arxiv_source import katex_known
from deixis.workflow.features.report import report_latex_math as lm
from deixis.workflow.features.report.report_latex_math import ALLOWED_ENVIRONMENTS, COMMAND_DENY, classify, closed_scan, convert_text, render
from deixis.workflow.features.report.report_latex_preamble import PREAMBLE_SHA256
from deixis.workflow.features.report.report_latex_text import Unmapped, escape_text, is_unmapped


@pytest.mark.parametrize("span", [r"$\input x$"])
def test_closed_scan_rejects(span):
    scan = closed_scan(span)
    assert not scan.ok and scan.reason
    m = classify(span)
    assert m.kind == "plain" and not m.labelable and m.notes
    assert render(m) == escape_text(span)


def test_converter_wires_labels_notes_and_document_collector():
    seen = []
    def labels(index, m):
        seen.append((index, m.kind))
        return "eq:EQ1" if m.labelable else None
    collector = Unmapped()
    output, notes = convert_text("$界$ $$x$$ $界&y$", label_for=labels, unmapped=collector)
    assert seen == [(0, "inline"), (1, "display_plain"), (2, "plain")]
    assert collector.count == 2
    assert collector.note() not in notes
    assert r"\label{eq:EQ1}" in output and len(notes) == 1
    for _ in range(2):
        classify(r"$\text{界}$")
    render(classify(r"$\text{界}$"), unmapped=collector)
    assert collector.count == 3
    with pytest.raises(ValueError):
        convert_text("$$x$$", label_for=lambda index, m: "invalid")


def test_names_file_current_provenance():
    path = Path(lm.__file__).with_name("latex_names.json")
    assert path.exists(), "Run scripts/latex_export_names.py"
    names = json.loads(path.read_text())
    vocabulary = Path(lm.__file__).resolve().parents[3] / "documents/katex_commands.json"
    assert names["preamble_sha256"] == PREAMBLE_SHA256, "Run scripts/latex_export_names.py"
    assert names["katex_commands_sha256"] == hashlib.sha256(vocabulary.read_bytes()).hexdigest(), "Run scripts/latex_export_names.py"
    assert isinstance(names["katex_version"], str) and {names["katex_version"]} == katex_known()["version"]
    for field, known in (("undefined_commands", "commands"), ("undefined_environments", "environments")):
        assert names[field] == sorted(set(names[field])) and set(names[field]) <= katex_known()[known]
    assert "XeTeX" in names["engine"]
    assert any(line.startswith("IEEEtran.cls ") for line in names["files"])
    assert {"R", "mathscr", "htmlClass"} <= set(names["undefined_commands"])
    assert not {"geq", "frac"} & set(names["undefined_commands"])
    assert names == lm._names()


def output_tokens(output, *, wrapper_dollars=frozenset()):
    """Return tokens and a failure; only recorded wrapper dollars may be bare."""
    if "^^" in output:
        return [], "superscript escape in output"
    i = 0
    tokens = []
    while i < len(output):
        ch = output[i]
        if ch in "%#":
            return tokens, f"bare {ch} at {i}"
        if ch == "$":
            if i not in wrapper_dollars:
                return tokens, f"bare $ at {i}"
            tokens.append((i, "$"))
        if ch != "\\":
            i += 1
            continue
        start = i
        i += 1
        if i == len(output):
            return tokens, "trailing backslash"
        if unicodedata.category(output[i])[0] in "LM":
            while i < len(output) and unicodedata.category(output[i])[0] in "LM":
                i += 1
            word = output[start + 1:i]
            tokens.append((start, "\\" + word))
            generated = {"textbackslash", "textasciicircum", "textasciitilde", "ensuremath", "label"}
            if word not in generated and word not in katex_known()["commands"] - COMMAND_DENY:
                return tokens, f"unknown or denied command: {word}"
            if word in {"begin", "end"}:
                while i < len(output) and output[i].isspace():
                    i += 1
                if i == len(output) or output[i] != "{":
                    return tokens, "missing environment argument"
                i += 1
                name_start = i
                while i < len(output) and ("A" <= output[i] <= "Z" or "a" <= output[i] <= "z" or output[i] == "*"):
                    i += 1
                if i == len(output) or output[i] != "}":
                    return tokens, "malformed environment argument"
                if output[name_start:i] not in ALLOWED_ENVIRONMENTS:
                    return tokens, "unknown environment"
                i += 1
        else:
            tokens.append((start, output[start:i + 1]))
            if output[i] not in katex_known()["symbols"] - {"(", ")", "]"}:
                return tokens, f"unknown control symbol at {start}"
            i += 1
    return tokens, None


def test_removed_controls_are_reported():
    collector = Unmapped()
    assert escape_text("a\x00\x01\x7f\x80b", collector) == "ab"
    assert collector.count == 4
    assert collector.note() == "Unmapped characters: 4 occurrences; first code points: U+0000, U+0001, U+007F, U+0080."
    assert all(is_unmapped(ch) for ch in "\x00\x01\x7f\x80")
