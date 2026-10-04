"""Synthetic syntax and rendering evidence; no scientific or compile claim."""

import hashlib
import json
import random
import unicodedata
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from deixis.documents.arxiv_source import katex_known
from deixis.domain.contracts import _math_spans
from deixis.workflow.report import latex_math as lm
from deixis.workflow.report.latex_math import (
    ALLOWED_ENVIRONMENTS, CELL_COMMANDS, COMMAND_DENY, E_ENVIRONMENTS, TEXT_COMMANDS,
    classify, closed_scan, command_status, convert_text, render, split_text,
)
from deixis.workflow.report.latex_preamble import PREAMBLE_SHA256
from deixis.workflow.report.latex_text import SYMBOLS, Unmapped, escape_text


CORPUS = ["", "plain", r"\$", "$", "$$", "$ $", "$x$", "$$x$$", r"\text{$x$}",
          "\\$x$\n$x$", "$$x$\n$x$", r"a\$x$ $x$", r"a\\$x$", "$$a\nb$$", "$a\nb$"]


def test_positional_twin_and_reassembly_seeded():
    rng = random.Random(5112)
    texts = CORPUS + ["".join(rng.choice("$\\x{}\n ") for _ in range(rng.randrange(100))) for _ in range(2000)]
    for text in texts:
        positions = lm._span_positions(text)
        assert [text[a:b] for a, b in positions] == _math_spans(text)
        assert [value for kind, value in split_text(text) if kind == "math"] == _math_spans(text)
        assert "".join(value for _, value in split_text(text)) == text


@pytest.mark.parametrize("text,pieces,positions", [
    ("\\$x$\n$x$", [("text", "\\$x$\n"), ("math", "$x$")], [(5, 8)]),
    ("$$x$\n$x$", [("text", "$$x$\n"), ("math", "$x$")], [(5, 8)]),
    (r"\$", [("text", r"\$")], []), ("$", [("text", "$")], []),
    ("$$", [("text", "$$")], []),
    (r"\text{$x$}", [("text", r"\text{"), ("math", "$x$"), ("text", "}")], [(6, 9)]),
])
def test_split_expected_positions(text, pieces, positions):
    assert lm._span_positions(text) == positions
    assert split_text(text) == pieces


def test_split_fails_closed_on_disagreement_or_reassembly(monkeypatch):
    monkeypatch.setattr(lm, "_math_spans", lambda text: [])
    assert split_text("a $x$") == [("text", "a $x$")]
    monkeypatch.setattr(lm, "_math_spans", lambda text: ["$x$", "$x$"])
    monkeypatch.setattr(lm, "_span_positions", lambda text: [(0, 3), (0, 3)])
    assert split_text("$x$") == [("text", "$x$")]


UNSAFE = [
    *["$\\" + name + " x$" for name in sorted(COMMAND_DENY)],
    *["$\\" + name + " x$" for name in ("input", "write", "csname", "catcode", "label", "ref", "cite",
                                        "immediate", "openout", "mbox", "ensuremath")],
    "$^^$", "$x%y$", "$x#y$", "$$a\n\nb$$", "$$a\n \t\nb$$", "$$a\n\r\nb$$",
    *["$a" + ch + "b$" for ch in ("\x00", "\x01", "\r", "\x7f", "\x80", "\u00a0", "\u200e", "\u2028", "\u2029", "\ud800", "\ue000", "\u0378")],
    "${x$", "$x}$", r"$\begin{unknown}x\end{unknown}$", r"$\end{document}$",
    r"$\begin {document}$", "$\\begin{\n document}$", "$\\begin\n{document}$",
    r"$$\begin{aligned}{\end{aligned}}$$", r"$$\begin{aligned}\begin{matrix}\end{aligned}\end{matrix}$$",
    r"$\left(x$", r"$\right)x$", r"$\middle|x$", r"$\begin x$",
    r"$\text{\foo}$", r"$\text{\\}$", r"$\text{\alpha}$", r"$\text{\begin{matrix}x\end{matrix}}$",
    r"$\text{\left(x\right)}$", r"$\text{\text{\text{\text{x}}}}$",
    r"${x&y}$", r"$$\frac{x&y}{z}$$", r"$x\tag{a}$",
    r"$$\begin{aligned}x&=y\tag{a}\end{aligned}$$", r"$$\begin{gathered}a&b\end{gathered}$$",
    r"$\substack{x&y}$", r"$$\begin{aligned}\left(a&b\right)\end{aligned}$$",
    "$" + "{" * 65 + "x" + "}" * 65 + "$", r"$\ $", r"$\1$", r"$\($", r"$\)$", r"$\]$",
    "$x\\$", "$ $", "$$$$", r"$$\tag x$$", r"$$\left({x\right)}$$",
]


@pytest.mark.parametrize("span", UNSAFE)
def test_closed_scan_rejects(span):
    scan = closed_scan(span)
    assert not scan.ok and scan.reason
    m = classify(span)
    assert m.kind == "plain" and not m.labelable and m.notes
    assert render(m) == escape_text(span)


@pytest.mark.parametrize("span", [
    r"$x&y$", r"$x\\y$", r"$$\tag{a}x&y$$", r"$$\tag*{a}x\\y$$",
    r"$$\begin{align}x\end{align}\begin{gather}y\end{gather}$$",
    r"$\begin{equation}x\end{equation}$", r"$$x\begin{equation}y\end{equation}$$",
    r"$$\begin{aligned}\begin{equation}x\end{equation}\end{aligned}$$",
    r"$$\begin{equation}\begin{equation}x\end{equation}\end{equation}$$",
])
def test_structurally_scanned_but_class_a(span):
    assert closed_scan(span).ok
    assert classify(span).kind == "plain"


def test_text_dollar_split_is_two_class_a_spans():
    text = r"$\text{$x$}$"
    assert _math_spans(text) == [r"$\text{$", "$}$"]
    assert all(classify(span).kind == "plain" for span in _math_spans(text))
    assert convert_text(text)[0] == escape_text(text)


def test_allowed_nested_groups_and_structural_facts():
    assert closed_scan(r"$$\begin{aligned}{x}+\begin{matrix}a&b\\c&d\end{matrix}\end{aligned}$$").ok
    assert closed_scan(r"$\substack{x\\y}$").ok
    assert closed_scan(r"$\left(\frac{x}{y}\middle|z\right)$").ok
    assert closed_scan(r"$\{x\}$").ok
    assert closed_scan(r"$\text{\&\%\$\#\_\{\}\,\;\quad\qquad\textbf{x}}$").ok
    assert closed_scan("$" + "{" * 64 + "x" + "}" * 64 + "$").ok
    assert closed_scan(r"$\frac{x}$").ok  # Argument counts remain a compile risk.
    assert closed_scan("not a span").reason == "delimiters"
    scan = closed_scan(r"$$x&=y\\z$$")
    assert scan.ok and scan.top_amp and scan.top_row and not scan.top_tag
    scan = closed_scan(r"$$\begin {align}x&=y\end {align}$$")
    assert scan.top_e == (("align", 0, 30),) and scan.e_count == 1


@pytest.mark.parametrize("name", sorted(ALLOWED_ENVIRONMENTS))
def test_environment_context_policy(name):
    def span(body):
        return "$$\\begin{" + name + "}" + body + "\\end{" + name + "}$$"
    assert closed_scan(span("x&y")).ok == (name in lm.AMP_ENVIRONMENTS)
    assert closed_scan(span(r"x\\y")).ok == (name not in {"equation", "equation*"})
    assert not closed_scan(span(r"{x&y}")).ok
    m = classify(span("x"))
    assert m.kind == ("display_env" if name in E_ENVIRONMENTS else "display_plain")


@pytest.mark.parametrize("span,kind,body,output", [
    ("$x$", "inline", "$x$", "$x$"),
    (r"$$\begin {align}x&=y\end {align}$$", "display_env", r"\begin {align}x&=y\end {align}", "\n\\begin {align}x&=y\\end {align}\n"),
    (r"$$x\tag{a}$$", "display_tag", r"x\tag{a}", "\n\\begin{equation*}\nx\\tag{a}\n\\end{equation*}\n"),
    (r"$$x&=y$$", "display_aligned", "x&=y", "\n\\begin{equation*}\n\\begin{aligned}\nx&=y\n\\end{aligned}\n\\end{equation*}\n"),
    (r"$$x\\y$$", "display_gathered", r"x\\y", "\n\\begin{equation*}\n\\begin{gathered}\nx\\\\y\n\\end{gathered}\n\\end{equation*}\n"),
    ("$$ x $$", "display_plain", "x", "\n\\begin{equation*}\nx\n\\end{equation*}\n"),
])
def test_stage_three_exact_layout(span, kind, body, output):
    m = classify(span)
    assert m.source == span and m.kind == kind and m.body == body
    assert m.labelable == (kind in {"display_aligned", "display_gathered", "display_plain"})
    assert render(m) == output
    assert "\n\n" not in output
    numbered = render(m, label="eq:EQ1")
    if m.labelable:
        assert numbered == output.replace("equation*", "equation").replace("\\begin{equation}\n", "\\begin{equation}\n\\label{eq:EQ1}\n", 1)
    else:
        assert numbered == output


@pytest.mark.parametrize("span", [r"$$x\tag*{a}$$", r"$$x\nonumber$$", r"$$x\notag$$"])
def test_tag_variants_unlabelled(span):
    m = classify(span)
    assert m.kind == "display_tag" and not m.labelable
    assert r"\label" not in render(m, label="eq:EQ1")


@pytest.mark.parametrize("source,expected", [
    (r"$x\lt y\gt z\ltimes w$", r"$x< y> z\ltimes w$"),
    ("$αx$", r"$\alpha x$"), ("$α x$", r"$\alpha x$"), ("$α1$", r"$\alpha1$"),
    ("$≥x$", r"$\geq x$"), ("$αé$", r"$\alpha é$"), ("$αı$", r"$\alpha ı$"),
    ("$α\u0301$", "$\\alpha \u0301$"), ("$α$", r"$\alpha$"),
    (r"$\text{αx}$", r"$\text{\ensuremath{\alpha}x}$"),
    (r"$\text{≥}$", r"$\text{\ensuremath{\geq}}$"),
    (r"$\text{\textbf{αx}}+βy$", r"$\text{\textbf{\ensuremath{\alpha}x}}+\beta y$"),
])
def test_token_rewrite_and_symbol_boundaries(source, expected):
    assert render(classify(source)) == expected


@pytest.mark.parametrize("source,expected", [
    ("$^°$", r"$^{^{\circ}}$"), (r"$\^°$", r"$\^{^{\circ}}$"),
    ("$x^°$", r"$x^{^{\circ}}$"), ("$30°$", r"$30{^{\circ}}$"),
    (r"$\text{°}$", r"$\text{\ensuremath{{^{\circ}}}}$"),
])
def test_degree_rewrite_cannot_form_superscript_escape(source, expected):
    m = classify(source)
    assert m.kind == "inline" and render(m) == expected
    assert "^^" not in render(m)


@pytest.mark.parametrize("rewritten,reason", [
    (r"\^^{\circ}", "superscript_escape"), ("x%y", "literal_special"),
    ("x#y", "literal_special"), (r"x\\%y", "literal_special"),
])
def test_stage_two_defence_escapes_original(monkeypatch, rewritten, reason):
    monkeypatch.setattr(lm, "_rewrite", lambda body, scan: rewritten)
    m = classify("$x$")
    assert m.kind == "plain" and m.source == "$x$"
    assert m.notes == (f"Math written as plain text: {reason}.",)
    assert render(m) == r"\$x\$"


@pytest.mark.parametrize("rewritten", [r"x\%y", r"x\#y"])
def test_stage_two_defence_preserves_escaped_specials(monkeypatch, rewritten):
    monkeypatch.setattr(lm, "_rewrite", lambda body, scan: rewritten)
    assert render(classify("$x$")) == "$" + rewritten + "$"


@pytest.mark.parametrize("body", [r"\alphaé", r"\geqı", "\\alpha\u0301", r"\quadé"])
@pytest.mark.parametrize("text_group", [False, True])
def test_saved_command_unicode_boundary_is_class_a(body, text_group):
    span = "$" + ("\\text{" + body + "}" if text_group else body) + "$"
    assert closed_scan(span).reason == "command_boundary"
    m = classify(span)
    assert m.kind == "plain" and m.notes == ("Math written as plain text: command_boundary.",)
    assert render(m) == reference_escape(span)


@pytest.mark.parametrize("span", [r"$\alpha é$", r"$\alpha1$", r"$\text{\quad é}$"])
def test_saved_command_separated_or_digit_boundary_is_accepted(span):
    assert closed_scan(span).ok
    assert classify(span).kind == "inline" and render(classify(span)) == span


@pytest.mark.parametrize("span", ["$$x$y$$", "$x$y$", r"$$\text{x$y}$$"])
@pytest.mark.parametrize("cell", [False, True])
def test_body_dollar_is_class_a(span, cell):
    assert closed_scan(span).reason == "dollar"
    m = classify(span, cell=cell)
    assert m.kind == "plain" and m.notes == ("Math written as plain text: dollar.",)
    assert render(m) == reference_escape(span)
    if span.startswith("$$"):
        assert convert_text(span, cell=cell)[0] == reference_escape(span)


@pytest.mark.parametrize("cell", [False, True])
def test_escaped_body_dollar_is_accepted(cell):
    m = classify(r"$$a\$b$$", cell=cell)
    assert closed_scan(m.source).ok
    assert m.kind == ("inline" if cell else "display_plain")
    expected = r"$a\$b$" if cell else "\n\\begin{equation*}\na\\$b\n\\end{equation*}\n"
    assert render(m) == expected


def test_valid_label_is_ignored_for_class_a():
    output = render(classify("$x&y$"), label="eq:EQ1")
    assert output == r"\$x\&y\$"
    assert r"\label" not in output


@pytest.mark.parametrize("ch,value", list(SYMBOLS.items()))
def test_every_symbol_in_math_and_text_argument(ch, value):
    suffix = " " if value.startswith("\\") else ""
    assert render(classify("$" + ch + "x$")) == "$" + value + suffix + "x$"
    assert render(classify("$\\text{" + ch + "x}$")) == "$\\text{\\ensuremath{" + value + "}x}$"


def test_class_b_after_rewrite():
    m = classify(r"$\R+\mathscr{X}+\R$")
    assert m.kind == "inline" and m.body == m.source
    assert m.class_b == (r"\R", r"\mathscr")
    assert m.notes == (r"\R, \mathscr is not defined by the export preamble; the document may not compile",)
    assert render(m) == m.source
    assert classify(r"$\lt$").class_b == ()


def test_class_b_environment_warning(monkeypatch):
    names = {**lm._names(), "undefined_environments": ["aligned"]}
    monkeypatch.setattr(lm, "_names", lambda: names)
    m = classify(r"$$\begin{aligned}x&=y\end{aligned}$$")
    assert m.class_b == ("{aligned}",)
    assert m.notes == ("{aligned} is not defined by the export preamble; the document may not compile",)


@pytest.mark.parametrize("span", ["$x$", "$$x$$", "$x&y$", r"$$x\tag{a}$$", r"$$\begin{equation}x\end{equation}$$"])
@pytest.mark.parametrize("label", ["eq:EQ1}\\input{x}\\label{p", "", "eq:EQ1234", "eq:EQ١", "eq:EQ1\n", 1])
def test_label_trust_boundary_before_collection(span, label):
    collector = Unmapped()
    with pytest.raises(ValueError, match="Equation label"):
        render(classify(span), label=label, unmapped=collector)
    assert collector.count == 0


def test_frozen_span_and_unexpected_failure(monkeypatch):
    m = classify("$x$")
    with pytest.raises(FrozenInstanceError):
        m.kind = "plain"
    def broken(span):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(lm, "closed_scan", broken)
    assert classify("$x$").kind == "plain"


@pytest.mark.parametrize("span", [
    r"$\begin{matrix}x\end{matrix}$", r"$$x\\y$$", r"$$x\\[1000pt]y$$",
    *["$1000.5 " + unit + "$" for unit in "pt em ex cm mm in bp pc mu sp dd cc px".split()],
    *["$\\" + name + "{x}$" for name in sorted(CELL_COMMANDS)],
    r"$$x&y$$", r"$$x\tag{a}$$", r"$$\begin{equation}x\end{equation}$$",
])
def test_cell_subset_rejected(span):
    m = classify(span, cell=True)
    assert m.kind == "plain" and m.notes
    assert render(m) == escape_text(span)


def test_cell_plain_display_becomes_inline():
    m = classify("$$ αx $$", cell=True)
    assert m.kind == "inline" and not m.labelable
    assert render(m, label="eq:EQ1") == r"$\alpha x$"
    assert m.notes == ("Display math written inline in a table cell.",)
    assert classify("$2ptx$", cell=True).kind == "inline"
    example = r"\begin{array}{c}x\\[1000pt]y\end{array}"
    assert len("$" + example + "$") == 41
    assert classify("$" + example + "$", cell=True).kind == "plain"
    assert classify("$" + example + "$").kind == "inline"


@pytest.mark.parametrize("source,expected", [
    ("a $$x$$ $$y$$ b", "a\n\\begin{equation*}\nx\n\\end{equation*}\n\\begin{equation*}\ny\n\\end{equation*}\nb"),
    ("$$x$$$$y$$", "\n\\begin{equation*}\nx\n\\end{equation*}\n\\begin{equation*}\ny\n\\end{equation*}\n"),
    ("$$x$$ tail", "\n\\begin{equation*}\nx\n\\end{equation*}\ntail"),
    ("$$x$$ $a&b$", "\n\\begin{equation*}\nx\n\\end{equation*}\n\\$a\\&b\\$"),
    ("$$\\begin\n{aligned}x&=y\\\\\nz&=w\n\\end{aligned}$$",
     "\n\\begin{equation*}\n\\begin\n{aligned}x&=y\\\\\nz&=w\n\\end{aligned}\n\\end{equation*}\n"),
])
def test_join_display_boundaries_only(source, expected):
    assert convert_text(source)[0] == expected
    assert "\n\n" not in expected
    assert all(line.strip() for line in expected.splitlines()[1:])


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


@pytest.mark.parametrize("name", sorted(katex_known()["commands"]))
def test_every_katex_command_partition_and_scan(name):
    assert len(katex_known()["commands"]) == 976
    assert COMMAND_DENY <= katex_known()["commands"]
    assert command_status(name) in {"denied", "allowed"}
    span = "$\\" + name + "$"
    if name in COMMAND_DENY:
        assert command_status(name) == "denied" and classify(span).kind == "plain"
    else:
        assert command_status(name) == "allowed"
        structural = {"begin", "end", "left", "right", "middle", "tag", "notag", "nonumber", "substack"} | TEXT_COMMANDS
        if name not in structural:
            assert closed_scan(span).ok


def test_names_file_current_provenance():
    path = Path(lm.__file__).with_name("latex_names.json")
    assert path.exists(), "Run scripts/latex_export_names.py"
    names = json.loads(path.read_text())
    vocabulary = Path(lm.__file__).resolve().parents[2] / "documents/katex_commands.json"
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


def test_missing_and_stale_names_raise_and_name_script(tmp_path, monkeypatch):
    original = json.loads(Path(lm.__file__).with_name("latex_names.json").read_text())
    vocabulary = tmp_path / "documents/katex_commands.json"
    vocabulary.parent.mkdir()
    real_vocabulary = Path(lm.__file__).resolve().parents[2] / "documents/katex_commands.json"
    vocabulary.write_bytes(real_vocabulary.read_bytes())
    # Match the module's parents[2] documents lookup with a deeper fake module.
    fake_module = tmp_path / "workflow/report/latex_math.py"
    fake_module.parent.mkdir(parents=True)
    monkeypatch.setattr(lm, "__file__", str(fake_module))
    lm._names.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match="scripts/latex_export_names.py"):
            classify("$x$")
        for field in ("preamble_sha256", "katex_commands_sha256", "katex_version"):
            stale = {**original, field: "stale"}
            fake_module.with_name("latex_names.json").write_text(json.dumps(stale))
            with pytest.raises(ValueError, match="scripts/latex_export_names.py"):
                lm._names()
    finally:
        lm._names.cache_clear()


def reference_escape(text):
    """Test-owned text oracle; never calls the production escaper or renderer."""
    mapping = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
        "&": r"\&", "#": r"\#", "^": r"\textasciicircum{}", "_": r"\_",
        "%": r"\%", "~": r"\textasciitilde{}",
    }
    result = []
    cursor = 0
    while cursor < len(text):
        ch = text[cursor]
        if ch.isspace() and ch != "\u00a0":
            if not result or result[-1] != " ":
                result.append(" ")
            cursor += 1
            while cursor < len(text) and text[cursor].isspace() and text[cursor] != "\u00a0":
                cursor += 1
            continue
        if unicodedata.category(ch) == "Cc":
            cursor += 1
            continue
        if ch == "\\":
            end = cursor + 1
            while end < len(text) and text[end] == "\\":
                end += 1
            count = end - cursor
            paired = count % 2 == 1 and end < len(text) and text[end] == "$"
            result.extend([mapping["\\"]] * (count - int(paired)))
            if paired:
                result.append(mapping["$"])
            cursor = end + int(paired)
            continue
        if ch == '"':
            opening = cursor == 0 or text[cursor - 1].isspace() or text[cursor - 1] in "([{"
            result.append("``" if opening else "''")
        elif ch == "\u00a0":
            result.append("~")
        elif ch in SYMBOLS:
            result.append("\\ensuremath{" + SYMBOLS[ch] + "}")
        else:
            result.append(mapping.get(ch, ch))
        cursor += 1
    return "".join(result)


def reference_math_body(span):
    """Rewrite saved input without latex_math bodies, tokens, or rewrite helpers."""
    display = span.startswith("$$")
    width = 2 if display else 1
    body = span[width:-width]
    result = []
    text_groups = []
    pending_text = False
    cursor = 0
    while cursor < len(body):
        ch = body[cursor]
        in_text = bool(text_groups and text_groups[-1])
        if ch == "\\":
            end = cursor + 1
            while end < len(body) and body[end] in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                end += 1
            if end == cursor + 1:
                end += 1  # A control symbol consumes its escaped brace or dollar.
            word = body[cursor + 1:end]
            result.append({"lt": "<", "gt": ">"}.get(word, body[cursor:end]))
            pending_text = word in {"text", "textrm", "textbf", "textit", "textsf", "texttt"}
            cursor = end
            continue
        if ch == "{":
            text_groups.append(in_text or pending_text)
            pending_text = False
        elif ch == "}":
            text_groups.pop()
        value = SYMBOLS.get(ch, ch)
        if ch in SYMBOLS:
            if in_text:
                value = "\\ensuremath{" + value + "}"
            elif (value.startswith("\\") and value[1:].isascii() and value[1:].isalpha()
                  and cursor + 1 < len(body) and unicodedata.category(body[cursor + 1])[0] in "LM"):
                value += " "
        result.append(value)
        cursor += 1
    rewritten = "".join(result)
    return rewritten.strip() if display else rewritten


def reference_parts(source, *, cell=False, label=None):
    """Use classification for layout only; derive all bodies from saved input."""
    parts = []
    previous_display = False
    for piece_kind, piece in split_text(source):
        m = classify(piece, cell=cell) if piece_kind == "math" else None
        display = m is not None and m.kind.startswith("display_")
        if m is None or m.kind == "plain":
            current = [(reference_escape(piece), "escaped")]
        else:
            body = reference_math_body(piece)
            if m.kind == "inline":
                current = [("$", "wrapper"), (body, "body"), ("$", "wrapper")]
            elif m.kind == "display_env":
                current = [("\n", "wrapper"), (body, "body"), ("\n", "wrapper")]
            else:
                env = "equation" if m.labelable and label is not None else "equation*"
                current = [("\n\\begin{" + env + "}\n", "wrapper")]
                if m.labelable and label is not None:
                    current.append(("\\label{" + label + "}\n", "wrapper"))
                inner = {"display_aligned": "aligned", "display_gathered": "gathered"}.get(m.kind)
                if inner is not None:
                    current.append(("\\begin{" + inner + "}\n", "wrapper"))
                current.append((body, "body"))
                if inner is not None:
                    current.append(("\n\\end{" + inner + "}", "wrapper"))
                current.append(("\n\\end{" + env + "}\n", "wrapper"))
        if display:
            # Only layout boundaries may lose whitespace; body text is untouched.
            while parts:
                value, origin = parts.pop()
                trimmed = value.rstrip(" \t\n")
                if trimmed:
                    parts.append((trimmed, origin))
                    break
        elif previous_display:
            value, origin = current[0]
            current[0] = (value.lstrip(" \t"), origin)
        if any(value for value, _ in current):
            parts.extend(current)
            previous_display = display
    return parts


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


def output_origin_failure(source, output, *, cell=False, label=None):
    parts = reference_parts(source, cell=cell, label=label)
    origins = {}
    wrapper_dollars = set()
    offset = 0
    for value, origin in parts:
        dollars = {i for i, ch in enumerate(value) if ch == "$"} if origin == "wrapper" else set()
        tokens, failure = output_tokens(value, wrapper_dollars=dollars)
        if failure is not None:
            return f"{origin}: {failure}"
        wrapper_dollars.update(offset + i for i in dollars)
        for position, token in tokens:
            origins[offset + position] = (token, origin)
        offset += len(value)
    tokens, failure = output_tokens(output, wrapper_dollars=wrapper_dollars)
    if failure is not None:
        return failure
    if output != "".join(value for value, _ in parts):
        return "output differs from independently derived parts"
    for position, token in tokens:
        if position not in origins or origins[position][0] != token:
            return f"unrecorded token at {position}: {token}"
        origin = origins[position][1]
        if token in {r"\label", "$"} and origin != "wrapper":
            return f"wrapper token in {origin}: {token}"
        if token in {r"\begin", r"\end"}:
            # Body commands belong to scanned saved math; wrapper positions come
            # only from the exact display-kind layout above.
            if origin not in {"wrapper", "body"}:
                return f"environment token in {origin}: {token}"
    return None


@pytest.mark.parametrize("source,expected", [
    ("\\{}$&#^_%~", r"\textbackslash{}\{\}\$\&\#\textasciicircum{}\_\%\textasciitilde{}"),
    (r"a\$b", r"a\$b"),
    (r"a\\$b", r"a\textbackslash{}\textbackslash{}\$b"),
    (r"a\\\$b", r"a\textbackslash{}\textbackslash{}\$b"),
    ('"a" ("b") c"d', "``a'' (``b'') c''d"),
    (" \x00 \t\n a\u00a0b ", " a~b "),
])
def test_reference_escaper_exact_contract(source, expected):
    assert reference_escape(source) == expected


@pytest.mark.parametrize("source,expected", [
    (r"$\lt x\gt y\lthook$", r"< x> y\lthook"),
    ("$ αx $", r" \alpha x "),
    ("$$ \tαx\n $$", r"\alpha x"),
    (r"$\text {αx {°} \textbf{≥y} \{μ\}}$",
     r"\text {\ensuremath{\alpha}x {\ensuremath{{^{\circ}}}} \textbf{\ensuremath{\geq}y} \{\ensuremath{\mu}\}}"),
    (r"$$a\$b$$", r"a\$b"),
])
def test_reference_math_body_exact_contract(source, expected):
    assert reference_math_body(source) == expected


@pytest.mark.parametrize("ch,value", list(SYMBOLS.items()))
@pytest.mark.parametrize("following", ["x", "é", "\u0301", "1", " "])
def test_reference_math_symbol_boundaries(ch, value, following):
    space = " " if value.startswith("\\") and unicodedata.category(following)[0] in "LM" else ""
    assert reference_math_body("$" + ch + following + "$") == value + space + following
    assert reference_math_body("$\\text{" + ch + following + "}$") == "\\text{\\ensuremath{" + value + "}" + following + "}"


@pytest.mark.parametrize("output", [r"$\^^{\circ}$", r"$\alphaé$", r"$\geqı$", "$\\alpha\u0301$"])
def test_no_leak_checker_rejects_tex_tokenization_hazards(output):
    assert output_tokens(output, wrapper_dollars={0, len(output) - 1})[1] is not None


@pytest.mark.parametrize("body", ["x$y", r"x\\$y", r"\text{x$y}"])
def test_no_leak_checker_rejects_bare_body_dollars(body):
    assert "bare $" in output_tokens(body)[1]


@pytest.mark.parametrize("source", ["$x$", r"$a\$b$", r"$$a\$b$$"])
@pytest.mark.parametrize("cell", [False, True])
def test_no_leak_checker_accepts_wrapper_and_escaped_dollars(source, cell):
    assert output_origin_failure(source, convert_text(source, cell=cell)[0], cell=cell) is None


@pytest.mark.parametrize("source", [r"$\input{x}$", r"$\alphaé$", "$x&y$"])
def test_independent_origin_oracle_rejects_bare_command_from_class_a(source):
    assert output_origin_failure(source, r"\alpha") is not None


@pytest.mark.parametrize("source", ["plain", "$x$", "$$x$$", "$$x&=y$$", r"$$x\\y$$",
                                       r"$$x\tag{a}$$", r"$$\begin{align}x\end{align}$$"])
def test_origin_oracle_rejects_misplaced_wrappers(source):
    assert output_origin_failure(source, r"\begin{equation*}" + convert_text(source)[0]) is not None


def test_independent_origin_oracle_catches_rewrite_dollar_leak(monkeypatch):
    original_rewrite = lm._rewrite
    monkeypatch.setattr(lm, "_rewrite", lambda body, scan: "x$y" if body == "x" else original_rewrite(body, scan))
    output, _ = convert_text("$x$")
    assert output == "$x$y$"
    assert output_origin_failure("$x$", output) == "bare $ at 4"


def test_no_leak_seeded_property():
    rng = random.Random(51023000)
    pool = ["word", "$", "$$", r"\$", "\n", "\n\n", "&", r"\\", "%", "#", "^^", "{", "}",
            "≥", "αx", "°", "^", "é", "ı", "\u0301", r"\alphaé", r"\geqı", "\\alpha\u0301",
            "界", "\x00", "\r", "\u00a0", "\u200e", r"\input{x}", r"\begin {document}",
            "\\begin\n{aligned}", r"\end {aligned}", r"\begin{aligned}", r"\end{aligned}"]
    pool += ["\\" + name for name in sorted(katex_known()["commands"])]
    pool += ["\\begin{" + name + "}" for name in sorted(katex_known()["environments"])]
    pool += ["\\end{" + name + "}" for name in sorted(katex_known()["environments"])]
    sources = [r"$$\begin {aligned}x&=y\end {aligned}$$",
               "$$\\begin\n{aligned}x&=y\\end\n{aligned}$$",
               "$^°$", r"$\^°$", "$x^°$", "$30°$", r"$\text{°}$",
               "$$x$y$$", r"$$\text{x$y}$$", r"$$a\$b$$",
               r"$\alphaé$", r"$\geqı$", "$\\alpha\u0301$", r"$\alpha é$", r"$\alpha1$",
               r'  "a" \\\$ \input{x} $x&y$ ',
               " \x00 \t $x&y$",
               "a $$x$$ $$y$$ b", "$$x$$$$y$$", r"$$x&y$$", r"$$x\\y$$", r"$$x\tag{a}$$"]
    # Also generate closed bodies so dollar and command-boundary hazards do not
    # depend on randomly finding both delimiters in the mixed-text corpus.
    sources += ["$$" + "".join(rng.choice(["x", "°", "^", "$", r"\alpha", "é", "ı", "\u0301"])
                                 for _ in range(rng.randrange(1, 10))) + "$$" for _ in range(300)]
    sources += ["".join(rng.choice(pool) for _ in range(rng.randrange(1, 30))) for _ in range(3000)]
    for source in sources:
        collector = Unmapped()
        output, notes = convert_text(source, unmapped=collector)
        assert output_origin_failure(source, output) is None, (source, output)
        assert all(note.isascii() and "\n" not in note for note in notes)
    for source in sources[:22]:
        for cell in (False, True):
            output, _ = convert_text(source, cell=cell, label_for=lambda index, m: "eq:EQ1")
            assert output_origin_failure(source, output, cell=cell, label="eq:EQ1") is None, (source, output)
    assert convert_text(sources[0])[0] == "\n\\begin{equation*}\n\\begin {aligned}x&=y\\end {aligned}\n\\end{equation*}\n"
