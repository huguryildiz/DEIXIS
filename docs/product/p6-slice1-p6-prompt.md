<!-- Plan review: gpt-6-sol high, round 1: hazir degil (2 high, 5 medium, 1 low), all folded in below (decisions 4, 5, 7, 11-14); round 2: hazir degil (1 high, 2 medium), folded in (decisions 15-17); round 3: düzeltmeyle hazır (1 high, 1 medium), folded in (decision 18); no round 4 (plan limit). -->

# Task: P6 slice 1, batch P6 — Section VIII's numeric core, written by code from the frozen snapshot

Repo: the git worktree you are started in (`-C`). All paths are relative to it. Plan: `docs/product/p6-slice1-report-run.md`
section 1e, Task 2 (line ~1946) and §3 of the design note ("VIII = code + model").

## What is in code today (checked on HEAD 8a829b0)

- `backend/deixis/workflow/report/review_methodology.py` writes **II** entirely from the frozen `snapshot["corpus"]` and
  the recorded steps, with two fixed templates (`en`, `tr`), and saves `{"text": ...}` with validation
  `{"ok": True, "issues": []}`. The same numbers exist only inside that prose.
- `sections.py::_run_section` runs **VIII** as an ordinary model section (round 4 of `ROUNDS`). Its `report_target`
  carries `plan.corpus` (the four-plus-one corpus counts) but no VIII-specific core; `selection.py::select_evidence` has **no branch for VIII** (it returns nothing for it by falling
  through, unnoticed). `limitations_core` does not exist anywhere (`grep -rn limitations_core` is empty).
- Every model-written section (III–IX; not II) already stores `validation_json["truncated"]` = the list of `{source_version_id, record_kind}`
  records that `select_evidence` omitted (record_kind `passage` and `cell` are budget cuts; `cell_missing_evidence` is a cell whose evidence passage was not found, a different failure) (`sections.py`, four save sites). The handoff's "no place for
  the truncation record" is out of date: the place exists; what is missing is the count shown in VIII.
- `assembly.py` rule 7 (`_check_corpus_counts`) reads label words in the `draft.text` of II and VIII with regexes.
  **Do not change assembly.py in this batch** (batch P7 replaces rule 7 by reading structured numbers).
- `report_phrase_repairs` (migration 0035) holds one row per repair with `outcome` in
  `kept | reverted_exception | unframed_exception`.
- `apps/web/src/report/ReportView.tsx` line ~149 shows `section.draft.text` for `id === 'II'` only.
- `report_target` in `contracts/research/step-input.schema.json` (required: report_id, section_id, columns, plan,
  cells, gap_candidates, prior_summaries, repair_request, review_scope, `additionalProperties: false`).

## Decisions taken (the plan's own default; do not reopen)

1. **Structured numbers live in `report_sections.validation_json["numbers"]`**, no migration. Shape, versioned:
   `{"version": 1, "kind": "review_methodology" | "limitations", ...}`. II stores the corpus counts it printed
   (`corpus`: found, unique, screened, included, full_text; `full_text_ratio`; `fetch_pdf`; `pdf_other_copy`).
   VIII stores its core (below). Batch P7 will read these instead of parsing prose; this batch does not change rule 7.
2. **The prose is rendered from the structured dict by one function per kind** (`render_review_methodology(numbers,
   ...)` and `render_limitations(numbers, language)`), so text and numbers cannot drift. II's rendered text must stay
   byte-identical for the existing test inputs (refactor the format call, keep `_TEMPLATES`, `_CHAIN_TEMPLATES`).
3. **VIII = code numbers + model prose.** Before the VIII model call, code computes `limitations_core` and puts it in
   `report_target["limitations_core"]`. After the model call (status valid or draft), code adds the rendered numeric paragraph to the stored draft as `draft["text"]` and stores
   `validation["numbers"]`. The model's claims stay in `draft["claims"]` untouched; `draft["text"]` is written by code
   after validation and phrase repair, never sent to the model, and not counted in `word_count` (assembly's word budget covers model prose only; the
   paragraph is one short sentence per item, and this is a limit for the decision). **When the VIII step fails**
   (`failed`, `draft` stays `None`) code still stores `validation["numbers"]` (the numbers are model-independent) but
   writes no `text`.
4. **`limitations_core(store, reports, report_id, snapshot)` -> dict** (the plan's signature took `phrase_repair_stats`;
   compute it inside from `report_phrase_repairs` instead of a parameter, because the caller has no other source). Keys:
   - `recall_measurement`: `None` (no known-set measurement exists in the app; do not invent one).
   - `open_access_bias_note`: `True`.
   - `no_full_text_share` (renamed from the plan's `summary_to_full_text_ratio`, which named something the snapshot
     does not measure): `(included - full_text) / included`, `0.0` when `included == 0`; also `included` and
     `full_text` counts. The rendered text says "included sources with no PDF text", never "read only from the abstract".
   - `analyst_inference_share`: `{"analyst_inference": n, "total": m, "share": n/m or None}` over the claims of
     sections III–VII whose status is `valid` at the time of the call (the plan said "after assembly"; VIII runs
     before I/IX/abstract, and those are derived claims, so the share is stated over III–VII and says so in the text).
   - `kill_search_status`: `"not_run"`.
   - `phrase_repair_exceptions`: `{"repaired": kept, "reverted_exception": n, "unframed_exception": n}` counted from
     `report_phrase_repairs` of this report for sections III–VII, **one row per (section_id, sentence_id): the latest**
     (`save_phrase_repair` appends on every re-run, so raw counting would double count). The numbers are as of the
     moment VIII is written; a later `report_review` revert (batch P9) does not update them; say so in the numbers
     (`"as_of": "before_viii"`) and the decision's Limits.
   - `truncation` (the deferred truncation record): `{"budget_cut": ..., "missing_evidence": ..., "by_section": {...}}` (the one and only shape; no `records` field)
     from the `validation["truncated"]` of the sections III–VII already saved. Budget cuts (`passage`, `cell`) and
     missing evidence (`cell_missing_evidence`) are counted apart: `{"budget_cut": total, "missing_evidence": total,
     "by_section": {"III": {"passage": 2, "cell": 1, "cell_missing_evidence": 0}}}`; sections with none are omitted.
     VIII's own selection cuts nothing (decision 6).
   - `items`: the ordered numbered list the model may reference (methods `report.md` line ~97 promises "the section's own
     numbered list, given in your input"): `[{"number": 1, "key": "no_full_text_share", "text": "<rendered sentence in
     the report language>"}, ...]`, one item per key above except `recall_measurement` when `None` (still one item
     saying no recall measurement exists). `render_limitations` renders exactly these items.
   All values are plain JSON numbers/strings/bools/None; the dict is the same object stored as `numbers` (plus
   `version`, `kind`, `as_of`, and the `corpus` counts copied from the snapshot so the stored numbers are complete).
5. **Truncation decision:** keep `validation_json["truncated"]` as the store (already written per section, survives
   resume, visible in the section view through `validation`). No new table. VIII shows the total and per-section counts
   in its rendered paragraph, so a reader sees that records were cut. Record this in the decision.
6. **`selection.py` gets an explicit `VIII` branch** that selects nothing (the section is written from the numeric
   core and prior summaries; limitation *claims from sources* belong to VI). It must not add passages or cells and
   must record no truncation. Add the branch with a comment saying so, and a test.
7. **Schema (and who builds the target):** `report_target.limitations_core`: `object | null`, added to `required`. It is an object only for
   section VIII, `null` for every other task and section. `additionalProperties` inside it: `false`, with the keys of
   decision 4 (define them; `analyst_inference_share.share` and `recall_measurement` nullable). Update
   `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/fakes.py::valid_response`, every place in backend
   and tests that builds a `report_target` dict (`grep -rn "repair_request" backend tests scripts` finds them), and add
   a semantic check in `domain/contracts.py::check_step_input`: `limitations_core` non-null iff `task_type ==
   "report_section"` and `section_id == "VIII"` (issue code `limitations_core_mismatch`).
11. **Central default:** `flow._model_step` sets `limitations_core` to `None` when a caller's `report_target` lacks it
    (`report_target = {"limitations_core": None, **report_target}` before the StepInput is built), so `phrasing.py`
    and every existing caller stay unchanged; `run_report`'s plan target and `_run_section` set it explicitly.
12. **Phrase-repair counts** are as of the VIII write (decision 4); no recount later.
13. **Rule 7 wording:** the rendered VIII paragraph may print counts with the words the rule knows (`found`, `unique`,
    `screened`, `included`, full-text forms) only with the corpus's own numbers; percentages and other counts must not
    sit next to those label words (rule 7 reads `N included`-style pairs). Test it through `run_assembly_checks`.
14. **Truncation wording:** "cut for the budget" only for `budget_cut`; missing evidence is worded as "a cell's evidence
    passage was not found".
15. **VIII claims may not restate the core (deterministic, in `contracts._check_report_section`, VIII only):** a claim
    text may contain digits only inside the forms `item N` / `öğe N` / `madde N` (a reference to the numbered list);
    any other digit is an Issue `limitations_number_restated` (goes into the existing bounded repair like other
    semantic issues). A VIII claim with `support_type == "source_stated"` and empty `passage_ids` and `cell_ids` is an
    Issue `source_stated_without_evidence` (VIII gets no evidence records, so it can only write `analyst_inference`
    or cite prior claims by `body_refs`). Tests for both, plus that II/other sections are unaffected. Use the fake
    adapter's VIII claim text without digits so existing flow tests keep passing.
16. **The `report.md` mismatch:** the loaded method text still says "summary-vs-full-text ratio". The rendered item says
    "included sources with no PDF text". Do not edit `methods/` (it moves `skill_package_hash`); record in the decision's
    Limits that `report.md` line ~97 should say "share of included sources with no PDF text" in a later methods change.
17. **Truncation shape** is decision 4's single shape; `numbers["truncation"]` and the schema use it.
18. **VIII may only write `analyst_inference`:** `plan.py::ALLOWED_SUPPORT["VIII"]` becomes `("analyst_inference",)`
    (plan.py is allowed for this line only; update `tests/test_report_plan.py` if it pins the old tuple). The fake
    adapter in `tests/test_report_flow.py` (and any scripted acceptance responder that writes VIII) must write VIII
    claims as `analyst_inference`, so the full-flow test keeps passing. The digit rule of decision 15 catches digits
    only; a number written in words is not caught. State that as a limit in your final message; it is not an absolute ban.
8. **No `methods/` change.** `references/report.md` already says the application writes VIII's numeric core and the
   model must not restate the numbers. `skill_package_hash` must not move; if you find you must edit `methods/`, stop
   and report instead.
9. **Web:** show `section.draft.text` for VIII the same way as II (one condition change in `ReportView.tsx`), placed
   before VIII's claims. The `ReportSection` draft type may need `text?: string` for VIII; reuse what II uses.
   No other UI change, no new i18n strings.
10. Language: `report["language"]`, else the scope's `language_hint`, else `en` (as II does); two fixed templates
    (`en`, `tr`) for the VIII paragraph, in `review_methodology.py`.

## Files

Allowed: `backend/deixis/workflow/report/review_methodology.py`, `sections.py`, `selection.py`;
`backend/deixis/workflow/flow.py` and `domain/contracts.py` only for decisions 7, 11 and 15; `backend/deixis/workflow/report/plan.py` only for decision 18; `contracts/research/step-input.schema.json`;
`tests/…` (new and existing report tests, fixtures, `tests/fakes.py`); `apps/web/src/report/ReportView.tsx` and its type file;
`apps/web/e2e/report.spec.ts` only if its scripted report needs to assert VIII's paragraph.
Not allowed: `assembly.py`, `phrasing.py` (read only; its `report_target` gets `limitations_core: None` through decision 11), `report/store.py` (unless a read helper is unavoidable; say so),
`methods/`, migrations, `docs/decisions.md`, the handoff, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`.local/`, anything under `../DEIXIS-s30`, ports 8858–8864 and 8765. The orchestrator writes the decision.

## Tests to add or extend (FakeAdapter only; no real model call)

- `tests/test_report_review_methodology.py`: II stores `validation["numbers"]` equal to the counts in the printed
  text; `limitations_core` on a fixture with known counts (ratio, analyst-inference share over valid III–VII claims,
  phrase-repair outcome counts from `report_phrase_repairs`, truncation counts by section and kind, `kill_search_status`,
  `recall_measurement is None`); `render_limitations` in `en` and `tr` contains every number of the dict.
- `tests/test_report_selection.py`: VIII returns no passages, cells or truncation.
- `tests/test_report_step_input.py` / `test_contracts.py`: `limitations_core` required; non-null only for VIII;
  a mismatch is `limitations_core_mismatch`; schema accepts the VIII shape.
- `tests/test_report_flow.py`: a full run — the VIII step input carries `limitations_core` (others carry `None`);
  VIII's stored draft has `text` and `validation["numbers"]["kind"] == "limitations"`; its numbers match
  `reports.snapshot(...)["corpus"]`; a section III whose evidence the budget cut (force a tiny budget or seed
  `validation["truncated"]`) shows up in `numbers["truncation"]`; assembly still returns no error for the run (rule 7
  reads VIII's text: the rendered paragraph must pass it — do not change the rule, choose wording that does, and add
  a test that a mismatching stored number in VIII text is still caught); a resumed run does not recompute VIII's
  numbers into a second section or call the model again.
- `tests/test_report_api.py`: the report view's VIII section exposes `draft.text` and `validation.numbers`.
- Web: extend `report.spec.ts` only enough to see VIII's paragraph in the report sheet.

## Checks to run in the worktree

`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (full; the only accepted failure is the known
memory-limit one; name any other and rerun it alone). In `apps/web`: `npm ci` (or link node_modules), `npm run build`,
`npm run lint` (17 warnings today, no new one). Do not run Playwright; the orchestrator does.

## Rules

- No git state-changing commands (no add/commit/stash/checkout/reset); leave everything uncommitted.
- Do not invent: if a file, table or function named here is not what this prompt says, report what you found and take
  the smallest consistent choice; list it in your final message.
- Simplicity: no new tables, no new abstractions beyond the two render functions and `limitations_core`.
- Final message: files changed, test counts, every choice you made that this prompt did not fix, anything left open.
