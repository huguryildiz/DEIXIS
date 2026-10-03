<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 5 medium + 2 low, folded in; r2: düzeltmeyle hazır, 1 high + 2 medium + 1 low, folded in; r3: düzeltmeyle hazır, 3 low, folded in (max 3 rounds reached, no high or medium open). -->

# Task: P9 batch RF2: the anchor-patch schema drops the `$ref`-with-siblings construction the live API rejected, and one test checks every schema the product can send against a stricter checker

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-p9rf2`, detached at `a093f6f` (origin/main with D202). Read `AGENTS.md`, `CLAUDE.md`,
D198 and D202 in `docs/decisions.md`, `backend/deixis/domain/contracts.py:200-303`, `contracts/research/report-section-anchor-repair.schema.json`,
`contracts/research/common.schema.json` (`$defs.short_text`), `backend/deixis/workflow/flow.py:5510-5530`, `backend/deixis/models/prompt.py:33-75`,
`tests/test_report_path_fix_contracts.py:180-200` and `tests/test_contracts.py:240-260`. Venv: `.venv` is a symlink to the main checkout's arm64 venv.
Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call,
no provider call, no network. Do not touch other `../DEIXIS*` worktrees (`../DEIXIS-h9b-run` and `../DEIXIS-h9*` are read-only evidence), `TODO.md`,
`.vscode/`, `scripts/local_index.py`, port 8765, the live data directory or the live `codex-home`. Decision number **D204** (the orchestrator writes it).
No migration. Speed matters: a waiting real-model measurement (H9b) needs this commit; keep the change small.

## Why

H9b arm A (D202, product `682ba1f`) stopped on a product bug. Section V's first output had `anchor_not_in_cell_evidence` issues, so RF's
(D198) patch path ran (session `mss_ZCfs0bP64HWgkESpi3r7`, step input `sti_MSGsJTIMFoL76Fu0QX4n`, attempt 1). The live Codex/OpenAI API
refused the request before any model output (evidence, read-only: `../DEIXIS-h9b-run/.local/p9r-h9b/protocol.md`, stop-rule entry for section V, and `evidence/a/report/results.json`, `stopped_by: model_call_failed_invalid_json_schema`; D202 in this checkout predates the result): `invalid_request_error` / `invalid_json_schema` for response format `codex_output_schema` at
`claims.items.properties.reason.anyOf[0]`, "$ref with sibling keywords". The stored transport schema has
`reason = {"anyOf":[{"$ref":"#/$defs/short_text","minLength":1,"pattern":"\\S"},{"type":"null"}]}`. The source is
`report-section-anchor-repair.schema.json` (`claims.items.properties.reason`), copied unchanged by `_adapter_schema` (`contracts.py:228-249`).

The fake-adapter tests never send a schema anywhere, and `strict_compatibility_issues` (`contracts.py:282-304`) checks only closed objects,
full `required`, and `oneOf`/`allOf`/`not`/`if`. `tests/test_report_path_fix_contracts.py:190-192` asserts that checker returns `[]` for the
patch schema, so it passes on the broken schema. A survey of every schema built by `step_output_schema`, `model_output_schema` (all 20 task
types) and `report_section_anchor_patch_schema` on `a093f6f` finds this one `$ref`-with-siblings node and no other; keywords in use are
`$defs $ref additionalProperties anyOf const description enum items maxItems maxLength minItems minLength minimum pattern properties required type`;
no `format`; object nesting depth at most 3, at most 46 properties (`step_output_schema("report_section")`; its model variant has 45) and 24 enum values per schema.
Whether the repaired schema is accepted live is not established by this batch; that is H9b's first gate.

## What to change

### 1. Fix the patch contract (decision taken)

In `contracts/research/report-section-anchor-repair.schema.json` replace `reason` with the same shape as its siblings `text` and `context`:
`{"type": ["string", "null"], "minLength": 1, "maxLength": 600, "pattern": "\\S"}` (600 is `short_text`'s `maxLength`). The canonical
validator accepts and rejects exactly the same values as before (null, or a string of 1–600 characters with a non-space), so `schema_version`
stays `deixis.report_section_anchor_repair.v1`; no other contract file changes. Rejected: a generic transform in `_adapter_schema` that inlines
`$ref` with siblings. It would hide authoring mistakes from the checker and make the stored transport schema differ from its contract file.
No method package file changes are expected (so `skill_package_hash` stays); if you find one is needed, say so in the report.

### 2. Strengthen `strict_compatibility_issues`

Keep its signature (`schema, path="$"`) and its list-of-strings result. It is the floor for the OpenAI Structured Outputs strict mode that
Codex uses (`codex_rpc.py:186` passes `outputSchema`; the API names it `codex_output_schema`). Rules, each with a distinct message prefix:

Implement it as a public wrapper that applies root-only rules (R4, R5's root `$defs`, R7) once to the schema it is given, plus a private
recursive walker for node rules; the recursion never re-applies root rules to properties or `anyOf` branches. Name the checker honestly in its docstring: a conservative offline guard for OpenAI strict mode, not a full specification. Label each rule in the code
comment and the docstring with its evidence class: **rejection observed** (live API refused it), **documented** (OpenAI Structured Outputs
supported-schemas page; not read offline in this batch), **request accepted** (sent in earlier live sessions without rejection, which shows
the API accepted the request, not that it enforces the keyword), or **DEIXIS policy** (conservative, stricter than any known API rule).

- R1 (rejection observed in H9b, `../DEIXIS-h9b-run/.local/p9r-h9b/protocol.md:9`, D202 run; also the openai-python SDK 2.20.0 `openai/lib/_pydantic.py:95-113` inlines any `$ref` with other keys,
  naming `description` as an example, "we can't use `$ref`s if there are also other properties defined"): a node with `$ref` has no other keyword.
- R2 (documented; kept): every object node, including one whose `type` list contains `"object"`, has `additionalProperties: false` and
  `required` equal to its property names.
- R3 (DEIXIS policy, keyword allowlist): flag any keyword outside `type properties required additionalProperties items enum const anyOf $ref
  $defs description title pattern format minLength maxLength minimum maximum exclusiveMinimum exclusiveMaximum multipleOf minItems maxItems`.
  This replaces the old `oneOf`/`allOf`/`not`/`if` list (documented unsupported composition) and also flags `then`, `else`,
  `patternProperties`, `unevaluatedProperties`, `dependentRequired`, `dependentSchemas`, `prefixItems`, `contains`, `uniqueItems`, `default`,
  `examples` and typos, whether or not the API would accept them. Walk only schema positions: keys of `properties` and `$defs` are names, and
  the values of `enum`, `const`, `required`, `pattern`, `description` and `title` are data. `type` must be one of `string number integer
  boolean object array null`, or a non-empty list of distinct such names.
- R4 (documented): the root is `type: "object"` with no `anyOf` at the root.
- R5: every `$ref` resolves within the schema (documented requirement); in addition, as DEIXIS policy, `$ref` is `#` or `#/$defs/<name>` and
  `$defs` appears only at the root.
- R6 (documented): `format`, when present, is one of `date-time time date duration email hostname ipv4 ipv6 uuid`.
- R7 (thresholds documented; the counting conventions are DEIXIS policy, a conservative offline guard, not a proof of equivalence to the API):
  at most 5000 object properties in total, at most 10 levels of object nesting, at most 1000 enum values in total, total string length of
  property names, `$defs` names and string enum/const values at most 120,000 characters, and a string-valued enum with more than 250 values at
  most 15,000 characters. Conventions: count properties, enum values and string lengths syntactically, once per declaration; depth counts
  object nodes only (an array's `items` object is one level deeper than the array's parent object, arrays themselves add none); follow `$ref`s
  for depth with a per-path cycle guard (a definition already on the current path stops that path; a global visited set is wrong because a
  definition reached shallowly first would be skipped on a deeper path). Recursion itself (through `#` or a definition) is allowed and is not
  flagged.
- R8 (DEIXIS policy): every subschema position holds an object (no boolean subschemas such as `true`/`false` as `items` or in `anyOf`; the
  `additionalProperties: false` value is not a subschema position here), an `array` node has `items`, and `anyOf` is a non-empty list.

Fine-tuned models reject more constraints (`minLength`, `maxLength`, `pattern` and others) per the documentation; DEIXIS does not send to
fine-tuned models, so the checker does not apply that list; say so in the docstring. The Claude and Gemini adapters have their own schema rules;
this batch does not check them.

In the same test file, also run `Draft202012Validator.check_schema` on every registry entry, so a malformed keyword value is caught outside the
allowlist.

### 3. One test over every schema the product can send

Add `contracts.model_transport_schemas() -> dict[str, dict]`: one entry per schema a model call can receive, built by the real builders:
`model_output_schema(t)` for every `t` in `TASK_OUTPUTS` (what `_model_step` sends, `flow.py:5517-5518`), `step_output_schema(t)` for every
`t` (sent by `scripts/model_behavior/*` and estimated by `workflow/review/run.py:76`), and `report_section_anchor_patch_schema()`. Keys name
the builder and task, e.g. `"model_output_schema:report_section"`.

New `tests/test_strict_schema_rules.py`:

- **T0:** the registry's keys equal an independently written expected set: `model_output_schema:<t>` and `step_output_schema:<t>` for each of
  the 20 task types listed literally in the test, plus `report_section_anchor_patch_schema` (41 keys). A new task type fails T0 until listed.
- **T1:** `strict_compatibility_issues` is `[]` for every registry entry, and `Draft202012Validator.check_schema` passes; the failure message names
  the key and the issues. Red-on-old for T1 means: new registry and new checker with the old contract file give exactly one R1 issue, at
  `$.properties.claims.items.properties.reason.anyOf[0]` of `report_section_anchor_patch_schema` (show this in the report using a scratch copy
  of the repo outside git, not with git).
- **T2 (must fail with the old checker):** a frozen literal copy of the old **transport** schema (as stored for `sti_MSGsJTIMFoL76Fu0QX4n`:
  the `reason` node `{"anyOf":[{"$ref":"#/$defs/short_text","minLength":1,"pattern":"\\S"},{"type":"null"}]}` with `$defs.short_text`
  present; build it from the current builder output, replace `reason` with that node and restore the frozen definition
  `$defs.short_text = {"type": "string", "maxLength": 600}`, which the fixed builder no longer emits) gives exactly one issue, R1, at
  `$.properties.claims.items.properties.reason.anyOf[0]`. The old checker returns `[]` for it, so T2 fails on `a093f6f`'s checker.
- **T3, bounded coverage guard (not a proof):** an AST scan of `backend/deixis/**/*.py` and `scripts/model_behavior/*.py` finds every call
  `contracts.<name>(...)` or bare `<name>(...)` whose name ends in `schema`; each name is in the registry's builder set
  (`model_output_schema`, `step_output_schema`, `report_section_anchor_patch_schema`) or in an explicit exclusion dict in the test with a
  one-line reason: at least `load_schema` (canonical contract files, never sent as is), `_adapter_schema` and `_common_schema` (internal steps
  of the registry builders), and bare `response_schema` **only inside `backend/deixis/models/gemini.py`** (`:39`, `:41`, `:115`; Gemini-only transform of a registry
  schema). Key exclusions by (file, name), not by name globally. It cannot see aliased imports,
  builders without a `schema` suffix or schemas built inline; say so in the test docstring.
- **T4:** for each rule R1–R8 one passing and one failing synthetic schema; for R7 a case at each limit and one just over it, for all five
  limits (generate the large schemas in code); a shared definition reached at depth 2 and again at depth 9 counts 9 + its own depth on the
  deep path; recursion through `#` and through a definition is accepted; property names and enum/const/pattern values spelled like keywords
  (`"if"`, `"default"`) are not flagged; a nullable object (`"type": ["object", "null"]`) without `additionalProperties: false` is flagged;
  an `anyOf` branch or a scalar property is never flagged by the root-only rules.

Existing callers that pass **canonical** schemas (with `$schema`, `$id`, external `common.schema.json` refs) to `strict_compatibility_issues`
(`tests/test_candidate_contract.py:75`, `tests/test_lineage_contract.py:70`, `tests/test_review_contract.py:25`) will now be flagged by R3/R5.
Change those assertions to check the transport schema from the real builder instead (they already have it a line or two later, or use
`model_output_schema`/`step_output_schema`), and keep their canonical-schema and reference-resolution checks. Do not loosen the checker for them.

Also check that the canonical `ReportSectionAnchorRepair` validator still accepts `reason: null` and a non-blank short string, and accepts a non-blank 600-character string, and rejects `""`,
`"   "` and a 601-character string, against both the canonical validator and the transport schema (add these to an existing patch-contract test if one is close). Existing tests that call
`strict_compatibility_issues` must keep passing; if one relied on a now-flagged keyword, report it rather than loosening the checker.

## Files

Allowed: `contracts/research/report-section-anchor-repair.schema.json`, `backend/deixis/domain/contracts.py`, `tests/test_strict_schema_rules.py`,
small edits to existing tests named above, including `tests/test_candidate_contract.py`, `tests/test_lineage_contract.py` and
`tests/test_review_contract.py`. Forbidden: every other contract file, `methods/`, migrations, `apps/web`, `docs/decisions.md`,
`STATUS.md` (the orchestrator writes records), fixture outputs unless a test proves they must change.

## Report

Write `/tmp/p9rf2-impl-report.md`: files changed with line ranges, the rule list with confirmed/unconfirmed status, how T1 and T2 fail on the old
contract and old checker (in a scratch copy outside the repo, never with git),
focused test results (`tests/test_strict_schema_rules.py tests/test_report_path_fix_contracts.py tests/test_report_path_fix.py
tests/test_report_anchor_repair.py tests/test_contracts.py tests/test_candidate_contract.py tests/test_lineage_contract.py
tests/test_review_contract.py` and every other test file that calls `strict_compatibility_issues`), and whether `skill_package_hash` changed. You cannot run the full suite or
Playwright; the orchestrator will.
