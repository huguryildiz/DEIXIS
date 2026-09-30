<!-- Plan review: gpt-6-sol high, rounds recorded below by the orchestrator (see the bottom line of this comment block). -->
<!-- PLAN-REVIEW-ROUNDS: gpt-6-sol high, 3 rounds: r1 3 high (index_terms numbering order, screen limits dropped, 409 state field), r2 2 high (VIII draft.text, review findings), r3 2 high (paragraph first-seen order, untrusted Markdown text); every finding folded in; round 3 fixes not re-reviewed (3-round cap) -->

# Task: P6 slice 1, batch P12, Markdown export and citation numbering (plan 1j)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p12` (detached at `437cef7`, main with P9/D118).
Read `AGENTS.md`, `CLAUDE.md`, `.impeccable.md` (before touching `apps/web`), `docs/product/p6-slice1-report-run.md`
section "1j" (its file layout is older than the code; where this prompt differs, this prompt wins), and D113, D115, D116,
D118 at the top of `docs/decisions.md`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not create files outside the list below. Do not invent; report what you could not find. No real-model
calls; tests use `FakeAdapter`/the scripted acceptance server only. Do not touch `../DEIXIS-s31`, `../DEIXIS`,
`.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`. Use a distinct port for any server
(never 8765, 8858–8864). Another session is editing `flow.py`, `contracts.py`, `store.py`, `worker.py`, `views.py`,
`ResearchView.tsx`, `Transcript.tsx`, `labels.ts`, `fakes.py`, fixtures and `fixture_server.py` in a different worktree:
keep your changes to files that session also touches (`api/app.py`, `i18n.ts`, `views.py`) to the minimum listed here.

## What is and is not in code (checked on 437cef7)

- Numbering exists, on the backend, in `views.py::report_view`: it walks `reports.sections()` in `ordinal` order
  (abstract 0, I 1, II 2, ... IX 9, index_terms 10) and claims in `ordinal` order, and gives
  each `source_version_id` the next number the first time a citation link names it (`ref_number` on each link;
  `references[]` in the same order; `table_i.rows[].ref_number`, null for a frozen row nobody cites). **That order is
  not the screen's**: `ReportView.tsx` displays `index_terms` second (its `DISPLAY` list: abstract, index_terms, I, II,
  ..., IX) while the backend numbers it last, so an `index_terms` claim citing a source no other section cites gets a
  number out of first-appearance order (plan 1j and D113 promise first-appearance order). The screen numbers equations
  `(1)`, `(2)` client-side by first `equation_ref` in `DISPLAY` order. There is no `numbering.py`, `export.py`, `to_markdown`, `reportMarkdown.ts` or export route. The plan's
  "number_citations/number_equations in numbering.py" is NOT built as separate modules: the numbers already come from
  `report_view` and must stay in exactly one place.
- The screen has no Copy or Download action.
- `report_view` returns: `status` (`in_progress`/`valid`/`draft`), `report_version`, `language`, `created_at`,
  `sections[]` (`section_id`, `status`, `draft` (`text` for II and VIII, `insufficient_evidence`), `validation` (II/VIII
  carry `numbers`, D115), `claims[]` with the current text (an edited claim's edited text, `edited`), `paragraph`,
  `table_ref`, `equation_ref`, `evidence[]`), `references[]`, `table_i` (`columns`, `rows`, `cells` with `state`, `value`,
  `options`), `edited_after_version`, `evidence_changes` (`any`, counts), `review`, `run`.

## Decisions taken (the plan's own default where it has one; own judgement is marked)

1. **One numbering source, fixed to display order.** `to_markdown` is a pure function over the dict `report_view`
   returns. It renumbers nothing: it uses the `ref_number` and `references[].number` already there and computes equation
   numbers with the screen's rule (first `equation_ref` in display order, claims in ordinal order). To make the backend
   numbers match the display order, `report_view` (`views.py`) is changed in exactly one place: it iterates
   `reports.sections(report_id)` sorted by a new constant `DISPLAY_ORDER = ("abstract", "index_terms", "I", "II", "III",
   "IV", "V", "VI", "VII", "VIII", "IX")` (define it in `report/store.py`, which `views.py` already imports, to avoid a
   circular import; a section id not in the list sorts last, stable), so `sections[]` in the response and the `numbers`
   dict follow display order. Within a section the screen groups claims by `paragraph` in first-seen order (not
   ascending, not adjacent-run order), so the same one-line change also orders each section's claims into that display
   order (stable: paragraph groups by first-seen `paragraph`, claims inside a group by `ordinal`) BEFORE numbers are
   assigned, and returns `claims[]` in that order. Then citation numbers, equation numbers (the screen's loop over
   `claims[]` and the export's) and reading order all derive from one order. Export groups paragraphs in this
   same first-seen order (not by ascending number). No other change to `views.py`. `ReportView.tsx` keeps its own `DISPLAY` and picks sections
   by id, so the screen only changes where `index_terms` cited a new source (its numbers now are first-appearance).
   (Views.py therefore has two small edits: section order and claim order, both before numbering.)
   Existing tests that assert section order or numbers must be checked and updated only if they encoded the old order
   (report it). Own judgement: no `numbering.py` and no `reportMarkdown.ts`, because a second (TypeScript) copy of the format
   would drift; the screen's Copy fetches the same text from the route.
2. **Module and signature.** New `backend/deixis/workflow/report/export.py`:
   `to_markdown(view: dict[str, Any], *, title: str, corpus: dict[str, int] | None) -> str`,
   `export_markdown(store: Store, research_id: str, report_id: str) -> tuple[str, str]` returning (text, file name),
   `MEDIA_TYPES = {"markdown": "text/markdown; charset=utf-8"}`. `export_markdown` calls `report_view(store, research_id,
   report_id)` (so it raises the same `NotFound` for an unknown or cross-research id), reads the title from
   `store.research(research_id)["title"]`, and reads `corpus` from `ReportStore(store).snapshot(report_id)["corpus"]`
   (`None` when the snapshot is missing). Import `report_view` lazily inside the function if a circular import appears.
3. **Route.** One route in `api/app.py`, next to `get_report`:
   `GET /api/researches/{research_id}/reports/{report_id}/export?format=markdown` (`format: Literal["markdown"]`, alias
   `format`, default `markdown`), `Response(text, media_type=MEDIA_TYPES["markdown"], headers={"Content-Disposition":
   f'attachment; filename="{name}"'})`, the same pattern as `export_bibliography`. Unknown id: the existing 404 path.
   The route is refused with 409 and the message "The report is still being written" when `report["status"] ==
   "in_progress"` (a report state, not a run state) OR its run (`view["run"]`) exists and its `status` is not one of
   `completed`, `failed`, `cancelled` (paused, queued or running; own judgement: an export of a half-written report would
   look final, and the screen's Edit is gated the same way). `draft` and `valid` reports whose run has finished export
   (see 5). The route returns the `Response` directly (no redirect).
   The file name: `report-<slug of the research title, max 60 chars, ascii-safe, fallback "report">-v<n>.md` for a valid
   report, `...-draft.md` for a draft; no version number is written for a draft (plan 4.2 decision 11).
4. **Format (English and Turkish by `view["language"]`, `tr` prefix; everything else English).** Lines in this order:
   - A draft report's first line is `> DRAFT: {n} sections not validated.` (Turkish `> TASLAK: {n} bölüm doğrulanmadı.`),
     then a blank line. A valid report has no such line. `in_progress` cannot reach here.
   - `# {title}`, then one line: `Evidence report · V{n}` (valid) or `Evidence report · draft` (draft; Turkish
     `Kanıt raporu · V{n}` / `Kanıt raporu · taslak`), then a blank line.
   - If `edited_after_version` is not null: `Edited by hand after version {n}; edited text was not checked again.`
     (Turkish counterpart). If `evidence_changes.any`: `Evidence changed after this report was written; the report text
     was not changed. Passage text was not checked.` (the screen's own sentence; Turkish counterpart from `i18n.ts`). Each as its own paragraph. Own judgement: these two lines keep an exported
     copy from looking more current or more checked than the screen says.
   - Sections in display order, each `## {heading}` with the same English/Turkish headings as `ReportView.tsx`
     (`HEADINGS`). Only sections that exist in the report; a section whose status is `draft` or `failed` gets the line
     `> This section was not validated and must be written again.` (Turkish counterpart) under its heading. Body:
     II and VIII: `draft["text"]`, when present, is ALWAYS written as its own paragraph first, whether or not the
     section also has claims (VIII stores its limitations text together with claims; the screen shows both). Then, for
     every section: claims grouped by `paragraph`
     (ascending), each paragraph = its claims' current text joined by one space; after a claim with an `equation_ref`,
     append ` ({k})` exactly as the screen does; after each claim, append its citation markers `[n]` from its
     `evidence` links, unique by `ref_number`, in link order, joined `, ` inside separate brackets (`[2], [5]`,
     matching the screen), separated from the text by one space. A claim with no links gets no marker. A section with no
     claims and no `draft.text` writes `Not enough evidence: {reason}` per `insufficient_evidence` entry, else
     `No text was written for this section.` (as the screen).
   - Section IV: Table I is embedded right after the paragraph containing the first claim whose `table_ref ==
     "TABLE_I"`; with no such claim, directly under the IV heading (the screen does the same). Section VI gets the line
     `Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.` under its heading.
   - Equation numbers: the screen shows `(k)` in its own span after the claim; the Markdown puts ` (k)` inline after the
     claim text (own judgement: Markdown has no separate span).
   - Table I: a caption line `TABLE I. Evidence table as frozen for this report ({rows} sources, {columns} columns).`
     (`1 column` singular, as the screen), then a Markdown table: header `Source | <column names>`, one row per frozen
     row, first cell `[n] source_key` (or `source_key`/title/`Source record unavailable` when uncited), then each cell:
     `value` cell shows the value text (same rules as the screen's `valueText`: `text`, `number` + `unit`, yes/no,
     option labels), `not_verified` shows `{value} (not verified: no quote linked)`, other states show the state with
     underscores as spaces, no cell record shows `—`. Every cell is escaped for Markdown table use: `|` becomes `\|`,
     newlines become a space, and nothing else is altered (LaTeX `$...$` is left as is everywhere).
   - `## References` (Turkish `## Kaynaklar`): one numbered line per `references[]` entry, in the screen's order and
     with the screen's fields (authors, title, venue, year; read the screen's exact composition in `ReportView.tsx` and
     reproduce it), plus, as an own-judgement addition for a file that leaves the app, `DOI: doi` and the version label in
     parentheses when the stored record has them. No empty separators when a field is missing.
   - A last paragraph: `Generated by DEIXIS; corpus: {found} found, {unique} unique, {screened} screened, {included}
     included, {full_text} with full text.` (Turkish: `DEIXIS ile üretildi; korpus: ...`). If `corpus` is `None` the
     paragraph reads `Generated by DEIXIS.`. Own judgement: the plan's footer text is Turkish-only; the language rule above
     replaces it. The corpus comes from the frozen snapshot, not from II's prose.
   - A final provenance paragraph reproducing the screen's statements without weakening or extending them: the anchor
     sentence (`Anchors were located in the cited passages or cells.` when every link has `anchor_match`, else `{n} of {m}
     citation anchors were located in their passages or cells; the others open without a mark.`; `n` counts links with a
     non-null `anchor_match`, `m` all links) followed by the review note exactly as the screen composes it: read
     `reviewNote` in `ReportView.tsx` (three cases: no review recorded; `not_reviewed` with its reason; `reviewed` with
     the counts, the reverted-sentences sentence and the `Not read:` list) and reproduce those English sentences verbatim
     in the backend (Turkish from `i18n.ts` where it has them, else the English sentence). After the paragraph, when `review.status == "reviewed"` and it has findings, a list headed `Model findings`
     (Turkish counterpart) with one bullet per finding, exactly as the screen's list: `{section heading or "Report"} ·
     {code label} · {text}`, using the screen's `reviewCodes` labels (unknown code: `Other`). These are model flags, not
     established errors, and the bullets are listed under the same "model's reading" sentences. A
     `reviewed` record must never read as verification: keep the sentences saying it is a model's reading, not peer
     review, that it can miss errors, and that whether each passage supports its claim was not checked by code.
   The output ends with one newline. The text is only stored claim text (as the model wrote it or as the person edited it, exactly as the
   screen shows), stored `draft.text`, headings and the fixed sentences above; the exported file carries the same
   "not checked" limits as the screen.
5. **Draft reports export** with the DRAFT line and no version number (plan 4.2 decision 11).
6. **Frontend.** In `ReportView.tsx`, two new buttons in the toolbar (`report-toolbar-actions`), disabled with a title
   while the report is null or its run is not finished (same `finished` rule as Edit; a `draft` report whose run finished
   is enabled): "Copy Markdown" and "Download .md". Both call a new `api.reportMarkdown(researchId, reportId)` returning
   `Promise<{ text: string; filename: string }>` (a plain GET `fetch` with `credentials: 'same-origin'`, no CSRF header;
   the file name from `Content-Disposition`, fallback `report.md`; a non-OK response throws `ApiError` with the server's
   message, as `request` does). Copy then calls `navigator.clipboard.writeText(text)`; Download builds a `Blob`
   (`text/markdown`), an object URL and a temporary `<a download={filename}>` click, then revokes the URL. Both show a
   success toast and, on any failure (409, 404, clipboard refused), an error toast; never silent. (Own judgement: a plain
   `<a download>` link would show the browser's error page or save the error body as a file on a 409/404.) New UI strings go through `t()` and are
   added to `i18n.ts` (Turkish too). Follow `.impeccable.md`: no new visual system, use the toolbar's existing button
   variant; the buttons must fit at 390 px (icon + short label may collapse to icon with `aria-label`/`title`, as the
   toolbar's other buttons do). Do not restructure `ReportView.tsx`.

7. **Untrusted text is neutralised, not rendered.** Claim text, `draft.text`, the research title, reference fields, column
   names, cell values and review-finding text are stored data (model-written, source-derived or user-edited); a value like
   `## References` or `[1]` must not create a heading or a citation in the file. One helper `_md(text)` (in `export.py`)
   is applied to every such value: collapse all runs of whitespace including newlines to one space and strip; leave every
   `$...$` and `$$...$$` math span byte-for-byte unchanged (find spans with a simple left-to-right scan for paired `$`;
   an unpaired `$` is ordinary text); outside math, backslash-escape `\`, `[`, `]`, `<`, `>`, `` ` `` and `|`, and
   backslash-escape a leading `#`, `-`, `+`, `*`, `>` or `digits.`/`digits)` at the start of the (stripped) value.
   The export's own markers (`[n]`, `## heading`, table pipes, the `>` lines) are written by code AFTER escaping the
   pieces, never escaped again. (Own judgement: escaping over-protects a little, e.g. a literal `[2]` in a claim shows as
   `\[2\]`; that is intended.) A math span containing a newline has the newline replaced by a space.

## Files

Allowed: create `backend/deixis/workflow/report/export.py`, `tests/test_report_export.py`; edit `backend/deixis/api/app.py`
(the import and the one route only; keep the hunk small, slice 31 edits this file elsewhere), `apps/web/src/api.ts` (two additions), `apps/web/src/report/ReportView.tsx` (the
two buttons and their handler only), `apps/web/src/report/report.css` (only if the buttons need it), `apps/web/src/i18n.ts`
(new strings only), `apps/web/e2e/report.spec.ts` (one added test or an added step in an existing test). Not allowed: any
migration (none is needed), `methods/`, `contracts/`, `tests/fakes.py`, fixtures, `fixture_server.py`, `labels.ts`, and any change to `views.py` other than the section-order line in decision 1. Also allowed: `backend/deixis/workflow/report/store.py`
(the `DISPLAY_ORDER` constant only) and `backend/deixis/workflow/views.py` (decision 1 only).
`skill_package_hash` must not move.

## Tests to add (`tests/test_report_export.py`, synthetic data, `FakeAdapter`; reuse `test_report_api.py`/`test_report_flow.py` helpers)

- A completed valid report exported over the route: 200, `text/markdown; charset=utf-8`, `Content-Disposition` attachment
  with the `-v<n>.md` name; the text contains `TABLE I`, a Markdown table with a header row and separator row, a
  `## References` section, the corpus footer with the counts equal to `snapshot["corpus"]`, and no DRAFT line.
- Order: a report whose `index_terms` claim cites a source that no other section cites, and whose `abstract` cites another:
  the export's first `[n]` in reading order is `[1]` and numbers first appear increasing across the whole text, with
  `index_terms` numbered right after `abstract` (this fails on the old backend order). Build it by writing claim links
  through the store with the technique existing tests use.
- Numbering agrees with the screen's data: for every `[n]` in the text, `references[n-1]` of `report_view` matches the
  `[n]` line in References; `[1]` appears before `[2]` in the body; a claim citing two sources renders `[a], [b]`.
- Equation numbers: a claim with an `equation_ref` renders ` (1)` and a second distinct ref renders ` (2)`; the same ref
  twice renders the same number.
- Draft report (make one section `draft`, using the same technique existing tests use to produce a draft report): first
  line is the DRAFT line with the right count, no `V` version in the file name or header.
- A claim edited through the edit route exports its edited text and the "Edited by hand after version" line appears.
- Section VIII with both `draft.text` and claims: the limitations text and the claims are both in the export.
- Table cell escaping: a cell value containing `|` and a newline yields a single well-formed row.
- Untrusted text: a claim text `## References\n[1] fake`, a research title and a finding text with `# H` / `- x` /
  `> q`, a column name with `|`, a reference title with `[3]` never produce a heading line, list item, quote line, table
  column, or `[n]` marker other than the code-written ones (assert on the parsed lines); `$a_1 | b$` inside a math span
  survives unchanged.
- Claim order: a section whose claims have paragraphs `1, 2, 1` (write them through the store as tests already do)
  exports and displays paragraph 1's two claims together, first; numbers increase along the text; `report_view`'s
  `claims[]` order equals the export's reading order; an `equation_ref` in the third claim is numbered after one in the
  first.
- Turkish report language gives Turkish headings, header and footer.
- Provenance paragraph: a report with a review record `not_reviewed`, one `reviewed` with a section not read and with findings (the
  `Not read:` list and the `Model findings` bullets with section, label and text appear), one with no review (the "no review recorded" sentence), and one with an
  unlocated anchor (the `n of m` sentence); an evidence-changed report shows the changed line including `Passage text was
  not checked.`.
- An `in_progress` report, and a finished-`draft` report whose run is `paused`: 409 with the message; a `draft` report with
  a finished run: 200.
- Unknown report id and a report id of another research: 404; no redirect (302) is ever returned.
- A `to_markdown` unit test on a hand-built `view` dict for: a section with no claims and `insufficient_evidence`; a
  claim with no links (no marker); an uncited frozen row (no `[n]`); `corpus=None` footer.
- Frontend Playwright (`apps/web/e2e/report.spec.ts`): in the existing write-read-edit test (or a new short one using
  the same scripted fixtures) click "Copy Markdown" with clipboard permission granted and read the clipboard: it contains
  `## References`; click "Download .md" and assert a download named `report-*.md` whose content starts with `# `; also one failure path (route the
  export request to a 409 with `page.route`) and assert an error toast appears and no download happens.

## Checks to run in the worktree

- `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_report_export.py -x` then the full
  `PYTHONPATH=backend:. uv run pytest` (one memory-limit failure is known; name it).
- `cd apps/web && npm run build && npm run lint` (17 warnings today, no new ones; `npm ci` or a `node_modules` symlink
  from `../DEIXIS/apps/web/node_modules` first if missing) and
  `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p12 npm run test:acceptance` against the fresh build.
- Do not run anything that starts a real model.

## Report at the end

Files changed; what you decided differently from this prompt and why; every place you used your own judgement; what you
could not find or verify; the exact commands run and their counts.
