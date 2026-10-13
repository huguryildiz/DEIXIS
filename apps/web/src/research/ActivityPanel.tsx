import { useEffect, useState } from 'react'
import { api, type ActivityEvent, type ActivityRun } from '../api'
import { effortLabels } from '../Home'
import { runKindLabels, runStatusLabels } from '../labels'
import { t, uiLocale } from '../i18n'
import { ActivityLog } from './ActivityLog'

// The Activity panel (UI parity S14, P34; mockup `activity()`): one row per run of the research with its status, how
// long it took, its model calls and when it started, then the recorded events under it (§2.2). Every value comes from a
// stored row (api/activity_routes.py): a time with no event behind it reads "not started" or "not finished", never 0,
// and "Took" is the wall time from the run's first start to its end, pauses included.

const STATUS_TONE: Record<ActivityRun['status'], 'ok' | 'run' | 'warn' | 'no'> = {
  completed: 'ok', running: 'run', queued: 'no', pause_requested: 'warn', paused: 'warn', failed: 'warn', cancelled: 'no',
}
const MODES: Record<string, keyof typeof effortLabels> = { quick: 'quick', standard: 'standard', deep: 'detailed' }

function took(run: ActivityRun): string {
  if (!run.started_at) return t('not started')
  if (!run.finished_at) return run.status === 'paused' ? t('paused') : t('not finished')
  const seconds = Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000))
  if (seconds < 60) return t('{s} s', { s: seconds })
  return t('{m} min {s} s', { m: Math.floor(seconds / 60), s: String(seconds % 60).padStart(2, '0') })
}

const when = (iso: string) => new Date(iso).toLocaleString(uiLocale(), { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export function ActivityPanel({ researchId, eventCursor, events }: { researchId: string; eventCursor: number; events: ActivityEvent[] }) {
  const [runs, setRuns] = useState<ActivityRun[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    api.activityRuns(researchId).then(next => { if (live) { setRuns(next.runs); setError('') } }, e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    return () => { live = false }
  }, [researchId, eventCursor])
  return <div className="activity-runs">
    {error && !runs ? <p className="empty-inline" role="alert">{t('Could not load the runs: {error}', { error })}</p>
      : !runs ? <p className="empty-inline" role="status">{t('Loading the runs…')}</p>
      : <>
        {/* A refresh that failed after the table loaded: the table stays, marked as the last one read. */}
        {error && <p className="activity-refresh-error" role="alert">{t('Could not refresh the runs: {error}. The table shows them as last read.', { error })}</p>}
        <div className="tbl-wrap"><table className="activity-table">
          <thead><tr><th>{t('Run')}</th><th>{t('Status')}</th><th>{t('Took')}</th><th>{t('Model calls')}</th><th>{t('Started')}</th></tr></thead>
          <tbody>{runs.map(run => {
            const name = run.kind === 'answer' && run.report_version ? `${t('Answer')} V${run.report_version}` : t(runKindLabels[run.kind] ?? run.kind)
            const mode = run.mode ? MODES[run.mode] : undefined
            const detail = [mode && t('{effort} depth', { effort: t(effortLabels[mode]) }), t('question revision {n}', { n: run.scope_revision })].filter(Boolean).join(' · ')
            return <tr key={run.id}>
              <td className="activity-run"><b>{name}</b><div className="src-m">{detail}</div></td>
              <td><span className={`status ${STATUS_TONE[run.status]}`}>{t(runStatusLabels[run.status])}</span></td>
              <td className="tnum">{took(run)}</td>
              <td className="tnum">{run.model_calls.toLocaleString(uiLocale())}</td>
              <td className="activity-started">{run.started_at ? when(run.started_at) : t('not started')}</td>
            </tr>
          })}</tbody>
        </table></div>
        {!runs.length && <p className="empty-inline">{t('No run is recorded yet.')}</p>}
        <p className="foot-note">{t('Every step is stored. A paused or interrupted run resumes without repeating model calls that already finished. Took runs from a run’s first start to its end, pauses included.')}</p>
      </>}
    <ActivityLog events={events} />
  </div>
}
