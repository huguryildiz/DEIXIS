import type { BroadIndex, FieldSearchRow, SourceCounts } from '../lib/api'
import { ConnectionIcon } from '../components/connectionIcons'
import { t, uiLocale } from '../lib/i18n'
import { armKindLabels, broadIndexReasonText, fieldSourceReasonText, providerName } from '../lib/labels'

// The search phase at a glance: one bar per route scaled to the unique works, a card per field source with the share
// of the question's records its fields hold, and one tile per arm. Every number is a stored count; the full text
// lines stay one click deeper in the step.
const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
const percent = (share: number) => new Intl.NumberFormat(uiLocale(), { style: 'percent', maximumFractionDigits: 0 }).format(share)

// One route's bar: the works only this route found (dark) and the works another route also found (light).
function RouteBar({ id, name, works, only, onlyText, scale }: { id: string; name: string; works: number; only: number; onlyText: string; scale: number }) {
  const width = (n: number) => `${scale > 0 ? (n / scale) * 100 : 0}%`
  return <li>
    <span className="search-summary-route"><ConnectionIcon id={id} />{name}</span>
    <span className="search-summary-track" aria-hidden>
      <span className="is-only" style={{ width: width(only) }} />
      <span className="is-shared" style={{ width: width(Math.max(0, works - only)) }} />
    </span>
    <span className="search-summary-count"><b className="tnum">{count(works)}</b> · {onlyText}</span>
  </li>
}

// A field source, or the second index, as a small card: its share (when one was read) and what the run did with it.
function SourceCard({ id, share, searched, text }: { id: string; share: number | null; searched: boolean; text: string }) {
  return <li className={searched ? 'is-searched' : undefined}>
    <span className="search-summary-card-head"><span><ConnectionIcon id={id} />{providerName(id)}</span>{share !== null && <span className="tnum">{percent(share)}</span>}</span>
    {share !== null && <span className="search-summary-share" aria-hidden><span style={{ width: `${Math.min(1, Math.max(0, share)) * 100}%` }} /></span>}
    <span className="search-summary-card-text">{text}</span>
  </li>
}

export function SearchSummary({ counts, unique, fields, broad }: {
  counts: SourceCounts; unique: number | null; fields: FieldSearchRow[]; broad: BroadIndex | null | undefined
}) {
  const several = counts.sources.length > 1
  const arms = counts.arms
  // The bars share one scale: the unique works when known, else the largest route.
  const scale = unique ?? Math.max(0, ...counts.sources.map(s => s.works), counts.chain?.works ?? 0)
  const fieldText = (row: FieldSearchRow) => row.state === 'searched'
    ? t('searched, {records} records', { records: count(row.records ?? 0) })
    : row.state === 'planned' ? t('planned, no reply recorded') : fieldSourceReasonText(row.reason)
  const broadText = (index: BroadIndex) => index.state === 'searched'
    ? t('searched as a second index, {records} records', { records: count(index.records_found ?? 0) })
    : index.state === 'planned' ? t('planned, no reply recorded') : broadIndexReasonText(index.reason)
  const kinds = arms?.kinds.filter(kind => kind.ran) ?? []
  return <div className="search-summary-visual">
    <p className="search-summary-head">{t('Where the works came from')}</p>
    <ul className="search-summary-routes">
      {counts.sources.map(source => <RouteBar key={source.provider_id} id={source.provider_id} name={providerName(source.provider_id)}
        works={source.works} only={several ? source.only : source.works} scale={scale}
        onlyText={several ? t('{n} only here', { n: count(source.only) }) : t('{n} works', { n: count(source.works) })} />)}
      {counts.chain && <RouteBar id="openalex" name={t('Citation chain')} works={counts.chain.works} only={counts.chain.only} scale={scale}
        onlyText={t('{n} new', { n: count(counts.chain.only) })} />}
    </ul>
    <p className="search-summary-legend" aria-hidden><span><i className="is-only" />{t('Found only by this route')}</span><span><i className="is-shared" />{t('Also found by another route')}</span></p>
    {(fields.length > 0 || broad) && <>
      <p className="search-summary-head">{t('Field sources · share of the question’s records')}</p>
      <ul className="search-summary-cards">
        {fields.map(row => <SourceCard key={row.provider_id} id={row.provider_id} share={row.share} searched={row.state === 'searched'} text={fieldText(row)} />)}
        {broad && <SourceCard id={broad.provider_id} share={null} searched={broad.state === 'searched'} text={broadText(broad)} />}
      </ul>
    </>}
    {kinds.length > 0 && <>
      <p className="search-summary-head">{t('What each route added')}</p>
      <ul className="search-summary-tiles">{kinds.map(kind => kind.ran && <li key={kind.kind}>
        <span>{t(armKindLabels[kind.kind])}</span>
        <span><b className="tnum">{count(kind.works)}</b> {t('works')}{arms?.read ? ` · ${t('{n} included', { n: count(kind.included) })}` : ''}</span>
      </li>)}</ul>
    </>}
  </div>
}

// The citation chain at a glance: one tile per place its records came from, then one bar of the works it brought,
// split into works no search found (dark) and works a search also found (light). Every number is a stored count.
export function ChainSummary({ links, backward, forward, seeds, asks, works, only }: {
  links: number | null; backward: number; forward: number; seeds: number; asks: boolean; works: number; only: number
}) {
  const width = (n: number) => `${works > 0 ? (n / works) * 100 : 0}%`
  return <div className="search-summary-visual">
    <ul className="search-summary-tiles">
      {links !== null && <li><span>{t('Citations inside the first page')}</span><span><b className="tnum">{count(links)}</b> {t('links, no request')}</span></li>}
      {asks && <li><span>{t(seeds === 1 ? 'References of {n} seed work' : 'References of {n} seed works', { n: count(seeds) })}</span><span><b className="tnum">{count(backward)}</b> {t('records kept')}</span></li>}
      {asks && <li><span>{t('Works citing the seeds')}</span><span><b className="tnum">{count(forward)}</b> {t('records kept')}</span></li>}
    </ul>
    <p className="search-summary-head">{t('Works the chain brought')}</p>
    <ul className="search-summary-routes">
      <li>
        <span className="search-summary-route">{t('Citation chain')}</span>
        <span className="search-summary-track" aria-hidden>
          <span className="is-only" style={{ width: width(only) }} />
          <span className="is-shared" style={{ width: width(Math.max(0, works - only)) }} />
        </span>
        <span className="search-summary-count"><b className="tnum">{count(works)}</b> · {t('{n} new', { n: count(only) })}</span>
      </li>
    </ul>
    <p className="search-summary-legend" aria-hidden><span><i className="is-only" />{t('Not found by any search')}</span><span><i className="is-shared" />{t('Also found by a search')}</span></p>
  </div>
}

// A row of numbers with short labels, split by hairlines: the quiet form for counts that need no bar.
export type StatItem = { n: number; label: string }
export function StatStrip({ items }: { items: StatItem[] }) {
  return <ul className="stat-strip">{items.map(item => <li key={item.label}><b className="tnum">{count(item.n)}</b>{item.label}</li>)}</ul>
}
