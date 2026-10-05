// Client for the local DEIXIS API. Types mirror backend/deixis/workflow/views.py.
import { t } from './i18n'

export type RunStatus = 'queued' | 'running' | 'pause_requested' | 'paused' | 'completed' | 'failed' | 'cancelled'
export type SourceScope = 'academic' | 'attached' | 'attached_and_academic'
export type Effort = 'quick' | 'standard' | 'detailed'

export type LineageRelation = 'extends' | 'relaxes_assumption' | 'changes_method' | 'new_domain_or_condition'
  | 'corrects_or_contradicts' | 'independent_parallel'
export type LineageSupport = 'source_stated' | 'analyst_inference'
export type LineageDecision = 'link' | 'no_relation' | 'insufficient_evidence' | 'removed'
export type LineageEdgeState = 'present' | 'absent_in_read_list' | 'unresolved' | 'not_read'
export type LineageReason = 'not_run' | 'no_pdf_text' | 'no_candidate' | 'no_relation' | 'insufficient_evidence'
  | 'rejected' | 'not_sent_budget' | 'step_failed' | 'human_removed' | 'cross_relation_only' | 'stale_only'
export type LineageStaleReason = 'evidence_not_current' | 'scope_changed' | 'node_changed' | 'passage_changed'
export type LineageCurrency = { current: boolean | null; stale_reasons: LineageStaleReason[]; unchecked: string[] }
export type LineageNode = {
  source_version_id: string; work_id: string; source_key: string | null; title: string; year: number | null
  version_label: string | null; live: boolean; position: number | null; eligible: boolean | null
  access_level: 'pdf_available' | 'abstract' | 'metadata' | null
}
export type LineagePairDecision = {
  link_id: string; from: string; to: string; version: number; current_revision_id: string | null
  decision: LineageDecision | null; author: 'model' | 'human' | null; disposition: 'accepted' | 'rejected' | null
}
export type LineageLink = {
  link_id: string; version: number; revision_id: string; from: string; to: string; relation: LineageRelation
  what_changed: string; support_type: LineageSupport; author: 'model' | 'human'; human_edited: boolean; note: string | null
  edge_state: LineageEdgeState | null; unexpected_no_citation_edge: boolean; year_order_warning: boolean
  not_head_ends: ('from' | 'to')[]; output_status: 'structurally_valid' | 'unverified_draft' | null
  scope_revision: number | null; run_id: string | null; created_at: string
  evidence: { passage_id: string; anchor_text: string; anchor_match: 'exact' | 'normalized' | 'fuzzy'
    physical_page: number | null; printed_label: string | null; kind: string }[]
  stale_reasons: LineageStaleReason[]
}
export type LineageComponent = {
  id: string // Derived at read time from members, never a persistent identity.
  members: string[]; links: LineageLink[]
  adjacency: { source_version_id: string; in_from: string[]; out_to: string[] }[]
  roots: string[]; branches: string[]; merges: string[]; has_cycle: boolean
}
export type LineageStepOutcome = LineageCurrency & {
  kind: 'failed_pair' | 'unsent_pair' | 'step_failed' | 'skipped'; from: string | null; to: string
  key: string | null; pair_fp: string | null; reason: string | null
  run_id: string; scope_revision: number; recorded_at: string
}
export type LineageUnplaceableDetail = LineageCurrency & {
  reason: LineageReason; from: string | null; to: string | null; link_id: string | null; revision_id: string | null
  run_id: string | null; scope_revision: number | null; recorded_at: string | null
}
export type LineageLastRun = { run_id: string; scope_revision: number; recorded_at: string }
export type LineageUnplaceable = {
  source_version_id: string; reasons: LineageReason[]; details: LineageUnplaceableDetail[]; last_run: LineageLastRun | null
}
export type LineageNotAccepted = {
  link_id: string; from: string; to: string; revision_id: string; rejection_code: string; decision: LineageDecision
  relation: LineageRelation | null; what_changed: string | null; support_type: LineageSupport | null; note: string | null
  run_id: string; created_at: string; superseded: boolean
  pair_state: { decision: LineageDecision | 'none'; author: 'model' | 'human' | null }
}
export type LineageView = {
  table_id: string; table_version: number
  status: { roles: Record<'problem' | 'change' | 'uncertainty', boolean>; live_rows: number; pdf_text_rows: number
    nodes_complete: number; nodes_partial: number; missing_cells: number; placed_rows: number; unplaced_rows: number }
  nodes: Record<string, LineageNode>; pair_decisions: LineagePairDecision[]; components: LineageComponent[]
  cross_relations: LineageLink[]; unplaceable: LineageUnplaceable[]; not_accepted: LineageNotAccepted[]
  unassessed_edges: { from: string; to: string }[]
  edges_into_unscanned_targets: { from: string; to: string; to_reason: 'no_pdf_text' | 'not_run' }[]
  step_outcomes: LineageStepOutcome[]; not_sent_budget: LineageStepOutcome[]; failed_pairs: LineageStepOutcome[]
  history: { stale: LineageLink[]; out_of_scope: (LineageLink & { not_live_ends: ('from' | 'to')[] })[] }
  counts: { components: number; current_links: number; cross_relations: number; history_stale: number; history_out_of_scope: number
    unplaceable: { total: number; reasons: Record<LineageReason, number> }; not_accepted: number; unassessed_edges: number
    edges_into_unscanned_targets: number; not_sent_budget: number; failed_pairs: number; step_outcomes: number; human_edited_links: number
    // Citation-list states of live ordered pairs of different works, not link counts.
    edge_states: Record<LineageEdgeState, number> }
}
export type LineageBaselineEntry = {
  work_id: string; source_version_id: string; source_key: string | null; title: string; year: number | null
  cited_by_count: number | null; cited_by_count_at: string | null; publication_type: string | null
  cited_by_included_works: { count: number | null; other_works: number; lists_read: number; target_resolved: boolean }
}
export type LineageBaselineList = { total: number; shown: LineageBaselineEntry[]; entries: LineageBaselineEntry[]; note: string }
export type LineageBaseline = {
  table_id: string; scope: 'Among the works this research included'
  representatives: { work_id: string; source_version_id: string; reason: 'head' | 'other_version'; versions_considered: string[] }[]
  most_cited_in_corpus: LineageBaselineList; review_in_corpus: LineageBaselineList; unknown_count_works: number
}
export type LineageLinkFields = {
  relation: LineageRelation; what_changed: string; support_type: LineageSupport
  evidence: { passage_id: string; quote: string }[]; note?: string | null; expected_version: number
}
export type LineageLinkAdd = LineageLinkFields & { from_source_version_id: string; to_source_version_id: string }
export type LineageLinkEdit = LineageLinkFields & { based_on_revision_id: string }
// DELETE request fields are query parameters.
export type LineageLinkRemove = { expected_version: number; based_on_revision_id: string; note?: string | null }

// The public preview of LineagePlanner.preview, not the larger frozen run target.
export type LineagePlanTarget = { to: string; class: 'new' | 'changed' | 'retry' | 'settled'; position: number; target_fp: string }
export type LineagePlan = {
  table_id: string; plan_version: number
  counts: { live_rows: number; eligible_targets: number; selected: number; not_selected: number; calls: number
    candidates: number; no_candidate: number; not_sent_budget: number; failed_unchanged: number
    development_columns: number; missing_cells: number }
  max_model_calls: number; max_provider_requests: number; calls: number; preview_fingerprint: string; retry_failed: boolean
  selected: (LineagePlanTarget & { no_candidate: boolean; outcome: 'settled' | 'incomplete'; candidate_count: number; chunk_count: number })[]
  not_selected: (LineagePlanTarget & { reason: 'settled' | 'beyond_work_limit' })[]
  not_sent_budget: { to: string; from: string; reason: string; pair_fingerprint: string }[]
  failed_unchanged: { to: string; from: string; pair_fp: string }[]
}

export type Scope = {
  research_id: string; revision: number; question: string; language_hint: string | null; source_scope: SourceScope
  seed_mode: 'question_only' | 'uploaded_seed'; seed_status: 'question_only' | 'missing' | 'ready' | 'stale'
  // The current revision's search finished; an sw research may then answer with no included work (SW22).
  discovery_completed?: boolean
  seed: { source_version_id: string; asset_id: string; asset_sha256: string; extraction_version: string
    title: string; title_basis: string; page_count: number | null; text_pages: number; passage_count: number } | null
  providers: string[]; search_providers: string[]; effort: Effort; model_connection: string; requested_model: string | null; reasoning_effort: string | null
  // null literature model: the research model runs the search steps (researches created before model roles).
  literature_model: string | null; literature_reasoning_effort: string | null
  review_mode: ReviewMode; review_model: string | null; review_reasoning_effort: string | null
  // null connection: the role uses model_connection (researches created before per-role connections).
  literature_connection: string | null; review_connection: string | null
  steering: string | null; created_at: string
  // Which search workflow this revision runs under, and the English key terms the user gave for it (SW2.1).
  search_workflow: 'legacy' | 'sw'; key_terms: string | null
}
export type ReviewMode = 'default' | 'custom' | 'off'
export type Verdict = 'supported' | 'partially_supported' | 'not_supported' | 'cannot_assess'
export type AnswerReview = {
  status: 'completed' | 'failed'; failure_reason: string | null; created_at: string
  reviews: { claim_label: string; verdict: Verdict; reason: string }[]; notes: string; issues: ValidationIssue[]
  model: { connection: string; requested_model: string | null; resolved_model: string | null } | null
}
export type ModelRole = 'answer' | 'literature' | 'reviewer'
// App-wide default for one role. model null: no default (for the reviewer: answers are not reviewed).
export type RoleModelSetting = { model_connection: string; model: string | null; reasoning_effort: string | null }
export type Step = {
  id: string; operation_key: string; kind: string; status: string; attempt: number; delivery_class: string | null
  error_code: string | null; error: unknown; started_at: string | null; finished_at: string | null
  // Only small counting/provenance outputs carry through this view; model prose remains in its own artifact view.
  output: { pdfs_read?: number; pdfs_skipped?: number; page_count?: number | null; passage_count?: number; model?: string; sources?: number; passages?: number; embedded?: number
    // A pdf_ocr run (D51): the pages without text it found, and whether the merged OCR text was taken into use.
    image_pages?: number[]; blank_pages?: number[]; asset_id?: string; outcome?: 'current' | 'rejected' | 'unchanged' | 'file_busy'; rejection_reason?: string | null
    // Citation chaining (D95): what its summary counted, with the seeds it froze.
    seed_list?: { source_version_id: string; kind: 'code' | 'user' }[]; new_works?: number; read_by_model?: number
    requests?: { sent?: number; failed?: number; not_reached_seeds?: number }
    semantic_scholar?: { status?: string; reason?: string | null; seeds_without_doi?: number }
    // The full-text retrieval summary (D83), also written by a discovery run that fetched beside its screening (17a).
    fetched?: number
    // An embedding step (slice 21): the model it froze, what it read from the store, what it still misses, its 429 waits,
    // the person's uploaded files whose text it sent, and why the built-in model skipped it.
    provider?: string; stored_model?: string; from_store?: number; missing?: number; query_origin?: string
    rate_limited_waits?: number; waited_seconds?: number; uploaded_files_attempted?: number; uploaded_passages_attempted?: number; uploaded_files_confirmed?: number; uploaded_passages_confirmed?: number; uploaded_files_unknown?: number; uploaded_passages_unknown?: number; stored_other_dimension?: number; model_installed?: boolean
    skipped?: boolean; reason?: string } | null
}
// What the search plan step reported, as the model wrote it.
export type SearchPlan = {
  question_interpretation: string; search_rationale: string; scope_boundaries: string[]
  concepts: { label: string; role: string; synonyms: string[] }[]
  queries: { provider_id: string; query_text: string; rationale: string }[]
}
export type RunKind = 'discovery' | 'answer' | 'report' | 'review' | 'watch_check' | 'pdf_collection' | 'pdf_ocr' | 'fulltext_fetch' | 'fulltext_adjudication' | 'table_columns' | 'table_fill' | 'cell_recheck' | 'research_title' | 'lineage_links' | 'claim_decomposition' | 'kill_search'
// What a table run works on, as stored when it was requested (D38); null for discovery and answer runs.
export type RunTarget = {
  plan?: { groups: ReviewGroup[] }
  target_kind?: ReviewTargetKind; target_id?: string
  pipeline?: { id: string; rounds?: number; round?: number }
  table_id?: string; column_id?: string; source_version_id?: string; cell_version?: number
  candidate_id?: string; candidate_version_id?: string; expected_version?: number
  model?: CandidatePlan['model']; providers?: string[]; transport?: CandidatePlan['transport']; limits?: CandidatePlan['limits']
  version?: number; scope_revision?: number; skill_package_hash?: string; plan_version?: number; preview_fingerprint?: string
  report_id?: string
  sources?: { source_version_id: string; column_ids: string[] }[]
  // pdf_ocr (D51): the PDF read and the Tesseract languages used.
  asset_id?: string; languages?: string[]
}
export type Run = {
  id: string; research_id: string; scope_revision: number; kind: RunKind; status: RunStatus; stage: string
  pause_reason: string | null; error: unknown; budget: Record<string, number>; usage: Record<string, number>
  created_at: string; updated_at: string; version: number; steps?: Step[]; target: RunTarget | null
  // plan null: this run wrote no search plan. screening_notes: the note of each screening batch, in order, with its step.
  plan: SearchPlan | null; screening_notes: { step_id: string; text: string }[]
  // What this run asked the user to approve before freezing its protocol; null for a legacy run (D80).
  approval: RunApproval | null
  // Per round, what each source brought in this discovery run and how much of it no other source did (D93).
  // counted false: the run was searched before these were kept, which is not the same as zero.
  source_counts?: SourceCounts | null
  // The phrases the second keyword round searched with; empty when it did not search.
  expansion_terms?: string[]
  // Where the person's confirmed works stood in this discovery run's keyword ranking, descriptively (slice 19); null
  // for a legacy research, another run kind, or a run that ranked nothing.
  signals?: SignalTable | null
}
export type SourceCounts = {
  counted: boolean
  rounds: { round: number; sources: { provider_id: string; works: number; only: number }[] }[]
  // What citation chaining brought in this run, and how much of it no keyword search did (D95); absent when it
  // sent nothing.
  chain?: { works: number; only: number }
  // Beside D93's rows, row for row (slice 19); null in a legacy research, absent when the counts were not kept.
  arms?: SourceArms | null
}
// Counted in D93's "only" universe: a source row against the other sources' searches, the chain against every search.
// `included`: two agreeing model runs included the work (never called verified); `verified`: the person confirmed it.
export type ArmCount = { rows: number; included: number; included_only: number; verified: number; verified_only: number }
export type ArmKind = 'keyword' | 'expansion' | 'chain'
export type SourceArms = {
  rounds: { round: number; sources: (ArmCount & { provider_id: string
    // The first round's works by the query that found them (D92), when a source was queried by both origins.
    by_origin?: { origin: string; works: number; included: number }[] })[] }[]
  chain?: ArmCount
  // The arm kinds in run order; `new_*` is what no earlier kind of this run found. Counts only: no stopping rule.
  kinds: ({ kind: ArmKind; ran: false } | { kind: ArmKind; ran: true; works: number; new_works: number; included: number
    new_included: number; verified: number; new_verified: number })[]
  // false while no work of this question revision has a full-text reading: included counts come with it.
  read: boolean
}
export type SignalCapture = { signal: string; top_100: number; top_200: number; tied_100: number; tied_200: number }
export type SignalTable = {
  step_id: string; pool: number | null
  signals: { signal: string; ran: boolean; reason: string | null; available: number | null }[]
  seeds: { verified: number; code: number }; no_reference_list_share: number | null
  // The person's confirmed works present in this ranking step; below the display minimum the table says too few.
  person: { denominator: number; status: 'too_few' | 'descriptive'; rows: SignalCapture[] }
  // Works two agreeing runs included: read because the order put them near the top, so not a signal's success.
  agreement: { denominator: number; rows: SignalCapture[]; note: 'read_because_ranked' }
  embedding: { moved_up: number; moved_up_then_included: number; moved_up_then_verified: number
    moved_up_already_decided: number; moved_up_time_unknown: number } | null
}
// The probe set of an sw research (slice 19): derived on read from the person's own decisions.
export type Probes = {
  verified: number
  // out_of_scope null: no answer records it, which is not zero.
  negatives: { criterion_not_met: number; not_recorded: number; out_of_scope: null }
  look_again: number; included_by_agreement: number; brought: number; judge_min: number
  // false while no work of this question revision has a full-text reading.
  read: boolean
  not_found: { status: 'counted' | 'partial' | 'not_counted' | 'no_search'
    works: { work_id: string; source_version_id: string; title: string; doi: string | null; source_key: string | null
      reasons: ('verified' | 'brought')[]; found: 'no' | 'unknown' }[] }
}

// ---- the protocol approval of an sw discovery run (D80) --------------------------------------------
// The blocks a term can sit in. setting and task are the two blocks that make the provider query; outcome orders
// the records; claim is the assertion under test and exclusion the words that keep a record out — neither is searched.
export type ApprovalBlock = 'setting' | 'task' | 'outcome' | 'claim' | 'exclusion'
export type ApprovalTerm = {
  phrase: string; block: ApprovalBlock
  // Who supplied the phrase (the question, the user's key terms, the user's own correction) and who put it in its
  // block (the code rule, the model's labelling step, the user).
  // 'model': the user added a name the model proposed for another term on this card (D82). The origin is derived
  // on the server from the stored proposals; the correction the browser sends never names it.
  // 'search_query': the model that wrote this run's query chose it (D92); its block origin is the same.
  origin: 'question' | 'key_terms' | 'user' | 'model' | 'search_query'; block_origin: 'rule' | 'model' | 'user' | 'search_query'
  // The form the phrase enters the query in, and what each form was counted at. A null count was not read.
  root: string; in_query: 'root' | 'phrase'; phrase_count: number | null; root_count: number | null
  // and_only: the form is too frequent to stand alone. dropped: why the phrase left the query, e.g. 'zero_results'.
  and_only: boolean; dropped: string | null
}
export type CriterionPart = { name: string; definition: string }
export type CriterionCue = { phrase: string; part: string | null; runs?: number[] }
export type ApprovalCriterion = {
  criterion: string; parts: CriterionPart[]; cue_phrases: CriterionCue[]; exclusion_title_words: string[]
  dropped_exclusion_title_words?: string[]; base_run?: number | null; runs_ok?: number[]
  // Whether what the question looks for is named in the criterion; null when it was not checked.
  sought_term_in_criterion?: boolean | null; origin?: string
}
// One side of the approval: what the run proposed, or what it was approved with.
export type ApprovalSide = {
  terms: ApprovalTerm[]
  // Phrases that never enter a provider query; they carry no count of their own.
  claim_words: string[]; exclusion_words: string[]; outcome_terms: string[]
  gate_count: number | null; too_broad: boolean
  criterion: ApprovalCriterion | null; criterion_available: boolean; sought_term_in_criterion: boolean | null
  // The approved side carries them, and a proposal whose query a model wrote (D92): the compiled text of every query
  // the run will send, and which vocabulary wrote each one.
  queries?: { provider_id: string; query_text: string; origin?: 'model' | 'code' }[]
  // Present when a model wrote the query, or was asked to and failed (D92).
  search_query?: SearchQuerySide
}
// What the card shows of a model-written query (D92). The counts and warnings are code's checks; `kind` and `why`
// are the model's own words about a term and decide nothing.
export type SearchQueryTerm = {
  phrase: string; kind: 'topic' | 'method' | 'population' | 'other' | null; why: string | null
  // The term this backup took the place of, when a chosen term held no record.
  backup_for: string | null
  // Records holding the term together with the other block's chosen terms; null was not counted.
  with_other_block: number | null
}
export type SearchQuerySide =
  | { status: 'ready'; terms: SearchQueryTerm[]
      warnings: { phrase: string; block: string; warning: 'no_records_with_other_block' | 'count_unknown' }[]
      backups_left: Record<'setting' | 'task', string[]>
      // The query code built from the question's words (slice 13g), offered beside the model's.
      code_query: { searched: boolean; available: boolean
                    terms: { phrase: string; block: 'setting' | 'task'; form: string }[]
                    queries: { provider_id: string; query_text: string }[] } }
  | { status: 'failed'; choice: 'code_only' | null; attempts: { attempt: number; reason: string | null }[] }
export type TermEdit = { op: 'remove' | 'move' | 'add'; phrase: string; block?: ApprovalBlock }
// What the user sends back. An empty package approves the proposal as it stands; a criterion given replaces the
// proposed one whole (slice 08a).
export type ProtocolEdits = {
  terms: TermEdit[]
  criterion: { criterion: string; parts: CriterionPart[]; cue_phrases: { phrase: string; part: string | null }[]; exclusion_title_words: string[] } | null
  note: string | null
  // Whether the code's query is searched beside a model-written one; null leaves the proposal's choice (D92).
  code_query?: boolean | null
}
export type RunApproval = {
  // waiting: the card is editable. submitted: the correction was sent and is being applied. approved: it is frozen.
  status: 'waiting' | 'submitted' | 'approved'
  approved_by: 'user' | 'setting' | 'earlier_approval' | 'no_warning' | 'model_advice' | null; edited: boolean | null; proposal_hash: string
  proposal: ApprovalSide; approved: ApprovalSide | null
  // Operations of an earlier approval this run could not apply, because the phrase is no longer in the proposal.
  skipped_edits: { op: string; phrase: string; block?: string; reason?: string }[]
  // Why the run stopped for the person: a term that alone inflates the matches, with the count without it.
  // `advice` is the model's remove-or-keep suggestion for the term and one plain sentence why (D232); null when none was asked or given.
  warnings?: { warning: string; phrase: string; block: string; matches: number; matches_without_term: number; advice?: { recommendation: 'remove' | 'keep'; reason: string } | null }[]
  // The model that gave that advice; null when it gave none.
  advice_model?: { connection: string; model: string | null } | null
  // When the run went on without asking (`approved_by` model_advice): what each warned term's advice did (D232).
  advice_applied?: { phrase: string; recommendation: 'remove' | 'keep' | null; reason: string | null; matches: number; matches_without_term: number; applied: boolean; not_applied?: string }[] | null
  // Other names the user asked a model for, and what came of it (D82).
  suggestions: ApprovalSuggestions
  // Which sources the queries were compiled for and why (D93); null for a card shown before routing existed.
  routing?: SourceRouting | null
  // How the run chains citations after its abstract stage (D95), frozen when the run was queued; null for a run
  // queued before D95.
  chaining?: CitationChaining | null
}
// The chain rule and its limits as the run froze them (D95). The seeds themselves are known only after the search.
export type CitationChaining = {
  enabled: boolean; seeds?: number; citing_cap?: number; request_limit?: number; abstract_read?: number
  plan_room?: number; directions?: string[]; sources?: string[]
}
// The source routing of an sw run (D93): the field distribution of the gate query and the sources it chose.
// status read: a distribution was read; unavailable: it could not be, so every source in scope is searched;
// not_needed: no field-specific source was in scope, so nothing was asked.
export type SourceRouting = {
  status: 'read' | 'unavailable' | 'not_needed'; query: string | null; total: number | null
  fields: { field: string; count: number; share: number }[]; route_share: number; table_version: string
  chosen: RoutedSource[]; left_out: RoutedSource[]; providers: string[]
  // The chosen sources the first round's queries go to; the effort's query limit can leave a chosen one none.
  queried?: string[]
}
export type RoutedSource = {
  provider_id: string
  reason: 'always' | 'share' | 'distribution_unavailable' | 'no_route' | 'share_below' | 'not_in_scope'
    | 'not_configured' | 'not_in_sw_search'
  fields?: string[]; share?: number
}
// One name the model proposed for a term of the card. `phrase_count` is how many records hold it; null was not
// counted, which is not zero. `dropped` says why it cannot enter the query, and a dropped row cannot be added.
export type SuggestedTerm = {
  phrase: string; synonym_of: string; block: ApprovalBlock
  phrase_count: number | null; dropped: string | null
}
export type ApprovalSuggestions = {
  // none: nothing was asked. requested: the run is asking a model. ready: the list is on record. failed: the
  // request did not complete and may be repeated.
  status: 'none' | 'requested' | 'ready' | 'failed'
  // Whether the run would take a request now, and why it would not.
  available: boolean; unavailable_reason: null | 'no_anchor_phrases' | 'already_suggested' | 'suggestion_call_spent'
  failure: string | null
  // Whether this list came from an earlier approval of the same question rather than from a request of this run.
  carried: boolean
  terms: SuggestedTerm[]
}
export type SearchRun = {
  id: string; run_id: string; scope_revision: number; provider: string; query_text: string; access_mode: string; status: string
  result_count: number; provider_total: number | null; page_limit: number; retrieved_at: string; error: { error: string | null; http_status: number | null } | null
  // 1: the approved queries; 2: the term expansion's, searched with phrases the first round's records brought.
  round?: number
}
export type Asset = {
  text_recovery?: TextRecoveryCapability | null
  id: string; extraction_status: string; extraction_error?: string | null; extraction_version?: string | null; page_count: number | null; origin: string; byte_size: number; original_filename: string | null
  // Europe PMC's open-access text drawn as a PDF by DEIXIS (SW21): its pages are not the publisher's.
  rendition?: boolean
  // Sources only (D45): whether the text comes from the current extractor, and a later extraction that was not taken.
  current_extraction?: boolean; rejected_extraction?: { extraction_version: string; rejection_reason: string; created_at: string } | null
  // Sources only (D52): whether Marker has read the PDF's pages with mathematics.
  // A read's `equations_to_check` counts display equations that did not match the PDF's text layer, on pages `to_check`.
  // Without Marker and with the arXiv source route on (D104), `route: 'arxiv_source'` and its own states/fields.
  equations?: {
    state: 'read' | 'no_math' | 'failed' | 'reading' | 'pending' | 'no_source' | 'source_waiting'
    reason?: string | null; attempts?: number; pages?: number; started_at?: string; to_check?: number[]; equations_to_check?: number
    route?: 'arxiv_source'; next_at?: string
    source?: {
      arxiv_id: string | null; version: number | null; version_from: 'url' | 'stamp' | 'both' | null; record_label: string | null
      placed: number; pages: number[]; not_placed: Record<string, number>
    } | null
  }
  // Sources only (D51): pages of the text in use without text (blank pages included), pages read with OCR, the latest OCR reading.
  ocr?: { pages_without_text: number; ocr_pages: number; last_read: OcrRead | null }
}
export type OcrRead = {
  outcome: 'current' | 'rejected' | 'superseded'; rejection_reason: string | null; created_at: string
  engine: string; version: string | null; languages: string[]; pages_read: number; pages_with_text: number; blank_pages: number; failed_pages: number[]
}
// The local Tesseract (D51): usable when it runs and has data for at least one language.
export type OcrTool = { available: boolean; version: string | null; languages: string[]; missing_languages: string[]; reason: string | null }
// What became of a cited passage's file since it was stored (D45).
export type EvidenceStatus = 'current' | 'pdf_removed' | 'pdf_replaced' | 'text_superseded'
export type ReplacedAsset = { id: string; original_filename: string | null; removed_at: string; replaced_by_asset_id: string }
export type AssetImpact = { asset_id: string; researches: { id: string; title: string }[]; cells: number; quotes: number }
export type Reextraction = { asset_id: string; outcome: 'current' | 'rejected' | 'unchanged'; rejection_reason?: string | null }
export type FileRestoreReceipt = {
  operation_id: string; sha256: string; lifecycle: 'running' | 'completed' | 'interrupted'
  outcome: 'file_restored' | 'file_reused' | 'file_refused' | null; reason: string | null
  before_integrity: string | null; after_integrity: string | null; retained: boolean; created_at: string; finished_at: string | null
}
export type TextRetryOperation = {
  operation_id: string; asset_id: string; lifecycle: 'running' | 'completed' | 'interrupted'
  outcome: 'promoted' | 'diagnosis_updated' | 'rejected' | 'no_change' | 'refused' | null
  reason: string | null; decision_code: string | null; input_observation_id: string | null; input_integrity: string | null
  candidate_status: string | null; extraction_id: string | null; extraction_version: string | null; baseline_extraction_id: string | null
  coverage: { old_text_pages: number[]; new_text_pages: number[]; missing_pages: number[] } | null
  created_at: string; finished_at: string | null
}
export type TextRetryRequest = { mode: 'retry_failed_or_partial'; expected_current_extraction_id: string; idempotency_key: string }
export type TextRecoveryCapability = {
  current_extraction_id: string | null; status: string; extractor_profile: string | null; extraction_version: string | null
  diagnostic_only: boolean; can_retry_text: boolean; reason: string | null; file_checked: boolean
  latest_operation: TextRetryOperation | null; latest_file_restore: FileRestoreReceipt | null
}
export type RecoveryHistory = {
  text_retries: { operation: TextRetryOperation; candidate: {
    extraction_id: string; extraction_version: string; extractor_profile: string; status: string; error: string | null
    page_count: number; outcome: string; decision_code: string | null; diagnostic_only: boolean
  } | null }[]
  file_restores: FileRestoreReceipt[]; text_retries_truncated: boolean; file_restores_truncated: boolean
}
export type ExtractionOccurrence = {
  extraction_id: string | null; extraction_version: string | null; extractor_profile: string | null; outcome: string | null
  is_current: boolean; current_extraction_id: string | null
  input: { observation_id: string; integrity: string; observed_sha256: string | null } | null
  input_relation: 'input_matched_expected_hash' | 'input_differed_from_expected_hash' | 'input_not_recorded'
  retained_copy?: boolean; file_restored_after: boolean; latest_file_restore: FileRestoreReceipt | null
}
export type PassageFreshness = {
  compared: 'passage_identity'; semantic_support: 'not_checked'; dependencies: string[]
  affected: { passage_id: string; source_version_id: string; evidence_status: EvidenceStatus; passage_extraction_id: string | null; current_extraction_id: string | null; used_by: { kind: string; ref: string }[] }[]
  unresolved: { passage_id: string | null; reason: 'passage_missing' | 'unreadable_record'; used_by: { kind: string; ref: string }[] }[]
  file_restored_after: string[]
}
export type AssetText = {
  occurrence: ExtractionOccurrence | null
  asset: Asset
  passages: { id: string; kind: 'pdf_page'; text: string; physical_page: number | null; printed_label: string | null; extraction_version: string | null; payload_ref: string | null; text_source?: 'text_layer' | 'ocr' | 'marker' | 'latex_source'; equations_to_check?: number; source_equations?: string[] }[]
  source: Passage['source']
}
// A figure found from its caption on a PDF page (D58); its picture is cut from the page by the server.
export type AssetFigure = { page: number; label: string; width: number; height: number }
export type PdfCandidate = {
  id: string; provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'europepmc' | 'web_search'; candidate_url: string; landing_url: string | null
  version_label: string | null; license: string | null; identity_status: 'doi_verified' | 'title_verified' | 'unverified' | 'mismatch'
  version_status: 'match' | 'different' | 'uncertain'; access_status: 'not_attempted' | 'downloaded' | 'http_error' | 'not_pdf' | 'too_large' | 'timeout' | 'blocked_url' | 'wrong_type' | 'failed'
  http_status: number | null; error_code: string | null; final_url: string | null; discovered_at: string; attempted_at: string | null
}
export type PdfDiscovery = {
  provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'europepmc' | 'web_search'; query_text: string; status: string; result_count: number; other_title_count: number
  http_status: number | null; error_code: string | null; created_at: string; finished_at: string | null
}
export type PdfMatch = { filename: string; source_version_id: string | null; basis: 'doi' | 'title' | null }
// One version of a work a dropped file may go to (slice 18a): the person picks it; `proposed` is the version the match named.
export type WaitingVersion = {
  source_version_id: string; title: string; version_label: string | null; year: number | null; publication_type: string | null; doi: string | null; has_pdf: boolean; proposed: boolean
  // The person's own full-text decision on this version, and what attaching a file with text to it would lead to (slice 18b).
  person_decision: string | null; after_attach?: AttachOutcome
}
// What attaching a person's file leads to (slice 18b): a reading request, no reading (off, or the work is not read here),
// the person's decision standing, or a file with no text keeping the work on the waiting list.
export type AttachOutcome = 'requested' | 'model_off' | 'not_eligible' | 'decision_stands' | 'unreadable'
export type WaitingWork = { work_id: string; head: string; title: string; versions: WaitingVersion[]; versions_digest: string }
// An sw research's match: the proposed work (or none) and what the confirmation sends back to be checked (decision 5).
// With no proposal, `candidates` holds every work a file may go to here, for the person to choose from.
export type WaitingMatch = PdfMatch & { sha256: string; scope_revision: number; page_count: number | null; has_text_layer: boolean | null; work: WaitingWork | null; candidates?: WaitingWork[] }
// A work waiting for the person's PDF, in reading order (slice 18a). Links come through the institution's proxy when one is set.
export type WaitingRow = {
  work_id: string; head: string; source_version_id: string; reason_code: 'no_fulltext' | 'text_unreadable' | 'human_pdf_wrong' | string
  decided_by: string; place: number; title: string; year: number | null; venue: string | null; authors: string[]; doi: string | null
  links: { doi: string | null; landing: string | null }; find_pdf_source_version_id: string | null
  versions: WaitingVersion[]; versions_digest: string
}
export type WaitingView = { rows: WaitingRow[]; count: number; scope_revision: number; has_plan: boolean; via_proxy: boolean; order: 'fulltext_plan'; files: PersonFiles }
// A file the person added, and what became of it, read from the stored decisions and steps (slice 18b, decision 9).
export type PersonFileState = 'waiting' | 'reading' | 'included' | 'criterion_not_met' | 'your_decision' | 'unread' | 'changed' | 'model_off' | 'decision_stands' | 'not_eligible'
export type PersonFile = {
  work_id: string; head: string; source_version_id: string; asset_id: string; title: string; version_label: string | null
  filename: string | null; added_at: string; state: PersonFileState; request_id: string | null; attempt: number
  unread_reason: 'run_cancelled' | 'run_failed' | 'no_decision' | 'file_changed' | null; reason_code: string | null
  quotes: { part: string; quote: string; page: number | null; rendition?: boolean }[]; after_run: boolean; decided_code: string | null
}
export type PersonFiles = { rows: PersonFile[]; reading_on: boolean; paused_run: { id: string; kind: string; status: string; pause_reason: string | null } | null }
export type Source = {
  // A short author–year key such as "Nakano13", one per work across the library (D59); null only before it is given.
  source_version_id: string; work_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; venue: string | null
  volume: string | null; issue: string | null; pages: string | null
  doi: string | null; landing_url: string | null; version_label: string | null; publication_type: string | null
  cited_by_count: number | null; cited_by_count_at: string | null
  origin: 'provider' | 'user_upload'; added_by: string; added_at: string; rank: number | null; similarity: number | null
  found_in_revision: number | null; applicability: 'current' | 'stale_scope'; version_role: 'record' | 'other_version'
  // The other version of the work whose text answers read, when the record has no PDF text (D48).
  answer_reads_version_id: string | null
  // No version of the work is read by an answer: its only PDF text is a person's file not read yet (slice 18b).
  answer_reads_nothing: boolean
  // Whether an answer reads this version's PDF pages rather than its abstract (D49).
  has_pdf_text: boolean
  // Some of that text was read with OCR from scanned pages (D51).
  has_ocr_text: boolean
  access: { abstract_passage_id: string | null; abstract_origin: string | null; oa_pdf_url: string | null; oa_pdf_version: string | null; assets: Asset[]; replaced_assets: ReplacedAsset[]; fetch: { status: string; error_code: string | null; http_status: number | null } | null; other_copy: { status: string; error_code: string | null } | null; pdf_candidates: PdfCandidate[]; pdf_discoveries: PdfDiscovery[] }
  selection: { state: 'included' | 'excluded' | 'pending'; origin: 'default' | 'model_proposal' | 'code_rule' | 'user'; version: number; proposal: string | null; proposal_reason: string | null; proposal_basis: string | null; user_reason: string | null; queue_answer: 'include' | 'criterion_not_met' | null }
  cited_in_latest_answer: boolean
  provider_records: string[]; suspected_duplicates: { source_version_id: string; basis: 'same_title' | 'published_doi' }[]
}
export type Evidence = {
  passage_id: string; source_version_id: string; source_key: string | null; kind: 'abstract' | 'pdf_page' | 'section'; physical_page: number | null
  printed_label: string | null; reading_depth: string; title: string; version_label: string | null; anchor_text: string | null
  evidence_status: EvidenceStatus
  // null for abstracts; 'ocr' text was not checked against the page (D51); 'latex_source' holds the authors' LaTeX of
  // numbered display equations matched to the page by their numbers, from the arXiv source of this version (D104).
  text_source: 'text_layer' | 'ocr' | 'marker' | 'latex_source' | null
  removed_from_research: boolean  // the source was removed from this research later; the quote still opens (D50)
  // Europe PMC's open-access text drawn as a PDF by DEIXIS (SW21): its pages are not the publisher's.
  rendition?: boolean
}
export type Claim = {
  id: string; label: string; section: string | null; text: string; support_type: 'source_stated' | 'analyst_inference'; semantic_review: string; evidence: Evidence[]
  review: { verdict: Verdict; reason: string } | null
}
export type Limitation = { kind: string; text: string; source_ids: string[] }
export type ValidationIssue = { code: string; path: string; message: string }
export type Answer = {
  id: string; run_id: string; status: 'structurally_valid' | 'unverified_draft' | 'clarification' | 'no_evidence'
  scope_revision: number; applicability: 'current' | 'stale_scope' | 'stale_selection'; answer_language: string | null; created_at: string
  report_version: number | null; report_title: string | null
  claims: Claim[]; limitations: Limitation[]; unanswered_aspects: string[]; capability_notice: string | null
  clarification: { question: string; ambiguity: string; why_it_matters: string; options: string[] } | null
  unverified_draft: { claims?: { claim_label: string; text: string }[] } | null
  validation: { ok?: boolean; issues?: ValidationIssue[]; warnings?: ValidationIssue[]; note?: string; reason?: 'no_includable_source' }
  model: { connection: string; requested_model: string | null; resolved_model: string | null; token_usage: unknown } | null
  inputs_given: { sources: number; passages: number; source_ids: string[] } | null
  source_text_changed: boolean  // a file or extraction this answer read is no longer in use (D45)
  // Where the flow stood when this sw answer's run started (slice 20); null when that run kept none, and in legacy.
  start_snapshot?: AnswerStartSnapshot | null
  review: AnswerReview | null
}
// Slice 20, decision 1: every work of the revision in one bucket, from the person's decisions first.
export type FlowBucket = 'confirmed' | 'person_not_met' | 'person_excluded' | 'look_again' | 'included' | 'not_met' | 'queued'
  | 'person_unsure' | 'waiting_for_pdf' | 'not_read_yet' | 'candidate_not_fetched' | 'abstract_open' | 'abstract_not_read'
  | 'survey' | 'out_of_scope_model' | 'out_of_scope_code' | 'not_screened' | 'other'
export type FlowCounts = {
  works: number; buckets: Record<FlowBucket, number>; other_reasons: Record<string, number>
  five: { included: number; included_by_agreement: number; confirmed: number; not_met: number; waiting_for_pdf: number
    queued: number; not_read: number; not_read_in_reading: number; not_read_not_tried: number }
  look_again_in_answer: number; queue_by_reason: Record<string, number>
}
export type FlowBoxes = { flow_status: 'incomplete_no_human_screening'; revision: number
  boxes: { key: string; count: number | null; flow_status: 'incomplete_no_human_screening' }[] }
export type OverrideClass = 'overruled' | 'agreed' | 'settled_open' | 'time_unknown'
export type Overrides = {
  decisions: number; changed: number; changed_by: { code: number; model_agreement: number }
  classes: Record<OverrideClass, number>; by_path: Record<'queue' | 'audit' | 'list', Record<OverrideClass, number>>
  overruled: { path: string; decided_by: string; stage: string; direction: string; count: number }[]
  apart: { not_sure: number; pdf_wrong: number; look_again: number }
}
export type AnswerStartSnapshot = {
  scope_revision: number; selection_revision: number; flow: FlowCounts; included: number
  included_without_answer_text: number; included_state_changed: boolean
}
export type Counts = {
  found: number; unique: number; included: number; excluded: number; pending: number; inspected: number; cited: number
  // Works the user removed from this research, and those of them a later search found again; neither is listed (D50).
  removed: number; removed_found_again: number
  // An sw research's human queue: open rows, and decisions made under an earlier criterion (slice 16). Absent in legacy.
  queue?: number; look_again?: number
  // An sw research's works waiting for the person's PDF (slice 18a). Absent in legacy.
  waiting_for_pdf?: number
  // Slice 20: the flow buckets, the PRISMA 2020-style boxes and the override count; null in legacy.
  flow?: FlowCounts | null; flow_boxes?: FlowBoxes | null; overrides?: Overrides | null
}
// The audit sample of an sw research (slice 20, decisions 5–7): F1 / F2 answered here, A1 / A2 for viewing only.
export type AuditAnswer = 'include' | 'criterion_not_met' | 'not_sure' | 'pdf_wrong'
export type AuditRow = {
  work_id: string; head: string; source_version_id: string; title: string; year: number | null; doi: string | null
  version_label: string | null; publication_type: string | null; stratum: 'F1' | 'F2'; kind: 'audit_include' | 'audit_not_met'
  question: string; machine: { decision_id: string; reason_code: string; decided_by: string }
  answered: { decision_id: string; reason_code: string; answer: AuditAnswer; note: string | null; created_at: string; stale: boolean } | null
  audit_token: string
}
export type AuditAbstractRow = {
  work_id: string; head: string; source_version_id: string; title: string; year: number | null; doi: string | null
  version_label: string | null; publication_type: string | null; stratum: 'A1' | 'A2'; reason_code: string; decided_by: string
  quotes: { run_no: number; label: string; quote: string | null; quote_verified: boolean | null }[]
  selection: { state: Source['selection']['state'] | null; origin: string | null; version: number | null }
}
export type AuditView = {
  revision: number; per_stratum: number
  fulltext: Record<'F1' | 'F2', { size: number; sample_size: number; rows: AuditRow[]; answered: number; differs: number }>
  earlier: { work_id: string; source_version_id: string; title: string; stratum: 'F1' | 'F2' | null; answer: AuditAnswer
    reason_code: string; created_at: string; in_sample: boolean; differs: boolean }[]
  earlier_counts: Record<'F1' | 'F2', { answers: number; differs: number }>
  abstract: Record<'A1' | 'A2', { size: number; rows: AuditAbstractRow[] }>
}
export type AuditRowView = { row: AuditRow | AuditAbstractRow | null; detail: QueueDetail & { cues: unknown } | null }
export type AuditResult = { row: AuditRow | null; selection: QueueAnswerResult['selection']; undo_token: string | null }
export type EffortLimits = { search_workflow: 'sw' | 'legacy'
  efforts: Record<'quick' | 'standard' | 'detailed', { read: number; abstracts: number; fetch: number; reads: number; runs: number
    chain_seeds: number; chain_abstracts: number; passages: number }> | null }
// The human queue of an sw research (slice 16, D96). Rows are derived from stored decisions each time they are read.
export type QueueKind = 'confirm_quote' | 'choose_run' | 'choose_version' | 'confirm_pdf' | 'confirm_absent' | 'find_part' | 'confirm_results' | 'look_again'
export type QueueAnswer = 'include' | 'criterion_not_met' | 'not_sure' | 'pdf_wrong' | 'pdf_confirmed'
export type QueueRow = {
  source_version_id: string; head: string; work_id: string; title: string; year: number | null; doi: string | null
  version_label: string | null; publication_type: string | null; reason_code: string; kind: QueueKind
  question: { part: string; definition: string | null } | null; place: number | null; arm: 'keyword' | 'chain'
  stale: boolean; decision_id: string; row_token: string
}
export type QueueCounts = {
  open: number; by_kind: Record<string, number>; by_reason: Record<string, number>; look_again: number
  decided: Record<string, number>; user_selected: number
}
// A work the person decided and can still take back (slice 17): its fresh human decision or its PDF confirmation.
export type QueueDecided = {
  work_id: string; source_version_id: string; head: string; title: string; version_label: string | null
  reason_code: string; answer: QueueAnswer; note: string | null; created_at: string
  // No token when the undo would be refused: a PDF confirmation whose reading has begun.
  undo_token: string | null; undo_blocked: 'reading_started' | null
}
export type QueueView = { rows: QueueRow[]; counts: QueueCounts; order: 'fused_rank'; decided: QueueDecided[] }
export type QueuePart = {
  part: string; label: 'present' | 'absent' | 'unclear'; quote: string | null; quote_verified: boolean | null
  page: number | null; passage: string | null; rationale: string | null
  // The passage that opens this quote's page, and the page's own text a verified quote was found as: the only span
  // the screen marks. Null for an unverified quote; a fuzzy match is never an anchor.
  passage_id: string | null; anchor_text: string | null; rendition?: boolean
  closest?: { page: number; text: string; kind: 'exact' | 'normalized' | 'fuzzy'; ratio: number; passage_id: string | null; rendition?: boolean } | null; closest_note?: string | null
}
export type QueueRun = { run_no: number; shown_pages: number[]; parts: QueuePart[] }
export type QueueDetail = {
  runs: QueueRun[]
  cues: { phrases: string[]; sentences: { page: number; sentence: string; passage_id: string | null; rendition?: boolean }[]; total: number; note: string | null }
  asset_id: string | null  // the file in use for the row's version
  rendition?: boolean  // that file is Europe PMC's text drawn by DEIXIS (SW21)
  // A `choose_version` row: every version with a fresh full-text decision, the named one first.
  versions?: { source_version_id: string; title: string; version_label: string | null; asset_id: string | null
    decision: { id: string; reason_code: string; outcome: string; decided_by: string }; runs: QueueRun[] }[]
  identity?: { first_page: string | null; work_title: string; work_doi: string | null; asset_id: string | null; retrieved_from: string | null; page_count: number | null }
}
export type QueueDecision = { id: string; reason_code: string; decided_by: 'code' | 'model_agreement' | 'human'; stale: boolean; undoable: boolean }
export type QueueRowView = { row: QueueRow | null; decision: QueueDecision | null; undo_token: string; detail?: QueueDetail }
export type QueueAnswerResult = {
  row: QueueRow | null; decision: QueueDecision | null; undo_token: string
  selection: { source_version_id: string; state: Source['selection']['state']; origin: Source['selection']['origin']; version: number } | null
}
export type ResearchView = {
  research: { id: string; title: string; current_scope_revision: number; version: number; created_at: string; updated_at: string; read_only_reason: string | null }
  scope: Scope; runs: Run[]; search_runs: SearchRun[]; sources: Source[]; answers: Answer[]; counts: Counts; last_event_id: number
  reportRuns: ReportSummary[]
  // null for a legacy research (slice 19).
  probes?: Probes | null
  // The reviewer the next answer gets: the research's own setting, else the app-wide default. model null: no review.
  reviewer: { mode: ReviewMode; connection: string | null; model: string | null; reasoning_effort: string | null }
  // The semantic search arm for the current revision (slice 21). Carries no count of what will be sent.
  semantic?: SemanticArm
}
export type SemanticArm = {
  provider: SemanticSearchProvider; stored_model: string | null; arm: 'on' | 'off' | 'english_question_missing' | 'not_installed'
  english_question: { text: string; origin: 'user' | 'question' } | null; needs_english_question: boolean
}
export type ResearchSummary = {
  id: string; title: string; question: string; version: number; source_scope: SourceScope; effort: Effort; last_run_status: RunStatus | null
  last_run_kind: RunKind | null
  answer_count: number; followup_new: number; created_at: string; updated_at: string
}
export type TrashedResearch = { id: string; title: string; trashed_at: string }
// The Trash page's groups (D50); a trashed research's tables and removed sources go and come back with it and are not listed.
export type TrashedTable = { id: string; title: string; research_id: string; research_title: string; version: number; trashed_at: string; rows: number; columns: number; cells: number; human_edits: number }
export type RemovedSource = {
  source_version_id: string; work_id: string; title: string; version_label: string | null; year: number | null; research_id: string; research_title: string
  removed_at: string; removal_note: string | null; found_again_at: string | null; quotes: number; cells: number
  // What the source sheet opens for this row. A former member's PDF opens only where this research cites it (D50), so the
  // abstract is what the Trash can inspect; null when no abstract is stored.
  abstract_passage_id: string | null
  cited: number  // 1 when an answer quote, a table or a report still cites the source anywhere; it cannot be deleted then (D65)
}
export type TrashedTemplate = { id: string; name: string; trashed_at: string; columns: number }
export type Trash = { researches: TrashedResearch[]; tables: TrashedTable[]; sources: RemovedSource[]; templates: TrashedTemplate[] }
export type Passage = {
  occurrence: ExtractionOccurrence | null
  id: string; kind: Evidence['kind']; text: string; physical_page: number | null; printed_label: string | null
  abstract_origin: string | null; extraction_version: string | null; payload_ref: string | null; text_source?: 'text_layer' | 'ocr' | 'marker' | 'latex_source'; equations_to_check?: number
  // The equation numbers placed from the arXiv source in this passage (D104); empty outside a 'latex_source' passage.
  source_equations?: string[]
  reading_depth: string; asset_id: string | null
  // Europe PMC's open-access text drawn as a PDF by DEIXIS (SW21): its pages are not the publisher's.
  rendition?: boolean
  evidence_status: EvidenceStatus
  removed_from_research: boolean
  source: { id: string; work_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; venue: string | null; doi: string | null; landing_url: string | null; version_label: string | null; origin: string; cited_by_count: number | null; cited_by_count_at: string | null }
}
export type ModelOption = {
  id: string; display_name: string; is_default: boolean; description?: string
  resolved_model?: string | null
  default_reasoning_effort?: string | null; reasoning_efforts?: { id: string; description: string }[]
}
export type ModelHealth = {
  connection: string; ready: boolean; reason?: string | null; installed?: boolean; cli_version?: string; signed_in?: boolean; key_configured?: boolean
  account_type?: string | null; plan_type?: string | null; models?: ModelOption[]
  isolation?: { instruction_sources: number; live_mcp_servers: string[] }
}
export type Connections = { models: Record<string, ModelHealth>; providers: { id: string; implemented: boolean; access_mode: string | null; supplementary?: boolean; role?: string; note: string }[] }
export type Keychain = { available: boolean; name: string | null }
export type KeyEntry = { env: string; group: 'model' | 'source'; service: string; configured: boolean; source: 'keychain' | 'dotenv' | 'environment' | null; testable: boolean }
export type Credentials = { keychain: Keychain; keys: KeyEntry[] }
export type KeyTest = { status: 'ok' | 'no_credit' | 'rejected' | 'failed'; detail: string; checked_at: string }
export type LocalToolModel = { id: string; size_bytes: number | null; embedding: boolean }
export type LocalToolInstall = { command: string; available: boolean; unavailable_reason: string | null; url: string }
export type LocalToolJob = { status: 'running' | 'succeeded' | 'failed' | 'cancelled'; started_at: string; finished_at: string | null; output: string } | null
export type LocalTool = {
  id: 'claude_code' | 'codex' | 'gemini_cli' | 'ollama' | 'lm_studio' | 'zotero'; name: string; kind: 'cli' | 'server' | 'app'
  installed: boolean; version: string | null; path: string | null; role: 'runs_steps' | 'detected' | 'imports'
  running?: boolean; endpoint?: string; models?: LocalToolModel[]; local_api?: boolean; web_configured?: boolean
  install: LocalToolInstall; job: LocalToolJob
}
// The optional equation reader (Marker, D52), installed under the data directory.
export type EquationReader = {
  installed: boolean; package: string; path: string; size_bytes: number; models_downloaded: boolean; disk_free_gb: number
  install: { available: boolean; unavailable_reason: string | null; url: string }
  job: { status: 'running' | 'succeeded' | 'failed' | 'cancelled'; step: number; steps: number; started_at: string; finished_at: string | null; output: string } | null
  reading: { asset_id: string; title: string | null; pages: number; started_at: string } | null
  pdfs: Partial<Record<'read' | 'no_math' | 'failed' | 'reading' | 'pending', number>>
}
export type LocalTools = { machine: { chip: string | null; memory_gb: number | null; disk_free_gb: number | null }; tools: LocalTool[] }
export type SemanticSearchProvider = 'gemini' | 'builtin' | 'openai' | 'ollama' | 'lm_studio' | 'off'
export type SemanticSearchOption = {
  provider: SemanticSearchProvider; models: string[]; available: boolean; reason: string | null
  // The built-in model only (slice 21): why it cannot be chosen, and the last full sha256 check of its files.
  reason_code?: string | null; last_full_check?: { at: string; passed: boolean } | null
}
// The built-in embedding model (slice 21), installed on request under the data directory.
export type BuiltinEmbeddingJob = {
  status: 'running' | 'succeeded' | 'failed' | 'cancelled' | 'remove_failed'; step: number; steps: number; step_name: string | null
  started_at: string | null; finished_at: string | null; pid?: number; bytes_done?: number; bytes_total?: number; output: string
}
export type BuiltinEmbedding = { status: 'unsupported_platform' } | {
  status: 'not_installed' | 'installing' | 'installing_elsewhere' | 'ready' | 'failed' | 'files_do_not_match' | 'removing' | 'remove_failed'
  installed: boolean; available: boolean; last_full_check: { at: string; passed: boolean } | null; job: BuiltinEmbeddingJob | null
  model: { name: string; id: string; repository: string; revision: string; package: string }
  sizes: { runtime_bytes: number; model_bytes: number; python_bytes: number }
  path: string; size_bytes: number; uv: { available: boolean; reason: string | null; url: string }
}
export type SemanticSearch = { provider: SemanticSearchProvider; model: string | null; explicit: boolean; options: SemanticSearchOption[] }
export type InstitutionalAccess = { status: 'institutional' | 'none' | 'unknown' | 'not_checked'; via?: string; reason?: string }
// Reading depth of a stored source version: a PDF text layer, an abstract, or bare metadata.
export type AccessLevel = 'pdf_available' | 'abstract' | 'metadata'
export type LibraryVersion = { source_version_id: string; version_label: string | null; year: number | null; venue: string | null; access_level: AccessLevel }
export type LibraryResearch = { id: string; title: string; updated_at: string }
export type LibraryEntry = {
  work_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; venue: string | null
  publication_type: string | null; doi: string | null; landing_url: string | null
  cited_by_count: number | null; cited_by_count_at: string | null; access_level: AccessLevel
  versions: LibraryVersion[]; researches: LibraryResearch[]; first_research_id: string | null; newest_source_at: string
}
export type LibraryView = { entries: LibraryEntry[]; researches: LibraryResearch[]; counts: { works: number; versions: number; researches: number } }
export type LibraryAddition = { work_id: string; research_id: string; source_version_id: string; access_level: AccessLevel; library: LibraryView }
export type LibraryWorkVersion = {
  source_version_id: string; version_label: string | null; year: number | null; venue: string | null
  doi: string | null; landing_url: string | null; publication_type: string | null; authors: string[]
  cited_by_count: number | null; added_at: string; access_level: AccessLevel
  abstract: string | null; abstract_origin: string | null; abstract_passage_id: string | null
  asset: { id: string; page_count: number | null; original_filename: string | null; extraction_status: string } | null
  // A research that holds this version now, and — when none does — the one it was removed from, which still opens its text (D50).
  research_id: string | null; removed_research_id: string | null
}
export type LibraryWork = {
  work_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; venue: string | null
  doi: string | null; landing_url: string | null; publication_type: string | null; cited_by_count: number | null
  versions: LibraryWorkVersion[]; researches: LibraryResearch[]
}
export type QuickFindResult = {
  researches: { id: string; title: string; question: string; updated_at: string }[]
  sources: { source_version_id: string; title: string; year: number | null; version_label: string | null; research_id: string; research_title: string }[]
}
export type ActivityEvent ={ id: number; type: string; run_id: string | null; payload: Record<string, unknown>; created_at: string }
export type ZoteroSource = 'local' | 'web'
export type ZoteroCollection = { key: string; name: string }
// note is an English template keyed in i18n; vars fill its {placeholders}.
export type ZoteroNote = { title: string; note: string; vars?: Record<string, string> }
export type ZoteroImport = { items: number; pdfs_added: number; notes: ZoteroNote[] }

// Evidence tables (P5, D37/D38). Types mirror backend/deixis/workflow/tables.py.
export type AnswerFormat = 'choice' | 'number_unit' | 'yes_no' | 'text'
export type CellState = 'value' | 'unknown' | 'not_reported' | 'not_verified' | 'not_applicable' | 'inaccessible' | 'not_found_in_inspected_scope'
export type ColumnOption = { id: string; label: string }
export type ColumnSpec = {
  name: string; instruction: string; answer_format: AnswerFormat
  // A new option has no id; an existing option keeps its id across column revisions.
  options: { id?: string | null; label: string }[] | null; allow_multiple: boolean; unit_hint: string | null
}
export type TableColumn = {
  lineage_role: 'problem' | 'change' | 'uncertainty' | null
  id: string; position: number; revision: number; version: number; origin: 'user' | 'model_suggestion' | 'template'; accepted_by: 'automatic' | null
  name: string; instruction: string; answer_format: AnswerFormat; options: ColumnOption[] | null; allow_multiple: boolean; unit_hint: string | null
}
export type TableRow = {
  source_version_id: string; work_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; version_label: string | null
  selection_state: 'included' | 'excluded' | 'pending' | null; added_by: 'included_at_creation' | 'user'; added_at: string; removed_at: string | null
  access_level: 'pdf_available' | 'abstract' | 'metadata'
}
export type CellValue = { option_ids?: string[]; number?: number; unit?: string | null; as_stated?: string | null; answer?: 'yes' | 'no'; text?: string }
export type CellEvidence = {
  passage_id: string; anchor_text: string | null; anchor_match: 'exact' | 'normalized' | 'fuzzy' | null; kind: Evidence['kind']
  physical_page: number | null; printed_label: string | null; asset_id: string | null; evidence_status: EvidenceStatus
  text_source: 'text_layer' | 'ocr' | 'marker' | 'latex_source' | null
}
export type CellRevision = {
  id: string; kind: 'model_fill' | 'model_proposal' | 'system_fill' | 'human_edit' | 'accept_proposal' | 'dismiss_proposal'
  author: 'model' | 'human' | 'system'; based_on_revision_id: string | null; column_revision: number; state: CellState | null
  value: CellValue | null; note: string | null; reading_depth: 'metadata' | 'abstract' | 'selected_sections' | 'full_text' | null
  output_status: 'structurally_valid' | 'unverified_draft' | null; cell_version_at_request: number | null; scope_revision: number | null
  run_id: string | null; created_at: string; model: { connection: string | null; resolved_model: string | null } | null; evidence: CellEvidence[]
  decision?: 'accepted' | 'dismissed' | 'pending' | 'superseded'  // model proposals in a cell's history
}
export type CellFlag = 'stale_column' | 'pdf_removed' | 'pdf_replaced' | 'text_superseded' | 'proposal_before_edit' | 'proposal_invalid' | 'ocr_numbers_unchecked'
export type CellSummary = {
  cell_id: string | null; column_id: string; source_version_id: string; version: number
  current: CellRevision | null; pending_proposal: CellRevision | null; flags: CellFlag[]
}
export type CellView = CellSummary & { revisions: CellRevision[] }
export type ColumnSuggestion = Omit<ColumnSpec, 'options'> & { options: { label: string }[] | null; rationale: string }
export type TableView = {
  table: { id: string; research_id: string; title: string; template_id: string | null; version: number; created_at: string; updated_at: string }
  columns: TableColumn[]; rows: TableRow[]; removed_rows: TableRow[]; cells: CellSummary[]
  counts: { rows: number; columns: number; with_value: number; empty: number; pending_proposals: number }
  fill_estimate: { sources: number; sources_without_text: number; sources_beyond_limit: number; model_calls: number; max_model_calls: number }
  column_suggestions: { run_id: string; step_id: string; columns: ColumnSuggestion[]; notes: string } | null
}
export type TableSummary = { id: string; title: string; version: number; created_at: string; updated_at: string; rows: number; columns: number; access: { pdf_available: number; abstract: number; metadata: number }; auto_columns: number
  report_ready: { ready: boolean; cells_left: number; cells_total: number; failed_rows: number; can_continue_with_failed: boolean; failed_cells: number; included_rows: number } }
export type ReportSummary = { id: string; status: 'in_progress' | 'valid' | 'draft'; report_version: number | null; created_at: string }
export type ReportLink = { link_id: string; passage_id: string | null; cell_id: string | null; source_version_id: string; ref_number: number; open_passage_id: string | null
  anchor_text: string | null; anchor_match: 'exact' | 'normalized' | 'fuzzy' | null }
export type ReportClaim = { id: string; claim_key: string; version: number; text: string; model_text: string; edited: boolean
  warnings: { kind: string; detail?: string }[]; revisions: { id: string; kind: 'human_edit' | 'human_restore'; restored_from: string | null; text: string; note: string | null; created_at: string; warnings: { kind: string; detail?: string }[]; link_count: number | null; link_ids: string[] | null; changes_current: boolean }[]
  support_type: 'source_stated' | 'analyst_inference'; paragraph: number; table_ref: string | null; equation_ref: string | null; evidence: ReportLink[]
  original_evidence_count: number; removed_links: (Pick<ReportLink, 'link_id' | 'passage_id' | 'cell_id' | 'source_version_id' | 'anchor_text' | 'anchor_match'> & { title?: string; source_key?: string | null })[]
  evidence_basis: 'direct' | 'none'; support_type_note: 'model_written_type' | null; edited_basis: string[] }
export type EditCheck = { id: string; created_at: string; checker_version: string; current: boolean; errors: number; warnings: number; skipped: number; edited_claims: number
  items: { rule: string; section_id: string | null; detail: string; severity: 'error' | 'warning' }[]
  skipped_rules: { rule: string; section_id: string | null; claim_key: string | null; reason: string }[]; rules_run: string[]; not_checked: string[] }
export type ReportSection = { section_id: string; status: string; word_count: number | null; draft: { text?: string; insufficient_evidence?: { reason: string }[] } | null
  validation: { issues?: { code?: string }[] } | null; claims: ReportClaim[]; evidence_changes: { open: { key: string; kind: string; via: string; source_version_id?: string; column_id?: string }[]; acknowledged_count: number; unresolved_refs: number } }
export type ReportReview = { status: 'reviewed'; step_input_id: string; sections_reviewed: string[]; sections_not_reviewed: { section_id: string; reason: string }[]
  findings: { claim_key: string | null; sentence_id: string | null; section_id: string | null; code: string; text: string }[]; notes: string
  reverted: { sentence_id: string; section_id: string }[]; not_reverted: { sentence_id: string; section_id: string; reason: string }[] }
  | { status: 'not_reviewed'; reason: string; detail: unknown; sections_reviewed: string[]; sections_not_reviewed: { section_id: string; reason: string }[]
    findings: []; notes: string; reverted: []; not_reverted: [] }
export type ReportDetail = ReportSummary & { language: string; updated_at: string; sections: ReportSection[]; edited_after_version: number | null; has_human_edits: boolean; edit_check: EditCheck | null; review: ReportReview | null
  passage_freshness: PassageFreshness
  missing_rows: { counts: { included: number; completed: number; failed: number; cells_missing: number; cells_total: number }
    failed_rows: { source_version_id: string; source_key: string | null; title: string; reason: string; missing_columns: { column_id: string; name: string; reason: string }[] }[] } | null
  evidence_changes: { any: boolean; changed_cells: number; removed_sources: number; added_sources: number; revised_columns: number; not_checked: string[] }
  references: { number: number; source_version_id: string; source_key: string | null; title: string; authors: string[]; year: number | null; venue: string | null; doi: string | null; version_label: string | null; open_passage_id: string | null }[]
  table_i: { columns: { column_id: string; name: string; answer_format: AnswerFormat; options: ColumnOption[] | null }[]; rows: { source_version_id: string; ref_number: number | null; source_key: string | null; title: string | null; failed?: boolean }[]
    cells: { cell_id: string; column_id: string; source_version_id: string; state: CellState; value: CellValue | null; evidence_passage_ids: string[] }[] } | null
  run: { id: string; status: RunStatus; pause_reason: string | null; error?: { rule: string; section_id: string | null; detail: string }[] | null } | null }
export type TableTemplate = { id: string; name: string; columns: ColumnSpec[]; created_at: string }
export type CellEdit = { state: CellState; value: CellValue | null; note: string | null; keep_evidence_from: string | null; expected_version: number }

export type CandidateStatus = 'not_run' | 'undecided' | 'narrowed' | 'closed' | 'open'
export type CandidateCounts = { found: number; kept: number; rank_cut: number; duplicates: number }
export type CandidateDepth = 'abstract' | 'stored_passages' | 'metadata_only'
export type CandidateComputed = {
  status: CandidateStatus; reason: string; reasons: string[]; warnings: string[]
  facts: CandidateCounts & { assessed: number; unread: number; queries_total: number; queries_succeeded: number; queries_failed: number; queries_unknown: number; reading_depths: Record<CandidateDepth, number> }
}
export type CandidateOwnerDecision = { id: string; candidate_version_id: string; status: CandidateStatus; reason: string; created_at: string }
export type CandidateRunRef = { id: string; kind: RunKind; status: RunStatus; pause_reason: string | null; error_code: string | null }
export type CandidateElementKind = 'mechanism' | 'condition' | 'outcome' | 'parameter'
export type CandidateVersion = {
  id: string; candidate_id: string; version: number; claim_statement: string; conditions: string[]; nearest_simple_explanation: string | null
  critical_assumption: string; validation_plan: string; origin: 'model_decomposition' | 'human_edit'; step_input_id: string | null; created_at: string
  elements: { id: string; candidate_version_id: string; position: number; text: string; kind: CandidateElementKind }[]
}
export type CandidateSearchOutcome = 'running' | 'paused' | 'completed' | 'failed' | 'stopped'
export type CandidateSearchRef = { id: string; candidate_version_id: string; run_id: string; outcome: CandidateSearchOutcome; created_at: string; version: number; counts: CandidateCounts }
export type CandidateListItem = {
  id: string; origin: 'owner_text' | 'report_gap'; origin_report_id: string | null; origin_gap_row_id: string | null; gap_kind: string | null
  origin_changed: boolean; current_version: number; trashed_at: string | null; claim_statement: string | null
  status: CandidateComputed | null; owner: CandidateOwnerDecision | null; active_run_id: string | null
}
type CandidateBasisItem = { id: string; missing: true } | { id: string; text: string }
export type CandidateCard = Omit<CandidateListItem, 'claim_statement' | 'status' | 'owner' | 'active_run_id'> & {
  research_id: string; origin_text: string; origin_basis: Record<string, unknown>
  origin_basis_view: { basis_cell_ids?: CandidateBasisItem[]; basis_passage_ids?: (CandidateBasisItem & { source_version_id?: string })[]; basis_claim_keys?: CandidateBasisItem[] }
  origin_provenance: { origin?: 'code' | 'model'; section_id?: string; step_input_id?: string | null }
  origin_fingerprint: string | null; created_at: string; versions: CandidateVersion[]; current_version_id: string | null
  owner_decisions: CandidateOwnerDecision[]; searches: CandidateSearchRef[]
  status: { computed: CandidateComputed; previous: CandidateComputed | null; owner: CandidateOwnerDecision | null } | null
  active_run: CandidateRunRef | null; runs: CandidateRunRef[]; decompose_budget: { max_model_calls: number; max_provider_requests: number }
}
export type CandidateOpen = { origin: 'owner_text'; text: string } | { origin: 'report_gap'; report_id: string; gap_row_id: string }
export type CandidateEdit = {
  claim_statement: string; conditions: string[]; elements: { text: string; kind: CandidateElementKind }[]
  nearest_simple_explanation: string | null; critical_assumption: string; validation_plan: string; expected_version: number
}
export type CandidatePlan = {
  candidate_id: string; candidate_version_id: string; version: number; scope_revision: number; providers: string[]
  model: { kill_search_query: [string, string, string | null]; claim_assessment: [string, string, string | null] }
  budget: { max_model_calls: number; max_provider_requests: number; steps: { kill_search_query: number; claim_assessment: number; assessment_works: number } }
  transport: { providers: { provider: string; requests_per_search: number; rate_limit_retries: number; transient_attempts: number; per_query: number }[]; max_provider_requests: number }
  limits: { queries: number; records: number; keep: number; max_message_chars: number; basis_items: number; basis_text_chars: number; abstract_chars: number; page_passages: number; page_text_chars: number }
  skill_package_hash: string; plan_version: number; preview_fingerprint: string
}
export type CandidateRelation = 'explicit_support' | 'reasoned_inference' | 'partial_match' | 'no_match_in_supplied_text' | 'uncertain'
export type CandidateAlignment = 'aligned' | 'different_conditions' | 'unclear'
export type CandidateCell = { id: string; kill_search_id: string; element_id: string; source_version_id: string; relation: CandidateRelation; condition_alignment: CandidateAlignment | null; note: string | null }
export type CandidateQuote = { id: string; kill_search_id: string; source_version_id: string; element_id: string | null; matrix_cell_id: string | null; evidence_kind: 'abstract' | 'passage'; passage_id: string | null; quote: string }
export type CandidateSource = { title: string; year: number | null; venue: string | null; doi: string | null; version_label: string | null }
export type CandidateHit = {
  source_version_id: string; reading_depth: CandidateDepth; assessment_state: 'pending' | 'assessed' | 'insufficient_access' | 'not_assessed_budget'
  work_relevance: 'unrelated' | 'related' | 'uncertain' | null; note: string | null; rank: number; states_whole_claim: boolean | null; source: CandidateSource
}
export type CandidateQuery = { position: number; provider: string; query_text: string; status: 'succeeded' | 'failed' | 'outcome_unknown'; record_count: number; error_code: string | null }
export type CandidateMatrix = {
  search: CandidateCounts & { id: string; candidate_version_id: string; run_id: string; outcome: CandidateSearchOutcome; hits_recorded: boolean; created_at: string
    query_block: { setting: { kind: string; term: string; why: string }[]; setting_backup: { term: string }[]; task: { kind: string; term: string; why: string }[]; task_backup: { term: string }[] }
    rendered_queries: { provider_id: string; query_text: string; rationale: string; dropped_terms?: string[] }[]; skipped_terms: string[]
    selection: Pick<CandidatePlan, 'model' | 'providers' | 'budget' | 'transport'> }
  queries: CandidateQuery[]; counts: CandidateCounts; hits: CandidateHit[]; cells: Record<string, Record<string, CandidateCell>>; evidence: CandidateQuote[]
  summary: { failure_code: string | null; counts: CandidateCounts; queries: Omit<CandidateQuery, 'query_text'>[]
    hits: { source_version_id: string; reading_depth: CandidateDepth; outcome: string; reason: string | null; omitted: { page_limit?: number; message_size?: number } }[]
    usage: { model_calls: number; provider_requests: number }; budget: CandidatePlan['budget']; frozen_reading_depth: boolean } | null
  search_status: CandidateComputed; candidate_version_id: string; version: number; kill_search_id: string; is_latest_search_of_version: boolean
}
export type CandidateEvidence = {
  source: CandidateSource & { source_version_id: string }
  passages: { passage_id: string; source_id: string; text: string; reading_depth: string; locator: { kind: string; physical_page: number | null; printed_label: string | null }; abstract_origin: string | null; text_source: string | null }[]
  quotes: CandidateQuote[]
}
export type ReportGap = { id: string; gap_id: string; kind: string; text: string }

export type ReviewFocus = 'source_support' | 'assumptions_and_consistency'
export type ReviewTargetKind = 'answer' | 'report' | 'candidate'
export type ReviewRequest = {
  target_kind: ReviewTargetKind; target_id: string; focus: ReviewFocus; owner_note: string | null
  connection: string; model: string; reasoning_effort: string | null
}
export type ReviewNotReviewed = { claim_ref: string | null; section_ref: string | null; source_id?: string | null; reason: string; request_chars?: number | null; group_index?: number }
export type ReviewPreview = {
  claim_count: number; passage_count: number; characters_to_be_sent: number; logical_steps: number
  element_count: number; matrix_source_count: number
  steps_with_repair_bound: number; total_send_bound: number; estimated_input_tokens_per_group: number[]
  estimated_input_tokens_total: number; cost_estimated: false; not_reviewed: ReviewNotReviewed[]
  snapshot_sha256: string; preview_fingerprint: string; connection: string; connection_display_name: string
}
export type ReviewGroup = { group_index: number; group_count: number; claim_refs: string[]; source_ids?: string[]; request_chars: number; passage_count: number }
export type ReviewState = RunStatus | 'partial'
export type ReviewCard = {
  id: string; run_id: string; state: ReviewState; pause_reason: string | null; failure_reason: string | null; outcome_unknown: boolean
  requested_model: { connection: string; model: string; reasoning_effort: string | null }
  created_at: string; finding_count: number; open_finding_count: number
}
export type ReviewTargetRef = { kind: 'claim' | 'section' | 'whole' | 'cell' | 'candidate_element' | 'candidate_source'; ref: string | null }
export type ReviewEvidence = { passage_id: string; source_version_id: string; anchor_text: string; anchor_match: 'exact' | 'normalized' }
export type ReviewResolvedTarget = {
  target_ref: ReviewTargetRef; target: { kind: string; ref: string | null; record_id: string | null; text_at_snapshot: string | null }
  group_index: number; group_count: number
}
export type ReviewFindingKind = 'unsupported' | 'partially_supported' | 'overstated' | 'missing_context' | 'inconsistent' | 'assumption_unstated' | 'other'
export type ReviewFinding = ReviewResolvedTarget & {
  kind: ReviewFindingKind; evidence: ReviewEvidence[]; rationale: string; possible_impact: string; suggested_fix: string | null; uncertainty: string
}
export type ReviewDecision = { id: string; ordinal: number; decision: 'accepted' | 'dismissed' | 'deferred'; reason: string | null; applied_ref: string | null; created_at: string }
export type ReviewFindingRow = {
  id: string; ordinal: number; finding: ReviewFinding; current_decision: ReviewDecision | null; decision_history: ReviewDecision[]
  written_against_earlier_text: boolean; dependency_fingerprint: string | null
}
export type ReviewDetail = ReviewCard & {
  focus: ReviewFocus; owner_note: string | null; skill_package_hash: string | null; assessment_notice: string
  snapshot: {
    id: string; target_kind: ReviewTargetKind; target_id: string; content_sha256: string; created_at: string; scope_revision: number
    elements?: { element_ref: string; position: number; kind: string }[]
    candidate_version?: number; candidate_id?: string; kill_search_id?: string
    matrix_sources?: { source_id: string; rank_key: number }[]
    passages?: { passage_id: string; source_id: string; locator: { kind: string; physical_page?: number | null; printed_label?: string | null }; text: string }[]
    claims: { claim_ref: string; section_ref: string | null }[]
    sources: { source_id: string; title: string; year: number | null; version_label: string | null; reading_depth: string }[]
    cells: { cell_id: string; column_id: string; column_name: string; source_version_id: string }[]
    columns: { column_id: string; name: string }[]
  }
  groups: (ReviewGroup & { coverage: 'reviewed' | 'not_reviewed' | 'pending'; not_reviewed: ReviewNotReviewed[] })[]
  not_reviewed: ReviewNotReviewed[]; findings: ReviewFindingRow[]
  supported_points: (ReviewResolvedTarget & { evidence: ReviewEvidence[] })[]
  context_limits: (ReviewResolvedTarget & { code: string; text: string })[]
  models_that_answered: { step_id: string; step_input_id: string; connection: string; requested_model: string; resolved_model: string | null; status: string }[]
  stale_reasons: ({ code: string; version?: number; kill_search_id?: string; status?: string; claim_ref?: string; cell_id?: string; column_id?: string; source_version_ids?: string[]; targets?: ReviewTargetRef[]; target_ref?: ReviewTargetRef })[]
}
export type ReviewApplyResult = { decision: ReviewDecision; revision: { id: string }; applied_matches_suggestion: boolean }

export class ApiError extends Error {
  status: number
  // A 422 from the approval route names every fault of the correction at once; the card shows them by their row.
  errors: string[]
  // A 409 of the human queue says why: `row_changed` or `reading_started` (slice 17).
  reason: string | null
  code: string | null
  details: Record<string, unknown> | null
  constructor(status: number, message: string, errors: string[] = [], reason: string | null = null, code: string | null = null, details: Record<string, unknown> | null = null) { super(message); this.status = status; this.errors = errors; this.reason = reason; this.code = code; this.details = details }
}

let csrfToken: string | null = null
async function csrf(): Promise<string> {
  if (!csrfToken) {
    const response = await fetch('/api/session', { credentials: 'same-origin' })
    csrfToken = (await response.json()).csrf_token as string
  }
  return csrfToken
}

async function request<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(init.headers)
  const method = init.method ?? 'GET'
  if (method !== 'GET') headers.set('x-deixis-csrf', await csrf())
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (response.status === 403 && method !== 'GET' && !retried) {
    csrfToken = null
    return request<T>(path, init, true)
  }
  if (!response.ok) {
    throw await responseError(response)
  }
  return response.json() as Promise<T>
}

const json = (method: string, body: unknown, extra: Record<string, string> = {}): RequestInit =>
  ({ method, headers: { 'content-type': 'application/json', ...extra }, body: JSON.stringify(body) })

async function responseError(response: Response): Promise<ApiError> {
  let detail = response.statusText
  let errors: string[] = []
  let reason: string | null = null
  let code: string | null = null
  let details: Record<string, unknown> | null = null
  try {
    const body = await response.json()
    if (typeof body.code === 'string') {
      code = body.code
      details = Object.fromEntries(Object.entries(body).filter(([key]) => key !== 'code' && key !== 'detail'))
    }
    // A refusal that names its cause with a `code` carries an English sentence that is also its i18n key (P9 H3).
    if (typeof body.detail === 'string') detail = typeof body.code === 'string' ? t(body.detail) : body.detail
    // A validation refusal answers with a list of faults rather than one sentence (slice 08a).
    else if (Array.isArray(body.detail?.errors)) { errors = body.detail.errors.map(String); detail = errors.join(' · ') }
    else if (typeof body.detail?.message === 'string') { detail = body.detail.message; reason = typeof body.detail.reason === 'string' ? body.detail.reason : null }
  } catch { /* keep status text */ }
  return new ApiError(response.status, detail, errors, reason, code, details)
}

async function reportMarkdown(id: string, reportId: string): Promise<{ text: string; filename: string }> {
  const response = await fetch(`/api/researches/${id}/reports/${reportId}/export?format=markdown`, { credentials: 'same-origin' })
  if (!response.ok) throw await responseError(response)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = /^attachment;\s*filename="([a-zA-Z0-9._-]+)"$/.exec(disposition)?.[1] ?? 'report.md'
  return { text: await response.text(), filename }
}

// The zip holds the .tex and the .bib. X-Deixis-Export-Notes is the total count of export notes, ASCII digits; the .tex lists at most 20.
async function reportLatex(id: string, reportId: string): Promise<{ blob: Blob; filename: string; notes: number }> {
  const response = await fetch(`/api/researches/${id}/reports/${reportId}/export?format=latex`, { credentials: 'same-origin' })
  if (!response.ok) throw await responseError(response)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = /^attachment;\s*filename="([a-zA-Z0-9._-]+)"$/.exec(disposition)?.[1] ?? 'report-latex.zip'
  const header = response.headers.get('X-Deixis-Export-Notes') ?? ''
  return { blob: await response.blob(), filename, notes: /^\d+$/.test(header) && Number.isSafeInteger(Number(header)) ? Number(header) : 0 }
}

export type WatchKind = 'protocol_queries' | 'citing_works'
export type WatchCaps = { per_page: number; pages: number; citing_sources: number; max_provider_requests: number; max_records: number; rate_limit_retries: number; deadline_seconds: number }
export type WatchUnit = {
  unit_key: string; provider_id?: string; display_name?: string; query_text?: string; work_id?: string; openalex_id?: string | null
  status: string; page_size?: number; date_sorted?: boolean; baseline?: boolean; continuation?: boolean
  requested_from?: string | null; requested_to?: string; index?: number
}
export type WatchObservation = {
  pages_read: number; pages_answered: number; exhausted: boolean; cut_by_cap: boolean; sort_sent: string | null
  oldest_publication_date: string | null; newest_publication_date: string | null; finished: boolean
  requested_from: string | null; requested_to: string; coverage: 'baseline_complete' | 'baseline_incomplete' | 'covered' | 'coverage_not_reached' | 'coverage_unknown'
  unread_window: { from: string | null; to: string } | null
}
export type WatchGap = {
  id: string; watch_id: string; research_id: string; opening_id: string; first_missed_due: string; last_missed_due: string
  missed_periods: number; observed_until: string | null; noticed_at: string; schedule_version: number
  outcome: 'catch_up_chosen' | 'catch_up_off' | 'opening_cap' | 'one_per_research' | 'not_eligible' | 'changed_before_record'
  outcome_reason: string | null; next_due_at: string | null; created_at: string; catch_up_check_id: string | null; catch_up_queued: boolean
}
export type WatchSchedule = {
  mode: 'manual' | 'interval'; interval_days: 1 | 7 | 30 | null; catch_up: boolean | null
  schedule_version: number; [key: string]: unknown
}
export type WatchCheck = {
  id: string; watch_id: string; research_id: string; run_id: string; trigger: 'manual' | 'scheduled' | 'catch_up'
  period_start: string; requested_from: string | null; requested_to: string; state_version: number; missed_periods: number
  completed_at: string | null; created_at: string; state: 'queued' | 'running' | 'pause_requested' | 'paused' | 'cancelled' | 'failed' | 'succeeded' | 'partial'
  pause_reason: string | null; failure_reason: string | null; outcome_unknown: boolean; partial_reasons: string[]
  config_revision: { units: WatchUnit[]; skipped_units: WatchUnit[]; [key: string]: unknown }; schedule: WatchSchedule | null
  gap: { from: string; to: string; missed_periods: number; notice: string } | null; caps: WatchCaps; units: WatchUnit[]
  observed: { units: Record<string, WatchObservation>; partial_reasons: string[]; rolled_over: number; rolled_over_units: number; skipped_units: WatchUnit[] }
  provider_status: Record<string, { provider: string; status: string; error_kind: string | null; returned: number; dropped: number }>
  counts: { records_read: number; new: number; notices: number; already_seen: number; already_in_library: number; baseline: number
    may_be_version: number; baseline_undated: number; returned: number; dropped: number; records_over_threshold: number
    new_open: number; dismissed: number; added: number; caps: WatchCaps; units: Record<string, { [key: string]: unknown }> } | null
  baseline_undated: { titles: string[]; count: number; notice: string }; follows_old_scope_reason: string | null
}
export type Watch = {
  id: string; research_id: string; kind: WatchKind; mode: 'manual' | 'interval'; interval_days: 1 | 7 | 30 | null
  catch_up: boolean | null; enabled: boolean; protocol_record_id: string | null; scope_revision: number
  state_version: number; schedule_version: number; last_checked_at: string | null; last_success_at: string | null
  next_due_at: string | null; created_at: string; disabled_at: string | null; waiting_reason: 'watch_follows_old_scope' | 'check_paused' | null
  follows_old_scope: boolean; follows_old_scope_reason: string | null; gaps: WatchGap[]
  baseline: Record<string, number | { state: 'pending' | 'partial' | 'complete'; cut?: string; cursor?: string | null; pages_read?: number; success_boundary?: string | null; covered_back_to?: string | null }>
  last_check: WatchCheck | null; notice: string
}
export type WatchRelation = { relation: string; against?: 'seen' | 'library'; id?: string; title?: string; link_kind?: string; rule?: string; check_id?: string }
export type WatchItem = {
  id: string; research_id: string; check_id: string; seen_id: string; kind: 'new_record' | 'notice'; status: 'new' | 'dismissed' | 'merged' | 'added'
  merged_into_item_id: string | null; dismissed_reason: string | null; dismissed_at: string | null; created_at: string
  record: { title: string; authors: string[]; year: number | null; publication_date: string | null
    publication_date_source: 'openalex.publication_date' | 'not_returned'; version_time: string | null; provider: string
    provider_record_id: string; doi: string | null; landing_url: string | null; abstract: string | null; identifiers: Record<string, unknown>
    version_label: string | null; retrieved_at: string; aliases: string[]; relations: WatchRelation[] }
  doi: string | null; landing_url: string | null; first_seen_at: string; identity_uncertain: boolean; identity_notice: string | null
  found_by: unknown[]; relations: WatchRelation[]; may_be_version_json: WatchRelation[]; kind_history: unknown[]
}
export type WatchPreview = { kind: WatchKind; units: WatchUnit[]; caps: WatchCaps; citing_works_count: number; no_openalex_id: number; notice: string }
export type WatchCommandResult = { replayed: boolean; watch_id?: string; check_id?: string; run_id?: string; item_id?: string; watch?: Watch; check?: WatchCheck; run?: Run; item?: WatchItem }

export const api = {
  previewWatch: (id: string, kind: WatchKind) => request<WatchPreview>(`/api/researches/${id}/watches/preview`, json('POST', { kind })),
  createWatch: (id: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watches`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  watches: (id: string) => request<Watch[]>(`/api/researches/${id}/watches`),
  checkWatch: (id: string, wid: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watches/${wid}/checks`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  disableWatch: (id: string, wid: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watches/${wid}/disable`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  scheduleWatch: (id: string, wid: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watches/${wid}/schedule`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  rebindWatch: (id: string, wid: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watches/${wid}/rebind`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  watchCheck: (id: string, wid: string, cid: string) => request<WatchCheck>(`/api/researches/${id}/watches/${wid}/checks/${cid}`),
  watchItems: (id: string, status: WatchItem['status'] = 'new') => request<WatchItem[]>(`/api/researches/${id}/watch-items?${new URLSearchParams({ status })}`),
  dismissWatchItem: (id: string, iid: string, body: string, key: string) => request<WatchCommandResult>(`/api/researches/${id}/watch-items/${iid}/dismiss`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  previewReview: (id: string, body: ReviewRequest) => request<ReviewPreview>(`/api/researches/${id}/reviews/preview`, json('POST', body)),
  startReview: (id: string, body: string, key: string) => request<{ review: { id: string }; run: Run }>(`/api/researches/${id}/reviews`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  reviews: (id: string, kind: ReviewTargetKind, targetId: string) => request<ReviewCard[]>(`/api/researches/${id}/reviews?${new URLSearchParams({ target_kind: kind, target_id: targetId })}`),
  review: (id: string, reviewId: string) => request<ReviewDetail>(`/api/researches/${id}/reviews/${reviewId}`),
  decideReview: (id: string, reviewId: string, findingId: string, body: string, key: string) => request<{ decision: ReviewDecision; no_change_made: boolean }>(`/api/researches/${id}/reviews/${reviewId}/findings/${findingId}/decisions`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  applyReview: (id: string, reviewId: string, findingId: string, body: string, key: string) => request<ReviewApplyResult>(`/api/researches/${id}/reviews/${reviewId}/findings/${findingId}/apply`, { method: 'POST', headers: { 'content-type': 'application/json', 'Idempotency-Key': key }, body }),
  researches: () => request<ResearchSummary[]>('/api/researches'),
  trash: () => request<Trash>('/api/trash'),
  moveToTrash: (id: string) => request<{ trashed: boolean }>(`/api/researches/${id}`, { method: 'DELETE' }),
  restore: (id: string) => request<{ restored: boolean }>(`/api/trash/${id}/restore`, { method: 'POST' }),
  deletePermanently: (id: string) => request<{ deleted: boolean; files_not_removed: string[] }>(`/api/trash/${id}`, { method: 'DELETE' }),
  search: (q: string) => request<QuickFindResult>(`/api/search?q=${encodeURIComponent(q)}`),
  library: () => request<LibraryView>('/api/library'),
  libraryWork: (workId: string) => request<LibraryWork>(`/api/library/works/${encodeURIComponent(workId)}`),
  addLibrarySource: (researchId: string, workId: string) =>
    request<LibraryAddition>(`/api/researches/${researchId}/library-sources`, json('POST', { work_id: workId })),
  research: (id: string) => request<ResearchView>(`/api/researches/${id}`),
  renameResearch: (id: string, title: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/title`, json('POST', { title, expected_version: expectedVersion })),
  create: (body: {
    question: string; source_scope: SourceScope; seed_mode?: 'question_only' | 'uploaded_seed'; effort: Effort; model_connection: string; requested_model: string; reasoning_effort: string | null
    literature_connection: string; literature_model: string; literature_reasoning_effort: string | null
    review_mode: ReviewMode; review_connection: string | null; review_model: string | null; review_reasoning_effort: string | null
  }) => request<ResearchView>('/api/researches', json('POST', body)),
  settings: () => request<Record<ModelRole, RoleModelSetting>>('/api/settings'),
  saveModelDefault: (role: ModelRole, setting: RoleModelSetting) =>
    request<Partial<Record<ModelRole, RoleModelSetting>>>(`/api/settings/${role}`, json('PUT', setting)),
  zoteroCollections: (source: ZoteroSource) => request<{ source: ZoteroSource; collections: ZoteroCollection[] }>(`/api/zotero/collections?source=${source}`),
  zoteroImport: (id: string, source: ZoteroSource, collectionKey: string) =>
    request<ResearchView & { zotero_import: ZoteroImport }>(`/api/researches/${id}/zotero-imports`, json('POST', { source, collection_key: collectionKey })),
  upload: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResearchView & { uploaded_source_version_id: string; file_restore: FileRestoreReceipt | null }>(`/api/researches/${id}/uploads`, { method: 'POST', body: form })
  },
  setSeed: (id: string, sourceVersionId: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/seed`, json('POST', { source_version_id: sourceVersionId, expected_version: expectedVersion })),
  uploadToSource: (id: string, sourceId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResearchView & { file_restore: FileRestoreReceipt | null }>(`/api/researches/${id}/sources/${sourceId}/uploads`, { method: 'POST', body: form })
  },
  // Attaches PDFs from the user's Zotero library to included works that have no PDF text yet (D49).
  zoteroPdfs: (id: string, source: ZoteroSource) =>
    request<ResearchView & { zotero_pdfs: { checked: number; added: number; notes: ZoteroNote[] } }>(`/api/researches/${id}/zotero-pdfs`, json('POST', { source })),
  // Proposes the included source each PDF belongs to (DOI, arXiv id, or title); nothing is attached (D49).
  matchUploads: (id: string, files: File[]) => {
    const form = new FormData()
    files.forEach(file => form.append('files', file))
    return request<{ matches: PdfMatch[] }>(`/api/researches/${id}/uploads/match`, { method: 'POST', body: form })
  },
  // An sw research's match: a work among those waiting for a PDF, with its versions to pick from (slice 18a).
  matchWaiting: (id: string, files: File[]) => {
    const form = new FormData()
    files.forEach(file => form.append('files', file))
    return request<{ matches: WaitingMatch[]; scope_revision: number }>(`/api/researches/${id}/uploads/match`, { method: 'POST', body: form })
  },
  waiting: (id: string) => request<WaitingView>(`/api/researches/${id}/waiting`),
  // Adds the file to the version the person picked; 409 with a reason when what the match showed has moved (slice 18a).
  attachWaiting: (id: string, file: File, match: WaitingMatch, work: WaitingWork, sourceId: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('work_id', work.work_id)
    form.append('source_version_id', sourceId)
    form.append('scope_revision', String(match.scope_revision))
    form.append('versions_digest', work.versions_digest)
    form.append('sha256', match.sha256)
    return request<ResearchView & { file_restore: FileRestoreReceipt | null; attached: { source_version_id: string; asset_id: string; reading: AttachOutcome } }>(`/api/researches/${id}/waiting/uploads`, { method: 'POST', body: form })
  },
  // Asks for a person's file to be read again after a reading that did not decide it (slice 18b, decision 6).
  retryPersonReading: (id: string, requestId: string) => request<{ run: Run | null }>(`/api/researches/${id}/waiting/requests/${requestId}/retry`, { method: 'POST' }),
  institutionProxy: () => request<{ address: string | null }>('/api/institution-proxy'),
  saveInstitutionProxy: (address: string) => request<{ address: string | null }>('/api/institution-proxy', json('PUT', { address })),
  // Takes sources out of this research; the library record, its files and the evidence citing it stay (D50).
  removeSources: (id: string, sourceIds: string[], note?: string) =>
    request<ResearchView & { changed_source_version_ids: string[] }>(`/api/researches/${id}/sources`, json('DELETE', { source_version_ids: sourceIds, note })),
  restoreSources: (id: string, sourceIds: string[]) =>
    request<ResearchView & { changed_source_version_ids: string[] }>(`/api/researches/${id}/sources/restore`, json('POST', { source_version_ids: sourceIds })),
  // Deletes removed sources for good; 409 while an answer, table or report still cites one (D65).
  purgeSources: (id: string, sourceIds: string[]) =>
    request<{ deleted: string[]; files_not_removed: string[] }>(`/api/researches/${id}/sources/purge`, json('POST', { source_version_ids: sourceIds })),
  // Puts a PDF removed as the wrong file back in use; 409 when another PDF is in use for the source.
  restoreAsset: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/restore`, { method: 'POST' }),
  removeAsset: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}`, { method: 'DELETE' }),
  assetImpact: (id: string, sourceId: string, assetId: string) =>
    request<AssetImpact>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/impact`),
  replaceAsset: (id: string, sourceId: string, assetId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResearchView & { file_restore: FileRestoreReceipt | null }>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}`, { method: 'PUT', body: form })
  },
  reextractAsset: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView & { reextraction: Reextraction }>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/extractions`, { method: 'POST' }),
  retryText: (id: string, sourceId: string, assetId: string, body: TextRetryRequest) =>
    request<ResearchView & { recovery: TextRetryOperation & { replayed: boolean } }>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/extractions`, json('POST', body)),
  textRecovery: (id: string, sourceId: string, assetId: string) =>
    request<TextRecoveryCapability>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/text-retry`),
  recoveryHistory: (id: string, sourceId: string, assetId: string) =>
    request<RecoveryHistory>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/recovery-history`),
  discoverPdf: (id: string, sourceId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/pdf-discovery`, { method: 'POST' }),
  attachPdfCandidate: (id: string, sourceId: string, candidateId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/pdf-candidates/${candidateId}/attach`, { method: 'POST' }),
  startRun: (id: string, kind: 'discovery' | 'answer' | 'pdf_collection' | 'research_title', idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/runs`, json('POST', { kind }, { 'Idempotency-Key': idempotencyKey })),
  controlRun: (runId: string, action: 'pause' | 'resume' | 'cancel' | 'retry_failed') => request<Run>(`/api/runs/${runId}/${action}`, { method: 'POST' }),
  select: (id: string, sourceId: string, state: Source['selection']['state'], expectedVersion: number, reason?: string) =>
    request<unknown>(`/api/researches/${id}/selections/${sourceId}`, json('PATCH', { state, expected_version: expectedVersion, reason })),
  queue: (id: string) => request<QueueView>(`/api/researches/${id}/queue`),
  queueRow: (id: string, sourceId: string) => request<QueueRowView>(`/api/researches/${id}/queue/${sourceId}`),
  answerQueueRow: (id: string, sourceId: string, decision: QueueAnswer, rowToken: string, note?: string | null) =>
    request<QueueAnswerResult>(`/api/researches/${id}/queue/${sourceId}/decision`, json('POST', { decision, note: note ?? null, row_token: rowToken })),
  undoQueueDecision: (id: string, sourceId: string, undoToken: string) =>
    request<QueueAnswerResult>(`/api/researches/${id}/queue/${sourceId}/undo`, json('POST', { row_token: undoToken })),
  audit: (id: string) => request<AuditView>(`/api/researches/${id}/audit`),
  auditRow: (id: string, sourceId: string) => request<AuditRowView>(`/api/researches/${id}/audit/${sourceId}`),
  answerAuditRow: (id: string, sourceId: string, decision: AuditAnswer, auditToken: string) =>
    request<AuditResult>(`/api/researches/${id}/audit/${sourceId}/decision`, json('POST', { decision, note: null, audit_token: auditToken })),
  undoAuditDecision: (id: string, sourceId: string, auditToken: string) =>
    request<AuditResult>(`/api/researches/${id}/audit/${sourceId}/undo`, json('POST', { audit_token: auditToken })),
  effortLimits: () => request<EffortLimits>('/api/effort-limits'),
  reviseScope: (id: string, question: string, expectedVersion: number, keyTerms?: string | null) =>
    request<ResearchView>(`/api/researches/${id}/scope`, json('POST', { question, expected_version: expectedVersion, key_terms: keyTerms ?? null })),
  // Approve or correct the protocol an sw discovery run stopped for; the run is queued again (D80).
  approveProtocol: (runId: string, edits: ProtocolEdits) =>
    request<Run>(`/api/runs/${runId}/protocol-approval`, json('POST', edits)),
  // Ask the model for other names of the terms on the card. Nothing it proposes is searched until the user adds
  // it in their correction (D82).
  skipEquations: (runId: string) => request<Run>(`/api/runs/${runId}/skip-equations`, { method: 'POST' }),
  suggestTerms: (runId: string) => request<Run>(`/api/runs/${runId}/term-suggestions`, { method: 'POST' }),
  // After the model could not write the query: search with the code's query alone (D92).
  chooseCodeQuery: (runId: string) => request<Run>(`/api/runs/${runId}/search-query-choice`, { method: 'POST' }),
  passage: (id: string, passageId: string) => request<Passage>(`/api/researches/${id}/passages/${passageId}`),
  assetText: (id: string, assetId: string, extractionId?: string) => request<AssetText>(`/api/researches/${id}/assets/${assetId}/text${extractionId ? `?extraction_id=${encodeURIComponent(extractionId)}` : ''}`),
  assetFigures: (id: string, assetId: string) => request<{ figures: AssetFigure[] }>(`/api/researches/${id}/assets/${assetId}/figures`),
  events: (id: string, after = 0) => request<ActivityEvent[]>(`/api/researches/${id}/events?after=${after}`),
  connections: (refresh = false) => request<Connections>(`/api/connections${refresh ? '?refresh=true' : ''}`),
  modelConnection: (connection: string, refresh = false) => request<ModelHealth>(`/api/connections/${encodeURIComponent(connection)}${refresh ? '?refresh=true' : ''}`),
  institutionalAccess: () => request<InstitutionalAccess>('/api/institutional-access'),
  credentials: () => request<Credentials>('/api/credentials'),
  saveCredential: (env: string, value: string) => request<{ key: KeyEntry; test: KeyTest | null }>(`/api/credentials/${env}`, json('PUT', { value })),
  removeCredential: (env: string) => request<{ key: KeyEntry }>(`/api/credentials/${env}`, { method: 'DELETE' }),
  testCredential: (env: string) => request<KeyTest>(`/api/credentials/${env}/test`, { method: 'POST' }),
  equationReader: () => request<EquationReader>('/api/equation-reader'),
  installEquationReader: () => request<{ job: EquationReader['job'] }>('/api/equation-reader/install', { method: 'POST' }),
  cancelEquationReaderInstall: () => request<{ job: EquationReader['job'] }>('/api/equation-reader/cancel', { method: 'POST' }),
  removeEquationReader: () => request<EquationReader>('/api/equation-reader', { method: 'DELETE' }),
  rereadEquations: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/equations`, { method: 'POST' }),
  ocr: () => request<OcrTool>('/api/ocr'),
  // Starts a pdf_ocr run that reads the PDF's pages without text with the local Tesseract (D51).
  readWithOcr: (id: string, sourceId: string, assetId: string) =>
    request<Run>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/ocr`, { method: 'POST' }),
  localTools: (refresh = false) => request<LocalTools>(`/api/local-tools${refresh ? '?refresh=true' : ''}`),
  installLocalTool: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/install`, { method: 'POST' }),
  cancelLocalToolInstall: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/cancel`, { method: 'POST' }),
  semanticSearch: () => request<SemanticSearch>('/api/semantic-search'),
  saveSemanticSearch: (provider: SemanticSearchProvider, model: string | null) =>
    request<SemanticSearch>('/api/semantic-search', json('PUT', { provider, model })),
  builtinEmbedding: () => request<BuiltinEmbedding>('/api/semantic-search/builtin'),
  installBuiltinEmbedding: () => request<{ job: BuiltinEmbeddingJob }>('/api/semantic-search/builtin/install', { method: 'POST' }),
  cancelBuiltinEmbedding: () => request<{ job: BuiltinEmbeddingJob }>('/api/semantic-search/builtin/cancel', { method: 'POST' }),
  removeBuiltinEmbedding: () => request<BuiltinEmbedding>('/api/semantic-search/builtin', { method: 'DELETE' }),
  // The built-in model's English sentence for the current question revision, written once (slice 21).
  saveEnglishQuestion: (id: string, body: { text: string; expected_version: number } | { use_question: true; expected_version: number }) =>
    request<ResearchView>(`/api/researches/${id}/english-question`, json('PUT', body)),
  tables: (id: string) => request<TableSummary[]>(`/api/researches/${id}/tables`),
  answerMethod: (id: string, answerId: string) => request<AnswerMethod>(`/api/researches/${id}/answers/${answerId}/method`),
  startReport: (id: string, tableId: string, key: string, options?: { continueWithFailed?: boolean }) => request<Run>(`/api/researches/${id}/reports`, json('POST', { table_id: tableId, ...(options?.continueWithFailed ? { continue_with_failed: true } : {}) }, { 'Idempotency-Key': key })),
  report: (id: string, reportId: string) => request<ReportDetail>(`/api/researches/${id}/reports/${reportId}`),
  reportGaps: (id: string, reportId: string) => request<ReportGap[]>(`/api/researches/${id}/reports/${reportId}/gaps`),
  candidates: (id: string) => request<CandidateListItem[]>(`/api/researches/${id}/candidates`),
  openCandidate: (id: string, body: CandidateOpen) => request<CandidateCard>(`/api/researches/${id}/candidates`, json('POST', body, { 'Idempotency-Key': crypto.randomUUID() })),
  candidate: (id: string, cid: string) => request<CandidateCard>(`/api/researches/${id}/candidates/${cid}`),
  editCandidate: (id: string, cid: string, body: CandidateEdit) => request<CandidateCard>(`/api/researches/${id}/candidates/${cid}/versions`, json('POST', body, { 'Idempotency-Key': crypto.randomUUID() })),
  decomposeCandidate: (id: string, cid: string) => request<Run>(`/api/researches/${id}/candidates/${cid}/decompose`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }),
  candidateKillSearchPlan: (id: string, cid: string) => request<CandidatePlan>(`/api/researches/${id}/candidates/${cid}/kill-search/plan`),
  startCandidateKillSearch: (id: string, cid: string, preview_fingerprint: string) => request<Run>(`/api/researches/${id}/candidates/${cid}/kill-search`, json('POST', { preview_fingerprint }, { 'Idempotency-Key': crypto.randomUUID() })),
  candidateMatrix: (id: string, cid: string, kid: string) => request<CandidateMatrix>(`/api/researches/${id}/candidates/${cid}/kill-searches/${kid}`),
  candidateHit: (id: string, cid: string, kid: string, svid: string) => request<CandidateEvidence>(`/api/researches/${id}/candidates/${cid}/kill-searches/${kid}/hits/${svid}`),
  candidateOwnerDecision: (id: string, cid: string, vid: string, body: { status: CandidateStatus; reason: string }) => request<CandidateCard>(`/api/researches/${id}/candidates/${cid}/versions/${vid}/owner-decision`, json('POST', body)),
  reportMarkdown,
  reportLatex,
  editReportClaim: (id: string, reportId: string, claimId: string, body: { expected_version: number; text?: string; note?: string | null; restore_from?: string; link_ids?: string[] }) =>
    request<ReportDetail>(`/api/researches/${id}/reports/${reportId}/claims/${claimId}`, json('PUT', body, { 'Idempotency-Key': crypto.randomUUID() })),
  acknowledgeReportChanges: (id: string, reportId: string, sectionId: string, changeKeys: string[]) =>
    request<ReportDetail>(`/api/researches/${id}/reports/${reportId}/sections/${sectionId}/acknowledge-changes`, json('POST', { change_keys: changeKeys })),
  checkReportEdits: (id: string, reportId: string) =>
    request<ReportDetail>(`/api/researches/${id}/reports/${reportId}/check-edits`, { method: 'POST' }),
  table: (id: string, tableId: string) => request<TableView>(`/api/researches/${id}/tables/${tableId}`),
  // rows omitted: the table starts with the research's included sources; given, those sources in that order, included or not.
  createTable: (id: string, body: { title: string; template_id?: string; rows?: string[] }, idempotencyKey: string) =>
    request<TableView>(`/api/researches/${id}/tables`, json('POST', body, { 'Idempotency-Key': idempotencyKey })),
  trashTable: (id: string, tableId: string, expectedVersion: number) =>
    request<{ trashed: boolean }>(`/api/researches/${id}/tables/${tableId}?expected_version=${expectedVersion}`, { method: 'DELETE' }),
  restoreTable: (id: string, tableId: string, expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/restore`, json('POST', { expected_version: expectedVersion })),
  purgeTable: (tableId: string) => request<{ deleted: boolean; cells: number; human_edits: number }>(`/api/trash/tables/${tableId}`, { method: 'DELETE' }),
  addTableRows: (id: string, tableId: string, sourceIds: string[], expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/rows`, json('POST', { source_version_ids: sourceIds, expected_version: expectedVersion })),
  removeTableRow: (id: string, tableId: string, sourceId: string, expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/rows/${sourceId}?expected_version=${expectedVersion}`, { method: 'DELETE' }),
  addColumn: (id: string, tableId: string, spec: ColumnSpec & { suggestion_step_id?: string }, expectedVersion: number, idempotencyKey: string) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/columns`, json('POST', { ...spec, expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  addDevelopmentColumns: (id: string, tableId: string, expectedVersion: number, idempotencyKey: string) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/lineage/columns`, json('POST', { expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  lineage: (id: string, tableId: string) => request<LineageView>(`/api/researches/${id}/tables/${tableId}/lineage`),
  lineageBaseline: (id: string, tableId: string) => request<LineageBaseline>(`/api/researches/${id}/tables/${tableId}/lineage/baseline`),
  lineagePlan: (id: string, tableId: string, retryFailed: boolean) => request<LineagePlan>(`/api/researches/${id}/tables/${tableId}/lineage/plan?retry_failed=${retryFailed}`),
  startLineageRun: (id: string, tableId: string, previewFingerprint: string, retryFailed: boolean, idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/tables/${tableId}/lineage/runs`, json('POST', { preview_fingerprint: previewFingerprint, retry_failed: retryFailed }, { 'Idempotency-Key': idempotencyKey })),
  addLineageLink: (id: string, tableId: string, body: LineageLinkAdd, idempotencyKey: string) =>
    request<LineageView>(`/api/researches/${id}/tables/${tableId}/lineage/links`, json('POST', body, { 'Idempotency-Key': idempotencyKey })),
  editLineageLink: (id: string, tableId: string, linkId: string, body: LineageLinkEdit, idempotencyKey: string) =>
    request<LineageView>(`/api/researches/${id}/tables/${tableId}/lineage/links/${linkId}`, json('PUT', body, { 'Idempotency-Key': idempotencyKey })),
  removeLineageLink: (id: string, tableId: string, linkId: string, body: LineageLinkRemove, idempotencyKey: string) => {
    const query = new URLSearchParams({ expected_version: String(body.expected_version), based_on_revision_id: body.based_on_revision_id })
    if (body.note != null) query.set('note', body.note)
    return request<LineageView>(`/api/researches/${id}/tables/${tableId}/lineage/links/${linkId}?${query}`, { method: 'DELETE', headers: { 'Idempotency-Key': idempotencyKey } })
  },
  // Only a table without columns takes a template's columns.
  applyTableTemplate: (id: string, tableId: string, templateId: string, expectedVersion: number, idempotencyKey: string) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/template-columns`, json('POST', { template_id: templateId, expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  reviseColumn: (id: string, tableId: string, columnId: string, spec: ColumnSpec, expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/columns/${columnId}`, json('PATCH', { ...spec, expected_version: expectedVersion })),
  removeColumn: (id: string, tableId: string, columnId: string, expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/columns/${columnId}?expected_version=${expectedVersion}`, { method: 'DELETE' }),
  restoreColumn: (id: string, tableId: string, columnId: string, expectedVersion: number) =>
    request<TableView>(`/api/researches/${id}/tables/${tableId}/columns/${columnId}/restore`, json('POST', { expected_version: expectedVersion })),
  suggestColumns: (id: string, tableId: string, idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/tables/${tableId}/column-suggestions`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey } }),
  fillTable: (id: string, tableId: string, expectedVersion: number, idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/tables/${tableId}/fill`, json('POST', { expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  cell: (id: string, tableId: string, columnId: string, sourceId: string) =>
    request<CellView>(`/api/researches/${id}/tables/${tableId}/cells/${columnId}/${sourceId}`),
  editCell: (id: string, tableId: string, columnId: string, sourceId: string, body: CellEdit, idempotencyKey: string) =>
    request<CellView>(`/api/researches/${id}/tables/${tableId}/cells/${columnId}/${sourceId}`, json('PUT', body, { 'Idempotency-Key': idempotencyKey })),
  recheckCell: (id: string, tableId: string, columnId: string, sourceId: string, expectedVersion: number, idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/tables/${tableId}/cells/${columnId}/${sourceId}/recheck`, json('POST', { expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  decideProposal: (id: string, tableId: string, columnId: string, sourceId: string, revisionId: string, decision: 'accept' | 'dismiss', expectedVersion: number, idempotencyKey: string) =>
    request<CellView>(`/api/researches/${id}/tables/${tableId}/cells/${columnId}/${sourceId}/proposals/${revisionId}/${decision}`, json('POST', { expected_version: expectedVersion }, { 'Idempotency-Key': idempotencyKey })),
  tableTemplates: () => request<TableTemplate[]>('/api/table-templates'),
  saveTableTemplate: (researchId: string, tableId: string, name: string, idempotencyKey: string) =>
    request<TableTemplate>('/api/table-templates', json('POST', { name, research_id: researchId, table_id: tableId }, { 'Idempotency-Key': idempotencyKey })),
  restoreTemplate: (templateId: string) => request<{ restored: boolean }>(`/api/table-templates/${templateId}/restore`, { method: 'POST' }),
  purgeTemplate: (templateId: string) => request<{ deleted: boolean; tables_unlinked: number }>(`/api/trash/templates/${templateId}`, { method: 'DELETE' }),
}

// The Method box under an answer (workflow/method_summary.py): stored counts only; null means the rows do not say.
export type AnswerMethod = {
  answer_id: string; scope_revision: number
  search: { queries: { provider: string; query: string; records_read: number; provider_total: number | null; date: string; complete: boolean; origin: string | null; round: number | null }[]
    records_read: number; planned: number; planned_not_sent: number; chaining: { ran: boolean; requests: number; records_read: number } }
  selection: { snapshot: boolean; works_found: number | null; screened: number; abstract_read: number; full_text_attempted: number; full_text_read: number; person_decisions: number; included: number | null; not_met: number | null
    waiting_for_pdf: number | null; not_read: number | null; criterion: string | null
    vocabulary_review: { reviewed_by_person: boolean | null; approved_by: string | null; edited: boolean | null } }
  extraction: { table: boolean; columns: string[]; columns_accepted_automatically: number }
  limitations: { access: { given: number; full_text: number; abstract_only: number; no_passage: number } | null; answer_limitations: number; access_limitations: number }
  evidence_base: { cited_sources: number; year_min: number | null; year_max: number | null }
  not_measured: string[]
}

export const prismaSUrl = (researchId: string, format: 'md' | 'json') =>
  `/api/researches/${researchId}/prisma-s?format=${format}`

export const bibliographyUrl = (researchId: string, format: 'bibtex' | 'ris', sources: 'included' | 'cited') =>
  `/api/researches/${researchId}/bibliography?format=${format}&sources=${sources}`

const textFragment = (text: string) => encodeURIComponent(text.replace(/\s+/g, ' ').trim()).replace(/-/g, '%2D')

export const figureUrl = (researchId: string, assetId: string, label: string) =>
  `/api/researches/${researchId}/assets/${assetId}/figures/${encodeURIComponent(label)}.png`

export const assetUrl = (researchId: string, assetId: string, page?: number | null, highlightText?: string | null) => {
  const openParams = page ? `page=${page}` : ''
  const highlight = highlightText?.trim() ? `:~:text=${textFragment(highlightText)}` : ''
  return `/api/researches/${researchId}/assets/${assetId}${openParams || highlight ? `#${openParams}${highlight}` : ''}`
}

export function subscribe(researchId: string, after: number, onEvent: () => void): () => void {
  const source = new EventSource(`/api/researches/${researchId}/events/stream?after=${after}`)
  source.onmessage = () => onEvent()
  return () => source.close()
}
