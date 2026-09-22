# Task: offline read-limit cut — would a smaller per-query read limit change what the model reads and what is included?

**On hold (2026-09-23):** run this only after `sw-vocabulary-experiment-prompt.md` and the slice that follows it.
The second round's query of these runs had lost its task block, so most of the pool this cuts is off topic; cut
the pools the corrected queries produce instead.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. A measurement, not a slice: no product code changes, no commit
of results until the owner says "uygun". Implementer: Opus · high. Written 2026-09-23 at the end of the slice 13f
conversation.

## Why

A `detailed` run collects about 6,200 works (second measurement after 13e: 6,696 records → 6,217 works), but the
model reads only the first 300 of the ranked list (`ABSTRACT_READ_LIMIT`), downloads 117 PDFs, reads 96 and includes
31. Collection is now the largest cost of discovery: pages, provider rate limits (Semantic Scholar 429s), and one
abstract lookup per record with no abstract. If a smaller `SW_READ_LIMIT` per query (today 400 / 1,000 / 2,000 by
effort, D88) leaves the first 300 and the 31 included works almost unchanged, the constants can be lowered with no
code change. If it does not, the limits stay. This measurement decides which.

## Data (read-only)

- `.local/sw-measure-2026-09-22b/data-{quick,standard,detailed}-luna/`: the three runs of the second measurement,
  commit `8fa06b4`. Copy each `library.sqlite` into a new folder `.local/sw-read-limit-cut-2026-09-23/` and read
  only the copies. Never write to the originals.
- `docs/product/sw-measure-2026-09-22.md` (last section) gives the numbers these runs produced.
- Do not open the product database (`~/Library/Application Support/DEIXIS`), do not start, stop or query the
  service on port 8765, no network, no model call.

## Method

1. For each run, rebuild what the discovery run saw: every `search_runs` row (query, page, `read_total`,
   `stop_reason`, `unread_count`), every candidate with its rank inside its query (`candidates.rank`, the record's
   place in the query across pages, slice 04c), the work each record belongs to, and the ranked list and read plan
   the run stored (`abstract_stage` / ranking step outputs; read `workflow/ranking.py`, `workflow/abstract_stage.py`
   and `flow._ranking` to find where they live).
2. Check the replay first: recompute the ranking on the full pool with the product's own ranking functions and the
   stored inputs, and confirm it gives the stored order. If it does not, find out why and STOP AND REPORT before
   cutting anything.
3. For each cut L in {200, 400, 600, 1,000} (below each run's own limit only): keep a record only if its rank in at
   least one query is below L; a work stays if any of its versions stays. Recompute the ranking on the reduced
   pool the same way; anything computed over the whole pool (term statistics, normalisation) is recomputed, not
   reused.
4. For each run × L report: works kept; how many of the full run's top 300 (or the effort's read limit) are still
   in the new top 300, and how many are still in the pool at all; the same for the 96 works read in full text and
   the 31 (or the effort's) `included` works; provider requests saved (pages not read, by provider); abstract
   lookups saved (records with no abstract that would not have been asked).
5. Name every `included` work lost at some L: its provider(s), its rank in each query, and why it fell out.

## Limits to state

- The second round's queries come from the first round's records (expansion, SW2.4). A cut first round could have
  produced other second-round queries; the replay keeps the stored ones. Say so, and do not estimate the effect.
- Provider ranking of a shorter read is assumed to be the prefix of the longer one (true for offset and cursor
  paging on an unchanged index; not checked live).
- One topic, one run per effort. Passing shows how the ranking reacts to a smaller pool on this topic, not recall
  in general, and not model quality.

## Output

`.local/sw-read-limit-cut-2026-09-23/result.md` (Turkish, plain language first, then tables) and the script that
produced it. In the final message: the table per effort, the L you would recommend per effort with the reason, what
was not measured, and confirmation that the originals, the product database and port 8765 were not touched. No commit
unless the owner asks; if asked, only the result summary goes into `docs/product/sw-measure-2026-09-22.md`, never the
databases.

## After this (not part of this task)

- Scopus leaves the search (D90 to be written): the slowest host (25 records a page, about 80 requests per
  `standard` run), no abstract with the configured key, no verified work of its own in the 2026-09-18 comparison.
  With a VPN, Scopus's `view=COMPLETE` can be the last source asked for a missing abstract, after Semantic Scholar
  and Crossref (`scopus.complete_view_entitled` already checks that access).
- Then one measurement of 13f + the new limits + Scopus out: the third run of 13ö.
