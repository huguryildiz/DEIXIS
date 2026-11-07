# Search benchmark

Two question sets, run on 2026-10-18 with the owner's settings. Each set has papers chosen by experts or authors for
every question, and the score is how many of them appear near the top of the candidate list. Reading and answers are
not measured.

| Set | Questions | Gold papers per question | Field |
|---|---|---|---|
| **BioASQ** | 100 of 5,486 | about 11 | biomedicine |
| **LitSearch** (Ajith et al., EMNLP 2024) | 200 of 597 | about 1 | ML and NLP |

**In short**

- DEIXIS finds more gold papers than one plain OpenAlex query on both sets.
- The reranker helps on both sets.
- On BioASQ, DEIXIS with the reranker is close to Elicit's published figures
  ([Evaluating Elicit's paper search](https://elicit.com/blog/evaluating-elicit-paper-search)).

![Recall at 10 to 200 results for each set and arm](../assets/benchmark-recall.png)

## Arms and settings

- **A**: one OpenAlex keyword query written by the same model, first 200 results (Elicit's baseline).
- **B**: DEIXIS with the reranker off (the fused order).
- **C**: DEIXIS with the reranker on. B and C come from the same run, so the rerank is the only difference between them.

Settings: Voyage `voyage-4-lite` for semantic similarity, Voyage `rerank-3-lite` for reranking (pool factor 4),
Standard depth, Claude Sonnet 5.5 at medium effort writing the queries. The harness writes these into a temporary data
folder and reads them back before the first question. Every row records them. A provider failure stops the run. It is
never scored as a product result.

Recall@k is the share of a question's gold papers in the first k results, averaged over questions. Intervals are
paired 95% bootstrap intervals over questions (10,000 resamples). A failed question counts as zero in a paired
difference.

![Paired differences at 50 results with 95% intervals](../assets/benchmark-gains.png)

## Results

| | @10 | @20 | @50 | @100 | @200 |
|---|---|---|---|---|---|
| **BioASQ (100)** | | | | | |
| A: plain OpenAlex | 0.281 | 0.364 | 0.489 | 0.607 | 0.674 |
| B: DEIXIS, reranker off | 0.353 | 0.445 | 0.546 | 0.657 | 0.744 |
| C: DEIXIS, reranker on | **0.392** | **0.502** | **0.618** | **0.693** | **0.744** |
| C − B | +0.039 (−0.005 to +0.084) | +0.058 (+0.012 to +0.105) | +0.072 (+0.037 to +0.108) | +0.036 (+0.021 to +0.054) | 0 |
| C − A | +0.114 (+0.048 to +0.180) | +0.142 (+0.076 to +0.209) | +0.133 (+0.072 to +0.199) | +0.092 (+0.037 to +0.149) | +0.077 (+0.028 to +0.129) |
| [Elicit, as published](https://elicit.com/blog/evaluating-elicit-paper-search) (5,486 questions) | 0.390 | 0.483 | 0.603 | 0.670 | |
| **LitSearch (200)** | | | | | |
| A: plain OpenAlex | 0.394 | 0.449 | 0.561 | 0.621 | 0.669 |
| B: DEIXIS, reranker off | 0.474 | 0.578 | 0.636 | 0.708 | 0.738 |
| C: DEIXIS, reranker on | **0.557** | **0.612** | **0.700** | **0.725** | **0.738** |
| C − B | +0.083 (+0.026 to +0.142) | +0.033 (−0.020 to +0.085) | +0.064 (+0.019 to +0.112) | +0.018 (−0.005 to +0.043) | 0 |
| C − A | +0.166 (+0.095 to +0.237) | +0.165 (+0.095 to +0.235) | +0.142 (+0.075 to +0.209) | +0.107 (+0.040 to +0.174) | +0.072 (+0.003 to +0.142) |

- The reranker reorders only the top of the list, so B and C are equal at 200.
- BioASQ: Elicit's figures come from all 5,486 questions and ours from a sample, so the two are not compared
  statistically.
- LitSearch: almost every request has one gold paper, so each question scores 0 or 1 and the intervals stay wide.
- No DEIXIS question failed on any set. A plain OpenAlex query failed once on BioASQ and once on LitSearch.
- Cost: about $0.033 of OpenAlex budget per DEIXIS question. Voyage cost under $0.01 per question.

## Papers DEIXIS never retrieved

These are gold papers that plain OpenAlex has in its first 200 but that never enter DEIXIS's candidate list: 17 on
LitSearch (12% of the gold papers plain OpenAlex found) and 57 on BioASQ (9%). DEIXIS's own queries were run again on
OpenAlex (title and abstract search, up to 2,000 results each) to find the cause.

| Why | LitSearch | BioASQ |
|---|---|---|
| None of DEIXIS's queries matches the paper | 12 | 23 |
| A query matches, but the paper sits past the 500 records read per query | 5 | 34 |
| Read, then lost later (year filter, duplicates, type) | 0 | 0 |

- **The query leaves out a name or adds a topic.** For the ZEB2 question, five gold papers use the gene's old name,
  ZFHX1B, which the plain query lists and DEIXIS's does not. For the Westermark sign, DEIXIS adds a "chest
  radiography" block the question never mentions.
- **The query is too broad for the depth read.** A second query of one or two words (`bromocriptine`, 11,005 results)
  pushes the topic's own papers past 500. Reading 1,000 records would add at most 16 of the 57 BioASQ papers.
- **Full text.** The plain query uses OpenAlex `search=`, which also matches full text; DEIXIS searches title and
  abstract only, by design. In 13 of the 17 LitSearch losses the plain query does not match the title or abstract
  either.
- Some BioASQ gold papers are only loosely on the question, so not every loss is a DEIXIS error.

## Method notes

- **Matching.** A result matches a gold paper by OpenAlex id, PMID (BioASQ), DOI, then normalized title.
- **BioASQ.** Questions from the 2b–13b golden enriched test sets of Task B (2014–2025), 5,486 in all, the count
  Elicit reports; a fixed seed (`20261017`) draws 100. Records after the question's challenge year are removed from
  DEIXIS's list afterwards; this removed no gold paper.
- **Query repair.** When OpenAlex rejects arm A's query, the model repairs it once, as in Elicit's method.
- **Query pause.** If DEIXIS pauses on a query the model wrote, the harness resumes it once, as a person would.
- **Earlier run.** A 17 Oct BioASQ run with Gemini embedding and no reranker gave DEIXIS 0.545 at 50 results against
  0.489 for plain OpenAlex. In that run 27% of the gold papers never entered the list and 22% sat below position 100.

## Not measured

- Reading and answers. Only the order of the candidate list is measured.
- Run-to-run variance: each system ran once, and the model's query writing varies between runs.
- Elicit's LLM-judged evaluation on real user searches; DEIXIS has no shared search log.
- Whether the missed papers would rank well once in the pool, and the fixes for the query patterns above.
- Recall depends a little on provider speed, since Standard depth has stage deadlines.
- A gold set is not exhaustive, and a passing benchmark is not scientific validation of DEIXIS's answers.

## Run data

The DEIXIS data folders behind these runs (library databases, provider responses, per-question rows) stay on the
owner's machine and are not in this repository; the scoring code and tests are. The two figures are drawn from the
stored scoring output by `scripts/benchmark/figures.py`.
