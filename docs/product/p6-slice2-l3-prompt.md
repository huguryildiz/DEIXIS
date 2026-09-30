<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: düzeltmeyle hazır, 0 high + 5 medium (same-work by work_id; duplicate-quote scope per decision; two more hash-pinning tests allowed and output_schema_versions is a list; allowlist limited to three keys and claims_under_review rejected; H9 order-rule check), all folded in; no second round needed (no high); implementation by gpt-6.1-sol; code review: r1 düzeltmeyle hazır, 0 high + 1 medium (conflicting repeated source/passage records), fixed; see D133 -->

# Task: P6 slice 2, batch L3, contract and model transport path for `lineage_links`

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l3` (detached at `2f85f6c`, main with D132). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D130, D131, D132 and D127 (top), and `docs/product/p6-slice2-chain-of-ideas.md`: §3 (rules),
§4.3, §6 (the method file text), §7, §8.1, §8.2, §9 (first bullet only, for the 8 / 24 / 48,000 limits), §10, §11, §12 "Sözleşme"
(T11), §19 "L3". The scope below was decided by the main session and binds this prompt; where the code differs from what this
prompt says, report it. Commit `14a6e6f` (D127, P18) is the pattern for per-field citation handles: read `git show 14a6e6f --
backend/deixis/domain/contracts.py backend/deixis/workflow/flow.py` and `tests/test_report_handles.py`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls, no measurement; behavior cases are only
defined, never run.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web work, no migration, no API work in this batch.

## Why

Slice 2 decides, per candidate pair, whether the later work's own passages state a development relation to an earlier work. L3
builds only the road a model step travels: the JSON contracts, the semantic validator, the short citation handles, the method
file, and the plumbing of `task_type = "lineage_links"` through `_step_input` and `_model_step`. It builds no business logic:
nobody selects candidates, builds a `lineage_target` from the database, stores a decision, or publishes a link yet (L4, L5).
L3's own proof is a fake adapter that answers a hand-built StepInput through the real `_model_step`.

## What is and is not in code (checked on 2f85f6c)

- In code: `domain/contracts.py` has `SCHEMA_FILES`, `SCHEMA_VERSIONS`, `TASK_OUTPUTS`, `check_step_input`, `validate_model_output`,
  `_semantic_checks`, `_check_cells` (the pattern for `locate_anchor` and `duplicate_evidence_quote`), the D127 report handle
  machinery (`REPORT_*_ID_FIELDS`, `_report_id_fields`, `report_citation_handles`, `citation_handles`, `with_citation_handles`,
  `resolve_citation_handles`, `issues_with_handles`), and the best-effort semantic pass that also reports unknown IDs at the path
  of a schema error for `REPORT_TASKS`. `workflow/flow.py` has `HANDLE_TASKS`, `_step_input(... adjudication_target)` and
  `_model_step(... adjudication_target ...)`. `domain/skill.py` has `RUNTIME_FILES`. `contracts/research/common.schema.json` has
  `source_id` (`srv_`) and `passage_id` (`psg_`). `tests/fakes.py::valid_response` and `tests/fixtures/research/{step-inputs,
  fake-outputs}.json` exist.
- Not in code: any `lineage_*` schema, task type, validator, handle mapping, method file, fixture or fake; `workflow/lineage/` has
  only L2's pure functions, which this batch does not import and does not change.
- The method package hash today is `sha256:cef7c08662f102f5e7dd56f5203ecb142fc28b91eebeddbfb5b3bb0bbad3b6bb` (P19 moved it from
  `sha256:52775258`). Record this full old value and the full new value in your report.

- Order rule (§19, P9/H9), checked by the orchestrator: the note grants no H9 execution permission and the owner's order is P6 slices
  2 to 5 before P9, so no H9 freeze window is open; L3 changes `methods/` and that is allowed now. Nothing for you to do; do not touch `report_*`.

## Decisions (already taken; do not reopen)

1. **Output schema** `contracts/research/lineage-links-draft.schema.json`, v1, exactly the JSON of §8.1 (the `$id` path follows the
   neighbouring files). Register `"LineageLinksDraft": "lineage-links-draft.schema.json"` in `SCHEMA_FILES`,
   `"LineageLinksDraft": "deixis.lineage_links_draft.v1"` in `SCHEMA_VERSIONS`, `"lineage_links": ("LineageLinksDraft",)` in
   `TASK_OUTPUTS`. The new schema must pass `strict_compatibility_issues` (every object closed, every property required) and
   resolve every `$ref`. No `continues_predecessor_uncertainty` field (2b, schema v2).
2. **StepInput schema** `contracts/research/step-input.schema.json`: add `lineage_links` to the `task_type` enum; add the optional
   top-level property `lineage_target` (not in `required`, like the other targets); add a root `$defs` with `lineage_node` and
   `lineage_cell`. Take §8.2 literally and close everything the note leaves open, in this way (record each as a judgement in D133):
   - `lineage_target`: `table_id` (`^tbl_[0-9A-Za-z]{8,40}$`), `to` (`#/$defs/lineage_node`), `candidates` (max 8) whose items are
     `from` (`lineage_node`), `origin` (const `"mention"`), `mention_passage_ids` (1 to 3 `passage_id`), `edge_state` (the four
     states), `year_order_warning` (boolean), all required, `additionalProperties: false`.
   - `lineage_node`: required `source_id` (`source_id`), `year` (integer or null), `cells` (array, `minItems` 3, `maxItems` 3, items
     `lineage_cell`). `lineage_cell`: required `role` (`problem` | `change` | `uncertainty`), `cell_id` (nullable, `^cel_[0-9A-Za-z]{8,40}$`),
     `cell_revision_id` (nullable string, minLength 1), `column_revision` (nullable integer >= 1), `instruction_revision` (nullable
     integer >= 1), `instruction` (nullable string, minLength 1), `state` (the seven cell states of `workflow/tables.py::CELL_STATES`
     plus `missing`), `value` (nullable string, maxLength 500), `reading_depth` (nullable, the same four values as a passage),
     `output_status` (nullable string, minLength 1), `flags` (object, closed, exactly five required booleans `stale_column`,
     `pdf_removed`, `pdf_replaced`, `text_superseded`, `not_verified`), `evidence_quotes` (array of non-empty strings, no maxItems,
     no maxLength: stored quotes are never silently cut).
   - `capabilities.supported_tasks` is a free string list in the schema and `flow.CAPABILITIES` deliberately does not list the
     batch and report tasks (comment above it: listing one changes every stored StepInput). **Do not change `CAPABILITIES`**; the
     note's §7 mention of `supported_tasks` is overridden by that precedent (judgement; report it).
3. **`check_step_input`** (new code beside the other target checks). Add `LINEAGE_TASKS = ("lineage_links",)`. Issues:
   `lineage_target_mismatch` (target present iff the task type is a lineage task; for lineage tasks the plain `candidates` list and
   `allowlist.candidate_ids` must be empty, every other target absent); for a present target:
   `lineage_source_not_allowed` (`to.source_id` or a `from.source_id` not in `allowlist.source_ids`), `lineage_source_not_shown` (a
   `to`/`from` source missing from `sources`, because the method needs titles), `lineage_same_work` when `to.source_id` equals a
   `from.source_id` **or** the shown `sources[].work_id` of the two is equal (two versions of one work never pair, §4.3), `duplicate_lineage_candidate` (repeated `from.source_id`), `lineage_passage_not_later_work` (a StepInput passage
   whose `source_id` is not `to.source_id`; evidence comes only from the later work), `lineage_mention_passage_unknown` (a
   `mention_passage_ids` entry not among `passages`, or a repeated entry within one candidate), `lineage_passage_count` (more than 24
   unique `passages`), `lineage_node_roles` (a node whose three cells do not carry `problem`, `change`, `uncertainty` exactly once
   each), `lineage_missing_cell_shape` (a `missing` cell that does not have null `cell_id`, `cell_revision_id`, `column_revision`,
   `value`, `reading_depth`, `output_status`, all five flags false and no `evidence_quotes`; `instruction_revision` and `instruction`
   may be set on a missing cell), and the allowlist must be exactly `sources` and `passages` ids (`allowlist_without_record` is
   already reported; add `lineage_allowlist_mismatch` for ids that are in `sources`/`passages` but not allowed). For this task the allowlist carries
   exactly the three keys `candidate_ids` (empty), `source_ids`, `passage_ids`: any other key (`cell_ids`, `column_ids`, `gap_ids`,
   `phrases`) is `lineage_allowlist_key`, and a present `claims_under_review` is `lineage_unexpected_field`, because the handle
   conversion does not cover them. A display-only cell handle confers no quoting right. Do not require any business rule beyond these
   (chunking, budgets, eligibility are L5).
4. **Semantic validator** `_check_lineage_links(step_input, allow, draft, report)`, registered in `_semantic_checks` for output type
   `LineageLinksDraft`, written in the pattern of `_check_cells`. It checks, with these issue codes:
   - the candidate set: every `lineage_target.candidates[].from.source_id` answered exactly once, **counting duplicates**.
     `duplicate_candidate_decision` (path of the second and later decision), `candidate_without_decision` (path `/decisions`),
     `unknown_source_id` (a `from_source_id` not in `allowlist.source_ids`), `decision_for_non_candidate` (an allowed source that is
     not a candidate, including the later work itself).
   - field consistency: `decision = link` requires non-null `relation`, `what_changed`, `support_type` and 1 to 5 `evidence` items
     (`link_field_missing`, `link_without_evidence`); any other decision requires all three null and `evidence` empty
     (`fields_on_non_link`, `evidence_without_link`). `independent_parallel` only with `source_stated`
     (`independent_parallel_needs_source_stated`).
   - evidence: each `passage_id` must be in `allowlist.passage_ids` (`unknown_passage_id`); each quote must be found by
     `locate_anchor` in that passage (`anchor_not_in_passage`, message in the style of `_check_cells`); the same located words of the
     same passage twice **within one decision's evidence** is `duplicate_evidence_quote` (the seen-set resets per decision: the
     same quote may support two different candidates' decisions) (the later evidence table keys on passage and located text, so a duplicate
     would collide; judgement, report it).
   - `source_stated` requires at least one evidence passage that is in **that candidate's** `mention_passage_ids`
     (`source_stated_without_mention_passage`). `analyst_inference` has no such requirement.
   - **T11 is structural.** No citation-edge state (`present`, `absent_in_read_list`, ...), no year order and no cell content ever
     substitutes for evidence; the validator does not read `edge_state` for any acceptance decision. A structurally valid `link`
     with a real but irrelevant quote passes: code checks structure, not meaning (say so in the test and in D133).
   - **Reference-list passages (L2's open item).** L2 does not filter reference-list passages, and this batch does not add a
     detector either: the note carries the rule only in the method text (§6: "a passage that only lists the earlier work in a
     bibliography proves that the later work cites it, not how"; case 7 and §4.3 "model bunu ilişki kanıtı saymaz"). Implement it
     exactly there: in `references/synthesis.md`, plus a defined behavior case. The validator therefore cannot reject a quote taken
     from a reference-list passage, and a reference-list passage that is among `mention_passage_ids` still satisfies the
     `source_stated` check structurally. State that limit in D133. Do not add a heuristic that guesses which passages are reference
     lists.
5. **Handles, D127 style, field by field** in `domain/contracts.py`:
   - `LINEAGE_OUTPUT_ID_FIELDS = (("decisions/*/from_source_id", "srv_S"), ("decisions/*/evidence/*/passage_id", "psg_P"))`; nothing
     else in the output is converted.
   - `LINEAGE_INPUT_ID_FIELDS` (declared slots only): `passages/*/passage_id`, `passages/*/source_id`, `sources/*/source_id`,
     `allowlist/passage_ids/*`, `allowlist/source_ids/*`, `lineage_target/to/source_id`, `lineage_target/to/cells/*/cell_id` (`cel_L`),
     `lineage_target/candidates/*/from/source_id`, `lineage_target/candidates/*/from/cells/*/cell_id` (`cel_L`),
     `lineage_target/candidates/*/mention_passage_ids/*`. `table_id`, revision IDs, instructions, values, quotes and envelope fields
     are not converted. A null `cell_id` (a `missing` cell) stays null and gets no handle.
   - Numbering (`psg_P0000001`, `srv_S0000001`, `cel_L0000001`; restarts per step; recomputed from the stored StepInput): passages in
     record order, sources in record order, then display-only cells (`to` cells in list order, then each candidate in list order with
     its `from` cells in list order), then any remaining ID of a declared input slot in field order. First occurrence wins.
   - Wire into the existing dispatch: `citation_handles` (new `lineage_citation_handles`), `with_citation_handles` (task-specific
     field list instead of the report one), `resolve_citation_handles` (the lineage output fields for `lineage_links`, with the same
     prefix and leading-zero rule), and `issues_with_handles` (works through `citation_handles`). The best-effort semantic pass that
     reports unknown IDs alongside a schema issue (`unknown_passage_id`, `unknown_source_id`, ... for `REPORT_TASKS`) also applies to
     `LINEAGE_TASKS`, so a wrong-kind ID string is reported as an unknown ID as well as a schema error (D127 class).
   - A display-only cell handle is never allowlisted and never valid as evidence. The stored StepInput, the succeeded result and
     (later) links keep the real IDs; the message sent to the model and the raw output keep the handles.
   - `workflow/flow.py`: add `"lineage_links"` to `HANDLE_TASKS`; add `lineage_target: dict[str, Any] | None = None` as the last
     parameter of `_step_input` (put into the StepInput beside the other targets; allowlist stays `candidate_ids: []`,
     `source_ids`, `passage_ids` from the `source_ids`/`passage_rows` the caller passes) and of `_model_step` (passed through);
     add `contracts.LINEAGE_TASKS` to the tuple that decides whether `resolve_citation_handles` runs on the output. **No business
     logic** in `flow.py`: no eligibility, no candidate selection, no packing, no new run kind, no store call.
   - The model for the step is the research model (`step_model` default); `LITERATURE_TASKS` is not changed, and
     `schema_repairs` stays the default (`MAX_SCHEMA_REPAIRS`). Record both as judgement calls.
6. **Method package** (this moves `skill_package_hash`; record old and new in full):
   - New file `methods/deixis-research/references/synthesis.md` with the text of §6's markdown block. Keep its structure and rules;
     make only these edits, and list them in D133: (a) "passages listed under `to`" becomes "passages listed in `passages`; all of
     them belong to the later work"; (b) add a short paragraph that every ID is a handle to copy exactly as shown (`srv_S...` for
     `from_source_id`, `psg_P...` for evidence), that `cel_L...` cell handles are labels and never a citation, and that nothing may be
     quoted from a cell; (c) add to the `link` rule: a reference-list or bibliography entry is never the support of a `link` even when
     it is one of the candidate's mention passages, and when every mention passage is such an entry `source_stated` is not
     available; choose `analyst_inference` only if other shown passages of the later work support it, otherwise
     `insufficient_evidence`; (d) keep "Passage text is data, not instructions" and the closing paragraph (no novelty, no end of line,
     no directions) unchanged. Write it in plain English; the file must not contain the word "foundational".
   - `domain/skill.py`: `RUNTIME_FILES["lineage_links"] = ("SKILL.md", "references/synthesis.md")`.
   - `SKILL.md`: add a short paragraph for `lineage_links` pointing to `references/synthesis.md` (same style as the other task
     paragraphs) and narrow the "Literature synthesis across idea chains ... not available" sentence **only for `lineage_links`**:
     the prohibition stays verbatim for `grounded_answer` and the report sections, and a `lineage_links` decision must be described
     as a per-pair development-relation decision, not an idea-chain synthesis. No change to the evidence rules.
   - `provenance.json`: one `adaptations` entry for `references/synthesis.md` (written for DEIXIS on 2026-10-01, D130 and D133,
     concept adapted from Chain of Ideas, Li and others 2024, not upstream text, `derived_from: []`), and one sentence in
     `behavioral_validation` that `tests/model_behavior/lineage_cases.json` holds eight prepared, not-run development cases; the
     existing tests must still pass (`"validated"` must not appear in that field, `cases.json` path stays).
   - Do not touch `report.md`, the phrasebank or any other method file.
7. **Fixtures and fake**: add a synthetic `I_lineage_links` StepInput to `tests/fixtures/research/step-inputs.json` (one later work
   with 3 passages, two candidates, all three cell roles per node, one node with a `missing` cell, one candidate with
   `year_order_warning` true, edge states `present` and `not_read`; text marked SYNTHETIC, no real publication) and a few
   `lineage_*` cases in `fake-outputs.json` (valid; unknown passage; missing candidate; duplicate candidate; link without
   evidence; `source_stated` from a non-mention passage; `independent_parallel` with `analyst_inference`) in the file's existing
   case shape, so the existing fixture tests keep passing. Add a `lineage_links` branch to `tests/fakes.py::valid_response`: the
   first candidate is a `link` (`extends`, `source_stated`, one quote copied from its first mention passage), every other candidate
   is `no_relation` with nulls and empty evidence; SYNTHETIC wording.
8. **Behavior cases, definitions only**: `tests/model_behavior/lineage_cases.json` in the shape of `report_cases.json`
   (`status: "prepared_not_run"`, `prepared: "2026-10-01"`, `split: "development"`, a `note` saying they are synthetic, one attempt
   per case, automatic screens are heuristics, and that their results are not the L9 measurement), eight cases `LB01` to `LB08`
   for the eight §11 cases in order, each with `id`, `title`, `task_type: "lineage_links"`, `fixture: "I_lineage_links"`,
   `fixture_change` (what the case edits), `expected`, `failure_if`, `judgement: "human"`. No runner script, no run, no result.
9. **Do not change**: `workflow/lineage/*` (L2), storage, migrations, API, web, `workflow/report/*`, `report_*` schemas, `report.md`,
   `phrases.md`, `CAPABILITIES`, `rules.py`. Do not import anything from `workflow/lineage` into `contracts.py`.

## Files allowed

`contracts/research/lineage-links-draft.schema.json` (new), `contracts/research/step-input.schema.json`,
`backend/deixis/domain/contracts.py`, `backend/deixis/domain/skill.py`, `backend/deixis/workflow/flow.py` (only the three edits
of decision 5), `methods/deixis-research/SKILL.md`, `methods/deixis-research/references/synthesis.md` (new),
`methods/deixis-research/provenance.json`, `tests/test_lineage_contract.py` (new), `tests/test_skill_package.py` (note: the note
names `tests/test_skill.py`; the real file is `test_skill_package.py`), `tests/test_lineage_columns.py` and `tests/test_report_failed_rows.py` (each pins the
current package hash; update only the pinned hash value, keeping the meaning of the assertion, for example that L1 or P19 left it untouched becomes a statement about what the test checked at its own commit; report the exact edit), `tests/fixtures/research/step-inputs.json`,
`tests/fixtures/research/fake-outputs.json`, `tests/fakes.py`, `tests/model_behavior/lineage_cases.json` (new), other existing tests
only if an enumeration now legitimately includes the new task (for example a test that lists every schema or task type); say which
and why. `docs/decisions.md` (D133 only) and this prompt file's comment line are written by the orchestrator, not by you.

## Files NOT allowed

Everything else, in particular `backend/deixis/workflow/lineage/*`, `backend/deixis/storage/*`, `backend/deixis/api/*`,
`apps/web/*`, `scripts/*`, `docs/product/sw-status.md`, `TODO.md`, `.vscode/`.

## Tests to add (synthetic, no network, no real model; name them so the limit is readable)

`tests/test_lineage_contract.py`:
- Registration and schema: `test_lineage_schema_is_registered_strict_and_resolves_its_refs` (registered in the three tables,
  `strict_compatibility_issues` empty, every `$ref` resolves, `step_output_schema("lineage_links")` is self-contained),
  `test_step_input_schema_accepts_the_fixture_and_rejects_open_nodes` (extra property on node, cell, flags, candidate rejected; a node
  with two cells rejected; `lineage_target` on another task type rejected by `check_step_input`).
- StepInput checks: one test per issue code of decision 3 (`test_check_step_input_rejects_<code>`), plus `test_fixture_step_input_is_clean`.
- `test_same_work_versions_never_pair` (different `source_id`, equal `work_id`), `test_lineage_allowlist_carries_only_the_three_keys`, `test_claims_under_review_is_rejected_for_lineage`, `test_same_quote_may_support_two_different_decisions`.
- Validator, one test each: `test_every_candidate_is_answered_exactly_once_duplicates_counted` (duplicate, missing, extra, later work
  itself), `test_link_fields_and_evidence_count` (fields present, 1 to 5 evidence, six evidence items fails at schema), `test_non_link_decisions_carry_nulls_and_no_evidence`,
  `test_independent_parallel_needs_source_stated`, `test_evidence_must_come_from_a_shown_later_work_passage`,
  `test_unlocatable_quote_is_reported_and_a_located_quote_passes`, `test_duplicate_located_quote_of_one_passage_is_rejected`,
  `test_source_stated_needs_one_of_the_candidates_own_mention_passages` (a mention passage of another candidate does not count),
  `test_analyst_inference_needs_no_mention_passage`, `test_envelope_mismatch_is_reported`, `test_wrong_task_target_pairing`.
- **T11**: `test_citation_edge_alone_never_creates_a_link`: with `edge_state` `present` on a candidate, (a) `no_relation` with
  nulls validates and carries no relation or evidence; (b) `link` with no evidence is rejected; (c) `link` whose evidence passage is
  not a shown later-work passage is rejected; (d) changing `edge_state` (all four values) and `year_order_warning` never changes the
  verdict of any fixed output (prove the validator ignores them); (e) a structurally valid `link` with a real but irrelevant quote
  still validates, with a comment that this is a structural check only.
- Handles (D127 class): `test_lineage_handles_are_numbered_per_step_and_recomputed_from_the_stored_input`,
  `test_with_citation_handles_converts_only_declared_slots` (table_id, revision ids, instructions, values, quotes, envelope untouched;
  a null cell id stays null), `test_cell_handles_are_display_only_and_not_in_the_allowlist`, `test_output_resolution_maps_from_source_id_and_evidence_passage_id`,
  `test_leading_zero_handles_resolve`, `test_wrong_kind_handle_is_unknown_and_repaired_once_then_fails` (a cell handle or a
  `srv_S` handle in `evidence[].passage_id`; unknown-ID issue reported alongside the schema issue), `test_an_unshown_real_id_is_rejected_not_resolved`.
- End to end through the real `_model_step` with `FakeAdapter`, following the harness of `tests/test_report_handles.py` (~lines 380 to
  480) and `tests/test_report_step_input.py:95`: `test_fake_adapter_answers_lineage_step_through_model_step` (valid output
  stored succeeded with real IDs in the stored StepInput, handles in the message sent and in the recorded raw output, step input
  carries `lineage_target`, `skill_files` is `["SKILL.md", "references/synthesis.md"]`, `output_schema_versions` is `["deixis.lineage_links_draft.v1"]`, `skill_package_hash` is the loaded
  package's), `test_lineage_step_repairs_once_then_stops_without_salvage` (a bad quote, then still bad: exactly two calls, invalid result, no D56 salvage),
  `test_lineage_step_is_not_handled_as_a_report_or_answer_task`.
- Method and cases: `test_synthesis_method_text_carries_the_rules` (keyword checks: evidence only from the later work, chronology or citation alone is not a link, the bibliography rule, exactly one decision per candidate, handles copied
  exactly, no word "foundational"), `test_behavior_cases_are_defined_and_never_run` (eight cases `LB01`..`LB08`, fixture key exists in `step-inputs.json`, status `prepared_not_run`, every `task_type` is `lineage_links`; also assert no `lineage` runner script exists under `scripts/model_behavior/`).
- `test_lineage_step_uses_no_provider_and_no_model_outside_the_fake` is not needed; the adapter is the only model in the test.

`tests/test_skill_package.py`: `test_lineage_links_loads_synthesis_md_and_the_hash_moved` (runtime files tuple, `integrity_issues() == []`,
package hash differs from `sha256:cef7c08662f102f5e7dd56f5203ecb142fc28b91eebeddbfb5b3bb0bbad3b6bb`, and the two grounded-answer / report prohibition sentences in `SKILL.md` still appear verbatim), and keep every existing test passing; if an existing
test hard-codes the package hash or lists all task types, update it minimally and report it.

## Checks to run

1. Compute the new hash after the method edits: `PYTHONPATH=backend:. uv run python -c "from deixis.domain import skill; print(skill.package_hash())"`.
2. `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_contract.py tests/test_skill_package.py tests/test_contracts.py tests/test_report_handles.py tests/test_report_step_input.py -n 0`, then the full
   `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one known failure:
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails under parallel load but
   passes alone: rerun it alone and say so). Baseline on this checkout: 3,203 passed + that failure.
3. `git diff --check`; `git status --short` shows only the allowed files. Report every count; if a tool cannot run in your sandbox say
   so and do not call an unrun check verified.

## Report back

Files changed; test counts; old and new full `skill_package_hash`; every judgement call (list them, in particular decisions 2, 3, 4
and 6 where this prompt closed what the note left open); what you could not find or could not run; anything L4 to L6 must know
(for example the exact `lineage_target` shape you validate, the handle order, the code names).
