# Compact two-provider search: external-question validation

**Status:** frozen before model plans or OpenAlex/Semantic Scholar searches for these six questions. The previous six LitSearch questions are development data. This is a fresh, manually selected LitSearch slice, not a random or cross-domain sample.

The six quality-2 questions and 12 gold CorpusIds/DOIs in `scripts/search_method_validation_cases_2026-09-17.json` are LitSearch indices 3, 26, 42, 53, 63, and 102. They have two gold works each, all with DOI metadata independently resolved from Semantic Scholar before this run; none is a prior development question or prior gold work. The question and gold files are versioned. Gold titles and DOIs never enter a model prompt.

## Frozen candidate

For each question, use exactly one `gpt-5.6-luna` medium, tool-free vocabulary call with the same schema and short-term instruction as `scripts/search_compact_development.py`: 1-2 canonical core phrases and 1-3 facet phrases, each at most three words. Compile with DEIXIS's existing provider rules. Send the core-only OpenAlex title-and-abstract query for up to 100 results and the plain first-core-plus-first-facet Semantic Scholar query for up to 100 results. The two queries are determined before either provider response. No additional synonyms, model calls, fallback providers, or citation chaining are allowed. Record model identity, usage, query strings, result depths, statuses, retries, payload hashes, and elapsed time. No live DEIXIS library or port 8765 is involved.

## Evaluation

The question is the unit. Count exact-DOI gold works in OpenAlex alone, Semantic Scholar alone, and their DOI-deduplicated union. Primary success condition: the union finds at least one gold work in at least five of six questions and Semantic Scholar supplies an additional gold work in at least two questions. Also report the number of gold works found of 12. This condition is a practical screening threshold, not a statistical guarantee or a claim of exhaustive recall.

For a provisional precision check, blind a separate tool-free model to provider origin and ask it to classify the union of each provider's top ten title/abstract records as clearly relevant, uncertain, or off-topic. These are model judgments, not human relevance labels. If gold coverage passes but the top-ten records are mostly off-topic, the method remains unsuitable for a product change. A human review on engineering questions remains necessary before adopting it across fields.
