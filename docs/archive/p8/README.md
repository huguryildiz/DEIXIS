# P8 closed-batch records

P8 added optional owner review of recorded answer/report/candidate snapshots
and bounded manual or scheduled follow-up. This directory holds completed B1
through B8b prompts. The
[design](../../product/p8-review-watch-design.md),
[acceptance record](../../product/p8-acceptance-record.md), result records and
the two expectation sheets read by model-behavior runners remain in product.

[B4](../../product/p8-review-results.md) recorded nine of nine planted faults
found in one real-model run on synthetic answer/report cases
([D184](../../decisions.md#d184--p8-b4-the-owner-review-was-run-on-a-real-model-against-frozen-synthetic-cases-nine-of-nine-planted-errors-were-found-and-no-finding-landed-on-an-unplanted-claim-in-one-run-of-one-model)).
[B8b](../../product/p8-b8b-results.md) recorded four of four planted candidate
faults found and three of three behavior cases passed, also in one run
([D189](../../decisions.md#d189--p8-b8b-a-real-model-read-candidate-review-inputs-4-of-4-planted-faults-found-3-of-3-behavior-cases-passed-one-run-and-the-p8-closing-record-is-written-p8-exit-conditionally-met)). P8 exit was conditionally met; these measurements
do not establish repeatability, human agreement or performance on real research.

[D180](../../decisions.md#d180--p8-design-review-by-another-model-is-a-separate-immutable-snapshot-record-the-user-starts-and-follow-up-is-a-manual-or-opt-in-bounded-check-that-runs-only-while-deixis-is-running) defines review as a separate immutable-snapshot
record requested by the user. Findings reach report text only through the
checked editor save. [D187](../../decisions.md#d187--p8-b6-interval-watches-are-checked-by-an-in-process-scheduler-while-deixis-runs-and-a-closed-or-sleeping-computer-gets-one-bounded-catch-up-per-research-that-says-what-was-not-checked) and
[D188](../../decisions.md#d188--p8-b7-follow-up-has-its-own-tab-that-shows-what-each-check-read-what-is-new-to-the-research-and-when-deixis-was-not-checking) record the scheduler, bounded catch-up and visible
follow-up history. Checking occurs while DEIXIS runs; sleeping or closed time
remains an explicit coverage gap.
