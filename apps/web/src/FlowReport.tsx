import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronRight, Download, Info, Workflow } from 'lucide-react'
import { api, ApiError, prismaSUrl, screenMoreApi, type Answer, type Counts, type EffortLimits, type FlowBucket, type FlowCounts, type Overrides, type ResearchView, type UnscreenedPage } from './api'
import { flowBoxLabels, flowBucketLabels } from './labels'
import { effortLabels } from './Home'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

// Where every work of an sw research stands (slice 20). Counts only: a work two agreeing runs included is never called
// confirmed, the override count is never a rate, and the boxes are not added up.

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

// The five of SW11.12 in one line.
function fiveText(flow: FlowCounts) {
  const five = flow.five
  return t('{included} included (two agreeing runs {agreed}, you confirmed {confirmed}) · {queued} in your queue, not looked at · {waiting} waiting for a PDF · {notRead} full text not read ({reading} in reading, {tried} not tried) · {notMet} criterion not met', {
    included: count(five.included), agreed: count(five.included_by_agreement), confirmed: count(five.confirmed),
    queued: count(five.queued), waiting: count(five.waiting_for_pdf), notRead: count(five.not_read),
    reading: count(five.not_read_in_reading), tried: count(five.not_read_not_tried), notMet: count(five.not_met),
  })
}

const ORDER = Object.keys(flowBucketLabels) as FlowBucket[]

// The Sources tab's flow block, beside the export links: the five in one line, every bucket and box when opened, and
// the PRISMA-S search report.
export function FlowBlock({ researchId, counts }: { researchId: string; counts: Counts }) {
  const flow = counts.flow
  if (!flow) return null
  return <details className="search-summary flow-block">
    <summary><span><Workflow size={14} aria-hidden />{t('Flow')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{fiveText(flow)}</small></summary>
    <div className="flow-detail">
      <div>
        <p className="flow-head">{t('Where each of the {n} works stands', { n: count(flow.works) })}</p>
        <ul className="flow-list">{ORDER.filter(key => flow.buckets[key] > 0).map(key => <li key={key}>
          <span>{t(flowBucketLabels[key])}</span><strong>{count(flow.buckets[key])}</strong>
        </li>)}</ul>
        {flow.buckets.other > 0 && <p className="flow-note">{t('Other, by reason code: {list}', { list: Object.entries(flow.other_reasons).map(([code, n]) => `${code} ${n}`).join(' · ') })}</p>}
        {flow.buckets.abstract_not_read > 0 && <p className="flow-note">{t('An abstract not read is not an exclusion: the work was not read.')}</p>}
        {Object.keys(flow.queue_by_reason).length > 0 && <p className="flow-note">{t('Your queue by reason: {list}', { list: Object.entries(flow.queue_by_reason).map(([code, n]) => `${code} ${n}`).join(' · ') })}</p>}
      </div>
      {counts.flow_boxes && <div>
        <p className="flow-head">{t('Counts in the style of PRISMA 2020')}</p>
        <ul className="flow-list">{counts.flow_boxes.boxes.map(box => <li key={box.key}>
          <span>{t(flowBoxLabels[box.key] ?? box.key)}</span><strong>{box.count === null ? t('not counted') : count(box.count)}</strong>
        </li>)}</ul>
        <p className="flow-note">{t('Incomplete: code and model runs did the screening, and you looked only at your queue and the audit sample. The counts are not added up.')}</p>
      </div>}
      <span className="export-links flow-report" role="group" aria-label={t('Search report (PRISMA-S)')}>
        <span className="export-links-label"><Download size={15} aria-hidden />{t('Search report (PRISMA-S)')}</span>
        <span className="export-formats">
          <a href={prismaSUrl(researchId, 'md')} download title={t('The search reported against the 16 PRISMA-S items, as Markdown')}>.md</a>
          <a href={prismaSUrl(researchId, 'json')} download title={t('The search reported against the 16 PRISMA-S items, as JSON')}>.json</a>
        </span>
      </span>
    </div>
  </details>
}

// Under an sw answer: where the flow stood when its run started, and what was given to the model, on separate lines.
export function AnswerFlowNote({ answer }: { answer: Answer }) {
  const snapshot = answer.start_snapshot
  const given = answer.inputs_given
  return <div className="answer-flow" role="group" aria-label={t('Flow at the start of this answer')}>
    {snapshot ? <>
      <p>{t('When the answer started: included {included} (two agreeing runs {agreed}, you confirmed {confirmed}); in your queue, not looked at {queued}; waiting for a PDF {waiting}; full text not read {notRead} ({reading} in reading, {tried} not tried); criterion not met {notMet}.', {
        included: count(snapshot.flow.five.included), agreed: count(snapshot.flow.five.included_by_agreement),
        confirmed: count(snapshot.flow.five.confirmed), queued: count(snapshot.flow.five.queued),
        waiting: count(snapshot.flow.five.waiting_for_pdf), notRead: count(snapshot.flow.five.not_read),
        reading: count(snapshot.flow.five.not_read_in_reading), tried: count(snapshot.flow.five.not_read_not_tried),
        notMet: count(snapshot.flow.five.not_met) })}</p>
      {snapshot.included_without_answer_text > 0 && <p>{t(snapshot.included_without_answer_text === 1 ? '{n} included work gave the answer no text: its only text is your file, not read yet.' : '{n} included works gave the answer no text: their only text is your file, not read yet.', { n: count(snapshot.included_without_answer_text) })}</p>}
      {snapshot.included_state_changed && <p className="is-attention">{t('The state of the included sources changed while the answer ran.')}</p>}
      {snapshot.flow.look_again_in_answer > 0 && <p className="is-attention">{t(snapshot.flow.look_again_in_answer === 1 ? '{n} work rests on a decision you made under the earlier criterion.' : '{n} works rest on a decision you made under the earlier criterion.', { n: count(snapshot.flow.look_again_in_answer) })}</p>}
    </> : <p>{t('The flow at the start of this answer was not recorded.')}</p>}
    {given && <p>{t('Given to the model: works {sources}, passages {passages}.', { sources: count(given.sources), passages: count(given.passages) })}</p>}
  </div>
}

// The queue tab's first line (decision 4): how many of the person's decisions changed what code or the runs decided.
export function OverridesLine({ overrides }: { overrides: Overrides | null | undefined }) {
  if (!overrides) return null
  const apart = [
    overrides.apart.not_sure > 0 && t('not sure {n}', { n: count(overrides.apart.not_sure) }),
    overrides.apart.pdf_wrong > 0 && t('wrong PDF {n}', { n: count(overrides.apart.pdf_wrong) }),
    overrides.apart.look_again > 0 && t('to look at again {n}', { n: count(overrides.apart.look_again) }),
  ].filter(Boolean)
  return <p className="overrides-line">
    {overrides.decisions === 0
      ? t('You have not decided yet; this line says nothing about how right code or the model is.')
      : t(overrides.decisions === 1 ? 'Of your {n} decision, you changed a decision of code or the model runs in {m} (code {code}, model runs {model}).' : 'Of your {n} decisions, you changed a decision of code or the model runs in {m} (code {code}, model runs {model}).', {
        n: count(overrides.decisions), m: count(overrides.changed), code: count(overrides.changed_by.code), model: count(overrides.changed_by.model_agreement) })}
    {apart.length > 0 && ` ${t('Counted apart: {list}.', { list: apart.join(' · ') })}`}
  </p>
}

// ---- the Search funnel panel (UI parity S14, P41) ---------------------------------------------------------------------
// Six stages from the unique works down to the cited ones, each with its share of the first stage, a bar and, where works
// left the path, a line that names them and opens the place that lists them. Every number is one another place shows:
// the first three are the search step's funnel (`counts.funnel`, flow_counts.py), "Full text read" is the rail's count,
// the lost lines use the flow's buckets and the counts the PDFs and queue panels list, and "Given" and "Cited" belong to
// the answer shown in the thread. A missing count is shown as not known, never as 0.

type Opener = (name: string, opener: HTMLElement) => void
type Stage = { label: string; n: number | null; about: string; extra?: ReactNode; lost?: ReactNode }

const SCREEN_MORE_SIZE = 40  // screen_more.SIZE: the next 40 screenable works of the ranked list

export function FunnelPanel({ researchId, view, answer, cited, queueCount, busy, active, onPanel, onShowSources, onChanged }: {
  researchId: string; view: ResearchView; answer: Answer | null; cited: number; queueCount: number; busy: boolean; active: boolean
  onPanel: Opener; onShowSources: (filter: 'included' | 'cited', opener: HTMLElement) => void; onChanged: () => Promise<void>
}) {
  const toast = useToast()
  const counts = view.counts
  const funnel = counts.funnel
  const flow = counts.flow
  const [limits, setLimits] = useState<EffortLimits | null>(null)
  useEffect(() => { api.effortLimits().then(setLimits, () => setLimits(null)) }, [])
  // The ranked list's never-screened works (F12): its first page says how many there are and how many have an abstract.
  const [page, setPage] = useState<UnscreenedPage | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const [items, setItems] = useState<UnscreenedPage['items']>([])
  const [screening, setScreening] = useState(false)
  // Each read of the list gets a number: a first page read again (an event) makes every older read stale, so a page that
  // arrives after it is dropped, and "Show more" is locked while its own read runs, so one page is never added twice.
  const listRead = useRef(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const loadPage = useCallback(() => {
    const read = ++listRead.current
    return screenMoreApi.unscreened(researchId, 0, 20).then(next => { if (read === listRead.current) { setPage(next); setItems(next.items) } },
      () => { if (read === listRead.current) { setPage(null); setItems([]) } })
  }, [researchId])
  useEffect(() => { void loadPage() }, [loadPage, view.last_event_id])
  const more = () => {
    if (!page || loadingMore) return
    const read = listRead.current
    setLoadingMore(true)
    void screenMoreApi.unscreened(researchId, items.length, 20).then(next => {
      if (read === listRead.current) setItems(prev => [...prev, ...next.items])
    }, () => {}).finally(() => setLoadingMore(false))
  }

  if (!funnel) return <p className="empty-inline">{t('The funnel appears when a search of this question has run.')}</p>

  const base = funnel.unique
  const number = (n: number) => n.toLocaleString(uiLocale())
  const effort = view.scope.effort
  const mode = limits?.efforts[effort]
  const detailed = limits?.efforts.detailed
  const given = answer?.inputs_given
  const givenWorks = given ? new Set(given.source_ids.map(id => view.sources.find(s => s.source_version_id === id)?.work_id ?? id)).size : null
  const version = answer?.report_version
  const notScreened = flow?.buckets.not_screened ?? null
  const screenable = page?.screenable ?? 0
  const nextBatch = Math.min(SCREEN_MORE_SIZE, screenable)
  const waiting = counts.waiting_for_pdf ?? 0

  const screenMore = async () => {
    setScreening(true)
    try {
      const run = await screenMoreApi.screenMore(researchId, crypto.randomUUID())
      const planned = (run.budget as unknown as { screen_more?: { planned?: number } }).screen_more?.planned
      toast('success', planned === undefined
        ? t('Screen more queued. Its works are read twice at the abstract stage; it never includes a source by itself.')
        : t(planned === 1 ? 'Screen more queued: {n} work is read twice at the abstract stage. It never includes a source by itself.' : 'Screen more queued: {n} works are read twice at the abstract stage. It never includes a source by itself.', { n: planned }))
      await Promise.all([onChanged(), loadPage()])
    } catch (e) {
      toast('error', e instanceof ApiError && e.status === 409 ? t('Another run of this research is active, so Screen more was not queued.')
        : e instanceof ApiError && e.code === 'nothing_left' ? t('No work with an abstract is left on the ranked list, so Screen more was not queued.')
        : e instanceof ApiError && e.code === 'no_completed_discovery' ? t('This research has no completed search with a ranked list, so Screen more was not queued.')
        : e instanceof Error ? e.message : String(e))
    } finally { setScreening(false) }
  }

  const lostItem = (n: number, text: string) => n > 0 ? <span key={text}><b className="tnum">{number(n)}</b> {t(text)}</span> : null
  const link = (label: string, onClick: (opener: HTMLElement) => void) => <button type="button" className="link" onClick={e => onClick(e.currentTarget)}>{t(label)}</button>
  const outOfScope = flow ? [lostItem(flow.buckets.out_of_scope_model, 'out of scope by two model reads'), lostItem(flow.buckets.out_of_scope_code, 'out of scope by a code rule'),
    lostItem(flow.buckets.survey, 'surveys by their title'), lostItem(flow.buckets.abstract_open, 'left open at the abstract stage')].filter(Boolean) : []
  const fulltextLost = [lostItem(waiting, 'waiting for a PDF'), flow ? lostItem(flow.five.not_read_in_reading, 'with text in hand, not read yet') : null,
    flow ? lostItem(flow.five.not_read_not_tried, 'passed the abstract stage, full text not tried') : null, lostItem(queueCount, 'waiting for your decision')].filter(Boolean)

  const stages: Stage[] = [
    { label: 'Found by search and citations', n: funnel.unique,
      about: funnel.chained
        ? t('{keyword} from the searches ({rows} records returned), {chained} only from citation chaining; duplicates merged by DOI.', { keyword: number(funnel.unique - funnel.chained), rows: number(funnel.retrieved), chained: number(funnel.chained) })
        : t('{rows} records returned by the searches, merged by DOI into these works.', { rows: number(funnel.retrieved) }) },
    { label: 'Abstract read', n: funnel.abstracts_read,
      about: mode ? t('Works a model read at the abstract stage. {depth} depth reads the top {n} of the ranked list.', { depth: t(effortLabels[effort]), n: number(mode.papers) }) : t('Works a model read at the abstract stage.'),
      lost: notScreened !== null && notScreened > 0 ? <>
        <span><b className="tnum">{number(notScreened)}</b> {t('never screened')}</span>
        {page && page.total > 0 && link(listOpen ? 'Hide them' : 'Show them', () => setListOpen(open => !open))}
        {page && nextBatch > 0 && <button type="button" className="link" disabled={busy || active || screening} title={active ? t('Available when the current run ends') : undefined} onClick={() => { void screenMore() }}>{t('Screen {n} more', { n: nextBatch })}</button>}
      </> : undefined,
      extra: listOpen && page ? <UnscreenedList page={page} items={items} notScreened={notScreened} loading={loadingMore} onMore={more} /> : undefined },
    { label: 'Passed the abstract stage', n: funnel.candidates,
      about: t('Works whose current abstract-stage decision is that they may meet the criterion. An abstract alone never includes a work.'),
      lost: outOfScope.length ? <>{outOfScope}</> : undefined },
    { label: 'Full text read', n: counts.fulltext_read_works ?? null,
      about: t('Works whose two full-text passes both stored a result in one run. Each pass reads selected pages of the PDF, not the whole text. Reading the full text, or your own decision, is what includes a work.'),
      extra: <div className="kv"><span>{t('Included')} <b className="tnum">{number(counts.included)}</b></span>{link('Included sources', opener => onShowSources('included', opener))}</div>,
      lost: fulltextLost.length ? <>{fulltextLost}
        {waiting > 0 && link('Get more full text', opener => onPanel('pdfs', opener))}
        {queueCount > 0 && link('Decide', opener => onPanel('queue', opener))}</> : undefined },
    { label: 'Given to the answer', n: givenWorks,
      about: given ? t('{passages} passages from these works went to the answer model for the answer shown (V{v}).', { passages: number(given.passages), v: version ?? '–' }) : t('No answer shown in the thread was given passages yet.') },
    { label: 'Cited', n: answer ? cited : null,
      about: answer ? t('Works behind at least one claim of the answer shown in the thread (V{v}).', { v: version ?? '–' }) : t('No answer is shown in the thread yet.'),
      lost: answer && cited > 0 ? link('Cited sources', opener => onShowSources('cited', opener)) : undefined },
  ]
  const share = (n: number) => (base ? n / base * 100 : 0)

  return <div className="mock-pad funnel-panel">
    <p>{t('Where works dropped out between search and answer. Each orange number is a place where something relevant could have been lost.')}</p>
    <div>{stages.map(stage => <div key={stage.label} className="stage">
      <h4>{t(stage.label)}<small>{stage.about}</small></h4>
      <div className="sb">
        <div className="kv"><span className="tnum stage-n">{stage.n === null ? t('not known') : number(stage.n)}</span>{stage.n !== null && base > 0 && <span className="tnum">{t('{p}% of found', { p: Math.round(share(stage.n)) })}</span>}</div>
        <div className="track" aria-hidden><i style={{ width: `${stage.n === null ? 0 : Math.max(1, share(stage.n))}%` }} /></div>
        {stage.extra}
        {stage.lost && <div className="lost">{stage.lost}</div>}
      </div>
    </div>)}</div>
    {limits && effort !== 'detailed' && detailed && <div className="notice"><Info size={16} aria-hidden /><span>{t('Want a wider net? Detailed depth screens up to {n} abstracts and reads up to {k} works in their full text (selected pages); it also adds one Semantic Scholar bulk query when that source is searched.', { n: number(detailed.papers), k: number(detailed.fulltext ?? 0) })}</span></div>}
    <FlowBlock researchId={researchId} counts={counts} />
  </div>
}

// "Show them" (F12): the never-screened works of the ranked list, in its order. Rank and similarity are the signals the
// list was ordered by, not relevance; the header's count is this list's own.
function UnscreenedList({ page, items, notScreened, loading, onMore }: { page: UnscreenedPage; items: UnscreenedPage['items']; notScreened: number | null; loading: boolean; onMore: () => void }) {
  const off = notScreened !== null ? notScreened - page.total : 0
  return <div className="unscreened">
    <p className="src-m">{t('{total} on the ranked list were never screened, in its order; {screenable} of them have an abstract to read. Rank and similarity are signals the list was ordered by, not relevance.', { total: page.total.toLocaleString(uiLocale()), screenable: page.screenable.toLocaleString(uiLocale()) })}
      {off > 0 && ` ${t(off === 1 ? '{n} more work never screened is not on the ranked list.' : '{n} more works never screened are not on the ranked list.', { n: off.toLocaleString(uiLocale()) })}`}</p>
    <ol>{items.map(item => <li key={item.work_id}>
      <span className="src-t">{item.title ?? t('Untitled record')}</span>
      <span className="src-m">{[item.year, item.venue, t('rank {n}', { n: item.signals.rank }), item.signals.similarity === null ? null : t('similarity {s}', { s: item.signals.similarity.toLocaleString(uiLocale(), { maximumFractionDigits: 2 }) }),
        !item.screenable && t(item.not_screenable_reason === 'no_abstract' ? 'no abstract to read' : item.not_screenable_reason === 'screen_more_could_not_read' ? 'Screen more could not read it' : 'its abstract is not on a searched version')].filter(Boolean).join(' · ')}</span>
    </li>)}</ol>
    {items.length < page.total && <button type="button" className="link" disabled={loading} aria-busy={loading} onClick={onMore}>{t('Show {n} more', { n: Math.min(20, page.total - items.length) })}</button>}
  </div>
}
