# SW slice 29 — `standard`'s full-text fetch limit (SW24)

**Date:** 28 September 2026. **Status:** closed as a record (D111): owner's answers 2026-09-28 A1, B1, D1, C not
applicable (see "Owner choices"); no code change, no migration; SW24 closed as measured and not changed. **Review rule (owner, D105):** Sol (`gpt-6-sol` · high) blocks only on a **high** finding; at most
**3** plan rounds and **4** code rounds. **Prompt:** sw-slice29-prompt.md. **Main file:**
[sw-status.md](sw-status.md). **Decision:** D111 (highest today D110; if another slice has taken D111 by the time this
one is built, the next free number). **Migration:** none (the limits are constants; a run's budget is JSON on its row).
**Prerequisite:** slices 24a, 27 and 28 recorded or closed (D105, D108, D109). **Type:** record (A1) or build (A2, A3).
**Implementer:** Opus · medium. **Review:** batch (Sol · high, the rule above): under A1 only a decision entry and a
comment change; under A2 or A3 two constants, two tests and a live acceptance. **Plan:** Opus 5.5 · high. **Scope:** the
two `standard` full-text limits only.

**Measurement:** [.local/archive/sw/sw-slice29-fetch-limit-replay-2026-09-28/](../local-runs.md#run-archive-sw-sw-slice29-fetch-limit-replay-2026-09-28) (`protocol.md`, frozen before any number;
`replay.py`; `out.json`; `result.md`). It reads slice 24a's and slice 27's stored `sw` libraries with `immutable=1` URIs:
quantum `standard` r1, r2, embedding and `detailed` (24a, `65a7ec8`); medicine `standard` r1, r2, embedding and
`detailed` from slice 27 (`142dfa1`) and from 24a. No model call, no provider request, no network; port 8765 and the live
library were not touched. One M1 Pro, Python 3.12 arm64 through `uv`.

**Goal:** SW24 says quantum `standard` loses more reference works at the full-text fetch limit than anywhere else (10
and 12 of 31 routed to full text but not planned in slice 24a) and still misses its time target. This slice answers
whether `standard`'s limits should rise and what that costs. The replay says each higher limit plans more of them, but
only the `detailed` limit (300) brings back 75% of the gain, and reading them costs about 17 more minutes per run. The proposed default is to change nothing and record why.

## What the code does today

Read on 28 September 2026 at `0ab379d`.

- `backend/deixis/domain/rules.py:89`: `FULLTEXT_WORK_LIMIT = {"quick": 80, "standard": 100, "detailed": 300}`;
  `:95`: `FULLTEXT_READ_LIMIT = {"quick": 40, "standard": 50, "detailed": 150}`. D94 set `quick` to 80 / 40 after
  slice 14a's replay; `standard` and `detailed` have been hand-picked since D83 / D85.
- `backend/deixis/workflow/fulltext.py:39` `fetch_budget(effort)` gives the keyword limit plus the chain's own room
  (`CHAIN_PLAN_ROOM`, 12). `fetch_plan` (`:142`) takes the first `limit` eligible keyword works in group order (user,
  candidate, unresolved), inspection order inside each group; the chain group comes after with its own room.
- `backend/deixis/workflow/adjudication.py:54` `read_budget(effort)`: `2 × FULLTEXT_READ_LIMIT` model calls. `read_plan`
  reads works with text in the same group and inspection order.
- Since slice 17a the fetch runs inside discovery (`overlap_budget`); the plan is frozen by `_overlap_plan`
  (`flow.py:3441`) against the stored `code:fetch_baseline`. A run keeps the budget it was queued with
  (`tests/test_fulltext_flow.py::test_a_resumed_run_keeps_the_limit_it_was_queued_with_after_the_effort_limit_changes`).
- The protocol body writes `fulltext_fetch.work_limit` and `fulltext_adjudication.read_limit` from the constants
  (`rules.py:239`, `tests/test_protocol_record.py:157`), and PRISMA-S reads them by name (`tests/test_prisma_s.py:307`).
  No UI string in `apps/web/src/i18n.ts` or `labels.ts` names these numbers.

## Numbers we have

All from the replay; every stored run is one run with `gpt-5.6-luna` · medium. The replay reproduced the stored plan
exactly in all 12 libraries.

**Quantum `standard`** (31 reference units; r1 / r2 / embedding → mean; read limit half the fetch limit):

| fetch / read | reference units in plan | est. reference units read | est. added minutes |
|---|---|---|---|
| 100 / 50 (today) | 13 / 12 / 14 → 13.0 | 10 / 10 / 11 → 10.3 | 0 |
| 150 / 75 | 18 / 16 / 16 → 16.7 | 15 / 14 / 13 → 14.0 | 6.0 / 4.1 / 2.8 → 4.3 |
| 200 / 100 | 19 / 17 / 20 → 18.7 | 17 / 16 / 18 → 17.0 | 12.0 / 8.2 / 5.6 → 8.6 |
| 300 / 150 | 23 / 21 / 24 → 22.7 | 20–21 / 19–20 / 22 → 20.3–21.0 | 24.0 / 16.4 / 11.2 → 17.2 |
| 300 / 50 | 22.7 | 10 / 11 / 10 → 10.3 | 4.6 / 4.8 / 4.7 |

1. **The loss is where SW24 says.** 664 / 818 / 639 eligible keyword works compete for 100 places. At 300 the plan holds
   22.7 of 31 on average, the same as `detailed` (23 planned in slice 24a).
2. **The read limit binds.** With the read limit held at 50, a larger fetch leaves the estimated reference works read
   at a mean of 10.3 (per run 10 → 10, 10 → 11, 11 → 10; corrected 2026-09-28 at D111's review, first written as "no
   more in any of the three runs"). The reading already stops at 50 with text left over (r1: 8 not reached, r2: 5).
3. **The cost is the reading.** Per added fetched work about 0.023 minutes of wall time (mean work 0.09 min at a
   parallelism of 3.9); per added read work 0.08–0.19 minutes (r1's figure includes a 5-minute call that ended
   `outcome_unknown`). At 300 / 150 that is 4.6 minutes of fetch (an upper bound: none of it is credited to the overlap
   with discovery) and 6.8–19.4 minutes of reading, and up to 200 more model calls per run.
4. **Time today.** Quantum `standard` took 17.7 and 19.9 minutes create to answer (r1 29.2 with a 10-minute wait);
   `detailed` 35.9. The target (K7, D88) is 15. At 300 / 150 the estimate puts `standard` at 35–37 minutes (today's times plus the mean 17.2; paired per run, the
   two runs without a timeout wait give about 34.1 and 31.2), near where
   `detailed` is now.
5. **Medicine gains little.** Planned reference units at 100 → 300: 9 → 11, 5 → 9, 5 → 8 (slice 27); 8 → 10, 8 → 11,
   4 → 8 (24a). Only 3 of 12 units (t02, t07, t09) got a PDF in any stored medicine run, so the lower bound of units read
   does not move from 2 (slice 27) and 0 (24a) at any limit. In five of six medicine runs the fetched text does not fill
   today's read limit of 50. Medicine's loss is the missing open PDF (slice 27, D108), not room.

**The frozen rule** (`protocol.md`, written before the numbers): change only if the quantum gain at 300 is at least 3;
then take the smallest limit reaching 75% of that gain whose added time is at most 5.0 minutes. The gain is 9.7; only
300 reaches 75% of it; its added time is 17.2 minutes. **Rule result: no change.** The 3-unit floor and 5-minute ceiling
were picked by hand, not derived.

**Seen after the numbers, not by the rule:** 150 / 75 is the only step under 5 minutes on average (4.3; r1 6.0) and
gives +3.7 planned and about +3.7 read. Raising only the read limit at fetch 100 reaches at most 3 / 1 / 0 more quantum
reference units (slice 24a: 11 / 11 / 11 had a PDF, 8 / 10 / 11 were read) for about a minute.

## SW items

SW24 (open since slice 24a). This slice closes it under any of A1–A3: A1 closes it as measured and not changed, A2 and
A3 as changed.

## Decisions

1. **Limits (A).** Proposed A1: both `standard` limits stay 100 / 50. Each step plans more works, but only 300 reaches the rule's
   75% of the gain, and 300 is `detailed`'s limit and costs about what `detailed` costs; a user who wants them has `detailed`. D111 records
   the replay, the rule and the cost, so the next person who asks does not repeat it.
2. **Read follows fetch (fixed).** If a fetch limit rises, the read limit rises with it at half (D94's rule). The replay
   shows a fetch change alone leaves the mean read at 10.3 (300 / 50 row).
3. **`quick` and `detailed` do not change.** `quick` was set by D94; `detailed` already plans what the candidates allow.
   Chain room (12) does not change.
4. **Frozen budgets.** A run queued before the change keeps its budget; only runs queued afterwards get the new limits.
   The existing resume test covers it; no migration.
5. **Medicine's PDF loss is outside this slice.** Europe PMC's open-access subset holds 1 of the 10 PDF-less medicine
   units (slice 27); nothing in this slice changes that.

## Frozen expectations (A2 or A3 only; written before any live run)

Estimates from the replay, one run per question. Quantum `standard` create-to-answer: A2 19–25 minutes, A3 30–40.
Quantum reference units planned: A2 15–18, A3 21–24; read: A2 12–16, A3 18–22. Medicine `standard` time: A2 17–22
minutes, A3 28–35; medicine reference units read: 1–3 under either (PDF-bound). Model calls: quantum A2 150–185, A3
280–330; medicine A2 150–180, A3 230–300 (slice 27's runs made 122, 124 and 90).

## Owner choices (answered 2026-09-28: A1, B1, C not applicable, D1)

**Owner's answers (28 September 2026).** A1: `FULLTEXT_WORK_LIMIT["standard"]` stays 100 and
`FULLTEXT_READ_LIMIT["standard"]` stays 50. B1: the read limit does not change on its own either. C: not applicable,
there is no live acceptance under A1. D1: the 15-minute `standard` target stays; D111 records that `standard` misses it
by about 3–5 minutes today. The owner answered "Ok" to the summary "limit stays 100, record as D111, close SW24". Done
under A1: D111, SW24's status, row 29. Not done: the dated comment above `FULLTEXT_WORK_LIMIT` (task outline, A1 step
1); the record was kept to docs, so the code is untouched and pytest was not re-run.


- **A — limits.** **A1 (proposed):** no change; D111 records the replay and closes SW24. A2: 150 / 75, the only step
  under 5 minutes on average; chosen after the numbers, 38% of the gain at 300, fails the frozen rule. A3: 300 / 150,
  the rule's option: about +10 reference units read and about +17 minutes, `standard` then costs what `detailed` costs.
- **B — read limit alone.** **B1 (proposed):** no read-only change in this slice; D111 records that at most 3 / 1 / 0
  more quantum units would be read. B2: `FULLTEXT_READ_LIMIT["standard"]` 50 → 60 with fetch 100 (about +1 minute; seen
  after the numbers, one question).
- **C — live acceptance (A2 or A3 only).** **C1 (proposed):** one full run per question at `standard` with the new
  limits, caps below. C2: two quantum runs (K8's "run it twice, keep the better" applied up front).
- **D — the time target.** **D1 (proposed):** K7's 15-minute `standard` target stays a target; D111 notes that `standard`
  misses it by 3–5 minutes today and that no fetch or read change here brings it closer. D2: the owner revises K7.

## What the owner does

Answers A–D (or says "önerildiği gibi"). The answers go into row 29 of `sw-status.md` before the prompt runs.

## Global constraints

- **Only `standard`'s two constants** change, and only under A2 or A3. Order, groups, chain room, `quick`, `detailed`,
  the method package and `skill_package_hash` stay as they are; `fetch_plan`, `read_plan` and `ranking.py` are untouched.
- **No migration.** A run queued before the change keeps its stored budget.
- Tests have no network. Port 8765 and the live library are off limits; the live acceptance uses its own server and data
  directories; from the live data directory only `codex-home` is used, through `DEIXIS_CODEX_HOME`.

## Task outline

**Under A1 (and B1, D1):**

1. `rules.py`: a dated comment above `FULLTEXT_WORK_LIMIT`: "2026-09-28 (D111, slice 29): `standard` kept at 100 / 50; a
   model-free replay ([.local/archive/sw/sw-slice29-fetch-limit-replay-2026-09-28](../local-runs.md#run-archive-sw-sw-slice29-fetch-limit-replay-2026-09-28)) reaches 75% of the quantum gain only at 300, at
   about +17 min per run; medicine's loss is PDFs." No value changes.
2. D111 at the top of `docs/decisions.md` (Status / Date / Context / Decision / Limits): the replay, the frozen rule and
   its result, the 300 / 50 row, the medicine finding, the time target note. Limits: two questions, three runs each, time
   and PDF yield estimated from stored runs, the quantum reference set is model-derived, the medicine rule was widened
   after the fact, the 3-unit floor and 5-minute ceiling were hand-picked.
3. SW24 in `search-workflow-review-2026-09-18.md`: **Status** closed by D111.
4. Full pytest (no test changes); `git diff --check`.

**Under A2 or A3:**

1. `rules.py`: `standard` → 150 / 75 (A2) or 300 / 150 (A3), with a dated D111 comment naming the replay folder and
   "estimated, not measured; measured by slice 29's acceptance".
2. Tests: `tests/test_fulltext_plan.py::test_the_budget_of_a_retrieval_run_calls_no_model_and_sends_no_search` expects
   `[80, 150, 300]` / `[92, 162, 312]` (A2) or `[80, 300, 300]` / `[92, 312, 312]` (A3), and its comment names D111;
   `tests/test_adjudication.py::test_the_read_budget_is_two_calls_for_each_work_the_limit_reaches` gets `("standard",
   150, 75)` (A2) or `("standard", 300, 150)` (A3). `test_protocol_record.py`, `test_prisma_s.py` and the resume test
   read the constants by name and pass unchanged. `grep -rn "100, 50\|standard.*100" tests/` for any other hard-coded
   copy.
3. Live acceptance (below), then D111 with the measured times beside the estimates.

## Live acceptance (A2 or A3 only)

- Environment: slice 27's campaign ([.local/archive/sw/sw-slice27-remeasure-2026-09-27-043237/drive.py](../local-runs.md#run-archive-sw-sw-slice27-remeasure-2026-09-27-043237), `measure.py`): own
  server and empty data directory per research, `DEIXIS_SEARCH_WORKFLOW=sw`, `DEIXIS_FULLTEXT_FETCH=auto`,
  `DEIXIS_FULLTEXT_ADJUDICATION=auto`, `DEIXIS_SEARCH_QUERY=model`, embedding off, protocol approval `as_proposed`,
  nobody answers the queue. Model: connection `codex`, `gpt-5.6-luna`, effort `medium`, every role (the model of slices
  24a, 27 and 28). Folder [.local/sw-slice29-acceptance-<date>/](../local-runs.md#historical-paths-absent-from-the-inspected-tree); the expectations above go into its `protocol.md`
  before the first request.
- Runs: quantum `standard` and medicine `standard`, each to the answer (C1); under C2 quantum twice.
- **Caps (model sessions, repairs and re-sends included):** A2: quantum 200, medicine 220; A3: quantum 360, medicine 360.
  Reaching a cap stops the run and is written down. On a quota or rate-limit error stop; on `client_timeout` resume once
  after 10 minutes; never switch model or connection.
- **Acceptance (K8):**
  1. Time, the slice's own effect: quantum `standard` create to answer at most A2 25.0 / A3 40.0 minutes, not counting
     a written timeout wait. Above that, if the excess is in the fetch or the reading, the slice fails and the constants
     return to 100 / 50; if it is in discovery, the slice passes and the cause is written as a separate item.
  2. Quantum reference units planned at least A2 15 / A3 21 (the replay's mean at the new limit, minus K8's 2).
  3. Medicine `standard` time at most A2 22.0 / A3 35.0 minutes, same rule as 1.
- **Written, not conditions:** reference units read, included and cited on both questions; fetch and reading stage times
  beside the replay's estimates; PDF yield; model calls.
- D111, full pytest, `git diff --check`, row 29 → `uygulandı, inceleme bekliyor`.

## Not in this slice

- The order of the plan (D94 kept it; slice 14a's replay).
- `quick`, `detailed`, chain room, the abstract read limit N (K3), `blocks_in_title`.
- Finding more PDFs (Europe PMC's subset, slice 27; any new route).
- A read-only change unless B2 is chosen.

## Not measured

Whether added works get PDFs (estimated from each run's yield and from other stored runs), whether a read reference work
would be included or cited, how much of the added fetch hides inside discovery (the fetch estimate is an upper bound),
whether a longer reading keeps the same pace, run-to-run variation beyond three runs per question, and any third field.
The quantum reference list is a model-derived subset of our own earlier runs, not a human truth; the medicine list rests
on a rule widened after 25b stopped.
