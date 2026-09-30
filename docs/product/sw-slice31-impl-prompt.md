# Task: SW slice 31 — remove the `legacy` search workflow (implementation)

Repo: the git worktree you are started in (`-C`), branched from `main` after P6 slice 1 P9 landed. All paths are
relative to it. The single source of truth is `docs/product/sw-slice31-legacy-removal.md` (the plan, Turkish, reviewed
by gpt-6-sol high over nine rounds). Read it in full, then D117 and D114 at the top of `docs/decisions.md`,
`AGENTS.md` and `CLAUDE.md`. Where the plan gives a line number, it refers to code before `389c344`; find the current
place with `rg`.

## What to build (summary; the plan decides every detail)

1. New researches never run `legacy` discovery. Remove the code that **executes** it: the `search_plan` and
   `screening` model steps of the legacy discovery branch in `workflow/flow.py`, `_search` (single unpaged request),
   the legacy screening batch loop and its `apply_screening_proposal` call, their `supported_tasks` entries, the
   matching `domain/skill.py` task map rows, `domain/contracts.py` / `contracts/research/*.schema.json` entries that only
   the removed steps use, the legacy `effort_limits` branches, `protocol.py`'s legacy body variants for new protocols,
   `store.apply_screening_proposal`, and `create_research` / `scope.setdefault` defaults (become `sw`).
2. Keep everything the plan lists under "Kalır" / "Kalacaklar": every branch that **rejects, skips or only reads**
   a stored `legacy` record (views, Transcript rendering of stored plan/screening notes, `labels.ts`, queue-context
   rejection, `decisions.py` no-derivation rule, full-text queuing guards, `providers/registry.py` legacy branch,
   answer-side code that reads stored `search_plan` concepts and `_criterion_phrases`, `SCREENING_BATCH`,
   `EffortBudget.max_candidates`, `_skip_unsearchable`, `_screening` for sw, `query_compiler.STRATEGIES`).
3. Old `legacy` researches are read-only on the discovery side (plan item 3): one guard `legacy_research_read_only(scope)`
   → 409 `legacy_research_read_only` for `discovery`, `fulltext_fetch`, `fulltext_adjudication` only, on every API
   entry the plan names (list the ones you find with `rg -n "start_run\|queue_run\|requeue" backend/deixis/api` in the
   D record), **and** a fail-closed guard in `Store` on every path that opens a scope revision (except
   `create_research`) and every path that sets a run to `queued` or `running` (including `create_run` before its
   idempotency early return, `queue_failed_search_retry`, resume/requeue paths and `update_run`). List every SQL that
   writes `runs.status` (`rg -n "UPDATE runs|INSERT INTO runs" backend/deixis`) and classify each (guarded / only writes a
   stopping status) in the D record. `research.read_only_reason` in the view; the UI hides both "Search again" entries,
   the scope edit form and the PDF-selection entry and shows the one-line explanation; `hasQueue` stays gated on `sw`.
4. Startup cleanup after `Worker.recover`, before the first run is picked (plan item 4), in the same transaction as its
   `reason: legacy_workflow_removed` event.
5. `DEIXIS_SEARCH_WORKFLOW` is no longer read; if set, one warning at startup, never an error (`serve`, `backup`,
   `restore` keep working).

## Tests, docs, checks

Exactly as the plan's "Testler", "Belgeler", "Denetimler" sections say: legacy-only tests deleted or moved to `sw`
(each deletion listed with what replaces it or "artık yok"), fixtures, the Playwright `[model-down]` marker moved to an
`sw` model step, the five new test groups (a)–(e). No migration. The D record takes the first free number after
`git pull --rebase` (expected D119; D118 is P9). Methods package edits change `skill_package_hash`; record the new
hash. Add the row-31 status and the D record; update `CLAUDE.md` "Runs and steps" and `README.md` where they describe
legacy discovery.

Run: `PYTHONPATH=backend uv run pytest` (one known memory-limit failure is pre-existing), `cd apps/web && npm run build
&& npm run lint` (warnings must not exceed 17), Playwright full run with `DEIXIS_ACCEPTANCE_DIR`, `git diff --check`,
and `rg -n "legacy" backend apps/web/src tests methods contracts` with a one-line justification per remaining hit in
the D record.

## Limits

- No real-model calls. No commit, no push: leave the changes in the working tree.
- Another session works on P6 slice 1 P12 in parallel on `main` (report export: `report/`, `ReportView.tsx`,
  `api.ts`, `i18n.ts`, maybe `api/app.py`). Touch those files only where the plan requires it.
- At the end, write a short Turkish report: what changed per file, test/build/lint/Playwright results with numbers,
  every place you used your own judgement, and anything in the plan you could not do.

## Environment

The venv and `apps/web/node_modules` are already installed: use `PYTHONPATH=backend uv run --no-sync pytest ...` and
never `uv sync` / `npm ci` (no network). Use `.local/` inside this worktree for any scratch or acceptance directory. If
the sandbox stops Playwright from launching Chrome, say so in the report; the reviewer runs it.
