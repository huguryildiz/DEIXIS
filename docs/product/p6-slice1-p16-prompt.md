<!-- Plan review: gpt-6-sol high; rounds recorded below by the orchestrator -->
<!-- PLAN-REVIEW-ROUNDS: gpt-6-sol high, r1 3 high (R2 unit was the claim not the link; B path froze the table id before it existed and allowed a 26-source research; rate-limit resends called hidden), r2 1 high (table id in the owner field for path B), all folded in; r3 0 high (one medium, R10 readability per ratio, folded in). Kit code review: gpt-6-sol high, 4 rounds (r1 3 high: R1 first output and resend vs repair, R8 sentence denominator, R10 per-ratio status; r2 2 high: repair input recognised by its stored message, R8 original sentences; r3 1 high: R8 recovered original count or not_readable; r4 1 high: per-field sentence counting, fixed; r4 medium left as a limit: a not-applied repair text can match another claim of the same section) -->

# Task: P6 slice 1, batch P16 (preparation half), the report measurement kit (plan 1n Task 2, Step 1 only)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p16` (detached at `760d351`: main with P6-P14, the
report review D118, Markdown export D120 and slice 31 D119, so every new research is `sw`). Read `AGENTS.md`, `CLAUDE.md`,
`docs/product/p6-slice1-report-run.md` section "1n" (older than the code; where this prompt differs, this prompt wins),
`docs/product/p6-report-design.md` section 13, `docs/product/p6-slice1-report-expectations.md` (the frozen expectations this
kit must be able to fill in, one row per R1-R11), `scripts/p4_eval/measure.py` (the shape to follow) and D113, D115, D116,
D118, D120, D121 at the top of `docs/decisions.md`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. **No real-model calls and no network calls in tests**: the kit is tested with fake and scripted adapters
through `create_app` only. Do not touch `../DEIXIS`, `../DEIXIS-p15` (batch P15 writes
`tests/model_behavior/report_cases.json` and `scripts/model_behavior/run_report_cases.py` there; you never edit either),
`.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`, `methods/` (so `skill_package_hash` does not
move), `contracts/`, `backend/` and `apps/web/`. Never use ports 8765, 8858-8864 or 8799. The kit itself starts no
server and calls no model; it only reads a running (or test) app through HTTP and, optionally, a read-only SQLite copy.

## Files you may create or edit

- Create `scripts/p6_eval/measure_report.py`.
- Create `tests/test_p6_measure_report.py`.
- Nothing else. (`scripts/p6_eval/` already holds `measure_fill.py`; leave it alone. Do not add `__init__.py` unless
  `tests/test_p4_eval.py`'s import style, `from scripts.p4_eval.measure import ...` under `PYTHONPATH=backend:.`, does not
  work for `scripts.p6_eval.measure_report`; if it does not, say so and add the smallest thing that makes it import.)

## What is in code today (checked on 760d351; verify before relying on it)

- `GET /api/researches/{id}/reports/{report_id}` returns `views.report_view`: the `reports` row (status, plan_json as
  `plan_json`/`plan`? read the real key, `report_version`, `language`, `run_id`), `sections` (each: `section_id`,
  `status`, `word_count`, `draft`, `validation` with `issues`, `truncated`, and for II and VIII `numbers`; `claims` with
  `id`, `claim_key`, `text`, `model_text`, `edited`, `support_type`, `paragraph`, `table_ref`, `equation_ref`, `evidence`
  with `passage_id`, `cell_id`, `source_version_id`, `ref_number`, `anchor_text`, `anchor_match`, `open_passage_id`),
  `references`, `table_i` (frozen columns, rows, cells), `evidence_changes`, `edited_after_version`, `run`.
- `GET .../reports/{report_id}/export?format=markdown` returns the Markdown file (409 while unfinished).
- `GET /api/researches/{id}` returns `runs` (kind `report`, `status`, `usage` including `model_calls`, `error`, `steps`
  with `kind`, `operation_key`, `status`, `started_at`, `finished_at`, `output`), `reportRuns`, `sources`, `counts`, `scope`
  (model fields). `GET /api/researches/{id}/passages/{passage_id}` opens a passage.
- The run's budget: `max_model_calls` = 50 (`REPORT_CALL_FLOOR`). Rounds: III, IV, V (concurrent); VI; VII; VIII; I, IX,
  abstract, index_terms (concurrent); II is written by code. One phrase-repair call per section at most, then one
  `report_review` step.
- Phrase repairs are in the table `report_phrase_repairs` (report_id, section_id, sentence_id, before, after, outcome in
  `kept`, `reverted_exception`, `unframed_exception`), not in the API. Token usage is in `model_sessions.token_usage_json`,
  also not in the API. Truncation is in each section's `validation.truncated` (records `{source_version_id, record_kind}`
  with `record_kind` in `passage`, `cell`, `cell_missing_evidence`) and as a count inside VIII's limitations text.
- What the API does NOT show and you must not invent: bölüm başına şema onarımı sayısı and whether a section was valid on
  its first model output, unless a run step or a `model_sessions` row shows it. Find out what the steps expose; if the
  API cannot show it and the optional `--db` cannot either, the field is `{"status": "not_readable", "reason": "..."}`,
  never a guess.

## The kit (decisions taken; own judgement is marked)

Three subcommands, following `scripts/p4_eval/measure.py` (argparse, one `main`, functions that take an
`httpx.Client` so a test can pass Starlette's `TestClient`, which is an `httpx.Client`):

1. **`snapshot --research ID [--report ID] --out DIR [--base URL] [--db PATH] [--seed 20260930] [--sample 30] [--pairs FILE] [--crossref]`**
   - `--report` defaults to the newest report of the research that has a `report_version` or status `draft`; refuse (exit
     with a clear message) when the research has no report at all. An `in_progress` report is measured only for R1 and R7
     (the expectations file: a run that stopped early counts in R1 and R7 only); the other metrics are written as
     `not_measurable` with reason `run_incomplete`.
   - Writes `snapshot.json` (the report view, the research view's report run and its steps, the opened passages of every
     cited passage, the Markdown export), `automated.json` and `review.md`. Nothing is written under the library; `--db` is
     opened `mode=ro` and never written.
   - `automated.json`, per metric, machine-checkable parts only, each metric `{"value": ..., "denominator": ..., "status":
     "measured" | "not_measurable" | "not_readable", "reason": ...}` (denominator zero means `not_measurable`, never 0 or
     1):
     - **R1**: per section the step status, the section status, `first_try_valid` (only when readable), the failed/draft
       reason from the run's stored `error`; counts a/b; c is written as `"1/1"` or `"0/1"` style plus the number of report
       runs the research has (the expectations file says c is not a rate when there is one run).
     - **R2 support**: nothing automatic beyond the link checks of `measure.py::check_links` for the report: every cited
       passage opens, is the same source version, and a cell link's anchor is located (`anchor_match`), and reading depth per
       claim derived from the linked passage kind (abstract vs pdf_page) and the cell's frozen reading depth; the kit
       records the depth it derived and where from.
     - **R3**: the negative and absence sentences found by a fixed lexicon (put it in one module constant, English and
       Turkish: not found, not reported, did not, no study, none of, absent, yok, bildirmedi, incelenmedi, ele almadı,
       bulunamadı and the `insufficient_evidence` texts), listed with claim id, section and the cells they cite. The
       lexicon is a finder, not a judge; the sheet says so and gives the reader a place for sentences it missed.
     - **R4a**: claims of abstract, I and IX with no `body_refs` (read from the section's `draft`; if the view does not
       carry `body_refs`, use the stored draft through the API or `--db`, else `not_readable`). **R4b** input list for
       the sheet only.
     - **R5**: per glossary term of the plan, occurrences of the canonical term in the text (case-insensitive, whole
       word), and an empty column the reader fills with other names.
     - **R6** input list: every claim with an `equation_ref` and its `equation_origin` passage, physical page and text.
     - **R7**: run start and end from the run and its steps, the sequential chain (steps ordered by start, the longest
       chain by `operation_key` rounds is not required; report total wall time, per-step durations, `model_calls` from
       usage, and, when `--db` is given, tokens from `model_sessions` split into first calls, repair calls and failed
       calls; without `--db` those are `not_readable`).
     - **R8** (needs `--db`, else `not_readable`): from `report_phrase_repairs`, latest row per (section, sentence);
       sentences flagged / all sentences of III-VII (claims plus `insufficient_evidence` entries), and counts of `kept`,
       `reverted_exception`, `unframed_exception`.
     - **R9**: reads `--pairs FILE` (JSON list of `{"source_key": ..., "formulation": ...}`, frozen before the run by the
       operator). Without the file R9 is `not_measurable` with reason `no_pairs_marked`. With it: for each pair whether the
       source's frozen cells or claims carry an equation and whether any report claim with an `equation_ref` cites it;
       the completeness of variable, objective and constraint parts is the reader's judgement.
     - **R11**: per section the truncated records by kind and the ratio cut / (given + cut) where `given` is the number of
       cells and passages in the section's step input (read what is stored; else `not_readable`), the number of
       `insufficient_evidence` entries, and the number of passages the reader marks as missing (sheet).
   - `review.md`: a header naming the report, the model, and the sentence that these readings are model readings unless the
     sheet says a person read it; then the blocks below, each with tick boxes in the style of `measure.py` (`- [ ] label`,
     scored by `re.search(r"- \[[xX]\] label")`). **R2 sheet**: R2's unit is the claim-record link (design section 13), so the sample is `--sample` claims (all claims
     when there are fewer), stratified by section, support type and reading depth, drawn with `random.Random(seed)` over a
     sorted stable order so the same snapshot and seed give the same sample, and **every link of a sampled claim is its
     own unit with its own boxes** (`Supports the claim`, `Partly supports the claim`, `Does not support the claim (wrong
     citation)`), shown with the claim text, support type, depth and the cited passage or cell quote in full (up to 1,500
     characters as `measure.py` does). Unit ids are `C<n>.L<m>`. `score` writes the denominator as judged links and also
     the number of sampled claims with at least one wrong link (the expectations file's range for R2 is on those claims). **R3 sheet**: every found sentence with the
     cells it cites and boxes `Follows the rule` / `Does not follow the rule`. The reader adds every sentence the lexicon missed as its own
     block `#### M<n> · <section> · <text> · cells: <cell ids or quoted cell text>` with the same two boxes (the sheet shows the format and a numbered empty slot
     `M1`); `score` counts the `M` units in the R3 denominator, and an `M` block with no box ticked is a read gap
     reported as `judged` < `total`, and an `M` block with no cells named is `no_evidence_given` and takes no verdict (the judgement is
     against the cells it rests on). **R4b sheet**: each Abstract/I/IX claim with its linked body claims and boxes `Same strength as
     the body` / `Stronger than the body`. **R5 sheet**: term, canonical count, `Other names found: <n>` line. **R6 sheet**:
     equation, origin passage text, page, boxes `Matches the page (equivalent LaTeX is a match)` / `Does not match the page`,
     and an `Error kinds:` line (symbol, index, operator, condition/range, missing part), plus the link that opens the
     original PDF page (`/api/researches/{id}/assets/{asset_id}` with the physical page) and the page examined; the extracted
     passage text alone does not verify symbols and indices. When no PDF asset opens for an equation the unit is written
     `not_readable` (reason `page_not_openable`) and takes no verdict. **R9 sheet**: per pair boxes
     `Present with all given parts` / `Present, parts missing` / `Absent`. **R11 sheet**: per section `Missing passage
     count: <n>`. A `Reader:` line at the top of the sheet (analyst, second, owner) which `score` reads.
   - Output for a Turkish report: the sheet labels stay English (like `measure.py`'s review labels), the quoted text is
     untouched.
2. **`second --out DIR`** (own judgement, the shape of slice 30's second reading): writes `second.md` for a blind second
   reader from a marked `review.md`: only the units the first reader marked `Does not support`, `Partly supports`,
   `Does not follow the rule`, `Stronger than the body` or `Does not match the page`, plus 5 units per sheet the first
   reader did not mark (seed-drawn, seed printed), with the first reader's marks NOT shown. Refuse when `review.md` has no
   marks. The unit ids stay identical so `score` can join them.
3. **`score --out DIR [--seeded RESULTS_JSON]`**: reads `review.md` (and `second.md` when present) and writes `human.json`
   and `results.json`. A unit is serious/negative when either reader marks it so; report the reader disagreement count.
   Per metric write value, denominator, status, sample description (whole or drawn, seed) and reader(s), exactly the four
   things the expectations file's reading rule 5 asks for. It never compares to the expectation ranges and prints no
   verdict (the expectations file says the comparison is made by hand in the results document); do not hard-code any range.
   `results.json` also holds the automated parts from `automated.json` so one file carries all eleven rows. A row whose
   reader marked fewer units than the sheet lists says so (`judged` vs `total`), and an unmarked sheet is `not_measurable`
   with reason `not_read`, not zero.
   - **R10 interface (P15 is not landed; do not touch its files):** `--seeded` takes a JSON file that is either a list or an
     object with a `cases` list; each entry whose `id` starts with `RS` counts as one seeded fault. Recognised optional
     fields: `review_caught` and `assembly_caught` (true, false or null), `seeded_fault`, `task`. The kit computes
     the review and the assembly catch counts separately (each over its readable entries, and also stated over all `RS` entries) and `neither` (both false). Readability is
     decided per ratio: for the review ratio an entry is readable when `review_caught` is true or false, for the assembly ratio when
     `assembly_caught` is; an entry unreadable for a ratio is `unscored` for that ratio, and each ratio carries its own readable
     count and `partial` flag (`neither` uses entries readable for both). Write the total `RS` count, the readable count and the unscored count on separate
     lines; the ratios are `caught / readable` and each carries `partial: true` when any entry is unscored for it (no silent change of the
     denominator). Fewer than 6 readable entries, no `RS` entries or no file gives R10 `not_measurable`. The field mapping is a
     proposal until P15's real output is checked against it; the run session confirms it by reading P15's file before scoring and
     records that in `protocol.md`. Write the accepted shape into the module docstring so P15's output can be
     reconciled to it later; do not guess P15's real field names beyond these.

## Tests (pytest; no model, no network)

`tests/test_p6_measure_report.py`, using the existing report test helpers (`test_report_export.py::complete`,
`test_report_api.py::upload_and_include/create_table/fill_table`, `test_report_flow.py::ReportAdapter/report_flow`,
`test_api_flow.py::app_for/create/session/wait_run`) to build a real stored fake-adapter report, then running the kit's
functions against `TestClient`:

- `snapshot` on a valid fake report writes the three files, the sample is deterministic for a fixed seed, `automated.json` has all eleven metric rows with a status each, and a metric with a zero denominator is
  `not_measurable` (not 0).
- The R2 sample takes all claims when there are fewer than `--sample`, every link of a sampled claim is its own unit, and the
  sheet lists each cited quote. The seed-difference assertion (another seed gives another sample) runs only on a set with more
  eligible claims than `--sample` (use a small `--sample` on the fake report); with fewer eligible claims the sample is all claims
  for every seed.
- A report with an unmatched anchor (build one by editing the stored link through the store, not by hand SQL against a
  schema you have not read) shows up in the link checks.
- R3 finds a seeded English and a seeded Turkish negative sentence and ignores a positive one.
- `--db` absent gives R8 and token counts `not_readable` with a reason; `--db` present (copy the test app's SQLite to a
  temp file first) gives R8 numbers from a seeded `report_phrase_repairs` row set, and the file is not modified.
- `second` refuses an unmarked sheet, never prints the first reader's marks, and its unit ids match the first sheet.
- `score` on a hand-marked sheet gives the expected counts, treats an either-reader-serious unit as serious, reports
  disagreements, and returns `not_measurable`/`not_read` for an unmarked sheet.
- `--seeded`: a list-shaped file, an object-shaped file, `unscored` entries (`partial: true`), fewer than 6 readable entries, a
  file with no `RS` entries, and no file.
- An in-progress or draft report: only R1 and R7 measured, the rest `not_measurable` with `run_incomplete`.
- The kit never issues a non-GET request to the app (assert on the transport's recorded methods) and never writes to the
  `--db` path.

## Checks to run

- `PYTHONPATH=backend:. uv run pytest tests/test_p6_measure_report.py` and then the full `PYTHONPATH=backend:. uv run pytest`
  (one known failure is accepted: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a
  test that fails under parallel load but passes alone: rerun it alone and say so). `UV_CACHE_DIR=/tmp/deixis-uv-cache` if
  the default cache is not writable.
- `python -m py_compile scripts/p6_eval/measure_report.py`. No web change, so no build or Playwright.

## Report back

What you built, what the API and the database could and could not show (the `not_readable` list with reasons, so the run
prompt can name it), every own-judgement decision, and anything in the expectations file that the kit cannot fill in as
written (name the row and the reason). Do not invent; report what you could not find.
