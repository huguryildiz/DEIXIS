import { useEffect, useState } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import { Button } from '@/components/ui/button'
import { api, type Watch, type WatchKind, type WatchPreview, type WatchUnit } from '../api'
import { ConnectionIcon } from '../connectionIcons'
import { providerName } from '../labels'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { useFollowUpCommand } from './commands'
import { CommandFeedback } from './CommandFeedback'
import { frequencyLabels, kindLabels, reasonText } from './labels'

function Units({ units }: { units: WatchUnit[] }) {
  const workIds = [...new Set(units.map(unit => unit.work_id ?? unit.unit_key))]
  return <div className="followup-preview-units">{workIds.map(workId => <div key={workId}>
    {units.find(unit => unit.work_id === workId) && <p>{t('Included work {id}', { id: workId })}</p>}
    {units.filter(unit => (unit.work_id ?? unit.unit_key) === workId).map(unit => <div key={unit.unit_key}>
      <span className="followup-provider"><ConnectionIcon id={unit.provider_id ?? 'openalex'} />{providerName(unit.provider_id ?? 'openalex')}</span>
      {unit.query_text && <p>{unit.query_text}</p>}{unit.status !== 'ready' && <p>{reasonText(unit.status)}</p>}
    </div>)}
  </div>)}</div>
}
export function ScheduleDialog({ researchId, scopeRevision, kind, watch, dark, active, reload, onClose }: {
  researchId: string; scopeRevision: number; kind: WatchKind; watch?: Watch; dark: boolean; active: boolean; reload: () => Promise<void>; onClose: () => void
}) {
  const [frequency, setFrequency] = useState<0 | 1 | 7 | 30>(watch?.mode === 'interval' ? watch.interval_days! : 0)
  const [catchUp, setCatchUp] = useState<boolean | null>(watch?.mode === 'interval' ? watch.catch_up : null)
  const [preview, setPreview] = useState<WatchPreview | null>(null)
  const [error, setError] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [opener] = useState(() => document.activeElement as HTMLElement | null)
  const command = useFollowUpCommand(watch ? `watch:${watch.id}:schedule` : `watch:${researchId}:${kind}:create`,
    saved => watch ? api.scheduleWatch(researchId, watch.id, saved.body, saved.key) : api.createWatch(researchId, saved.body, saved.key), reload, onClose)
  const needsPreview = !watch?.last_check
  const loadPreview = async () => {
    setPreviewing(true)
    try { setPreview(await api.previewWatch(researchId, kind)); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setPreviewing(false) }
  }
  useEffect(() => {
    if (!needsPreview) return
    let live = true
    api.previewWatch(researchId, kind).then(value => { if (live) setPreview(value) }, cause => { if (live) setError(cause instanceof Error ? cause.message : String(cause)) })
    return () => { live = false }
  }, [researchId, kind, needsPreview])
  const reason = command.locked ? t('Resolve the pending command before changing its settings.')
    : needsPreview && !preview ? t('Wait for the follow-up preview before starting.')
    : frequency && catchUp === null ? t('Choose Yes or No for catch-up on opening.')
    : !watch && active ? t('Finish or cancel the active research run first.') : ''
  const save = () => command.start({ mode: frequency ? 'interval' : 'manual', interval_days: frequency || null, catch_up: frequency ? catchUp : null,
    ...(watch ? { expected_schedule_version: watch.schedule_version } : { kind, expected_scope_revision: scopeRevision }) })
  return <Dialog.Root open onOpenChange={open => { if (!open) onClose() }}>
    <Dialog.Portal><Dialog.Backdrop className="confirm-dialog-backdrop" />
      <Dialog.Popup className={`followup-dialog ${dark ? 'dark' : ''}`} finalFocus={() => opener?.isConnected ? opener : true}>
        <Dialog.Title>{t(watch ? 'Schedule follow-up' : 'Enable follow-up')}</Dialog.Title>
        <Dialog.Description>{t(kindLabels[kind])}</Dialog.Description>
        <div className="followup-dialog-body">
          <p>{t('DEIXIS checks only while it is running.')}</p>
          {error && <Notice tone="error">{error} <Button variant="outline" disabled={previewing} onClick={() => { void loadPreview() }}>{t('Retry')}</Button></Notice>}
          {needsPreview && !preview && !error && <p role="status">{t('Loading follow-up…')}</p>}
          <Units units={watch?.last_check?.units ?? preview?.units ?? []} />
          {preview && <>
            {kind === 'citing_works' && <p>{t('{n} included works; {m} have no OpenAlex id and cannot be followed; at most {cap} OpenAlex ids are read per check and the rest roll to the next one', { n: preview.citing_works_count, m: preview.no_openalex_id, cap: preview.caps.citing_sources })}</p>}
            <p>{t('At most {pages} pages of {per_page} records per query, {requests} requests and {records} records per check.', { pages: preview.caps.pages, per_page: preview.caps.per_page, requests: preview.caps.max_provider_requests, records: preview.caps.max_records })}</p>
          </>}
          {!watch && <p>{t('The first check records the records returned within its page budget and announces none of them.')}</p>}
          <fieldset disabled={command.locked}><legend>{t('Frequency')}</legend>
            {([0, 1, 7, 30] as const).map(value => <label key={value}><input type="radio" name="followup-frequency" value={value} checked={frequency === value} onChange={() => { setFrequency(value); if (value !== frequency) setCatchUp(null) }} />{t(frequencyLabels[value])}</label>)}
          </fieldset>
          {frequency > 0 && <fieldset disabled={command.locked}><legend>{t('Catch-up on opening')}</legend>
            <p>{t('When DEIXIS opens after a missed due time, make one bounded check.')}</p>
            {[true, false].map(value => <label key={String(value)}><input type="radio" name="followup-catch-up" checked={catchUp === value} onChange={() => setCatchUp(value)} />{t(value ? 'Yes' : 'No')}</label>)}
          </fieldset>}
          {watch && <p>{t('A check already queued or running keeps its settings.')}</p>}
          <CommandFeedback command={command} />
          {reason && <p id="followup-save-reason" className="followup-muted">{reason}</p>}
        </div>
        <div className="followup-actions"><Button variant="outline" onClick={onClose}>{t('Cancel')}</Button><Button disabled={Boolean(reason)} aria-describedby={reason ? 'followup-save-reason' : undefined} onClick={save}>{t(watch ? 'Save' : 'Start')}</Button></div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>
}
