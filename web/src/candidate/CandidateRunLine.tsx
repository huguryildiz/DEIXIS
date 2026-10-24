import { Pause, Play, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import type { CandidateMatrix, CandidateRunRef, Run } from '../api'
import { pauseReasonText, runKindLabels, runStatusLabels, stepLabel } from '../labels'
import { ModelName } from '../ModelName'
import type { ModelText } from '../modelText'
import { t } from '../i18n'
import { label, stepStateLabels, runReasonLabels } from './labels'
import { QueryList } from './SearchMatrix'

export const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
export const CANDIDATE_KINDS = new Set(['claim_decomposition', 'kill_search'])
export function CandidateRunLine({ run, fullRun, matrix, busy, connection, model, modelText, onControl }: {
  run: CandidateRunRef; fullRun?: Run; matrix?: CandidateMatrix | null; busy: boolean; connection: string; model: string
  modelText: ModelText; onControl: (run: CandidateRunRef, action: 'pause' | 'resume' | 'cancel', opener: HTMLElement) => void
}) {
  const line = useRef<HTMLElement>(null)
  const focusedControl = useRef<HTMLElement | null>(null)
  useEffect(() => {
    // A later run refresh can remove the control after the mutation itself has returned.
    if (focusedControl.current && !focusedControl.current.isConnected && document.activeElement === document.body) {
      const next = line.current?.querySelector<HTMLElement>('[data-run-action="resume"], [data-run-action="pause"], [data-run-action="cancel"]') ?? line.current
      next?.focus({ preventScroll: true }); focusedControl.current = next
    }
  }, [run.status])
  const controllable = ACTIVE.has(run.status) || run.status === 'paused'
  const frozenModels = matrix?.search.selection.model ?? fullRun?.target?.model
  return <section ref={line} tabIndex={-1} data-candidate-run={run.id} className="candidate-run" aria-label={t(runKindLabels[run.kind])} onFocusCapture={e => { focusedControl.current = e.target as HTMLElement }} onBlurCapture={e => { if (e.relatedTarget instanceof Node && !e.currentTarget.contains(e.relatedTarget)) focusedControl.current = null }}>
    <div className="candidate-actions" role="status"><strong>{t(runKindLabels[run.kind])}</strong><span>{t(runStatusLabels[run.status])}</span>{run.kind === 'claim_decomposition' && <ModelName connection={connection} text={model} />}
      {controllable && <><Button data-run-action="cancel" variant="ghost" size="sm" disabled={busy} focusableWhenDisabled aria-describedby={busy ? 'candidate-working' : undefined} onClick={e => onControl(run, 'cancel', e.currentTarget)}><X size={13} aria-hidden />{t('Cancel')}</Button>
        {(run.status === 'queued' || run.status === 'running') && <Button data-run-action="pause" variant="ghost" size="sm" disabled={busy} focusableWhenDisabled aria-describedby={busy ? 'candidate-working' : undefined} onClick={e => onControl(run, 'pause', e.currentTarget)}><Pause size={13} aria-hidden />{t('Pause')}</Button>}
        {run.status === 'paused' && <Button data-run-action="resume" variant="ghost" size="sm" disabled={busy} focusableWhenDisabled aria-describedby={busy ? 'candidate-working' : undefined} onClick={e => onControl(run, 'resume', e.currentTarget)}><Play size={13} aria-hidden />{t('Resume')}</Button>}</>}
    </div>
    {run.kind === 'kill_search' && (frozenModels ? <ul>{(['kill_search_query', 'claim_assessment'] as const).map(task => <li key={task}>{t(task === 'kill_search_query' ? 'Search terms (model)' : 'Claim assessment (model)')} · <ModelName connection={frozenModels[task][0]} text={modelText(frozenModels[task][1], frozenModels[task][2])} /></li>)}</ul> : <p>{t('Model details are unavailable in these run views.')}</p>)}
    {run.pause_reason && <p>{run.status === 'failed' ? label(runReasonLabels, run.pause_reason) : pauseReasonText(run.pause_reason)}</p>}{run.error_code && <p>{t('Run failure:')} {label(runReasonLabels, run.error_code)}</p>}
    <ol className="candidate-timeline">{run.kind === 'claim_decomposition' ? <li>{t('Claim breakdown (model)')}</li> : <><li>{t('Search terms (model)')}</li><li>{t('Provider searches')}{matrix && <QueryList matrix={matrix} />}</li>{matrix && <li>{t('Assessment: {n} of {k} works assessed', { n: matrix.summary?.hits.filter(h => h.outcome === 'assessed').length ?? matrix.hits.filter(h => h.assessment_state === 'assessed').length, k: matrix.hits.length })}</li>}</>}</ol>
    {fullRun?.steps && <details><summary>{t('Recorded steps')} · {fullRun.steps.length}</summary>{fullRun.steps.length ? <ol>{fullRun.steps.map(step => <li key={step.id}>{stepLabel(step.kind, step.operation_key, true)} · {label(stepStateLabels, step.status)}{step.error_code && <> · {label(runReasonLabels, step.error_code)}</>}</li>)}</ol> : <p>{t('None.')}</p>}</details>}
  </section>
}
