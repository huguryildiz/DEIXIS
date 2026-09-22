# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage inspection → source-linked answer with highlightable citation anchors. A FastAPI backend (`backend/deixis`) serves a React/Vite UI (`apps/web`) on loopback.

**Read [AGENTS.md](AGENTS.md) first.** It is the working agreement for the whole repo (evidence semantics, timeline states, UI hierarchy); read [.impeccable.md](.impeccable.md) too before touching `apps/web`. The README's status paragraph is out of date: all providers in `providers/registry.py` and the Codex, Claude Code, Gemini and DeepSeek model connections are implemented.

## Commands

Python 3.12 via `uv` (the venv must be native arm64 on Apple Silicon). Run from the repo root.

```sh
uv sync
PYTHONPATH=backend uv run pytest                                   # all deterministic tests (parallel by default, ~1–2 min; -n 0 for serial)
PYTHONPATH=backend uv run pytest tests/test_contracts.py -k anchor # one file / one test
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

**Runs and steps** (`workflow/`). A research has scope revisions; work happens in runs of two kinds, executed by `ResearchFlow` (`flow.py`):
- `discovery`: `search_plan` model step (concept vocabulary with one core concept, plus providers; D44) → `providers/query_compiler.py` builds every provider query from the synonyms and they are stored with the plan step → one provider search per compiled query (a failed search is recorded and the rest continue, D18) → `screening` model steps in batches → optional embedding similarity.
- `answer`: inspection (PDF fetch, one lookup for another open copy, lexical + semantic passage ranking fused with RRF) → `grounded_answer` model step → background `answer_review` claim check.

Every step is a row keyed by `operation_key`; a step that already `succeeded` returns its stored output, which is what makes pause/resume and crash recovery work without repeating model calls. `_checkpoint` stops the run on pause, cancel, or a newer scope revision. `worker.py` owns execution through an OS advisory lock and, on start, marks half-finished work `outcome_unknown`/`paused` rather than retrying it.

**Model boundary** (`flow._model_step`, `models/`, `domain/contracts.py`). Each model step gets a `StepInput` (records, allowlisted IDs, `step_input_id`, `scope_revision`, `skill_package_hash`) plus a strict JSON output schema. Everything sent is stored before the call. Invariants enforced in code: the model has no tools (any tool item → `model_isolation_violation`); output from a model other than the requested one is recorded but never used (`model_mismatch`, no silent fallback); schema repair is bounded; answer/review steps see short citation handles (D12) that are resolved back to record IDs before validation. Adapters implement the `ModelAdapter` protocol in `models/adapter.py`.

**Contracts** (`contracts/research/*.schema.json`) are the language-neutral step I/O. `domain/contracts.py` converts them to strict model schemas and adds semantic checks: IDs must come from the StepInput allowlist, the OpenAlex query shape, citation anchors located in passage text, LaTeX math well-formedness, and phrasebank phrasing (warnings only). A schema change usually also needs `tests/fixtures/research/{step-inputs,fake-outputs}.json` and `tests/fakes.py::valid_response` updated.

**Method package** (`methods/deixis-research/`) holds the instructions loaded into model steps (`domain/skill.py::RUNTIME_FILES`). Editing a runtime file changes `skill_package_hash`, which every StepInput echoes. The app refuses to start if the integrity check fails: frontmatter `name` must match the directory, relative links must resolve, and `provenance.json` must have its required keys.

**Providers** (`providers/`): one module per scholarly source, registered in `registry.py::CONNECTORS` (order = display order; `key_required` connectors without a key are `not_configured`). Per-provider query rules live in `query_rules.py`; records merge by DOI. PDF acquisition and version checks (D4, D22, D35) are in `documents/acquisition.py` and `documents/fetch.py`; text extraction uses PyMuPDF (`documents/pdf.py`).

**Storage** (`storage/`, `workflow/store.py`). One SQLite connection is shared by the API and worker on the event-loop thread: writes are short synchronous transactions, never `await` inside one, and UI-visible events are written in the same transaction as the state they describe. Schema changes are new numbered files in `storage/migrations/NNNN_name.sql`, applied at startup; an already-applied file is never re-run, so don't edit old ones.

**API** (`api/app.py`): loopback only, Host/Origin allowlist, double-submit CSRF (`deixis_csrf` cookie / `x-deixis-csrf` header) on mutations. `workflow/views.py` builds the research/passage view models the UI renders. `create_app(settings, adapters=, http_client=, fetcher=, start_worker=)` is the injection seam for tests.

**Frontend** (`apps/web/src`): React 19 + Tailwind 4 + shadcn/base-ui components in `components/ui`. `api.ts` is the typed client; `ResearchView.tsx`/`Transcript.tsx` render the run timeline, `citations.tsx`/`PassageSheet.tsx`/`PdfViewer.tsx` handle evidence inspection; UI strings go through `i18n.ts`/`labels.ts`.

## Tests

- pytest tests are model-independent: `tests/fakes.py::FakeAdapter`, mocked `httpx` transports and a fake PDF fetcher injected through `create_app`; `tests/helpers.py::make_pdf` builds tiny PDFs. `conftest.py` strips model API keys and swaps in an in-memory keyring for every test.
- The Playwright suite (`apps/web/e2e`) spawns `tests/acceptance/fixture_server.py`: the real app with a scripted model and mocked OpenAlex. Question markers such as `[rate-limit]`, `[model-down]` and `[invent-locator]` select failure scripts.
- Fixture records are labeled SYNTHETIC. Passing tests shows workflow behavior, not model quality or live provider access; say which one a result measures.

## Decisions and docs

Durable decisions go in [docs/decisions.md](docs/decisions.md) as `## DNN — title`, newest at the top, with Status/Date/Context/Decision/Limits (check the highest existing number; D27 is used twice). An accepted decision is not the same as a verified implementation. `docs/layout.md` says where each kind of file belongs; `docs/desktop/` is a dated handoff record and gets no new specifications. `docs/product/implementation-plan.md` is in Turkish.
