# External scan — how other projects and the literature design scholarly search

**Status:** reference record; it selects no strategy, changes no default, and proposes no dependency. **Date:** 2026-09-18.

This file answers a question the two companion records do not: **how do open-source projects and the peer-reviewed literature handle multi-provider scholarly query design, and where does DEIXIS stand relative to them.** The critique is in `docs/product/search-strategy-critical-review-2026-09-18.md`; the design that answers it is in `docs/product/search-query-structure-design-2026-09-18.md`. Neither is reopened here.

Nothing in this file is a decision. It is input for a future decision, and every claim below carries its own verification status.

## 0. Method and evidence tiers

Scan performed **2026-09-18**. Sources: GitHub API through the authenticated `gh` CLI for star counts, dates, contributor counts and licences; repository files fetched from `raw.githubusercontent.com` and read directly; arXiv API and Crossref REST API for identifier and date verification; a separate literature pass over Crossref, Semantic Scholar, PubMed, ACL Anthology and arXiv.

Tiers used throughout:

- **[V]** verified directly by this scan — API response, file content, or identifier resolution.
- **[R]** reported by the literature pass against primary metadata or full text, not independently re-read here.
- **[U]** unverified or contested. Do not build on it.

## 1. Star ranking, and why it does not answer the question

Star counts **[V]** as of 2026-09-18:

| Repository | Stars | What it actually does |
|---|---|---|
| stanford-oval/storm | 31,424 | Wikipedia-article generation over web sources |
| assafelovic/gpt-researcher | 29,497 | General research agent; 3 generated SERP queries; retriever list includes arxiv, semantic_scholar, pubmed_central |
| Alibaba-NLP/DeepResearch | 19,959 | General web deep research |
| dzhng/deep-research | 19,693 | General web deep research |
| SakanaAI/AI-Scientist | 14,572 | Idea and paper generation |
| Future-House/paper-qa | 9,212 | Provider clients plus metadata enrichment; local search index for discovery |
| LearningCircuit/local-deep-research | 9,099 | General |
| nickscamara/open-deep-research | 6,284 | General |
| bytedance/pasa | 1,658 | Crawler and selector agents; Google Search API plus arXiv |
| AkariAsai/OpenScholar | 1,598 | Retriever over S2 and PeS2o, plus citation verification |
| ChaokunHong/MetaScreener | 1,333 | Screening, not discovery |
| asreview/asreview | 1,008 | Active-learning screening |
| **jonatasgrosman/findpapers** | **402** | **Multi-provider query compilation and execution planning** |
| O0000-code/paper-search-pro | 166 | Academic discovery as a Claude/Codex `SKILL.md` |
| elizagrames/litsearchr | 126 | Search-term selection from a seed set (R, last push 2021-04-07) |
| princeton-nlp/LitSearch | 109 | Retrieval benchmark, not a system |
| ielab/searchrefiner | 17 | Boolean query visualisation and measurement over a labelled set |

The five highest-starred repositories are general-purpose agent shells. **Star count measures agent-framework adoption, not scholarly query-design quality.** In the query-design class the distribution falls three to four orders of magnitude, and the entry that does the relevant work best has 402 stars.

## 2. Which repository does this work most cleanly

The question has different answers per job, and collapsing them is what produces a misleading ranking.

### 2.1 Query compilation and execution planning → findpapers

The only clear match. **[V]** from repository files:

- `findpapers/query/builder.py` exposes `QueryBuilder`, `QueryValidationResult`, and **`QueryExecutionPlan(request_payloads, combination_expression)`** — one logical query, split into a list of provider-specific request payloads, recombined with set semantics such as `q0 AND q1`. Splitting one intent across several requests is architectural here, not an afterthought.
- `findpapers/query/builders/{arxiv,ieee,openalex,pubmed,scopus,semantic_scholar,wos}.py` — one builder per provider, each with `validate_query` and `convert_query`.
- `findpapers/query/{parser,normalizer,validator,propagator}.py` — nested field-filter propagation across the query tree.
- `docs/query-syntax.md` and `docs/databases.md` — the square-bracket Boolean language, per-provider field-code support tables, per-provider rate limits, and an explicit limitations section per database.

Practical limits **[V]**: MIT licence, Python 3.11+, **2 contributors**, latest PyPI release v0.6.7 (2022-11-09), README warns the main branch is in flux, last push 2026-08-18. This is a **design reference, not a dependency candidate**: two contributors and a rewritten main branch is a maintenance risk that a vendored adapter would import into DEIXIS.

### 2.2 Provider clients and metadata enrichment → paper-qa

9,212 stars, and the closest thing to a mature scholarly provider layer — but it does **not** solve DEIXIS's problem. **[V]**:

- `src/paperqa/clients/openalex.py` uses `params["filter"] = f"title.search:{title}"`. The provider clients are for **resolving and enriching a known `DocDetails`**, not for discovery.
- Discovery runs through a local `SearchIndex` (`src/paperqa/agents/search.py`).
- `agent.search_count = 8` is a budget dial alongside `max_timesteps` and `timeout`; `journal_quality`, `retractions` and `unpaywall` add quality and integrity layers.

The transferable idea is the explicit agent budget surface plus the quality/retraction layer — not the search path.

### 2.3 Search-term selection methodology → litsearchr and SearchRefiner

- **litsearchr** (126 stars) — text mining and keyword co-occurrence over **seed articles** to generate search terms. Small, R-based, last push 2021-04-07. Its peer-reviewed paper is Grames et al., *Methods in Ecology and Evolution* 10(10):1645–1654, 2019, DOI `10.1111/2041-210X.13268` **[R]**; validation is author-reported and no independent replication was located **[U]**.
- **SearchRefiner** (17 stars) — Boolean query visualisation plus measurement against **validation citations** (a known-relevant set). This is the seed-document workflow that the previous design conversation proposed as a runtime check, implemented at small scale years ago **[V]** for the repository, **[R]** for Scells & Zuccon, CIKM 2018.

### 2.4 Benchmark and screening

- **princeton-nlp/LitSearch** (109 stars) — a benchmark, not a system; used later in this file.
- **asreview/asreview** (1,008 stars) — active-learning screening; screening is downstream of discovery and does not address query design.

### 2.5 The combination DEIXIS has is not represented

No scanned repository combines anchor-vocabulary planning, a recorded request budget, passage-level claim–citation traceability, and a stored evidence chain. findpapers covers query compilation; paper-qa covers provider clients and quality metadata; litsearchr and SearchRefiner cover term selection and validation; none of them cover sourcing evidence records or anchor integrity. **DEIXIS's distinctive layer is the evidence chain, not the query compiler.**

## 3. What findpapers has that this codebase does not, and vice versa

**[V]** comparison against this repository:

| findpapers has | DEIXIS status |
|---|---|
| Per-provider `validate_query` + `convert_query` contract | Equivalent knowledge exists as shape rules in `backend/deixis/providers/query_rules.py`, concentrated on OpenAlex rather than expressed as a per-provider interface |
| Explicit per-database limitations documented per provider | Present for OpenAlex only (D11); other providers' phrase and field limits are not recorded |
| Provider-dependent default field (`tiabskey` for IEEE/PubMed/Scopus/WoS, `tiabs` for arXiv/OpenAlex/S2) | Not expressed as a rule |
| Query split into multiple request payloads with set-semantics recombination | `backend/deixis/providers/query_compiler.py` compiles per provider, but there is no recombination contract |

| DEIXIS has | findpapers status |
|---|---|
| Anchor vocabulary, request-budget matrix, candidate ceiling | No discovery planner |
| Stored `StepInput` per model step, with allowlisted IDs and skill-package hash | Not present |
| Screening, passage inspection, located citation anchors | Not present |
| Numeric per-provider operator/term ceilings | Not observed in the scanned files |

## 4. Directly transferable, operationally relevant findings

These are the findings that touch this codebase today.

1. **Keyless OpenAlex daily budget — does not apply to this installation.** findpapers `docs/databases.md` states that without an API key OpenAlex allows **~10 requests per day** (0.01 USD budget) **[V]** as project documentation. **Measured against this machine's live library on 2026-09-18: all 62 recorded OpenAlex calls carry `access_mode = api_key`**, and the stored response headers read `x-ratelimit-limit: 10000`, `x-ratelimit-cost-usd: 0.001`, `x-ratelimit-remaining: 9240–9990`, `x-ratelimit-remaining-usd: 0.924–0.999` **[V]**. The keyless ceiling is therefore **not** a binding constraint here; headroom is at least two orders of magnitude above a full default run.
   The remaining ambiguity is the header's unit scale: `remaining` only ever moves in multiples of ten while the recorded per-call cost is 0.001 USD, so the exact daily ceiling should be read from `x-ratelimit-remaining-usd` divided by `x-ratelimit-cost-usd` rather than from either header alone. **The correct action was to measure, not to adopt the documented figure** — see section 4a for the measurement this produced.
2. **PubMed phrase length.** findpapers `docs/databases.md` records that PubMed's phrase index supports roughly three-word phrases and that longer exact phrases **silently return zero results** **[V]** as documentation. This is the same failure class as DEIXIS's recorded OpenAlex D11 measurement, arrived at independently.
3. **Provider choice is a first-order recall determinant** — see Bramer et al. in section 5. Consequence for an 8-request budget: spreading requests across providers is better supported than deepening a single provider.
4. **Silent shape failure is the shared risk.** findpapers documents a phrase length that returns **zero** results without an error; DEIXIS's recorded D11 measurement is the neighbour of the same problem, a broad shape that returns records of which almost none are relevant. Neither failure announces itself, which is why a request that returns nothing — or returns only non-relevant records — must be recorded as a shaped-query problem before it is recorded as "the topic is not there".
5. **Cross-project confirmation of the operational-error class.** The literature pass itself received **HTTP 406** from Springer and BioMed Central **[V]**, the same class of bot-blocking that this repository recorded from arXiv. Provider-side blocking is not a retrieval-quality signal.

## 4a. Measurement against this machine's recorded calls

Recorded from `search_runs` in the live library on 2026-09-18, read-only **[V]**. Scope: the 18 researches that have recorded searches, created between 2026-09-14 and 2026-09-16. The last recorded search is 2026-09-16T23:55; the two researches created on 2026-09-17 are present in the library but have **zero** `search_runs` rows, and the probe scripts in `scripts/` never write to `search_runs` at all. This table therefore describes the 2026-09-14 to 2026-09-16 application runs and says nothing about the 2026-09-17 question work.

| Provider | Recorded calls | Access mode | Result |
|---|---|---|---|
| openalex | 62 | `api_key` (all) | 60 completed, 2 zero_results; `x-ratelimit-cost-usd: 0.001`, limit 10000 |
| ieee_xplore | 18 | `api_key` | completed |
| scopus | 13 | `api_key` | completed |
| arxiv | 18 | keyless | 9 completed, **8 `ReadTimeout`** (all on 2026-09-14), 1 zero_results |
| crossref | 7 | keyless | completed |
| semantic_scholar | 10 | `api_key` | 7 completed, **3 `rate_limited` (HTTP 429)** |
| serpapi | 3 | `api_key` | completed |
| pubmed | 2 | `api_key` | completed |
| core | 1 | `api_key` | completed |

Two findings that the scan did not predict and that matter more than the imported figure:

1. **Three Semantic Scholar requests failed with HTTP 429 while the recorded mode is `api_key`.** Dates: 2026-09-15 18:57, 2026-09-15 20:47, and **2026-09-16 13:00 with the query `quantum entanglement routing MILP decoherence`** — that is the quantum-question research (`res_WXhs`, recorded 8 searches across 6 providers, 95 records). The provider's message is the generic "Too Many Requests … apply for a key for higher rate limits", and the stored `rate_limit` map is **empty**, so no `retry-after` was available for a bounded retry (D66). A keyed request that the provider still throttles, with no retry hint, is a different operational state from both "rate limited but retryable" and "entitlement missing".
2. **The app's own arXiv calls contain no 406.** The 406 exists only in the standalone probe `.local/elicit-consensus-deixis-comparison-2026-09-17-v2/Q5-arxiv-search.json`. In the application path, arXiv failed as **`ReadTimeout`** and in one case returned zero results. The two are separate work items and should stay separate: a probe that is blocked while the app times out is not evidence that the app would be blocked.

Also measured: recorded searches per research question range from 4 to 16, with 8 and 10 both occurring for single questions, so the "8 requests" figure is the default rather than an observed maximum.

Across all 134 recorded searches in this window, every recorded HTTP status is **200** except the three Semantic Scholar 429s, and the only non-status failure is the eight arXiv `ReadTimeout`s. In other words the application's recorded search layer is otherwise status-clean; the two operational defects above are the complete set, not examples.

### 4a.1 Semantic Scholar 429 diagnosis — live, read-only, 2026-09-18

The keyed-429 row above was left as "a keyed request that the provider still throttles" with the mechanism unresolved. It has since been diagnosed with live requests from this machine: **34 requests to `api.semanticscholar.org` in five series**, none of them touching the library or the running service. The result changes the interpretation of the recorded failures.

**What was ruled out [V]:**

- **The key is not being rejected.** With the same key the app loads, `GET /graph/v1/paper/search` returned **200**; a deliberately invalid key returned **403** `{"message":"Forbidden"}`; a keyless request returned **429** carrying byte-identical provider text to the three recorded failures. So a 429 is not a key-status signal, and the recorded message ("…apply for a key for higher rate limits") cannot be read as evidence that no key was used.
- **The User-Agent is not the trigger** — although the first three requests suggested it. With a valid key and the app's own header (`DEIXIS/0.1 (local research workspace)`) one request returned 429 and another returned 200 **two minutes apart**; in a 16-request interleaved series (two `User-Agent` values alternated, constant 3 s spacing, identical query, valid key) both values scored **exactly 5 × 200 and 3 × 429**. An intermediate UA-blocking hypothesis was formed and then refuted by its own control; it is recorded here so it is not rediscovered as a fix.
- **DEIXIS's own traffic is not the cause.** Recorded searches are strictly sequential, the 2026-09-15 18:57 failure came ~20 h after the previous Semantic Scholar call, and the provider answers a rejected request in **0.6–0.7 s** while a served request takes **1.2–1.4 s** — a fast edge rejection, not a queued quota response.
- **Retry spacing does not explain the recorded pattern either.** In the app's own record the *same query* was `rate_limited` at 2026-09-15 18:57 and `completed` with 25 results at 19:37, with no code, key, or header change between them.

**What the evidence supports [V]:** the intermittent 429 is generated at the provider's CDN edge, not by the documented per-key quota. In the series where response headers were recorded, **every 429 carried `x-cache: Error from cloudfront` and every 200 carried `x-cache: Miss from cloudfront`**, from the same edge location. The condition is **time-clustered at the minute scale**: 3 of 8 requests in one series failed, and a further 8 requests minutes later on the same key failed 0 times. Across the two paths that can be compared, the rate agrees — **3 of 10 keyed searches in the app record (30%)**, **3 of 8 requests in the live series (37%)**.

**Consequences for the product [I]:**

- The 429 is a minor, externally imposed nuisance affecting roughly one keyed search in three, not a misconfiguration. D18's behaviour (record the failure, keep the run, continue with the remaining providers) is already the right response, and the UI already renders it: `provider_rate_limited` in `apps/web/src/labels.ts` and `rate_limited: 'warn'` in `apps/web/src/ResearchView.tsx`.
- The provider's message becomes **wrong for a keyed user** — it instructs them to obtain the key they are already using. A message copy that names the observed state (provider-side edge rejection, no `retry-after` given) would be more accurate than the provider's own text.
- **The current retry configuration has never been exercised.** `UNSTATED_RATE_LIMIT_WAIT` was raised 3.0 → 15.0 in `8d61ad0` (2026-09-16 16:33 local), **33 minutes after** the third recorded failure; no Semantic Scholar search row exists after that commit. Whether 15 s + 30 s clears a bad window is therefore **untested**, and the record does not support "wait longer fixed it".
- The recorded 10.9 s gap between the preceding Scopus row (13:00:24.355) and the failing Semantic Scholar row (13:00:35.289) is consistent with one rejected request plus 3 s and 6 s retries — i.e. at the time of the failure all three attempts were rejected, in a window where the edge was rejecting essentially everything. `add_search_run` stamps `retrieved_at` *after* `send()` returns, so a row timestamp measures completion including retries; attempt counts are not persisted.
- **Latent inconsistency, observed and not changed:** `_retry_wait()` in `backend/deixis/providers/common.py` returns `unstated_wait * (retries + 1)` when `retry-after` is absent and **never applies `max_retry_wait`**, contradicting `send()`'s own docstring and the `MAX_RETRY_WAIT_SECONDS` comment. With the current constant a single search can sleep 15 s + 30 s inside one HTTP call. This is recorded as an observation, not fixed, and it is a code-level finding rather than a search-quality one.

**Still unresolved [U]:** what the edge limit is keyed to (client IP, API key, connection reuse, or shared edge capacity); whether the currently configured 15 s/30 s waits would clear a bad window; and whether Semantic Scholar exposes any key-status endpoint for quota introspection — the API surface was not enumerated, so no claim is made here. An endpoint control (paper lookup vs. search, 4 + 4 requests) returned 200 on all eight and therefore **failed to discriminate** endpoint scope, because it happened to run in a clean window.

## 5. Literature scan

Peer-reviewed unless marked otherwise. **[R]** throughout unless noted; I independently re-verified only the two identifiers named in section 6.

### Established

| Finding | Source | Numbers |
|---|---|---|
| Provider choice dominates recall under fixed search effort | Bramer, Rethlefsen, Kleijnen et al., *Systematic Reviews* 6:245, 2017 | Four-database combination reached >95% recall in **93%** of reviews; without Embase, **39%** |
| Hand-built broad Boolean queries over-retrieve non-relevant records | Scells, Zuccon, Koopman, WWW 2019 (`10.1145/3308558.3313544`) and WWW 2020 (`10.1145/3366423.3380185`) | Qualitative; abstract wording confirmed verbatim |
| Systematic-review search strategies are mostly flawed | Salvador-Oliván, Marco-Cuenca, Arquero-Avilés, *JMLA* 107(2):210–221, 2019 | **92.7%** of 137 strategies contained at least one error, with measurable retrieval loss |
| Fusing multiple providers' runs beats single runs | Cormack, Clarke, Büttcher, SIGIR 2009, RRF (`10.1145/1571941.1572114`) | — |
| Natural-language literature search has a low ceiling | Ajith et al., LitSearch, EMNLP 2024 (`10.18653/v1/2024.emnlp-main.840`) | Best dense retriever **74.8%** recall@5 (+24.8 over BM25); commercial web search **≤42.8%** |
| Reinforcement-learned query generation plus citation crawling | He, Huang, Feng, Lin, Zhang et al., PaSa, ACL 2025 long (`10.18653/v1/2025.acl-long.572`) | **+37.78%** recall@20 over Google + GPT-4o |
| Multi-perspective question asking | Shao et al., STORM, NAACL 2024 | **+25%** absolute "organized"; **+10%** breadth |
| End-to-end academic synthesis system | Asai et al., OpenScholar, **Nature** 2025, "Synthesizing scientific literature with retrieval-augmented language models" (`10.1038/s41586-025-10072-4`) | GPT-4o citation hallucination **78–90%** (vendor-reported) |
| Search reporting standard | Rethlefsen, Kirtley, Waffenschmidt et al., PRISMA-S, *Systematic Reviews* 10:39, 2021 | 16-item checklist; prescribes reporting, not optimisation |
| Effort-budgeted recall evaluation | TREC Total Recall Track overviews, `trec.nist.gov/pubs/trec24/papers/Overview-TR.pdf` and `.../trec25/papers/Overview-TR.pdf` | Measures **human review effort**, not API requests |
| Boolean query refinement against validation citations | Scells & Zuccon, CIKM 2018 (SearchRefiner); Scells et al., ECIR 2020; Scells et al., *Information Retrieval Journal*, 2020 | Objective-based formulation beats conceptual formulation; **numeric results unverified** (paywall, publisher 406) |
| RL-trained Boolean query generation | Wang, Scells, Koopman, Zuccon, "AutoBool", **preprint** arXiv:2602.00005 | Reports matching or exceeding GPT-4o and o3 while retrieving **10×–16× fewer documents**; self-reported, not peer-reviewed **[U]** |
| Seed-based term selection | Grames et al., litsearchr, *Methods Ecol. Evol.* 2019 (`10.1111/2041-210X.13268`) | Author-reported only |

### Interpretation

Pre-retrieval and feedback methods confirm the general shape of the problem without settling it: Cormack & Grossman's tuning-free calibration work supports calibrated score thresholds over manual cut-offs; Cao, Nie & Gao (SIGIR 2008, `10.1145/1390334.1390377`) frames pseudo-relevance feedback as a recall gain that risks query drift; Cronen-Townsend, Zhou & Croft (SIGIR 2002) establishes that pre-retrieval predictors such as query clarity correlate with average precision only **moderately**, which is not reliable enough for a hard cutoff decision.

## 6. Corrections to earlier reasoning in this repository's design thread

Recorded because the earlier turns stated them, and one of them is now known to be misattributed.

1. **The set-cover / integer-programming framing of search-strategy design was not located in any peer-reviewed source.** The nearest verified optimisation framing is Scells' "objective-based" formulation, in which queries are derived computationally from seed or known-relevant documents. **The set-cover proposal was a design inference made in conversation, not a literature-backed method, and must not be recorded as one.**
2. **The Scells "saving strategy" terminology could not be located** and is likely a conflation **[U]**.
3. **"PaperQA2 exceeds human performance" is broader than its evidence.** On LitQA2 (arXiv:2409.13740, preprint), precision was 85.2% ± 1.1 against human 73.8% ± 9.6 (p = 0.0036), while accuracy was 66.0% ± 1.2 against human 67.7% ± 11.9 (**p = 0.66, not significantly different**). The superiority claim holds for precision only — and the paper's own title ("Language agents achieve superhuman synthesis of scientific knowledge") is where the broader restatement comes from.
4. **AutoBool verified directly:** arXiv:2602.00005, submitted 2025-11-21, authors Shuai Wang, Harrisen Scells, Bevan Koopman, Guido Zuccon **[V]** via the arXiv API. Peer-review status **[U]**.
5. **Scells IRJ 2020 DOI verified directly:** `10.1007/s10791-020-09381-1`, *Information Retrieval Journal*, "A comparison of automatic Boolean query formulation for systematic reviews" **[V]** via Crossref.

## 7. Where no evidence exists

These gaps matter more than the findings, because they define what DEIXIS cannot borrow.

- **No located benchmark measures known-item recall under a fixed API-request budget** across OpenAlex, Semantic Scholar, Crossref or arXiv. TREC Total Recall is the closest framing and measures human review effort instead.
- **No finding on the optimal number of queries or the provider-call allocation.** The 250-record candidate ceiling and the 8-request default are design choices; nothing in this scan validates those numbers.
- **No independent replication of litsearchr's validation.**
- **No peer-reviewed source adopts the set-cover framing** (section 6.1).
- **Scells' numeric results remain unverified** behind paywalls and a publisher 406.
- The star counts and repository facts in sections 1–4 are dated **2026-09-18** and will drift.

## 8. Bounded conclusions

1. No scanned project or paper implements the combination this repository has, and none of them can be adopted as the search strategy. findpapers is the closest architectural match for query compilation only.
2. The imported keyless-OpenAlex budget figure **does not hold here** — the measured mode is `api_key` on all 62 recorded calls, with headroom far above a default run (section 4a). The scan's instruction to measure rather than adopt was the useful part; the figure itself was not.
3. The literature supports distributing a fixed request budget across providers (Bramer) over deepening one, and supports recording provider-specific query-shape limits rather than assuming one shape works everywhere.
4. The measurement in section 4a did surface two operational items that the scan had not predicted, and they outrank the imported figure: **keyed Semantic Scholar requests that still returned 429 with no `retry-after`**, one of them on the quantum question's own run, and the need to keep the **probe-path 406** separate from the **application-path `ReadTimeout`**. The first of these was subsequently diagnosed (section 4a.1): the key is honoured, the `User-Agent` is not the trigger, and the rejection is edge-generated, intermittent, and time-clustered at roughly one keyed search in three — so it is a nuisance to record and survive, not a configuration error to repair.
5. The gap in section 7 is the reason the frozen evaluation protocol in `docs/product/search-query-structure-design-2026-09-18.md` cannot be replaced by a published metric: there is no published metric for this budget regime. That makes the protocol more necessary, and also means an apparently good result will have no external baseline to check it against.
6. **Nothing here promotes a strategy to default.** The selectable-experiment status recorded in the companion documents stands unchanged.

## 9. Limits of this scan

- Star counts, contributor counts and push dates are a 2026-09-18 snapshot taken from the GitHub API **[V]**.
- Every DOI cited in section 5 was resolved against the Crossref API on 2026-09-18 and returned a matching title **[V]**. `arXiv:2602.00005`, `arXiv:2504.12516` and `arXiv:2409.13740` were resolved against the arXiv API **[V]**. Identifiers are therefore checkable; **the reported numbers inside those papers are still [R] or [U]**, not re-measured here.
- Repository internals were read from current default-branch files **[V]**; a rewritten main branch can invalidate file paths cited here.
- Most literature items are **[R]**: identifiers, venues and reported numbers were checked against primary metadata, but the underlying papers were not re-read here except where marked **[V]**.
- Two paywalled venues returned HTTP 406 to the literature pass, so the Scells numeric results could not be confirmed.
- Vendor-reported figures (OpenScholar, Deep Research inside BrowseComp, AutoBool) are labelled as such and are not independent measurements.
- The section 4a measurement is a **read-only snapshot** of `search_runs` in the live library on 2026-09-18, covering the 2026-09-14 to 2026-09-16 application runs. The 2026-09-17 question work has no rows in that table and is **not** described here; no claim in this scan describes its provider behaviour. The live service was not stopped or restarted.
- Section 4a reports recorded state, not transport-level truth: `access_mode` is what DEIXIS sent, and a 429 recorded against `api_key` mode does not establish which limit the provider applied. Section 4a.1 supplies the transport-level measurement that the recorded table could not, from 34 live requests on 2026-09-18.
- Section 4a.1 established that the key is honoured, that the `User-Agent` is not the trigger, and that the 429 is edge-generated and time-clustered. It did **not** establish what the edge limit is keyed to, and it did **not** exercise the current 15 s/30 s retry configuration, which no recorded search has used. The "wait longer" change therefore remains an untested mitigation, not a verified fix.
- Every number in section 5 that comes from a source other than this repository is a report of that source's own measurement or of a vendor's own claim; nothing in section 5 was reproduced here.
- This scan contains no measurement of DEIXIS's own search behaviour. Its only claims about this repository are about code structure, the recorded provider-call table above, and numbers already recorded in the companion documents.
