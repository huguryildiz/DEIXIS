# CLAUDE.md

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage reading → an answer whose every citation points to a located passage. FastAPI backend (`backend/deixis`) serves a React/Vite UI (`apps/web`) on loopback.

Rules (evidence semantics, safety, UI, verification, completion report) are in [AGENTS.md](AGENTS.md). Read it before changing code, and [.impeccable.md](.impeccable.md) before touching `apps/web`.

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

- `workflow/`: runs and steps. Discovery is the fast path (`fast_path.py`, then `fast_search.py`, `fast_chain.py`, `fast_read.py`); answers in `fast_answer.py`. Every step is a row keyed by `operation_key`, so a succeeded step is never re-run.
- `models/` + `flow._model_step`: model calls get a stored `StepInput` and a strict schema; no tools, no silent model fallback, bounded repair.
- `contracts/research/*.schema.json` + `domain/contracts.py`: step I/O and semantic checks. A schema change also updates `tests/fixtures/research/*` and `tests/fakes.py::valid_response`.
- `methods/deixis-research/`: instructions loaded into model steps; editing them changes `skill_package_hash`.
- `providers/registry.py`: scholarly sources. `storage/migrations/`: new numbered file per schema change; never edit an applied one.

## Tests and decisions

Tests are model-free (`tests/fakes.py::FakeAdapter`, mocked `httpx`, fake PDF fetcher via `create_app`); a new test folder must be added to `pythonpath` in `pyproject.toml`. Passing tests show workflow behavior, not model quality.

Decisions go in [docs/decisions.md](docs/decisions.md), newest on top. Plans and design notes go in the ignored `.local/`, not `docs/`.
