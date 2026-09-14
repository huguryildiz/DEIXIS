// Client for the local DEIXIS API. Types mirror backend/deixis/workflow/views.py.

export type RunStatus = 'queued' | 'running' | 'pause_requested' | 'paused' | 'completed' | 'failed' | 'cancelled'
export type SourceScope = 'academic' | 'attached' | 'attached_and_academic'
export type Effort = 'quick' | 'standard' | 'detailed'

export type Scope = {
  research_id: string; revision: number; question: string; language_hint: string | null; source_scope: SourceScope
  providers: string[]; effort: Effort; model_connection: string; requested_model: string | null; steering: string | null; created_at: string
}
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
  id: string; run_id: string; provider: string; query_text: string; access_mode: string; status: string
  result_count: number; provider_total: number | null; page_limit: number; retrieved_at: string; error: { error: string | null; http_status: number | null } | null
}
export type Asset = { id: string; extraction_status: string; page_count: number | null; origin: string; byte_size: number }
export type Source = {
  source_version_id: string; work_id: string; title: string; authors: string[]; year: number | null; venue: string | null
  doi: string | null; landing_url: string | null; version_label: string | null; publication_type: string | null
  origin: 'provider' | 'user_upload'; added_by: string; rank: number | null
  access: { abstract_passage_id: string | null; abstract_origin: string | null; oa_pdf_url: string | null; oa_pdf_version: string | null; assets: Asset[]; fetch: { status: string; error_code: string | null } | null }
  selection: { state: 'included' | 'excluded' | 'pending'; origin: 'default' | 'model_proposal' | 'user'; version: number; proposal: string | null; proposal_reason: string | null; proposal_basis: string | null; user_reason: string | null }
  cited_in_latest_answer: boolean
}
export type Evidence = {
  passage_id: string; source_version_id: string; kind: 'abstract' | 'pdf_page' | 'section'; physical_page: number | null
  printed_label: string | null; reading_depth: string; title: string
}
export type Claim = { id: string; label: string; text: string; support_type: 'source_stated' | 'analyst_inference'; semantic_review: string; evidence: Evidence[] }
export type Limitation = { kind: string; text: string; source_ids: string[] }
export type ValidationIssue = { code: string; path: string; message: string }
export type Answer = {
  id: string; run_id: string; status: 'structurally_valid' | 'unverified_draft' | 'clarification' | 'no_evidence'
  scope_revision: number; applicability: 'current' | 'stale_scope' | 'stale_selection'; answer_language: string | null; created_at: string
  claims: Claim[]; limitations: Limitation[]; unanswered_aspects: string[]; capability_notice: string | null
  clarification: { question: string; ambiguity: string; why_it_matters: string; options: string[] } | null
  unverified_draft: { claims?: { claim_label: string; text: string }[] } | null
  validation: { ok?: boolean; issues?: ValidationIssue[]; note?: string }
  model: { connection: string; requested_model: string | null; resolved_model: string | null; token_usage: unknown } | null
  inputs_given: { sources: number; passages: number; source_ids: string[] } | null
}
export type Counts = { found: number; unique: number; included: number; excluded: number; pending: number; inspected: number; cited: number }
export type ResearchView = {
  research: { id: string; title: string; current_scope_revision: number; version: number; created_at: string; updated_at: string }
  scope: Scope; runs: Run[]; search_runs: SearchRun[]; sources: Source[]; answers: Answer[]; counts: Counts; last_event_id: number
}
export type ResearchSummary = {
  id: string; title: string; question: string; source_scope: SourceScope; effort: Effort; last_run_status: RunStatus | null
  answer_count: number; created_at: string; updated_at: string
}
export type Passage = {
  id: string; kind: Evidence['kind']; text: string; physical_page: number | null; printed_label: string | null
  abstract_origin: string | null; extraction_version: string | null; payload_ref: string | null; reading_depth: string; asset_id: string | null
  source: { id: string; work_id: string; title: string; authors: string[]; year: number | null; venue: string | null; doi: string | null; landing_url: string | null; version_label: string | null; origin: string }
}
export type ModelHealth = {
  connection: string; ready: boolean; reason?: string | null; installed?: boolean; cli_version?: string; signed_in?: boolean
  account_type?: string | null; plan_type?: string | null; models?: { id: string; display_name: string; is_default: boolean }[]
  isolation?: { instruction_sources: number; live_mcp_servers: string[] }
}
export type Connections = { models: Record<string, ModelHealth>; providers: { id: string; implemented: boolean; access_mode: string | null; note: string }[] }
export type ActivityEvent = { id: number; type: string; run_id: string | null; payload: Record<string, unknown>; created_at: string }

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
  research: (id: string) => request<ResearchView>(`/api/researches/${id}`),
  create: (body: { question: string; source_scope: SourceScope; effort: Effort; model_connection: string; requested_model: string }) =>
    request<ResearchView>('/api/researches', json('POST', body)),
  upload: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResearchView>(`/api/researches/${id}/uploads`, { method: 'POST', body: form })
  },
  startRun: (id: string, kind: 'discovery' | 'answer', idempotencyKey: string) =>
    request<Run>(`/api/researches/${id}/runs`, json('POST', { kind }, { 'Idempotency-Key': idempotencyKey })),
  controlRun: (runId: string, action: 'pause' | 'resume' | 'cancel') => request<Run>(`/api/runs/${runId}/${action}`, { method: 'POST' }),
  select: (id: string, sourceId: string, state: Source['selection']['state'], expectedVersion: number) =>
    request<unknown>(`/api/researches/${id}/selections/${sourceId}`, json('PATCH', { state, expected_version: expectedVersion })),
  reviseScope: (id: string, question: string, expectedVersion: number) =>
    request<ResearchView>(`/api/researches/${id}/scope`, json('POST', { question, expected_version: expectedVersion })),
  passage: (id: string, passageId: string) => request<Passage>(`/api/researches/${id}/passages/${passageId}`),
  events: (id: string, after = 0) => request<ActivityEvent[]>(`/api/researches/${id}/events?after=${after}`),
  connections: (refresh = false) => request<Connections>(`/api/connections${refresh ? '?refresh=true' : ''}`),
}

export const assetUrl = (researchId: string, assetId: string, page?: number | null) =>
  `/api/researches/${researchId}/assets/${assetId}${page ? `#page=${page}` : ''}`

export function subscribe(researchId: string, after: number, onEvent: () => void): () => void {
  const source = new EventSource(`/api/researches/${researchId}/events/stream?after=${after}`)
  source.onmessage = () => onEvent()
  return () => source.close()
}
