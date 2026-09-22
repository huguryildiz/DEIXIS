# Task: SW slice 13 — run the sw backbone once, end to end, with a real model, and record where it stops

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13 of the search workflow build: a smoke run, not a build. The master file is `docs/product/sw-status.md`; the run plan is `docs/product/sw-slice13-smoke-test.md` and is the single source of truth. Recommended model for this session: Fable, effort high.

## Ground rules

1. Git: `git pull --ff-only` first. Nothing under `.local/` is ever staged. A fix found by the run is its own commit (`Smoke slice 13: …`) with a failing test first, full pytest green except the one known failure, then `git push origin main`; no branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. `TODO.md`, `scripts/local_index.py` and `.vscode/` are the owner's: leave them alone.
2. **The live library is not touched.** Everything runs against `DEIXIS_DATA_DIR=.local/sw-smoke-2026-09-22/data` on port 8799. Do not start, stop or query the service on port 8765 and do not open `~/Library/Application Support/DEIXIS`.
3. **Freeze the expectation before the first call** (Task 1 of the plan) and never edit it afterwards; deviations go to `result.md`.
4. **No quality judgement.** You record whether it ran, where it stopped, counts per stage, calls, tokens and time. Whether labels, phrases or the answer are good is "ölçülmedi" and belongs to slice 24. Do not tune a prompt, a threshold or a method file because an output looks poor.
5. **A product bug is fixed, not worked around:** failing test with the fake model, minimal fix, separate commit, then the whole run again in a fresh data dir. A paused or failed run is never resumed as a result. An external cause (provider 5xx, quota, key) is recorded and the run repeated once.
6. The approval pause is passed the product's way: approve the proposal as proposed through the API, record the card body, and do not set `DEIXIS_PROTOCOL_APPROVAL=as_proposed`.
7. The three defaults (model `deepseek-flash` on the `deepseek` connection at `high`, the quantum question verbatim, effort `quick`) are plan defaults the owner did not confirm; if the owner names others before you start, use those and say so.
8. Read the numbers from stored steps and tables (read-only SQLite), not from your memory of the log; where two sources disagree, write both.
9. Do not ask the owner for keys or tokens. If `GET /api/connections/deepseek` is not ready, stop and report.

## Read first

- `docs/product/sw-status.md` (the "Bir tur" section, rows 01–12 and the whole review log), `docs/product/sw-implementation-plan.md` §2 and the slice 13 entry, `docs/product/sw-slice13-smoke-test.md` whole.
- `docs/decisions.md` D78, D80, D81, D83, D84, D85 (what each stage writes and what its limits say).
- `backend/deixis/api/app.py`: research creation, `start_run`, `protocol-approval`, the run actions; `backend/deixis/config.py`; `backend/deixis/__main__.py` (`serve --port --no-browser`); `workflow/views.py::research_view`.
- The step outputs you will read: `code:abstract_stage`, `code:fulltext_plan` / `code:fulltext_summary`, `code:adjudication_plan` / `code:adjudication_summary`, `protocol:freeze`; tables `stage_decisions`, `selections`, `model_proposals`, `model_sessions` (`token_usage_json`), `run_steps`.

## What to do

Tasks 1–4 of the plan, in order.

## Final message

Written for the owner, in Turkish, plain language first: did it run to the answer, where did it stop, the five expectation lines each marked held / not held, one table of stage counts, calls / tokens / time, bugs found with commit hashes, whether the run was repeated after a fix, what stayed unmeasured (named "ölçülmedi"), confirmation that the live library and port 8765 were not touched, the `.local` path, and which of model / question / effort were plan defaults.
