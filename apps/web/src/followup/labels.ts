import type { Watch, WatchCheck, WatchGap, WatchKind, WatchObservation } from '../api'
import { t, uiLocale } from '../i18n'

export const kindLabels: Record<WatchKind, string> = {
  protocol_queries: 'Search queries of this research', citing_works: 'Works citing the included sources',
}
export const stateLabels: Record<WatchCheck['state'], string> = {
  queued: 'Queued', running: 'Running', pause_requested: 'Pausing after the current call', paused: 'Paused',
  cancelled: 'Cancelled', failed: 'Failed', succeeded: 'Completed', partial: 'Partial',
}
export const triggerLabels: Record<WatchCheck['trigger'], string> = {
  manual: 'Your check', scheduled: 'Scheduled check', catch_up: 'Catch-up check',
}
export const reasonLabels: Record<string, string> = {
  provider_failed: 'A provider read failed.', not_configured: 'The provider is not configured.',
  quota_deferred: 'The provider quota deferred this read.', budget_deferred: 'The check budget deferred this read.',
  deadline_deferred: 'The check deadline deferred this read.', outcome_unknown: 'The read outcome is unknown.',
  coverage_unknown: 'Publication-date coverage is unknown.', coverage_not_reached: 'The read did not reach the start of the window.',
  baseline_incomplete: 'The first read is not finished.', rolled_over: 'Some citing ids roll to the next check.',
  no_openalex_id: 'The work has no OpenAlex id.', skipped_not_searchable: 'This provider cannot be searched.',
  watch_follows_old_scope: 'This follow-up follows an earlier question or protocol.',
  check_paused: 'Resume or cancel this follow-up’s unfinished check first.',
  scope_revised: 'The question was revised.', watch_protocol_changed: 'The frozen protocol changed.',
  disabled: 'The follow-up was turned off.', schedule_changed: 'The schedule changed.', next_due_changed: 'The next due time changed.',
  research_unavailable: 'The research is no longer available.',
  completed: 'Completed', zero_results: 'No results returned', ready: 'Ready', failed: 'Failed',
  deferred_budget: 'The check budget deferred this read.', deferred_deadline: 'The check deadline deferred this read.',
  stopped: 'The read was stopped.', watch_disabled: 'The follow-up was turned off.',
  watch_state_changed: 'The follow-up changed while this check was working.', adapter_revision_changed: 'The connector version changed; this check cannot continue its frozen reads.',
  timeout: 'The provider did not answer in time.', before_send: 'The request was not sent.',
  after_send_unknown: 'The request was sent; its outcome is unknown.', http_error: 'The provider returned an HTTP error.',
  parse_error: 'The provider response could not be read.', rate_limited: 'The provider rate-limited this request.',
  quota_exhausted: 'The provider quota was exhausted.', auth_required: 'The provider requires authentication.',
  entitlement_missing: 'The provider did not accept the configured key.', network_error: 'The provider request encountered a network error.',
}
export const reasonText = (reason: string | null) => reason ? t(reasonLabels[reason] ?? reason) : ''
export const timeText = (value: string) => new Date(value).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })
// Calendar dates have no time zone. Do not shift a publication date through the viewer's local midnight.
export const dateText = (value: string) => new Date(`${value.slice(0, 10)}T00:00:00Z`).toLocaleDateString(uiLocale(), { dateStyle: 'medium', timeZone: 'UTC' })
export const frequencyLabels = { 0: 'Manual', 1: 'Every day', 7: 'Every 7 days', 30: 'Every 30 days' } as const
export const modeText = (watch: Watch) => watch.mode === 'manual' ? t('Checked when you ask')
  : `${t(frequencyLabels[watch.interval_days!])} · ${t(watch.catch_up ? 'catch-up on opening on' : 'catch-up on opening off')}`
export function coverageText(observed: WatchObservation) {
  switch (observed.coverage) {
    case 'covered': return observed.oldest_publication_date ? t('Covered back to {date}', { date: dateText(observed.oldest_publication_date) })
      : observed.exhausted ? t('All results read (the list ended)') : t('No publication date was reached')
    case 'coverage_not_reached': return observed.oldest_publication_date
      ? t('Read {pages_read} pages; reached {date}, not the start of the window', { pages_read: observed.pages_read, date: dateText(observed.oldest_publication_date) })
      : t('No publication date was reached')
    case 'coverage_unknown': return t('Coverage unknown: this provider is not read by publication date')
    case 'baseline_complete': return t('First read complete within its page budget')
    case 'baseline_incomplete': return t('First read not finished; it continues at the next check')
  }
}
export function gapOutcomeText(gap: WatchGap) {
  switch (gap.outcome) {
    case 'catch_up_chosen': return t(gap.catch_up_queued ? 'One catch-up check was queued.' : 'Chosen for a catch-up check; none has been queued yet.')
    case 'catch_up_off': return t('Catch-up on opening is off, so this gap was not checked.')
    case 'opening_cap': return t('Not caught up: at most three researches are caught up each time DEIXIS opens.')
    case 'one_per_research': return t('Not caught up: one follow-up of each research is caught up when DEIXIS opens, and the other one was chosen.')
    case 'not_eligible': return t('Not caught up: {reason}', { reason: reasonText(gap.outcome_reason) })
    case 'changed_before_record': return t('The follow-up changed before this gap was recorded.')
  }
}
