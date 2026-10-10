# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage inspection → source-linked answer with highlightable citation anchors. A FastAPI backend (`backend/deixis`) serves a React/Vite UI (`apps/web`) on loopback.

**Read [AGENTS.md](AGENTS.md) first.** It is the working agreement for the whole repo (evidence semantics, timeline states, UI hierarchy); read [.impeccable.md](.impeccable.md) too before touching `apps/web`. All providers in `providers/registry.py` and the Codex, Claude Code, Gemini and DeepSeek model connections are implemented, and the README's status paragraph says so (P9 H1).

## Commands

Python 3.12 via `uv` (the venv must be native arm64 on Apple Silicon). Run from the repo root.

```sh
uv sync
PYTHONPATH=backend uv run pytest                                   # quick run: slow tests (tests/slow_tests.txt) left out, 6 workers, ~1.5 min
PYTHONPATH=backend uv run pytest -m "slow or not slow"            # everything, ~3.5 min; run before a push
PYTHONPATH=backend uv run pytest tests/contracts/test_contracts.py -k anchor # one file / one test
PYTHONPATH=backend uv run python -m deixis serve                   # http://127.0.0.1:8765, serves apps/web/dist
PYTHONPATH=backend uv run python -m deixis serve --dev --no-browser   # + (cd apps/web && npm run dev) → Vite on :5178 proxies /api

cd apps/web
npm ci
npm run build        # tsc -b && vite build; the backend serves dist/
npm run lint         # oxlint
DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance   # Playwright A–G in Chrome; needs a fresh build
```

Real-model behavior cases (not part of pytest) run against the Codex connection: `PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/run_cases.py --model gpt-5.6-luna`. Results go to ignored `.local/`. `scripts/p4_eval/measure.py` is the P4 measurement kit (see README).

Runtime data (SQLite `library.sqlite`, PDFs, provider payloads, `codex-home`) lives in `DEIXIS_DATA_DIR` (default `~/Library/Application Support/DEIXIS`), never in the repo. Provider/model keys come from an untracked `.env` (template: `docs/product/providers.env.example`) or the system keychain via `credentials.py`.

## Architecture

**Runs and steps** (`workflow/`). A research has scope revisions; `ResearchFlow` (`flow.py`) executes its runs:
- `discovery` always runs the fast path (`fast_path.py`, policy `fast_path_v1`), frozen into the run's budget with the Quick/Standard/Detailed numbers in `fast_path.MODES`. Plan: code takes search words from the question (`question_words`), three optional `vocabulary_labels` calls sort them into blocks, a `search_query` model call writes the query blocks (setting `DEIXIS_SEARCH_QUERY=model`, the default; a failed call stops the run with `search_query_failed`), at most one OpenAlex request routes the sources, three optional `criterion_proposal` calls vote the inclusion criterion, and the approval is recorded as `unattended` with nobody asked. An empty or too-broad vocabulary ends the run with `vocabulary_empty` / `vocabulary_too_broad`; the user rewrites the question. The protocol and its search plan freeze after these planning requests (OpenAlex term counts, routing) and before the first request that fetches search results. Search (`fast_search.py`): one OpenAlex semantic page plus OpenAlex keyword pages under a record cap; Detailed adds one Semantic Scholar bulk query. One citation-chain round (`fast_chain.py`, OpenAlex only) overlaps the search. Ranking embeds the pool and freezes the list. Read (`small_batch.execute` → `fast_read.py`): Semantic Scholar and Crossref abstract lookups for the top N (then Scopus when it is in scope, configured, its COMPLETE view is confirmed and within budget), two `abstract_screening` reads per batch, full text for at most K works (`fulltext_adjudication`), the rest queued for background PDF fetch. Abstract screening never includes a source on its own. When discovery completes, one answer run is queued automatically.
- `answer`: a discovery-bound answer runs `fast_answer.py`: it answers from the evidence the read stage owned at its cutoff, then queues a separate `answer_review` run; late full text can produce one new answer revision (`late_revision.py`). An answer over attached PDFs only (no completed discovery) uses inspection (PDF fetch, one lookup for another open copy, lexical + semantic passage ranking fused with RRF) → `grounded_answer`.

Every step is a row keyed by `operation_key`; a step that already `succeeded` returns its stored output, which is what makes pause/resume and crash recovery work without repeating model calls. `_checkpoint` stops the run on pause, cancel, or a newer scope revision. `worker.py` owns execution through an OS advisory lock and, on start, marks half-finished work `outcome_unknown`/`paused` rather than retrying it.

**Model boundary** (`flow._model_step`, `models/`, `domain/contracts.py`). Each model step gets a `StepInput` (records, allowlisted IDs, `step_input_id`, `scope_revision`, `skill_package_hash`) plus a strict JSON output schema. Everything sent is stored before the call. Invariants enforced in code: the model has no tools (any tool item → `model_isolation_violation`); output from a model other than the requested one is recorded but never used (`model_mismatch`, no silent fallback); schema repair is bounded; answer/review steps see short citation handles (D12) that are resolved back to record IDs before validation. Adapters implement the `ModelAdapter` protocol in `models/adapter.py`.

**Contracts** (`contracts/research/*.schema.json`) are the language-neutral step I/O. `domain/contracts.py` converts them to strict model schemas and adds semantic checks: IDs must come from the StepInput allowlist, the OpenAlex query shape, citation anchors located in passage text, LaTeX math well-formedness, and phrasebank phrasing (warnings only). A schema change usually also needs `tests/fixtures/research/{step-inputs,fake-outputs}.json` and `tests/fakes.py::valid_response` updated.

**Method package** (`methods/deixis-research/`) holds the instructions loaded into model steps (`domain/skill.py::RUNTIME_FILES`). Editing a runtime file changes `skill_package_hash`, which every StepInput echoes. The app refuses to start if the integrity check fails: frontmatter `name` must match the directory, relative links must resolve, and `provenance.json` must have its required keys.

**Providers** (`providers/`): one module per scholarly source, registered in `registry.py::CONNECTORS` (order = display order; `key_required` connectors without a key are `not_configured`). Per-provider query rules live in `query_rules.py`; records merge by DOI. PDF acquisition and version checks (D4, D22, D35) are in `documents/acquisition.py` and `documents/fetch.py`; text extraction uses PyMuPDF (`documents/pdf.py`).

**Storage** (`storage/`, `workflow/store.py`). One SQLite connection is shared by the API and worker on the event-loop thread: writes are short synchronous transactions, never `await` inside one, and UI-visible events are written in the same transaction as the state they describe. The schema starts from one squashed `storage/migrations/0001_baseline.sql` (clean start, 10 Oct 2026); a schema change is a new numbered file from `0002_` on, applied at startup. An already-applied file is never re-run, so never edit it (the baseline included), and don't drop tables.

**API** (`api/app.py`): loopback only, Host/Origin allowlist, double-submit CSRF (`deixis_csrf` cookie / `x-deixis-csrf` header) on mutations. `workflow/views.py` builds the research/passage view models the UI renders. `create_app(settings, adapters=, http_client=, fetcher=, start_worker=)` is the injection seam for tests.

**Frontend** (`apps/web/src`): React 19 + Tailwind 4 + shadcn/base-ui components in `components/ui`. `api.ts` is the typed client; `ResearchView.tsx`/`Transcript.tsx` render the run timeline, `citations.tsx`/`PassageSheet.tsx`/`PdfViewer.tsx` handle evidence inspection; UI strings go through `i18n.ts`/`labels.ts`.

## Tests

- Test modules live in topic folders under `tests/` (`app`, `candidates`, `contracts`, `discovery`, `documents`, `hardening`, `lineage`, `measurement`, `models`, `providers`, `reextract`, `report`, `review`, `storage`, `watch`); shared helpers (`fakes.py`, `helpers.py`, `*_helpers.py`, `conftest.py`) stay at `tests/`. Every folder is on `pythonpath` in `pyproject.toml`, so `from test_api_flow import ...` works across folders; a new folder must be added there.
- pytest tests are model-independent: `tests/fakes.py::FakeAdapter`, mocked `httpx` transports and a fake PDF fetcher injected through `create_app`; `tests/helpers.py::make_pdf` builds tiny PDFs. `conftest.py` strips model API keys and swaps in an in-memory keyring for every test.
- The Playwright suite (`apps/web/e2e`) spawns `tests/acceptance/fixture_server.py`: the real app with a scripted model and mocked OpenAlex. Question markers such as `[rate-limit]`, `[model-down]` and `[invent-locator]` select failure scripts.
- Fixture records are labeled SYNTHETIC. Passing tests shows workflow behavior, not model quality or live provider access; say which one a result measures.

## Decisions and docs

Durable decisions go in [docs/decisions.md](docs/decisions.md) as `## DNN — title`, newest at the top, with Status/Date/Context/Decision/Limits. The log restarted on 10 Oct 2026 at `D1 — Baseline`, which lists the decisions in force; the next entry is D2. Older D numbers in code and test comments point to the old log in Git history. An accepted decision is not the same as a verified implementation. `docs/layout.md` says where each kind of file belongs. Design records, plans and closed-phase archives live in the ignored `.local/docs/` (local only, not in git); do not add new ones to `docs/`.
