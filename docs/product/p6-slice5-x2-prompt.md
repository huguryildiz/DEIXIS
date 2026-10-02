<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, 3 rounds: r1 0 high (8 medium/low: split_text position, symbol command boundary, unmapped collector in math, label trust boundary, no-leak test vs `\begin {aligned}`, symbol-table definedness test, katex_version type, missing test file), r2 0 high (4 medium: positional twin, Unicode letter boundary, collector call wiring, no blank line when joining), r3 0 high (1 low test addition), verdict hazir; all folded in -->
<!-- CODE-REVIEW-ROUNDS: gpt-6.1-sol high, 2 rounds: r1 3 high (symbol rewrite producing `^^`, ASCII-only control-word scan vs XeTeX Unicode letters, bare `$` inside a display body), 1 medium, 1 low; r2 0 high, 1 medium (no-leak test took the expected math body from production code); all fixed -->

# Task: P6 slice 5, batch X2, pure LaTeX text and math conversion (no model, no TeX at run time)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-x2` (detached at `e718670`, which is `origin/main`
with the slice 5 design, D149, on top). Read `AGENTS.md`, `CLAUDE.md`, `docs/product/p6-slice5-latex-export.md`
(the whole note; this batch is its section 11 "X2"; sections 3, 4, 9 and decisions Q5, Q6, Q12, Q17 bind it) and D149,
D145 and D144 at the top of `docs/decisions.md`. Where this prompt differs from the note, this prompt wins and says so.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find or could not make pass. No real-model call, no network, no
provider call. Do not touch `../DEIXIS`, `../DEIXIS-k*`, `../DEIXIS-e*`, `../DEIXIS-s4*`, `.local/`, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, `sw-status.md`, ports 8765 and 8858-8864. Tests run with
`PYTHONPATH=backend:. uv run pytest ...` (`UV_CACHE_DIR=/tmp/deixis-uv-cache` if uv cannot write its cache).

## What is and is not in code (checked on e718670)

- Nothing of this batch exists: no `latex_*.py` under `backend/deixis/workflow/report/`, no `latex_names.json`, no
  `scripts/latex_export_names.py`, no LaTeX-producing code anywhere. `backend/deixis/workflow/bibliography.py::_tex` is a
  BibTeX field escaper for the Zotero export (D16); it is not touched and not reused here.
- Present and used read-only: `deixis.domain.contracts._math_spans(text) -> list[str]` and `_is_escaped(text, index)`
  (private names; `assembly.py:535-536` already imports them the same way; `contracts.py` is **not** changed, no alias
  added). `deixis.documents.arxiv_source.katex_known()` returns `{"commands", "environments", "symbols", "version"}` sets
  from `backend/deixis/documents/katex_commands.json` (KaTeX 0.16.47: 976 commands, 33 environments, 24 symbols).
  `katex_unknown` and `contracts._math_span_is_well_formed` exist and are **not** relied on for safety (they miss
  `\begin {document}`).
- `scripts/latex_kernel_names.py` is the model for a TeX-driven names script (candidate list, `\ifdefined` probe in a
  temporary directory, JSON written next to the code). It targets pdfLaTeX and article.cls, so it cannot be reused for
  this preamble; it is not changed.
- This machine has TeX Live 2021: `/Library/TeX/texbin/xelatex`, `kpsewhich` (IEEEtran.cls and IEEEtran.bst found). Put
  `/Library/TeX/texbin` on `PATH` for the script. A probe on 2 October 2026 showed that with the preamble below,
  `\@ifundefined{endalign}` is false (defined), `\ifdefined\geq` true, `\ifdefined\R` false and `pmatrix*` undefined, so the
  script design works. If the sandbox you run in cannot execute `xelatex` or write a temporary directory, write the script
  anyway, do **not** hand-write or guess the JSON, run every test that does not need it, and say so in your report: the
  orchestrator runs the script outside the sandbox.

## Decisions taken (the note's own default where it has one; own judgement is marked)

1. **Files and layering.** Four modules under `backend/deixis/workflow/report/`: `latex_preamble.py` (no imports from the
   others), `latex_text.py` (imports nothing from `latex_math.py`), `latex_math.py` (imports `latex_text.py`, `contracts`
   privates, `katex_known`). No import of `export.py`, `views.py`, the store, `httpx`, `subprocess`, `os.system` or anything
   that touches the database, the network or TeX at run time (a test greps the three modules' import lines).
2. **`latex_preamble.py`.** `PREAMBLE: str` is the fixed text of note section 3 up to and including the package lines,
   in this order: `\documentclass[journal]{IEEEtran}`, then `\usepackage{...}` lines for `fontspec`, `amsmath`, `amssymb`,
   `bm`, `xcolor`, `cite`, `url`, `booktabs`, `longtable`, `array`. No `hyperref`, no `tabularx`, no `polyglossia`, no
   `\begin{document}`, no language-specific `\renewcommand` (X3 writes those after `\begin{document}`). `PREAMBLE_SHA256`
   is the hex sha256 of `PREAMBLE.encode("utf-8")`. The compile comment lines of note section 3 and the export notes are
   X3's, not here. Own judgement: ends with one newline.
3. **Plain-text escape (`latex_text.py`).** `escape_text(text, unmapped=None) -> str` (note section 3, Q12):
   - characters `\ { } $ & # ^ _ % ~` are escaped (`\textbackslash{}`, `\{`, `\}`, `\$`, `\&`, `\#`, `\textasciicircum{}`,
     `\_`, `\%`, `\textasciitilde{}`); a `$` is a literal dollar `\$` in plain text;
   - **own judgement (parity rule, matches `contracts._is_escaped`):** a backslash run of odd length directly before a `$`
     means the last backslash and the `$` together are one escaped dollar (written `\$`) and the other backslashes of the
     run are plain backslashes; an even run means all are plain backslashes and the `$` is a bare dollar (also `\$`).
     Every other backslash is a plain character (`\textbackslash{}`); plain text never makes a TeX command;
   - runs of whitespace (any `str.isspace()` character except U+00A0) collapse to one space; **no strip** at the ends (the
     caller joins pieces around math spans); U+00A0 becomes `~`;
   - `"` becomes ``` `` ``` at the start, after whitespace or after one of `([{` and `''` otherwise; `'` and backtick are
     left alone;
   - **own judgement:** C0/C1 control characters other than the whitespace above (NUL, DEL and so on) are removed and
     recorded in the same unmapped-character collector as a code point, so a loss is never silent;
   - **command boundary (bare commands only: math context, i.e. `symbol_math` and stage 2 outside `\text{}`):** a control
     word followed directly by a letter changes the command (`α` then `x` becoming `\alphax`). XeTeX gives every Unicode
     letter and combining mark catcode 11, so the rule is not ASCII only: when the character after the symbol has Unicode
     category `L*` or `M*`, one space is written after the control word (TeX ignores a space after a control word);
     digits, punctuation, `$`-end of span and the end of the string need none. The text form
     `\ensuremath{<command>}` is closed by `}` and needs no boundary space, and no visible space is ever added after that
     brace. Tests compare full output strings for `$αx$`, `$α x$`, `$α1$`, `$≥x$`, `$αé$`, `$αı$`, `$α` + U+0301 + `$`
     (combining mark), a symbol at the end of the span, and `\text{αx}` (no space).
   - the closed symbol table (`SYMBOLS: dict[str, str]`, character to math-mode command text, exact keys chosen by you
     and listed in a comment: at least `≤ ≥ ≠ ≈ ≡ ± ∓ × ÷ − · ⋅ ° µ μ → ← ↔ ⇒ ⇔ ∞ ∈ ∉ ⊂ ⊆ ∪ ∩ ∅ ∑ ∏ ∫ √ ∂ ∇ ∀ ∃ ¬ ∧ ∨ ∝ ∼ ≪ ≫`, the lower and upper case
     Greek letters that have a LaTeX command, with a one-line comment on the φ/ϕ and ε/ϵ choice) is applied in text as
     `\ensuremath{<command>}` and in math as the bare command (`symbol_text(ch)`, `symbol_math(ch)`). Table beats
     pass-through: `±` is written `\ensuremath{\pm}` even though Latin-1. Every control word in a table value must be a KaTeX command
     (so the scanner vocabulary and the table cannot drift apart) **and** defined by the preamble (a test checks both:
     first membership in `katex_known()["commands"]`, then absence from `latex_names.json`'s `undefined_commands`);
   - characters that are not in the table and are outside Latin Basic, Latin-1, Latin Extended-A and U+2010-U+2027 are
     written unchanged and added to the collector: `Unmapped` (class) with `add`, `count`, and `note() -> str | None`, one
     English single-line ASCII note per document: the total and the first 10 distinct code points in `U+XXXX` form, in
     first-seen order. The collector is created by the caller; `escape_text(..., unmapped=None)` collects nothing.
     `count` counts occurrences (total), the note lists distinct code points. **The same collector serves math:** after
     stage 2, `render` collects any character of a non-class-A span body that is outside the symbol table and the safe
     ranges (this includes characters inside `\text{}`), and a class A span goes through `escape_text` with the same
     collector, so there is still one note per document. Collection happens in `render`, never in `classify`, because X3
     calls `classify` in a first pass (label targets) and `render` in a second; a test calls `classify` twice and
     `render` once and checks the count is not doubled, and a `convert_text` test (one valid math span and one class A
     span, each holding one unmapped character) checks that each is counted exactly once. A helper `is_unmapped(ch)` in `latex_text.py` is the single
     definition.
   - Other notes this module returns are plain `str`, English, ASCII, one line, deterministic, with no newline. Final
     listing (dedupe, ordering, 200-character cut) is X3's.
4. **Math (`latex_math.py`), public surface (own judgement on names; X3 consumes them, so keep them stable and listed in
   the decision record).**
   - `split_text(text) -> list[tuple[str, str]]` pieces `("text" | "math", string)`. Spans are the ones
     `contracts._math_spans` returns, but their **positions** come from a private positional twin of that scan in
     `latex_math.py` (same delimiter width, escape test via `contracts._is_escaped`, newline rule and advance rule,
     returning `(start, end)` pairs); a `str.find` approach is wrong in two ways (it finds an escaped `\$x$` earlier, and
     it can start a span at the second dollar of an opening `$$`). At run time the twin's span strings must equal
     `_math_spans(text)` exactly; if they differ, or `"".join` of the pieces is not `text`, the whole text becomes one
     `"text"` piece (fail closed). Tests: the twin equals `_math_spans` on a fixed corpus plus 2,000 seeded random strings
     over the alphabet `$ \\ x { } newline space`; hand-written expected pieces (with positions) for `"\\$x$" + "\n" + "$x$"` and for
     `"$$x$" + "\n" + "$x$"`, `\$`, a lone `$`, `$$`, `\text{$x$}`.
   - `classify(span, *, cell=False) -> MathSpan` (pure, no collector), a frozen dataclass: `source` (the original span), `kind`
     (`"inline" | "display_env" | "display_tag" | "display_aligned" | "display_gathered" | "display_plain" | "plain"`,
     where `"plain"` is class A), `labelable: bool` (true only for the last three display kinds), `body` (display body
     after stage 2, outer whitespace stripped; inline: the whole span after stage 2), `class_b: tuple[str, ...]` (sorted
     names, commands as `\name`, environments as `{name}`), `notes: tuple[str, ...]`.
   - `render(m: MathSpan, label: str | None = None, unmapped: Unmapped | None = None) -> str`. Plain: `escape_text(m.source, unmapped)` (the whole original span
     **including its `$` delimiters**, so `$x&y$` becomes `\$x\&y\$`; own judgement, the note says only "özgün
     karakterleriyle"). Inline: `m.body` unchanged. Display env: `"\n" + body + "\n"`. Display tag: starred
     `equation*`; aligned and gathered: `equation`/`equation*` around `\begin{aligned}`/`\begin{gathered}`; plain display:
     `equation`/`equation*`. `label=None` gives the starred form; a label gives `equation` with
     `\label{<label>}` on its own line before the body (labelable kinds only; for other kinds a label is ignored).
     **Trust boundary:** a label must fully match `eq:EQ[0-9]{1,3}` (`re.fullmatch`); any other string raises
     `ValueError` before anything is written (a test passes `"eq:EQ1}\\input{x}\\label{p"` and an empty string and
     checks the exception and that no TeX is produced). Layout
     is fixed: `"\n\\begin{equation*}\n" + body + "\n\\end{equation*}\n"` (no blank lines anywhere, so a claim stays one
     paragraph). The caller (X3) decides labels per note section 4 "Denklem etiketi ve numarası (Q6)"; X2 only exposes
     `kind`, `labelable` and `render(label=)`.
   - `convert_text(text, *, cell=False, label_for=None, unmapped=None) -> tuple[str, list[str]]`: splits, escapes the text
     pieces with `escape_text(..., unmapped)`, classifies and renders the math pieces with `render(..., unmapped=unmapped)` (`label_for(index_among_math_pieces,
     MathSpan) -> str | None` is optional; its result is validated by `render`), returns the string and the notes (the
     unmapped-character note is **not** among them; the caller asks the collector once per document). **Joining rule
     (no blank line may appear):** `render` keeps the fixed layout of display output (single LF on both sides), and
     `convert_text` removes the spaces and tabs that touch a display's LF and merges consecutive line breaks into one, so
     the result never holds an empty or whitespace-only line (TeX reads such a line as a paragraph break). Tests with
     exact output for `a $$x$$ $$y$$ b`, `$$x$$$$y$$`, `$$x$$ tail`, `$$x$$ $a&b$` (class A text next to a display) and a valid
     display whose body holds `\begin` + LF + `{aligned}`, a `\\` row separator and further LF characters (the body must come out
     unchanged: the joining rule touches only the line breaks `render` adds). A thin loop; no more.
   - `closed_scan(span) -> ScanResult` (ok flag, reason code when not ok, and the structural facts stage 3 needs: top-level
     `&`, top-level `\\`, top-level `\tag`/`\nonumber`/`\notag`, top-level E environments). Public so it can be tested
     on its own.
5. **Stage 1, the closed scan: unified stack, iterative, fail closed.** Implement note section 4 stage 1 exactly, with
   these precisions (own judgement where marked):
   - Scan the whole span (delimiters excluded), nested arguments included. No recursion (a nesting depth above 64 is
     class A). Any unexpected exception inside `classify` gives class A (`except Exception`), never a crash and never
     TeX.
   - **One stack** holds three kinds of open group: `{` (a brace group, remembering whether it is the argument of
     `\substack`), `\begin{env}` and `\left`. A closer must match the top: `}` closes only `{`, `\end{x}` only `\begin{x}`
     (same name), `\right` only `\left`, `\middle` needs a `\left` on top. Anything else (including crossed nesting) is
     class A, and so is a non-empty stack at the end. Escaped `\{` and `\}` are control symbols and are not counted.
   - Tokens: a control word is `\` plus `[A-Za-z]+`; a control symbol is `\` plus one other character, which must be in
     `katex_known()["symbols"]` **minus** `(`, `)` and `]` (own judgement: these open or close TeX math and can only
     break compilation); a backslash at the end of the span is class A. Every control word must be in
     `katex_known()["commands"]` and not in `COMMAND_DENY`.
   - **`COMMAND_DENY`** (own judgement, fixed after reading all 976 names; a frozenset literal with a comment per group):
     the note's floor `def gdef edef xdef let futurelet newcommand renewcommand providecommand global expandafter verb
     begingroup endgroup url href includegraphics htmlClass htmlData htmlId htmlStyle`, plus `noexpand bgroup egroup char
     message errmessage show hbox fbox raisebox color textcolor colorbox fcolorbox`. Everything else KaTeX knows is allowed
     in math (height and size commands stay allowed in display math; they are refused only in table cells, decision 8).
     `command_status(name) -> "denied" | "allowed"` is public for the split test.
   - `\begin` / `\end`: after skipping whitespace (including a line break) the next character must be `{`, then an
     environment name of letters and `*`, then `}`; otherwise class A. Allowed names: `aligned alignedat gathered split
     cases array matrix pmatrix bmatrix Bmatrix vmatrix Vmatrix smallmatrix subarray` and the E set `align align* alignat
     alignat* gather gather* multline multline* flalign flalign* equation equation*`. `\begin {document}`,
     `\begin{\n document}` and `\end{document}` are class A.
   - Class A for: `^^`, an unescaped `%` or `#`, a blank line (two line breaks separated only by blank characters), and
     every character that is not printable math input: **own judgement, fail-closed rule:** Unicode category Cc except TAB
     and LF, Cf, Zl, Zp, Cs, Co, Cn, and Zs other than U+0020 (so NUL, CR, DEL, bidi marks and NBSP are class A).
   - Text arguments (`\text \textrm \textbf \textit \textsf \texttt`): the brace group right after one of them is a text
     group (depth of nested text groups at most 3); inside, the only control sequences allowed are `\& \% \$ \# \_ \{ \}
     \, \;`, `\quad`, `\qquad` and the six text commands; any other control sequence, `\\`, `\begin`, `\left` is class A.
   - `&` and `\\` rules exactly as in section 4 "Bağlam kuralları": valid when the **top of the stack is an environment**
     that accepts it (`&`: `aligned alignedat array matrix pmatrix bmatrix Bmatrix vmatrix Vmatrix cases split smallmatrix
     subarray align align* alignat alignat* flalign flalign*`; `\\`: all environments except `equation` and `equation*`);
     `\\` is also valid directly inside the brace group of `\substack`; with an **empty stack** they are recorded as
     top-level facts for stage 3; anywhere else (`{x&y}`, `\frac{x&y}{z}`, `&` in `gathered`, inside `\left...\right`)
     class A. `\tag`, `\tag*`, `\nonumber`, `\notag` are valid only in a display span with an empty stack (and `\tag`
     must be followed by its `{...}` argument); otherwise class A. Brace balance and these checks do not check argument
     counts (`\frac{x}`); that stays a documented compile risk.
   - Whitespace-only and empty spans (`$ $`) are class A (own judgement: nothing to write).
6. **Stages 2 and 3.** Stage 2 works on tokens, not on a regex over characters: `\lt` becomes `<`, `\gt` becomes `>`
   (only the exact control words), Unicode symbols are rewritten with `symbol_math` outside text groups and `symbol_text`
   inside text groups, nothing else is rewritten. Stage 3 follows the table of section 4 row for row (inline; display with
   one E environment spanning the body, otherwise E anywhere in a display or inline is class A; display with `\tag`-class
   commands and no top-level `&`/`\\` is `display_tag`; both together class A; top-level `&` is `display_aligned`
   (`aligned`); only top-level `\\` is `display_gathered`; the rest `display_plain`). A `$$...$$` that is not display-valid
   in a table cell: see decision 8. Class B: after stage 1 and stage 2, a remaining command in `latex_names.json`'s
   `undefined_commands` or environment in `undefined_environments` goes into `class_b` and one note per span
   ("<names> is not defined by the export preamble; the document may not compile"); the span is written unchanged.
7. **Equation label data.** Nothing in X2 decides labels; the tests for "label target scenarios" are tests of
   `classify(...).labelable`/`kind` and of `render(m, label="eq:EQ1")` (labelable kinds get `equation` plus `\label`,
   E and tag kinds never get a label and are written unchanged and unlabeled, plain inline never labelable). The scenario
   tests of section 9 that need claims and `equation_ref` move to X3; say so in the decision record.
8. **Table-cell subset (`cell=True`).** Applied after stage 1 and before stage 2 on the original input (note section 5).
   A span outside the subset is class A (`plain`, written as escaped original text) with a note. Outside the subset:
   any `\begin`/`\end` (no environment), any `\\` or `\substack`, a number followed by one of the units `pt em ex cm mm
   in bp pc mu sp dd cc px` (regex over digits, optional decimal part, optional spaces, the unit as a whole word), and
   the control words `rule vphantom hphantom phantom smash raisebox substack genfrac hspace vspace kern mkern hskip mskip`
   and `Huge huge LARGE Large large normalsize small footnotesize scriptsize tiny`. A `$$...$$` span in a cell that
   would be `display_plain` is written inline (`$...$`, with a note); any other display kind in a cell is class A. The
   subset limits height only; say so in a comment. (Hücre eşikleri, "see note k" yolu ve tablo biçimi X3'tedir.)
9. **`scripts/latex_export_names.py` and `latex_names.json`.** Run from the repo root with
   `PATH=/Library/TeX/texbin:$PATH PYTHONPATH=backend:. uv run --no-sync python scripts/latex_export_names.py`. It builds a
   temporary document from `PREAMBLE` plus `\listfiles` and `\makeatletter`, `\begin{document}`; probes every KaTeX
   command with `\ifdefined\name` and every KaTeX environment with `\@ifundefined{name}` and `\@ifundefined{endname}`
   (undefined if either is undefined), writing results to a file with `\immediate\write` and a `:complete` terminator
   (the `latex_kernel_names.py` pattern); runs `xelatex -interaction=nonstopmode -no-shell-escape` (twice if `\listfiles`
   needs it) in a `tempfile.TemporaryDirectory`; reads the package versions from the log's `*File List*` block. It writes
   `backend/deixis/workflow/report/latex_names.json` with keys: `preamble_sha256`, `katex_commands_sha256` (sha256 of the
   bytes of `katex_commands.json`), `katex_version`, `engine` (first line of `xelatex --version`), `files` (the file list
   lines for the class and packages of the preamble, e.g. `IEEEtran.cls 2015/08/26 V1.8b ...`), `undefined_commands`
   (sorted), `undefined_environments` (sorted). Stable output (sorted, `indent=0`, trailing newline). It exits non-zero
   without writing if the probe did not reach `:complete`. The JSON is committed with the TeX version inside it.
   `latex_math.py` loads it lazily with `functools.cache`; a missing file raises (no silent empty list).
10. **Decision record.** New entry at the top of `docs/decisions.md`, titled `## D151 — P6 slice 5 X2: ...` (Status
    `accepted (implemented, uncommitted)`, Date `2026-10-02, P6 slice 5 batch X2`, Context, Decision, Verification,
    Limits; D145 is the model; the number is a placeholder because other worktrees also add entries). The orchestrator
    writes it; **you do not edit `docs/decisions.md`**. Give the orchestrator, in your report, what the Decision part must
    say: the public surface (decision 4), every own judgement above you kept or changed, the deny list as shipped, the
    symbol table size, the TeX version in the JSON and counts of undefined commands and environments.

## Files allowed

- `backend/deixis/workflow/report/latex_preamble.py`, `latex_text.py`, `latex_math.py`, `latex_names.json` (all new)
- `scripts/latex_export_names.py` (new)
- `tests/test_report_latex_text.py`, `tests/test_report_latex_math.py` (new)
- This prompt file: no edits.

## Files NOT allowed

Everything else. In particular `backend/deixis/domain/contracts.py`, `documents/arxiv_source.py`,
`documents/katex_commands.json`, `workflow/report/export.py`, `views.py`, `assembly.py`, `workflow/bibliography.py`,
`api/app.py`, anything under `apps/web`, `methods/`, `contracts/`, `storage/migrations/`, `docs/decisions.md`, other
tests, `tests/fixtures/`, lockfiles. No migration, no contract schema change, no `skill_package_hash` change. If a needed
change seems to require one of these, stop that item and report it.

## Tests to add (no test may need TeX, the network or the database)

`tests/test_report_latex_text.py`: the escape table for each of the ten characters; `\$` and the parity rule
(`a\$b`, `a\\$b`, `a\\\$b`, a lone trailing `$`); quotes (start, after space, after bracket, mid-word); `~` for NBSP;
whitespace collapse and no strip; control-character removal reported through the collector; the symbol table in text
(`\ensuremath{...}`), table beats pass-through for `±`; the unmapped-character note (one note, first 10 code points in
order, total, none when empty, none when the collector is not passed); characters inside the safe ranges are untouched;
a test that every command in `SYMBOLS` values is a command defined by the preamble (not in `undefined_commands`), skipping
nothing silently; `PREAMBLE` shape (documentclass line first, packages in order, no `hyperref`/`tabularx`, hash equals
`hashlib.sha256`); import-line check of the three modules (decision 1).

`tests/test_report_latex_math.py`:
- `split_text` equals `_math_spans` positions on a corpus; reassembly identity; failure falls back to one text piece.
- Closed scan, one case per item: every `COMMAND_DENY` member (each as `$\name x$`), `\input`, `\write`, `\csname`,
  `\catcode`, `\label`, `\ref`, `\cite`, `\immediate`, `\openout`, `\mbox`, `\ensuremath` (saved input), `^^`, `%`, `#`,
  blank line (also with CR), NUL and other controls, NBSP, unbalanced braces, unknown environment, `\end{document}`,
  **`\begin {document}`, `\begin{\n document}`, `\begin\n{document}`**, nested and crossed environments
  (`\begin{aligned}{\end{aligned}}`), `\left` without `\right`, `\right` first, `\middle` without `\left`, `\begin` without
  `{`, text-argument violations (`\text{\foo}`, `\text{\\}`, depth 4), `$x&y$`, `${x&y}$`, `$$\frac{x&y}{z}$$`,
  `$x\\y$`, `$x\tag{a}$`, `$$\begin{aligned}x&=y\tag{a}\end{aligned}$$`, `$$\begin{gathered}a&b\end{gathered}$$`,
  `\substack` with `\\` (valid) and with `&` (class A), `\left( a & b \right)` inside `aligned` (class A), `\tag`+`&`,
  more than one display environment, E inside inline, `\text{$x$}` (two spans, both class A), a nesting depth of 65, a
  control symbol outside the symbol set (`\ `, `\1`, `\(`), a trailing backslash, an empty span.
- Stages 2 and 3: one example per row of the section 4 table, exact output strings (inline, E, `\tag`, `&`, `\\`, plain,
  cell); `\lt`/`\gt` rewrite only on whole control words (`\ltimes` untouched); symbols in math and in `\text{}`; class
  B for `\R` and `\mathscr` (written unchanged, one note, listed in `class_b`), `\lt` not class B; `labelable` per kind;
  `render(label=)` for each labelable and non-labelable kind; fixed layout with no blank line.
- Cell subset: environment, `\\`, `\\[1000pt]`, a number with each unit, each listed control word, display-in-cell inline
  note, other display kinds class A; the 41-character `\begin{array}{c}x\\[1000pt]y\end{array}` example is class A in a
  cell and valid (not class A) outside one.
- **Split test:** every one of the 976 commands is exactly one of `denied`/`allowed` by `command_status`; `COMMAND_DENY`
  is a subset of the KaTeX commands; every denied command makes `$\name$` class A; every allowed command that is not
  structural (`begin end left right middle tag notag nonumber substack`, the six text commands) makes `$\name$` pass the
  closed scan.
- **Names file:** `preamble_sha256` equals `PREAMBLE_SHA256`; `katex_commands_sha256` equals the sha256 of the file's bytes;
  `katex_version` is a string and `{katex_version} == katex_known()["version"]` (the latter is a one-element set); both undefined lists are sorted, are subsets of KaTeX's commands and
  environments; the file records an engine line containing `XeTeX` and a file entry for `IEEEtran.cls`; each of `R`,
  `mathscr`, `htmlClass` is undefined and each of `geq`, `frac` is defined. A stale file fails with a message that names
  the script.
- **No-leak property test** (seeded `random.Random`, at least 3,000 generated texts from a token pool that mixes plain
  words, `$`, `$$`, `\$`, newlines, every deny-listed and allowed command, environments, `&`, `\\`, `%`, `#`, `^^`, braces,
  Unicode symbols and controls): `convert_text(...)` never raises; after removing the escape sequences `escape_text`
  produces and the wrapper commands this module writes (`\begin{equation}`, `\end{...}`, `\label`, `\ensuremath`, the
  symbol-table commands), every remaining control word in the output belongs to `katex_known()["commands"]` minus
  `COMMAND_DENY`, every output backslash that is not part of a produced sequence belongs to a span that passed the closed
  scan, and no output contains `\input`, `\def`, `\write`, `\csname`, `\catcode`, `^^`, an unescaped `%` or `#`, or an
  `\begin`/`\end` whose environment name (whitespace and line breaks skipped, as the scanner does) is not in the
  allowed-environment set; `\begin{document}` and `\begin {document}` never appear. A valid `$$\begin {aligned}x&=y\end {aligned}$$`
  is **not** forbidden: it is a positive test and its output keeps the spaces. (Write the checker as a small tokenizer in
  the test, not a regex that shares the scanner's code.)

## Checks to run (in the worktree)

1. `PYTHONPATH=backend:. uv run pytest tests/test_report_latex_text.py tests/test_report_latex_math.py -q`.
2. The names script (decision 9) once, then re-run 1.
3. `PYTHONPATH=backend:. uv run pytest tests/test_report_export.py tests/test_report_failure_display.py tests/test_p6_measure_report.py tests/test_bibliography.py tests/test_arxiv_source_archive.py tests/test_arxiv_source_fetch.py tests/test_arxiv_source_route.py tests/test_arxiv_source_matching.py tests/test_arxiv_source_migration.py tests/test_contracts.py -q`
   (unchanged files must still pass); the orchestrator runs the full pytest.
4. `git diff --check`; `git status --short` shows only the allowed files.
5. Spot check by hand (not a test): compile one small `.tex` with `PREAMBLE`, a plain paragraph using the escape output,
   one display of each kind from `render`, and `\text{≥}` converted; report whether it compiled and anything odd (for
   example how `` `` `` quotes and `--` print under fontspec). Do not commit the files; delete them under `/tmp`.

## Report at the end

Files created; the public surface as shipped (names and signatures); the deny list as shipped; the symbol table size and
any entry you were unsure about; every own judgement kept or changed; the names script run (TeX version line, counts of
undefined commands and environments) or why it could not run; test counts and the exact pytest summary; the compile spot
check result; anything you could not find or make pass, and anything in the note that looks wrong or contradictory.
