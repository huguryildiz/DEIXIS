# Task: SW slice 04a — code vocabulary and concept blocks

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 04a of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice04a-code-vocabulary.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 04a of `sw-status.md`.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, or any existing migration file. `skill_package_hash` must not change.
3. **The `legacy` workflow must behave exactly as before.** The change in `flow._discovery` is one `sw` branch; the legacy path keeps its `search_plan` model step line for line. No existing test expectation may change. If an existing test fails, the change is wrong or the slice file is; stop and report.
4. **No model call in the `sw` discovery path before the first search.** The acceptance test runs with a model adapter that fails on every call.
5. **No topic word in product code.** The word lists hold English function words, question frames, prepositions and field-independent general words only. If a test seems to need a field's term added to a list, the rule is wrong for that case: report it, do not add the word.
6. **Do not invent.** The cue table, the narrowing algorithm and the pause reasons are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
7. No network in tests. `count_works` is tested with a mocked `httpx` transport. One manual live count request to confirm the request shape is allowed; say so if you make it.
8. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. Stored step output is what makes a resumed run repeat nothing; the count probes must not run twice.
9. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765.
10. Fixture records and questions are SYNTHETIC. A passing test shows workflow behavior, not vocabulary quality.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md`, then `docs/product/sw-implementation-plan.md` §2 and the slice 04 entry.
- `docs/product/sw-slice04a-code-vocabulary.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW2` whole entry including Limits; SW1 point 3; SW3 point 5.
- `docs/decisions.md` — D18, D44, D70.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` (~215–290), `_search`, `_pause`, `_checkpoint`, and the passage-ranking terms (~710–720).
  - `backend/deixis/providers/query_compiler.py` (whole file) and `providers/query_rules.py`.
  - `backend/deixis/providers/openalex.py::search_works` and `providers/common.py` (`redact`, error statuses).
  - `backend/deixis/workflow/protocol.py::build_protocol`; `backend/deixis/domain/canonical.py`.
  - `backend/deixis/workflow/store.py`: `create_research`, `revise_scope`, `scope`, `step`, `set_step_output`.
  - `backend/deixis/api/app.py`: the create-research and revise-scope request bodies.
  - Tests: the query compiler tests, `tests/test_protocol_record.py`, `tests/test_api_flow.py` (how a discovery run is driven through `create_app` with a fake adapter and a mocked OpenAlex), `tests/fakes.py`, `tests/determinism_stages.py`.

Line numbers are approximate; find the symbol.

## What to build

Tasks 1–7 of the slice file, in that order.

## Procedure

1. `git status --short` (expect a clean tree), `ls backend/deixis/storage/migrations | tail -1` (expect `0039_record_links.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D72). If any differs, say so before going on.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Expect `1 failed, 855 passed`; the one failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 04a to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a resumed run must not probe again); what happens when the probe fails or the model is down; does the result depend on the order rows or providers arrive in.
6. Task 7: the dry run on the two topic questions, full test run, `git diff --check`, the `D<NN>` entry, the SW2 status line, row 04a, then the commit and push.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, commit nothing, and write the remaining tasks into row 04a of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- The dry-run extraction of the two topic questions: blocks, claim words, exclusion words.
- The size of each word list and how you checked that none holds a field's term.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the protocol record's content changes).
- Confirmation that the live service was not touched, and the commit hash.
