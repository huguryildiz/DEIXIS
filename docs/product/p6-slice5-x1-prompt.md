<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1 2 high (esc argument required vs WHOLE contract; tracer "no fixed word wrapped" vs real _md calls on fixed strings), 4 medium/low folded in; r2 0 high (2 medium/low: raw-return test vs draft_line underscore mapping, gate cases with run None) folded in -->
<!-- CODE-REVIEW-ROUNDS: gpt-6.1-sol high, 1 round: 0 high, 0 medium, 0 low; verdict hazir -->

# Task: P6 slice 5, batch X1, pin the Markdown export byte for byte, then extract the shared bilingual text (no behavior change, no model)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-x1` (detached at `887f592`, which is `origin/main`
with slice 4 E1 (D148) and E2 (D150) and slice 5 X2 (D151) on top). Read `AGENTS.md`, `CLAUDE.md`,
`docs/product/p6-slice5-latex-export.md` (the whole note; this batch is its section 11 "X1"; decisions Q2, Q16, Q18, Q22
bind it) and D151, D150, D148, D149, D120 in `docs/decisions.md`. Where this prompt differs from the note, this prompt
wins and says so. It differs in two places, both to keep today's bytes: the note's section 11 says Markdown applies `_md`
to the missing-rows sentence and that `review_note` escapes the reason; in the code the missing-rows counts sentence is
not escaped at all (only the per-source name and reason are), and the `not_reviewed` reason is a fixed lookup written
raw. The code is the reference.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find or could not make pass. No real-model call, no network, no
provider call. Do not touch `../DEIXIS`, `../DEIXIS-k*`, `../DEIXIS-e*`, `../DEIXIS-s4*`, `.local/`, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, `sw-status.md`, ports 8765 and 8858-8864. Tests run with
`PYTHONPATH=backend:. uv run pytest ...` (`UV_CACHE_DIR=/tmp/deixis-uv-cache` if uv cannot write its cache).

This batch changes **no output byte**. It has two parts, in this order, and the order is the point: (1) golden tests
that pin what `to_markdown` and `export_markdown` write today, written and run green against the **unmodified**
`export.py`; (2) a pure refactor that moves the shared bilingual text into a new module so that the later LaTeX writer
(X3) says the same sentences. If part 2 changes one byte of any pinned output, part 2 is wrong, not the pin.

## What is and is not in code (checked on 887f592)

- `backend/deixis/workflow/report/export.py` (387 lines) holds everything: `MEDIA_TYPES` (one entry, `markdown`),
  `HEADINGS`, `REVIEW_CODES`, `REVIEW_REASONS` (constants, each value an `(English, Turkish)` pair), `_md` (Markdown
  prose escape), `_label`, `_value_text`, `_table(table, tr)` (caption, header, rows; contains the nested pipe and
  dollar handling `table_cell`), `_review_note(view, tr)`, `_edit_note(view, tr)` (slice 4 E1: three-state "edited by
  hand" sentence, items, skipped rules, not-checked list), `to_markdown(view, *, title, corpus)` and
  `export_markdown(store, research_id, report_id) -> (text, filename)`. Slice 4 E2 added the `removed_claims` anchor
  sentences inside `to_markdown`. `to_markdown` mixes three kinds of text: fixed bilingual sentences, sentences with
  numbers, and stored values (claim text, titles, rule names, dates) escaped with `_md`.
- `export_markdown` reads `report_view`, refuses an unfinished report (`RevisionConflict("The report is still being
  written")` when `view["status"] == "in_progress"` or the run is not completed, failed or cancelled), reads
  `store.research(...)["title"]`, reads `ReportStore(store).snapshot(report_id)["corpus"]` (`NotFound` gives `None`)
  and builds the file name `report-<slug>-<draft|vN>.md` (NFKD to ASCII, lower case, non-alphanumerics to `-`, at most
  60 characters, `report` when empty).
- `api/app.py` calls `report_export.export_markdown` and `report_export.MEDIA_TYPES[fmt]`; `fmt` is
  `Literal["markdown"]`. **This batch does not touch `app.py`.**
- Importers of `export.py`: `app.py` (module import), `tests/test_report_export.py` (`_md`, `_table`, `to_markdown`,
  `export_markdown`), `tests/test_report_failure_display.py` and `tests/test_report_failed_rows.py` (`to_markdown`).
  Nothing outside `export.py` imports `_label`, `_value_text`, `_edit_note`, `_review_note`, `HEADINGS`,
  `REVIEW_CODES` or `REVIEW_REASONS` (checked by grep); the note nevertheless requires `export.py` to keep exposing
  `HEADINGS`, `REVIEW_CODES` and `REVIEW_REASONS` under the same names.
- `tests/test_report_export.py` (494 lines) already asserts many substrings and holds two exact literals
  (`E2_BASE_EXPORTS`, `E2_ZERO_LINK_EXPORTS`, captured on `def7c26`) for a real two-section report. There is no
  whole-output pin of hand-built views, and no pin of the file name or the unfinished-report gate beyond one route test.
- Not in code: `report/export_text.py`, `tests/test_report_export_pin.py`, `report/latex.py`, any LaTeX writer, any
  `format=latex` route. X2's `latex_text.py`, `latex_math.py`, `latex_preamble.py` exist but nothing calls them and
  `export.py` does not import them. `contracts.py`, the migrations, `methods/` and the contract schemas are not touched.
- Other worktrees: `../DEIXIS-k4` (slice 3) has an uncommitted change in `workflow/views.py`; it is not ours and
  `views.py` is not in our allowed list. `report_view`'s output shape is therefore taken as it is on `887f592`.

## Decisions taken (the note's own default where it has one; own judgement is marked)

1. **Pins first, against unmodified code.** Create `tests/test_report_export_pin.py` and make it pass before any edit to
   `export.py`. Expected outputs are literal strings in the test file (no fixture directory; the note's allowed files
   do not include one). Produce each literal by running the current `to_markdown` on a hand-built view, **read the output
   against the sentence the code means to write** (not only paste it), then store it. Also save, outside the repo, the
   original source (`git show HEAD:backend/deixis/workflow/report/export.py > /tmp/x1-export-orig.py`) and a JSON dump
   `/tmp/x1-pin-before.json` mapping every `case/language` id to its output string and the file-name checks, written
   **before** step 2 of the refactor; the orchestrator compares against it. Record in your report the pytest summary of
   the pin file run against the unmodified source.
2. **Pin matrix (note section 11 X1 plus Q18 and Q22).** Hand-built `view` dicts, every case in **both** languages
   (`"language": "en"` and `"tr"`; use `"tr-TR"` in at least one case to pin the `startswith("tr")` rule). Required
   cases, each one a separate parametrised test id so a failure names the case:
   - Q18 (1) **draft with all sections valid and the assembly refused**: `run.error` a list mixing repeated known rules,
     four or more distinct known rules (the "and N more" wording; only the first three are named, so across the cases every one
     of the six known rule names appears among the first three, and an unknown rule name (underscores become spaces)
     appears both among the first three and beyond the third), a
     `*_warning` rule whose detail starts with `WARNING:` (filtered out), a non-dict entry; also: error absent, empty
     list, not a list (all give the plain "DRAFT: 0 sections not validated." wording); and draft with some sections not
     `valid` (count wording, section "must be written again" note for `draft` and `failed` sections).
   - Q18 (2) **missing rows**: counts sentence, the excluded-from-denominators sentence, per-source reasons with a
     `source_key`, with `source_key` `None` falling back to the title, reason `no_stored_text`, another reason with
     underscores.
   - Q18 (3) **insufficient evidence and empty sections**: several `insufficient_evidence` reasons (one starting with
     `- ` to pin the escape), an empty section with no reasons ("No text was written"), an empty II or VIII whose draft
     has `text` (no "No text" line), section VI preface.
   - Q18 (4) **review**: no review; `not_reviewed` with each of the six `REVIEW_REASONS` keys, an unknown reason and a
     missing reason; `reviewed` with 0, 1 and 2 findings (singular/plural of "problem"), 0, 1 and 2 reverted sentences
     (singular/plural wording), no unread sections and two unread sections (names through the heading table, one with an
     unknown `section_id`), findings with a known section, `section_id` `None` ("Report"), a known and an unknown code
     ("Other"), stored finding text needing Markdown escape; the base-version suffix ("covers the model's base
     version") present for `reviewed` and absent otherwise.
   - Q18 (5) **II and VIII text and identity**: `draft.text` written with and without claims, in the order the code
     writes it; draft identity line "Evidence report · draft" and valid "· V<n>" with a two-digit version.
   - Q22 (sixth group, slice 4) **edit wording**: `has_human_edits` true with `edited_after_version` `None` and `1`,
     crossed with `edit_check` absent / `current` / historical (`current` false); items with a stored detail needing
     escape; `skipped_rules`; `not_checked` containing the three known values and one unknown value; an `edit_check` that exists with
     `items`, `skipped_rules` and `not_checked` all empty (the blank lines and the "Not checked:" heading are still
     written); the
     `has_human_edits` fallback when the key is absent (`edited_after_version is not None`) and the explicit `False`;
     the edited-after-draft case (draft status with edits); **a claim with zero effective links**: claims whose
     `evidence_basis == "none"` and `support_type_note` is not `None`, once with other links still located (only the
     "N claims have no direct citations" suffix) and once with no links at all (the "No citation anchors remain"
     sentence plus the suffix); the evidence-changed sentence (`evidence_changes.any`).
   - Anchors and footer: all located; some unlocated (`anchor_match` `None`); zero links and no removed claims;
     `corpus` `None` ("Generated by DEIXIS.") and a real corpus dict with five counts.
   - Table: `table_i` placed after the first paragraph that holds a `table_ref == "TABLE_I"` claim; placed at the start
     of IV when no claim refers to it; absent; one column vs several (the singular caption wording in both languages);
     cell states `value` (text with `|` and a newline, number with unit, number without unit, yes and no, `option_ids`
     with a known and an unknown id, an empty value), `not_verified` (with and without a value), another state such as
     `not_found`, a missing cell (`—`); a source with `source_key`, with only `title`, with neither, with and without
     `ref_number`; a column name with `|`; math with `|`, `\|` and `\\` inside a cell and in a column name (the existing
     `test_table_pipes_in_math_and_column_names_stay_inside_cells` pins parts of this; pin the whole table).
   - Body: sections given out of `DISPLAY_ORDER` plus an unknown `section_id` (heading fallback is the id itself in
     both languages); paragraph grouping by first appearance; equation numbering by first appearance of `equation_ref` in claim order (the numbers are assigned from the claim list
     before paragraphs are grouped: use paragraphs 1, 2, 1 with refs A, B, A, and a second section reusing ref B, so claim
     scan order and printed order differ);
     `[n]` markers with repeated links in one claim; claims with stored text needing every `_md` rule (the start-of-text escape looks only at the start of one claim's
     text, so use **one separate claim per leading form**: `#`, `-`, `+`, `*`, `1.`, `2)`; plus claims with `\`, `[`, `]`,
     `<`, `>`, `|`, a backtick, a matched `$...$` and `$$...$$` span with `<`, `>`, `[`, `]` inside, an unmatched `$`); a title needing escape; references with authors, venue, year, DOI,
     `version_label` and with none of them; no references.
   - Two **kitchen-sink** cases, one per language, that combine as many of the above as fit in a single view, so one
     failure shows an ordering or blank-line change that the small cases cannot.
   - `export_markdown` through the public entry (real store, the `complete(tmp_path)` helper or the
     `test_draft_gating_and_unknown_ids` setup in `tests/test_report_export.py`): the file name for a valid report
     (`-v1.md`), a draft (`-draft.md`), a non-ASCII title (accents, Turkish letters), an all-symbol title (falls back to
     `report`), a title longer than 60 characters that would end in `-` after the cut; the 409 for `in_progress` and for
     a run that is `paused` or `running`; 200 for run `failed`, `cancelled` and `completed`, and for a finished report whose
     view has `run` `None` (hand-built view through `to_markdown`; the gate itself is only reachable through the store); `NotFound` snapshot gives the
     "Generated by DEIXIS." footer (corpus `None`). Change the title with a direct SQL update on the research row (find
     the table name in `storage/migrations`; this is a test-only write to a temporary database).
   Own judgement: a case that cannot be built from a hand-built view without a store (the last group) uses the store
   helpers already in `tests/test_report_export.py`; import them, do not copy them.
3. **`export_text.py` is text only and format-neutral.** New module `backend/deixis/workflow/report/export_text.py`.
   Allowed imports: `__future__`, `dataclasses`, `re`, `unicodedata`, `typing`, `collections.abc`,
   `deixis.domain.rules` (`RevisionConflict`), `deixis.workflow.report.review_methodology` (`failed_reason_text`). It
   must **not** import or define `_md`, `escape_prose`, `escape_text` or anything from `export.py`, `latex_text.py`,
   `latex_math.py`, `latex_preamble.py`; it must not contain a Markdown or LaTeX escape of its own. A function that
   is **PIECEWISE** (decision 4) takes a required `esc: Callable[[Any], str]` argument and calls it where `export.py`
   called `_md` today; the Markdown writer passes `_md`. A **WHOLE** function takes no `esc`: it returns raw text and the
   caller escapes the whole. Do not add an escape inside a WHOLE function or inside a function that has none today.
4. **Escape contract per function (the note's Q2 requirement; each docstring states its class in one line).** Three
   text classes and one helper class, no function belongs to two:
   - **PLAIN**: contains no stored text (only fixed words, integers, counts); returned unescaped; the caller writes it
     as it did before (Markdown does not escape it today and still does not).
   - **WHOLE**: a complete sentence or label that may contain stored text; returned **unescaped**; the caller applies
     its escape to the whole string, exactly as `to_markdown` applies `_md(...)` to the whole today.
   - **PIECEWISE**: the function calls `esc` itself, once for each place where `export.py` calls `_md` today (stored
     values, and also the fixed or table-derived strings that `_md` receives today: the three known `limits` sentences,
     the "Source record unavailable" label, a value's yes/no or option label, known section headings and code labels, the
     "Report" fallback); the result is final and the caller must not escape it again. The outer template words around
     those pieces stay unescaped, and a string that `export.py` does not pass to `_md` today is **not** passed to `esc`
     (for example the fixed `not_reviewed` reason, which is looked up in `REVIEW_REASONS` and written raw). This is how
     `_review_note` and `_edit_note` behave today; a whole-string `_md` on them would change bytes (a Turkish
     "1. sürümden sonra ..." sentence would gain a backslash).
   - **helper**: not text for a format (`is_turkish`, `pick`, `ensure_report_finished`, `report_stem`); `report_stem`
     takes the stored title and returns the file stem, with today's slug rules; none of them escapes.
   Required surface (names are the contract X3 will use; own judgement on exact parameter names if the class and
   behavior stay as listed; do not add functions beyond this list except private helpers):

   | Function | Class | Returns |
   |---|---|---|
   | `HEADINGS`, `REVIEW_CODES`, `REVIEW_REASONS` | constants | moved here unchanged; `export.py` imports and re-exposes the same three names |
   | `is_turkish(view) -> bool` | helper | `str(view.get("language", "")).startswith("tr")` |
   | `pick(english, tr, turkish) -> str` | helper | the old `_label` |
   | `heading(section_id, tr) -> str` | WHOLE | `HEADINGS.get(sid, (sid, sid))[int(tr)]` |
   | `references_heading(tr)` | PLAIN | "References" / "Kaynaklar" |
   | `report_identity(view, tr)` | PLAIN | "Evidence report · draft" / "· V<n>" and the Turkish pair |
   | `draft_line(view, tr) -> str or None` | WHOLE | the whole "DRAFT: ..." sentence including the up-to-three stored rule names and "and N more"; `None` when `view["status"] != "draft"` |
   | `section_unvalidated_note(tr)` | PLAIN | "This section was not validated and must be written again." |
   | `vi_preface(tr)` | PLAIN | the section VI candidate-aspects sentence |
   | `missing_rows_sentence(missing, tr)` | PLAIN | the counts sentence plus the denominators sentence (numbers only; `export.py` does not escape it today) |
   | `missing_row_fields(row, tr, esc) -> (source, reason)` | PIECEWISE | `esc(row["source_key"] or row["title"])` and `esc(failed_reason_text(...))` |
   | `edit_note(view, tr, esc)` | PIECEWISE | `None` when there are no human edits; otherwise an object (frozen dataclass or tuple, own judgement) carrying: the paragraph text (only `check["created_at"]` goes through `esc`), and, when `edit_check` exists, the item tuples `(section_id, rule, severity, detail)`, the "Not checked:" heading text, the skipped tuples `(section_id, claim_key, rule, reason)` and the not-checked limit strings, every stored field through `esc`, the limit strings through `esc` as a whole (as today) |
   | `evidence_changed_sentence(tr)` | PLAIN | the "Evidence changed after this report was written ..." sentence |
   | `no_text_sentence(tr)`, `not_enough_evidence_label(tr)` | PLAIN | the two fixed strings |
   | `table_caption(table, tr)` | PLAIN | the "TABLE I. ..." / "TABLO I. ..." caption incl. singular column wording |
   | `source_heading(tr)` | WHOLE | "Source" / "Kaynak" (the caller keeps today's `_md` then `table_cell` chain) |
   | `value_text(value, options, tr)` | WHOLE | the old `_value_text` (raw text; caller escapes the whole) |
   | `source_cell(row, tr, esc)` | PIECEWISE | `[n] ` prefix plus `esc(source_key or title or the fixed unavailable label)` |
   | `cell_text(cell, column, tr, esc)` | PIECEWISE | `—` for a missing cell; `esc(value_text)` for `value`; `esc(value_text)` plus the fixed "(not verified: no quote linked)" parenthesis for `not_verified`; `esc(state.replace("_", " "))` otherwise |
   | `corpus_footer(corpus, tr)` | PLAIN | "Generated by DEIXIS." or the five-count footer |
   | `anchor_note(view, tr)` | PLAIN | the located-anchors sentence including the E2 removed-claims sentences (it reads the links and claims from `view`) |
   | `review_note(view, tr, esc)` | PIECEWISE | the old `_review_note` plus the base-version suffix for `reviewed`; section names through `esc` one by one |
   | `findings_heading(tr)` | PLAIN | "Model findings" / "Model bulguları" |
   | `finding_fields(finding, tr, esc) -> (section, code, text)` | PIECEWISE | each of the three through `esc`; the "Report" fallback for no section |
   | `ensure_report_finished(view)` | helper | raises `RevisionConflict("The report is still being written")` under exactly today's condition |
   | `report_stem(view, title) -> str` | helper | `report-<slug>-<draft|vN>` without extension (same slug rules as today) |

   The Markdown-only structure stays in `export.py` and is not moved: `_md`, the `# `, `## `, `> ` and `- ` prefixes, the
   ` · ` joins in findings and edit items, the pipe table and `table_cell` (pipe and dollar escaping inside cells), the
   reference line format (`[n] authors, title, venue, year, DOI: ..., (version)`), blank-line placement, the final
   newline rule, `export_markdown`'s store reads, `MEDIA_TYPES`.
5. **`export.py` keeps its names and behavior.** `_md`, `_table(table, tr)`, `to_markdown(view, *, title, corpus)`,
   `export_markdown(store, research_id, report_id)`, `MEDIA_TYPES`, `HEADINGS` (and `REVIEW_CODES`, `REVIEW_REASONS`)
   stay importable from `deixis.workflow.report.export` with unchanged signatures. `_label`, `_value_text`,
   `_review_note`, `_edit_note` may be removed (nothing imports them). `to_markdown` and `_table` call `export_text`
   functions and apply `_md` or `table_cell` exactly where they did before; the order of `lines.extend` calls does not
   change. No new behavior, no new warning text, no wording fix: if you find a wording problem, report it, do not fix it.
6. **Why this class split, in one place (for the docstring of the module).** The old `_review_note` and `_edit_note`
   escaped stored parts inside the sentence; the old `to_markdown` escaped whole sentences that may carry stored rule
   names; both behaviors must survive byte for byte, and the LaTeX writer needs the same words with a different escape.
   Passing a callback keeps one copy of the words and lets each format escape its own way.
7. **Contract tests for `export_text.py` go in `tests/test_report_export.py`** (additions only; no existing test is
   edited or removed): (a) an AST test: the module imports only the allowed names of decision 3 and defines or imports no
   name `_md`, `escape_prose`, `escape_text` (this checks imports and names only; that no function writes its own
   escape under another name is checked by your reading of the module and by (b) and (c)); (b) a **call-log test** for
   every PIECEWISE function: pass an `esc` that records its arguments and returns them wrapped in `<<...>>`, feed a view
   whose stored strings are unique markers, and assert the **exact list of `esc` arguments in call order** for each
   branch (this is the check that every old `_md` call is still one `esc` call and that no new one was added, for
   example no `esc` on the `not_reviewed` reason and on the missing-rows counts sentence), and that the returned text
   equals the expected string with the wrapped pieces; (c) a **no-escape test** for the WHOLE functions and a **literal test** for the PLAIN ones: "returned raw" means
   "no escape is applied", not "the input is copied": `draft_line` still turns underscores in an unknown rule name into
   spaces (today's behavior, not an escape), `heading` falls back to the stored id, `value_text` joins number and unit and
   maps option ids to labels. For each WHOLE function feed stored strings containing `\ [ ] < > ` | $ # _ %` and a
   leading `1.` in the fields it reads and compare the **complete return value** against a literal computed by hand from
   today's naming and formatting rules (for example `SYNTHETIC_1.[x]` becomes `SYNTHETIC 1.[x]` inside `draft_line`);
   assert no backslash or other character was added. For each PLAIN function compare the complete return value for both
   languages with a literal, covering each number branch (singular/plural, zero, the removed-claims branches of
   `anchor_note`, `corpus` `None` and a dict); PLAIN functions accept no stored text, so no special characters are
   fed to them; (d) `report_stem` unit cases mirroring the pinned `export_markdown` file names, and
   `ensure_report_finished` cases: a finished report accepts (`status` valid or draft; run completed, failed,
   cancelled, and `run` `None`), and rejects with the same `RevisionConflict` message for `in_progress` (also with
   `run` `None`) and for a run that is not completed, failed or cancelled.
   The pin file, not these tests, guards the Markdown bytes; do not duplicate pin literals in `test_report_export.py`.
   The edit note when `edit_check` is `None` still yields only the paragraph and one blank line in Markdown (pinned).

## Files allowed

- `backend/deixis/workflow/report/export.py`
- `backend/deixis/workflow/report/export_text.py` (new)
- `tests/test_report_export.py` (additions only)
- `tests/test_report_export_pin.py` (new)
- `docs/decisions.md` is **not** yours; the orchestrator writes the decision entry.

## Files NOT allowed

Everything else, in particular `backend/deixis/api/app.py`, `workflow/views.py`, `workflow/report/assembly.py`,
`workflow/report/store.py`, `workflow/bibliography.py`, `domain/contracts.py`, `latex_*.py`, `storage/migrations/`,
`methods/`, `contracts/`, `apps/web/`, `scripts/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, every other test file,
every other worktree. If a change outside the allowed list seems needed, stop and report it.

## Tests to add

- `tests/test_report_export_pin.py` as in decision 2: the whole pin matrix, every case in both languages, one pytest id per
  `case-language`, all literal outputs inline, no TeX, no network, no model. Add a small module-level
  `CASES` mapping (id to a function building the view, title, corpus) and an `EXPECTED` mapping so the orchestrator can
  render the same cases with `/tmp/x1-export-orig.py` and with the refactored module and compare.
- Additions to `tests/test_report_export.py` as in decision 7.
- Hand-built views are SYNTHETIC; label the titles and texts that way as the existing tests do.

## Checks to run (in the worktree)

1. Before any edit to `export.py`: `PYTHONPATH=backend:. uv run pytest tests/test_report_export_pin.py -q` is green;
   write `/tmp/x1-pin-before.json`; report the summary line.
2. After the refactor: `PYTHONPATH=backend:. uv run pytest tests/test_report_export.py tests/test_report_export_pin.py tests/test_report_failure_display.py tests/test_report_failed_rows.py tests/test_report_api.py tests/test_p6_measure_report.py tests/test_report_edit_check.py tests/test_report_claim_links.py -q`.
3. Re-render every pin case with the refactored `export.py` and compare with `/tmp/x1-pin-before.json` (write
   `/tmp/x1-pin-after.json` and `cmp` them); they must be byte-identical.
4. `git diff --check`; `git status --short` shows only the allowed files (plus `docs/product/p6-slice5-x1-prompt.md`,
   which is the orchestrator's). The orchestrator runs the full pytest.

## Report at the end

Files created and changed; the public surface of `export_text.py` as shipped (names, signatures, class of each); the
pin matrix as shipped (case ids per group, the count of pin tests); the pytest summary of the pin file against the
unmodified source (before) and of every check after; the `cmp` result of the before/after JSON; every own judgement kept
or changed; anything you could not find or make pass, and any wording or behavior in `export.py` that looks wrong (not
fixed, only reported).
