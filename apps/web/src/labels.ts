import type { ApprovalBlock, Evidence, RunKind, RunStatus, Source, SourceScope, Verdict } from './api'
import { t, uiLocale } from './i18n'

// Label records hold English text; callers show them through t().

export const scopeLabels: Record<SourceScope, string> = {
  academic: 'Academic search',
  attached: 'Attached files',
  attached_and_academic: 'Files + academic search',
}

export const versionTones: Record<string, string> = { publishedVersion: 'published', acceptedVersion: 'accepted', submittedVersion: 'submitted' }

// Codex reports effort ids such as "xhigh"; unknown ids are shown as given.
const reasoningNames: Record<string, string> = { none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max', ultra: 'Ultra' }
export const reasoningLabel = (id: string) => t(reasoningNames[id] ?? id)

export const runStatusLabels: Record<RunStatus, string> = {
  queued: 'Queued', running: 'Running', pause_requested: 'Pausing after the current call', paused: 'Paused',
  completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled',
}

export const runKindLabels: Record<RunKind, string> = {
  discovery: 'Search & screening', answer: 'Answer', pdf_collection: 'PDF collection', pdf_ocr: 'OCR reading', table_fill: 'Table fill', cell_recheck: 'Cell recheck', table_columns: 'Column suggestions', research_title: 'Research title',
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
  model_mismatch: 'The connection answered with a different model than the one chosen for this step. Its output was not used.',
  scope_revised: 'The question was revised while this run was working. Its remaining results were not applied.',
  table_unavailable: 'The table was removed while this run was waiting.',
  cell_unavailable: 'The cell’s column or row left the table before the recheck ran.',
  no_text: 'The source has no stored text to read.',
  equations_failed: 'Reading the equations of a PDF failed. Resume to answer from that PDF’s text layer.',
  equations_blocked_by_run: 'A PDF’s equations could not be stored while another run uses the same source. Resume when that run ends.',
  equation_reader_unavailable: 'The equation reader (Marker) could not start. Resume to answer from the PDFs’ text layer.',
  ocr_pages_failed: 'OCR could not read some pages. Nothing was stored; resuming reads only those pages again.',
  ocr_blocked_by_run: 'The OCR text could not be stored while another run uses the same source. Resume when that run ends.',
  ocr_pages_changed: 'The PDF’s pages without text changed while OCR was running. Nothing was stored; start OCR again.',
  asset_removed: 'The PDF was removed from the source before OCR finished. Nothing was stored.',
  extraction_failed: 'The PDF could not be opened to find its pages without text.',
  // The sw workflow's own stops: the run has searched nothing yet and waits for the user (D80).
  protocol_approval_needed: 'This run has not searched yet. Check the search terms and the inclusion criterion below, correct them if needed, and approve them.',
  key_terms_needed: 'DEIXIS reads search terms from an English question and does not translate. Revise the question in English, or give the English key terms below.',
  vocabulary_empty: 'No term is left that a provider query could be built from. Add a term below, or move one back into the setting or task block.',
  vocabulary_too_broad: 'Every remaining term is too frequent to search on its own, and they are all in one block. Add a term to the other block, or replace one with a narrower phrase.',
}
export const pauseReasonText = (reason: string | null) => (reason ? t(pauseReasons[reason] ?? reason) : '')

// ---- the protocol approval card (D80) ----
// The five blocks a term can sit in, and what each one does with it.
export const blockLabels: Record<ApprovalBlock, string> = {
  setting: 'Setting', task: 'Task', outcome: 'Outcome', claim: 'Claim under test', exclusion: 'Excluded words',
}
export const blockNotes: Record<ApprovalBlock, string> = {
  setting: 'Searched: one part of the provider query.',
  task: 'Searched: the other part of the provider query.',
  outcome: 'Not searched; used to order the records that were found.',
  claim: 'Not searched: a record that states the claim is what the search is looking for.',
  exclusion: 'Not searched. Kept with the protocol; in this version no record is kept out by them yet.',
}
// Who supplied a phrase, and who put it in its block. Both are shown, because they answer different questions.
const termOrigins: Record<string, string> = { question: 'from the question', key_terms: 'from your key terms', user: 'added by you' }
const blockOrigins: Record<string, string> = { rule: 'block by rule', model: 'block by the model', user: 'block by you' }
export const termOriginText = (origin: string) => t(termOrigins[origin] ?? origin)
export const blockOriginText = (origin: string) => t(blockOrigins[origin] ?? origin)
// Why a phrase left the query. It stays on record with its reason rather than disappearing.
const dropReasons: Record<string, string> = { zero_results: 'no record holds it' }
export const dropReasonText = (reason: string) => t(dropReasons[reason] ?? reason)
const approvedByNames: Record<string, string> = {
  user: 'You approved these search terms and this criterion.',
  setting: 'Approved as proposed by the unattended setting, not by a person.',
  earlier_approval: 'Approved with the correction you made earlier for this question.',
}
export const approvedByText = (by: string | null) => (by ? t(approvedByNames[by] ?? by) : '')

const stageNames: Record<string, string> = { claim_check: 'claim review' }
export const stageLabel = (stage: string) => t(stageNames[stage] ?? stage)

export const verdictLabels: Record<Verdict, string> = {
  supported: 'supported', partially_supported: 'partly supported', not_supported: 'not supported', cannot_assess: 'cannot assess',
}

const providerNames: Record<string, string> = {
  unpaywall: 'Unpaywall', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', ieee_xplore: 'IEEE Xplore', scopus: 'Scopus', core: 'CORE', serpapi: 'SerpApi', web_search: 'Web Search', zotero: 'Zotero',
}
export const providerName = (id: string) => providerNames[id] ?? id

export const connectionNames: Record<string, string> = { codex: 'Codex', claude: 'Claude Code', deepseek: 'DeepSeek', gemini: 'Gemini', kimi: 'Kimi', grok: 'Grok', copilot: 'GitHub Copilot', glm: 'GLM', muse_spark: 'Muse Spark', muse_glimmer: 'Muse Glimmer', ollama: 'Ollama', qwen: 'Qwen', mistral: 'Mistral' }
export const connectionName = (id: string) => connectionNames[id] ?? id
export const isPlannedModel = (reason?: string | null) => reason === 'Adapter not implemented in this version'

export const localToolNames: Record<string, string> = { claude_code: 'Claude Code', codex: 'Codex CLI', gemini_cli: 'Gemini CLI', ollama: 'Ollama', lm_studio: 'LM Studio', zotero: 'Zotero' }
export const localToolIcon = (id: string) => (id === 'gemini_cli' ? 'gemini' : id)

export const stepLabel = (kind: string, key: string) => {
  if (kind === 'model:search_plan') return t('Search plan (model)')
  if (kind === 'model:screening') return t('Screening proposal (model)')
  if (kind === 'code:abstract_stage') return t('Abstract screening (code)')
  if (kind === 'model:abstract_screening') return t('Abstract screening proposal (model)')
  if (kind === 'model:grounded_answer') return t('Source-linked answer (model)')
  if (kind === 'model:answer_review') return t('Claim review (reviewer model)')
  if (kind === 'model:cell_extraction') return t('Cell extraction (model)')
  if (kind === 'model:table_columns') return t('Column suggestions (model)')
  if (kind === 'model:research_title') return t('Research title (model)')
  if (kind === 'table_no_text') return t('Source without stored text')
  if (kind.startsWith('provider_search')) return t('{provider} search {n}', { provider: providerName(kind.split(':')[1] ?? ''), n: Number(key.split(':')[1]) + 1 })
  if (kind === 'fetch_pdf') return t('Open-access PDF retrieval')
  if (kind === 'pdf_other_copy') return t('Search for another open copy')
  if (kind === 'read_equations') return t('Reading equations (Marker)')
  if (kind === 'ocr_pages') return t('Finding pages without text')
  if (kind === 'ocr_page') return t('OCR of PDF p. {page}', { page: key.split(':')[2] ?? '?' })
  if (kind === 'ocr_merge') return t('Storing the OCR text')
  return kind
}

// Why a PDF step gave no file, in plain words; the HTTP status stays in view for the record.
const fetchReasons: Record<string, string> = { fetch_timeout: 'timed out', fetch_too_large: 'file too large', fetch_not_pdf: 'not a PDF', fetch_blocked_url: 'address not allowed', fetch_failed: 'connection failed', no_other_copy: 'no other open copy found' }
export function fetchReasonText(code: string | null | undefined, httpStatus?: number | null) {
  if (code !== 'fetch_http_error') return t(fetchReasons[code ?? ''] ?? 'connection failed')
  if (httpStatus === 401 || httpStatus === 403) return t('site blocked automatic download · HTTP {status}', { status: httpStatus })
  if (httpStatus === 404 || httpStatus === 410) return t('no file at this link · HTTP {status}', { status: httpStatus })
  return httpStatus ? t('server refused · HTTP {status}', { status: httpStatus }) : t('server refused')
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
export function accessParts(source: Source): { tone: 'text' | 'abstract' | 'unstated' | 'ocr'; text: string }[] {
  const parts: { tone: 'text' | 'abstract' | 'unstated' | 'ocr'; text: string }[] = []
  const asset = source.access.assets[0]
  if (asset) parts.push(asset.extraction_status === 'no_text' ? { tone: 'unstated', text: t('PDF without a text layer') } : { tone: 'text', text: t('PDF · {pages} pages · text {status}', { pages: asset.page_count ?? '?', status: t(asset.extraction_status) }) })
  else if (source.access.fetch?.status === 'failed') {
    const reason = fetchReasonText(source.access.fetch.error_code, source.access.fetch.http_status)
    parts.push({ tone: 'unstated', text: source.access.other_copy?.status === 'failed' ? t('PDF not retrieved ({reason}) · no other open copy found · attach the PDF yourself', { reason }) : t('PDF not retrieved ({reason})', { reason }) })
  }
  else if (source.access.oa_pdf_url && source.access.oa_pdf_version !== source.version_label) parts.push({ tone: 'unstated', text: t('Open-access PDF is a different version ({version}) · not used for this version', { version: versionText(source.access.oa_pdf_version) }) })
  else if (source.access.oa_pdf_url) parts.push({ tone: 'unstated', text: t('Open-access PDF listed · not yet retrieved') })
  // OCR pages are named apart from the text layer and are not checked against the page (D51).
  if (asset?.ocr?.ocr_pages) parts.push({ tone: 'ocr', text: t('OCR text on {k} of {n} pages · check against the page', { k: asset.ocr.ocr_pages, n: asset.page_count ?? '?' }) })
  const equations = asset?.equations
  if (equations?.state === 'reading') parts.push({ tone: 'unstated', text: t('Reading equations · {n} pages', { n: equations.pages ?? '?' }) })
  else if (equations?.state === 'pending') parts.push({ tone: 'unstated', text: t('Equations not read yet') })
  else if (equations?.state === 'read') parts.push(equations.equations_to_check
    ? { tone: 'unstated', text: t(equations.equations_to_check === 1 ? 'Equations read (LaTeX) · {n} to check against the page' : 'Equations read (LaTeX) · {n} to check against the pages', { n: equations.equations_to_check }) }
    : { tone: 'text', text: t('Equations read (LaTeX)') })
  else if (equations?.state === 'failed') parts.push({ tone: 'unstated', text: t('Equations could not be read') })
  if (source.access.abstract_passage_id) parts.push({ tone: 'abstract', text: t(source.access.abstract_origin === 'provider_openalex_inverted_index' ? 'Abstract (rebuilt from OpenAlex index)' : 'Abstract') })
  if (!parts.length) parts.push({ tone: 'unstated', text: t('Metadata only') })
  return parts
}
