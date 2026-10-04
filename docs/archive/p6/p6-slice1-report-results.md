# P6 slice 1, batch P16: report measurement results

**Date:** 30 September 2026. **Frozen expectations:** `p6-slice1-report-expectations.md` (commit `cdf79ba`, sha256 `31f2666e…b25c7`), not edited.

**What this measures.** One research (`res_IXBsnzhYZsKByEdTpSJo`, Turkish question on packet size in wireless sensor networks, 25 included sources), one evidence table built for the run, one model (`gpt-5.6-luna` through Codex, effort medium), one attempt. The run stopped before a report could start, so **none of R1 to R11 was measured**. What the run does show is the table fill (one real-model run) and why the table was not ready for a report. No reader, model or human, read anything: there was nothing to read.

## What happened

1. A library copy was taken with the product's own backup and restore (the live library was at migration 36; migrations 37 to 57 were applied to the copy only). Two paused runs of other researches were set to `cancelled` in the copy so that no foreign model call could run. Server on port 8866 with `DEIXIS_CODEX_HOME` set; according to `protocol.md`, no listener was detected on port 8765 at run start; that service was not touched. `skill_package_hash` `sha256:08f1bdea…04ee`.
2. The scope read `codex / gpt-5.6-luna / medium`. It is a stored `legacy`-workflow research (the expectations text assumed every research is `sw`); table and report do not depend on that, so the run went on.
3. A table `tbl_x8xnc1S4b7ha3WtIJDVU` was created with exactly the seven frozen columns (names and instructions checked against the expectations text). 25 rows, 175 cells. Rows by recorded access level: `abstract` 14, `pdf_available` 9, `metadata` 2.
4. **Fill (path B), one run.** Requested 13:26:47 UTC, completed 13:30:02 UTC: **36 model sessions; 3.3 minutes from request to backend completion, 3.45 minutes to the final counter read** (caps 60 sessions, 60 minutes), all resolved to `gpt-5.6-luna`, no over-cap sessions. 23 extraction steps were planned (the two metadata-only rows need no call). 22 succeeded; 10 steps needed one session, 13 needed two (schema repair). One step failed after its repair: Sankarasub03 (`anchor_not_in_passage`), leaving 7 cells without a value.
5. **Readiness.** Cell states after the fill: value 129, `not_found_in_inspected_scope` 24, `unknown` 1, `inaccessible` 14 (Nandi12 and Zaman20, no stored passages), no stored value 7 (Sankarasub03). The product's readiness check says `ready: false, cells_left: 21 of 175, failed_rows: 3`. The report request calls that check without the "continue with failed rows" switch and the API offers no way to set it, so a report request would be refused with 409.
6. **Stop.** The frozen run prompt says a table that is not `report_ready` starts no report and nothing is edited by hand, and that there is no second run. Making the table ready would have needed a second fill or recheck (beyond the one fill) and, for the two metadata-only rows, removing them from the research (a change to the frozen 25-source corpus). Claude and gpt-6.1-sol (high, read-only) agreed on stopping (`protocol.md`, deviation record 1). No report, snapshot, reading or scoring was made.

## R1 to R11

Every row: **not measured, no report started** (reason `table_not_report_ready`). The stop-early exception (R1 and R7 only) applies to a report run that was interrupted; none existed, so R1 and R7 are not measured either. Values, denominators and samples are empty; readers: none.

| # | Frozen range | Result |
|---|---|---|
| R1a | 7 to 10 of 10 sections valid on first try | not measured |
| R1b | at least 9 of 10 valid after repair | not measured |
| R1c | 1/1 report completed | not measured (0 reports started) |
| R2 | at most 3 claims with a wrong link; at most 8 with a partial link (30 sampled) | not measured |
| R3 | U at most max(1, floor(0.10 N)) | not measured |
| R4a | 0 claims without `body_refs` | not measured |
| R4b | at most 10% overreach | not measured |
| R5 | mean at most 1 alternate-name occurrence per glossary term | not measured |
| R6 | 0 to 6 equations; if at least 3 are displayed, at least half match the original PDF pages | not measured |
| R7 | 10 to 30 minutes, 15 to 46 calls, 7 to 13 sequential | not measured (the fill's 36 sessions and 3.3 minutes are not report figures) |
| R8 | 30% to 70% first-try misfit; at most 25% unframed after repair; `reverted_exception` 0 to 2 | not measured |
| R9 | at least half of marked pairs present with parts | not measured (no `pairs.json`; it is marked only for a report that starts) |
| R10 | none (not measured in this slice by design) | not measured (`p15_behavior_is_not_r10`); P15 results were not used |
| R11 | truncation at most 20%, `insufficient_evidence` 0 to 3, missed at most 2 | not measured |

The three hard rows (R2, R3, R4a) cannot be applied; no sentence in this document says the report kind passed or failed.

## What the run shows and does not show

Shows (measured, one attempt, gpt-5.6-luna): on this 25-source table the seven-column fill finished in 3.3 minutes (backend completion) and 36 sessions, 13 of 23 extraction steps needed a schema repair, one of them still failed on an anchor that was not in the cited passage, and 2 of 25 included sources had no text to read. A table in this state cannot start a report through the product, and the product gives the person no way to continue with the failed rows.

Does not show: anything about the report (its sections, citations, absence wording, equations, patterns, time or cost), any model other than `gpt-5.6-luna`, or whether a retry would have succeeded (one failed anchor may be a chance failure; the two metadata-only rows are not). The fill figures are from one run on one corpus and are not a rate.

## Left open (for the owner, nothing done)

A later P16 attempt needs its own frozen choice before it starts: a table whose sources all have text, or an explicit owner decision to exclude Nandi12 and Zaman20 and allow one recheck of Sankarasub03. Excluding sources selects the corpus and would be a different measurement from the frozen path B. Separately, the missing "continue with failed rows" path in the report request is a product question (recorded in D124, not changed here).

Working files (ignored by git): [.local/p6-eval-2026-09-30/](../local-runs.md#run-p6-eval-2026-09-30) (`protocol.md`, `ledger.jsonl`, `poll.log`, `table_after_fill.json`, `fill_run.json`, `sol/q1.md`, `sol/a1.md`).
