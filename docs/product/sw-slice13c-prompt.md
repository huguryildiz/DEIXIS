# Task: SW slice 13c — the efforts bound what a run collects: per-query read limits and provider waiting by effort, no wall-clock limit

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13c of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan is `docs/product/sw-slice13c-effort-collection-limits.md`; the decision is D88 in `docs/decisions.md`. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · medium. The review is done afterwards, together with 13b and 13d, against the slice files.

## Ground rules

1. Git: start with `git pull --ff-only` (13b `9b1f2a8` and 13d `59845ca` have landed; HEAD is at or after `5bc33e6`). Read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, `git pull --ff-only` again, then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 13c of `sw-status.md`. `TODO.md`, `scripts/local_index.py`, `.vscode/` and everything under `.local/` are the owner's: never stage them.
2. **No wall-clock limit anywhere.** The minute figures in D88 are targets the measurement step checks afterwards; nothing in the product stops a run at a time. If you find yourself adding a deadline, stop.
3. **Nothing read is dropped.** A read that ends early counts what it left (`unread_count`, `stop_reason`, slice 04c); a lookup batch that is not retried writes its records `abstract_not_found` and the next batch runs. Every skipped wait is recorded on the search or lookup step; never silent.
4. **`legacy` is unchanged:** one page per query, today's retries. A `legacy` request body stays byte for byte what it was.
5. **Constants in one place:** `SW_READ_LIMIT` becomes a per-effort dict and `PROVIDER_WAIT` (retry count by effort) sits beside it in `domain/rules.py`, hand-picked, with the D88 comment; both go into the protocol record's `thresholds.search_read` for this research's effort. `_request_allowance`, `_stop_reason`, `_search_pages` and `lookups.py` read them through `scope["effort"]`; `providers/common.py::request` takes the retry count as a parameter whose default is today's constant (so the `legacy` path and the lookup path you do not change keep their behaviour).
6. **UI:** only the three `effortOptions` detail strings in `apps/web/src/Home.tsx`, and only their numbers, derived from the constants the way the slice file says (the strings are already stale; slice 20 rewrites them, you do not). Read `.impeccable.md` first. `npm run build && npm run lint` must pass.
7. Existing tests: only the changes the slice file names. Do not invent: if a case falls between the rules, STOP AND REPORT.
8. No network in tests, no live provider request, no timing. Do not start, stop or query the service on port 8765 and do not open the product database.
9. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root on the native arm64 venv; the suite runs in parallel by default (about 100 s). Fixture records are SYNTHETIC and from at least two fields; no topic word in product code.

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` ("Bir tur", rows 04c, 05, 13, 13b, 13c, and the review log, especially the 04c row on request allowance and 429s); `docs/product/sw-implementation-plan.md` §2; the slice file whole; `docs/decisions.md` D75, D77, D87, D88.
- Code: `backend/deixis/domain/rules.py` (`SW_READ_LIMIT`, the effort dicts around it), `workflow/flow.py` (`_request_allowance`, `_stop_reason`, `_search_pages`, the page loop's retry handling, `_discovery` where the queries are read), `workflow/lookups.py` (whole: the Semantic Scholar batch loop and how a `rate_limited` batch is recorded), `providers/common.py` (`request`, `_retry_wait`, `MAX_RATE_LIMIT_RETRIES`, `MAX_TRANSIENT_NETWORK_RETRIES`), `providers/registry.py` (`Connector.searchable` from 13b), `workflow/protocol.py` (`thresholds`), `apps/web/src/Home.tsx` (`effortOptions`); tests: `tests/test_search_paging.py`, `tests/test_lookup_flow.py`, `tests/test_record_lookups.py`, `tests/test_providers.py` (retry tests), `tests/test_provider_roles.py`.

## What to build

Tasks 1–3 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `grep -n '^## D' docs/decisions.md | head -3` (expect D88 first; this slice implements it), `ls backend/deixis/storage/migrations | tail -1` (expect `0047`; no migration here).
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers (one expected failure: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`).
3. Set row 13c to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. Ask for every path: a `quick` page that gets a 429 (ends the read, counted, run continues and completes); a `quick` lookup batch that gets a 429 (`rate_limited`, records `abstract_not_found`, next batch runs); `standard` waits once; `detailed` as today; the request allowance shrinks with the limit; a resumed run reads its stored pages and does not re-request; the protocol record carries the effort's figures; `legacy` untouched.
6. Task 3: full test run, web build and lint, `git diff --check`, D88 status line, row 13c, second pull, commit, push.

## Final message

Files changed; baseline and final test counts with the command; the constants as implemented; the names of the tests for the `quick` 429 page, the `quick` 429 lookup batch, the allowance, the protocol record and `legacy`; every deviation with its reason; what is "ölçülmedi" (durations, recall effect, how many records `quick` leaves `abstract_not_found`); confirmation that the live service and product database were not touched; the commit hash.
