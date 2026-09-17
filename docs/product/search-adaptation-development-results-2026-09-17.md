# Search adaptation: three-question development result

**Status:** exploratory development evidence, not a product decision. The scored run is in ignored `.local/search-adaptation-2026-09-17-v2/`; the earlier `.local/search-adaptation-2026-09-17/` run is invalid because its A query came from an OpenAlex-only recompile. The [frozen protocol](search-adaptation-experiment-2026-09-17.md) records that correction. The scored run's manifest hashes the protocol, script, frozen plan database, and source revision; the saved protocol and script hashes still match.

## Result

All arms shared the same first OpenAlex title-and-abstract query and its first 100 records for each question. A used the first OpenAlex paired query in the original eight-query, full-provider compilation. B used a `gpt-5.6-luna` medium proposal made before first results; C used the same model and effort after seeing 100 titles and truncated abstract snippets. Each arm made one further OpenAlex request for at most 25 records. Counts below are distinct known works with exact DOI matches in the union of the first and second requests; the self/tutorial paper is excluded.

| Development question | Known works | First 100 | A: current pair | B: static diversity | C: adaptive |
| --- | ---: | ---: | ---: | ---: | ---: |
| S1a, packet size | 17 | 11 | 11 | 11 | 11 |
| S2, k-connectivity | 22 | 7 | 7 | **8** | 7 |
| S3, IRS/RIS | 31 | 2 | 2 | 2 | **3** |

S2 B added DOI `10.1109/tpds.2014.2316142`, *A Distributed Fault-Tolerant Topology Control Algorithm for Heterogeneous Wireless Sensor Networks*, at rank 3 of its second response. S3 C added DOI `10.1109/icc40277.2020.9149146`, *Broadband Channel Estimation for Intelligent Reflecting Surface Aided mmWave Massive MIMO Systems*, at rank 7. Both are in the pre-existing question-specific known lists. An independent count directly from saved provider payload DOIs matched all nine scored arm counts. There were no title-only candidate matches in this run.

The first query returned 100 records in every case. The A/B/C second requests returned, respectively, 0/25/4 records for S1a, 8/25/25 for S2, and 25/25/25 for S3. In S3, A's 25 records added no distinct work to the first 100. No provider request retried or failed; S1a A was a valid zero-result response. All six model proposals completed with resolved model `gpt-5.6-luna`, no tool items, and a valid distinct compiled query. The isolated model home reported no loaded instruction files or live MCP servers.

B used 7,864 total model tokens across three calls; C used 30,101 because it received the first-result snippets. Recorded model call time was 36.31 seconds for B and 35.41 seconds for C across the three questions. These are observed timings, not a stable latency estimate or a monetary cost comparison. Raw OpenAlex responses, hashes, exact queries, statuses, rate-limit headers, model outputs, and usage are in the ignored run directory. No application library or live service was used.

## Interpretation and next experiment

This run shows one known-work gain from static vocabulary diversification and one from result-informed vocabulary diversification, on different questions. It does not show a consistent advantage for adaptation. The current paired OpenAlex queries supplied no incremental known DOI in these three questions, but unknown works have not been relevance-labeled. In particular, a new record is not automatically a relevant record.

The known lists are incomplete and were used in earlier design work; they are not a holdout. One model proposal per arm cannot estimate proposal variability. OpenAlex ranking and corpus can change over time. DOI coverage misses records without a matching DOI, and known-work coverage is not exhaustive recall or precision. The S2 known list includes adjacent underwater context entries that are not presumed relevant positives, so the total column is a reference-list denominator, not a clean relevance denominator.

The next bounded test should compare several static query variants with the adaptive second query on new questions, using independent known works and blinded relevance labels for returned titles/abstracts. Freeze the queries, budgets, acceptance threshold, and labels before collecting responses. This pilot does not justify changing DEIXIS search behavior yet.
