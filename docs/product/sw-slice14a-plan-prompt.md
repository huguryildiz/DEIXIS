# Task: plan SW slice 14a, the full-text order (planning session, no product code)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`. Slice 14 closed on
23 September 2026 (`9b57756`, D93). By the owner's decision, 14a comes before 15, because the citation chain in slice
15 adds records to the same order. This session plans 14a. It does not implement it. Run it as Fable · high, since the
plan turn of every slice is Fable · high (`sw-status.md`, the paragraph after the order list).

## The problem, as row 14a states it

In the third D88 measurement, of the quantum question's 31 verified works, 13 / 17 / 21 passed the abstract stage
(quick / standard / detailed), but only 1 / 7 / 17 were read in full text. The full-text plan reads the head of the
inspection order (40 / 100 / 300 works, `FULLTEXT_WORK_LIMIT`), and most verified works are not there. In `quick`, one
of the 13 is in the first 40, and the others sit at places 46 to 181 among 246 works. The 13e run showed the same.
So the loss is in the order, not in the search.

## Ground rules

1. **Git.** `git pull --ff-only` first, on `main` in the main checkout. At the end, ONE commit with the plan file and
   the status row, then `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or
   reset. Leave untracked files (`.vscode/`, `scripts/local_index.py`) and the owner's uncommitted `TODO.md` alone.
2. **No product code change.** Analysis scripts go under `.local/sw-slice14a-order-replay-<date>/`.
3. **No network and no live model.** The first step replays the order on stored libraries only. If a question needs a
   live run, write it into the plan as a step for the implementer, and do not run it.
4. **Do not start, stop or query the service on port 8765, and do not open the product database**
   (`~/Library/Application Support/DEIXIS`). Open the measurement libraries read-only
   (`file:…?mode=ro`).
5. **Python:** `PYTHONPATH=backend:. uv run --no-sync ...` from the repo root, native arm64.
6. **Generalise.** Nothing may be tuned to the quantum question alone. Check every candidate rule on the packet-size
   question too (`.local/second-topic-packet-size-2026-09-20/`, `.local/sw-slice14-acceptance-2026-09-23b/data-q2-detailed`),
   and say plainly what one or two topics cannot show.

## Read first

- `AGENTS.md`, `CLAUDE.md`.
- `docs/product/sw-status.md`: rows 13e, 13ö, 14 and 14a; decision K8 (acceptance rule, below); the review rows.
- `docs/decisions.md`: D79 (the rank fusion that orders the inspection list), D81 (abstract stage), D83 (full-text
  retrieval in rank order), D85 (full-text reading), D88 (limits by effort), D93.
- `docs/product/search-workflow-review-2026-09-18.md`, the sections on ranking and full text.
- Code: `backend/deixis/workflow/ranking.py`, `workflow/fulltext.py`, the abstract stage in `workflow/flow.py`, and
  `domain/rules.py` (`ABSTRACT_READ_LIMIT`, `FULLTEXT_WORK_LIMIT`, `FULLTEXT_READ_LIMIT`).
- Measurements:
  - `.local/sw-measure-2026-09-24/` (`result.md`, `quality.py` with `verified_kept_place`, `quality-*.json`,
    `data-{quick,standard,detailed}-luna/`): the third measurement, the one row 14a quotes.
  - `.local/sw-slice14-acceptance-2026-09-23b/`: discovery only, with slice 14's routing. It has no abstract or
    full-text stage, but its pools show what the new search puts in front of the order.
  - `.local/quantum-work-adjudication-2026-09-18/adjudication.jsonl`: the 31 verified works (`confirmed_mathematical_model`,
    confidence `high`).

## What to do

1. **Replay, no model.** In the three libraries of the third measurement, rebuild the inspection order from the stored
   ranking inputs and find where each verified work sits. Answer, with numbers:
   - Which signal pushes the verified works down: each of the four code signals of D79, and the embedding signal where
     one was stored.
   - Does the abstract stage's decision (included / unsure / excluded) reach the order, or does the full-text plan
     read the raw rank?
   - How many verified works the full-text plan would read under a few candidate orders, at the same limits
     (40 / 100 / 300). Candidates to try at least: the abstract stage's included works first, then the rest by rank; the
     same with unsure after included; and one order of your own. Fix the candidates before looking at their numbers,
     and write them into the replay folder's `protocol.md` first.
   - The same for the packet-size question, as far as its stored data allows.
2. **Write the slice file** `docs/product/sw-slice14a-fulltext-order.md` in the shape of
   `sw-slice14-source-routing.md`: goal, the numbers, the decisions the owner must take (each with your recommendation
   and its reason), tasks for the implementer with tests named, a live acceptance, and "Bu dilimde yok" and
   "Ölçülmedi" sections. The slice writes the next decision number (check the top of `docs/decisions.md`; D93 is the
   latest).
3. **Acceptance under K8.** One run is compared with one earlier run and may fall at most 2 works short. A larger drop
   fails the slice only when the slice's own change causes it; otherwise the slice passes and the cause is written down
   as a separate item. When a result is borderline, run that side twice and take the better one. Write the acceptance
   so that it can pass under this rule, and name the numbers it compares.
4. **Update row 14a** in `sw-status.md` to `plan yazıldı, sahip onayı bekliyor`, with a link to the slice file.
5. Commit and push, then stop. The owner approves the decisions before anyone implements.

## Out of scope

- The citation chain (slice 15).
- The two items slice 14 left open: a code query left with one block is not caught (the second acceptance run lost
  five works in `detailed` this way), and arXiv returned no page in either acceptance run (406). Mention them in the
  plan only if the replay shows they affect the order.
- Europe PMC (D93 context: after 14a, beside the full-text work, the owner's call).

## Final message (in Turkish, plain language first)

- What the replay showed, in one paragraph a non-specialist can read: where the verified works sit and why.
- The table of candidate orders × efforts: verified works the full-text plan would read.
- The decisions waiting for the owner, each with a recommendation.
- What was not measured.
- The commit hash.
