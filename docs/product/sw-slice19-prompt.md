# Task: SW slice 19: probe set, arm table and signal table (stopping rule stays an open requirement)

**Run this prompt only after the owner has answered questions A–E of the plan and the answers are written in row 19
of `docs/product/sw-status.md`.** If row 19 does not record the owner's answers to all five, stop at once and change
nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice19-probe-tables.md` and it is
the only source of truth. Build decisions 1–11 and tasks 1–8, as the owner's answers to A–E leave them; where an
answer differs from the plan's provisional one, name the decisions and tasks it changed. List every place where you
used your own judgement.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave `TODO.md`, `.vscode/`
   and `scripts/local_index.py` alone. If the slice is not finished, commit nothing: write what remains into row 19.
2. **Read only.** Nothing this slice adds writes to the database: no migration (the highest stays `0052`), no step, no
   decision, no event, no selection. The protocol body does not change. Discovery, fetch, reading and answer behave
   exactly as before.
3. **Unchanged:** the model contract (`skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`), the method package, the reason-code
   table, `legacy` (its new fields are `null`), and the meaning of D93's existing `source_counts` fields.
4. **Words.** A work two agreeing model runs included is never called verified; only a person's decision is. No
   screen sentence says a signal helps or does not help. The "only" labels name D93's comparison universe.
5. **One snapshot, one derivation.** `research_view` reads in one snapshot and derives `DecisionStore.facts()` once;
   the queue counts, the probe set, the arm counts and the signal table share it and its `work_outcome` results.
   `queue.verified_records` is not called from the view.
6. **Tests** use no network and no live model. Existing pytest tests must pass unchanged; if one cannot, stop and
   write why into row 19. A Playwright scenario may gain assertions (task 5); none may lose one. Every decision is
   fixed by a test (the plan names them per task), including both stale cases of decision 1.
7. **Port 8765 and the product database are off limits.** The acceptance runs on copies of the stored libraries, made
   and migrated under the session's scratch directory, never on the originals (open the originals read-only).
8. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
9. **UI:** read `.impeccable.md` before touching `apps/web`; strings go through `i18n.ts` / `labels.ts`. Verify the
   changed transcript lines yourself with a screenshot at desktop and phone width.

## Build

Tasks 1–8 of the plan, in order:

1. `workflow/probes.py`: the probe set by decision 1's single precedence rule (current head selection, its link in
   `human_selection_links`, the staleness test), the three disjoint columns of decision 2, and the probes no arm found
   across every discovery run of the revision, with `unknown` for a revision mixing pre- and post-D93 runs.
2. `views.source_counts` extended: rows returned, included and verified counts in D93's "only" universe, `by_origin`
   read from the approved query list by step index, `read: false` before any reading, the arm-kind line.
3. The signal table: which signals ran and why not; the person probe's top-100 / top-200 capture with its denominator
   (work-level person positives present in that ranking step, found by joining each row's `record_signal_ranks.source_version_id` to `source_versions.work_id` (the rank table stores no `work_id`)) and
   `too_few` below `PROBE_JUDGE_MIN` (30). In a single signal only rows the signal scored (`available = true`) count,
   and a tie group counts only when its last position is inside the cut (a straddling group is counted apart as "tied
   at the cut"); `fused` and `inspection` use the stored exact order. The agreement row apart with its note. The
   embedding's `moved_up`, and `moved_up_then_included` / `moved_up_then_verified` only for decisions written after the
   ranking step finished (stored `created_at` / `updated_at` against `run_steps.finished_at`); earlier ones go to
   `moved_up_already_decided`, unreadable times and a decision stamped in the same millisecond as the ranking step's end to `moved_up_time_unknown` (test both the inclusion and the person's confirmation at that boundary).
4. `research_view` gains `probes` and per-run `signals` on the shared derivation; a test that the view changes no
   table's row count.
5. The transcript lines; Playwright as the plan says.
6. `scripts/probe_report.py` with a reference-set file (header `origin` and `completeness`) and its tests.
7. Acceptance (a)–(d) on migrated copies of the plan's 25 attributable libraries. Timing (decision 10): the new
   derivation alone, given the shared `facts`, one warm-up call then the median of 5 repeats, on the four largest
   attributable libraries, at most 0.25 s each; `research_view` before (on the parent commit) and after, same method,
   written down. If the budget is missed, apply decision 10's fallback (the `probes` endpoint) and record it.
8. Close.

## Close

Write a new D number at the top of `docs/decisions.md` (the highest today is D100), with the owner's answers to A–E.
Its Limits name the open requirements with their condition and the event that reopens them: the stopping rule
(SW13.4–5) and the costly-signal switch-off (SW13.3, SW7.6, SW8.7); and they name what went to the script, the
out-of-scope answer, the list-edit rule that does not go stale, and that TF-IDF and the embedding ran in none of the
plan's 43 stored researches. Update the status lines of SW13, SW1, SW7 and SW8 in
`docs/product/search-workflow-review-2026-09-18.md` and row 19. Run the full pytest suite, `npm run build`,
`npm run lint` (17 warnings), Playwright A–L (and M if added); check `git diff --check` and the hash. Report the test
run as "the known single failure apart, the rest of the full run passed" with the counts. The final message, in
Turkish, gives what was done, the judgement calls, the test counts, the acceptance numbers next to the plan's, and
what was not measured.
