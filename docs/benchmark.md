# Search benchmark

Run on 2026-10-18 (results commit `437867ed`, reranker default D104). Two public sets with expert or author-chosen
papers per question:

- **BioASQ**, 100 biomedical questions, about 11 gold papers each. Scored the way Elicit scores its paper search
  ([Evaluating Elicit's paper search](https://elicit.com/blog/evaluating-elicit-paper-search)); method details are in
  [`benchmark-bioasq.md`](benchmark-bioasq.md).
- **LitSearch** (Ajith et al., EMNLP 2024), 200 of its 597 ML/NLP literature requests, about one gold paper each
  (198 in all; 195 resolve to an OpenAlex work).

## Settings

The settings the owner uses: Voyage `voyage-4-lite` for semantic similarity, Voyage `rerank-3-lite` for reranking
(pool factor 4), Standard depth, Claude Sonnet 5.5 at medium effort writing the queries. The harness writes these
settings into a temporary data folder, reads them back from the server before the first question, and records them
on every row; a provider failure stops the run instead of letting it continue without that step.

Three arms per question:

- **A**: one OpenAlex keyword query written by the same model, first 200 results (Elicit's baseline).
- **B**: DEIXIS, reranker off (the fused order).
- **C**: DEIXIS, reranker on. B and C come from the same run, so they differ only in the rerank.

## Result

Recall@k is the share of a question's gold papers in the first k results, averaged over questions. Intervals are
paired 95% bootstrap intervals over questions.

| | @10 | @20 | @50 | @100 | @200 |
|---|---|---|---|---|---|
| **BioASQ (100)** | | | | | |
| A: plain OpenAlex | 0.281 | 0.364 | 0.489 | 0.607 | 0.674 |
| B: DEIXIS, reranker off | 0.353 | 0.445 | 0.546 | 0.657 | 0.744 |
| C: DEIXIS, reranker on | **0.392** | **0.502** | **0.618** | **0.693** | **0.744** |
| C − B | +0.039 (−0.005 to +0.084) | +0.058 (+0.012 to +0.105) | +0.072 (+0.037 to +0.108) | +0.036 (+0.021 to +0.054) | 0 |
| C − A | +0.114 (+0.048 to +0.180) | +0.142 (+0.076 to +0.209) | +0.133 (+0.072 to +0.199) | +0.092 (+0.037 to +0.149) | +0.077 (+0.028 to +0.129) |
| Elicit, as published (5,486 questions) | 0.390 | 0.483 | 0.603 | 0.670 | |
| **LitSearch (200)** | | | | | |
| A: plain OpenAlex | 0.394 | 0.449 | 0.561 | 0.621 | 0.669 |
| B: DEIXIS, reranker off | 0.474 | 0.578 | 0.636 | 0.708 | 0.738 |
| C: DEIXIS, reranker on | **0.557** | **0.612** | **0.700** | **0.725** | **0.738** |
| C − B | +0.083 (+0.026 to +0.142) | +0.033 (−0.020 to +0.085) | +0.064 (+0.019 to +0.112) | +0.018 (−0.005 to +0.043) | 0 |
| C − A | +0.166 (+0.095 to +0.237) | +0.165 (+0.095 to +0.235) | +0.142 (+0.075 to +0.209) | +0.107 (+0.040 to +0.174) | +0.072 (+0.003 to +0.142) |

- The reranker helps on both sets: at 50 results the interval of C − B is above zero on both. It only reorders the
  first records of the list, so @200 is the same for B and C.
- DEIXIS with the reranker finds more gold papers than one plain OpenAlex query at every depth on both sets.
- On BioASQ, C is close to Elicit's published figures. Elicit's come from all 5,486 questions and ours from a sample,
  so the two are not compared statistically.
- On LitSearch nearly every request has one gold paper, so each question scores 0 or 1 and the intervals stay wide.
- No question failed. A plain OpenAlex query failed once per set and that question is left out of A. DEIXIS cost about
  $0.033 of OpenAlex budget per question.

## Papers DEIXIS never retrieved

A gold paper that plain OpenAlex has in its first 200 but that never enters DEIXIS's candidate list: 17 on LitSearch
(12% of the gold papers plain OpenAlex found) and 57 on BioASQ (9%), 74 in all. DEIXIS's own queries were run again
on OpenAlex the same way (title and abstract search, up to 2,000 results each) to see why.

| Why | LitSearch | BioASQ |
|---|---|---|
| None of DEIXIS's queries matches the paper | 12 | 23 |
| A query matches, but the paper sits past the 500 records read per query | 5 | 34 |
| Read, then lost later (year filter, duplicates, type) | 0 | 0 |

The loss is in the search step; no paper was dropped after it was read. The patterns:

- **The query leaves out a name or adds a topic.** For the ZEB2 question, five gold papers use the gene's old name,
  ZFHX1B, which the plain query lists and DEIXIS's does not. For the Westermark sign, DEIXIS's first query requires a
  "chest radiography" block the question never mentions.
- **The query is too broad for the depth read.** The second query often shrinks to one or two words
  (`bromocriptine`, 11,005 results; `"young athletes"`, 14,565), or a block carries general words like "treatment" or
  "adult". The topic's own papers then rank past 500. Reading 1,000 records instead of 500 would add at most 16 of the
  57 BioASQ papers.
- **Full text.** The plain query uses OpenAlex `search=`, which also matches full text; DEIXIS uses
  `search.title_and_abstract=`. In 13 of the 17 LitSearch losses the plain query does not match the title or abstract
  either, so it most likely found them through full text. DEIXIS chose title-and-abstract search on purpose (see
  `providers/openalex.py`).
- Some BioASQ gold papers are only loosely on the question (a Swyer-James case report for the Westermark question),
  so not every loss is a DEIXIS error.

## Not measured

- Reading and answers: this measures the order of the candidate list only.
- Whether the missed papers would rank well once in the pool, and where semantic search places them.
- Fixes for the query patterns above. They are a direction, not a measured result.
