<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: 2 high (source ids outside `sources` in D125 failed_rows and review claim `count`; membership checks missing for section anchors, count, gap basis and nearest match), folded in as decisions 10 and 11; r2: 1 high (count source set inconsistent with the keep-valid-outputs rule), folded in by choosing shown-evidence sources only and stating the narrowing; r3 not needed (only the one high, fixed as Sol proposed); code review: 1 round, verdict hazır, 0 high -->

# Task: P6 slice 1, batch P18, short citation handles (D12) for the four report tasks

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p18` (detached at `5c0a4ab`, main with D126). Read
`AGENTS.md`, `CLAUDE.md`, `docs/decisions.md` D12, D56, D125, D126 (top and the D12/D56 entries), and
`docs/product/p6-slice1-report-results-run2.md`. The scope below was decided by the main session with gpt-6.1-sol
(option A after D126) and binds this prompt; where the code differs from what this prompt says it is, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find. **No real-model calls.** Do not touch `../DEIXIS`,
`.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864.
Tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`.

## Why

The second P16 report run stopped at section IV: the model copied the passage id `psg_FpnsupjsR0ckcocxc8rY` as
`psg_FpnsupjsR0ckcoc8rY` (two characters dropped), twice, so the section failed `unknown_passage_id` after its one
schema repair. The four report steps show the model the long raw ids (in run 2 the section IV input held 15 allowed
passages, 29 cells, 7 source versions, 7 columns). The answer, review and cell steps already show short per-step handles
(`psg_P0000001`, `srv_S0000001`, `col_C0000001`, D12) and map them back before validation. The report tasks do neither.

## What is and is not in code (checked on 5c0a4ab)

- `flow.py`: `HANDLE_TASKS` (line ~96) lists `grounded_answer`, `answer_review`, `cell_extraction`,
  `abstract_screening`, `fulltext_adjudication`; `_model_step` shows `contracts.with_citation_handles(payload)` for those
  and, after the call, resolves with `contracts.resolve_citation_handles(payload, output_text)` for a separate list
  (`grounded_answer`, `cell_extraction`, `abstract_screening`, `fulltext_adjudication`; `answer_review` is resolved at its
  own call site near line 4495). The four report tasks (`contracts.REPORT_TASKS`: `report_plan`, `report_section`,
  `report_phrase_repair`, `report_review`) are in neither list.
- `domain/contracts.py`: `citation_handles`, `with_citation_handles`, `issues_with_handles`, `resolve_citation_handles`
  (handles for passages, columns of `extraction_target`, candidates, sources; leading-zero normalisation via
  `PADDED_HANDLE`), `salvage_answer_draft` (D56, used only for `grounded_answer`).
- `flow._step_input` puts `report_target` (columns, cells with `cell_id`, `cell_revision_id`, `column_id`,
  `source_version_id`, evidence `passage_id`; `gap_candidates` with `column_id` and `basis_cell_ids`; `plan` with glossary
  `passage_id`, axes `column_id`, `limitations_column_id`, `future_work_column_id`; `review_sections[].claims[].citations`
  with `passage_id` / `cell_id`; `limitations_core.failed_rows[].source_version_id`) and an allowlist with `passage_ids`,
  `source_ids`, `column_ids`, `cell_ids`, `gap_ids` into the StepInput. Walk `contracts/research/step-input.schema.json`
  and the four output schemas (`report-plan`, `report-section-draft`, `report-phrase-repair`, `report-review`) to list
  every field that carries a passage, cell, source-version or column id; do not rely on this list being complete.
- Output id fields (from the schemas): plan `glossary[].passage_id`, `axes[].column_id`, `limitations_column_id`,
  `future_work_column_id`; section `claims[].passage_ids`, `claims[].cell_ids`, `claims[].count.numerator_source_ids`,
  `claims[].count.denominator_source_ids`, `claims[].count.column_id`, `claims[].equation_origin.passage_id`,
  `citation_anchors[].passage_id`, `citation_anchors[].cell_id`, `gaps[].basis_passage_ids`, `gaps[].basis_cell_ids`,
  `gaps[].nearest_match.source_id`, `gaps[].nearest_match.cell_id`. `report_phrase_repair` and `report_review` output
  carry only `sentence_id` / `claim_key` (already short) and no record id; confirm this by walking the schemas.
- Handle shapes must match the id patterns the schemas already use (`^psg_[0-9A-Za-z]{8,40}$`, `srv_`, `col_`, `cel_`):
  `psg_P0000001`, `srv_S0000001`, `col_C0000001` exist; add cells as `cel_L0000001`. No schema change is expected
  (handles fit the existing patterns and the stored StepInput keeps real ids), so no schema version, fixture or migration.

## Decisions (already taken; do not reopen)

1. **The four report tasks join both paths.** `report_plan`, `report_section`, `report_phrase_repair`, `report_review`
   are shown handles and their raw output is resolved back to real ids before `normalise_output` and
   `validate_model_output`. Prefer one report-specific pair of functions in `contracts.py` (for example
   `report_citation_handles(step_input)`, used by `with_citation_handles`/`resolve_citation_handles`/`issues_with_handles`
   for `task_type in REPORT_TASKS`) over changing the answer/cell behavior; the answer, cell, abstract and adjudication
   handle output must stay byte-for-byte what it is today (their existing tests are the check).
2. **Handles are numbered per step from the stored StepInput, in a fixed order, and are recomputed from the stored
   StepInput** (nothing new is stored): passages in `passages` order (`psg_P`), source versions in `sources` order
   (`srv_S`), cells in `report_target.cells` order (`cel_L`), columns in `report_target.columns` order and then any
   column id of the allowlist / cells / gap candidates / plan axes not yet numbered, in that order (`col_C`). A step
   never sees a handle from another step: numbers restart at 1 in every step, and nothing in the message may carry a
   handle computed for an earlier step.
3. **Field by field, both directions.** Shown (input): every field that carries a passage, cell, source-version or
   column id listed above and found by the walk, including `allowlist.passage_ids/source_ids/column_ids/cell_ids`,
   `report_target.cells[]`, `report_target.gap_candidates[]`, `report_target.plan` (glossary passage ids, axis and
   limitations/future-work column ids), `report_target.review_sections[].claims[].citations[]`,
   `report_target.limitations_core.failed_rows[].source_version_id`, `report_target.columns[]`. Resolved (output): the
   output fields listed above. **Left as they are:** `cell_revision_id` and every envelope field (`step_input_id`,
   `research_id`, `run_id`, `step_id`, `report_id`, `work_id`, `table_id`, `gap_id`), and the already short `claim_key`,
   `sentence_id`, `axis_id`, `rq_id`, `section_id`. `null` stays `null`; a value that is not a string is left for schema
   validation.
4. **A plan passage that is not allowlisted in this step gets a handle to read but no permission.** The plan the
   `report_section` / `report_phrase_repair` steps see may name a glossary passage that is not in this step's
   `passages` (it was chosen for the whole report). Such an id needs some display, and the raw long id is the very
   copy-error surface. Give it a handle numbered after the step's passages (continue the `psg_P` numbering in glossary
   order), so the model does not see a long id; it is **not** put in the shown `allowlist.passage_ids`, and after
   resolution the real id is checked against the real allowlist, so citing it fails `unknown_passage_id` exactly as today.
   Add nothing to `passages`, the allowlist or any citation permission.
5. **Phrase repair gets no new evidence.** `report_phrase_repair` shows the handles of what its StepInput already
   carries; its input, allowlist and evidence do not change, only their display.
6. **What stays real and what shows handles.** The stored StepInput (`insert_step_input` payload), the resolved
   `output["result"]`, evidence links and everything the report code reads afterwards keep real ids. The sent message
   and the stored raw model output (`raw_output`, the model session) keep handles (that is what was sent and received).
   Allowlist checks, anchor location against passage text and quote checks run on real ids and on passage text and
   quotes exactly as today; no text or quote is changed by this work. Repair messages after a failed validation use
   `issues_with_handles` (extend it to the report handles) so an issue that names a real id names its handle.
7. **No salvage for reports.** D56's `salvage_answer_draft` stays `grounded_answer` only. After the bounded repair, an
   output whose id does not resolve to an allowlisted id still ends the step invalid exactly as now (the section stops
   the run with `unknown_passage_id` / `unknown_cell_id` / the same issue codes). Do not drop citations, do not
   guess, do not map a near-miss handle to a record.
8. **Leading-zero normalisation is id resolution, not fuzzy matching.** Extend `PADDED_HANDLE` to the `cel_L` prefix so
   `cel_L00000003` reads as `cel_L0000003` (the same rule as today for the other prefixes). Nothing else: a handle with a
   missing or changed character other than leading zeros, a handle of another kind (`psg_P0000001` where a cell is
   expected), a handle number out of range and a real long id copied by the model all stay unresolved and are
   reported by validation as an unknown id. Make sure a real long id the model copies is not silently accepted where it
   was not before: today the real id passes the allowlist check (`real` returns unknown strings unchanged); keep that
   behavior (a correct real id still validates) and say in the test names that it is the existing behavior.
9. **The method text changes so `skill_package_hash` moves.** Edit `methods/deixis-research/references/report.md` only
   where the text names ids: say once that passages, evidence-table cells, sources and columns appear as short ids like
   `psg_P0000001`, `cel_L0000001`, `srv_S0000001`, `col_C0000001`; that they must be copied exactly as shown, that only
   ids given in the allowlist may be used, and that a glossary passage the input names but the allowlist does not
   carry may not be cited. Keep the file's other rules unchanged; keep frontmatter and relative links valid. Update
   the `report.md` entry's `change` text in `methods/deixis-research/provenance.json` with one dated sentence
   (30 September 2026, P18); if `methods/deixis-research/SKILL_MANIFEST.sha256` or any other file records the file's hash
   and the integrity check needs it, update it, otherwise leave it. **Report the old and new `skill_package_hash`**: the
   old one on 5c0a4ab is `sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee`; get the new one with
   `load_skill_package().package_hash`. Other tests that pin the hash or embed the package text must be updated to the
   new state, and only for that reason.

10. **Source ids that are not in the step's `sources` are displayed with handles too (Sol plan review r1).**
    `limitations_core.failed_rows[].source_version_id` (section VIII; D125 failed rows are not among the step's
    `sources`, see `report/review_methodology.py` and `report/sections.py`) and the stored `count` objects a review input
    carries in `review_sections[].claims[].count` (`numerator_source_ids`, `denominator_source_ids`, `column_id`; see
    `report/review.py`; the StepInput schema does not describe the inside of `count`, so the schema walk will not find
    it) must show handles, not raw ids. Numbering: `srv_S` handles continue after the `sources` list, then these extra
    ids in a fixed order (failed rows in list order, then review claims in section and claim order, numerator then
    denominator), first occurrence wins, all recomputable from the stored StepInput. The extra ids are **display only**:
    they are not added to `sources`, `passages`, the shown allowlist or the stored StepInput. The same holds for any
    other id you find in `report_target` by reading `report/*.py` that builds each task's `report_target` (read the
    builders, do not rely on the schemas alone) and for column ids that are only in a plan or a gap candidate.
11. **Every id field of a report output is checked after resolution, fail closed (Sol plan review r1).** Today the
    section checks in `contracts.py` (`_check_report_section` and neighbours) do not reject an unknown or non-allowlisted
    id in `citation_anchors[].passage_id` / `cell_id`, `claims[].count.*`, `gaps[].basis_passage_ids`,
    `gaps[].basis_cell_ids` and `gaps[].nearest_match.*`: a fabricated `cel_L9999999` anchor gave `ok=True` and then a
    `KeyError` in `report/sections.py::_citation_links`, and a non-allowlisted glossary passage was refused in a claim but
    accepted in an anchor. Since an unresolved handle would now travel as an unknown string through those fields, add,
    in `_check_report_section` (and `_check_report_plan` for plan ids if a gap exists there), one membership check per
    field against the step's real records: passages and cells and columns against the real allowlist, sources against
    the real `allowlist.source_ids` plus the `source_version_id` of the cells the step shows. **Chosen boundary for
    `count`, `gaps[].nearest_match.source_id` and any other source id of a section output (Sol plan review r2, decided
    by the main session): only sources the step actually shows as evidence.** The model can only name a source it was
    shown, so this narrows nothing a real model could write; it does narrow what a scripted or invented output may
    pass (today `report/assembly.py` checks count members against the whole frozen snapshot, so a `count` naming a
    snapshot source the step never showed would have passed; it now fails here). State this narrowing in the
    decision's Limits. **Display rights are not use rights:** the extra handles of decision 10 (`failed_rows`
    sources, review `count` ids, plan-only passages and columns) are never part of this allowed set, so citing,
    counting or matching them fails. Use new issue codes (in the style of the existing ones, for example
    `unknown_passage_id`, `unknown_cell_id`, `unknown_source_id`, `unknown_column_id`; reuse existing codes where the
    field already has one). A real allowlisted id keeps validating exactly as today; every other existing valid
    fixture output must still pass (existing tests are the check). An output that fails is repaired once and then stops
    the section, as any other invalid output (decision 7). The tests of decision 3 and item 5 below cover each of these fields, including the
    glossary-only passage used in an anchor.

## Files allowed

- `backend/deixis/domain/contracts.py`, `backend/deixis/workflow/flow.py` (show and resolve paths only; the output id checks of decision 11 live in `contracts.py`, not here).
- `methods/deixis-research/references/report.md`, `methods/deixis-research/provenance.json`, and the manifest file only
  if it exists and must change.
- New or extended tests: `tests/test_contracts.py` (or a new `tests/test_report_handles.py`), `tests/test_report_step_input.py`,
  `tests/test_report_flow.py`, and any existing test that must change because the report steps now show handles (say
  which and why); `tests/fakes.py` only if a helper cannot serve the new tests otherwise (say why).
- `docs/decisions.md` (one entry at the top: D127), `docs/product/p6-slice1-handoff.md` (one line in "Partiler", style
  of the P17 line, ending `commit: bu satırı ekleyen commit`).
- This prompt file itself only to fill in the review-round comment line.

## Files NOT allowed

`backend/deixis/workflow/report/*` (plan, sections, assembly, review, store...) unless a reading of a raw output there
proves it needs a handle-aware change (then stop, keep it minimal and say so); `apps/web/`; `contracts/` (schemas);
`tests/fixtures/research/`; `storage/migrations/`; the fill or answer behavior; `scripts/`; `tests/acceptance/fixture_server.py`
(the scripted server answers from the shown message; it must keep working, which the Playwright run checks; if it does
not, stop and report instead of editing it).

## Tests to add (each limit above has one; name them so the limit is readable)

1. Show: for each of the four tasks, build a real StepInput (the existing report test helpers) and assert the message
   sent to the model contains **no** real passage, cell, source-version or column id anywhere in its text (search the
   whole message for every real id of the stored payload; `cell_revision_id` and `report_id` are excluded), and does
   contain handles. Assert the allowlist shown lists handles of the same count.
2. Order and restart: two different steps of one report both start at `psg_P0000001` / `cel_L0000001`; handles are
   recomputed identically from the stored StepInput; a handle from step A is not present in step B's message.
3. Resolve, per output field: plan (glossary passage, axis column, limitations and future-work column), section (claim
   `passage_ids`, `cell_ids`, count numerator, denominator and column, equation origin passage, anchors passage and
   cell, gap basis passages, basis cells, nearest match source and cell). Each becomes the real id in the stored
   `result`; `null` stays `null`; an anchor keeps its quote unchanged.
4. Real ids and handles in the stored records: the stored StepInput row has real ids; the stored model session
   `raw_output` and the stored message row keep the handles; the succeeded step output and its evidence links have real ids.
5. Glossary passage not in this step's allowlist: shown as a handle beyond the allowlisted range, not listed in the shown
   allowlist, and a claim citing it, an anchor naming it, a `gaps[].basis_passage_ids` naming it and an
   `equation_origin` naming it each fail with an unknown-id issue (no new permission); a claim citing an allowlisted
   passage still passes. Same for fabricated cell, source and column ids in anchors, `count`, gap basis and
   nearest match (decision 11): each is refused after resolution and none reaches `_citation_links`.
5a. `count` naming a source that the step did not show (also one only in `failed_rows`) fails; a `count` over shown sources passes.
5b. Decision 10: the VIII input with D125 failed rows and a review input whose claims carry `count` show no raw source
   or column id anywhere in the message; the extra handles are not in the shown allowlist or `sources`.
6. Phrase repair: input, allowlist and passages equal the section step's shown evidence for the same sentences; no new id.
7. No salvage: a `report_section` output with a bad passage id (and with a bad cell id) after its one repair ends the
   step invalid and the section stops the run as before (assert the issue code and that no citation was dropped);
   a `grounded_answer` output still gets D56's salvage (existing test stays and passes).
8. No fuzzy matching: `psg_P0000001` written as `psg_P00000001` resolves (leading zeros), `cel_L00000003` resolves;
   `psg_P0000O01`, a handle with a dropped character, `cel_L0000001` where a passage is expected, a number out of range,
   and `psg_P0000001` where a cell id is expected all stay unresolved and validation names them unknown ids; a correct
   real long id still validates (existing behavior).
9. The answer/cell/abstract/adjudication handle output is unchanged (existing tests untouched and passing; add one
   assertion that `with_citation_handles` for a `grounded_answer` input equals its pre-change shape if none exists).
10. Repair message: the issue text of a failed report output names handles, not real ids.
11. `skill_package_hash` differs from `sha256:08f1bdea...` and the integrity check passes.

## Checks to run (in the worktree)

1. `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_contracts.py tests/test_report_step_input.py tests/test_report_flow.py -q`, then the full `uv run pytest` (one known failure is accepted:
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails only under
   parallel load: rerun it alone and say so).
2. Report the new `skill_package_hash` and how many existing tests you had to change and why.

## Final message

List the files changed, every id-bearing field you found by the walk that is not in this prompt's list (and what you did
with it), every decision you took where this prompt was silent, the test counts, and anything you could not do.
