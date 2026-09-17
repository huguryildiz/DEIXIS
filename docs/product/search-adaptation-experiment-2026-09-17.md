# Search adaptation: bounded development experiment

**Status:** frozen development protocol, before the new A/B/C searches. **Date:** 2026-09-17. This experiment does not change DEIXIS search behavior or establish literature completeness.

## Question and units

Does a second OpenAlex query chosen after inspecting the first results find more relevant known works than either the current paired query or an alternative chosen before seeing results? The unit is a research question. Repeated model proposals for one question are variability checks, not independent questions.

The development questions are the frozen Kurt packet-size, underwater k-connectivity, and IRS/RIS questions under `scripts/p4_eval/sets/`. Their known-work lists were previously used to design or assess search changes; none is a holdout. The frozen SearchPlan for each question is the `deep` run in ignored `.local/depth-measure-2026-09-17/data-deep/library.sqlite`. The target/tutorial paper is excluded from its own known-work denominator. The lists never enter a model prompt.

## Paired arms

For each question, all arms share the *same* compiled OpenAlex core-only query and its first 100 returned records. Each then gets one OpenAlex request limited to 25 results:

| Arm | Second query |
| --- | --- |
| A, current | First OpenAlex core-plus-family query in the frozen plan. |
| B, static diversity | One alternative query proposed from the question and frozen plan before results are seen. |
| C, adaptive | One alternative query proposed from the same inputs plus the first query's returned titles and abstract snippets. |

B and C use the same requested model and effort (`gpt-5.6-luna`, `medium`), one model call each. The model proposes concept terms and a rationale; the existing OpenAlex compiler and syntax checks produce or reject the literal query. All three arms have the same provider, two search requests, and requested result depths (100 plus 25). Actual retries, failures, model tokens, elapsed time, and distinct provider records are reported, rather than called equal cost. No fallback provider or model is substituted.

The first request is made once and shared. The A, B, and C second requests are sent in a seeded randomized order to reduce temporal ranking drift. Exact response payloads and hashes are saved outside Git. The first 100 records, not the known-work list or arm scores, are the only search feedback available to C. Retrieved paper text is treated as data, never as instructions. B and C proposals are generated before their second requests or any scoring.

## Measures and boundaries

The primary development measure is the number of distinct known works retrieved by each arm before model screening, by the existing strata. This is *known-work coverage*, not exhaustive recall. DOI aliases match one work; title-only entries need a conservative manual identity check before a disputed gain is credited. Secondary measures are distinct works, each second query's incremental known works, request status and retries, model usage, and elapsed time. Provider-reported match totals are not evidence of retrieval or relevance. A returned work can be off-topic; this pilot does not establish candidate precision without a separate blinded title/abstract assessment.

A model output, a zero-result request, or a provider failure never silently triggers another request. A failed or invalid arm is reported as such. The three existing questions can diagnose failure modes and decide whether a larger test is worth doing. They cannot approve a product change. If B or C shows a credible gain, freeze a separate protocol and at least six new questions with independently assembled, versioned known-work sets and blinded relevance labels before running a holdout comparison. The holdout must include narrow and popular multi-part questions. The B-versus-C criterion and acceptable precision, latency, and cost limits must be set before those holdout responses are collected. Citation chaining and provider selection are separate experiments.

## Safety and provenance

Run the probe outside the application library. Do not connect to or restart port 8765. Store runtime payloads and model outputs in ignored `.local/search-adaptation-2026-09-17-v2/`, with source revision, protocol hash, model request and resolved identities, exact query and limit, provider status, raw-response hash, and scorer version. Do not print or store API keys. No code, model package, or result from this pilot becomes an accepted product decision merely because the probe completes.

## Correction before the scored run

The first execution wrote `.local/search-adaptation-2026-09-17/`. Its A query was mistakenly selected by recompiling the frozen plan with only OpenAlex enabled. That changes round-robin query order and is not the first OpenAlex paired query in the original full-provider plan. Therefore its A/B/C comparison is an invalid dry run; its outputs remain intact for audit and are not used for the conclusion. The scored run in `-v2/` selects the first OpenAlex paired query from the original eight-query compilation with the frozen enabled-provider list. All model proposals and provider responses are generated again. This correction was recorded before the scored run began.
