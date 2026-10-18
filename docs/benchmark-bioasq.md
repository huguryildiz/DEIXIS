# BioASQ search benchmark

The 18 Oct re-run with the owner's settings (Voyage embedding and reranker) is in [`benchmark.md`](benchmark.md); this page is the 17 Oct run and the method.

Run on 2026-10-17 at commit `0b09c904`. This adapts Elicit's paper-search evaluation
([Evaluating Elicit's paper search](https://elicit.com/blog/evaluating-elicit-paper-search)) to DEIXIS, using 100 of
its 5,486 questions.

## Result

Recall@k is the share of a question's expert-chosen papers found in the first k results, averaged over questions
(macro-recall). The 95% intervals come from 10,000 bootstrap resamples of questions.

| System | @10 | @20 | @50 | @100 | Questions |
|---|---|---|---|---|---|
| DEIXIS, Standard | **0.352** | **0.423** | **0.545** | **0.635** | 100 |
| 95% interval | 0.28–0.42 | 0.35–0.49 | 0.47–0.62 | 0.57–0.70 | |
| OpenAlex keyword | 0.281 | 0.364 | 0.489 | 0.607 | 99 of 100 |
| DEIXIS − OpenAlex | **+0.073** | +0.063 | +0.061 | +0.034 | 100, paired |
| 95% interval | +0.02 to +0.13 | −0.00 to +0.13 | −0.00 to +0.13 | −0.02 to +0.09 | |
| Elicit, as published | 0.390 | 0.483 | 0.603 | 0.670 | 5,486 |

DEIXIS finds more of the expert papers than a plain OpenAlex keyword search on the same questions at every depth. The
gap is clear at 10 results. At 20 and 50 the interval just touches zero, and at 100 there is no measurable
difference.

DEIXIS's numbers are below Elicit's published ones at every depth. Elicit's figures fall
inside DEIXIS's 95% intervals at every depth, so 100 questions can't tell the two systems apart. Elicit's figures come
from all 5,486 questions and ours from a sample, so this is not a paired comparison.

Our OpenAlex baseline gives 0.489 at 50 results. Elicit's gives 0.474 on the full set. The two are close, which
suggests the harness scores the way Elicit's does.

## Where DEIXIS lost papers

The 100 questions have 1,098 expert papers. Each one was traced through DEIXIS's frozen candidate list for that
question:

| Where the paper ended up | Papers | Share |
|---|---|---|
| In the first 100 | 561 | 51% |
| In the list, below position 100 | 237 | 22% |
| Never in the list | 300 | 27% |
| Dropped by the year cut | 0 | 0% |

The loss splits between ranking and search. About a fifth of the expert papers were in the list but below position
100, and the search queries DEIXIS writes never brought in about a quarter of them. All 1,096 distinct gold papers are indexed in OpenAlex (checked by PMID), so the loss is not a
coverage gap. The median candidate list held 1,008 works.

## Method

**Questions.** The 2b–13b golden enriched test sets of BioASQ Task B (2014–2025) hold 5,486 questions, the same count
Elicit reports. Each question's gold set is its expert `documents` list, with a mean of 11.0 papers and a median of 7.
A fixed seed (`20261017`) draws 100 questions. The same seed with a larger n keeps these 100 and adds more.

**DEIXIS.** Each question goes to an isolated DEIXIS server (temporary data directory, not the owner's library) as a
new research. The settings are Standard depth, model `claude-sonnet-5-5` at medium reasoning effort, review off and
`gemini-embedding-2` for semantic similarity. DEIXIS writes its own queries; the question is passed as a user would
type it. The run is cancelled once the small-batch candidate list (`small_batch:v1:list`) is frozen, so reading and
answering are not measured. The fast path searches OpenAlex only (semantic and keyword search, then citation
chaining). The median question took 74 seconds.

**OpenAlex keyword.** `claude-sonnet-5-5` at medium effort writes one OpenAlex boolean query per question. The first
200 results are read with `to_publication_date` set to the end of the question's challenge year. OpenAlex rejected
three queries. Following Elicit's method, each one got a single model repair: two passed and one failed again. That
question is scored as a failure.

**Matching and scoring.** Results are matched to gold papers by PMID, then DOI, then normalized title. Gold DOIs and
titles come from PubMed. DEIXIS keeps no PMID, so the harness reads OpenAlex's `ids.pmid` from the stored raw provider
payload. Recall is computed per question, then averaged. In the paired comparison a failed question counts as zero.

**Year cut.** Elicit filtered by date inside each API call. DEIXIS has no date filter, so records published after
the question's challenge year are removed from its list afterwards, and positions shift up. Newer papers could still
have taken search slots that older ones would have filled, so this works slightly against DEIXIS. In this sample it
removed no gold paper.

## Differences from Elicit's evaluation

- 100 questions instead of 5,486, so the intervals are wider.
- No Consensus, Semantic Scholar, OpenAlex semantic or Google Scholar runs.
- DEIXIS is scored with its own query writing, chaining and ranking, as a user would get it. It is not given a
  prepared query.
- Elicit's second evaluation (LLM-judged pairs from real user searches) was not repeated. DEIXIS has no shared search
  log to sample from.

## Incident during the run

Gemini prepaid credits ran out partway through the first pass. DEIXIS recorded the failed `source_similarity` step and
ranked 34 questions without semantic similarity. Those 34 were set aside, the credits were topped up and the 34 were
rerun with the same settings. The table uses only runs where the embedding step succeeded. The harness now refuses to
score any run whose `source_similarity` step failed.

## Limits

- BioASQ is biomedical only. The result says nothing direct about engineering questions such as the DBR/VBF set.
- Gold sets are not exhaustive. Recall measures how many expert-chosen papers were found, not how many relevant papers
  exist.
- This is one run of each system. Model query writing varies between runs, and that variance was not measured.
- Standard-depth stage deadlines bound search time, so recall also depends on provider speed during the run.
- A passing benchmark is not scientific validation of the answers DEIXIS writes. Only the candidate list is measured.

## Reproduce

The BioASQ files need a free account at participants-area.bioasq.org (CC BY 2.5). Put the 2b–13b golden enriched
zips, unpacked, under `.local/bioasq/raw/`, then:

```sh
uv run python scripts/benchmark/bioasq_run.py prepare --n 100
uv run python scripts/benchmark/bioasq_run.py openalex
uv run python scripts/benchmark/bioasq_run.py openalex-repair
DEIXIS_DATA_DIR=$PWD/.local/bioasq/deixis-data uv run python -m deixis serve --no-browser --port 8873
uv run python scripts/benchmark/bioasq_run.py deixis --base http://127.0.0.1:8873 --data-dir .local/bioasq/deixis-data
uv run python scripts/benchmark/bioasq_run.py score
uv run python scripts/benchmark/bioasq_run.py loss --data-dir .local/bioasq/deixis-data
```

Scoring code: `scripts/benchmark/bioasq.py`, tested by `tests/measurement/test_bioasq_recall.py`.
