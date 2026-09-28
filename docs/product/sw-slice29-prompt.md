# Task: SW slice 29: `standard`'s full-text fetch limit (SW24)

**Run this prompt only when row 29 of `docs/product/sw-status.md` names the owner's answers to A, B, C and D** (for
example `dosya hazır; A1, B1, C1, D1 önerildiği gibi …`). If row 29 names no answer to any of A–D, stop at once and
change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice29-fetch-limit.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice29-fetch-limit.md` and check that
`git status --porcelain docs/product/sw-slice29-fetch-limit.md docs/product/sw-slice29-prompt.md` prints nothing. If the
plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message. The
plan and the replay in `.local/sw-slice29-fetch-limit-replay-2026-09-28/` are the only sources of truth; do not re-run
or edit the replay. List every place where you used your own judgement.

**Which part to run.** Read row 29.
- `dosya hazır` with the owner's answers and A1: run **Record** below. B2 or D2 alongside A1: also the matching item
  under **Extras**.
- `dosya hazır` with A2 or A3: run **Build** below (and **Extras** for B2 / D2).
- `uygulanıyor`: an earlier run stopped; read the working tree and finish, never start over by discarding changes. If it
  reads `uygulanıyor: acceptance failed` or `uygulanıyor: cap reached; sahip kararı`, stop and change nothing.
- `uygulandı, inceleme bekliyor`, `kapandı` or `sahip kararı bekliyor: …`: stop and change nothing.

## Rules

1. **Git.** One commit for the whole slice, on `main`, pushed to `origin main`, only after full pytest passes. No
   branch, no pull request, no `Co-authored-by` or any AI attribution in the message. Before pushing, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by` and strip any trailer it finds. The owner's
   working-tree files stay untouched and uncommitted: `TODO.md`, `.vscode/`, `scripts/local_index.py`, anything else that
   is not this slice's. `.local/` is never committed.
2. **Review rule (owner, D105).** Sol (`gpt-6-sol` · high) blocks only on high-severity findings: at most 3 plan rounds
   and 4 code rounds. You do not run the review.
3. **Port 8765 and the live library are off limits.** The live acceptance (A2 or A3 only) uses its own servers and data
   directories under `.local/`; from the live data directory only `codex-home` is used, through `DEIXIS_CODEX_HOME`.
4. **Model (A2 or A3 only).** Every product call: connection `codex`, `requested_model` `gpt-5.6-luna`,
   `reasoning_effort` `medium`. Caps in model sessions, repairs and re-sends included: A2 quantum 200, medicine 220; A3
   quantum 360, medicine 360. Never open a session past a cap; reaching it stops that run (row 29
   `uygulanıyor: cap reached; sahip kararı`). On a quota or rate-limit error stop and write where; on `client_timeout`
   resume once after 10 minutes; never switch model or connection. Under A1 no model call is made at all.
5. **Python:** `PYTHONPATH=backend uv run pytest …` and `PYTHONPATH=backend:. uv run --no-sync python …`, native arm64.
6. **Words.** Every number with its sample size, machine and model; one run is one run; an estimate is called an
   estimate.

## Record (A1)

1. Row 29: `uygulanıyor`.
2. `backend/deixis/domain/rules.py`: the dated D111 comment above `FULLTEXT_WORK_LIMIT` from the plan's task outline. No
   value changes.
3. D111 at the top of `docs/decisions.md`, from the plan's task outline and "Numbers we have": the replay (12 libraries,
   stored plans reproduced exactly), the frozen rule and its result (gain 9.7 at 300, only 300 reaches 75%, +17.2 min
   estimated), the 300 / 50 row (a fetch change alone reads nothing more), medicine's PDF finding, and the owner's
   answers to B and D. Limits as in the plan.
4. SW24 in `docs/product/search-workflow-review-2026-09-18.md`: **Status** "closed by D111 (slice 29): measured, not
   changed".
5. Full pytest; `git diff --check`; row 29 → `uygulandı, inceleme bekliyor` with the pytest count; one commit; push.

## Build (A2 or A3)

1. Row 29: `uygulanıyor`.
2. `rules.py`: `FULLTEXT_WORK_LIMIT["standard"]` and `FULLTEXT_READ_LIMIT["standard"]` to the chosen pair (A2 150 / 75,
   A3 300 / 150) with the dated D111 comment; nothing else in the file changes.
3. Tests as the plan's task outline names them; grep for any other hard-coded `standard` limit. Full pytest green before
   the acceptance.
4. Live acceptance exactly as the plan's "Live acceptance" section: folder `.local/sw-slice29-acceptance-<date>/`, its
   `protocol.md` with the plan's frozen expectations written before the first request, slice 27's `drive.py` and
   `measure.py` copied and pointed at the new folder, quantum `standard` then medicine `standard` (C2: quantum twice).
5. Judge the three acceptance conditions. If condition 1 or 3 fails with the excess in the fetch or the reading: put the
   constants back to 100 / 50, keep the tests matching, write the numbers into row 29 and D111 ("tried, returned"), and
   still commit the record. If it passes: D111 with measured times beside the replay's estimates.
6. SW24's **Status** closed by D111; full pytest; `git diff --check`; row 29 → `uygulandı, inceleme bekliyor` with the
   run numbers; one commit; push.

## Extras

- **B2:** `FULLTEXT_READ_LIMIT["standard"]` 50 → 60, fetch unchanged (under A1) with its D111 comment and the
  `test_adjudication.py` parameter `("standard", 120, 60)`. Say in D111 that it was chosen after the numbers.
- **D2:** write the owner's new `standard` target into D111 and K7's row in `sw-status.md`, word for word as row 29
  gives it.

## Close

Final message: the plan's commit hash, the commit you made, files changed (from `git status --porcelain`, minus the
owner's), pytest count, and under A2 / A3 each run's time, calls and reference counts beside the frozen expectations.
