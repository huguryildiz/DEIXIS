# Search strategy critical review — anchored multi-intent proposal

**Status:** proposal; no search behavior has changed and no query strategy is selected. **Date:** 2026-09-18.

The question under review is the quantum-network one used in the 2026-09-17 application run. That run is now a training case: its failure was seen before this design was written, so nothing derived from it is generalization evidence.

The query-structure design that follows from this review is recorded separately in `docs/product/search-query-structure-design-2026-09-18.md`; that file keeps D11's two-part topology and D60's deep core read and adds anchor vocabulary, spread, provider allocation and the deterministic guards. The external comparison — open-source projects that compile multi-provider scholarly queries, and the peer-reviewed literature on Boolean query formulation and budgeted retrieval — is in `docs/product/search-strategy-external-scan-2026-09-18.md`. That scan also corrects one item stated during this review: the set-cover framing of strategy design was a design inference, not a located research result.

## Decision proposal

1. Promote no strategy to default. The evidence does not validate one; it shows that the active `legacy` plan produced measurably dead requests on this question.
2. Do not promote `compact_openalex_v1`; it already failed the LitSearch validation (`docs/product/search-method-validation-results-2026-09-17.md`, 2/6 questions, 4/12 gold).
3. Add **anchored multi-intent with provider depth** as a selectable experiment only, with two hard rules: every request carries a mandatory domain anchor, and the core phrase is not imposed as a required quoted part. That form is not sendable under the active shape rules today (C.4), so promoting it also means changing the validator — one more reason to keep it opt-in.
4. Keep the deep core read, but concentrate it on two or three providers, and treat arXiv HTTP 406 as a separate operational work item.

## A. What the evidence shows and does not show

### A.1 Request-by-request record of the real run

From `.local/quantum-entanglement-search-2026-09-17/application-run/summary.json`:

| # | Provider | Query shape | Limit | Returned | Provider total |
|---|---|---|---|---|---|
| 1 | openalex | core only, three quoted phrases OR-ed (deep read) | 100 | 100 | 253 |
| 2 | openalex | core (2) **AND** formulation family (4) | 25 | **1** | 1 |
| 3 | semantic_scholar | plain six words | 25 | 25 | 614 |
| 4 | arxiv | `abs:` core AND `abs:` scheduling family | 25 | 0 | **HTTP 406, empty body** |
| 5 | ieee_xplore | core (2) AND memory family (4) | 25 | **1** | 1 |
| 6 | crossref | plain six words | 25 | 25 | 1,715,921 |
| 7 | scopus | `TITLE-ABS-KEY(core AND performance family)` | 25 | **0** | 0 |
| 8 | core | core (2) AND quantum-network family (4) | 25 | 9 | 9 |

The totals sum to 161 = 100 + 1 + 25 + 0 + 1 + 25 + 0 + 9.

What this shows: the budget was spent on provider breadth (eight requests, seven providers) while half the requests returned almost nothing, and roughly 62% of the 149 unique works came from a single request. A direct lookup of the six controls proved 6/6 are in the provider indexes, so this is a query-formulation and ranking observation, not an index gap. The run's stored `library.sqlite` under `.local/quantum-entanglement-search-2026-09-17/application-run/data/` additionally shows that **the 100-row OpenAlex deep read contained none of them**, while the same provider served five of the six under the short-query rescue later that day (the sixth was missed by both providers).

What this does not show: that these eight queries are the best or worst possible. It is one question, one day, one model. "The required narrow core phrase caused the dead intersections" is a hypothesis, not an established cause, because query formulation was not varied independently of provider and depth.

### A.2 Why 1/6, 5/6 and 0/8 are not directly comparable

| Dimension | 1/6 (application run) | 5/6 (rescue) | 0/8 (engineering pilot) |
|---|---|---|---|
| Question | one quantum question | **the same** question | four different questions (H1–H4) |
| Provider mix | seven providers, eight requests | **two providers**, eight requests | OpenAlex-heavy, 31 requests per arm |
| Query form | Boolean with a required quoted core | four-word plain text | A: quoted core; B: free intents |
| Depth | 25 per request plus one 100 read | 25 per request | 25 per request |
| Control selection | afterwards, by the analyst who saw the failure | designed **after** the failure | before the pilot, same analyst |
| Human relevance labels | none | none | **none** (blind packages were produced but left empty) |
| Outcome measured | control coverage plus structural validity | control coverage plus ranks | control coverage plus raw volume |

Seven confounders are in play: question count, provider mix, query form, depth, control-selection timing, absent labels, and a single day against a single index state. The 1/6 to 5/6 change is therefore not evidence that one strategy is better; the strongest defensible reading is that short plain queries reached five of six controls on this question, and OpenAlex served five of them by itself. The 0/8 result does not show that independent search intents are bad in principle; it shows this application of them failed because the topical anchor was dropped (816 rows, 784 unique, `"storage siting"` drifting to biology and geology, `"joint routing scheduling"` drifting to wireless mesh).

### A.3 Limits of the remaining evidence

- The 35 included records are a model screening proposal, not human-verified relevance. `structurally_valid` is a deterministic contract check; it is not semantic support. Manual spot checks of two citations in that run did not support every sub-claim, and no systematic claim-to-passage support measurement was performed.
- Three PDFs were acquired out of eight attempts. PDF access is a separate measurement and must not be merged with control coverage.
- The Elicit query records show only that several angles exist for the same question (distribution/fidelity, repeater routing and resource allocation, ILP, general end-to-end optimization). They establish nothing about Elicit's internal algorithm, its automatic second pass, or its literature coverage.
- arXiv HTTP 406 is unrelated to search quality and does not by itself explain the run: three other requests answered HTTP 200 with 0 or 1 records. "Server rejected" and "nothing matched" are different states and both stayed visible.

### A.4 Where the active code produces this

- `max_provider_requests = 8`, `results_per_query = 25`, `max_candidates = 250`, `core_depth = 100` (`backend/deixis/domain/rules.py`). The `core_depth` query consumes a request slot (`backend/deixis/providers/query_compiler.py`).
- `_round_robin(families, providers)` gives every provider its own request once the provider count reaches the request budget, so a second angle on the same provider cannot be expressed.
- `_fit()` drops trailing terms until the shape and character limits pass, silently narrowing the query.
- Candidates are sliced in query order (`backend/deixis/workflow/flow.py`); once `max_candidates` is reached, later queries' candidates never reach screening. This did not trigger in the run (161 stored), but the plan in section C can trigger it.

## B. Strategies comparable under one budget

Shared budget: eight provider requests, 25 per request with one 100-row read, the 250-candidate ceiling, the same provider set, the same model and reasoning effort, and the same screening. Only query generation changes.

**S1 — current `legacy`: one long core plus families.** Gain: the forced core expression raises precision and carries the formulation signal. Failure modes: (i) it treats question wording as a required phrase, so intersections are empty when the literature uses different words (1/1/0/9 here); (ii) the budget spreads across providers, forbidding a second angle per provider; (iii) `_fit()` drops terms silently; (iv) the OpenAlex shape rules (at most two required parts, at most five Boolean operators) distort the planning space; (v) HTTP 200 with `zero_results` reads like "no such literature".

**S2 — compact many-query.** Gain: removes the vocabulary dependency. Four short queries in the rescue recovered five of six controls (OpenAlex served five, at ranks 1/4/6/14/16; Semantic Scholar three, at ranks 3/6/8/21), and a plain Semantic Scholar query returned the only control the application run found, at rank 0. Failure modes: (i) precision loss and unfocused volume (Crossref reported 1,715,921 matches); (ii) loss of the formulation signal, so method papers no longer rise; (iii) drift when the anchor is weak; (iv) it failed the LitSearch threshold (2/6 questions, 4/12 gold); (v) a larger candidate load raises screening cost and false-positive selection risk.

**S3 — anchored multi-intent with provider depth (preferred).** Derive five to seven intents from the question (distribution flow, path selection, scheduling and multiplexing, memory capacity, fidelity and decoherence, formulation class). Every request carries a mandatory domain anchor. The budget concentrates on two or three providers, one of them deep. The core phrase is not imposed as a required quoted part.

Accepted failure modes of S3:

1. **Domain drift.** General terms such as `routing`, `scheduling` and `resource allocation` reintroduce the drift seen in the engineering pilot (H1, H2, H4).
2. **Volume against quality.** More candidates approach the 250 ceiling, where later queries' candidates are dropped and screening silently runs short.
3. **Provider coverage loss.** Concentrating eight requests on two or three providers discards other indexes. That is an independent intervention and must be reported as a confounder.
4. **Control-driven overfitting.** Optimising for a small control set can inflate coverage without improving human-judged relevance, which is why control coverage is never the only acceptance measure.
5. **Unmeasured transfer.** More discovery does not imply better claim-to-passage support; the two are reported separately.
6. **Hidden vocabulary dependency.** If intents are still derived from the question wording, anchors stay weak when the literature uses other words. Anchor terms should come from field terminology, not from the question's phrasing.

## C. Concrete plan for the test question, at most eight requests

This plan is a development artifact: the question is a training case, so a result from it is development evidence only. No DOI, title or author name appears in any query; queries are derived from the question text and field terminology alone.

### C.1 Provider syntax treated separately

| | OpenAlex | Semantic Scholar |
|---|---|---|
| Field | `search.title_and_abstract` | plain `query`, abstracts included |
| Boolean | shape checks apply: at most two required parts, no three-plus unquoted consecutive words, at most five Boolean operators | quotes, parentheses and AND/OR are not interpreted; free words |
| Words | required quoted core with OR families (current compiler) **or** three to four unquoted words (the form that worked in the rescue) | at most eight words, no quotes |
| Use here | three to four unquoted words, no required quoted part (not sendable today — C.4), plus one deep read | two plain-word angles (up to eight words) |
| Depth | up to 200 per request at the adapter | `limit` |

Only the behaviours recorded in the adapter docstrings are relied on: `search=` is interpreted as full-text search with poor topical precision and `search.title_and_abstract=` searches titles (`backend/deixis/providers/openalex.py`); Semantic Scholar takes a plain `query` with `limit` (`backend/deixis/providers/semantic_scholar.py`). No unverified API behaviour is asserted.

### C.2 Requests

| # | Provider | Purpose | Mandatory anchor | Distinguishing model/mechanism terms | Query draft | Limit | Off-topic drift risk |
|---|---|---|---|---|---|---|---|
| 1 | openalex | Broad topical base and deep read | `entanglement distribution quantum network` | — (breadth on purpose; the qualifier is dropped so the rank list stays wide) | `entanglement distribution quantum network` | **100** | Medium-high: "entanglement" in condensed-matter and optics senses |
| 2 | openalex | Path selection / routing | `quantum network entanglement` | `routing` | `quantum network entanglement routing` | 25 | High: classical network routing, QKD-only papers |
| 3 | openalex | Scheduling / memory | `quantum repeater memory` | `scheduling` | `quantum repeater memory scheduling` | 25 | High: general scheduling; dies without the anchor |
| 4 | openalex | Formulation class (model family) | `quantum network programming` | `linear` | `quantum network linear programming` | 25 | Medium: LP/ILP method papers in unrelated domains |
| 5 | openalex | Fidelity, decoherence, purification | `entanglement fidelity decoherence purification` | `purification`, `decoherence` | `entanglement fidelity decoherence purification` | 25 | Medium: decoherence in quantum computing and condensed matter |
| 6 | semantic_scholar | Independent ranking and second vocabulary | `entanglement distribution quantum network` | `routing`, `optimization` | `entanglement distribution quantum network routing optimization` | 25 | Medium: loose relevance ranking, wide volume (614 matches in the run) |
| 7 | semantic_scholar | Resource-allocation angle | `quantum repeater` | `resource allocation`, `scheduling` | `quantum repeater network resource allocation scheduling` | 25 | High: classical network, EV and cloud allocation literature |
| 8 | crossref | Publisher records and preprints | `entanglement distribution quantum network` | — | `entanglement distribution quantum network` | 25 | Very high: loose ranking (1.7M matches in the run), abstracts often absent |

Every OpenAlex draft stays at three to four unquoted words on purpose: with the loose form each word is required (implicit AND), and the rules' own probe found six unquoted words collapsing to four works. That ceiling costs vocabulary — `integer`, `multiplexing` and `optimization` had to be dropped from the drafts above, and `linear programming` alone does not reliably surface ILP formulations. The compiler-valid alternative for those requests is a quoted core plus one parenthesized OR group (`"quantum repeater" (scheduling OR multiplexing OR "memory allocation")`), which keeps two required parts and can be sent today; the plan should carry one or two requests in that form so both shapes are measured in the same run.

### C.3 Budget conflict to resolve first

The plan asks for 275 rows (100 + 7×25) against `standard`'s 250-candidate ceiling, and because candidates are sliced in query order the eighth request's candidates may never reach screening. One option must be chosen and recorded: drop to seven requests and keep the 100-row read; use `detailed` (12 requests, 300 candidates), which changes the comparison budget; or lower the deep read to 75 and keep eight requests.

The plan also changes the provider mix (seven providers to three). That is a separate intervention and belongs in the comparison as a confounder, not as part of "the effect of the query strategy".

### C.4 Which part of this plan the active code can actually send

The shape rules (`backend/deixis/providers/query_rules.py`) reject three or more unquoted words in a row and more than two required parts for OpenAlex-style queries, so the loose three-to-four-word form used above is **not sendable today**: the compiler builds every query to pass those checks (D44) and would have to change for this plan to run inside the product.

The rescue that produced the five-of-six result called the connector directly (`.local/quantum-entanglement-search-2026-09-17/rescue.py`), so it bypassed the validator entirely and is a probe result, not a product-executable form. The rules' own live probe points the other way at the other end of the range: six unquoted required words returned four works and none of 22 user-known papers. The two observations bound OpenAlex's behaviour but the boundary between them is untested, so the anchor form must be measured under the frozen protocol before any code change is justified.

## D. Frozen evaluation to run before any default change

`holdout-design.md` is a good draft but is not frozen. It is extended as follows.

### D.1 Freeze before any query is written

One file, sealed with SHA-256, holding the question list, control list, both blind rating packages, arm definitions and thresholds.

- **Unseen questions:** at least 12, chosen before any query plan exists, at least six from fields DEIXIS has not touched. The planner receives the question text and nothing else.
- **Controls:** four to eight works per question, selected by someone other than the query author, from a source independent of the strategy's own output. Each control is verified by exact identifier lookup against the provider index **before** the run, and the verifying provider and timestamp are recorded. A control that cannot be verified is not added, otherwise "not retrieved" and "not indexed" become indistinguishable; the run already showed both states separately.
- **Equal budget:** the same provider set, request count, `results_per_query`, `core_depth`, `max_candidates`, model, reasoning effort and screening. Only query generation differs. A provider-mix change becomes a separately labelled arm.
- **Same sending path for every arm:** each arm sends its queries through one shared request builder, and the arm's constraints are recorded next to the queries. A probe that calls connectors directly is a load-bearing difference, not an implementation detail (C.4), and it must be visible in the table. Control requests that a validator would reject must be reported as rejected, never dropped silently, so the arms stay comparable.

### D.2 Four separate result tables, never one score

| Table | Measurement | Reported as |
|---|---|---|
| 1. Known-item coverage | found/not found per control, first rank, provider | per question plus total, with median rank in its own column |
| 2. Human relevance | two blind raters, title and abstract only, three levels (`directly relevant` / `not directly relevant` / `insufficient information`) | shuffled candidate order, provider and arm hidden, rater agreement reported, at least 60% of returned records labelled |
| 3. PDF access | attempted versus acquired full texts, with failure reason | rate plus reason breakdown (3/8 in the application run) |
| 4. Claim–citation support | random sample of answer claims against the cited passage | `supported` / `partially` / `not supported`, presented as a recorded assessment rather than independent human verification |

Requested K, returned count, provider total and failed-request count stay visible per query; a failed request and a zero-result request are never shown as the same row.

### D.3 Pass and fail thresholds, all required together

1. **Coverage:** S3 beats S1 on total control coverage, improves at least 3 of 12 questions by one control, and regresses on none.
2. **Quality guard:** the `directly relevant` rate does not fall more than 10 points below S1.
3. **Volume guard:** candidates reaching screening stay within 1.5× S1.
4. **PDF guard:** the acquisition rate does not fall below S1.
5. **Claim-support guard:** no material increase in `not supported`.
6. **Operational:** no request is labelled a zero result when it failed; 406-class rejections appear as `failed/rejected_not_executed`.

### D.4 When the strategy stays an experiment only

- If controls cannot be verified against the index, or fewer than two blind raters are available, the protocol stops in preparation and no result is published.
- If equal budgets cannot be held, the result is exploratory only and cannot feed a product decision.
- If the guards in D.3 fail, the strategy is not made default; at most it remains a selectable `query_strategy` marked experimental in the interface.
- Statistical significance, generalization and "better search" are never claimed; n is small and the controls are not a complete gold standard.

## E. Separate short diagnostic for arXiv HTTP 406

Fixed rule: 406 is never counted as zero results and no provider is silently substituted. The current behaviour is correct and stays: `backend/deixis/providers/arxiv.py` routes the response through `send()` to `status="failed"`, `delivery="rejected_not_executed"`.

**Measured scope, added 2026-09-18 (read-only, live library):** the 406 is recorded **only** in the standalone probe `.local/elicit-consensus-deixis-comparison-2026-09-17-v2/Q5-arxiv-search.json`. The application's own arXiv calls in `search_runs` contain **no 406** — they failed as `ReadTimeout` (8 calls, one day, keyless) or completed. So step 0 of this diagnostic is to establish **which calling path produces 406** before ablating parameters: a probe-path rejection is not yet evidence that the application path would be rejected, and vice versa.

1. **Preserve the evidence.** For every request: full URL and parameters, timestamp, body (possibly empty), all response headers (especially `via`, `x-cache`, `server`, `age`), egress IP, HTTP version, and a body hash. This is what makes "which layer rejected it" discussable later.
2. **Reproducibility.** Repeat the same request three times from the same network, at least three seconds apart. Does the 406 reproduce, or is it intermittent?
3. **Parameter ablation, one variable at a time, at most ten requests.** In order: full query with sorting parameters; full query without them; a documented minimal `all:` query with sorting; the same without sorting; a single-term `abs:` shortening of the full query; a `ti:` variant. Record which inputs answered 200 and which answered 406.
4. **Client identity.** Repeat with a `User-Agent` and a contact address. Behind a corporate network or VPN, repeat once from a second network.
5. **Bound the finding, invent no cause.** The output is a table of which inputs passed and which were rejected. "Sorting parameters cause it" or "an edge layer blocks it" are written as hypotheses, never as findings.
6. **If the adapter must change.** Keep it minimal; add an `httpx`-mocked regression test (sorted 406, then an unsorted attempt, then a record or a `failed` outcome); if a fallback is used, write it to provenance and report it separately from the search-quality tables; add a new decision entry in `docs/decisions.md`.

Expectation management: fixing arXiv does not explain the 1/6 result. In the same run, IEEE, Scopus and the paired OpenAlex request answered HTTP 200 with 0 or 1 records. This is a separate operational item, independent of the query-strategy decision.

## Evidence sources

- `.local/quantum-entanglement-search-2026-09-17/result.md`, `application-run/summary.json`, `application-run/data/library.sqlite`, `rescue-run/score.json`, `rescue-protocol.md`, `holdout-design.md`, `arxiv-406-diagnostic.md`
- `.local/elicit-query-intents-2026-09-17/run2/RESULT.md`
- `docs/product/search-strategy-review-2026-09-16.md`, `search-recall-depth-2026-09-17.md`, `search-method-validation-results-2026-09-17.md`, `search-diverse-query-development-results-2026-09-17.md`, `search-adaptation-development-results-2026-09-17.md`, `elicit-consensus-deixis-comparison-results-2026-09-17.md`
- `backend/deixis/providers/query_compiler.py`, `backend/deixis/providers/query_rules.py`, `backend/deixis/providers/arxiv.py`, `backend/deixis/providers/openalex.py`, `backend/deixis/providers/semantic_scholar.py`, `backend/deixis/domain/rules.py`, `backend/deixis/workflow/flow.py`

Synthetic or scripted evidence is not involved in this document; every count above is either a stored record from a recorded run or read from the active code. Nothing here is an executed scientific review, a claim about Elicit's internals, a claim of complete literature coverage, or a claim of citation semantic correctness.
