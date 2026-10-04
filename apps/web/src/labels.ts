import type { ApprovalBlock, Evidence, FileRestoreReceipt, PersonFile, PersonFileState, QueueAnswer, QueueKind, RunKind, RunStatus, Source, SourceScope, TextRecoveryCapability, TextRetryOperation, Verdict } from './api'
import { t, uiLocale } from './i18n'

// Label records hold English text; callers show them through t().

const recoveryReasons: Record<string, string> = {
  run_active: 'a research using this source has an active run', baseline_changed: 'the stored text changed first',
  membership_changed: 'this research no longer holds the source', asset_removed: 'the PDF record was removed',
  asset_replaced: 'the PDF record was replaced', no_holding_research: 'no research holds this source',
  process_ended: 'DEIXIS stopped before it finished', storage_full: 'the disk is full',
  storage_unavailable: 'storage could not be written', cancelled: 'it was cancelled', unexpected_error: 'an unexpected error',
  file_missing: 'the stored file was missing', file_mismatch: 'the stored file differed from its recorded hash',
  input_not_verified: 'the bytes read could not be matched to the recorded hash',
  retention_conflict: 'the damaged bytes could not be kept because their stored name holds another file',
  file_not_regular: 'the stored entry is not a regular file',
}
const recoveryDecisions: Record<string, string> = {
  candidate_failed: 'the new read failed', augmented_text_would_be_lost: 'the new read would drop OCR, Marker or arXiv source text',
  status_worse: 'the new read is less complete', page_count_changed: 'the page count changed',
  legacy_page_count_untrusted: 'the page count changed and the earlier input was not recorded',
  text_page_lost: 'a page that had text would lose it', recovered_text: 'text was extracted from an earlier empty read',
  recovered_from_corrupt_input: 'text was extracted after a read from damaged bytes', text_updated: 'stored text was updated',
  password_diagnosed: 'the PDF requires a password; no text was extracted', no_text_diagnosed: 'no text was extracted',
  no_change: 'no change', upgraded: 'extractor updated', fewer_text_pages: 'fewer pages have text',
  ocr_found_no_text: 'OCR found no text', input_not_verified: 'the bytes read could not be matched to the recorded hash',
}
export const recoveryReasonText = (reason: string | null) => t(recoveryReasons[reason ?? ''] ?? (reason ?? '').replaceAll('_', ' '))
export const recoveryDecisionText = (code: string | null) => t(recoveryDecisions[code ?? ''] ?? (code ?? '').replaceAll('_', ' '))
export function textRecoveryReasonText(reason: string | null): string {
  const reasons: Record<string, string> = {
    operation_running: 'A text retry is already running for this PDF.',
    run_active: 'A research using this source has an active run; retry when it ends.', pending: 'This PDF is still being read.',
    file_missing: 'The stored PDF is missing; upload it again to restore it.', no_current_extraction: 'No extraction is stored for this PDF.',
    already_current: 'This text already comes from the current extractor.',
    password_protected: 'This PDF requires a password. Text was not recovered. Replace it with an unlocked copy.',
  }
  return t(reasons[reason ?? ''] ?? 'Text retry is unavailable.')
}
export function textRetryResultText(operation: TextRetryOperation, currentId: string | null, history = false): string {
  const reason = recoveryReasonText(operation.reason)
  if (operation.lifecycle === 'running') return t('Text retry is running…')
  if (operation.lifecycle === 'interrupted') return history
    ? t('Interrupted: {reason}; nothing was published.', { reason })
    : `${t('Text retry was interrupted; no new extraction was published.')} ${reason}.`
  switch (operation.outcome) {
    case 'promoted':
      if (history) return t('This extraction became current.')
      if (operation.extraction_id !== currentId) return t('This extraction became current; a later extraction is in use now.')
      return operation.candidate_status === 'succeeded'
        ? t('Text extracted again. Future work uses this extraction; earlier evidence keeps its cited text.')
        : `${t('Text extraction updated, but some pages still have no extracted text.')} ${operation.coverage ? t('Pages with text: {pages}.', { pages: operation.coverage.new_text_pages.join(', ') || t('none') }) : ''}`.trim()
    case 'diagnosis_updated': return history
      ? t('Diagnosis recorded: {reason}.', { reason: recoveryDecisionText(operation.decision_code) })
      : t(operation.decision_code === 'password_diagnosed' ? 'This PDF requires a password. Text was not recovered. Replace it with an unlocked copy.' : 'PDF text checked again. No text was extracted.')
    case 'rejected': return t(history ? 'Not used: {reason}.' : 'Earlier text stays in use: {reason}.', { reason: recoveryDecisionText(operation.decision_code) })
    case 'no_change': return t('No change to stored text.')
    case 'refused':
      if (history) return t('Refused: {reason}.', { reason })
      if (operation.reason === 'file_mismatch') return t('The stored PDF does not match its recorded hash. Upload the same PDF again to restore it, then retry.')
      if (operation.reason === 'file_missing') return t('The stored PDF was missing when the retry looked for it. Upload the same PDF again to restore it, then retry.')
      if (operation.reason === 'input_not_verified') return t("The bytes read could not be matched to the file's recorded hash, so no text was published.")
      return t('Text retry refused: {reason}.', { reason })
    default: return t('No recorded text retry result.')
  }
}
export function fileRestoreText(receipt: FileRestoreReceipt, history = false): string {
  const reason = recoveryReasonText(receipt.reason)
  if (receipt.lifecycle === 'running') return t('File restore is running…')
  if (receipt.lifecycle === 'interrupted') return history ? t('File restore did not finish: {reason}.', { reason })
    : `${t('File restore did not finish; upload the PDF again.')} ${reason}.`
  if (receipt.outcome === 'file_refused') return t('File not restored: {reason}.', { reason })
  if (receipt.outcome === 'file_reused') return t(history ? 'File was already whole; nothing was rewritten.' : 'The stored file was already whole; nothing was rewritten.')
  if (receipt.outcome === 'file_restored') return [t(history ? 'File restored; this operation did not retry text.' : 'File restored. Stored text has not been retried.'),
    receipt.before_integrity === 'missing' ? t('The stored file was missing.') : receipt.before_integrity === 'mismatch'
      ? t(receipt.retained ? history ? 'The stored file was damaged; its damaged bytes were kept.' : 'The stored file was damaged; its damaged bytes are kept.' : 'The stored file was damaged.') : ''].filter(Boolean).join(' ')
  return t('No recorded file restore result.')
}
// A restore receipt describes file placement, not the attachment/replacement's text extraction.
export function fileRestoreNote(receipt: FileRestoreReceipt | null | undefined): string {
  if (!receipt || receipt.outcome === 'file_reused') return ''
  if (receipt.lifecycle !== 'completed' || receipt.outcome !== 'file_restored') return fileRestoreText(receipt)
  if (receipt.before_integrity === 'missing') return t('The stored copy of this file was missing and was restored first.')
  if (receipt.before_integrity === 'mismatch') return t(receipt.retained
    ? 'A damaged stored copy of this file was restored first; its damaged bytes are kept.'
    : 'A damaged stored copy of this file was restored first.')
  return t('The stored copy of this file was restored first.')
}
export function textRecoveryResultText(capability: TextRecoveryCapability): string {
  const op = capability.latest_operation, file = capability.latest_file_restore
  if (op?.lifecycle === 'running') return textRetryResultText(op, capability.current_extraction_id)
  if (file && (file.lifecycle === 'running' || !op || file.created_at > op.created_at)) return fileRestoreText(file)
  if (op) return [file?.lifecycle === 'completed' && file.outcome === 'file_restored' && file.finished_at && file.finished_at < op.created_at ? t('File restored.') : '',
    textRetryResultText(op, capability.current_extraction_id)].filter(Boolean).join(' ')
  return capability.reason === 'password_protected' ? textRecoveryReasonText(capability.reason) : ''
}
export const textRetryTone = (op: TextRetryOperation) => op.lifecycle === 'completed' && op.outcome === 'diagnosis_updated' && op.decision_code === 'password_diagnosed'
  ? 'error' as const : op.lifecycle === 'completed' && op.outcome === 'promoted' && op.candidate_status === 'succeeded' ? 'success' as const : 'warning' as const
export const fileRestoreTone = (file: FileRestoreReceipt) => file.lifecycle === 'completed' && file.outcome !== 'file_refused' ? 'success' as const : 'warning' as const

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
  watch_check: 'Follow-up check',
  review: 'Review by another model',
  discovery: 'Search & screening', answer: 'Answer', report: 'Evidence report', pdf_collection: 'PDF collection', pdf_ocr: 'OCR reading', fulltext_fetch: 'Full-text retrieval', fulltext_adjudication: 'Full-text reading', table_fill: 'Table fill', cell_recheck: 'Cell recheck', table_columns: 'Column suggestions', research_title: 'Research title', lineage_links: 'Development links', claim_decomposition: 'Claim breakdown', kill_search: 'Prior-art search for a claim',
}

export const reportSupportLabels: Record<string, string> = { source_stated: 'Stated by the source', analyst_inference: 'Analyst inference' }
export const reportRevisionLabels: Record<string, string> = { human_edit: 'Your edit', human_restore: 'Restored' }
export const reportChangeLabels: Record<string, string> = { cell_changed: 'a cited cell changed', source_removed: 'a cited source left the table or the research' }
export const reportChangeViaLabels: Record<string, string> = { body_ref: '(through the section it summarises)', gap_ref: '(through a candidate aspect)' }

const pauseReasons: Record<string, string> = {
  no_provider_read: 'No provider read succeeded.',
  watch_disabled: 'The follow-up was turned off.',
  watch_state_changed: 'The follow-up changed while this check was working.',
  watch_protocol_changed: 'The follow-up’s frozen protocol changed.',
  adapter_revision_changed: 'The connector version changed; this check cannot continue its frozen reads.',
  research_unavailable: 'The research is no longer available.',
  skill_package_changed: 'The method package changed. This run cannot send more calls with its frozen package.',
  review_unavailable: 'The review is no longer available.',
  unknown_run_kind: 'The run kind is not recognised.',
  nothing_reviewed: 'No group was reviewed.',
  message_too_large: 'request exceeds the size limit',
  repair_message_too_large: 'repair request exceeds the size limit',
  deadline_passed: 'review deadline passed',
  user_requested: 'You paused this run.',
  disk_full: 'The disk is full, so DEIXIS could not save this run. Free some space and start the run again.',
  backend_restarted: 'DEIXIS was closed while this run was working. Completed steps are kept; resuming may repeat an unfinished search or model call.',
  model_connection_not_ready: 'The selected model connection is not ready. Nothing was sent to another model.',
  model_connection_unavailable: 'The selected model connection is not available. Nothing was sent to another model.',
  model_call_failed: 'The model call did not complete. Completed work is saved.',
  section_must_be_rewritten: 'A section must be written again.',
  section_failed: 'A section could not be written.',
  model_isolation_violation: 'The model session reported tool use or loaded instructions, so its output was rejected.',
  provider_rate_limited: 'A scholarly provider rate-limited a search. Completed searches are kept; no other provider was used in its place.',
  provider_quota_exhausted: 'A scholarly provider exhausted its quota. Completed searches are kept; no other provider was used in its place. This run will not retry it automatically; resuming or retrying allows another attempt.',
  provider_not_configured: 'A scholarly provider has no configured key, so its search was not sent. Completed searches are kept; no other provider was used in its place.',
  provider_adapter_revision_changed: 'The connector version recorded for earlier pages changed or could not be read, so this search cannot continue. Completed searches are kept; no other provider was used in its place.',
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
  search_query_failed: 'The model could not write the search query, and nothing has been searched. Resume to ask it once more, or search with the query DEIXIS built from the question’s words.',
}
export { reviewFindingLabels, reviewFocusLabels, reviewDecisionLabels, reviewStaleLabels, reviewNotReviewedLabels, reviewContextLabels, notReviewedText } from './review/labels'
export const pauseReasonText = (reason: string | null) => (reason ? t(pauseReasons[reason] ?? reason) : '')
// What the run stored about a model stop, in the connection's own words: a usage limit and a rate limit read differently
// there, and DEIXIS does not guess which one it was. A second line under the reason, never a replacement for it.
const oneLine = (text: unknown, max = 240) => {
  const flat = typeof text === 'string' ? text.replace(/\s+/g, ' ').trim() : ''
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}
export const pauseDetailText = (run: { pause_reason: string | null; error: unknown }): string[] => {
  const error = run.error && typeof run.error === 'object' ? run.error as Record<string, unknown> : {}
  if (run.pause_reason === 'model_connection_not_ready') {
    const reason = oneLine(error.reason)
    return [t('Open Settings, connect it again, then resume this run.'), ...(reason ? [t('The connection says: {text}', { text: reason })] : [])]
  }
  if (run.pause_reason === 'model_call_failed') {
    const text = oneLine(error.error)
    return text ? [t('The connection reported: {text}', { text })] : []
  }
  return []
}
export const failedRowReasonText = (reason: string) => reason === 'no_stored_text' ? t('no stored text') : reason.replaceAll('_', ' ')
const sectionFailureReasons: Record<string, string> = {
  anchor_not_in_cell_evidence: 'a cited quote was not found in that table cell’s stored evidence',
  anchor_not_in_passage: 'a cited quote was not found in the stored passage',
  unknown_passage_id: 'a cited passage was not in the allowed evidence',
  unknown_cell_id: 'a cited table cell was not in the allowed evidence',
  unknown_source_id: 'a named source was not in the allowed evidence',
  unknown_column_id: 'a named column was not allowed for this section',
  empty_section: 'the section had no claims or explanation of missing evidence',
  model_mismatch: 'the connection answered with a different model',
  invalid_model_output: 'the model output failed validation',
  invalid_json: 'the model output could not be read as JSON',
  schema_invalid: 'the model output did not match the required format',
  envelope_mismatch: 'the model output did not match this step’s recorded input',
  citation_anchor_target_count: 'a citation must name exactly one passage or table cell',
  unframed_exception: 'a sentence did not follow a supplied phrase frame',
}
export const failedSectionReasonText = (code: string) => t(sectionFailureReasons[code] ?? code.replaceAll('_', ' '))

const assemblyRuleLabels: Record<string, string> = {
  banned_word: 'banned word', empty_section: 'empty section',
  corpus_count_mismatch: 'corpus count mismatch', citation_anchor_unmatched: 'unlocated citation quote',
  anchor_not_in_cell_evidence: 'quote missing from cell evidence', anchor_not_in_passage: 'quote missing from passage',
}
export const reportAssemblyDraftText = (error: unknown) => {
  const rules: string[] = []
  if (Array.isArray(error)) for (const entry of error) {
    if (!entry || typeof entry.rule !== 'string') continue
    if (entry.rule.endsWith('_warning') && typeof entry.detail === 'string' && entry.detail.startsWith('WARNING:')) continue
    if (!rules.includes(entry.rule)) rules.push(entry.rule)
  }
  const names = rules.slice(0, 3).map(rule => t(assemblyRuleLabels[rule] ?? rule.replaceAll('_', ' '))).join(', ')
  const reason = names + (rules.length > 3 ? t(' and {n} more', { n: rules.length - 3 }) : '')
  return reason ? t('DRAFT: the assembly check refused the report ({reason})', { reason }) : ''
}
// How many more times resuming may ask the model to write the query; the pause carries it (D92).
export const searchQueryTriesLeft = (run: { error: unknown }) => (run.error as { retries_left?: number } | null)?.retries_left ?? 1

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
const termOrigins: Record<string, string> = {
  question: 'from the question', key_terms: 'from your key terms', user: 'added by you',
  // The model proposed the name; it is in the search because the user added it (D82).
  model: 'suggested by the model',
  // The model that wrote this run's query chose it (D92).
  search_query: 'written by the model',
}
const blockOrigins: Record<string, string> = { rule: 'block by rule', model: 'block by the model', user: 'block by you', search_query: 'block by the model' }
// What the model said a term of its query names (D92). Shown, never used by a rule.
const termKinds: Record<string, string> = { topic: 'topic', method: 'method', population: 'population', other: 'other' }
export const termKindText = (kind: string) => t(termKinds[kind] ?? kind)
const queryWarnings: Record<string, string> = {
  no_records_with_other_block: 'no record holds it together with the other block',
  count_unknown: 'its count could not be read',
}
export const queryWarningText = (warning: string) => t(queryWarnings[warning] ?? warning)
// Why a source is or is not searched by an sw run (D93).
const routeReasons: Record<string, string> = {
  always: 'always searched',
  share: 'its fields hold enough of the records',
  distribution_unavailable: 'searched because the field distribution could not be read',
  no_route: 'searched; no field rule names it',
  share_below: 'its fields hold too few of the records',
  not_in_scope: 'not among this research’s sources',
  not_configured: 'no key configured',
  not_in_sw_search: 'not searched by this workflow',
}
export const routeReasonText = (reason: string) => t(routeReasons[reason] ?? reason)
export const termOriginText = (origin: string) => t(termOrigins[origin] ?? origin)
export const blockOriginText = (origin: string) => t(blockOrigins[origin] ?? origin)
// Why a phrase left the query. It stays on record with its reason rather than disappearing.
const dropReasons: Record<string, string> = {
  zero_results: 'no record holds it',
  // Why a proposed name cannot enter the search (D82).
  already_present: 'already one of the terms above',
  contains_claim_word: 'contains a word of the claim under test',
  contains_exclusion_word: 'contains an excluded word',
  too_long: 'longer than six words',
  duplicate: 'proposed twice',
  anchor_not_searched: 'the term it was another name for is no longer searched',
}
export const dropReasonText = (reason: string) => t(dropReasons[reason] ?? reason)
// Why the model cannot be asked for other names right now.
const suggestionBlockers: Record<string, string> = {
  no_anchor_phrases: 'There is no searched term to ask about. Add a term to the setting or task block first.',
  already_suggested: 'The model has already been asked for this question; its proposals are below.',
  suggestion_call_spent: 'This run has used the one model call it had for other names. You can still add terms yourself.',
}
export const suggestionBlockerText = (reason: string | null) => (reason ? t(suggestionBlockers[reason] ?? reason) : '')
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
  unpaywall: 'Unpaywall', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', arxiv: 'arXiv', biorxiv: 'bioRxiv', pubmed: 'PubMed', ieee_xplore: 'IEEE Xplore', scopus: 'Scopus', core: 'CORE', europepmc: 'Europe PMC', serpapi: 'SerpApi', web_search: 'Web Search', zotero: 'Zotero',
}
export const providerName = (id: string) => providerNames[id] ?? id

export const connectionNames: Record<string, string> = { codex: 'Codex', claude: 'Claude Code', deepseek: 'DeepSeek', gemini: 'Gemini', kimi: 'Kimi', grok: 'Grok', copilot: 'GitHub Copilot', glm: 'GLM', muse_spark: 'Muse Spark', muse_glimmer: 'Muse Glimmer', ollama: 'Ollama', qwen: 'Qwen', mistral: 'Mistral' }
export const connectionName = (id: string) => connectionNames[id] ?? id
export const isPlannedModel = (reason?: string | null) => reason === 'Adapter not implemented in this version'

export const localToolNames: Record<string, string> = { claude_code: 'Claude Code', codex: 'Codex CLI', gemini_cli: 'Gemini CLI', qwen_code: 'Qwen Code', kimi_cli: 'Kimi CLI', mistral_vibe: 'Mistral Vibe', copilot_cli: 'GitHub Copilot CLI', opencode: 'OpenCode', aider: 'Aider', goose: 'Goose', amp: 'Amp', cline: 'Cline', ollama: 'Ollama', lm_studio: 'LM Studio', zotero: 'Zotero' }
// Brand marks exist only for a few tools; the other command-line tools get a neutral terminal glyph.
const localToolIcons: Record<string, string> = { gemini_cli: 'gemini', qwen_code: 'qwen', mistral_vibe: 'mistral', kimi_cli: 'kimi', copilot_cli: 'terminal', opencode: 'terminal', aider: 'terminal', goose: 'terminal', amp: 'terminal', cline: 'terminal' }
export const localToolIcon = (id: string) => localToolIcons[id] ?? id

// Model connections that share the OpenAI-compatible adapter: connection id -> its key variable.
export const compatConnectionKeys: Record<string, string> = { qwen: 'DASHSCOPE_API_KEY', kimi: 'MOONSHOT_API_KEY', mistral: 'MISTRAL_API_KEY' }

// What a scholarly source is used for: searched for records, or asked what a record whose DOI is known is (D87).
export const providerRole = (role: string | undefined) => t(role === 'verification' ? 'Metadata verification' : 'Record search')

export const stepLabel = (kind: string, key: string, candidate = false) => {
  if (kind === 'watch_read') return t('Follow-up provider read')
  if (kind === 'watch_complete') return t('Recording follow-up results')
  if (kind === 'model:claim_decomposition') return t('Claim breakdown (model)')
  if (kind === 'model:kill_search_query') return t('Search terms (model)')
  if (kind === 'model:claim_assessment') return t('Claim assessment (model)')
  if (kind === 'claim_decomposition_summary') return t('Claim breakdown summary (code)')
  if (kind === 'kill_search_plan') return t('Frozen claim assessment plan (code)')
  if (kind === 'kill_search_summary') return t('Claim search summary (code)')
  if (kind === 'model:lineage_links') return t('Development link proposals (model)')
  if (kind === 'lineage_publication') return t('Recording development decisions (code)')
  if (kind === 'model:search_plan') return t('Search plan (model)')
  if (kind === 'model:screening') return t('Screening proposal (model)')
  if (kind === 'code:term_suggestions') return t('Other names for the search terms (code)')
  if (kind === 'model:term_suggestions') return t('Other names for the search terms (model)')
  if (kind === 'code:abstract_stage') return t('Abstract screening (code)')
  if (kind === 'model:abstract_screening') return t('Abstract screening proposal (model)')
  if (kind === 'code:chain_abstract_stage') return t('Abstract screening of chained works (code)')
  if (kind === 'provider_chain:openalex') return t('Citation chaining request, {direction}', { direction: t(key.split(':')[1] === 'backward' ? 'references' : 'citing works') })
  if (kind.startsWith('code:chain_')) return t('Citation chaining (code)')
  if (kind === 'model:grounded_answer') return t('Source-linked answer (model)')
  if (kind === 'model:answer_review') return t('Claim review (reviewer model)')
  if (kind === 'model:cell_extraction') return t('Cell extraction (model)')
  if (kind === 'model:table_columns') return t('Column suggestions (model)')
  if (kind === 'model:research_title') return t('Research title (model)')
  if (kind === 'table_no_text') return t('Source without stored text')
  if (kind.startsWith('provider_search')) return t('{provider} search {n}', { provider: providerName(kind.split(':')[1] ?? ''), n: Number(key.split(':')[1]) + (candidate ? 0 : 1) })
  if (kind === 'code:fulltext_plan') return t('Retrieval plan (code)')
  if (kind === 'code:fetch_baseline') return t('Retrieval baseline (code)')
  if (kind === 'code:fulltext_work') return t('Full text of one work')
  if (kind === 'code:fulltext_summary') return t('Retrieval summary (code)')
  if (kind === 'code:adjudication_plan') return t('Reading plan (code)')
  if (kind === 'model:fulltext_adjudication') return t('Full-text proposal')
  if (kind === 'code:adjudication_summary') return t('Reading summary (code)')
  if (kind === 'code:criterion_phrases') return t('Criterion phrases (code)')
  if (kind === 'fetch_pdf') return t('Open-access PDF retrieval')
  if (kind === 'pdf_other_copy') return t('Search for another open copy')
  if (kind === 'read_equations') return t('Reading equations (Marker)')
  if (kind === 'ocr_pages') return t('Finding pages without text')
  if (kind === 'ocr_page') return t('OCR of PDF p. {page}', { page: key.split(':')[2] ?? '?' })
  if (kind === 'ocr_merge') return t('Storing the OCR text')
  return kind
}

// Why a PDF step gave no file, in plain words; the HTTP status stays in view for the record.
const fetchReasons: Record<string, string> = { fetch_file_repair_refused: 'the stored file could not be repaired now', fetch_file_busy: 'the stored file was busy', fetch_timeout: 'timed out', fetch_too_large: 'file too large', fetch_not_pdf: 'not a PDF', fetch_blocked_url: 'address not allowed', fetch_failed: 'connection failed', no_other_copy: 'no other open copy found' }
export function fetchReasonText(code: string | null | undefined, httpStatus?: number | null) {
  if (code !== 'fetch_http_error') return t(fetchReasons[code ?? ''] ?? 'connection failed')
  if (httpStatus === 401 || httpStatus === 403) return t('site blocked automatic download · HTTP {status}', { status: httpStatus })
  if (httpStatus === 404 || httpStatus === 410) return t('no file at this link · HTTP {status}', { status: httpStatus })
  return httpStatus ? t('server refused · HTTP {status}', { status: httpStatus }) : t('server refused')
}

// The one way a page is named (SW21): a page of Europe PMC's text drawn by DEIXIS is never written as a PDF page of
// the publisher's file, on any surface.
export function pageLocator(page: number | string, rendition?: boolean | null, printed?: string | null) {
  if (rendition) return t('Europe PMC text, rendered p. {page}', { page })
  return printed ? t('PDF p. {page} (printed {label})', { page, label: printed }) : t('PDF p. {page}', { page })
}

export function locatorText(e: Pick<Evidence, 'kind' | 'physical_page' | 'printed_label' | 'rendition'>) {
  if (e.kind === 'abstract') return t('abstract')
  if (e.physical_page) return pageLocator(e.physical_page, e.rendition, e.printed_label)
  return t('section')
}

const versionNames: Record<string, string> = {
  publishedVersion: 'published version', acceptedVersion: 'accepted manuscript', submittedVersion: 'submitted manuscript',
}
export const versionText = (label: string | null) => (label ? t(versionNames[label] ?? label) : t('version not stated'))
// OpenAlex's count; other indexes (Google Scholar, Scopus) report different numbers.
export const citedText = (count: number | null) => (count === null ? '' : t('cited by {count} (OpenAlex)', { count: count.toLocaleString(uiLocale()) }))

// The arXiv source route's reason codes (D104), in plain words. Never "verified", "exact", "reliable" or "correct":
// the route matches a numbered equation to the page by its number and letters; it does not check that the source
// compiles to this page.
const arxivSourceReasons: Record<string, string> = {
  no_version: 'no arXiv version could be read from the PDF or its record',
  version_conflict: 'the PDF’s address and its printed stamp name different versions',
  record_identity_unknown: 'the record does not name an arXiv identifier',
  record_identity_conflict: 'the record names more than one arXiv identifier',
  record_version_conflict: 'the record names a different arXiv version',
  not_settled: 'the arXiv source could not be retrieved after 3 attempts',
  pdf_only: 'the arXiv source has no LaTeX, only a PDF',
  no_tex: 'the arXiv source archive has no LaTeX file',
  too_large: 'the arXiv source archive is too large',
  unreadable: 'the arXiv source could not be read',
  version_mismatch: 'the file retrieved did not name this version',
  cache_corrupt: 'the stored arXiv source file did not check out and could not be retrieved again',
  withdrawn: 'the record’s identity or version changed since this was read',
  nothing_placed: 'no equation could be matched to the page',
  offsets_unresolved: 'a matched equation could not be located in the page text',
  extraction_failed: 'the PDF’s text could not be extracted again within its time or memory limit',
  not_available_on_this_system: 'not available on this system',
}
const arxivSourceReasonText = (reason: string | null | undefined) => t(arxivSourceReasons[reason ?? ''] ?? reason ?? 'unavailable')

function arxivSourcePart(equations: NonNullable<Source['access']['assets'][number]['equations']>): { tone: 'text' | 'unstated'; text: string } {
  if (equations.state === 'read' && equations.source) {
    const { version, placed, pages } = equations.source
    return { tone: 'text', text: t(placed === 1 && pages.length === 1
      ? 'Equations from the arXiv source (v{version}) · {n} matched to {p} page by its number'
      : placed === 1
        ? 'Equations from the arXiv source (v{version}) · {n} matched to {p} pages by its number'
        : pages.length === 1
          ? 'Equations from the arXiv source (v{version}) · {n} matched to {p} page by their numbers'
          : 'Equations from the arXiv source (v{version}) · {n} matched to {p} pages by their numbers',
      { version: version ?? '?', n: placed, p: pages.length }) }
  }
  if (equations.state === 'source_waiting') return { tone: 'unstated', text: t('arXiv source not received yet · tried {n} times · next try after {time}',
    { n: equations.attempts ?? 0, time: equations.next_at ? new Date(equations.next_at).toLocaleTimeString(uiLocale()) : '?' }) }
  if (equations.state === 'no_source') return { tone: 'unstated', text: t('No equations from the arXiv source · {reason}', { reason: arxivSourceReasonText(equations.reason) }) }
  if (equations.state === 'failed') return { tone: 'unstated', text: t('Equations from the arXiv source could not be used · {reason}', { reason: arxivSourceReasonText(equations.reason) }) }
  if (equations.state === 'reading') return { tone: 'unstated', text: t('Reading the arXiv source · {n} pages', { n: equations.pages ?? '?' }) }
  return { tone: 'unstated', text: t('Equations not read yet') }
}

// Why a PDF could not be read, from the asset's stored extraction_error; anything else reads as unreadable.
export function pdfFailureText(error: string | null | undefined): string {
  if (error === 'password-protected PDF') return t('PDF is password-protected')
  if (error === 'PDF has no pages') return t('PDF has no pages')
  return t('PDF could not be read')
}

// Each part carries a tone so the source list can colour usable text apart from gaps.
export function accessParts(source: Source): { tone: 'text' | 'abstract' | 'unstated' | 'ocr'; text: string }[] {
  const parts: { tone: 'text' | 'abstract' | 'unstated' | 'ocr'; text: string }[] = []
  const asset = source.access.assets[0]
  if (asset) parts.push(asset.extraction_status === 'no_text' ? { tone: 'unstated', text: t('PDF without a text layer') } : asset.extraction_status === 'failed' ? { tone: 'unstated', text: pdfFailureText(asset.extraction_error) } : { tone: 'text', text: t('PDF · {pages} pages · text {status}', { pages: asset.page_count ?? '?', status: t(asset.extraction_status) }) })
  else if (source.access.fetch?.status === 'failed') {
    const reason = fetchReasonText(source.access.fetch.error_code, source.access.fetch.http_status)
    parts.push({ tone: 'unstated', text: source.access.other_copy?.status === 'failed' ? t('PDF not retrieved ({reason}) · no other open copy found · attach the PDF yourself', { reason }) : t('PDF not retrieved ({reason})', { reason }) })
  }
  else if (source.access.oa_pdf_url && source.access.oa_pdf_version !== source.version_label) parts.push({ tone: 'unstated', text: t('Open-access PDF is a different version ({version}) · not used for this version', { version: versionText(source.access.oa_pdf_version) }) })
  else if (source.access.oa_pdf_url) parts.push({ tone: 'unstated', text: t('Open-access PDF listed · not yet retrieved') })
  // OCR pages are named apart from the text layer and are not checked against the page (D51).
  if (asset?.ocr?.ocr_pages) parts.push({ tone: 'ocr', text: t('OCR text on {k} of {n} pages · check against the page', { k: asset.ocr.ocr_pages, n: asset.page_count ?? '?' }) })
  const equations = asset?.equations
  if (equations?.route === 'arxiv_source') parts.push(arxivSourcePart(equations))
  else if (equations?.state === 'reading') parts.push({ tone: 'unstated', text: t('Reading equations · {n} pages', { n: equations.pages ?? '?' }) })
  else if (equations?.state === 'pending') parts.push({ tone: 'unstated', text: t('Equations not read yet') })
  else if (equations?.state === 'read') parts.push(equations.equations_to_check
    ? { tone: 'unstated', text: t(equations.equations_to_check === 1 ? 'Equations read (LaTeX) · {n} to check against the page' : 'Equations read (LaTeX) · {n} to check against the pages', { n: equations.equations_to_check }) }
    : { tone: 'text', text: t('Equations read (LaTeX)') })
  else if (equations?.state === 'failed') parts.push({ tone: 'unstated', text: t('Equations could not be read') })
  if (source.access.abstract_passage_id) parts.push({ tone: 'abstract', text: t(source.access.abstract_origin === 'provider_openalex_inverted_index' ? 'Abstract (rebuilt from OpenAlex index)' : 'Abstract') })
  if (!parts.length) parts.push({ tone: 'unstated', text: t('Metadata only') })
  return parts
}

// ---- the human queue of an sw research (slice 17, D97) ----
// What each row asks the person to do, in the order the filter chips list them.
export const queueKindLabels: Record<Exclude<QueueKind, 'look_again'>, string> = {
  confirm_quote: 'Confirm the quote', choose_run: 'Choose one of the runs', choose_version: 'Choose one of the versions',
  confirm_pdf: 'Confirm the PDF', confirm_absent: 'Confirm the absence', find_part: 'Find the part',
  confirm_results: 'Confirm the results',
}
// Why a work is in the queue, by the reason code the backend stored. The code itself is shown only beside this, small.
const queueReasons: Record<string, string> = {
  include_quote_unverified: 'Both runs found every part, but a quote was not found on the page it was taken from.',
  fulltext_runs_disagree: 'The two reading runs came to different readings of the text.',
  versions_disagree: 'Two versions of this work were read, and their decisions are opposite.',
  pdf_identity_unconfirmed: 'The first page of the PDF does not name this work, so the model has not read it.',
  protocol_title: 'The title names a study protocol, so the reading neither included nor excluded this work.',
  comparator_exclusion_withheld: 'Both runs found parts missing, but the criterion has a comparison group, so the reading did not exclude this work.',
  fulltext_runs_agree_unresolved: 'Neither run could tell from the text whether the parts are there.',
  abstract_promise_absent: 'The abstract promises a part the text does not show.',
  part_without_evidence: 'The runs found some of the criterion’s parts, but not this one.',
  human_include: 'You included this work under an earlier question or criterion.',
  human_criterion_not_met: 'You excluded this work under an earlier question or criterion.',
  human_not_sure: 'You were not sure about this work under an earlier question or criterion.',
  human_pdf_wrong: 'You marked this PDF as wrong under an earlier question or criterion.',
}
export const queueReasonText = (code: string) => t(queueReasons[code] ?? 'This work needs a person’s decision.')
// Why a work waits for the person's PDF (slice 18a), by the reason code the backend stored.
const waitingReasons: Record<string, string> = {
  no_fulltext: 'No open copy was found by any route.',
  text_unreadable: 'The PDF that was found has no text layer.',
  human_pdf_wrong: 'You marked the PDF that was found as wrong.',
}
export const waitingReasonText = (code: string) => t(waitingReasons[code] ?? 'No PDF with text is in hand.')
// What became of a file the person added (slice 18b, decision 9), in plain words; the view adds the details.
const personFileStates: Record<PersonFileState, string> = {
  waiting: 'Waiting to be read.',
  reading: 'The model is reading it…',
  included: 'Included: both readings found every part of the criterion, and code found each quote on its page.',
  criterion_not_met: 'Does not meet the criterion: the parts of the criterion were not found in the passages shown.',
  your_decision: 'Awaiting your decision: the two readings did not settle it.',
  unread: 'Not read.',
  changed: 'The file’s text changed after it was read, so nothing it was read for is shown as verified. Read it again to use it.',
  model_off: 'The model does not read it: full-text reading is off, or no criterion is frozen.',
  decision_stands: 'Your decision stands; the model does not read this file.',
  not_eligible: 'The model does not read it: this work is not in the reading order.',
}
export const personFileStateText = (row: Pick<PersonFile, 'state' | 'after_run'>) =>
  row.state === 'waiting' && row.after_run ? t('Waiting to be read, after the run in progress.') : t(personFileStates[row.state])
const personUnread: Record<NonNullable<PersonFile['unread_reason']>, string> = {
  no_decision: 'The reading run ended without a decision on it.',
  run_cancelled: 'The run that was to read it was cancelled.',
  run_failed: 'The run that was to read it failed.',
  file_changed: 'The file changed after the reading was planned.',
}
export const personUnreadText = (reason: NonNullable<PersonFile['unread_reason']>) => t(personUnread[reason])
export const queueAnswerLabels: Record<QueueAnswer, string> = {
  pdf_confirmed: 'PDF is right, let the model read it', include: 'Include', criterion_not_met: 'Does not meet the criterion',
  not_sure: 'Not sure', pdf_wrong: 'PDF is wrong or incomplete',
}
// The three plain states of SW11.1: every open row awaits a decision; an answer leaves one of these.
export const queueStateOf = (answer: QueueAnswer) =>
  t(answer === 'include' ? 'Included' : answer === 'criterion_not_met' ? 'Does not meet the criterion' : 'Awaiting a decision')
export const partLabelText = (label: 'present' | 'absent' | 'unclear') => t(label === 'present' ? 'present' : label === 'absent' ? 'absent' : 'unclear')
// The answer an earlier human decision gave, by its stored reason code: a look_again row names it beside its label.
export const queueAnswerOfCode: Record<string, QueueAnswer> = {
  human_include: 'include', human_criterion_not_met: 'criterion_not_met', human_not_sure: 'not_sure', human_pdf_wrong: 'pdf_wrong',
}
// What the person answered, as the "Your decisions" list says it.
export const queueAnsweredText: Record<QueueAnswer, string> = {
  include: 'you included it', criterion_not_met: 'you said it does not meet the criterion', not_sure: 'you were not sure',
  pdf_wrong: 'you marked the PDF as wrong', pdf_confirmed: 'you confirmed the PDF; it waits for a reading run',
}

// Slice 19: the arm kinds of an sw discovery run, in run order, and the origin of a first-round query (D92).
export const armKindLabels: Record<string, string> = { keyword: 'Keywords', expansion: 'Term expansion', chain: 'Citation chaining' }
export const queryOriginLabels: Record<string, string> = { model: 'the model’s query', code: 'the code’s query' }
// The ranking signals (D79) and the two stored orders the signal table reads beside them.
export const signalLabels: Record<string, string> = {
  bm25: 'BM25', blocks: 'Concept blocks', tfidf: 'TF-IDF', graph: 'Citation graph', embedding: 'Embedding',
  fused: 'Fused order', inspection: 'Screening order',
}
const signalReasons: Record<string, string> = {
  no_verified_seeds: 'no work you confirmed to compare with',
  no_seed_with_references: 'no seed with a reference list',
  embedding_off: 'semantic search is off',
  no_stored_similarity: 'no similarity was stored',
  english_question_missing: 'no English sentence for the built-in model',
}
export const signalReasonText = (reason: string | null) => t(reason ? signalReasons[reason] ?? reason : 'no reason recorded')
// Where each work of an sw research stands in the flow (slice 20, decision 1). "Two agreeing runs" and "you
// confirmed" stay apart: only a person's decision is a confirmation.
export const flowBucketLabels: Record<string, string> = {
  confirmed: 'You confirmed', person_not_met: 'You said the criterion is not met',
  person_excluded: 'You excluded (kind not recorded)', look_again: 'Your earlier decision, to look at again',
  included: 'Included by two agreeing runs', not_met: 'Criterion not met (two agreeing runs)',
  queued: 'In your queue, not looked at', person_unsure: 'You were not sure', waiting_for_pdf: 'Waiting for a PDF',
  not_read_yet: 'Text in hand, not read yet', candidate_not_fetched: 'Passed the abstract stage, full text not tried',
  abstract_open: 'Abstract could not decide', abstract_not_read: 'Abstract not read',
  survey: 'Survey, kept for citation chaining', out_of_scope_model: 'Out of scope (model runs)',
  out_of_scope_code: 'Out of scope (code rule)', not_screened: 'Not screened', other: 'Other',
}
// PRISMA 2020-style boxes (decision 2): counts only, never added up, all marked incomplete.
export const flowBoxLabels: Record<string, string> = {
  rows_returned: 'Records returned by the searches', chain_rows_returned: 'Records returned by citation requests',
  works_found_by_search: 'Works a search or citation request found', works: 'Works in this question revision',
  abstract_read_by_model: 'Works whose abstract the model read',
  out_of_scope_model: 'Out of scope at the abstract stage (model runs)',
  out_of_scope_code: 'Out of scope at the abstract stage (code rule)', fulltext_sought: 'Full text sought',
  fulltext_not_retrieved: 'Full text not retrieved', fulltext_read: 'Full text read',
  not_met: 'Criterion not met', queued: 'In your queue', included: 'Included (two agreeing runs or you)',
}
// The audit sample's groups (decision 5): the machine decision that puts a work in each.
export const auditStratumLabels: Record<string, string> = {
  F1: 'Included by two agreeing runs', F2: 'Criterion not met (two agreeing runs)',
  A1: 'Out of scope at the abstract stage (model runs)', A2: 'Out of scope at the abstract stage (code rule)',
}
