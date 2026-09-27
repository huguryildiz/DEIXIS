# Task: SW slice 28: the full-text reading checks what the comparison group actually receives

**Run this prompt only when row 28 of `docs/product/sw-status.md` names A1, B1, C1, D1 and E1** (its status reads
`plan …; A1, B1, C1, D1, E1 önerildiği gibi …`). If row 28 names a different answer to any of A–E, or none, stop at
once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice28-comparator-reading.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice28-comparator-reading.md` and check that
`git status --porcelain docs/product/sw-slice28-comparator-reading.md docs/product/sw-slice28-prompt.md` prints nothing.
If the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message.
Do not pull, fetch or change branches to get it. The plan is the only source of truth for this slice. Where it departs
from the slice 27 finding's wording (the new rule sends a work to the queue and never excludes by itself; no lexical
check on the quote; no isocaloric clause), the plan wins. List every place where you used your own judgement.

**Which part to run.** Read row 28.
- Row 28 is `plan` or `dosya hazır` and names the owner's answers without `uygulanıyor`, `uygulandı` or `kapandı`: run
  the build below.
- Row 28 is `uygulanıyor`: an earlier run stopped; read the working tree, finish, never start over by discarding
  changes. If it reads `uygulanıyor: replay failed`, `uygulanıyor: dry run control changed; sahip kararı` or
  `uygulanıyor: dry run cap reached; sahip kararı`, stop and change nothing: the owner decides.
- Row 28 is `uygulandı, inceleme bekliyor`, `kapandı` or `sahip kararı bekliyor: …`: stop and change nothing.
- Anything else: stop and change nothing.

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. `git add` nothing (not
   even `-N`). The owner's working-tree files stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py`, and
   anything else that is not this slice's. Only row 28 of `sw-status.md` is touched. In your final message list every
   file you created or changed (from `git status --porcelain`, minus those).
2. **Review rule (owner, D105).** Sol (`gpt-6-sol` · high) blocks only on high-severity findings: at most 3 plan rounds
   and 4 code rounds. You do not run the review; you leave the tree ready for it.
3. **Port 8765 and the live library are off limits.** The dry run uses its own data directories under `.local/`; from
   the live data directory only `codex-home` is used, through `DEIXIS_CODEX_HOME`. No provider request anywhere.
4. **Model.** This rule and its cap cover the product's model calls (the dry run through DEIXIS adapters); the two blind readers of effect condition (ii) are not product calls and are outside it: they are two subagent sessions you launch with the Agent tool, `model: sonnet`, one packet each, counted and logged separately (exactly two; a reader that fails to answer is an invalid reading, not re-run). Every live product call: connection `codex`, `requested_model` `gpt-5.6-luna`, `reasoning_effort` `medium`; 22
   planned calls and **at most 25 model sessions in total**, schema repairs and re-sends included (plan decision 5.3);
   never open a 26th, and reaching the cap first is a stop (row 28 `uygulanıyor: dry run cap reached; sahip kararı`). On
   a quota or rate-limit error stop and write where; on `client_timeout` resume once after 10 minutes; never switch
   model or connection.
5. **Python:** `PYTHONPATH=backend uv run pytest …` and `PYTHONPATH=backend:. uv run --no-sync python …`, native arm64.
   Scripts that read stored libraries use `immutable=1` URIs.
6. **Words.** Every number with its sample size, machine and model; one run is one run. A reading by you or a model is a
   model reading, never a human verification.

## Build

1. **Row.** `sw-status.md` row 28: `uygulanıyor`.
2. **Reading method** (plan decision 2): `methods/deixis-research/references/fulltext-adjudication.md`, after the result
   rule: a part marked `"role": "comparator"` is `present` only when a passage shows the comparison group receives what
   the part names (quote it); judge the group by everything it receives, not only by what it lacks; a shared addition
   that makes the comparison group something the part does not name gives `absent` (a comparator named as unrestricted
   or usual X is not met when both groups follow the same restriction of X), a shared addition that leaves what the part
   names as it was does not matter; with several arms, one arm receiving what the part names compared with an arm
   receiving the thing sought meets it; `unclear` when the passages do not show what the comparison group received. No
   field word. The plan's meaning is kept; the final wording is yours. Update `tests/test_skill_package.py`.
3. **Criterion rule** (plan decision 4): `methods/deixis-research/references/criterion-proposal.md` rule 8: the
   comparator's definition names what the comparison group must receive, in the question's words, not only the absence
   of the thing sought, adds no alternative the question does not name, and says that a comparison group that also
   receives an addition making it something other than the named comparator does not meet it; the hard case at `:63-66`
   gains "or the same added treatment or restriction as the intervention group". Consensus, checks and contract
   unchanged.
4. **Marker** (3.1): `backend/deixis/workflow/adjudication.py` `mark_comparator(parts, question_elements,
   required_roles) -> list[dict]` (plan's `target_roles.py::mark`: the part a `comparator` element names gets `"role":
   "comparator"` only when `comparator` is in `required_roles`; everything else untouched and in order).
   `backend/deixis/workflow/flow.py` `_adjudication_plan` (`:3708-3711`) applies it to `sent` with the frozen criterion's
   `question_elements` and `required_roles`. `contracts/research/step-input.schema.json` (`:531-556`): optional `role` on
   `adjudication_target.parts` items, `enum: ["comparator"]`. The output contract does not change.
5. **Guard** (3.3, revised after Sol r1): `with_comparator(code, part) -> tuple[str | None, str | None]` beside
   `with_title`: when `code` is `criterion_absent` and `part` (the marked comparator part) is not None, return
   `("comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:<part>")`; otherwise pass through
   with no note. On a criterion with a comparator part code therefore never writes `criterion_absent`, whatever the
   other parts say (Sol r1: a comparator moving `present` → `absent` while another part is `absent` in both runs must
   not exclude). `_close_adjudication` (`flow.py:3852-3855`) finds the marked part from the plan's parts and applies
   `combine` → `with_comparator` → `with_title` (a note from either helper goes through the existing write path; every
   other code's write stays byte-identical). `backend/deixis/domain/reason_codes.py`:
   `ReasonCode("comparator_exclusion_withheld", "fulltext", "unresolved", "code", "human_queue")` with a comment (both
   runs found parts missing, but on a criterion with a comparator part code does not exclude; a person answers).
   `FRESH_MODEL_CODES` gains it. `backend/deixis/workflow/queue.py`:
   `KIND_OF["comparator_exclusion_withheld"] = "confirm_absent"`; `_question` names the comparator part for this code.
   `apps/web/src/labels.ts` `queueReasons.comparator_exclusion_withheld` ("Both runs found parts missing, but the
   criterion has a comparison group, so the reading did not exclude this work.") and its Turkish in
   `apps/web/src/i18n.ts`. Read `.impeccable.md` first; no new kind, component or dependency.
6. **Tests** (plan "Tests"): `tests/test_adjudication.py`, `tests/test_adjudication_flow.py`, `tests/test_queue.py`,
   `tests/test_queue_api.py`, the StepInput schema test, `tests/test_skill_package.py`, with Sol r1's case (another
   part and the comparator `absent` in both runs, nothing `present`: `comparator_exclusion_withheld` on a comparator
   criterion, `criterion_absent` and `excluded` without one); fixtures with a comparator element
   change only by the marker, and each such change is listed in your final message. Playwright only if the new reason
   text has no case (one `confirm_absent` row at 1440 and 390 px). Every fixture stays SYNTHETIC and field-independent.
   No test touches the network.
7. **Acceptance** (plan decision 5), scripts and outputs under `.local/sw-slice28-acceptance-<YYYY-MM-DD>/`:
   - Full pytest (report "the known single failure apart, the rest of the full run passed" with counts; the known one is
     `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
     `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest migration `0055`;
     `uv.lock` unchanged; the new `skill_package_hash` in your final message.
   - **Replay (a):** as `.local/sw-slice28-plan-2026-09-27/comparator_check.py`, but through the product's `combine` →
     `with_comparator` → `with_title` with each library's marked part: slice 27 284 of 294 equal, with exactly the 10
     stored `criterion_absent` changing to `comparator_exclusion_withheld`; slice 24a 452 of 455 equal with exactly the
     3 known `protocol_title` changes in `qtre-sw-detailed-r1`; quantum 304 of 304. **Replay (b):** as `.local/sw-slice28-plan-2026-09-27/target_roles.py`, through the product's
     `mark_comparator`: 625 quantum and 305 slice 24a medicine StepInputs byte-identical, 614 slice 27 medicine with
     exactly the comparator part marked. Anything else: stop, row 28 `uygulanıyor: replay failed`, and write the
     difference.
   - **Dry run (D1), 22 calls, cap 25 sessions,** exactly as plan decision 5.3. Start from slice 26's
     `.local/sw-slice26-acceptance-2026-09-27/dry-run/run.py` (reading) and slice 25a's
     `.local/sw-slice25-acceptance-2026-09-26/dry-run/run.py` (criterion). Copies of slice 27's `data-qtre-sw-standard-r1`
     and `data-qtre-sw-standard-r2` and slice 24a's `data-q1-sw-standard-r1` in their own directories. Reading, 8 works ×
     2 runs through `ResearchFlow._model_step` (`fulltext_adjudication`, each work's latest stored reading StepInput
     passages, its stored criterion's parts through `mark_comparator`, the new method text): errors `10.1016/j.xcrm.2024.101801`
     and `10.1093/lifemedi/lnac017` (`standard-r2`), `10.1111/apt.70044` (`standard-r1`); controls `10.14814/phy2.14868`,
     `10.3390/nu16142187`, `10.3390/nu13041155` (`standard-r1`) and quantum `10.1038/s41598-024-70114-1`; edge
     `10.1002/oby.70270` (`standard-r1`). Each pair through `proposals_of`, `run_view`, `combine`, `with_comparator`,
     `with_title`, beside the stored code; nothing is written as a decision. Criterion, 3 medicine + 3 quantum
     `criterion_proposal` calls with the new method text, each consensus through `criterion.consensus`. Apply the plan's
     stop rules (any control deviation per part or combined; a `role` in the quantum target; a quantum proposal with a
     question element or a quantum consensus with roles; a medicine consensus without both roles). Then the plan's
     **effect conditions** (Sol r1): (i) at least 2 of the 3 errors leave `all_parts_verified` with the comparator part
     not `present` in at least one run; (ii) the plan's two-reader blind reading of the three new medicine
     comparator definitions (plan decision 5.3 (ii), rule and six calibration items frozen in
     `.local/sw-slice28-plan-2026-09-27/definition-gate-calibration.json`, do not edit it): two separate Claude Sonnet
     subagent sessions (Agent tool, `model: sonnet`; outside rule 4's Luna cap), blind to each other and to which items are new, one packet each (question, rule, nine definitions shuffled
     with seed `2809270`), PASS/FAIL plus one sentence per item, stored as `definition-gate-r1.jsonl` and
     `definition-gate-r2.jsonl`; valid only if both match all six calibration verdicts (an invalid reading is not
     repeated and counts as a failure); the condition holds only when both readers PASS all 3 new definitions. Run
     `definition_check.py` too and report it, never as the gate. If either fails,
     do not close the slice as implemented: leave code and tests uncommitted in the tree, write D109 as "implemented,
     not effective in the dry run" with the numbers, set row 28 to `sahip kararı bekliyor: dry run not effective` with
     the failed condition, and stop there (skip the rest of step 8 except D109). Report every error's code and
     comparator rationales, every control's labels, TRIM's code, and the three medicine definitions with their check
     result.
8. **Documents** (plan decision 6): D109 at the top of `docs/decisions.md` (if D109 exists already, the next free number,
   and say so): decision, replay and dry-run numbers, Limits (the rule is the model's reading of a marked part, measured
   on one medicine question; the marker and guard are code and leave quantum byte-identical; on a criterion with a comparator
   part the guard withholds every automatic full-text exclusion (10 of 294 stored slice 27 codes) and never excludes; no lexical check, because on stored data it withheld 24 of 29
   correct includes; the isocaloric edge is not special-cased; one machine, one model). In
   `docs/product/search-workflow-review-2026-09-18.md`: the new SW27 entry (finding, status "implemented in slice 28
   (D109)", Return to). Row 28: `uygulandı, inceleme bekliyor` with the headline numbers. Nothing else in `sw-status.md`.

## Close

Commit nothing. The final message, in Turkish, gives: the plan's commit hash; the changed files; the test counts; the new
`skill_package_hash`; replay (a) and (b); the dry run's error, control, edge and criterion results in one line each, with
the errors' comparator rationales; each judgement call; every file created or changed.
