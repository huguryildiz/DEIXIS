# DEIXIS short-query rescue protocol

**Status:** frozen before provider responses. **Date:** 2026-09-17.

This is a bounded follow-up to the first Elicit–Consensus–DEIXIS comparison. It
tests whether short, diverse literal queries recover the seven DOI controls
missed by the current generated plan. It is a diagnostic, not a product-policy
change and not a comparison of vendor quality.

## Frozen queries

The same four queries are sent to OpenAlex and Semantic Scholar, at 25 records
per query per provider:

1. `algae communication`
2. `algal signalling`
3. `molecular communication algae`
4. `algae resource allocation`

The total request count is eight and the maximum returned-record budget is 200.
No model-generated query, result-informed adaptation, fallback, or query editing
is allowed.

## Scoring

Score exact DOI matches against the seven controls in
`scripts/elicit_consensus_deixis_comparison_cases_2026-09-17.json`. Report each
provider separately and as a union. The controls are incomplete known works;
they are not a gold standard or a recall denominator. Also report returned and
unique counts, statuses, raw payload hashes, and query-level results.
