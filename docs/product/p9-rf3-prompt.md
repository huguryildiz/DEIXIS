<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 3 medium + 1 low, folded in; r2: düzeltmeyle hazır, 1 medium + 1 low, folded in; r3: hazır. -->

# Task: P9 batch RF3: an empty report section becomes a semantic validation issue (JSON Schema unchanged), so the existing bounded repair asks the model once to write claims or name the missing evidence

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-p9rf3`, detached at `5c8cb98` (origin/main with D204 and D202 Ek C). Read `AGENTS.md`,
`CLAUDE.md`, D198, D202 and D204 in `docs/decisions.md`, `backend/deixis/workflow/report/sections.py:113-215`,
`backend/deixis/workflow/report/selection.py:120-140`, `backend/deixis/workflow/report/gaps.py`, `backend/deixis/domain/contracts.py:1936-2016`,
`backend/deixis/workflow/flow.py:5440-5690`, `methods/deixis-research/references/report.md:23-110` and `tests/test_report_flow.py:77-260, 766-781`.
Venv: `.venv` is a symlink to the main checkout's arm64 venv. Run tests with
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call,
no provider call, no network. Do not touch other `../DEIXIS*` worktrees (`../DEIXIS-h9*` are read-only evidence), `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `apps/web` (other batches own it), port 8765, the live data directory or the live `codex-home`. Decision number
**D206** (the orchestrator writes it). No migration, no contract (`*.schema.json`) change. Speed matters: H9b's arm B report may use this commit.

## Why

H9b arm A2 (D202 Ek C, `gpt-5.6-luna`, product `7cc1168`, run `run_Zjf9QhU911vTx2O7KmzX`) paused with `section_must_be_rewritten`,
`{"code":"empty_section","section_id":"VI"}`. Sections II to V were valid (IV through the RF patch path, accepted live after RF2). Section VI's
first output (session `mss_CThHztI2ODi1BIJBAHfE`, step input `sti_q2RozwnQE5H3V1Ug4ToM`) passed validation (`ok: true`, no issues) and was:

```json
{"schema_version":"deixis.report_section_draft.v2","section_id":"VI","claims":[],"citation_anchors":[],"subsections":[],"gaps":[],"insufficient_evidence":[]}
```

The product has no repair for this: `sections.py:180` computes `empty` after validation, `sections.py:194-198` stores the section as `draft`
and `run_report` pauses (`sections.py:295-297`). This is the fifth real-model report without completion (D124, D126, D128, D171, D202 A/A2).

**Why the model returned an empty section (read from the stored step input, read-only).** The stored records establish the input and the
validation; they cannot establish the model's reasons. The following is a plausible contributing explanation, not a proven cause:

1. *The input had no material for the only content VI is told to write.* The stored payload has `passages: []`, `sources: []`,
   `report_target.cells: []`, `report_target.gap_candidates: []`, and allowlist `cell_ids`, `passage_ids`, `source_ids`, `gap_ids` all empty;
   only `prior_summaries` (38 claim summaries of III to V) and the plan were present. Cause: the model-written plan set
   `limitations_column_id: null`, so the VI branch (`selection.py:135-140`) selects no cell; the frozen snapshot has 35 abstract-depth cells,
   14 selected-section cells and zero full-text cells, so `gaps.generate_corpus_absence_candidates` (needs at least 3 applicable full-text
   cells per axis, `gaps.py:15`) produces none.
   `allowed_support.VI` is `["analyst_inference"]`.
2. *The instructions point away from claims and give VI no "nothing to report" rule.* `report.md`'s VI bullet says "write the `gaps` array,
   not ordinary prose claims"; the only `insufficient_evidence` rule (`report.md:40-42`) covers a missing glossary term, axis or budget
   evidence. Nothing says a section must not come back with neither claims nor `insufficient_evidence` entries. V's summaries describe
   differences under different conditions and metrics; they do not establish a comparable conflict, so no supported `conflicting_evidence`
   candidate was evidently available either.
3. *The contract allows the empty answer.* The schema has no `minItems` on `claims` or `insufficient_evidence`, and
   `_check_report_section` (`contracts.py:1967`) has no emptiness check, so the existing bounded repair (`MAX_SCHEMA_REPAIRS = 1`,
   `flow.py:5442`, `rules.py:13`) never runs for it. The emptiness rule lives only after validation, in `sections.py`.

The same mode was seen once before on synthetic input: D123's behavior case RB03 (`report_section`, VI, empty axis) returned an empty section
with no `insufficient_evidence` entry. Note also that a VI with gaps but no claims counts as empty in `sections.py:180` too (gaps are not claims),
which conflicts with the "not ordinary prose claims" wording.

## Decisions taken (owner-level, agreed with gpt-6.1-sol medium in the review of this prompt)

**A. Make an empty section a semantic validation issue (smallest code change).** In `_check_report_section`, when `draft["claims"]` and
`draft["insufficient_evidence"]` are both empty, append `Issue("empty_section", "/claims", <message>)` for every `report_section` output
(every section, as `sections.py` does today). Message (it is what the repair call shows the model; keep it in one module-level constant):
"section has no claims or insufficient-evidence entries; write at least one claim supported by the given evidence, or one
insufficient_evidence entry naming the missing material and why; never invent a claim, passage, cell, gap or quote". The existing full
repair then gets its one permitted attempt, subject to the existing budget and transport gates (`flow.py:5498`): same step, attempt 1, `repair_issues` carrying `empty_section`, ordinary report-section schema (the anchor patch is not
eligible: `report_section_anchor_patch_eligible` accepts only `anchor_not_in_cell_evidence`). If the repaired output is invalid, the step ends
`invalid_model_output` as today, the section is stored `failed` with all its issues, and the run pauses `section_failed`; the pause shows only
the first issue (`sections.py:103`). For a repair with a valid envelope whose only issue is still emptiness, that reason code is
`empty_section` (the web already labels it, `apps/web/src/labels.ts:113`); its pause `detail` is `null`, because semantic issues carry
`message`, not `detail`. Schema or envelope issues can come first in other cases. This changes the final pause
reason for a twice-empty section from `section_must_be_rewritten` to `section_failed`; record that. No new model call type, no new step, no
new budget: the one repair is the existing `max_schema_repairs` slot.

**B. Keep the post-validation check in `sections.py` unchanged** as defensive protection (a validated model output can no longer reach it;
VIII follows the same validated path, its numeric text is added afterwards at `sections.py:191`). Do not remove or reword it.

**C. Instruction change in `methods/deixis-research/references/report.md`** (changes `skill_package_hash`; allowed, record old and new):
- In the shared section rules, next to the `insufficient_evidence` rule: a section answer must contain at least one claim or one
  `insufficient_evidence` entry; when the evidence you were given supports no claim for this section, write `insufficient_evidence` entries
  naming what was missing (for example no limitations cell, no candidate, no passage) instead of an empty answer; the application rejects an
  answer with neither.
- VI bullet: replace "write the `gaps` array, not ordinary prose claims" with wording that matches the code: write each candidate as a `gaps`
  entry; the section's prose is `analyst_inference` claims about those candidates, citing the same basis evidence the gap cites; `gap_refs`
  may name only ids from `report_target.gap_candidates` (a freshly minted gap id is rejected as `unknown_gap_ref`, `flow.py:5333`,
  `contracts.py:2002`). By kind: a `stated_limitation` claim cites the supplied, allowlisted limitations cells or passages
  its gap cites; a `conflicting_evidence` gap keeps the V claim keys in `basis_claim_keys`, and its claim cites source records only when
  such records were supplied (VI receives V's summaries without source ids). If no supported prose claim about a gap is possible, the
  model writes an `insufficient_evidence` entry alongside the gap. Minted ids never go into `gap_refs`. When `gap_candidates` is empty and no
  limitations cell or passage and no comparable V conflict was given, write no gap and record one `insufficient_evidence` entry saying which
  of these was missing. Do not change gap-reference policy in this batch. Keep the existing banned-word and
  "candidate, no kill-search" sentences unchanged.
- Nothing else in the method package changes. Update the tests that pin the package hash
  (`tests/test_lineage_columns.py:293`, `tests/test_report_path_fix.py:393`, `tests/test_report_failed_rows.py:363`, and any other the full
  suite finds) to the new hash, and say in the report which pins moved.

**D. Code never writes content.** No code-written claim, `insufficient_evidence` entry, gap or quote for an empty section; no code-chosen
"no evidence" outcome. The model writes the entry; code only rejects the empty answer and repairs once. D198's invariants hold: no silent
claim loss (`report_section_repair_issues` still runs on the repair), code never picks quotes.

**Rejected:** a schema rule ("one of two arrays non-empty" needs a root `anyOf` of two object variants, which D204's R4 forbids; a `minItems` on
`claims` alone would forbid the legitimate insufficient-evidence-only answer; and a schema change needs a new version); a separate repair call type for empty sections (more code, same
effect as the existing full repair); a code-recorded "no evidence for this section" outcome (code would assert something about evidence
that the model, which saw V's summaries, did not state).

## Files

Allowed: `backend/deixis/domain/contracts.py`, `methods/deixis-research/references/report.md`, tests under `tests/` (new
`tests/test_report_empty_section.py`, edits to `tests/test_report_flow.py` and the hash pins), one new fixture
`tests/fixtures/research/report-empty-vi-replay.json`. Read-only for this batch: everything else, in particular `sections.py`, `flow.py`,
`selection.py`, `gaps.py`, `contracts/research/*.schema.json`, `apps/web`. If you find one of these must change, stop and say why in the report.

## Tests (all model-free; every behavior-changing assertion must fail on `5c8cb98`; positive regression checks may pass on both)

1. **Replay fixture.** `tests/fixtures/research/report-empty-vi-replay.json`, labeled `"SYNTHETIC": "shape replayed from H9b A2 VI output
   mss_CThHztI2ODi1BIJBAHfE; no real text"`: the stored output above (with a synthetic but canonical `step_input_id`, the same `scope_revision` and a
   `skill_package_hash` equal to the input's, since direct validation checks the envelope, `contracts.py:910`) and a minimal VI step input carrying
   only what validation needs (task_type `report_section`, `report_target.section_id: "VI"`, empty `cells`, `gap_candidates`, `passages`,
   `sources`, the allowlist with only synthetic column ids, two synthetic V `prior_summaries`, `allowed_support.VI = ["analyst_inference"]`,
   `limitations_column_id: null`). Test: `validate_model_output` on it returns `ok: false` with exactly one `empty_section` issue at
   `/claims` (old code: `ok: true`). Same input with one `insufficient_evidence` entry (synthetic context and reason) validates `ok: true`
   with no `empty_section` issue; with one valid `analyst_inference` claim and no anchors it also passes this check.
2. **Flow, repaired.** Use a local adapter in the new file (the existing `ReportAdapter` builds a VI gap from `cells[0]` and would raise
   `IndexError` with no cells, `tests/test_report_flow.py:138`), reusing `report_flow`'s setup, with a plan whose `limitations_column_id` is
   null and a VI responder that returns the empty draft (`gaps: []`) on attempt 0 and, on the repair (attempt 1), one `insufficient_evidence`
   entry whose reason follows a supplied VI phrasebank frame (so no phrase-repair session is added). Assert: VI's step input has no cells and no gap candidates; exactly two VI sessions; attempt 1's stored
   `user_message` contains the `empty_section` issue and its exact message (issues are appended to the user message, `models/prompt.py:96`,
   not to `payload_json`); the first session's `validation_json` holds the issue; VI ends `valid`; no claim, gap or anchor was written by code; the report
   completes (`valid`, or whatever the existing fixture's assembly gives for the other sections, asserted explicitly). Old code: one VI
   session and a `section_must_be_rewritten` pause.
3. **Flow, still empty.** Same, but the repair is empty too: VI is stored `failed`; assert its full stored issue list separately from the
   displayed first reason; the run pauses `section_failed` with reason `{"section_id": "VI", "code": "empty_section", "detail": null}`, exactly two VI sessions (bounded), no third call,
   no code-written content.
4. **Existing empty test.** `test_an_empty_section_without_insufficient_evidence_pauses_the_run` (`tests/test_report_flow.py:768`) and
   `test_report_rewrite_reason_uses_first_three_issues` (`:533`) use `empty_section=` (always empty, so also on the repair): update their
   expectations to the new path (`failed`, `section_failed`, issue code `empty_section`) or move them to a fixture that still reaches the
   `sections.py` guard; do not weaken what they check about the pause detail; the first-three-rewrite-reasons behavior must stay tested on a `draft` section
   (it edits stored issues by hand, so it can seed a `draft` section without going through the empty path). Say which you did.
5. **Instruction text.** A test that the loaded `report.md` contains the new shared rule and the new VI wording (exact key phrases), and no
   longer contains "not ordinary prose claims".
6. `tests/test_strict_schema_rules.py` stays green with no change (no schema changes in this batch). Run the report test files, the contract
   tests and the strict-schema test; the orchestrator runs the full suite.

## Report (to `/tmp/p9rf3-impl-report.md`)

Files changed with line ranges; the old and new `skill_package_hash`; each test and its old-code failure (run the new tests against a
`git stash`-free copy of the old files, for example by temporarily reverting your contracts edit in place, and show the failure lines);
the pins you moved; anything you could not do. Do not claim the fix makes a real model write VI; that is H9b's measurement.
