# P6 slice 1, batch P16, third and last attempt: report measurement results

**Date:** 30 September 2026. **Frozen files:** `p6-slice1-report-expectations.md` (sha256 `31f2666e…b25c7`, commit `cdf79ba`), `p6-slice1-report-expectations-addendum.md` (freeze commit `15bb131`) and `p6-slice1-report-expectations-addendum-2.md` (freeze commit `b1cbcfb`); none edited. The results of the first two attempts (`p6-slice1-report-results.md`, D124; `p6-slice1-report-results-run2.md`, D126) stand unchanged; this document sits beside them.

**What this measures.** One research (`res_IXBsnzhYZsKByEdTpSJo`, 25 included sources), one table (`tbl_x8xnc1S4b7ha3WtIJDVU`), one new report run, one model (`gpt-5.6-luna` through Codex, effort medium). Readings would be model readings unless the owner read; there were none, because the run stopped early. The fill result (3 failed rows, 21 of 175 cells missing) and the second attempt's stop at section IV were known before the run, and the report was requested with `continue_with_failed`, so the three rows were left out of its evidence. The result is therefore **a development measurement on a product fixed after an observed failure (D127, `14a6e6f`), conditional on the same known corpus**. It was the last attempt of this series.

**The three attempts side by side (not three report runs).** D124: the table was not `report_ready`, no report started, R1 to R11 not measured. D126: one report run, stopped at section IV after 7 sessions on an `unknown_passage_id` (a passage id copied with two characters missing); R1 and R7 measured. This run: one report run, stopped at section IV after 8 sessions on a different error, `anchor_not_in_cell_evidence` (a citation quote that does not occur in the stored cell evidence); R1 and R7 measured. Nothing here replaces or contradicts D124 or D126.

**Outcome in one paragraph.** The report request was accepted and the run wrote for 3.3 minutes and 8 model sessions (caps: 60 sessions, 90 minutes). Section II (code) and III became valid (III after one phrase repair). Section V's model draft validated after one schema repair, but its phrase repair was cut off by the measurement-ending cancel (below), so its record stayed `running`. Section IV failed: its quote check `anchor_not_in_cell_evidence` fired in the first call and again after the one schema repair, on two different anchors. No passage, cell, source or column id issue (`unknown_*_id`) appeared in any validated session. The frozen last-attempt rule allows a resume only for `client_timeout`; the cause here is not a timeout, so there was no resume, no repair and no fourth attempt. Only R1 and R7 are measured. R2 to R6, R8, R9 and R11 are not measurable, and R10 is not measured by design. Nothing here says the report kind passed or failed.

## What happened

1. Start checks all held: addendum 2 status DONDU; `14a6e6f` is an ancestor of the freeze commit `b1cbcfb`; the code diff `14a6e6f..b1cbcfb` is empty and stayed empty to the end; `git diff 15bb131 14a6e6f` sha256 `4185cb2d…5413`; expectations and addendum hashes matched; `skill_package_hash` `sha256:52775258…81ac` (dry start, port 8868); schema-list hash `65df8e3c…af32`; kit hashes `db203420e4b1` and `7f7d2f0d5004`, 117 kit tests passed. `$RUN3` did not exist; it was made by `cp -Rp` from the first attempt's folder (`library.sqlite` sha256 `d8c83eee…6db8`); the digests of both files were byte-identical and equal to the first addendum's table (25 rows, 7 columns, 175 cells, 219 links, 1417 passages, 25 included, 0 reports, 0 active runs, migration 57). Eleven `pending` steps under terminal runs were preserved; no other foreign work.
2. The scope read `codex / gpt-5.6-luna / medium`; `GET .../tables` showed `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25, `can_continue_with_failed` true. `pairs.json` was copied byte for byte from the second attempt (sha256 `2037d993…6b96`, verified) before the report; all seven sources are completed rows (for Kurt16 the pair belongs to `srv_z66jQh7wK2BEWMrDicMF`; another row also carries that key and states no equation).
3. One report request (`continue_with_failed: true`, key `p16-run3-report-1`, 18:17:44 UTC) was accepted: run `run_ClVDKhUoKV0ddjH1eNOW`, report `rpt_IJPPcP3jFvUXsfmCO66I`. Sessions: `report_plan` 1, III 1, IV 2, V 2, phrase repair III 1, phrase repair V 1 (interrupted): 8, all on `gpt-5.6-luna`.
4. At 18:21:01 UTC the step `report_section:IV` was stored as `failed` (`invalid_model_output`, `anchor_not_in_cell_evidence` at `/citation_anchors/11/quote`; first call: anchor 25) while the run still showed `running` and the phrase repair for V was in flight. The frozen rule for a stop cause other than `client_timeout` found in a running run is to cancel it solely to end the measurement; the observer did so. The in-flight V phrase-repair session ended `interrupted` (step `outcome_unknown`, `model_interrupted`). The run's final backend status is `cancelled` (the second attempt's run stayed `paused`). Zero sessions stayed `started`; no `over_cap_in_flight`. `snapshot --stopped section_failed` and `score` followed; no reader started.

## Procedure notes

Two departures from the frozen text, recorded here and in `protocol3.md`: (1) the digest script and driver skeleton were taken from the second attempt's folder (`digest.py` was checked identical to the prompt's script; `drive3.py` is adapted from `drive2.py`), which goes beyond the prompt's "only `pairs.json`" read of `$RUN2` but uses no data of that run. (2) The observer read step and session error records on every poll, but not the sections' validations or `review.reason` on each poll (they were read at the end); the IV failure was caught from the step record, and the review step never ran, so nothing was missed.

## R1 to R11

Sample: the whole run. Reader: `code` (the kit) for R1 and R7. Ranges are copied from the frozen expectations; the addendum 2 meaning shifts (D127) are noted where they bear.

| # | Frozen range | Value | Status |
|---|---|---|---|
| R1a | 7 to 10 of 10 model-written sections valid on the first try; wrong if 5 or fewer, or more than 2 failed | **0 of 3** readable sections (III needed a phrase repair, V a schema repair, IV failed); 7 sections never started | **out of range.** A count, not a rate; the denominator is 3 |
| R1b | at least 9 of 10 valid after repair; wrong if the run stopped because of a section | **1 of 3** by section record (III valid; V's record `running` because of the cancel, IV `failed`); stopped because of section IV | **out of range** (the frozen sentence fires) |
| R1c | 1/1 completed report | **0/1**; the report is `in_progress`, no `report_version` | **out of range** |
| R2 | at most 3 claims with a wrong link; at most 8 partial (hard row) | none | **not measurable** (`run_incomplete`) |
| R3 | U at most max(1, floor(0.10 N)) (hard row) | none | **not measurable** (`run_incomplete`) |
| R4a | 0 claims without `body_refs` (hard row) | none | **not measurable** (`run_incomplete`; Abstract, I, IX never written) |
| R4b | at most 10% overreach | none | **not measurable** |
| R5 | mean at most 1 alternate name per term | none | **not measurable** |
| R6 | 0 to 6 equations; at least half match if 3 or more | none | **not measurable** |
| R7 | 10 to 30 minutes; 15 to 46 calls; 7 to 13 sequential | 3.28 minutes (196.8 s, run created to the cancel record); **8 model calls** (7 completed, 1 interrupted); sequential chain 2 rounds, 195.0 s, `partial`; tokens for the 7 completed sessions (`token_usage_json.total`, summed read-only): 173,499 input, 26,084 output, 199,583 total (the kit's summary omits these nested totals); queue and quota wait `not_readable` | **out of range** numerically. A stopped run cannot meet a completed-run range; not evidence of speed or cost. Not compared with D126's 189,969 tokens (a different partial run) |
| R8 | 30% to 70% first-try misfit; at most 25% unframed after repair | none | **not measurable** |
| R9 | at least half of the marked pairs present with parts | none | **not measurable** (pairs fixed before the report, never used) |
| R10 | no range | none | **not measured** (`p15_behavior_is_not_r10`) |
| R11 | truncation at most 20%; `insufficient_evidence` 0 to 3; missed at most 2 | none | **not measurable** |

Context (not part of R7): the first attempt's fill took 36 sessions and 3.3 minutes. Sessions against the cap: 8 of 60. Minutes: about 3.4 of 90. The three hard rows (R2, R3, R4a) could not be applied, and none was outside its range.

The R1 section breakdown for the addendum 2 shifts: the stop cause (`anchor_not_in_cell_evidence`) belongs to the older class. That issue code existed at `15bb131` and the `15bb131..14a6e6f` diff does not touch it. It is not one of the new D127 section-level membership checks and not an id copy error.

## Manual checks (addendum 2, not R-rows; content that exists only)

Details are in `report/manual_checks.md` in the run folder.

- **D125 exclusion count: 0.** The three failed source-version ids and their 101 passage ids occur in none of the 8 stored step inputs and none of the 8 sent messages. Stored claims exist only for III (17 claims, 26 evidence links); none points to a failed source; the 7 references contain none. Equation origins: III has two (III.11, III.12), both pointing to a passage of the completed source `srv_e9gmGxS8HIm6CN1mJKXQ`, zero violations. Gap bases: no section that writes them ran. The count says nothing about VI to IX. The inputs are not empty: a section input holds 33 real passage ids while its sent message holds none.
- **Product note.** `missing_rows` in the report view: yes. II states 25 included, 22 completed, 3 failed and 21 of 175 cells missing (one sentence plus its `numbers.rows` record). Markdown export note: not readable (HTTP 409, "still being written"). VIII's eighth item: not readable, VIII never written.
- **Failure statements.** II's only sentence on failed rows says they did not complete and were left out of the evidence: fine. No claim of absence in the source: 0 in the readable content.
- **Id-issue record (descriptive).** Across the 7 validated sessions: 0 issue codes of the `unknown_passage_id`, `unknown_cell_id`, `unknown_source_id`, `unknown_column_id` kind, and 0 from the new section-level membership fields. The only issues are `anchor_not_in_cell_evidence`: IV first call 1 (anchor 25), IV repair 1 (anchor 11, survived), V first call 4 (anchors 0, 1, 20, 21; gone after repair). Figures are read from stored validation (real ids after resolution); the raw model output carries handles (for example `cel_L0000019`). The phrase-repair V session was interrupted and not read. This record does not say whether handles reduced id errors: one run, random output, and the second attempt's error was a different model output.

## What the run shows and does not show

It shows, on one run: with `14a6e6f` the report path started and wrote three sections' worth of text for the filled table on a real model without a single id error in validated outputs, and the three failed rows stayed out of every stored step input and of the stored claims, links and references. It also shows that a report section can fail its quote check against the stored cell evidence, here twice in a row on different anchors despite the one permitted repair, and that one such failure ends the whole report. Two sections (IV, V) hit that code in the first call, and V's structural check passed after its repair (that says nothing about its content).

It does not show: any claim-level quality (R2 to R6, R8, R9, R11); how sections VI to IX, the Markdown export and VIII's eighth item behave; whether handles caused the absence of id errors (they did not get a controlled test); a failure rate; anything about another table, corpus or model. These need an independent corpus and a completed run.

Open question for the owner (no proposal for a fourth attempt): the frozen series ended without a completed report. Whether the anchor-quote failure should be handled at section level (for example a targeted quote repair) is a product change outside the frozen path.

## Kept under the run folder

`.local/p6-eval-2026-09-30-run3/`: `protocol3.md`, `digest.py` with both digest outputs, `pairs.json`, `tables_response.json`, `drive3.py`, `ledger.jsonl`, `poll.log`, `server.log`, `run.json`, `report.json`, `report.md` (the 409 body), `research_final.json`, `data/`, `report/{snapshot.json,automated.json,review.md,manifest.json,results.json,manual_checks.md}`. Not committed.
