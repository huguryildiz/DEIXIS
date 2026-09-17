# Diverse short queries: development result

**Outcome:** four short Semantic Scholar queries found exact-DOI gold works in two questions where the saved single query found none, with the same maximum of 100 returned records per question. This is a promising development signal, not a validated DEIXIS search policy. One of six model proposals was rejected by the frozen validator and received no provider calls.

The frozen protocol is `search-diverse-query-development-2026-09-17.md`; the isolated runner is `scripts/search_diverse_query_development.py`. The questions were already used in the preceding validation, so this comparison reuses development data. Raw model outputs, the 20 provider payloads, request metadata, payload hashes, and exact-DOI scores are in ignored `.local/search-diverse-query-development-2026-09-17/`. All five valid proposals used the requested `gpt-5.6-luna` medium without tools; all 20 Semantic Scholar requests completed. The model saw only each question, never its gold list or saved search results.

| LitSearch index | Saved single query, top 100 | Four queries, top 25 each | Diverse unique DOIs | Interpretation |
| --- | ---: | ---: | ---: | --- |
| 3 | 0/2 | 0/2 | 82 | No gold recovered |
| 26 | 1/2 | 2/2 | 87 | One additional gold |
| 42 | 0/2 | Not run | — | Model emitted `GPT 2`; validator rejected the numeric token |
| 53 | 0/2 | 1/2 | 79 | One additional gold, at rank 24 of query 3 |
| 63 | 0/2 | 1/2 | 94 | One additional gold, at rank 8 of query 1 |
| 102 | 0/2 | 0/2 | 91 | No gold recovered |

On the five completed questions, exact-gold coverage rose from 1 to 4 works and from 1/5 to 3/5 questions. The predeclared promising condition required a gain in two previously missed questions and no regression in both baseline-hit questions. Gains occurred in indices 53 and 63, but index 42 was not run, so the full condition cannot be declared passed. The validator's blanket alphabetic-token rule rejected a plausible academic term (`GPT 2`); future probes should accept alphanumeric scientific terms under a newly frozen protocol. Do not reinterpret this invalid case as a retrieval failure.

This experiment varies query diversity and the number of provider ranking lists at the same maximum returned-record budget. It does not isolate which factor caused the gains, and it does not measure human relevance precision. Gold works are an incomplete benchmark of relevance. A later comparison should use new questions, equal provider budgets, alphanumeric-safe validation, and manual top-result review, including engineering literature. No DEIXIS product code or live service was changed.
