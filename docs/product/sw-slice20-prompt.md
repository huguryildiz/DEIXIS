# Task: SW slice 20: flow counts, audit sample, override count, PRISMA-S export

**Run this prompt only after the owner has answered questions A and B of the plan and the answers are written in row
20 of `docs/product/sw-status.md`.** If row 20 does not record the owner's answers to both, stop at once and change
nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice20-flow-audit-prisma.md` and it
is the only source of truth. Build decisions 1–11 and tasks 1–10, as the owner's answers to A and B leave them; where
an answer differs from the plan's provisional one, name the decisions and tasks it changed. List every place where you
used your own judgement.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Stage only the slice's own
   files, each by explicit path (never `git add -A` or `git add .`); existing unrelated working-tree changes stay out of
   the commit and untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py` and anything else that is not the slice's.
   Check `git diff --cached --name-only` before committing. If the slice is not finished, commit nothing: write what
   remains into row 20.
2. **What writes.** Only two things write: the `sw` answer run's new `code:answer_start_snapshot` step (operation key
   `answer_start_snapshot`, opened after `included_works` and `selection_revision` are read, with no `await` until it is
   written), and the new audit endpoints' answer and undo, which go through a separate audit branch in `queue.py` that
   shares D96's answer body, transaction and undo rules and writes D96's tables. D96's endpoints stay as they are and the undo result
   of valid existing D96 decisions is preserved; D96's undo path gains the origin check of task 4. The
   research view, the queue view and the PRISMA-S export write nothing. No migration (the highest stays `0052`), no new
   reason code, no change to the protocol body.
3. **Unchanged:** the model contract (`skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`), the method package, the reason-code
   table, D96's `counts.queue` (audit rows are not in it), D101's probe set and columns, `legacy` (new fields `null`, its
   answer run opens no new step, its depth texts stay).
4. **Words.** A work two agreeing model runs included is never called verified; only a person's decision is. The
   override count is never shown as a rate or an accuracy; the audit result has no percentage, and the current sample
   and earlier audit answers are shown apart. The start snapshot is never called "the works the answer used"; the
   answer's input (`inputs_given`) is its own line, and the change warning says "the state of the included sources
   changed", never "the selection changed" or "the set of works changed". The export never says "PRISMA-compliant"; it opens with the plan's
   statement; "not recorded" is never written as "not performed". An unread abstract is not a negative.
5. **One snapshot, one context.** `research_view` keeps slice 19's single snapshot and single queue context; the flow
   counts, boxes and override count read it and its `work_outcome` results.
6. **Tests** use no network and no live model. Existing pytest tests must pass unchanged; if one cannot, stop and write
   why into row 20. A Playwright scenario may gain assertions (task 8); none may lose one. Every decision is fixed by a
   test (the plan names them per task).
7. **Port 8765 and the product database are off limits.** The acceptance runs on copies of the stored libraries, made
   with SQLite's backup API and migrated under the session's scratch directory, never on the originals (open the
   originals read-only).
8. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
9. **UI:** read `.impeccable.md` before touching `apps/web`; strings go through `i18n.ts` / `labels.ts`. Verify the
   flow block, the answer's flow line, the queue's audit section and the Home depth text yourself with a screenshot at
   desktop and phone width.

## Build

Tasks 1–10 of the plan, in order:

1. `workflow/flow_counts.py`: decision 1's buckets (person first by D101's `probe_set`, then `work_outcome` by stage,
   reason code and the table's `next_step`), their sum equal to the works, the SW11.12 five, `look_again_in_answer`,
   the queue's reasons; decision 2's boxes with `flow_status: "incomplete_no_human_screening"`.
2. The answer run's `code:answer_start_snapshot` step (run's `scope_revision`, the `selection_revision` read, the flow
   counts, `included_without_answer_text`) and each answer's `start_snapshot` in `research_view` (`null` without the
   step), shown beside, not instead of, `inputs_given`. Asking for an answer with a non-empty queue stays allowed, with
   no dialog.
3. `workflow/overrides.py`: decision 4's machine view at the moment of the person's decision — for a queue or audit
   answer, the work's decision rows strictly before the human row by `(created_at, rowid)`; for a list edit, as of the
   `created_at` of the `selection_history` row that set the current user selection, with a same-millisecond decision
   giving `time_unknown`; staleness judged with the key of that moment; the person-file exception left out. The three
   classes by path, decider, stage and direction; `not_sure`, `pdf_wrong` and `look_again` apart.
4. The audit sample (`workflow/audit.py`; decision 5: strata F1, F2, A1, A2; extended membership; bottom
   `AUDIT_PER_STRATUM = 3` by `sha256("{research_id}|{scope_revision}|{criterion_hash or 'none'}|{stratum}|{work_id}")`;
   stateless, no migration) and the audit branch (decision 6): `GET …/audit`, `GET …/audit/{svid}`,
   `POST …/audit/{svid}/decision`, `POST …/audit/{svid}/undo`; inside the write transaction, in order, the work is still
   in its stratum's current sample, the version's current full-text decision is still the token's machine decision, and
   the token matches, else 409 and nothing written; undo only when the decision strictly before the human one is an
   F1 / F2 code. An audit decision's origin is verified by its decision id (the `stage_decision_recorded` event with
   `via: "audit"` written in the same transaction); it is kept out of D96's `decided` list. Both undo paths positively
   verify their own origin from the event tied to the current human decision's id: `via: "audit"` is audit, an event
   without `via` (every pre-slice-20 D96 event) is D96, and an event whose `via` is present but not `"audit"` is
   unknown. D96's queue undo refuses an audit decision (409 `audit_decision`),
   the audit undo refuses a D96 decision (409 `not_an_audit_decision`), and a missing or conflicting event gives 409
   `origin_unknown` on both paths, with nothing written and no fallback (tested, including a `via` that is neither absent
   nor `"audit"`). Two-way endpoint tests preserve the undo result of valid existing D96 decisions.
   Under answer A1, A1 / A2 are "view and manual selection", outside the audit answer and result totals.
   Decision 7's result: current sample and earlier audit answers apart, no rate.
5. `workflow/prisma_s.py` and `GET /api/researches/{id}/prisma-s?format=md|json` (decision 8, in the language answer B
   sets): the 16 items with the plan's sources and status rules (items 2, 7, 9, 12, 15 and 16 as narrowed there; item
   15 on query groups; item 16 names `candidate_hits` "tracked candidate versions / hits", gives the distinct returned
   provider-record count as `null` / not recorded, and describes the dedup rules), `search_table` one row per query
   group, `flow`, `trace` of resolvable row ids only, `aggregates` for counts, and a `code_source` for facts read from code
   absence (items 3 and 10) carrying `code_version`, the source file name and the sha256 of the running code's source, pinned when the module is
   imported; at export the file on disk is hashed again and, if it differs, `code_source.verified` is `false` (otherwise `true`) and
   the item says the code origin is not verified (test: change the file after import); `legacy` 422.
6. `GET /api/effort-limits` and the `sw` depth text in `Home.tsx` from it (decision 9).
7. View and cost (decision 10), timed with the product's code (the plan's timings are plan-helper measurements only):
   one warm-up call then the median of 5 repeats on the four largest distinct libraries — the view derivation given
   the shared context at most 0.05 s, `GET …/audit` at most 0.5 s, the export in both formats at most 1 s, an audit
   answer's and undo's write transaction (with its full-context membership check) at most 0.5 s; `research_view` before
   (on the parent commit) and after, same method, written down. If the write budget is missed, apply decision 10's
   fallback and record it.
8. The UI of decision 11; Playwright J extended and the new M as the plan says.
9. Acceptance (a)–(f) on migrated copies of the plan's 46 libraries, against the plan's `measure.json` and
   `item15.json` (390 keyword and 294 chain query groups; item 15 `incomplete` in 40 / 40; 33 researches with a group
   that read nothing because of a rate limit, 37 with one that read nothing for any reason).
10. Close.

## Close

Write a new D number at the top of `docs/decisions.md` (the highest today is D101), with the owner's answers to A and
B. Its Limits name: the open requirement of a person's abstract-stage decision ("send back to full text") and the event
that reopens it; that the audit gives counts, not rates; that stored data has 4 person decisions in 2 researches and
no answered audit row, so the override classes and the audit answers are covered by synthetic tests; that the audit
sample is stateless and can drift, so it gives counts for the current sample and earlier answers apart, no rate, and a
frozen cohort is an open requirement; that PRISMA-S item 15 reads `incomplete` in all 40 of the plan's researches
(a keyword query group that did not end completed or zero-results in each; in 33 a group read nothing because of a rate
limit) and item 9 in all 40 (limits without a stored justification); that the export was not checked by a journal or a
librarian. Update SW11's status line in
`docs/product/search-workflow-review-2026-09-18.md` (points 8, 12 and 13 built with their limits; point 11 was built in
D96) and row 20. Run the full pytest suite, `npm run build`, `npm run lint` (17 warnings), Playwright A–M; check
`git diff --check` and the hash. Report the test run as "the known single failure apart, the rest of the full run
passed" with the counts. The final message, in Turkish, gives what was done, the judgement calls, the test counts, the
acceptance numbers next to the plan's, and what was not measured.
