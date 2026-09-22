# Task: SW slice 13b — Crossref leaves the search and stays for DOI and metadata verification

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13b of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan is `docs/product/sw-slice13b-crossref-verification-only.md`; the decision is D87 in `docs/decisions.md`. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · medium. The review is done later, together with 13c and 13d, against the slice file, so everything you decide on your own must be named in your final message.

Slice 13d runs in parallel in a separate worktree and touches `flow._abstract_code_stage`, `_write_abstract_codes`, `decisions.py`, `criterion.py` and `views.py`. You do not touch those; you touch `_discovery`'s provider list and the search step. If your work needs one of 13d's functions changed, stop and report.

## Ground rules

1. Git: start with `git pull --ff-only`. Read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, `git pull --ff-only` again (13d may have landed; if the pull is not a fast-forward, stop and report), then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 13b of `sw-status.md`. `TODO.md`, `scripts/local_index.py`, `.vscode/` and everything under `.local/` are the owner's: never stage them.
2. **Nothing is deleted and nothing old changes meaning.** Records Crossref found, `search_runs` rows, protocol records and `record_lookup:crossref` steps stay as they are. A stored plan that names a Crossref query is not searched again on resume: the search step writes `skipped` / `provider_not_searchable` and the run goes on (the D18 pattern).
3. **No provider name in the flow.** The filter is `Connector.searchable`; `flow` and `query_compiler` ask the connector, they never say "crossref". `PLAIN_PROVIDERS` stays, Semantic Scholar keeps its plain query.
4. **Verification paths are untouched:** `workflow/lookups.py`'s Crossref lookup, `documents/acquisition.py`'s DOI checks and their tests do not change. If a test there fails, your change is wrong.
5. **`legacy` keeps working:** the provider list the `search_plan` model step is shown loses Crossref too, but an old `legacy` research and its stored steps are read back as they were.
6. **UI:** only the connection list's role label (`labels.ts` / `i18n.ts`, both languages). Read `.impeccable.md` first. `npm run build && npm run lint` must pass.
7. Existing tests: only the changes the slice file names. Do not invent: if a case falls between the slice file's rules, STOP AND REPORT.
8. No network in tests and no live provider request anywhere. Do not start, stop or query the service on port 8765 and do not open the product database.
9. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root on the native arm64 venv; the suite runs in parallel by default (about 75 s). Fixture records are SYNTHETIC and from at least two fields; no topic word in product code.

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` ("Bir tur", rows 04a, 04c, 05, 13, 13b, and the review log); `docs/product/sw-implementation-plan.md` §2; the slice file whole; `docs/decisions.md` D18, D75, D77, D87.
- Code: `backend/deixis/providers/registry.py` (whole), `providers/query_compiler.py` (whole), `providers/crossref.py` (what `search` and the lookup do), `workflow/flow.py` (`_discovery`, `_search_page`, `_request_allowance`, the search step's `skipped` path if one exists, `_stop_reason`), `workflow/lookups.py` (the Crossref batch), `api/app.py` (`available_providers`, the connections view, research creation), `apps/web/src/{labels.ts,i18n.ts}`; tests: `tests/test_query_compiler.py` (if present, else `tests/test_provider_records.py`), `tests/test_search_paging.py`, `tests/test_lookups*.py`, `tests/test_api_flow.py` (provider list assertions).

## What to build

Tasks 1–3 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `grep -n '^## D' docs/decisions.md | head -3` (expect D88, D87, D86; this slice implements D87), `ls backend/deixis/storage/migrations | tail -1` (expect `0047`; no migration here).
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers (one expected failure: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`).
3. Set row 13b to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. Ask for every write path: a resumed `sw` run whose stored plan holds a Crossref query; a `legacy` research created before this slice; the lookup path; the protocol record's provider list (what a new `sw` research freezes).
6. Task 3: full test run, web build and lint, `git diff --check`, D87 status line, row 13b, second pull, commit, push.

## Final message

Files changed; baseline and final test counts with the command; the names of the tests showing that no `sw` query is compiled for Crossref, that a stored Crossref query is skipped on resume, that the lookup still runs, and that `legacy` is unchanged; every deviation with its reason; what is "ölçülmedi" (recall cost; measured after 13c); confirmation that the live service and product database were not touched; the commit hash.
