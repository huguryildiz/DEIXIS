<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 5 high (kept is not read, an empty evidence answer is not 'never sent', empty assumption/plan are refused by the API, a paused decomposition does not block a second start, mandatory sentence broke its own forbidden-word scan) + 6 medium + 1 low, all folded in; r2: hazır değil, 2 high (the 'K works were read' sentence kept, 'FULL view.runs' is only the last 10 runs of the research and the card the last 5) + 5 medium + 1 low, folded in; r3: hazır (0 high); CODE-REVIEW: r1 1 high (single earlier-version search unreachable), r2 hazır (0 high) -->

# Task: P6 slice 3, batch K4 ("Arayuz"), the Candidates screen for claim candidates and the claim-specific kill-search

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-k4` (detached at `b206ad9`, main with D146). Read `AGENTS.md`,
`CLAUDE.md`, `.impeccable.md` (MANDATORY before touching `apps/web`; its rules bind every line of UI you write), `docs/decisions.md`
D143 to D146 and D137 (the slice 2 screen batch, the model for this one), and `docs/product/p6-slice3-kill-search.md`: §0 to §5 (rules and
status table), §9 item 4, §10 (the UI behaviour), §12 "Web (K4...)", §17 "K4". The note is in Turkish; this prompt is the binding English
scope. Read `docs/product/p6-slice2-l7-prompt.md` and the code it produced (`apps/web/src/lineage/*`, `apps/web/e2e/lineage.spec.ts`,
the `[lineage]` scenario in `tests/acceptance/fixture_server.py`): patterns to copy are the sub-view's refetch ordering guard, the inline
plan card, `LinkEditor`'s CAS and 409/422 handling, the mocked-JSON rendering test and the forbidden-word scan. Where the code differs from what
this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model call, no real provider request, no network: the fixture server's scripted
model, its mocked OpenAlex and synthetic data only.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. `apps/web/node_modules` in the worktree is an APFS clone made by the orchestrator (leave it; the
orchestrator removes it). The worktree has no `.venv`: for Playwright set
`DEIXIS_TEST_PYTHON=/Users/huguryildiz/Documents/GitHub/DEIXIS/.venv/bin/python` (the specs set `PYTHONPATH` to the worktree). If your
sandbox blocks loopback binds or process spawning, say so and continue; the orchestrator runs Playwright and takes the screenshots.
`docs/decisions.md` and this file's comment line are written by the orchestrator, not by you.

## Why

K1 to K3 built storage, contracts and the flow/API of claim candidates. Nothing shows them. K4 adds the screen: the sentence a researcher wants
to test becomes a candidate card, the card can be edited into versions, a bounded prior-art search can be started with its budget in view, and
its result is a matrix of works against the claim's elements with a computed status and the researcher's own decision beside it. The screen only
presents recorded state and never claims more than the contract supports: a stored quote is "located text", never "verified"; `open` means "no
match in the assessed subset" (not novelty, not a gap); a computed status and the owner's decision are two different things shown side by side;
no list is hidden or silently capped.

## What is and is not in code (checked on b206ad9)

- In code, do not change (except the one route below): the K3 API under `/api/researches/{id}/candidates` (see "Data" for the exact JSON);
  run kinds `claim_decomposition` and `kill_search` (stage `candidate`, `target.candidate_id`, `target.candidate_version_id`, a frozen
  `target` plan for `kill_search`); `POST /api/runs/{id}/{pause|resume|cancel}` (`api.controlRun`); events of type `candidate_changed`
  (written in the same transaction as every candidate change, so `view.last_event_id` moves for each); CSRF and `Idempotency-Key`.
- In code (web): `RunKind` in `api.ts` has no candidate kinds; `labels.ts::runKindLabels` has no entry for the candidate kinds (a lookup yields nothing) and `stepLabel` returns an unknown step kind raw; `ResearchPage` accepts `initialTab` values `sources|queue|waiting|evidence|artifacts|activity`; `EvidenceTable.tsx`
  has `TABLE_RUN_KINDS`, `TableRunLine` and the cancel `ConfirmDialog` (read how a run line with Pause, Resume and Cancel is built and reuse
  or lightly extract it); `PassageSheet.tsx` opens passages of the research's corpus only; `ReportView.tsx` renders section VI claims and has
  no gap data; `ResearchPage` passes `Transcript` an allowlist of run kinds (candidate runs stay out of it).
- Not in code: any candidate fetch function or type, any component under `apps/web/src/candidate/`, EN/TR copy, run-kind and step labels for
  the two kinds, a Candidates tab, "Investigate" on VI, a fixture scenario, `apps/web/e2e/candidate.spec.ts`, a way for the web to learn the
  `report_gaps` row ids of a report (the report view does not carry them: see "Report rows"). Check, do not assume.

## Data (K3's API, mirror it exactly; `dict[str, Any]` fields in `app.py` are described here from real responses)

All paths are under `/api/researches/{rid}`; every mutation sends `x-deixis-csrf` (the existing `request` helper does) and, where noted,
`Idempotency-Key: crypto.randomUUID()`.

- `GET /candidates` -> `CandidateListItem[]` (non-trashed candidates only; it carries NO `origin_text`): `{id, origin: 'owner_text'|'report_gap', origin_report_id, origin_gap_row_id, gap_kind, origin_changed,
  current_version, trashed_at, claim_statement|null, status: Computed|null, owner: OwnerDecision|null, active_run_id|null}`.
- `POST /candidates` (201, `Idempotency-Key`; body `{origin:'owner_text', text}` text 1..2000, or `{origin:'report_gap', report_id, gap_row_id}`)
  -> `CandidateCard`. A repeated gap open with the same row content returns the same candidate; a rewritten row opens a new one.
- `GET /candidates/{cid}` -> `CandidateCard`: `{id, research_id, origin, origin_report_id, origin_gap_row_id, gap_kind, origin_text, origin_basis,
  origin_basis_view: {} for owner_text, else {basis_cell_ids: ({id, text} | {id, missing: true})[], basis_passage_ids: ({id, text, source_version_id} | {id, missing: true})[], basis_claim_keys: ({id, text} | {id, missing: true})[]},
  origin_provenance: {} for an owner_text candidate, {origin:'code'|'model', section_id, step_input_id} for a gap, origin_fingerprint, origin_changed, current_version, trashed_at,
  created_at, versions: Version[], current_version_id|null, owner_decisions: OwnerDecision[], searches: SearchRef[],
  status: {computed: Computed, previous: Computed|null, owner: OwnerDecision|null} | null, active_run: RunRef|null, runs: RunRef[] (last five),
  decompose_budget: {max_model_calls: 6, max_provider_requests: 0}}`.
  `Version = {id, candidate_id, version, claim_statement, conditions: string[], nearest_simple_explanation: string|null, critical_assumption,
  validation_plan, origin: 'model_decomposition'|'human_edit', step_input_id, created_at, elements: {id, candidate_version_id, position, text,
  kind: 'mechanism'|'condition'|'outcome'|'parameter'}[]}`. `SearchRef = {id, candidate_version_id, run_id, outcome: 'running'|'paused'|'completed'|
  'failed'|'stopped', created_at, version, counts: {found, kept, rank_cut, duplicates}}`. `RunRef = {id, kind, status, pause_reason, error_code|null}`.
  `OwnerDecision = {id, candidate_version_id, status, reason, created_at}`.
  `Computed = {status: 'not_run'|'undecided'|'narrowed'|'closed'|'open', reason: string, reasons: string[], warnings: string[],
  facts: {found, kept, rank_cut, duplicates, assessed, unread, queries_total, queries_succeeded, queries_failed, queries_unknown,
  reading_depths: {abstract, stored_passages, metadata_only}}}`. Reason codes (K1 `status.py`): `not_searched`, `whole_claim_stated`,
  `partial_overlap`, `no_match_in_assessed_subset`, `search_running`, `search_paused`, `search_failed`, `search_incomplete`,
  `query_outcome_unknown`, `insufficient_access`, `not_assessed_budget`, `uncertain_relevance`, `uncertain_cell`, `unclear_alignment`,
  `unclassified`; warnings include `merge_missing` and `unmatched_shape:...`. Read `backend/deixis/workflow/candidates/status.py` and confirm.
- `POST /candidates/{cid}/versions` (201, `Idempotency-Key`; body `{claim_statement 1..4000, conditions[] (<=24, each 1..2000), elements[] (2..6,
  `{text 1..2000, kind}`), nearest_simple_explanation: string|null (<=4000, non-blank when given), critical_assumption (1..4000, NON-BLANK: the
  API refuses an empty one with a 422), validation_plan (1..4000, NON-BLANK likewise), expected_version: int >= 0}`) -> `CandidateCard`. `expected_version` is `card.current_version` (0 when no version exists yet); a stale
  value is a 409. Text containing NUL, only whitespace or unencodable characters is a 422 with a message.
- `POST /candidates/{cid}/decompose` (202, `Idempotency-Key`, no body) -> a run. 409 when another run is active; a candidate that already has a version is not decomposed again (409, read the 4xx and show its
  message). NOTE (verified defect of K3): `request_decomposition` has NO guard against a PAUSED candidate run (only queued, running and
  pause_requested runs block a start), while the kill-search planner refuses one with a 409. Fix it in this batch, narrowly (see "Backend
  exceptions"), and keep the screen's own disabling (item 11) so the user sees why.
- `GET /candidates/{cid}/kill-search/plan` -> the plan: `{candidate_id, candidate_version_id, version, scope_revision, providers: string[],
  model: {kill_search_query: [connection, model, effort|null], claim_assessment: [...]}, budget: {max_model_calls: 54, max_provider_requests,
  steps: {kill_search_query, claim_assessment, assessment_works}}, transport: {providers: {provider, requests_per_search, rate_limit_retries,
  transient_attempts, per_query}[], max_provider_requests}, limits: {queries: 6, records: 20, keep: 8, max_message_chars, basis_items,
  basis_text_chars, abstract_chars, page_passages, page_text_chars}, skill_package_hash, plan_version, preview_fingerprint}`. 422/409 with codes
  such as `candidate_not_decomposed`, `no_searchable_provider` (read `workflow/candidates/run.py` and the API tests for the exact detail strings).
- `POST /candidates/{cid}/kill-search` (202, `Idempotency-Key`; body `{preview_fingerprint}`) -> a run; 409 "plan changed" refetches the plan.
- `GET /candidates/{cid}/kill-searches/{kid}` -> `Matrix`: `{search: {id, candidate_version_id, run_id, outcome, found, kept, rank_cut, duplicates,
  hits_recorded, created_at, query_block: {setting: {kind, term, why}[], setting_backup: {term}[], task: ..., task_backup: ...},
  rendered_queries: {provider_id, query_text, rationale, dropped_terms: ...}[], skipped_terms: ..., selection: {model, providers, budget, transport} (the frozen part of the plan; it has no `limits` or `scope_revision`)},
  queries: {position, provider, query_text, status: 'succeeded'|'failed'|'outcome_unknown', record_count, error_code|null}[],
  counts: {found, kept, rank_cut, duplicates}, hits: Hit[] (KEPT works only, in rank order), cells: {[source_version_id]: {[element_id]:
  {id, kill_search_id, element_id, source_version_id, relation, condition_alignment|null, note}}}, evidence: Quote[], summary: {failure_code, counts, queries, hits: {source_version_id,
  reading_depth, outcome, reason, omitted}[], usage: {model_calls, provider_requests}, budget, frozen_reading_depth}|null,
  search_status: Computed (for THIS search), candidate_version_id, version, kill_search_id, is_latest_search_of_version}`.
  `Hit = {source_version_id, reading_depth: 'abstract'|'stored_passages'|'metadata_only', assessment_state: 'pending'|'assessed'|
  'insufficient_access'|'not_assessed_budget', work_relevance: 'unrelated'|'related'|'uncertain'|null, note, rank, states_whole_claim: boolean|null,
  source: {title, year, venue, doi, version_label}}`. Relations: `explicit_support`, `reasoned_inference`, `partial_match`,
  `no_match_in_supplied_text`, `uncertain`; alignment: `aligned`, `different_conditions`, `unclear`. `Quote = {id, kill_search_id,
  source_version_id, element_id|null, matrix_cell_id|null, evidence_kind: 'abstract'|'passage', passage_id|null, quote}`. Works that were cut
  by rank, and duplicates, are NOT listed by the API: only their counts are known. State that plainly; do not invent a list.
- `GET /candidates/{cid}/kill-searches/{kid}/hits/{svid}` -> `{source: {source_version_id, title, year, venue, doi, version_label},
  passages: {passage_id, source_id, text, reading_depth, locator: {kind, physical_page, printed_label}, abstract_origin, text_source}[]
  (EXACTLY the text the model received, from the stored StepInput; empty for a work never sent), quotes: Quote[]}`. 404 for a cut work.
- `POST /candidates/{cid}/versions/{vid}/owner-decision` (201, no Idempotency-Key by design; body `{status, reason 1..2000}`) -> `CandidateCard`.
  Append-only: it never changes the computed status and a later search does not delete it.
- Run controls: `api.controlRun(run.id, 'pause'|'resume'|'cancel')`. A resume is refused (409) while another run of the research is active.
- Candidate runs make the research's single active run: while one is active every other run-starting action of the page is already disabled
  by existing code (the page derives `active` from `view.runs[0]`, the newest run, which is where an active run always is); the Candidates screen disables its
  own start actions when ANY run of `view.runs` is queued, running or pause_requested and shows why; the backend 409 (a second active run) is shown
  in its own words if it still happens.

## Report rows (the one backend exception)

The plan puts "Investigate" on the section VI rows of a report. The report view (`GET .../reports/{id}`) does not return the `report_gaps` rows
or their ids, so the web cannot open a candidate from a row. Decision: add ONE additive, read-only route
`GET /api/researches/{research_id}/reports/{report_id}/gaps` returning `[{id, gap_id, kind, text}]` (the `report_gaps` rows of that report in
insertion order; `id` is the row id the candidate API wants as `gap_row_id`), implemented as a small function in `backend/deixis/workflow/views.py`
beside `report_view` (same research-ownership check, `NotFound` otherwise) and wired in `api/app.py`. Do NOT touch `report_view`'s output,
`workflow/report/*`, any `report_*` schema or any migration, and do not add other fields. Add `tests/test_report_gaps_view.py` (ownership 404 for
another research's report, order, empty list, exact keys, nothing else changes). `workflow/report/*` stays byte-for-byte unchanged. Report this
exception loudly in your final report as a judgement call that the main session may veto.

On the web: `ReportView` (`apps/web/src/report/ReportView.tsx`) gets, inside section VI only, one extra block after the section's own content:
heading "Aspects you can investigate" (sentence case), a one-line explanation ("Each row is an aspect the report recorded. Investigating one opens
a candidate card; nothing is searched until you start a search on the card."), then every recorded gap row as a list item (the rows exist whatever
the section's status; none is hidden): the kind in plain words (`stated_limitation` "stated limitation", `conflicting_evidence` "conflicting
evidence", `corpus_absence` "absent from the corpus read"; an unknown kind prints raw), the stored `text` byte for byte, the candidates already
opened from that row (matched by `origin_gap_row_id` against the candidate list; each as a control that opens the candidate, with its computed
status word and, when `origin_changed`, "(a later candidate was opened from this row)"), and an "Investigate" button (opens or returns the candidate
through `POST /candidates`, then navigates: close the report sheet, switch to the Candidates tab, select the card). When VI's `status` is not
`valid` the block starts with an attention-tone sentence "This section was not validated; the rows below are what the model proposed, not rows
that passed the report's checks." (Investigate stays available: it only copies the row's text into a card.) The block also carries the line "The
note above describes the report as it was written; a candidate's own search status is on its card." An empty list prints "No aspects were recorded
for this report." and the block stays visible; a fetch error shows the error card with Retry; the rows refetch when `view.last_event_id` moves.
Nothing else of the report changes: claims, citations, the existing VI fine print, copy and export are untouched (the existing report specs must
pass unchanged). "Investigate" is NOT disabled by an active run (opening a card starts nothing). A same-row re-open returns the same candidate only
while the row's content is unchanged; a rewritten row opens a new candidate (K1 behaviour; do not promise more).

## Backend exceptions (two, both narrow; report both loudly, the main session may veto either)

1. The read route for report rows (above).
2. **K3 defect fix.** `request_decomposition` (`workflow/candidates/run.py`) must refuse a start while a PAUSED `claim_decomposition` or `kill_search`
   run of the same candidate exists, with the same SQL and the same `RevisionConflict` text as `KillSearchPlanner.request_run` (409 through the
   existing handler), checked inside the same transaction after the idempotent replay and before `create_run`. Change nothing else in that file.
   Add `tests/test_candidate_decompose_guard.py`: a paused decomposition blocks a second decomposition and a kill-search start (the latter
   already refused) of the same candidate with 409, does not block another candidate's decomposition, replay of the original key still returns the
   original run, and a cancelled or completed run does not block.

## Decisions (already taken; do not reopen)

### Placement and structure

1. **Where.** A new research tab "Candidates" after "Evidence" (value `candidates`, a count pill with the number of non-trashed candidates,
   shown for every research), added to `ResearchPage`'s `initialTab` whitelist, the tab list and a `TabsContent`. The content is a new
   `apps/web/src/candidate/CandidatesView.tsx` with sub-components in `apps/web/src/candidate/` and a `candidate.css` imported beside the other
   feature CSS. `ResearchView.tsx` gets the smallest possible edits (tab, whitelist, props, the tab-bar chip of item 14, the report callback).
2. **Two states, one tab.** The tab shows either the **list** or one candidate's **detail**; selection is component state (not persisted), a
   "Candidates" back control returns to the list, and focus moves to the detail heading on open and back to the invoking row on return.
3. **One data owner.** `CandidatesView` fetches the list; the detail fetches the card and, for the selected search, the matrix. Mutations return
   the fresh card (replace the state, no second fetch). Refetch the list, the open card and the open matrix whenever `view.last_event_id` moves (a
   candidate change always writes an event), when a candidate run for this candidate leaves the active state, and on a "Refresh" control, with one
   ordering guard shared by reads and writes (copy L7's: a late read never overwrites a newer write). Read endpoints perform an idempotent sync
   write server-side; that is expected. No polling of its own.
4. **API client.** Add typed functions to `api.ts` (`candidates`, `openCandidate`, `candidate`, `editCandidate`, `decomposeCandidate`,
   `candidateKillSearchPlan`, `startCandidateKillSearch`, `candidateMatrix`, `candidateHit`, `candidateOwnerDecision`, `reportGaps`) and the
   types above, mirroring the JSON exactly (`RunTarget.table_id` is required today and candidate runs have none: adjust the type minimally (optional field or a union) so everything compiles without casts, and add the optional `candidate_id`/`candidate_version_id` and the frozen plan fields you read; add the two kinds to `RunKind`).
   Mutations send a fresh `Idempotency-Key` as the other mutations do (not owner-decision).

### Candidates list

5. Heading "Candidates" with one explanatory sentence ("A candidate is one claim you want to test against the literature. Nothing is searched until
   you start a search on a card.") and the "Add candidate" control. A real list (`<ul>`): each row is one button (keyboard focusable, the whole row
   opens the detail) with the claim statement (serif, as stored, clamped to three lines in the list because the detail shows it whole; a versionless row shows its origin text, which the list endpoint does not carry: fetch those few cards with `GET /candidates/{cid}` in parallel and show "Loading…" meanwhile), a plain line for the origin ("From a report
   row: stated limitation" / "Your proposal"), the version number or "No card yet", the computed status as a short text label with the owner's
   decision beside it when present ("You: closed"), and "Search running" text while `active_run_id` is set. A candidate with `trashed_at` is shown
   with "In the Trash" plain text and no actions (there is no trash UI in K4; do not add one). Empty list: a muted sentence that names the next
   action. "Add candidate": an inline form (not a dialog): one textarea (1..2000, counter; the card shows the text as the API returns it, trimmed), the line "Your sentence is stored with
   surrounding whitespace removed. It is your proposal, not a finding from the literature.", Save and Cancel; a 422 shows the backend message under the field and keeps
   the text; Save opens the new card.

### Candidate detail (top to bottom; every list the API returns is shown, none hidden or capped silently)

6. **Header.** Origin line: gap origin "Opened from a report row: <kind>" with the stored `origin_text` byte for byte; owner origin "Your proposal"
   plus a persistent plain notice (`Notice`, info tone) "This is your sentence, not a finding from the literature. The breakdown below and the
   search do not make it one." `origin_changed` true (the store sets it when a LATER candidate was opened from the same report row; it does not compare the live row): an
   attention-tone sentence "A later candidate was opened from the same report row; the row may have been rewritten. This card keeps the wording it
   was opened with." For gap origin a disclosure "What it was opened from" listing every `origin_basis_view` item
   (cell values, passage texts, claim texts byte for byte, an item with `missing: true` as "no longer available"); empty basis prints "None.".
7. **No version yet.** Two actions side by side: "Break the claim into testable parts" (decompose; shows the budget "at most N model calls, no
   provider requests" from `decompose_budget`, the research's model name with its connection icon as the table fill shows it, disabled with a
   visible reason while a run is active or while any run of THIS candidate is paused) and "Write the card myself" (opens the editor of item 9 prefilled with the origin text as the claim and
   empty elements; `expected_version` 0). No other state may pretend a card exists.
8. **Card body (the current version).** Version number and who wrote it ("model proposal" for `model_decomposition`, "your edit" for `human_edit`)
   with the date; claim statement (serif); conditions (list, "None." when empty); elements as an ordered list, each with its kind in words and its
   text; nearest simple explanation (`null` prints "None stated" with the line "The model could not name one from the records it was given, or you
   left it empty." for a model version and just "None stated" for a human one); critical assumption and validation plan (the API never stores them empty). Under the plan a fixed line: "A validation plan names what check would support, narrow or weaken the claim. It is not an experiment
   design." Earlier versions in a disclosure whose summary always shows the count ("Earlier versions (N)"), each rendered read-only with the same
   fields; a version with searches says so ("N searches ran on this version"). A model version carries the fixed line "Written by a model from the
   text above; its structure was checked by code, its scientific content was not."
9. **Editor** (a sheet in the style of `LinkEditor`/the column editor, focus moves in on open and back to the invoking button): fields for
   `claim_statement`, `conditions` (add/remove lines, <=24), `elements` (2..6 rows: kind select with the four kinds in words, text; add/remove with
   the 2 and 6 limits explained in text when reached), nearest simple explanation (a field plus "None" checkbox that sends `null`), critical
   assumption and validation plan (both REQUIRED non-blank in the form, with the reason shown, because the API refuses blank text with a 422),
   counters for the limits. Save sends `expected_version = card.current_version`. A saved edit is a new version
   ("Saved as version N. The searches of earlier versions stay with those versions."). 409: "This card changed since you opened it" with a
   "Reload" control that refetches and keeps the typed text; 422: the backend message under the form, typed text kept. The card shows what the API returns (the API trims surrounding whitespace of owner text and of decision reasons), so the screen says "saved" and shows the stored text, not the typed text.
10. **Search for prior art on this claim** (heading exactly this). Shown only when a version exists. A "Plan the search" button calls the plan
    endpoint and shows the plan as an inline confirmation card (not a native dialog): the version it searches ("version N only; results of other
    versions are not carried over"), providers (names through the existing provider labels with their icons, one line each with the
    requests-per-search from `transport`), the model for the two steps (name with connection icon), the limits in plain sentences (at most 6 queries
    of 20 records each, no paging; at most 8 works are read; reading is title, abstract and stored passages only, never full text), and two separate
    ceilings stated as such: "at most N model calls" (`budget.max_model_calls`) and "at most M provider requests" (`budget.max_provider_requests`),
    then "Start" and "Cancel". Start sends `preview_fingerprint` with a fresh key; a 409 shows the backend message and refetches the plan; a 422
    shows its message. While a candidate run is active the button is disabled with the reason ("A run is working on this research" /
    "Search running"). A plan that cannot be had (`candidate_not_decomposed`, `no_searchable_provider`) shows a fixed sentence per code and an
    unknown code prints raw. Nothing in this block says the search will find, cover or miss anything.
11. **Run line.** Which runs belong to the candidate is learned from three bounded sources, merged by run id: the research view's `view.runs` (the
    research's NEWEST 10 runs only), the card's `runs` (this candidate's newest 5; print "Showing the last 5 runs" when it has five) and the card's
    `searches` (a search whose `outcome` is `paused` names its run). None of them is a complete history and the screen never says it is; do not use
    only `view.runs[0]`. While such a run is active or paused, one line with the run state and controls matching what the API accepts: Pause for
    `queued`/`running` (not `pause_requested`), Resume for `paused`, Cancel for `queued`/`running`/`pause_requested`/`paused`; a failed or finished run
    shows its failure reason and `error_code` in words with NO controls. Cancel goes through the existing `ConfirmDialog` ("The run stops. Records
    already stored are kept. A cancelled run cannot be resumed."). Show the pause reason through `pauseReasonText` and one step timeline: terms
    (model) -> provider searches, one sub-line per stored query (provider icon and name, rendered query text, `succeeded`/`failed`/`outcome_unknown`
    in words, record count, error code in plain words) -> assessment ("n of k works assessed", from `summary.hits`/`hits`). Read the real step `kind`
    and `operation_key` strings of both runs in `flow.py`/`run.py` and give every one an entry in `labels.ts::stepLabel` (EN and TR); an unknown step
    must not fall back to an answer-run description. A resume the backend refuses shows its message. While a paused run of this candidate is known,
    "Break the claim into testable parts" and "Plan the search"/Start are disabled with the reason "A run of this candidate is paused: resume or
    cancel it first"; when the paused run is outside the three sources, the backend now refuses the start (409, both kinds) and its message is shown.
    If you reuse `TableRunLine`, make sure it never offers Cancel, Pause or Resume where the API refuses.
12. **Status block** (the computed status of the search being shown, from `search_status`, or `status.computed` for the latest): the status as a
    word ("Not searched", "Undecided", "Narrowed", "Closed", "Open") plus one plain sentence chosen by `reason` from a fixed map (EN and TR) and the
    facts as a compact line that keeps the counts apart (they answer different questions): found; kept for assessment (`kept`); assessed
    (`assessed`); not read (`unread`, which is the results ranked lower than the cut PLUS kept works whose assessment did not complete: say both
    parts, `rank_cut` and `kept - assessed`); duplicates merged; queries failed and queries of unknown outcome; reading depth counts ("abstract N,
    stored passages N, metadata only N"). Never write "read" for a work that is only kept. The reason sentences must be exact and modest, for
    example `open`: "No match was found among the {assessed} works that were assessed (of {found} results found; {unread} were not read). This says
    nothing about works that were not read." `closed`: "One assessed work states the whole claim under the same conditions; its quoted text is
    shown below. Whether the text supports the claim has not been checked." `narrowed`: "Partial overlap was recorded for the assessed works. This
    assessment did not establish that the whole claim is stated together under the same conditions." `undecided`: one sentence per reason
    (running, paused, every query failed, stopped early, a query's outcome unknown, a work could not be assessed for lack of text, a work's
    assessment did not complete, relevance or a cell uncertain, conditions unclear, unclassified) and ALL `reasons` listed, not only the first;
    `warnings` printed in plain text (unknown ones raw). Then the fixed note "Code derived this status from the matrix below. It is not a model
    verdict, and it says nothing about works that were not read." (Do not use the words of item 20 even in a negation.) `previous`, when present,
    is a plain line "Earlier search: <status>" and is not the status.
13. **Owner decision**, beside the status (the same block, side by side on desktop, stacked on 390 px): "Computed: closed · Yours: not recorded" style
    two-part line using the latest `owner` decision (`Yours: closed` with its reason and date), the sentence "Your decision is a note of your own.
    It is not independent evidence and does not change the computed status.", the full `owner_decisions` history of the current version as a list
    (newest first, reasons byte for byte, "None." when empty), and a "Record my decision" control: status select (the five values in words), a
    required reason (1..2000, counter), Save. A 422 shows its message and keeps the text. No edit or delete of a recorded decision exists.
14. **Run kinds in the shell.** Add the two kinds to `RunKind`, `runKindLabels` ("Claim breakdown" / "Prior-art search for a claim", EN and TR)
    and to the tab-bar logic of `ResearchPage`: while one of them is active or paused, the bar shows the same quiet `run-chip` the table runs
    use, linking to the Candidates tab, instead of the generic `run-strip` (their controls live on the card). `TABLE_RUN_KINDS` is NOT extended (that would route candidate runs to the Evidence tab); `ResearchPage`'s Transcript allowlist is NOT
    extended (candidate runs are not conversation turns); `BackgroundJobs.JOB_KINDS` is NOT extended (not PDF work). Justify both in the report.
    A run of these kinds must never be described anywhere as an answer run.

### Matrix

15. **Searches.** When the card has more than one search, a plain list "Searches" (newest first; version, date, outcome in words, found/kept) of
    controls that choose which matrix is shown (default: the latest search of the current version; a search of an older version is labelled "version
    N, not the current version"). The matrix status is the status of THAT search (`search_status`), with the "Earlier search" rule of item 12.
16. **Above the matrix** (always visible, in plain sentences): "Found F results in P provider searches; K works were kept for assessment, A of them were
    assessed; R results ranked lower were not read; D duplicates were merged." (stored counts; zero is printed as zero; `K - A` kept works whose
    assessment did not complete are named separately, never counted as read), the reading-depth line (a count of the kept works' frozen reading depth,
    NOT a count of completed readings), and the query list (a real
    list: provider icon and name, the rendered query text as stored, status in words, record count, error code in words, `dropped_terms` and
    `skipped_terms` printed in plain words when non-empty). The frozen terms the model wrote (`query_block`: setting and task terms, backup terms)
    in a disclosure "Search terms the model wrote". "Show the plan this search ran under" is not needed.
17. **The matrix itself.** One row per kept work, rank order as given, one column per element of THAT search's version (look the elements up in
    the card's `versions` by `candidate_version_id`). Desktop: a real `<table>` (`<th scope="row">` the work, `<th scope="col">` the element with
    its kind and text); at or below 760 px the same data stacks (each work a block, each element a labelled line; CSS only, no second DOM
    path that could drift). The work cell: rank, the title as a visible keyboard-reachable control that opens the evidence sheet (item 18), year
    and venue, the reading-depth `.ref-pill` with a text label ("abstract", "stored passages", "metadata only"), the assessment state in words
    ("assessed"; `insufficient_access` "assessment could not be completed: usable text was unavailable (no abstract or stored text, or the frozen text could no
    longer be read)"; say nothing about whether a send happened; `not_assessed_budget` "assessment did not complete"; `pending` "no published assessment"), and, where `summary.hits` carries the work's
    outcome and reason (`assessed`, `insufficient_access`, `invalid_output`, `message_too_large`, `not_reached_budget`, `pending`) and its
    `omitted` counts (`page_limit`, `message_size`), that exact outcome in words (never collapse `invalid_output` or `message_too_large` into a
    budget message; an unknown outcome prints raw), the work relevance in words ("unrelated", "related", "uncertain"), whether it states
    the whole claim ("states the whole claim: yes/no", only when assessed), and the model's `note` byte for byte labelled as the model's note.
    A cell prints the relation as TEXT (`explicit_support` "stated in the text", `reasoned_inference` "inferred from the text", `partial_match`
    "partly matched", `no_match_in_supplied_text` "no match in the text shown", `uncertain` "uncertain") and, for the three support relations,
    the alignment in words ("same conditions", "different conditions", "conditions unclear"); `uncertain`, `insufficient_access` and unclear
    alignment use the amber tone with an icon and text, never red, never colour alone; a work with no cells prints a single sentence naming the
    reason it has none. The cell's note byte for byte, labelled as the model's. Never merge relations into a score or a count of "matches".
18. **Evidence sheet** ("Show evidence" on a work, and the title control): a sheet in the existing sheet style, opened on top of the page, that
    shows the source header (key chip if the work has one, title, year, venue, DOI link chip, version label), the reading depth and the sentence
    "These are the exact passages the model was given. Nothing else of this work was read.", then every returned passage (locator caption from
    `locator`, its text), and the stored quotes: each as a serif blockquote with the element it was stored for ("For element: ..."), the relation
    and alignment words, and the locator caption "Located in the text shown to the model" (never "verified", never "supports"). Mark a quote inside
    its passage only when it can be located the way `PassageSheet`'s `HighlightedPassageText` does it (reuse or lightly export that component
    for it, narrowing its parameter to `Pick<Passage, 'text' | 'kind'>` (the two fields it reads) rather than filling a fake `Passage`; pass a `markLabel` suited to this context,
    for example "Text located for the stored quote"; do not write a second marking algorithm); a quote that cannot be located exactly is shown as a blockquote with "not marked: shown
    separately" and no guessed mark. A work whose evidence endpoint returns no passages (the endpoint returns passages only for an `assessed` hit) says exactly that and
    nothing more: "No assessed passages are stored for this work" with its assessment state and its `summary.hits` outcome in words; it must NOT
    claim that nothing was sent to the model (a `pending` hit may have been sent and its answer not published). A quote with `element_id` null is
    labelled "For the whole claim". The sheet ends with the fixed "Semantic support not checked." note (once). A 404 or other
    error shows the error card with Retry. Do not call `PassageSheet`: the passages are not in the research corpus and its routes would refuse them.
    Focus moves into the sheet and returns to the invoking control on close; Escape closes.

### Copy, labels, i18n

19. All UI strings go through `t()` with EN as the key and TR in `i18n.ts` (read how strings are added; Turkish is required for every new string,
    correct and natural). Fixed maps (statuses, reasons, relations, alignments, kinds, assessment states, reading depths, run reasons, plan
    refusals) live in `apps/web/src/candidate/labels.ts` with EN and TR; an unknown code prints raw in plain text, never hidden.
20. Forbidden in any string DEIXIS writes: "novel", "novelty", "original", "originality", "unique", "gap", "foundational", "verified" (for a
    quote or a status), "proof", "proven", "refuted", "disproved", "score", "importance", "no prior work", "does not exist". The scan covers the
    chrome text of the NEW candidate UI and the new VI block only (not the rest of the application, not the existing report text). The existing
    VI heading "Candidate Unanswered Aspects" and the existing fine print stay as they are.
    Stored titles, abstracts, quotes, notes, claim text and owner reasons are shown byte for byte even if they contain such words (the scan of
    the Playwright spec uses a stored title and a stored claim that contain "novel" and "gap" and asserts they stay intact).

### Design (`.impeccable.md` applies; read all of it)

21. Editorial tokens only, no literal colors, no new token unless added to both `:root` and `.dark` in `index.css` (say so in the report); hierarchy
    from type, weight, spacing and hairlines; no cards inside cards, no shadows outside floating layers; real `<ul>/<ol>/<table>/<dl>` with
    `h2`/`h3`/`h4` in a logical order; sentence-case labels, no uppercase eyebrows; lucide icons with `aria-hidden`; disclosures are `<details>` or
    buttons with `aria-expanded`; every control has a visible focus ring from existing styles, accessible names, and a visible or accessible
    reason when disabled; amber for attention/uncertain, `--tone-include` only for completed work (never for "closed" or "open": those are states,
    not success), red only for blocking errors; `prefers-reduced-motion` honoured (no new animation); model and provider names carry their icons;
    works at 1440 and 390 px in light and dark; the NEW tab content must not overflow sideways at 390 px (`overflow-wrap:anywhere` for long
    titles, terms and quotes; the matrix stacks as item 17 says, it does not scroll sideways). Loading uses `role=status` text, blocking errors
    `role=alert` through `Notice`. Reuse `ConfirmDialog`, `Notice`, `ModelName`/`useModelText`, `SourceKey`, `Sheet`, `Button`.

### Fixture scenario and tests

22. **Fixture server** (`tests/acceptance/fixture_server.py`, `ScriptedCodex.respond`, the OpenAlex mock): a question marker `[candidate]` (add it to
    the file header list) that makes a research whose candidate flow can be driven end to end with the scripted model and mocked retrieval and no
    other scenario changing. The scripted model must answer the three tasks with contract-valid JSON (start from `valid_response(si)`, read
    `tests/test_candidate_flow.py` and `tests/test_candidate_contract.py` for what the validators require, use real handles/ids from `si`):
    `claim_decomposition` (a claim with three elements of different kinds, conditions, a nearest simple explanation, an assumption, a plan);
    `kill_search_query` (two blocks); `claim_assessment` per work. The mocked OpenAlex must serve, for a kill-search query only, a small set of
    SYNTHETIC works (a distinct marker term in the scripted terms is the simplest switch; do not disturb discovery's answers): W-A whose
    abstract states element 1 in the same conditions and element 2 in other conditions (`explicit_support` aligned, `partial_match`
    `different_conditions`, element 3 `no_match_in_supplied_text`; relevance `related`, whole claim false); W-B unrelated (all cells no match); W-C
    with an abstract that does not cover the claim but is shown, `unrelated`; and a variant marker `[candidate-access]` that adds W-D with no
    abstract and no stored text (metadata only: never sent to the model, `insufficient_access`) so the status is `undecided`
    (`insufficient_access`). Default `[candidate]` must end `narrowed`. State in a comment block exactly which work, cell and status each marker
    produces. For a gap-origin candidate: if a real report run of the fixture can carry a gap row without any backend change, use it; otherwise the
    spec seeds ONE `report_gaps` row (kind `corpus_absence`, synthetic text, valid JSON in `basis_json` and `provenance_json`) into the fixture's
    temp SQLite file for a report that the fixture produced, through a small Python helper run with `DEIXIS_TEST_PYTHON` against the temp data
    dir (the data dir path is the spec's own), and says so in a comment. For a controllable run line the scripted model sleeps a short fixed time (about 0.8 s) per candidate-task call under `[candidate]` only, as
    `[slow-cells]` does for cells, so the intermediate states can be asserted. The seed (if used) is committed only after the report run is terminal and
    the report sheet is then reopened. The Python seeding snippet may be inlined in the spec (`spawnSync(python, ['-c', ...])`). Every other scenario of
    the fixture stays untouched (existing specs pass unchanged).
23. **Playwright `apps/web/e2e/candidate.spec.ts`** (own fixture-server instance on an unused port: search `apps/web/e2e/*.spec.ts` and `tests/` for every port in use (`PORT =`, constructor
    arguments such as `new ...Server(88xx)`, `--port`), pick a free one in 8806-8899, comment it, copy the server class of `lineage.spec.ts`). Real fixture server:
    - start a research with `[candidate]`, let discovery finish, open the Candidates tab (keyboard: Tab reaches the tab, Enter opens it): empty
      list sentence; "Add candidate" with a sentence that contains "novel" and "gap"; the owner notice is visible; Save opens the card; "Break the
      claim into testable parts" shows its budget, runs, the run line and timeline update, and the card shows version 1 "model proposal" with three
      elements and the fixed lines;
    - edit: change an element and the claim, save: version 2 "your edit"; version 1 is in "Earlier versions (1)"; a stale save (change the card
      through the API first) gives the 409 text and "Reload" and keeps the typed text; an all-whitespace claim gives the 422 message;
    - "Plan the search": the plan card shows version 2, providers, both ceilings and the limits sentences; Start; the run line shows the terms,
      the provider query line and the assessment progress; wait for completion; the status block says Narrowed with its sentence and ALL its
      facts; the matrix shows W-A, W-B, W-C in rank order with the exact relation and alignment words of the scenario, no colour-only state, the
      counts sentence, the queries list, the terms disclosure;
    - "Show evidence" on W-A: the sheet shows the passage text the model received and the stored quote marked exactly (assert the `<mark>` text equals
      the stored quote) and the fixed lines; Escape closes and focus returns; a work never sent says so (use `[candidate-access]` in a second
      research on the same server: status Undecided with the `insufficient_access` sentence, W-D row with its sentence);
    - owner decision: record "closed" with a reason: the block shows "Computed: Narrowed" and "Yours: closed" side by side and the reason; a blank
      reason is refused; reload the page: both still shown; the computed status is unchanged;
    - paused runs: pause a decomposition and a kill-search of the candidate (the scripted delay makes this possible), assert Resume and Cancel
      are offered and no other start is, resume completes each; with a paused run the second start is refused in the UI with its reason, and
      through the API with 409 for both kinds (a request sent by the spec); and, with more than ten later research runs after an old paused
      candidate run, assert the screen does not claim a complete history and the backend's 409 message is shown on a start attempt;
    - gap origin: open a report for the research (the report spec shows how the fixture produces one), the VI block lists the seeded/real row with
      its kind words and text, "Investigate" opens the candidate on the Candidates tab, a second "Investigate" on the same row opens the same card;
      the existing report content is unchanged;
    - the forbidden-word scan of item 20 over the rendered Candidates tab, the plan card, the status block, the sheets AND the new VI block of the report (its
      stored gap text may contain "novel" or "gap" and must stay intact) (chrome only, with the
      stored "novel"/"gap" strings asserted intact); keyboard path through list, card, editor, plan, matrix title, evidence, decision;
      `prefers-reduced-motion` emulated; 1440 and 390 px, light and dark screenshots into `OUT` for: list, card, editor, plan card, status+decision
      block, matrix, evidence sheet, VI block. At 390 px assert the Candidates content has `scrollWidth <= clientWidth`.
    Mocked-JSON rendering test in the same file (`page.route` on the candidate GET endpoints for a research opened on the fixture server, serving
    hand-built JSON that matches `api.ts`): every one of the five statuses and every `reason` code and warning of item 12 (one candidate each, or
    one card re-served), a card with a gap origin including `missing: true` basis items and `origin_changed`, a trashed candidate row, an
    `owner_text` candidate, a card with three versions and searches on two of them, a running and a paused run with a failed query and an
    `outcome_unknown` query, a matrix with every relation and alignment, every assessment state, every reading depth, a work with no cells, a
    cut count and duplicates, ten-line owner decision history, long unbroken strings in titles, terms, quotes, notes and reasons, the stored
    "novel"/"gap" strings; assert every list heading is present with "None."/zero where empty, no raw code is printed for a known code, the
    forbidden-word scan, and 390 px light/dark screenshots of the busiest states.
24. Checks to run: `cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new ones); the focused specs
    `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-k4 DEIXIS_TEST_PYTHON=... npx playwright test e2e/candidate.spec.ts e2e/report.spec.ts
    e2e/lineage.spec.ts` (see `package.json`/`playwright.config.ts` for the exact script); `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache
    uv run pytest tests/test_report_gaps_view.py tests/test_candidate_api.py tests/test_report_api.py -n 0` (smoke; the orchestrator runs the
    full suites).

## Limits of K4 (do not exceed)

No backend change other than the two "Backend exceptions" (the read route with its `views.py` function and test, and the paused-run guard in
`request_decomposition` with its test) and `tests/acceptance/fixture_server.py`. No migration,
no contract or method change (`skill_package_hash` stays `sha256:8e1e4a8453a286ac9da8628dd095dd7796f3a49ae374d7930cb3ef06c546ee76`), no other
route, no change to `workflow/report/*`, `report_view`'s output or any `report_*` schema. No trash or restore UI (the routes do not exist), no
export, no report write-back, no PDF reading, no chain-end entry, no graph or canvas drawing, no new colour vocabulary, no score or ranking of
candidates, no auto-start of a search or a decomposition, no model call from any control other than "Break the claim into testable parts" and a
confirmed "Start" of a planned search, no persistence of UI choices, no claim that a quote proves support. Do not fix the pre-existing sideways
scrolling of other pages.

## Files allowed

`apps/web/src/candidate/*` (new), `apps/web/src/api.ts`, `apps/web/src/i18n.ts`, `apps/web/src/labels.ts`, `apps/web/src/ResearchView.tsx`,
`apps/web/src/report/ReportView.tsx` (+ `report.css` for the new block only), `apps/web/src/EvidenceTable.tsx` (only to export or lightly extract
the run line), `apps/web/src/PassageSheet.tsx` (only to export the highlighted-text component, no behaviour change), `apps/web/src/index.css` (only
a new token, both themes, if unavoidable), `apps/web/e2e/candidate.spec.ts` (new), `tests/acceptance/fixture_server.py`,
`backend/deixis/workflow/views.py`, `backend/deixis/api/app.py` (the one route only), `tests/test_report_gaps_view.py` (new),
`backend/deixis/workflow/candidates/run.py` (only the paused-run guard of `request_decomposition`), `tests/test_candidate_decompose_guard.py` (new).

## Files NOT allowed

`backend/` (everything else), `methods/`, `contracts/`, migrations, every other `tests/*.py`, `package.json`, `package-lock.json`,
`apps/web/node_modules`, `workflow/report/*`, everything in the "do not touch" list above.

## Report at the end

Files changed; the exact request/response types you added; every judgement call (tab placement, the report-gaps route, where the run line lives,
the evidence sheet's marking path, fixed sentence maps, run-kind handling in each place you touched or deliberately left alone); what the fixture
scenario really produces for each marker; how the gap-origin path was driven (real report row or seeded); what is deferred; everything you could
not find or verify; build, lint and Playwright results (counts, or why not run) and the paths of any screenshots you looked at.
