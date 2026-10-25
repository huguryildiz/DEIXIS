import { useEffect, useState, type ReactNode } from 'react'
import { Check, ChevronDown, ChevronRight, Clock, Copy, File, FileText, Lightbulb, ListChecks, MessageSquareQuote, Table2, type LucideIcon } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, type Answer, type QueueRow, type ResearchView, type Run, type TableSummary } from '../lib/api'
import { collectionProgress } from '../shell/BackgroundJobs'
import { LATE_REVISION_LABEL, queueKindLabels, researchHeading, runKindLabels, tableTitle } from '../lib/labels'
import { t, uiLocale } from '../lib/i18n'
import { useRailWide } from './railData'
import { budgetAsOf, budgetFigure, prepaidFigure, useOpenAlexBudget, usageRun } from './usageData'

// The artifacts rail (mockup `rail()`, RL1-RL7): 300px beside the thread from 1100px, gone while a panel is open (the
// page hides it, it stays mounted so the button that opened a panel takes focus back). Every number comes from the view
// the page already holds, or from the queue list for the amber box. The Usage box (RL8, S27) reads the newest run with a
// model-call limit and OpenAlex's budget today as its last stored response says it, with that response's time.

// The funnel box and its bars open the Search funnel panel (S14, P41).
const FUNNEL_PANEL = 'funnel'
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

function Row({ icon: Icon, label, aside, ariaLabel, tile = false, onClick }: { icon: LucideIcon; label: ReactNode; aside?: string; ariaLabel?: string; tile?: boolean; onClick: (opener: HTMLElement) => void }) {
  return <button type="button" className={`li${tile ? ' li-tile' : ''}`} aria-label={ariaLabel} title={ariaLabel} onClick={e => onClick(e.currentTarget)}>
    {tile ? <span className="li-ico" aria-hidden><Icon size={15} strokeWidth={1.7} /></span> : <Icon size={16} strokeWidth={1.6} aria-hidden />}
    <span>{label}</span>{aside && <em>{aside}</em>}{tile && <ChevronRight size={15} className="li-go" aria-hidden />}
  </button>
}

// A count at the head of a row label ("19 waiting for a PDF"), set in the figure weight; the sentence stays one string.
const leadNumber = (text: string) => { const m = text.match(/^(\d[\d.,]*)(\s.*)$/); return m ? <><b className="tnum">{m[1]}</b>{m[2]}</> : text }

type Version = { id: string; tag: string; note?: string; at: string }

const when = (iso: string) => new Date(iso).toLocaleString(uiLocale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

// One artifact, however many versions it has: the row opens the newest (versions[0]); the version chip lists every
// version, newest first, and opens the one picked. A single version shows its tag without a menu.
function VersionedRow({ icon: Icon, label, ariaLabel, versions, onOpen }: { icon: LucideIcon; label: string; ariaLabel?: string; versions: Version[]; onOpen: (id: string) => void }) {
  const [latest] = versions
  return <div className="li vrow">
    <button type="button" className="vrow-main" aria-label={ariaLabel} title={ariaLabel} onClick={() => onOpen(latest.id)}>
      <Icon size={16} strokeWidth={1.6} aria-hidden /><span>{label}</span>
    </button>
    {versions.length === 1
      ? <em>{latest.tag}</em>
      : <DropdownMenu>
        <DropdownMenuTrigger render={<button type="button" className="vchip" aria-label={t('Versions of {name}', { name: ariaLabel ?? label })} />}>
          {latest.tag}<ChevronDown size={12} strokeWidth={2} aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" sideOffset={6} className="rail-versions">
          <DropdownMenuGroup>
          <DropdownMenuLabel>{t('{n} versions', { n: versions.length })}</DropdownMenuLabel>
          {versions.map((v, i) => <DropdownMenuItem key={v.id} onClick={() => onOpen(v.id)}>
            <b className="tnum">{v.tag}</b>
            <span>{i === 0 ? t('latest') : v.note ?? ''}{(i === 0 || v.note) && ' · '}<time dateTime={v.at}>{when(v.at)}</time></span>
            {i === 0 && <Check size={14} aria-hidden />}
          </DropdownMenuItem>)}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>}
  </div>
}

type Reports = { answer: Answer; version: number; title: string }[]

export function Rail({ view, researchId, cited, reports, tables, hidden, candidateCount, followupCount, openPanel, onOpenReport, onOpenEvidenceReport, onOpenTable }: {
  view: ResearchView; researchId: string; cited: number; reports: Reports; tables: TableSummary[] | null; hidden: boolean
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

  // Tables with one title are one artifact in versions, oldest V1; the evidence reports are one artifact too.
  const byTitle = new Map<string, TableSummary[]>()
  for (const table of [...(tables ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))) byTitle.set(table.title, [...(byTitle.get(table.title) ?? []), table])
  const tableGroups = [...byTitle.values()]
  // The study table a running answer opens when it ends: shown as coming, not counted until it exists.
  const pending = view.study_table_pending
  const artifactCount = (reports.length > 0 ? 1 : 0) + tableGroups.length + (view.reportRuns.length > 0 ? 1 : 0)
  const funnel = counts.funnel
  // Reading depth is what the newest report's answer was given (its stored input), in works: a PDF or a list edit after
  // it does not rewrite it, and a file not read yet was not given.
  const depth = reports[0]?.answer.inputs_given?.depth ?? { pdf: 0, abstract: 0, metadata: 0 }
  const depthTotal = depth.pdf + depth.abstract + depth.metadata
  const runCount = view.run_total ?? view.runs.length
  const collecting = view.runs.find((r: Run) => r.kind === 'pdf_collection' && ['queued', 'running', 'pause_requested', 'paused'].includes(r.status))
  const collection = collecting ? collectionProgress(view, collecting.steps ?? []) : null
  // Usage (RL8): the run's calls are `usage.model_calls`, which the store counts in the same write as each stored model
  // session (store.start_model_session), so it is the run's Usage box total; the limit is the run's frozen budget.
  const callsRun = usageRun(view.runs)
  const calls = callsRun?.usage.model_calls ?? 0
  const callLimit = callsRun?.budget.max_model_calls ?? 0
  const budget = useOpenAlexBudget(!off, view.last_event_id)
  const budgetValue = budget.value
  const budgetText = budgetValue ? budgetFigure(budgetValue) : null
  const prepaidText = budgetValue ? prepaidFigure(budgetValue) : null
  const used = budgetValue?.used_fraction ?? null

  // The mockup's "Found" bar shows unique works (duplicates merged), so it is named so; rows found stay in the Funnel
  // panel. "Full text read" counts each work once over every run of this question; the reading step counts one run.
  // "Cited" counts the works the answer shown in the thread cites (`cited`), as the facts strip does.
  const bars: [string, number, string?][] = funnel ? [
    ['Unique works', funnel.unique], ['Abstract read', funnel.abstracts_read], ['Passed the abstract stage', funnel.candidates],
    ['Full text read', counts.fulltext_read_works ?? 0, 'Works whose two full-text passes both stored a result in one run, over every run of this question'],
    ['Cited', cited],
  ] : []
  const widest = Math.max(1, ...bars.map(([, n]) => n))

  return <aside className="rail research-rail" aria-labelledby="rail-artifacts-title" hidden={off}>
    <div className="box">
      <h5><span id="rail-artifacts-title">{t('Artifacts')} ({artifactCount})</span></h5>
      {artifactCount === 0 && !pending
        ? <span className="rail-empty">{t('The report appears here when it is written.')}</span>
        : <>
          {reports.length > 0 && <VersionedRow icon={MessageSquareQuote} label={reports[0].title} onOpen={onOpenReport}
            versions={reports.map(({ answer, version }) => ({ id: answer.id, tag: `V${version}`, at: answer.created_at,
              note: [answer.late_revision && t(LATE_REVISION_LABEL), (answer.applicability !== 'current' || answer.late_revision_status?.status === 'published') && t('earlier')].filter(Boolean).join(' · ') || undefined }))} />}
          {tableGroups.map(group => {
            const [table] = group
            const label = t('Evidence table · {sources} · {columns}', {
              sources: t(table.rows === 1 ? '{n} source' : '{n} sources', { n: table.rows }), columns: t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns }) })
            return <VersionedRow key={table.id} icon={Table2} label={label} ariaLabel={`${label} · ${tableTitle(table.title, researchHeading(view))}`} onOpen={onOpenTable}
              // A study table is numbered as the report version that opened it (D57); a table made otherwise by its order.
              versions={group.map((item, i) => ({ id: item.id, tag: `V${item.answer_version ?? group.length - i}`, at: item.created_at,
                note: t('{sources} · {columns}', { sources: t(item.rows === 1 ? '{n} source' : '{n} sources', { n: item.rows }), columns: t(item.columns === 1 ? '{n} column' : '{n} columns', { n: item.columns }) }) }))} />
          })}
          {view.reportRuns.length > 0 && <VersionedRow icon={FileText} label={t('Evidence report')} onOpen={onOpenEvidenceReport}
            versions={view.reportRuns.map(item => ({ id: item.id, at: item.created_at,
              tag: item.status === 'valid' ? `V${item.report_version ?? ''}` : t(item.status === 'draft' ? 'draft' : 'being written') }))} />}
          {pending && <div className="li pending" title={t('Filled in after the answer is written')}>
            <Table2 size={16} strokeWidth={1.6} aria-hidden />
            <span>{t('Evidence table · {sources} · after the answer', { sources: t(pending.sources === 1 ? '{n} source' : '{n} sources', { n: pending.sources }) })}</span>
          </div>}
        </>}
    </div>

    {(queueCount > 0 || waitingCount > 0) && <Box warn title={t('Waiting for your decision')} action={{ label: t('Open'), name: t('Waiting for your decision'), onClick: open(queueCount > 0 ? 'queue' : 'pdfs') }}>
      {queueRows.slice(0, QUEUE_ROWS).map(row => <Row key={row.row_token} tile icon={row.kind === 'confirm_pdf' ? File : row.kind === 'choose_version' ? Copy : ListChecks}
        label={row.title} aside={row.kind === 'look_again' ? t('Look again') : t(queueKindLabels[row.kind])} onClick={open('queue')} />)}
      {queueCount > Math.min(QUEUE_ROWS, queueRows.length) && <Row tile icon={ListChecks} label={leadNumber(t('{n} waiting for you', { n: queueCount }))} onClick={open('queue')} />}
      {waitingCount > 0 && <Row tile icon={File} label={leadNumber(t('{n} waiting for a PDF', { n: waitingCount }))} aside={t('PDF')} onClick={open('pdfs')} />}
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

    <Box title={t('Usage')}>
      {callsRun && <>
        <div className="kv"><span>{t('Model calls')}</span><span className="tnum rail-data">{number(calls)} / {number(callLimit)}</span></div>
        <div className="bar" aria-hidden><i style={{ width: `${Math.min(100, calls / callLimit * 100)}%`, background: 'var(--accent)' }} /></div>
        <p className="rail-usage-note">{t('Latest run: {kind}', { kind: t(runKindLabels[callsRun.kind]) })}</p>
      </>}
      <div className="kv rail-usage-budget"><span>{t('OpenAlex budget today')}</span><span className="tnum rail-data" title={budgetValue && !budgetText ? t('No OpenAlex response with a budget figure is stored since the daily reset (midnight UTC).') : undefined}>
        {budgetText ?? (budgetValue ? t('not known') : budget.failed ? t('could not be read') : '…')}</span></div>
      {used !== null && <div className="bar" aria-hidden><i style={{ width: `${Math.max(1, used * 100)}%`, background: used >= 1 ? 'var(--error-ink)' : 'var(--accent)' }} /></div>}
      {prepaidText && <div className="kv rail-usage-budget"><span>{t('OpenAlex extra balance')}</span><span className="tnum rail-data" title={budgetValue?.prepaid_expires_at ? t('Expires {date}', { date: new Date(budgetValue.prepaid_expires_at).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'long', year: 'numeric' }) }) : undefined}>{prepaidText}</span></div>}
      {budgetValue && <p className="rail-usage-note">{[budgetAsOf(budgetValue) ?? t('No OpenAlex response stored since the daily reset'), budget.failed && t('not refreshed: the last read failed')].filter(Boolean).join(' · ')}</p>}
    </Box>
  </aside>
}
