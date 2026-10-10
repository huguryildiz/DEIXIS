import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type ResearchView, type Watch, type WatchKind } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { Disclosure } from './Disclosure'
import { GapNotice } from './GapNotice'
import { ItemList } from './ItemList'
import { ScheduleDialog } from './ScheduleDialog'
import { WatchSection } from './WatchSection'
import { kindLabels } from './labels'
import { useFollowUp } from './useFollowUp'
import './followup.css'

function EnableEntry({ id, kind, view, watchList, onEnable }: { id: string; kind: WatchKind; view: ResearchView; watchList: string; onEnable: () => void }) {
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
  return <section className="followup-enable-entry" aria-label={t(kindLabels[kind])}>
    <p>{t(kindLabels[kind])}</p>
    {reason ? <Notice tone={state.retry && !noIncluded ? 'error' : 'attention'}>{reason}
      {state.retry && !noIncluded && <Button variant="outline" onClick={() => setAttempt(value => value + 1)}>{t('Retry')}</Button>}
    </Notice> : state.ready ? <Button variant="outline" onClick={onEnable}>{t('Follow…')}</Button> : <p role="status">{t('Loading follow-up…')}</p>}
  </section>
}
export function FollowUpView({ researchId, view, dark, onReload, onChanged }: {
  researchId: string; view: ResearchView; dark: boolean; onReload: () => Promise<void>; onChanged: () => Promise<void>
}) {
  const data = useFollowUp(researchId, view.last_event_id, onReload)
  const [dialog, setDialog] = useState<{ kind: WatchKind; watch?: Watch } | null>(null)
  const enabled = data.watches.filter(watch => watch.enabled).sort((a, b) => Number(a.kind === 'citing_works') - Number(b.kind === 'citing_works'))
  const disabled = data.watches.filter(watch => !watch.enabled)
  const records = data.items.filter(item => item.kind === 'new_record')
  const notices = data.items.filter(item => item.kind === 'notice')
  const reload = async () => { await data.reload(); await onChanged() }
  return <section className="followup-view" aria-labelledby="followup-heading">
    <div className="workspace-pane-head"><div><h2 id="followup-heading">{t('Follow-up')}</h2><p>{t('DEIXIS checks only while it is running.')}</p></div>
      <Button variant="outline" onClick={() => { void data.reload() }}>{t('Refresh')}</Button></div>
    {data.loading && <p role="status">{t('Loading follow-up…')}</p>}
    {data.error && <Notice tone="error">{t('Could not load follow-up: {error}', { error: data.error })} <Button variant="outline" onClick={() => { void data.reload() }}>{t('Retry')}</Button></Notice>}
    {enabled.map(watch => <GapNotice key={watch.id} researchId={researchId} watch={watch} />)}
    {enabled.map(watch => <WatchSection key={watch.id} researchId={researchId} watch={watch} view={view} dark={dark} reload={reload} onSchedule={current => setDialog({ kind: current.kind, watch: current })} />)}
    {!data.loading && (['protocol_queries', 'citing_works'] as const).filter(kind => !enabled.some(watch => watch.kind === kind)).map(kind => <EnableEntry key={`${kind}:${view.research.current_scope_revision}`} id={researchId} kind={kind} view={view}
      watchList={JSON.stringify(data.watches.filter(watch => watch.kind === kind).map(watch => [watch.id, watch.enabled]).sort())} onEnable={() => setDialog({ kind })} />)}
    <p className="followup-limit">{t('A check reads a limited number of pages. Records indexed late with an older publication date, and records ranked below the page limit, can be missed.')}</p>
    <h3>{t('New to this research ({n})', { n: data.itemsLoaded ? records.length : '…' })}</h3>
    <ItemList items={records} researchId={researchId} reload={reload} />
    <p className="followup-fine">{t('Adding a found record to this research is not available yet; open it at the publisher or copy its DOI.')}</p>
    <Disclosure title={t('Notices ({n})', { n: data.itemsLoaded ? notices.length : '…' })}><ItemList items={notices} researchId={researchId} reload={reload} /></Disclosure>
    <Disclosure title={data.historyLoaded ? t('Dismissed ({n})', { n: data.history.length }) : t('Dismissed')} onToggle={data.setHistoryOpen}><ItemList items={data.history} researchId={researchId} reload={reload} /></Disclosure>
    <Disclosure title={t('Turned off ({n})', { n: disabled.length })}>{disabled.map(watch => <WatchSection key={watch.id} researchId={researchId} watch={watch} view={view} dark={dark} reload={reload} onSchedule={() => {}} />)}</Disclosure>
    {dialog && <ScheduleDialog key={dialog.watch?.id ?? dialog.kind} researchId={researchId} scopeRevision={view.research.current_scope_revision} kind={dialog.kind} watch={dialog.watch} dark={dark}
      active={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} reload={reload} onClose={() => setDialog(null)} />}
  </section>
}
