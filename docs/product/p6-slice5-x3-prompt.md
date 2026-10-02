<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1 4 high (bib year written raw, key-suffix contradiction, invariants vs expected-error cases, claim_key leak vs skipped-rule list), 8 medium/low folded in; r2 3 high (escaped braces unbalance BibTeX fields, year reaches the automatic key, link number without source_version_id check), 7 medium folded in; r3 1 high (given keys checked only in latex_report mode), 4 medium/low folded in; no fourth round (limit) -->
<!-- CODE-REVIEW-ROUNDS: gpt-6.1-sol high, 1 round: 0 high, no finding, verdict hazir (after two orchestrator fixes from the hand compile: no bibliography commands without a citation, source column 1.0in) -->

# Task: P6 slice 5, batch X3, the LaTeX assembler `to_latex`, the bibliography parameters and the golden `.tex`/`.bib` files (no model, no TeX at run time)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-x3` (detached at `dc4b19c`, which is `origin/main`
with slice 5 X1 (D153) and X2 (D151) on top). Read `AGENTS.md`, `CLAUDE.md`,
`docs/product/p6-slice5-latex-export.md` (the whole note; this batch is its section 11 "X3"; sections 3, 5, 6, 7, 9 and
decisions Q2, Q3, Q4, Q6, Q7, Q10, Q11, Q18, Q19, Q21, Q22 bind it) and D153, D151, D149, D120 and D127 at the top of
`docs/decisions.md`. Read also `docs/product/p6-slice5-x1-prompt.md` and `p6-slice5-x2-prompt.md` (same style, and their
"left open" notes). Where this prompt differs from the note, this prompt wins and says so.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find or could not make pass. No real-model call, no network, no
provider call, no TeX in any test. Do not touch `../DEIXIS`, `../DEIXIS-k*`, `../DEIXIS-e*`, `../DEIXIS-s4*`, `.local/`,
`TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`, ports 8765 and 8858-8864. Tests run with
`PYTHONPATH=backend:. uv run pytest ...` (`UV_CACHE_DIR=/tmp/deixis-uv-cache` if uv cannot write its cache). Do not run
`xelatex` or `bibtex`; the orchestrator compiles the golden files by hand outside the sandbox.

## What is and is not in code (checked on dc4b19c)

- Not in code: `workflow/report/latex.py`, `tests/test_report_latex.py`, `tests/report_latex_cases.py`,
  `tests/fixtures/report_latex/`, any `latex_report`/`keys` parameter of `bibliography.to_bibtex`, any call of
  `latex_text`/`latex_math` from production code (nothing calls them yet), any `format=latex` route (X4).
- Present and used read-only (X2, D151): `latex_preamble.PREAMBLE`, `PREAMBLE_SHA256`; `latex_text.escape_text(text,
  unmapped=None)`, `symbol_text`, `symbol_math`, `is_unmapped`, `SYMBOLS`, `Unmapped` (`add`, `count`, `note()`);
  `latex_math.split_text`, `classify(span, *, cell=False) -> MathSpan(source, kind, labelable, body, class_b, notes)`,
  `render(m, label=None, unmapped=None)`, `convert_text(text, *, cell=False, label_for=None, unmapped=None) -> (text,
  notes)`, `closed_scan`, `command_status`, `COMMAND_DENY`; `latex_names.json`. `convert_text` removes spaces next to a
  display's line breaks, never leaves a blank line, and does **not** strip the two ends of its result. `render` raises
  `ValueError` for a label that is not `eq:EQ[0-9]{1,3}`. `escape_text` collapses whitespace and does not strip. X2 files
  are **not** changed by this batch.
- Present (X1, D153): `export_text.py` with `HEADINGS`, `REVIEW_CODES`, `REVIEW_REASONS` and 26 functions in the classes
  PLAIN (no stored text, returned raw), WHOLE (may hold stored text, returned unescaped, the caller escapes the whole),
  PIECEWISE (takes `esc: Callable[[Any], str]`, calls it exactly where the Markdown writer called `_md`, result final) and
  helper. `export.py` keeps `_md`, `_table`, `to_markdown`, `export_markdown` and is the reference for section order, table
  placement, paragraph grouping and what is written when a section is empty. `tests/test_report_export_pin.py` pins 120
  Markdown outputs and must still pass **unchanged**.
- X1's open question (PIECEWISE/WHOLE split has no LaTeX consumer yet): read against this batch, **no signature has to
  change**. The LaTeX writer calls PIECEWISE functions with its own `esc`, WHOLE functions by escaping the returned whole,
  and takes the "final formatted raw text" that the long-value threshold needs by calling `cell_text`/`source_cell` with an
  identity `esc` (decision 7). If you find a case where this is wrong, you may edit `export_text.py` and
  `tests/test_report_export.py` (additions only), but only if `tests/test_report_export_pin.py` and every existing export
  test stay green with no change to any pinned literal; say so in your report. Otherwise do not touch them.
- `report_view` (in `workflow/views.py`, not ours) gives: `sections` in `DISPLAY_ORDER` with `claims` already grouped by
  first-appearing paragraph, each claim `{text, paragraph, equation_ref, table_ref, evidence: [{ref_number, anchor_match,
  ...}], evidence_basis, support_type_note, ...}`; `references` (`number, source_version_id, source_key, title, authors,
  year, venue, doi, version_label`; numbers are assigned in first-appearance order over the claims, so every reference is
  cited at least once); `table_i`; `missing_rows`; `has_human_edits`, `edited_after_version`, `edit_check`,
  `evidence_changes`, `review`, `run`, `status`, `report_version`, `language`. `source_key` may be `None`; two source
  versions of one work share a key. The fields `publication_type`, `volume`, `issue`, `pages`, `landing_url`, `arxiv_id`
  are **not** in `references`; they come from `bib_sources` (below), which X4 reads from `source_versions` and
  `identifier_mappings` in the same read.
- `bibliography.to_bibtex(sources)` (D16, Zotero export) exists with `_keys`, `_tex`, `_author`, `_raw`, `_line`;
  `tests/test_bibliography.py` pins parts of its output. `bibliography.py` imports `workflow.views` at the top; if
  `latex.py` importing it creates an import cycle, import it lazily inside the function and say so.
- This machine has TeX Live 2021, but the sandbox you run in may not execute it. You do not need it.

## Decisions taken (the note's own default where it has one; own judgement is marked)

1. **Public surface (X4 consumes it, keep it stable and list it in your report).** New module
   `backend/deixis/workflow/report/latex.py`:
   `to_latex(view, *, title, corpus, bib_sources) -> LatexBundle`, a frozen dataclass `LatexBundle(stem: str, tex: str,
   bib: str, notes: tuple[str, ...])` (`note_count` as a property = `len(notes)`). `stem` is
   `export_text.report_stem(view, title)` (so `\bibliography{<stem>}` and the future zip names agree with Markdown).
   `bib_sources: list[dict]` holds one dict per source version, each with `source_version_id` and the keys
   `to_bibtex` reads (`title, authors, year, venue, publication_type, doi, landing_url, version_label, arxiv_id`, optional
   `volume, issue, pages`). `to_latex` is pure: it reads only its arguments, never mutates `view` (a test deep-copies and
   compares), and is deterministic. Allowed imports in `latex.py`: `__future__`, `dataclasses`, `re`, `unicodedata`,
   `typing`, `collections.abc`, `deixis.domain.rules` (`RevisionConflict`), `deixis.workflow.bibliography`,
   `deixis.workflow.report.export_text`, `latex_math`, `latex_text`, `latex_preamble`, and
   `deixis.workflow.report.store.DISPLAY_ORDER` (a constant; the Markdown writer imports it from there too). No `sqlite3`,
   `httpx`, `subprocess`, `os`, `tempfile`, `export.py` or `views.py` (a test checks the import lines). **Failure modes
   (all `RevisionConflict` with a plain English message; X4 maps it to 409; the note's "no silent drop, no renumbering"):**
   a reference `number` that is not a positive `int` (a `bool` does not count), two references with the same `number` or the
   same `source_version_id`; a claim link (it must carry both `ref_number` and `source_version_id`) whose pair does not
   resolve to the **same single** entry of `view["references"]`; a table row whose `ref_number` differs from the number of the
   reference with the row's `source_version_id` (expected `None` when no reference has that version); a reference with no `bib_sources` row, or two
   `bib_sources` rows with the same `source_version_id`; a cite key collision that cannot be resolved (decision 10); a
   `bib_sources` row missing a key `to_bibtex` needs. **Type guards (own judgement, fail closed, because
   `export_text` PIECEWISE results are written raw):** `edited_after_version` must be `None` or an `int`, and each
   `edit_check` `errors`/`warnings` an `int` (a `bool` does not count), else `RevisionConflict`; the `stem` must
   fullmatch `report-[a-z0-9-]+-(draft|v[0-9]+)` (it reaches `\bibliography{}` and a comment), else `RevisionConflict`.
   PLAIN functions' numbers need no guard because their results go through `fixed`.
2. **One escape path per context (own judgement; the note says "one escape path" and fixes only the cell case).** Create
   one `Unmapped()` per call and one note list. Three small private callables, all starting from the one coercion
   `text_of(v) = "" if v is None else str(v)` (tested for all three with `None`):
   - `fixed(text)`: `escape_text(text, unmapped)`; for PLAIN strings from `export_text` and for the fixed words this module
     writes. These contain no `$`.
   - `line(value)`: `convert_text(text_of(value), cell=True, unmapped=um)`, notes collected, result **stripped**; for every
     stored value in a one-line position: the title, the draft line (WHOLE: escape the returned whole), headings (WHOLE),
     the `esc` argument of every PIECEWISE call (`missing_row_fields`, `edit_note`, `review_note`, `finding_fields`),
     keyword terms, table headings, table cells and the source column. `cell=True` means the note's table-cell math subset
     applies everywhere `line` is used and a `$$..$$` span that is plain becomes inline; the X2 notes it produces say
     "table cell" even outside a table, which is a known wording limit (put it in the decision record).
   - `body(text, label_for)`: `convert_text(text, cell=False, label_for=label_for, unmapped=um)`, result stripped; for
     claim text of the abstract and sections I-IX and for `draft.text` of II and VIII (no labels there).
   Template words that PIECEWISE functions write around the `esc` pieces stay unescaped by contract; a test (below) proves
   they hold none of `\ { } $ & # ^ _ % ~ "` and no unmapped character, so this is safe. Stored text never reaches the
   output except through one of these three callables, a long-value note list (decision 8) which uses `line`, the
   bibliography (decision 10) or the cite-key rule (decision 10). The `esc` of the long-value threshold is an identity
   (decision 7), and its result goes through `line` before it is written.
3. **Document skeleton.** In this order, one blank line between blocks, the environments and commands this module writes on their own lines (the display
   environments X2 keeps as saved, such as a `$$\begin {align}x&=y\end {align}$$` body, are exempt), file
   ends with `\end{document}` and a single newline:
   1. export-notes comment block (decision 11);
   2. `PREAMBLE` verbatim;
   3. `\begin{document}`; for Turkish only, right after it, three lines `\renewcommand{\abstractname}{Özet}`,
      `\renewcommand{\IEEEkeywordsname}{Dizin Terimleri}`, `\renewcommand{\refname}{Kaynaklar}` (note section 3, M11);
   4. `\title{<line(title)>}` then `\maketitle` (no `\author`);
   5. the identity paragraph and the unchecked blocks (decision 4), each a `\noindent` paragraph or list;
   6. the abstract environment, then the keywords environment, then sections I to IX and Table I (decision 5, 7);
   7. `\section*{Report notes}` (`Rapor notları`) (decision 9);
   8. `\bibliographystyle{IEEEtran}`, `\bibliography{<stem>}`, `\end{document}`.
   Language is Turkish exactly when `export_text.is_turkish(view)`.
4. **Identity and unchecked blocks (note section 3 item 2; the order differs from Markdown on purpose).** After
   `\maketitle`: (a) `\noindent` + `fixed(report_identity(view, tr))`; (b) the draft line, `\noindent` +
   `line(draft_line(view, tr))` when it is not `None`; (c) missing rows when `view["missing_rows"]` is truthy: a
   `\noindent` paragraph `fixed(missing_rows_sentence(...))`, then, only when there is at least one failed row, an
   `itemize` with one `\item <source>: <reason>` per row (`missing_row_fields(row, tr, line)`); (d) the edit note when
   `edit_note(view, tr, line)` is not `None`: a `\noindent` paragraph of `.paragraph`; when `.not_checked_heading` is not
   `None`: an `itemize` of the `.items` (each `\item <section> M <rule> (<severity>): <detail>`), only if there are any,
   then a `\noindent` paragraph of `.not_checked_heading`, then an `itemize` of the `.skipped_rules`
   (`\item <section> M <claim_key>: <rule> (<reason>)`; the stored `claim_key` value is written as Markdown writes it, a
   narrow explicit exception to "no internal id": D148 gives the user no other handle for a skipped rule) followed by the `.not_checked` strings, only if there is at least
   one of either (`M` is the middle dot: write `fixed(" · ")`, i.e. whatever the table gives, once, as a module constant);
   (e) `fixed(evidence_changed_sentence(tr))` as a `\noindent` paragraph when `view["evidence_changes"]["any"]` is truthy.
   **An empty `itemize` is a LaTeX error: never write one** (a test scans every golden). **List-start guard:** the text of a
   `\item`, and the first cell of every table row, is prefixed with `{}` when it starts with `[` or `*` (an `\item [` is read
   as an optional argument and a row start `[` or `*` after `\\` is read as `\\[...]`/`\\*`; this is the X1-open point a
   LaTeX consumer meets); every other position needs no guard.
5. **Sections.** Sections are sorted exactly as `to_markdown` sorts them (`DISPLAY_ORDER`, unknown ids last). Claim reading
   order: paragraphs in first-appearance order, claims in list order inside a paragraph (the Markdown rule, including its
   use for table placement and for the label pass below).
   - **Fragment** of a claim: `body(claim["text"], label_for)` + (` \eqref{<label>}` when decision 6 says so) + (` \cite{k1,k2}`
     when the claim has links: keys in the order of first appearance of `ref_number`, duplicates dropped, the Markdown rule).
     Fragments of one paragraph are joined with one space; paragraphs are separated by one blank line. A plain space, not
     `~`, before `\cite`. **Display boundary rule (one helper `join(a, b)` used for fragments, ` \eqref` and ` \cite`):**
     the separator is a single LF instead of a space when `a` ends with a display closer (it matches
     `\\end\s*\{[A-Za-z*]+\}$`) or `b` starts with `\\begin\s*\{` (X2 keeps a saved `\begin {align}` or an `\end` + LF +
     `{align}` as written, so whitespace before the brace is allowed; stored text can never start or end that way, since a
     stored backslash is written `\textbackslash{}`; a valid inline span starts and ends with `$`). So two displays in a row, a
     display followed by `\cite{..}`, and a claim starting with a display each sit on their own lines, with no blank line.
     Tests give exact output for each of these three, and again for a spaced `\begin {align}` and an `\end` + LF + `{align}`.
   - `abstract`: `\begin{abstract}` ... `\end{abstract}`; the paragraphs inside. `index_terms`: `\begin{IEEEkeywords}` ...
     `\end{IEEEkeywords}` holding the claims of the section in reading order, each fragment made with `line` instead of
     `body` and **no** `\eqref`, joined with `, ` (decision: the index terms are one line; `\cite` is kept, Q4). If the
     section is absent from the view its environment is absent. A section with status `draft` or `failed` gets the
     unvalidated note: for the two environments it is one `\noindent\textit{...}` paragraph **before** the environment
     (own judgement: they have no heading of their own, so the text is `line(heading(sid, tr))`, `: `, then
     `fixed(section_unvalidated_note(tr))`); for sections I-IX it is a `\noindent\textit{<fixed(section_unvalidated_note(tr))>}`
     paragraph right after the heading.
   - Sections I-IX: `\section*{<line(heading(sid, tr))>}` (IEEEtran's own numbering is not used; the Roman numeral is part
     of the heading text, as in `HEADINGS`); then in this order, as in `to_markdown`: unvalidated note (draft/failed), the
     VI preface (`fixed(vi_preface(tr))` as a plain paragraph), Table I at the start of IV when no claim of IV carries
     `table_ref == "TABLE_I"`, the `draft.text` of II/VIII as `body(text, None)` when present, the claim paragraphs (Table I
     right after the paragraph holding the first `TABLE_I` claim), and, when there is no claim and no II/VIII `draft.text`,
     the insufficient-evidence paragraphs (`fixed(not_enough_evidence_label(tr)) + ": " + line(reason)`, one per stored
     reason) or, with none, `fixed(no_text_sentence(tr))`. Unknown section ids use the id as heading (WHOLE, through
     `line`). The abstract and keyword environments use the same empty-section rule inside the environment.
6. **Equation labels (note section 4 "Denklem etiketi ve numarası", Q6; the scenario tests moved here from X2).** A first
   pass over the claims of the abstract and sections I-IX in reading order (index-term claims do not take part), before
   anything is written, decides per `equation_ref` value R (stored text, never written): the **target** is the first
   `labelable` math piece (classified with `classify(piece, cell=False)`, pieces from `split_text`) among the claims that
   carry R, in reading order. R gets a label `eq:EQ<k>` where `k` is the 1-based rank of R among the distinct refs in order
   of first appearance; a rank above 999 is treated as "no target". The write pass passes `label_for(index, m)` returning
   the label for exactly the target piece of the target claim and `None` otherwise (so every other labelable piece of that
   ref, and every labelable piece of claims without a ref, is `equation*`; E-class and `\tag`-class pieces stay unchanged
   and unlabeled; `render` ignores a label for them). A claim that carries R whose target is in another claim: if it has no
   display piece of its own (no piece whose `classify(...).kind` starts with `display_`), append ` \eqref{<label>}` to its
   body fragment (before the `\cite`); if it has one, append nothing and count it for the note "claims that cite an equation
   reference and hold a display expression of their own" (the code does not compare the two expressions; an identical
   `$$x$$` repeated in the claim gets the same note, and a test says so). A ref with no target: append nothing for any of its claims and count
   it for the note "equation references without a numberable display expression". Each of the two notes is **one** note
   per document with the count, written only when the count is above zero; literal texts (`k` = the count): `k equation
   references have no numberable display expression; no cross-reference was written for them.` (`1 equation reference has
   no numberable display expression; no cross-reference was written for it.`) and `k claims cite an equation reference and
   hold a display expression of their own; no cross-reference was written for them.` (`1 claim cites an equation reference
   and holds a display expression of its own; no cross-reference was written for it.`). The
   Markdown number `(n)` is not written. Invariants (tests): every `\eqref{L}` has a `\label{L}`, every label is unique.
7. **Table I (note section 5, Q7, Q19).** Placement as Markdown. The table is written only if `view["table_i"]` is truthy
   and the section IV exists (the Markdown rule). `caption` = `export_text.table_caption(table, tr)` with its leading
   `"TABLE I. "`/`"TABLO I. "` removed by `removeprefix` (a test pins both prefixes; if the prefix is missing, raise
   `AssertionError`), passed through `fixed`.
   - **Column groups:** `columns` are split into consecutive groups of at most 7 (module constant `MAX_DATA_COLUMNS = 7`);
     no columns means one group with only the source column. Every group repeats all rows and the source column. Layout
     per group is the skeleton of the note section 5, written once as `\onecolumn` before the first group and
     `\twocolumn` after the last. Each group is `{\scriptsize` newline `\begin{longtable}{<colspec>}` ... `\end{longtable}}`;
     every group after the first is preceded by `\addtocounter{table}{-1}` (so every caption says TABLE I). The colspec
     is `>{\raggedright\arraybackslash}p{<SRC>}` followed by one `>{\raggedright\arraybackslash}p{<W>}` per data column in
     the group, where `SRC` is the module constant `SOURCE_COLUMN_WIDTH = "0.6in"` and
     `W = \dimexpr(\textwidth-<SRC>-2\tabcolsep)/<n>-2\tabcolsep\relax` with `n` the data columns of the group. The first
     head is `\caption{<caption>[ (columns a–b of N)]}\\` (the bracket part only when there is more than one group; en dash
     U+2013 is inside the safe range) followed by `\toprule`, the header row, `\midrule`, `\endfirsthead`; then
     `\caption[]{<caption> (columns a–b of N) (continued)}\\` (the middle part again only with several groups),
     `\toprule`, the header row, `\midrule`, `\endhead`, `\bottomrule`, `\endlastfoot`; then the rows, each ending with
     ` \\`. Turkish words: `(N sütundan a–b)` and `(devamı)`. Header cells: `line(source_heading(tr))` then the
     column names. Cells and source column are the **Markdown cell texts** (next bullet) with the list-start guard.
   - **Cell text = the Markdown text.** Get the final formatted raw text with
     `export_text.cell_text(cell, column, tr, identity)` and `export_text.source_cell(row, tr, identity)` where `identity`
     returns `str(v)`; the heading raw text is `column["name"]`. Write `line(raw)` when the raw length is within the
     threshold, or the "see note" pointer (decision 8) when it is above. Missing cells are `—` (U+2014, written raw as
     `export_text` returns it, through `fixed`).
   - **A hostile first cell:** the guard of decision 4 applies to each row's first cell (and to the header's).
   - A note `Table I was split into <g> column groups of at most 7 data columns.` when `g > 1`. The group count is
     `max(1, ceil(N / 7))`.
8. **Long values (note section 5, "Uzun değerler kayıpsız yola alınır").** Thresholds on the **final formatted raw text**
   (the contract in the note: after the state words such as the "not verified" parenthetical, before TeX escape), counted
   in Python `len()` of the string: column heading > 400, cell > 400, source column > 200 (module constants; strictly
   greater; a test pins 400 kept and 401 moved, 200 kept and 201 moved). A moved value is written in the table as
   `fixed("see note k")` / `fixed("k numaralı nota bakın")` and the full raw text goes into the list. Numbering is done in
   one pass over the whole table before any group is written: column headings first (column order), then rows in row order,
   each row's source text first and then its cells in column order. A moved value takes the next number `k` from 1 **by
   position** (a column heading, a row's source text, or one row-and-column cell); the same position never gets two
   numbers, and a row's source text, which repeats in every column group, reuses the number of its position. Equal texts at
   different positions get different numbers (the entry names its own position).
   The entries are written in the `Report notes` section (decision 9) as an `itemize` of `\item[k.] <text>`, with
   `text` = `Column c heading: <line(full)>`, `Row r source (<L>): <line(full)>` or `Row r, column c (<L>): <line(full)>`
   (Turkish: `Sütun c başlığı: `, `Satır r kaynağı (<L>): `, `Satır r, sütun c (<L>): `), where `c`, `r` are 1-based order in
   the table and `L` is `[n] source_key` when the row has a `ref_number` (just `[n]` when its key is `None`), otherwise
   `row r` / `satır r`; the label goes through `line` as it holds the stored key. The list is preceded by a
   `\noindent\textbf{<Long table values | Uzun tablo değerleri>}` line. A note `<k> table values were moved to the Long
   table values list in Report notes.` (`1 table value was moved to the Long table values list in Report notes.`) is
   added when `k > 0` (k counts entries, i.e. positions). No moved value is ever lost: every
   full text appears (escaped) in the list.
9. **Report notes (note section 3 item 6 and Q21; order own judgement where the note lists several).** `\section*{Report
   notes}` / `\section*{Rapor notları}`; then, each a plain paragraph, in this order: (a) `fixed(corpus_footer(corpus, tr))`;
   (b) `fixed(anchor_note(view, tr)) + " " + review_note(view, tr, line)` (one paragraph, as Markdown; `review_note` is
   PIECEWISE so it is not escaped again); (c) when `view["review"]` is reviewed with findings: a
   `\noindent\textbf{<fixed(findings_heading(tr))>}` line and an `itemize` of `\item <section> M <code> M <text>` (the
   `finding_fields(finding, tr, line)` pieces joined with the middle dot); (d) the Long table values block (decision 8)
   when there is any entry; (e) the traceability limit, a fixed sentence pair defined in `latex.py`: English "This export
   carries the report text and its bibliography. The quoted passages, the table cell evidence and the located citation
   anchors stay in DEIXIS." Turkish "Bu çıktı raporun metnini ve kaynakçasını taşır. Alıntı pasajları, tablo hücresi
   kanıtları ve konumlanmış atıf çapaları DEIXIS'te kalır." (written through `fixed`; these two sentences are literal.)
10. **Cite keys and bibliography (note section 6, Q3, Q10).**
    - Key per reference, in `view["references"]` order: the base is `source_key` when it is a `str` and `re.fullmatch(r"[A-Za-z0-9]+", ...)` succeeds
      (own judgement, fail closed: D59 keys are letters and digits; anything else, including a key with a trailing newline,
      is unusable), otherwise `ref<number>`.
      **Suffixes apply only to a usable `source_key` that an earlier reference already holds** (compared
      case-insensitively): the second, third, ... holder become `<base>-2`, `-3`, ...; a fallback `ref<number>` never gets a
      suffix. After all keys are assigned they must be unique case-insensitively across the whole list; any collision (for
      example a real key `ref1` and a fallback `ref1`, in either reference order) raises `RevisionConflict`. Notes, literal:
      `Reference [n] has no usable source key; cite key ref<n> was used.` and `Reference [n] shares a source key with an
      earlier reference; cite key <key> was used.` Keys are `[A-Za-z0-9-]+`, never stored text, so a cite key and a comment
      note can never carry TeX.
    - Reference order check: number the cited references 1, 2, ... in the order of their first `\cite` in the document
      (position `p`); if any cited reference has `p` different from its recorded `number`, add the note `Reference numbers in
      the PDF follow the order of first citation and differ from the numbers in DEIXIS.` (an uncited reference at the end
      does not trigger it; an uncited one in the middle does, correctly, because later numbers shift) A reference never cited gets the note
      `Reference [n] is not cited in the text and BibTeX will not print it.` (do not add `\nocite`; Q4).
    - `.bib`: `bib = bibtex_with_notes([bib row of each reference], keys, latex_report=True, unmapped=um)`; its notes join
      the list. A reference without a matching `bib_sources` row raises `RevisionConflict`.
    - **`bibliography.py` changes (the only ones):** an internal `bibtex_with_notes(sources, keys=None, *,
      latex_report=False, unmapped=None) -> tuple[str, list[str]]`; `to_bibtex(sources, keys=None, *, latex_report=False)
      -> str` is `bibtex_with_notes(...)[0]` (no collector). With `keys` given, its length must equal `len(sources)` and
      its values must be unique case-insensitively and each be a `str` that `re.fullmatch`es `[A-Za-z0-9][A-Za-z0-9-]*`,
      else `ValueError` (a `zip` must never drop a source); this applies to **both** modes, because a key is written into
      the file (the check on keys the function **generates** is only in `latex_report=True`, so the default path's output
      does not change). With `latex_report=False` and no `keys` **the output is byte-identical to today** (decision: `to_bibtex(sources)`
      stays exactly what D16 shipped); when `keys` is given with `latex_report=False`, the given keys replace `_keys` and
      nothing else in the output changes. With `latex_report=True`: the title is wrapped
      in a second pair of braces (`title = {{...}}`, M4); every text field (title, authors, venue field, volume, number,
      pages, note) is written with `latex_text.escape_text(_line(value), unmapped)` instead of `_tex` (one escape pass that
      also applies the symbol table, so there is no double escaping; an author name containing the word "and" keeps its
      brace wrap), **followed by** `.replace("\\{", "\\textbraceleft{}").replace("\\}", "\\textbraceright{}")`: BibTeX counts
      the braces of `\{` and `\}` too, so a lone `{` in a title would unbalance the field (`escape_text` produces `\{` only
      for a stored brace); tests with a lone `{`, a lone `}` and a pair in a title, an author, a venue and a version note;
      **in this mode the years are checked first**: a `year` that is not an `int` (a `bool` does not count) or `None` is replaced by
      `None` in a copy of the row **before** `_keys` runs (the default path stays as it is), and every key, given or
      generated, must be a `str` that `re.fullmatch`es `[A-Za-z0-9][A-Za-z0-9-]*`, else `ValueError`; `doi`, `url`, `eprint` are first checked on the **original value** (before `_raw`, which strips whitespace and would hide
      a newline): the field is **omitted** when it holds a backslash or a character of Unicode category Cc, Cf, Zl, Zp, Cs,
      Co or Cn (so LF, TAB, CR, NUL, bidi marks and U+2028 are all covered; a test per class), with the note
      `Bibliography: omitted <field> of <key> because it holds a backslash or a control character.`; otherwise `_raw` as
      now. `year` is written only when it is an `int` (not a `bool`) or `None`/falsy as today; any other type is dropped, with the note
      `Bibliography: omitted year of <key> because it is not a number.` (a hostile string year such as `2026}\input{evil}` must
      never reach the file, an automatic key, or a field). Everything else (entry type map, field order, `eprinttype`) is unchanged.
11. **Export notes (note section 7; the 20/200 limits apply to the comment block only).** `notes` is built in this order:
    key notes and the reference-order notes; equation notes; the notes collected while writing, in document order (the
    `convert_text` notes of X2, the table-group and long-value notes); `.bib` notes; finally the one `Unmapped.note()`
    (shared by text and bibliography, once). Each note is normalised before it is stored: whitespace collapsed, every
    character outside printable ASCII (U+0020..U+007E) replaced by `?`, then stripped; the list is de-duplicated keeping
    first occurrence; `LatexBundle.notes` holds this full list uncut. The comment block at the top of the `.tex`
    (every line starts with `%`): `% DEIXIS evidence report, IEEEtran export for XeLaTeX.`, `% Compile with: latexmk
    -xelatex <stem>.tex`, `% Needs XeLaTeX, BibTeX and the IEEEtran class and IEEEtran.bst style; they are not included.`,
    `% Export notes: <N>` (or `% Export notes: none`), then up to 20 lines `% <i>. <note>` **where the whole line, prefix
    included, is cut to at most 200 characters** (note section 7: 200 per line), then `% and <K> more` when `N > 20`.
    Tests: 0, 1, 20 and 21 notes; whole lines of 199, 200 and 201 characters; de-duplication after normalisation;
    `bundle.notes` stays complete and uncut when the comment block cuts. A hostile stored string can reach a note only through the ASCII normalisation, so a
    newline cannot end the comment (a test). The response header and toast are X4/X5.
12. **Own judgements to list in the decision record** (the orchestrator writes it; give it what it needs): the `line`/`body`
    split and the `cell=True` wording limit; the abstract/keywords unvalidated-note form; the order of the unchecked blocks
    versus Markdown; the middle dot via the symbol table; `\item[k.]` for long values; the key regex; the bib control-char
    rule; the source-column constant and what the hand compile showed (the orchestrator will report it); the notes order.

## Files allowed

- `backend/deixis/workflow/report/latex.py` (new)
- `backend/deixis/workflow/bibliography.py` (decision 10 only)
- `tests/test_report_latex.py`, `tests/report_latex_cases.py` (new), `tests/fixtures/report_latex/*.tex` and `*.bib` (new)
- `tests/test_bibliography.py` (new tests appended; existing tests unchanged)
- **Exception to the note's X3 file list, only for a demonstrated consumer-contract problem** (see "What is and is not in
  code", X1's open question): `backend/deixis/workflow/report/export_text.py`, `tests/test_report_export.py` (additions
  only); `tests/test_report_export_pin.py` must stay byte-identical. Name the problem in your report if you use it.
- `docs/decisions.md` is **not** yours; the orchestrator writes the decision entry. This prompt file: no edits.

## Files NOT allowed

Everything else. In particular `latex_preamble.py`, `latex_text.py`, `latex_math.py`, `latex_names.json`,
`scripts/latex_export_names.py`, `workflow/report/export.py`, `views.py`, `assembly.py`, `workflow/store.py`,
`api/app.py` (the route is X4), `domain/contracts.py`, `apps/web/`, `methods/`, `contracts/`, `storage/migrations/`, other
tests, `tests/test_report_export_pin.py`, lockfiles. No migration, no contract schema change, no `skill_package_hash`
change. If a needed change seems to require one of these, stop that item and report it.

## Tests to add (no test may need TeX, the network, a model or a real database; golden views are SYNTHETIC)

`tests/report_latex_cases.py`: hand-built `view` dicts and `bib_sources` (a small `CASES` mapping from case id to a builder
returning `(view, title, corpus, bib_sources)`), numbered like `report_view` numbers (first appearance in reading order),
claims and links carrying sentinel internal ids (`psg_SENTINEL`, `cel_SENTINEL`, a sentinel `claim_key` **value** on each
claim, a sentinel `support_type`, link and claim row ids) so an absence test means something. The file also holds a
`COVERAGE` mapping from branch names to case base names (a case id is `<base>-en` or `<base>-tr`), and the test file holds the
required branch set as its own literal: `draft_rules_known`, `draft_rules_more_than_three`, `draft_rule_unknown`,
`draft_warning_filtered`, `draft_error_absent_or_invalid`, `draft_sections_unvalidated`, `missing_rows_key`,
`missing_rows_title_fallback`, `insufficient_reasons`, `empty_section`, `ii_viii_text_with_claims`,
`ii_viii_text_no_claims`, `vi_preface`, `review_none`, `review_not_reviewed_unknown_reason`, `review_reverted`, `review_unread_sections`, `identity_draft_and_valid`, `edit_none`,
`edit_current`, `edit_historical`, `edit_in_draft`, `edit_empty_lists`, `edit_zero_links_with_other_links`,
`edit_zero_links_none_left`, `evidence_changed`, `anchors_all_located`, `anchors_unlocated`, `corpus_none`, `corpus_dict`.
A test asserts `set(COVERAGE) == REQUIRED`, every value is a non-empty list of base names, and both the `-en` and `-tr` id of
each base exist in `CASES`. **Each branch also has a predicate** over the case's `view` in the test file (for example
`len(view["review"]["findings"]) == 2` for `review_reviewed_2_findings`), run on every mapped case and required to be true,
so one empty case cannot stand for several branches. The required set also holds one branch per review sub-state:
`review_not_reviewed_<reason>` for each of the six `REVIEW_REASONS` keys and `review_reviewed_0_findings`,
`review_reviewed_1_finding`, `review_reviewed_2_findings`. **Three kinds of case:** *normal* cases get every invariant below and a golden; *noted-exception* cases (a reference
order that differs from first citation, an uncited reference, a ref without target, ...) keep the golden but are excluded from
exactly the invariant they are built to break (say which in a comment) and get an assertion on the exact note; *expected-error*
cases (missing reference, missing `bib_sources` row, duplicate numbers, key collision, bad `edited_after_version` type)
assert only the `RevisionConflict` and its message. This is a deliberate narrowing of the note's "invariants over every
case" and goes into the decision record. `tests/test_report_latex.py`: one parametrised golden test per **normal and noted-exception** case id comparing
`bundle.tex` **and** `bundle.bib` with `tests/fixtures/report_latex/<case>.tex` and `<case>.bib` byte for byte (a case with
no references has an empty `.bib` file and it is compared too; expected-error cases have no golden) (read as UTF-8, no newline translation). **Goldens are written by reading, not by blind regeneration:** produce each
file once with a throwaway script in `/tmp`, then read it against the sentence and structure the code is meant to write,
fix the code or the case, and only then keep it. Record how many files and which cases.

Cases (every case in `en` and `tr`, one `tr-TR` somewhere, unless marked): the Q18 groups and the Q22 sixth group as in the
X1 pin matrix (draft with the assembly refused incl. unknown and `*_warning` rules; missing rows with `source_key`, with
`None` falling back to title; insufficient evidence and empty sections; II/VIII `draft.text` with and without claims; no
review, `not_reviewed` with each reason class, reviewed with 0/1/2 findings, reverted, unread sections; edit states: none,
current check, historical check, draft with edits, all-empty lists, a claim with zero effective links with and without
other links; evidence changed; located and unlocated anchors; corpus `None` and a dict); **math classes in claims**:
inline, E environment, `\tag`, `aligned`, `gathered`, plain display, class A (plain text), class B (`\R`), an unmapped
character in text and in math (one note); **equation labels**: a ref repeated across claims with its target in the first
(later claim gets `\eqref`), the target in a claim holding several displays, a ref whose first span is E-class or `\tag`
(not labelable) and a later plain display (target is the later one), a claim whose own display differs from the ref's target
(no `\eqref`, note), the same ref on two different expressions, a ref with no labelable span (no `\eqref`, note), two refs
(labels `EQ1`, `EQ2`), an abstract claim holding a display; **references**: two source versions of one work key
(`-2`), a `None` key (`ref<n>`, note), a key with a hyphen or a space (unusable), a `ref1`-style collision (raises),
`index_terms` with a cite, a reference order that differs from first citation (note), an uncited reference (note), a
claim link to a missing reference (raises), a missing `bib_sources` row (raises); **table**: 1, 7, 8, 13 and 20 columns
(group counts 1, 1, 2, 2, 3, widths and `\addtocounter` count), 0 columns, a cell at exactly 400 and at 401 characters, a
source text at 200 and 201, a heading at 400 and 401, a value that crosses 400 only through the "not verified"
parenthetical, a long option label, a long source title, the same long source repeated across groups (one note number),
a row without `ref_number` (`row r` in the list), first cells starting with `[` and `*`, math in cells (valid subset and
`$\begin{array}{c}x\\[1000pt]y\end{array}$`, `$1pt$`, `$\Huge x$`, a `$$x$$` cell), the Table I placement variants
(after the first `TABLE_I` paragraph, at the start of IV, no IV, absent); an en and a tr kitchen-sink view that combines
most of the above so one failure shows an ordering or blank-line change. Plus a **hostile** view (below).

Invariant tests over every **normal** case (not only goldens), each written with its own small helper, not with the production
scanner: no sentinel internal id (`psg_SENTINEL`, `cel_SENTINEL`, the sentinel `claim_key` and `support_type` values of claims,
link and claim row ids, in plain and in escaped form such as `psg\_SENTINEL`; the field names `claim_key`/`support_type`)
in `tex` or `bib`, with the one exception that the `claim_key` value of a **skipped rule** item (a separate sentinel the
test knows) appears in the edit note exactly where Markdown writes it; the first-appearance order of unique cite keys equals the `references` order (mapped to keys); every cite key
is in the `.bib` and every `.bib` key is cited; every `\eqref` label is defined and labels are unique; `\begin`/`\end`
environments balance with a small tokenizer of the test's own; no `itemize` is empty (every `\begin{itemize}` is followed
by an `\item` line before its `\end`); the header comment lines all start with `%` and the first non-comment line is
`\documentclass[journal]{IEEEtran}`; `to_latex` does not mutate the view and is deterministic; the file contains exactly one
`\begin{document}`, one `\end{document}` and one `\bibliography` line.

**Hostile view test:** every stored field the writer reads holds a payload (title, claim text plain and inside `$`/`$$`,
`draft.text`, section ids, rule names in the run error, cell values, option labels, column names, source keys and titles,
missing-row names and reasons, edit-check dates, items, rules, details, review reasons, findings, unread section ids, and
every `bib_sources` field including `year`, `doi`, `landing_url`, `arxiv_id`, and the type-guarded numbers, which get
their own expected-error cases) built from `\input{evil}`, `\def\x{y}`,
`\begin {document}`, `\begin{\n document}`, `\write18{x}`, `\csname x\endcsname`, `\catcode`, `\immediate`, `^^M`, `%`,
`#`, braces, a newline then `\input{evil}` in a source key, and `}` `\n@article{evil,` in titles. After conversion: no
output control word `\input`, `\def`, `\write`, `\csname`, `\catcode`, `\immediate`, `\openout` outside the form
`\textbackslash{}name` (checked with a tokenizer that treats `\textbackslash{}` as a produced sequence); `\begin{document}`
and `\end{document}` occur exactly once each; the `.bib` has exactly one `@` entry start per reference and balanced
braces; no stored value ends a comment line (the header holds only `%` lines); the `ref<n>` fallback is used for the
hostile key. A **valid** `$$\begin {aligned}x&=y\end {aligned}$$` stays valid in a claim (positive test).

Other tests: the import lines of `latex.py` (decision 1, AST); a test that every template word written by the four PIECEWISE
functions (`missing_row_fields`, `edit_note`, `review_note`, `finding_fields`) and by `source_cell`/`cell_text` is
TeX-neutral (call each branch with an `esc` that returns the plain token `X` and assert the result holds none of
`\ { } $ & # ^ _ % ~ "` and no `is_unmapped` character); `table_caption` prefixes; thresholds at the boundaries; `render`
labels only through `label_for`; the 0/1/7/8/13/20 group invariants (count of `longtable` = max(1, ceil(N/7)), `\addtocounter{table}{-1}`
count = groups - 1, every data column once, the source column and every row in every group, `\onecolumn` and `\twocolumn`
once, every `\endlastfoot` followed by the rows when `len(rows) > 0`; with zero rows the group still has its caption,
header, `\endlastfoot` and `\end{longtable}`, no data line, and the same group count); long-value invariants (every moved full text appears in the list, numbering
follows the table reading order, the note count equals the list length).

Also required as separate case ids: a table with zero rows; a body of 999 and of 1,000 distinct `equation_ref` values (the
1,000th has no label and counts in the no-target note); a claim with display math and no `equation_ref`; a repeated E
environment; a table with every cell value above 400 characters; a claim with two displays in a row, one ending with a display
plus `\cite`, and one starting with a display (exact outputs, decision 5).

`tests/test_bibliography.py` (new tests, existing untouched): (a) **before editing `bibliography.py`**, save
`git show HEAD:backend/deixis/workflow/bibliography.py > /tmp/x3-bibliography-orig.py`, write a full literal for a
multi-source `to_bibtex` output (all entry types, repeated keys with suffixes, a `None` year, `volume/issue/pages`,
`arxiv_id`, special characters, an author containing "and", an empty `venue`) and run it green against the unmodified file;
also dump `/tmp/x3-bib-before.json` mapping the outputs of `to_bibtex(sources)` for 300 source lists from
`random.Random(20261002)` (list sizes 0 to 6; field values drawn from pools that include empty strings, `None`, TeX
specials, braces, quotes, non-ASCII text, an author containing "and", and a series of 30 sources with the same author, year
and title word so the suffix path beyond `z` runs) and compare with `/tmp/x3-bib-after.json` after the change (`cmp`, the
same generator file kept under `/tmp`); the empty list is one of the cases; **plus one separate deterministic list of 40 sources with the same author, year and
title word** (the 300 short lists cannot reach the suffix branch beyond `z`), compared before and after in the same dump; (b) `keys` length and uniqueness errors (case-insensitive) and the
character rule; (c) `keys` replace `_keys` and only the keys change; (d) `latex_report=True`: double-braced title, the
symbol table without double escaping (`a ≥ b & c` gives `{{a \ensuremath{\geq} b \& c}}`), `url`/`doi`/`eprint` with a
backslash or a control character omitted with the exact note, an unmapped character counted in a passed `Unmapped`, no
note list when called through `to_bibtex`.

## Checks to run (in the worktree)

1. `PYTHONPATH=backend:. uv run pytest tests/test_report_latex.py tests/test_bibliography.py -q`.
2. Unchanged files must still pass: `PYTHONPATH=backend:. uv run pytest tests/test_report_export.py tests/test_report_export_pin.py
   tests/test_report_failure_display.py tests/test_report_failed_rows.py tests/test_report_api.py tests/test_p6_measure_report.py
   tests/test_report_latex_text.py tests/test_report_latex_math.py -q`; the orchestrator runs the full pytest and the hand
   compile of the golden files.
3. The `cmp` of `/tmp/x3-bib-before.json` and `/tmp/x3-bib-after.json` (byte-identical).
4. `git diff --check`; `git status --short` shows only the allowed files (plus this prompt file, which is the
   orchestrator's).

## Report at the end

Files created and changed; the public surface as shipped (names, signatures, constants); the case ids and the golden file
count; the pytest summaries of checks 1 and 2; the `cmp` result; every own judgement kept or changed; whether `export_text.py`
had to change (and why); the length of `latex.py`; anything you could not find or make pass, and anything in the note that
looks wrong or contradictory (for example the 0.6in source column against real D59 keys; do not change it without
evidence, the orchestrator measures it by compiling).
