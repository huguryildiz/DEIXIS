# Repository layout

```text
DEIXIS/
├── README.md              project entry
├── STATUS.md              the one project-status page (Turkish), mirrored to Notion
├── docs/
│   ├── layout.md          this file
│   ├── decisions.md       durable decisions (DNN; restarted at D1, 10 Oct 2026)
│   └── search-architecture.md  Mermaid map of the search pipeline (fast_path_v1)
├── backend/deixis/        local API, worker, persistence, providers, model adapters
├── apps/web/              React UI served by the backend
├── contracts/research/    JSON Schema model-step contracts
├── methods/deixis-research/  app-loaded method package
├── tests/                 deterministic tests and fixtures
├── scripts/               probes, evaluation kits, real-model case runners
└── .local/                ignored: INDEX.md, LESSONS.md, plans/, 2026-10-10-baseline/
```

- Files that code reads sit next to their reader: the connector ledger in `tests/providers/`, the frozen P8 expectation sheets (hashed by the runners) in `tests/model_behavior/`, and `providers.env.example` at the root.
- `.local/` is outside git. `INDEX.md` says what is where (measurement and pilot folders are named `YYYY-MM-DD-topic`), `LESSONS.md` holds one-sentence lessons from past work, `plans/` holds the waiting P10 packaging plan and other open plans, and `2026-10-10-baseline/` holds the frozen 10 Oct measurement numbers, the scoring rule and the live-run tools for search work after P10. New design records and plans for current work go there, not in `docs/`. Older design documents and archives remain in Git history.
- Links in `decisions.md` and `STATUS.md` that point into `.local/` resolve only on the owner's machine.
- The decision entries before the clean start (old D1 to D261) are in Git history; `docs/decisions.md` at commit `26c8214` is the last full copy.
- Runtime data (database, PDFs, provider payloads, Codex home) lives in the app-data directory, never in the repository.
- Every non-Python file the app reads at run time is listed in `backend/deixis/package_manifest.py`; a packaged build copies exactly those (P10d uses it as PyInstaller `datas`). A new data file read from disk goes on that list.
