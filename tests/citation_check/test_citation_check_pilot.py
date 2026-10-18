"""Verify Citations after the V5 live pilot (D105): table rows, plain claims, the negation phrases, the repair messages,
staleness by what the check uses and the freeze refused while a re-extraction waits.

The LaTeX sentences and the table are copied from the owner's draft of the pilot (`brief-short-v0.tex`, 18 Oct 2026)
and the passage excerpts from the pilot's given passages (published papers, a sentence or two each): they are real
pilot cases, NOT SYNTHETIC. The drafts, records and model answers of the workflow tests at the end are SYNTHETIC
(`test_citation_check_text`). No model is called; passing shows what the code does with these texts, not what a model
answers."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from deixis.documents import draft_parse, pdf
from deixis.domain import contracts
from deixis.domain.contracts import locate_anchor, quote_meaning, quote_meaning_differs
from deixis.workflow import equations
from test_citation_check_contract import SI, VALID, case, codes
from test_citation_check_run import answer, make, quote_of, run, sentence  # noqa: F401 - `make` is a fixture
from test_citation_check_text import A_PAGES, frozen, pair_rows, session, start, upload

# ---- from the owner's draft (V5 pilot), not SYNTHETIC

TABLE_TEX = r"""\begin{document}
\section{Related work}\label{sec:related}
Erçetin and Gedik define a Fidelity-Age that resets to zero after a usable delivery and schedule competing flows with heuristics built on it~\cite[pp.~7 to 12]{ercetin2026}~\tP.

\begin{table}[!htb]
\caption{Scheduling works reviewed (\cmark{} evidenced, \xmark{} not evidenced). Assignment: competing demands share resources. Age objective: delivered-entanglement age optimized or reported. Age-dependent fidelity: storage-age quality model in the formulation, not expiry. Exact MDP: full problem solved exactly. Delayed control: delayed observations or commands.}\label{tab:closest}
\centering\tablestyle\renewcommand{\arraystretch}{0.8}
% Hand-coded from the cited pages (17 October 2026); not generated.
\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lcccccc@{}}
\toprule
Work & \shortstack{Under-\\water} & \shortstack{Resource\\assignment} & \shortstack{Age\\objective} & \shortstack{Age-dep.\\fidelity} & \shortstack{Exact MDP\\solution} & \shortstack{Delayed\\control}\\
\midrule
Ceran~\cite{ceran2026} & \xmark & \xmark & \cmark & \xmark & \cmark & \xmark\\
Erçetin and Gedik~\cite{ercetin2026} & \xmark & \cmark & \cmark & \cmark & \xmark & \xmark\\
Mitrolaris~\cite{mitrolaris2026}; Banerjee~\cite{banerjee2026} & \xmark & \cmark & \cmark & \xmark & \xmark & \xmark\\
Kumar \emph{et al.}~\cite{kumar2023} & \xmark & \xmark & \xmark & \cmark & \xmark & \xmark\\
Haldar \emph{et al.}~\cite{haldar2025} & \xmark & \xmark & \cmark & \cmark & \xmark & \cmark\\
Shared storage~\cite{zubeldia2026,fittipaldi2023,promponas2024,bhambay2025,srikant2026,gu2023,rode2026} & \xmark & \cmark & \xmark & \xmark & \xmark & \xmark\\
\midrule
\textbf{Proposal (planned; $^{*}$deferred)} & \cmark & \cmark & \cmark & \cmark & \cmark & \cmark$^{*}$\\
\bottomrule
\end{tabular*}
\end{table}
\end{document}
"""
CAPTION = ("Scheduling works reviewed (yes evidenced, no not evidenced). Assignment: competing demands share resources. Age"
           " objective: delivered-entanglement age optimized or reported. Age-dependent fidelity: storage-age quality model"
           " in the formulation, not expiry. Exact MDP: full problem solved exactly. Delayed control: delayed observations"
           " or commands.")


def claims(text):
    draft = draft_parse.parse_draft("tex", text)
    return {m.raw: m for m in draft.markers}, draft


def test_a_table_citation_is_checked_against_its_row_as_header_cell_pairs_never_the_whole_table():
    found, draft = claims(TABLE_TEX)
    ceran = found[r"\cite{ceran2026}"]
    assert ceran.claim == ("Work: Ceran; Age objective: yes; Exact MDP solution: yes; Under-water: no; Resource assignment:"
                           " no; Age-dep. fidelity: no; Delayed control: no")
    assert ceran.claim_context == CAPTION
    # The raw sentence the screen marks the marker in is the row alone, never the tabular.
    row = draft.text[ceran.sentence_start:ceran.sentence_end]
    assert row.startswith(r"Ceran~\cite{ceran2026} & \xmark") and r"\begin{tabular" not in row and "Erçetin" not in row
    assert found[r"\cite{haldar2025}"].claim == ("Work: Haldar et al.; Age objective: yes; Age-dep. fidelity: yes; Delayed"
                                                 " control: yes; Under-water: no; Resource assignment: no; Exact MDP"
                                                 " solution: no")
    # Two citations of one row read the same row; seven keys of one marker read it once.
    assert found[r"\cite{mitrolaris2026}"].claim == found[r"\cite{banerjee2026}"].claim
    assert found[r"\cite{mitrolaris2026}"].claim.startswith("Work: Mitrolaris; Banerjee; Resource assignment: yes")
    assert found[r"\cite{zubeldia2026,fittipaldi2023,promponas2024,bhambay2025,srikant2026,gu2023,rode2026}"].claim == (
        "Work: Shared storage; Resource assignment: yes; Under-water: no; Age objective: no; Age-dep. fidelity: no; Exact"
        " MDP solution: no; Delayed control: no")
    # The sentence before the table is a sentence, not a row, and has no context.
    prose = found[r"\cite[pp.~7 to 12]{ercetin2026}"]
    assert prose.claim_context is None and prose.claim == ("Erçetin and Gedik define a Fidelity-Age that resets to zero"
                                                           " after a usable delivery and schedule competing flows with"
                                                           " heuristics built on it.")
    # Every table claim fits one part (the schema's 1,000 characters), so a model can copy it.
    assert all(len(m.claim) < 1000 for m in found.values())


def test_a_table_row_claim_is_covered_by_parts_copied_from_it_and_its_crosses_fit_one_part():
    found, _ = claims(TABLE_TEX)
    claim = found[r"\cite{ceran2026}"].claim
    parts = [{"text": "Work: Ceran; Age objective: yes"}, {"text": "Exact MDP solution: yes"},
             {"text": "Under-water: no; Resource assignment: no; Age-dep. fidelity: no; Delayed control: no"}]
    assert contracts.citation_check_covers(claim, parts) is True
    # The pilot's model answer copied the LaTeX table into a part; that text is no span of the row.
    assert contracts.citation_check_spans(claim, [{"text": r"Ceran~ & \xmark & \xmark & \cmark"}])[0] == [None]


def test_marks_unicode_ticks_and_empty_cells_follow_the_rule():  # SYNTHETIC
    text = ("\\begin{tabular}{lll}\nWork & A & Note\\\\\n\\midrule\nZeng \\cite{z} & ✓ & \\\\\n"
            "Kim \\cite{k} & ✗ & late\\\\\n\\end{tabular}\n")
    found, _ = claims(text)
    assert found[r"\cite{z}"].claim == "Work: Zeng; A: yes"
    assert found[r"\cite{k}"].claim == "Work: Kim; Note: late; A: no"
    assert found[r"\cite{k}"].claim_context is None  # a tabular outside a table environment has no caption


# ---- Sol round 1 of ace45a68: each repro below reached `found_whole`; now each is kept verbatim or refused.

@pytest.mark.parametrize("a, b", [  # SYNTHETIC
    (r"$\frac{1}{2+3}$", r"$\frac{1}{2}+3$"),
    (r"$x^{-12}$", r"$x^{-1}2$"),
    (r"$x^{12}$", r"$x^12$"),
    (r"$\sqrt{x+1}$", r"$\sqrt{x}+1$"),
    (r"$\left(a+b\right)c$", r"$(a+b)c$"),
])
def test_two_different_math_sources_never_give_the_same_claim(a, b):
    assert draft_parse.plain_latex(f"It is {a} here.") != draft_parse.plain_latex(f"It is {b} here.")


def test_sols_math_repros_stay_verbatim():  # SYNTHETIC
    assert draft_parse.plain_latex(r"It is $\frac{1}{2+3}$ here.") == r"It is $\frac{1}{2+3}$ here."
    assert draft_parse.plain_latex(r"It is $x^{-12}$ here.") == r"It is $x^{-12}$ here."
    assert draft_parse.plain_latex(r"It is $x^{-1}2$ here.") == r"It is $x^{-1}2$ here."
    # One-token scripts and allowlisted commands still convert.
    assert draft_parse.plain_latex(r"It is $x^2 + y_{i} \le \alpha$ here.") == "It is x^2 + y_i ≤ α here."


def test_kept_math_is_one_opaque_token_a_part_must_copy_whole_and_exactly():  # SYNTHETIC
    claim = draft_parse.plain_latex(r"The gain is $x^{-12}$ in water.")
    assert contracts.citation_check_covers(claim, [{"text": "The gain is $x^{-12}$ in water"}])
    for wrong in ("The gain is $x^{-1}2$ in water", "The gain is x^{-12} in water", "The gain is $x^{-12 }$ in water"):
        assert not contracts.citation_check_covers(claim, [{"text": wrong}])


def test_a_simple_table_is_read_with_its_leading_rules_and_spacing_stripped():  # SYNTHETIC
    text = ("\\begin{tabular}{lll}\n\\toprule\nWork & A & B\\\\\n\\midrule\nX \\cite{x} & yes & 3 m\\\\\n"
            "\\addlinespace \\rowcolor{gray} Y \\cite{y} & \\xmark & \\\\\n\\hline\nZ \\cite{z} & & late\\\\\n"
            "\\bottomrule\n\\end{tabular}\n")
    found, _ = claims(text)
    assert found[r"\cite{x}"].claim == "Work: X; A: yes; B: 3 m"
    assert found[r"\cite{y}"].claim == "Work: Y; A: no"
    assert found[r"\cite{z}"].claim == "Work: Z; B: late"


@pytest.mark.parametrize("text", [  # SYNTHETIC
    # Sol round 2: a \multicolumn in a data row after a rule (was "Work: 2 c X; A: yes").
    "\\begin{tabular}{lll}\nWork & A & B\\\\\n\\midrule \\multicolumn{2}{c}{X}\\cite{x} & yes\\\\\n\\end{tabular}\n",
    # Sol round 2: a \multirow from the row above is not carried (was "Mode: remote; Score: 2").
    "\\begin{tabular}{lll}\nSite & Mode & Score\\\\\n\\midrule\n\\multirow{2}{*}{Lab} & local & 1\\\\\n"
    " & remote \\cite{x} & 2\\\\\n\\end{tabular}\n",
    # Sol round 2: a two-line header without a rule (was "Age: yes").
    "\\begin{tabular}{ll}\nWork & Age\\\\\n & objective\\\\\nX \\cite{x} & yes\\\\\n\\end{tabular}\n",
    # Sol round 2: a citation in the second header line before the rule (was "Age: objective").
    "\\begin{tabular}{ll}\nWork & Age\\\\\n\\cite{x} & objective\\\\\n\\midrule\nX & yes\\\\\n\\end{tabular}\n",
    # A data \multicolumn: no longer spread over its headers.
    "\\begin{tabular}{lll}\nWork & A & B\\\\\n\\midrule\nX \\cite{x} & \\multicolumn{2}{c}{yes}\\\\\n\\end{tabular}\n",
    # A citation in a nested tabular, and the outer row holding it.
    "\\begin{tabular}{ll}\nWork & Notes\\\\\n\\midrule\nfirst \\cite{x} & \\begin{tabular}{l}Inner\\\\\n\\hline\nsecond"
    "\\\\\\end{tabular}\\\\\n\\end{tabular}\n",
    "\\begin{tabular}{ll}\nWork & Notes\\\\\n\\midrule\nfirst & \\begin{tabular}{l}Inner\\\\\n\\hline\nsecond \\cite{x}"
    "\\\\\\end{tabular}\\\\\n\\end{tabular}\n",
    # A \cline or \cmidrule anywhere, a row split with spacing, fewer cells than headers.
    "\\begin{tabular}{ll}\nWork & A\\\\\n\\midrule\nX \\cite{x} & yes\\\\\n\\cline{1-2}\nY & no\\\\\n\\end{tabular}\n",
    "\\begin{tabular}{ll}\nWork & A\\\\\n\\midrule\nX \\cite{x} & yes\\\\[2pt]\nY & no\\\\\n\\end{tabular}\n",
    "\\begin{tabular}{lll}\nWork & A & B\\\\\n\\midrule\nX \\cite{x} & yes\\\\\n\\end{tabular}\n",
    # \multirow in the citation's row.
    "\\begin{tabular}{ll}\nWork & A\\\\\n\\multirow{2}{*}{X \\cite{x}} & yes\\\\\n & no\\\\\n\\end{tabular}\n",
    # A header \multicolumn over two columns.
    "\\begin{tabular}{lll}\nWork & \\multicolumn{2}{c}{Shared}\\\\\nX \\cite{x} & yes & no\\\\\n\\end{tabular}\n",
    # A header over two rows before the rule.
    "\\begin{tabular}{ll}\nWork & Age\\\\\n & objective\\\\\n\\midrule\nX \\cite{x} & yes\\\\\n\\end{tabular}\n",
    # A nested tabular in the citation's own row.
    "\\begin{tabular}{ll}\nWork & Notes\\\\\nX \\cite{x} & \\begin{tabular}{l}a\\\\ b\\end{tabular}\\\\\n\\end{tabular}\n",
    # More cells than headers.
    "\\begin{tabular}{ll}\nWork & A\\\\\nX \\cite{x} & yes & no\\\\\n\\end{tabular}\n",
    # A citation in the header row.
    "\\begin{tabular}{ll}\nWork \\cite{x} & A\\\\\nY & yes\\\\\n\\end{tabular}\n",
])
def test_a_table_layout_not_read_one_cell_to_one_header_is_unrecognized_with_no_pair(text):
    found, _ = claims(text)
    cited = found[r"\cite{x}"]
    assert (cited.status, cited.targets, cited.claim, cited.reason) == ("unrecognized", [], "",
                                                                       draft_parse.TABLE_LAYOUT_NOT_READ)


TEX_HEAD = "\\documentclass{article}\n\\newcommand{\\site}{\\multirow{2}{*}{Lab}}\n\\newcommand{\\pair}{A & B}\n"


@pytest.mark.parametrize("table", [  # SYNTHETIC: Sol round 3, a user macro inside the tabular
    # `\site` is a \multirow: the continuation row lost Lab (was "Mode: remote; Score: 2").
    "\\begin{tabular}{lll}\nSite & Mode & Score\\\\\n\\midrule\n\\site & local & 1\\\\\n & remote \\cite{x} & 2\\\\\n"
    "\\end{tabular}",
    # `\pair` is two cells: header and row each lost one (was "Work: X").
    "\\begin{tabular}{lll}\nWork & \\pair\\\\\n\\midrule\nX \\cite{x} & \\pair\\\\\n\\end{tabular}",
    # A command off the allowlist in the column spec, and in math.
    "\\begin{tabular}{>{\\mycol}ll}\nWork & A\\\\\n\\midrule\nX \\cite{x} & yes\\\\\n\\end{tabular}",
    "\\begin{tabular}{ll}\nWork & A\\\\\n\\midrule\nX \\cite{x} & $\\pair$\\\\\n\\end{tabular}",
])
def test_a_command_off_the_tabular_allowlist_refuses_the_whole_table(table):
    found, _ = claims(TEX_HEAD + "\\begin{document}\n" + table + "\n\\end{document}\n")
    cited = found[r"\cite{x}"]
    assert (cited.status, cited.targets, cited.claim, cited.reason) == ("unrecognized", [], "",
                                                                       draft_parse.TABLE_LAYOUT_NOT_READ)


@pytest.mark.parametrize("name", ["\\textbf@pair", "\\@foo", "\\emph@x"])  # SYNTHETIC: Sol round 4
def test_a_command_name_with_at_is_read_whole_and_refuses_the_table(name):
    head = "\\makeatletter\\def" + name + "{A & B}\\makeatother\n"
    table = f"\\begin{{tabular}}{{lll}}\nWork & {name}\\\\\n\\midrule\nX \\cite{{x}} & {name}\\\\\n\\end{{tabular}}"
    found, _ = claims(head + "\\begin{document}\n" + table + "\n\\end{document}\n")
    cited = found[r"\cite{x}"]
    assert (cited.status, cited.claim, cited.reason) == ("unrecognized", "", draft_parse.TABLE_LAYOUT_NOT_READ)
    # In math inside the table too.
    table = f"\\begin{{tabular}}{{ll}}\nWork & A\\\\\n\\midrule\nX \\cite{{x}} & ${name}$\\\\\n\\end{{tabular}}"
    found, _ = claims("\\begin{document}\n" + table + "\n\\end{document}\n")
    assert found[r"\cite{x}"].reason == draft_parse.TABLE_LAYOUT_NOT_READ


def test_a_star_or_digit_after_an_allowed_name_reads_no_other_macro():  # SYNTHETIC
    for cell in ("\\textbf*{yes}", "\\emph2"):
        table = f"\\begin{{tabular}}{{ll}}\nWork & A\\\\\n\\midrule\nX \\cite{{x}} & {cell}\\\\\n\\end{{tabular}}"
        found, _ = claims("\\begin{document}\n" + table + "\n\\end{document}\n")
        assert found[r"\cite{x}"].status == "recognized"  # TeX reads `\textbf` then `*`, `\emph` then `2`
    # `\cite*` stays the cite family; `\cite@pair` is another macro, and a command inside a marker's note is checked.
    for cell, read in (("\\cite*{y}", True), ("\\cite@pair", False), ("\\cite[\\pair]{y}", False)):
        table = f"\\begin{{tabular}}{{ll}}\nWork & A\\\\\n\\midrule\nX \\cite{{x}} & {cell}\\\\\n\\end{{tabular}}"
        found, _ = claims("\\begin{document}\n" + table + "\n\\end{document}\n")
        assert (found[r"\cite{x}"].reason is None) is read, cell


def test_allowlisted_commands_in_body_spec_and_math_keep_the_table_read():  # SYNTHETIC
    text = ("\\begin{tabular*}{\\linewidth}{@{\\extracolsep{\\fill}}ll@{}}\n\\toprule\n\\textbf{Work} & \\shortstack{Rate\\\\"
            "(\\%)}\\\\\n\\midrule\n\\emph{X} \\citep[p.~2]{x} & $\\alpha^{*}$ \\cmark\\\\\n\\bottomrule\n\\end{tabular*}")
    found, _ = claims("\\begin{document}\n" + text + "\n\\end{document}\n")
    assert found[r"\citep[p.~2]{x}"].status == "recognized"
    assert found[r"\citep[p.~2]{x}"].claim.startswith("Work: X; Rate")


@pytest.mark.parametrize("raw, kept", [  # SYNTHETIC: Sol round 3, comment stripping
    ("X & yes\\\\% Fake \\cite{x} & no\\\\\nY", "X & yes\\\\\nY"),  # `\\%`: a line break, then a comment
    ("It rose 5\\% here \\cite{a}.", "It rose 5\\% here \\cite{a}."),  # `\%`: a literal percent sign
    ("a\\\\\\% b \\cite{a}.", "a\\\\\\% b \\cite{a}."),  # `\\\%`: a line break and a literal percent sign
    ("Before % hidden \\cite{z}\nafter", "Before \nafter"),
])
def test_a_percent_starts_a_comment_after_an_even_run_of_backslashes(raw, kept):
    assert draft_parse.strip_comments(raw) == kept


def test_a_cite_inside_a_comment_never_becomes_a_marker():  # SYNTHETIC
    text = ("\\begin{document}\nShown \\cite{a}. % hidden \\cite{z}\n\\begin{tabular}{ll}\nWork & A\\\\\n\\midrule\n"
            "X & yes\\\\% Fake \\cite{x} & no\\\\\nY \\cite{y} & no\\\\\n\\end{tabular}\n\\end{document}\n")
    found, _ = claims(text)
    assert set(found) == {r"\cite{a}", r"\cite{y}"}
    assert found[r"\cite{y}"].claim == "Work: Y; A: no"


def test_a_quote_overlapping_the_placeholder_even_in_part_is_refused():  # SYNTHETIC
    # Sol's repro: a passage that is only the placeholder.
    si, draft = case("The symbols are readable in the PDF", pdf.UNREADABLE,
                     [("The symbols are readable in the PDF", "readable in the PDF")])
    assert "quote_meaning_differs" in codes(si, draft)
    passage = "The map is " + pdf.UNREADABLE + " here."
    for quote in ("The map is [symbols", "PDF] here", "symbols not readable"):
        assert quote_meaning_differs(quote, passage, located(quote, passage)) == "placeholder"


@pytest.mark.parametrize("raw, plain", [
    # P44: \emph, the marker, a person's tag macro.
    (r"Haldar \emph{et al.} learn swap, wait and discard decisions from link ages, with state-dependent cutoffs below the"
     r" maximum~\cite[pp.~13, 15]{haldar2024}~\tP; in multiplexed chains they pair stored links by age, youngest first,"
     r" and charge classical communication time as extra aging~\cite[pp.~4, 5]{haldar2025}~\tP.",
     "Haldar et al. learn swap, wait and discard decisions from link ages, with state-dependent cutoffs below the maximum;"
     " in multiplexed chains they pair stored links by age, youngest first, and charge classical communication time as"
     " extra aging."),
    # P65: a run-in \textbf heading, tags with braces, inline and display math.
    (r"\textbf{Memory and fidelity.} Combining Werner-state decay~\cite[Eqs.~(1), (3)]{inesta2023}~\tP{} with ideal"
     r" swapping of independent inputs~\cite[arXiv v2, Eq.~(61)]{khatri2022}~\tP{}~\tA{}, a swap of links with ages $a$"
     r" and $b$ delivers fidelity \begin{equation} F(a,b)=\tfrac14\!\left(1+3w_0^2e^{-(a+b)\tau/T_2}\right), \qquad"
     r" w_0=(4F_0-1)/3,\label{eq:F} \end{equation} where $T_2$ is the adopted whole-link decay time \tA.",
     "Memory and fidelity. Combining Werner-state decay with ideal swapping of independent inputs, a swap of links with"
     r" ages a and b delivers fidelity $F(a,b)=\tfrac14\!\left(1+3w_0^2e^{-(a+b)\tau/T_2}\right), \qquad"
     r" w_0=(4F_0-1)/3,\label{eq:F}$ where T_2 is the adopted whole-link decay time."),
    # P73: a section heading and its label before the sentence, a thin space before a unit.
    (r"\section{Limitations and future work}\label{sec:limits}" "\n" r"No cited experiment shows an underwater memory"
     r" link or the adopted rate, fidelity and storage time together: the reviewed underwater systems use"
     r" prepare-and-measure BB84~\cite[p.~18]{paglierani2023}~\tP, and laboratory memory nodes keep inter-node"
     r" entanglement for up to 1\,s with error detection and dynamical decoupling~\cite[p.~5]{knaut2024}~\tP.",
     "No cited experiment shows an underwater memory link or the adopted rate, fidelity and storage time together: the"
     " reviewed underwater systems use prepare-and-measure BB84, and laboratory memory nodes keep inter-node entanglement"
     " for up to 1 s with error detection and dynamical decoupling."),
    # P08: a grouped exponent of two tokens stays verbatim, attached to its unit (Sol round 1).
    (r"Seawater loss depends on water type, with extinction coefficients of 0.151\,m$^{-1}$ in clear and 0.398\,m$^{-1}$"
     r" in coastal water~\cite[p.~13, Table~11]{paglierani2023}~\tP.",
     "Seawater loss depends on water type, with extinction coefficients of 0.151 m$^{-1}$ in clear and 0.398 m$^{-1}$ in"
     " coastal water."),
    # P61: a command off the allowlist and escaped braces keep the math verbatim.
    (r"A successful delivery resets it to $\min\{D,a+b\}$, adapting Ceran's pre-action input-age"
     r" sum~\cite[Eq.~(9)]{ceran2026}~\tP; otherwise it increases by one up to $D$.",
     r"A successful delivery resets it to $\min\{D,a+b\}$, adapting Ceran's pre-action input-age sum; otherwise it"
     " increases by one up to D."),
])
def test_a_latex_sentence_is_given_as_plain_text_the_same_way_everywhere(raw, plain):
    found, _ = claims("\\begin{document}\n" + raw + "\n\\end{document}")
    assert {m.claim for m in found.values()} == {plain}


@pytest.mark.parametrize("raw, plain", [  # SYNTHETIC
    (r"It rose by 5\,\% in 2019--2020 (see Fig.~\ref{f}) \footnote{Measured.} as ``expected''% a comment",
     "It rose by 5 % in 2019–2020 (see Fig.) Measured. as “expected”"),
    (r"Erg\"{o}r and Ga\c{c}an's \textit{very} \textcolor{red}{fast} \href{https://x.org}{method} \& more",
     "Ergör and Gaçan's very fast method & more"),
    (r"Thresholds $\alpha \le 0.5$ and $\beta\geq 2$ with $\sqrt{N}$ \cmark", r"Thresholds α ≤ 0.5 and β≥ 2 with $\sqrt{N}$ yes"),
])
def test_the_plain_text_rules(raw, plain):
    assert draft_parse.plain_latex(raw) == plain


def test_parts_copied_from_the_plain_claim_cover_it_and_the_pilots_latex_parts_do_not():
    found, _ = claims("\\begin{document}\n" + r"Haldar \emph{et al.} learn swap, wait and discard decisions from link"
                      r" ages~\cite{h}~\tP." + "\n\\end{document}")
    claim = found[r"\cite{h}"].claim
    assert contracts.citation_check_covers(claim, [{"text": "Haldar et al. learn swap, wait and discard decisions from"
                                                            " link ages"}])
    # The pilot's part kept `\emph{...}` and `~~\tP`, which left words out (P44, P13, P40).
    spans, left = contracts.citation_check_spans(claim, [{"text": r"Haldar \emph{et al.} learn swap"}])
    assert spans == [None] and left


# ---- the 11 negation and cut-quote refusals of the pilot (D105 lists each with its verdict)

def located(quote, passage):
    anchor = locate_anchor(quote, passage)
    assert anchor is not None
    return anchor


P40 = ("identify optimal policies for distributing end-toend Bell pairs by connecting randomly generated elementary\nBell"
       " pairs in a quantum switch having two clients, with and\nwithout the option of entanglement distillation. In"
       " particular,\nwe derive policies that optimize the end-to-e")
P44 = ("These cutoffs are, in general, less than\nthe maximum cutoff 𝑚★, which is allowed within our MDP\nframework; see"
       " Sec. II and Appendix A.\n\nIn order to see that the cutoffs are not only state dependent\nbut that different links"
       " can have different cutoffs, we calculate\nan average cutoff ⟨𝑡★⟩𝑖, 𝑗for every node pair (𝑖, 𝑗).")
P49 = ("[symbols not readable in the PDF]\nSi(1)2�\n\n< ∞. All these five processes are independent of each other."
       " Moreover,\neach qubit departs from the system at each time slot via abandonments, with probability γ1 from the"
       " first\nand third queues, and with probability γ2 from the second queue.")
P65 = ("depolarizing channel is applied to the entangled state at every\ninstant. As a result, the fidelity of a Werner"
       " state at time t, F(t), is\ngiven by\n\nFðtÞ ¼ 1\n\n4 þ\nFðt �ΔtÞ �1\n\n[symbols not readable in the PDF]\ne�Δt=τ;"
       "\n(3)\n\nwhere Δt is an arbitrary interval of time and τ is a parameter that")
P46 = ("from the respective buffers to avoid overflow. We first observe\nthat there is no benefit to removing a qubit from a"
       " buffer before\nit is full; hence we only consider polices that remove qubits at\nthe time overflow occurs. Second,"
       " we restrict ourselves to work\nconserving policies; those that a")
P47 = ("i, j as possible and to stabilize the system. For now, we assume that there is no limit to the\n\nnumber of EPR"
       " pairs that can be stored in the nodes. Moreover, we assume that a qubit never\n\ndecoheres. These assumptions will"
       " be relaxed in a later section")
P13 = ("work optimized throughput and end-to-end fidelity, yet little attention has been paid to the freshness of"
       " entanglement-the time since a usable Bell pair was last delivered. We introduce the Fidelity-Age (FA) metric")
P73 = ("entanglement of separated nodes and does not require phase stability\nacross the link. We further make use of the"
       " multi-qubit capabilities to\nentangle two long-lived nuclear spins, using integrated error detection to enhance"
       " entanglement fidelities and dynamical decoupling\nsequences to extend the entanglement duration to 1\u2009s.")
P55 = "then designed two scheduling and distribution algorithms\nbased on the idea of scheduling via prioritization."
P09 = "The example shows the significance of scheduling in serving time-sensitive communication demands."


@pytest.mark.parametrize("quote, passage, part", [
    ("in a quantum switch having two clients", P40, "the authors solve a switch MDP for one client pair"),  # with and without
    ("In order to see that the cutoffs are not only state dependent", P44, "with state-dependent cutoffs below the maximum"),
    ("each qubit departs from the system at each time slot via abandonments, with probability γ1 from the first", P49,
     "with memoryless abandonment"),  # DEIXIS's own placeholder in the window
    ("the fidelity of a Werner state at time t, F(t), is\ngiven by", P65, "Combining Werner-state decay"),
])
def test_the_pilots_false_alarms_are_no_longer_refused(quote, passage, part):
    assert quote_meaning_differs(quote, passage, located(quote, passage), part) is None


@pytest.mark.parametrize("quote, passage, part, reason, detail", [
    ("we only consider polices that remove qubits at\nthe time overflow occurs", P46,
     "among work-conserving policies that drop only on overflow", "negation", '"no"'),
    ("there is no limit to the\n\nnumber of EPR pairs that can be stored in the nodes", P47,
     "with unlimited memory and infinite qubit lifetime", "part_negation", 'the quote holds the negation "no"'),
    ("Moreover, we assume that a qubit never\n\ndecoheres.", P47, "with unlimited memory and infinite qubit lifetime",
     "part_negation", '"never"'),
    ("the time since a usable Bell pair was last delivered", P13, "resets to zero after a usable delivery", "boundary",
     'the passage writes "-" right before the quote'),
    ("using integrated error detection to enhance entanglement fidelities", P73,
     "keep inter-node entanglement for up to 1 s with error detection", "negation", '"not"'),
    ("scheduling via prioritization", P55, "rank requests by expected completion time without age or fidelity",
     "part_negation", 'the part holds the negation "without"'),
    (P09.rstrip("."), P09, "Order matters even without decay", "part_negation", '"without"'),
])
def test_the_pilots_right_refusals_stay_and_say_what_and_where(quote, passage, part, reason, detail):
    found = quote_meaning(quote, passage, located(quote, passage), part)
    assert found is not None and found[0] == reason and detail in found[1]


@pytest.mark.parametrize("quote, passage, part", [  # SYNTHETIC: a shielded phrase the quote cuts still refuses
    ("only state dependent", "The cutoffs are not only state dependent.", "the cutoffs are only state dependent"),
    ("without the option of distillation", "Policies with and without the option of distillation.",
     "policies use the option of distillation"),
    ("significantly improve accuracy", "It does [symbols not readable in the PDF] not significantly improve accuracy.",
     "it significantly improves accuracy"),
])
def test_a_negation_phrase_the_quote_cuts_or_a_real_negation_beside_the_placeholder_is_still_refused(quote, passage, part):
    assert quote_meaning_differs(quote, passage, located(quote, passage), part) in ("negation", "part_negation")


def test_the_placeholder_is_the_pdf_readers_own_words():
    assert contracts.UNREADABLE_MARK == pdf.UNREADABLE


def test_a_refused_quote_beside_a_kept_one_says_removing_it_keeps_the_others():
    # P47's first answer: one quote located, the other refused for a negation in its window.
    passage = ("We determine the capacity region under the assumption of infinite memory slots. " + "Filler words. " * 25
               + P47)
    si, draft = case("with unlimited memory and infinite qubit lifetime", passage, [(
        "with unlimited memory and infinite qubit lifetime", "there is no limit to the\n\nnumber of EPR pairs")])
    draft["parts"][0]["evidence"].insert(0, {"passage_id": "psg_SYNTHCIT001",
                                             "quote": "the capacity region under the assumption of infinite memory slots"})
    report = contracts.validate_model_output(si, draft)
    message = next(i.message for i in report.issues if i.code == "quote_meaning_differs")
    assert contracts.KEPT_QUOTES_HINT in message and 'the quote holds the negation "no"' in message


# ---- the claim through the workflow, staleness by what the check uses, and the freeze while a re-extraction waits.
# Drafts, records, PDFs and answers here are SYNTHETIC.

TEX_DRAFT = (b"\\begin{document}\nDepth based routing \\emph{raises} packet delivery in sparse networks~\\cite{a}~\\tP."
             b" Void avoidance keeps packets moving around holes~\\cite{b}. Mobile sinks save forwarding energy \\cite{c}."
             b" Nothing is known \\cite{d}.\n\n\\begin{table}\\caption{Works (\\cmark{} shown).}\n"
             b"\\begin{tabular}{ll}\nWork & Delivery\\\\\n\\midrule\nZeng~\\cite{a} & \\cmark\\\\\n\\end{tabular}\n\\end{table}\n"
             b"\\end{document}\n")


def test_the_check_reads_the_plain_claim_and_a_table_row_with_its_caption_and_keeps_the_raw_sentence(make):
    seen = []

    def respond(si):
        seen.append(copy.deepcopy(si["citation_check_target"]))
        words = "depth routing raises packet delivery" if "Depth" in sentence(si) else None
        if words:
            return answer(si, [{"text": sentence(si).rstrip("."), "assessment": "partly",
                                "evidence": [quote_of(si, words)]}])
        return answer(si, [{"text": sentence(si).rstrip("."), "assessment": "not_stated", "evidence": []}])
    app, _ = make(responder=respond)
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client, draft=TEX_DRAFT)
        upload(client, view, "a", A_PAGES)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        checked = run(client, view["id"])
        assert checked.json()["check_run"]["status"] == "completed", checked.text
        targets = {t["sentence"]: t for t in seen}
        assert "Depth based routing raises packet delivery in sparse networks." in targets
        row = targets["Work: Zeng; Delivery: yes"]
        assert row["context"] == "Works (yes shown)." and "context" not in targets[
            "Depth based routing raises packet delivery in sparse networks."]
        final = client.get(f"/api/citation-checks/{view['id']}").json()
        first = final["markers"][0]
        assert first["sentence"].startswith(r"Depth based routing \emph{raises}") and first["claim"].startswith(
            "Depth based routing raises")
        assert next(p for p in first["pairs"])["result"] == "found_partial"
        csv_text = client.get(f"/api/citation-checks/{view['id']}/export", params={"format": "csv"}).text
        assert csv_text.splitlines()[0].startswith("pair,marker,sentence,claim,target")


def b_item(client, draft_id):
    return next(i for i in client.get(f"/api/citation-checks/{draft_id}/preview").json()["selected"] if i["target"] == "b")


def acquired(client):
    view = start(client)
    upload(client, view, "a", A_PAGES)
    client.post(f"/api/citation-checks/{view['id']}/acquire")
    return view


def swap(store, passage, text):
    """Passages are immutable: a passage read again is a new row beside the old one's removal, same page and file."""
    with store.conn:
        store.conn.execute("DELETE FROM passages WHERE id = ?", (passage["id"],))
        return store._insert_passage(passage["source_version_id"], passage["asset_id"], passage["kind"],
                                     passage["physical_page"], None, None, passage["payload_ref"],
                                     passage["extraction_version"], text)


def test_a_change_elsewhere_in_the_record_keeps_the_plan_and_is_shown_and_recorded(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = acquired(client)
        frozen(client, view["id"])
        b = b_item(client, view["id"])
        assert (b["stale"], b["text_changed_elsewhere"], b["passages_not_given"]) == (False, False, 3)
        store = app.state.store
        svid = store.passage(b["passage_ids"][0])["source_version_id"]
        other = next(p for p in store.passages_for(svid) if p["id"] not in b["passage_ids"])
        swap(store, other, "SYNTHETIC page read again")
        b = b_item(client, view["id"])
        assert (b["stale"], b["text_changed_elsewhere"], b["passages_not_given"]) == (False, True, 3)
        checked = run(client, view["id"])
        assert checked.json()["check_run"]["status"] == "completed", checked.text
        check = next(p for _, p in pair_rows(client.get(f"/api/citation-checks/{view['id']}").json())
                     if p["target"] == "b")["check"]
        assert check["basis"]["text_changed_elsewhere"] is True


def test_a_changed_given_passage_a_changed_count_or_a_new_extraction_makes_the_plan_stale(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = acquired(client)
        frozen(client, view["id"])
        store = app.state.store
        b = b_item(client, view["id"])
        given = store.passage(b["passage_ids"][0])
        swap(store, given, given["text"] + " Changed.")
        assert b_item(client, view["id"])["stale"] is True
        refused = run(client, view["id"])
        assert refused.status_code == 409 and refused.json()["code"] == "plan_stale"
        # The not-given count would change: a passage added to the record.
        frozen(client, view["id"], refreeze=True)
        b = b_item(client, view["id"])
        assert b["stale"] is False
        page = store.passage(b["passage_ids"][0])
        with store.conn:
            store._insert_passage(page["source_version_id"], page["asset_id"], "pdf_page", 40, None, None, "chars:0-9",
                                  page["extraction_version"], "SYNTHETIC added page")
        assert b_item(client, view["id"])["stale"] is True
        # A re-extraction writes the same texts under a new extraction: the given passages are no longer the ones a
        # model step may read of the record (D46), so the plan is stale although no given text changed.
        frozen(client, view["id"], refreeze=True)
        b = b_item(client, view["id"])
        page = store.passage(b["passage_ids"][0])
        asset_id, version = page["asset_id"], page["extraction_version"]
        with store.conn:
            for p in store.conn.execute("SELECT * FROM passages WHERE asset_id = ? AND extraction_version = ?",
                                        (asset_id, version)).fetchall():
                store._insert_passage(p["source_version_id"], asset_id, p["kind"], p["physical_page"], None, None,
                                      p["payload_ref"], version + "+reread", p["text"])
            store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?", (version + "+reread", asset_id))
        assert len(store.passages_for(page["source_version_id"])) == b["passages_total"]
        assert b_item(client, view["id"])["stale"] is True


class WaitingReader:
    """An equation service whose reader is installed: every PDF not read yet by it is pending (`_marker_state`)."""
    reading = None

    def __init__(self, on=True):
        self.on = on

    def available(self):
        return self.on

    def installing(self):
        return False

    def marker_present(self):
        return self.on

    def route_active(self):
        return False

    def mathpix_active(self):
        return False

    def route_flag(self):
        return False

    def mathpix_ready(self):
        return False


def test_the_freeze_waits_for_a_re_extraction_of_a_cited_works_pdf(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = acquired(client)
        store = app.state.store
        before = getattr(store, "equation_route", None)
        try:
            store.equation_route = WaitingReader()
            shown = client.get(f"/api/citation-checks/{view['id']}").json()["reextraction_waiting"]
            b_entry = next(e for e in view["entries"] if e["key"] == "b")
            assert {w["entry_ordinal"] for w in shown} >= {b_entry["ordinal"]}
            assert all(w["state"] in equations.QUEUED_STATES and "next_at" in w for w in shown)
            refused = client.post(f"/api/citation-checks/{view['id']}/plan", json={})
            assert refused.status_code == 409 and refused.json()["code"] == "reextraction_pending"
            assert not client.get(f"/api/citation-checks/{view['id']}").json()["plan"]["revision"]
            store.equation_route = WaitingReader(on=False)  # no reader can run: nothing waits
            assert client.get(f"/api/citation-checks/{view['id']}").json()["reextraction_waiting"] == []
            frozen(client, view["id"])
        finally:
            store.equation_route = before


def test_a_failed_read_with_attempts_left_waits_and_a_spent_one_does_not(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = acquired(client)
        store = app.state.store
        before = getattr(store, "equation_route", None)
        try:
            store.equation_route = WaitingReader()
            asset = next(iter(store.conn.execute("SELECT * FROM source_assets WHERE removed_at IS NULL").fetchall()))
            version = equations.target_version(asset["extraction_version"])
            with store.conn:
                store.conn.execute(
                    "INSERT INTO asset_extractions (id, asset_id, extraction_version, extractor_profile, status, text_pages,"
                    " passage_count, outcome, rejection_reason, math_json, created_at) VALUES ('aex_SYNTH1', ?, ?, ?,"
                    " 'failed', 0, 0, 'rejected', 'crash', ?, '2026-10-18T00:00:00+00:00')",
                    (asset["id"], version, version, json.dumps({"attempts": 1})))
            assert equations.background_read_waiting(store, asset["id"])["state"] == "failed"
            with store.conn:
                store.conn.execute("DELETE FROM asset_extractions WHERE id = 'aex_SYNTH1'")
                store.conn.execute(
                    "INSERT INTO asset_extractions (id, asset_id, extraction_version, extractor_profile, status, text_pages,"
                    " passage_count, outcome, rejection_reason, math_json, created_at) VALUES ('aex_SYNTH2', ?, ?, ?,"
                    " 'failed', 0, 0, 'rejected', 'crash', ?, '2026-10-18T00:00:00+00:00')",
                    (asset["id"], version, version, json.dumps({"attempts": equations.MAX_ATTEMPTS})))
            assert equations.background_read_waiting(store, asset["id"]) is None
        finally:
            store.equation_route = before


def test_the_next_try_time_comes_from_the_state():  # SYNTHETIC
    assert equations.next_try_at({"state": "source_waiting", "next_at": "2026-10-18T10:00:00.000+00:00"}) == (
        "2026-10-18T10:00:00.000+00:00")
    assert equations.next_try_at({"state": "failed", "at": "2026-10-18T10:00:00.000+00:00"}) == (
        "2026-10-18T10:10:00.000+00:00")
    assert equations.next_try_at({"state": "pending"}) is None


def test_an_unread_table_layout_is_stored_and_shown_with_its_reason_and_no_pair(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        text = (b"\\begin{document}\nPlain claim \\cite{a}.\n\\begin{tabular}{lll}\nWork & \\multicolumn{2}{c}{Shared}"
                b"\\\\\nX \\cite{b} & yes & no\\\\\n\\end{tabular}\n\\end{document}\n")
        view = start(client, draft=text)
        marker = next(m for m in view["markers"] if m["raw"] == r"\cite{b}")
        assert (marker["parse_status"], marker["parse_reason"], marker["claim"], marker["pairs"]) == (
            "unrecognized", draft_parse.TABLE_LAYOUT_NOT_READ, None, [])


def test_the_step_input_context_is_optional_and_bounded():
    si = copy.deepcopy(SI)
    assert contracts.check_step_input(si) == []
    si["citation_check_target"]["context"] = "Works (yes shown)."
    assert contracts.check_step_input(si) == []
    si["citation_check_target"]["context"] = "x" * 1001
    assert contracts.check_step_input(si) != []
    assert codes(copy.deepcopy(SI), copy.deepcopy(VALID)) == []
