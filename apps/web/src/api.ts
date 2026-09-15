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
}
export type Run = {
  id: string; research_id: string; scope_revision: number; kind: 'discovery' | 'answer'; status: RunStatus; stage: string
  pause_reason: string | null; error: unknown; budget: Record<string, number>; usage: Record<string, number>
  created_at: string; updated_at: string; version: number; steps?: Step[]
}
export type SearchRun = {
  id: string; run_id: string; scope_revision: number; provider: string; query_text: string; access_mode: string; status: string
  result_count: number; provider_total: number | null; page_limit: number; retrieved_at: string; error: { error: string | null; http_status: number | null } | null
}
export type Asset = { id: string; extraction_status: string; page_count: number | null; origin: string; byte_size: number; original_filename: string | null }
export type PdfCandidate = {
  id: string; provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'web_search'; candidate_url: string; landing_url: string | null
  version_label: string | null; license: string | null; identity_status: 'doi_verified' | 'title_verified' | 'unverified' | 'mismatch'
  version_status: 'match' | 'different' | 'uncertain'; access_status: 'not_attempted' | 'downloaded' | 'http_error' | 'not_pdf' | 'too_large' | 'timeout' | 'blocked_url' | 'failed'
  http_status: number | null; error_code: string | null; final_url: string | null; discovered_at: string; attempted_at: string | null
}
export type PdfDiscovery = {
  provider: 'unpaywall' | 'openalex' | 'crossref' | 'core' | 'web_search'; query_text: string; status: string; result_count: number
  http_status: number | null; error_code: string | null; created_at: string; finished_at: string | null
}
export type Source = {
  source_version_id: string; work_id: string; title: string; authors: string[]; year: number | null; venue: string | null
  volume: string | null; issue: string | null; pages: string | null
  doi: string | null; landing_url: string | null; version_label: string | null; publication_type: string | null
  cited_by_count: number | null; cited_by_count_at: string | null
  origin: 'provider' | 'user_upload'; added_by: string; rank: number | null; similarity: number | null
  found_in_revision: number | null; applicability: 'current' | 'stale_scope'; version_role: 'record' | 'other_version'
  access: { abstract_passage_id: string | null; abstract_origin: string | null; oa_pdf_url: string | null; oa_pdf_version: string | null; assets: Asset[]; fetch: { status: string; error_code: string | null } | null; pdf_candidates: PdfCandidate[]; pdf_discoveries: PdfDiscovery[] }
  selection: { state: 'included' | 'excluded' | 'pending'; origin: 'default' | 'model_proposal' | 'user'; version: number; proposal: string | null; proposal_reason: string | null; proposal_basis: string | null; user_reason: string | null }
  cited_in_latest_answer: boolean
  provider_records: string[]; suspected_duplicates: { source_version_id: string; basis: 'same_title' | 'published_doi' }[]
}
export type Evidence = {
  passage_id: string; source_version_id: string; kind: 'abstract' | 'pdf_page' | 'section'; physical_page: number | null
  printed_label: string | null; reading_depth: string; title: string; version_label: string | null; anchor_text: string | null
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
  claims: Claim[]; limitations: Limitation[]; unanswered_aspects: string[]; capability_notice: string | null
  clarification: { question: string; ambiguity: string; why_it_matters: string; options: string[] } | null
  unverified_draft: { claims?: { claim_label: string; text: string }[] } | null
  validation: { ok?: boolean; issues?: ValidationIssue[]; warnings?: ValidationIssue[]; note?: string }
  model: { connection: string; requested_model: string | null; resolved_model: string | null; token_usage: unknown } | null
  inputs_given: { sources: number; passages: number; source_ids: string[] } | null
  review: AnswerReview | null
}
export type Counts = { found: number; unique: number; included: number; excluded: number; pending: number; inspected: number; cited: number }
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
export type Passage = {
  id: string; kind: Evidence['kind']; text: string; physical_page: number | null; printed_label: string | null
  abstract_origin: string | null; extraction_version: string | null; payload_ref: string | null; reading_depth: string; asset_id: string | null
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
  id: 'claude_code' | 'codex' | 'gemini_cli' | 'ollama' | 'lm_studio'; name: string; kind: 'cli' | 'server'
  installed: boolean; version: string | null; path: string | null; role: 'runs_steps' | 'detected'
  running?: boolean; endpoint?: string; models?: LocalToolModel[]; install: LocalToolInstall; job: LocalToolJob
}
export type LocalTools = { machine: { chip: string | null; memory_gb: number | null; disk_free_gb: number | null }; tools: LocalTool[] }
export type SemanticSearchProvider = 'gemini' | 'openai' | 'ollama' | 'lm_studio' | 'off'
export type SemanticSearchOption = { provider: SemanticSearchProvider; models: string[]; available: boolean; reason: string | null }
export type SemanticSearch = { provider: SemanticSearchProvider; model: string | null; explicit: boolean; options: SemanticSearchOption[] }
export type InstitutionalAccess = { status: 'institutional' | 'none' | 'unknown' | 'not_checked'; via?: string; reason?: string }
export type QuickFindResult = {
  researches: { id: string; title: string; question: string; updated_at: string }[]
  sources: { source_version_id: string; title: string; year: number | null; version_label: string | null; research_id: string; research_title: string }[]
}
export type ActivityEvent ={ id: number; type: string; run_id: string | null; payload: Record<string, unknown>; created_at: string }
export type ZoteroSource = 'local' | 'web'
export type ZoteroCollection = { key: string; name: string }
export type ZoteroImport = { items: number; pdfs_added: number; notes: { title: string; note: string }[] }

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
  trash: () => request<TrashedResearch[]>('/api/trash'),
  moveToTrash: (id: string) => request<{ trashed: boolean }>(`/api/researches/${id}`, { method: 'DELETE' }),
  restore: (id: string) => request<{ restored: boolean }>(`/api/trash/${id}/restore`, { method: 'POST' }),
  deletePermanently: (id: string) => request<{ deleted: boolean; files_not_removed: string[] }>(`/api/trash/${id}`, { method: 'DELETE' }),
  search: (q: string) => request<QuickFindResult>(`/api/search?q=${encodeURIComponent(q)}`),
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
  removeAsset: (id: string, sourceId: string, assetId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/assets/${assetId}`, { method: 'DELETE' }),
  discoverPdf: (id: string, sourceId: string) =>
    request<ResearchView>(`/api/researches/${id}/sources/${sourceId}/pdf-discovery`, { method: 'POST' }),
  startRun: (id: string, kind: 'discovery' | 'answer', idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/runs`, json('POST', { kind }, { 'Idempotency-Key': idempotencyKey })),
  controlRun: (runId: string, action: 'pause' | 'resume' | 'cancel') => request<Run>(`/api/runs/${runId}/${action}`, { method: 'POST' }),
  select: (id: string, sourceId: string, state: Source['selection']['state'], expectedVersion: number, reason?: string) =>
    request<unknown>(`/api/researches/${id}/selections/${sourceId}`, json('PATCH', { state, expected_version: expectedVersion, reason })),
  reviseScope: (id: string, question: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/scope`, json('POST', { question, expected_version: expectedVersion })),
  passage: (id: string, passageId: string) => request<Passage>(`/api/researches/${id}/passages/${passageId}`),
  events: (id: string, after = 0) => request<ActivityEvent[]>(`/api/researches/${id}/events?after=${after}`),
  connections: (refresh = false) => request<Connections>(`/api/connections${refresh ? '?refresh=true' : ''}`),
  modelConnection: (connection: string, refresh = false) => request<ModelHealth>(`/api/connections/${encodeURIComponent(connection)}${refresh ? '?refresh=true' : ''}`),
  institutionalAccess: () => request<InstitutionalAccess>('/api/institutional-access'),
  credentials: () => request<Credentials>('/api/credentials'),
  saveCredential: (env: string, value: string) => request<{ key: KeyEntry; test: KeyTest | null }>(`/api/credentials/${env}`, json('PUT', { value })),
  removeCredential: (env: string) => request<{ key: KeyEntry }>(`/api/credentials/${env}`, { method: 'DELETE' }),
  testCredential: (env: string) => request<KeyTest>(`/api/credentials/${env}/test`, { method: 'POST' }),
  localTools: (refresh = false) => request<LocalTools>(`/api/local-tools${refresh ? '?refresh=true' : ''}`),
  installLocalTool: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/install`, { method: 'POST' }),
  cancelLocalToolInstall: (id: string) => request<{ job: LocalToolJob }>(`/api/local-tools/${id}/cancel`, { method: 'POST' }),
  semanticSearch: () => request<SemanticSearch>('/api/semantic-search'),
  saveSemanticSearch: (provider: SemanticSearchProvider, model: string | null) =>
    request<SemanticSearch>('/api/semantic-search', json('PUT', { provider, model })),
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
