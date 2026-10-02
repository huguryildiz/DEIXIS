<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1 0 high, 4 medium (PDF expectation of title/bbl, Q19 long-text cases tied to final text and source_key None, golden list pinned with the 16 Overfull files excluded, zip bytes asserted against bundle encodings) and 3 low folded in -->
<!-- CODE-REVIEW-ROUNDS: gpt-6.1-sol high, r1 0 high, 1 medium (PDF-wide search could be satisfied by the bibliography copy; note numbers unchecked) folded in; r2 0 high, 1 medium (note number 1 accepted as 11) folded in by Sol; no r3 (Codex usage limit), the last fix verified by tests and the orchestrator's reading -->

# Task: P6 slice 5, batch X4, `export_latex`, the `format=latex` route, the zip of `.tex` and `.bib`, and the optional compile test (no model, no network, TeX only in the optional test)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-x4` (detached at `2b77b85`, which is `origin/main`
with slice 5 X1 (D153), X2 (D151) and X3 (D155) on top). Read `AGENTS.md`, `CLAUDE.md`,
`docs/product/p6-slice5-latex-export.md` (the whole note; this batch is its section 11 "X4"; sections 7 and 9 and decisions
Q9, Q13, Q15, Q19, Q20 bind it) and D155, D153, D151, D149 and D120 at the top of `docs/decisions.md`. Read also
`docs/product/p6-slice5-x3-prompt.md` (same style, and its decision 1 for the `to_latex` surface). Where this prompt differs
from the note, this prompt wins and says so.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find or could not make pass. No real-model call, no network, no
provider call. Do not touch `../DEIXIS`, `../DEIXIS-k*`, `../DEIXIS-e*`, `../DEIXIS-s4*`, `.local/`, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `sw-status.md`, the live data directory, ports 8765 and 8858-8864. Tests run with
`PYTHONPATH=backend:. uv run pytest ...` (`UV_CACHE_DIR=/tmp/deixis-uv-cache` if uv cannot write its cache). The sandbox you
run in may not be able to execute `xelatex`; if `xelatex` fails to start or cannot write its caches, say so in your report
and do not weaken a check to get around it. The orchestrator runs the compile test outside the sandbox and sends you the
failures. Do not edit `docs/decisions.md`; the orchestrator writes the decision record.

## What is and is not in code (checked on 2b77b85)

- Not in code: any `format=latex` route, any zip writer, any `X-Deixis-Export-Notes` header, `tests/test_report_latex_export.py`,
  `tests/test_report_latex_compile.py`, any reader that builds `bib_sources` from `source_versions` and
  `identifier_mappings`. Nothing outside the tests calls `latex.to_latex`.
- Present (X3, D155), read-only here: `workflow/report/latex.py` with `to_latex(view, *, title, corpus, bib_sources) ->
  LatexBundle(stem, tex, bib, notes)` (`note_count` is `len(notes)`; `stem = export_text.report_stem(view, title)`). It is
  pure; `tests/test_report_latex.py::test_import_boundary` fails when `latex.py` imports anything outside a fixed list (no
  `zipfile`, no database or `Store` code, no `views.py`). It raises `RevisionConflict` for a claim citation that does not
  resolve to one reference, a reference with no `bib_sources` row, a duplicate row, a cite-key collision, a non-int counter and
  an invalid stem. `bib_sources` is one dict per source version holding `source_version_id` and the keys `title, authors,
  year, venue, publication_type, doi, landing_url, version_label, arxiv_id` (all required) and optional `volume, issue,
  pages`. `tests/fixtures/report_latex/` holds 188 golden `.tex`/`.bib` pairs and `tests/report_latex_cases.py` the SYNTHETIC
  builders (`build`, `claim`, `section`, `table`, `bibrow`, `BASES`); both are read-only here.
- Present: `workflow/report/export.py::export_markdown(store, research_id, report_id) -> (text, filename)` (calls
  `report_view`, `export_text.ensure_report_finished` for the 409 "The report is still being written", reads the research
  title and `ReportStore(store).snapshot(report_id)["corpus"]` with `NotFound` meaning `corpus=None`), and the route
  `GET /api/researches/{id}/reports/{report_id}/export` in `api/app.py` (`fmt: Literal["markdown"] = Query("markdown",
  alias="format")`, `Response(text, media_type=report_export.MEDIA_TYPES[fmt], Content-Disposition)`). `NotFound` is mapped to
  404 and `RevisionConflict` to 409 (`{"detail": <message>}`) by exception handlers in `app.py`. `export.py` is **not**
  changed by this batch and its bytes stay pinned by `tests/test_report_export_pin.py`.
- Present: `queue._snapshot(conn)` (`workflow/queue.py:80`, one read transaction, a context manager that yields without
  `BEGIN` when a transaction is already open; `audit.py` calls it as `queue._snapshot(store.conn)`). The note (section 7)
  names it as the single read moment.
- `report_view` gives `references` with `number, source_version_id, source_key, title, authors, year, venue, doi,
  version_label` and **silently skips** a reference whose `source_versions` row is missing (`views.py`, `if source is None:
  continue`). A claim link to such a version then resolves to no reference and `to_latex` raises `RevisionConflict`. That is
  the missing-source 409; no extra check is needed, but a test must pin it.
- The fields `publication_type`, `volume`, `issue`, `pages`, `landing_url`, `arxiv_id` are not in `references`. They come
  from `source_versions` (columns `title, authors_json, year, venue, version_label, publication_type, doi, landing_url,
  volume, issue, pages`) and from `identifier_mappings` (`scheme = 'arxiv'`, column `value`; the Zotero export reads it with
  `SELECT value ... WHERE source_version_id = ? AND scheme = 'arxiv' LIMIT 1` in `bibliography.export_sources`).
- This machine has TeX Live 2021 at `/Library/TeX/texbin` (xelatex, bibtex, latexmk, kpsewhich; `pdftotext` is in
  `/opt/homebrew/bin`). X3's hand compile of the goldens is the only TeX measurement so far; no test needs TeX yet.

## Decisions taken (the note's own default where it has one; own judgement is marked)

1. **Where `export_latex` lives (own judgement; the note's file list says `latex.py`).** A new module
   `backend/deixis/workflow/report/latex_export.py`. `latex.py` stays pure and unchanged: adding `zipfile`, `Store` and
   `views` imports to it would break D155's import-boundary test, and that test is not in this batch's file list. The new
   module is listed in the decision record as a deviation from the note. It exports `MEDIA_TYPE = "application/zip"`,
   `read_bib_sources(store, view) -> list[dict]`, `build_zip(bundle) -> bytes` and
   `export_latex(store, research_id, report_id) -> tuple[bytes, str, int]` (zip bytes, filename, note count). Imports of
   `views`, `queue` and `ReportStore` are lazy inside functions where a cycle would otherwise arise, as `export_markdown`
   does for `views`; say in your report which ones you made lazy.
2. **One read moment (Q20).** `export_latex` runs these reads inside one `with queue._snapshot(store.conn):`: `report_view`,
   `export_text.ensure_report_finished`, the research title, the corpus snapshot (`NotFound` means `None`, as in
   Markdown) and `read_bib_sources`. `to_latex` and the zip are built after the block from values already read; they touch
   no database. Nothing is written. The order of the reads inside is the Markdown order (view first, so an unknown report
   or a report of another research is a 404 before anything else, and the 409 for an unfinished report comes before
   the title is read).
3. **`read_bib_sources(store, view)`.** One dict per entry of `view["references"]`, in that order, with exactly the keys
   `to_latex` needs: `source_version_id`, `title`, `authors` (decoded from `authors_json`, a list), `year`, `venue`,
   `publication_type`, `doi`, `landing_url`, `version_label`, `volume`, `issue`, `pages`, `arxiv_id` (from
   `identifier_mappings`, `ORDER BY id LIMIT 1` so the choice is deterministic; `None` when absent). It reads
   `source_versions` by `id`, never by title or key. A version whose row is missing is simply not returned (the report view
   already left it out; `to_latex` then decides). It does not enrich, does not use the network and does not mutate `view`.
   It must not copy the title or authors from `view["references"]`: all bibliographic fields come from the stored row in
   the same snapshot, so the `.bib` and the view agree because they were read together, not because they were copied.
4. **The zip (Q9).** Exactly two entries, in this order: `<stem>.tex` then `<stem>.bib`, where `<stem>` is `bundle.stem`.
   Both are `bundle.tex` / `bundle.bib` encoded as UTF-8 with no change (no newline added or removed, no BOM). Entries are
   written with `zipfile.ZipInfo` with a fixed timestamp `(1980, 1, 1, 0, 0, 0)`, `compress_type=ZIP_DEFLATED`,
   `create_system = 3` and `external_attr = 0o644 << 16`, so the same bundle always gives the same bytes (a test calls the
   function twice). No directory entry, no extra file, no IEEEtran class or style, no README, no comment on the archive. An
   empty `.bib` (a report with no citations) is still written as an empty second entry. Filename `<stem>-latex.zip`, which for
   a finished report matches `^report-[a-z0-9-]+-v[0-9]+-latex\.zip$` and for a draft `^report-[a-z0-9-]+-draft-latex\.zip$`.
5. **The route (Q15).** Only the `export` route changes: `fmt: Literal["markdown", "latex"] = Query("markdown",
   alias="format")`. For `latex`: `data, name, notes = latex_export.export_latex(store_of(request), research_id, report_id)`
   and `Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"',
   "X-Deixis-Export-Notes": str(notes)})`. For `markdown` the body, media type and headers are **exactly** what they are now:
   no `X-Deixis-Export-Notes` header on Markdown, and the existing lines stay as they are (put the `latex` branch first or
   after, whichever leaves the existing lines untouched). The default stays Markdown. An unknown format stays FastAPI's 422.
   Keep the `app.py` change to the import, the `Literal` and the branch: another chat edits the same file. The header carries
   the total number of export notes as ASCII digits (`0` when there are none); the comment block in the `.tex` says
   `% Export notes: none` for zero (X3). Errors: 404 (`NotFound`) and 409 (`RevisionConflict`, with its `detail` text) as for
   Markdown; an error response carries no `Content-Disposition` and no `X-Deixis-Export-Notes` header and is not a zip.
6. **The compile test (Q13, section 9 of the note).** `tests/test_report_latex_compile.py`, described in the "Tests" section.
   Own judgements: it does not need `latexmk` (the note lists it, but the test runs `xelatex`, `bibtex`, `xelatex`, `xelatex`
   itself, so the command in the `.tex` header, which names `latexmk`, is **not** exercised and the decision record says so);
   it reads the committed goldens for its first group so it compiles exactly the pinned bytes; page text is checked after
   `unicodedata.normalize("NFKC", ...)` and removal of all whitespace, `-` and U+00AD on both sides, because `pdftotext`
   returns ligatures as single characters and the long cells wrap and hyphenate.
7. **Status codes for X5 (list them in your report).** Success 200 `application/zip`; 404 unknown research, unknown report or a
   report that belongs to another research; 409 for the unfinished report ("The report is still being written") and for
   every `RevisionConflict` from `to_latex`; 422 for an unknown `format`.

## Files

Allowed (create or edit): `backend/deixis/workflow/report/latex_export.py` (new), `backend/deixis/api/app.py` (the import, the
`Literal` and the `latex` branch of the one route; nothing else), `tests/test_report_latex_export.py` (new),
`tests/test_report_latex_compile.py` (new).

Not allowed: `workflow/report/latex.py`, `latex_text.py`, `latex_math.py`, `latex_preamble.py`, `latex_names.json`,
`export.py`, `export_text.py`, `bibliography.py`, `views.py`, `queue.py`, `store.py`, `domain/contracts.py`, any migration,
`methods/`, `contracts/`, `apps/web`, `tests/report_latex_cases.py`, `tests/fixtures/report_latex/`, existing test files,
`docs/decisions.md`. If you think one of them must change, stop and report why; do not change it.

## Tests

`tests/test_report_latex_export.py` (no TeX; real report flow through the route, the pattern of
`tests/test_report_export.py::test_valid_export_route_contains_frozen_table_references_and_corpus` and
`test_draft_gating_and_unknown_ids`, whose helpers `complete`, `app_for`, `create`, `session`, `upload_and_include`,
`create_table`, `fill_table`, `ReportAdapter` you may import without editing, and `wait_run` from `test_api_flow`, as that test
does inside its body; `app_for`, `create` and `session` come from `test_api_flow`, `upload_and_include`, `create_table` and
`fill_table` from `test_report_api`, `ReportAdapter` from `test_report_flow`):

1. Success through the HTTP route on a real finished report: status 200; `content-type` `application/zip`; the
   `content-disposition` matches the finished-report filename pattern; `zipfile.ZipFile(io.BytesIO(response.content))`
   `.namelist()` equals `[stem + ".tex", stem + ".bib"]` with the stem taken from the filename; `testzip()` is `None`; every
   entry decodes as UTF-8. Content: the `.tex` starts with the comment block and `\documentclass[journal]{IEEEtran}`, contains
   `\bibliography{<stem>}` and the research title, and holds no `claim_key`, `psg_`, `cel_` or `support_type`; every key in a
   `\cite{...}` is a key of an entry in the `.bib` and every `.bib` key is cited; the cite-key order (first appearance) equals
   the `source_key` order of `view["references"]` of the same report (from `GET .../reports/{id}`); the `.bib` entry count
   equals the reference count; the same bytes come back from two requests; and the zip equals what `export_latex(store, ...)`
   returns when called directly with the same store (the route adds nothing).
2. `X-Deixis-Export-Notes` is present on the latex response, is `str(int)`, and equals the number the `.tex` comment block
   announces (`% Export notes: N` or `none`). Build at least one report whose export has notes (for example a source with no
   usable `source_key`, set in the store, or a view that makes `to_latex` write a note) and check a non-zero header equals
   the numbered lines plus any `% and N more`; also check a zero case. If a real flow cannot produce a note, produce it by
   changing a stored field of the source (`works.source_key`) in the test database and say so in the test.
3. Draft report (failed or cancelled run, the `test_draft_gating_and_unknown_ids` setup): 200, filename
   `report-...-draft-latex.zip`, the `.tex` carries the draft line.
4. 409 for an unfinished report (`in_progress`, and a run that is still `paused`), with `detail` equal to `"The report is
   still being written"` and neither a zip, a `Content-Disposition` nor an `X-Deixis-Export-Notes` header. 404 for an unknown
   report id, for the report of another research and for an unknown research. One shared assertion helper checks, for **every**
   404, 409 (including the missing-source one of item 5) and 422 case, that the response has a JSON `detail`, no
   `Content-Disposition` header, no `X-Deixis-Export-Notes` header and a `content-type` that is not `application/zip`.
5. Missing source record: on a finished report whose claims cite a source, delete that source's `source_versions` row
   (`PRAGMA foreign_keys = OFF` for the delete and back to its previous value afterwards, in the test), then the route returns
   409 with a non-empty `detail` that is the `RevisionConflict` text, and no zip. Also a direct `export_latex` call raises
   `RevisionConflict`. Check that no row of any table changed because of the export (compare `store.conn.total_changes` and
   the row counts of `source_versions`, `works`, `reports`, `runs` before and after a successful export too).
6. A direct unit test of `read_bib_sources`: returns the references' versions in order, the `arxiv_id` from
   `identifier_mappings` (insert one in the test), `None` when none, `authors` as a list, the optional fields; a second
   `identifier_mappings` row for the same version makes the lowest `id` win; a reference whose row is gone is not returned;
   `view` is not mutated (deep copy compare).
7. One read moment, in two ways. (a) With `store.conn.set_trace_callback` collect the statements of one `export_latex` call:
   exactly one `BEGIN` and one `COMMIT`, and every `SELECT` lies between them; no statement that starts with `INSERT`,
   `UPDATE`, `DELETE` or `REPLACE`. (b) A test that fails if the reads are moved out of the snapshot: wrap
   `deixis.workflow.views.report_view` and `latex_export.read_bib_sources` (or the corresponding module attribute, whichever
   your code calls) with spies that record `store.conn.in_transaction` at call time, and assert both were `True`; assert
   `store.conn.in_transaction is False` before the call and after it. (c) A separate test with a transaction already open
   (`store.conn.execute("BEGIN")` before the call): `export_latex` neither issues a second `BEGIN` nor commits the caller's
   transaction (`in_transaction` still `True` after the call), and the caller then ends it. Say how the test (b) would fail for
   the wrong implementation. The store connection uses `isolation_level=None` (`storage/db.py`), so a bare `SELECT` opens no
   transaction and only the explicit `BEGIN` of `_snapshot` makes `in_transaction` true; do not rely on the driver's implicit
   transactions.
8. The Markdown path is unchanged: for the same finished report `format=markdown` and no `format` give identical bytes, the
   content type `text/markdown; charset=utf-8` (as in the existing test), `.md` filename, no `X-Deixis-Export-Notes` header,
   and the text equals `export_markdown(store, ...)` called directly; an unknown format (`format=pdf`) is 422. `tests/test_report_export_pin.py` and
   `tests/test_report_export.py` pass unchanged.
9. `build_zip`: for a hand-built `LatexBundle` the opened entries equal `bundle.tex.encode("utf-8")` and
   `bundle.bib.encode("utf-8")` byte for byte (use a `.tex` with non-ASCII text, a `\r`-free trailing newline case and a case
   without a trailing newline, so a BOM or newline change shows); two calls give equal bytes; the entry order, `date_time`
   `(1980, 1, 1, 0, 0, 0)`, `compress_type` `ZIP_DEFLATED`, `create_system` 3, `external_attr` `0o644 << 16` and an empty
   `ZipFile.comment` are each asserted; no directory entry; an empty `.bib` is still a second entry. The route test of item 1
   also compares the opened entries with `bundle.tex.encode("utf-8")` of a direct `to_latex` call on the same snapshot data.
10. Import boundary of the new module: `latex.py` is still free of `zipfile` and database imports (the existing X3 test
    covers it; add nothing there), and `latex_export.py` does not import `export.py`'s Markdown writer, TeX, `subprocess`,
    `httpx` or any network module (an AST check of the import lines, in the style of `test_import_boundary`).

`tests/test_report_latex_compile.py` (the optional compile test; section 9 of the note):

11. **Skip rule.** A function `missing_tex()` returns `None` when everything is present, else one string naming what is
    missing. Programs by `shutil.which`: `xelatex`, `bibtex`, `pdftotext`, `kpsewhich`. Files by `kpsewhich <name>` (empty
    output means missing): `IEEEtran.cls`, `IEEEtran.bst`, `fontspec.sty`, `cite.sty`, `url.sty`, `booktabs.sty`,
    `longtable.sty`, `array.sty`, `amsmath.sty`, `amssymb.sty`, `bm.sty`, `xcolor.sty`. Compile tests carry
    `pytest.mark.skipif(missing_tex() is not None, reason=...)` with that string in the reason (the `needs_tesseract` pattern
    of `tests/test_ocr.py`). A missing dependency is a skip; a compile or check failure is a failure. A test with a
    monkeypatched `shutil.which` (and a monkeypatched `kpsewhich` call) proves the reason string names the missing items and
    that it is `None` when all are present. This test and the log-scanner tests below run on every machine; only the tests
    that start TeX skip.
12. **Pure scanners, always run.** `scan_log(log_text, *, allow_overfull_hbox=False) -> list[str]` returns one entry per
    failure found in the final `xelatex` log: `Missing character`, `Overfull \vbox`, `Overfull \hbox` (unless allowed),
    `Float too large for page`, `LaTeX Error`, `Citation ... undefined`, `Reference ... undefined`, `Label ... multiply defined`
    and `There were undefined references`. The known IEEEtran message `Font shape ... undefined` and `Underfull` boxes are
    **not** failures. `bibtex_failures(blg_text)` flags `error message`, `I couldn't open` and `---line` (BibTeX warnings are
    not failures). `bbl_keys(bbl_text)` returns the `\bibitem` keys in order (with or without the optional argument).
    `cite_keys_in_order(tex_text)` returns the unique `\cite` keys in first-appearance order. `pdf_contains(pdf_text,
    needle)` applies the normalisation of decision 6. Unit tests for each use short synthetic strings, including a negative
    for each failure kind and the two non-failures above.
13. **Compilation helper.** For one `.tex`/`.bib` pair in a fresh `tmp_path` directory: `xelatex -no-shell-escape
    -interaction=nonstopmode -halt-on-error <stem>.tex`, `bibtex <stem>`, then `xelatex` twice more with the same flags,
    each `subprocess.run` with `cwd`, `timeout=180`, `capture_output=True`, no `shell=True`, and a minimal environment
    (inherit `PATH` and `HOME`, set nothing that enables a network or a shell escape). A non-zero exit of any `xelatex` run
    fails with the tail of its log. Checks run on the **last** `xelatex` log and the `.blg`; the first runs are allowed to
    have undefined references. `pdftotext <stem>.pdf -` gives the page text.
14. **Group 1: committed goldens** (parametrize over a fixed list of names under `tests/fixtures/report_latex/`; compile the
    committed `.tex` and `.bib` bytes as they are). The list is fixed in the test as literal names. The orchestrator's X3 compile
    log shows `Overfull \hbox` in 16 goldens (D155 says 14; the log holds these eight names in en and tr): `table_cell_400`,
    `table_cell_401`, `table_heading_400`, `table_heading_401`, `table_source_200`, `table_source_201`, `table_parenthetical`,
    `table_math`. None of the 16 may be in this group (their cases belong to groups 2 and 3). Choose names from the rest that
    cover:
    an English and a Turkish plain report, a draft with unvalidated sections, missing rows, an edit note, a reviewed report
    with findings, equations with labels and `\eqref` (`eq_several`, `eq_repeated` or similar), two source versions of one
    key (`keys_versions`), a reference order that differs from the `.bib` order (`ref_order`), `keyword_cite`, `corpus`, a
    7-column table. Exclude the four class-B goldens (`kitchen_sink`, `math_classes`, en and tr: `\R` is undefined by design)
    and `hostile` (BibTeX reports an error for the stored author name). If one of your chosen goldens does not compile clean
    on the orchestrator's machine, report it, do not silently drop it. For each: no entry from `scan_log`, no
    `bibtex_failures`, `bbl_keys(bbl) == cite_keys_in_order(tex)` and `set(bbl_keys) ==` the set of keys of the `.bib`
    entries (two separate assertions, order and set), and the PDF exists. Expected page text comes from the **fixture data,
    never from the raw `.tex`**: the title and each source title are searched as the plain strings that
    `tests/report_latex_cases.py` stores (for example `SYNTHETIC report` and `SYNTHETIC source s1`), not as the escaped or
    `\ensuremath` form that the `.tex` holds (`&` and `α` print differently from their TeX source), and no `.bbl` text is
    searched in the PDF.
15. **Group 2: table fixtures built in the test** (not committed; build the `view` with the `tests/report_latex_cases.py`
    helpers or by hand, run `latex.to_latex`, write the files, compile). One report each with a Table I of 8, 13 and 20 data
    columns (2, 2 and 3 groups) and at least 12 rows. Every cell value is built from words of at most 12 characters and carries
    a unique end marker (for example `END` plus row, column and a fixed tail; the marker never wraps into a number or hyphen).
    The set holds: cells of 400 characters (inline, at the threshold) and 500 characters (above it, so `see note k` in the cell
    and the full text in `Long table values`), a source title just under and well over 200 characters, a column heading and an
    option label just under and well over 400 (the thresholds apply to the **final formatted text**: the source cell is
    `[n] <key-or-title>` and a usable `source_key` replaces the title, so the long-source-title rows use `source_key=None`, and
    each boundary case is sized on the formatted text, 200 and 201 for the source cell and 400 and 401 for headings and
    cells, counting the `[n] ` prefix as `export_text.source_cell` and `cell_text` produce it), mapped Unicode symbols (for example `≥ ≤ α ± ×`; **no character outside
    the X2 symbol table and no class-B command such as `\R`**, so `Missing character` can be asserted absent), a Turkish
    variant of the 13-column report. Pass conditions: no `scan_log` entry, no `bibtex_failures`; **every** cell text and every
    marker of the fixture is found by `pdf_contains` (expected strings are taken from the fixture data, not from the `.tex`),
    and the same holds for the **full** text and end marker of every long source title, column heading and option label, below
    and above its threshold; for the above-threshold values the page text holds `see note` in the cell and the full text in
    `Long table values` (so the marker is found there); the caption numerals
    in the page text are all `I` (`re.findall(r"TABLE\s+([IVX]+)", ...)` has the single value `I`) and appear at least once
    per column group; the `.bbl` order equals `view["references"]` key order. Words of at most 12 characters keep natural
    overfull warnings out; if an `Overfull \hbox` still appears for a fixture value that is not the explained exception,
    treat it as a failure and report which value, do not widen the allowance.
16. **Group 3: the explained exception.** A separate fixture with one table cell holding a single unbroken token wider than its
    column (for example 150 characters of `W` with no break point, below the 400-character threshold so it stays inline).
    The test **asserts** that the final log contains `Overfull \hbox` (the known limit of note section 5) and that no other
    failure kind from `scan_log` appears. This is the only place `allow_overfull_hbox=True` is used; a test greps the module to
    prove that argument is passed exactly once outside the scanner's own tests.
17. **The scanner would have caught it.** One TeX-backed negative control: compile a tiny hand-written document that holds an
    undefined citation and a character the font lacks (for example U+6587 in plain text, which the preamble's Latin Modern
    does not have) and assert that `scan_log` reports `Missing character` and an undefined citation. This proves the
    scanner is wired to real logs, so a clean result on the fixtures is meaningful. It uses the same preamble file
    (`latex_preamble.PREAMBLE`) so the missing-glyph message is the one the exports would produce.
18. Compile time: the whole file is allowed to take about two minutes serially; keep per-fixture work to the four runs above,
    use `tmp_path` (so `pytest -n` is safe) and do not share state between tests.

## Checks

```sh
PYTHONPATH=backend:. uv run pytest tests/test_report_latex_export.py tests/test_report_latex_compile.py \
  tests/test_report_export.py tests/test_report_export_pin.py tests/test_report_latex.py tests/test_bibliography.py \
  tests/test_report_api.py tests/test_p6_measure_report.py
PYTHONPATH=backend:. uv run pytest          # full suite; known flaky under parallel load: test_audit (stratum), test_builtin_embedding_flow (429 wait) - rerun alone and say so
git diff --check
git status --short                           # compared with the start state: the only new or changed paths are the four allowed ones (the untracked X4 prompt and the pre-existing TODO.md, .vscode, other untracked files are not yours)
git diff --stat -- backend/deixis/storage/migrations methods contracts apps/web   # empty
```

Report the compile-test outcome as run (passed, skipped with the reason, or not executable in your sandbox) and, separately,
the pytest counts. Say plainly that on a machine without TeX the compile tests skip and the claim "the exports compile" is
not measured there.

## Done when

The route tests are green; `format=markdown` bytes, headers and the pin tests are unchanged; the zip holds exactly the two
right files with the right content and a fixed byte image; the 404, 409 and 422 cases behave as in decision 7 and carry no
zip; the missing-source case is a 409 and writes nothing; the reads happen in one snapshot and a test fails if they do not;
the compile test passes on a TeX machine (or its skip reason is stated, and on this machine it was executed); the scanner
tests run everywhere; `skill_package_hash`, the migration list, `latex.py` and `export.py` are untouched; no other file
changed.

## Report

List: the files changed; the public surface of `latex_export.py`; which imports you made lazy; every own-judgement decision;
the status codes and header name for X5; the full pytest result; the compile-test result with the TeX version line
(`xelatex --version`) if you could run it; anything you could not find or make pass, with the failing fixture and value.
