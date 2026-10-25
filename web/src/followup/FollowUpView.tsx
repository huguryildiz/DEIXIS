import { useEffect, useState } from 'react'
import { CircleX, RotateCw, TriangleAlert } from 'lucide-react'
import { api, ApiError, type ResearchView, type Watch, type WatchKind } from '../lib/api'
import { t } from '../lib/i18n'
import { Disclosure } from './Disclosure'
import { GapNotice } from './GapNotice'
import { ItemList } from './ItemList'
import { ScheduleDialog } from './ScheduleDialog'
import { WatchIcon, WatchSection } from './WatchSection'
import { kindLabels } from './labels'
import { useFollowUp } from './useFollowUp'
import '../research/kit.css'
import './followup.css'

// A follow-up kind with no follow-up on (mockup `.watch` "This follow-up is turned off."): the server's preview must
// accept it before Follow… opens the dialog.
function EnableEntry({ id, kind, view, watchList, turnedOff, onEnable }: { id: string; kind: WatchKind; view: ResearchView; watchList: string; turnedOff: boolean; onEnable: () => void }) {
  const [state, setState] = useState<{ ready: boolean; reason: string; retry: boolean }>({ ready: false, reason: '', retry: false })
  const [attempt, setAttempt] = useState(0)
  const noIncluded = kind === 'citing_works' && !view.sources.some(source => source.selection.state === 'included')
  useEffect(() => {
    if (noIncluded) return
    let live = true
    api.previewWatch(id, kind).then(() => { if (live) setState({ ready: true, reason: '', retry: false }) }, cause => {
      if (live) setState({ ready: false, reason: cause instanceof Error ? cause.message : String(cause),
        retry: !(cause instanceof ApiError && ['no_protocol', 'no_included_sources'].includes(cause.code ?? cause.message)) })
    })
    return () => { live = false }
  }, [id, kind, noIncluded, view.research.current_scope_revision, watchList, attempt])
  const reason = noIncluded ? t('Include a source before following citing works.') : state.reason
  return <section className="watch followup-enable-entry" aria-label={t(kindLabels[kind])}>
    <h4><WatchIcon kind={kind} />{t(kindLabels[kind])}</h4>
    <small>{t(turnedOff ? 'This follow-up is turned off.' : 'This follow-up is not on.')}</small>
    {reason ? <div className={`notice ${state.retry && !noIncluded ? 'bad' : 'warn'}`} role={state.retry && !noIncluded ? 'alert' : undefined}>{state.retry && !noIncluded ? <CircleX aria-hidden /> : <TriangleAlert aria-hidden />}<div className="nb"><span>{reason}</span>
      {state.retry && !noIncluded && <div className="acts"><button type="button" className="ghost" onClick={() => setAttempt(value => value + 1)}>{t('Retry')}</button></div>}</div></div>
      : state.ready ? <div className="acts"><button type="button" className="ghost" onClick={onEnable}>{t('Follow…')}</button></div> : <small role="status"><span className="shimmer-text">{t('Loading follow-up…')}</span></small>}
  </section>
}
// The Follow-up panel (mockup `watchPanel`, P37/P38): one box for each kind of follow-up, then the records found that
// are new to this research, the notices of missed checks, and what was dismissed or turned off.
export function FollowUpView({ researchId, view, dark, onReload, onChanged }: {
  researchId: string; view: ResearchView; dark: boolean; onReload: () => Promise<void>; onChanged: () => Promise<void>
}) {
  const data = useFollowUp(researchId, view.last_event_id, onReload)
  const [dialog, setDialog] = useState<{ kind: WatchKind; watch?: Watch } | null>(null)
  const enabled = data.watches.filter(watch => watch.enabled)
  const disabled = data.watches.filter(watch => !watch.enabled)
  const records = data.items.filter(item => item.kind === 'new_record')
  const notices = data.items.filter(item => item.kind === 'notice')
  const reload = async () => { await data.reload(); await onChanged() }
  return <section className="followup-view mk pad" aria-label={t('Follow-up')}>
    <div className="followup-intro"><p>{t('Follow-up watches for works that appear after this research ran. DEIXIS checks only while it is running.')}</p>
      <button type="button" className="ib" aria-label={t('Refresh')} title={t('Refresh')} onClick={() => { void data.reload() }}><RotateCw size={15} aria-hidden /></button></div>
    {data.loading && <p role="status" className="foot-note"><span className="shimmer-text">{t('Loading follow-up…')}</span></p>}
    {data.error && <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{t('Could not load follow-up: {error}', { error: data.error })}</span><div className="acts"><button type="button" className="ghost" onClick={() => { void data.reload() }}>{t('Retry')}</button></div></div></div>}
    {!data.loading && (['protocol_queries', 'citing_works'] as const).map(kind => {
      const watches = enabled.filter(item => item.kind === kind)
      return watches.length ? watches.map(watch => <WatchSection key={watch.id} researchId={researchId} watch={watch} view={view} dark={dark} reload={reload} onSchedule={current => setDialog({ kind: current.kind, watch: current })} />)
        : <EnableEntry key={`${kind}:${view.research.current_scope_revision}`} id={researchId} kind={kind} view={view} turnedOff={disabled.some(item => item.kind === kind)}
          watchList={JSON.stringify(data.watches.filter(item => item.kind === kind).map(item => [item.id, item.enabled]).sort())} onEnable={() => setDialog({ kind })} />
    })}
    <h3>{t('New to this research ({n})', { n: data.itemsLoaded ? records.length : '…' })}</h3>
    {data.itemsLoaded && records.length === 0 ? <p className="foot-note">{t('No new record is listed.')}</p> : <ItemList items={records} researchId={researchId} watches={data.watches} reload={reload} />}
    {enabled.map(watch => <GapNotice key={watch.id} researchId={researchId} watch={watch} />)}
    <Disclosure title={t('Notices ({n})', { n: data.itemsLoaded ? notices.length : '…' })}><ItemList items={notices} researchId={researchId} watches={data.watches} reload={reload} /></Disclosure>
    <Disclosure title={data.historyLoaded ? t('Dismissed ({n})', { n: data.history.length }) : t('Dismissed')} onToggle={data.setHistoryOpen}><ItemList items={data.history} researchId={researchId} watches={data.watches} reload={reload} /></Disclosure>
    <Disclosure title={t('Turned off ({n})', { n: disabled.length })}>{disabled.map(watch => <WatchSection key={watch.id} researchId={researchId} watch={watch} view={view} dark={dark} reload={reload} onSchedule={() => {}} />)}</Disclosure>
    <p className="foot-note">{t('Adding a found record to this research is not available yet; open it at the publisher or copy its DOI.')} {t('A check reads a limited number of pages. Records indexed late with an older publication date, and records ranked below the page limit, can be missed.')}</p>
    {dialog && <ScheduleDialog key={dialog.watch?.id ?? dialog.kind} researchId={researchId} scopeRevision={view.research.current_scope_revision} kind={dialog.kind} watch={dialog.watch} dark={dark}
      active={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} reload={reload} onClose={() => setDialog(null)} />}
  </section>
}
