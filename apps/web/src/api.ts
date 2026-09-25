// Client for the local DEIXIS API. Types mirror backend/deixis/workflow/views.py.

export type RunStatus = 'queued' | 'running' | 'pause_requested' | 'paused' | 'completed' | 'failed' | 'cancelled'
export type SourceScope = 'academic' | 'attached' | 'attached_and_academic'
export type Effort = 'quick' | 'standard' | 'detailed'

export type Scope = {
  research_id: string; revision: number; question: string; language_hint: string | null; source_scope: SourceScope
  seed_mode: 'question_only' | 'uploaded_seed'; seed_status: 'question_only' | 'missing' | 'ready' | 'stale'
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
  output: { page_count?: number | null; passage_count?: number; model?: string; sources?: number; passages?: number; embedded?: number
    // A pdf_ocr run (D51): the pages without text it found, and whether the merged OCR text was taken into use.
    image_pages?: number[]; blank_pages?: number[]; outcome?: 'current' | 'rejected' | 'unchanged'; rejection_reason?: string | null
    // Citation chaining (D95): what its summary counted, with the seeds it froze.
    seed_list?: { source_version_id: string; kind: 'code' | 'user' }[]; new_works?: number; read_by_model?: number
    requests?: { sent?: number; failed?: number; not_reached_seeds?: number }
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
export type RunKind = 'discovery' | 'answer' | 'pdf_collection' | 'pdf_ocr' | 'fulltext_fetch' | 'fulltext_adjudication' | 'table_columns' | 'table_fill' | 'cell_recheck' | 'research_title'
// What a table run works on, as stored when it was requested (D38); null for discovery and answer runs.
export type RunTarget = {
  table_id: string; column_id?: string; source_version_id?: string; cell_version?: number
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
  approved_by: 'user' | 'setting' | 'earlier_approval' | null; edited: boolean | null; proposal_hash: string
  proposal: ApprovalSide; approved: ApprovalSide | null
  // Operations of an earlier approval this run could not apply, because the phrase is no longer in the proposal.
  skipped_edits: { op: string; phrase: string; block?: string; reason?: string }[]
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
  plan_room?: number; directions?: string[]
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
}
export type Asset = {
  id: string; extraction_status: string; extraction_version?: string | null; page_count: number | null; origin: string; byte_size: number; original_filename: string | null
  // Sources only (D45): whether the text comes from the current extractor, and a later extraction that was not taken.
  current_extraction?: boolean; rejected_extraction?: { extraction_version: string; rejection_reason: string; created_at: string } | null
  // Sources only (D52): whether Marker has read the PDF's pages with mathematics.
  // A read's `equations_to_check` counts display equations that did not match the PDF's text layer, on pages `to_check`.
  equations?: { state: 'read' | 'no_math' | 'failed' | 'reading' | 'pending'; reason?: string | null; attempts?: number; pages?: number; started_at?: string; to_check?: number[]; equations_to_check?: number }
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
export type AssetText = {
  asset: Asset
  passages: { id: string; kind: 'pdf_page'; text: string; physical_page: number | null; printed_label: string | null; extraction_version: string | null; payload_ref: string | null; text_source?: 'text_layer' | 'ocr' | 'marker'; equations_to_check?: number }[]
  source: Passage['source']
}
// A figure found from its caption on a PDF page (D58); its picture is cut from the page by the server.
export type AssetFigure = { page: number; label: string; width: number; height: number }
export type PdfCandidate = {
  id: string; provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'web_search'; candidate_url: string; landing_url: string | null
  version_label: string | null; license: string | null; identity_status: 'doi_verified' | 'title_verified' | 'unverified' | 'mismatch'
  version_status: 'match' | 'different' | 'uncertain'; access_status: 'not_attempted' | 'downloaded' | 'http_error' | 'not_pdf' | 'too_large' | 'timeout' | 'blocked_url' | 'failed'
  http_status: number | null; error_code: string | null; final_url: string | null; discovered_at: string; attempted_at: string | null
}
export type PdfDiscovery = {
  provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'web_search'; query_text: string; status: string; result_count: number; other_title_count: number
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
  quotes: { part: string; quote: string; page: number | null }[]; after_run: boolean; decided_code: string | null
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
  text_source: 'text_layer' | 'ocr' | 'marker' | null  // null for abstracts; 'ocr' text was not checked against the page (D51)
  removed_from_research: boolean  // the source was removed from this research later; the quote still opens (D50)
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
  validation: { ok?: boolean; issues?: ValidationIssue[]; warnings?: ValidationIssue[]; note?: string }
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
export type QueueKind = 'confirm_quote' | 'choose_run' | 'choose_version' | 'confirm_pdf' | 'confirm_absent' | 'find_part' | 'look_again'
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
  passage_id: string | null; anchor_text: string | null
  closest?: { page: number; text: string; kind: 'exact' | 'normalized' | 'fuzzy'; ratio: number; passage_id: string | null } | null; closest_note?: string | null
}
export type QueueRun = { run_no: number; shown_pages: number[]; parts: QueuePart[] }
export type QueueDetail = {
  runs: QueueRun[]
  cues: { phrases: string[]; sentences: { page: number; sentence: string; passage_id: string | null }[]; total: number; note: string | null }
  asset_id: string | null  // the file in use for the row's version
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
  research: { id: string; title: string; current_scope_revision: number; version: number; created_at: string; updated_at: string }
  scope: Scope; runs: Run[]; search_runs: SearchRun[]; sources: Source[]; answers: Answer[]; counts: Counts; last_event_id: number
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
  answer_count: number; created_at: string; updated_at: string
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
  id: string; kind: Evidence['kind']; text: string; physical_page: number | null; printed_label: string | null
  abstract_origin: string | null; extraction_version: string | null; payload_ref: string | null; text_source?: 'text_layer' | 'ocr' | 'marker'; equations_to_check?: number; reading_depth: string; asset_id: string | null
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
export type ZoteroImport = { items: number; pdfs_added: number; notes: { title: string; note: string }[] }

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
  id: string; position: number; revision: number; version: number; origin: 'user' | 'model_suggestion' | 'template'
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
  text_source: 'text_layer' | 'ocr' | 'marker' | null
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
export type TableSummary = { id: string; title: string; version: number; created_at: string; updated_at: string; rows: number; columns: number }
export type TableTemplate = { id: string; name: string; columns: ColumnSpec[]; created_at: string }
export type CellEdit = { state: CellState; value: CellValue | null; note: string | null; keep_evidence_from: string | null; expected_version: number }

export class ApiError extends Error {
  status: number
  // A 422 from the approval route names every fault of the correction at once; the card shows them by their row.
  errors: string[]
  // A 409 of the human queue says why: `row_changed` or `reading_started` (slice 17).
  reason: string | null
  constructor(status: number, message: string, errors: string[] = [], reason: string | null = null) { super(message); this.status = status; this.errors = errors; this.reason = reason }
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
    let detail = response.statusText
    let errors: string[] = []
    let reason: string | null = null
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      // A validation refusal answers with a list of faults rather than one sentence (slice 08a).
      else if (Array.isArray(body.detail?.errors)) { errors = body.detail.errors.map(String); detail = errors.join(' · ') }
      else if (typeof body.detail?.message === 'string') { detail = body.detail.message; reason = typeof body.detail.reason === 'string' ? body.detail.reason : null }
    } catch { /* keep status text */ }
    throw new ApiError(response.status, detail, errors, reason)
  }
  return response.json() as Promise<T>
}

const json = (method: string, body: unknown, extra: Record<string, string> = {}): RequestInit =>
  ({ method, headers: { 'content-type': 'application/json', ...extra }, body: JSON.stringify(body) })

export const api = {
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
    return request<ResearchView & { uploaded_source_version_id: string }>(`/api/researches/${id}/uploads`, { method: 'POST', body: form })
  },
  setSeed: (id: string, sourceVersionId: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/seed`, json('POST', { source_version_id: sourceVersionId, expected_version: expectedVersion })),
  uploadToSource: (id: string, sourceId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/uploads`, { method: 'POST', body: form })
  },
  // Attaches PDFs from the user's Zotero library to included works that have no PDF text yet (D49).
  zoteroPdfs: (id: string, source: ZoteroSource) =>
    request<ResearchView & { zotero_pdfs: { checked: number; added: number; notes: { title: string; note: string }[] } }>(`/api/researches/${id}/zotero-pdfs`, json('POST', { source })),
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
    return request<ResearchView & { attached: { source_version_id: string; asset_id: string; reading: AttachOutcome } }>(`/api/researches/${id}/waiting/uploads`, { method: 'POST', body: form })
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
    return request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}`, { method: 'PUT', body: form })
  },
  reextractAsset: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView & { reextraction: Reextraction }>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}/extractions`, { method: 'POST' }),
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
  suggestTerms: (runId: string) => request<Run>(`/api/runs/${runId}/term-suggestions`, { method: 'POST' }),
  // After the model could not write the query: search with the code's query alone (D92).
  chooseCodeQuery: (runId: string) => request<Run>(`/api/runs/${runId}/search-query-choice`, { method: 'POST' }),
  passage: (id: string, passageId: string) => request<Passage>(`/api/researches/${id}/passages/${passageId}`),
  assetText: (id: string, assetId: string) => request<AssetText>(`/api/researches/${id}/assets/${assetId}/text`),
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
