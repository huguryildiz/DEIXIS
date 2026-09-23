# Task: plan SW slice 16, the human queue back end (planning session, no product code)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`. Slice 15 closed on
24 September 2026 (`d6f84bd`, fixes `6b8cf26` and `24728e9`, D95). Slice 16 is next. This session plans it; it does not
implement it. Run it as Fable · high: the plan turn of every slice is Fable · high (`sw-status.md`, the paragraph after
the order list), and slice 16 is also one of the slices marked **tam** for review.

## What slice 16 is, and why it is next

`sw-implementation-plan.md`, item 16: SW11.4–7, 11.10–11 and 11.13, with slice 12 as its prerequisite. In short: the
reasons a work enters the human queue; one question per row, with quote, page and version label; for a "no" decision
the cue sentences and their pages; for a rejected quote the closest passage in the text; a person's decision is final,
can be undone, and the model is never asked about that work again; "not sure" and "this PDF is wrong or incomplete";
a decision is stored with the scope revision and criterion it was made under, and a changed criterion marks it "made
under the earlier criterion, look again"; the queue is ordered by the fused rank; human decisions count as verified
positives and are never used to retune a rule.

The owner's order (row 17a's note in `sw-status.md`): 15 closes, then 16, 17, 17a, 18. Slice 16 comes first because 17
(the queue screen) needs its data, and because slice 12 already writes five reason codes that route to `human_queue`
with nothing that reads them (`sw-slice12-fulltext-adjudication.md`, "Kuyruk boş ekran"). The reason codes for a
person's answers (`human_include`, `human_criterion_not_met`, `human_not_sure`, `human_pdf_wrong`) are in
`domain/reason_codes.py`; nothing writes them yet.

## What changed since SW11 was written

SW11 was measured on 19 September on one topic, before the product had a retrieval run, a reading run, effort limits
or a chain. Four decisions change what "unresolved" means today, and the plan must start from them, not from SW11's
numbers (140 of 160 works in the old queue):

1. **D83 (full-text retrieval).** A work with no text after one attempt is `no_fulltext` or `text_unreadable`, next
   step `waiting_for_pdf`. It is unresolved, but it is slice 18's list, not the queue. A work the fetch limit did not
   reach has no full-text decision at all.
2. **D85 (full-text reading, slice 12).** Two model runs per work, code checks every quote on the page. Five codes go to
   `human_queue`: `fulltext_runs_disagree`, `include_quote_unverified`, `part_without_evidence`,
   `abstract_promise_absent`, `fulltext_runs_agree_unresolved`; `pdf_identity_unconfirmed` goes there too. A work with
   text the read limit did not reach stays `not_read_yet` (next step `reading_queue`).
3. **D94 (slice 14a).** `quick` fetches 80 works and reads 40. Most works in the plan are therefore never read in one
   run: their unresolved state comes from the limit, not from indecision.
4. **D95 (slice 15).** Chained works have their own abstract read (`abstract_not_read` beyond it) and 12 places after
   the keyword plan. A chained work can reach the queue only through the same reading run.

At the abstract stage nothing reaches a person (SW11.4): disagreement and `runs_agree_unresolved` go on to full text.
The plan must confirm that this is still what the code does.

## Ground rules

1. **Git.** Run `git pull --ff-only` first, on `main` in the main checkout. At the end make ONE commit with the plan file
   and the status row, then `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push,
   run `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave the owner's files
   alone: `TODO.md`, `.vscode/`, `scripts/local_index.py`.
2. **No product code change.** Analysis scripts go under `.local/sw-slice16-queue-measure-<date>/`.
3. **No network and no live model.** Everything is measured on stored libraries.
4. **Do not start, stop or query the service on port 8765, and do not open the product database**
   (`~/Library/Application Support/DEIXIS`). Open measurement libraries read-only (`file:…?mode=ro`).
5. **Python:** `PYTHONPATH=backend:. uv run --no-sync ...` from the repo root, native arm64. A script in a folder that
   holds a `numbers.py` must run with `python -P`, or it shadows the standard library.
6. **Model contract.** If the plan changes the contract or the method package, say so as a decision: today
   `skill_package_hash` is `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`.
7. **Generalise.** Nothing may be tuned to the quantum question. Check every count on the packet-size question too, and
   say plainly what two topics cannot show.
8. **Codex** (for a second opinion or the joint decisions): call the real binary
   `/Applications/ChatGPT.app/Contents/Resources/codex` and pipe the prompt with `-`:
   `codex exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only --skip-git-repo-check -C "$PWD" -o out.md - < prompt.md`.
   Sol cannot run pytest in read-only mode; say so when you pass on its verdict.

## Read first

- `AGENTS.md`, `CLAUDE.md`, `.impeccable.md` (only for what slice 17 will need from the back end).
- `docs/product/sw-status.md`: rows 12, 15, 16, 17, 17a, 18, 20; decision K8 (acceptance rule); the review rows.
- `docs/product/search-workflow-review-2026-09-18.md`: **SW11 in full**, SW1 points 6–8, SW5.4, SW6.6, SW7 (fused rank),
  SW10 point 5, SW15.5, SW16.
- `docs/product/sw-implementation-plan.md`: items 12, 16, 17, 18, 20 and the rules that hold for every slice.
- `docs/product/sw-slice12-fulltext-adjudication.md` and `sw-slice12-prompt.md`: what slice 12 writes and what it left
  to 16.
- `docs/decisions.md`: D83, D85, D93, D94, D95, and the decision that added `stage_decisions` (migration `0038`).
- Code: `domain/reason_codes.py` (the reason-code table: outcome, decider, next step), `workflow/decisions.py`
  (`work_outcome`, `DecisionStore`, `derive_selection`), `workflow/flow.py` (the reading run: adjudication plan,
  `_close_adjudication` or its equivalent, `pdf_identity_unconfirmed`), `workflow/views.py`, `workflow/fulltext.py`,
  `workflow/adjudication.py`, the `selections` table and how a user's include/exclude is stored today.
- Stored libraries with a reading run (check each has `fulltext_adjudication` runs before counting it):
  `.local/sw-slice15-acceptance-2026-09-23/data-*`, `.local/sw-slice14a-acceptance-2026-09-23/data-*`,
  `.local/sw-slice14-acceptance-2026-09-23{,b}/data-*`, `.local/sw-measure-2026-09-24/data-*-luna`.
- Truth for the quantum question: `.local/quantum-work-adjudication-2026-09-18/adjudication.jsonl` (31 works) and
  SW11's own queue measurement in `.local/quantum-queue-design-2026-09-19/`.

## What to do

1. **Measure before you design.** Write `protocol.md` first (libraries, the counting rule, what counts as "a person
   would really have to decide"), then answer with numbers, per library and per effort:
   - How many works end in each unresolved reason code, split by stage and by next step (`human_queue`,
     `waiting_for_pdf`, `reading_queue`, `fulltext_fetch`, `abstract_model`, `seed_pool`, none). Include works with no
     full-text decision because the fetch or read limit did not reach them.
   - How many rows the queue would hold today: works whose current decision routes to `human_queue`, counted once per
     work, keyword and chained works apart.
   - Of those rows, which a person would really have to decide. Read a sample of each reason (the quotes, the parts,
     the two runs' labels) and sort them: a real open question, a model or code artefact the rules should close, or a
     wrong PDF. Say how large the sample was.
   - For each queued row, whether the data a row needs is already stored: the one question, the quote and page, the
     version label, the cue sentences for a "no", the closest passage for a rejected quote. Name what is missing.
   - How the queue order would look under the fused rank, and whether verified quantum works sit near its top.
   - The same for the packet-size question, as far as its data allows.
2. **Write the slice file** `docs/product/sw-slice16-human-queue.md` in the shape of
   `sw-slice15-citation-chaining.md`: goal, the numbers, the decisions the owner must take (each with your
   recommendation and its reason), global constraints, tasks for the implementer with the tests named, a live or
   replayed acceptance, and "Bu dilimde yok" and "Ölçülmedi" sections. The slice writes the next decision number: check
   the top of `docs/decisions.md`, where D95 is the latest.
3. **Update row 16** in `sw-status.md` to `plan yazıldı, sahip onayı bekliyor`, with a link to the slice file.
4. Commit and push, then stop. The owner approves the decisions before anyone implements.

## Decisions the owner must take (the slice file answers each with a recommendation)

- **Queue reasons.** Which of today's `human_queue` codes enter the queue, and whether any should be closed by a rule
  instead (for example `fulltext_runs_agree_unresolved`, or `part_without_evidence` when the part is absent in both
  runs). SW1.6 (two runs disagree), the gate–model contradiction (SW16 keeps the gate off, so does it occur?), SW5.4
  and SW6.6 must each be answered: in, out, or not reachable today.
- **The row.** What one row stores and serves: the question, quote, page, version label, cue sentences, closest
  passage; which of these are computed when the row is served and which are stored.
- **The decision.** Where a person's answer lives (`stage_decisions` with `decided_by = 'human'`, `selections`, or
  both), how "undo" works, how "the model is not asked again" is enforced in the reading run and in a later discovery
  run, and how `human_not_sure` and `human_pdf_wrong` keep a work out of the queue.
- **Staleness.** How a decision is tied to its scope revision and criterion, what "look again" means in the data, and
  what a new scope revision does to open rows.
- **Order and size.** The queue order (fused rank, SW7) for keyword and chained works together, and whether the queue
  needs a cap per research.
- **What counts as verified.** How human decisions feed the probe set and the vocabulary rule (SW11.13) without
  retuning anything.
- **The API.** The endpoints slice 17 will call, with their CSRF and loopback rules, and what `views.py` returns.

## Acceptance under K8

One run is compared with one earlier run and may fall at most 2 works short. A larger drop fails the slice only when
the slice's own change causes it; otherwise the slice passes and the cause is written down as a separate item. When a
result is borderline, run that side twice and take the better one. Slice 16 should change no discovery, fetch or read
result: its acceptance must show that the pool, plan, read and include counts of a replayed or new run equal the
earlier run's, and that the queue holds the rows the measurement predicted. Name the earlier runs (the slice 15
acceptance) and the numbers.

## Out of scope

- The queue screen (slice 17). The back end must serve what 17 needs, nothing drawn.
- The time slice (17a): fetch overlapping discovery.
- The "waiting for your PDF" list and the user-supplied PDF path (slice 18, SW11.9).
- Flow counts, the audit sample, the override count and the PRISMA-S export (slice 20, SW11.8, 11.12).
- The user-approved code gate (slice 23).

## Final message (in Turkish, plain language first)

- What the measurement showed, in one paragraph a non-specialist can read: how many works a queue would hold per
  effort, how many of them a person would really have to decide, and why the rest are unresolved.
- A table of reason codes × efforts (both questions): works, and the next step each goes to.
- The decisions waiting for the owner, each with a recommendation.
- What was not measured.
- The commit hash.
