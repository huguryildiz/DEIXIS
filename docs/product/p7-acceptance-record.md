# P7 acceptance record: G1 connector contract and P7 exit

**Date:** 3 October 2026. **Base:** `30b070c` (main after D194), detached worktree `DEIXIS-g1-b5`. **Written by** Claude Opus 5.5 as P7 G1 batch B5 (D196). **Reviewed by** gpt-6.1-sol high (read-only); rounds and verdicts are in D196. The dispositions in section 6 and the two verdicts in section 1 were decided jointly by Claude Opus 5.5 and gpt-6.1-sol medium under the owner's standing order of 3 October 2026.

**What this record shows and does not show.** It shows that the internal scholarly connector contract exists, that every registered connector and endpoint passes the mocked, registry-driven suites on one machine, and which behavior changes were made on the way. The G1 connector suites use SYNTHETIC provider fixtures and mocked or deny-network transports; the full backend run is separate regression evidence. Neither shows provider availability, current provider documentation, live error or quota formats, recall, retrieval quality or scientific correctness. B5 changes no code; it records evidence, updates the product documents and names the work still owed.

Design: [p7-connector-contract-design.md](p7-connector-contract-design.md) (D174), B5 row of section 10 and section 13. Procedure for a new source: [connector-onboarding.md](connector-onboarding.md). Earlier P7 matrix: [p7-coverage-verification.md](p7-coverage-verification.md).

## 1. Verdicts

**G1: accepted with conditions.** Wording agreed with gpt-6.1-sol medium:

> G1 is accepted for the internal, versioned search connector interface and its mocked conformance scope. Lookup and citation-chaining capabilities remain unbound; facade lookup returns unsupported without sending requests. Acceptance requires B5 to correct the product scope documents, record measured coverage and named exceptions, and assign owners and pre-P10 completion gates to F1 and F2. This acceptance does not establish strict actual-subrequest budget enforcement or wider P7 completion.

B5 meets those conditions as follows: the product documents are corrected (section 9), coverage and exceptions are recorded (sections 3 to 5), and F1 and F2 are named with an owner and a gate (section 7).

**P7 exit: not met.** Wording agreed with gpt-6.1-sol medium:

> P7 exit is not met at B5. G1's internal search/conformance scope is accepted conditionally, while F1–F3 remain mandatory closure work before P10. Deterministic matrices will provide the acceptance evidence; live error/quota formats remain explicitly unmeasured limits, and G12 remains unreproduced.

The third sentence of that wording is a new joint disposition, not a reading of earlier text: P7 will close on deterministic matrices, and live error and quota formats are carried as recorded, unmeasured limits rather than as a closing gate (section 8).

## 2. Section 13 conditions

| # | Condition (design section 13) | Evidence on `30b070c` | Status |
|---|---|---|---|
| 1 | Versioned internal interface, explicit registration path, onboarding procedure; owner accepts the internal interpretation; README and API/data design say sources are reviewed adapters and packaged builds cannot add them | `deixis.scholarly_connector.v1` in `backend/deixis/providers/contract.py` (D177); registration in `providers/registry.py`; five gates and version rules in [connector-onboarding.md](connector-onboarding.md); Q1 internal reading accepted in D174; both documents updated in this batch (section 9) | Met |
| 2 | Every registered connector, endpoint and declared capability passes the registry-driven mocked suite, including unsupported/no-request cases; exact commands, counts, failures and skips recorded | Ten connectors, eleven provider/endpoint pairs, one declared capability (`search`); lookup returns `unsupported` with zero requests for all ten; 2,686 connector-suite tests pass with no skip or `xfail` (section 3) | Met for search; lookup declared unsupported |
| 3 | Existing connectors keep the integrated G8 request/output behavior, source, stored query semantics, identity, payload provenance and user choices, every intentional exception named | Byte-identical freezes (section 3.4); direct/facade and dispatcher equivalence (D179, D194); named changes listed in section 5 | Met, with the named exceptions |
| 4 | Error/limit evidence reaches storage without credentials; quota and temporary limits distinct; missing keys send nothing and spend nothing, including removal after freeze; B2 and B4 regressions pass; logical operations and subrequests distinct; remaining enforcement debt has the Q4 disposition | B2 regressions (D178), B4 limit kinds, S2 binding and sanitization (D194) pass in the measured run; Q4: PubMed transport accounting stays unenforced and is now owned by F2 (section 7) | Met under Q4 |
| 5 | Unsupported operations, observed live access, unmeasured live behavior and carried-forward P7 work listed; G1 does not satisfy model, embedding, entitlement or live rows | Sections 6, 8 and 10 | Met |

## 3. Measured coverage

All commands ran outside any sandbox from the worktree root, with the main checkout's native arm64 virtual environment (Python 3.12.13) linked as `.venv` and `apps/web/node_modules` installed by `npm ci`.

### 3.1 Full backend suite

`PYTHONPATH=backend:. .venv/bin/python -m pytest -q -rs -p no:cacheprovider`: **12,377 passed, 0 failed, 2 skipped, 62 warnings in 425.79 s**. The two skips are the opt-in F09 production-threshold tests (`tests/test_documents.py:232`, `tests/test_arxiv_source_archive.py:575`; they need `DEIXIS_P9_PRODUCTION_THRESHOLD=1`). The warnings are dependency deprecations (SWIG types in PyMuPDF, a Starlette alias) plus two `UserWarning`s from `tests/test_cli_options.py` about the ignored `DEIXIS_SEARCH_WORKFLOW` variable. Log: `/tmp/g1b5-full.log`. No web file changed in B5, so build, lint and Playwright were not run.

### 3.2 Connector suites

`PYTHONPATH=backend:. .venv/bin/python -m pytest -q -rs -p no:cacheprovider tests/test_connector_boundary.py tests/test_connector_contract.py tests/test_connector_facade.py tests/test_query_delegation.py tests/test_connector_dispatch.py --junitxml=/tmp/g1b5-conformance.xml`: **2,686 passed, 0 failed, 0 skipped, 60 warnings in 20.52 s** (the same dependency deprecations). None of the five files contains an `xfail` or `skip` mark.

| Suite | Batch | Tests |
|---|---|---:|
| `test_connector_boundary.py` | B1 (D177) | 296 |
| `test_connector_contract.py` | B2 (D178) | 641 |
| `test_connector_facade.py` | B3a (D179) | 925 |
| `test_query_delegation.py` | B3b (D193) | 339 |
| `test_connector_dispatch.py` | B4 (D194) | 485 |
| Total | | 2,686 |

### 3.3 By connector and endpoint

Each test was assigned to a provider/endpoint pair from its parametrize ID (the first registered provider name in the ID; S2 tests whose ID names `bulk` go to the bulk endpoint). Tests whose ID names no provider (registry, static-scan, synthetic-connector, workflow and migration tests) are counted as provider-free. The assignment is mechanical and counts tests, not distinct behaviors; a test that exercises several providers in one case is counted once.

| Provider / endpoint | Boundary | Contract | Facade | Query | Dispatch | Total |
|---|---:|---:|---:|---:|---:|---:|
| OpenAlex / default | 29 | 69 | 110 | 30 | 41 | 279 |
| Semantic Scholar / default | 27 | 61 | 80 | 21 | 26 | 215 |
| Semantic Scholar / bulk | 17 | 68 | 93 | 9 | 23 | 210 |
| Crossref / default | 23 | 45 | 72 | 30 | 39 | 209 |
| arXiv / default | 22 | 32 | 59 | 30 | 39 | 182 |
| bioRxiv / default | 22 | 69 | 96 | 30 | 41 | 258 |
| PubMed / default | 26 | 92 | 119 | 30 | 36 | 303 |
| IEEE Xplore / default | 25 | 47 | 74 | 30 | 42 | 218 |
| Scopus / default | 23 | 47 | 74 | 30 | 43 | 217 |
| CORE / default | 23 | 45 | 72 | 30 | 42 | 212 |
| SerpApi / default | 22 | 46 | 73 | 30 | 42 | 213 |
| Provider-free | 37 | 20 | 3 | 39 | 71 | 170 |
| Total | 296 | 641 | 925 | 339 | 485 | 2,686 |

The 566 SYNTHETIC conformance fixture cases in `test_connector_contract.py` split by the design's case groups (section 8.1) as follows. Group 1 (registration) and group 2 (access) run as separate tests: `test_registration_schema_and_purity`, `test_exact_coverage`, `test_missing_fixture_is_named`, `test_complete_synthetic_connector_needs_no_suite_branch` and the 44 `test_required_access_sends_nothing` cases.

| Provider / endpoint | Records and identity | Paging | Error, retry, payload | Fixture cases |
|---|---:|---:|---:|---:|
| OpenAlex / default | 8 | 11 | 45 | 64 |
| Semantic Scholar / default | 6 | 5 | 45 | 56 |
| Semantic Scholar / bulk | 6 | 12 | 45 | 63 |
| Crossref / default | 6 | 5 | 29 | 40 |
| arXiv / default | 4 | 5 | 18 | 27 |
| bioRxiv / default | 8 | 11 | 45 | 64 |
| PubMed / default | 4 | 5 | 78 | 87 |
| IEEE Xplore / default | 6 | 5 | 31 | 42 |
| Scopus / default | 8 | 5 | 29 | 42 |
| CORE / default | 6 | 5 | 29 | 40 |
| SerpApi / default | 6 | 6 | 29 | 41 |
| Total | 68 | 75 | 423 | 566 |

### 3.4 By capability

The contract vocabulary has four capabilities (`contract.CAPABILITIES`: `search`, `doi_lookup`, `id_lookup`, `citing_works`). Every one of the ten descriptors declares only `search`.

| Capability | Declared by | Evidence |
|---|---|---|
| `search` | all ten connectors, eleven endpoint pairs | every row of section 3.3; positive and failure cases through each provider's real parser |
| lookup (`CompatibilityConnector.lookup`) | none; returns `unsupported` | `test_lookup_unsupported_without_search_outcome`: 20 cases (ten connectors, two requests each), zero requests and no `SearchOutcome`; `test_lookup_validation_before_send`: 4 cases |
| `doi_lookup`, `id_lookup`, `citing_works` | none | the workflow's existing lookups and chaining call provider helpers directly (`registry.UNBOUND_HELPERS`); two keyed-lookup payload tests in `test_connector_dispatch.py` check that those direct writers store no key |

Frozen fixtures, unchanged since D179/D193 and checked here: `tests/fixtures/connectors/baseline.json` 408,249 bytes, SHA-256 `e9aa47950ea55a770b9d8dff1eebc89e39760d8e777361760d3e9f0d3a04b4b0`; `tests/fixtures/connectors/query_baseline.json` 3,227,353 bytes, SHA-256 `ecc658ad6b5964e513f90144de0220a552e170ba11afe1f85d989fe22ac5e586`. All ten connectors are at adapter revision 2.

## 4. Batches accounted for

| Batch | Decision | What it did | Reviewer full pytest (outside sandbox) |
|---|---|---|---|
| Model and key gaps G2–G5, G9 | D172 | Claude model check, DeepSeek 402 as quota, no send without a required key in four provider modules | 8,525 passed, 0 failed |
| Gap batch G6–G8, G11, G12 | D173 | Quota versus temporary limit, run-wide quota guard, exact Gemini identity, typed local embedding errors | 8,674 passed, 0 failed (round 2) |
| G10 live check | D173, D174 | One live search each to IEEE Xplore, Scopus, CORE, SerpApi (section 8) | not a test run |
| Design | D174 | Internal interface, six batches, Q1–Q5 defaults | design only |
| B1 | D177 | Contract, facade, descriptors, 111-case freeze; no dispatch change | 9,231 passed, 0 failed |
| B2 | D178 | Registry-driven conformance suite; five named fixes | 9,992 passed, 0 failed |
| B3a | D179 | Facade checks option types, values and retry allowance before send | 11,180 passed, 0 failed |
| B3b | D193 | Query rendering and rules from registry declarations; byte-equal compiler output | 11,686 passed, 0 failed |
| B4 | D194 | Search dispatch through the facade; four named changes; continuation refusal; migration 0067 | 12,235 passed, 0 failed |
| B5 | D196 | This record; 12,377 passed, 0 failed on `30b070c` | section 3.1 |

## 5. Compatibility and exception ledger

The refactor itself (B1, B3a's equivalence, B3b's rendering, B4's dispatch) is claimed equivalent on the frozen and matrix cases. These intentional behavior changes were made beside it and are named in their decisions:

| Decision | Named change |
|---|---|
| D172 | IEEE Xplore, Scopus, CORE and SerpApi `search()` returns `not_configured`/`before_send` with no request when the key is missing |
| D173 | Explicit quota exhaustion stops retries and suppresses later sends to that provider within one execution; `error_kind` separates quota from temporary limits |
| D178 1 | A key removed after the protocol freezes sends nothing, counts nothing and records a failed step without a `search_runs` row |
| D178 2 | PubMed EFetch keeps `error_kind` |
| D178 3 | Malformed HTTP 200 roots, containers and items return `parse_error` instead of raising |
| D178 4 | Empty or non-string continuation tokens become None (OpenAlex, bioRxiv, S2 bulk) |
| D178 5 | Rate-limit header values are redacted with the supplied key; negative or non-finite Retry-After is unusable |
| D179 | The facade refuses wrong option types, undeclared option values and invalid retry allowances before send |
| D193 | Undeclared endpoints and unregistered providers are refused before rendering (97 recorded inputs) |
| D194 1 | Search, chain and kill-search errors keep `error_kind`; quota pauses as `provider_quota_exhausted` |
| D194 2 | S2 batch answers bind by DOI/ArXiv identifier, not position |
| D194 3 | Stored payloads and record `raw` are sanitized of the operation's own key before writing and hashing |
| D194 4 | Records without a usable provider identity are dropped and counted |
| D194 | A pending page refuses to continue when its recorded adapter revision changed or its provenance is unreadable |

Two bounded version-rule amendments replace revision bumps and are recorded in [connector-onboarding.md](connector-onboarding.md): B3a's pre-send input refusals (D179) and B3b's undeclared-input refusals (D193). Neither changes what an accepted request sends or returns.

## 6. Open items and their dispositions

Decided jointly by Claude Opus 5.5 and gpt-6.1-sol medium. "Limit" means the item is recorded and blocks neither G1 nor P7. "Blocks P7" items are owned by a named follow-up batch in section 7; none of them blocks G1's search-scoped acceptance.

| # | Item | Facts | Disposition |
|---|---|---|---|
| 1 | `RetryPolicy` describes but does not drive retries (ledger g) | `contract.py:52-53`; D179's agreement tests pin the descriptor to module behavior for every pair | Limit |
| 2 | Local `ValueError` conversions unscheduled (ledger d) | An unknown stored paged endpoint raises `KeyError` before usage; S2 kill-search reserves, then raises `ContractViolation`. Removing a registered endpoint is one way to reach this; the code does not show it is the only way | Limit |
| 3 | Lookup capability binding moved out of B4; D174 Q3 default not met | Every descriptor declares only `search`; existing Crossref, S2 batch and Scopus lookups use direct helpers (`registry.UNBOUND_HELPERS`). A new adapter can add search through the contract, not lookup | Blocks P7; G1-F1 |
| 4 | Numeric-text record IDs admitted | `"17"` from OpenAlex, bioRxiv or S2 is admitted because the adapter's string cannot show its JSON type; valid numeric identities such as CORE's must stay admitted | Limit |
| 5 | Kill-search writes no `connector_json` | Kill-search writes to the candidate store, not `search_runs`. Kill-search runs can resume pending work, but that path has no paged continuation needing the B4 revision check | Limit |
| 6 | Chaining calls OpenAlex directly | `workflow/flow.py:1704-1709` (`citing_works`, `works_by_ids`); count and distribution probes at `flow.py:581` and `:1093` also call OpenAlex directly | Chaining: blocks P7, G1-F1. Count/distribution probes: limit |
| 7 | PubMed request accounting (Q4, ledger e) | Discovery counts one base request plus retries per search (`flow.py:2058`, `:2068`), while PubMed can send ESearch and then EFetch; kill-search reserves `requests_per_search=2` times (1 + retries) (`flow.py:4749`) | Blocks P7; P7-F2. Owning it satisfies Q4 for G1 |
| 8 | OpenAI embedding path | `documents/embeddings.py:218,289`: shares `embed_openai_compatible` with Ollama and LM Studio, whose refusal, 429, 413 and success cases D173 tests. The credential probe has Bearer and 401 tests, and missing-key cases exist (`tests/test_settings_connections.py:225`, `tests/test_semantic_retrieval.py:151`); the authenticated `Embedder("openai", ...)` run has no separate test | Blocks P7; P7-F3 |
| 9 | Other recorded limits | Ledger k (empty or null result containers, not checked against provider documentation); `scopus_count_unmapped`; only the operation's own key is redacted; live error and quota formats unmeasured; G12 not reproduced | Limit |

## 7. Named follow-up batches

These are not implemented in B5. Each must land before P7 closes and before P10. The coordinating Claude session owns their scheduling and closure evidence; each follows the usual writer/reviewer split.

| Batch | Scope | Closes |
|---|---|---|
| **G1-F1: lookup and chaining capability binding** | Bind the existing single and batched lookup helpers and OpenAlex chaining (`citing_works`, `works_by_ids`) through versioned capabilities, keeping identity, batching, accounting and unsupported behavior | Items 3 and 6 (chaining); D174 Q3 |
| **P7-F2: transport accounting** | Separate actual sends from reservations; count and bound every PubMed subrequest and retry, with explicit reconciliation rules for discovery and kill-search | Item 7; ledger e; Q4 |
| **P7-F3: OpenAI embedding auth and 401** | Exercise the authenticated OpenAI embedding route: URL, model and Bearer placement, success and 401, with provider-specific cases or a justified shared-path argument | Item 8 |

## 8. Unsupported operations and live evidence

Unsupported through the contract, for every connector: DOI lookup, ID lookup and citing works (declared in the vocabulary, bound by none) and full text (not in the vocabulary). The workflow's existing lookup and chaining paths still work through direct helpers; full-text retrieval stays in `documents/`. No external plugin, runtime loading or declarative mapping exists (D174 Q1, Q2).

Observed live access (G10): an owner-approved check sent one search, "graph neural network power system", limit 3, no retries, to each of IEEE Xplore, Scopus, CORE and SerpApi with the owner's keys. It called the provider modules' `search()` directly, on code before B1, not through the facade. The result file `/tmp/g10-live/result.json` (1,308 bytes, SHA-256 `629ab415f3f9cea39a9670dfe73f41136c537634bb0dfb55e94b69282bdf1303`) was still present and was read for this record; it shows all four `completed`, HTTP 200, three records each, 1.04 to 1.61 s, totals 7,124 / 180,295 / 25,137,458 / 2,590,000, Scopus `x-ratelimit-limit` 20000 and CORE 150. The coordinator recorded the check at 02:48; the file's modification time is 02:42 local time. B5 repeated no live call.

Not measured: live error and quota formats for any connector; current provider documentation; entitlement beyond those four successful searches; OpenAlex, S2, Crossref, arXiv, bioRxiv and PubMed live behavior in this batch; recall and retrieval quality.

## 9. Product documents updated in B5

- [README.md](README.md) line 13: sources beyond the ten are added as reviewed adapters in the codebase through the internal, versioned contract; packaged builds cannot add sources; the contract covers search only for now.
- [api-and-data.md](api-and-data.md) lines 52-57 before the edit, now 52-62: the same statement, with the contract ID, the onboarding procedure, the absence of plugins and declarative mappings, and the unbound lookup and chaining capabilities.
- [connector-onboarding.md](connector-onboarding.md): G1 acceptance status; ledger e names P7-F2 as its owner. The `b4_resume_lookup` row names G1-F1 in its evidence column but keeps the owner cell "Lookup capability binding; unscheduled (D194)", because `tests/test_connector_contract.py:433` pins that exact string and B5 changes no test. G1-F1 should update both together.
- [p7-coverage-verification.md](p7-coverage-verification.md): G1 row and closing note.

## 10. P7 exit

Exit condition (implementation plan, P7 row): "Her etkin bağlantı auth/model/kota/hata matrisiyle ayrı doğrulanmış; ürün kapsamındaki uygulanmamış bağlantılar açık listeli".

| Area | Deterministic evidence | Open |
|---|---|---|
| Model connections (Codex, Claude, Gemini, DeepSeek) | D172 (G2–G5), D173 (G6, G7) | Live error and quota formats unmeasured |
| Embeddings (built-in, Gemini, Ollama, LM Studio, OpenAI) | Coverage note section 2; D173 (G11) | OpenAI authenticated run: P7-F3 |
| Scholarly connectors (ten) | Sections 3 to 5; D172 (G9), D173 (G8) | Lookup and chaining binding: G1-F1; PubMed accounting: P7-F2; live error and quota formats unmeasured |
| Live access | G10: four keyed connectors, one search each | Live formats unmeasured |
| Unimplemented connections listed | Coverage note section 4: nine model connections shown as not implemented, no research adapter for OpenAI or LM Studio; Google Scholar is reached through SerpApi rather than a separate connector; Zotero is an implemented import path, not a search connector | none |
| G12 | Not reproduced: 50 of 50 serial runs and 20 of 20 parallel runs of its file passed (D173) | Remains unreproduced |

Verdict: **not met** (section 1). P7 can close when G1-F1, P7-F2 and P7-F3 pass their gates, on deterministic evidence, with the live rows above carried as limits.

## Limits

Synthetic fixtures and mocked transports establish application behavior on the enumerated cases only. The per-pair assignment in section 3.3 is mechanical. The full pytest is one run on one machine. B5 made no live provider or model call, network request, service start or code change; port 8765 and the live data directory were not touched.
