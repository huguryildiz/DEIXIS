# Task: SW slice 26: a trial protocol is not an include, and the code query stops welding a verb into a phrase

**Run this prompt only when row 26 of `docs/product/sw-status.md` names A1, B1, C1, D1, E1 and F1** (its status reads
`plan …; A1, B1, C1, D1, E1, F1 önerildiği gibi …`). If row 26 names a different answer to any of A–F, or none, stop at
once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice26-protocol-results-and-phrases.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice26-protocol-results-and-phrases.md` and check that
`git status --porcelain docs/product/sw-slice26-protocol-results-and-phrases.md docs/product/sw-slice26-prompt.md`
prints nothing. If the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your
final message. Do not pull, fetch or change branches to get it. The plan is the only source of truth for this slice.
Where it departs from SW25's and SW26's "Return to" lines (a title rule that sends a would-be include to the queue
rather than excluding; a cut only in clauses inverted by an auxiliary; spelling and OpenAlex's budget as notes, not
code), the plan wins. List every place where you used your own judgement.

**Which part to run.** Read row 26.
- Row 26 is `plan` or `dosya hazır` and names the owner's answers without `uygulanıyor`, `uygulandı` or `kapandı`: run
  the build below.
- Row 26 is `uygulanıyor`: an earlier run stopped; read the working tree, finish, never start over by discarding
  changes. If it reads `uygulanıyor: replay failed` or `uygulanıyor: dry run control changed; sahip kararı`, stop and
  change nothing: the owner decides.
- Row 26 is `uygulandı, inceleme bekliyor` or `kapandı`: stop and change nothing.
- Anything else: stop and change nothing.

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. `git add` nothing. The
   owner's working-tree files stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py`, and anything else that is
   not this slice's. Rows 17, 24 and 25 of `sw-status.md` are not touched. In your final message list every file you
   created or changed (from `git status --porcelain`, minus those).
2. **Review rule (owner, D105).** Sol (`gpt-6-sol` · high) blocks only on high-severity findings: at most 3 plan rounds
   and 4 code rounds. You do not run the review; you leave the tree ready for it.
3. **Port 8765 and the live library are off limits.** The dry run uses its own data directories under `.local/`; from
   the live data directory only `codex-home` is used, through `DEIXIS_CODEX_HOME`. No provider request anywhere.
4. **Model.** Every live call: connection `codex`, `requested_model` `gpt-5.6-luna`, `reasoning_effort` `medium`; 19
   planned calls and **at most 22 model sessions in total**, schema repairs and re-sends included (plan decision
   5.3); never open a 23rd, and reaching the cap first is a stop (row 26 `uygulanıyor: dry run cap reached; sahip
   kararı`). On a quota or rate-limit error stop and write where; on `client_timeout` resume
   once after 10 minutes; never switch model or connection.
5. **Python:** `PYTHONPATH=backend uv run pytest …` and `PYTHONPATH=backend:. uv run --no-sync python …`, native arm64.
   Scripts that read stored libraries use `immutable=1` URIs.
6. **Words.** Every number with its sample size, machine and model; one run is one run. A reading by you or a model is a
   model reading, never a human verification.

## Build

1. **Row.** `sw-status.md` row 26: `uygulanıyor`.
2. **Method sentence** (plan decision 2.1): `methods/deixis-research/references/fulltext-adjudication.md`, after the
   future-work sentence: a part about a result, an effect or a measured outcome is `present` when a passage reports
   that result or an analysis of it as a finding of this paper, whatever its source (own trial or experiment,
   re-analysis, a review's pooled estimate, a derivation or simulation); a result the paper only plans to measure is not
   reported, so a protocol, registration or design paper does not contain it (`absent` when the passages show no result
   is reported yet, `unclear` when they cannot tell). Do not write "own data" (Sol r1). No field
   word. The plan's sentence is the meaning to keep; the final wording is yours. Update `tests/test_skill_package.py:83-89`.
3. **Title rule** (2.2–2.4), `backend/deixis/workflow/adjudication.py`: `protocol_title(title) -> str | None` with the
   plan's pattern byte for byte (it is `.local/sw-slice26-plan-2026-09-27/protocol_titles.py`'s `"proposed"` rule);
   `with_title(code, title) -> tuple[str, str | None]` that turns `all_parts_verified` **and `criterion_absent`** into
   `protocol_title` with note `protocol_title:<combined code>:<matched words>` when the title names a protocol, and
   passes every other code through (a protocol-titled work is neither included nor excluded by code; Sol r1); `FRESH_MODEL_CODES` gains `protocol_title`; the module docstring says a work is
   included or excluded without the user only when, in addition, its read version's title names no study protocol.
   `backend/deixis/domain/reason_codes.py`: `ReasonCode("protocol_title", "fulltext", "unresolved", "code",
   "human_queue")` with its comment. `backend/deixis/workflow/flow.py` `_close_adjudication` (`:3815-3868`): after
   `combine` (`:3852`), apply `with_title` to the read version's own title and write the code and note through the
   existing write path (`_write_adjudication_codes` may need to carry a note; keep every other code's write
   byte-identical). `combine` and `verdict` do not change.
4. **Queue and screen** (2.5): `backend/deixis/workflow/queue.py` `KIND_OF["protocol_title"] = "confirm_results"` and
   `_question` returning `None` for that kind; `apps/web/src/api.ts:449` `QueueKind` gains `confirm_results`;
   `apps/web/src/labels.ts` `queueKindLabels` ("Confirm the results") and `queueReasons.protocol_title` ("The title names a
   study protocol, so the reading neither included nor excluded this work."); `apps/web/src/HumanQueue.tsx:409-414` the question for this
   kind ("The title names a study protocol. Does this paper report its own results for every part?"); Turkish for all
   three in `apps/web/src/i18n.ts`. Read `.impeccable.md` first; no new component, no new dependency.
5. **Verb cut** (3.1–3.3): `backend/deixis/domain/vocabulary_words.py` gains `AUXILIARIES` and `EFFECT_VERBS` (the
   plan's lists, which are `verb_split.py`'s; extend the module docstring to name a verb list);
   `backend/deixis/domain/vocabulary.py::_phrases` gains the cut exactly as `verb_split.py::phrases_new` does it (an
   inverted clause by a token or by the stripped frame's last word; punctuation ends it; one cut per candidate phrase at
   the last listed word with a content word on each side; left keeps the position, right is `outcome`); update the
   module docstring. Every test that fails only because of the cut gets the cut's output and nothing else; list each in
   your final message.
6. **Notes** (3.4, 3.5): the comment above `OPENALEX_API_KEY` in `docs/product/providers.env.example` with only what was
   observed (2026-09-26, 14 researches, HTTP 429, `x-ratelimit-remaining: 0`, reset about 8.4 hours; a key avoids the
   shared budget). No number from OpenAlex's documentation unless you read it there, with its date; no network call to
   read it.
7. **Tests** (plan decision 4): `tests/test_adjudication.py`, `tests/test_adjudication_flow.py`, `tests/test_queue.py`,
   `tests/test_queue_api.py`, `tests/test_skill_package.py`, `tests/test_vocabulary.py` (with the single-result-part
   criterion and the all-absent two-part case on a protocol title, plan decision 4), and the Playwright case (1440 and
   390 px; add a SYNTHETIC `[protocol-title]` scenario to `tests/acceptance/fixture_server.py` only if none can show a
   `confirm_results` row). Every fixture stays SYNTHETIC and field-independent. No test touches the network.
8. **Acceptance** (plan decision 5), scripts and outputs under `.local/sw-slice26-acceptance-<YYYY-MM-DD>/`:
   - Full pytest (report "the known single failure apart, the rest of the full run passed" with counts; the known one is
     `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
     `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest migration `0055`;
     `uv.lock` unchanged; the new `skill_package_hash` in your final message.
   - **Replay (a):** as `.local/sw-slice26-plan-2026-09-27/replay_reading.py`, but calling the product's `with_title`:
     455 of 455 stored codes reproduced before the title rule; exactly the 3 protocols of `qtre-sw-detailed-r1` change,
     from `all_parts_verified` to `protocol_title`; 0 changes in quantum; no `criterion_absent` changes. **Replay (b):** the 13 questions of
     `.local/sw-slice26-plan-2026-09-27/verb-split.json` through `vocabulary.extract` / `_phrases` give its `new`
     phrases and positions byte for byte (4 changed, 9 unchanged). Anything else: stop, row 26
     `uygulanıyor: replay failed`, and write the difference.
   - **Dry run (D1), 19 calls,** exactly as plan decision 5.3: copies of `data-qtre-sw-detailed-r1` and
     `data-q1-sw-standard-r1` in their own directories; 8 works × 2 reading runs through `ResearchFlow._model_step`
     (`fulltext_adjudication`, the passages of each work's latest stored reading StepInput, its stored criterion, the
     new method text), each pair's code through `combine` and `with_title` beside the stored code; then the medicine
     question's new phrases through `flow._vocabulary_labels` (3 calls). Apply the plan's stop rules: each of the five
     controls is compared with its stored decision per part and combined (stored: every part `present` with a verified
     quote in both runs, `all_parts_verified`) and any deviation stops; every model session counts against the cap of
     22; report the
     protocols' codes against the frozen expectation (2 or 3 of 3 kept out by the model alone), every control's labels,
     and the labelling's votes. Read the 6 protocol runs' outcome-part rationales and write what they say.
9. **Documents** (plan decision 6): D107 at the top of `docs/decisions.md` (if D107 exists already, the next free number,
   and say so): decision, the replay and dry-run numbers, Limits (the title rule is English and hand-written, measured
   on two fields plus packet; it withholds both an automatic include and an automatic exclusion and never excludes; the cut covers inverted clauses only; spelling
   variants are not written; one machine, one model). In `docs/product/search-workflow-review-2026-09-18.md`: SW25's
   and SW26's status lines ("implemented in slice 26 (D107)"), SW25's with the spelling note. Row 26:
   `uygulandı, inceleme bekliyor` with the headline numbers. Nothing else in `sw-status.md`.

## Close

Commit nothing. The final message, in Turkish, gives: the plan's commit hash; the changed files; the test counts; the new
`skill_package_hash`; replay (a) and (b); the dry run's protocol and control codes, the labelling's blocks, and the
protocols' rationales in one line each; each judgement call; every file created or changed.
