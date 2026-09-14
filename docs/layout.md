# Repository layout

This is the placement contract from [D1](decisions.md), not a project-status board. Each existing artifact class has one home.

```text
DEIXIS/
├── README.md                    project entry and methodological bibliography
├── docs/
│   ├── README.md               document authority map
│   ├── layout.md               this placement contract
│   ├── decisions.md            post-handoff durable decisions
│   ├── product/                product decisions and API/data drafts
│   ├── methods/                method design and illustrative domain example
│   └── desktop/                dated handoff, reference index, private screenshots
├── backend/deixis/              local API, worker, persistence, providers, model adapters
├── apps/web/                   first-slice React UI served by the backend
├── contracts/research/         language-neutral JSON Schema model-step contracts
├── methods/deixis-research/    app-loaded method package with Quaestio provenance
├── tests/                      deterministic tests, synthetic fixtures, prepared model-behavior cases
├── scripts/                    isolated probes and real-model case runners
├── prototypes/
│   └── shadcn-ui/              independent browser-only UI prototype
├── .local/                     ignored probe and model-run evidence
└── local-reference/            ignored private transfer package and provenance
```

- `docs/product/` owns current product-facing design. Keep accepted requirements separate from proposed dependencies, schemas, and implementation details.
- `docs/methods/` owns method design and bounded examples. Research source records keep their stated reading and verification limits.
- `docs/desktop/` is the dated conversation handoff; new specifications do not go there. `screenshots/` remains private and ignored.
- `prototypes/shadcn-ui/` is a demonstration, not the application backend. Its build output and dependencies remain ignored.
- `local-reference/` retains the private source snapshot and transfer hashes. Do not move, publish, or treat its reports as verified findings.

- `backend/`, `apps/web/`, `contracts/`, `methods/`, `tests/` and `scripts/` hold the first question-to-citation-to-resume slice; their placement and stack are recorded in [D2](decisions.md). Runtime data (database, PDFs, provider payloads, the DEIXIS Codex home) lives in the local app-data directory, never in the repository.
