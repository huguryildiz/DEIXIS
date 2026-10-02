<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 4 high (removed-source step used a source outside the table snapshot; purge refusal expected after restore; xfail ends the sequence; two-library fingerprint equality) + 2 medium, all folded in; r2: hazır değil, 2 high (acknowledging only the cell key leaves source_removed open; a recheck cannot be accepted while the source is removed), folded in; r3: hazır değil, 1 high (the recheck runs stay active and block remove_sources), folded in without a fourth round -->

# Task: P6 slice 4, batch E4 ("Senaryo dizisi, kapanis ve P9 borcu"), the scripted edit sequence

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-e4` (detached at `f1a7db0`, main with D156). Read `AGENTS.md`, `CLAUDE.md`,
`docs/decisions.md` D147, D148, D150 and D156 (the slice 4 decision and the three batches this one closes), and
`docs/product/p6-slice4-editing-stale-measurement.md` (Turkish): §2, §3, §4, §7, §9 "E4 senaryo dizisi", §10, §14 "E4". This prompt is the binding English
scope. Read the code and tests the sequence stands on: `tests/test_report_claim_links.py` (helpers `edit`, `cell_report`, `change_cell`,
`dedicated_report_source`, `view_claim`, `state`, `rows`; the E2 tests of staleness, removed source and lifecycle), `tests/test_report_edit_check.py`
(`finish`, `check`, `current`), `tests/test_report_assembly.py::report_with_sections` (the fixture; note it is `report_with_sections.__wrapped__(data_dir)`
in `tests/test_backup.py` when the database must live under a `Settings.data_dir`), `tests/test_backup.py` (the two report backup tests) and
`backend/deixis/workflow/report/{store,assembly,edit_check,export,export_text}.py`, `workflow/views.py::report_view`, `workflow/tables.py`
(`save_model_output`, `decide_proposal`). Where the code differs from what this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No model call, no provider request, no network: synthetic rows, the fixture's fake step inputs, nothing else.**
Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data
directory. Backend tests need `PYTHONPATH=backend:.`, `UV_CACHE_DIR=/tmp/deixis-uv-cache`, `UV_OFFLINE=1`, `UV_PROJECT_ENVIRONMENT=/tmp/e3-venv` (a ready arm64
venv; do not create a `.venv` in the worktree). `docs/decisions.md`, the slice note, `p6-report-design.md`, `p9-hardening-plan.md`, the slice 3 note and
this file's comment line are written by the orchestrator, not by you.

## Why

E1 (D148) made an edited report checkable by code, E2 (D150) made a claim able to lose citations reversibly, E3 (D156) put a screen on both. Each batch tested
its own part. Nothing yet runs the pieces in one order on one report, which is where an interaction would show: a removed citation and a cell change, a
source leaving the research while a citation is removed, the check going out of date after a link change, a "Keep as is" followed by a new change, a restore,
and finally a backup and a purge with citation sets and check records present. E4 adds that sequence as a deterministic test. It tests code behaviour on
synthetic rows. It does not test model quality, a real report or a real corpus, and its name and docstring must say so.

## What is and is not in code (checked on f1a7db0; re-check, do not assume)

- In code, do not change: everything under `backend/`, `apps/web/`, `contracts/`, `methods/`, `storage/migrations/`. E4 adds one test file and nothing else
  in code. If the sequence exposes a defect, do not fix it and do not use `pytest.xfail` (it ends the function at that point and the later steps would not
  run). Collect assertion failures per step in a small local helper (`soft(step, condition, message)` appending to a list), keep running every step that can
  still run, and fail the test at the end with the list; a step that cannot run because an earlier one broke its precondition is listed as "not run". Report every
  such observation (file, line, what the code does, what the note says); a sequence with a failed or not-run step does not close the slice.
- In code: `ReportStore.edit_claim(research_id, report_id, claim_id, *, text, restore_from, note, expected_version, idempotency_key, link_ids=...)`,
  `check_edits`, `evidence_changes`, `acknowledge_changes`, `effective_links`, `original_links`, `claim_revisions`; `report_view`; `export_markdown`;
  `TableStore.save_model_output(..., recheck=True)` (a recheck result waits as a `model_proposal`) and `decide_proposal(..., accept=True)`;
  `Store.remove_sources`, `restore_sources`, `purge_sources` (refuses while evidence still cites), `trash_research`, `purge_research`;
  `create_backup` / `restore_backup`.
- Not in code: an end-to-end test that uses them in one order. `tests/test_report_edit_sequence.py` does not exist.

## The file

`tests/test_report_edit_sequence.py` (new). Imports helpers from the existing test modules the way `tests/test_report_claim_links.py` and `tests/test_backup.py`
do; do not copy their bodies and do not edit those files. A module docstring says: synthetic rows, a fake step input, no model, no provider, no network; it
shows how the stored pieces behave when used in one order, not how a real report reads. One local pytest fixture builds the library under a
`Settings(data_dir=tmp_path / "data")` via `report_with_sections.__wrapped__(settings.data_dir)` (as `tests/test_backup.py` does) so a backup can be taken, and
tears the generator down the same way.

### Setup (before `finish`)

Start from `report_with_sections`. Build, with the existing helpers and `_add_claim`/`save_claims`:
- `III.1` (section III): two original citation links, `L_cell` (a cell link to the fixture cell) and `L_pass` (a passage link on `section_passage`), **both on
  the fixture source A**. A is the only source in the frozen table snapshot (`ReportStore.evidence_changes` computes `removed_sources` from `snapshot["rows"]`,
  `report/store.py` around lines 422-440), so a source that is not in the snapshot, such as one built like `dedicated_report_source`, cannot produce a
  `source_removed` mark or a `removed_sources` count. Do not use `dedicated_report_source` in this sequence: it writes an asset row for a file that does not exist,
  and `storage/backup.py` refuses such a library (step 14).
- `IV.1` (section IV): one link to the same fixture cell (the retained basis).
- `abstract.1` already derives from `III.1` through `body_refs`; `VI.1` with `gap_refs=["gap1"]` and a gap `stated_limitation` whose `basis_claim_keys` is
  `["III.1"]` (as `cell_report` does).
- Then `finish(lib)` (report `valid`, run completed). Keep the id of the research and of every link.

Take a **baseline** of: the `report_citation_links` rows, the report row's `status`, `report_version`, the section rows' `status`, and the
`report_review`/`reviews` rows if the view exposes them. These must be identical at the end of the whole sequence apart from `edited_after_version`, which
the existing code may set; assert on what you can read and say in the report which fields you compared.

### The sequence (one test function with numbered steps, comments naming each step)

Use `report_view(...)` for what the owner would see and `ReportStore` for the stored state. Expected outcomes below are what the design says; **run each step
and check the real behaviour**; where reality differs, report it as above.

1. **Baseline.** View: `has_human_edits` false, `edit_check` null, III.1 shows 2 effective citations, `evidence_changes` has nothing open and `changed_cells` 0,
   Markdown export contains no "Edited by hand" sentence.
2. **Edit text.** Edit III.1 to `"Resource allocation is novel."` (a banned word on purpose). View: `has_human_edits` true, `edit_check` null, claim `edited`;
   export says the edited text was not checked again (the exact sentence from `export_text.edit_note`, English). Citations unchanged (2).
3. **Remove one citation, text kept.** `link_ids=[L_pass]` (drop `L_cell`). View: 1 effective citation, `removed_links` has `L_cell`,
   `original_evidence_count` 2, `evidence_basis` "direct", text unchanged from step 2 (verbatim). `report_citation_links` rows unchanged.
4. **Change the removed link's cell with a recheck.** (A `cell_recheck` run that stays `queued` makes `remove_sources` and `restore_sources` fail with "Cancel or
   finish active runs before changing this research's sources" (`workflow/store.py::_check_corpus_change`), and neither `save_model_output` nor `decide_proposal`
   changes a run's status. So after every recheck proposal is saved and accepted, call `store.update_run(run_id, status="completed")` for that run, and assert
   that the research has no active run before the next source change. This applies again to the second recheck in step 9.) Create a `cell_recheck` run/step/step input the way the fixture does for the fill, call
   `save_model_output(..., recheck=True, value=<new>)` and assert the cell has NOT changed yet (proposal only: `changed_cells` 0), then
   `decide_proposal(..., accept=True)` with the current cell version. Now `evidence_changes`: `changed_cells` 1; section III `open == []` (the cell link was
   removed), `abstract` (body_ref through III.1) `open == []`, `VI` (gap_ref, basis claim III.1) `open == []`, section IV `open` has one `cell_changed` through
   `citation` (IV.1 still links the cell). A removed citation opens no flag, the retained one does.
5. **Remove a source from the research.** `remove_sources(research_id, [A], note)`. III.1 still has an effective link on A (`L_pass`), IV.1 cites A's cell, so
   sections III and IV each open a `source_removed` mark (IV keeps its earlier `cell_changed` too); report level `removed_sources` 1. (Check the real `open` entry
   kinds and keys.) While the membership is removed, `purge_sources(research_id, [A])` raises `RevisionConflict` (evidence still cites A); assert nothing was
   written by the refused call (compare the rows of `report_citation_links`, `report_claim_revisions`, `source_versions` and the events count before and after).
6. **Check the edits.** `check_edits`. Record exists, `current` true in the view, the banned word is listed as an `error` for section III, `rules_run` and
   `skipped_rules` are lists, `not_checked` is `["semantic_support","numbers_written_as_words","passages"]`. The report's status, `report_version` and section
   statuses are unchanged by the check, and exactly one `report_edits_checked` event was added. A second `check_edits` with no change returns the same record id
   and adds no row and no event. Export now carries the "checked by code rules" sentence with the same error and warning counts as the view.
7. **Edit again; the check goes out of date.** Edit III.1 to `"Resource allocation assigns capacity."` (removing the banned word). View: `edit_check.current`
   false and still carries the old record (the old error is still in `items`); export carries the "does not cover the current inputs" sentence.
   `check_edits` again: a **new** row (now two rows for the report, the first row byte-identical to before), `current` true, no banned-word error.
8. **A link change alone makes the check out of date.** Edit with `link_ids=[]` only (text unchanged): now `edit_check.current` is false although no text
   changed. View of III.1: no effective evidence, `evidence_basis` "none", `support_type_note` "model_written_type", `removed_links` has both links.
   Section III now has no `source_removed` mark (the claim no longer cites A; S7) while section IV still has one and report-level `removed_sources` stays 1. `check_edits` again: new row,
   `current` true; the zero-citation claim does not make the check fail and is not reported as "checked and clean" for a rule that needs citations (assert the
   real `skipped_rules` entries, whatever they are, are present and stable on a second call).
9. **"Keep as is", then a new change.** In section IV take only the open `cell_changed` key and `acknowledge_changes` it: `acknowledged_count` 1, and the
   section's `open` still holds the `source_removed` mark (A is still removed and IV.1 still cites A) and nothing else; a second `acknowledge_changes` with the
   same key raises `RevisionConflict`. Acknowledging does not change `edit_check.current` (assert the real behaviour before and after, and say which it is).
   A recheck proposal cannot be accepted while A's membership is removed (`TableStore._active_row` refuses a removed row, `InvalidTableInput`), so: `restore_sources`
   A, make a second recheck proposal for the cell and accept it (current cell version), section IV opens a `cell_changed` again with a **different** key than the
   acknowledged one and the old key is rejected, then `remove_sources` A again (the precondition of step 10). Assert the new `source_removed` mark is open again
   after the second removal.
10. **Restore the model's version.** `restore_from="model"` on III.1. View: text equals the model's original, 2 effective citations (both links back),
    `removed_links` empty. `evidence_changes`: section III opens a `cell_changed` through `citation` and, because `L_pass` is effective again, a
    `source_removed` mark (A is still removed from the research); `abstract` opens through `body_ref`; `VI` through `gap_ref`; the check is out of date again. Revision history of III.1: every earlier
    revision is present oldest first, `link_count` values match what you did (2? None? 1, 0, 0, 2, and so on; read them, then pin them), and the revision `changes_current` flags are right
    (restoring a revision that equals the current state is not offered). Restore the step 3 revision by id: text and set come back together.
11. **Restore the source membership.** `restore_sources(research_id, [A])`: the `source_removed` marks and `removed_sources` disappear from the next
    `evidence_changes`; the `cell_changed` marks stay. Do not expect `purge_sources` to refuse after the restore: it selects only memberships with
    `removed_at IS NOT NULL` and returns three empty lists. The refusal is asserted in step 5 (membership removed) and, with the report as the only citer, in the
    small test below.
12. **Original links are untouched.** `report_citation_links` rows equal the baseline, byte for byte, after steps 2 to 11.
13. **Export with a citation set present.** Markdown export finishes with no exception, mentions the edited state, and numbers references from the effective
    set only (assert that the reference numbers the view shows for III.1 are the ones the export prints for it).
14. **Backup and restore.** `create_backup(settings, dir)` then `restore_backup(backup, restored_settings)`, `db.migrate`, and compare these tables row for
    row between the source database and the restored one (the library has no asset rows, which is why step 5 used A and not a dedicated source): `report_claim_revisions`, `report_claim_revision_links`, `report_citation_links`, `report_claims`,
    `reports`, `report_sections`, `report_claim_refs`, `report_gaps`, `report_snapshot`, `report_edit_checks`, `report_stale_acknowledgements`, `events`;
    `PRAGMA foreign_key_check` empty; `effective_links` and the view's `edit_check` (state, counts) equal on the restored database. Close the connection.
15. **Purge.** In the original library create a second research with its own small finished report and one claim edit (so a second set exists), then
    `trash_research` the first, assert the report is still readable and every table above is unchanged by the trash, `restore_research`, trash again,
    `purge_research`: no row of the first research remains in `reports`, `report_claim_revisions`, `report_claim_revision_links`, `report_edit_checks`,
    `report_stale_acknowledgements` (the second research's rows are exactly what they were), `PRAGMA foreign_key_check` empty. The second research is built
    from the helpers `tests/test_report_claim_links.py::test_trash_restore_and_purge_preserve_then_delete_sets_and_other_research` already shows; copy its
    shape, not its code path, if a helper is not reusable.

If a step's real behaviour is not what is written, keep the test asserting the real behaviour only when the real behaviour is what the D147 note's design
says it should be. When it is not, leave the step out of the green path, report the observation (file, line, what it does, what the note says) and do not
change code.

### Small extra tests (same file)

- An autouse fixture in the file makes every test in it fail on any socket or HTTP use: it patches `socket.socket.connect`, `socket.create_connection`,
  `httpx.Client.send` and `httpx.AsyncClient.send` to raise `AssertionError`. The main sequence therefore runs under it. `test_the_sequence_is_model_free` also
  asserts that the `runs` and `step_inputs` of the sequence library are exactly the ones the setup and the two recheck proposals created (count them), and
  that the test module imports no adapter module, `httpx` or `requests` (a source scan of the file, as E2's allowlist test does).
- `test_two_orders_end_in_the_same_effective_set`: on two fresh libraries (the plain `report_with_sections` fixture, two instances through a helper) do the
  citation removal and the text edit in the two possible orders. Row ids and the check fingerprint are not comparable between libraries (ids are random and the
  fingerprint contains `current_revision_id`), so compare normalised values: the claim text, the effective links as `(claim_key, anchor_text, passage-or-cell)`,
  the view's `removed_links` in the same normal form, and `original_evidence_count`. In each library separately: `check_edits` makes `current` true, and a second
  call returns the same record id.
- `test_report_only_source_stays_protected_through_removal_and_restore`: a compact variant of E2's report-only case, no asset row and no backup: a second
  source B with one synthetic passage (inserted with `_insert_passage`, no `add_asset_with_pages`), a claim whose only link is on B, B's membership removed;
  in three stages (original link, link removed by hand, link restored) `purge_sources` raises `RevisionConflict` ("Evidence still cites") and writes nothing.

## Tests / checks to run

Focused: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache UV_OFFLINE=1 UV_PROJECT_ENVIRONMENT=/tmp/e3-venv uv run pytest tests/test_report_edit_sequence.py -q`
and, once green, `tests/test_report_claim_links.py tests/test_report_edit_check.py tests/test_backup.py -q` to show nothing else moved. The full pytest is run by
the orchestrator. `git diff --check` clean. Print `skill_package_hash` before and after (it must not move). Run the new file three times in a row (and once with `-p no:randomly -n 0` if the suite uses xdist) to show it is deterministic.

## Report back (concise)

Files changed (expected: only `tests/test_report_edit_sequence.py`); for each numbered step whether it passed as written, and for every step where the real
behaviour differed from the text above: what it did and what you asserted; the real `link_count` series of step 10; the real `skipped_rules` of step 8; whether
acknowledging changes `edit_check.current` (step 9); any defect found (do not fix); the focused commands you ran with counts; anything you could not run. Do not
write decision or note text.
