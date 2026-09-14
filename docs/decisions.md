# DEIXIS decisions

Accepted product decisions from the 14 September 2026 conversation are recorded in the [dated handoff](desktop/README.md). This file records subsequent durable decisions; an entry does not turn an unimplemented proposal into a working feature. New entries go above older ones. Status values are `accepted`, `superseded`, `rejected`, and `deferred`.

## D6 — Close P4 technical gaps: backup, resource bounds, versions and revision labels

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The P4 exit condition requires a restore test; the plan bounds PDF work and private-network fetches in P2–P4 (T07/G, §7.1); case C requires one work with separate versions; T18 requires older-revision results to carry their revision; §8 requires Cmd/Ctrl+K on real data. D5 left the version model, memory limits and DNS rebinding open.

**Decision**: `deixis backup` writes an SQLite backup-API snapshot plus every referenced PDF and provider payload with a SHA-256 manifest, never the Codex home; `deixis restore` verifies all hashes and restores only into a data directory without a library. PDF extraction caps total text (3 M characters) and stops the child when its peak resident memory passes 1 GB (a watchdog, since macOS does not enforce `RLIMIT_AS`; no memory cap on Windows yet). Uploads are refused above the declared length before parsing and copied in chunks while hashing. PDF fetches connect to the address that passed the public-address check (Host header and TLS server name keep the host) and ignore environment proxies. An OpenAlex open-access location with a different version label becomes a separate source version of the same work (no DOI or abstract copied, not screened separately, included only by the user); counts of unique, included, given and cited sources count works. Search results show the question revision they were found for. Cmd/Ctrl+K searches research titles, questions and source titles (not passage text).

**Impact**: No migration. Records found before this change get their other version when found again; PDFs already attached under D4's earlier behavior are not re-checked. Changed provider metadata for an existing record is still not re-recorded (P5 version history). Locator assertions inside claim text remain unchecked by code (case B relies on the method rule and model behavior case MB01).

## D5 — Enforce the chosen model, result applicability and local boundaries

**Status**: accepted  
**Date**: 2026-09-14

**Context**: A read-only review of the initial commit by Codex `gpt-5.6-sol` (high reasoning effort) found that runs could apply results after pause, cancel or a question revision; that a research could start without a model and accept output from another model; that answers stayed "current" after source-selection changes; that a crash between a completed model call or search and its step record could repeat work or duplicate answers; that the package hash covered `provenance.json`; and that `.env` secrets reached the Codex process. Evidence: `.local/review-gpt-5.6-sol-high-2026-09-14.md` (local, not versioned).

**Decision**: A research requires an explicit model that the connection lists; output whose resolved model differs is recorded and the run pauses (`model_mismatch`). Runs check pause and cancel after every external call and before applying results; discovery also stops (`cancelled`, `scope_revised`) when the question is revised. Search runs and candidates carry the question revision, and screening uses only the current revision. A research-level selection revision is stored with answer StepInputs and answers, so later selection changes mark answers `stale_selection`. Model-session and search results commit in the same transaction as their step outcome, and answers and screening proposals are applied at most once per step. The package hash covers only the instruction files loaded into model steps. The Codex process receives an allowlisted environment without provider keys. The API accepts only loopback peers, and attachments only when the source scope includes them.

**Impact**: Migration 0003. Answers created before it keep question-only applicability. The version-family source model, locator assertions inside claim text, upload/extraction memory limits and DNS-rebinding protection remained open review items (see D6).

## D4 — Attach an open-access PDF only to the source version it belongs to

**Status**: accepted  
**Date**: 2026-09-14

**Context**: In the first live run, OpenAlex described a record's primary location as `publishedVersion` while its best open-access PDF was a `submittedVersion` manuscript. DEIXIS attached that manuscript to the published record, so a PDF page citation was labeled with the wrong version.

**Decision**: Store the open-access location's version (`source_versions.oa_pdf_version`, migration 0002) separately and fetch the PDF only when it equals the record's `version_label`. A PDF of another version is shown as "different version · not used" until separate version records exist. Search uses OpenAlex `search.title_and_abstract`; plain `search=` also matches full text and returned off-topic records in probing.

**Impact**: Fewer PDFs are retrieved. Records created before migration 0002 have no stored OA version, so their already-attached PDFs are not re-checked.

## D3 — Run Codex in a DEIXIS-owned Codex home with explicit models

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Probing showed that the user's `~/.codex/AGENTS.md` was loaded into app-server threads despite `project_doc_max_bytes=0`, and that the resolved default model differed between runs.

**Decision**: The Codex adapter uses `CODEX_HOME` under the DEIXIS data directory (the user signs in there once), disables tools, connectors, skills and instruction files through config overrides, starts one ephemeral read-only thread per step, rejects any thread reporting instruction sources and any output accompanied by tool items, and always sends the model chosen for the research. Evidence: `.local/codex-boundary-2026-09-14/report-deixis-home.json` (local, not versioned).

**Impact**: Codex readiness requires a separate sign-in. `skills/list` still discovers host skills, although none were injected into the probed prompts; this is recorded as a residual boundary.

## D2 — Place the first-slice application code

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Implementation of the first slice began after D1 deliberately left app directories undecided.

**Decision**: Python 3.12 backend (FastAPI, SQLite) in `backend/deixis/`; React UI in `apps/web/` (started from a copy of the prototype, which stays untouched); language-neutral JSON Schema contracts in `contracts/research/`; the app-loaded method package in `methods/deixis-research/`; tests in `tests/`; isolated probes and real-model case runners in `scripts/`. Run with `PYTHONPATH=backend uv run python -m deixis serve`; the explicit `PYTHONPATH` is needed because macOS marks files in iCloud-synced folders hidden and Python skips hidden `.pth` files.

**Impact**: `docs/layout.md` lists the new homes. Local data stays outside the repository (`~/Library/Application Support/DEIXIS` on macOS).

## D1 — Separate current design drafts from the dated handoff

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The repository arrived with a long dated continuation record, active API and research-method drafts, a UI-only prototype, and a private local evidence package. The `docs/desktop/` name reflects the transfer history rather than the selected local-web first release. Moving the entire handoff would break its supplied path and private screenshot references.

**Decision**: Keep `docs/desktop/` as the dated handoff and reference index. Place active product/API drafts in `docs/product/` and methodological design and domain examples in `docs/methods/`. Keep the UI prototype under `prototypes/shadcn-ui/` and the private transfer package under ignored `local-reference/`. Use `docs/README.md` as the authority map and `docs/layout.md` as the placement contract. Do not create empty application directories or select a frontend/backend stack by reorganizing files.

**Impact**: Update internal links and root navigation. No research behavior, model adapter, academic API connector, or UI runtime changes. The handoff remains the historical source for accepted user decisions; product drafts retain their proposal status.
