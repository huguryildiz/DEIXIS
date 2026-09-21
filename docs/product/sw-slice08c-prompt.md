# Task: SW slice 08c — on the approval card the user can ask a model for other names of the search terms; every proposal is counted and none enters the query unless the user adds it

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 08c of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice08c-model-term-suggestions.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. **Do not start unless slice 09 is committed**: row 09 of `sw-status.md` says `uygulandı, inceleme bekliyor` or `kapandı`, and rows 08a and 08b say `kapandı`. Slice 09 changes the same contract, method package, fixture and budget files and the same `skill_package_hash`; two sessions writing them at once collide. If row 09 says anything else, stop and say so.
2. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and every check is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing, leave the tree passing and write what remains into row 08c — except at the split point the slice file names (Tasks 1–4 and 7 without the card), which may be committed as it says. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
3. **No automatic trigger.** The model is asked only when the new route is called. Write no code that judges whether a first round was thin, and open no suggestion step in `as_proposed` mode, in a run closed by an earlier approval, or in a `legacy` research.
4. **Nothing the model proposed enters the query unless the user adds it.** A run whose user asked for suggestions and added none searches the proposal's queries byte for byte. A run that never asked has the protocol body and digest it had before this slice.
5. **The origin is derived on the server.** The `add` operation keeps its shape; a term is `model` when its normalised phrase is one of this approval's stored suggestions, `user` otherwise. Its block origin is `user` either way.
6. **One code path builds a vocabulary.** An added suggestion goes through `edited_extraction` and `build_vocabulary` like any added term; the count the suggestion step already read goes into `known` and is not asked again. The suggestion step itself sends one phrase count per surviving proposal and nothing else.
7. **Claim and exclusion words never reach the query** (SW1.3): a proposal that contains one is dropped by code, stays on record with its reason, and cannot be added from the card.
8. **The model is not asked twice for the same thing** (SW2.6): no second request once a list is `ready` or was carried from an earlier approval; only a `failed` request may be repeated, under a new step key.
9. **The method file's text is given in the slice file. Copy it; do not reword it.** It has been tried against no model, and this slice tries it against none: no live model call, no provider request, no dry run. Record it as not measured in the decision entry and in row 08c.
10. **Network and model work run in the worker, not in the route.** The route validates, stores the request and queues the run in one transaction.
11. **No existing test expectation may change**, and Playwright cases A–G and the existing H cases stay as they are. If an existing test fails, the change is wrong or the slice file is; stop and report.
12. **Do not invent.** The target, the contract, the drop reasons and their order, the step keys, the route's refusals and the view shape are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
13. Interface: read `.impeccable.md` first; no new design language; render recorded backend state; every string through `i18n.ts` / `labels.ts` in English and Turkish, in the calm factual tone of the existing card. A missing count is "not counted", never 0. The card does not say a proposal is verified: the count shows that records hold the name, nothing more. The user's draft edits survive the suggestion round trip. Visual work needs no step-by-step approval: take screenshots (light, dark, 390 px), open them with the Read tool, fix, look again.
14. No network in tests. Fixture questions, terms and proposals are SYNTHETIC and from at least two fields. No topic word in product code or in the method package. Do not start, stop or restart the service on port 8765, and do not open the product database.
15. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, UI-visible events written in the same transaction as the state they describe. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.

## Read first

- `AGENTS.md` — whole file; `.impeccable.md` — whole file.
- `docs/product/sw-status.md` (rows 04d, 06, 08a, 08b, 08c, 09 and the review log for 06, 08a, 08b), then the slice 08 entry of `docs/product/sw-implementation-plan.md`.
- `docs/product/sw-slice08c-model-term-suggestions.md` — whole file. Then `docs/product/sw-slice08a-protocol-approval-backend.md` Tasks 1–4 and `docs/product/sw-slice08b-protocol-approval-ui.md` Task 2.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW2` (points 5, 6), SW1 point 3, SW14 points 2 and 6, SW17 points 1 and 2.
- `docs/decisions.md` — D74, D78, D80 and slice 09's entry.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` (the `sw` branch), `_vocabulary_labels`, `_criterion`, `_approval`, `_approved_vocabulary`, `_searchable`, `_count_probe`, `_pause`, `_checkpoint`, `_step_input` (the `vocabulary_target` branch and the allowlist), `_model_step`, `_freeze_expansion`.
  - `backend/deixis/workflow/approval.py` and `workflow/vocabulary.py` whole; `workflow/criterion.py::norm`; `providers/query_compiler.py::quoted`; `workflow/protocol.py`; `workflow/store.py`: `approval_step`, `approvals_of`, `submit_approval`, `set_step_output`; `workflow/views.py::approval_view` and `_approval_side`.
  - `backend/deixis/domain/contracts.py`: `VOCABULARY_TASKS`, the `vocabulary_target` check in `check_step_input`, `_check_vocabulary_labels`, the output-type tables; `domain/rules.py`: `LITERATURE_TASKS`, `NO_REPAIR_TASKS`, `CRITERION_CALLS`; `domain/skill.py::RUNTIME_FILES`; `api/app.py`: the approval route, `APPROVABLE_PAUSES`, where `CRITERION_CALLS` is added to an `sw` discovery budget.
  - `contracts/research/vocabulary-labels.schema.json`, `contracts/research/step-input.schema.json` (`vocabulary_target`), `methods/deixis-research/SKILL.md`, `provenance.json`, `references/vocabulary-labels.md`.
  - `apps/web/src/ProtocolApproval.tsx` whole, `api.ts` (the approval types), `labels.ts` (`termOrigins`, `dropReasons`), `Transcript.tsx` (the step kind → phase mapping), `apps/web/e2e/protocol-approval.spec.ts`, `tests/acceptance/fixture_server.py`, `tests/fakes.py::valid_response`, `tests/determinism_stages.py`.
  - Tests: `tests/test_protocol_approval.py`, `tests/test_approval_flow.py`, `tests/test_vocabulary_labels.py`, `tests/test_criterion_flow.py`.

## What to build

Tasks 1–7 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, check rows 08a, 08b and 09. `ls backend/deixis/storage/migrations | tail -1` and `grep -n '^## D' docs/decisions.md | head -1`: this slice takes the next free D number (expected D82) and no migration.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `cd apps/web && npm run build && npm run lint`, and the acceptance run. Record the numbers and the current `skill_package_hash`.
3. Set `sw-status.md` row 08c to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the request is posted twice; when it arrives while an old `submitted` is still stored; when the run is paused and resumed during the model call or between two count requests; when the model fails, and when the user asks again; when a second discovery run or a re-asked card meets an earlier approval that held suggestions; when the user types a dropped suggestion by hand; does the row order depend on the order the model wrote; does the expansion revision still carry the `model` origin; does a run that never asked keep its old protocol digest; does a `legacy` run ever open a step.
6. Task 7: full test run, build, lint, acceptance, `git diff --check`, the decision entry, the SW2 status line, row 08c, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts and the exact command; build, lint and Playwright results (A–G and H separately). `skill_package_hash` before and after (expected: changed).
- The names of the tests showing that a suggestion the user did not add is never searched, that an added suggestion's count is not asked again, that the `model` origin is derived on the server, and that a run that never asked keeps its body and digest.
- Confirmation that the method file's text is the slice file's, unchanged, and that no live model was called.
- Paths of the screenshots you looked at, and what you found and fixed in them.
- Whether the split point was used.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: a term of an `sw` protocol may carry the origin `model`; the `approval` body gains `suggestions` when they were asked for; nothing proposed is searched without the user adding it).
- Confirmation that the live service and the product database were not touched, and the commit hash.
