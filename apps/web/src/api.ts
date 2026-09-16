// Client for the local DEIXIS API. Types mirror backend/deixis/workflow/views.py.

export type RunStatus = 'queued' | 'running' | 'pause_requested' | 'paused' | 'completed' | 'failed' | 'cancelled'
export type SourceScope = 'academic' | 'attached' | 'attached_and_academic'
export type Effort = 'quick' | 'standard' | 'detailed'

export type Scope = {
  research_id: string; revision: number; question: string; language_hint: string | null; source_scope: SourceScope
  providers: string[]; effort: Effort; model_connection: string; requested_model: string | null; reasoning_effort: string | null
  // null literature model: the research model runs the search steps (researches created before model roles).
  literature_model: string | null; literature_reasoning_effort: string | null
  review_mode: ReviewMode; review_model: string | null; review_reasoning_effort: string | null
  // null connection: the role uses model_connection (researches created before per-role connections).
  literature_connection: string | null; review_connection: string | null
  steering: string | null; created_at: string
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
  output: { page_count?: number | null; passage_count?: number; model?: string; sources?: number; passages?: number; embedded?: number } | null
}
// What the search plan step reported, as the model wrote it.
export type SearchPlan = {
  question_interpretation: string; search_rationale: string; scope_boundaries: string[]
  concepts: { label: string; role: string; synonyms: string[] }[]
  queries: { provider_id: string; query_text: string; rationale: string }[]
}
export type RunKind = 'discovery' | 'answer' | 'pdf_collection' | 'table_columns' | 'table_fill' | 'cell_recheck' | 'research_title'
// What a table run works on, as stored when it was requested (D38); null for discovery and answer runs.
export type RunTarget = {
  table_id: string; column_id?: string; source_version_id?: string; cell_version?: number
  sources?: { source_version_id: string; column_ids: string[] }[]
}
export type Run = {
  id: string; research_id: string; scope_revision: number; kind: RunKind; status: RunStatus; stage: string
  pause_reason: string | null; error: unknown; budget: Record<string, number>; usage: Record<string, number>
  created_at: string; updated_at: string; version: number; steps?: Step[]; target: RunTarget | null
  // plan null: this run wrote no search plan. screening_notes: the note of each screening batch, in order, with its step.
  plan: SearchPlan | null; screening_notes: { step_id: string; text: string }[]
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
}
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
export type Source = {
  source_version_id: string; work_id: string; title: string; authors: string[]; year: number | null; venue: string | null
  volume: string | null; issue: string | null; pages: string | null
  doi: string | null; landing_url: string | null; version_label: string | null; publication_type: string | null
  cited_by_count: number | null; cited_by_count_at: string | null
  origin: 'provider' | 'user_upload'; added_by: string; added_at: string; rank: number | null; similarity: number | null
  found_in_revision: number | null; applicability: 'current' | 'stale_scope'; version_role: 'record' | 'other_version'
  // The other version of the work whose text answers read, when the record has no PDF text (D48).
  answer_reads_version_id: string | null
  // Whether an answer reads this version's PDF pages rather than its abstract (D49).
  has_pdf_text: boolean
  access: { abstract_passage_id: string | null; abstract_origin: string | null; oa_pdf_url: string | null; oa_pdf_version: string | null; assets: Asset[]; replaced_assets: ReplacedAsset[]; fetch: { status: string; error_code: string | null; http_status: number | null } | null; other_copy: { status: string; error_code: string | null } | null; pdf_candidates: PdfCandidate[]; pdf_discoveries: PdfDiscovery[] }
  selection: { state: 'included' | 'excluded' | 'pending'; origin: 'default' | 'model_proposal' | 'user'; version: number; proposal: string | null; proposal_reason: string | null; proposal_basis: string | null; user_reason: string | null }
  cited_in_latest_answer: boolean
  provider_records: string[]; suspected_duplicates: { source_version_id: string; basis: 'same_title' | 'published_doi' }[]
}
export type Evidence = {
  passage_id: string; source_version_id: string; kind: 'abstract' | 'pdf_page' | 'section'; physical_page: number | null
  printed_label: string | null; reading_depth: string; title: string; version_label: string | null; anchor_text: string | null
  evidence_status: EvidenceStatus
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
  review: AnswerReview | null
}
export type Counts = {
  found: number; unique: number; included: number; excluded: number; pending: number; inspected: number; cited: number
  // Works the user removed from this research, and those of them a later search found again; neither is listed (D50).
  removed: number; removed_found_again: number
}
export type ResearchView = {
  research: { id: string; title: string; current_scope_revision: number; version: number; created_at: string; updated_at: string }
  scope: Scope; runs: Run[]; search_runs: SearchRun[]; sources: Source[]; answers: Answer[]; counts: Counts; last_event_id: number
  // The reviewer the next answer gets: the research's own setting, else the app-wide default. model null: no review.
  reviewer: { mode: ReviewMode; connection: string | null; model: string | null; reasoning_effort: string | null }
}
export type ResearchSummary = {
  id: string; title: string; question: string; source_scope: SourceScope; effort: Effort; last_run_status: RunStatus | null
  answer_count: number; created_at: string; updated_at: string
}
export type TrashedResearch = { id: string; title: string; trashed_at: string }
// The Trash page's groups (D50); a trashed research's tables and removed sources go and come back with it and are not listed.
export type TrashedTable = { id: string; title: string; research_id: string; research_title: string; version: number; trashed_at: string; rows: number; columns: number; cells: number; human_edits: number }
export type RemovedSource = {
  source_version_id: string; work_id: string; title: string; version_label: string | null; year: number | null; research_id: string; research_title: string
  removed_at: string; removal_note: string | null; found_again_at: string | null; quotes: number; cells: number
}
export type TrashedTemplate = { id: string; name: string; trashed_at: string; columns: number }
export type Trash = { researches: TrashedResearch[]; tables: TrashedTable[]; sources: RemovedSource[]; templates: TrashedTemplate[] }
export type Passage = {
  id: string; kind: Evidence['kind']; text: string; physical_page: number | null; printed_label: string | null
  abstract_origin: string | null; extraction_version: string | null; payload_ref: string | null; text_source?: 'text_layer' | 'ocr' | 'marker'; equations_to_check?: number; reading_depth: string; asset_id: string | null
  evidence_status: EvidenceStatus
  removed_from_research: boolean
  source: { id: string; work_id: string; title: string; authors: string[]; year: number | null; venue: string | null; doi: string | null; landing_url: string | null; version_label: string | null; origin: string; cited_by_count: number | null; cited_by_count_at: string | null }
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
export type Connections = { models: Record<string, ModelHealth>; providers: { id: string; implemented: boolean; access_mode: string | null; supplementary?: boolean; note: string }[] }
export type Keychain = { available: boolean; name: string | null }
export type KeyEntry = { env: string; group: 'model' | 'source'; service: string; configured: boolean; source: 'keychain' | 'environment' | null; testable: boolean }
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
  reading: { asset_id: string; pages: number; started_at: string } | null
  pdfs: Partial<Record<'read' | 'no_math' | 'failed' | 'reading' | 'pending', number>>
}
export type LocalTools = { machine: { chip: string | null; memory_gb: number | null; disk_free_gb: number | null }; tools: LocalTool[] }
export type SemanticSearchProvider = 'gemini' | 'openai' | 'ollama' | 'lm_studio' | 'off'
export type SemanticSearchOption = { provider: SemanticSearchProvider; models: string[]; available: boolean; reason: string | null }
export type SemanticSearch = { provider: SemanticSearchProvider; model: string | null; explicit: boolean; options: SemanticSearchOption[] }
export type InstitutionalAccess = { status: 'institutional' | 'none' | 'unknown' | 'not_checked'; via?: string; reason?: string }
// Reading depth of a stored source version: a PDF text layer, an abstract, or bare metadata.
export type AccessLevel = 'pdf_available' | 'abstract' | 'metadata'
export type LibraryVersion = { source_version_id: string; version_label: string | null; year: number | null; venue: string | null; access_level: AccessLevel }
export type LibraryResearch = { id: string; title: string; updated_at: string }
export type LibraryEntry = {
  work_id: string; title: string; authors: string[]; year: number | null; venue: string | null
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
  abstract: string | null; abstract_origin: string | null
  asset: { id: string; page_count: number | null; original_filename: string | null; extraction_status: string } | null
  research_id: string | null
}
export type LibraryWork = {
  work_id: string; title: string; authors: string[]; year: number | null; venue: string | null
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
  source_version_id: string; work_id: string; title: string; authors: string[]; year: number | null; version_label: string | null
  selection_state: 'included' | 'excluded' | 'pending' | null; added_by: 'included_at_creation' | 'user'; added_at: string; removed_at: string | null
  access_level: 'pdf_available' | 'abstract' | 'metadata'
}
export type CellValue = { option_ids?: string[]; number?: number; unit?: string | null; as_stated?: string | null; answer?: 'yes' | 'no'; text?: string }
export type CellEvidence = {
  passage_id: string; anchor_text: string | null; anchor_match: 'exact' | 'normalized' | 'fuzzy' | null; kind: Evidence['kind']
  physical_page: number | null; printed_label: string | null; asset_id: string | null; evidence_status: EvidenceStatus
}
export type CellRevision = {
  id: string; kind: 'model_fill' | 'model_proposal' | 'system_fill' | 'human_edit' | 'accept_proposal' | 'dismiss_proposal'
  author: 'model' | 'human' | 'system'; based_on_revision_id: string | null; column_revision: number; state: CellState | null
  value: CellValue | null; note: string | null; reading_depth: 'metadata' | 'abstract' | 'selected_sections' | 'full_text' | null
  output_status: 'structurally_valid' | 'unverified_draft' | null; cell_version_at_request: number | null; scope_revision: number | null
  run_id: string | null; created_at: string; model: { connection: string | null; resolved_model: string | null } | null; evidence: CellEvidence[]
  decision?: 'accepted' | 'dismissed' | 'pending' | 'superseded'  // model proposals in a cell's history
}
export type CellFlag = 'stale_column' | 'pdf_removed' | 'pdf_replaced' | 'text_superseded' | 'proposal_before_edit' | 'proposal_invalid'
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
  constructor(status: number, message: string) { super(message); this.status = status }
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
    try { const body = await response.json(); if (typeof body.detail === 'string') detail = body.detail } catch { /* keep status text */ }
    throw new ApiError(response.status, detail)
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
  create: (body: {
    question: string; source_scope: SourceScope; effort: Effort; model_connection: string; requested_model: string; reasoning_effort: string | null
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
    return request<ResearchView>(`/api/researches/${id}/uploads`, { method: 'POST', body: form })
  },
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
  // Takes sources out of this research; the library record, its files and the evidence citing it stay (D50).
  removeSources: (id: string, sourceIds: string[], note?: string) =>
    request<ResearchView & { changed_source_version_ids: string[] }>(`/api/researches/${id}/sources`, json('DELETE', { source_version_ids: sourceIds, note })),
  restoreSources: (id: string, sourceIds: string[]) =>
    request<ResearchView & { changed_source_version_ids: string[] }>(`/api/researches/${id}/sources/restore`, json('POST', { source_version_ids: sourceIds })),
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
  controlRun: (runId: string, action: 'pause' | 'resume' | 'cancel') => request<Run>(`/api/runs/${runId}/${action}`, { method: 'POST' }),
  select: (id: string, sourceId: string, state: Source['selection']['state'], expectedVersion: number, reason?: string) =>
    request<unknown>(`/api/researches/${id}/selections/${sourceId}`, json('PATCH', { state, expected_version: expectedVersion, reason })),
  reviseScope: (id: string, question: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/scope`, json('POST', { question, expected_version: expectedVersion })),
  passage: (id: string, passageId: string) => request<Passage>(`/api/researches/${id}/passages/${passageId}`),
  assetText: (id: string, assetId: string) => request<AssetText>(`/api/researches/${id}/assets/${assetId}/text`),
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
  localTools: (refresh = false) => request<LocalTools>(`/api/local-tools${refresh ? '?refresh=true' : ''}`),
  installLocalTool: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/install`, { method: 'POST' }),
  cancelLocalToolInstall: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/cancel`, { method: 'POST' }),
  semanticSearch: () => request<SemanticSearch>('/api/semantic-search'),
  saveSemanticSearch: (provider: SemanticSearchProvider, model: string | null) =>
    request<SemanticSearch>('/api/semantic-search', json('PUT', { provider, model })),
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

export const bibliographyUrl = (researchId: string, format: 'bibtex' | 'ris', sources: 'included' | 'cited') =>
  `/api/researches/${researchId}/bibliography?format=${format}&sources=${sources}`

const textFragment = (text: string) => encodeURIComponent(text.replace(/\s+/g, ' ').trim()).replace(/-/g, '%2D')

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
