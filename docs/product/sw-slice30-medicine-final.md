# SW slice 30 — The last medicine measurement, after the comparator fix

**Date:** 28 September 2026. **Status:** plan, frozen by its commit before any live run; Sol r1 (`gpt-6-sol` · high) "hazır değil": 2 high findings fixed, 1 medium fixed, 1 low folded in (last section). **Main file:**
[sw-status.md](sw-status.md). **Decision:** D112 (the next free number after D111). **Migration:** none (highest stays
`0055`). **Type:** measure; no product file changes. **Prerequisite:** slice 27 recorded (D108), slice 28 closed (D109),
slice 29 recorded (D111). **Implementer:** Opus 5.5 (the run session). **Review:** Sol (`gpt-6-sol` · high), one plan
round; a second round only if a high finding stays open. **Run folder:** `.local/sw-slice30-medicine-final-2026-09-28/`.

## What this is and why

This is the last measurement of the SW track. It runs slice 27's medicine measurement again, unchanged, on current
`main`, which now carries slice 28's comparator fix (D109). Slice 27 failed gates 2 and 4 on medicine (D108). Gate 4
failed on three includes whose comparison group followed the same calorie restriction as the time-restricted-eating
group; D109 was built to stop exactly that. Gate 2 failed at the PDF stage, which no slice since has changed.

The result decides 24b, the switch of the default search workflow from `legacy` to `sw`:

- **All four gates pass:** 24b is unblocked. The owner may switch the default in 24b, written then as its own prompt
  (slice 24's Part B tasks 10–14, the next free D, the hash measured here). This slice does not switch it.
- **Any gate fails:** the default stays `legacy` for good in this track. 24b is closed as not done, and the SW track
  ends. A later switch would need a new track with its own plan.
- **The run stops before the gates can be read** (model quota, Codex unavailable, the session cap below, a stop rule of
  slice 27's protocol): no verdict. Row 30 records where it stopped, D112 is not written, and the owner decides.

## The protocol: slice 27's, with these changes and nothing else

Slice 27's plan ([sw-slice27-medicine-remeasure.md](sw-slice27-medicine-remeasure.md)) and its run's `protocol.md`
(`.local/sw-slice27-remeasure-2026-09-27-043237/protocol.md`) apply as written: the question byte for byte; the seven
researches in the same order (`qtre-sw-standard-r1`, `qtre-legacy-standard-r1`, `qtre-sw-quick-r1`,
`qtre-sw-detailed-r1`, `qtre-sw-standard-emb-r1`, `qtre-sw-standard-r2`, `qtre-legacy-standard-r2`), one at a time,
2 minutes apart, ports 8858–8864, each in its own empty data directory; the server environment
(`DEIXIS_CODEX_HOME` from the live data directory, every other `DEIXIS_*` removed, the `sw` flags as listed); Codex
`gpt-5.6-luna` · medium in every role; nobody approves, edits, answers the queue or adds a PDF; the stop rules (quota or
rate limit: stop; one `client_timeout`: resume once after 10 minutes; any other `model_call_failed`: stop; never another
model or connection; no extra research for any gate); the gates as `gates25.py` applies them; gate 2's one-unit reading
(`gate2_oneunit.py`); the analyst sample of gate 4 with seed `2409261` from the union of the two `sw` `standard` runs,
read first by the run session (not blind) and then by a separate Claude Sonnet session, blind to the first verdict, on
every unit the first reader called serious plus 5 seeded non-serious units (`sample.py second`). A unit is serious when
either reader says so.

Changes:

1. **Code under test: current `main`.** At freeze, `git diff --stat 41c8da1 -- backend apps/web contracts methods` is
   empty; the plan commit adds only this file. Against slice 27's `142dfa1` the code differs by slice 28 (D109) and
   SW19/SW20 (`0ab379d`: the block-labelling thresholds move into the protocol, same values). The `skill_package_hash`
   from a dry server start in an empty data directory must equal D109's
   `sha256:1122205caf88fe87b4baad10dc529df93e391150b9b6ea0502e018a380baa2d8`; any other value stops the slice before any
   research. The run's `protocol.md` names the plan commit, the code commit and the hash, and the run checks before each
   research that the diff is still empty.
2. **Reference set copied, not rebuilt.** R is slice 27's: |R| = 12 (Cienfuegos 2020 as two units), 8
   comparator-differs, 4 unknown (25.0%), with the post-hoc BMI widening of D108. The run copies slice 27's scripts and
   reference files and checks each against the sha256 table of slice 27's `protocol.md` before anything else
   (`check_copies30.py`: 80 unchanged files by sha256, `drive.py` as slice 27's driver plus exactly `drive30.diff`,
   `runs.json` written fresh with the same seven rows, every one `pending`; at plan time nothing differed). No new esearch, no table
   read, no re-decision. Gate 2's medicine verdict stays descriptive and conditional on the post-hoc rule, reported
   beside the one-unit reading (|R| = 11), as D108 did.
3. **A hard cap on model calls.** Slice 27 opened 766 model sessions for the seven researches. The driver
   (`drive.py`, diff frozen as `drive30.diff`) counts the `model_sessions` rows of every data directory in the run folder
   before each research and on every 15-second poll, and stops the campaign when the count reaches **1,000** (slice 27
   plus 30%). Calls already in flight at that poll are counted and reported. A count that cannot be read stops the
   campaign, and after the last research the driver counts once more: a total of 1,000 or more at that point is also a
   stop (Sol r1). A cap stop is a stop, not a gate failure: no verdict. The Sonnet reading of gate 4 is a subagent
   session outside the cap and is counted separately.
   Frozen sha256: `drive.py` `192adc6841198c90beccc2656962e55834079f1eb6b1fc4acf7e020d0b959498`, `drive30.diff`
   `663d524df434b160557ee59abd9fba50f918e969fa1adf604800e81d946c0b64`, `check_copies30.py`
   `81299e154c8704a64560fdb5f9216847aca210d7d297d5f8fe9a1ba328999a71`, `check_reading30.py`
   `3e76d91aa59975ecd734d226355b5737c936372de083ed1c03765902e4008e41`.
4. **Quantum stays from slice 24a (`65a7ec8`), as in slice 27 (F1).** Gates 1, 2, 3 and 4 read quantum from
   `.local/sw-slice24-campaign-2026-09-26-134050/`. The gap is wider than in slice 27: besides slices 25a and 26, the
   code now has D109 and SW19/SW20. What is known: D109's marker leaves 625 of 625 stored quantum reading StepInputs
   byte-identical and its guard changes 0 of 304 quantum reading codes (replay); in D109's dry run one quantum reading
   stayed unchanged and 3 of 3 quantum criterion proposals carried no role; SW19/SW20 keep the same threshold values.
   Not measured: a full quantum research at this commit. The results document says so beside each gate.
5. **Names.** Run folder and marker `.local/sw-slice30-active` (written only after `protocol.md`); idempotency keys
   prefixed `s30-`; row 30 and D112 in place of row 27 and D108. The results file is `sw-slice30-results.md`, in the
   shape of slice 27's.
6. **PubMed.** Slice 27 lost PubMed from its second research on (D108). Before the first research the run sends one
   esearch for the question and records the answer. If PubMed is down, the run waits and retries every 10 minutes for
   at most 60 minutes, then starts anyway and records the outage. As in slice 27, no research is repeated because a
   provider failed.

## Pass and fail

The verdicts are `gates25.py`'s, read from `gates.json`. Gate 1 needs 10 of 10 `sw` researches answered (5 quantum
carried, 5 medicine here). Gate 2 (medicine) needs pool mean(`sw`) ≥ mean(`legacy`) − 2 and cited mean(`sw`) ≥
mean(`legacy`) − 1, with both `sw` `standard` runs citing at least one R unit when mean(`legacy`) ≥ 1. Gate 3 needs no
bad link, no isolation violation and no other model's output in the five medicine `sw` answers. Gate 4 (medicine) needs
at least 8 includes and 8 `sw` claims read, with at most 1 serious error in each.

Before `gates25.py` runs, `check_reading30.py` checks the analyst reading by unit id (Sol r1): every unit drawn in
`analyst/sample-qtre.json` has exactly one first reading, nothing outside the sample is read, and every unit named in
`analyst/second-qtre.json` (all first-serious units and the 5 seeded others) carries a second reading. Any gap means no
verdict until the gap is read; no reading is changed after the second draw.

"Gates 1–4 pass" means all four pass by that script, gate 2 under the chosen rule. Nothing else counts as a pass: no
re-run of a research, no re-reading of the sample after the verdict, no second draw. If all four pass, D112 and 24b's
prompt say in the same words as D108 that each verdict joins two commits (quantum from `65a7ec8`, medicine from this
one) and that the medicine half of gate 2 rests on a reference rule chosen after the numbers were seen.

## Frozen expectations

Written before any live run; one run of each research, one machine, one model.

- Gate 1 and gate 3 pass, as in slices 24a and 27.
- **Gate 2 most likely fails again on the citation half.** Slice 27's loss was the PDF stage: of R's units without a
  PDF in the `sw` runs, only one was in Europe PMC's open-access subset, and slice 29 (D111) found that only 3 of 12
  units got a PDF in any stored medicine run. Nothing since touches that. Expected: `sw` cites 0–2 R units per
  `standard` run, `legacy` 2–4, so the cited half fails unless `legacy` cites less than 2 on average. The pool half
  passes (slice 27: 11.5 vs 8.0).
- Gate 4: 0–2 serious errors in the sampled includes (weak). D109's dry run moved 2 of 3 of slice 27's comparator
  errors out of `all_parts_verified`; the third (APT 2025) stayed. More works go to the queue (`part_without_evidence`,
  `fulltext_runs_disagree`, `comparator_exclusion_withheld`) than in slice 27, so includes per `standard` run fall
  below slice 27's 9 (weak: 4–9). If fewer than 8 unique includes exist across the two `standard` runs, gate 4 is
  unreadable and does not pass.
- Model sessions 650–950 in all; wall time about 3 hours.

## Not measured, and not in this slice

A quantum research at this commit; a second run of any research; the PubMed effect if PubMed fails again; a human
reading of any include or claim (both readers are models); any product change; the default switch itself (24b).

## Sol r1 and what changed

Sol (`gpt-6-sol` · high), one plan round, 28 September 2026: "hazır değil", two high, one medium, one low. It confirmed
that the question, order, reference set and gate thresholds match slice 27.

1. **High: gate 4 could pass on an incomplete reading.** `gates25.py` counts rows and `serious` fields only. *Changed:*
   `check_reading30.py` checks the reading by unit id before the gates (section "Pass and fail").
2. **High: the cap could be passed silently.** An unreadable count was skipped and there was no count after the last
   research. *Changed:* an unreadable count stops the campaign; a final count at or above 1,000 is a stop (change 3).
3. **Medium: slice 27's `check_copies.py` would stop on the new driver.** *Changed:* `check_copies30.py` (change 2).
4. **Low: the two-commit join and the post-hoc rule must appear in D112 and 24b if the gates pass.** *Changed:* said
   in "Pass and fail".
