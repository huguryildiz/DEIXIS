import { useEffect, useState } from 'react'
import { CircleX, Link, Pause, Play, RotateCw, Search, TriangleAlert, X } from 'lucide-react'
import { api, type Watch, type ResearchView } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { t } from '../i18n'
import { CheckDetail } from './CheckDetail'
import { useFollowUpCommand } from './commands'
import { CommandFeedback } from './CommandFeedback'
import { kindLabels, modeText, reasonText, timeText } from './labels'

export const WatchIcon = ({ kind }: { kind: Watch['kind'] }) => kind === 'protocol_queries' ? <Search size={15} aria-hidden /> : <Link size={15} aria-hidden />

// One follow-up (mockup `watchPanel` `.watch`): how often it checks, a stop while it follows an earlier question,
// its latest check, and Check now / Schedule… / Turn off. A check only starts when the server accepts it.
export function WatchSection({ researchId, watch, view, dark, reload, onSchedule }: {
  researchId: string; watch: Watch; view: ResearchView; dark: boolean; reload: () => Promise<void>; onSchedule: (watch: Watch) => void
}) {
  const [confirm, setConfirm] = useState<'disable' | 'rebind' | null>(null)
  const [controlError, setControlError] = useState('')
  const [controlling, setControlling] = useState(false)
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = setTimeout(() => setNow(Date.now()), 0)
    return () => clearTimeout(timer)
  }, [watch])
  const check = watch.last_check
  const active = view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))
  const checkCommand = useFollowUpCommand(`watch:${watch.id}:check`, saved => api.checkWatch(researchId, watch.id, saved.body, saved.key), reload)
  const disable = useFollowUpCommand(`watch:${watch.id}:disable`, saved => api.disableWatch(researchId, watch.id, saved.body, saved.key), reload, () => setConfirm(null))
  const rebind = useFollowUpCommand(`watch:${watch.id}:rebind`, saved => api.rebindWatch(researchId, watch.id, saved.body, saved.key), reload, () => setConfirm(null))
  const locked = checkCommand.locked || disable.locked || rebind.locked || controlling
  const oldScope = watch.follows_old_scope || watch.waiting_reason === 'watch_follows_old_scope'
  const reason = locked ? t('Resolve the pending command before starting another.')
    : !watch.enabled ? t('This follow-up is turned off.')
    : oldScope ? t('Checks wait until you rebind this follow-up to the current question.')
    : watch.waiting_reason === 'check_paused' || check?.state === 'paused' || check?.outcome_unknown ? reasonText('check_paused')
    : active ? t('Finish or cancel the active research run first.') : ''
  const control = async (action: 'pause' | 'resume' | 'cancel') => {
    if (!check) return
    setControlling(true)
    try { await api.controlRun(check.run_id, action); setControlError(''); await reload() }
    catch (cause) { setControlError(cause instanceof Error ? cause.message : String(cause)); await reload() }
    finally { setControlling(false) }
  }
  const unfinished = check && ['queued', 'running', 'pause_requested', 'paused'].includes(check.state)
  const describedBy = locked ? `watch-reason-${watch.id}` : undefined
  return <section className="watch followup-watch" aria-label={t(kindLabels[watch.kind])} data-watch-id={watch.id}>
    <h4><WatchIcon kind={watch.kind} />{t(kindLabels[watch.kind])}{unfinished && <span className="spin" aria-hidden />}</h4>
    {watch.enabled ? <>
      <small>{modeText(watch)}</small>
      {watch.mode === 'interval' && <small>{watch.next_due_at && <>{t(new Date(watch.next_due_at).getTime() <= now ? 'Due since {time}' : 'Next check due {time}', { time: timeText(watch.next_due_at) })} · </>}{t('A due check waits while any run in DEIXIS is queued or running.')}</small>}
      {oldScope ? <div className="notice warn"><TriangleAlert aria-hidden /><div className="nb"><span>{t('This follow-up still follows an earlier revision of the question. Checks are stopped until you rebind it to the current question and protocol.')}{watch.follows_old_scope_reason && <> {reasonText(watch.follows_old_scope_reason)}</>}</span>
        <div className="acts"><button type="button" className="btn-pri" disabled={locked} aria-describedby={describedBy} onClick={() => setConfirm('rebind')}>{t('Rebind')}</button></div></div></div>
        : watch.waiting_reason && <div className="notice warn"><TriangleAlert aria-hidden /><span>{reasonText(watch.waiting_reason)}</span></div>}
    </> : watch.disabled_at && <small>{t('Turned off {time}', { time: timeText(watch.disabled_at) })}</small>}
    {check ? <CheckDetail check={check} /> : <small>{t('No check is recorded yet.')}</small>}
    {unfinished && <div className="acts">
      {watch.enabled && ['queued', 'running'].includes(check.state) && <button type="button" className="ghost" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('pause') }}><Pause aria-hidden />{t('Pause')}</button>}
      {watch.enabled && check.state === 'paused' && <button type="button" className="ghost" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('resume') }}><Play aria-hidden />{t('Resume')}</button>}
      <button type="button" className="ghost" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('cancel') }}><X aria-hidden />{t('Cancel')}</button>
      <span id={`watch-control-${watch.id}`} role="status" className="foot-note">{locked ? t('Resolve the pending command before starting another.') : ''}</span>
    </div>}
    {controlError && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{controlError}</span></div>}
    {watch.enabled && reason && <small className="followup-reason" id={`watch-reason-${watch.id}`}>{reason}</small>}
    {watch.enabled && <div className="acts">
      <button type="button" className="ghost" disabled={Boolean(reason)} aria-describedby={reason ? `watch-reason-${watch.id}` : undefined} onClick={() => checkCommand.start({ expected_state_version: watch.state_version })}><RotateCw aria-hidden />{t('Check now')}</button>
      <button type="button" className="ghost" disabled={locked} aria-describedby={describedBy} onClick={() => onSchedule(watch)}>{t('Schedule…')}</button>
      <button type="button" className="ghost" disabled={locked} aria-describedby={describedBy} onClick={() => setConfirm('disable')}>{t('Turn off')}</button>
    </div>}
    <CommandFeedback command={checkCommand} /><CommandFeedback command={disable} /><CommandFeedback command={rebind} />
    <ConfirmDialog open={confirm !== null} dark={dark} neutral title={t(confirm === 'rebind' ? 'Rebind follow-up?' : 'Turn off follow-up?')}
      description={t(confirm === 'rebind' ? 'A new follow-up starts from the current question with a fresh first check; what was seen stays seen.' : 'Found records stay listed; no further checks run.')}
      context={t(kindLabels[watch.kind])} confirmLabel={t(confirm === 'rebind' ? 'Rebind' : 'Turn off')} cancelLabel={t('Cancel')}
      busy={confirm === 'rebind' ? rebind.busy : disable.busy} onOpenChange={open => { if (!open) setConfirm(null) }}
      onConfirm={() => (confirm === 'rebind' ? rebind : disable).start({ expected_state_version: watch.state_version })}>
      {confirm === 'rebind' ? <CommandFeedback command={rebind} /> : <CommandFeedback command={disable} />}
    </ConfirmDialog>
  </section>
}
