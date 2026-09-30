<!-- Plan review: gpt-6-sol high, rounds recorded below by the orchestrator (see the PLAN-REVIEW-ROUNDS line). -->
<!-- PLAN-REVIEW-ROUNDS: gpt-6-sol high, 2 rounds: r1 2 high (repair_section writes report_phrase_repairs after a stop; scope-change test assumed III/V were sent), r2 0 high (hazır; 1 medium folded in: direct test for the repair OptionalStepFailed branch); r1 also had 1 medium (run completed vs report valid) folded in -->

# Task: P6 slice 1, batch P13, interruption tests for the report run, and why a section failed (plan 1k)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p13` (detached at `545745c`, main with P9/D118 and
P12/D120). Read `AGENTS.md`, `CLAUDE.md`, `docs/product/p6-slice1-report-run.md` section "1k" (its Step 1 sketches are
older than the code; where this prompt differs, this prompt wins), the handoff's "Bilinen zayıflık: bölüm
başarısızlığının nedeni kayboluyor", and D113, D115, D116, D118, D120 at the top of `docs/decisions.md`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not create files outside the list below. Do not invent; report what you could not find. No real-model
calls; tests use `FakeAdapter` only. No server is started in this batch (no port needed); do not touch `../DEIXIS`,
`../DEIXIS-s30`, `../DEIXIS-s31`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`,
`docs/product/sw-slice31-legacy-removal.md`.

**Stay out of the legacy discovery code.** Another session is deleting the legacy search workflow (slice 31, D119) and
is editing `flow.py`, `worker.py`, `store.py`, `contracts.py`, `fakes.py`, the research fixtures and `fixture_server.py`
at the same time. This batch is about the `report` run only: do not read, change or add tests around legacy discovery,
do not add tests to `tests/test_api_flow.py` (its discovery tests are being edited by that session), and do not touch
any of the files above. If a fix appears to need one of them, do not edit it: write down which line and why in your
final report.

## What is and is not in code (checked on 545745c)

- `report/sections.py::_run_section` calls `flow._model_step(..., optional=True, limiter=flow.deps.limiter)` inside
  `flow.deps.limiter.run(operation_key, call)`. An optional step that cannot produce a result raises
  `OptionalStepFailed(reason, detail)`; `_run_section` catches it, writes the section as `failed` with
  `validation_json = {"ok": False, "issues": [{"code": reason, "detail": detail}], "truncated": ..., ["numbers": ...]}`
  and returns `"failed"`. An `invalid` output is also written `failed`, with the model's `issues`. So the real reason
  of a failed section lives only in `report_sections.validation_json`.
- `run_report` runs the rounds `ROUNDS` with `asyncio.gather(..., return_exceptions=True)`, re-raises the first
  exception, calls `flow._checkpoint(run_id, run["scope_revision"])` after each round, then pauses the run:
  `section_must_be_rewritten` for `draft` sections, `section_failed` for `failed` ones, each with
  `error_json = {"sections": [<section ids>]}`. The run's `pause_reason` for a quota, connection, budget, model-mismatch
  or isolation failure of a section is therefore always the same `section_failed`, with no reason (the handoff's known
  weakness). The UI line for it (`labels.ts`: "A section could not be written.") and `Transcript.tsx` are not changed here.
- `_run_section` has NO checkpoint between the model call and writing its result: after the call returns it goes on
  to `repair_section` (which itself writes `report_phrase_repairs` rows, `phrasing.py`), `save_claims`, `save_section_draft`, `save_gaps` even if the run was cancelled, paused by the
  user (`pause_requested`) or the question was revised while the call was out. The only checkpoints are before a round
  and after it. This is the "late result" hole this batch closes; the existing answer run does not have it
  (`_model_step` for `grounded_answer` results is applied only after the run's own checkpoint in its caller).
- Inherited and already right, to be pinned by tests, not rebuilt: `_call_adapter` resends a rate-limited call at
  most `MAX_RATE_LIMIT_MODEL_RETRIES` (2) times, lowering the limiter each time (`flow.py`,
  `RATE_LIMIT_BACKOFF_SECONDS = 1.5`, monkeypatched to 0 in tests as `tests/test_abstract_concurrency.py` does);
  `Worker.recover()` (`worker.py`) marks `running` steps and `started` model sessions `outcome_unknown` and
  `running`/`pause_requested` runs `paused` / `backend_restarted`; a step that already `succeeded` returns its stored
  output on the next `_model_step`; `_model_step` for a model other than the requested one records `model_mismatch`
  and halts (optional: raises `OptionalStepFailed("model_mismatch", ...)`).
- `tests/test_report_flow.py` already has the harness: `report_flow(tmp_path, ...)` returns
  `(flow, store, reports, adapter, run, scope, report_id)` with `ReportAdapter(FakeAdapter)` (assign `adapter.fail` or
  `adapter.before` after construction to script a failure), `ModelCallLimiter(3)`, run status `running`, and
  `asyncio.run(run_report(flow, run, scope))` raising `RunStopped` when the run stops. Existing tests
  `test_a_failed_section_pauses_the_run_after_its_round` and `test_a_resumed_report_run_does_not_call_the_model_again_for_a_succeeded_section`
  show the pause and resume pattern (`store.update_run(run["id"], status="running", pause_reason=None, error_json=None)`,
  then `run_report(flow, store.run(run["id"]), scope)`).

## Decisions taken (the plan's own default where it has one; own judgement is marked)

1. **The reason a section failed is stored on the run.** `pause_reason` stays `section_failed` (own judgement: the
   contract the screen and 5 existing tests read does not change; one run can also have several failed sections with
   different reasons). `error_json` becomes
   `{"sections": [<ids>], "reasons": [{"section_id": "IV", "code": "model_call_failed", "detail": ...}, ...]}` where each
   entry comes from the section's stored `validation_json["issues"]` (first issue: `code` and `detail`; a section with
   no issues records `code: "unknown"`), in the same order as `sections`. `detail` is copied as stored except that a
   string, and every string value nested one level in a dict, is cut to 300 characters (adapter error text can be
   long). The same `reasons` list is written for `section_must_be_rewritten`, from its `draft` sections' issues
   (their `validation_json["issues"]` are phrase or limitations issues and may be many: keep the first three per
   section). `sections` keeps its meaning and position, so `Transcript.tsx`'s read of `error.sections` keeps working.
   Nothing new is stored in the database schema: no migration. The web UI is not changed (own judgement: `Transcript.tsx`
   and `labels.ts` are in the other session's file set, and the run's `error` is already sent to the screen; showing
   the reason as text is left open and named in the decision's Limits).
2. **A late result is never applied.** In `_run_section`, call `flow._checkpoint(run["id"], run["scope_revision"])`
   (a) immediately after the `limiter.run(...)` await returns or raises, before anything is written to the report
   tables (also before the `OptionalStepFailed` and `invalid` branches write `failed`), and (b) after
   `repair_section` returns, before `save_claims`, and (c) inside `report/phrasing.py::repair_section` (a one-line
   edit each, the only change allowed in that file): `flow._checkpoint(run["id"], run["scope_revision"])` as the first
   line of the `except OptionalStepFailed` branch and right after the `try/except` that awaits
   `flow.deps.limiter.run(operation_key, factory)`, before the `output.get("invalid")` branch. Without (c) a stop that
   arrives while the repair call is out would still let `repair_section` write `report_phrase_repairs` rows
   (`reports.save_phrase_repair`) before returning. `_checkpoint` raises `RunStopped` on `pause_requested` (it pauses the
   run as `user_requested`), on `cancelled`, and on a newer scope revision (it cancels the run as `scope_revised`).
   The recorded model step stays `succeeded` with its output, so after a user pause and resume the result is applied
   once without another call (the same rule as the answer run). The section row stays as `run_report` left it at the
   start of the call (`running`); do not write `failed` for a stop. `run_report`'s `return_exceptions=True` and
   re-raise stay as they are: verify by test that when one section of a round raises `RunStopped` the sibling sections of
   that round also stop without writing (each has its own checkpoint), and that the exception seen by the caller is
   `RunStopped`, not an `OptionalStepFailed` or a wrapped error.
3. **Wrong model in a section.** The plan's sketch says the run pauses with `model_mismatch`. That is not what an
   optional step does and this batch does not change it: the section is `failed` with the issue code `model_mismatch`
   (detail: requested and resolved model), the run pauses `section_failed`, and by decision 1 `error_json.reasons`
   carries `model_mismatch`. Nothing of the wrong model's output is written (no claims, no gaps). The test asserts this.
4. **Crash.** No process is killed, but a dead process is imitated so the rows are left exactly as a kill leaves them:
   a hook raises `SystemExit` (a `BaseException` the flow never catches; asyncio re-raises it out of `asyncio.run`, so
   no `except` in the flow writes a `failed` status). Wrap `asyncio.run(run_report(...))` in `pytest.raises(SystemExit)`.
   Before recovery, read the rows and assert what a kill leaves for the section that was in flight: its
   `report_section:<id>` step `running`, its model session `started`, the run `running`, the section row `running`, no
   claims for it. If asyncio's cleanup leaves the sibling sections' rows in some other state, assert on the crashed
   section only and do not assert on siblings.
   Crash test A, during the call: raise `SystemExit` from `adapter.before` for section `IV`. Then call the real
   `Worker.recover()` (build `Worker(store, flow, tmp_path / "lock")` only as far as `recover()` needs; see
   `tests/test_fetch_overlap_flow.py` line ~620 and `api/app.py` line ~424; if it cannot be built without an app,
   replicate exactly what `app.py` does and say so). Assert the run `paused` / `backend_restarted`, IV's step
   `outcome_unknown`, then clear the hook and resume as the pause tests do, and assert: `run_report` returns normally
   and the report is `valid` (the run row's own `completed` is written by `ResearchFlow.execute`, which these
   flow-level tests do not call: never assert `status == "completed"`), every section has exactly one row and each claim
   key appears once in `report_claims` (no duplicate claim from the resumed run), and a section whose step had
   `succeeded` before the crash was not sent again. Own judgement (record it in the decision): a step left
   `outcome_unknown` IS sent again on resume, because the earlier call's result was never stored; assert IV has exactly
   2 `report_section` calls in `adapter.calls` (one before the crash, one after).
   Crash test B, after the result was stored and before it was applied: monkeypatch `ReportStore.save_claims` (with
   `monkeypatch.setattr`) to raise `SystemExit` for section IV once; the step is then `succeeded` with its output, the
   section row still `running`. Recover, restore `save_claims`, resume: IV is written from the stored output with
   exactly 1 `report_section` call for IV in total, and no duplicate claim.

5. **Quota.** Scripted with `adapter.fail`: for `section_id == "III"` only, return
   `ModelStepResult("failed", error="rate_limit_error: quota exhausted")` (import from `deixis.models.adapter`) the
   first two times, then let it answer. Assert 3 `report_section` calls for III (the first send and two resends, the
   limit in `MAX_RATE_LIMIT_MODEL_RETRIES`), the limiter's `limit` went from 3 down (`ModelCallLimiter.limit`; reduce
   halves: 3 to 1), `run_report` returns without `RunStopped`, and III and the report are `valid`
   (`reports.report(report_id)["status"] == "valid"`). Second quota test: `fail` for III returns the rate limit
   every time. Assert III gets exactly 3 sends, ends `failed` with code `model_call_failed`, the run pauses
   `section_failed` (`store.run(...)["status"] == "paused"`) and `error_json.reasons` has one entry `{"section_id": "III", "code": "model_call_failed", ...}`
   whose detail contains the rate-limit text; the other sections of that round (IV, V) are `valid`; then clear
   `adapter.fail`, resume, and assert only III is called again (IV and V are not) and the report ends `valid` with `run_report` returning normally. Every
   quota test sets `flow_module.RATE_LIMIT_BACKOFF_SECONDS = 0` with `monkeypatch`
   (`from deixis.workflow import flow as flow_module`).
6. **Cancel.** `adapter.before` runs inside `run_step` synchronously, before the answer, for the one call it sees; it is
   not a barrier: sibling sections of the same round (III, V) may or may not have been sent yet when it fires, and the
   tests below must not depend on which. In `adapter.before` for section `IV`, cancel the run:
   `store.update_run(run["id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")`. Assert
   `RunStopped` from `run_report`, run `cancelled`, the `report_section:IV` step `succeeded` (recorded, unapplied; IV's call is the one the hook fired in, so it was sent),
   `report_claims` has no row for section IV, IV's section row is not `valid` and not `failed`, the report is not
   finalized (`reports.report(report_id)["status"] == "in_progress"`), and no later round's section (VI, VII, VIII, I,
   IX, abstract, index_terms) was called.
7. **Scope change.** In `adapter.before` for section `IV` (once), revise the question:
   `store.revise_scope(research_id, store.research(research_id)["version"], "A revised SYNTHETIC question", None)`.
   Assert `RunStopped`, run `cancelled` with `pause_reason == "scope_revised"`, `report_claims` has no row for any
   section of that round (a section whose call was already sent is late; one not yet sent is stopped by
   `_model_step`'s own checkpoint and has no succeeded step: assert only that every `report_section` step of the
   round that is `succeeded` has no claims, and that IV's step is `succeeded`), no later round called, report
   `in_progress`. Do not assert that III and V were sent.
8. **Pause (late result, resumed).** Same shape as `test_pause_during_final_model_call_applies_result_only_after_resume`:
   in `adapter.before` for section `IV` (once) set the run `pause_requested`
   (`store.update_run(run["id"], event="run_pause_requested", status="pause_requested", pause_reason="user_requested")`).
   Assert `RunStopped`, run `paused` / `user_requested`, no IV claims; resume (as the existing pause tests do); `run_report`
   returns normally, the report is `valid`, IV is written from the recorded output, and `report_section` calls for IV
   total 1 (no second call; III and V also at most 1 each).
   Add a fourth stop test for the repair call: `ReportAdapter(unframed_section="IV")`, cancel the run in
   `adapter.before` when the task is `report_phrase_repair`, assert `RunStopped`, run `cancelled`, and that the table
   `report_phrase_repairs` has no row for the report and IV has no claims (this is what (c) of decision 2 pins).
   Add a fifth, for the `except OptionalStepFailed` branch of `repair_section`: same setup, but `adapter.fail` returns
   `ModelStepResult("failed", error="SYNTHETIC connection lost")` for `report_phrase_repair` and the same hook first
   cancels the run (so the repair fails while the run is already cancelled); assert `RunStopped`, run `cancelled`,
   and no `report_phrase_repairs` row (without the first checkpoint line of (c) that branch writes
   `unframed_exception` rows).
9. **Reasons on the run for the other three failure kinds** (small tests, one per kind, all through the existing
   `report_flow`): `model_mismatch` (decision 3; per-section and deterministic: `adapter.before` runs and the answer's `resolved_model`
   is read in the same synchronous stretch of `FakeAdapter.run_step` (no `await` between them when `delay` is 0), so
   in `before` set `adapter.resolved_model = "some-other-model"` when the call is the `report_section` for IV and
   `None` for every other call; assert IV is `failed` with code `model_mismatch`, no IV claims, siblings valid,
   run `section_failed`, `reasons` has `model_mismatch`), `budget_exhausted` (build the run with `max_model_calls` just enough for `report_plan` and less
   than one round; assert the failed sections carry `budget_exhausted` and the run pauses `section_failed`), and
   `invalid_model_output` (the existing `broken_section="IV"`: the reason entry for IV has the code of the model's
   first issue, not `unknown`). If the budget test cannot be made deterministic with the round's concurrency, keep the
   other two and say so in the report.
10. **Existing behaviour that must not change.** Every existing test in `tests/test_report_flow.py` still passes
    unchanged except where an assertion reads `error_json` exactly (check; update only such an assertion, and report
    it). The pause for `section_must_be_rewritten` still happens after its round.

## Files you may change

- `backend/deixis/workflow/report/sections.py` (decisions 1 and 2 only), and in `backend/deixis/workflow/report/phrasing.py` only the two checkpoint lines of decision 2 (c).
- `tests/test_report_flow.py` (the new tests; a small helper next to `report_flow` is fine).
- `docs/decisions.md`: one new decision at the top, `## D121 — ...` (D119 is reserved for slice 31; if main's file
  already has a higher number than D120 when you write, take the next free one; say which you took), with
  Status/Date (2026-09-30 or the day you write)/Context/Decision/Limits in the style of D118 and D120. The Limits must
  say: fake and scripted models only, nothing here measures real quota or crash behaviour of a provider; the crash is a
  simulated state plus the real `Worker.recover()`, not a killed process; an `outcome_unknown` step is sent again on
  resume; the UI still shows only "A section could not be written." and the reason is only in the run's `error` (the
  screen line is open); the plan's `model_mismatch` pause wording was not built (decision 3).
- `docs/product/p6-slice1-handoff.md`: a one-line status for P13 in the "Partiler" list with the placeholder `<hash>`
  for the commit hash (in the style of the P9 and P12 lines), and one line under "Bilinen zayıflık: bölüm
  başarısızlığının nedeni kayboluyor" saying it is settled in P13 (D121) with what was kept open (the UI text).

Everything else is off limits, in particular: `flow.py`, `worker.py`, `store.py`, `contracts.py`, `views.py`,
`report/store.py`, `report/assembly.py`, `report/review.py`, the rest of `report/phrasing.py`, `tests/fakes.py`,
`tests/fixtures/`, `tests/acceptance/`, `apps/web/`, `methods/` (so `skill_package_hash` must not move; report it
unchanged), `backend/deixis/storage/migrations/` (no migration), `tests/test_api_flow.py`, and any legacy-discovery
file or test.

## Checks to run (in the worktree, with `PYTHONPATH=backend:.`; add `UV_CACHE_DIR=/tmp/deixis-uv-cache` if uv needs it)

1. The new tests first, written before the change to `sections.py` and `phrasing.py`: run
   `uv run pytest tests/test_report_flow.py -k "quota or rate_limit or crash or cancel or scope or pause or reasons"`
   and confirm the cancel, scope-change and pause tests FAIL for the reason of decision 2 (result applied after the
   stop) and the reason tests FAIL for decision 1 (no `reasons`), while the quota-then-success test and the crash
   tests may already pass (they pin inherited behaviour). Report which failed and which did not.
2. After the change: `uv run pytest tests/test_report_flow.py -q`, then the full `uv run pytest` (the one known
   memory-limit failure is the only accepted failure: name it; a test that fails only under parallel load: rerun it
   alone and say so). Also `uv run pytest tests/test_report_assembly.py tests/test_report_api.py -q` if those files
   exist, because they read the run and report state.
3. No web build, lint or Playwright run is needed (no `apps/web` change); say so in the report.

## Final report (your last message; keep it tight)

Files changed (`git status --short`); the D number taken; for every test in decision 4 to 9 whether it failed before
the change to `sections.py` and why; the full-suite counts and named failures; every own-judgement choice; anything
you could not do (the budget test, the per-section wrong-model script, building a `Worker` for `recover()`); any line in
a forbidden file that seems to need a change, with the reason; and the statement that `skill_package_hash` did not move.
Results say what they measure: these tests show workflow behaviour with fake models, not report quality or a
provider's real quota behaviour.
