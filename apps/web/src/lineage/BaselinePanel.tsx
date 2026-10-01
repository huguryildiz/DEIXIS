import { useState } from 'react'
import { Button } from '@/components/ui/button'
import type { LineageBaseline, LineageBaselineList } from '../api'
import { t } from '../i18n'
import { WorkName, type WorkProps } from './LinkRow'
import { dateText } from './labels'

function BaselineList({ title, list, ...work }: WorkProps & { title: string; list: LineageBaselineList }) {
  const [all, setAll] = useState(false)
  return <section className="lineage-section"><h4>{t(title)} · {list.total}</h4><p>{t(list.note)}</p>
    {list.entries.length ? <ol>{(all ? list.entries : list.shown).map(entry => { const count = entry.cited_by_included_works; return <li key={entry.work_id}>
      <WorkName id={entry.source_version_id} {...work} />
      <p>{entry.cited_by_count != null ? t('Provider count: {n}', { n: entry.cited_by_count }) : t('No stored provider count')}{entry.cited_by_count_at && <> · {dateText(entry.cited_by_count_at)}</>}
        {entry.publication_type != null && <> · {t('Registered type: {type}', { type: entry.publication_type })}</>}</p>
      <p>{count.count != null ? t('cited by {n} of the works in this table', { n: count.count })
        : !count.target_resolved ? t('not counted: this work could not be matched to the identifiers in the stored reference lists')
        : count.lists_read === 0 ? t('not counted: no reference list of the other works was read') : t('not counted')}
        {' · '}{t('reference lists read: {a} of {b}', { a: count.lists_read, b: count.other_works })}</p>
    </li> })}</ol> : <p>{t('None.')}</p>}
    {!all && list.entries.length > list.shown.length && <Button variant="ghost" onClick={() => setAll(true)}>{t('Show all {n}', { n: list.total })}</Button>}
  </section>
}
export function BaselinePanel({ baseline, ...work }: WorkProps & { baseline: LineageBaseline }) {
  return <section className="lineage-baseline" aria-labelledby="lineage-baseline-heading"><h3 id="lineage-baseline-heading">{t('Field baseline')}</h3>
    <p>{t(baseline.scope)}</p><p>{t('Computed when you open it from stored data; no search was made.')}</p>
    <h4>{t('Versions representing the works')}</h4>
    {baseline.representatives.length ? <ul>{baseline.representatives.map(rep => <li key={rep.work_id}><WorkName id={rep.source_version_id} {...work} />
      <span> · {t(rep.reason === 'head' ? 'head version represents this work' : 'another version represents this work')}</span>
      <details><summary>{t('Versions considered · {n}', { n: rep.versions_considered.length })}</summary><ul>{rep.versions_considered.map(id => <li key={id}><WorkName id={id} {...work} /></li>)}</ul></details>
    </li>)}</ul> : <p>{t('None.')}</p>}
    <BaselineList title="Most cited in this corpus" list={baseline.most_cited_in_corpus} {...work} />
    <BaselineList title="Reviews in this corpus" list={baseline.review_in_corpus} {...work} />
    <p>{t('{n} works have no stored count; they are not ranked and not counted as zero', { n: baseline.unknown_count_works })}</p>
  </section>
}
