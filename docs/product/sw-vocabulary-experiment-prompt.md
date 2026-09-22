# Task: search vocabulary experiment — the code's word list against a model-proposed one, on three fields

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. A measurement, not a slice: no product code changes. Results go
to `.local/`; nothing is written to `docs/` until the owner says "uygun". Implementer: Opus · high. Written
2026-09-23 at the end of the slice 13f conversation. This comes **before** `sw-read-limit-cut-prompt.md`.

## Why (what the 13f conversation found)

Read on the `detailed` run of the second measurement (`.local/sw-measure-2026-09-22b/data-detailed-luna/`, question
on optimization models for end-to-end entanglement distribution in quantum networks):

1. **The core of the question was never searched.** Code (`domain/vocabulary.py::extract`) put *mathematical
   optimization models* in the task block; the block labelling model (`vocabulary_labels`, three runs, SW17) called
   it `claim` all three times, so it left every query. The task words (*decision variables, objectives, …*) were
   labelled `outcome` by one of the three runs and survived by majority.
2. **The first round kept 4 of 8 task words.** OpenAlex allows five boolean operators
   (`query_rules.OPENALEX_MAX_OPERATORS`), so `query_compiler._fit_blocks` cut *scheduling, memory capacity,
   fidelity, decoherence* from the end.
3. **The second round lost the task entirely.** `workflow/expansion.py::expand` took the most frequent title
   n-grams of the whole first round (all topic words: *quantum network* 242 works, *entanglement distribution*
   140, …) and accepted a phrase when it co-occurs with the setting block (≥ 20 records and ≥ 20% of the phrase's
   own count). Setting synonyms pass by construction (*quantum network*: 12,558 of 12,558, the singular of a
   setting term the blocked-word check missed); task and method words fail it (*resource allocation* 140 of
   213,947, *reinforcement learning* 91 of 242,607). `second_round_vocabulary` then **replaced** the task block with
   the accepted phrases, so the query became `(setting) AND (setting synonyms)`: OpenAlex 12,559 hits, Scopus 6,820,
   7,184 of the run's 11,126 search rows.

The owner is considering letting a model propose the vocabulary. This experiment measures whether a model-proposed
list, checked by code, finds more of the known relevant works than today's code list, and what each costs in
records.

## Arms

For each question below, build and store:

- **A — today's code list.** Exactly what the product builds: `extract` → `vocabulary_labels` (three runs) →
  `build_vocabulary` → `compile_block_queries`, then today's `expand` + `second_round_vocabulary` for round two.
  Call the product functions; do not reimplement them.
- **B — model-proposed list, code-checked.** One model call per question (three runs, majority, as SW17 does):
  the question in, a setting block and a task block out, each with the question's own terms plus the synonyms and
  field terms the model proposes (method names such as MILP / integer programming count as task terms). Code then
  probes every term against OpenAlex (count alone, and count AND the other block), marks terms with zero hits or no
  field share, and compiles through the same `compile_block_queries` limits. Write the prompt and output schema in
  the experiment folder, not in `methods/deixis-research/`.
- **C — A with the second round fixed** (no model): the second round keeps the task block and adds only phrases
  that are not setting synonyms; setting synonyms go to the setting block. Only if A's second round reproduces the
  finding above on at least one other question; otherwise say so and skip.

## Questions (at least three fields; no topic word enters product code)

1. The quantum question of the measurement above. Ground truth: the 31 high-confidence full-text-verified
   positives of `.local/quantum-source-comparison-2026-09-18/` (`compare_sources.py` builds them).
2. The packet-size question of `.local/second-topic-packet-size-2026-09-20/` (read its `protocol.md`, `labels/`,
   `criterion.json` for what counts as a positive there, and say how strong that ground truth is).
3. One question from a field neither of the two touches (medicine or life science preferred, so PubMed is in play).
   No verified positives exist: report counts and a hand-readable sample only, and say so.

## Measure, per question × arm

- The terms, their block, their probe counts, what the compiler dropped to fit the operator limit.
- Records each round's OpenAlex query returns (`meta.count`), and, where ground truth exists, how many positives
  fall inside the first 400 / 1,000 / 2,000 results of each round (read pages of OpenAlex only; Semantic Scholar is
  rate limited and adds nothing here per SW3 of the 2026-09-18 review).
- For question 3: the first 25 titles of each arm's first round, side by side.
- Requests and model calls spent.

## Rules

- Live OpenAlex and model calls are allowed; keep a request ledger, pace OpenAlex politely, stop and report on
  repeated 429s. Model: `gpt-5.6-luna` through the Codex connection; if its quota is out, `deepseek-flash` and say
  which one produced which numbers.
- Do not open the product database (`~/Library/Application Support/DEIXIS`), do not start, stop or query the
  service on port 8765. The measurement databases under `.local/` are read-only.
- Everything under `.local/sw-vocabulary-experiment-2026-09-23/`: scripts, raw responses, `result.md` (Turkish,
  plain language first, then tables).

## Final message

Per question: A vs B (vs C) on positives found and records returned; which terms made the difference; whether B's
model runs agreed with each other; a recommendation (keep the code list and fix round two, or model proposes and
code checks) with what it rests on; what was not measured (one run per arm, ground truth only on two fields, the
third field unlabelled); confirmation that the product database and port 8765 were not touched. No commit unless the
owner asks.

## After this

A slice that implements the recommendation, with Scopus out of the search (D90; with a VPN it stays the last source
asked for a missing abstract). Then `sw-read-limit-cut-prompt.md` on the new queries, then the third measurement.
