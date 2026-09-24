# Task: SW slice 17a: full-text fetch overlaps discovery

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice17a-fetch-overlap.md` and it is
the only source of truth. Read its sections "Ortak kararlar" and "Kalıcı koordinasyon sözleşmesi" first. The master
file is `docs/product/sw-status.md`, row 17a. List every place where you used your own judgement.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave `TODO.md`, `.vscode/`
   and `scripts/local_index.py` alone. If the slice is not finished, commit nothing: write what remains into row 17a.
2. **Unchanged:** the model contract (`skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`), `legacy`, the set of fetched works (under
   decision 2's conditions), fetch codes (`fulltext.OWNED_CODES`), limits, `host_gate`, fetch parallelism (4) and the
   worker's one-run model. No new reason code. A migration only if the contract does not fit in `run_steps` (the
   highest is `0051`).
3. **Tests** use no network and no live model. Change an existing test only where the plan names it, and list each
   change. Playwright A–J must pass.
4. **Port 8765 and the product database are off limits.** Live runs (decision 8) go under `.local/`, on another port
   with their own `DEIXIS_DATA_DIR`. The owner chooses the model.
5. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.

## Build

Tasks 1–6 of the plan, in order:

1. `safe_to_fetch`, with its property tests.
2. The fetch branch and the coordinator inside `_discovery`.
3. Pause, resume and crash.
4. Timeline.
5. Tests.
6. Acceptance.

Every item of the contract (1–7) is fixed by a test.

## Close

Write a new D number at the top of `docs/decisions.md`, and update the SW10 status line and row 17a. Run the full
pytest suite, `npm run build`, `npm run lint` (17 warnings) and Playwright A–J; check `git diff --check` and the hash.
The final message, in Turkish, gives what was done, the judgement calls, the changed tests, the test counts, and the
live measurement next to what was not measured.
