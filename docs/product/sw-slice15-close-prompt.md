# Task: close SW slice 15 (three review findings), then write the slice 16 plan prompt

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. Master file: `docs/product/sw-status.md`. Run as Opus · high.

## Where things stand (24 September 2026)

- Slice 15, citation chaining, is on `main`. The implementation is `d6f84bd` and the fixes from the first review are
  `6b8cf26`. D95 is at the top of `docs/decisions.md`. Row 15 reads `uygulandı, inceleme bekliyor`.
- The live acceptance passed on the third attempt. The plan room was changed to 12 / 12 / 12 after the results were
  seen, by joint decision with `gpt-6-sol` · medium (D95). Records: `.local/sw-slice15-acceptance-2026-09-23/`
  (`result.md`, `attempt1.md`, `attempt2.md`, `protocol-3.md`, `sol-decision*.md`).
- The full review by `gpt-6-sol` · high accepted the slice with fixes (`sol-review-high.md`); `6b8cf26` applied them.
  Sol's check of those fixes (`sol-fix-check-high.md`, the review row dated 2026-09-24, "15 düzeltmeleri") left
  **three findings open**. Closing them is this task.
- Owner's rule for this slice: when the reviewer asks for a fix, the implementer and Sol settle it between themselves.
  The owner is not asked.

## Ground rules

1. **Git.** Run `git pull --ff-only` first and stay on `main`. Make one commit per step and run `git push origin main`
   after each. No branch, no PR, no AI attribution, no co-author. Before every push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave the owner's files
   alone: `TODO.md`, `.vscode/`, `scripts/local_index.py`.
2. **Tests before code.** Every fix gets a test that fails on the current code first.
3. **No network, no live model.**
4. **Do not start, stop or query the service on port 8765, and do not open the product database.**
5. **Python:** `PYTHONPATH=backend:. uv run --no-sync ...` from the repo root, native arm64.
6. **Model contract unchanged.** `skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`.
7. **Two invariants hold:**
   - A research that never chained behaves exactly as before.
   - Within one run, the keyword path (ranking, keyword abstract read plan, the first three full-text groups) is the
     same with chaining on and off. `test_the_keyword_ranking_read_plan_and_fetch_plan_are_unchanged_by_chaining`
     must stay green.
8. **Codex:** call the real binary `/Applications/ChatGPT.app/Contents/Resources/codex` and pipe the prompt with `-`:
   `codex exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only --skip-git-repo-check -C "$PWD" -o out.md - < prompt.md`.
   Sol cannot run pytest in read-only mode. Say so when you pass on its verdict.

## Step 1: close the three findings

1. **High — a failed chain read is called again on resume.**
   - The setup: a chain read call fails. That call is optional since `6b8cf26`, so the run goes on. The run is then
     paused for another reason and resumed.
   - The bug: `_abstract_stage` counts a step as answered only if it succeeded or had invalid output
     (`flow.py`, `answered`). So the failed chain step is sent and charged again.
   - The fix: for the chain prefix only, a `failed` / `outcome_unknown` step counts as answered and reads as `None`.
     The keyword stage keeps its rule.
   - The test: the chain read fails, a user pause follows, the run resumes, and no second model call is made for
     that key.
2. **High — pre-D93 records are misread as chain-only.**
   - The bug: `Store.chain_only_works` reads a work's origin from `candidate_hits` alone. Researches older than D93
     have no keyword hits in that table. If the chain adds a hit to one of their keyword works, the next run drops
     that work from the keyword pool.
   - The fix: a work also counts as a keyword work when any of its candidate rows names a non-chain search
     (`candidates.search_run_id` whose `query_text` does not start with `chain:`).
   - The test: a store-level test that deletes the keyword hits to imitate a pre-D93 research.
3. **Medium — a work a keyword search finds later stays in the chain group.**
   - The bug: `_chain_state` merges the stored `chain_filter` list in without a condition. A work the chain found in
     one run and a keyword search found in the next therefore stays in the chain group.
   - The fix: the chained set is the heads of `chain_only_works` alone.
   - The test: the first run's chain finds W700. The second run's keyword search returns W700. The second fetch plan
     must count W700 in a keyword group, not in `chain`.

Then:
- Run the full pytest. The one known failure is `test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
- Run `git diff --check` and check the hash.
- Commit and push.
- Send Sol · high a fix check that names the three findings and the commit.

If Sol finds nothing left:
- Set row 15 in `sw-status.md` to `kapandı`.
- Write the review row with its "Düzeltme" column filled.
- Update the memory file `slice15-plan.md` (Claude's memory directory) and its line in `MEMORY.md`.
- Commit and push.

If Sol finds more, repeat Step 1. After two rounds, stop and report to the owner.

## Step 2: write the slice 16 plan prompt (do not plan the slice itself)

The owner's order (the row 17a note in `sw-status.md`): 15 closes, then 16, 17, 17a, 18. Slice 16 is "İnsan kuyruğu
(arka uç)". In `docs/product/sw-implementation-plan.md`, item 16 covers SW11.4–7, 11.10–11 and 11.13, with slice 12
as its prerequisite.

Write `docs/product/sw-slice16-plan-prompt.md` in the shape of `docs/product/sw-slice15-plan-prompt.md`:
- the task and why it is next;
- what changed since SW11 was written: D83, D85, D94 and D95, and what they route to "unresolved" today;
- the ground rules from above;
- what to read (SW11 in full, `sw-slice12-*.md`, `workflow/decisions.py` `work_outcome`, the reason-code table);
- what to measure first on the stored acceptance libraries: how many works per effort end in each unresolved reason,
  which of them a person would really have to decide, and how many rows a queue would hold;
- the decisions the owner must take;
- K8 acceptance;
- out of scope: the queue UI (17), the time slice (17a), PDF-waiting (18);
- the final message.

The plan turn runs as Fable · high: the rule is in `sw-status.md`, and the prompt must say so. Set row 16 to
`plan promptu hazır` with a link. Commit and push.

## Final message (in Turkish, plain language first)

- Step 1: what each of the three fixes changed. Include the test names, the pytest count, Sol's verdict and whether
  row 15 is closed.
- Step 2: the path of the plan prompt, and the first sentence the owner should paste into a new chat.
- The commit hashes.
