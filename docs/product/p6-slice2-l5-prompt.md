<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 7 high (target_fp scope, stale reuse of old fingerprints, pair_fp vs shown evidence, unbounded failed retries, plan key vs send input, stop gate, stale cycle graph) + 6 medium, all folded in; r2: hazır değil, 4 high (target_fp sources, retry_failed reach, resume losing stored successes, resend counter), all folded in; r3: hazır değil, 1 high (send record built from the job, not from the real payload) folded in as the attempt_record hook; the 3-round limit is reached, no fourth round; implementation by gpt-6.1-sol (Part A, Part B); code review r1 hazır değil (2 high, 1 medium), r2 hazır değil (1 high, 1 medium), r3 hazır değil (1 high, 1 medium), r4 hazır (0 findings), all fixed; see D135 -->

# Task: P6 slice 2, batch L5 ("Akış"), the flow that finds, asks and publishes development links

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l5` (detached at `8162c8b`, main with D134). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D130 to D134 (top), and `docs/product/p6-slice2-chain-of-ideas.md`: §3 (rules), §4.2, §4.3 (all of
it), §5 (SQL and the lifecycle paragraph), §8.2, §9 (all of it), §10, §12 "Akış", §19 "L5" and the L1 to L4 entries. The scope below was
decided by the main session and binds this prompt; where the code differs from what this prompt says, report it. Patterns to copy:
`flow.py::_table_fill`, `_send_through_limiter`, `_fill_jobs`, `_extraction`, `_model_step`, `_call_adapter`;
`tables.py::TableStore.fill_plan` and `request_fill` (plan stored in `runs.target_json`, `_replayed_run`); the L2 pure functions
(`workflow/lineage/{mentions,edges,candidates}.py`), L3's `lineage_target` schema (`contracts/research/step-input.schema.json`,
`contracts._check_lineage_target`, `tests/test_lineage_contract.py`, the `I_lineage_links` fixture, `tests/fakes.py`), and L4's
`LineageStore` (`workflow/lineage/store.py`, `tests/test_lineage_store.py`).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls, no measurement; the fake adapter and the
synthetic fixtures only.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web work (`apps/web` is not touched), no method or contract change (so `skill_package_hash`
stays `sha256:371fcecb...`), no migration (if you find one is unavoidable, stop and report instead of adding it).

## Why

L1 gave role columns, L2 pure candidate functions, L3 the contract and transport, L4 durable storage. L5 joins them: from a table it
builds the per-pair model inputs from the database, decides which works a run reads and which candidates go in which call, shows the
call ceiling before anything is sent (`GET .../lineage/plan`), queues a run whose frozen plan is stored with it
(`POST .../lineage/runs`), sends the calls through the shared limiter, and publishes the validated decisions through L4's primitives
in one fixed-order transaction. No route shows lineage results yet (L6) and no screen exists (L7).

The work has **two internal acceptance steps inside one batch and one commit**: Part A (L5a, model-free: building and planning) and
Part B (L5b, fake adapter: sending, stopping, publishing). You are told which part to do in each call. After Part A the focused
tests must be green before Part B starts.

## What is and is not in code (checked on 8162c8b)

- In code: `workflow/lineage/{mentions,edges,candidates,baseline,store}.py` (L2 and L4); `LineageStore` with `apply_model_proposal(s)`,
  human primitives, `active_links`, `human_decided_pairs`, `link`, `ensure_link`, `revisions`, `evidence`, `LIVE_ENDPOINT_SQL`;
  `mention_rules()`; `find_candidates`, `pack_candidates(candidates, fits, ...)`, `NotSent`, `Packing`, `unassessed_edges`;
  `flow._model_step(..., lineage_target=...)`, `_step_input(... lineage_target ...)`, `HANDLE_TASKS` and handle resolution for
  `lineage_links`; `contracts.LINEAGE_TASKS`, `_check_lineage_target`, `_check_lineage_links`; migration `0059` (`runs.kind` accepts
  `lineage_links`; `runs.stage` list is unchanged and includes `synthesis`); `TableStore.trash_table`/`table_impact` already know
  lineage runs.
- Not in code: any builder of a `lineage_target` from the database, any planner, any `lineage_links` flow branch (`flow.execute`
  falls to `_table_columns` for an unknown kind: **dangerous, close it in Part A**), any lineage route, any run stage mapping for the
  kind (`Store.create_run` falls back to `extraction`), `input_stale` in `apply_model_proposal`. Check, do not assume.

## Decisions (already taken; do not reopen)

### Shared vocabulary

- **Pair fingerprint** (`pair_fp`): sha256 hex of the canonical JSON (sorted keys, no whitespace, `ensure_ascii=False`) of the
  model-visible input of ONE candidate pair: `plan_version`, `table_id`, `scope_revision`, `selection_revision` (the research's
  current one; D130 lists it, so any inclusion change re-asks: a stated limit), `skill_package_hash`, the output schema version
  (`contracts.SCHEMA_VERSIONS["LineageLinksDraft"]`), the model triple of `step_model(scope, "lineage_links")`, the mention rules
  version (`mentions.NORMALIZATION_VERSION`), both nodes exactly as `lineage_target` shows them (source id, year, the three cells
  with cell revision id, column revision, instruction revision, instruction text, state, value, reading depth, output status, flags,
  evidence quotes), the two `sources` records the StepInput shows for them (title, `work_id`, year, version label, access level), the
  candidate's `edge_state`, `year_order_warning`, `mention_passage_ids`, and the sha256 of each mention passage's text. Timestamps and
  new step, run or step-input ids never enter it. It does NOT depend on the other candidates of the same call, so chunk shape alone
  never re-asks a pair. The fingerprint is a SELECTION and REUSE key; the passages a decision may cite beyond its own mention
  passages are guarded separately at publication (Part B item 7).
- **Three different identifiers, never mixed.** (1) The **planned chunk key** `lineage_links:{to}:{index}:{plan chunk_fp[:16]}`, stable
  for the life of the run, is the step `operation_key`. (2) `pair_fp` above is the pair's evaluation key: it selects work, decides
  reuse, and is what L4 stores as `inputs_json.fingerprint`; it is computed by ONE pure function from a StepInput payload (real or
  planning stub) plus the research's selection revision, so planning, sending and publication cannot disagree about its meaning.
  (3) The **send record** of an attempt: everything publication and later plans need to know about what was REALLY sent, derived from the
  real payload of that attempt (Part B items 2 and 3(d)): per pair the `pair_fp`, `link_version`, edge state and node snapshots; per
  shown passage its id, text sha256 and currency; the selection revision. This replaces the design note's single `input_fingerprint`
  wording ("whole task input digest"): the orchestrator records the split in D135 and the note.
- **Target fingerprint** (`target_fp`, cheap, computed for EVERY eligible target BEFORE any scanning): sha256 of `plan_version`,
  `mention_rules()`, `scope_revision`, `selection_revision`, `skill_package_hash`, the schema version, the model triple, the target's
  `source_version_id`, `references_read`, referenced ids and passage `(id, extraction_version)` pairs, every OTHER live work's identity
  (source version id, work id, title, authors, year, same-work years, OpenAlex ids), the StepInput `sources` record of EVERY live work
  including the target (title, `work_id`, year, version label, access level, which changes when a first PDF is attached even though
  no revision counter moves), the compact node snapshot (source id, year, the three cells' revision ids, column revisions,
  instruction revisions and texts, states, flags) of EVERY live work including the target, and the human-decided pairs that end at this target. It says "neither the model-free scan nor any model-visible node input
  could differ from when this target was last assessed". A node edit anywhere re-opens every target (class `changed`); that costs a
  scan, not a call, because pending pairs are decided by `pair_fp` (below).
- **Eligible target**: a live endpoint (L4's `LIVE_ENDPOINT_SQL` rule; take rows in table order and number them `position` 0..n-1) with at
  least one current `pdf_page` passage in `Store.passages_for(svid)` (stored text, not "full text reviewed").
- **Assessed pair**: a candidate pair whose LATEST `model_propose` revision (by `created_at`, then id) has `inputs_json.fingerprint`
  equal to the pair's current `pair_fp` AND is either accepted or rejected with `anchor_not_found`, `same_work` or `cycle`. A latest
  revision at another fingerprint, or rejected with `stale_input`, `endpoint_not_included` or `superseded_by_human`, does not make the
  pair assessed (so an A, then B, then A input history re-asks the pair; a rejected record is never reused as the current decision, and
  no old output is reused at all). Limit to record: a `cycle` rejection is not retried until the fingerprint changes.
- **Known-failed pair**: not assessed, and an earlier `lineage_publication` record of this table lists it in `failed_pairs` with the same
  `pair_fp`, and the pair has no `model_propose` revision created AFTER that record (a later successful retry, at any fingerprint, ends
  the failure: so a failure at A, a successful retry at A, a change to B and a return to A re-asks the pair). It is NOT pending for automatic runs (no unbounded retry, no starvation of later candidates by pairs that always fail);
  it becomes pending again when its fingerprint changes or when the request says `retry_failed: true` (Part A items 8 and 9).
- **Pending pair** of a scanned target: a candidate pair (after `excluded_pairs = LineageStore.human_decided_pairs(table_id)`) that fits
  one call alone, is not assessed and is not a known-failed pair (unless `retry_failed`).

### Part A (L5a, model-free)

1. **Module** `backend/deixis/workflow/lineage/run.py` (new; it may import `store.py` and the L2 modules and `workflow.tables`/`store`;
   it must NOT import `flow.py`: anything needing the flow's `_step_input` arrives as an injected callable). Public pieces, names yours:
   a snapshot builder, the `lineage_target` builder, the fingerprints, the planner, the preview, `request_run`, and
   `stale_link_revisions(table_id)` (Part B uses it, L6 will too). A second new file under `workflow/lineage/` is allowed only if
   `run.py` would pass about 900 lines; say so.
2. **Snapshot** (one synchronous read, no awaits, so it is consistent): live rows in table order; per row `LineageWork` (title, authors
   from `authors_json`, year, `years` = distinct non-null years of the OTHER source versions of the same work, `references_read`,
   referenced ids from `record_references`, `openalex_ids` from `identifier_mappings` where `scheme = 'openalex'`, passages from
   `Store.passages_for` as `PassageText`). Non-target works need no passage texts (use `()`); load texts only for targets that are
   actually scanned. The same builder serves L6, so it takes `table_id` and returns plain frozen data.
3. **Node and `lineage_target` builder.** For one source version: for each role `problem`, `change`, `uncertainty` the table's active
   (`removed_at IS NULL`) column with that `lineage_role`. Read ONLY the cell's current revision (`evidence_cells.current_revision_id`);
   a pending model proposal is never read as the value. Fields as L3's schema: `role`, `cell_id` (display handle source; the cell is `missing` when the row does not exist OR its current revision is
   NULL, for example a row that only holds a pending proposal; then `cell_id` and every stored-content field are null), `cell_revision_id`, `column_revision` (the column revision the current cell revision was made under),
   `instruction_revision` and `instruction` (the column's CURRENT
   revision, also set when the cell is missing but the column exists; null when the role has no column), `state` (the seven cell states or
   `missing`), `value` (the text value's `text`, at most 500 characters, else null), `reading_depth`, `output_status`, `flags`
   (`stale_column` = revision's `column_revision` differs from the column's current revision; `pdf_removed`, `pdf_replaced`,
   `text_superseded` from the same evidence status SQL the table view uses; `not_verified` = state `not_verified` or output status
   `unverified_draft`), `evidence_quotes` (non-null stored `anchor_text` of the current revision's evidence links, in link `rowid`
   order, never truncated and without passage ids). A `missing` cell carries no stored content (the L3 validator checks this). The
   builder output must pass `contracts.check_step_input` inside a real StepInput (test it).
4. **Real size predicate.** `fits(chunk)` for `pack_candidates` builds the chunk's real `lineage_target`, the real StepInput through
   an injected function (provided by the flow: it calls `ResearchFlow._step_input` with a stub run whose ids have the real `new_id`
   lengths and `max_model_calls` set to the plan-wide upper bound, then `contracts.with_citation_handles` and
   `prompt.step_message`) and requires `len(message) <= 48_000` AND at most 8 candidates AND at most 24 unique shown passages. Add a
   flow method for this (e.g. `ResearchFlow.lineage_message_chars(...)`), no business logic in it. The stub's `max_model_calls` is the
   plan-wide upper bound (`6 * 75`, three digits), so the measured length is an UPPER BOUND of the real first message by
   construction (the real budget has at most as many digits; test that the real first message is never longer). Repair messages are
   guarded at send time: Part B item 3(a).
   Every `NotSent` from `pack_candidates` becomes a recorded `not_sent_budget` entry `{to, from, reason, pair_fingerprint}` with
   reason `too_large_for_one_call` or `beyond_call_limit`; nothing is silently dropped and nothing is "no relation".
5. **Run selection** (the 25-work limit; classification happens BEFORE scanning, using target fingerprints only):
   - History comes from earlier lineage runs of this table at the research's current scope revision: their stored plans
     (`runs.target_json`, `selected` entries with their `target_fp`) and their `lineage_publication` step output (Part B item 6,
     `targets[].outcome`, `failed_pairs`). A target selected in an earlier plan whose run never published counts as `incomplete`.
   - Class per eligible target: `new` (never selected in an earlier plan of this table and scope revision), `changed` (selected before,
     current `target_fp` differs from the latest recorded one), `retry` (selected before, same `target_fp`, latest outcome
     `incomplete`), or skipped as `settled` (same `target_fp`, latest outcome `settled`, and, when the request says `retry_failed`, no known-failed pair recorded for
     it: a settled target that still holds known-failed pairs is class `retry` under `retry_failed`, otherwise an explicit retry
     could never select it). Take targets in class order `new`, `changed`,
     `retry`, and inside a class in table order, at most `MAX_LINEAGE_TARGETS = 25`. The rest are recorded in the plan as
     `not_selected` with reason `beyond_work_limit` or `settled` (a count and the list; no hiding).
   - Scan only the selected targets with L2's `find_candidates(works, targets=selected, excluded_pairs=...)`, then drop non-pending
     pairs (already assessed at the current `pair_fp`); a selected target left with no pending candidate is `settled` (failed pairs that are known-failed and unchanged are listed in
     the plan as `failed_unchanged`, never hidden) (no call,
     and still occupies its slot: the 25 is a scan-cost bound). `no_candidate_targets` and `scanned_targets` of L2 are recorded in the
     plan. Pairs that do not fit alone are never pending-for-sending and never block anything: they are recorded as
     `not_sent_budget` with `too_large_for_one_call` and the target is `settled` if nothing else is pending. A target with more
     sendable candidates than three calls hold leaves the rest `beyond_call_limit` and the target `incomplete` (so the next run
     reaches them, `retry`).
   - Pack each target's pending candidates with `pack_candidates(..., fits=...)` (priority order is L2's). `C` = total chunks.
6. **Plan** (stored, frozen, never regenerated on resume). `runs.target_json` carries at the root `table_id` and `plan_version` (1) and
   also: `scope_revision`, `selection_revision`, the model triple, `rules` (`mention_rules()` verbatim plus the packing limits 8, 3, 24,
   48,000, `MAX_LINEAGE_TARGETS`, `max_schema_repairs` = `schema_repairs("lineage_links")`, `max_rate_limit_model_retries` =
   `MAX_RATE_LIMIT_MODEL_RETRIES`), `selected` (per target: `to`, `class`, `target_fp`, `position`, candidates with `from`,
   `pair_fp`, `edge_state`, `year_order_warning`, `basis`, `mention_passage_ids`, `total_matches`, and the pair's
   `link_version`/`current_revision_id` as they stood), `no_candidate`, `chunks` (`key`, `to`, `index`, ordered `from` ids, chunk
   fingerprint, shown passage ids, measured `message_chars`), `not_selected`, `not_sent_budget`, `failed_unchanged` (known-failed pairs left out), `retry_failed` (the flag the plan was
   built with), `unassessed_edges` (a COUNT only; the
   list is derived live by L6), `counts`, `preview_fingerprint`, `max_model_calls`, `max_provider_requests` (0). The planned chunk `key` is
   `lineage_links:{to}:{index}:{chunk_fp[:16]}` and names the chunk in the plan and in reports; the step `operation_key` is this planned
   key (Part B item 2).
   `preview_fingerprint` = sha256 of the canonical plan content EXCLUDING ids that are new on each build and timestamps.
7. **Budget.** `max_model_calls = C * (1 + schema_repairs("lineage_links")) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)` (today `6 * C`),
   `max_provider_requests = 0`; the factors are stored in the plan. The ceiling is shown by the preview before anything is sent.
8. **Preview and request.** `request_run(research_id, table_id, preview_fingerprint, retry_failed, idempotency_key)`:
   in ONE transaction: replay a stored run for the same idempotency key BEFORE anything else, accepting it only when its
   `research_id`, kind and `target.table_id` all match the request (otherwise `RevisionConflict`, 409: never return another table's run; the stored key is namespaced per research as the other table
   runs are, `lineage:{research_id}:{key}`, so the same raw key in another research is simply a different key, and the same raw key
   for another table of the SAME research finds the first table's run and is refused); refuse (`RevisionConflict`, 409) while another run of
   the research is active (`create_run` does this) AND while another `lineage_links` run of THIS table is `paused` (its stored
   results are unpublished: resume or cancel it first); rebuild the plan with the request's `retry_failed`;
   if its `preview_fingerprint` differs from the request's, `RevisionConflict` (409) naming that the plan changed; if no target is
   selected at all, `InvalidLineageInput` (422, "nothing to assess"); a plan with selected targets but ZERO calls is allowed (the run
   records that those works have no candidates, otherwise the same first 25 works would be offered forever); then
   `Store.create_run(research_id, "lineage_links", budget, key, target)`. Add the stage mapping for the kind in `create_run`
   (use `synthesis`, which the schema allows and `i18n.ts` already labels; confirm by reading how the web uses `stage` that nothing
   breaks for it, change no web file, and if it would break something use `extraction` and say why).
9. **API** (`api/app.py`): `GET /api/researches/{research_id}/tables/{table_id}/lineage/plan?retry_failed=false` (the preview:
   everything of the plan that a person needs to see before starting, i.e. the counts, `calls` = C, `max_model_calls`,
   `max_provider_requests`, the selected targets with class and candidate/chunk counts, `not_selected`, `not_sent_budget`,
   `failed_unchanged`, the development-column and missing-cell counts, `preview_fingerprint`; no model call) and
   `POST .../lineage/runs` (202, body `{preview_fingerprint, retry_failed}`, header `Idempotency-Key`, wakes the worker, returns the
   run). Add an exception handler mapping `InvalidLineageInput` to 422 like `InvalidTableInput`. CSRF and Host rules are the existing
   ones. The cancel route must not call `adapter.cancel()` for a running `lineage_links` run either (extend the `table_fill`
   exemption: calls run concurrently). The existing web does not know the kind (`RunKind`, `runKindLabels`; `Transcript` would
   describe it as an answer run): that is an L7 item, not an L5 check; do not touch `apps/web`.
10. **Flow dispatch (safety, part A).** `ResearchFlow.execute` gets `elif run["kind"] == "lineage_links": await self._lineage_links(run,
    scope)`. In Part A `_lineage_links` is a placeholder that raises `NotImplementedError("lineage flow: part B")`; Part A tests never
    start the worker. Part B replaces it.

### Part B (L5b, fake adapter)

1. **`_lineage_links(run, scope)`** in `flow.py` (helpers may live in `lineage/run.py` when they do not need the flow): reads the plan from
   `run["target"]` (never rebuilds it), `_checkpoint(run_id, run["scope_revision"])`, fails the run with `table_unavailable` if the table
   is gone or trashed, and goes straight to completion when a `lineage_publication` step already `succeeded` (no call, no second
   publication).
2. **Jobs and keys.** One job per planned chunk, in plan order, sent through `_send_through_limiter(run, jobs, call, applied)` with
   `self.deps.limiter` (D61). The step `operation_key` is the planned chunk key (`lineage_links:{to}:{index}:{plan chunk_fp[:16]}`).
   Before a job decides anything it loads the chunk's stored step: **a step that already `succeeded` is used as it is, whatever the
   database looks like now** (no skip, no new call, no new key): its output carries the send-time record (below), and the
   publication checks of items 5 and 7 judge it against the current database and write its accepted or rejected revisions. So a
   stored successful proposal can never vanish unrecorded (target excluded, extraction replaced, cell edited, human decided: each ends
   as a recorded `endpoint_not_included`, `stale_input` or `superseded_by_human` revision). Only a chunk with no succeeded step is
   sent. Nothing is filtered out of a chunk to be sent because of a human decision or an excluded end (those are enforced at
   publication). Such a chunk is skipped (no call, recorded under `skipped` with a reason, its pairs stay pending) only when its `to`
   is no longer a live endpoint, has no current text, or a passage the chunk shows is no longer current. When a chunk is sent
   ("send time") the code builds the `lineage_target` from the database NOW (Part A item 3) and hands it to `_model_step`; the
   **send record** is NOT assembled here from that build, because `_model_step` waits on `adapter.health()` and then rebuilds the
   StepInput (re-reading `sources`), and again on every repair. The record is produced by the `attempt_record` hook of item 3(d),
   from the payload of the attempt that is actually sent, and the output of a successful step (and the stored output of a terminally
   failed one) carries it together with the planned chunk key. A step that failed or is `outcome_unknown` under the same key is sent again with the
   CURRENT build (unchanged input is the same call, changed input is asked as it now is; the new attempt stores its own StepInput).
   Calls go through `_model_step(run, scope, chunk_key, "lineage_links", source_ids=[to, *froms], passage_rows=<the shown
   to-passages, deterministic order>, lineage_target=..., limiter=limiter, step_output_extra=..., ...)`. A step already `failed` with
   `invalid_model_output` or `message_too_large` is not asked again on resume (the `_extraction` pattern). Publication reads
   the send-time record from the OUTPUT of each step (never from a freshly built job), and works from the outputs collected in this
   invocation (a resumed invocation re-iterates every job and succeeded steps return instantly).
3. **`_model_step` additions (additive; defaults keep every other task unchanged; test that).** Hooks, active only when passed. (a) and
   (c) are evaluated at the TOP of the attempt loop in one synchronous section with no `await` between them and the session start (say
   so in a comment), so they run before the first send, a schema repair and an `outcome_unknown` resend:
   (a) `max_message_chars`: a message longer than the limit (first or repair; the repair message is `step_message` plus the issues) makes
   the step finish `failed` with `error_code="message_too_large"` BEFORE any session or counter increment, sends nothing, keeps the
   earlier invalid answer's recorded cost and error, and returns `{"invalid": True, "issues": [], "step_input_id": ...,
   "message_too_large": True}`; lineage passes 48,000;
   (b) the budget check that already exists at the top (`usage.model_calls >= max_model_calls` pauses, `budget_short="pause"`) stays.
   The rate-limit resend inside `_call_adapter` bypasses the top of the loop and has no budget or stop check today. Add a keyword
   `resend_guard: Callable[[], bool] | None` to `_model_step`, combined with the existing `unchanged` hook and handed to
   `_call_adapter` as `resend`: it runs right before each resend (no `await` between it and the session start), raises `RunStopped`
   through the send gate when the run is not `running` or the scope moved, and returns False when `usage.model_calls >=
   max_model_calls` (then `_call_adapter` returns the no-session result, `_model_step` continues to the top of its loop and its
   budget branch pauses the run). It must NOT make every resend leave `_call_adapter`: that function's retry counter restarts at each
   entry, so routing every resend through the outer loop would turn the two-resends limit into an endless loop until the whole run
   budget is gone. Keep the counter where it is, so one logical attempt still makes at most one send plus two resends (this is what
   the `6 * C` ceiling counts); test the per-chunk limit and the pause reason, not only the run total;
   (c) a `send_gate` callable: raises `RunStopped` when the run's status is anything but `running` (a `pause_requested` is turned
   into `paused` with `user_requested`, a `cancelled` run just stops) or when the research's current scope revision differs from the
   run's (the run is cancelled with `scope_revised`, as `_checkpoint` does). The existing `_checkpoint` calls alone do not give this
   (the repair path has none, `_call_adapter` checks before its backoff sleep, and `_checkpoint` ignores `paused`). The gate runs
   at the top of every loop pass, i.e. after the limiter wait and the `adapter.health()` await, and again through `resend_guard`;
   (d) an `attempt_record` callable `(payload) -> dict`: called at the top of every attempt, right after `_step_input` has built the
   real payload and in the same synchronous section as (a), (b) and (c) (before `insert_step_input` and the session start). It returns
   the send record: the model-visible part comes from `payload` through the pure `pair_fp` function (never from a separate build),
   the rest (link versions, selection revision, shown-passage digests and currency) is read from the database in that same
   instant. `_model_step` keeps the record of each attempt; the output of the attempt that succeeded carries it (merged like
   `step_output_extra`), and a terminally failed step (`invalid_model_output`, `message_too_large`) stores it in its `output`
   next to `step_input_id`, so `failed_pairs` carry the fingerprint that was really sent. A rate-limit resend reuses the record of its
   attempt (same payload).
4. **Stopping and budget.** After a pause, cancel, new scope revision or model/budget pause, calls already in flight finish and their
   steps record their results, but NOTHING is published. A paused run's stored successful outputs are used on resume with no new call;
   a cancelled or scope-revised run never publishes. `budget_exhausted` pauses the run. A resume does NOT enlarge the budget or reset
   its counter, so a run paused for budget with unsent chunks pauses again at once without sending; the way forward is cancel and a
   new preview (document this in a comment and in the report). No revision is ever produced for an unsent or failed candidate
   (bounded failure never becomes `no_relation`).
5. **Terminal states and the barrier.** A chunk is terminal when it `succeeded`, or is `invalid` after the one allowed repair
   (`invalid_model_output`), or `message_too_large`, or was `skipped`. Anything else (pause, budget, a model failure that pauses the
   run) is not terminal and blocks publication. Publication happens only when EVERY planned chunk is terminal, in ONE
   `transaction(conn)`: (i) re-check in that transaction, with `_checkpoint(run_id, scope_revision)` semantics, that the run is
   `running` (a `pause_requested` or `paused` status raises `RunStopped` unpublished; `execute` must never turn such a run into
   `completed`; add a guard if `execute`'s generic completion would), that the research's scope revision equals the run's, and that
   the table exists and is not trashed; (ii) take the decisions of every succeeded chunk from the collected outputs (real ids, because
   `_model_step` resolved the handles); (iii) build one proposal per decision with `research_id, table_id, from_svid, to_svid,
   decision` (the draft's item), `edge_state`, `run_id, step_id, step_input_id, scope_revision` (the step input's),
   `link_version_at_request` (the recorded pair version), `inputs` (the compact object of item 7), `input_fingerprint` (the send-time
   `pair_fp`), `output_status="structurally_valid"`, `idempotency_key=f"lineage:{step_input_id}:{from}"` and `input_stale` (item 7);
   (iv) call `LineageStore.apply_model_proposals(proposals, stale_revisions=stale_link_revisions(table_id))` over ALL chunks at once,
   so the `(to, from)` order is global and independent of finishing order; (v) write the `lineage_publication` step in the same
   transaction. If anything raises, everything rolls back and the run fails with the error recorded (no half-applied batch).
6. **Result record.** The `lineage_publication` step (`operation_key` and kind `lineage_publication`) output carries: `published`
   (one entry per decision: `to`, `from`, `revision_id`, `disposition`, `rejection_code`, `current`), `step_failed` (planned chunk key,
   target, reason code, issue count), `failed_pairs` (`to`, `from`, the SENT `pair_fp` from the send record, reason: the pairs of every `step_failed` chunk, so a
   later plan can leave them out while their fingerprint is unchanged), `targets` (per selected target of the plan: `to`, `target_fp`,
   `outcome` `settled` | `incomplete`, `no_candidate`), `not_sent_budget` (copied from the plan), `skipped` (chunks not sent, with
   reasons), and counts. A target is `incomplete` when it has a `skipped` chunk, `beyond_call_limit` pairs, or a published pair rejected with `stale_input`, `endpoint_not_included` or `superseded_by_human`; otherwise it is `settled` (other recorded rejections count as assessments, and failed pairs are listed in `failed_pairs` and in the next preview's `failed_unchanged`). The run still ends `completed`; the partial outcome is explicit in
   this record, not hidden. A replayed or restarted run that finds a succeeded `lineage_publication` step publishes nothing a second
   time and makes no model call.
7. **Stale input at publication.** Add to `LineageStore.apply_model_proposal` (additive, default keeps L4 behavior; L4 tests unchanged)
   a keyword-only `input_stale: bool = False` evaluated at rule 4: when true the proposal is stored rejected with `stale_input`. The
   caller sets it when ANY of these holds: the pair's send-time `pair_fp` differs from the fingerprint recomputed at publication from
   the then-current database (using the pair's recorded candidate fields: mention passage ids, edge state, year warning) with the same
   function as planning; any passage the decision cites as evidence (it may be a passage shown only because of another candidate in
   the chunk), or any mention passage, is no longer current or its text sha256 differs from the digest recorded at send time. The
   compact `inputs` object stored with each proposal is `{"to": node snapshot, "from": node snapshot, "mention_passage_ids": [...],
   "edge_state": ..., "year_order_warning": ...}`, a node snapshot being the source id, year and, per role, the cell revision id,
   column revision, instruction revision, instruction text, state and flags.
   `stale_link_revisions(table_id)` returns `{link_id: revision_id}` for the table's current ACTIVE links that must leave the cycle
   graph: (a) any link, human or model, one of whose stored evidence passages is no longer a current passage (removed or replaced
   file, superseded extraction; use the same currency rule as `Store.passages_for`); (b) a model-authored link whose recorded `inputs`
   node snapshots differ from the current node snapshots of its two ends, or whose revision `scope_revision` differs from the
   research's current one. It is deliberately NOT keyed on the selection revision (a global inclusion change must not make every
   published link stale; ends that are no longer live are L4's job). A human link with stale evidence leaves the graph too, but a
   human decision is never rewritten. The map is by revision id, as L4 requires.
8. **Stage and kind plumbing.** `Store.create_run` stage mapping (Part A). The table-run family checks (trash, delete) are L4's.
   `research_view`/`views.py` must not break when a `lineage_links` run exists (test: GET the research with such a run in each status
   returns 200); change `views.py` only if it does break and then minimally. This is an API-level check only, not a UI acceptance.
9. **Second run progresses** (Part A item 5 plus this): after run 1 publishes, a new preview skips settled targets, reaches
   works 26 and beyond, never re-sends a pair already assessed at the same `pair_fp`, leaves known-failed pairs out until their
   fingerprint changes or `retry_failed` is asked, and re-selects a target whose input changed.
10. **Fixture server.** Do NOT change `tests/acceptance/fixture_server.py` in this batch (nothing calls lineage from the web until L7,
    which owns the §13 scenario and its scripted model). Report this as a judgement.

### Limits of L5 (do not exceed)

No view model, no `GET .../lineage`, no human edit routes, no baseline route (L6); no web; no real provider, no model call outside the
fake adapter; no change to contracts, schemas, methods or migrations; no change to `mentions/edges/candidates/baseline.py` (if you
need a different signature, wrap it in `run.py` and report). L4 store changes: only `input_stale` and, if truly needed, small
read helpers. No semantic claim: stored quotes are located text, the validator checks structure not meaning.

## Files allowed

`backend/deixis/workflow/lineage/run.py` (new, plus at most one more new file there), `backend/deixis/workflow/lineage/store.py`
(additive only), `backend/deixis/workflow/flow.py` (`execute` dispatch, `_lineage_links` and its helpers, `lineage_message_chars`,
`_model_step`/`_call_adapter` additive parameters), `backend/deixis/workflow/store.py` (only the `create_run` stage mapping),
`backend/deixis/api/app.py` (two routes, request model, exception handler, cancel exemption), `backend/deixis/workflow/views.py` only
if a lineage run breaks it, `tests/test_lineage_plan.py` (new, Part A), `tests/test_lineage_flow.py` (new, Part B), and any existing
test whose exact expectation legitimately changes (say which and why; for example a test that pins the set of `execute` branches or the
purity allow-list of `workflow/lineage`). `docs/decisions.md` (D135), the slice note and this prompt's comment line are written by the
orchestrator, not by you.

## Files NOT allowed

Everything else, in particular `backend/deixis/domain/*`, `contracts/*`, `methods/*`, `backend/deixis/storage/migrations/*`,
`backend/deixis/workflow/worker.py` (touch only if recovery really needs it, and report), `workflow/lineage/{mentions,edges,
candidates,baseline}.py`, `apps/web/*`, `tests/acceptance/*`, `scripts/*`, `docs/product/sw-status.md`, `TODO.md`, `.vscode/`.

## Tests to add (synthetic, no network, no real model; name each so its limit is readable)

Fixture: a synthetic research with one table, role columns added through `add_development_columns`, six to twelve live source versions
with PDF passages (some abstract-only), cell revisions filled through the real `TableStore` primitives, text marked SYNTHETIC; reuse
the helpers of `test_lineage_store.py` and `test_lineage_contract.py`.

`tests/test_lineage_plan.py` (Part A; no adapter is ever called: use an adapter that raises on any call, and assert the provider
http client saw nothing):
- Node builder: `test_node_cells_read_only_the_current_revision` (a pending proposal is never the value),
  `..._missing_role_and_missing_cell` (including a row that only holds a pending proposal: `missing`, null `cell_id`),
  `..._flags_and_stale_column`, `..._evidence_quotes_order_and_no_truncation`, `..._value_is_cut_at_500`,
  `test_built_target_passes_check_step_input`.
- Eligibility: `test_only_current_pdf_text_makes_a_target_eligible` (abstract-only no; replaced extraction no),
  `test_excluded_pairs_are_the_human_decided_ones`.
- Packing with the REAL message: `test_nine_candidates_make_two_calls`, `test_message_over_48000_splits_a_chunk`,
  `test_single_candidate_too_large_is_recorded_not_sent_budget`, `test_beyond_three_calls_is_recorded`,
  `test_pack_fits_uses_the_handle_message`, `test_measured_message_is_an_upper_bound_of_the_real_first_message`.
- Selection: `test_twenty_five_target_limit_and_classes_order` (at least 26 eligible targets; new, then changed, then retry; table
  order inside a class), `test_second_plan_reaches_targets_beyond_the_first_25`,
  `test_unchanged_too_large_candidate_does_not_block_new_work`, `test_settled_target_is_skipped_and_changed_target_is_reselected`,
  `test_a_cell_or_instruction_edit_anywhere_reopens_targets_but_asks_only_pending_pairs`,
  `test_no_candidate_target_is_recorded_and_not_asked`, `test_zero_call_plan_is_allowed_and_nothing_selected_is_refused`,
  `test_assessed_pair_uses_the_latest_revision_only` (input A, then B, then A again re-asks; a `stale_input` or
  `endpoint_not_included` rejection does not count as assessed; `cycle`, `anchor_not_found`, `same_work` do),
  `test_known_failed_pairs_are_left_out_until_the_fingerprint_changes_or_retry_failed` (and that a first block of always-failing pairs
  does not starve the rest; `retry_failed` selects an otherwise settled target that holds failed pairs; failure at A, successful retry at
  A, change to B, return to A re-asks the pair), `test_first_pdf_attached_to_a_from_work_reopens_targets_without_any_revision_counter_moving`
  (a real store primitive adds the PDF; cells, scope and selection revision are unchanged).
- Fingerprints: `test_pair_fp_changes_with_instruction_text_when_cell_id_is_unchanged`, `..._pdf_extraction`, `..._scope_revision`,
  `..._selection_revision`, `..._cell_revision`, `..._edge_state`, `..._source_title_or_version_label`;
  `test_pair_fp_ignores_timestamps_and_new_ids`; `test_pair_fp_ignores_the_other_candidates_in_the_call`;
  `test_target_fp_changes_with_any_node_snapshot_and_with_model_or_skill`; `test_preview_fingerprint_is_stable_across_two_builds`.
- Plan and budget: `test_stored_plan_content` (rules incl. `mention_rules()`, the repair and retry factors, not_sent, failed_unchanged,
  expected pair versions, chunk keys), `test_max_model_calls_formula_and_zero_provider_requests`,
  `test_preview_equals_stored_plan_fingerprint`, `test_request_run_409_when_the_plan_changed`,
  `test_request_run_replays_an_idempotency_key_first`, `test_idempotency_key_of_another_table_of_the_same_research_is_refused` (and the same raw key in another research is independent),
  `test_paused_lineage_run_blocks_a_new_one`, `test_active_run_of_another_kind_blocks`,
  `test_routes_get_plan_and_post_run_202_and_error_codes` (through `create_app`, CSRF as the other table routes do),
  `test_stage_is_synthesis_and_research_view_still_loads` (API level only), `test_cancel_route_does_not_cancel_the_adapter_for_lineage`.
- `test_plan_building_calls_no_model_and_no_provider`.

`tests/test_lineage_flow.py` (Part B; fake adapter, real `_model_step`, `create_app(..., start_worker=False)` or a direct
`ResearchFlow.execute`, as `test_lineage_contract.py` does; use `Worker.recover()` where a restart is meant):
- Happy path: `test_a_run_finds_asks_and_publishes` (links published by `LineageStore`, run `completed`),
  `test_no_relation_with_a_present_edge_publishes_no_link` and the same for `insufficient_evidence` (T11 integration: `active_links`
  stays empty), `test_cycle_rejection_is_recorded_not_lost` (a real flow case: two chunks of one run close a directed cycle, or an
  existing link does; shown through the revisions), `test_invalid_draft_after_one_repair_keeps_raw_output_and_makes_no_revision`
  (the real `_model_step` rejects an unlocated quote as `anchor_not_in_passage` and the chunk becomes `step_failed`; it must NOT
  be turned into an L4 `anchor_not_found` revision, and the validator must not be bypassed to fake `structurally_valid`).
- Chunks and budget: `test_nine_candidates_are_two_calls`, `test_each_send_checks_the_budget` (first send, schema repair,
  rate-limited resend, `outcome_unknown` resend: `usage.model_calls` never exceeds `max_model_calls`),
  `test_budget_exhaustion_pauses_and_invents_no_relation`, `test_resume_after_budget_pause_makes_no_progress_and_keeps_the_counter`
  (pauses again at once, no extra send, counter not reset), `test_message_too_large_is_terminal_and_sends_nothing`,
  `test_repair_message_over_48000_is_not_sent` (the first message fits, the repair would not: step failed `message_too_large`, the
  earlier invalid answer's cost and error kept), `test_invalid_after_one_repair_is_step_failed_and_others_still_publish`,
  `test_default_tasks_do_not_see_the_new_hooks` (other tasks' behavior unchanged).
- Stopping: `test_pause_while_calls_in_flight_applies_nothing_and_resume_publishes_from_stored_outputs`, `test_cancel_never_publishes`,
  `test_cancel_between_repair_and_resend_sends_nothing_more` (the send gate), `test_pause_requested_at_the_barrier_does_not_complete_the_run`,
  `test_new_scope_revision_cancels_and_nothing_is_published`, `test_outcome_unknown_resend_uses_budget_and_does_not_double_publish`,
  `test_late_result_after_pause_is_not_applied`, `test_worker_recover_marks_the_half_sent_run_paused_and_resume_finishes_it`,
  `test_crash_after_publication_does_not_publish_twice_or_call_the_model` (via `Worker.recover()` and a second `execute`).
- Order and atomicity: `test_publication_order_is_fixed_when_calls_finish_out_of_order` (limiter with several slots, adapter delays so
  chunks finish in reverse; compare the stored revision order and results with `(to, from)` order),
  `test_publication_is_one_transaction_and_a_failure_rolls_everything_back`,
  `test_stored_success_is_kept_and_judged_while_unsuccessful_steps_are_resent_with_the_current_input` (success, pause, then target
  excluded / extraction replaced / cell edited / human decision: the stored proposal is recorded as a rejected revision with its code,
  the send-time record is read from the stored output, not from a new job; a step that never succeeded is resent with the current
  input after a cell edit; a planned chunk whose shown passage was superseded by a new extraction is `skipped`, its target
  `incomplete`, and the next preview builds a new plan on the current passages).
- In-flight changes (each recorded, none applied, none lost): `test_end_excluded_in_flight_is_recorded_endpoint_not_included`,
  `test_human_decision_in_flight_is_recorded_superseded_by_human`, `test_cell_or_instruction_change_in_flight_is_recorded_stale_input`,
  `test_pdf_extraction_change_in_flight_is_recorded_stale_input`, `test_selection_change_in_flight_is_recorded_stale_input`,
  `test_superseded_cited_passage_shown_through_another_candidate_is_recorded_stale_input`,
  `test_stored_successful_output_is_checked_at_publication_even_after_a_human_decision_on_resume`.
- Human survival: `test_human_decision_survives_a_later_model_run` (excluded from candidates; and rejected in flight), the L6-dependent
  item the note ties to L5b.
- Second run: `test_second_run_progresses_and_skips_unchanged` (end to end: run 1 publishes 25 works, run 2 reaches the next ones, a
  later preview is empty), `test_incomplete_target_is_retried_with_only_its_missing_pairs`,
  `test_failed_chunks_do_not_block_the_remaining_pairs_in_later_runs`.
- `stale_link_revisions`: `test_stale_edges_leave_the_cycle_graph_by_revision` (a link whose cell revision changed no longer blocks a
  closing edge; a refreshed link counts again; a link whose evidence file was removed or replaced leaves the graph, human or model;
  a selection change alone does not make links stale).
- Real-machinery checkpoints (through the real `_model_step`, `_send_through_limiter`, `Store.update_run`, `Worker.recover()`; not direct
  callback calls): `test_pause_cancel_or_scope_change_during_limiter_wait_health_and_backoff_stops_the_send`,
  `test_rate_limit_retries_are_at_most_two_per_attempt_per_chunk_and_then_pause_as_model_failure` (one chunk that always answers 429
  cannot consume the other chunks' budget), `test_repair_counter_survives_pause_and_restart_between_invalid_answer_and_repair`,
  `test_barrier_stop_leaves_the_run_paused_or_cancelled_never_completed`.
- Send record: `test_send_record_comes_from_the_real_payload_not_from_the_job_build` (a change during the `adapter.health()` await,
  and a change between the invalid answer and its repair, appear in the record; no false `stale_input` and no acceptance under a
  fingerprint that was not sent), `test_shared_source_that_goes_metadata_to_pdf_and_back_is_judged_by_what_was_sent`,
  `test_terminal_failure_keeps_the_sent_fingerprint_and_a_plan_with_another_fingerprint_does_not_treat_the_pair_as_known_failed`
  (plan A, sent B, terminal failure, restart, publication, next preview), `test_message_too_large_failure_keeps_a_record`.
- `test_lineage_run_has_no_provider_request_and_no_other_model_task` (only `lineage_links` model calls; `max_provider_requests` 0).

## Checks to run

Part A focused: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_plan.py tests/test_lineage_store.py
tests/test_lineage_contract.py tests/test_lineage_candidates.py tests/test_lineage_columns.py -n 0`. Part B focused: add
`tests/test_lineage_flow.py` and the existing flow tests (`tests/test_flow*.py`, `tests/test_tables*.py` or whatever files cover
`_model_step`, `table_fill` and the API; find them). Then the full `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest`
(one failure is accepted: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails
only under parallel load and passes alone: rerun it alone and say so). If a test outside the allowed list fails, stop and report; do
not widen scope. If your sandbox blocks loopback or process access and a failure looks environmental, say so; do not "fix" it.

## Report at the end

Files changed; every judgement call (stage, fingerprint contents and what is deliberately left out, target classes, the zero-call run,
the paused-run block, selection revision in the fingerprint, the three `_model_step` hooks, `input_stale`, `retry_failed`, the
budget-pause resume limit, fixture server deferred, anything the note left open); what is deferred to L7 (web kind labels, build,
lint and Playwright are not run because `apps/web` is untouched); everything you could not find or verify; the exact pytest counts per part.
