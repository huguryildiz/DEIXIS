import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type Watch, type ResearchView } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { CheckDetail } from './CheckDetail'
import { useFollowUpCommand } from './commands'
import { CommandFeedback } from './CommandFeedback'
import { kindLabels, modeText, reasonText, timeText } from './labels'

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
  const reason = locked ? t('Resolve the pending command before starting another.')
    : !watch.enabled ? t('This follow-up is turned off.')
    : watch.follows_old_scope ? `${reasonText('watch_follows_old_scope')} ${reasonText(watch.follows_old_scope_reason)}`
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
  return <section className="followup-watch" aria-label={t(kindLabels[watch.kind])} data-watch-id={watch.id}>
    <div className="followup-watch-head"><div><h3>{t(kindLabels[watch.kind])}</h3>
      {watch.enabled ? <>
        <p>{modeText(watch)}</p>
        {watch.mode === 'interval' && <>
          {watch.next_due_at && <p>{t(new Date(watch.next_due_at).getTime() <= now ? 'Due since {time}' : 'Next check due {time}', { time: timeText(watch.next_due_at) })}</p>}
          <p className="followup-fine">{t('A due check waits while any run in DEIXIS is queued or running.')}</p>
        </>}
      </> : watch.disabled_at && <p>{t('Turned off {time}', { time: timeText(watch.disabled_at) })}</p>}
    </div>
    {watch.enabled && <div className="followup-actions">
      <Button variant="outline" disabled={Boolean(reason)} aria-describedby={reason ? `watch-reason-${watch.id}` : undefined} onClick={() => checkCommand.start({ expected_state_version: watch.state_version })}>{t('Check now')}</Button>
      <Button variant="ghost" disabled={locked} aria-describedby={locked ? `watch-reason-${watch.id}` : undefined} onClick={() => onSchedule(watch)}>{t('Schedule…')}</Button>
      <Button variant="ghost" disabled={locked} aria-describedby={locked ? `watch-reason-${watch.id}` : undefined} onClick={() => setConfirm('disable')}>{t('Turn off')}</Button>
    </div>}</div>
    {watch.enabled && reason && <p className="followup-muted" id={`watch-reason-${watch.id}`}>{reason}</p>}
    {watch.enabled && watch.waiting_reason && <Notice tone="attention">
      {reasonText(watch.waiting_reason)} {watch.waiting_reason === 'watch_follows_old_scope' && <>
        {reasonText(watch.follows_old_scope_reason)} <Button variant="outline" disabled={locked} aria-describedby={locked ? `watch-reason-${watch.id}` : undefined} onClick={() => setConfirm('rebind')}>{t('Rebind')}</Button>
      </>}
    </Notice>}
    {check ? <CheckDetail check={check} /> : <p>{t('No check is recorded yet.')}</p>}
    {unfinished && <div className="followup-actions">
      {watch.enabled && ['queued', 'running'].includes(check.state) && <Button variant="ghost" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('pause') }}>{t('Pause')}</Button>}
      {watch.enabled && check.state === 'paused' && <Button variant="outline" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('resume') }}>{t('Resume')}</Button>}
      <Button variant="ghost" disabled={locked} aria-describedby={`watch-control-${watch.id}`} onClick={() => { void control('cancel') }}>{t('Cancel')}</Button>
      <span id={`watch-control-${watch.id}`} role="status">{locked ? t('Resolve the pending command before starting another.') : ''}</span>
    </div>}
    {controlError && <Notice tone="error">{controlError}</Notice>}
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
