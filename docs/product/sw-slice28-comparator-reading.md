# SW slice 28 — The full-text reading checks what the comparison group actually receives

**Date:** 27 September 2026. **Status:** plan written; Sol r1 (high only) "hazır değil", 2 high findings addressed; Sol r2: r1 closed, 1 new high addressed (last section). A1, B1, C1, D1, E1 önerildiği gibi
(sahip soru sorulmadan ilerlenmesini istedi, 2026-09-27). **Review rule (owner, D105):** Sol (`gpt-6-sol` · high) blocks
only on a **high** finding; at most **3** plan rounds and **4** code rounds. Medium and low findings are fixed or left
with a reason and open no round; a high finding still open after the third plan round or the fourth code round goes to
the owner. **Prompt:** [sw-slice28-prompt.md](sw-slice28-prompt.md). **Main file:** [sw-status.md](sw-status.md).
**Decision:** D109 (highest today D108; if another slice has taken D109 by the time this one is built, the next free
number). **Migration:** none (highest stays `0055`: a reason code is not a database CHECK, and the StepInput schema is a
JSON contract, not a table). **Prerequisite:** slice 26 closed (`142dfa1`), slice 27 recorded (`ddbd76a`). **Type:**
build. **Implementer:** Opus · high. **Review:** full (Sol · high, with the rule above): the slice changes when code
includes a work. **Plan:** Opus 5.5 · high. **Scope:** the comparator part of the full-text reading (new SW27) only.

**Measurement:** `.local/sw-slice28-plan-2026-09-27/`: `comparator_check.py` → `comparator-check.json`,
`comparator-check.txt` (replay and the rejected quote check); `includes_reading.py` → `includes-reading.json`,
`includes-reading.txt` (this session's comparator reading of every slice 27 include, from `includes-27-raw.txt`);
`absent_paths.py` → `absent-paths.json`, `absent-paths.txt`; `definition_check.py` → `definition-check.json`,
`definition-check.txt` (a screen, not the gate, Sol r2); `definition-gate-calibration.json` (the frozen rule and six
calibration definitions of the criterion gate, Sol r2); `target_roles.py` → `target-roles.json`,
`target-roles.txt`. All read stored libraries with `immutable=1` URIs: slice 24a's ten `sw` libraries
(`.local/sw-slice24-campaign-2026-09-26-134050/data-*-sw-*`) and slice 27's five
(`.local/sw-slice27-remeasure-2026-09-27-043237/data-qtre-sw-*`). No model call, no provider request, no network.
Port 8765 and the live library were not touched. One M1 Pro, Python 3.12 arm64 through `uv`.

**Goal:** Slice 27 (D108) failed gate 4 on medicine: 3 serious errors in 10 sampled includes, all three a trial whose
comparison group followed the same calorie restriction as the time-restricted-eating group. The question asks for
"unrestricted eating or usual diet", the criterion had a comparator part (slice 25a, D106), and both reading runs still
labelled that part `present`. After this slice the reading judges a comparator part by what the comparison group
receives, including an addition both groups share, and code tells the reading which part is the comparator. On a
criterion with a comparator part, code no longer excludes at full text by itself: a reading that would have been an
automatic exclusion goes to the queue, so the new comparator rule can move a work from include to the queue but never
out (Sol r1). Quantum criteria have no comparator part, so
nothing code does changes for them.

## What the code does today

Code read on 27 September 2026 at `ddbd76a` (slice 26's `142dfa1` plus the slice 27 result commits).

- **The reading method has no comparator rule.** `methods/deixis-research/references/fulltext-adjudication.md` (five
  lines) defines `present` / `absent` / `unclear`, the future-work rule and slice 26's result rule (`:5`). Nothing
  says how to judge a comparison group. The one sentence that does, "A comparator named as no treatment, usual care or
  an unrestricted alternative is not met by a comparison group that receives something the question's comparator does
  not name" (`criterion-proposal.md:63-66`), is in the criterion proposal's file. The reading step never loads it:
  `skill.RUNTIME_FILES["fulltext_adjudication"]` is `SKILL.md` and `fulltext-adjudication.md` only
  (`tests/test_skill_package.py:83`). The file's text is pinned by `tests/test_skill_package.py:83-89`.
- **The reading does not know which part is the comparator.** `flow._adjudication_plan` (`backend/deixis/workflow/flow.py:3688`)
  sends each part as `{"name", "definition"}` (`:3708-3711`); `_adjudication_call` builds `adjudication_target` from
  them (`:3798-3799`). `frozen_criterion` (`workflow/store.py:597-624`) already returns `question_elements` and
  `required_roles`, but the plan drops them. The StepInput schema allows only `name` and `definition` per part
  (`contracts/research/step-input.schema.json:531-556`, `additionalProperties: false`).
- **The criterion proposal may define the comparator by what it lacks.** Rule 8 (`criterion-proposal.md:34-43`) asks
  for a definition "so that a study … compared with something else, does not meet it", but does not ask the definition
  to name what the comparison group receives, and does not forbid widening it.
- **Code includes on agreement alone.** `adjudication.combine` (`workflow/adjudication.py`) gives `all_parts_verified`
  when both runs label every part `present` with verified quotes; `with_title` (slice 26) withholds that only for a
  protocol title. `_close_adjudication` applies both (`flow.py:3852`, `:3855`). `combine` sees labels, not meaning.
- **A missing part goes to the queue; only an all-negative reading excludes.** With the other parts `present`, a
  comparator labelled `absent` in both runs gives `partial` → `part_without_evidence` → queue kind `confirm_absent`,
  whose question names that part (`workflow/queue.py:197-221`). `criterion_absent` (both runs `not_met`: no part
  `present`, at least one `absent`) derives an exclusion (D85).

## Numbers we have

All from stored data on one M1 Pro; the model behind the stored runs is `gpt-5.6-luna` · medium. A stored run is one
run. The comparator readings below are this plan session's (a model, not blind, not a human check).

1. **The three errors are seven decisions, fourteen runs.** Cell Reports Medicine 2024 (`10.1016/j.xcrm.2024.101801`) is
   `all_parts_verified` in four slice 27 libraries (`detailed`, `quick`, `standard-emb`, `standard-r2`), Alimentary
   Pharmacology & Therapeutics 2025 (`10.1111/apt.70044`) in two (`detailed`, `standard-r1`), the TREATY commentary
   (`10.1093/lifemedi/lnac017`) in one (`standard-r2`; in `quick` the runs disagreed). In all 14 runs the comparator part
   is `present` with a verified quote: "The participants in the control group were provided with control diets and
   instructed to follow their usual eating regimens"; "The control group consumed meals throughout the day without time
   restrictions (over 12 h daily)"; "daily-calorie-restriction group without time restriction". Every rationale speaks of
   timing only ("The comparator group is explicitly described as eating without time restriction"). In the 24a libraries
   none of the three was read (no full text or not in the pool).
2. **The shared restriction was on the pages shown.** In each of the 14 calls the passages shown held 18 to 24 sentences
   naming calories, energy or a restriction, among them the one that settles the part: "three groups, all following a
   hypocaloric Mediterranean-type diet" (the abstract's Methods, `apt.70044`); "All participants were instructed to
   follow a diet that represented a 25% calorie reduction" (TREATY, all 7 pages shown); "isocaloric-restricted feeding"
   in the abstract of `xcrm` (its p. 2 gives about 25% caloric restriction for all four arms). The loss is in the
   reading, not in page selection.
3. **Criterion wording.** All 5 slice 27 criteria have the comparator part (D108). Two of the five definitions admit a
   comparison group that is not the named comparator: `standard-r2` "a group instructed to eat without time restriction
   **or** to continue its usual diet", `quick` "… **or a comparable non-time-restricted dietary condition**". The other
   three name the comparator (`standard-emb`: "rather than a specified alternative dietary intervention"), and errors
   still occurred under all three. So the definition explains part of it; the reading explains all of it.
4. **All 24 unique slice 27 includes** (49 `all_parts_verified` decisions; `includes-reading.txt`), by this session's
   reading against slice 27's reference rule (same calorie restriction in both arms: a different comparator; same
   exercise or same isocaloric, weight-keeping diet in both arms: the named comparator):
   - comparator not met: **8 unique, 13 decisions**: the three gate 4 errors, two more trials that add TRE to the same
     calorie restriction (`10.1001/jamanetworkopen.2023.3513`, `10.1002/osp4.702`), one where every arm is
     calorie-restricted (`10.1186/s12916-025-04182-z`), and two against an active diet programme
     (`10.3390/nu17142360`, `10.1007/s00125-026-06762-x`). The five outside the gate 4 sample sit in `detailed` and
     `quick`, which gate 4 did not sample.
   - comparator met: 11 unique, 29 decisions (among them Kotarsky 2021, the same exercise in both arms).
   - edge, same isocaloric diet in both arms: 3 unique, 4 decisions (TRIM, `10.1002/oby.70270`, is an R unit).
   - edge, the same usual-care diet education in both arms (IMIFASTT): 2 unique, 3 decisions.
5. **Replay of the reading's code** (`comparator-check.txt`). Every current full-text decision this stage wrote, recomputed
   from its two runs' stored proposals with the product's `run_view`, `combine` and `with_title`: slice 27, **294 of 294**
   equal the stored code; slice 24a, 452 of 455 equal and the 3 others are slice 26's known `protocol_title` changes
   (stored before slice 26; D107). Quantum: 304 of 304 equal.
6. **A code check on the quote does not work** (`comparator-check.txt`, `includes-reading.txt`). The obvious
   deterministic check (withhold an include when a run's comparator quote holds none of the comparator's words or cue
   phrases) would withhold 39 of 49 medicine includes: 8 of the 13 errors, but also 24 of the 29 correct ones, 4 of 4
   isocaloric and 3 of 3 usual-care edges. It misses `xcrm` in all four libraries, because that quote literally says
   "usual eating regimens". Authors write "maintained their dietary habits", "continue their usual eating habits"; a
   phrase list cannot tell those from a restricted control. Rejected (option A4).
7. **The comparator marker, prototyped** (`target-roles.txt`). Marking the part a `comparator` question element names
   (when `comparator` is a required role) on every stored reading StepInput: 625 of 625 quantum and 305 of 305 slice 24a
   medicine StepInputs come out byte-identical (no role), 614 of 614 slice 27 medicine StepInputs differ in exactly one
   part.
8. **The exclusion path** (`absent-paths.txt`). Slice 27 has 10 `criterion_absent` decisions (294 in all); in all 10
   the comparator is `absent` in at least one run, and in all 10 each run also has another `absent` part. The guard of
   decision 3.3 (Sol r1) withholds every `criterion_absent` on a criterion with a comparator part, so it changes these
   **10 of 294** stored slice 27 codes (to `comparator_exclusion_withheld`, queue) and 0 elsewhere: 24a and quantum have
   no comparator part. The first draft's narrower guard (comparator the only `absent` part in a run) changed 0 of 10,
   and missed the case Sol named: a comparator moving `present` → `absent` while another part is `absent` in both runs
   turns `part_without_evidence` into `criterion_absent`. One slice 27 reading is `fulltext_runs_agree_unresolved`
   (every part `unclear`), the other shape a new `absent` could turn into an exclusion.
9. **The criterion-definition gate** (Sol r1, r2). A word-list screen (`definition_check.py`: every alternative of the
   comparator element's words present, none of `comparable`, `similar`, `equivalent`, `or other`, `any other`) passes
   3 of 5 stored slice 27 definitions, but Sol r2 showed it is not sound: "The paper must compare time-restricted eating
   with unrestricted eating or usual diet or a calorie-restricted diet" passes it. A structural check (split the
   definition into its alternatives, require each to be one of the question's terms) is not sound either, and this plan
   does not use it: rule 8 now **requires** the definition to name what does not meet the part ("… such as the same
   restriction the intervention group follows, does not meet it"), so a split at "or" / "such as" produces exactly the
   excluded condition as an "alternative"; telling an exclusion clause from an admitted alternative needs a reading of
   the sentence, not a word list. The gate is therefore a **recorded two-reader blind reading** with the rule frozen
   here and in `definition-gate-calibration.json` before any run:
   > A comparator definition PASSES only when all three hold: (a) every comparison condition it admits is one the
   > question's comparator words name, or a plain restatement of one (for "unrestricted eating or usual diet":
   > unrestricted, ad libitum, usual, habitual or normal eating or diet, a usual-diet control), possibly with qualifiers
   > that only say what the comparison group must not receive in addition; (b) it admits no further condition, whether
   > by "or", a list, "such as", "including", "e.g.", "comparable", "similar", "other" or an example; a clause that says
   > a group receiving something else does not meet the part is an exclusion, not an alternative; (c) it names what the
   > comparison group receives, not only that it lacks the thing sought ("eats without time restriction" alone fails).
   > Otherwise it FAILS.

   Six calibration definitions with frozen verdicts (this plan session's reading of the rule): the five stored slice 27
   definitions, `detailed`, `standard-emb`, `standard-r1` **pass** and `quick` (admits "a comparable non-time-restricted
   dietary condition"), `standard-r2` (admits "a group instructed to eat without time restriction") **fail**, i.e.
   **3 of 5** stored pass; and Sol r2's counter-example **fails** (it passes the word-list screen).

What the numbers cannot show: whether the new method text moves the model (the dry run, decision 5.3, reads the three
errors, four controls and one edge once each); how many queue rows it adds in a fresh research; whether the
isocaloric edge stays included.

## SW items

- **SW27** (new, build): "The full-text reading meets the comparator part with a comparison group that shares the
  intervention's restriction". Closes in this slice (D109) with the replay and the dry run; the implementer adds the entry
  to `search-workflow-review-2026-09-18.md`.
- Out of scope, waiting in order: the medicine re-measurement after this slice (owner's decision), SW18, 24b, SW19,
  SW20, SW24, slice 23, D96 (b)–(c), SW6.6, the gate 2 loss at the PDF stage (D108).

## Decisions

1. **One slice, three small pieces on one part.** The reading method (2), the comparator marker and the exclusion guard
   in code (3), the criterion proposal's rule (4). One commit after Sol's review.

2. **The reading judges what the comparison group receives (A1).** `fulltext-adjudication.md`, after the result rule of
   line 5, the meaning of: "A part marked `"role": "comparator"` is `present` only when a passage shows that the
   comparison group receives what the part names; quote that passage. Judge the comparison group by everything it
   receives, not only by what it lacks: a group described only as not receiving the thing sought meets the part only
   when nothing shown makes it something else. When the passages show that both groups receive the same added
   treatment, restriction or prescribed regimen, and that addition makes the comparison group something the part does
   not name, label the part `absent`: a comparator named as unrestricted or usual X is not met when both groups follow
   the same restriction of X. An addition that leaves what the part names as it was does not matter: the same Y given to
   both groups, when the part names only X. With several arms, the part is met when an arm that receives what the part
   names is compared with an arm that receives the thing sought. When the passages do not show what the comparison
   group received, label it `unclear`." No field word (time, eating, calories, weight, a trial's name). The final wording
   is the implementer's; the meaning, the "everything it receives" test, the shared-addition line with its two sides
   and the `absent` / `unclear` split are kept. It is a runtime file, so `skill_package_hash` changes. A part without
   the marker is read exactly as today.

3. **Code: the marker, and no new exclusion (A1, C1).**
   1. **Marker.** In `flow._adjudication_plan` the part that a `comparator` question element of the frozen criterion
      names gets `"role": "comparator"`, only when `comparator` is in the criterion's `required_roles`; every other part,
      and every part of a criterion without that role, is sent exactly as today (so quantum and older criteria are
      byte-identical, number 7). One pure helper in `workflow/adjudication.py`, `mark_comparator(parts, question_elements,
      required_roles) -> list[dict]`, used by the flow and the replay; it is `target_roles.py::mark`.
      `contracts/research/step-input.schema.json` gains an optional `role` on `adjudication_target.parts` items, `enum:
      ["comparator"]`. The output contract `deixis.fulltext_adjudication.v1` does not change. A plan stored before this
      slice (a resumed run) has no marker and is read as it was frozen.
   2. **The label stays the model's; the decision stays code's.** No lexical check on the quote (number 6). With some
      other part `present`, a comparator `absent` in both runs is `part_without_evidence` → queue `confirm_absent`;
      `absent` in one run is `fulltext_runs_disagree`. Both exist today.
   3. **Guard (C1, revised after Sol r1).** The new rule can move the comparator from `present` to `absent` or `unclear`.
      Whenever the comparator was a run's only `present` part, that turns `partial` into `not_met`, and two such runs
      into `criterion_absent`: an automatic exclusion the comparator label decided. The test "would the outcome still
      be `criterion_absent` if the comparator were `present`" is always no (a `present` part makes a run `partial`), so
      the rule is simply: **on a criterion with a marked comparator part, `criterion_absent` is never written**; code
      writes `comparator_exclusion_withheld` (full text, `unresolved`, decided by code, next step the queue) with note
      `comparator_exclusion_withheld:criterion_absent:<part>`. Every other code passes through. A criterion without a
      comparator part (quantum, older criteria) is untouched: D85's exclusion of two all-negative runs stands there. One
      pure helper beside `with_title`, `with_comparator(code, part) -> (code, note)`; the flow applies `combine` →
      `with_comparator` → `with_title` (on a comparator criterion a protocol-titled all-negative reading therefore
      shows `comparator_exclusion_withheld`, still a queue row; `with_title` keeps acting on `all_parts_verified`).
      `ReasonCode("comparator_exclusion_withheld", "fulltext", "unresolved", "code", "human_queue")` in
      `reason_codes.py` with its comment; `FRESH_MODEL_CODES` gains it; `queue.KIND_OF` maps it to the existing
      `confirm_absent`, and `_question` names the comparator part for this code. Screen: only the reason text,
      `queueReasons.comparator_exclusion_withheld` "Both runs found parts missing, but the criterion has a comparison
      group, so the reading did not exclude this work." and its Turkish in `i18n.ts`; no new kind, no new component.
      Cost: the 10 slice 27 exclusions of number 8 would have been queue rows (2 per research on average); a person
      answers them. The owner can lift the guard after a measurement shows the comparator reading holds.
   4. **What does not change.** `combine`, `verdict`, `run_view`, `proposals_of`, page selection, the reading budget, the
      abstract stage, `legacy`, every stored decision (the rules act on the next reading only), the queue's kinds.

4. **The criterion proposal names what the comparison group receives (B1).** `criterion-proposal.md` rule 8, the meaning
   of: "The comparator part's `definition` names what the comparison group must receive, in the question's words, not
   only that it does not receive the thing sought, and adds no alternative the question does not name (no 'or a
   comparable …'). It says that a comparison group that also receives an addition making it something other than the
   named comparator, such as the same restriction the intervention group follows, does not meet it." The hard case at
   `:63-66` gains "or the same added treatment or restriction as the intervention group". The consensus, the four
   question-element checks and the contract `criterion_proposal.v2` do not change; a stored criterion is not rewritten.
   Runtime file: `skill_package_hash` changes (once for both files).

5. **Acceptance** (scripts and outputs under `.local/sw-slice28-acceptance-<YYYY-MM-DD>/`).
   1. Full pytest (the known single failure apart: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`),
      `npm run build`, `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest
      migration `0055`; `uv.lock` unchanged; the new `skill_package_hash` in the final message.
   2. **Replay** (offline, read-only). (a) Reading codes: as `comparator_check.py`, but through the product's
      `combine` → `with_comparator` → `with_title`, over slice 24a's ten and slice 27's five `sw` libraries: slice 27
      284 of 294 equal, with exactly the 10 stored `criterion_absent` changing to `comparator_exclusion_withheld`
      (number 8), slice 24a 452 of 455 equal with exactly the 3 known protocol changes, quantum 304 of 304. (b) Marker: as `target_roles.py`, through the product's `mark_comparator` on every stored reading
      StepInput's parts: 625 quantum and 305 slice 24a medicine byte-identical, 614 slice 27 medicine with exactly the
      comparator part marked. Anything else: stop, row 28 `uygulanıyor: replay failed`, and write the difference.
   3. **Dry run (D1), 22 planned calls, at most 25 model sessions**, justified because a method sentence cannot be
      replayed without a model. Connection `codex`, `gpt-5.6-luna`, effort `medium`, `DEIXIS_CODEX_HOME` from the live
      data directory, own data directories (copies of the three libraries named below), no provider request, port 8765
      untouched. The script counts every model session it opens (a first call, a schema repair, a re-send after
      `client_timeout` or a rate limit) from the stored steps and never opens a 26th; reaching the cap before the 22
      planned calls are answered is a stop (row 28 `uygulanıyor: dry run cap reached; sahip kararı`).
      - **Reading, 16 calls** (8 works × 2 runs) through `ResearchFlow._model_step` (`fulltext_adjudication`), each work
        shown the passages of its latest stored reading StepInput and its stored criterion with the product's marker,
        with the new method text; each pair verified and combined as `_close_adjudication` does (`proposals_of`,
        `run_view`, `combine`, `with_comparator`, `with_title`) and reported beside the stored code; nothing is written as
        a decision. Errors: `xcrm` and TREATY (copy of slice 27 `standard-r2`), `apt.70044` (copy of slice 27
        `standard-r1`). Medicine controls (copy of `standard-r1`): Kotarsky 2021 `10.14814/phy2.14868` (same exercise in
        both arms), `10.3390/nu16142187` (ad libitum control), `10.3390/nu13041155` (usual eating). Edge (same copy):
        TRIM `10.1002/oby.70270`. Quantum control (copy of slice 24a `q1-sw-standard-r1`): `10.1038/s41598-024-70114-1`.
      - **Criterion, 6 calls:** three `criterion_proposal` calls for the medicine question and three for the quantum
        question (slice 24a's wording) with the new method text, each consensus through `criterion.consensus`, as slice
        25a's dry run did (`.local/sw-slice25-acceptance-2026-09-26/dry-run/run.py`).
      - **Stop rules.** Each of the four controls is compared with its stored decision per part and combined; the stored
        state of all four is `all_parts_verified` (both runs `present` with a verified quote on every part). Any
        deviation stops: a combined code other than `all_parts_verified`, any part other than `present` in either run,
        a `present` quote that does not verify, a run with no valid output. The quantum control's `adjudication_target`
        carrying any `role` stops (a code fault). Criterion: any quantum proposal listing a question element, or a
        quantum consensus with `required_roles` other than `[]`, stops; a medicine consensus with `required_roles` other
        than `["comparator", "population"]` stops. Stop means row 28 `uygulanıyor: dry run control changed; sahip
        kararı`, with each deviating part's labels, quotes and rationales beside the stored ones. A quota or rate-limit
        error → stop and write where; one `client_timeout` → resume once after 10 minutes; never another model.
      - **Effect conditions (Sol r1).** Checked after all 22 calls are answered and no stop fired; they do not stop the
        run, they decide whether the slice closes as implemented.
        (i) *Errors:* at least **2 of the 3** errors leave `all_parts_verified`, each with the comparator part other
        than `present` in at least one run (stored: 0 of 3; 7 of 7 decisions `all_parts_verified`, 14 of 14 runs
        `present`). A work that leaves `all_parts_verified` only for another part does not count.
        (ii) *Criterion (revised after Sol r2):* the three new medicine comparator definitions are read by **two
        readers**, separate model sessions (Claude Sonnet, as slice 27's second reader), each blind to the other and to
        which definition is new: each gets one packet with the question, the frozen rule of number 9 and nine
        definitions (the three new ones and the six calibration items) in an order shuffled with seed `2809270`, and
        answers PASS or FAIL with one sentence per item, stored as `definition-gate-r1.jsonl` and
        `definition-gate-r2.jsonl`. The reading is valid only when both readers match all six frozen calibration
        verdicts; an invalid reading is not repeated and counts as the condition failing (owner decides). The condition
        holds when **both readers PASS all 3** new definitions; a disagreement on any new definition is a FAIL. The
        consensus's comparator definition is one of the three (its base run), so it is covered. The word-list screen is
        run and reported beside it, never as the gate.
        If (i) or (ii) is not met, the slice does not close as implemented: the code and tests stay in the tree
        uncommitted, D109 is written as "implemented, not effective in the dry run" with the numbers, and row 28 becomes
        `sahip kararı bekliyor: dry run not effective` with which condition failed. The owner decides.
      - **Reported, not a condition:** the comparator rationales of the three errors; TRIM's code and comparator labels;
        the three medicine comparator definitions and each one's check result.

6. **Documents.** D109 at the top of `docs/decisions.md` (decision, replay and dry-run numbers, Limits). In
   `docs/product/search-workflow-review-2026-09-18.md`: the new SW27 entry (finding: numbers 1–4 in short; status:
   implemented in slice 28 (D109); Return to: the full-text reading's comparator part). Row 28 of `sw-status.md`:
   `uygulandı, inceleme bekliyor` with the headline numbers. Nothing else in `sw-status.md`.

## Frozen expectations

Written before any code. One machine, one model; the dry run is one run of each call.

- Replay (a): slice 27 284 of 294 with exactly the 10 `criterion_absent` → `comparator_exclusion_withheld`, slice 24a
  452 of 455 with the 3 known protocol changes, quantum 304 of 304. Measured (numbers 5 and 8), so any other result
  means the product differs from the prototype.
- Replay (b): 625 + 305 identical, 614 with exactly one part marked. Measured (number 7).
- Dry run, errors: the model keeps **2 or 3 of 3** out of `all_parts_verified` on the comparator part; fewer is the
  effect condition (i) failing, not a surprise to report (slice 26's sentence moved 3 of 3 protocols, D107). `apt.70044` and TREATY are the likelier two: their shown pages say the
  restriction applies to all groups in one sentence; in `xcrm` it is spread over several.
- Dry run, controls: 4 of 4 unchanged, per part and combined. Kotarsky 2021 is the one at risk (the shared exercise);
  any deviation is a stop.
- Dry run, TRIM (edge): either way. If both runs keep the comparator `present` it stays included. If not, the guard
  guarantees only that code does not exclude it on this criterion: it becomes a queue row (`part_without_evidence`,
  `fulltext_runs_disagree` or `comparator_exclusion_withheld`), and a person can still exclude it. Reported as a cost
  against R, not a failure.
- Dry run, criterion: quantum `required_roles = []` and 0 of 3 proposals listing a role; medicine `["comparator",
  "population"]`; both blind readers PASS 3 of 3 new medicine comparator definitions and match all 6 calibration verdicts (effect
  condition (ii)).
- Not in this slice, for the next medicine measurement: of the 13 slice 27 decisions whose comparator this session reads
  as not met, most should reach the queue; of the 29 met, none should move. Not measured here.

## Owner choices (27 September 2026: A1, B1, C1, D1, E1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; every proposed option is taken. The alternatives stay for the record. None
needs the owner's money or hands.

- **A — The reading's mechanism.** Proposed **A1**: a method sentence scoped to a part code marks as the comparator
  (decisions 2 and 3.1); no output-contract change. *A2*: the sentence without the marker; the model guesses which part
  is the comparator, and a quantum part could be read under a rule meant for comparators. *A3*: output contract
  `fulltext_adjudication.v2` with a per-comparator field ("what the comparison group receives" quote plus "shared with
  the intervention group" list) that code checks; changes the contract, fixtures, the queue and the screen, and the field
  is still the model's reading. *A4*: a lexical code check on the comparator quote; measured, it withholds 24 of 29
  correct includes and misses `xcrm` (number 6).
- **B — The criterion proposal.** Proposed **B1**: rule 8 asks the definition to name what the comparison group receives
  and forbids widening (decision 4). *B2*: leave the proposal as is; 2 of 5 slice 27 definitions widen the comparator.
- **C — The exclusion path.** Proposed **C1** (revised after Sol r1): on a criterion with a comparator part code never
  writes `criterion_absent`; it writes `comparator_exclusion_withheld` (decision 3.3), so the new rule never excludes a
  work; cost 10 more queue rows over slice 27's five researches. *C1-narrow* (the first draft): withhold only when the
  comparator is a run's only `absent` part; Sol r1 showed it lets a `present` → `absent` change exclude. *C2*: no
  guard; D85 already lets two all-negative runs exclude, and a comparison group that
  shares the restriction does fail the criterion, but the passages are a selection and the rule is new.
- **D — Live check.** Proposed **D1**: the 22-call dry run of decision 5.3 (cap 25 sessions). *D2*: offline only; the
  method text stays unmeasured. *D3*: a full medicine research; that is the next measurement, not this slice.
- **E — The isocaloric edge.** Proposed **E1**: no special case; TRIM is watched in the dry run and any move is recorded
  as a cost (it goes to the queue, not out). *E2*: a method clause saying a shared diet that keeps intake unchanged is not
  a restriction; that is field wording in a method file that must work for any field.

## What the owner does

Nothing is a question. Only if Luna's quota runs out during the dry run: wait for it to renew (no money).

## Global constraints

- **Behaviour changes in two places only:** the full-text reading of a comparator part (method sentence, marker, guard)
  and the criterion proposal's comparator definition. Abstract stage, ranking, fetching, queries, the answer, `legacy`
  and `pdf_collection` do not change. No migration.
- **Nothing new is excluded by code.** The marker and the method can move a work from include to the queue; the guard
  withholds every automatic full-text exclusion on a criterion with a comparator part. A person can still exclude.
- **Quantum does not change in code**: no comparator role, so its StepInput parts, codes and queue are byte-identical;
  only the method files and `skill_package_hash` reach it, and the dry run checks one quantum reading and three quantum
  proposals.
- **Evidence contract.** No reading is invented or edited; stored proposals, quotes and decisions stay as written.
- **Every number** with its sample size, machine and model; one run is one run; a model reading is not a human check.
- **Port 8765 and the live library are off limits.** Model never switched, no silent fallback.
- **The owner's files** (`TODO.md`, `.vscode/`, `scripts/local_index.py`) are not changed or staged. Only row 28 of
  `sw-status.md` is touched.

## Task outline

1. Row 28 `uygulanıyor`.
2. Reading method sentence (decision 2) and criterion rule (decision 4), their tests.
3. `mark_comparator`, the schema's optional `role`, `_adjudication_plan` (3.1).
4. `with_comparator`, the reason code, `FRESH_MODEL_CODES`, `_close_adjudication`, queue mapping and question, reason
   text (3.3).
5. Tests (below); fixtures stay SYNTHETIC.
6. Acceptance (decision 5): checks, replay, dry run.
7. Documents (decision 6); row 28 `uygulandı, inceleme bekliyor`.

**Tests** (all SYNTHETIC, no network, no model):
- `tests/test_adjudication.py`: `mark_comparator` marks exactly the named part when `comparator` is required, and
  nothing when the role is not required, when there are no elements, or when the element names no sent part;
  `with_comparator` turns `criterion_absent` into `comparator_exclusion_withheld` whenever a comparator part is given
  (the comparator the only `absent` part, another part `absent` in both runs, the comparator `unclear` in both runs),
  passes `criterion_absent` through when there is no comparator part, and passes every other code through.
- `tests/test_adjudication_flow.py`: a reading of a criterion with a comparator element sends the marker on that part
  only; a criterion without one sends parts byte-identical to today; both runs with the comparator `absent` and every
  other part `unclear` write `comparator_exclusion_withheld` (queue, no `excluded` selection); **Sol r1's case:** a
  run pair where another part is `absent` in both runs and the comparator is `absent` in both (`present` nowhere) also
  writes `comparator_exclusion_withheld`, while the same pair on a criterion without a comparator element still writes
  `criterion_absent` and derives `excluded`; a comparator `absent` with other parts `present` writes
  `part_without_evidence` (unchanged); a protocol title on an all-negative comparator reading writes
  `comparator_exclusion_withheld`; a person's decision is never overwritten.
- `tests/test_queue.py` / `tests/test_queue_api.py`: the row's kind is `confirm_absent`, its question names the
  comparator part, its answers work and undo.
- `tests/test_contracts.py` (or the StepInput schema test): a part with `role: "comparator"` validates; any other
  `role` value does not.
- `tests/test_skill_package.py`: the new method texts.
- The determinism replay stages (`tests/determinism_stages.py`) stay byte-identical for inputs without a comparator
  element; any fixture that has one changes only by the marker, listed in the final message.
- Playwright: none new unless the queue's reason text for the new code has no case; then one `confirm_absent` row with
  the new reason at 1440 and 390 px.

## Acceptance conditions

Decision 5's items; full pytest (known single failure apart), build, lint ≤ 17 warnings, Playwright, `git diff
--check`; highest migration `0055`; `uv.lock` unchanged; `skill_package_hash` changed and written; replay (a) and (b)
exactly as frozen; dry run within its stop rules.

## Not in this slice

- A medicine re-measurement, gate 4 again, 24b; SW18–SW20, SW24, slice 23, D96 (b)–(c), SW6.6.
- A lexical check on the comparator quote (A4); an output-contract field (A3); a population rule (the population part
  had no serious error in slice 27's sample).
- Excluding by the comparator alone (C2); an isocaloric clause (E2).
- Re-reading any stored decision; re-running any 24a or 27 research.

## Not measured

Whether the new sentences move the model beyond the dry run's 22 calls; how many slice 27-like includes reach the
queue in a fresh research (13 of 49 are this session's reading, not a measurement of the product); how many exclusions the guard
withholds in a fresh research (10 of 294 stored slice 27 decisions), and how a person answers them; how the rule reads a comparator in a field other
than medicine (quantum has none; a field with "standard practice" comparators was not seen); whether TRIM-like
isocaloric trials stay included; the second reader's agreement with this session's reading of the 24 includes.

## Sol r1–r2 findings and what changed

Sol (`gpt-6-sol` · high), plan round 1, 27 September 2026: "hazır değil", two high findings, one medium
(`.local/sw-slice28-plan-2026-09-27/sol-plan-answer-r1.md`).

- **High 1 — the guard let the comparator decide an exclusion.** It fired only when the comparator was a run's only
  `absent` part; with another part `absent` in both runs, a comparator moving `present` → `absent` still turned
  `part_without_evidence` into `criterion_absent`. **Changed:** decision 3.3 now withholds every `criterion_absent` on a
  criterion with a marked comparator part (asking "would it still be `criterion_absent` with the comparator `present`?"
  always answers no), code `comparator_exclusion_withheld`, queue `confirm_absent`. Number 8, replay (a) (slice 27 now
  284 of 294 with exactly the 10 stored `criterion_absent` changing), the frozen expectations, choice C (C1 revised,
  the first draft kept as C1-narrow), the global constraint and the tests (Sol's case explicitly) follow. Criteria
  without a comparator part, quantum among them, keep D85's exclusion unchanged.
- **High 2 — the dry run could pass with no effect.** The errors and the criterion wording were only reported.
  **Changed:** decision 5.3 adds two effect conditions: (i) at least 2 of the 3 errors leave `all_parts_verified` with
  the comparator not `present` in at least one run; (ii) 3 of 3 medicine proposals and the consensus pass a mechanical
  definition check (number 9, new `definition_check.py`; stored baseline 3 of 5; replaced after Sol r2, below). If either fails, the slice does not
  close as implemented: D109 records "implemented, not effective in the dry run", row 28 becomes `sahip kararı
  bekliyor: dry run not effective`, and the owner decides. The prompt says the same.
- **Medium — TRIM.** The frozen expectation no longer says TRIM is "never out": the guard guarantees only that code does
  not exclude it on this criterion; a person still can.
- **Medium — the prompt's precondition** (plan not yet committed): kept; the plan is committed before the build.

Sol, plan round 2, 27 September 2026 (the last plan round; `.local/sw-slice28-plan-2026-09-27/sol-plan-answer-r2.md`):
all r1 findings closed, one new high.

- **High — the criterion gate could miss the widening it targets.** `definition_check.py` checks only that the
  comparator's words are present and that five phrases are absent, so "… unrestricted eating or usual diet or a
  calorie-restricted diet" passes. **Changed:** a structural check was considered and is not sound here (number 9:
  the new rule 8 makes every definition carry an exclusion clause that a split at "or" / "such as" reads as an
  alternative). Effect condition (ii) is now a recorded two-reader blind reading (two separate model sessions) under a
  rule frozen in number 9 and `definition-gate-calibration.json` before the run, with six calibration items and frozen
  verdicts (the five stored definitions, 3 pass and 2 fail, and Sol's counter-example, fail); a reading that misses any
  calibration verdict is invalid and counts as the condition failing; any disagreement on a new definition is a FAIL.
  The word-list screen stays as a reported number only. The prompt says the same.

### Sol r3

r2's high finding closed. One new high: the prompt's rule 4 (every live call Luna, cap 25) and the two Sonnet readers of effect condition (ii) conflicted. Fixed as wording by the coordinator without a fourth round (the slice 25 r3 precedent): rule 4 and its cap cover product model calls only; the two readers are subagent sessions launched with the Agent tool (`model: sonnet`), exactly two, logged separately, outside the Luna cap.
