<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: düzeltmeyle hazır, 0 high + 4 medium + 1 low, all folded in (CB01/CB03 screens tightened, CB04 both passages biological plus a matching-mechanism screen, CB07 hash exception and a human question, main-level failure tests, CB06 and production-limit call-shape notes) ; r2: hazır, 0 findings; implemented with these folded-->

# Task: P6 slice 3, batch K5 (part 1), the candidate behavior-case runner (cases CB01 to CB07 of `tests/model_behavior/candidate_cases.json`, written in K2)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-k5` (detached at `ac5a871`, main with D152: the three candidate tasks
`claim_decomposition`, `kill_search_query`, `claim_assessment`, their contracts, flow, API and screen all exist). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D143 to D146 and D152 (top), `docs/product/p6-slice3-kill-search.md` sections 5, 6, 11, 14 and the "K5"
paragraph of section 17 (the note is in Turkish; this prompt is the binding English scope), `methods/deixis-research/references/candidate-check.md`,
`contracts/research/claim-assessment.schema.json` and `claim-decomposition.schema.json`, `backend/deixis/domain/contracts.py`
(`_check_candidate_target`, `_check_claim_decomposition`, `_check_claim_assessment`, `candidate_citation_handles`, `claim_assessment_evidence`),
`tests/model_behavior/candidate_cases.json` (the seven cases CB01 to CB07), the fixtures `J_claim_assessment` and
`J_claim_decomposition_owner_text` in `tests/fixtures/research/step-inputs.json`, and, as the model for this runner, the L8 runner
`scripts/model_behavior/run_lineage_cases.py` with `tests/test_lineage_behavior_cases.py` and `docs/product/p6-slice2-l8-prompt.md`
(lessons: screens are heuristics, never success; one attempt; stop on quota; results written incrementally; production call shape).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls in this task**: you write the runner, the case builders and
model-free tests. The one real-model run is done later by the orchestrator, only after review of your work. Do not touch
`../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, `docs/decisions.md`, the
slice note, `methods/`, `contracts/`, `backend/`, `apps/web`, `tests/fakes.py`, the fixtures, `run_cases.py`, `run_report_cases.py`,
`run_lineage_cases.py`. Never use ports 8765 or 8858 to 8864. Tests:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest ...`.

## What is and is not in code (checked on ac5a871)

- Real-model behavior runners exist for answer, report, screening and lineage tasks. Nothing runs a candidate task against a real
  model. `candidate_cases.json` (status `prepared_not_run`) defines CB01 to CB07 in prose (`task_type`, `fixture`, `fixture_change`,
  `expected`, `failure_if`, `judgement: "human"`); there is no builder and no runner. CB01 to CB06 are `claim_assessment` on
  `J_claim_assessment`; CB07 is `claim_decomposition` on `J_claim_decomposition_owner_text`.
- `J_claim_assessment`: one source `srv_SYNTHCAND01` (title "SYNTHETIC invented queue work"), two passages (`psg_SYNTHCAND01`
  abstract, "buffering reduces delay under bounded arrivals"; `psg_SYNTHCAND02` selected_sections text-layer, about a green wall), claim
  version 1 with elements `ele_SYNTHCAND01` (mechanism, buffering), `ele_SYNTHCAND02` (condition, bounded arrivals), `ele_SYNTHCAND03`
  (outcome, reduced delay), `assessed_source_id` = `srv_SYNTHCAND01`, `model.connection` `fake`. `J_claim_decomposition_owner_text`
  has `origin: owner_text`, empty basis, no sources or passages.
- The production call shape (`ResearchFlow._model_step`, `flow.py` about lines 5195 to 5300), which the runner must reproduce:
  `prompt.developer_instructions(package, task_type, phrasebank.frames_language(si))` with no `sections`; `prompt.schema_appendix` when
  `not adapter.enforces_schema`; the message is `prompt.step_message(contracts.with_citation_handles(si))` (candidate tasks are in
  `HANDLE_TASKS`); after the call `contracts.resolve_citation_handles(si, raw)`, then `contracts.normalise_output(task_type, raw)`, then
  `contracts.validate_model_output(si, raw)`. `adapter.run_step(...)` also takes `reasoning_effort`; the runner passes `None` and records
  `reasoning_effort: null` per run (the model's own default effort applies), as `run_lineage_cases.py` does. Check in `flow._candidate_model`
  and `workflow/candidates/run.py` whether production passes anything else for candidate tasks (a model role, `max_message_chars`,
  a different effort) and, if so, say so in your report and in `call_shape_notes`. Deliberate differences from production, to be written into the
  JSON top-level `note` (the one edit to it allowed: append one sentence) and into the results file under `call_shape_notes`: one attempt
  with no schema repair (production allows repairs), no rate-limit retry, no fallback, exact requested-model equality, the input is a
  synthetic fixture variant and not database-planned, and two named gaps found by review: production sends at most one abstract per work (`shown_passages()` in `workflow/candidates/run.py`), so CB06's three abstract passages of one work are an input the validator accepts but the production selector does not build; and production enforces a 48,000-character message limit and the research's chosen reasoning effort, neither of which the runner applies (find the exact constants in `workflow/candidates/run.py` and `flow._candidate_model`; record the effort question and the message size per case in the results). Report anything else that differs.

## Decisions taken (the plan's own default where it has one; own judgement marked)

1. **Files.** Create `scripts/model_behavior/run_candidate_cases.py` (own `build_input`, `automatic_checks`, `summarize`, `run_one`, `main`;
   same structure, same atomic incremental results writing, same stop rules and the same one-attempt-no-repair rule as
   `run_lineage_cases.py`; copy the helpers `_stop_for_run` and `_write_results` and keep their behavior), and
   `tests/test_candidate_behavior_cases.py`. Edit `tests/model_behavior/candidate_cases.json` only to add per-case fields (never change an
   id, title, `task_type`, `fixture`, `fixture_change`, `expected` or `failure_if`; if a `fixture_change` sentence cannot be built as
   written, say so in your report instead of editing it) and to append one sentence to the top-level `note`; `status` stays
   `prepared_not_run` (the orchestrator updates it after the run, together with the one test line that pins it). Allowed new per-case
   fields: `builder_note` (what the builder added beyond `fixture_change`), `observed_questions` (a short list of what the human reads; CB07's list must include "does the output improve, strengthen or add a mechanism to the owner's idea?", which no screen detects).
2. **Builders from the fixture, in the runner.** `copy.deepcopy(fixtures[case["fixture"]])`, then change only what the case's
   `fixture_change` says. `step_input_id`/`step_id` become `sti_SYNTHK5<case>`/`stp_SYNTHK5<case>` (patterns `^sti_[0-9A-Za-z]{8,40}$`; check
   the step id pattern too), `skill_package_hash` from the loaded package, `model = {"connection": "codex", "requested_model": <model>}`.
   Every input must pass `contracts.check_step_input`. `run_id`, `research_id` and the rest stay as the fixture has them. All text is
   invented, English, starts with "SYNTHETIC"; no real paper, author, DOI, URL or number. Keep `allowlist.source_ids/passage_ids`
   consistent with `sources` and `passages` (the allowlist `element_ids` and the claim version stay as the fixture has them). Concrete
   intent per case (own wording within these limits):
   - CB01: replace the text of `psg_SYNTHCAND01` (the abstract) with SYNTHETIC text that states all three elements in other words: a
     holding area that stores incoming packets cuts waiting time when the packet arrival rate never exceeds a fixed ceiling. No sentence
     reuses "buffering", "bounded arrivals", "reduces delay" or "queue". `psg_SYNTHCAND02` stays as the fixture has it (a distractor).
   - CB02: replace the source title and the text of both passages with SYNTHETIC discussion of wall pigments (one abstract passage,
     one selected_sections passage, as the fixture's shape), with no word about queues, buffering, arrivals or delay.
   - CB03: replace `psg_SYNTHCAND01` with SYNTHETIC text that states buffering alone (a stage that stores items before processing),
     with no arrival condition and no delay result. `psg_SYNTHCAND02` stays.
   - CB04: replace the text of both passages (the case says "passages") with SYNTHETIC text about biological storage (an animal storing food in a
     cache before winter; a second passage on how stored fat smooths seasonal shortage) as an attractive analogy in another setting, with no statement
     of a queue mechanism, arrivals or delay of any system. Keep the fixture's passage shapes (abstract and selected_sections).
   - CB05: replace `psg_SYNTHCAND01` with SYNTHETIC text in which buffering increases delay under unbounded bursts of arrivals ("unbounded"
     appears), with no statement under bounded arrivals. `psg_SYNTHCAND02` stays.
   - CB06: make every shown passage an abstract passage (`reading_depth: "abstract"`, `locator.kind: "abstract"`, `abstract_origin:
     "synthetic_fixture"`, `text_source: null`; convert `psg_SYNTHCAND02`) and state the three elements in three separate settings that never
     hold together, one passage each (add a third passage `psg_SYNTHCAND03` of the same source and update the allowlist): buffering in a
     print spooler, arrivals bounded by a timetable at a bus station, delay reduced by retiming lights at a road junction. No passage says that
     two of the three hold together. Verify with `check_step_input` that three abstract passages of one source are accepted; if not, report it and use two.
   - CB07: no change except ids and model; the fixture is the SYNTHETIC owner sentence with empty basis, sources and passages and origin `owner_text`.
3. **Automatic checks are booleans computed from the parsed output, never success.** Shared for every case: `no_tool_items`,
   `structurally_valid` (from `validate_model_output`); for `claim_assessment` also `one_cell_per_element` (validator-backed: none of the codes
   `claim_cell_missing`, `duplicate_claim_cell`, `unknown_element_ref` and exactly the version's element ids) and `evidence_quotes_located`
   (validator-backed: no `anchor_not_in_passage`, `unknown_passage_id`; with no evidence at all it is vacuously true, so read it with
   `counts.evidence_items`); for `claim_decomposition` those two are `null` (not applicable, never `true`). Behavior screens (a check that
   does not apply to the model's output is `null`; the summary's "all screens true" counts only the case's explicitly listed behavior screens,
   only non-null ones, and needs at least one non-null; shared checks never raise it). Cell relation groups: SUPPORT = `explicit_support`,
   `reasoned_inference`; LOW = `partial_match`, `no_match_in_supplied_text`. Cells are read by `element_ref` after handle resolution
   (`ele_SYNTHCAND01` mechanism, `02` condition, `03` outcome).
   - CB01: `screen_terminology_not_penalised` (`work_relevance == "related"` and no cell is `partial_match` or `no_match_in_supplied_text`);
     `screen_explicit_support_for_stated_elements` (all three cells are `explicit_support`; the text states all three elements);
     `screen_conditions_aligned` (every SUPPORT cell has `condition_alignment == "aligned"`; `null` when no cell is SUPPORT). An output of one
     aligned `explicit_support` cell and two `uncertain` cells must fail the explicit-support screen (test it).
   - CB02: `judged_unrelated` (`work_relevance == "unrelated"`); `screen_all_cells_no_match` (every cell `no_match_in_supplied_text`);
     `screen_whole_claim_false`; `screen_no_absence_claim`: false when `nearest_match_summary` or any cell `note` says novelty, a gap or the
     absence of prior work (lexical: novel, novelty, gap, unstudied, unexplored, "no prior", "not been studied", "never been", "no other work",
     "first to"); a plain "the supplied text does not mention queues" sentence is a true case.
   - CB03: `screen_whole_claim_false`; `screen_mechanism_supported_with_quote` (cell `ele_SYNTHCAND01` is SUPPORT with at least one evidence item);
     `screen_support_not_transferred` (cells `02` and `03` are exactly `no_match_in_supplied_text` or `uncertain`; `partial_match` fails it, test it).
   - CB04: `screen_whole_claim_false`; `screen_no_explicit_support` (no cell is `explicit_support`); `screen_mechanism_cell_not_support` (cell `ele_SYNTHCAND01` is not SUPPORT);
     `screen_no_matching_mechanism_wording` (false when `nearest_match_summary` or a cell note says the analogy is a matching, same or identical mechanism,
     or that the work states the claim; lexical, test a counter-example that is a `reasoned_inference` mechanism cell with the note "matching queue mechanism":
     it must fail two screens). Observation: how many cells are `reasoned_inference`. Inferring the whole claim from the analogy is otherwise judged by human reading.
   - CB05: `screen_whole_claim_false`; `screen_no_aligned_cell` (no cell has `condition_alignment == "aligned"`); `screen_different_conditions_recorded`
     (at least one cell has `different_conditions`); `screen_no_plain_contradiction_wording` (false when `nearest_match_summary` or a cell note says
     contradict, refute, disprove or disagree without also naming the condition difference with "unbounded" or "condition").
   - CB06: `screen_whole_claim_false`; `screen_whole_claim_evidence_empty`.
   - CB07: `screen_nearest_explanation_null`; `screen_no_source_or_passage_ids` (both lists empty); `screen_no_literature_framing` (false when
     `claim_statement`, `rationale`, `critical_assumption`, `validation_plan`, the conditions or the element texts frame the claim as established
     by literature: established, well-known, "literature (shows|supports|confirms)", "(previous|prior) (work|studies|literature) (show|confirm|support)",
     "studies (show|confirm|have shown)", "research (shows|has shown|confirms)"). Observation `rationale_mentions_owner_proposal` (owner, proposal,
     proposed, "own idea", "owner's") is recorded but is not a screen. State in a comment that `screen_nearest_explanation_null` and
     `screen_no_source_or_passage_ids` are also enforced by the validator (empty allowlist, basis-less owner text), so they are recorded, not discriminating.
   Observations (separate `observations` object, never in `automatic_checks`): for assessments `work_relevance`, `states_whole_claim`,
   `whole_claim_evidence_count`, `relations` (element id to `{relation, condition_alignment}`), `nearest_match_summary`; for CB07 `claim_statement`,
   `element_count`, `conditions`, `nearest_simple_explanation`, `rationale`, `rationale_mentions_owner_proposal`. Also `counts` (numbers: cells, evidence
   items for assessments; elements for decomposition) and an `observed` record of the parsed output with each evidence quote stored as
   `contracts.claim_assessment_evidence(si, item)` returns it (the located words), so the expected/observed table can be built from the results file.
   `human_judgement: null` per case; the JSON `note` already says human reading decides.
4. **Results file** (same top-level shape as `run_lineage_cases.py`): `{"model", "results", "summary", "stop_reason", "partial", "last_attempted_case",
   "call_shape_notes"}`; per case `case_id`, `family: "CB"`, `title`, `task_type`, `expected` and `failure_if` copied from the JSON, `builder_note`,
   `observed_questions`, `started_at`, `skill_package_hash`, `sent_input` (the StepInput as built plus the handle map from
   `contracts.candidate_citation_handles`), `automatic_checks`, `observations`, `counts`, `observed`, `human_judgement: null`, `runs` (one run:
   `status`, `requested_model`, `resolved_model`, `tool_item_types`, `reasoning_effort` (null), `token_usage`, `error`, `validation` (`ok`, `codes`),
   `raw_output`, `parsed`). `summary` lists `selected`, `attempted`, `not_attempted` with reasons and counts of cases, completed, structurally valid,
   all screens true, and a `screen_note` saying screens are heuristics and nothing here is a rate. Output directory: `--out-dir` (default
   `.local/p6-slice3-k5-<date>`, relative to the repo root unless absolute; the orchestrator passes the main checkout's path). `--model`
   required, `--cases` optional filter, `--only-build` builds and validates the selected inputs (all seven unless `--cases` filters), prints their
   ids and creates no adapter and no directory, `--codex-home` optional. Stop the whole run on the first step where
   `models.adapter.is_rate_limited(result)` is true, the error text says quota, rate limit, capacity or overloaded, a tool item appeared,
   `status == "isolation_violation"`, or `resolved_model != requested_model`: write what was collected, print why, exit non-zero. No retry in the
   script, no model fallback. `run_one` refuses any task type other than `claim_assessment` and `claim_decomposition` and any input that fails
   `check_step_input`, before sending.
5. **Model-free tests** in `tests/test_candidate_behavior_cases.py` (no adapter, no network): the case ids in the JSON equal the runner's and
   `task_type` and `fixture` match the builder; the catalogue test pins status `prepared_not_run` and the note sentences; every built input passes
   `check_step_input`, shows handles that resolve back (`candidate_citation_handles`; include element handles and a handle for an unknown id staying
   unknown) and leaves the loaded fixtures unmodified; per-case builder-intent tests (CB01 reuses none of the four words, CB02 mentions no queue word,
   CB06 has three abstract passages, CB07 equals the fixture apart from ids, model and `skill_package_hash`); every case has a hand-written "good" output that passes
   `validate_model_output` with all its applicable screens true and a hand-written "bad" output (the trap it is named for) that the screens reject
   while it stays schema-valid where possible (CB07's bad output: a literature-framed rationale; its `nearest_simple_explanation` and id trap is
   rejected by the validator, test that the validator rejects them and the runner records `structurally_valid` false); counter-examples: CB02 plain
   "does not mention queues" sentence true and "this is a research gap" false, CB05 a plain contradiction note false and a condition-naming one true,
   CB01 `null` alignment screen when no SUPPORT cell, a SUPPORT cell with `different_conditions` false; no-evidence outputs (counts, vacuity);
   `summarize` counts a small fake result list; the `--only-build` path prints seven ids and never constructs `CodexAdapter` or loads settings
   (monkeypatch both to raise); stop-rule helper cases (rate limit, quota, capacity, model mismatch, tool item, isolation_violation without tool items);
   integration tests of `main` with a stub adapter as in `test_lineage_behavior_cases.py` (read it and carry over each such test): a handle-resolution or validation exception inside `run_one` keeps the raw reply in the results (`processing_error` field present in the run record); a stop rule or an exception on the second call writes a checkpoint with the first case's result and the last attempted case, makes no further call, and still closes the adapter; an existing `results.json` is never overwritten; `run_one` production message and validation order for both task types (stub adapter with `enforces_schema` true and false, wire output in
   handles, `reasoning_effort=None` as keyword); an invalid response retained without repair; `run_one` refuses other tasks and invalid inputs without
   sending; a test that no fixture text contains a DOI, URL or e-mail. Build outputs with helper functions in the test file. Nothing goes to `tests/fakes.py`.

## Files allowed

Create: `scripts/model_behavior/run_candidate_cases.py`, `tests/test_candidate_behavior_cases.py`. Edit: `tests/model_behavior/candidate_cases.json`
(per-case added fields and one appended note sentence), `tests/test_candidate_contract.py` (only `test_behavior_cases_are_defined_and_never_run`: allow added per-case fields, drop the no-runner assertion). Nothing else.

## Checks to run

- `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_candidate_behavior_cases.py -q`, then the full
  `PYTHONPATH=backend:. uv run pytest` (one known failure: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`;
  a test that fails only under load: rerun it alone).
- `PYTHONPATH=backend uv run --no-sync python scripts/model_behavior/run_candidate_cases.py --model gpt-5.6-luna --only-build` prints
  CB01 to CB07 and exits 0 without contacting a model.
- `git diff --check`; no change to `skill_package_hash` (no `methods/` edit).

## Report back

Files changed; the call-shape differences you found (if any); what each screen can and cannot catch; which `fixture_change` sentences you built as
written and which you had to read loosely; test counts.
