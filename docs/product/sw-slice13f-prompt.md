# Task: SW slice 13f — discovery searches read in parallel across hosts and written in query order, with the request allowance split per query (D89)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13f of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan is `docs/product/sw-slice13f-search-parallelism.md`; the measurement that motivates it is the last section of `docs/product/sw-measure-2026-09-22.md` (re-measurement after 13e). The slice writes decision D89. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · high. The review is a full one (Fable), so list every place you used your own judgement.

## Ground rules

1. Git: `git pull --ff-only` first, work in the main checkout on `main`, read-only until the slice is finished; then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or reset. If the slice is not finished, commit nothing: write what remains into row 13f of `sw-status.md` and say so.
2. **Same input, same evidence.** In every run where no query reaches its allowance: same `search_runs` rows, record / version / candidate rows and head records, step outputs and `operation_key`s, events, in the same write order. Only step times and the order in which `run_steps` rows are created may change. The proof is the equality tests of Task 1, written FIRST on the unchanged sequential code, then kept passing.
3. **The one behaviour change is D89:** the request allowance is split per query before reading, each query is checked only against its own share, and a query that uses up its share ends its own read (`stop_reason: "budget_exhausted"`, counted as unread); the run no longer pauses on `budget_exhausted` in the search stage. D18 is unchanged. Nothing else changes behaviour.
4. **Network work and store writes are separated:** host-group tasks read pages and write nothing to the store except request counts; an applier writes pages in query-index order. At most one request per host at a time; at most `SEARCH_PARALLEL_HOSTS = 4` host groups in flight. Existing pacers, `page_gap`, arXiv's interval and D88's per-effort rate-limit wait stay as they are, inside the group task.
5. **Event-loop rule stays:** short synchronous transactions, no `await` inside one, no `asyncio.to_thread` for store work.
6. **Stop-and-report cases** are in the slice file (a page read on the network whose step could stay `outcome_unknown` and never be asked again; anything that makes a query's allowance depend on another query's history). Do not invent; if a case falls between the rules, STOP AND REPORT.
7. Existing tests: only the changes the slice file names. No network in tests, no live model, no live provider. Do not start, stop or query the service on port 8765 and do not open the product database or anything under `.local/`.
8. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root; the suite runs in parallel by default (about 2 min; `-n 0` for serial). Fixture records are SYNTHETIC and from at least two fields; no topic word in product code.
9. The method package (`methods/deixis-research/`) and the contracts are not touched; `skill_package_hash` must be unchanged at the end (`PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`, before and after).

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` ("Bir tur", rows 04c, 07, 13c, 13ö, 13e, 13f); the slice file whole; the last section of `docs/product/sw-measure-2026-09-22.md`; `docs/decisions.md` D18, D75, D87, D88; `docs/product/sw-slice13e-retrieval-parallelism.md` Task 2 (the earlier attempt and why it was left out).
- Code: `backend/deixis/workflow/flow.py` (`_discovery`'s two search loops, `_search`, `_search_pages`, `Page`, `extra_page_requests`, `_stop_reason`, `_skip_unsearchable`, `_expansion`, `_pause`, `_checkpoint`, `_send_through_limiter` — the stop pattern; `_fulltext_fetch` as 13e built it), `workflow/store.py` (`add_usage`, `start_step`, `finish_step`, `record_search`), `domain/rules.py` (`SW_READ_LIMIT`, `PROVIDER_WAIT`, the effort budgets), `providers/registry.py` (`CONNECTORS`, the hosts each connector calls), `providers/common.py::send`, `providers/pacing.py`, `documents/fetch.py` (13e's host gate, as a pattern); tests: `tests/test_provider_flow.py`, `tests/test_search_paging.py`, `tests/test_effort_limits.py`, `tests/determinism_stages.py`, `tests/test_determinism.py`, `tests/fakes.py`.

## What to build

Tasks 1–4 of the slice file, in that order. Task 1 is the equality tests on the unchanged code; each later task's tests come before its code.

## Procedure

1. `git pull --ff-only`; `git status --short`; baseline `PYTHONPATH=backend:. uv run pytest -q` (record the count); record `skill_package_hash`.
2. Set row 13f to `uygulanıyor`.
3. Task 1: equality tests (a)–(c) on the sequential code; green.
4. Task 2: per-query allowance tests, then the per-query share and count; all green, Task 1 still green.
5. Task 3: parallelism, order, stop and step-time tests, then the host groups and the ordered applier; all green.
6. Task 4: D89, full test run, `git diff --check`, `skill_package_hash` unchanged, row 13f → `uygulandı, inceleme bekliyor`, commit, push.

## Final message

Files changed; baseline and final test counts; the names of the equality, allowance, parallelism, order, stop and step-time tests; how the per-query share is computed and how far its total departs from today's run allowance (numbers per effort); where the per-query count is stored and why; where a query's allowance end is recorded; how hosts are derived and which connectors share one; how the applier keeps query order (one paragraph); every place you used your own judgement, with the rule you applied; every deviation from the slice file with its reason; what is "ölçülmedi" (the wall-clock gain, whether 4 is the right bound, whether four providers at once raises 429 / 406, whether a per-query share ever runs out on real runs); confirmation that the live service, the product database and `.local/` were not touched; the commit hash.
