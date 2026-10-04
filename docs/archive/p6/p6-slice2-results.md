# P6 slice 2, batch L9: development-lines measurement results

**Date:** 1 October 2026. **Frozen expectations:** `p6-slice2-expectations.md` (freeze commit `62812a1`, sha256 `342cf257…1644`), `../../product/p6-slice2-chain.json` (sha256 `cc0be4bb…8a4`) and the kit `scripts/p6_eval/measure_lineage.py`, none edited. Run folder (ignored by git): [.local/p6-slice2-l9/](../local-runs.md#run-p6-slice2-l9).

**What this measures.** The planned measurement was one run of the lineage task on one fresh table of an author-year/title field, with `gpt-5.6-luna` as the only link-producing model; what was actually done is one fresh corpus (NLP, one question, one preparation attempt, `gpt-5.6-luna` through Codex, effort medium, product tree of `6e85654`, `skill_package_hash` `sha256:371fcecb…e8c`) prepared by the product's own default discovery flow. **The corpus did not reach the frozen gates, so no lineage run was made and none of R12 to R15 was measured.** The result says nothing about the quality, the support or the recovery of development links. It is also not evidence that development lines are useless on author-year fields: the measurement never reached the step that would show it.

## What happened

1. **Start.** Dry start on an empty data directory (port 8867, `DEIXIS_DATA_DIR` and `DEIXIS_CODEX_HOME` set, all other `DEIXIS_*` variables unset): `skill_package_hash` equal to the frozen value, the four product trees equal, zero `started` sessions, zero runs. The executing worktree was clean for `apps/web`, `backend`, `contracts` and `methods` before the run, after it, and the five freeze files still matched their recorded sha256. The owner approved the read-only product backup of the live library (for K0) in chat; it was written under the run folder only.
2. **Research.** `res_SQ8KMWIzxERpBxeSWceO`, the frozen question, `academic`, `standard`, `codex` / `gpt-5.6-luna` / `medium`, `language_hint=en`, `review_mode=off`; the scope read back as frozen. One attempt (no second attempt was needed or allowed).
3. **Discovery** (run `run_VD5rrFvHQfFmw0uObWMZ`): protocol card approved as proposed, no edits; 17 model sessions, 4.5 minutes, `completed`. The full-text fetch ran inside it (`fulltext_summary` `succeeded`) and queued one `fulltext_adjudication` run: 53 sessions (52 completed, 1 failed and handled by the product), 7.4 minutes, `completed`.
4. **Funnel as the product stored it.** 161 rows returned, 99 unique works, 79 abstracts read by the model, 29 works excluded, **1 work included**, 69 pending (25 of them in the review queue waiting for a PDF, 22 of those with the reason `part_without_evidence`). Of the four works of the frozen chain G, the search returned three (ELMo, BERT, ALBERT) and not RoBERTa. All three that were returned stayed `pending`, none included; ELMo and ALBERT had stored PDF text (38 and 51 page passages), BERT had none. The single included work was a 2022 ICD-coding paper that uses contextualized language models. The frozen rules forbid adding works by hand or deciding queue items, so nothing was added.
5. **Rows, K0, table.** `measure_lineage.py rows` listed the frozen selection: 1 included work with PDF text, 1 row. K0 (independence against every version and identifier of the owner's library): no overlap, no unverified source. The table `tbl_G0uOSjWYnyFpbcoKMKBs` was created with that row, development columns added, and filled by the product (1 session, 13 seconds, `completed`; all three node cells filled).
6. **Gates.** K1 `pdf_text_rows >= 6`: **failed, 1**. K2 `nodes_complete >= 4`: **failed, 1**. K3 at least 3 candidate pairs from at least 2 later works: **failed, 0 candidates** (the one selected work had no candidate). K0 passed. By the frozen rule the corpus condition was not met: no lineage run, no new corpus, no second preparation attempt (the infrastructure exception did not apply: every run completed).
7. **End.** Server stopped. At the end: 71 model sessions in the library, 0 `started`, 0 non-terminal runs.

## Metric rows

| # | Status | Reason |
|---|---|---|
| R12 | not measurable | no lineage run was made (corpus gates K1 to K3 failed) |
| R13 | not measurable | same |
| R14 | not measurable | same; the freeze keeps "zero" for a lineage run that was made and found no link, not for a run that was never made (G still has 3 pairs; the table held none of its works) |
| R15 | not measurable | same |
| Structural counts | not applicable | zero lineage runs, zero candidates sent, zero decisions |

Hard rows (R12 not-supports, R13): not measured, so the freeze's hard-row rule does not apply. The model reader was never started (zero reader sessions).

## Cost of the preparation (recorded, not a measured rate)

71 model sessions (discovery 17, adjudication 53, fill 1); recorded tokens from 70 sessions: 677,824 input, 64,669 output, 742,493 total (summed from the recorded nested totals; the one failed session has no recorded usage), 13.0 minutes from the research record to the filled table. Lineage run: none. Reader sessions: none. The gpt-6.1-sol reviews of this text are editorial and outside the measurement.

## What this shows and what it does not

- It shows that, for this one question and this one run, the product's default automatic flow (abstract screening, full-text retrieval and adjudication, no human queue decisions) ended with one included work, and that famous works the frozen chain G names were found but left undecided. The undecided state is the product's own: the review queue held 25 works and wanted a PDF or evidence for them.
- It does not show how often the default flow leaves a topic with too few included works, why this question did so, or what a human working the queue would have changed. One question, one run, one model.
- It does not show anything about the finder, the lineage task or the model's links on an author-year corpus. The L8 open item (reference-list-only mentions) and the numbered-citation blind spot stay open.
- The frozen gates did their job: the run stopped before spending a lineage call on a one-row table.

## Open points for the owner

- To get an L9 measurement, a new freeze with a new fresh topic is needed (this corpus is burned), and the freeze should decide how the corpus is made when the automatic flow includes too few works: for example an owner-attached PDF seed, or a rule that works the review queue holds are decided by a recorded human step before the table. Neither was frozen here and nothing was changed after the fact.
- The quota/load resume rule frozen for this measurement (a deviation from D130 section 14.4) was not used.
