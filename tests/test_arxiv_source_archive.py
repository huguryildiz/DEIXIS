"""The arXiv source archive (slice 22, D104, decision 3): reading it in memory, its limits, macros, groups and the
KaTeX gate, and the bounded child process. Every archive is SYNTHETIC and built in memory; no network is used."""

import asyncio
import gzip
import io
import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from arxiv_helpers import make_arxiv_pdf, make_tar, no_network, source_archive  # noqa: F401 - no_network is an autouse fixture
from deixis.documents import arxiv_source as src

REPO = Path(__file__).resolve().parents[1]


def groups_of(tex: str) -> list[dict]:
    found, _ = src.source_groups({"main.tex": tex})
    return found


def doc(body: str, preamble: str = "") -> str:
    return "\\documentclass{article}\n" + preamble + "\n\\begin{document}\n" + body + "\n\\end{document}\n"


def test_inputs_are_inlined_to_depth_five_and_a_self_including_file_stops_there():
    files = {"main.tex": doc("\\input{sec/a}\n\\include{b}"), "sec/a.tex": "A \\input{c}", "sec/c.tex": "C text",
             "b.tex": "B \\input{b}"}
    tex, _ = src.flatten(files)
    assert "A C text" in tex and tex.count("B ") == 5  # b.tex inlined at depths 1 to 5, then the limit drops its own input
    assert "\\input" not in tex


def test_comments_are_stripped_but_an_escaped_percent_is_kept():
    assert src.strip_comments("a = 5\\% of b % a comment\nc") == "a = 5\\% of b \nc"
    assert src.strip_comments("x \\\\% comment") == "x \\\\"


def test_the_five_macro_forms_expand_including_optional_arguments_and_def_arguments():
    pre = ("\\newcommand{\\pr}[2][P]{#1(#2)}\\def\\pair#1#2{\\langle #1, #2\\rangle}"
           "\\DeclareMathOperator*{\\argmaxx}{arg\\,max}\\newcommand\\RR{\\mathbb{R}}\\newcommand{\\vv}{V}\\renewcommand{\\vv}{V}")
    found = groups_of(doc("\\begin{equation}\\pr{x} + \\pr[Q]{y} + \\pair{a}{b} + \\argmaxx_{z} \\in \\RR + \\vv\\end{equation}", pre))
    assert found[0]["latex"] == "P(x) + Q(y) + \\langle a, b\\rangle + \\operatorname*{arg\\,max}_{z} \\in \\mathbb{R} + V"
    assert found[0]["refused"] is None


def test_a_self_growing_macro_stops_at_the_expander_limit_and_leaves_out_only_its_group():
    found = groups_of(doc("\\begin{equation}\\grow + b\\end{equation}\n\\begin{equation}c = d\\end{equation}", "\\def\\grow{\\grow\\grow}"))
    assert found[0]["refused"] in ("macro_limit", "too_long") and found[1]["refused"] is None and found[1]["latex"] == "c = d"


def test_a_user_macro_with_two_bodies_anywhere_is_refused_and_one_body_expands_wherever_it_is_used():
    # Since Sol r8 position plays no part: a user macro with one body is expanded wherever the group is (a source that
    # compiles uses it only where it is defined); one renewed anywhere, here a top-level \renewcommand between two
    # equations, has two bodies and every group using it is refused. The r1 timeline is traded for safety.
    body = ("\\begin{equation}\\varx = b\\end{equation}\n\\renewcommand{\\varx}{c}\n\\begin{equation}\\varx = d\\end{equation}\n"
            "\\begin{equation}\\late + \\sty\\end{equation}\n\\def\\late{L}")
    found, info = src.source_groups({"main.tex": doc(body, "\\usepackage{defs}\\newcommand{\\varx}{a}"), "defs.sty": "\\newcommand{\\sty}{S}"})
    assert [(g["latex"], g["refused"]) for g in found] == [("\\varx = b", "macro_ambiguous"), ("\\varx = d", "macro_ambiguous"),
                                                         ("L + S", None)]
    assert found[0]["ambiguous"] == ["\\varx"] and info["ambiguous_macros"] == ["\\varx"]


def test_r8_providecommand_renew_only_and_a_known_name_are_never_trusted():
    eq = "\\begin{equation}\\myx + p\\end{equation}\\begin{equation}p = q\\end{equation}"
    for preamble in ("\\providecommand{\\myx}{a}", "\\renewcommand{\\myx}{a}", "\\newcommand{\\myx}{a}\\providecommand{\\myx}{a}"):
        found, info = src.source_groups({"main.tex": doc(eq, preamble)})
        assert [g["refused"] for g in found] == ["macro_ambiguous", None] and "\\myx" in info["ambiguous_macros"], preamble
    # a name KaTeX or the LaTeX kernel knows, defined once at the top level: not trusted (it may be used where that
    # definition is not in force); a name KaTeX does not know but the kernel defines is refused the same way
    for preamble, name in (("\\def\\alpha{\\beta}", "\\alpha"), ("\\renewcommand{\\vec}[1]{\\mathbf{#1}}", "\\vec"),
                           ("\\newcommand{\\a}{A}", "\\a"), ("\\let\\label\\relax", "\\label")):
        found, info = src.source_groups({"main.tex": doc(eq.replace("\\myx", name), preamble)})
        assert found[0]["refused"] == "macro_ambiguous" and name in info["ambiguous_macros"], preamble
    assert {"\\alpha", "\\label", "\\section", "\\begingroup", "\\a", "\\\\"} <= src.known_names() and "\\myx" not in src.known_names()


def test_r5_a_definition_that_may_not_run_let_or_a_delimited_def_refuses_the_groups_that_use_the_name():
    # Sol r5: (a) \iffalse then the same body repeated at the top level after the equation; (b) a local group; (c) \let;
    # (d) a \def with delimited parameters. Each used to expand silently with the wrong or the old body.
    long = " + ".join(f"q_{{{k}}}" for k in range(12))

    def one(preamble, body):
        found, info = src.source_groups({"main.tex": doc(body, preamble)})
        return [(g["latex"], g["refused"]) for g in found], info
    eq = "\\begin{equation}\\x + " + long + "\\end{equation}"
    rows, _ = one("\\newcommand{\\x}{a}\\iffalse\\renewcommand{\\x}{b}\\fi", eq + "\\renewcommand{\\x}{b}")
    assert rows[0][1] == "macro_ambiguous"
    rows, _ = one("\\newcommand{\\x}{a}", "{\\renewcommand{\\x}{b}}" + eq)
    assert rows[0][1] == "macro_ambiguous"
    rows, info = one("\\newcommand{\\x}{a}\\newcommand{\\y}{b}\\let\\x\\y", eq)
    assert rows[0][1] == "macro_ambiguous" and "\\x" in info["ambiguous_macros"]
    rows, info = one("\\newcommand{\\x}{a}\\def\\x#1,#2{#2}", eq)
    assert rows[0][1] == "macro_ambiguous" and "\\x" in info["ambiguous_macros"]
    for form in ("\\gdef\\x{b}", "\\edef\\x{b}", "\\DeclareRobustCommand{\\x}{b}", "\\NewDocumentCommand{\\x}{}{b}",
                 "\\global\\let\\x\\relax", "\\expandafter\\def\\csname x\\endcsname{b}", "\\csdef{x}{b}", "\\@namedef{x}{b}"):
        rows, info = one("\\newcommand{\\x}{a}" + form, eq)
        assert rows[0][1] == "macro_ambiguous" and not info["unbounded"], form
    # a name built by expansion cannot be bounded: every group that uses a macro of the archive is refused, others place
    for form in ("\\expandafter\\def\\csname\\prefix x\\endcsname{b}", "\\expandafter\\let\\name\\relax", "\\csdef{\\prefix}{b}"):
        found, info = src.source_groups({"main.tex": doc(eq + "\\begin{equation}p = q\\end{equation}", "\\newcommand{\\x}{a}" + form)})
        assert info["unbounded"] and [g["refused"] for g in found] == ["macro_ambiguous", None], form
    # a name of plain characters is bounded: a letter name is that macro, one with a digit cannot be written in an equation,
    # and a declaration with a plain-text argument marks its letter runs; none of them makes the source unbounded
    for form, marked in (("\\expandafter\\def\\csname ul9@Scale\\endcsname{#1}", set()),
                         ("\\DeclareGraphicsExtensions{.pdf,.png}", {"\\pdf", "\\png"}),
                         ("\\expandafter\\let\\csname ,\\endcsname\\relax", {"\\,"}),
                         ("\\DeclareOption{x}{}", {"\\x"})):
        found, info = src.source_groups({"main.tex": doc(eq + "\\begin{equation}p = q\\end{equation}", "\\newcommand{\\x}{a}" + form)})
        assert not info["unbounded"] and marked <= set(info["ambiguous_macros"]), form
        assert [g["refused"] for g in found] == ["macro_ambiguous" if "\\x" in marked else None, None], form


def test_r6_latex3_code_or_a_definition_inside_a_group_refuses_every_group_that_uses_the_name():
    # Sol r6: (1) `\\cs_set:Npn \\x {b}` under \\ExplSyntaxOn was read as `\\cs`, so `\\x` expanded to its old body;
    # (2) `\\begingroup\\def\\alpha{\\beta}\\endgroup` was applied to the next equation. Both direct and through a macro.
    def rows(preamble, body):
        found, info = src.source_groups({"main.tex": doc(body, preamble)})
        return [(g["latex"], g["refused"]) for g in found], info
    plain = "\\begin{equation}p = q\\end{equation}"
    for expl in ("\\ExplSyntaxOn\\cs_set:Npn \\x {b}\\ExplSyntaxOff", "\\ExplSyntaxOn\\tl_set:Nn \\alpha {b}\\ExplSyntaxOff",
                 "\\cs_new:Npn \\x {b}"):
        found, info = rows("\\newcommand{\\x}{a}\\newcommand{\\wrap}{\\x}" + expl,
                           "\\begin{equation}\\x + 1\\end{equation}\\begin{equation}\\wrap + 1\\end{equation}"
                           "\\begin{equation}\\alpha + 1\\end{equation}" + plain)
        assert info["unbounded"], expl
        assert [r for _, r in found] == ["macro_ambiguous"] * 3 + [None], expl  # \\alpha too: any name may be redefined
    for local in ("\\begingroup\\def\\alpha{\\beta}\\endgroup", "\\bgroup\\renewcommand{\\alpha}{\\beta}\\egroup",
                  "{\\def\\alpha{\\beta}}", "\\begin{lemma}\\def\\alpha{\\beta}\\end{lemma}"):
        found, info = rows("\\newcommand{\\wrap}{\\alpha}",
                           local + "\\begin{equation}\\alpha + p = q\\end{equation}\\begin{equation}\\wrap\\end{equation}" + plain)
        assert not info["unbounded"] and "\\alpha" in info["ambiguous_macros"], local
        assert found == [("\\alpha + p = q", "macro_ambiguous"), ("\\alpha", "macro_ambiguous"), ("p = q", None)], local
    # a built name with a plain-letter prefix is bounded by it: names with that prefix are unsafe, others are not
    for built in ("\\newcommand\\citecolor[1]{\\@namedef{keycolor#1}{b}}", "\\expandafter\\def\\csname keycolor#1\\endcsname{b}"):
        found, info = rows("\\newcommand{\\keycolorx}{a}\\newcommand{\\wrap}{\\keycolorx}" + built,
                           "\\begin{equation}\\keycolorx\\end{equation}\\begin{equation}\\wrap\\end{equation}"
                           "\\begin{equation}\\alpha + 1\\end{equation}")
        assert not info["unbounded"] and info["ambiguous_prefixes"] == ["keycolor"], built
        assert [r for _, r in found] == ["macro_ambiguous", "macro_ambiguous", None], built
    # a user macro defined once inside a group and used inside it places; an \\input inside an environment still runs
    found, _ = rows("", "\\begingroup\\newcommand{\\myop}{M}\\begin{equation}\\myop + p = q\\end{equation}\\endgroup")
    assert found == [("M + p = q", None)]
    found, _ = src.source_groups({"main.tex": doc("\\begin{appendix}\\input{app}\\end{appendix}"),
                                  "app.tex": "\\begin{equation}r = s\\end{equation}"})
    assert [(g["latex"], g["refused"]) for g in found] == [("r = s", None)]


def test_r9_a_name_that_a_name_building_construct_gives_is_never_trusted():
    # Sol r9: {\newcommand{\foo}{x}} then a bare \csname foo\endcsname makes \foo \relax outside the group, so the printed
    # equation has no x; the one body was expanded anyway. Any name a name-building construct gives is now unsafe.
    long = " + ".join("abcdefghijk")
    eq = "\\begin{equation}\\foo + " + long + " = l\\end{equation}\\begin{equation}p = q\\end{equation}"
    for build in ("\\csname foo\\endcsname", "\\makeatletter\\@ifundefined{foo}{}{}\\makeatother",
                  "\\ifcsname foo\\endcsname\\fi", "\\expandafter\\ifx\\csname foo\\endcsname\\relax\\fi", "\\csuse{foo}",
                  "\\ifcsdef{foo}{}{}", "\\makeatletter\\@nameuse{foo}\\makeatother", "\\makeatletter\\@ifdefinable\\foo{}\\makeatother"):
        found, info = src.source_groups({"main.tex": doc("{\\newcommand{\\foo}{x}}" + build + eq)})
        assert [g["refused"] for g in found] == ["macro_ambiguous", None] and "\\foo" in info["ambiguous_macros"], build
        assert not info["unbounded"], build
    # a computed name keeps the prefix and unbounded rules; the same macro with no such construct expands
    found, info = src.source_groups({"main.tex": doc("\\makeatletter\\@ifundefined{fo#1}{}{}\\makeatother" + eq, "\\newcommand{\\foo}{x}")})
    assert info["ambiguous_prefixes"] == ["fo"] and found[0]["refused"] == "macro_ambiguous"
    found, info = src.source_groups({"main.tex": doc("\\csname\\prefix foo\\endcsname" + eq, "\\newcommand{\\foo}{x}")})
    assert info["unbounded"] and [g["refused"] for g in found] == ["macro_ambiguous", None]
    # Sol r10: an argument holding a control sequence is computed (\\pick expands to foo), so the source is unbounded;
    # so is one holding `#` after anything but plain letters, and a control sequence given where a name is expected
    for build in ("\\makeatletter\\@nameuse{\\pick}\\makeatother", "\\csname\\pick\\endcsname",
                  "\\makeatletter\\@nameuse\\pick\\makeatother", "\\ifcsdef{\\pick}{}{}", "\\csname fo\\pick\\endcsname",
                  "\\makeatletter\\@ifundefined{,#1}{}{}\\makeatother", "\\makeatletter\\@ifundefined{f9#1}{}{}\\makeatother"):
        found, info = src.source_groups({"main.tex": doc("{\\newcommand{\\foo}{x}}" + build + eq, "\\def\\pick{foo}")})
        assert info["unbounded"] and [g["refused"] for g in found] == ["macro_ambiguous", None], build
    found, info = src.source_groups({"main.tex": doc(eq, "\\newcommand{\\foo}{x}")})
    assert found[0]["latex"] == "x + " + long + " = l" and found[0]["refused"] is None


def test_r11_what_the_scan_cannot_read_fails_closed():
    # Sol r11: `\@nameuse{\pick{foo}}` has nested braces, the argument was not matched and the loop just stopped. Every
    # place the scan cannot read now makes the name unsafe or, when the name cannot be known, the source unbounded.
    long = " + ".join("abcdefghijk")
    eq = "\\begin{equation}\\foo + " + long + " = l\\end{equation}\\begin{equation}p = q\\end{equation}"

    def rows(body, preamble="", extra=None):
        found, info = src.source_groups({"main.tex": doc(body + eq, preamble)} | (extra or {}))
        return [g["refused"] for g in found], info
    unbounded = [("{\\newcommand{\\foo}{x}}\\makeatletter\\@nameuse{\\pick{foo}}\\makeatother", "\\def\\pick#1{#1}"),  # Sol's
                 ("\\newcommand{\\foo}{x}\\makeatletter\\@nameuse{foo", ""),  # an unclosed name argument
                 ("\\newcommand{\\foo}{x}\\makeatletter\\@ifundefined", ""),  # no argument at all
                 ("\\newcommand{\\foo}{x}\\endcsname", ""),  # a stray \endcsname
                 ("\\newcommand{\\foo}{x}\\csname foo", ""),  # a \csname never ended
                 ("\\newcommand{\\foo}{x}\\verb|open", ""),  # a \verb never closed on its line
                 ("\\newcommand{\\foo}{x}", "", {"notes.tex": "\\begin{comment} x"})]  # a verbatim-like environment never ended
    for body, preamble, *extra in unbounded:
        refused, info = rows(body, preamble, *extra)
        assert info["unbounded"] and refused[0] == "macro_ambiguous", body + preamble
    # a truncated or malformed definition makes its own name unsafe
    for preamble in ("\\newcommand{\\foo}{x}\\def\\foo", "\\newcommand{\\foo}{x}\\newcommand{\\foo}", "\\newcommand{\\foo}[1]{x#2}",
                     "\\newcommand{\\foo}{x}\\def\\foo #1{y}"):
        refused, info = rows("", preamble)
        assert refused == ["macro_ambiguous", None] and "\\foo" in info["ambiguous_macros"], preamble
    refused, info = rows("", "", {"late.tex": "\\newcommand{\\foo}{x"})  # a body never closed, in a file never read
    assert refused == ["macro_ambiguous", None] and "\\foo" in info["ambiguous_macros"]
    # a use whose argument cannot be read (the group ends first, an unclosed optional argument) refuses its group
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}p + \\pr\\end{equation}\\begin{equation}\\pr[a + b\\end{equation}"
                                                  "\\begin{equation}\\pr{y}\\end{equation}", "\\newcommand{\\pr}[2][P]{#1(#2)}")})
    assert [(g["latex"], g["refused"]) for g in found][2] == ("P(y)", None)
    assert [g["refused"] for g in found][:2] == ["macro_ambiguous", "macro_ambiguous"]
    # Sol r12: the optional argument ended at the first `]`, even inside braces: `\\myop[{x]y}]{z}` expanded wrongly and
    # placed. Braces in an optional argument now make the use unreadable; a plain one still reads
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}\\myop[{x]y}]{z} + " + long + "\\end{equation}"
                                                  "\\begin{equation}\\myop[w]{z}\\end{equation}", "\\newcommand{\\myop}[2][d]{#1(#2)}")})
    assert found[0]["refused"] == "macro_ambiguous" and (found[1]["latex"], found[1]["refused"]) == ("w(z)", None)
    # Sol r13: a brace after `\\\\` (a line break) is a real brace; one after a single `\\` is an escaped character
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}\\myop[a\\\\{x]y\\\\}b]{z} + " + long + "\\end{equation}"
                                                  "\\begin{equation}\\myop[a\\{w\\}]{z}\\end{equation}", "\\newcommand{\\myop}[2][d]{#1(#2)}")})
    assert found[0]["refused"] == "macro_ambiguous" and (found[1]["latex"], found[1]["refused"]) == ("a\\{w\\}(z)", None)


def test_r7_r8_a_group_opened_by_a_macro_or_its_argument_cannot_carry_a_known_name_into_an_equation():
    # Sol r7: `\\startlocal` (a macro holding \\begingroup) and r8: `\\pass{\\begingroup}` (a macro's argument) open a group
    # the scan cannot see; a local `\\def\\alpha` there was applied to the next equation. \\alpha is a known name, so any
    # definition of it refuses every group that uses it, directly or through \\wrap, wherever the group is.
    eqs = "\\begin{equation}\\alpha + p = q\\end{equation}\\begin{equation}\\wrap\\end{equation}\\begin{equation}p = q\\end{equation}"
    wrap = "\\newcommand{\\wrap}{\\alpha}"
    cases = [({}, "\\newcommand{\\startlocal}{\\begingroup}", "\\startlocal\\def\\alpha{\\beta}\\endgroup"),
             ({"defs.tex": "\\def\\alpha{\\beta}"}, "\\newcommand{\\startlocal}{\\begingroup}", "\\startlocal\\input{defs}\\endgroup"),
             ({}, "\\let\\startlocal\\begingroup", "\\startlocal\\def\\alpha{\\beta}\\endgroup"),
             ({"defs.tex": "\\def\\alpha{\\beta}"}, "\\newcommand{\\pass}[1]{#1}", "\\pass{\\begingroup}\\input{defs}\\endgroup"),
             ({}, "\\newcommand{\\pass}[1]{#1}", "\\pass{\\begingroup}\\def\\alpha{\\beta}\\endgroup")]
    for extra, preamble, body in cases:
        found, info = src.source_groups({"main.tex": doc(body + eqs, wrap + preamble)} | extra)
        assert not info["unbounded"] and "\\alpha" in info["ambiguous_macros"], body
        assert [(g["latex"], g["refused"]) for g in found] == [("\\alpha + p = q", "macro_ambiguous"),
                                                             ("\\alpha", "macro_ambiguous"), ("p = q", None)], body
    # a user name given a second body inside such a group has two bodies: refused
    found, _ = src.source_groups({"main.tex": doc("\\pass{\\begingroup}\\def\\myx{b}\\endgroup\\begin{equation}\\myx\\end{equation}",
                                                  "\\newcommand{\\pass}[1]{#1}\\newcommand{\\myx}{a}")})
    assert found[0]["refused"] == "macro_ambiguous"
    # macros holding group primitives no longer make the source unbounded; the groups that use no unsafe name place
    harmless = ("\\newcommand{\\vv}[1]{\\mathbf{#1}_{#1}}\\newcommand{\\be}{\\begin{equation}}"
                "\\newcommand{\\tabincell}[2]{\\begin{tabular}{#1}#2\\end{tabular}}\\newcommand\\lead[1]{\\begingroup #1\\endgroup}")
    found, info = src.source_groups({"main.tex": doc("\\begin{equation}\\vv{p} = q\\end{equation}", harmless)})
    assert not info["unbounded"] and [(g["latex"], g["refused"]) for g in found] == [("\\mathbf{p}_{p} = q", None)]


def test_archive_packages_take_effect_wherever_they_are_loaded_and_a_file_never_read_defines_nothing():
    # Sol r2 finding 1: .sty files used to be applied in archive member order. Since r5 a package that redefines another's
    # macro makes it unsafe in either order; packages that define their own names expand.
    eq = "\\begin{equation}\\x = y\\end{equation}"
    a, b = "\\newcommand{\\x}{a}", "\\renewcommand{\\x}{b}"
    for files in ({"b.sty": b, "a.sty": a}, {"a.sty": a, "b.sty": b}):  # both archive orders
        assert groups_of_files(files | {"main.tex": doc(eq, "\\usepackage{a}\\usepackage{b}")})[0]["refused"] == "macro_ambiguous"
        found = groups_of_files({"a.sty": a, "b.sty": "\\newcommand{\\w}{w}"} | {"main.tex": doc(eq + "\\begin{equation}\\w\\end{equation}",
                                                                                              "\\usepackage{a,b}")})
        assert [(g["latex"], g["refused"]) for g in found] == [("a = y", None), ("w", None)]
    # a package loaded by another is read where that one requires it; one loaded twice is read once; an unloaded .sty and a
    # .def that no \input reaches define nothing (their macros stay unexpanded and fail the KaTeX gate); a .def that an
    # \input reaches does
    files = {"outer.sty": "\\RequirePackage{inner}\\newcommand{\\w}{outer}", "inner.sty": "\\newcommand{\\x}{inner}",
             "unused.sty": "\\newcommand{\\uu}{U}", "loose.def": "\\newcommand{\\dd}{D}",
             "used.def": "\\newcommand{\\e}{E}",
             "main.tex": doc("\\begin{equation}\\x + \\w\\end{equation}\\begin{equation}\\uu + \\dd\\end{equation}"
                             "\\begin{equation}\\e\\end{equation}", "\\usepackage{outer}\\usepackage{inner}\\input{used.def}")}
    found, info = src.source_groups(files)
    assert (found[0]["latex"], found[0]["refused"]) == ("inner + outer", None) and info["packages"] == ["outer.sty", "inner.sty"]
    assert found[1]["refused"] == "katex_unknown" and set(found[1]["unknown"]) == {"\\uu", "\\dd"}
    assert found[2]["latex"] == "E" and found[2]["refused"] is None


def test_a_load_that_may_not_run_reads_nothing_and_a_macro_it_would_change_is_never_placed():
    # Sol r3 finding 1: a load inside \iffalse … \fi, another conditional or a macro body counted as run. Whatever the load
    # rule decides, \x has two bodies in the archive (a.sty and bad.sty), so every group using it is refused; \z, defined
    # once and only in bad.sty, expands only when bad.sty is read.
    eq = "\\begin{equation}\\x = y\\end{equation}\\begin{equation}\\z\\end{equation}"
    a, bad = "\\newcommand{\\x}{a}", "\\renewcommand{\\x}{b}\\newcommand{\\z}{Z}"

    def outcome(preamble, extra=None, body=eq):
        found, info = src.source_groups({"a.sty": a, "bad.sty": bad, "main.tex": doc(body, preamble)} | (extra or {}))
        return [(g["latex"], g["refused"]) for g in found], info["packages"]
    refused = ([("\\x = y", "macro_ambiguous"), ("\\z", "katex_unknown")], ["a.sty"])
    assert outcome("\\usepackage{a}\\iffalse \\usepackage{bad} \\fi") == refused
    assert outcome("\\usepackage{a}\n% \\usepackage{bad}\n") == refused
    assert outcome("\\usepackage{a}\\ifdefined\\foo\\usepackage{bad}\\else\\relax\\fi") == refused
    assert outcome("\\usepackage{a}\\newcommand{\\loadbad}{\\usepackage{bad}}") == refused
    assert outcome("\\usepackage{a}\\makeatletter\\@ifpackageloaded{x}{\\usepackage{bad}}{}\\makeatother") == refused
    assert outcome("\\usepackage{a}\\iffalse\\input{bad.def}\\fi", {"bad.def": bad}) == refused
    assert outcome("\\usepackage{a}\\ifx\\a\\b\\usepackage{bad}") == refused  # conditionals that never close
    # at the top level, \makeatletter around it, after a balanced conditional, after \newif and \iff: it runs
    ran = ([("\\x = y", "macro_ambiguous"), ("Z", None)], ["a.sty", "bad.sty"])
    assert outcome("\\usepackage{a}\\makeatletter\\usepackage{bad}\\makeatother") == ran
    assert outcome("\\usepackage{a}\\iffalse x \\fi\\newif\\ifdraft\\def\\q{p \\iff q}\\usepackage{bad}") == ran
    assert outcome("\\usepackage{a}\\ifthenelse{\\boolean{x}}{}{}\\usepackage{bad}") == ran


def test_r4_a_tex_input_that_may_not_run_or_a_verb_changes_no_equation():
    # Sol r4: (a) a .tex \input inside \iffalse or a macro body was read; (b) \verb content counted as a load or a comment.
    eq = "\\begin{equation}\\x = y\\end{equation}"
    files = {"a.sty": "\\newcommand{\\x}{a}", "bad.tex": "\\renewcommand{\\x}{b}", "new.tex": "\\newcommand{\\w}{w}"}

    def first(preamble):
        found, _ = src.source_groups(files | {"main.tex": doc(eq, preamble)})
        return found[0]["latex"], found[0]["refused"]
    assert first("\\usepackage{a}\\iffalse \\input{bad.tex} \\fi") == ("\\x = y", "macro_ambiguous")
    assert first("\\usepackage{a}\\newcommand{\\skipload}{\\input{bad.tex}}") == ("\\x = y", "macro_ambiguous")
    assert first("\\usepackage{a}\\verb|\\usepackage{bad}|") == ("\\x = y", "macro_ambiguous")  # bad.tex still defines \x
    found, _ = src.source_groups(files | {"main.tex": doc("\\begin{equation}\\w\\end{equation}", "\\verb|%| \\input{new.tex}")})
    assert (found[0]["latex"], found[0]["refused"]) == ("w", None)  # the real \input after the verb runs
    # the strip itself: verb and verbatim content blanked, never a command or a comment
    assert src.strip_comments("\\verb|%| \\input{x}") == "\\verb| | \\input{x}"
    assert src.strip_comments("\\verb*+\\input{x}+ y % c") == "\\verb*+" + " " * 9 + "+ y "
    assert src.strip_comments("\\begin{verbatim}\n\\input{x} % no\n\\end{verbatim} z") == "\\begin{verbatim}\n" + " " * 14 + "\n\\end{verbatim} z"
    assert src.strip_comments("100\\% sure % gone\nnext") == "100\\% sure \nnext"
    # a .tex input inside a conditional reads nothing, its equations included
    found, _ = src.source_groups({"sec.tex": "\\begin{equation}q = r\\end{equation}", "main.tex": doc("\\iffalse\\input{sec}\\fi p")})
    assert found == []
    found, _ = src.source_groups({"sec.tex": "\\begin{equation}q = r\\end{equation}", "main.tex": doc("\\input{sec}")})
    assert [g["latex"] for g in found] == ["q = r"]


def test_an_identical_duplicate_definition_anywhere_does_not_make_a_macro_ambiguous():
    eq = "\\begin{equation}\\x = y\\end{equation}"
    for extra in ({"main.tex": doc(eq, "\\usepackage{a}\\def\\x{a}")},
                  {"main.tex": doc(eq, "\\usepackage{a}\\iffalse\\newcommand{\\x}{a}\\fi")},
                  {"notes.tex": "\\def\\x{a}", "main.tex": doc(eq, "\\usepackage{a}")}):
        found, info = src.source_groups({"a.sty": "\\newcommand{\\x}{a}"} | extra)
        assert (found[0]["latex"], found[0]["refused"]) == ("a = y", None) and info["ambiguous_macros"] == [], extra


def groups_of_files(files: dict[str, str]) -> list[dict]:
    found, _ = src.source_groups(files)
    return found


def test_the_expansion_cap_counts_every_macro_use_and_leaves_out_the_group_that_passes_it():
    # Sol r1 finding 2: 5,000 uses a pass for four passes used to count as four calls. \q expands to itself, so the text
    # stays under the length limit while the uses add up.
    pre = "\\newcommand{\\x}{}\\newcommand{\\q}{\\q}"
    body = ("\\begin{equation}a\\x = 1\\end{equation}\n\\begin{equation}" + "\\q " * 5000 + "\\end{equation}\n"
            "\\begin{equation}p = q\\end{equation}\n\\begin{equation}b\\x = 2\\end{equation}")
    found, info = src.source_groups({"main.tex": doc(body, pre)})
    assert found[0]["refused"] is None and found[0]["latex"] == "a = 1"
    assert found[1]["refused"] == "macro_limit"
    assert found[2]["refused"] is None and found[2]["latex"] == "p = q"  # a group needing no expansion is still read
    assert found[3]["refused"] == "macro_limit"  # the paper's count is spent
    assert info["expander_calls"] == src.MAX_EXPANDER_CALLS + 2


def test_a_group_growing_past_the_length_limit_stops_while_it_is_being_expanded():
    found, info = src.source_groups({"main.tex": doc("\\begin{equation}" + "\\w " * 50 + "\\end{equation}",
                                                     "\\newcommand{\\w}{" + "v" * 1000 + "}")})
    assert found[0]["refused"] == "too_long"
    assert info["expander_calls"] == 4 * src.MAX_GROUP_CHARS // 1000  # stopped at the use that passed 16,000 characters


def test_groups_follow_their_numbers():
    body = r"""
\begin{align} a &= b \\ c &= d \end{align}
\begin{align} e &= f \nonumber \\ g &= h \end{align}
\begin{align*} i &= j \end{align*}
\[ k = l \]
\begin{equation} m = n \tag{A1} \end{equation}
\begin{align} o &= p \\ q &= r \nonumber \\ s &= t \nonumber \end{align}
"""
    found = groups_of(doc(body))
    numbered = [(g["latex"], g["tag"], g["continues"]) for g in found if g["numbered"]]
    assert numbered == [
        ("\\begin{aligned}a &= b\\end{aligned}", None, False),
        ("\\begin{aligned}c &= d\\end{aligned}", None, False),
        ("\\begin{aligned}e &= f \\\\ g &= h\\end{aligned}", None, False),  # one group: numbered on its last row
        ("m = n", "A1", False),
        ("\\begin{aligned}o &= p\\end{aligned}", None, True),  # numbered on its first row, goes on unnumbered
    ]
    assert [g for g in found if g["numbered"]][-1]["refused"] == "continues_after_number"
    assert [g["latex"] for g in found if not g["numbered"]] == ["\\begin{aligned}i &= j\\end{aligned}", "k = l",
                                                              "\\begin{aligned}q &= r \\\\ s &= t\\end{aligned}"]


def test_layout_commands_are_removed_the_rewrite_table_applies_and_references_are_never_placed():
    found = groups_of(doc("\\begin{equation}\\label{e} x \\hspace{1em} = \\mbox{rate} \\setcounter{a}{2}\\end{equation}"
                          "\\begin{equation} y = z \\eqref{e}\\end{equation}"
                          "\\begin{equation} u = \\paren{v}\\end{equation}"))
    assert found[0]["latex"] == "x = \\text{rate}" and found[0]["refused"] is None
    assert found[1]["refused"] == "ref_or_cite"
    assert found[2]["refused"] == "katex_unknown" and found[2]["unknown"] == ["\\paren"]


def test_a_control_symbol_macro_expands_and_an_undefined_one_is_refused_by_the_katex_gate():
    # Found in acceptance (b) on a real source: \newcommand{\1}[1]{...} was left unexpanded and KaTeX could not draw it.
    found = groups_of(doc("\\begin{equation} X = \\sum_i \\1{D_i} \\\\1 \\end{equation}", "\\newcommand{\\1}[1]{{\\bf 1}\\left[#1\\right]}"))
    assert found[0]["latex"] == "\\begin{aligned}X = \\sum_i {\\bf 1}\\left[D_i\\right] \\\\1\\end{aligned}"  # `\\1` is `\\` then 1
    assert found[0]["refused"] is None
    found = groups_of(doc("\\begin{equation} x = \\1{D} + \\, y \\end{equation}"))
    assert found[0]["refused"] == "katex_unknown" and found[0]["unknown"] == ["\\1"]


def test_a_trailing_control_space_does_not_eat_the_closing_aligned():
    # Found in acceptance (b): `\end{array}\` then a newline became `\end{array}\\end{aligned}`.
    found = groups_of(doc("\\begin{equation}\\begin{array}{l} a \\\\ b \\end{array}\\\n\\label{m}\\end{equation}"))
    assert found[0]["latex"] == "\\begin{aligned}\\begin{array}{l} a \\\\ b \\end{array}\\end{aligned}"


def test_katex_commands_file_carries_the_web_apps_katex_version():
    data = json.loads((REPO / "backend/deixis/documents/katex_commands.json").read_text())
    package = json.loads((REPO / "apps/web/package.json").read_text())
    assert data["katex_version"] == package["dependencies"]["katex"].lstrip("^~") == "0.16.47"
    assert {"frac", "mathbb", "text", "operatorname"} <= set(data["commands"]) and "paren" not in data["commands"]
    assert "aligned" in data["environments"]
    assert {",", ";", "!", "{", "}", "\\"} <= set(data["symbols"]) and "1" not in data["symbols"]
    assert (REPO / "scripts/katex_commands.mjs").read_text().count("katex_commands.json") >= 1


def test_archive_limits_members_size_and_bombs():
    members = make_tar({f"f{i}.txt": "x" for i in range(1001)})
    assert src.read_archive(members).content == "too_large"
    started = time.perf_counter()
    bomb = gzip.compress(b"\0" * (100 * 1024 * 1024))
    assert len(bomb) < 200_000 and src.read_archive(bomb).content == "too_large"
    assert time.perf_counter() - started < src.CHILD_TIMEOUT_SECONDS
    big = make_tar({"main.tex": "\\begin{document}" + "a" * (6 * 1024 * 1024)})
    assert src.read_archive(big).content == "too_large"


def test_links_devices_and_unsafe_names_are_never_read_and_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(os.listdir(tempfile.gettempdir())), sorted(os.listdir(tmp_path))
    link = tarfile.TarInfo("link.tex")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    hard = tarfile.TarInfo("hard.tex")
    hard.type, hard.linkname = tarfile.LNKTYPE, "main.tex"
    device = tarfile.TarInfo("dev.tex")
    device.type = tarfile.CHRTYPE
    fifo = tarfile.TarInfo("pipe.tex")
    fifo.type = tarfile.FIFOTYPE
    archive = src.read_archive(make_tar({"main.tex": doc("x"), "../evil.tex": "evil", "/etc/evil.tex": "evil"},
                                        extra=[link, hard, device, fifo]))
    assert archive.content == "tex" and set(archive.files) == {"main.tex"}
    assert (sorted(os.listdir(tempfile.gettempdir())), sorted(os.listdir(tmp_path))) == before


def test_a_pdf_is_pdf_only_a_tar_without_tex_is_no_tex_and_a_single_gzipped_tex_is_read():
    assert src.read_archive(make_arxiv_pdf()).content == "pdf_only"
    assert src.read_archive(make_tar({"fig.eps": "%!PS", "paper.dvi": b"\xf7\x02"})).content == "no_tex"
    single = src.read_archive(gzip.compress(doc("\\begin{equation} a = b \\end{equation}").encode()))
    assert single.content == "tex" and list(single.files) == ["main.tex"]
    assert src.read_archive(b"not an archive at all").content == "no_tex"


def test_the_child_is_stopped_at_its_time_limit_and_its_output_limit():
    slow = asyncio.run(src.run_child([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1))
    assert slow.failure == "timed_out"
    loud = asyncio.run(src.run_child([sys.executable, "-c", "import sys; sys.stdout.write('x' * 3_000_000)"], max_stdout=1_000_000))
    assert loud.failure == "output_too_large"


def test_a_child_writing_a_megabyte_to_stderr_before_stdout_does_not_stall_and_keeps_only_the_tail():
    code = "import sys; sys.stderr.write('e' * 1_048_576 + 'END'); sys.stderr.flush(); sys.stdout.write('{\"content\": \"tex\"}')"
    started = time.perf_counter()
    result = asyncio.run(src.run_child([sys.executable, "-c", code], timeout=src.CHILD_TIMEOUT_SECONDS))
    assert time.perf_counter() - started < 10 and result.failure is None and result.stdout == b'{"content": "tex"}'
    assert len(result.stderr_tail) == src.OUTPUT_TAIL_CHARS and result.stderr_tail.endswith("END")


def test_a_child_limit_or_the_memory_watch_makes_the_source_unreadable(tmp_path, monkeypatch):
    for failure in ("timed_out", "memory_limit", "output_too_large"):
        async def fake(argv, stdin=b"", **kwargs):
            return src.ChildResult(None, b"", "SYNTHETIC", failure)
        monkeypatch.setattr(src, "run_child", fake)
        found = asyncio.run(src.read_source(source_archive(), tmp_path / "x.pdf", set()))
        assert found["content"] == "unreadable" and found["error"] == failure


def test_the_real_child_reads_a_synthetic_source_against_a_synthetic_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_arxiv_pdf())
    found = asyncio.run(src.read_source(source_archive(), path, set()))
    assert found["content"] == "tex" and [p["n"] for p in found["placements"]] == ["1", "2"]
    assert found["placements"][0]["latex"] == "P_{a b} = c_{d}"
