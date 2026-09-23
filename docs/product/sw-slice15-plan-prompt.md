# Task: plan SW slice 15, citation chaining (planning session, no product code)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`. Slice 14a closed on
23 September 2026 (`8f86f54`, D94). Slice 15 is next. This session plans it; it does not implement it. Run it as
Fable · high: the plan turn of every slice is Fable · high (`sw-status.md`, the paragraph after the order list).

## What slice 15 is

`sw-implementation-plan.md`, item 15: SW4 in full and SW3.6. Seeds are chosen by code (blocks in the title, then
BM25), with no embedding and no topic-specific title gate. There are 15 to 25 seeds, and the list stops early when the
last five seeds add almost no new work. Seeds are deduplicated at work level. References and citing works come from
OpenAlex. A broad setting-or-task text filter is applied, and every work that passes it goes to screening. The number
of linking seeds is a priority, never a cut. A paper the user named or uploaded is always a seed. A second ring is
built from verified works, and only under a condition. Slice 14 (D93) left Semantic Scholar as a possible second
citation graph (SW3.4) to this slice.

Three records are already routed toward chaining and are waiting for it: survey records (`survey_title_word`, next
step `seed_pool`, SW5.4), `criterion_not_met` works (SW11.2), and stored reference lists (`record_references`, which the
ranking's graph signal already reads).

## Why the plan cannot copy SW4 as written

SW4 was measured on 18 September, before the product had an abstract stage, a full-text plan or effort limits. Since
then three findings change the question:

1. **D94 (slice 14a):** the full-text plan already has far more candidates than room: in `quick`, 234–348 eligible
   works for 80 places; in `standard`, 520–816 for 100. Chaining adds works to the same candidate groups and the same
   inspection order. SW3.6 measured a filtered chain pool of 580 works from 26 seeds. The plan must say where those
   works enter, and what they push out.
2. **Time:** `quick` now runs 9.8 minutes against a 10-minute target (D94 acceptance). `standard` runs 17.9 against 15
   and `detailed` 39.7 against 20 (third D88 measurement). SW3.6's chaining cost 114 requests. The plan must say which
   efforts chain, at what cost, and what the time targets become.
3. **Seeds are not verified.** In none of the eleven libraries replayed for 14a did the user include a work, so every
   seed is a code seed (SW4 (b): with 3–10 unverified seeds chaining reached 0 of the missed positives, with 15–25 it
   reached 4).

## Ground rules

1. **Git.** Run `git pull --ff-only` first, on `main` in the main checkout. At the end make ONE commit with the plan file
   and the status row, then `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or
   reset. Leave the owner's uncommitted and untracked files alone (`TODO.md`, `.vscode/`, `scripts/local_index.py`).
2. **No product code change.** Analysis scripts go under `.local/sw-slice15-chain-replay-<date>/`.
3. **No live model.** Network requests to OpenAlex (and to Semantic Scholar, if the plan needs it) are allowed only for
   the measurement in step 1, within a request budget you write into `protocol.md` before the first request, under the
   D67 pacing gate. Keep the budget modest: SW3.6 used 114 requests per research. Everything else replays stored data.
4. **Do not start, stop or query the service on port 8765, and do not open the product database**
   (`~/Library/Application Support/DEIXIS`). Open measurement libraries read-only (`file:…?mode=ro`).
5. **Python:** `PYTHONPATH=backend:. uv run --no-sync ...` from the repo root, native arm64. A script in a folder that
   holds a `numbers.py` must run with `python -P`, or it shadows the standard library (hit in 14a).
6. **Generalise.** Nothing may be tuned to the quantum question. Check every rule on the packet-size question too, and
   say plainly what two topics cannot show.
7. **Codex reviews** (if you want a second opinion): call the real binary `/Applications/ChatGPT.app/Contents/Resources/codex`,
   because the `~/.local/bin` symlink cannot run shell commands, and pipe the prompt with `-`.

## Read first

- `AGENTS.md`, `CLAUDE.md`.
- `docs/product/sw-status.md`: rows 14, 14a and 15; decision K8 (acceptance rule); the review rows.
- `docs/product/search-workflow-review-2026-09-18.md`: SW4 (all), SW3.4, SW3.6, SW5.4, SW11.2, SW13.4 (the stopping
  rule per arm kind).
- `docs/product/sw-implementation-plan.md`: item 15, and the rules that hold for every slice.
- `docs/decisions.md`: D79 (ranking and its graph signal), D81 (abstract stage), D83 (full-text plan groups), D88
  (effort limits and time targets), D93, D94.
- `docs/product/sw-slice14a-fulltext-order.md` (the shape to follow) and `.local/sw-slice14a-order-replay-2026-09-23/`
  (`replay.py` rebuilds the fetch plan from a stored library; reuse it rather than writing a second one).
- Code: `workflow/ranking.py` (`verified_seeds`, `graph_scores`, `GRAPH_SEEDS`), `workflow/flow.py` (discovery order:
  search, expansion, lookups, ranking, abstract stage), `workflow/lookups.py` and `domain/survey.py` (survey routing),
  `providers/openalex.py`, the `record_references` table.
- Measurements:
  - `.local/quantum-source-comparison-2026-09-18/` (`citation_chaining.py`, `citation-chaining.json`,
    `chain-pool-k25.json`, `chain_scope.py`): SW3.6 and SW4.
  - `.local/quantum-chain-precision-2026-09-18/`: the precision of the chain pool.
  - `.local/sw-measure-2026-09-24/data-*-luna`, `.local/sw-slice14-acceptance-2026-09-23{,b}/data-*`,
    `.local/sw-slice14a-acceptance-2026-09-23/data-*`: product libraries with stored reference lists.
  - Truth: `.local/quantum-work-adjudication-2026-09-18/adjudication.jsonl` (31 works) and
    `sw-vocabulary-experiment-2026-09-23/common.py::positives("q2")` (4 works).

## What to do

1. **Measure before you design.** On the product libraries, answer these with numbers:
   - Which verified works are missing from each pool, and which of them the code seeds would reach. Measure backward
     links (their references) from the stored `record_references`, with no request. Measure forward links (works that
     cite them) with OpenAlex requests inside the frozen budget.
   - How many works the chain adds before and after the broad text filter, per seed count (for example 5, 10, 15, 25),
     and how many requests that costs.
   - Where the reached verified works would land in today's inspection order and full-text plan if they joined the
     pool, using `replay.py`'s plan at D94's limits. A work that is reached but sits behind the plan limit is not a
     gain.
   - Whether surveys (`survey_title_word`) and `criterion_not_met` works make better seeds than code seeds. Say so if
     the libraries hold too few of them to tell.
   - The same for the packet-size question, as far as its data allows.

   Fix the candidate seed rules and the numbers you will compare in `protocol.md` before any request.
2. **Write the slice file** `docs/product/sw-slice15-citation-chaining.md` in the shape of
   `sw-slice14a-fulltext-order.md`: goal, the numbers, the decisions the owner must take (each with your recommendation
   and its reason), global constraints, tasks for the implementer with the tests named, a live acceptance, and
   "Bu dilimde yok" and "Ölçülmedi" sections. The decisions must at least cover:
   - which efforts chain, and what that does to each time target;
   - seed rule and count;
   - backward and forward links, and whether Semantic Scholar is used;
   - where chained works enter (the abstract stage? the ranking? which group of the full-text plan?);
   - the second ring;
   - how the approval card and the protocol show chaining.

   The slice writes the next decision number: check the top of `docs/decisions.md`, where D94 is the latest.
3. **Acceptance under K8.** One run is compared with one earlier run and may fall at most 2 works short. A larger drop
   fails the slice only when the slice's own change causes it; otherwise the slice passes and the cause is written down
   as a separate item. When a result is borderline, run that side twice and take the better one. The acceptance must
   name the earlier runs it compares against (the D94 acceptance for `quick`, the third D88 measurement for the others)
   and the numbers: works in the pool, works in the plan, works read, and time.
4. **Update row 15** in `sw-status.md` to `plan yazıldı, sahip onayı bekliyor`, with a link to the slice file.
5. Commit and push, then stop. The owner approves the decisions before anyone implements.

## Out of scope

- The human queue (slice 16).
- The abstract stage's read limit and the `blocks_in_title` rule (left open by D94). Mention them only if the
  measurement shows they decide what chaining can deliver.
- Europe PMC (the owner's call, after 14a).
- The two items slice 14 left open (a code query left with one block; arXiv's 406).

## Final message (in Turkish, plain language first)

- What the measurement showed, in one paragraph a non-specialist can read: how many missing works chaining reaches,
  at what cost, and whether they would actually be read.
- A table of seed rules × efforts: verified works reached, works added after the filter, requests, and reached works
  inside the full-text plan.
- The decisions waiting for the owner, each with a recommendation.
- What was not measured.
- The commit hash.
