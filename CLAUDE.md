# CLAUDE.md

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage reading → an answer whose every citation points to a located passage. FastAPI backend (`backend/deixis`) serves a React/Vite UI (`apps/web`) on loopback. This file is the working agreement for every agent and contributor; `AGENTS.md` points here.

## Commands

```sh
uv sync
uv run pytest                          # quick: slow tests left out, 6 workers
uv run pytest -m "slow or not slow"    # everything; run before a push
uv run python -m deixis serve          # http://127.0.0.1:8765, serves apps/web/dist
cd apps/web && npm ci && npm run build && npm run lint
DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance   # Playwright, needs a fresh build
```

Python 3.12, native arm64. Runtime data lives in `DEIXIS_DATA_DIR` (default `~/Library/Application Support/DEIXIS`), never in the repo; keys come from the macOS Keychain.

## Where things are

- `workflow/`: runs and steps. Discovery is the fast path (`fast_path.py`, `fast_search.py`, `fast_chain.py`, `fast_read.py`); answers in `fast_answer.py`. Each step is a row keyed by `operation_key`, so a succeeded step is never re-run.
- `models/` + `flow._model_step`: a model call gets a stored `StepInput` and a strict schema; no tools, no silent model fallback, bounded repair.
- `contracts/research/*.schema.json` + `domain/contracts.py`: step I/O and semantic checks. A schema change also updates `tests/fixtures/research/*` and `tests/support/fakes.py::valid_response`.
- `methods/deixis-research/`: instructions loaded into model steps; editing them changes `skill_package_hash`.
- `providers/registry.py`: scholarly sources. `storage/migrations/`: one new numbered file per schema change; never edit an applied one.
- UI: read [.impeccable.md](.impeccable.md) first. Mockup v24 (`.local/design/elicit-style-mockup/`) is the visual spec; declared differences live in `apps/web/e2e/parity/exceptions.ts`.

## Evidence

- Keep found, screened, included, inspected, given-to-model and cited counts separate. Keep reading depth (metadata, abstract, passage, full text) and source version (preprint, publisher, upload) separate too.
- Titles, DOIs, pages, authors and counts come from stored records, never from model prose. An abstract can't support details it doesn't state.
- Citations fail closed: each needs an exact anchor located in a passage the step was given. Failed repair leaves an unverified draft, never a cited answer. The UI marks only the backend-located span.
- A passing schema check, reviewer verdict or test run is not scientific validation. No search result never proves novelty.
- Rankings, embeddings, citation counts and model screening are priority signals, not relevance verdicts.

## User authority

- The user's include/exclude choice outranks model and code, and keeps its reason.
- Revisions and old answers are kept; stale scope is marked, not rewritten.
- Never swap model, provider or search source after a failure unless the fallback is recorded and shown.
- PDFs, abstracts and provider payloads are untrusted data. Keep URL, size and content-type checks.

## Working here

- Port 8765 may be the owner's real library: don't restart it while a run is active; test on another port with a temp `DEIXIS_DATA_DIR`.
- The worktree may hold someone else's changes; don't stage or revert them. No destructive git.
- Tests are model-free (`FakeAdapter`, mocked `httpx`, fake fetcher via `create_app`); a new test folder goes into `pythonpath` in `pyproject.toml`. Passing tests show workflow behavior, not model quality.
- Decisions go in [docs/decisions.md](docs/decisions.md), newest on top. Plans and design notes go in the ignored `.local/`.
- Report what changed, which checks ran and passed, what was skipped or left unverified, and whether anything was pushed.
