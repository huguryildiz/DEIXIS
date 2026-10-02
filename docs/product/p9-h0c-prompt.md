<!-- PLAN-REVIEW-ROUNDS: none run: gpt-6.1-sol and gpt-6-sol returned a usage-limit error (until 3 October 2026); self-reviewed, flagged for Sol review when quota returns; see D159 -->

# Task: P9 batch H0c, the 1 GiB memory limit in the OCR, JATS render and arXiv source children

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h0c`, detached at `d65a7ea` (main with D157). Follows H0b (commit `129791a`, D138). Plan:
`docs/product/p9-hardening-plan.md` §4 rule 2 and F09. **No git state-changing commands.** No real-model call, no provider call. Do not touch
the live service on 8765, the live data directory, `TODO.md`, `.vscode/`, `scripts/local_index.py` or the `../DEIXIS-x*` worktrees. No method,
contract or migration change. Do not invent; report what could not be measured.

## Why

D138 showed that the in-child watchdog (`pdf._watch_memory`, a thread polling `ru_maxrss`) cannot run while PyMuPDF holds the interpreter lock,
and moved PDF extraction to a parent-side watcher. `ocr.py`, `jats.py` and `arxiv_source.py` still rely on the in-child thread. Until each is
measured, "the 1 GiB limit works" is shown for PDF text extraction only (D138 Limits; P9 cannot close on an unenforced safety limit).

## Rule applied

Per child: run the production child argv at the production 1 GiB limit on a scaled input; record kernel peak (`wait4` rusage), sampled peak,
elapsed time and stop reason. A child that exits with code 3 by itself is "stopped by the in-child watchdog" and is left alone. A child that
crosses 1 GiB and is not stopped is routed through the parent watcher with behaviour otherwise unchanged.

## Measured before implementation (`scripts/p9/child_memory_probe.py`, raw lines in the main checkout's ignored `.local/p9-h0c/runs.jsonl`)

macOS 27.0.1 arm64, Python 3.12, load average 4 to 13 (foreign load), `tesseract` present (Homebrew), LaTeX not needed.

- OCR (`documents.ocr`, one blank-with-a-glyph page whose MediaBox is N points square, rendered at 300 dpi): stopped by the in-child
  watchdog (exit 3, "memory limit exceeded") at 2000, 2500, 3000 (twice), 4000 pt; kernel peaks 1073, 1636, 2329, 1856, 2453 MiB, so it stops
  but overshoots, by as much as 2.4x for the largest pages (one allocation of the pixmap). Pages from about 5000 pt are refused by PyMuPDF
  ("Overly large image") at 55 MiB. 1000 and 1500 pt (318, 635 MiB) finish normally.
- JATS render (`documents.jats`, XML under the 5 MB input cap): five shapes (plain text, one huge table cell, many cells, very many
  paragraphs, one unbreakable word) never reach 1 GiB within the input, page (200) and 60 s limits (peaks 124 to 577 MiB; they end by the page
  limit, a recursion error or the clock). A shape of 1.2 million `a-b` tokens, each wrapped in a `nowrap` span by `_esc`, crosses the limit and
  is stopped by the in-child watchdog (exit 3) in 7 to 8 s, three of three runs, kernel peaks 1474 to 1585 MiB (about 50% over).
- arXiv source (`documents.arxiv_source`, a tiny `.tar.gz` with one numbered equation, plus a PDF whose content stream decodes to N MiB,
  read by `match()` through PyMuPDF): NOT stopped. 200 MiB decoded at the production limit: three runs reached 1162, 1039 and 1176 MiB and ran
  until the probe killed them at 60 or 120 s (a fourth, 672 MiB, was under heavy load and is not offered as evidence). 67 MiB decoded at a
  100 MiB limit: 3 of 3 not stopped (754 to 912 MiB). The 60 s child clock is the only stop, so the memory limit does not bind.

## What to do

1. `arxiv_source.run_child` gains `max_memory: int | None = None`. When given and `pdf._watch_supported()`, a task beside the readers polls
   `pdf._resident_bytes(proc.pid)` every `pdf.WATCH_INTERVAL_SECONDS`; over the limit it kills the child and `failure = "memory_limit"`; after
   `pdf.WATCH_LOST_TURNS` unreadable turns in a row with the child alive it kills it and `failure = "memory_watch_lost"`. A finished child is
   never a lost watch. `read_source` passes `MAX_MEMORY_BYTES`. Everything else (stdin feed, stdout cap, stderr tail, timeout) is unchanged.
   The in-child thread stays as a second guard.
2. OCR and JATS: unchanged. The evidence above is the record. Their overshoot is recorded as a limit, not fixed here.
3. Tests (`tests/test_arxiv_source_archive.py`): a child that holds the lock inside `PyDLL` calls past a 200 MiB limit is stopped fast; a child under
   the limit and a quick child end normally; unreadable size gives `memory_watch_lost`; `read_source` passes the production limit; an opt-in test
   (`DEIXIS_P9_PRODUCTION_THRESHOLD=1`) stops the real source child at the production limit.
4. Record: `scripts/p9/child_memory_probe.py`, D159 at the top of `docs/decisions.md`, a line in `docs/product/p9-hardening-plan.md` next to F09 and the D138
   open item.

## Limits to state in D159

One input shape per child; OCR and JATS overshoot is not removed; Windows has no limit; the arXiv growth is bounded by the 60 s clock (about
30 MiB/s measured), so a faster allocation can still overshoot the poll interval; the watcher reads current, not peak, size.
