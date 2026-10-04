# P9 closed-batch records

P9 measured hardening, recovery, capacity, accessibility and the real-model
report path. This directory holds completed re-extraction, report-fix,
keyboard/matrix-fix and H9 execution prompts. The
[hardening plan](../../product/p9-hardening-plan.md),
[re-extraction design](../../product/p9-reextract-design.md),
[closing record](../../product/p9-reextract-closing-record.md), freezes,
[H9 results](../../product/p9r-report-results.md),
[owed-measurement results](../../product/p9-owed-measurements-results.md) and
[acceptance record](../../product/p9-acceptance-record.md) stay in product.

[D218](../../decisions.md#d218--p9-exit) records two consecutive full matrix
runs on `0af3216`: 14,265 pytest cases collected, zero failures, 23 skips;
process checks 45/45 and browser checks 212/212 in each. This is synthetic,
scripted-model evidence on one macOS arm64 machine. Capacity rows ran under
parallel load; no scientific or live-provider validation follows from the matrix.

[D202](../../decisions.md#d202--p9-h9b-the-report-path-is-measured-again-on-a-real-model-after-rf-first-on-h9s-own-table-not-independent-and-then-on-a-fresh-corpus-for-q3) records the H9 report series: H9e was the first
assembly-accepted real-model report, with most quality conditions out of range.
[D208](../../decisions.md#d208--p9-re-extraction-r5-compatibility-regression-and-closing-record-h7-finding-2-is-closed-for-the-explicit-text-retry-workflow-with-named-limits-and-no-must-fix-item) closes explicit text retry with named synthetic
regression limits. [D217](../../decisions.md#d217--p9-owed-batch-closed-l9-stays-an-unmeasured-named-debt-and-the-queue-pass-failure-is-a-deferred-driver-fix-not-a-packaging-blocker) closes the owed batch while
retaining unmeasured lineage R12–R15 and the deferred queue-driver fix.
Slice 4 E06–E18, H10 real-model crash recovery and other named limits remain
open in the [carried-debt table](../../product/p9-acceptance-record.md#open-debts-carried-past-p9).
No measurement was rerun during this archive move.
