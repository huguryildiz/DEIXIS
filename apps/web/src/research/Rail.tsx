import { useEffect, useState, type ReactNode } from 'react'
import { AlignLeft, Clock, Copy, File, Lightbulb, ListChecks, Table2, type LucideIcon } from 'lucide-react'
import { api, type Answer, type QueueRow, type ResearchView, type Run, type TableSummary } from '../api'
import { collectionProgress } from '../BackgroundJobs'
import { queueKindLabels } from '../labels'
import { t } from '../i18n'
import { useRailWide } from './railData'

// The artifacts rail (mockup `rail()`, RL1-RL7): 300px beside the thread from 1100px, gone while a panel is open (the
// page hides it, it stays mounted so the button that opened a panel takes focus back). Every number comes from the view
// the page already holds, or from the queue list for the amber box. RL8 (the Usage box) is S27's.

// Until the Funnel panel exists (S14) the funnel box opens the Sources panel, which holds the flow counts and the search report.
const FUNNEL_PANEL = 'sources'
// The queue rows listed in the amber box; the rest are one click away in the panel.
const QUEUE_ROWS = 8

type OpenPanel = (name: string, options?: { opener?: HTMLElement | null }) => void

const number = (n: number) => n.toLocaleString()

function Box({ id, title, action, warn, children }: { id?: string; title: string; action?: { label: string; name: string; onClick: (opener: HTMLElement) => void }; warn?: boolean; children: ReactNode }) {
  return <div className={`box${warn ? ' warnbox' : ''}`}>
    <h5><span id={id}>{title}</span>{action && <button type="button" aria-label={t('Open {name}', { name: action.name })} onClick={e => action.onClick(e.currentTarget)}>{action.label}</button>}</h5>
    {children}
  </div>
}

function Row({ icon: Icon, label, aside, ariaLabel, onClick }: { icon: LucideIcon; label: string; aside?: string; ariaLabel?: string; onClick: (opener: HTMLElement) => void }) {
  return <button type="button" className="li" aria-label={ariaLabel} title={ariaLabel} onClick={e => onClick(e.currentTarget)}>
    <Icon size={16} strokeWidth={1.6} aria-hidden /><span>{label}</span>{aside && <em>{aside}</em>}
  </button>
}

type Reports = { answer: Answer; version: number; title: string }[]

export function Rail({ view, researchId, reports, tables, hidden, candidateCount, followupCount, openPanel, onOpenReport, onOpenEvidenceReport, onOpenTable }: {
  view: ResearchView; researchId: string; reports: Reports; tables: TableSummary[] | null; hidden: boolean
  candidateCount: number | null; followupCount: number | null; openPanel: OpenPanel
  onOpenReport: (answerId: string) => void; onOpenEvidenceReport: (reportId: string) => void; onOpenTable: (tableId: string) => void
}) {
  const counts = view.counts
  const wide = useRailWide()
  const off = hidden || !wide
  const queueCount = (counts.queue ?? 0) + (counts.look_again ?? 0)
  const waitingCount = counts.waiting_for_pdf ?? 0
  const open = (name: string) => (opener: HTMLElement) => openPanel(name, { opener })

  // The amber box lists the queue's rows. The list is read again on every recorded event while the rail shows.
  const [queue, setQueue] = useState<{ research: string; rows: QueueRow[] } | null>(null)
  useEffect(() => {
    if (off || queueCount === 0) return
    let live = true
    api.queue(researchId).then(next => { if (live) setQueue({ research: researchId, rows: next.rows }) }, () => { /* the box keeps its last rows */ })
    return () => { live = false }
  }, [researchId, off, queueCount, view.last_event_id])
  // An emptied queue shows none of the rows read before it emptied, also while works wait for a PDF.
  const queueRows = queueCount > 0 && queue?.research === researchId ? queue.rows : []

  const artifactCount = reports.length + view.reportRuns.length + (tables?.length ?? 0)
  const funnel = counts.funnel
  // Reading depth is what the newest report's answer was given (its stored input), in works: a PDF or a list edit after
  // it does not rewrite it, and a file not read yet was not given.
  const depth = reports[0]?.answer.inputs_given?.depth ?? { pdf: 0, abstract: 0, metadata: 0 }
  const depthTotal = depth.pdf + depth.abstract + depth.metadata
  const runCount = view.run_total ?? view.runs.length
  const collecting = view.runs.find((r: Run) => r.kind === 'pdf_collection' && ['queued', 'running', 'pause_requested', 'paused'].includes(r.status))
  const collection = collecting ? collectionProgress(view, collecting.steps ?? []) : null

  // The mockup's "Found" bar shows unique works (duplicates merged), so it is named so; rows found stay in the Funnel
  // panel. "Full text read" counts each work once over every run of this question; the reading step counts one run.
  const bars: [string, number, string?][] = funnel ? [
    ['Unique works', funnel.unique], ['Abstract read', funnel.abstracts_read], ['Passed the abstract stage', funnel.candidates],
    ['Full text read', counts.fulltext_read_works ?? 0, 'Works whose two full-text passes both stored a result in one run, over every run of this question'],
    ['Cited', counts.cited],
  ] : []
  const widest = Math.max(1, ...bars.map(([, n]) => n))

  return <aside className="rail research-rail" aria-labelledby="rail-artifacts-title" hidden={off}>
    <div className="box">
      <h5><span id="rail-artifacts-title">{t('Artifacts')} ({artifactCount})</span></h5>
      {artifactCount === 0
        ? <span className="rail-empty">{t('The report appears here when it is written.')}</span>
        : <>
          {reports.map(({ answer, version, title }) => <Row key={answer.id} icon={AlignLeft} label={title}
            aside={`V${version}${answer.applicability !== 'current' || answer.late_revision_status?.status === 'published' ? ` · ${t('earlier')}` : ''}`} onClick={() => onOpenReport(answer.id)} />)}
          {tables?.map(table => {
            const label = t('Evidence table · {sources} · {columns}', {
              sources: t(table.rows === 1 ? '{n} source' : '{n} sources', { n: table.rows }), columns: t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns }) })
            return <Row key={table.id} icon={Table2} label={label} ariaLabel={`${label} · ${table.title}`} onClick={() => onOpenTable(table.id)} />
          })}
          {view.reportRuns.map(item => <Row key={item.id} icon={AlignLeft} label={t('Evidence report')}
            aside={item.status === 'valid' ? `V${item.report_version ?? ''}` : t(item.status === 'draft' ? 'draft' : 'being written')} onClick={() => onOpenEvidenceReport(item.id)} />)}
        </>}
    </div>

    {(queueCount > 0 || waitingCount > 0) && <Box warn title={t('Waiting for your decision')} action={{ label: t('Open'), name: t('Waiting for your decision'), onClick: open(queueCount > 0 ? 'queue' : 'pdfs') }}>
      {queueRows.slice(0, QUEUE_ROWS).map(row => <Row key={row.row_token} icon={row.kind === 'confirm_pdf' ? File : row.kind === 'choose_version' ? Copy : ListChecks}
        label={row.title} aside={row.kind === 'look_again' ? t('Look again') : t(queueKindLabels[row.kind])} onClick={open('queue')} />)}
      {queueCount > Math.min(QUEUE_ROWS, queueRows.length) && <Row icon={ListChecks} label={t('{n} waiting for you', { n: queueCount })} onClick={open('queue')} />}
      {waitingCount > 0 && <Row icon={File} label={t('{n} waiting for a PDF', { n: waitingCount })} aside={t('PDF')} onClick={open('pdfs')} />}
    </Box>}

    {funnel && <Box title={t('From search to answer')} action={{ label: t('Open'), name: t('From search to answer'), onClick: open(FUNNEL_PANEL) }}>
      <div className="fun">{bars.map(([label, n, hint]) => <button key={label} type="button" title={hint && t(hint)} onClick={e => openPanel(FUNNEL_PANEL, { opener: e.currentTarget })}>
        <span>{t(label)}</span><i style={{ width: `${Math.max(2, Math.round(Math.sqrt(n / widest) * 100))}%` }} aria-hidden /><b className="tnum rail-data">{number(n)}</b>
      </button>)}</div>
    </Box>}

    {reports.length > 0 && depthTotal > 0 && <Box title={t('How deeply sources were read')} action={{ label: t('Open'), name: t('How deeply sources were read'), onClick: open('pdfs') }}>
      {/* Its scope: the works the newest report's answer was given, which after a question change belong to an earlier revision. */}
      <p className="rail-scope">{t('Works given to the latest report (V{n})', { n: reports[0].version })}{reports[0].answer.scope_revision !== view.research.current_scope_revision ? ` · ${t('question revision {n}', { n: reports[0].answer.scope_revision })}` : ''}</p>
      <div className="bar" aria-hidden>
        <i style={{ width: `${depth.pdf / depthTotal * 100}%`, background: 'var(--attr-text)' }} />
        <i style={{ width: `${depth.abstract / depthTotal * 100}%`, background: 'var(--attr-abstract)' }} />
        <i style={{ width: `${depth.metadata / depthTotal * 100}%`, background: 'var(--line)' }} />
      </div>
      <div className="legend">
        <span><i style={{ background: 'var(--attr-text)' }} />{t('PDF text')} <span className="rail-data">{number(depth.pdf)}</span></span>
        <span><i style={{ background: 'var(--attr-abstract)' }} />{t('Abstract only')} <span className="rail-data">{number(depth.abstract)}</span></span>
        {depth.metadata > 0 && <span><i style={{ background: 'var(--line)' }} />{t('Metadata only')} <span className="rail-data">{number(depth.metadata)}</span></span>}
      </div>
    </Box>}

    {collection && collection.total > 0 && <Box title={t('In the background')}>
      {/* A paused collection is named as paused (as the jobs sheet does), not as collecting. */}
      <div className="kv"><span>{t(collecting?.status === 'paused' ? 'PDF collection paused' : 'Collecting PDFs')}</span><span className="tnum rail-data">{number(collection.inHand)} / {number(collection.total)}</span></div>
      <div className="bar" aria-hidden><i style={{ width: `${collection.inHand / collection.total * 100}%`, background: collecting?.status === 'paused' ? 'var(--muted)' : 'var(--accent)' }} /></div>
    </Box>}

    <Box title={t('Run')}>
      <Row icon={Clock} label={t('Activity')} aside={t(runCount === 1 ? '{n} run' : '{n} runs', { n: runCount })} onClick={open('activity')} />
      <Row icon={Lightbulb} label={t('Candidates')} aside={candidateCount === null ? undefined : String(candidateCount)} onClick={open('cands')} />
      <Row icon={Clock} label={t('Follow-up')} aside={followupCount === null ? undefined : t('{n} new', { n: followupCount })} onClick={open('watch')} />
    </Box>
  </aside>
}
