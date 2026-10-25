import { type ResearchSummary, type RunStatus } from '../lib/api'
import { runKindLabels, runStatusLabels, tableRunLabels } from '../lib/labels'
import { t } from '../lib/i18n'
import { TABLE_RUN_KINDS } from '../table/EvidenceTable'
import { CANDIDATE_KINDS } from '../candidate/CandidateRunLine'

const ACTIVE = new Set<RunStatus>(['queued', 'running', 'pause_requested'])
// PDF work has its own card under this slot (shell/BackgroundJobs.tsx).
const JOB_KINDS = new Set(['pdf_collection', 'pdf_ocr', 'fulltext_fetch', 'fulltext_adjudication'])

// The sidebar slot's live runs of the researches not on screen, from the research list (refreshed every few seconds), so a
// run's status stays in the sidebar on every page. The open research draws its own, richer lines (research/Topbar.tsx).
// A click opens the research at the panel that holds the run's controls.
export function SidebarRuns({ researches, openId, onOpen }: { researches: ResearchSummary[]; openId: string | null; onOpen: (id: string, tab?: string) => void }) {
  const live = researches.filter(r => r.id !== openId && r.last_run_kind && !JOB_KINDS.has(r.last_run_kind) && r.last_run_status && ACTIVE.has(r.last_run_status))
  return live.map(r => {
    const kind = r.last_run_kind!
    const tab = TABLE_RUN_KINDS.has(kind) ? 'table' : CANDIDATE_KINDS.has(kind) ? 'cands' : kind === 'watch_check' ? 'watch' : undefined
    const label = t(tableRunLabels[kind] ?? runKindLabels[kind])
    return <button key={r.id} type="button" className="runchip is-live sidebar-run" title={t('Open this research')} onClick={() => onOpen(r.id, tab)}>
      <span className="runchip-dot" aria-hidden />
      <span className="sidebar-run-text"><span className="runchip-text">{label}{r.last_run_status !== 'running' && ` · ${t(runStatusLabels[r.last_run_status!])}`}</span><small>{r.title}</small></span>
      <span className="runchip-sweep" aria-hidden />
    </button>
  })
}
