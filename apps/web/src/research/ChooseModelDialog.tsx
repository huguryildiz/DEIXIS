import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, ApiError, researchModelApi, type ModelRole, type ResearchView, type ReviewCard, type ReviewFocus, type ReviewTargetKind, type Run } from '../api'
import { ConfirmDialog } from '../ConfirmDialog'
import { connectionModels, modelKey, modelRoles, type ConnectionModel } from '../Home'
import { connectionName, reasoningLabel } from '../labels'
import { ReviewRequest } from '../review/ReviewRequest'
import '../review/review.css'
import { exposesEffortControl } from '../modelEffort'
import { useToast } from '../Toast'
import { t } from '../i18n'

// "Choose another model" on the model-down notice (R20; F10, UI parity S27). A model that did not answer is never
// replaced by the app; this is the person's explicit choice, recorded with the research (`research_model_changes`) and
// shown on the notice. Only steps that run after the change use the new model: finished steps keep the model they ran
// on, and nothing is sent until the person retries the stopped step. The toast reports the change the server returned.

// `review`: the run is a review by another model, which keeps the model it was requested with (flow._owner_review), so a
// role change would not move it; the dialog then starts a new review of the same target on the chosen model instead.
export type ChooseModelTarget = { run: Run; role: ModelRole; opener: HTMLElement | null; review?: { card: ReviewCard; kind: ReviewTargetKind } }

// The owner keys the dialog by the target's run, so a new target starts the form afresh.
// `onReviewStarted` gets the new review's run, so the page announces it once (here) and not again as a run that started.
export function ChooseModelDialog({ target, view, dark, onClose, onChanged, onReload, onReviewStarted }: {
  target: ChooseModelTarget | null; view: ResearchView; dark: boolean; onClose: () => void; onChanged: (view: ResearchView) => void
  onReload: () => Promise<unknown>; onReviewStarted: (runId: string) => Promise<unknown>
}) {
  if (target?.review) return <ReviewAgainDialog target={target} review={target.review} view={view} dark={dark} onClose={onClose} onStarted={onReviewStarted} />
  return <RoleModelDialog target={target} view={view} dark={dark} onClose={onClose} onChanged={onChanged} onReload={onReload} />
}

function RoleModelDialog({ target, view, dark, onClose, onChanged, onReload }: {
  target: ChooseModelTarget | null; view: ResearchView; dark: boolean; onClose: () => void; onChanged: (view: ResearchView) => void
  onReload: () => Promise<unknown>
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
      if (e instanceof ApiError && e.status === 409) {
        // The research moved on (another tab, a run started): read it again before saying the page shows it.
        const reloaded = await onReload().then(() => true, () => false)
        toast('warning', reloaded ? t('Not changed: {message}. The page now shows the latest state.', { message: e.message })
          : t('Not changed: {message}. The latest state could not be read; reload the page.', { message: e.message }))
      } else toast('error', e instanceof Error ? e.message : String(e))
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

// A stopped review by another model, asked again on another model (S27, Sol r1): the review request flow (Preview, then
// Start review) for the same target, with the stopped review's focus and note filled in. A new review is started and
// versioned beside the stopped one, which keeps its requested model; nothing about the stopped review is changed.
function ReviewAgainDialog({ target, review, view, dark, onClose, onStarted }: {
  target: ChooseModelTarget; review: { card: ReviewCard; kind: ReviewTargetKind }; view: ResearchView; dark: boolean
  onClose: () => void; onStarted: (runId: string) => Promise<unknown>
}) {
  const toast = useToast()
  const rid = view.research.id
  const [request, setRequest] = useState<{ kind: ReviewTargetKind; id: string; version: number; focus: ReviewFocus; owner_note: string | null } | null>(null)
  const [failed, setFailed] = useState('')
  useEffect(() => {
    let live = true
    api.review(rid, review.card.id).then(async detail => {
      const { target_kind: kind, target_id: id } = detail.snapshot
      // The version the request names is the target's as it is now, which is what a new review reads.
      const version = kind === 'answer' ? view.answers.find(a => a.id === id)?.report_version ?? detail.snapshot.report_version ?? 0
        : kind === 'candidate' ? detail.snapshot.candidate_version ?? 0
        : (await api.report(rid, id)).report_version ?? 0
      if (live) setRequest({ kind, id, version, focus: detail.focus, owner_note: detail.owner_note })
    }).catch(e => { if (live) setFailed(e instanceof Error ? e.message : String(e)) })
    return () => { live = false }
  }, [rid, review.card.id, view.answers])
  const close = () => { onClose(); target.opener?.focus() }
  const started = async (id: string) => {
    onClose()
    const card = await api.review(rid, id).catch(() => null)
    if (card) await onStarted(card.run_id)
    toast('success', card ? t('A new review started on {model}. The stopped review keeps {old} and stays as it was.', { model: card.requested_model.model, old: review.card.requested_model.model })
      : t('A new review started. The stopped review keeps its model and stays as it was.'))
  }
  return <Dialog open onOpenChange={next => { if (!next) close() }}>
    <DialogContent className={`review-dialog${dark ? ' dark' : ''}`} icon={<ShieldCheck size={16} aria-hidden />} title={t('Review again with another model')}>
      {request ? <ReviewRequest researchId={rid} targetKind={request.kind} targetId={request.id} version={request.version} initial={request}
        runActive={view.runs.some(r => ['queued', 'running', 'pause_requested'].includes(r.status))} sectionLabel={ref => ref}
        lead={<p className="foot-note review-again-lead">{t('This review keeps the model it was requested with ({model}); Retry sends it there again. Start review begins a new review of the same target on the model you choose, with the same focus and note; the stopped review stays as it is.', { model: review.card.requested_model.model })}</p>}
        started={started} cancel={close} />
        : <p className="choose-model-note review-again-wait" role={failed ? 'alert' : 'status'}>{failed ? t('The stopped review could not be read: {error}', { error: failed }) : t('Reading the stopped review…')}</p>}
    </DialogContent>
  </Dialog>
}
