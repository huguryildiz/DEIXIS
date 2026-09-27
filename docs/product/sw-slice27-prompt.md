# Task: SW slice 27: the medicine re-measurement, with BMI counted as body weight

**Run this prompt only when row 27 of `docs/product/sw-status.md` names the owner's (b) decision and A1, B1, C1, D1, E1,
F1** (its status reads `… (b)'de BMI vücut ağırlığı sayılır, sahibin kararı …; A1, B1, C1, D1, E1, F1 önerildiği gibi …`).
If row 27 names a different answer to any of A–F, or none, stop at once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice27-medicine-remeasure.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice27-medicine-remeasure.md` and check that
`git status --porcelain docs/product/sw-slice27-medicine-remeasure.md docs/product/sw-slice27-prompt.md` prints nothing.
If the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message and
in `protocol.md`: the plan's section "Frozen expectations" is the frozen expectation, frozen by that commit. Do not pull,
fetch or change branches to get it.

The plan is a short amendment. It is slice 25's plan decisions 7, 8 and 9 (`docs/product/sw-slice25-pico-criterion.md`)
and slice 25's prompt, Part B tasks 12–17 (`docs/product/sw-slice25-prompt.md`), with six changes: (1) condition (b)
accepts BMI, only rank 25 is re-decided, and R is rebuilt from 25b's copied decisions plus the plan's pre-work; (2) the
code under test is `142dfa1`; (3) Part B always writes D108; (4) quantum is read from slice 24's folder; (5) everything
else as 25b; (6) a pass does not change the default: gate 2's medicine verdict is descriptive and conditional on the
post-hoc rule, reported beside the one-unit reading, and 24b does not run from this prompt. Where the plan and slice 25's texts differ, the plan wins. Slice 24's plan
(`docs/product/sw-slice24-measurement-campaign.md`) and prompt (`docs/product/sw-slice24-prompt.md`) give the method
wherever slice 25 says "the same". List every place where you used your own judgement.

**Which part to run.** Read the status cells of rows 27, 24 and 17.
- Row 27 is `plan`, `dosya hazır` or names the owner's answers without `uygulanıyor`, `durdu`, `bitti` or `kapandı`: run
  **Part B** from the start. There is no Part A and no Part C; the part keeps 25b's letter.
- Row 27 is `uygulanıyor (27)` or `27 durdu: …`: resume or restart Part B under slice 24's decision 13, reading only the
  folder named in `.local/sw-slice27-active`. Resume only if every frozen file's sha256 still matches that folder's
  `protocol.md` and `git diff --stat 142dfa1 -- backend apps/web contracts methods` is empty; otherwise restart in a new
  folder and keep the old one untouched. If the marker is missing or its folder has no `protocol.md`, start Part B over in
  a new folder. A stop at the paper check (task 2) is final: do not restart it; the owner decides.
- Anything else (including row 27 `kapandı; 27 bitti`): stop and change nothing. This prompt never runs 24b; the default
  decision is the owner's (plan change 6).

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. `git add` nothing. The
   owner's working-tree files stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py`, and anything else that is
   not this slice's. In your final message list every file you created or changed (from `git status --porcelain`, minus
   those).
2. **Part B changes no product file.** Its only tracked edits are `docs/product/sw-status.md` (rows 27 and 24),
   `docs/product/sw-slice27-remeasure-results.md`, SW18's status line in
   `docs/product/search-workflow-review-2026-09-18.md` and D108 at the top of `docs/decisions.md` (always).
   Everything else goes under the run folder in `.local/`.
3. **Port 8765 and the live library are off limits.** Every server uses its own `DEIXIS_DATA_DIR` inside the run folder
   and its own port (8858–8864); from the live data directory only `codex-home` is used, through `DEIXIS_CODEX_HOME`.
4. **Nobody decides for the product.** `DEIXIS_PROTOCOL_APPROVAL=as_proposed`; no term, criterion, block or selection is
   edited, the queue gets no answer, no PDF is added.
5. **Model.** Every role of every research: connection `codex`, `requested_model` `gpt-5.6-luna`, `reasoning_effort`
   `medium`. On a quota or rate-limit error stop and write where (row 27 `27 durdu: <where>`); on `client_timeout` resume
   once after 10 minutes; never switch model or connection.
6. **Network.** Allowed: the product's own traffic from the run servers; the built-in embedding download; read-only
   campaign requests through the copied `net.py` (at most one per second per host, logged), only for the missed-work
   diagnosis (PubMed only if OpenAlex's keyless budget is spent; write it). The reference set needs no request: it is
   rebuilt from copied files.
7. **Python:** `PYTHONPATH=backend:. uv run --no-sync python …`, native arm64. Scripts that read stored libraries use
   `immutable=1` URIs.
8. **Words.** Every number with its sample size, machine and model; one run is one run. An analyst reading is a model
   reading, never a human verification. A reference set and Elicit are lists to compare against, never ground truth.
   Wherever R appears (protocol, reference headers, results), say that the (b) widening was chosen after 25b's stop.

## Part B — the re-measurement

1. **Row, folder, copies.** Row 27: `uygulanıyor (27)`. Create `.local/sw-slice27-remeasure-<YYYY-MM-DD>-<HHMMSS>/` (a name
   that never existed) and start `ledger.jsonl` with the copied `ledger.py`. Copy:
   - from `.local/sw-slice24-campaign-2026-09-26-134050/` the files slice 25's decision 7.1 lists, each checked against
     that folder's `frozen-sha256.json` (as 25b's task 12 did);
   - from `.local/sw-slice25-remeasure-2026-09-26-224554/` the nine files of the plan's change 1.2 table, plus its
     `tre-abstracts/`, `tre-trial-abstracts/` and `whatif/`, each of the nine checked against the plan's sha256;
   - from `.local/sw-slice27-plan-2026-09-27/` the five files of the plan's pre-work table, each checked against the
     plan's sha256, and its `tre-trial-abstracts/` copied as `tre-trial-abstracts-rank25/`;
   - both abstract directories checked against the plan's two frozen lists: the same file names, no more and no fewer,
     and each file's sha256.
   Any mismatch stops the run before anything else. Check that `git diff --stat 142dfa1 -- backend apps/web contracts
   methods` is empty; write the result in the ledger.
2. **Reference set** (plan change 1). Write `tre_decisions27.py`: 25b's `tre_decisions25.py` with exactly these changes,
   and freeze `tre_decisions27.diff` against it: candidate 25's decision and reason are replaced by the plan's (the
   `CAND25` text of the copied `rank25_decisions.py`); ranks 6, 7, 24 and 26 get a ledger note that they stay
   `excluded_b` (the `STAY` texts); rank 25's 11 rows and decisions come from `rank25-decisions.json`; the tables are
   processed in rank order 9, 25, 30 with the stop check after each; the step-4 entry and the headers follow the plan's
   changes 1.5 and 1.6. Ledger entries for ranks 1–30 and 25b's 30 rows are copied from 25b's ledger with a
   `copied_from` field (25b's folder and line number). Candidate 25 is the only new decision; no candidate or row is read
   again (A1, C1). The merge code is unchanged.
   The rebuilt set must equal the pre-work's `r-estimate.json`: |R| = 12, comparator-differs 8, unknown 4, the same R
   and unknown units by PMID. Any difference: stop before any research, row 27 `27 durdu: R rebuild differs`, and write
   the difference. Then the paper check (slice 25 decision 8.7): if |R| < 10 or the unknown share is above 25%, stop
   before any research, row 27 `27 durdu: |R| = <n>, bilinmiyor <share>`, and write why. Write `reference-tre.jsonl`,
   `comparator-differs-tre.jsonl` and `unknown-tre.jsonl` with the headers of change 1.6 (post-hoc widening; Cienfuegos
   2020 as two units under E1).
3. **Freeze** (slice 25 decisions 7.4, 7.5 and 9, as its task 14 spells out). Write `measure25.py`, `gates25.py`,
   `post25.py` and `gates25_selftest.py` exactly as slice 25's task 14 describes, with the diffs `measure25.diff`,
   `gates25.diff` and `post25.diff` against 24a's `measure.py`, `gates.py` and `post.py`. `gates25.py` reads quantum
   from the slice 24 folder and medicine from this one. `post25.py`'s `HERE` is this folder. Run the self-test (its five
   cases plus `post25.py`'s keyless check) before the freeze; any failure stops the run. Start one server with this
   run's environment in an empty data directory, read `skill_package_hash`, stop it; it must equal
   `sha256:a633e9c7091ed3338b0a51d3c7bdb99e524678f5cc4bdb60e1049d8b4a68028a`, otherwise stop. Write `protocol.md`:
   this plan's commit, `142dfa1`, the hash, the sentence "In (b), BMI counts as body weight; the owner chose this on
   2026-09-27 after 25b stopped at |R| = 7, having seen the what-if estimate", E1's double count, the question byte for
   byte, the matrix and ports 8858–8864, the server environment and stop rules of slice 24's `protocol.md`, the gates as
   slice 25 decision 7.5 re-reads them, seed `2409261`, and every frozen file's sha256 (copies, R files,
   `tre_decisions27.py` and `.diff`, the three scripts, their diffs, the self-test). Ledger entry; only then write
   `.local/sw-slice27-active` (folder path and plan commit).
4. **Runs** (slice 25 task 15): the seven medicine researches in slice 24's order, one at a time, 2 minutes apart, with
   slice 24's server environment and the copied driver. The embedding research installs the built-in model in its own
   data directory first. The answer run starts once the reading run has finished, as in slice 24. After each research
   save its view, PRISMA-S export, queue rows and server log, then stop the server.
5. **Measure** (slice 25 task 16). Each research with `post25.py <slug>`, then `gates25.py` once all seven are measured;
   nothing runs 24a's `post.py` or `measure.py`. Report everything slice 25's task 16 lists against the new R and
   Elicit's five, and the analyst sample and second reading exactly as slice 24's decision 10 with seed `2409261` from
   the union of the two `sw` `standard` runs. Add, for slice 26: each `sw` research's code-query phrases (plan step);
   every `protocol_title` row and what became of 24a's three medicine protocol works. Gate 2's medicine numbers are
   computed twice, with Cienfuegos 2020 as two units (|R| = 12) and as one (|R| = 11), both with threshold 2.
6. **Gates and result** (plan change 6). `gates25.py` → `gates.json`. Gates 1, 3 and 4 do not depend on R and are
   reported as usual. Gate 2's medicine verdict is recorded as descriptive and conditional on the post-hoc rule (BMI as
   body weight; Cienfuegos 2020 as two units, while one unit would have stopped the paper check at 26.7%), always with the
   one-unit reading beside it; a pass there is written "passes under the chosen rule". Write
   `docs/product/sw-slice27-remeasure-results.md` in Turkish: a short plain summary first that says the (b) widening was
   chosen after 25b's stop, that Cienfuegos 2020 is counted twice, and that the run does not change the default; then
   every table beside the plan's frozen expectation; next to each gate, the quantum half's commit (`65a7ec8`) and the
   plan's change 4 paragraph in plain words; every deviation from `protocol.md`; the gates' verdicts; what was not
   measured. SW18's status line: the rule used (slice 25 decision 8 with slice 27's (b)), |R|, the unknown share. D108 at
   the top of `docs/decisions.md`, whatever the gates say: the four verdicts, gate 2 both ways, the post-hoc widening,
   the two commits, Limits, and one of two endings. All four pass: "the owner may switch the default in 24b on this
   evidence, within these limits; this run did not switch it". Otherwise: "the default still stays `legacy`". Row 27:
   `kapandı; 27 bitti` with the headline numbers. Row 24: replace only its leading status phrase and keep the rest of the
   cell, including `A1, B1, C1, D1, E1, F1, G1, H1, I1 önerildiği gibi`: `24a bitti; 27 kapıları kaydedildi (dördü de
   geçti, tıbbın kapı 2'si sonradan seçilen kurala bağlı ve betimleyici); varsayılan kararı sahipte` if all four pass;
   otherwise `24a bitti; kapı N geçmedi (27); varsayılan legacy kalır`. Never write `dört kapı geçti`, which slice 24's
   prompt reads as the trigger for its Part B. If gate 2 or 4 fails on medicine and the loss is at the PDF stage, write
   where the loss sits (not in the Europe PMC open-access subset, author manuscript, or later) and leave the next step to
   the owner. Row 25 is not edited. Nothing in this prompt runs 24b.

## Close

Commit nothing. The final message, in Turkish, gives: the plan's commit hash; which part ran; for Part B the rebuilt
|R|, unknown share and tables, what ran and where it stopped if it stopped, the headline numbers next to the frozen
expectation, the gates' verdicts, and what was not measured; the D108 summary; in every case, each judgement call and every file created or changed.
