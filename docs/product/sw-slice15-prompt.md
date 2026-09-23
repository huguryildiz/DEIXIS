# Task: SW slice 15: citation chaining (D95)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`, and the
line-level plan is `docs/product/sw-slice15-citation-chaining.md`. Its six decisions were settled jointly by Claude
and `gpt-6-sol` · medium in three rounds (23 September 2026, `ef62fa3`), and the owner asked to move on to
implementation the same day. The slice writes D95. The slice file is the only source of truth; this prompt sets the
rules of the session. The implementer is Opus · high. The review is a full one (Codex `gpt-6-sol` · high), so list
every place where you used your own judgement.

## Ground rules

1. **Git.** Run `git pull --ff-only` first and work in the main checkout on `main`. At the end make ONE commit and
   run `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or reset. Leave
   untracked files and the owner's uncommitted `TODO.md` edits alone. If the slice is not finished, or Task 8's
   acceptance fails on the chain's own cause, commit nothing: write what remains into row 15 of `sw-status.md` and
   say so.
2. **No model contract change.** The chain's abstract read uses the existing `abstract_screening` contract and prompt.
   `skill_package_hash` must be the same at the end. Check it before and after with
   `PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`.
3. **No topic word in product code.** The filter reads the approved vocabulary's two gate blocks. Fixtures are
   SYNTHETIC and come from at least two fields.
4. **The keyword path does not change.** The `ranking` step, the keyword abstract read plan and the first three groups
   of the full-text plan must be byte-identical with and without chained works. A test proves it (Task 6), and the
   acceptance checks it against a chain-off replay (Task 8).
5. **`legacy` does not change.** A legacy research never chains; its protocol body, budget and requests stay
   byte-identical.
6. **Frozen state stands.** Seed list, chain links, chained list and the chain's read plan are frozen in step output or
   rows; a resumed run reads them back and asks OpenAlex nothing again. A run queued before this change keeps its
   budget and does not chain.
7. **Failures do not pause.** A failed chain request is recorded and the others go on (D18). Reaching
   `max_chain_requests` stops chaining (the rest counted `not_reached`); it never pauses the run.
8. **Existing tests.** Change only what the slice file names, and list each change in the final message. Tests use no
   network and no live model. Do not start, stop or query the service on port 8765, and do not open the product
   database.
9. **Live steps.** Only Task 8 touches the network. Keep a request ledger, pace politely through the existing host
   gate. On repeated 429s, stop and report. In the final message, say how many OpenAlex requests the chain cost per run.
10. **Live model.** Task 8 uses `gpt-5.6-luna` · medium over the Codex connection, passed explicitly. If Luna fails,
    for quota or anything else, stop and report. Do not switch models.
11. **Python.** Run it as `PYTHONPATH=backend:. uv run ...` from the repo root, native arm64. Scripts under a folder
    holding a `numbers.py` run with `python -P`. Known failures that are not this slice's:
    `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, and the import errors of
    `test_isolated_pdf_prefetch.py` and `test_p4_eval.py`.

## Read first

- `AGENTS.md`, `CLAUDE.md` and `.impeccable.md` (Task 5 touches the approval card and the run view).
- `docs/product/sw-status.md`: rows 14, 14a and 15, decision K8, the review rows dated 2026-09-23.
- The slice file, in full, including "Sahibin vereceği kararlar" as revised with Sol.
- `.local/sw-slice15-chain-replay-2026-09-23/`: `protocol.md`, `result.md`, `sol-review.md`, `p4.json`; the scripts
  `common.py`, `rerank.py`, `analyse.py`, `p4.py`; the `cache/` responses (Task 7 replays against them offline).
- `docs/product/search-workflow-review-2026-09-18.md`: SW4, SW3 point 6, SW5 point 4.
- `docs/decisions.md`: D18, D46, D79, D81, D83, D85, D88, D93, D94.
- Code:
  - `workflow/flow.py` (`_discovery`, `_ranking`, `_abstract_stage`, `_abstract_code_stage`, `_freeze_expansion`,
    `_fulltext_plan` around the `fetch_plan` call, the queueing of the retrieval run, `_fulltext_adjudication`'s
    read order, `_record_search`);
  - `workflow/ranking.py` (`rank_records`, `fuse`, `verified_seeds`, `blocks_in`, `block_forms`),
    `workflow/abstract_stage.py`, `workflow/fulltext.py` (`GROUPS`, `group_of`, `fetch_plan`, `fetch_budget`),
    `workflow/adjudication.py` (`read_plan`), `workflow/lookups.py` (`flag_and_decide`), `workflow/protocol.py`,
    `workflow/views.py`, `workflow/store.py` (record and candidate writes, `candidate_hits`);
  - `providers/openalex.py`, `providers/common.py` (`send`, host gate);
  - `api/app.py` (sw discovery budget), `domain/rules.py`, `settings`;
  - `storage/migrations/` (the highest file is `0049`);
  - `apps/web/src/ProtocolApproval.tsx`, `Transcript.tsx`, `api.ts`, `i18n.ts`, `labels.ts`.
- Tests: `test_abstract_stage.py`, `test_abstract_flow.py`, `test_fulltext_plan.py`, `test_fulltext_flow.py`,
  `test_adjudication.py`, `test_protocol_record.py`, `test_ranking*.py`, `test_lookup_flow.py`,
  `apps/web/e2e/protocol-approval.spec.ts`.

## What to build

Build Tasks 1–8 of the slice file in that order. For each task, write its tests before its code. Task 7 is an offline
check against the replay cache and must pass before Task 8 sends any live request.

## Procedure

1. Run `git pull --ff-only` and `git status --short`. Run the baseline `PYTHONPATH=backend:. uv run pytest -q` and
   record the count. Record `skill_package_hash`.
2. Set row 15 to `uygulanıyor`.
3. Tasks 1–6, tests first and then code. Run the suite after each task and keep it green.
4. Run `npm run build`, `npm run lint` and the Playwright acceptance suite
   (`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance`).
5. Task 7, offline.
6. Task 8: write `protocol.md` (expectations, the chain-off comparator, the benefit gate) in
   `.local/sw-slice15-acceptance-<date>/` before the first request, then run the four live runs. If it passes:
   - write D95 at the top of `docs/decisions.md` (with the benefit gate's outcome and, if it failed, default `off`);
   - update the SW4, SW3.6 and SW5.4 status lines as Task 8 says;
   - run the full test suite and `git diff --check`;
   - check that `skill_package_hash` is unchanged;
   - set row 15 to `uygulandı, inceleme bekliyor`;
   - commit and push.

   If it fails on the chain's own cause, commit nothing.

## Final message

- Files changed, with the migration number.
- Baseline and final test counts; the names of the new tests, and every changed expectation with its reason.
- Task 7: seeds and filtered counts against `result.md`'s `code` 15 row for a14a `quick`.
- For each live run: seeds (user and code), requests (backward batches, forward pages, failed, `not_reached`), links
  per direction, new works, filtered, read by the model, chain candidates, chain works in the plan, their PDFs; verified
  works in pool / plan / read / cited, and those that came only through the chain; against the K8 baselines
  (quick 18 / 8 / 4, 9.8 min; standard 25 / 8 / 7, 17.9 min; detailed 30 / 19 / 17, 39.7 min; packet quick 1 / 0,
  8.4 min).
- The chain-off comparator result per run, and the benefit gate's outcome.
- Time: whole run against 10 / 15 / 20 min, and the chain's own share against 2.0 / 3.0 / 3.0 min.
- Every place where you used your own judgement, with the rule you applied; every deviation from the slice file.
- What was "ölçülmedi".
- Confirmation that the live service and the product database were not touched.
- The commit hash, or why there is none.
