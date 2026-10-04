"""Deterministic text-export checks; no TeX, database, provider or model calls."""

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from deixis.documents.arxiv_source import katex_known
from deixis.workflow.report import latex_math, latex_preamble, latex_text
from deixis.workflow.report.latex_preamble import PREAMBLE, PREAMBLE_SHA256
from deixis.workflow.report.latex_text import SYMBOLS, Unmapped, escape_text, is_unmapped, symbol_math, symbol_text


@pytest.mark.parametrize("ch,expected", [
    ("\\", r"\textbackslash{}"), ("{", r"\{"), ("}", r"\}"), ("$", r"\$"),
    ("&", r"\&"), ("#", r"\#"), ("^", r"\textasciicircum{}"), ("_", r"\_"),
    ("%", r"\%"), ("~", r"\textasciitilde{}"),
])
def test_special_character(ch, expected):
    assert escape_text(ch) == expected


@pytest.mark.parametrize("source,expected", [
    (r"\$", r"\$"), (r"a\$b", r"a\$b"),
    (r"a\\$b", r"a\textbackslash{}\textbackslash{}\$b"),
    (r"a\\\$b", r"a\textbackslash{}\textbackslash{}\$b"), ("a$", r"a\$"),
    (r"\input{x}", r"\textbackslash{}input\{x\}"),
])
def test_dollar_parity_and_plain_commands(source, expected):
    assert escape_text(source) == expected


@pytest.mark.parametrize("source,expected", [
    ('"x"', "``x''"), ('a "x"', "a ``x''"), ('("x")', "(``x'')"),
    ('["x', "[``x"), ('{"x', r"\{``x"), ('a"b', "a''b"), ("a'`b", "a'`b"),
])
def test_quotes(source, expected):
    assert escape_text(source) == expected


def test_whitespace_and_nbsp_without_strip():
    assert escape_text(" \t\n a\r\v\fb \u00a0 c\n") == " a b ~ c "
    assert escape_text("\u00a0\u00a0") == "~~"


def test_removed_controls_are_reported():
    collector = Unmapped()
    assert escape_text("a\x00\x01\x7f\x80b", collector) == "ab"
    assert collector.count == 4
    assert collector.note() == "Unmapped characters: 4 occurrences; first code points: U+0000, U+0001, U+007F, U+0080."
    assert all(is_unmapped(ch) for ch in "\x00\x01\x7f\x80")


@pytest.mark.parametrize("ch,command", list(SYMBOLS.items()))
def test_symbols(ch, command):
    collector = Unmapped()
    expected = r"\ensuremath{" + command + "}"
    assert escape_text(ch + "x", collector) == expected + "x"
    assert symbol_text(ch) == expected
    assert symbol_math(ch) == command
    assert collector.note() is None


def test_symbol_table_floor_and_glyph_choices():
    assert set("≤≥≠≈≡±∓×÷−·⋅°µμ→←↔⇒⇔∞∈∉⊂⊆∪∩∅∑∏∫√∂∇∀∃¬∧∨∝∼≪≫") <= SYMBOLS.keys()
    assert escape_text("±") == r"\ensuremath{\pm}"
    assert SYMBOLS["°"] == r"{^{\circ}}"
    assert escape_text("30°") == r"30\ensuremath{{^{\circ}}}"
    assert [SYMBOLS[ch] for ch in "φϕεϵ"] == [r"\varphi", r"\phi", r"\varepsilon", r"\epsilon"]
    assert symbol_math("x") == symbol_text("x") == "x"


def test_unmapped_occurrences_first_ten_and_one_note():
    collector = Unmapped()
    assert collector.note() is None
    source = "界" + "".join(chr(0x4E00 + i) for i in range(12)) + "界"
    assert escape_text(source, collector) == source
    assert collector.count == 14
    assert collector.note() == ("Unmapped characters: 14 occurrences; first code points: U+754C, "
                                "U+4E00, U+4E01, U+4E02, U+4E03, U+4E04, U+4E05, U+4E06, U+4E07, U+4E08.")
    assert collector.note().isascii() and "\n" not in collector.note()
    assert escape_text(source) == source
    assert collector.count == 14


def test_safe_ranges_are_unchanged():
    source = "Az09éÿĀıſ‐‑‒–—‘’‚‛“”„‟†‡•‣․‥…‧"
    collector = Unmapped()
    assert escape_text(source, collector) == source
    assert collector.note() is None


def test_every_symbol_command_is_known_and_defined():
    path = Path(latex_math.__file__).with_name("latex_names.json")
    assert path.exists(), "Run scripts/latex_export_names.py; symbol definedness cannot be skipped"
    data = json.loads(path.read_text())
    for ch, value in SYMBOLS.items():
        for name in re.findall(r"\\([A-Za-z]+)", value):
            assert name in katex_known()["commands"], (ch, name)
            assert name not in data["undefined_commands"], (ch, name)


def test_preamble_shape_and_hash():
    packages = ["fontspec", "amsmath", "amssymb", "bm", "xcolor", "cite", "url", "booktabs", "longtable", "array"]
    assert PREAMBLE.splitlines() == [r"\documentclass[journal]{IEEEtran}"] + [r"\usepackage{" + p + "}" for p in packages]
    assert PREAMBLE.endswith("\n") and not PREAMBLE.endswith("\n\n")
    assert not any(name in PREAMBLE for name in ("hyperref", "tabularx", "polyglossia", r"\begin{document}", r"\renewcommand"))
    assert PREAMBLE_SHA256 == hashlib.sha256(PREAMBLE.encode("utf-8")).hexdigest()


def test_import_layering_and_no_runtime_effects():
    for module in (latex_preamble, latex_text, latex_math):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = [node.module if isinstance(node, ast.ImportFrom) else alias.name
                 for node in imports for alias in (node.names if isinstance(node, ast.Import) else [None])]
        assert not any(re.search(r"(?:^|\.)(?:export|views|store|httpx|subprocess|storage|models|providers|os)(?:\.|$)", name)
                       for name in names)
        if module is latex_preamble:
            assert names == ["hashlib"]
        if module is latex_text:
            assert not any("latex_math" in name for name in names)
