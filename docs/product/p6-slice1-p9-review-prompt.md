<!-- Plan review: gpt-6-sol high, round 1: 4 high (rollback vs assembly and word_count, claim-less sections uncounted, cited passage resolved by id not by source, on-screen wording overstated) and 1 medium; round 2: 2 high (insufficient_evidence sentences outside the rollback scope, assembly baseline independent of interruption); round 3: 1 high (report-level finding with null claim_key had no section_id or heading); all folded in below, round 3's fix not re-reviewed (the three-round cap) -->

# Task: P6 slice 1, batch P9 (review) — `report_review`, and rolling back a repair that breaks support

Repo: the git worktree you are started in (`-C`). All paths below are relative to it. (The file
`p6-slice1-p9-prompt.md` is an older batch, the report run's own budget; this batch is the plan's 1f and is named
`p9-review` only to keep that file.)

Today `run_report` (`backend/deixis/workflow/report/sections.py`) ends after assembly with the comment "Report
review is added by 1f", and the report screen says "this report was not reviewed by a model or a person"
(`apps/web/src/report/ReportView.tsx`, the `evidence-report-provenance` paragraph). This batch adds the review
step (plan `docs/product/p6-slice1-report-run.md`, "1f", ~line 2111, and its schema at ~line 377) and makes the
screen's closing note say exactly what the review did, never more. Read that plan section, D112, D113, D115 and
D116 at the top of `docs/decisions.md`, and `AGENTS.md`.

## What is and is not in code (checked on `ccd32e4`)

- In code and unused: `contracts/research/report-review.schema.json`, `domain/contracts.py` (`ReportReview`,
  `TASK_OUTPUTS["report_review"]`, `REPORT_TASKS`, `_check_report_review` = a bare `pass`), `domain/skill.py`
  `RUNTIME_FILES["report_review"] = ("SKILL.md", "references/report.md")`, the "Report review" section of
  `methods/deixis-research/references/report.md`, fixtures `C_report_review` / `report_review_valid`, and
  `tests/fakes.py::valid_response` (no findings). The `report_target` StepInput field already has `review_scope`
  (always null today).
- Not in code: any call to a `report_review` step, a place to store its result, the code-applied rollback,
  the review in `report_view`, the review on screen, the review's share of the report run's model-call budget
  (`ReportStore.request_report` counts plan + sections + title + one repair per section, not a review).
- `report_phrase_repairs` is append-only and every reader (assembly, `review_methodology.limitations_core`)
  takes the **latest row per (section_id, sentence_id) by rowid**. The rollback must be a new row with outcome
  `reverted_exception` (the migration's CHECK already allows it), never an UPDATE.
- Repairs happen in `phrasing.py::repair_section`; a `kept` repair replaced one sentence of one claim's `text`
  (or an `insufficient_evidence` entry's `reason`) inside `draft_json`; `_location(draft, sentence_id)` resolves
  a sentence id like `IV.3#2` (claim key `#` 1-based sentence order) or `insufficient_evidence.2#1`. The claim
  row `report_claims.text` is the model text; a human edit is a separate revision row and is only allowed after the
  run has finished (`edit_claim`), so no human edit can exist while the report run is still running.

## Decisions taken for this task (the plan's text is the intent; these settle where it is unclear)

1. **When it runs.** After assembly and after `finalize` (the plan's default; the code comment already says so),
   at the end of `run_report`, for both a `valid` and a `draft` report. The review never changes
   `reports.status`, `report_version` or section status. The one code-applied change is the rollback (decision 6).
   One call for the whole report (plan: "minimal, single call"), `optional=True`, `limiter=flow.deps.limiter`,
   operation key `report_review`. A pause or cancel still stops the run (`_checkpoint` after the call); on resume the
   succeeded step returns its stored output, so the rollback must be idempotent (decision 6). On replay (the `report_review` step already `succeeded`) do not
   rebuild the target from the current tables, whose latest repair rows the first pass may already have changed: build
   the stored record from the succeeded step's stored output and the stored StepInput payload
   (`flow.store.step_input_payload(output["step_input_id"])`: its `review_scope` is `sections_reviewed`, its
   `review_sections[].repairs` are the shown repairs), so the record equals the first pass's.
2. **What the model is shown.** New required `report_target` field `review_sections`, `null` for every task
   except `report_review`, where it is a list, one entry per section shown, in report order (abstract, I, III … IX,
   index_terms). II is code-written and is never shown and never counted; a section with no claims (it may still hold `insufficient_evidence` entries) is never shown and is recorded in `sections_not_reviewed` with reason `no_claims`; the `insufficient_evidence` reasons of a section that is shown are not shown either, and the screen says the review read *claims* (decision 9):
   `{section_id, claims: [{claim_key, text, support_type, table_ref, equation_ref, count (object|null),
   citations: [{passage_id|null, cell_id|null, anchor_text|null}]}], repairs: [{sentence_id, before, after}]}`.
   `repairs` lists only the sentences whose **latest** repair row is `kept` for that section **and whose owner is a claim** (its `sentence_id` does not start with `insufficient_evidence.`): a sentence of an `insufficient_evidence` reason has no `report_claims` copy, its id repeats across sections and the finding carries no section id, so such sentences are outside the review's rollback scope and are never shown as repairs. Claim `text` is the
   stored model text (`report_claims.text`), never a human revision. Cited passages go in the StepInput's ordinary
   `passages`, resolved by the **exact `passage_id` stored on the citation link** through the store's by-id passage
   getter (find it; do not use `store.passages_for(source)`, which drops passages of a removed file or an earlier
   extraction that a stored link may still name). A link whose passage cannot be resolved is never replaced by another
   passage: its whole section is not shown and lands in `sections_not_reviewed` with reason `passage_unavailable`, and
   is not counted as reviewed. Each shown passage has its `passage_id` on the allowlist, cited cells and
   their frozen evidence quotes in `report_target.cells` (taken from the frozen snapshot, evidence passages added to
   `passages` because `check_step_input` requires every cell evidence passage id on the allowlist). `plan` is null,
   `review_scope` is the list of shown section ids, `gap_candidates` and `prior_summaries` are empty arrays,
   `repair_request` null, `limitations_core` null. Adding `review_sections` is a schema change to
   `contracts/research/step-input.schema.json` (`required`, like `limitations_core` was added), so: `flow._model_step`
   defaults it to `None` exactly as it defaults `limitations_core`; `check_step_input` checks
   `(review_sections is not None) == (task_type == "report_review")` with a new issue code
   `review_sections_mismatch`, and that every citation names a passage or cell that is in the allowlist and every
   `review_scope` id equals a shown section; every `report_target` in `tests/fixtures/research/step-inputs.json`
   gets `"review_sections": null` and `C_report_review` gets a real, valid value.
3. **Size.** Sections are admitted whole, in report order, until an estimated token budget is spent
   (`REVIEW_BUDGET_TOKENS = 30000`, same four-characters-per-token estimate `selection._estimated_tokens` uses:
   count the claims block, the cells and the passages the section adds that are not already admitted). A section that
   does not fit is not shown and is recorded in the stored review as `sections_not_reviewed` with reason
   `input_too_large`. If not even one section fits, do not call the model; store `status: "not_reviewed"`,
   reason `input_too_large`. Never truncate a passage or a claim to fit.
4. **Storage.** New migration `0057_report_review.sql` (after `0056`; do not edit any old file):
   `ALTER TABLE reports ADD COLUMN review_json TEXT;`. `ReportStore.report()` parses it into `report["review"]`
   (and drops `review_json`), `None` when not run. The stored record is always one of:
   - `{"status": "reviewed", "step_input_id", "sections_reviewed": [ids], "sections_not_reviewed": [{"section_id",
     "reason"}], "findings": [...as returned, plus "section_id": the shown section owning `claim_key`, or `null` for a report-level finding (`claim_key` null, e.g. an abstract-and-body mismatch)], "notes", "reverted":
     [{"sentence_id","section_id"}], "not_reverted": [{"sentence_id","section_id","reason"}]}`
   - `{"status": "not_reviewed", "reason": <code>, "detail": ..., "sections_reviewed": [], "sections_not_reviewed":
     [...], "findings": [], "notes": "", "reverted": [], "not_reverted": []}` for `input_too_large`, an
     `OptionalStepFailed` (`reason` = its reason, e.g. `budget_exhausted`, `model_mismatch`,
     `model_call_failed`) and an invalid output (`reason` = `invalid_model_output`, `detail` = its issues).
   Coverage invariant: `sections_reviewed` plus `sections_not_reviewed` is exactly the report's stored sections
   other than II, each once. A not-shown section's reason is one of `no_claims`, `input_too_large`,
   `passage_unavailable`; for a `not_reviewed` record every such section is listed with the record's reason.
   `save_review(report_id, record)` is a plain overwrite by report id plus one event `report_review_saved` in the
   same transaction (the review is written once per run; a replay writes an equal record).
   Do not add a table.
5. **Validation of the output** (`contracts._check_report_review`, issues go through the existing bounded schema
   repair, no new loop): every non-null `claim_key` must be a claim key in `review_sections`
   (`review_claim_unknown`); every non-null `sentence_id` must be in the shown `repairs` of that claim's section
   (`review_sentence_not_repaired`) and, when `claim_key` is also set, must start with `claim_key + "#"`
   (`review_sentence_claim_mismatch`); a `support_broken` finding must carry a `sentence_id`
   (`support_broken_without_sentence`) — a `support_broken` about a claim as a whole is not something code can
   act on, so the model must use another code for it. An `insufficient_evidence.N#K` sentence id is never valid (never shown). Claim keys are unique in a report
   because they start with the section id, so a shown `sentence_id` names exactly one claim.
6. **The rollback (fail closed).** For every finding with `code == "support_broken"` and a `sentence_id`: revert
   only when (a) the latest repair row for that sentence is `kept`, and (b) the sentence currently at that position
   in the stored text still equals the row's `after` (compared as `phrasebank.sentences` split, exact string). Then
   put the row's `before` text back at that position in **both** `report_claims.text` and the section's
   `draft_json` (claim `text`, or `insufficient_evidence[i].reason`), append a `report_phrase_repairs` row
   (`before` = the repaired sentence, `after` = the restored original, outcome `reverted_exception`), write event
   `report_repair_reverted`, all in one transaction, one transaction per sentence, and list it in `reverted`. If
   (a) or (b) fails, change nothing and list it in `not_reverted` with reason `not_kept` or `text_changed`. Running
   the same review twice (resume replay) must revert nothing the second time: if the latest row for the sentence is
   already `reverted_exception` skip it silently and keep the earlier `reverted` entry out of the second record's
   `not_reverted`; the stored record of a replay must equal the first one, so build `reverted`/`not_reverted` from
   the step's finding list plus the repair rows (a sentence already rolled back by this report's review counts as
   `reverted`). Fail closed on assembly too, with a rule that does not depend on how far an interrupted pass got: a rollback is
   applied only when `assembly.run_assembly_checks` (the same non-warning error filter `run_report` uses) shows **no
   error** for the report both before the rollback and after it. So on a `draft` report (assembly errors exist) no
   sentence is rolled back and each `support_broken` sentence lands in `not_reverted` with reason
   `report_has_assembly_errors`; on a clean report each rollback transaction recomputes the section's `word_count`
   from the restored draft (`_word_count` in `sections.py`), applies the change, runs the checks, and if any error
   appeared rolls the whole transaction back (nothing changes, no repair row) and lists the sentence in
   `not_reverted` with reason `would_break_assembly`. Checks (a) and (b) are made inside that same transaction,
   against **both** copies (`report_claims.text` and the `draft_json` claim): if either differs from what `after`
   implies, change neither copy (`text_changed`). The report's status, version and every other section stay as they
   are (a `valid` report is never demoted by this step). If
   `run_assembly_checks` is not read-only (it writes anything), stop and report instead of using it here.
   Never touch any other sentence, claim, citation link,
   anchor, count or section status. Unit-test that a sentence whose finding is any other code is not reverted, and
   that after a rollback `assembly.run_assembly_checks` reports the same errors as before it (the restored
   original has the same numbers, math spans and anchors, since the repair check required that).
7. **Budget.** `ReportStore.request_report`'s formula gets one more model step: `(1 + section_count + 1 +
   section_count + 1) * (1 + MAX_SCHEMA_REPAIRS)` (still floored by `REPORT_CALL_FLOOR`). With today's ten model-written sections and one schema repair the floor of 50 still
   wins, so the stored number does not change for a normal report: test the formula itself (monkeypatch
   `REPORT_CALL_FLOOR` low or the repair count high) rather than expecting a new literal, and update a test only if
   one really pins the term count. This closes the handoff's open question 3 (the report run has its own budget); say so in the
   decision, do not change `TEST_EFFORT_BUDGETS`.
8. **Method package.** `methods/deixis-research/references/report.md` "Report review" section: add a short
   paragraph saying what the model receives (`report_target.review_sections`: each shown section's claims with their
   citation anchors and the sentences a repair changed, `repairs[].before` / `after`) and that `sentence_id` and
   `claim_key` must be copied from there. Keep every existing rule. This moves `skill_package_hash`; report the
   old and new hash in your final message. Update `provenance.json` only if the integrity check or an existing test
   needs it. No other methods file changes.
9. **Screen.** `report_view` returns `review` (the stored record or `null`). `apps/web/src/api.ts` gets the type.
   The closing paragraph of `ReportView.tsx` (`evidence-report-provenance`) keeps its anchors sentence and
   replaces its last sentence by one of these, through `t()` with Turkish strings in `i18n.ts` like the others:
   - `review` null: "Whether each passage supports its claim was not checked, and this report was not reviewed by
     a model or a person." (unchanged)
   - `reviewed`: "A second model read the claims of {n} of {m} sections against their cited passages and cells and
     flagged {k} possible problems. That is a model's reading, not peer review, and it can miss errors;
     whether each passage supports its claim was not checked by code." plus, when `reverted` is non-empty, "The
     model flagged {r} rewritten sentences as possibly no longer matching their sources; they were returned to
     their original wording.", and when `sections_not_reviewed` is non-empty, "Not read: {section names}."
     (`n` = `sections_reviewed`, `m` = `n` + `sections_not_reviewed`; pluralised properly; section names in the
     report language map already in the component). The reasons of `sections_not_reviewed` are not spelled out.
   - `not_reviewed`: "No accepted review result exists for this report ({reason}); whether a second model read
     it in part is not recorded here."
     where `reason` is a short fixed English phrase per code (`input_too_large`, `budget_exhausted`,
     `model_mismatch`, `model_call_failed`, `invalid_model_output`, anything else = "the review step failed").
   Findings, when there are any, are listed under the paragraph in a `<details>` "Review findings ({k})": one
   line per finding "{section heading, or "Report" when `section_id` is null} · {code label} · {text}", labelled as model findings; codes get plain
   labels (support_broken "Support no longer matches", count_error "Count", terminology_inconsistent
   "Terminology", abstract_body_mismatch "Abstract and body differ", equation_mismatch "Equation",
   comparability_error "Comparability", other "Other"). No red, no success ticks; a finding is a flag, not a
   verdict. Model text is rendered as plain text. The timeline label for `model:report_review`
   (`apps/web/src/Transcript.tsx`, next to `model:report_section`) is "Report review" (find how other kinds
   are labelled and use the same mechanism). No other screen change; Markdown export is P12 and not here.
10. **Test doubles.** `tests/fakes.py::valid_response("report_review")` keeps returning no findings. Add a way for
    a test to script findings without editing `valid_response` for everyone (a small subclass or a callable the
    test passes, following how other tests script special outputs). In `tests/acceptance/fixture_server.py` add a
    `report_review` branch (the default: no findings) and a question marker `[report-review-finding]` that returns
    one `other` finding for the first claim of the first shown section. Do not use a real model anywhere.

## Files you may change

`backend/deixis/workflow/report/review.py` (new), `sections.py` (call site only), `store.py` (`report()` parsing,
`save_review`, `revert_repair`, budget formula), `backend/deixis/workflow/views.py` (`report_view` only),
`backend/deixis/workflow/flow.py` (only the `report_target` default and, if it needs it, nothing else),
`backend/deixis/domain/contracts.py` (`_check_report_review`, `check_step_input` branch),
`backend/deixis/storage/migrations/0057_report_review.sql` (new), `contracts/research/step-input.schema.json`,
`methods/deixis-research/references/report.md` (+ `provenance.json` only if needed),
`tests/fixtures/research/step-inputs.json` and `fake-outputs.json`, `tests/fakes.py`, `tests/test_report_review.py`
(new), `tests/test_report_*.py` and `tests/test_contracts.py` / `tests/test_skill_package.py` where a pinned value
changes, `tests/acceptance/fixture_server.py`, `apps/web/src/report/ReportView.tsx`, `apps/web/src/api.ts`,
`apps/web/src/i18n.ts`, `apps/web/src/Transcript.tsx`, `apps/web/e2e/report.spec.ts`.

## Files you must not change

`docs/decisions.md`, `docs/product/*` (the orchestrator writes those), `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `.local/`, `../DEIXIS-s30`, `sw-status.md`, `assembly.py` (read only: if a rollback
makes it fail, stop and report), `phrasing.py` (read only), any old migration, `TEST_EFFORT_BUDGETS`, and any
`apps/web` file not listed. No provider, no real model call, no port 8765 or 8858–8864.

## Tests to add

- `tests/test_report_review.py`: (a) a review with no findings stores `reviewed` with the right
  `sections_reviewed` and reverts nothing; (b) a `support_broken` finding for a `kept` repaired sentence restores the
  original in `report_claims.text` and `draft_json`, appends a `reverted_exception` row, changes nothing else
  (other sentences, section status, `reports.status`, `report_version`), and assembly errors are unchanged;
  (c) a finding with another code on the same sentence reverts nothing; (d) a `support_broken` finding for a sentence
  that is not `kept` or whose text no longer equals `after` reverts nothing and lands in `not_reverted`;
  (e) running the review step twice (resume replay) reverts once and stores an equal record; (f0) a report-level finding (`claim_key` and `sentence_id` both null, code `abstract_body_mismatch`) is accepted, stored with `section_id: null`, and shown under the heading "Report"; (f) an unknown
  `claim_key`, an unknown/unrepaired `sentence_id`, a mismatched pair and a `support_broken` without a sentence id
  each produce their issue code through `validate_model_output`; (g) `OptionalStepFailed` (a `FakeAdapter` model
  mismatch or a call failure) gives `not_reviewed` with the reason and leaves the report `valid` with its version;
  (h) an input over the token budget: the later sections land in `sections_not_reviewed` (monkeypatch
  `REVIEW_BUDGET_TOKENS` small), and with a budget of 0 no model call is made; (i) the review's StepInput shows
  only `kept` repairs, never II, and passes `check_step_input`; (j) the review runs for a `draft` report too, does not change its status, and rolls nothing back
  (`report_has_assembly_errors`); (k) a cancel/pause between finalize and review leaves the report as finalized and
  the resumed run reviews it once; (l) an interruption after the first of two rollbacks and before `save_review`:
  the resumed run produces the same texts and an equal record as an uninterrupted run; (m) a rollback that would
  make assembly fail (script a repaired sentence whose original breaks a rule) changes nothing and is listed as
  `would_break_assembly`.
- `tests/test_report_api.py` (or the file that already tests `report_view`): the view returns `review` null before a
  review and the stored record after.
- The budget test for the new formula; `check_step_input` cases for `review_sections_mismatch`.
- Playwright (`apps/web/e2e/report.spec.ts`): default run shows the "A second model read … 0 findings" closing note
  and never the old "not reviewed by a model or a person" sentence; the `[report-review-finding]` marker shows a
  finding in the "Review findings" details and the count in the note; a `page.route` fulfilment of the report
  GET with `review` set to a `not_reviewed` record shows the "review did not run" note. Assert the exact claims the
  note makes (counts, "Not read"), not just that some text exists.

## Checks to run (in the worktree)

`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` in full (one known memory-limit failure is
accepted: name it; a test that fails only under parallel load: rerun it alone and say so).
`cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new ones) and
`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p9 npm run test:acceptance` against the fresh build if the sandbox
lets you run it; if it does not, say so and the orchestrator will run it. Report test counts before and after.

## Rules

- No git state-changing commands (no add, commit, stash, checkout, reset). Leave everything uncommitted.
- Do not invent. Where the plan, the code or this prompt disagree or a thing is missing, say what you found and
  which way you went. Report every place you used your own judgement.
- Results must say what they measure: a fake model shows workflow behavior, not review quality; nothing here
  measures how many errors a real review catches (that is P15/P16).
- Final message: files changed, the old and new `skill_package_hash`, test counts, any check you could not run,
  and the list of judgement calls.
