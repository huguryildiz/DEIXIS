# Elicit–Consensus–DEIXIS comparison: first result

**Date:** 2026-09-17. **Status:** isolated exploratory comparison; not a
scientific review, field-recall estimate, or product-superiority claim.

## Result at a glance

The same algae-specific OR question was submitted to the current DEIXIS search
planner in an isolated run. The planner used `gpt-5.6-luna` at medium effort and
the current query compiler. Eight provider requests were compiled:

| Provider | Requests | Requested depth | Returned | Status | Known controls found |
|---|---:|---:|---:|---|---:|
| OpenAlex | 3 | 100, 25, 25 | 0 | HTTP 200, zero results | 0/7 |
| Semantic Scholar | 1 | 25 | 25 | completed | 0/7 |
| Crossref | 1 | 25 | 25 | completed | 0/7 |
| arXiv | 1 | 25 | 0 | HTTP 406, failed | 0/7 |
| bioRxiv | 1 | 25 | 0 | HTTP 200, zero results | 0/7 |
| PubMed | 1 | 25 | 0 | HTTP 200, zero results | 0/7 |
| **Total** | **8** |  | **50** |  | **0/7** |

The seven controls were DOI-identified papers cited in, or central to, the two
external reports. They are an incomplete known-work set, not a gold standard.
The 50 returned records were unique by DOI in this run. The full raw payloads,
queries, statuses, and hashes are retained in the ignored run directory:
`.local/elicit-consensus-deixis-comparison-2026-09-17-v2/`.

## Comparison with the external reports

The [Elicit report](../../../../algae-meeting-deck/reports/external_ai/2026-09-14-elicit-evidence-gated-gap-assessment.md)
and [Consensus report](../../../../algae-meeting-deck/reports/external_ai/2026-09-14-consensus-algae-or-research-gap.md)
each produced a structured research-gap argument with an evidence matrix,
candidate gaps, an LP/MIP admission decision, and calibration conditions. Their
reported source lists are not independent ground truth and were not produced
under the DEIXIS request budget or provider configuration.

DEIXIS did not retrieve any of the seven selected controls under its current
plan. The returned Semantic Scholar titles were predominantly general molecular-
communication channel/model papers; the returned Crossref titles were mostly
general signalling or controllability papers, with some potentially relevant
algal records. This is consistent with a plan whose core vocabulary was too
specific and whose paired queries added several constraints simultaneously.

The first DEIXIS result therefore does **not** establish that Elicit or Consensus
has better retrieval. It establishes a reproducible failure mode in the current
DEIXIS search plan for this question: the plan generated no OpenAlex/PubMed
algae results and did not recover the selected report references through the
other two providers.

## Evidence and answer-level comparison still pending

This run compares discovery only. It did not run PDF acquisition, passage
inspection, report generation, or citation-anchor validation. A proper second
stage must separately compare the two external report claims against DEIXIS
passages, preserving demonstrated, modelled, proposed, inferred, and unresolved
statuses. It must also use a bounded short-query rescue experiment or a revised
SearchPlan under a newly frozen protocol; the rescue must not overwrite this
baseline.

No live service was restarted, no application library was changed, and nothing
was committed, pushed, or published.

## Short-query rescue follow-up

A separate frozen diagnostic then sent four short queries to OpenAlex and
Semantic Scholar, 25 records per query per provider. It returned 200 records
before deduplication and 162 records after provider-identity deduplication; 156
had unique DOI values.

| Provider | Returned | Known controls | Report DOI overlap |
|---|---:|---:|---:|
| OpenAlex | 100 | 1/7 | 1 |
| Semantic Scholar | 100 | 3/7 | 4 |
| Union | 200 (162 deduplicated) | **3/7** | **5** |

The five exact DOI overlaps with the external reports were:

- *Algae Communication* (2025);
- *The Internet of Algae* (2026);
- *Algal volatiles* (2022);
- *Communication mediated interaction between bacteria and microalgae* (2024);
- *Indole-3-acetic acid as a cross-talking molecule* (2023).

This is a useful retrieval diagnostic: short queries recovered the two central
algae-communication papers and the algal-volatiles review that the generated
baseline missed. It also increased the candidate workload substantially and did
not recover four of seven controls. No title/abstract relevance review or PDF
passage validation was performed, so the result supports a query-recall
hypothesis, not a validated search-policy change.

The rescue protocol and raw results are in
`.local/elicit-consensus-deixis-short-query-rescue-2026-09-17/`.
