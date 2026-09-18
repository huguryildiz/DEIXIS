# Task: P6 slice 1, batch P8 — targeted phrase repair (`repair_section`) and its exception bookkeeping

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

This is plan task **1d Task 3** in `docs/product/p6-slice1-report-run.md` (~line 1833), the half that was
deferred. `flagged_sentences` is already written and used; `repair_section` does not exist, so a section with
one unframed sentence stays `draft` and the run pauses with `section_must_be_rewritten`. That is exactly what
stopped both real-model runs (handoff entries **P5** and **P5.5**).

## Why this batch is now well-founded (measured, do not re-litigate)

Two real runs on the same research, `gpt-5.6-luna`:

- before the method-package tightening: 11 flagged sentences, whose nearest frames were unrelated fragments;
- after it (`758f304`): **2** flagged sentences, both genuine near-misses, with relevant nearest frames —
  e.g. the model wrote "… ele almaktadır" where the frame is "sorusunu ele almaktadır".

So the repair call now has a real, small job: rewrite a couple of sentences into a supplied frame without
changing what they assert.

## Ground rules

1. **Run NO state-changing git command.** `git status` / `git diff` / `git log` are fine. The reviewing session
   commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/api/app.py`, `backend/deixis/providers/`, `docs/decisions.md`, `docs/README.md`,
   `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`, `tests/test_providers.py`,
   `scripts/isolated_*.py`, `tests/test_isolated_*.py`, `.gitignore`, `.impeccable.md`, or the
   `Elicit - *.csv` files. Another session is working in the same tree; leave its uncommitted edits alone.
   `backend/deixis/workflow/flow.py` also carries its edits — **do not change `flow.py`**; if you believe you
   must, stop and report why.
3. **Do not invent.** If something cannot be written as specified, stop and report it. Earlier batches stopped
   this way five times and each stop was correct.
4. Tests need `PYTHONPATH=backend:.`. Set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is unreachable.

## Read first

- `docs/product/p6-slice1-report-run.md` task **1d Task 3** (~line 1833) — the spec, in full, including its
  Step 3 paragraph, which is the authority for this batch.
- `backend/deixis/workflow/report/phrasing.py` — `flagged_sentences` and what it returns per sentence.
- `backend/deixis/workflow/report/sections.py::_run_section` — the comment "Targeted repair is added by 1d Task
  3; this batch records the local validation result only" marks where repair goes, and how `issues`/`status`
  are decided today.
- `backend/deixis/workflow/report/store.py::save_phrase_repair`, and migration
  `backend/deixis/storage/migrations/0035_report_run_kind.sql` line ~139: `outcome` is one of
  `kept` / `reverted_exception` / `unframed_exception`.
- `backend/deixis/domain/contracts.py::_math_spans` — the math-span helper the number/math comparison uses.
- `backend/deixis/domain/phrasebank.py` — `unframed`, `nearest_frames`, `REPORT_PHRASEBANK_SECTIONS`.
- `backend/deixis/domain/skill.py::RUNTIME_FILES` and `backend/deixis/workflow/flow.py` ~line 1099.
- `methods/deixis-research/references/report.md` — `## Phrase repair (report_phrase_repair)`.
- `tests/test_report_flow.py` — `ReportAdapter`, `report_flow`, and how a fake response is scripted.

## What to build

**Files:** `backend/deixis/workflow/report/phrasing.py`, `backend/deixis/workflow/report/sections.py`,
`backend/deixis/domain/skill.py` (one line, see 4), tests in `tests/test_report_phrasing.py` (new) and
`tests/test_report_flow.py`.

1. `async def repair_section(flow, run, scope, report_id, section_id, draft, flagged) -> tuple[dict, list[dict]]`
   exactly as the plan's Step 3 paragraph describes:
   - empty `flagged` → return `(draft, [])` without any call;
   - otherwise **one** `report_phrase_repair` model step, built through `report_target.repair_request`, sent as
     `flow.deps.limiter.run(f"report_phrase_repair:{section_id}", factory)`, with the factory passing
     `limiter=flow.deps.limiter` into `_model_step`;
   - splice each returned sentence back into its claim by `sentence_id` and rejoin the claim text;
   - **code-side guard:** for each touched claim compare, before and after, the multiset of
     `re.findall(r"\d+(?:\.\d+)?", text)` and the output of `contracts._math_spans`. Equal → record `kept` and
     apply. Not equal → do **not** apply that sentence, record `unframed_exception`;
   - after repair, any sentence still `unframed` is recorded `unframed_exception`;
   - **no exception drops the section to `draft`** (plan §8 decision 12).
2. Call it from `_run_section`, replacing the deferred-repair comment. After repair, a section whose only
   remaining issues are recorded exceptions is `valid`. An **empty** section stays invalid as it is today —
   do not weaken that check (it was added in P2.5 for a reason; see the handoff).
3. Make the repair call **`optional=True`** so a failed or budget-exhausted repair records the sentences as
   exceptions instead of pausing the run, consistent with §8's "an unframed sentence becomes a recorded
   exception". If you find something that contradicts this, stop and report it instead of choosing silently.
4. `RUNTIME_FILES["report_phrase_repair"]` does not include the phrasebank, although `flow.py` already computes
   the per-section frame filter for that task type — so that filter is dead today and the repair model sees
   only the three frames carried in the request. The plan's task 1a specifies the phrasebank for this task
   type. Add it. Then **verify the package integrity check still passes** and report whether
   `skill_package_hash` changed:
   `PYTHONPATH=backend:. uv run --no-sync python -c "from deixis.domain import skill; print(skill.integrity_issues())"`.

## Tests

In `tests/test_report_phrasing.py`:
- the plan's `test_flagged_sentences_only_checks_claims_and_insufficient_evidence_reasons`;
- a repair that is applied and recorded `kept`;
- a repair that **changes a number** is rejected, not applied, and recorded `unframed_exception` — assert the
  claim text still holds the original number;
- a repair that **changes a math span** (`$...$`) is likewise rejected;
- a sentence the model leaves unframed after repair is recorded `unframed_exception`.

In `tests/test_report_flow.py`:
- a run whose section comes back with an unframed sentence now **completes** instead of pausing, the section is
  `valid`, and the repair row exists. Do not weaken the existing pause tests
  (`test_a_failed_section_pauses_the_run_after_its_round`,
  `test_an_empty_section_without_insufficient_evidence_pauses_the_run`) — if your change makes one of them
  fail, stop and report it rather than editing it.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q`. Record the exact numbers you see. Another
   session keeps adding tests, so do not expect a fixed count; the **only** acceptable failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
3. Write the failing tests first; confirm they fail for the right reason.
4. Implement, then run the report suites, then the whole suite.

## Final message

- before/after test counts and any new failure;
- what `_run_section` now does with exceptions, quoted from your code;
- whether the package hash changed after the `RUNTIME_FILES` edit, and the integrity output;
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
