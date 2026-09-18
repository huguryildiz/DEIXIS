# Search query structure — anchor × family design

**Status:** proposal; no code implemented and no default changed. **Date:** 2026-09-18.

This is a design and protocol record, not an accepted decision. It builds on the accepted record instead of reopening it: [D11](decisions.md) fixes the OpenAlex query topology, [D60](decisions.md) fixes the deep core read, [D64](decisions.md) owns the opt-in compact variant, and [D66](decisions.md) owns retrying failed searches. The critique and the candidate strategies are in `docs/product/search-strategy-critical-review-2026-09-18.md`; how other projects and the literature handle the same problem is in `docs/product/search-strategy-external-scan-2026-09-18.md`; this file answers one narrower question: **how should the query a provider receives be structured.**

## 1. Design in one sentence

A request is one **compound field anchor** crossed with one **family group**, and it is the *spread across requests* — not the size of any single query — that buys coverage; the deep read stays on the core-only query that D60 measured, with its anchor vocabulary drawn from field terminology rather than from the question's wording.

Three axes stay separate, because conflating them is what produced the recorded failures:

| Axis | Effect | Who owns it |
|---|---|---|
| Required part (`∩`) | narrows, can empty the intersection | D11's two-part limit; never more |
| Loose/relevance terms | broadens, reranks, drifts | family groups and plain-word providers |
| Provider shape | re-encodes, must not change meaning | `backend/deixis/providers/query_rules.py` |

## 2. What this design deliberately does not relitigate

- **D11's topology stands.** Broad boolean queries placed 1 of 22 known works, focused two-part queries 5 each, so the design keeps exactly two required parts with a quoted multiword anchor, and the earlier "drop the required anchor" idea is *not* proposed as a default. The loose three-to-four unquoted-word form appears only as a separately measured arm (section 7), because the only evidence for it — the rescue's five of six — came from a probe that bypassed the shape validator (`.local/quantum-entanglement-search-2026-09-17/rescue.py`).
- **D60's depth stays on the core-only query.** Its measured gains are real (S1 6/8 → 11/11, S2 4 → 7) and moving the 100-row read elsewhere would trade them away unmeasured. What this design does change is *which vocabulary the core query is built from* (R1), because D60's own recorded miss is a popular-topic question where a narrow core phrase kept the deep read from helping (S3 0 → 2 against a frozen expectation of at least +3).
- **D64 and D66 are not duplicated.** `compact_openalex_v1` remains the existing opt-in experiment; failed searches use D66's `retry_failed` rather than a new retry mechanism.

## 3. The rules

**R1 — Anchor vocabulary comes from the field, not from the question.** The anchor pool is a small, recorded set of compound field terms (for this question: `"quantum repeater"`, `"entanglement distribution"`, `"quantum network"`, `"entanglement routing"`, `"quantum internet"`). A deterministic check refuses an anchor that is a verbatim multi-token substring of the question, and refuses a single-token anchor. Rationale to be tested, not assumed: the only control-bearing request in the recorded run was a plain field-term query, and D60's miss is attributed to a narrow core phrase.

**R2 — One request = one anchor × one family group, in D11's form.** `"field anchor" (term1 OR term2 [OR term3])`: two required parts, at most five operators, at most three alternatives. Alternatives inside a group must sit at the same semantic level; a group is where a mechanism family lives (routing, scheduling/multiplexing, memory capacity, fidelity/decoherence/purification, formulation class).

**R3 — Spread is the coverage mechanism.** The plan is a matrix of anchors against families:

- the same (anchor × family) cell is never requested twice;
- every family appears in at least two requests, preferably on two providers;
- each anchor is used one or two times, so vocabulary risk is diversified rather than repeated;
- the allocation is deterministic and stored with the run, so a missing cell is visible as a *choice*, not as an accident.

For plain-word providers (Semantic Scholar, Crossref), where quotes and operators are not interpreted, the same intent takes the form **anchor-pool words first, then at most three family words, at most eight words total** — enforced by a check, so a family can never arrive without its anchor.

**R4 — Depth stays core-only, with an explicit alternative path.** `core_depth` 100 remains on the core-only query (D60). Reallocating depth is allowed only as a labelled arm with its own D60-style re-measurement: split 50/50 between the core-only query and the broadest anchor, or reduce the deep read to 75 to keep eight requests inside the candidate ceiling.

**R5 — Provider allocation is planned, not round-robin.** Allocation by recorded capability, not by turn: a provider receives either at least two requests or none, because the recorded run spent requests on IEEE, CORE and Scopus for 1, 9 and 0 rows. Crossref gets at most one request and is treated as an identity-resolution channel (loose ranking, 1.7M matches, abstracts often absent). arXiv gets zero requests until the `HTTP 406` diagnostic (review doc section E) concludes; a 406 stays a recorded `failed/rejected_not_executed` request and is never a zero result.

**R6 — Deterministic invariants, not prompt requests.**

- `sum(limits) ≤ max_candidates` before the run, so query-order slicing in `backend/deixis/workflow/flow.py` can never silently drop a planned request's candidates.
- `narrowed ≠ planned`: if a shape fixer has to drop terms, the request records `query_narrowed` and the dropped terms; if it cannot fit, the request is not sent and is reported as `not_sent` with the reason. Today `_fit()` drops trailing terms silently (`backend/deixis/providers/query_compiler.py`).
- `failed ≠ zero_results` (already enforced) and `empty facet ≠ no literature`: a family that produced no candidates is a coverage gap that the UI states, not an absence claim.
- **Known-control leakage check:** no generated query may contain a token from a control work's title or its DOI. This turns "no DOI or title leaked into the queries" from an inspection into a test.
- **Generic-term guard:** `routing`, `scheduling`, `optimization`, `model`, `resource allocation` and similar may never be the only non-anchor content of a request. On OpenAlex this generalizes D11's requirement that every query quote a multiword phrase; on plain-word providers it is new, and it is the deterministic version of the pilot's zero-of-eight failure, where free intents carried no topic anchor.

**R7 — Compensation is bounded and separated by cause.** A failed request is retried through D66's existing `retry_failed` path. An *empty* family (no candidates anywhere, no failure) is a different state and may trigger at most one compensation request built from the same anchor pool, recorded as a compensation request. No second round, no loop, no budget growth beyond the recorded allowance.

## 4. Retrievability map, and what it means for the answer

The eight features the test question asks about are not equally returnable by any query. The plan therefore records, per feature, how it can be reached:

| Feature | Retrievable as a term? | Route |
|---|---|---|
| routing / path selection | yes | family group (R2) |
| scheduling, multiplexing | yes | family group |
| memory capacity | partly (`"quantum memory"`, `buffering`) | family group plus full-text inspection |
| fidelity, decoherence, purification | yes | family group |
| formulation class (ILP, MILP, LP) | partly — `optimization` alone is generic | family group with a specific formulation term |
| decision variables, objectives, constraints | essentially no | full-text inspection only; `optimization`, `model`, `formulation` are proxies for retrieval, not verification |

The consequence is a claim boundary the answer layer must respect: for a feature the map marks full-text-only, a passage-level statement may not be recorded as abstract-verified. That makes the test question's own "verified from the abstract or the full text" distinction a *plan-level* pre-registration instead of a post-hoc judgement. This mapping is a design assumption; its accuracy is itself something the frozen protocol should measure.

## 5. Default plan for the test question (7 requests, exactly the candidate ceiling)

| # | Provider | Anchor | Family group | Limit |
|---|---|---|---|---|
| 1 | openalex | `"entanglement distribution"` | core-only (D60 deep read) | **100** |
| 2 | openalex | `"quantum repeater"` | routing / path selection | 25 |
| 3 | openalex | `"quantum network"` | scheduling / multiplexing | 25 |
| 4 | openalex | `"entanglement distribution"` | memory capacity | 25 |
| 5 | openalex | `"quantum repeater"` | fidelity / decoherence / purification | 25 |
| 6 | semantic_scholar | `entanglement distribution quantum network` (anchor-first plain form) | formulation class | 25 |
| 7 | crossref | `entanglement distribution quantum network` (anchor-first plain form) | scheduling / memory | 25 |

Arithmetic: `100 + 6 × 25 = 250`, so nothing is sliced and no request is wasted. Providers: three, each with at least two requests except Crossref, which carries the identity channel. Families: routing, scheduling/decision-time, memory and fidelity each appear twice; the formulation family appears on Semantic Scholar, which ranks differently from OpenAlex. Anchors: two OpenAlex anchors used twice each, diversified by family.

Two defects in this table are visible on inspection and are recorded rather than silently repaired, because both are design choices rather than typos. First, Semantic Scholar carries **one** request, so the plan does not satisfy R5's "at least two requests or none" for that provider, and — measured on 2026-09-18 (scan doc section 4a.1) — a single Semantic Scholar request has roughly a one-in-three chance of returning nothing at all, because the provider's edge intermittently rejects keyed requests. A plan that spends one request on a provider that can silently deliver zero is not the same as a plan that spends one request on a reliable provider, even though the budget arithmetic is identical. Second, the family-coverage sentence above does not follow from the table: reading the rows, routing and fidelity appear **once** each and only scheduling, memory and formulation appear in the intended pattern. Fixing either one changes which families are covered, so both are left for an explicit decision rather than resolved here.

This plan is developed on a question whose failure has already been seen, so any result from it is development evidence only, and no DOI, title or author name enters a query (R6 leakage check).

## 6. Implementation surfaces, when the decision is taken

- `contracts/research/search-plan.schema.json`: version bump for per-request `(anchor, family_group, provider, limit)` and the retrievability map.
- Same change: `methods/deixis-research/` instructions, `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/fakes.py::valid_response`, and the compiler version string.
- `backend/deixis/providers/query_compiler.py`: matrix allocation, anchor-first plain form, `query_narrowed`/`not_sent`.
- `backend/deixis/providers/query_rules.py`: leakage check, generic-term guard, anchor-pool check.
- `backend/deixis/workflow/flow.py`: the candidate-ceiling invariant and the empty-family state.
- Default stays `legacy`; the variant is selectable as a `query_strategy` value.

## 7. What has to be measured before this becomes a default

Run under the frozen protocol in section D of the review doc, and treat the arms separately:

1. **Anchor vocabulary (R1):** field-term anchors against question-derived anchors, same topology and budget.
2. **D11 relaxation (R2):** the quoted two-part form against the loose three-to-four-word form, in the same run, on the same provider, remembering that the loose form needs a validator change first and that D11's measurement currently favours the focused form.
3. **Deep read (R4):** core-only 100 against a 50/50 split on a popular-topic question, judged against a D60-style frozen expectation.
4. **Spread (R3):** family coverage per request budget, with the number of families reached by at least one candidate.
5. **Generic-term guard (R6):** the off-topic share of candidates with and without the guard, using blind title-and-abstract labels.
6. **Retrievability map (section 4):** how often a feature marked full-text-only was in fact absent from the abstract.

If any of the six cannot be held to an equal budget, or if fewer than two blind raters are available, the result is exploratory only, and the design stays a selectable experiment marked as such in the interface. Statistical significance, generalization, and "better search" are never claimed.

One budget caveat, measured on 2026-09-18 (scan doc section 4a.1): a provider can be present and correctly configured and still not deliver, because the Semantic Scholar edge intermittently rejects keyed requests — roughly one keyed search in three in this machine's own record, with the rejection generated at the CDN edge and independent of the `User-Agent`, query, or spacing. Arms compared on this provider must therefore record **attempted and delivered** provider calls separately. Otherwise an arm that happened to run in a bad window is scored as if it had searched a smaller corpus, and the equal-budget condition that the whole comparison rests on is silently violated.

## 8. Not claimed

No implementation exists. The OpenAlex loose-form boundary is untested (four unquoted words worked in a probe, six collapsed to four works in the rules' own probe, the span between them is unknown). Semantic Scholar and Crossref **operator** behaviour is taken from the local rules file, not verified against the live API; what was re-probed on 2026-09-18 for Semantic Scholar is transport behaviour only (the key is honoured, no rate-limit headers are sent, and the intermittent 429 is edge-generated — scan doc section 4a.1), which says nothing about how it interprets quotes or multiword phrases. The claim that the core phrase's vocabulary — rather than the query count, provider mix, or screening — caused the recorded one-of-six is a hypothesis with a supporting trace, not an established cause. Nothing here is an executed scientific review, a statement about Elicit's internals, a completeness claim about the literature, or a claim that citations are semantically correct.
