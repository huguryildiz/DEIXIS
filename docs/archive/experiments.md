# Retired experiment scripts

Stage C, 2026-10-04. These 12 runners and three associated fixtures had no
references from tests, `pyproject.toml`, living documentation, backend code, or
scripts retained after dependency tracing. Self-references and references within
an otherwise unused experiment group do not keep that group alive. All files
listed below are recoverable from Git revision
`04ea934a34cba3b035e2292b13dc0f5b118365f0` with
`git show <revision>:<path>`.

Results below are historical reports in tracked documentation, not measurements
repeated during cleanup. Private run payloads were not inspected. `bilinmiyor`
means the inspected repository records did not establish the outcome or a
direct decision association. Contextual decision links do not mean an
experiment's policy was adopted. Existing archived protocols retain historical
script names; those names do not identify currently executable files.

## `scripts/arxiv_source_report.py`

Tried the product's arXiv LaTeX matching and extraction on a read-only library
copy, checked migrations and passage identity, and compared placements with
stored Marker readings. [D104](../decisions.md#d104--an-arxiv-pdf-read-without-marker-takes-its-numbered-display-equations-from-the-authors-latex-source-matched-to-the-page-by-their-numbers-behind-a-flag-that-is-off)
records the acceptance measurements and subsequent review corrections: the
initial product measurement placed 787 blocks; after rounds 9–12 it placed
776 on 221 pages of 42 versions with no KaTeX errors. These are successive
measurements, not an accuracy estimate; Marker was a reference, not ground
truth. D104 accepted the route behind a flag that defaults to off.

## `scripts/elicit_consensus_deixis_comparison.py`

Tried the frozen algae question with a tool-free vocabulary model and the
existing provider compiler, scoring seven known DOI controls.
The [result](search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md)
reports eight provider requests, 50 unique returned records and 0/7 controls;
arXiv failed with HTTP 406. This was discovery only, with unequal external
vendor budgets and no passage validation. Direct decision: bilinmiyor.
[D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is later compact-query context, not adoption of this comparison.

## `scripts/elicit_consensus_deixis_short_query_rescue.py`

Tried four fixed short algae queries on OpenAlex and Semantic Scholar, with
25 records per query per provider. The comparison's
[follow-up result](search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md#short-query-rescue-follow-up)
reports 200 returned records, 162 after provider-identity deduplication, 156
unique DOI values, and 3/7 known controls in the union. No relevance or passage
review was performed. Direct decision: bilinmiyor; [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is related query-policy context only.

## `scripts/elicit_consensus_deixis_comparison_cases_2026-09-17.json`

Fixture for the preceding two runners: the algae question and seven DOI/title
controls. It is an incomplete known-work set, not an independent relevance
standard. Results belong to those runners (0/7 baseline, 3/7 rescue).
Direct decision: bilinmiyor; related context is [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search).

## `scripts/evaluate_isolated_query_branches.py`

Tried post-run exact DOI and normalized-title diagnostics for frozen and hybrid
quantum query arms. It required a completed 20-call ledger, six prior controls
and nine Elicit CSV rows, and reported overlap and incremental records.
Execution result: bilinmiyor. Direct decision link: bilinmiyor. The retained
[query-branch protocol](../methods/quantum-query-branches-isolated-2026-09-18.md)
provides experiment context without establishing this evaluator's outcome.

## `scripts/isolated_survey_search.py`

Tried a separate quantum survey lane: three fixed OpenAlex queries, two pages
per query, at most 600 returned slots. Title words supplied provisional genre
signals, and the known survey DOI was checked after retrieval.
Execution result: bilinmiyor. Direct decision: bilinmiyor.
The [auxiliary protocol](../methods/quantum-auxiliary-search-isolated-2026-09-18.md)
states the limits; [D77](../decisions.md#d77--flag-surveys-by-title-abstract-and-reference-count-ask-a-second-source-for-a-missing-abstract-by-doi-and-let-an-external-link-confirm-or-block-a-merge)
is related product survey-routing context, not a result of this runner.

## `scripts/probes/time_link_records.py`

Tried offline timing of paged `record_search` and its `link_records` component
in a temporary library, using real saved titles when available or seeded
synthetic records otherwise. [D75](../decisions.md#d75--read-an-sw-query-page-by-page-up-to-one-named-read-limit-and-count-what-was-not-read)
reports 1,500 candidates in eight pages: slowest whole page 0.75 s, its linking
component 0.25 s, total 4.03 s. The under-one-second page result led to no
linking change. Which title input was used in that reported run: bilinmiyor.
Live-provider pagination was not tested by this probe.

## `scripts/search_adaptation_probe.py`

Tried existing paired queries, static vocabulary diversification, and
result-informed vocabulary diversification after the same first 100 OpenAlex
records on three engineering development questions.
The [result](search-2026-09/search-adaptation-development-results-2026-09-17.md)
reports no gain on packet size; static diversification added one known DOI on
k-connectivity and adaptation added one on IRS/RIS. It found no consistent
adaptation advantage and did not justify a product change. The first run was
invalid; the documented counts belong to the corrected v2 run.
Direct decision: bilinmiyor; [D60](../decisions.md#d60--read-openalexs-core-only-query-100-results-deep-on-one-popular-topic-question-a-narrow-core-phrase-kept-it-from-helping)
records the preceding core-depth policy that supplied the baseline.

## `scripts/search_method_holdout.py`

Tried static and adaptive vocabulary arms on six external LitSearch questions,
with exact DOI scoring and provisional blinded title/abstract model judgments.
The subsequent [compact-development protocol](search-2026-09/search-compact-development-2026-09-17.md)
reports that the preceding comparison found two of 17 gold works across its
best arms, while exact DOI lookups found all 17 in OpenAlex. The questions then
became development data. Direct decision: bilinmiyor; [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is later compact-query context only.

## `scripts/search_compact_development.py`

Tried short canonical core and facet vocabulary on the six already-used
LitSearch questions, reading OpenAlex core top 100 and paired top 25.
Its [protocol](search-2026-09/search-compact-development-2026-09-17.md)
predeclares coverage and incremental-gain thresholds but does not report this
runner's scored outcome: bilinmiyor. The later two-provider candidate must not
be treated as this OpenAlex-only runner's result. Direct decision: bilinmiyor;
[D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
describes a separate compiler diagnostic, not this model-vocabulary experiment.

## `scripts/search_provider_complement.py`

Tried adding one Semantic Scholar top-100 query to the saved compact OpenAlex
top-100 response, without new model calls. Its
[protocol](search-2026-09/search-provider-complement-development-2026-09-17.md)
states that the provider budgets differ and the six questions are development
data. This runner's scored outcome: bilinmiyor. Direct decision: bilinmiyor;
[D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is related query-policy context only.

## `scripts/search_method_cases_2026-09-17.json`

Fixture for the holdout, compact-development and provider-complement runners:
six LitSearch questions and 17 DOI/CorpusId/title controls. The holdout result
above reports two of 17 across its best arms; subsequent reuse made this a
development set. Direct decision: bilinmiyor; related context is
[D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search).

## `scripts/search_method_validation.py`

Tried the frozen compact OpenAlex plus Semantic Scholar candidate on six
previously unused LitSearch questions. The
[result](search-2026-09/search-method-validation-results-2026-09-17.md)
reports 4/12 gold works in 2/6 questions and no incremental gold from Semantic
Scholar. It failed the required 5/6 question coverage and additional-work gains
in two questions. All 12 gold DOIs were later found by exact lookup; the
diagnostic was outside the retrieval budget. The model relevance labels remain
provisional. Direct decision: bilinmiyor; [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is related context, not adoption of this failed candidate.

## `scripts/search_diverse_query_development.py`

Tried four Semantic Scholar top-25 queries against one saved top-100 query on
the now-reused validation questions. The
[result](search-2026-09/search-diverse-query-development-results-2026-09-17.md)
reports gold coverage rising from one to four works over five completed
questions. A sixth proposal containing `GPT 2` was rejected by the numeric-token
validator, so the full frozen condition could not be declared passed. Query
diversity and number of ranking lists changed together; no human precision
measurement was made. Direct decision: bilinmiyor; [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search)
is related context only.

## `scripts/search_method_validation_cases_2026-09-17.json`

Fixture for the validation and diverse-query runners: six new LitSearch
questions with two DOI/CorpusId/title controls each. The validation recovered
4/12 works; the subsequent diverse-query development reused these questions
and had one invalid case, as recorded above. Direct decision: bilinmiyor;
related context is [D64](../decisions.md#d64--add-an-opt-in-compact-openalex-query-strategy-retain-the-measured-deep-core-search).
