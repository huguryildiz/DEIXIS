import { type ReactNode } from 'react'
import { Activity, Ban, BookOpenText, CircleCheck, CircleDot, CircleX, FilePlus2, Hand, Info, ListChecks, ListMinus, ListPlus, Replace, RotateCcw, ScanText, Sigma, MessageSquareQuote, Pause, PencilLine, Play, RotateCw, ShieldCheck, Table2, Trash2, UserPen, type LucideIcon } from 'lucide-react'
import { type ActivityEvent, type RunKind } from '../lib/api'
import { serviceErrorText, serviceKind, serviceWaitingText, connectionName, fetchReasonText, pauseReasonText, providerName, recoveryDecisionText, recoveryReasonText, runKindLabels, stepLabel } from '../lib/labels'
import { LATE_REVISION_LABEL, LATE_REVISION_QUEUED, LATE_REVISION_SKIPPED, lateRevisionReasons } from '../lib/labels'
import { ConnectionIcon } from '../components/connectionIcons'
import { ocrLanguagesText } from '../reading/ocr'
import { t, uiLocale } from '../lib/i18n'

function activityDayKey(value: string) {
  const date = new Date(value)
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

export function ActivityLog({ events }: { events: ActivityEvent[] }) {
  const groups = new Map<string, ActivityEvent[]>()
  events.slice().reverse().forEach(event => {
    const key = activityDayKey(event.created_at)
    groups.set(key, [...(groups.get(key) ?? []), event])
  })
  return <section className="activity-panel" aria-labelledby="activity-heading">
    <header className="workspace-pane-head"><div><h2 id="activity-heading">{t('Recorded activity')}</h2><p>{t(events.length === 1 ? '{n} recorded event' : '{n} recorded events', { n: events.length })}</p></div></header>
    {[...groups.values()].map(group => <section className="activity-day" key={activityDayKey(group[0].created_at)}>
      <h3>{new Date(group[0].created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</h3>
      <ol className="activity-list">{group.map(event => {
        const { icon, text, chips } = describeEvent(event)
        return <li key={event.id}>
          <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })}</time>
          <span className="activity-event"><span className="activity-icon">{icon}</span><span className="activity-copy">{text}</span>{chips.map((chip, i) => <span key={i} className={`activity-chip is-${chip.tone}`}>{chip.label}</span>)}</span>
        </li>
      })}</ol>
    </section>)}
    {!events.length && <p className="empty-inline">{t('No recorded activity.')}</p>}
  </section>
}

const selectionStates: Record<string, string> = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' }

type ChipTone = 'ok' | 'bad' | 'warn' | 'live' | 'neutral'
type EventChip = { label: string; tone: ChipTone }

const statusTones: Record<string, ChipTone> = {
  completed: 'ok', succeeded: 'ok', structurally_valid: 'ok',
  partial: 'warn', unverified_draft: 'warn', outcome_unknown: 'warn', rate_limited: 'warn', timeout: 'warn',
  failed: 'bad', auth_required: 'bad', entitlement_missing: 'bad', parse_error: 'bad',
  pending: 'live', running: 'live',
}
const statusChip = (status: unknown): EventChip => ({ label: t(String(status).replaceAll('_', ' ')), tone: statusTones[String(status)] ?? 'neutral' })
const selectionTones: Record<string, ChipTone> = { included: 'ok', excluded: 'bad', pending: 'warn' }

function describeEvent(event: ActivityEvent): { icon: ReactNode; text: string; chips: EventChip[] } {
  const p = event.payload as Record<string, string | number | null>
  const lucide = (Icon: LucideIcon, text: string, chips: EventChip[] = []) => ({ icon: <Icon size={15} aria-hidden />, text, chips })
  const brand = (id: string, text: string, chips: EventChip[] = []) => ({ icon: <ConnectionIcon id={id} />, text, chips })
  const errorProvider = p.provider ?? (typeof p.kind === 'string' && p.kind.startsWith('provider_search:') ? p.kind.split(':')[1] : null)
  const reason = p.pause_reason ? [{ label: pauseReasonText(String(p.pause_reason), p.error_json), tone: 'neutral' as const }] : []
  // Only events that carry a service classification get the service sentence; other and older codes keep their chip.
  const errorChip: EventChip[] = !p.error_code ? [] : !p.service_kind ? [{ label: String(p.error_code), tone: 'neutral' }] : [{ label: serviceErrorText({ kind: serviceKind(p.service_kind, typeof p.http_status === 'number' ? p.http_status : null),
    service: errorProvider ? providerName(String(errorProvider)) : p.connection ? connectionName(String(p.connection)) : t('The selected service') }).what, tone: 'neutral' }]
  if (typeof p.reset_at === 'string') errorChip.push({ label: serviceErrorText({ service: t('The selected service'), resetAt: p.reset_at }).when, tone: 'neutral' })
  switch (event.type) {
    case 'research_created': return lucide(FilePlus2, t('Research created'))
    case 'scope_revised': return lucide(PencilLine, t('Question revised (revision {n})', { n: String(p.scope_revision) }))
    case 'research_title_edited': return lucide(PencilLine, t('Research title edited'))
    case 'run_queued': return lucide(ListPlus, p.kind === 'discovery' || p.kind === 'answer' ? t(p.kind === 'discovery' ? 'Search run queued' : 'Answer run queued') : t('{label} queued', { label: t(runKindLabels[String(p.kind) as RunKind] ?? String(p.kind)) }))
    case 'service_waiting': return brand(String(p.connection), serviceWaitingText(connectionName(String(p.connection)), Number(p.attempt)), [])
    case 'run_started': return lucide(Play, t('Run started'))
    case 'run_completed': return lucide(CircleCheck, t('Run completed'), [statusChip('completed')])
    case 'run_paused': {
      const detail = event.payload.error_json as Record<string, unknown> | undefined
      return lucide(Pause, t('Run paused'), [...reason, ...(detail?.reset_at ? [{ label: serviceErrorText({ service: t('The selected service'), resetAt: detail.reset_at }).when, tone: 'neutral' as const }] : [])])
    }
    case 'run_failed': return lucide(CircleX, t('Run failed'), [statusChip('failed'), ...reason])
    case 'run_resumed': return lucide(RotateCw, t('Run resumed'))
    case 'run_cancelled': return lucide(Ban, t('Run cancelled'))
    case 'run_pause_requested': return lucide(Hand, t('Pause requested'))
    case 'step_started': return lucide(CircleDot, t('{step} started', { step: stepLabel(String(p.kind), String(p.operation_key)) }))
    case 'step_finished': {
      const pdfStep = p.kind === 'fetch_pdf' || p.kind === 'pdf_other_copy'
      const chips = p.error_code && pdfStep ? [{ label: fetchReasonText(String(p.error_code), typeof p.http_status === 'number' ? p.http_status : null), tone: 'neutral' as const }] : errorChip
      return lucide(ListChecks, stepLabel(String(p.kind), String(p.operation_key)), [statusChip(p.status), ...chips])
    }
    case 'model_call_started': return brand(String(p.connection), t('Model call sent to {connection}', { connection: connectionName(String(p.connection)) }), p.requested_model ? [{ label: String(p.requested_model), tone: 'neutral' }] : [])
    case 'search_recorded': return brand(String(p.provider), t('{provider} search', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} records', { count: String(p.result_count) }), tone: 'neutral' }])
    case 'pdf_discovery_recorded': return brand(String(p.provider), t('{provider} PDF lookup', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} candidates', { count: String(p.result_count) }), tone: 'neutral' }, ...errorChip])
    case 'openalex_budget_exhausted': {
      const refused = Number(p.lookups_refused ?? 0)
      const skipped = Number(p.lookups_skipped ?? 0)
      const reset = p.reset_at ? new Date(String(p.reset_at)) : null
      return lucide(Info, t('OpenAlex daily budget ran out. Its PDF lookups wait for the reset; the other routes went on, and the works affected stay open for a later run.'), [
        { label: t('{n} lookups refused', { n: refused }), tone: 'warn' },
        { label: t('{n} lookups not sent', { n: skipped }), tone: 'warn' },
        ...(reset && !Number.isNaN(reset.getTime()) ? [{ label: t('resets {time}', { time: reset.toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) }), tone: 'neutral' as const }] : []),
      ])
    }
    case 'asset_removed': return lucide(Trash2, t('PDF removed from a source'))
    case 'asset_replaced': return lucide(Replace, t('PDF replaced on a source'))
    case 'asset_text_retried': {
      const outcomes: Record<string, EventChip> = { promoted: { label: t('in use'), tone: 'ok' }, diagnosis_updated: { label: t('diagnosis'), tone: 'warn' }, rejected: { label: t('not used'), tone: 'warn' }, no_change: { label: t('no change'), tone: 'neutral' }, refused: { label: t('refused'), tone: 'warn' }, interrupted: { label: t('interrupted'), tone: 'warn' } }
      return lucide(ScanText, t('PDF text retried'), [outcomes[String(p.lifecycle === 'interrupted' ? p.lifecycle : p.outcome)] ?? statusChip(p.lifecycle),
        ...(p.reason || p.decision_code ? [{ label: p.reason ? recoveryReasonText(String(p.reason)) : recoveryDecisionText(String(p.decision_code)), tone: 'neutral' as const }] : [])])
    }
    case 'asset_file_restore_finished': return lucide(ShieldCheck, t('PDF file restore'), [
      { label: t(p.lifecycle === 'interrupted' ? 'interrupted' : p.outcome === 'file_restored' ? 'file restored' : p.outcome === 'file_reused' ? 'file reused' : 'file refused'), tone: p.lifecycle === 'completed' && p.outcome === 'file_restored' ? 'ok' : 'warn' },
      ...(p.reason ? [{ label: recoveryReasonText(String(p.reason)), tone: 'neutral' as const }] : []),
      ...(p.retained ? [{ label: t('damaged bytes kept'), tone: 'neutral' as const }] : []),
      ...(Array.isArray(p.affected_asset_ids) && p.affected_asset_ids.length > 1 ? [{ label: t('{n} PDF records share this file', { n: p.affected_asset_ids.length }), tone: 'neutral' as const }] : []),
    ])
    case 'equations_failed': return lucide(Sigma, t('Reading a PDF’s equations failed'), [{ label: t('attempt {n}', { n: String(p.attempts) }), tone: 'warn' }])
    case 'asset_ocr_read': return lucide(ScanText, t('PDF pages read with OCR'), [p.outcome === 'current' ? { label: t('in use'), tone: 'ok' } : { label: t('not used'), tone: 'warn' }, { label: t('{k} of {n} pages with text', { k: String(p.pages_with_text), n: String(p.pages_read) }), tone: 'neutral' }, { label: ocrLanguagesText(Array.isArray(p.languages) ? p.languages.map(String) : []), tone: 'neutral' }])
    case 'asset_reextracted': return lucide(ScanText, t('PDF text extracted again'), [p.outcome === 'current' ? { label: t('in use'), tone: 'ok' } : { label: t('not used'), tone: 'warn' }, { label: String(p.extraction_version), tone: 'neutral' }])
    case 'selection_changed': return lucide(UserPen, t('You marked a source'), [{ label: t(selectionStates[String(p.state)] ?? String(p.state)), tone: selectionTones[String(p.state)] ?? 'neutral' }])
    case 'answer_saved': return lucide(MessageSquareQuote, t('Answer saved'), [statusChip(p.status)])
    case 'late_revision_queued': return lucide(BookOpenText, t(LATE_REVISION_QUEUED))
    case 'late_revision_skipped': return lucide(Info, t(LATE_REVISION_SKIPPED), [{ label: t(lateRevisionReasons[String(p.reason)] ?? pauseReasonText(String(p.reason))), tone: 'neutral' }])
    case 'late_revision_published': return lucide(MessageSquareQuote, t(LATE_REVISION_LABEL))
    case 'watch_check_completed': return lucide(ListChecks, t('Follow-up check completed'), [{ label: t('{n} new', { n: Number(p.new ?? 0) }), tone: 'neutral' }, { label: t('{n} notices', { n: Number(p.notices ?? 0) }), tone: 'neutral' }])
    case 'table_changed': return lucide(Table2, t('Evidence table changed'))
    case 'table_trashed': return lucide(Trash2, t('Evidence table moved to Trash'))
    case 'table_restored': return lucide(RotateCcw, t('Evidence table restored'))
    case 'table_purged': return lucide(Trash2, t('Evidence table permanently deleted'))
    case 'column_restored': return lucide(RotateCcw, t('Table column restored'))
    case 'source_removed': return lucide(ListMinus, t(Array.isArray(p.source_version_ids) && p.source_version_ids.length === 1 ? 'You removed a source from this research' : 'You removed {n} sources from this research', { n: Array.isArray(p.source_version_ids) ? p.source_version_ids.length : 0 }))
    case 'source_restored': return lucide(RotateCcw, t(Array.isArray(p.source_version_ids) && p.source_version_ids.length === 1 ? 'You restored a source to this research' : 'You restored {n} sources to this research', { n: Array.isArray(p.source_version_ids) ? p.source_version_ids.length : 0 }))
    case 'asset_restored': return lucide(RotateCcw, t('PDF restored to a source'))
    case 'cell_revision_saved': return lucide(PencilLine, t('Cell revision saved'), [{ label: t(String(p.kind).replaceAll('_', ' ')), tone: 'neutral' }])
    case 'answer_reviewed': return lucide(ShieldCheck, t('Answer review saved'), [statusChip(p.status)])
    default: return lucide(Activity, plainEventTexts[event.type] ? t(plainEventTexts[event.type]) : event.type.replaceAll('_', ' '))
  }
}

// Events with no detail of their own: one plain sentence each, so the log never shows a raw event code.
const plainEventTexts: Record<string, string> = {
  report_created: 'Report created',
  report_plan_saved: 'Report outline saved',
  report_section_created: 'Report section added',
  report_section_saved: 'Report section saved',
  report_claims_saved: 'Claims in a report section saved',
  report_finalized: 'Report finished',
  report_review_saved: 'Report check saved',
  report_gaps_saved: 'Gaps in the report saved',
  report_snapshot_saved: 'A version of the report saved',
  report_claim_edited: 'You edited a claim in the report',
  report_edits_checked: 'Your report edits were checked',
  report_changes_acknowledged: 'Report changes marked as seen',
  report_repair_reverted: 'A report fix was undone',
  report_repair_restoration_rejected: 'Undoing a report fix was refused',
  english_question_saved: 'English version of the question saved',
  followup_asked: 'Follow-up question asked',
  followup_answered: 'Follow-up question answered',
  protocol_frozen: 'Search plan fixed',
  research_model_changed: 'Model for this research changed',
  seed_selected: 'Starting PDF chosen',
  read_cutoff: 'Reading stage closed',
  auto_answer_skipped: 'Automatic answer skipped',
  run_retry_failed_searches: 'Failed searches queued again.',
  stage_decision_recorded: 'Source decision recorded',
  stage_decision_undone: 'Source decision undone',
  study_table_skipped: 'Study table skipped',
  study_table_ready: 'Study table ready',
  study_table_columns_accepted: 'Study table columns accepted',
  study_table_stopped: 'Study table stopped',
  fulltext_work_settled: 'Full text of a work settled',
  screen_more_candidates: 'More works queued for screening',
  arxiv_source_refused: 'arXiv LaTeX source not used',
  arxiv_source_withdrawn: 'arXiv LaTeX source withdrawn',
  pdf_identity_confirmed: 'PDF confirmed as the right paper',
  pdf_identity_revoked: 'PDF no longer confirmed as the right paper',
  person_pdf_request: 'PDF requested from a person',
  waiting_pdf_attached: 'Awaited PDF attached',
  waiting_pdf_skipped: 'Continued without a PDF',
  waiting_pdf_skip_undone: 'Continuing without a PDF undone',
  lineage_changed: 'Development links changed',
  lookup_version_opened: 'Source version opened',
}
