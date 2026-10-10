# Repository layout

```text
DEIXIS/
├── README.md              project entry
├── STATUS.md              the one project-status page (Turkish), mirrored to Notion
├── docs/
│   ├── layout.md          this file
│   ├── decisions.md       durable decisions (DNN; restarted at D1, 10 Oct 2026)
│   └── product/           only files that code, tests or scripts read
├── backend/deixis/        local API, worker, persistence, providers, model adapters
├── apps/web/              React UI served by the backend
├── contracts/research/    JSON Schema model-step contracts
├── methods/deixis-research/  app-loaded method package
├── tests/                 deterministic tests and fixtures
├── scripts/               probes, evaluation kits, real-model case runners
└── .local/                ignored: run evidence and docs/ (design records, plans, closed-phase archives)
```

- `docs/product/` keeps the connector ledger read by `tests/providers/test_connector_contract.py`, the P8 expectation sheets, the P9 owed-measurement freeze, results and JSON inputs read by `scripts/` and `tests/`, and `providers.env.example`. Nothing else goes there.
- Design documents, implementation plans, prompts, acceptance records and phase archives live in `.local/docs/`, outside git. Their committed versions remain in Git history up to the commit that removed them.
- Links in `decisions.md` and `STATUS.md` that point into `.local/docs/` resolve only on the owner's machine.
- The decision entries before the clean start (old D1 to D261) are in Git history; `docs/decisions.md` at commit `26c8214` is the last full copy.
- Runtime data (database, PDFs, provider payloads, Codex home) lives in the app-data directory, never in the repository.
