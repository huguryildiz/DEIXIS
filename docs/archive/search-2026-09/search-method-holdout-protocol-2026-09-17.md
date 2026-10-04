# Search method: external-question comparison

**Status:** frozen before any OpenAlex response or model query-plan proposal for these six questions. **Date:** 2026-09-17. This is an isolated retrieval experiment, not a DEIXIS product run or a claim of scientific completeness.

## Independent questions and target works

The six question texts and 17 gold work identities in `scripts/search_method_cases_2026-09-17.json` come from the [Princeton LitSearch query data](https://huggingface.co/datasets/princeton-nlp/LitSearch), indices 12, 18, 65, 96, 156, and 335. These are quality-2 questions with at least two gold works and different NLP/ML topics. This manual selection is not a random sample. Before this experiment's OpenAlex queries, Semantic Scholar's paper batch endpoint resolved each LitSearch CorpusId to the saved title and DOI. The gold entries are never shown to a query-planning or screening model. LitSearch is an independent benchmark, but its target lists are incomplete and its field is narrower than DEIXIS's intended coverage.

## Fixed search budget and arms

The question is the unit of comparison. For each question, one `gpt-5.6-luna` medium call proposes exactly one core vocabulary concept and 2-5 separate concept families from the question alone, using the same concept rules as DEIXIS's search method. The model never writes provider syntax. The existing query compiler generates the first core-only OpenAlex query and the first paired OpenAlex query from a fixed provider order: OpenAlex, Semantic Scholar, Crossref, arXiv; maximum eight compiled queries. This isolates OpenAlex query construction, not the full multi-provider DEIXIS workflow.

All arms share the same first OpenAlex `search.title_and_abstract` response, requested depth 100. Each then has exactly one second OpenAlex request, depth 25:

| Arm | Second query |
| --- | --- |
| A | First OpenAlex paired query in the compiler's full four-provider order. |
| B | One alternative proposed from the question and frozen concept plan without first-result feedback. |
| C | One alternative proposed from those inputs plus up to 100 first-result titles and 260-character abstract snippets. |

B and C each get one `gpt-5.6-luna` medium proposal call under the same schema and compiler. B is generated before the first provider response; C afterward. Neither sees gold titles/DOIs, scoring, or the other's proposal. Duplicate, invalid, failed, or wrong-model proposals stay invalid; no fallback or extra attempt is substituted. The first provider response is shared once, and the second requests run in a seeded random order. Request status, retries, returned versus distinct works, payload hashes, model identity, effort, tokens, and elapsed time are recorded. The live DEIXIS library and port 8765 are untouched.

## Outcomes and decision rule

The primary measure is, per question and arm, the number of LitSearch gold works found by exact DOI in the first-plus-second response. This is known-target coverage, not recall over all relevant literature. Report both absolute coverage and the second request's incremental hits. The first request's same result means a second arm cannot lose a first-query gold hit; compare second-arm differences directly.

As a secondary precision signal, mask arm and query origin, mix the distinct top-ten second-response records for each question, and assess their titles and available abstracts against the question as `clear_relevance`, `uncertain`, or `off_topic`. A separate tool-free model call can produce provisional labels; these are model assessments, not human ground truth. Report missing abstracts and disagreement or ambiguity, and do not use these labels to claim scientific relevance has been validated.

Prefer the simpler B query for a product prototype unless C adds at least two more gold works than B across at least two distinct questions, never loses a gold work relative to B in a question, and has no material drop in the provisional clear-relevance share. A candidate method counts as promising only if it retrieves at least one gold work in at least four of the six questions and its second queries add gold works in at least two questions. Six questions cannot establish a statistical guarantee. If none meets that bar, report the failure and diagnose query vocabulary or provider ranking before a product change. These thresholds are fixed before the OpenAlex run.
