<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: 3 high (guidance allowed silently dropping an unsupported claim; test 5 contradicted persistence of an invalid section; test 4 assumed a whole-passage quote is always rejected), all folded in (insufficient_evidence entry required for a removal, raw_output check, passage-length quote test), plus 1 medium (reason display edge cases, test 7a); r2 not run, the fixes are Sol's own corrections; code review r1: 1 high (D129 recorded the sandbox-blocked browser run as unverified; fixed by running build, lint and Playwright outside the sandbox and viewing the screenshots), 0 other -->

# Task: P6 slice 1, batch P19, targeted anchor repair in report sections, and the failed section's reason on screen

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p19` (detached at `9f42a95`, main with D128). Read
`AGENTS.md`, `CLAUDE.md`, `.impeccable.md` (before touching `apps/web`), `docs/decisions.md` D121, D122, D127, D128 (top),
and `docs/product/p6-slice1-report-results-run3.md`. The scope below was decided by the main session with gpt-6.1-sol
and binds this prompt; where the code differs from what this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find. **No real-model calls. No measurement.** Do not touch
`../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and
8858-8864. Backend tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. For the web build and
Playwright the worktree needs `apps/web/node_modules` (symlink from `../DEIXIS/apps/web/node_modules` if absent;
remove the symlink at the end; say so).

## Why

The third and last P16 real-model run stopped at section IV on `anchor_not_in_cell_evidence`, in the first call and
again after the one schema repair (D128). The check (`domain/contracts.py::_check_report_section`) requires the quote of
an anchor that names a cell to be located in one of that cell's stored evidence quotes. The repair message
(`models/prompt.py::repair_message`) already sends the error codes and the whole StepInput, cell quotes included, but
nothing pairs the failing anchor with the allowed quotes of THAT cell. Separately, a failed section's stored reason
(D121 keeps it in the run's `error_json`, and the section's own `validation_json`) is not shown on screen, and an
assembly-only refusal shows `DRAFT: 0 sections not validated` without naming the rule (D122 Limits).

## What is and is not in code (checked on 9f42a95)

- `flow.py::_model_step` (around line 4725): after an invalid output, `repair_issues` holds the issues and the next
  attempt sends `prompt.repair_message(shown, issues_with_handles(...))`; `MAX_SCHEMA_REPAIRS = 1`
  (`domain/rules.py`), so a report section gets exactly one repair; after it, `after_invalid_output` ends the step
  `failed` / `invalid_model_output`. The resolved output of the failed attempt is `output_text` (real ids). D56 salvage
  is `grounded_answer` only; reports have none (D127).
- `sections.py::_run_section` stores a failed section with `validation.issues = output["issues"]` (each
  `{code, path, message}` for an invalid output, or `{code, detail}` for an optional-step failure), and
  `_pause_detail` puts `{sections, reasons: [{section_id, code, detail}]}` in the paused run's `error_json`.
  `run_report` finalises an assembly-refused report as `draft` and stores the assembly issue list
  (`[{rule, section_id, detail}]`, warnings included: a `*_warning` rule whose detail starts `WARNING:` is not an
  error) as the run's `error_json`.
- `views.py::report_view` returns `sections[].status` and `sections[].validation`; `run` is only `{id, status,
  pause_reason}`. `apps/web/src/report/ReportView.tsx` shows `This section was not validated and must be written
  again.` for a `draft`/`failed` section and the header `DRAFT: {n} sections not validated` where n counts
  non-valid sections (0 for an assembly-only refusal). `Transcript.tsx` (line ~331) shows `{section}: must be written
  again` or `{section} failed` with no reason. `report/export.py` line ~198 writes the same draft line to Markdown.
- `report.md` (`methods/deixis-research/references/report.md`) line 25 already says a cell anchor quotes one of that
  cell's stored evidence quotes. `skill_package_hash` today: `sha256:52775258...81ac`.

## Decisions (already taken; do not reopen)

1. **Specialise the EXISTING single repair; nothing new.** No new model call, no resume, no salvage, no extra repair
   round, no change to `MAX_SCHEMA_REPAIRS`. If the repaired output still fails the check, the section stays failed
   exactly as today. No validator is loosened; `_check_report_section` and assembly's `_check_anchors` stay as they are.
2. **Repair context, built in code from the stored StepInput and the failed output.** Add to `domain/contracts.py` one
   function, for example `report_section_anchor_repair_context(step_input, draft, issues)`, returning, for every
   issue with code `anchor_not_in_cell_evidence` whose path is `/citation_anchors/{i}/quote` and whose anchor names a
   cell of the step's real allowlist, one entry: the anchor index `i`, that anchor's `claim_key`, the `cell_id`, the
   quote the model wrote, the cell's allowed quotes (each stored evidence `quote` of THAT cell in the StepInput, with
   its `passage_id`), and the claims of the failed draft that cite that cell (`claim_key`, `text`). It reads only the
   StepInput and the failed draft; it adds no evidence, no cell, no quote that is not already in the StepInput. It
   returns nothing for any other issue code, for another task, for an anchor whose cell is not allowlisted, or when
   the draft is not a dict with a `citation_anchors` list (fail closed: no guidance rather than a guess).
3. **Shown with handles.** The context is displayed with the same short handles as the rest of the message
   (`cel_L`, `psg_P`; D127's `report_citation_handles`), so no real id reaches the model. `prompt.repair_message`
   gets an optional argument (the context) and, only when it is non-empty, appends one block after the issue list:
   the per-anchor pairs as JSON and a fixed instruction text. `flow.py` passes the context only when
   `task_type == "report_section"` (the `_model_step` path at ~4730); every other task's repair message stays byte for
   byte what it is today. The instruction text (English, a module constant in `prompt.py`) says, in substance:
   for each failing anchor, the quote must be copied exactly from one of the allowed quotes of the SAME cell named in
   that pair; a quote from any other cell, or a whole passage, is not allowed, and a cell anchor is never a whole
   passage; **a quote that is found does not show that the claim is supported**: use a quote only if the claim says no
   more than that quote states; otherwise rewrite the claim so it says only what a stored quote of that cell states,
   or remove that cell citation (and its anchor) from the claim; if the claim is then left without support, it may be
   removed from `claims` only together with an `insufficient_evidence` entry that names that claim (its `claim_key`)
   and says why it was removed, so the removal is visible in the stored section; never swap in a quote only to pass
   the check; do not cite ids outside the allowlist. (Sol plan review r1, finding 1.) The guidance does not say a
   whole passage is rejected by the validator: the validator only requires the quote to be located in one stored
   cell quote, and this batch does not change that; the text only tells the model not to use a passage as a cell anchor.
4. **Method text.** Add one short rule to `methods/deixis-research/references/report.md` next to line 25: a located
   anchor does not prove support; if no stored quote of the cited cell supports the claim, rewrite the claim or drop
   the cell citation; a quote of another cell or a passage is never a substitute. Keep frontmatter and relative links
   valid; one dated sentence (30 September 2026, P19) in the `report.md` entry of
   `methods/deixis-research/provenance.json`. **Report the old and new `skill_package_hash`** (get the new one with
   `load_skill_package().package_hash`); update tests that pin the hash or embed the package text, only for that
   reason.
5. **Not allowed, in any form:** attaching an arbitrary valid quote to a claim in code (code never chooses or swaps a
   quote), using a whole passage as a cell anchor, widening the evidence set or the allowlist, silently deleting a
   claim or anchor in code, loosening any validator, a second repair, resume or salvage for reports.
6. **The failed section's reason in plain words, on screen.** Add to `apps/web/src/labels.ts` one helper (style of
   `failedRowReasonText`, strings through `t()` and `i18n.ts` Turkish entries) mapping the codes a section can store
   to a plain phrase, with the code-with-spaces fallback for unknown ones. At least: `anchor_not_in_cell_evidence`
   (a quote the model cited was not found in the stored evidence of that table cell), `anchor_not_in_passage`,
   `unknown_passage_id`, `unknown_cell_id`, `unknown_source_id`, `unknown_column_id`, `empty_section`,
   `model_mismatch`, `invalid_model_output`, and the codes of a schema failure if they occur in stored sections
   (read `_model_step` and the contracts to find them; do not guess). Show it (a) in the timeline line of a failed or
   must-be-rewritten section (`{section} failed: {reason}` / `{section}: must be written again: {reason}`) from
   `run.error.reasons` for that section (first reason), and (b) in the report sheet's section notice from the section's
   own `validation.issues[0]` (`code`). No raw id, no quote text and no model-written text is shown: only the
   plain-word reason. A section with no stored reason keeps today's text. Keep it short; follow `.impeccable.md`; no
   new component if the existing `Notice` and timeline line serve.
7. **Assembly-only draft header names the rule.** `report_view`'s `run` gets the run's parsed `error`
   (only when it is the assembly list) and `ReportView.tsx` shows, when status is `draft` and the count of non-valid
   sections is 0, a header that names the refused assembly rules in plain words (for example `DRAFT: the assembly
   check refused the report (banned word)`), from the error entries that are errors (not a `*_warning` rule with a
   `WARNING:` detail), deduplicated, in order, at most three then `and {n} more`. The non-zero count header stays
   as is. Map a few known assembly rules to plain words (`banned_word` at least) with the rule-with-spaces fallback.
   `report/export.py` writes the same sentence for that case so the Markdown follows the screen; the existing
   `DRAFT: {n} sections not validated.` line is unchanged when n is not 0.
8. **Scripted support for the browser case.** `tests/acceptance/fixture_server.py` gets one marker,
   `[report-bad-anchor]`: section IV returns its usual cell claim but its anchor quote is a string that is in no
   stored quote, in every call including the repair (so the section fails `anchor_not_in_cell_evidence` after its one
   repair). Document the marker in the file's header comment like the other two.

## Files allowed

`backend/deixis/domain/contracts.py`, `backend/deixis/models/prompt.py`, `backend/deixis/workflow/flow.py` (the repair
message path only), `backend/deixis/workflow/views.py` (`report_view` run dict only), `backend/deixis/workflow/report/export.py`
(the draft line only), `methods/deixis-research/references/report.md`, `methods/deixis-research/provenance.json`,
`apps/web/src/labels.ts`, `apps/web/src/i18n.ts`, `apps/web/src/Transcript.tsx`, `apps/web/src/report/ReportView.tsx`
(+ `report.css` only if truly needed), `apps/web/src/api.ts` (types only), `tests/acceptance/fixture_server.py`,
`apps/web/e2e/report.spec.ts`, new or extended tests under `tests/` (for example `tests/test_report_anchor_repair.py`,
`tests/test_report_api.py`, `tests/test_report_flow.py`; any existing test that must change, say which and why),
`docs/decisions.md` (D129 at the top), `docs/product/p6-slice1-handoff.md` (one line in "Partiler", style of the P17
line, ending `commit: bu satırı ekleyen commit`), and this prompt's comment line.

## Files NOT allowed

`backend/deixis/workflow/report/{sections,assembly,plan,review,store,...}.py` other than the export line (if a reading
proves a change there is needed, stop and report), `contracts/` schemas, `tests/fixtures/research/`,
`storage/migrations/`, fill/answer/discovery behavior, `scripts/`, validators' acceptance rules.

## Tests to add (name them so the limit is readable)

1. **Context content.** From a real report-section StepInput with two cells with different quotes and a failed draft
   whose anchor 0 cites cell A with a quote found in no quote: the context has one entry with cell A's allowed quotes
   only (none of cell B's), the failing quote, the citing claim; nothing for an anchor that is fine; nothing for other
   issue codes (`anchor_not_in_passage`, `unknown_cell_id`); nothing when the cell is not allowlisted or the draft has no
   `citation_anchors` list.
2. **Message.** The repair message of the second attempt (through the scripted model in `_model_step`) contains the
   guidance text, the pair with handles, no real cell/passage id anywhere, and the statement that a found quote is not
   proof of support and that nothing may be swapped blindly; a `grounded_answer`, `cell_extraction`, and a
   `report_section` repair for a non-anchor issue send the same message as before (equality with the old builder).
3. **Repair bound.** A scripted model that fails the anchor check in both calls: exactly 2 calls, the section ends
   `failed` with `anchor_not_in_cell_evidence`, the run pauses `section_failed` with `reasons` carrying the code, no
   claim is stored, no third call, no resume. A scripted model that fixes it in the repair: the section is valid.
4. **Wrong cell / wrong quote rejected.** After the repair a quote taken from another cell's evidence, a quote found
   in no cell, a passage id and a cell id on one anchor, and a passage-length quote (build the passage text longer than
   the cell's stored quote and containing text outside it, so the quote is located in no stored cell quote) all stay
   rejected with the existing codes; the validator and assembly behave as before (existing tests untouched). Do not
   assert that a quote equal to a stored cell quote is rejected: it is located and passes, as today.
5. **No code-side swap.** The stored model session `raw_output` of both calls is what the model wrote; the failed
   section's `draft` is `None` and it has zero stored claims and zero citation links (current behavior: an invalid
   output never reaches `save_claims`); do not change persistence to satisfy this test.
5a. **Guidance text.** A test on the constant: it tells the model that removing an unsupported claim requires an
   `insufficient_evidence` entry naming it, that a found quote does not prove support, that a quote of another cell or
   a passage is not allowed, and that nothing is swapped in only to pass.
6. **Reason visibility (API).** `report_view` of the `[report-bad-anchor]`-style stored failed section carries
   `validation.issues[0].code == "anchor_not_in_cell_evidence"`; the run dict carries the assembly `error` for an
   assembly-only draft; export's draft line names the rule for n = 0 and is unchanged for n > 0.
7. **Playwright** (`report.spec.ts`, own port not among those in use: read the file and pick a free one, for example
   8804): a report with `[report-bad-anchor]` ends paused `section_failed`; the timeline shows `IV failed:` with the
   plain reason and the sheet's section notice shows the plain reason; no quote or id text appears; Copy/Download
   stay disabled. In the existing banned-word case add an assertion that the header names `banned word`. Screenshots
   1440 and 390, light and dark, of the new states; look at them.
7a. **Reason display edge cases (label/API/export tests, English and Turkish).** A stored `message`/`detail` that
   contains a real id or model-written text never appears on screen or in export (only the mapped plain phrase); a
   section or run with no stored reason keeps today's text; assembly warnings (`*_warning` with `WARNING:`) are not
   named in the header; repeated rules appear once; with more than three rules the header says `and {n} more`; an
   unknown code falls back to code-with-spaces.
8. `skill_package_hash` differs from `sha256:52775258...` and the integrity check passes.

## Checks to run

`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one known failure:
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `cd apps/web && npm run build
&& npm run lint` (17 warnings baseline, no new ones) and Playwright against a fresh build
(`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p19 npm run test:acceptance`; 109 today plus the new case), `git diff
--check`. Report every count. If a tool cannot run in your sandbox, say so; do not skip silently.

## Decision record

`## D129 — Report sections: the one repair pairs each failing cell anchor with its own cell's quotes, and a failed section's reason is shown`,
with Status/Date/Context/Decision/Limits. Limits must say: synthetic fake and scripted models only, no real-model call, no
measurement; the repair guidance changes a prompt, so whether it lowers real-model anchor failures is unmeasured; a
success on the known corpus later would not be independent validation (the fix was developed after seeing that corpus's
failure); a located anchor still does not prove the claim is supported (assembly and the model review check only
location and wording, not meaning); `anchor_not_in_passage` and other codes get no specialised guidance; the series
closed by D128 stays closed and this is not a fourth attempt; old and new `skill_package_hash`; the open question of a
real-model acceptance for the report stays open. Add nothing about results you did not measure.
