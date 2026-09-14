import type { Evidence, RunStatus, Source, SourceScope } from './api'

export const scopeLabels: Record<SourceScope, string> = {
  academic: 'Academic search',
  attached: 'Attached files',
  attached_and_academic: 'Files + academic search',
}

export const runStatusLabels: Record<RunStatus, string> = {
  queued: 'Queued', running: 'Running', pause_requested: 'Pausing after the current call', paused: 'Paused',
  completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled',
}

const pauseReasons: Record<string, string> = {
  user_requested: 'You paused this run.',
  backend_restarted: 'DEIXIS was closed while this run was working. Completed steps are kept; resuming may repeat an unfinished search or model call.',
  model_connection_not_ready: 'The selected model connection is not ready. Nothing was sent to another model.',
  model_connection_unavailable: 'The selected model connection is not available. Nothing was sent to another model.',
  model_call_failed: 'The model call did not complete. Completed work is saved.',
  model_isolation_violation: 'The model session reported tool use or loaded instructions, so its output was rejected.',
  provider_rate_limited: 'OpenAlex rate-limited the request. Completed searches are kept; no other provider was used.',
  provider_auth_required: 'OpenAlex requires authentication for this request.',
  provider_entitlement_missing: 'The configured OpenAlex key was not accepted.',
  provider_timeout: 'OpenAlex did not answer in time. Whether the request was processed is unknown.',
  provider_failed: 'The OpenAlex request failed.',
  provider_parse_error: 'OpenAlex returned a response DEIXIS could not read.',
  budget_exhausted: 'This run reached its call budget.',
  invalid_model_output: 'The model output failed validation after one repair attempt.',
  no_included_sources: 'No source is included.',
  internal_error: 'An internal error stopped the run.',
  user_cancelled: 'You cancelled this run.',
  model_mismatch: 'Codex answered with a different model than the one chosen for this research. Its output was not used.',
  scope_revised: 'The question was revised while this run was working. Its remaining results were not applied.',
}
export const pauseReasonText = (reason: string | null) => (reason ? pauseReasons[reason] ?? reason : '')

export const stepLabel = (kind: string, key: string) => {
  if (kind === 'model:search_plan') return 'Search plan (model)'
  if (kind === 'model:screening') return 'Screening proposal (model)'
  if (kind === 'model:grounded_answer') return 'Source-linked answer (model)'
  if (kind.startsWith('provider_search')) return `OpenAlex search ${Number(key.split(':')[1]) + 1}`
  if (kind === 'fetch_pdf') return 'Open-access PDF retrieval'
  return kind
}

export function locatorText(e: Pick<Evidence, 'kind' | 'physical_page' | 'printed_label'>) {
  if (e.kind === 'abstract') return 'abstract'
  if (e.physical_page) return `PDF p. ${e.physical_page}${e.printed_label ? ` (printed ${e.printed_label})` : ''}`
  return 'section'
}

export function accessText(source: Source) {
  const parts: string[] = []
  const asset = source.access.assets[0]
  if (asset) parts.push(asset.extraction_status === 'no_text' ? 'PDF without a text layer (no OCR in this version)' : `PDF · ${asset.page_count ?? '?'} pages · text ${asset.extraction_status}`)
  else if (source.access.fetch?.status === 'failed') parts.push(`PDF not retrieved (${source.access.fetch.error_code?.replace('fetch_', '').replace('_', ' ')})`)
  else if (source.access.oa_pdf_url && source.access.oa_pdf_version !== source.version_label) parts.push(`Open-access PDF is a different version (${source.access.oa_pdf_version ?? 'version not stated'}) · not used`)
  else if (source.access.oa_pdf_url) parts.push('Open-access PDF listed · not yet retrieved')
  if (source.access.abstract_passage_id) parts.push(source.access.abstract_origin === 'provider_openalex_inverted_index' ? 'Abstract (rebuilt from OpenAlex index)' : 'Abstract')
  if (!parts.length) parts.push('Metadata only')
  return parts.join(' · ')
}
