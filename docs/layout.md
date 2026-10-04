# Repository layout

This is the placement contract from [D1](decisions.md), not a project-status board. Each existing artifact class has one home.

```text
DEIXIS/
├── README.md                    project entry and methodological bibliography
├── STATUS.md                    the one project-status page (Turkish), mirrored to Notion
├── docs/
│   ├── README.md               document authority map
│   ├── layout.md               this placement contract
│   ├── decisions.md            post-handoff durable decisions
│   ├── product/                product decisions and API/data drafts
│   ├── methods/                method design and illustrative domain example
│   ├── archive/                closed work: p5/–p9/, sw/, search-2026-09/; experiments.md (retired runners)
│   └── desktop/                dated handoff, reference index, private screenshots
├── backend/deixis/              local API, worker, persistence, providers, model adapters
├── apps/web/                   first-slice React UI served by the backend
├── contracts/research/         language-neutral JSON Schema model-step contracts
├── methods/deixis-research/    app-loaded method package with Quaestio provenance;
│                               references/phrases.md holds the phrase frames
├── tests/                      deterministic tests, synthetic fixtures, prepared model-behavior cases,
│                               acceptance/ fixture server for the browser run in apps/web/e2e
├── scripts/                    referenced probes, evaluation kits and real-model case runners
├── .local/                     ignored probe and model-run evidence; closed runs under archive/sw and archive/early
└── local-reference/            ignored private transfer package and provenance
```

- `docs/product/` owns current product-facing design, acceptance records, measurement freezes and results still cited as current. Documents and JSON inputs read by tests or scripts stay here, including the expectation sheets for P8 and the P6 Chain of Ideas design cited by the frozen L9 input. Keep accepted requirements separate from proposals and implementation evidence.
- `docs/archive/` holds closed-batch prompts, expectations, handoffs, superseded results and completed slice plans under their phase (`p5/` through `p9/`). Each phase's `README.md` summarizes recorded measurements, outcomes and decision links; nothing new is specified there. Existing `sw/` and `search-2026-09/` archives retain their homes. Historical records remain evidence of their dated scope, not current implementation instructions.
- Recorded freeze hashes identify the original committed bytes. Path updates during archiving do not rerun a measurement or establish a new freeze; reproduce the original run from its recorded commit.
- [Retired experiments](archive/experiments.md) records removed runners and fixtures, reported outcomes, decision associations and Git recovery. `scripts/` retains test/doc dependencies and their helper scripts, including `p9/`, `p9_owed/`, `model_behavior/` and `p4_eval/`; historical archive script paths may no longer exist.
- [Local run archive](archive/local-runs.md) describes the ignored evidence tree, surviving result summaries and raw-data losses. `.local/INDEX.md` is a local navigation index; the planned `.local/archive/p9-evidence.tar.gz` was absent at the 4 October 2026 inspection. Runtime data stays in the application-data directory.
- `docs/methods/` owns method design and bounded examples. Research source records keep their stated reading and verification limits.
- `docs/desktop/` is the dated conversation handoff; new specifications do not go there. `screenshots/` remains private and ignored.
- `local-reference/` retains the private source snapshot and transfer hashes. Do not move, publish, or treat its reports as verified findings.

- `backend/`, `apps/web/`, `contracts/`, `methods/`, `tests/` and `scripts/` hold the first question-to-citation-to-resume slice; their placement and stack are recorded in [D2](decisions.md). Runtime data (database, PDFs, provider payloads, the DEIXIS Codex home) lives in the local app-data directory, never in the repository.
