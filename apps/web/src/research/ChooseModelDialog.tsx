import { useEffect, useState } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, ApiError, researchModelApi, type ModelRole, type ResearchView, type Run } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { connectionModels, modelKey, modelRoles, type ConnectionModel } from '../Home'
import { connectionName, reasoningLabel } from '../labels'
import { exposesEffortControl } from '../modelEffort'
import { useToast } from '../Toast'
import { t } from '../i18n'

// "Choose another model" on the model-down notice (R20; F10, UI parity S27). A model that did not answer is never
// replaced by the app; this is the person's explicit choice, recorded with the research (`research_model_changes`) and
// shown on the notice. Only steps that run after the change use the new model: finished steps keep the model they ran
// on, and nothing is sent until the person retries the stopped step. The toast reports the change the server returned.

export type ChooseModelTarget = { run: Run; role: ModelRole; opener: HTMLElement | null }

// The owner keys the dialog by the target's run, so a new target starts the form afresh.
export function ChooseModelDialog({ target, view, dark, onClose, onChanged }: {
  target: ChooseModelTarget | null; view: ResearchView; dark: boolean; onClose: () => void; onChanged: (view: ResearchView) => void
}) {
  const toast = useToast()
  const [models, setModels] = useState<ConnectionModel[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [role, setRole] = useState<ModelRole>(target?.role ?? 'literature')
  const [choice, setChoice] = useState('')
  const [effort, setEffort] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const open = Boolean(target)
  useEffect(() => {
    if (!open) return
    let live = true
    api.connections().then(next => { if (live) setModels(connectionModels(next).filter(m => next.models[m.connection]?.ready)) }, () => { if (live) setFailed(true) })
    return () => { live = false }
  }, [open])
  const chosen = models?.find(m => m.id === choice)
  const efforts = chosen && exposesEffortControl(chosen) ? chosen.reasoning_efforts ?? [] : []
  const close = () => { if (!busy) { onClose(); target?.opener?.focus() } }
  const save = async () => {
    if (!target || !chosen) return
    setBusy(true)
    try {
      const next = await researchModelApi.changeModel(view.research.id, { role, connection: chosen.connection, model: chosen.model, reasoning_effort: effort,
        reason: target.run.pause_reason ?? undefined, expected_version: view.research.version })
      const change = next.model_changes.at(-1)
      onChanged(next)
      onClose()
      toast('success', change
        ? t('{role} model changed from {from} to {to} for this research. Steps that run from now on use it; finished steps keep the model they ran on. Retry the step to send it.', {
          role: t(modelRoles[change.role].label), from: change.from.model ?? t('none'), to: change.to.model ?? '' })
        : t('The model change was saved.'))
    } catch (e) {
      toast(e instanceof ApiError && e.status === 409 ? 'warning' : 'error', e instanceof ApiError && e.status === 409
        ? t('Not changed: {message}. The page now shows the latest state.', { message: e.message }) : e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  return <ConfirmDialog open={open} dark={dark} neutral busy={busy} title={t('Choose another model')}
    description={t('The stopped step and the steps after it use the model you choose. Steps that already finished keep the model they ran on, and nothing is sent until you retry the step.')}
    confirmLabel={t('Use this model')} cancelLabel={t('Cancel')} confirmDisabled={!chosen} onConfirm={() => { if (chosen) void save() }} onOpenChange={next => { if (!next) close() }}>
    <div className="choose-model">
      <label className="choose-model-row"><span>{t('Role')}</span>
        <Select value={role} onValueChange={value => { if (value) setRole(value as ModelRole) }}>
          <SelectTrigger aria-label={t('Role')}><SelectValue>{(value: string) => t(modelRoles[value as ModelRole].label)}</SelectValue></SelectTrigger>
          <SelectContent align="start" alignItemWithTrigger={false}>
            {(Object.keys(modelRoles) as ModelRole[]).map(r => <SelectItem key={r} value={r}>{t(modelRoles[r].label)}</SelectItem>)}
          </SelectContent>
        </Select>
      </label>
      <label className="choose-model-row"><span>{t('Model')}</span>
        {models === null ? <span className="choose-model-note">{failed ? t('The model connections could not be read.') : t('Reading the model connections…')}</span>
          : !models.length ? <span className="choose-model-note">{t('No connected model is ready.')}</span>
          : <Select value={choice || null} onValueChange={value => { if (value) { setChoice(value as string); setEffort(null) } }}>
            <SelectTrigger aria-label={t('Model')}><SelectValue placeholder={t('Choose a model')}>{(value: string) => { const m = models.find(x => x.id === value); return m ? `${connectionName(m.connection)} · ${m.display_name}` : t('Choose a model') }}</SelectValue></SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
              {models.map(m => <SelectItem key={modelKey(m.connection, m.model)} value={m.id}>{connectionName(m.connection)} · {m.display_name}</SelectItem>)}
            </SelectContent>
          </Select>}
      </label>
      {efforts.length > 0 && <label className="choose-model-row"><span>{t('Reasoning effort')}</span>
        <Select value={effort ?? '__provider_default'} onValueChange={value => { if (value) setEffort(value === '__provider_default' ? null : value as string) }}>
          <SelectTrigger aria-label={t('Reasoning effort')}><SelectValue>{(value: string) => value === '__provider_default' ? t('Provider default') : reasoningLabel(value)}</SelectValue></SelectTrigger>
          <SelectContent align="start" alignItemWithTrigger={false}>
            <SelectItem value="__provider_default">{t('Provider default')}</SelectItem>
            {efforts.map(e => <SelectItem key={e.id} value={e.id}>{reasoningLabel(e.id)}</SelectItem>)}
          </SelectContent>
        </Select>
      </label>}
    </div>
  </ConfirmDialog>
}
