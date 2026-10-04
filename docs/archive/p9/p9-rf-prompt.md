<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 7 medium, all folded in; decisions 1-3 agreed with changes (transport versioning exception, exact claim-key marker, kept insufficient_evidence check); r2: düzeltmeyle hazır, 2 medium + 2 low, folded in; r3: düzeltmeyle hazır, 1 medium + 1 low, folded in; r4: hazır. -->

# Task: P9 batch RF (report path fix): code stamps the package hash, a failing cell anchor is repaired by a patch the model chooses and code applies, and no claim leaves a repaired section without a record

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-p9rf`, detached at `581e156` (origin/main with the H9 result, D171 result section).
Read `AGENTS.md`, `CLAUDE.md`, in `docs/decisions.md` D12, D86, D124, D126, D127, D128, D129 and the D171 result section, and
`docs/product/p9r-report-results.md` (the H9 result). Read `backend/deixis/workflow/flow.py::_model_step` (`:5281-5548`) in full,
`backend/deixis/domain/contracts.py` (`:123`, `:221-241`, `:704-750`, `:1581-1649`, `:1789-2100`), `backend/deixis/models/prompt.py`
(`:78-97`), `methods/deixis-research/SKILL.md`, `methods/deixis-research/references/report.md`, `tests/fakes.py`,
`tests/test_report_anchor_repair.py` and `tests/acceptance/fixture_server.py:540-610`. Venv: `.venv` is a symlink to the main checkout's arm64
venv. Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model
call, no provider call, no network. Do not touch `../DEIXIS*` worktrees (in particular `../DEIXIS-h9run` is read-only evidence), `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765 or the live data directory. The decision number is **D198** (one entry).
No migration.

## Why

No real-model report has ever completed: D124 stopped at the table, D126 at section IV on a miscopied passage id (fixed by D127's handles),
D128 at IV on an unlocatable cell quote (D129 then added a targeted repair message), and H9 (D171 result, run `run_YHPhlrH3yeRdPIQwCdoI`,
`codex`/`gpt-5.6-luna` medium) at IV again. The orchestrator read H9's stored inputs and outputs (a copy of
[../DEIXIS-h9run/.local/p9r-h9/data/library.sqlite](../local-runs.md#run-archive-p9-evidence-deixis-h9run)). What they show:

1. **Package hash miscopy, three times in 52 sessions.** The model copied `skill_package_hash`
   (`sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff`) wrong in the same region each time:
   `…3e6c1c6d9ff…` (report_section IV repair, `mss_xhk50S1g0GOlJmHgeH9a`), `…3e6c1d6d9ff…` (abstract_screening
   `mss_h5nfepCU8lHyzXZ1W3qz`; this task has no repair, so the call was lost and its step `failed`) and `…3e6c1d9ff99dcf75ff2b`
   (fulltext_adjudication `mss_IEbEtej7GQuNAUvyNukU`; its repair succeeded at the cost of one call). Three observations are not a rate.
2. **The repair is a blind rewrite.** `prompt.repair_message` (`prompt.py:86-97`) sends the StepInput, the issues and (D129) the anchor pairs,
   but **not the failed output**; each call is a new thread (distinct `external_thread_id`). So the model regenerates the whole section:
   - IV first output (`mss_HG8MzJk21LAPfYmdMxmF`): 18 claims, 18 anchors, 2 `insufficient_evidence` entries, one issue
     (`anchor_not_in_cell_evidence` at `/citation_anchors/8/quote`, claim IV.9, cell `cel_L0000024`). The failing quote keeps the PDF private-use glyph U+E0A8 but runs past the
     stored evidence quote: the stored quote ends at `A =(tb` + U+E0A8 + `k`, the model's continues with ` ) because the actions are
     taken sequentially`.
   - IV repair (`mss_xhk50S1g0GOlJmHgeH9a`): a new section of 19 claims and 21 anchors, 0 `insufficient_evidence` entries (the first output's
     two were lost), the miscopied hash, and **every** anchor carrying both `passage_id` and `cell_id` (21 × `citation_anchor_target_count`).
     The results document says the anchors carried neither; the stored output shows both. The likely bait: D129's pairs label each allowed quote
     with `"passage_id"` (`contracts.py:1609`), and the model copied that passage handle into each anchor next to its cell.
   - V first output (`mss_AmPVJSuzHvTMLEntGcfu`): 8 claims, 7 failing cell anchors, all seven quoting the **Turkish cell value** instead of a
     stored English evidence quote. V repair (`mss_c57ZHZgnqrGFdJNCZhv0`) validated, but rewrote the section into 6 claims: V.7 and V.8 (the two
     passage-anchored comparison claims of the first output) vanished with no `insufficient_evidence` entry (P19 e = 0).
   One anchor failing in 18 turned into 22 issues because the repair could not keep what was already valid.
3. Not fixed here, named for later: first-pass cell anchors that quote the cell value (V's seven) or run past the stored evidence span
   (IV.9). The
   patch below repairs them; preventing them in the first pass needs a cell-anchor-by-evidence-index contract (a report-section schema v3),
   which is out of scope.

## What is and is not in code (checked on 581e156)

Paths under `backend/deixis/` unless stated.

- `domain/contracts.py:123` `ENVELOPE_FIELDS = ("step_input_id", "scope_revision", "skill_package_hash")`; `:742-746` reports
  `envelope_mismatch` for any of them. `:221-241` `step_output_schema(task_type)` is both the schema sent to the model
  (`workflow/flow.py:5420`, stored in `step_inputs.output_schema_json`, appended for non-enforcing adapters at `:5427-5428`) and the
  schema `validate_model_output` validates against (`:717`). Every output contract in `contracts/research/*.schema.json` requires
  `skill_package_hash`. `methods/deixis-research/SKILL.md:25` and five reference files (`abstract-screening.md:30`, `search-query.md:57`,
  `term-suggestions.md:24`, `vocabulary-labels.md:26`, `criterion-proposal.md:50`; `review.md:38` "echo its envelope fields") tell the
  model to echo the hash. `scripts/model_behavior/run_cases.py:80-86` and `anchor_measure.py:115-126` load the runtime method
  instructions, send `step_output_schema` and validate without stamping.
- `workflow/flow.py:5509-5513`: handles are resolved, `normalise_output` renames aliases (D86; changes recorded in
  `validation_json.normalised`), then `validate_model_output`. Model isolation (`:5486-5490`, tool items) and model mismatch
  (`:5503-5508`, `resolved_model`) are checked before any parsing and do not read envelope fields.
- `workflow/flow.py:5431-5444`: on repair, report sections get `report_section_anchor_repair_context(failed_input, output_text,
  repair_issues)` (`contracts.py:1581-1616`; one pair per `anchor_not_in_cell_evidence` issue at `/citation_anchors/N/quote` whose anchor
  names an allowlisted cell), handles substituted for `cell_id` and each allowed quote's `passage_id`, then `prompt.repair_message`
  (`prompt.py:86-97`) with `REPORT_SECTION_ANCHOR_REPAIR_GUIDANCE` (`:78-83`). The repair asks for a whole corrected object under the
  same `report_section` schema. `output_text` at that point is the previous attempt's resolved, normalised draft (a dict when it parsed).
- `contracts.py:1619-1649` `_check_report_section`: exactly one of `passage_id`/`cell_id` per anchor; a cell anchor must be located by
  `locate_anchor` inside one stored evidence quote of that cell.
- `workflow/report/sections.py:162-178`: an `invalid` model-step output stores the section `failed` with `output["issues"]`; the timeline and
  sheet show the **first** issue's code (D129). `tests/acceptance/fixture_server.py:598-599` `[report-bad-anchor]` gives IV a quote absent from
  all stored quotes in both calls; `apps/web/e2e/report.spec.ts:501-545` expects pause `section_failed` with first reason
  `anchor_not_in_cell_evidence`.
- `domain/rules.py:179` `NO_REPAIR_TASKS = ("vocabulary_labels", "term_suggestions", "abstract_screening")`; `MAX_SCHEMA_REPAIRS = 1`.
- `workflow/review/run.py:75` sizes owner-review requests with `step_output_schema("owner_review")`.

## Decisions (agreed in plan review; use these, never ask)

### 1. Code stamps `skill_package_hash`; the model echoes only the short binding fields

Options weighed:

- **A, stamp (chosen).** The model-facing schema has no `skill_package_hash`; code writes the StepInput's value into the output before
  validation. Keeps: model isolation and model mismatch (they never used envelope fields); the `step_input_id` and `scope_revision` echo
  (still required and checked, so an output that answers another call is still caught); the stored record of which package each call used
  (`step_inputs.skill_package_hash` and the stored `developer_instructions`). Loses: the model's copy of the hash. That copy never showed
  that the model read or followed the package; it only showed that it could copy 71 characters, and in H9 it failed to 3 times in 52.
- **B, short echo token.** Show the hash as a short token and map it back, as D12 does for citations. Keeps an echo, but of a constant
  the model copies from the same message, so it proves no more than A; it adds mapping code and a token in every input. Rejected.
- **C, stamp all three fields.** Removes the remaining binding check for no observed failure (`step_input_id` and `scope_revision` were
  copied correctly in all 52 H9 sessions; not a rate). Rejected.

Implementation:

- `contracts.model_output_schema(task_type)`: a deep copy of `step_output_schema(task_type)` with `skill_package_hash` removed from
  `properties` and `required` of each output object (the single-output root, or each wrapper alternative that is an object). It must pass
  `strict_compatibility_issues`. `step_output_schema` and every contract file stay unchanged: the stored result keeps its shape and
  `schema_version`. **Versioning exception (agreed with gpt-6.1-sol medium):** the model-facing wire schema changes (one required field
  fewer) while the stored contract and its `schema_version` do not. No new version string is introduced; the transport actually used is
  recorded per attempt in `step_inputs.output_schema_json`, so an attempt sent before D198 and one sent after are told apart by their
  stored schema. D198 states this exception explicitly.
- `contracts.stamp_package_hash(task_type, step_input, draft) -> (draft, changes)`: for a dict draft, set `skill_package_hash` on each output
  object present (root, or each non-null wrapper object), from `step_input["skill_package_hash"]`. A value the model supplied anyway (a
  non-enforcing adapter, a test fake) is replaced. Each stamp adds one change `{"path": <JSON pointer>, "stamped": "skill_package_hash",
  "model_value": <the supplied value, or null when absent>}`. A non-dict or unparsable draft is returned unchanged with no changes.
- `_model_step` sends `model_output_schema` (to the adapter, to `schema_appendix` and to `insert_step_input`, so the stored schema is what was
  sent) and calls `stamp_package_hash` right after `normalise_output`, appending its changes to the same `normalised` list. Every task that
  goes through `_model_step` gets this, including the no-repair tasks, so an H9-style abstract-screening miscopy no longer loses the call.
  **Exception: the patch attempt of decision 2 is not stamped.** Its answer is validated against the patch schema first (which has no
  hash); only the merged section draft is stamped (decision 2, application step 5).
- `validate_model_output` is unchanged: it still checks all three envelope fields. Callers that do not stamp (`scripts/model_behavior/*`)
  still send `step_output_schema`, which requires the hash; the method wording below tells the model to copy the hash whenever its output
  schema has that field, so those callers keep asking for an echo. Whether their models echo it as reliably as before is not tested (a
  D198 limit; the scripts are not on the product path). Do not edit `scripts/`
  or `workflow/review/run.py` (its size estimate stays computed on the larger canonical schema, which over-counts by the hash property:
  conservative; name it in D198).
- Method package: `SKILL.md:25` becomes "Echo `step_input_id` and `scope_revision` exactly as given. If your output schema has a
  `skill_package_hash` field, copy it exactly too; otherwise the application fills it in. The application rejects mismatches." The five
  reference lines drop `skill_package_hash` from their echo list and point to that rule; `review.md:38` says the same. Add dated D198 provenance entries in `provenance.json` as earlier batches did.

### 2. A failing cell anchor is repaired by a patch: the model chooses, code applies, code never invents

**When.** The repair of a `report_section` step takes the patch path when every issue of the failed attempt is `anchor_not_in_cell_evidence`
at `/citation_anchors/N/quote` and `report_section_anchor_repair_context` returns exactly one pair per issue (distinct `anchor_index`
values, each equal to its issue's N). Otherwise the full repair (decision 3) runs. Either way it is the step's one schema repair; repair
counting, budget checks, the limiter and the single-repair limit do not change.

**Contract.** New file `contracts/research/report-section-anchor-repair.schema.json`, title `ReportSectionAnchorRepair`, `schema_version`
const `deixis.report_section_anchor_repair.v1`, closed and strict-compatible, with `$ref`s into `common.schema.json` like the other
contracts. Register it in `SCHEMA_FILES`/`SCHEMA_VERSIONS` (it is **not** a task output and not in `TASK_OUTPUTS`). Two schemas come from it:
the canonical one, validated with `canonical_validator` (registry-resolved refs), and a self-contained adapter schema built by the same
inlining as `step_output_schema` (`contracts.py:205-241`; factor out one helper rather than copying it), which must pass
`strict_compatibility_issues`; that adapter schema is what is sent and stored for the patch attempt. Fields, all required:

- `schema_version`, `step_input_id`, `scope_revision` (echoed and checked as in decision 1; no `skill_package_hash`).
- `anchors`: array (`minItems` 1, `maxItems` 300), one item per failing anchor: `{"anchor_index": integer >= 0, "quote_number": integer >= 1 or null}`. A number picks
  that pair's allowed quote (1-based, in the order shown); `null` removes this anchor.
- `claims`: array (`maxItems` 40), at most one item per claim: `{"claim_key": pattern of claim keys, "text": string 1..2000 with at least
  one non-whitespace character or null, "removed": boolean, "context": string 1..180 with a non-whitespace character or null, "reason":
  string within the `short_text` bound with a non-whitespace character or null}` (a `pattern` such as `\S` expresses non-whitespace and
  stays strict-compatible). `text` rewrites the claim; `removed: true` removes
  the claim and needs `context` and `reason` and `text: null`; `removed: false` needs `context` and `reason` null.

**Message.** The step's StepInput (shown with handles) as now, then the failed attempt's issues, then the pairs, then a new fixed
`REPORT_SECTION_ANCHOR_PATCH_GUIDANCE` in `prompt.py`. In the pairs each allowed quote is `{"quote_number": k, "quote": text}`: no
`passage_id` key (the H9 bait) and no handle other than the pair's `cell_id`. Each pair's `claims` entries also list that claim's
current anchors: `{"anchor_index", "target": "cell" or "passage", "failing": true/false}` (handles for the target ids are not needed and
not shown), so the model can see whether dropping a failing anchor leaves the claim any support. The guidance says, in plain English: return only the patch;
for each failing anchor pick the number of a stored quote of that same cell that states what the claim says, or `null`; a quote that is
found does not prove support, so rewrite the claim (`text`) to say no more than the chosen quotes state, or drop the anchor; a claim left with
no anchor must be removed with `removed: true` and a `context` and `reason` that say why, so the removal stays visible; do not write quotes,
identifiers or claims that are not asked for. The output schema sent for this call (and stored for this attempt) is the patch schema; for a
non-enforcing adapter `schema_appendix` gets the patch schema. Developer instructions stay the `report_section` ones.

**Validation of the patch (code, fail-closed; every rule an issue with its own code):** schema; envelope (`step_input_id`,
`scope_revision`); `anchors` covers each pair's `anchor_index` exactly once and nothing else (`anchor_patch_index`); each `quote_number` is
within its pair's allowed quotes (`anchor_patch_quote_number`); each `claims[].claim_key` is a claim of the failed draft that owns at least one
failing anchor, at most once (`anchor_patch_claim`); `removed`/`text`/`context`/`reason` consistency (`anchor_patch_removal`); a claim all of
whose anchors would be gone after the patch must be `removed: true` (`anchor_patch_claim_unsupported`); `context` after the prefix below stays
within the contract's 200 characters.

**Application (code, deterministic, on a deep copy of the failed draft, which is `output_text` of the previous attempt):**
1. For each anchor item with a number: set that anchor's `quote` to the chosen stored evidence quote **verbatim** (the same string
   `_check_report_section` locates against). `claim_key`, `cell_id`, `passage_id` of the anchor are not touched.
2. For each anchor item with `null`: remove that anchor; then, if no remaining anchor of that claim names that cell, remove the cell from the
   claim's `cell_ids`.
3. For each claim item with `text`: replace the claim's text.
4. For each claim item with `removed: true`: remove the claim and every anchor whose `claim_key` is that claim's, and append
   `{"context": f"{claim_key}: {context}", "reason": reason}` to `insufficient_evidence`. The `claim_key: ` prefix is the only text code writes
   into the section; D198 says so.
5. Stamp the envelope of the merged draft from the repair attempt's StepInput (`step_input_id`, `scope_revision`, `skill_package_hash`),
   because the patch has no section envelope and the merged draft answers this attempt.
Then run `validate_model_output(payload, merged)` exactly as for any output. Code never chooses a quote, never adds an anchor, never adds a
citation, never removes a claim the patch did not remove, and never edits anything outside what the patch names.

**Records.** The model session keeps the patch as `raw_output` (as received). Its `validation_json` is the merged draft's validation plus
`"anchor_patch": {"base_step_input_id": <failed attempt's input id>, "changes": [...]}`, one change per applied item (anchor index and old
and new quote, or removal; claim key and old and new text, or removal). If the patch itself is invalid, `validation_json.issues` are the
patch issues and no merged draft exists. On success the step output is the usual one (`result` = merged draft, `step_input_id` = repair
attempt) plus `"anchor_patch"` with the same object. On failure the step fails as today (`invalid_model_output`) and the returned
`issues` are the **failed first attempt's anchor issues first**, then the patch or merged-draft issues, so the section's shown reason stays
the anchor reason (D129 labels, no UI change).

### 3. The full repair of a report section sees what it is repairing and cannot drop a claim silently

For `report_section` only, when the patch path does not apply:
- `prompt.repair_message` adds, after the issues, the failed attempt's raw output as received (handle form) under a fixed heading, with a fixed
  line: keep every claim's `claim_key`; change only what the issues require; a claim you remove must be named by its `claim_key` in an
  `insufficient_evidence` entry. When anchor pairs are present in this path, their allowed quotes also drop the `passage_id` key (same shape as
  decision 2). Other tasks' repair messages stay byte-for-byte as they are.
- The keep-keys line also says: a removed claim needs an `insufficient_evidence` entry whose `context` starts with exactly
  `<claim_key>: ` followed by the explanation (the same marker the patch path writes), and every `insufficient_evidence` entry of the
  failed output must be kept unchanged.
- After validating the repaired draft, code adds one `repair_dropped_claim` issue (path `/claims`, message the claim key) for each key of
  the failed draft that is neither an exact `claim_key` of a repaired claim nor marked by an `insufficient_evidence` entry whose `context`
  starts with exactly `f"{key}: "` and has a non-whitespace character after that prefix (so `V.10: ...` never covers `V.1`); and one
  `repair_dropped_insufficient_evidence` issue (path `/insufficient_evidence`) for each `insufficient_evidence` entry of the failed draft
  with no equal entry (same `context` and `reason`) in the repaired draft. Code checks; it never merges entries back into the output.
- Robustness: the failed draft may be schema-invalid. Read keys only from list items that are dicts with a string `claim_key`, count a
  duplicated key once, and read old `insufficient_evidence` entries only when they are dicts with string `context` and `reason`. A failed
  draft that did not parse yields no such issues. The two collections are read independently: a `claims` that is not a list disables only
  the claim-key check, and an `insufficient_evidence` that is not a list disables only the kept-entry check. No exception, no extra call.
- This guarantees **key coverage**, not that a kept key still says what it said: a repair may keep `V.3` and change its meaning.
  Renumbering fails; the message tells the model to keep keys. With the one repair used, the step then fails visibly instead of storing a
  section that lost claims.

### 4. Out of scope (name in D198, do not build)

First-pass anchor contract (decision "Why" 3); anchor patches for `anchor_not_in_passage` or any other code; sending the failed output in
repairs of other tasks; repair for `NO_REPAIR_TASKS`; UI labels for the new codes (the existing code-with-spaces fallback shows them);
`scripts/model_behavior/*`; the H9b real-model re-measurement (a later step the coordinator schedules).

## Files

Allowed: `backend/deixis/domain/contracts.py`, `backend/deixis/models/prompt.py`, `backend/deixis/workflow/flow.py` (only `_model_step`
and new private helpers next to it; P8 B5 edits flow.py's provider code at the same time, keep the diff local),
`contracts/research/report-section-anchor-repair.schema.json` (new), `methods/deixis-research/SKILL.md`, the six reference files named in
decision 1, `methods/deixis-research/references/report.md` (one short paragraph on the patch beside the anchor rules at `:25-30`),
`methods/deixis-research/provenance.json`, `tests/fakes.py` (only if a helper for patch answers is needed), `tests/acceptance/fixture_server.py`
(answer the patch call: `[report-bad-anchor]` returns a patch whose `quote_number` is out of range, so IV still fails with the anchor reason
first; a new marker `[report-anchor-patch]` returns quote number 1 so IV becomes valid), new test files, `tests/fixtures/research/` (new
replay fixture, and `fake-outputs.json` only if a test requires an example for every contract file), and existing tests only where decisions
1-3 change pinned behavior (package-hash pins in `tests/test_lineage_columns.py:293`, `tests/test_report_failed_rows.py:363`,
`tests/test_report_anchor_repair.py`; any test asserting the sent schema equals `step_output_schema`); list each change and why.
`docs/decisions.md` (the D198 draft only).

Forbidden: `backend/deixis/storage/*` and migrations, `backend/deixis/workflow/report/*`, `workflow/views.py`, `workflow/review/*`,
`providers/*`, `apps/web/*` (including `e2e`), `scripts/*`, every existing `contracts/research/*.schema.json`, `STATUS.md`. If the batch truly
needs one of them, stop and report.

## Tests that must fail on the old code, and regression guards

Name each test's role: **red on old** (its first assertion is behavioral, uses only what exists on `581e156`, and fails there for the named
defect), **guard** (passes on both) or **new contract** (exercises something absent on `581e156`; name its paired red-on-old or guard). The
orchestrator re-runs the red-on-old tests against a clean copy of `581e156`. New module `tests/test_report_path_fix.py` (split if long).

**H9 replay fixture** `tests/fixtures/research/h9-report-replay.json`, top-level `"label": "SYNTHETIC replay fixture derived from H9 stored
outputs (run_YHPhlrH3yeRdPIQwCdoI); only the fields the checks read"`. Build it with a one-off script you do not commit, from a copy of the
H9 library the orchestrator placed at
`/private/tmp/claude-501/-Users-huguryildiz-Documents-GitHub-DEIXIS/16852fcf-1db8-4cf8-824b-323504a194da/scratchpad/h9/library.sqlite`
(read-only; never open `../DEIXIS-h9run`). Contents: for IV and V, the first attempt's StepInput reduced to what validation needs (envelope,
task type, `report_target` with section id, plan axes the drafts use, and the cells the drafts cite with their evidence quotes; the
allowlist; passages only those the drafts cite, each `text` cut to the anchor quotes that cite it joined by a space), the first raw output, its
stored issues, and the repair raw output with its stored issues; for the abstract-screening and full-text sessions, only the hash strings. If
a reduced StepInput no longer validates the stored first output to exactly its stored issues, keep more fields until it does, and assert
that equality in a test. No full abstracts beyond what the anchors quote. Store the outputs in their resolved form (real record IDs, as
`resolve_citation_handles` returned them; D127 accepts correct real IDs from the model).

**Replay through `_model_step`.** Do not rebuild H9's tables in a database. Use `_model_step`'s `step_input_builder` seam
(`flow.py:5299`, `:5410`) to supply the fixture StepInput for each attempt with that attempt's fresh `step_id`/`step_input_id`
(the builder receives the step id; keep `scope_revision` and the package hash consistent with the flow). The fake adapter returns the stored
output with **only** its envelope fields rebound to the attempt it answers (`step_input_id`, `scope_revision`, and, for the stored hash
cases, the miscopied hash string kept on purpose); claims, anchors, IDs and text stay byte-for-byte as stored. Before any repair assertion,
assert that the first attempt reproduces exactly the stored first-attempt issues (codes and paths). The StepInput must pass
`check_step_input`; keep the passages and sources it needs for that.

- **E1 (red on old): a miscopied hash no longer fails a step.** FakeAdapter answers `abstract_screening`, `fulltext_adjudication` and
  `report_section` with otherwise valid outputs carrying each H9 miscopied hash string. First assertion: the step succeeds (old:
  `envelope_mismatch`; for abstract screening the step failed with no repair). Then the stored result carries the StepInput's hash and
  `validation_json.normalised` records the stamp with the model's value.
- **E2 (new contract, paired with E1): the sent schema has no hash, the stored contract does.** For every task type in `TASK_OUTPUTS`:
  `model_output_schema` lacks the property, passes `strict_compatibility_issues`, and is what the adapter received and
  `step_inputs.output_schema_json` stored; `step_output_schema` and the contract files are unchanged; `validate_model_output` on an output
  without the hash still reports it (stamping supplies it, validation does not relax). A non-enforcing fake adapter gets the patch-free
  model schema in its appendix.
- **E3 (guard): binding and isolation keep their value.** A wrong `step_input_id` or `scope_revision` still gives `envelope_mismatch` and the
  repair path; a resolved model other than the requested one still fails `model_mismatch` with output unused; a tool item still fails
  `model_isolation_violation`.
- **A1 (red on old): H9 IV replay is repaired by a one-anchor patch.** Through `_model_step` with the replay seam above, first call returns
  the stored IV first output; the second
  returns `{"anchors": [{"anchor_index": 8, "quote_number": 1}], "claims": []}` plus envelope. First assertion: the step output is not
  `invalid` (old: invalid, because the patch does not fit the whole-section schema). Then: 18 claims and the 2 `insufficient_evidence` entries of the first output are unchanged; anchor 8's quote equals the
  stored evidence quote byte for byte (including U+E0A8); no other anchor changed; the session keeps the patch as raw output; the step output
  and session record `anchor_patch` with the base input id.
- **A2 (new contract, paired with E1): the H9 IV repair output keeps failing on its anchors, not on its hash.** Validate the stored IV repair raw output
  against its stored StepInput after stamping. First assertion: no `envelope_mismatch` (old: present). Then all 21
  `citation_anchor_target_count` issues remain: code does not pick a target for an anchor that names two.
- **A3 (red on old): H9 V's dropped claims are caught on the full path.** Feed the stored V first output, then the stored V repair output,
  through `_model_step` forced onto the full path (add one non-anchor issue to the first attempt, for example one extra anchor naming an
  unknown cell id in the scripted first output; the unmodified replay's exact-issue check is a separate assertion, and here the first
  attempt's issues must equal the stored V issues plus exactly the injected one). First assertion: the step's output is invalid (old:
  succeeded). Then the issues include
  `repair_dropped_claim` for exactly `V.7` and `V.8`. Also unit checks on the dropped-claim and kept-entry functions: `V.10: …` does not
  cover `V.1`; `V.1: ` with nothing after it does not cover `V.1`; a dropped first-draft `insufficient_evidence` entry (H9 IV's two
  entries against the stored IV repair output) gives `repair_dropped_insufficient_evidence` twice; malformed failed drafts (claims `null`,
  a scalar item, an item without `claim_key`, duplicated keys, non-JSON text) give no exception and no claim-key issues; `claims: null` with a
  valid `insufficient_evidence` entry that the repair omits still gives `repair_dropped_insufficient_evidence`.
- **A4 (new contract, paired with A1): V on the patch path.** The stored V first output and a patch that sets numbers for some failing anchors
  and removes `V.1` with context and reason: the merged draft has an `insufficient_evidence` entry starting `V.1: `, no anchor of `V.1`, and
  every other claim unchanged; validation decides the rest.
- **A5 (red on old): the patch message carries no passage bait and the full message carries the failed output.** Through `_model_step`
  with a fake adapter that records what it receives (no new symbol imported before the first assertion). Patch repair: first assertion, the
  second call's message has no `"passage_id"` inside the anchor-pair block (old: present); then each allowed quote has `quote_number`, the
  guidance text is present, and the schema the adapter received and the stored `output_schema_json` are the patch adapter schema. Full
  report-section repair: first assertion, the message contains the failed raw output (old: absent); then the keep-keys line. For
  `grounded_answer` and `cell_extraction` the message stays byte-for-byte the old one (keep that existing pin).
- **A6 (new contract, paired with A1): the patch fails closed.** One parametrized case per rule: a missing failing index, an extra index, a
  duplicate, a quote number 0 or beyond the list, a removed claim without reason, `removed: false` with a reason, a claim key that owns no
  failing anchor, a claim whose only anchor is dropped and is not removed, a too-long context, a wrong `step_input_id`, a non-object answer.
  Each: no third call, section failed, the returned issues start with the first attempt's anchor issues, the patch issue code present, the raw
  patch kept, no merged draft stored.
- **A6b (new contract): pair context shows remaining support.** Two drafts that differ only in whether the failing anchor's claim has a
  second, passing anchor give different pair contexts (`failing` flags and anchor counts); with one anchor, dropping it without removal is
  `anchor_patch_claim_unsupported`; with two, dropping it is accepted.
- **A7 (new contract): dropping an anchor keeps citations consistent.** A claim with two anchors on one cell and one on another: dropping one of
  the two keeps the cell in `cell_ids`; dropping the single one removes that cell.
- **A8 (guard as a property, new contract): code never invents.** Over A1, A4, A6, A7 and randomized patches on a synthetic section: every
  anchor of a merged draft is either an unchanged anchor of the failed draft or carries a stored evidence quote of its own cell selected by a
  patch number; the anchor count never grows; claim texts change only where the patch gave `text`.
- **A9 (red on old): the browser fixture answers the patch.** In-process with `ScriptedCodex`. `[report-anchor-patch]`: its first IV
  output must carry the same bad quote as `[report-bad-anchor]`; first assertion, IV is valid after exactly two IV calls (old: failed, because
  the fixture had no patch answer); then the first attempt was invalid with `anchor_not_in_cell_evidence`, the second answered the patch
  schema, and the stored anchor is the cell's stored quote. `[report-bad-anchor]`: IV still fails after exactly two calls with first issue
  `anchor_not_in_cell_evidence` (guard). Keep `test_browser_fixture_bad_anchor_marker_fails_the_same_cell_check_in_both_scripted_calls`
  meaning the same.
- **A10 (adaptation of existing tests).** `tests/test_report_anchor_repair.py:100-106` pins `prompt.repair_message(si, problem)` as the old
  message for three tasks including `report_section`: keep that pin byte-for-byte for every call without a failed output (that call form must
  not change), and add a separate report-section assertion for the call with a failed output (failed output and keep-keys guidance present).
  `:202-225` (`test_model_step_non_anchor_repairs_keep_the_old_message_byte_for_byte`) pins the `_model_step` message for
  `report_section` too: keep its `grounded_answer` and `cell_extraction` cases; replace the `report_section` case with assertions that the
  failed output and keep-keys guidance are present. `:109-155` (`test_section_gets_exactly_one_targeted_repair...`)
  and `:228-261` (`test_model_repair_cannot_publish_another_cells_quote_or_a_whole_passage`) script whole-section second answers, which
  become schema-invalid patches. Adapt them deliberately: keep their direct-validator and assembly guards
  (`test_existing_validator_rejects_wrong_cell_quotes_and_ambiguous_targets_after_guidance`, `:265` assembly test) unchanged; where they test
  the repair call on anchor-only issues, script patches and add the patch-contract rejection counterparts (wrong cell's quote cannot be
  chosen: a number only selects inside its own pair); where they mean to test whole-section repairs, force a mixed first attempt so the full
  path runs, and keep their original rejection codes. Report each change.
- **S1 (new contract): patch schemas.** The canonical patch schema resolves its common refs through `canonical_validator`; the adapter
  schema is self-contained (no external `$ref`) and strict-compatible; whitespace-only `context`, `reason` or `text` and over-long arrays are
  rejected by schema.
- **M1 (guard): package.** The package hash changed from `sha256:5ba2d214…75ff`, integrity passes; the two pinned hashes are updated to the
  new value, which D198 records.

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests your sandbox blocks (sockets,
Chrome): list them by name; the orchestrator reruns the full suite and Playwright outside it. Then `git diff --check`. No web build is needed
for this batch (no `apps/web` change); the orchestrator runs Playwright because the fixture server changes.

## Report and records

Write `/tmp/p9rf-impl-report.md`: files changed, each decision's implementation with file:line, every test with its role and what it shows,
existing tests changed and why, full-suite counts with the failure list, the new package hash, what you could not do. Draft the decision entry at
the top of `docs/decisions.md`, above D195: `## D198 — P9 RF: code stamps the package hash, a failing cell anchor is repaired by a model-chosen
patch that code applies, and a repaired section cannot lose a claim silently` with Status (accepted, implemented; writer gpt-6.1-sol high; leave
the reviewer line for the orchestrator), Date 2026-10-03, Context (the H9 mechanics above, with session ids; D124/D126/D128 causes), Decision
(1: options A/B/C with what each keeps and loses; 2: when, contract, message, validation, application, records; 3; no schema version bump and
why), Verification (leave counts for the orchestrator), Limits (synthetic and replayed outputs only, no real-model call: whether the patch path
completes a real report is unmeasured and is the H9b re-measurement's question; H9's own outputs were used to design the fix, so a later success
on that corpus is not independent; a located quote still does not prove support; first-pass anchor failures are not prevented; the claim-key
prefix is code-written text; scripts and the review size estimate keep the canonical schema; `repair_dropped_claim` also fails a full repair
that only renumbered claims; old package hash and new). Do not edit `STATUS.md`.

## Do not

Let code choose, write or translate a quote; add an anchor or a citation; remove a claim, anchor or `insufficient_evidence` entry the patch
did not name; send a second repair or open a loop; relax `validate_model_output`'s envelope check; change the stored output contracts or their
`schema_version`; change other tasks' repair messages; touch the files listed as forbidden.
