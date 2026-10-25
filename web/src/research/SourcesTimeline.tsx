import type { Source } from '../lib/api'
import { t } from '../lib/i18n'
import { byRank, shortTag } from './RunCards'

// The Sources panel's Timeline view: one column per publication year, each work a short author-year tag stacked upward
// from the axis, best stored rank at the bottom. Tag colour is the stored state (cited, included, passed abstract,
// undecided, excluded); rank only orders a column and says nothing about relevance. Works without a year are counted
// under the axis, never placed.
type TimelineState = 'cited' | 'included' | 'passed' | 'pending' | 'excluded'
const timelineStates: Array<[TimelineState, string]> = [['cited', 'Cited in answer'], ['included', 'Included'], ['passed', 'Passed abstract'], ['pending', 'Undecided'], ['excluded', 'Excluded']]

export function SourcesTimeline({ records, stateOf, onOpen }: { records: Source[]; stateOf: (source: Source) => TimelineState; onOpen: (source: Source) => void }) {
  const dated = records.filter(s => s.year !== null)
  const undated = records.length - dated.length
  const years = new Map<number, Source[]>()
  for (const s of dated) years.set(s.year as number, [...(years.get(s.year as number) ?? []), s])
  const columns = [...years.entries()].sort((a, b) => a[0] - b[0])
  const present = timelineStates.filter(([key]) => dated.some(s => stateOf(s) === key))
  if (!columns.length) return <p className="empty-inline timeline-empty">{records.length ? t('None of the works shown has a publication year.') : t('No source matches this filter.')}</p>
  return <div className="source-timeline">
    <ul className="timeline-legend" aria-label={t('Tag colour')}>
      {present.map(([key, label]) => <li key={key}><span className={`timeline-swatch is-${key}`} aria-hidden />{t(label)}</li>)}
    </ul>
    <div className="timeline-scroll" role="region" aria-label={t('Timeline of the works shown')} tabIndex={0}>
      <ol className="timeline-years">
        {columns.map(([year, works]) => <li key={year} className="timeline-year">
          <ul className="timeline-stack" aria-label={t('{year}: {n} works', { year, n: works.length })}>
            {[...works].sort(byRank).map(s => {
              const state = stateOf(s)
              return <li key={s.source_version_id}><button type="button" className={`timeline-tag is-${state}`} title={s.title} aria-label={`${s.title} (${year}) · ${t(timelineStates.find(([key]) => key === state)![1])}`} onClick={() => onOpen(s)}>{shortTag(s)}</button></li>
            })}
          </ul>
          <span className="timeline-axis tnum">{year}</span>
        </li>)}
      </ol>
    </div>
    <p className="timeline-note">{t('Colour is the stored state of each work. Within a year the best search position is lowest; position is an ordering signal, not relevance.')}{undated > 0 && <> {t(undated === 1 ? '{n} work has no publication year and is not placed.' : '{n} works have no publication year and are not placed.', { n: undated })}</>}</p>
  </div>
}
