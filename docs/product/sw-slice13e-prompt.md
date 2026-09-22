# Task: SW slice 13e — retrieval polite per host and parallel across hosts, discovery searches parallel across providers with the same write order, one timed-out reading call retried once

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13e of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan is `docs/product/sw-slice13e-retrieval-parallelism.md`; the measurement that motivates it is `docs/product/sw-measure-2026-09-22.md`. No decision record: behaviour does not change. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · high. The review is a full one (Fable), so list every place you used your own judgement.

## Ground rules

1. Git: `git pull --ff-only` first, work in the main checkout on `main`, read-only until the slice is finished; then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or reset. If the slice is not finished, commit nothing: write what remains into row 13e of `sw-status.md` and say so.
2. **Behaviour is identical.** Same input → same `stage_decisions`, `selections`, `pdf_discoveries`, `search_runs`, record and version rows, step outputs, events, in the same write order. Only when steps *finish* may change. The proof is the equality tests the slice file names, written FIRST on the unchanged code, then kept passing.
3. **Event-loop rule stays:** short synchronous transactions, no `await` inside one, no `asyncio.to_thread` for store work. Parallelism lives in network waits only. The model limiter (`deps.limiter`) is for model calls; downloads get their own bound.
4. **Network work and store writes are separated in the search stage:** pages are read per query in their own task, results are applied in query-index order. If the page allowance (`extra_page_requests`) or anything else decides *while* reading in a way that depends on which provider answered first, STOP AND REPORT — do not pick an order.
5. **Stop-and-report cases** are in the slice file's Global constraints (two in-flight works that could open the same source version; the allowance rule). Do not invent; if a case falls between the rules, STOP AND REPORT.
6. Existing tests: only the changes the slice file names. No network in tests, no live model, no live provider. Do not start, stop or query the service on port 8765 and do not open the product database or anything under `.local/`.
7. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root; the suite runs in parallel by default (about 2 min; `-n 0` for serial). Fixture records are SYNTHETIC and from at least two fields; no topic word in product code.
8. The method package (`methods/deixis-research/`) and the contracts are not touched; `skill_package_hash` must be unchanged at the end (`PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`, before and after).

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` ("Bir tur", rows 07, 09, 13, 13c, 13d, 13ö, 13e, and the review log rows for 07 and 09: they are about the plan being frozen and the one-lookup rule); the slice file whole; `docs/product/sw-measure-2026-09-22.md` ("Zaman nereye gidiyor"); `docs/decisions.md` D18, D35, D48, D81, D83, D85, D88.
- Code: `backend/deixis/workflow/flow.py` (`_send_through_limiter` — the pattern; `_fulltext_fetch`, `_fulltext_plan`, `_fulltext_work`, `_fetch_work_text`, `_acquire_pdf`, `_fulltext_summary`; `_discovery`'s two search loops, `_search_pages`, `_search`, `extra_page_requests`, `_skip_unsearchable`; `_model_step`'s `client_timeout` / `model_call_failed` path and `budget_short`), `workflow/concurrency.py`, `workflow/fulltext.py` (`fetch_plan`, `group_of`), `documents/fetch.py`, `documents/acquisition.py`, `providers/pacing.py`, `providers/common.py::send`, `models/adapter.py` (turn timeout) and `models/codex_rpc.py` (where `client_timeout` is set); tests: `tests/test_fulltext_flow.py`, `tests/test_fulltext_plan.py`, `tests/test_provider_flow.py`, `tests/test_search_paging.py`, `tests/test_adjudication_flow.py`, `tests/determinism_stages.py`, `tests/fakes.py` (`FakeAdapter`, the fake fetcher).

## What to build

Tasks 1–4 of the slice file, in that order. Each task's tests first, on the unchanged code.

## Procedure

1. `git pull --ff-only`; `git status --short`; baseline `PYTHONPATH=backend:. uv run pytest -q` (record the count); record `skill_package_hash`.
2. Set row 13e to `uygulanıyor`.
3. Task 1: equality test (a) on the unchanged sequential code, then (b) and (c), then the download sender and the host gate; all green.
4. Task 2: equality test (a) with two providers sharing a DOI, then (b) and (c), then the split of reading and applying; all green.
5. Task 3: the three tests, then the retry-once path, scoped to `fulltext_adjudication` and `abstract_screening` only.
6. Task 4: full test run, `git diff --check`, `skill_package_hash` unchanged, row 13e → `uygulandı, inceleme bekliyor`, commit, push.

## Final message

Files changed; baseline and final test counts; the names of the three equality tests and of the parallelism and stop tests; the constant chosen for the download bound and where the host gate lives; how the search stage applies results in query order (one paragraph); every place you used your own judgement, with the rule you applied; every deviation from the slice file with its reason; what is "ölçülmedi" (the wall-clock gain, the politeness of one-per-host on real publishers, whether 4 is the right bound); confirmation that the live service, the product database and `.local/` were not touched; the commit hash.
