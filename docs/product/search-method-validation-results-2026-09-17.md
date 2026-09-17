# Compact two-provider search: validation result

**Outcome:** the frozen candidate failed its practical screening threshold on six previously unused LitSearch questions. The OpenAlex plus Semantic Scholar union found at least one exact-DOI gold work in 2/6 questions and 4/12 gold works. Semantic Scholar supplied no gold work beyond OpenAlex. The required thresholds were at least 5/6 questions and an additional work from Semantic Scholar in at least two questions.

The protocol and case file were frozen before this run: `search-method-validation-2026-09-17.md` and `scripts/search_method_validation_cases_2026-09-17.json`. The isolated runner is `scripts/search_method_validation.py`. Raw model outputs, provider responses, exact compiled queries, status/retry metadata, hashes, and blinded review records are in ignored `.local/search-method-validation-2026-09-17/`. The manifest hashes the protocol, cases, runner, and source revision. All six planning calls completed with requested `gpt-5.6-luna` medium identity and no tool items. All twelve provider requests completed, with one Semantic Scholar request retry. Each provider returned 100 records per question.

| LitSearch index | OpenAlex gold | Semantic Scholar gold | Union gold | OpenAlex query | Semantic Scholar query |
| --- | ---: | ---: | ---: | --- | --- |
| 3 | 0/2 | 0/2 | 0/2 | `("Arabic morphological analysis" OR "Arabic morphological analyzer")` | `Arabic morphological analysis dialects` |
| 26 | 2/2 | 1/2 | 2/2 | `("stance detection" OR "Twitter stance")` | `stance detection target-specific` |
| 42 | 2/2 | 0/2 | 2/2 | `("computational humor" OR "humor recognition")` | `computational humor repetition` |
| 53 | 0/2 | 0/2 | 0/2 | `("language modeling" OR "CCG supertagging")` | `language modeling LSTM` |
| 63 | 0/2 | 0/2 | 0/2 | `("beam search" OR "neural machine translation")` | `beam search lookahead decoding` |
| 102 | 0/2 | 0/2 | 0/2 | `("few-shot learning" OR "intent classification")` | `few-shot learning example-based` |

Across the first ten records per provider per question, a separate blinded title/abstract model labeled 9/60 OpenAlex and 18/60 Semantic Scholar records clearly relevant, 9/60 and 16/60 uncertain, and 42/60 and 26/60 off-topic. These are provisional model judgments rather than human precision labels. The gold set is incomplete by design, so failure to recover one listed DOI does not establish that all returned papers are irrelevant. Conversely, provider result totals do not establish recall.

The prior six-question development result of 6/6 for this candidate did not replicate. Both slices are manually selected ML/NLP questions. No engineering-domain or user-relevance validation has been done. This result does not justify changing the live DEIXIS retrieval policy. No live service was restarted and no repository product code was changed.

After scoring, a separate exact-DOI OpenAlex lookup found all 12 gold works indexed (12/12 HTTP 200 with matching returned DOI). This diagnostic is in `doi-diagnostic.json` (SHA-256 `2c66ad82e1c762fb46020674984adbb5a0d39b11e7bcc50ca886801feeff16a9`). It supports a query/ranking explanation for OpenAlex misses rather than missing index coverage; it was not part of the candidate's retrieval budget.
