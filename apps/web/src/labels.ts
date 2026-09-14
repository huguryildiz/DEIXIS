import type { Evidence, RunStatus, Source, SourceScope, Verdict } from './api'
import { t, uiLocale } from './i18n'

// Label records hold English text; callers show them through t().

export const scopeLabels: Record<SourceScope, string> = {
  academic: 'Academic search',
  attached: 'Attached files',
  attached_and_academic: 'Files + academic search',
}

// Codex reports effort ids such as "xhigh"; unknown ids are shown as given.
const reasoningNames: Record<string, string> = { none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max', ultra: 'Ultra' }
export const reasoningLabel = (id: string) => t(reasoningNames[id] ?? id)

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
  provider_rate_limited: 'A scholarly provider rate-limited a search. Completed searches are kept; no other provider was used in its place.',
  provider_auth_required: 'A scholarly provider requires authentication for this search.',
  provider_entitlement_missing: 'A scholarly provider did not accept the configured key.',
  provider_timeout: 'A scholarly provider did not answer in time. Whether the search was processed is unknown.',
  provider_failed: 'A scholarly provider search failed.',
  provider_parse_error: 'A scholarly provider returned a response DEIXIS could not read.',
  budget_exhausted: 'This run reached its call budget.',
  invalid_model_output: 'The model output failed validation after one repair attempt.',
  no_included_sources: 'No source is included.',
  internal_error: 'An internal error stopped the run.',
  user_cancelled: 'You cancelled this run.',
  model_mismatch: 'Codex answered with a different model than the one chosen for this research. Its output was not used.',
  scope_revised: 'The question was revised while this run was working. Its remaining results were not applied.',
}
export const pauseReasonText = (reason: string | null) => (reason ? t(pauseReasons[reason] ?? reason) : '')

const stageNames: Record<string, string> = { claim_check: 'claim review' }
export const stageLabel = (stage: string) => t(stageNames[stage] ?? stage)

export const verdictLabels: Record<Verdict, string> = {
  supported: 'supported', partially_supported: 'partly supported', not_supported: 'not supported', cannot_assess: 'cannot assess',
}

const providerNames: Record<string, string> = {
  openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', ieee_xplore: 'IEEE Xplore', scopus: 'Scopus', serpapi: 'SerpApi', zotero: 'Zotero',
}
export const providerName = (id: string) => providerNames[id] ?? id

export const stepLabel = (kind: string, key: string) => {
  if (kind === 'model:search_plan') return t('Search plan (model)')
  if (kind === 'model:screening') return t('Screening proposal (model)')
  if (kind === 'model:grounded_answer') return t('Source-linked answer (model)')
  if (kind === 'model:answer_review') return t('Claim review (reviewer model)')
  if (kind.startsWith('provider_search')) return t('{provider} search {n}', { provider: providerName(kind.split(':')[1] ?? ''), n: Number(key.split(':')[1]) + 1 })
  if (kind === 'fetch_pdf') return t('Open-access PDF retrieval')
  return kind
}

export function locatorText(e: Pick<Evidence, 'kind' | 'physical_page' | 'printed_label'>) {
  if (e.kind === 'abstract') return t('abstract')
  if (e.physical_page) return e.printed_label ? t('PDF p. {page} (printed {label})', { page: e.physical_page, label: e.printed_label }) : t('PDF p. {page}', { page: e.physical_page })
  return t('section')
}

const versionNames: Record<string, string> = {
  publishedVersion: 'published version', acceptedVersion: 'accepted manuscript', submittedVersion: 'submitted manuscript',
}
export const versionText = (label: string | null) => (label ? t(versionNames[label] ?? label) : t('version not stated'))
// OpenAlex's count; other indexes (Google Scholar, Scopus) report different numbers.
export const citedText = (count: number | null) => (count === null ? '' : t('cited by {count} (OpenAlex)', { count: count.toLocaleString(uiLocale()) }))

// Each part carries a tone so the source list can colour usable text apart from gaps.
export function accessParts(source: Source): { tone: 'text' | 'abstract' | 'unstated'; text: string }[] {
  const parts: { tone: 'text' | 'abstract' | 'unstated'; text: string }[] = []
  const asset = source.access.assets[0]
  if (asset) parts.push(asset.extraction_status === 'no_text' ? { tone: 'unstated', text: t('PDF without a text layer (no OCR in this version)') } : { tone: 'text', text: t('PDF · {pages} pages · text {status}', { pages: asset.page_count ?? '?', status: t(asset.extraction_status) }) })
  else if (source.access.fetch?.status === 'failed') parts.push({ tone: 'unstated', text: t('PDF not retrieved ({reason})', { reason: source.access.fetch.error_code?.replace('fetch_', '').replace('_', ' ') ?? '' }) })
  else if (source.access.oa_pdf_url && source.access.oa_pdf_version !== source.version_label) parts.push({ tone: 'unstated', text: t('Open-access PDF is a different version ({version}) · not used for this version', { version: versionText(source.access.oa_pdf_version) }) })
  else if (source.access.oa_pdf_url) parts.push({ tone: 'unstated', text: t('Open-access PDF listed · not yet retrieved') })
  if (source.access.abstract_passage_id) parts.push({ tone: 'abstract', text: t(source.access.abstract_origin === 'provider_openalex_inverted_index' ? 'Abstract (rebuilt from OpenAlex index)' : 'Abstract') })
  if (!parts.length) parts.push({ tone: 'unstated', text: t('Metadata only') })
  return parts
}
