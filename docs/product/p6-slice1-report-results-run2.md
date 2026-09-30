# P6 slice 1, batch P16, second attempt: report measurement results

**Date:** 30 September 2026. **Frozen files:** `p6-slice1-report-expectations.md` (sha256 `31f2666e…b25c7`, commit `cdf79ba`) and `p6-slice1-report-expectations-addendum.md` (freeze commit `15bb131`), neither edited. The first attempt's results (`p6-slice1-report-results.md`, D124) stand unchanged; this document sits beside them.

**What this measures.** One research (`res_IXBsnzhYZsKByEdTpSJo`, 25 included sources), one table (`tbl_x8xnc1S4b7ha3WtIJDVU`), one report run, one model (`gpt-5.6-luna` through Codex, effort medium), one attempt. All readings are model readings; here there were none, because the run stopped early. The table's fill result (3 failed rows, 21 of 175 cells missing) was known before the report started, and the report was requested with the explicit choice `continue_with_failed` (D125), so those three rows were left out of its evidence. The result is therefore a measurement conditional on a table whose fill result was known.

**Outcome in one paragraph.** The product accepted the report request and wrote for 3.7 minutes and 7 model sessions (caps: 60 sessions, 90 minutes). Section II (code) and sections III and V were valid; section IV failed because the model wrote a passage id with two characters missing, twice (first call and its one schema repair). The backend paused the run with `section_failed`. The frozen rules resume a paused run only for `client_timeout`, so the run was not resumed and concluded as a stopped run. Only R1 and R7 are measured. R2 to R6, R8, R9 and R11 are not measurable, and R10 is not measured by design. Nothing here says the report kind passed or failed, and no range of R2, R3 or R4a could be applied.

## What happened

1. Start checks all held: addendum status DONDU; frozen diff `97faf6d..15bb131` empty for code, methods, contracts, scripts and tests; expectations sha256, kit hashes, `skill_package_hash` `sha256:08f1bdea…04ee` and the schema-list hash `65df8e3c…af32` matched; the first attempt's `library.sqlite` sha256 `d8c83eee…6db8` matched; the working copy was byte-identical and the digests of both files were identical and equal to the addendum table (25 rows, 7 columns, 175 cells, 219 links, 1417 passages, 25 included, 0 reports, 0 active runs, migration 57). The copy holds 11 `pending` steps under terminal runs (2 cancelled, 9 completed), preserved unchanged, and no other foreign work.
2. The scope read `codex / gpt-5.6-luna / medium`. `GET .../tables` showed `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25, `can_continue_with_failed` true, as the addendum requires.
3. `pairs.json` was written before the report (seven pairs from completed rows whose "Denklem" cell holds an equation: Dong14, Vuran08, Akbas14, Noda13, Oto12, Kurt16, Yaakob10; never Nandi12, Zaman20 or Sankarasub03).
4. One report request (`continue_with_failed: true`, key `p16-run2-report-1`) was accepted (202), run `run_wODL7ceeQPzODt2ncqnh`, report `rpt_ZV6m44jBsiIlIUHoE7Hy`. Sessions, per step: `report_plan` 1, III 1, IV 2, V 1, phrase repairs for V and III 1 each, total 7, all resolved to `gpt-5.6-luna`, no over-cap sessions. III, IV and V ran in parallel.
5. Section IV failed: the model cited `psg_FpnsupjsR0ckcoc8rY`; the id in the step input is `psg_FpnsupjsR0ckcocxc8rY`. The first call also had an `anchor_not_in_cell_evidence` issue (repaired); the wrong id survived the one repair (claims 5 and 10), so the step failed with `unknown_passage_id`. The backend paused the run at 15:51:09 UTC (3.71 minutes after it was created). No quota, `client_timeout` or model mismatch was involved.
6. **Decision at the stop** (Claude and gpt-6.1-sol, high, read-only; both agreed): the frozen prompt allows resuming a paused run only for `client_timeout`, once, and a resume would replay the failed section by intervention. The run was not resumed, cancelled or repaired; the backend status stayed `paused`. `snapshot --stopped section_failed` and `score` were run; no reader was started. This is recorded as a deviation in `protocol2.md`.

## R1 to R11

Sample: the whole run (nothing sampled). Readers: `code` (the kit) for R1 and R7. Ranges are copied from the frozen expectations.

| # | Frozen range | Value | Status |
|---|---|---|---|
| R1a | 7 to 10 of 10 model-written sections valid on the first try; wrong if 5 or fewer, or more than 2 failed | **0 of 3** written sections (III and V valid only after a phrase repair, IV failed); 7 sections never started | **out of range.** Read this as a count, not a rate: the denominator is 3, and 7 of 10 was no longer reachable |
| R1b | at least 9 of 10 valid after repair; wrong if the run stopped because of a section | **2 of 3** (III, V); the run stopped because of section IV | **out of range** (the frozen "if I see this" sentence fires: a run stopped because of a section) |
| R1c | 1/1 completed report | **0/1**; the run is `paused`, no `report_version` | **out of range** (the frozen sentence fires: the report stays paused; cause: section IV, `unknown_passage_id`) |
| R2 | at most 3 claims with a wrong link; at most 8 with a partial link (hard row) | none | **not measurable** (`run_incomplete`; no claims read) |
| R3 | U at most max(1, floor(0.10 N)) (hard row) | none | **not measurable** (`run_incomplete`) |
| R4a | 0 claims without `body_refs` (hard row) | none | **not measurable** (`run_incomplete`; Abstract, I and IX were never written) |
| R4b | at most 10% overreach | none | **not measurable** (`run_incomplete`) |
| R5 | mean at most 1 alternate name per glossary term | none | **not measurable** (`run_incomplete`) |
| R6 | 0 to 6 equations; at least half match if 3 or more | none | **not measurable** (`run_incomplete`) |
| R7 | 10 to 30 minutes; 15 to 46 calls; 7 to 13 sequential | 3.71 minutes (222.6 s from run created to paused; 3.8 minutes at the last poll); **7 model calls**; sequential chain 2 rounds, 221.0 s, marked `partial`; token usage is stored for all 7 sessions (`token_usage_json.total`): 169,012 input, 20,957 output, 189,969 total tokens (summed read-only from the session records; the frozen kit aggregates only top-level numeric fields and so shows only `modelContextWindow`; by the kit's disjoint groups the totals are 79,251 for first calls (3 sessions), 32,303 for repair calls (2) and 78,415 for failed calls (2), recomputed by gpt-6.1-sol); queue and quota wait `not_readable` (`wait_intervals_not_separately_recorded`) | **out of range** numerically (below 10 minutes and 15 calls). A stopped run cannot meet a completed-run range, so this is not evidence of speed or cost. The frozen sentence "finishes under 4 minutes: look at R1" describes this case: the run ended fast because a section failed |
| R8 | 30% to 70% first-try misfit; at most 25% unframed after repair | none | **not measurable** (`run_incomplete`) |
| R9 | at least half of the marked pairs present with parts | none | **not measurable** (`run_incomplete`; the seven pairs were marked before the report and never used) |
| R10 | no range | none | **not measured** (`p15_behavior_is_not_r10`); P15 results were not used |
| R11 | truncation at most 20%; `insufficient_evidence` 0 to 3; missed at most 2 | none | **not measurable** (`run_incomplete`) |

Context row (not part of R7): the first attempt's fill took 36 sessions and 3.3 minutes; it is not a report figure. Session count against the cap: 7 of 60; minutes against the cap: 3.8 of 90.

The three hard rows (R2, R3, R4a) could not be applied. The expectations say a hard row outside its range makes the record say the report must not be called "usable as is"; none was outside its range, none was measured, and the report is not a finished report anyway.

## Manual checks (addendum, not R-rows; partial report only)

Details are in `report/manual_checks.md` under the run folder. They cover sections II, III and V and say nothing about VI to IX, which do not exist.

- **D125 exclusion count: 0.** Of 18 claims (III 13, V 5) and 35 citation links, none points to Nandi12, Zaman20 or Sankarasub03 (checked by source-version id and by their 101 passage ids); the 15 references contain none of them; no claim has an equation reference; the frozen snapshot has 154 cells (22 rows x 7) and none from a failed source; none of the 7 stored step inputs sent to the model mentions the three source-version ids or their passages. Gap bases: not readable, no gap section was written. This is the first real-model evidence that the exclusion holds on a written section, on 18 claims, and no more than that.
- **Product note.** `missing_rows` in the report view: yes (25 included, 22 completed, 3 failed, 21 of 175 cells missing; the three sources with reasons `invalid_model_output` and `no_stored_text` and their seven columns each). II states 25, 22, 3 and 21/175 in one sentence, without the word "failed" and without naming the rows. Markdown export note: not readable, the export returned HTTP 409 ("The report is still being written"). VIII's eighth item: not readable, VIII was never written.
- **Failure statements.** II's sentence says the rows did not complete and are left out of the evidence: fine. No sentence in III or V describes a failed row. Statements turned into a claim of absence in the source: 0 in the readable content.

## What the run shows and does not show

It shows, on one run: the report path with `continue_with_failed` starts and runs against a real model on a table with recorded failed rows; the three failed rows stayed out of the plan, section inputs, claims, links and references of the sections that were written; II carries the counts. It also shows that a report section can fail hard on a copied passage id that is one repair away from being right, and that the run then stops the whole report, three sections in.

It does not show: any claim-level quality (R2 to R6, R8, R9, R11 were not measured); how the report behaves through sections VI to IX, the Markdown export and the eighth item of VIII; whether a second run would stop at the same place (the failing id is a model copy error, so it may not); a rate of section failures (one run, one section); anything about a fully filled table or another model. The result does not replace the first attempt's D124.

Open: the frozen rules give no way to continue past a section failure without a second attempt or an intervention. The product's own resume would replay the stored step. Whether a later run should be allowed to resume such a pause is for the owner.

## Kept under the run folder

`.local/p6-eval-2026-09-30-run2/`: `protocol2.md`, `digest.py` with both digest outputs, `pairs.json`, `tables_response.json`, `report_start_response.json`, `drive2.py`, `poll.log`, `ledger.jsonl`, `server.log`, `report.json`, `report_export_response.txt`, `data/` (the copy with the report run), `sol/` (the stop-decision question and answer), `report/{snapshot.json,automated.json,review.md,manifest.json,results.json,manual_checks.md}`. Not committed.
