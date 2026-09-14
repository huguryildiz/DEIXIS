# First research slice — design and test plan

The [comprehensive implementation plan](implementation-plan.md) now defines the staged skill, architecture and acceptance work. This document remains a narrow example: its OR question is not a mandatory product domain. P1 runs deterministic contract checks and prepares model-behavior cases; P2 runs those cases with the actual adapter; P4 verifies the browser workflow. Historical gate wording below does not add a new approval round or claim that these tests have run.

**Status:** proposed, not implemented. **Test question:** “Moleküler haberleşmede yöneylem araştırması nasıl kullanılıyor; yayımlanmış modellerin karar değişkenleri, amaçları, kısıtları ve doğrulama düzeyleri neler?” Include preprints, explicitly labelled. This is a bounded source-grounded question-answering test, not a systematic review or a novelty assessment.

## Boundary and order

1. **Approve the behavior contract.** A question starts a research session; the backend records the query, search scope, depth and budget. It shows candidate publications and a reason for inclusion or exclusion. The user can alter the selection before answer generation. The answer defaults to the question's language, here Turkish.
2. **Write the minimal research instruction.** Adapt the existing, separate [Quaestio skill](../../../quaestio/SKILL.md) only for this question-to-answer task: search terms, selection rationale, reading-depth labels, source-versus-inference distinction, and claim-to-passage citation rules. Do not copy its full question-discovery or kill-search workflow into every ordinary answer. Whether this instruction is packaged as a DEIXIS `SKILL.md` or loaded as a method file is an implementation choice; the instruction and its examples must be testable either way.
3. **Run an offline contract test.** Use small, explicitly synthetic records to exercise selection, source versions, abstract-only access, a cited passage, a non-OR false positive, and interrupted/resumed state. This checks schema and workflow behavior, not scientific accuracy.
4. **Build one live vertical slice.** Connect one selected academic search API and one supported Codex connection through the local backend, then use a real, accessible source. The first successful result must survive page reload and backend restart and reopen its cited source location. Claude is the next adapter; DeepSeek requires a rotated key. All seven scholarly providers remain in product scope, but none is silently represented as implemented.
5. **Evaluate against known papers.** The owner selects a small familiar set after the first live slice. Compare source selection, wrong citations, missed relevant evidence, correction effort and persistence. A model-generated answer is not its own ground truth.

Do not let a background literature agent's finished report stand in for steps 3–5. Such a report can later be a candidate reference set, with its own search and reading limits.

## Minimal data and ownership

| Record | Minimum provenance or state |
|---|---|
| Question/session | Stable question and session IDs, original wording, selected scope, timestamps, resumable stage |
| Search run | Provider, exact query, retrieval time, result/error/partial state and candidate IDs |
| Publication/version | Stable work-family and version IDs, DOI or other identifier, preprint/published status, access level |
| Selection | Included/excluded/pending, reason, user override and active research scope |
| Evidence passage | Source version, text or faithful short excerpt, actual locator (page/section/abstract), reading depth, extraction status |
| Answer claim/citation | Claim ID, passage IDs, support versus inference/uncertainty, requested and reported model ID |

The backend owns retrieval, identity/version matching, extraction, citation linkage, budget enforcement and durable storage. The method instruction governs interpretation; the model cannot invent absent locators or silently promote metadata to full-text evidence. The UI displays the recorded states, outgoing content for cloud-model calls, and source selection and citation inspection. This division follows the [draft data contract](api-and-data.md) but does not freeze its database schema or choose a framework.

## Acceptance cases prepared before implementation

These cases are synthetic test designs, not retrieved papers or executed tests.

| Case | Required observable behavior | Failure if |
|---|---|---|
| A. Selected source with accessible passage | Answer claim links to that source/version and opens the stored passage | Citation points only to a paper title or a different version |
| B. Abstract only | Claim is labelled abstract-based; no PDF page or full-text method detail is asserted | A page, equation or model constraint is invented |
| C. Preprint and published version | One work family, separate versions; evidence remains attached to the inspected version | Versions count as independent papers or old evidence silently moves to the new version |
| D. “Optimization” false positive | Candidate can be excluded with a reason if no actual OR formulation is evidenced | A keyword match becomes a claimed LP/MIP/MILP model |
| E. Model or provider failure | Completed work is saved; session pauses with a visible error and no silent fallback | A failed search is shown as zero results or another model is substituted |
| F. Reload/restart | Question, selection, answer and passage link reopen from durable state | Browser-local demo history is mistaken for persisted research state |
| G. Untrusted source text | Abstract/PDF content is treated as data, not instructions to change scope or reveal credentials | Retrieved text controls tools or overwrites the user's choices |

## Design walkthrough and gate

**Tabletop check, 14 September 2026:** Cases A–G each have a named owner, state and expected visible outcome above. This shows that the proposed contract can express the main success and failure branches. It does **not** demonstrate that any branch runs. In particular, the existing UI prototype has no academic retrieval, real model invocation, passage extraction or backend-owned persistence; it cannot pass A–G as an application test.

**Gate to writing the method instruction:** confirm that the first output is a source-grounded map of existing OR formulations, not a new optimization model or an originality verdict. **Gate to live integration:** implement and execute A–G on synthetic fixtures, then verify at least one real source's identity, version and passage. **Gate to calling the slice usable:** a real question completes through selected sources, linked answer and restart/resume, with access limits and failures visible. No gate is passed by a mock screen or a second model's opinion.
