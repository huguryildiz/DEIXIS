import type { WatchCheck } from '../api'
import { ConnectionIcon } from '../connectionIcons'
import { pauseReasonText, providerName } from '../labels'
import { t } from '../i18n'
import { coverageText, dateText, reasonText, stateLabels, timeText, triggerLabels } from './labels'
import { Disclosure } from './Disclosure'

export function CheckDetail({ check }: { check: WatchCheck }) {
  const first = check.config_revision.units.length > 0 && check.config_revision.units.every(unit => unit.baseline && !unit.continuation)
  const terminal = ['succeeded', 'partial', 'failed', 'cancelled'].includes(check.state)
  const committed = Boolean(check.completed_at && check.counts)
  const pages = Object.values(check.observed.units).reduce((sum, unit) => sum + unit.pages_read, 0)
  return <div className="followup-check" data-check-id={check.id}>
    <p className={`followup-state is-${check.state}`} role={terminal ? undefined : 'status'}>
      {t(triggerLabels[check.trigger])} · {t(stateLabels[check.state])}{check.outcome_unknown && ` · ${t('outcome unknown')}`} · {timeText(check.completed_at ?? check.created_at)}
      {check.failure_reason && ` · ${pauseReasonText(check.failure_reason)}`}{check.state === 'paused' && check.pause_reason && ` · ${pauseReasonText(check.pause_reason)}`}
    </p>
    {committed && check.counts ? <>
      <p className="followup-facts">{t(check.counts.records_read === 1
        ? pages === 1 ? '{records_read} record read in {pages_read} page' : '{records_read} record read in {pages_read} pages'
        : pages === 1 ? '{records_read} records read in {pages_read} page' : '{records_read} records read in {pages_read} pages',
      { records_read: check.counts.records_read, pages_read: pages })} · {t('{n} new', { n: check.counts.new })} · {t('{n} already in the library', { n: check.counts.already_in_library })} · {t('{n} seen before', { n: check.counts.already_seen })} · {t('{n} notices', { n: check.counts.notices })} · {t('{n} joined the baseline', { n: check.counts.baseline })}</p>
      {pages > 0 && (first ? <p>{t('First check: the records returned within its page budget were recorded and none was announced.')}</p>
        : check.counts.new === 0 && <p>{t('No record new to this research in the pages read.')}</p>)}
    </> : <p role={terminal ? undefined : 'status'}>{t(terminal ? 'No counts were recorded for this check.' : first ? 'First check in progress.' : 'Counts appear when the check completes.')}</p>}
    {check.gap && <p>{t('Catch-up check range: {from} to {to}.', { from: timeText(check.gap.from), to: timeText(check.gap.to) })}</p>}
    <Disclosure title={t('Details')}>
      {check.partial_reasons.length > 0 && <ul>{check.partial_reasons.map(reason => <li key={reason}>{reasonText(reason)}</li>)}</ul>}
      <div className="followup-units">{check.units.map(unit => {
        const observed = check.observed.units[unit.unit_key]
        const status = check.provider_status[unit.unit_key]
        return <div className="followup-unit" key={unit.unit_key}>
          <div><span className="followup-provider"><ConnectionIcon id={unit.provider_id ?? 'openalex'} />{providerName(unit.provider_id ?? 'openalex')}</span><p>{unit.query_text}</p>
            <p className="followup-muted">{t(unit.baseline ? unit.continuation ? 'continued first read' : 'first read' : 'regular read')}</p></div>
          <div>{observed && <>
            <p>{coverageText(observed)}</p>
            <p>{unit.requested_from ? t('Asked for records since {date}', { date: timeText(unit.requested_from) }) : t('First read: no lower date')}</p>
            {observed.unread_window && <p>{t('Unread window: {from} to {to}', { from: observed.unread_window.from ? timeText(observed.unread_window.from) : t('No lower date'), to: timeText(observed.unread_window.to) })}</p>}
            {observed.cut_by_cap && <p>{t('The list was cut by the page cap.')}</p>}
          </>}
          {status && <p>{reasonText(status.status)}{status.error_kind && ` · ${reasonText(status.error_kind)}`} · {t('{n} returned', { n: status.returned })} · {t('{n} dropped', { n: status.dropped })}</p>}</div>
        </div>
      })}</div>
      {check.observed.rolled_over > 0 && <p>{t('{n} included works were not read in this check', { n: check.observed.rolled_over })}</p>}
      {check.observed.rolled_over_units > 0 && <p>{t('{n} OpenAlex ids roll to the next check', { n: check.observed.rolled_over_units })}</p>}
      {check.observed.skipped_units.length > 0 && <><p>{t('{n} works have no OpenAlex id', { n: check.observed.skipped_units.length })}</p><ul>{check.observed.skipped_units.map(unit => <li key={unit.unit_key}>{unit.work_id} · {reasonText(unit.status)}</li>)}</ul></>}
      {check.baseline_undated.count > 0 && <Disclosure title={t('Joined the baseline without a publication date ({n})', { n: check.baseline_undated.count })}>
        <p>{t('Some of these may be newer than the cut.')}</p><ul>{check.baseline_undated.titles.map((title, index) => <li key={index} data-stored-text>{title}</li>)}</ul>
      </Disclosure>}
      {Object.values(check.observed.units).some(unit => unit.newest_publication_date) && <p className="followup-muted">{t('Newest publication date observed: {date}', { date: dateText(Object.values(check.observed.units).flatMap(unit => unit.newest_publication_date ? [unit.newest_publication_date] : []).sort().at(-1)!) })}</p>}
    </Disclosure>
  </div>
}
