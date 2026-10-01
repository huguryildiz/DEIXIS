<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 7 high (transport refusal could derive open, durable provider reservation, repair history on resume, two K1 resume windows, one-way single-active-run guard, post-call publication barrier, frozen reading depth vs dropped passages) + 3 medium + 1 low, all folded in; r2: hazır değil, 3 high (terminal invalid steps re-sent on resume and the terms step lacking hooks, transport-refusal finishing order and terminal-resume branch, delivery-class to outcome_unknown mapping) + 1 medium + 1 low, all folded in; r3: hazır değil, 1 high (terminal failed resume branch needs a persisted failure code on every failure path) + 1 medium, folded in without a fourth round (3-round limit); implementation by gpt-6.1-sol (Part A, Part B); code review r1 hazır değil (1 high: a pause during a provider request lost an uncertain delivery; 2 medium: frozen skill hash not enforced, human text NUL/surrogate gave 500), r2 hazır (0 high); see D146 -->

# Task: P6 slice 3, batch K3 ("Akış ve API"), the flow and the API for claim candidates and the claim-specific kill-search

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-k3` (detached at `58676f1`, main with D145). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D143, D144, D145 (top) and D135 (the slice 2 flow batch), and `docs/product/p6-slice3-kill-search.md`: §0, §2,
§3, §4, §5, §6, §7, §8, §9 (all of it, in particular item 4), §11, §12 "Akış (K3...)", §17 "K3". The note is in Turkish; this prompt is the
binding English scope. Where the code differs from what this prompt says, report it. Patterns to copy: L5's `ResearchFlow._lineage_links`,
`_lineage_send_gate`, `_send_through_limiter` and the opt-in `_model_step` hooks (`max_message_chars`, `resend_guard`, `send_gate`),
`workflow/lineage/run.py` (frozen plan in `runs.target_json`, preview fingerprint, `request_run`, replay check), L6's API routes and error
mapping in `api/app.py`, discovery's search request and payload file writing (`_send_search`, `_record_search`), and K1's `CandidateStore`
(`workflow/candidates/store.py`) and K2's contracts (`contracts.CANDIDATE_TASKS`, `_check_candidate_target`, `claim_assessment_evidence`,
`tests/test_candidate_contract.py` for hand-built `candidate_target` values that pass the checks).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model call, no real provider request, no network, no measurement: the fake adapter,
mocked `httpx` transports and synthetic fixtures only.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web work (`apps/web` is not touched), no method or contract change (`skill_package_hash` stays
`sha256:8e1e4a8453a286ac9da8628dd095dd7796f3a49ae374d7930cb3ef06c546ee76`), no migration (if one proves unavoidable, stop and report).
`docs/decisions.md` (D146) and this file's comment line are written by the orchestrator, not by you.

## Why

K1 built storage and pure computation, K2 the contracts and the road a candidate model step travels. K3 joins them with the database and the
network: it builds a `candidate_target` from stored rows, runs the two new run kinds (`claim_decomposition`, `kill_search`) end to end with a
frozen, durable, resumable record, and exposes them through the API so K4 can build the screen. K3 builds no screen and makes no real call.
The research's own corpus, selections, discovery counts and `selection_revision` must stay byte-for-byte unchanged by anything K3 runs.

The work has **two internal acceptance steps inside one batch and one commit**: **Part A (flow, model and provider side)** and **Part B (API)**.
You are told which part to do in each call; after Part A the focused tests must be green before Part B starts.

## What is and is not in code (checked on 58676f1)

- In code: the K1 migration `0060` (kinds `claim_decomposition` and `kill_search`, stage `candidate` already allowed), `CandidateStore`
  (`open_from_gap`, `open_from_owner_text`, `add_version(expected_version, idempotency_key)`, `start_kill_search`, `record_query`,
  `query_records`, `record_hits`, `publish_assessment`, `finish_kill_search`, `set_kill_search_state`, `record_owner_decision`,
  `candidate_status`, trash/restore, readers `candidate(s)`, `version(s)`, `searches`, `queries`, `hits`, `cells`, `evidence`), `status.derive_status`,
  `hits.merge_and_cut`, `terms.block_vocabulary` and `terms.compile_queries`; K2's schemas, `_check_candidate_target`, `_check_claim_decomposition`,
  `_check_claim_assessment`, `claim_assessment_evidence`, handles, `HANDLE_TASKS`, the `candidate_target` parameter of `_step_input` and
  `_model_step`; `_model_step` hooks `max_message_chars`, `resend_guard`, `send_gate`, `budget_short="skip"`; `ModelCallLimiter`;
  `Store.create_run` (one active run per research; global `idempotency_key` replay).
- Not in code: any builder of a `candidate_target`, any `claim_decomposition` or `kill_search` dispatch (`ResearchFlow.execute` falls through to
  `_table_columns` for an unknown kind: **dangerous, close it in Part A**), the stage mapping for the two kinds in `create_run` (it falls back to
  `extraction`), any route, any provider-request counting for kill-search, any candidate-scoped evidence reader, `Connector` has no per-search request count
  (PubMed sends two HTTP requests per search: ESearch then EFetch; every other connector one). Check, do not assume.

## Decisions (already taken; do not reopen)

### Shared vocabulary and constants (`workflow/candidates/run.py`, pure, no flow import)

- Constants: `KILL_QUERIES = 6` (logical provider queries), `KILL_RECORDS = 20` (records per query), `KILL_KEEP = 8` (works assessed),
  `MAX_MESSAGE_CHARS = 48_000`, `BASIS_ITEMS = 24`, `BASIS_TEXT_CHARS = 1_500`, `ABSTRACT_CHARS = 2_500`, `PAGE_PASSAGES = 6`,
  `PAGE_TEXT_CHARS = 4_000`.
- **Model ceiling, computed from the constants, never a literal**: `attempts(task) = (1 + schema_repairs(task)) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)`
  = 6 per step today. Decomposition run `max_model_calls = attempts("claim_decomposition")` = 6. Kill-search run
  `max_model_calls = attempts("kill_search_query") + KILL_KEEP * attempts("claim_assessment")` = 6 + 48 = 54. Both runs together 60. A test asserts
  6, 54 and 60 and that they follow from the constants. The ceiling is checked before **every** send (`_model_step` already does for the loop,
  repair included; pass `resend_guard` so a rate-limit resend inside `_call_adapter` is checked too, and a resumed run keeps its counter: resume
  never renews it). A timeout resend is not enabled (K2 left candidate tasks out of `TIMEOUT_RETRIED_TASKS`; do not change that).
- **Transport ceiling** (separate from the model ceiling, shown in the preview and frozen): add `requests_per_search: int = 1` to `Connector`
  in `providers/registry.py` (the only change there; PubMed = 2, with a comment naming ESearch and EFetch). For a connector, the HTTP requests
  one logical query may cost is `requests_per_search * (1 + MAX_RATE_LIMIT_RETRIES)` per attempt, and an attempt is repeated at most
  `MAX_TRANSIENT_NETWORK_RETRIES` times after a `before_send` failure (as `_send_search` does): `per_query(connector) = requests_per_search *
  (1 + MAX_RATE_LIMIT_RETRIES) * (1 + MAX_TRANSIENT_NETWORK_RETRIES)`. `max_provider_requests` of the kill-search run = the sum of `per_query` over
  the (at most `KILL_QUERIES`) eligible providers of the preview; the frozen record lists each provider's `requests_per_search` and the two retry
  constants. A connector whose request count cannot be bounded is not eligible (none exists today; the test enumerates all connectors and
  asserts the field is set and, for PubMed, equals what a mocked transport really receives).
- **Eligible providers** (preview and run): the research scope's providers passed through `registry.search_providers(scope["providers"],
  scope.get("search_workflow"))`, dropping a connector whose `access_mode()` is `not_configured` (a key removed since the scope was set), in scope
  order, at most `KILL_QUERIES`. None eligible: the preview and the start request answer 422 `no_searchable_provider`.
- **Reading depth and shown passages** (pure function, tested): for a source version, from `Store.passages_for`: the abstract passage if it has
  non-blank text (text cut to `ABSTRACT_CHARS`), then at most `PAGE_PASSAGES` `pdf_page` passages with non-blank text in page order (each cut to
  `PAGE_TEXT_CHARS`); other kinds are ignored; depth `stored_passages` if any page passage is shown, else `abstract` if the abstract is shown,
  else `metadata_only`. The cut text is what the StepInput carries (so `locate_anchor` runs against exactly what the model saw). If the real handle
  message would exceed `MAX_MESSAGE_CHARS`, drop trailing page passages until it fits; the abstract always stays; if the abstract alone does not fit,
  the hit stays unread and the summary says `message_too_large` (no send).
- **Frozen shown passages**: before the first assessment the flow writes a plan step (`kill_search_plan`) whose output lists, per kept hit, the
  reading depth and the shown passage ids with the sha256 of each shown text; `record_hits` takes its depths from that plan; a resumed run reuses
  the stored plan (and the stored hits), re-reads the passages by id. **If an assessment step of that hit already succeeded, its stored StepInput
  (`step_input_id` of the stored output) is what is published from, before any live passage check.** Otherwise, if any frozen passage of the hit no longer resolves among
  `passages_for` or its text hash changed, the hit is published whole as `insufficient_access` (never a partly different text under the frozen
  reading depth, which is immutable in the table; note that such a hit keeps its frozen depth beside the state, and say so in the summary). Order of writes: plan step first, then `record_hits`
  (a crash between them is recovered by reusing the plan; a search whose hits are already recorded skips the call).

### Part A: the flow

1. **Dispatch and stage.** `ResearchFlow.execute` gets explicit branches for the two kinds (placed before the `else`); the unknown-kind fall-through
   must no longer be reachable by them (a test proves neither kind runs `_table_columns`). `Store.create_run` stage mapping: both kinds -> `candidate`.
   `app.py`'s run-control cancel path keeps interrupting adapters for these two kinds (the calls are sequential; write that in a comment, §9 item 3).
2. **`claim_decomposition` run.** Request (store-level helper, used by the API): refuses a trashed candidate, a candidate whose `current_version` is
   not 0 (a decomposition is the only model formulation and human edit is the revision path; Q9: no automatic reformulation) with `RevisionConflict`;
   `create_run(research_id, "claim_decomposition", {"max_model_calls": attempts("claim_decomposition"), "max_provider_requests": 0}, key, target)`, `target = {"candidate_id",
   "expected_version": 0}`. **Replay lookup comes first:** with a key, find the run by the scoped key (`f"decompose:{research_id}:{candidate_id}:{key}"`) before any current-state
   check; a found run must match research, candidate and kind or the request is a 409, and is returned as is even though the candidate now has a version (a
   successful decomposition's replay must not turn into the `current_version != 0` refusal). Only a new request checks `current_version`, trashed and the
   active-run rule (`create_run` itself verifies no content). The flow (`_claim_decomposition`): checkpoint, load the candidate (trashed or gone: fail `candidate_unavailable`),
   build the target and run one `_model_step` (`operation_key "decompose"`, `limiter=self.deps.limiter`, `resend_guard`, `send_gate`,
   `max_message_chars`, and **`attempt_record`** with a minimal record such as `lambda payload: {"send_record": {"task": "claim_decomposition"}}`, because
   that hook is what makes `_model_step` rebuild the repair history from stored sessions on resume; without it a pause or crash between an invalid first
   answer and its repair would open a fresh first call and a fresh repair, breaking the one-repair rule), publish **inside one transaction that first re-checks, with no await between the check and the write,** that the run is `running`, the research's scope revision is still the run's, and the
   candidate is not trashed (`_candidate_send_gate`, the L5 pattern; a pause, cancel or scope change that arrived during the call publishes nothing and stops the run) through `CandidateStore.add_version(..., origin="model_decomposition", step_input_id=<output["step_input_id"]>,
   expected_version=0, idempotency_key=f"decompose:{run_id}")`. An invalid step output or a refused publication (`RevisionConflict` because the owner
   edited meanwhile, `InvalidCandidateInput`) fails the run with a code (`invalid_model_output` is already the step's; use `candidate_version_changed`
   and `candidate_publication_failed`), writes no version, and never retries. A stored succeeded step is reused on resume (publication is idempotent).
3. **Decomposition `candidate_target`** (built by a pure function in `candidates/run.py`, validated by `check_step_input` in `_model_step`):
   `candidate_id`, `origin`, `gap_kind` (null for `owner_text`), `origin_text` = the candidate's `origin_text`, `version` null, `assessed_source_id` null,
   `basis` from the stored `origin_basis_view_json` in this order: cells (`kind "cell"`, `text` the frozen view text, `passage_id` null), passages
   (`kind "passage"`, `passage_id` = the id, included only if that id is among `Store.passages_for(source_version_id)` of its source, text = the live
   passage text cut to `BASIS_TEXT_CHARS`), claims (`kind "claim"`, text, null id); an item the view marks `missing`, a passage that is no longer current and
   an item beyond `BASIS_ITEMS` are omitted and **counted** in the run's summary step (never silently); a blank text is omitted too. Empty for `owner_text`.
   `sources` = the basis passages' sources, `passages` = those passages (rows as `_step_input` expects), nothing else. If the real message exceeds
   `MAX_MESSAGE_CHARS`, drop trailing basis items until it fits, counting them.
4. **`kill_search` run request and plan** (pure `KillSearchPlanner` in `candidates/run.py`, like `LineagePlanner`; the flow does not import the API):
   `preview(research_id, candidate_id)` for the candidate's **current version** (refuse: no version -> 422 `candidate_not_decomposed`; trashed ->
   409) returns the frozen plan: `candidate_id`, `candidate_version_id`, `version`, `scope_revision`, `providers`, `model` (the `step_model` triples of
   `kill_search_query` and `claim_assessment`), `budget` (`max_model_calls` 54, `max_provider_requests`, plus the per-step breakdown), `transport`
   (per provider `requests_per_search`, `rate_limit_retries`, `transient_attempts`, `per_query`, and the total), the limits (6 queries, 20 records,
   8 works), `skill_package_hash`, `plan_version`, and `preview_fingerprint` (sha256 of the canonical JSON of everything above that the model or
   the network will see; no timestamps or ids of runs). `request_run(research_id, candidate_id, preview_fingerprint, idempotency_key)`:
   **replay lookup first**: with a key, find the run by the scoped key before recomputing anything; it must belong to this research, candidate and kind and its stored
   `target["preview_fingerprint"]` must equal the request's `preview_fingerprint` (else 409); it is returned as is even if the candidate was edited since. A new request recomputes the plan from
   the current version, answers 409 on a fingerprint mismatch, then `create_run(research_id, "kill_search", budget, key, plan)` with the key
   `f"killsearch:{research_id}:{candidate_id}:{idempotency_key}"` when given; (the replay rule above). The plan is stored
   in `runs.target_json` and is the single source of the frozen `selection` below.
5. **`_kill_search` flow** (all steps keyed by `operation_key`, every stored success reused on resume, checkpoint/send-gate between steps; any pause,
   cancel or newer scope revision stops with `RunStopped` as in L5; no write is made after a stop):
   a. at start, if a search exists for the run: `paused` -> `set_kill_search_state(running)`; already `running` -> nothing; **terminal** (the crash window
      after `finish_kill_search("completed")` and before the run completed) -> skip every step and fall to the run's normal completion, never re-open the
      search (K1 refuses it); a terminal `failed` search (crash after the search was finished and before the run was) is carried to the run: fail the run with the exact `failure_code` stored in the summary step
      (`transport_budget`, `no_query_compiled`, `candidate_evidence_unlocated`, `search_failed`), never re-open the search; **every path that finishes a search `failed` must write the summary step with its
      `failure_code` first**, and the normal-completion branch applies only when the search outcome is `completed`; a `stopped` search belongs to a cancelled run and does nothing;
   b. **terminal steps are never re-sent.** For all three candidate tasks, before calling `_model_step`, look at the stored step: `succeeded` -> use its output;
      `failed` with `invalid_model_output` or `message_too_large` -> rebuild the terminal result from the stored step (L5's `call()` does this at `flow.py:4548`; the stored output of a terminal
      invalid step carries no `invalid` flag, so the caller rebuilds it) and **do not send again** (without this, history rebuilt by `attempt_record` could send a third call). For the decomposition
      and the terms step a terminal invalid result fails the run (`invalid_model_output`, `query_terms_invalid`); for an assessment it leaves the hit pending as below. The terms step
      uses the **same hook set as every other candidate step** (`limiter`, `resend_guard`, `send_gate`, `max_message_chars`, `attempt_record`) and gets the same test.
   b2. **terms**: build `kill_search_query` target (`version` set, `origin_text` null, `basis` empty, no sources, no passages; `gap_kind` and `origin` copied),
      one `_model_step` (`operation_key "query_terms"`); the result's chosen terms go to `terms.block_vocabulary` (an `InvalidTerms` fails the run
      `query_terms_invalid`), then `terms.compile_queries(vocabulary, plan providers, KILL_QUERIES)`;
   (A failure before the freeze, whether an invalid or failed terms step, `InvalidTerms` or a connection error, means **the search did not start**: no search
   record is written, so the candidate's status stays what it was (`not_run` or the earlier result); the failed run and its code are visible in the card's `runs` list below.)
   c. **freeze**: `CandidateStore.start_kill_search(research_id, candidate_version_id, run_id, query_block=<the model's four blocks, backups
      included>, rendered_queries=<compiled list with dropped_terms, endpoint and sort>, skipped_terms=<terms the compiler dropped>, selection=<the
      plan's frozen model, providers, budget and transport>)`. On a resumed run read the frozen row back (add a small additive
      `CandidateStore.search_for_run(run_id)`), never recompile. If nothing compiled, freeze an empty list, write the summary step with `failure_code "no_query_compiled"`, finish the search `failed`, and fail the
      run `no_query_compiled` (a search that was attempted and read nothing: status `undecided`, K1's rule);
   d. **provider searches**, one logical query per rendered query, in order, position 1..n, step `search:{position}` of kind
      `provider_search:{provider}`; **skip a position already recorded in `kill_search_queries`** (a recorded `failed` or `outcome_unknown` query is
      never re-sent); a step left `outcome_unknown` by worker recovery with no recorded query row is recorded as `outcome_unknown` with no records.
      The request is `connector.search(self.deps.http, text, KILL_RECORDS, connector.api_key(), settings.contact_email, **endpoint_options(query))`
      with **no cursor, no paging, no count probe, no enrichment** (do not reuse `_send_search`: it drops `endpoint_options` without a page; write a
      small `_kill_search_request`). Retry only a `before_send` failure, at most `MAX_TRANSIENT_NETWORK_RETRIES` times with the existing backoff,
      stop-aware. **Transport counting is a durable reservation made before every attempt:** with `reserve = requests_per_search * (1 + MAX_RATE_LIMIT_RETRIES)`,
      the attempt may start only if `usage.provider_requests + reserve <= max_provider_requests`; the flow then writes `add_usage(run_id,
      "provider_requests", reserve)` **before** the call and never refunds it (an uncertain delivery keeps its reservation), so a crash between the call and any later
      write cannot lose spent requests. If the reservation does not fit, the query is recorded `failed` with `error_code "transport_budget"` and not sent,
      and **the search's final outcome is `failed`, not `completed`** (the terminalisation happens at the end, see the finishing order below, never at the refusal) (K1's status code would turn one successful zero-result query plus refused queries into
      `open`; a `failed` search is `undecided`/`search_incomplete` unless a published `closed` finding already exists); the summary names the budget as the reason. Payload files as
      `_record_search` writes them (`payloads_dir/<step id>.json`, sha256), passed to `record_query` (also for empty and failed answers). A failed
      query is recorded and the others go on (D18). **Mapping of an answer to the recorded status:** `completed` and `zero_results` -> `succeeded`; any non-success answer whose
      `delivery_class` is `after_send_unknown` (timeout and some HTTP errors, `providers/common.py`) -> `outcome_unknown` with no records and the outcome status as `error_code` (as discovery does at
      `flow.py:2082`; K1 derives `query_outcome_unknown`, which keeps one successful zero-result query from turning into `open`); every other failure -> `failed`.
      A transport refusal is recorded durably on its query (`failed`, `transport_budget`); the search stays **non-terminal** (this is about the search record, not the candidate status `open`) until the final writes below (K1 refuses writes to a terminal search),
      so the remaining queries, the merge and the assessments still run on what was read. Never call `record_search`, `add_search_run`, `add_to_corpus`, `link_records` (a test asserts it);
   e. **merge**: when every position is terminal, if at least one query `succeeded`: `merged = hits.merge_and_cut(cs.query_records(kls_id), keep=8)`
      (read the records back from the store, K1 leftover), write the plan step (decision above), `record_hits(kls_id, merged, depths)` **only when `hits_recorded` is not yet set** (K1's `record_hits` refuses a
      second call with `RevisionConflict`; on resume read the stored hits instead). Test both crash windows separately: plan written but hits not, and hits recorded but the run not
      advanced. With no succeeded query write neither plan nor hits;
   f. **assessment**, sequential, kept hits in rank order: a hit already published (`assessment_state != pending`) is skipped; `metadata_only` (or no
      passage left) -> `publish_assessment(kill_search_id, svid, assessment_state="insufficient_access")`, nothing sent to the model; otherwise build the target and call `_model_step`
      (`operation_key f"assess:{source_version_id}"`, `source_ids=[svid]`, `passage_rows` = the shown passages, `budget_short="skip"`,
      `limiter=self.deps.limiter`, `resend_guard`, `send_gate`, `max_message_chars`, `attempt_record` as in item 2, same reason). A model step left
      `outcome_unknown` is not retried by the worker; a **manual** resume sends it once more, counted against the ceiling (L5's accepted behavior; §9's
      "not retried" means no automatic retry). A provider query left `outcome_unknown` is never re-sent (recorded, K1 derives `query_outcome_unknown`). Publication of a **valid** output is preceded by the same synchronous re-check of run `running`, scope and candidate (no await between check and write), and goes through
      `CandidateStore.publish_assessment(... assessment_state="assessed", work_relevance, states_whole_claim, note=<nearest_match_summary>,
      step_input_id, cells=[{element_id (the resolved real `ele_` id), relation, condition_alignment, note, quotes}], whole_claim_quotes)` where every
      quote is produced **only** by `contracts.claim_assessment_evidence(stored_step_input_payload, item)`; an unexpected `None` from it stops publishing for the
      whole search: write the summary step with `failure_code "candidate_evidence_unlocated"`, finish the search `failed` and fail the run `candidate_evidence_unlocated` (it cannot happen after validation, so it fails closed). Read the stored
      StepInput with `store.step_input_payload(output["step_input_id"])`. An invalid output after the one repair, a `message_too_large`, and a
      `not_reached` (budget) result leave the hit `pending` (do not publish, do not write `not_assessed_budget` for them: K1 derives
      `not_assessed_budget` for a pending hit of a finished search); the reason is recorded in the summary below. A budget that runs out ends the loop
      early, the rest stay pending;
   g. **finish**: write the `kill_search_summary` step (counts, per-hit outcome: `assessed`, `insufficient_access`, `invalid_output`,
      `message_too_large`, `not_reached_budget`, the omitted counts, the transport and model usage), then `finish_kill_search("completed")`; **if any query was refused for transport budget, the order is: summary step (it names the reason), `finish_kill_search("failed")`, then the run is failed
      with `transport_budget`** (a crash between the last two is recovered by the terminal-`failed` resume branch of item a). The run
      completes through the existing `execute` tail (not when step g finished the search `failed`). The code never writes or implies a status string: status is only `candidate_status` computed on read.
6. **Search outcome follows the run.** Add `CandidateStore.sync_search_outcome(run_id)` (additive, idempotent): maps the run's status to the search
   `outcome` (`queued`/`running`/`pause_requested`/`paused` -> `running` while executing or `paused` when paused; `cancelled` -> `stopped`; `failed` -> `failed`;
   `completed` -> leaves the already-written `completed`), never moving a terminal search. Call it (i) in `ResearchFlow.execute` for a `kill_search` run in a
   `finally` (so pause, cancel, scope revision and failure are reflected), (ii) in `app.py`'s run control after pause, resume, cancel and
   at the end of `fail` paths that happen outside the flow, (iii) before computing a candidate's status on every read endpoint, for the candidate's
   searches (this covers worker recovery marking a run `paused` after a restart). The orchestrator accepts that a read endpoint performs this idempotent write; say so
   in a comment and test it.
7. **Resume guards.** `resume` of **any** run kind (the shared resume branch in `control_run`) is refused with 409 while another run of the research is active
   (`queued`, `running`, `pause_requested`), so a paused `answer` or `lineage_links` run cannot become active beside a running candidate run either (a small `Store`
   helper; test both directions; if an existing test relies on two active runs, report it instead of weakening the rule). A resume never resets `usage`. A new `kill_search` request is refused (409) while
   the same candidate has a paused kill-search or decomposition run (resume or cancel it first, like L5's paused-lineage rule).
8. **Isolation.** A test snapshots, before and after a full kill-search through the real flow: `corpus_memberships`, `candidates`, `search_runs`,
   selections, the research's `selection_revision`, discovery counts, `run_steps` of other runs, and asserts equality; and asserts `record_search`,
   `add_search_run`, `add_to_corpus` and `link_records` are never called (monkeypatch them to raise).
9. **Candidate-scoped evidence reader** (pure read model in `candidates/run.py`, used by Part B): for a search of this research and one of its **kept**
   hits, return the source's identity (title, year, venue, DOI, version label) and the text the model **really received**, taken from the stored
   StepInput of the hit's assessment (`step_input_id` -> `passages` of the payload, with each passage's locator kind and text) plus the stored
   quotes; a kept hit with no assessment (`pending`, `insufficient_access`) returns identity only and an empty passage list; a cut hit, a hit of another
   search or research, and an unknown id raise `NotFound`. It never calls `Store.passage_view` and does not read `corpus_memberships`.

### Part B: the API (`api/app.py`, routes under `/api/researches/{research_id}/candidates`)

All mutating routes use the existing CSRF/Origin machinery; research and candidate mismatch is 404; `InvalidCandidateInput` maps to 422 (new exception
handler, like `InvalidLineageInput`); `RevisionConflict` is already 409. Pydantic bodies are closed (`extra="forbid"`), strings bounded, `expected_version`
strict integers. Use `Idempotency-Key` (max 200) where noted, always passed to the store in a research-and-candidate-scoped form
(`f"{research_id}:{candidate_id}:{key}"`; for opening, `f"{research_id}:{key}"`), so a key can never replay across researches.

- `POST .../candidates` (201): body `{"origin": "owner_text", "text"}` (1 to 2000) or `{"origin": "report_gap", "report_id", "gap_row_id"}`; returns the card.
  `Idempotency-Key` applies to `owner_text` (the store binds it to the content); a `report_gap` replay is already idempotent by fingerprint.
- `GET .../candidates` (the Report VI row binding): per candidate `id`, `origin`, `origin_report_id`, `origin_gap_row_id`, `gap_kind`, `origin_changed`,
  `current_version`, `trashed_at`, the current version's claim statement (null before decomposition), the computed status (`status`, `reason`) of the current
  version and the owner's last decision beside it, and the active run id, if any. Trashed candidates are not listed. Report data is not read or changed.
- `GET .../candidates/{candidate_id}`: the card: candidate fields (including the "owner's proposal, not literature supported" fact as `origin`), every
  version with its elements, the current version id, owner decisions of the current version, its searches (id, run id, outcome, counts, created time) with the
  status object (`candidate_status`: `computed`, `previous`, `owner`), the active run, `runs` (the candidate's last five `claim_decomposition`/`kill_search` runs: id, kind, status, pause reason or error code), and the two budgets: `decompose_budget` (6 model attempts, 0 provider
  requests) and nothing for kill-search (that has its own plan route). Runs `sync_search_outcome` first. Before a version exists `current_version_id` and `status` are `null` (there is no version id to compute for).
- `POST .../candidates/{candidate_id}/versions` (201): human edit: `{claim_statement, conditions, elements: [{text, kind}], nearest_simple_explanation,
  critical_assumption, validation_plan, expected_version}`, origin `human_edit`, `Idempotency-Key`; returns the card. Version-protected by `expected_version`.
- `POST .../candidates/{candidate_id}/decompose` (202, `Idempotency-Key`): Part A's request; wakes the worker; returns the run. Replay returns the original
  run and 409 on content mismatch.
- `GET .../candidates/{candidate_id}/kill-search/plan`: the preview (Part A item 4). `POST .../kill-search` (202, `Idempotency-Key`): body
  `{preview_fingerprint}` (64 hex); wakes the worker; returns the run.
- `GET .../candidates/{candidate_id}/kill-searches/{kill_search_id}`: the matrix view for one search: search row (outcome, frozen query block, rendered
  queries, skipped terms, selection), queries (provider, text, status, record count, error code), hit counts (`found`, `kept`, `rank_cut`, `duplicates`),
  kept hits (rank, source identity, reading depth, assessment state, relevance, `states_whole_claim`, note), cells grouped by hit and element, evidence
  quotes, the summary step's output, and `search_status`: the status derived **for this search** (add an additive public `CandidateStore.search_status(kill_search_id)` over the private derivation), with
  `candidate_version_id`, `version`, `kill_search_id` and `is_latest_search_of_version` so a historical matrix is never shown beside the latest search's status. Sources and quotes are data; no text is invented.
- `GET .../candidates/{candidate_id}/kill-searches/{kill_search_id}/hits/{source_version_id}`: the candidate-scoped evidence reader (Part A item 9).
- `POST .../candidates/{candidate_id}/versions/{version_id}/owner-decision` (201): `{status, reason}`, status one of the five, reason required and
  non-blank after strip (422 otherwise); returns the card. No `Idempotency-Key` (the record is append-only; say so).
- No trash/restore route, no list-of-searches route beyond the card, no report integration, no web change.
- Run control: nothing new except Part A items 6 and 7.

## Limits (do not exceed)

No PDF acquisition, no full-text fetch, no citation expansion, no enrichment or paging of kill-search queries, no change to `workflow/report/*`,
`report_*`, `workflow/lineage/*`, discovery, the methods package or contracts. Do not make any hit enter the research corpus. Do not write
`report_gaps`. Do not invent a status in prose; a status is computed only by K1's derivation, reached through the two public readers `CandidateStore.candidate_status` (latest search of a version) and
the additive `CandidateStore.search_status` (one given search), which both use the same private `_derive`.

## Files allowed

`backend/deixis/workflow/candidates/run.py` (new), `backend/deixis/workflow/candidates/store.py` (additive methods only: `search_for_run`,
`sync_search_outcome`, `search_status`, small readers; no change to existing behavior), `backend/deixis/workflow/flow.py`, `backend/deixis/workflow/store.py` (stage
mapping, the resume helper), `backend/deixis/api/app.py`, `backend/deixis/providers/registry.py` (`requests_per_search` only),
`tests/test_candidate_run.py` (new, model- and network-free parts), `tests/test_candidate_flow.py` (new), `tests/test_candidate_api.py` (new), and an
existing test only if an enumeration now legitimately includes the new kinds or the connector field (say which and why). `tests/acceptance/fixture_server.py`
is **not** touched (left for K4 if the screen needs a scripted candidate scenario).

## Files NOT allowed

Everything else, in particular `contracts/*`, `methods/*`, `backend/deixis/domain/*`, `backend/deixis/storage/*`, `backend/deixis/workflow/report/*`,
`backend/deixis/workflow/lineage/*`, `apps/web/*`, `scripts/*`, `docs/*`, `TODO.md`, `.vscode/`.

## Tests to add (synthetic, no network, no real model; name each so its limit is readable)

`tests/test_candidate_run.py` (pure): constants and ceilings (`test_model_ceilings_follow_the_constants_6_54_60`), transport ceiling per provider
(including PubMed 2 and every connector having the field), `test_pubmed_really_sends_two_requests_per_search` (mocked transport counts), eligible
providers (scope order, not-configured dropped, sw filter, none -> 422 in API), reading depth and shown passages (abstract only, abstract plus pages, blank
text, cut lengths, six pages max, metadata only, drop trailing pages to fit, abstract alone too large), the decomposition target builder (gap with cells,
passages, claims; missing item omitted and counted; non-current passage omitted; 24 cap; owner_text empty), the plan fingerprint (stable, changes with
version, providers, model, skill hash), evidence reader read model.
`tests/test_candidate_flow.py` (fake adapter, mocked `httpx`, real `_model_step`; patterns from `tests/test_lineage_flow.py` and the discovery tests):
decomposition from a gap and from `owner_text` (version 1 stored, `step_input_id` set, nearest explanation null for the owner's sentence, run completed);
owner edit during the run -> `candidate_version_changed`, no version; decompose twice -> 409; kill-search end to end (terms, frozen record, queries, hits,
assessments, summary, status computed, run completed, search `completed`); frozen `selection`, `rendered_queries` and `skipped_terms` equal the plan and
are not recompiled on resume; D18 (one provider fails, others go on; all fail -> status `undecided`/`search_failed`; zero records -> `open` with the
depth and unread counts the status facts carry); transport ceiling (attempts refused with `transport_budget` once the ceiling would be crossed, retries
counted, PubMed counted as two); model ceiling (54 reached mid-assessment: the rest stay pending, no send past the ceiling, rate-limit resend blocked by
`resend_guard`, a resumed run does not renew it); metadata-only hit is never sent and is `insufficient_access`; invalid assessment after the one repair
leaves the hit pending and does not write `open`; `message_too_large` leaves it pending; quotes stored are the **located words** (the
"increases"/"decreases" regression through the flow) and an abstract quote has `evidence_kind abstract` and no passage id; (each of `no_query_compiled`, `candidate_evidence_unlocated` and `transport_budget`: search `failed`, run still `running`, crash, `Worker.recover` -> `paused`, resume -> the run fails with that exact code and the search is not re-opened); a monkeypatched `None` from
`claim_assessment_evidence` fails the run `candidate_evidence_unlocated`; pause between steps and resume (stored steps not re-sent, a recorded failed query
not re-sent, `outcome_unknown` step recorded as such), cancel (search `stopped`, hits already published stay), a new scope revision cancels the run, crash
recovery (`Worker.recover` then `sync_search_outcome` gives `paused`), resume refused with 409 while another run is active, second active run 409 on
request; isolation (Part A item 8); the two kinds never reach `_table_columns`; the research view still renders with a completed candidate run; the
stage is `candidate`; shown passages frozen (any frozen passage of an unassessed hit that disappears or whose text hash changed between runs makes the whole hit `insufficient_access`).
Further required flow tests (from the plan review): transport refusal after one successful zero-result query finishes the search `failed` and the status is `undecided`, not
`open`; the provider-request reservation survives a crash between call and any later write; invalid first answer, then pause or crash, then resume: exactly one repair in total, no fresh first call;
a model step left `outcome_unknown` is re-sent once by a manual resume and counted; crash after `record_hits` (hits recorded, run not advanced) and crash after the search was finished `completed` (run not completed) both resume cleanly;
pause, cancel and scope revision **during** the decomposition call and during an assessment call publish nothing; a stored succeeded assessment is published from its stored StepInput even if live passages changed;
a changed frozen passage makes the unassessed hit `insufficient_access`; resume of a paused `answer`/`lineage_links` run is refused (409) while a candidate run is active and the reverse.
`tests/test_candidate_api.py` (`TestClient` through `create_app` with injected adapters/http as the lineage API tests do): both open origins, replay of
an owner-text key and of a gap fingerprint, other research's candidate 404, list shape, card shape, human edit with `expected_version` conflict 409 and
replay, decompose request/replay/409/422 shapes, kill-search plan and start (fingerprint mismatch 409, replay, no version 422, no provider 422, trashed 409),
matrix view shape, evidence reader (kept hit text equals the stored StepInput passages; pending/insufficient hits identity only; cut hit 404; another
candidate's search 404; the corpus-membership state does not matter), owner decision (blank reason 422, appended beside the computed status, never changes it),
CSRF and Host/Origin behavior as the other mutating routes, `Idempotency-Key` never replaying across researches.
Every test that asserts a status uses `CandidateStore.candidate_status` or `search_status` (a test with two searches of different results asserts that the historical matrix returns its own status); none asserts a free-text state. State in comments that fake outputs prove plumbing,
not that a model reads a work correctly.

## Checks to run

1. Part A: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_candidate_run.py tests/test_candidate_flow.py tests/test_candidate_contract.py tests/test_candidate_store.py tests/test_candidate_status.py tests/test_lineage_flow.py -n 0`; Part B adds `tests/test_candidate_api.py` and the
   lineage and run-control API tests that exist.
2. Full `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (baseline on this checkout: 4,653 passed, 1 skipped; known parallel-load flakes that pass
   alone: `tests/test_audit.py::test_an_answered_work_stays_in_its_stratum...`, `tests/test_builtin_embedding_flow.py::test_a_new_scope_revision_during_a_429_wait_cancels_the_run`; rerun alone and say so). If a tool cannot run in your
   sandbox (loopback bind, process access) say so; an unrun check is not verified.
3. `git diff --check`; `git status --short` shows only the allowed files; `skill_package_hash` unchanged (print it).

## Report at the end

Files changed; test counts; every judgement call (list them, in particular: decomposition once only, empty-compile failing the run, pending hits for invalid output,
the read endpoint's idempotent sync write, the conservative transport counting, `requests_per_search`, frozen shown passages, basis omissions); what you could not find
or run; and what K4 must know (the exact response shapes, the status object, the per-hit outcome codes in the summary, the run kinds and stage, the idempotency key forms,
the fixture-server scenario K4 will need).
