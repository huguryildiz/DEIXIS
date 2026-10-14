import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, ChevronRight, Clock, Ellipsis, FileText, FileUp, Funnel, Inbox, Lightbulb, ListMinus, PencilLine, Search, Sparkles, Table2, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, ApiError, followupApi, libraryApi, subscribe, type ActivityEvent, type Answer, type AssetImpact, type ResearchView, type Run, type OcrTool, type RunKind, type RunStatus, type Source, type TableSummary, type ZoteroSource } from './api'
import { serviceErrorSentence, serviceKind, fileRestoreNote, fileRestoreText, fileRestoreTone, pauseReasonText, providerName, runKindLabels, runStatusLabels, scopeLabels, seedSkipText, seedUseText } from './labels'
import { PassageSheet } from './PassageSheet'
import { TextRecoveryContext } from './TextRecoveryContext'
import { EvidenceTab, TABLE_RUN_KINDS } from './EvidenceTable'
import { Transcript } from './Transcript'
import { PdfReadiness } from './PdfReadiness'
import { includedReading } from './includedReading'
import { ReportView } from './report/ReportView'
import { FollowUpView } from './followup/FollowUpView'
import { useFollowUpCount } from './followup/useFollowUp'
import { CandidatesView, type CandidateSelection } from './candidate/CandidatesView'
import { CANDIDATE_KINDS } from './candidate/CandidateRunLine'
import { ZoteroPanel } from './ZoteroPanel'
import { useToast, type ToastAction } from './Toast'
import { ConnectionIcon } from './connectionIcons'
import { useModelText } from './modelText'
import { ConfirmDialog } from './ConfirmDialog'
import { effortLabels, effortOptions, MAX_SEED_PDFS, scopeOptions } from './Home'
import { t } from './i18n'
import { focusWhenLost } from './focus'
import { scrollBehavior } from './motion'
import { Notice } from './Notice'
import { HumanQueue } from './HumanQueue'
import { FunnelPanel } from './FlowReport'
import { AuditSample } from './AuditSample'
import { WaitingForPdf } from './WaitingForPdf'
import { EnglishQuestion, UploadedTextNote } from './SemanticNotes'
import { AnswerThread, type AnswerReviewControl, type AnswerThreadContext } from './research/AnswerThread'
import { printReport } from './research/printPanel'
import { ChooseModelDialog, type ChooseModelTarget } from './research/ChooseModelDialog'
import { comparisonBase } from './research/answerDiff'
import { ReviewSurface } from './review/ReviewSurface'
import { useReviewSurface } from './review/useReviewSurface'
import { CitationPanel, type CitationOpen } from './research/CitationPanel'
import { ActivityPanel } from './research/ActivityPanel'
import { PlanPanel } from './research/PlanPanel'
import { TableCard } from './research/ArtifactsTab'
import { Rail } from './research/Rail'
import { useRailWide } from './research/railData'
import { ExportLinks, ExportMenu } from './research/ExportMenu'
import { RevisionForm } from './research/RevisionForm'
import { EarlierRevision, QuestionBubble } from './research/QuestionBubble'
import { RunChip, TitleButton, TitleEditRow } from './research/Topbar'
import { SourcesPanel, type StateFilter } from './research/SourcesPanel'
import { SplitPanel, StackPanel } from './research/SplitPanel'
import { PanelStackContext, panelFromSegment, usePanelStack, usePhone, URL_PANELS } from './research/usePanelStack'
import { RESEARCH_PANEL_EVENT, type ResearchPanelRequest } from './Shortcuts'
import { FollowupComposer, type FollowupFill } from './research/FollowupComposer'
import { FollowupTurnView } from './research/FollowupTurns'
import { followupClaim, followupClaimId, useFollowupTurns } from './research/followupData'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Rechecks a person starts from the table; short enough to start and end between two reads of the research.
const RECHECK_KINDS = new Set(['cell_recheck', 'table_column_recheck'])
const TRANSCRIPT_KINDS = new Set<RunKind>(['discovery', 'pdf_collection', 'fulltext_fetch', 'fulltext_adjudication', 'pdf_ocr', 'answer', 'report', 'review'])
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

const shownAnswer = (view: ResearchView) => (view.answers.find(a => !(a.late_revision && a.status !== 'structurally_valid')) ?? view.answers[0]) as Answer | undefined

// "No research yet" (mockup `.empty` of the first open, R32): Current research before any research was opened in this
// browser. With researches in the list, none has been opened here yet, so the page says that instead.
export function EmptyResearch({ opened }: { opened: boolean }) {
  return <section className="research-empty"><div>
    <Clock size={16} aria-hidden />
    <h1>{t(opened ? 'No research opened yet' : 'No research yet')}</h1>
    <p>{t(opened ? 'Open one from Recent research, or start a new one.' : 'Your questions and their answers will appear here. Set up a model first, then ask a question.')}</p>
    <Button onClick={() => { window.location.hash = '/' }}>{t('New research')}</Button>
  </div></section>
}

export function ResearchPage({ id, initialTab, dark, onChanged }: { id: string; initialTab?: string; dark: boolean; onChanged: () => void }) {
  const [view, setView] = useState<ResearchView | null>(null)
  const [titleEditing, setTitleEditing] = useState(false)
  // The question bubble turns into the revise form (R7); 'terms' opens it on the key-terms field.
  // The revise form, pinned to the question revision it was opened on (see saveRevision).
  // `ask` counts the requests to focus a field while the form is open.
  const [revising, setRevising] = useState<false | { focus: 'question' | 'terms'; revision: number; ask: number }>(false)
  const [savingRevision, setSavingRevision] = useState(false)
  const [error, setError] = useState('')
  const toast = useToast()
  // The tabs became a side panel beside the thread (R10): the URL's last segment names the open panel, old tab names included.
  const panels = usePanelStack(panelFromSegment(initialTab))
  const panel = panels.current
  const phone = usePhone()
  const railWide = useRailWide()
  const [candidateCount, setCandidateCount] = useState<number | null>(null)
  const [candidateSelection, setCandidateSelection] = useState<CandidateSelection | null>(null)
  // `view`: the tab Source details opens on (the Citation panel's Show in the PDF); `find`: start the open-copy lookup there.
  const [passageTarget, setPassageTarget] = useState<{ passageId: string; highlightText: string | null; fromCitation: boolean; reportCitation?: boolean; view?: 'text' | 'pdf'; find?: boolean } | null>(null)
  // The claim of the latest answer whose citations the Citation panel shows (P11).
  const [citeClaimId, setCiteClaimId] = useState<string | null>(null)
  // A PDF (opened on its PDF or plain-text tab) or a source opened from its title in the Sources table.
  const [pdfTarget, setPdfTarget] = useState<{ assetId: string | null; sourceVersionId?: string; view?: 'text' | 'pdf' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  // The counts under the question open the Sources tab, so the selection filter lives here rather than inside the list.
  const [sourceFilter, setSourceFilter] = useState<StateFilter>('all')
  // The model-down notice's "Choose another model" (R20): the stopped run and the role of its stopped step.
  const [chooseModel, setChooseModel] = useState<ChooseModelTarget | null>(null)
  // One work the audit sample sent the person to (slice 20): the Sources list shows that work alone, by its id.
  const [sourceFocus, setSourceFocus] = useState<string | null>(null)
  const openPanel = panels.open
  // The works whose open-copy lookup is running; each lookup removes only its own entry when it ends.
  const [pdfFinding, setPdfFinding] = useState<string[]>([])
  const [attachTarget, setAttachTarget] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<{ source: Source; assetId: string } | null>(null)
  // Replacing a PDF: the file is chosen first, then the confirmation names what still cites the old file (D45).
  const [replacePick, setReplacePick] = useState<{ source: Source; assetId: string } | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<{ source: Source; assetId: string; file: File; impact: AssetImpact } | null>(null)
  const [openReportId, setOpenReportId] = useState<string | null>(null)
  // The report's answer diff (P4, S21): on while the report panel stays open, whichever version it shows; closing the
  // panel turns it off. The comparison itself is derived from the stored answers at each render, so a version switch or
  // a newer view never shows an earlier comparison.
  const [changesShown, setChangesShown] = useState(false)
  const [changesReport, setChangesReport] = useState(openReportId)
  if (changesReport !== openReportId) {
    setChangesReport(openReportId)
    if (!openReportId) setChangesShown(false)
  }
  const reportChanges = (shown: Answer) => ({ on: changesShown, base: comparisonBase(shown, view?.answers ?? []), onToggle: () => setChangesShown(on => !on) })
  // The answer's review dialog and panel (P32/P33) live here, not in the answer thread: when a newer answer replaces the
  // thread, an open review stays on the answer version it was opened for and says it is stale.
  const answerReviews = useReviewSurface()
  const [answerReviewTarget, setAnswerReviewTarget] = useState<{ id: string; version: number } | null>(null)
  const [answerReviewRevision, setAnswerReviewRevision] = useState(0)
  const answerReview: AnswerReviewControl = { surface: answerReviews, revision: answerReviewRevision, target: (answerId, version) => setAnswerReviewTarget({ id: answerId, version }) }
  const [openEvidenceReportId, setOpenEvidenceReportId] = useState<string | null>(null)
  // Sources chosen for a table or for removal (D50). Kept only while the Sources tab is open.
  const [picked, setPicked] = useState<string[]>([])
  // Boxes ticked on the PDF list but not saved yet; null shows the PDFs the research stored.
  const [seedPick, setSeedPick] = useState<string[] | null>(null)
  const [removal, setRemoval] = useState<{ ids: string[]; versions: number; elsewhere: number | null } | null>(null)
  const [tableStart, setTableStart] = useState<{ ids: string[]; notIncluded: number } | null>(null)
  // The table to show, with a count of requests: asking for the same table again (a card clicked twice) still shows it.
  // `cell`: a cell to open with the table (an evidence report's "Open the current cell"); the table clears it once shown.
  const [focusTable, setFocusTable] = useState<{ id: string; request: number; cell?: { columnId: string; sourceId: string } | null } | null>(null)
  const showTableFirst = (tableId: string, cell: { columnId: string; sourceId: string } | null = null) => setFocusTable(previous => ({ id: tableId, request: (previous?.request ?? 0) + 1, cell }))
  const cellShown = useCallback(() => setFocusTable(previous => (previous?.cell ? { ...previous, cell: null } : previous)), [])
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceFileInput = useRef<HTMLInputElement>(null)
  const replaceFileInput = useRef<HTMLInputElement>(null)
  const firstEvent = useRef<number | null>(null)
  const lastRun = useRef<{ id: string; status: RunStatus } | null>(null)
  // Runs another toast already announced when they were opened (a person's file whose attach opened its reading, 18b).
  const announcedRuns = useRef(new Set<string>())
  const moreButton = useRef<HTMLButtonElement>(null)
  const reviseButton = useRef<HTMLButtonElement>(null)
  // Escape on the Research actions menu gives focus back to its button; choosing a row hands it to the panel that opens.
  const rowChosen = useRef(false)

  const load = useCallback(async () => {
    try {
      const next = await api.research(id)
      setView(next)
      setError('')
      if (firstEvent.current === null) firstEvent.current = next.last_event_id
      return true
    } catch (e) { setError(errorText(e)); return false }  // whether the view was read, for callers that report it
  }, [id])
  useEffect(() => { void load() }, [load])
  // Tables of this research, for the Evidence count and the table cards; refreshed on every recorded event (a table created, edited, trashed or restored).
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  const lastEventId = view?.last_event_id
  const followupCount = useFollowUpCount(id, lastEventId)
  // Follow-up questions of this research (R30/R31, S22b); not the Follow-up panel above, which watches for new works.
  const followups = useFollowupTurns(id, lastEventId ?? 0)
  const [asking, setAsking] = useState(false)
  const [followupFill, setFollowupFill] = useState<FollowupFill | null>(null)
  const followupChanged = useCallback(async () => { await load(); onChanged() }, [load, onChanged])
  useEffect(() => {
    let live = true
    api.tables(id).then(list => { if (live) setTables(list) }, () => { /* the count and cards are left out */ })
    return () => { live = false }
  }, [id, lastEventId])
  // Codex lists each model's default effort; a research created without an effort runs at that default.
  const modelText = useModelText()

  const loaded = view !== null
  // The open panel is written to the URL without a navigation, so the page is not opened again.
  const urlPanel = [...panels.entries].reverse().find(entry => URL_PANELS.has(entry.name))?.name
  useEffect(() => {
    const hash = `#/research/${id}${urlPanel ? `/${urlPanel}` : ''}`
    if (window.location.hash !== hash) window.history.replaceState(window.history.state, '', hash)
  }, [id, urlPanel])
  // A link to this research's panel (e.g. "Open it in Awaiting your decision") opens that panel here.
  useEffect(() => {
    const onHash = () => {
      const [hashId, segment] = window.location.hash.replace(/^#\/?research\//, '').split('/')
      const name = hashId === id ? panelFromSegment(segment) : null
      if (name) openPanel(name, { fresh: true })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [id, openPanel])
  // The shortcut keys and the search palette (S3) open a panel, the shown answer's report, or close the open panel. Each
  // starts a new stack, so R brings the report back in front of a source opened from one of its citations.
  const closePanels = panels.close
  useEffect(() => {
    const onRequest = (event: Event) => {
      const { name, opener } = (event as CustomEvent<ResearchPanelRequest>).detail
      const shown = view && shownAnswer(view)
      if (name === null) closePanels()
      else if (name === 'report') { if (shown) { openPanel(`report:${shown.id}`, { fresh: true, opener }); setOpenReportId(shown.id) } }
      else openPanel(name, { fresh: true, opener })
    }
    window.addEventListener(RESEARCH_PANEL_EVENT, onRequest)
    return () => window.removeEventListener(RESEARCH_PANEL_EVENT, onRequest)
  }, [view, openPanel, closePanels])
  // A research over attached files only has no search plan: its panel (opened from a URL) leaves the stack.
  const removePanel = panels.remove
  const searches = view ? view.scope.source_scope !== 'attached' : true
  useEffect(() => { if (!searches) removePanel('plan') }, [searches, removePanel])
  // Leaving the Sources panel ends the audit sample's focus and the chosen rows: coming back shows the whole list.
  const sourcesOpen = panels.entries.some(entry => entry.name === 'sources')
  const [sourcesWereOpen, setSourcesWereOpen] = useState(sourcesOpen)
  if (sourcesWereOpen !== sourcesOpen) {
    setSourcesWereOpen(sourcesOpen)
    if (!sourcesOpen) { setSourceFocus(null); setPicked([]) }
  }

  useEffect(() => {
    if (!loaded) return
    // A running discovery records several events a second and one reload of a large research takes about a second, so reloads
    // are throttled: never two at once, at least 1.5 s apart, and the last event always gets one.
    let timer: ReturnType<typeof setTimeout> | undefined
    let running = false
    let pending = false
    let last = 0
    let stopped = false
    const reload = async () => {
      timer = undefined
      running = true
      pending = false
      await load()
      if (stopped) return
      onChanged()
      last = Date.now()
      running = false
      if (pending) schedule()
    }
    const schedule = () => {
      if (running) { pending = true; return }
      if (timer) return
      timer = setTimeout(() => { void reload() }, Math.max(250, 1500 - (Date.now() - last)))
    }
    const stop = subscribe(id, firstEvent.current ?? 0, schedule)
    return () => { stopped = true; stop(); clearTimeout(timer) }
  }, [id, loaded, load, onChanged])

  // The local Tesseract is asked once a PDF has pages without text, so its rows can offer OCR or say why it is off (D51).
  const needsOcr = Boolean(view?.sources.some(s => s.access.assets.some(a => a.ocr?.pages_without_text && a.extraction_status !== 'succeeded')))
  useEffect(() => {
    if (!needsOcr) return
    api.ocr().then(setOcrTool).catch(e => toast('error', t('Could not check the OCR tool: {error}', { error: errorText(e) })))
  }, [needsOcr, toast])

  useEffect(() => {
    if (panel !== 'activity') return
    api.events(id).then(setEvents).catch(e => toast('error', t('Could not load activity: {error}', { error: errorText(e) })))
  }, [panel, id, view?.last_event_id, toast])

  // Runs finish in the background, often while another tab is open: announce each status change of the latest run.
  useEffect(() => {
    const current = view?.runs[0]
    if (!view || !current) return
    const previous = lastRun.current
    lastRun.current = { id: current.id, status: current.status }
    if (current.kind === 'watch_check') return
    if (!previous || (previous.id === current.id && previous.status === current.status)) return
    const label = t(current.kind === 'answer' ? 'Answer generation' : runKindLabels[current.kind])
    const reason = pauseReasonText(current.pause_reason, current.error)
    // A new run still under way says it started. One that already ended by the next read stays silent (a background run,
    // such as a title suggestion after a saved revision, must not take the toast slot), except a recheck the person asked
    // for, which can start and finish between two reads: its end is announced below.
    if (previous.id !== current.id) {
      if (ACTIVE.has(current.status)) { if (!announcedRuns.current.has(current.id)) toast('success', t('{label} started.', { label })); return }
      if (!RECHECK_KINDS.has(current.kind)) return
    }
    switch (current.status) {
      case 'completed': {
        if (current.kind !== 'discovery' && current.kind !== 'answer') { toast('success', current.kind === 'cell_recheck' ? t('Recheck finished. Its result waits as a proposal in the cell.') : current.kind === 'table_column_recheck' ? t('Column recheck finished. Its results wait as proposals in the cells; no value was changed.') : t('{label} finished.', { label })); break }
        const answer = view.answers.find(a => a.run_id === current.id)
        if (current.kind === 'discovery') toast('success', t('Search & screening finished. Review the sources and include the ones to use.'))
        else if (answer?.status === 'structurally_valid') toast('success', t('Answer ready.'))
        else if (answer?.status === 'clarification') toast('warning', t('The model needs a clarification before it can answer.'))
        else if (answer?.status === 'no_evidence') toast('warning', answer.validation.reason === 'no_includable_source'
          ? t('No answer: no work was included at full text when this answer started.')
          : t('No answer: no text passages were available for the included sources.'))
        else toast('warning', t('The answer failed validation; it is kept as an unverified draft.'))
        break
      }
      case 'paused': toast(current.pause_reason === 'user_requested' ? 'success' : 'warning', t('{label} paused. {reason}', { label, reason })); break
      case 'failed': toast('error', t('{label} failed. {reason}', { label, reason })); break
      case 'cancelled': toast('success', t('{label} cancelled.', { label })); break
      case 'pause_requested': toast('success', t('Pause requested: the run stops after the current call.')); break
      case 'queued': case 'running': if (previous.status === 'paused') toast('success', t('{label} resumed.', { label })); break
    }
  }, [view, toast])

  async function act(action: () => Promise<unknown>, success?: string, undo?: ToastAction) {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setBusy(true)
    try { await action(); if (success) toast('success', success, undo); await load(); onChanged(); return true }
    catch (e) {
      // 409: the research or run changed after this page loaded (another tab, or a run that moved on).
      if (e instanceof ApiError && e.status === 409) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message })); await load() }
      else toast('error', errorText(e))
      // On failure, restore the initiating control only after it is enabled again and focus is still lost.
      focusWhenLost(() => opener?.isConnected && !opener.matches(':disabled') ? opener : null, 2500, false, opener)
      return false
    } finally { setBusy(false) }
  }

  if (error && !view) return <section className="research-view"><Notice tone="error">{t('Could not open this research: {error}', { error })}</Notice></section>
  if (!view) return <section className="research-view"><p className="session-meta">{t('Loading research…')}</p></section>

  const run = view.runs[0] as Run | undefined
  const active = run ? ACTIVE.has(run.status) : false
  const candidateRun = view.runs.find(r => CANDIDATE_KINDS.has(r.kind) && (ACTIVE.has(r.status) || r.status === 'paused'))
  const watchRun = view.runs.find(r => r.kind === 'watch_check' && (ACTIVE.has(r.status) || r.status === 'paused'))
  const answer = shownAnswer(view)
  // The works the shown answer cites, from its stored claims: each citation keeps its work id, so a source since removed
  // from the research still counts as the work it was (the view's `counts.cited` follows the newest draft instead, which
  // after a failed late revision cites nothing while V1 is shown). The facts strip, the rail and the Cited tab use it.
  const citedWorkIds = new Set(answer?.claims.flatMap(c => c.evidence.map(e => e.work_id)) ?? [])
  const citedCount = citedWorkIds.size
  // How many claims of the shown answer cite each work (the Cited tab) and each version (a Sources row's "cited in N
  // claims" pill: an uncited version of a cited work gets none).
  const citedClaims = new Map<string, number>()
  const citedVersionClaims = new Map<string, number>()
  answer?.claims.forEach(c => {
    new Set(c.evidence.map(e => e.work_id)).forEach(w => citedClaims.set(w, (citedClaims.get(w) ?? 0) + 1))
    new Set(c.evidence.map(e => e.source_version_id)).forEach(v => citedVersionClaims.set(v, (citedVersionClaims.get(v) ?? 0) + 1))
  })
  // What its BibTeX export lists: the cited versions still in this research, counted as works.
  const citedVersions = new Set(answer?.claims.flatMap(c => c.evidence.map(e => e.source_version_id)) ?? [])
  const citedListed = new Set(view.sources.filter(s => citedVersions.has(s.source_version_id)).map(s => s.work_id)).size
  const hasAcademic = view.scope.source_scope !== 'attached'
  const needsSeed = view.scope.source_scope === 'attached_and_academic' && view.scope.seed_mode === 'uploaded_seed'
  const seedSearchReady = !needsSeed || view.scope.seed_status === 'ready'
  // The backend decides which PDFs can guide a search; the page lists them and sends back the ticked ones in list order.
  const seedCandidates = view.scope.seed_candidates
  const storedSeedIds = view.scope.seeds.map(seed => seed.source_version_id).filter(sourceId => seedCandidates.some(c => c.source_version_id === sourceId))
  const tickedSeeds = seedPick ?? storedSeedIds
  const seedTitle = (sourceId: string) => view.sources.find(source => source.source_version_id === sourceId)?.title ?? sourceId
  const included = view.counts.included
  // Included sources an answer could read only from their abstract: the thread names them before the first answer.
  const missingPdfs = includedReading(view).missing.length

  // Only the run returned by this successful request can receive its focus handoff.
  const toRunStatus = (runId: string, origin: Element | null) => { focusWhenLost(() => {
    const escapedId = CSS.escape(runId)
    return document.querySelector<HTMLElement>(`.chat-turn .chat-toggle[data-run-id="${escapedId}"]`)
      ?? document.querySelector<HTMLElement>(`.run-strip-status[data-run-id="${escapedId}"]`)
  }, 2500, false, origin) }
  const startAnswer = async () => {
    const origin = document.activeElement
    let started: Run | undefined
    if (await act(async () => { started = await api.startRun(id, 'answer', crypto.randomUUID()) }) && started) toRunStatus(started.id, origin)
  }
  const startDiscovery = () => {
    if (!seedSearchReady) { toast('error', t('Choose a readable PDF to guide the search.')); return }
    return act(() => api.startRun(id, 'discovery', crypto.randomUUID()))
  }
  // A new choice goes in candidate order; refreshing the current text re-sends the stored seeds in their stored order,
  // removed ones included, so the backend keeps the order and records any it can no longer use (D3).
  const saveSeeds = async (ids: string[], keepOrder = false) => {
    const orderedIds = keepOrder ? ids : seedCandidates.map(c => c.source_version_id).filter(sourceId => ids.includes(sourceId))
    if (await act(() => api.setSeeds(id, { source_version_ids: orderedIds }, view.research.version), t('PDFs selected for the next search.'))) setSeedPick(null)
  }
  // The PDFs that guide the search and their choice (D3), shown in the Search plan panel (§2.2, S23b): what each stored PDF
  // was used for, the PDFs the backend offers with the saved ones ticked, accepting a changed PDF's current text, and the notes.
  const seedChoice = view.scope.source_scope === 'attached_and_academic' ? <>
    {view.scope.seed_status === 'ready' || (view.scope.seed_status === 'stale' && view.scope.seeds.length)
      ? <ul className="research-seed-uses">{view.scope.seeds.map(seed =>
          <li key={seed.source_version_id}><span>{seed.title}</span>{seedUseText(seed.use)}</li>)}</ul>
      : <small>{view.scope.seed_status === 'question_only'
          ? t('This earlier research searches from the question. Choose PDFs to guide a later search.')
          : t('Choose readable PDFs before searching scholarly providers.')}</small>}
    {seedCandidates.length > 0 && <fieldset className="research-seed-pick" disabled={busy || active}>
      <legend className="sr-only">{t('Choose the PDFs that guide the search')}</legend>
      {seedCandidates.map(candidate => {
        const checked = tickedSeeds.includes(candidate.source_version_id)
        return <label key={candidate.source_version_id}>
          <input type="checkbox" checked={checked} disabled={!checked && tickedSeeds.length >= MAX_SEED_PDFS}
            onChange={e => setSeedPick(e.target.checked ? [...tickedSeeds, candidate.source_version_id] : tickedSeeds.filter(sourceId => sourceId !== candidate.source_version_id))} />
          <span>{candidate.title}</span>
        </label>
      })}
      <div className="research-seed-pick-foot">
        <button type="button" className="ghost" disabled={busy || active || !tickedSeeds.length} onClick={() => void saveSeeds(tickedSeeds)}>{t('Use selected PDFs')}</button>
        <small>{t('{n} of {max} chosen', { n: tickedSeeds.length, max: MAX_SEED_PDFS })}
          {tickedSeeds.length >= MAX_SEED_PDFS && seedCandidates.length > MAX_SEED_PDFS ? ` · ${t('untick one to choose another')}` : ''}
          {active ? ` · ${t('available when the run ends')}` : ''}</small>
      </div>
    </fieldset>}
    {view.scope.seed_status === 'stale' && storedSeedIds.length > 0 &&
      <div><button type="button" className="ghost" disabled={busy || active} onClick={() => void saveSeeds(view.scope.seeds.map(seed => seed.source_version_id), true)}>{t('Use current PDF text')}</button></div>}
    {view.scope.seed_status === 'stale' && <Notice tone="attention">{t('A selected PDF changed or was removed. Select the current PDFs again before searching.')}</Notice>}
    {view.scope.seed_not_selected.length > 0 &&
      <Notice tone="info">{t('Only {max} PDFs can guide a search. Left out: {titles}.', { max: MAX_SEED_PDFS, titles: view.scope.seed_not_selected.map(item => item.title).join('; ') })}</Notice>}
    {view.scope.seed_skipped.length > 0 &&
      <Notice tone="attention">{t('Not used: {items}.', { items: view.scope.seed_skipped.map(item => `${seedTitle(item.source_version_id)} (${seedSkipText(item.reason)})`).join('; ') })}</Notice>}
    {view.scope.seed_status === 'ready' && view.scope.seeds.some(seed => seed.page_count != null && seed.text_pages < seed.page_count) &&
      <Notice tone="attention">{t('Some PDF pages have no extracted text; the search uses only the readable passages.')}</Notice>}
    {!seedCandidates.length && <Notice tone="attention">{t('Attach a PDF with readable text, or read scanned pages with OCR, to guide the search.')}</Notice>}
  </> : null
  // The thread's line about them, while something waits on the person or while the current question revision has not
  // searched yet (a new revision, e.g. after accepting a changed PDF's text, has no plan step to open the panel from).
  const seedLine = view.scope.source_scope === 'attached_and_academic'
    && (view.scope.seed_status !== 'ready' || !view.runs.some(r => r.kind === 'discovery' && r.scope_revision === view.research.current_scope_revision))
  const startTitle = () => act(() => api.startRun(id, 'research_title', crypto.randomUUID()))
  const upload = (list: FileList | null) => list && act(async () => { for (const file of Array.from(list)) {
    const next = await api.upload(id, file)
    toast(next.file_restore ? fileRestoreTone(next.file_restore) : 'success', [t('PDF added and included. Its text was extracted page by page (no OCR).'), fileRestoreNote(next.file_restore)].filter(Boolean).join(' '))
  } })
  const uploadToSource = (list: FileList | null) => list && attachTarget && act(async () => {
    for (const file of Array.from(list)) {
      const next = await api.uploadToSource(id, attachTarget, file)
      toast(next.file_restore ? fileRestoreTone(next.file_restore) : 'success', [t('PDF attached to this source. Its text was extracted page by page (no OCR).'), fileRestoreNote(next.file_restore)].filter(Boolean).join(' '))
    }
  })
  // Whether the lookup finished (Source details then reads its recorded answers).
  const discoverPdf = async (source: Source) => {
    setPdfFinding(list => [...list, source.source_version_id])
    try { await api.discoverPdf(id, source.source_version_id); await load(); onChanged(); return true }
    catch (e) { toast('error', errorText(e)); return false }
    finally { setPdfFinding(list => { const at = list.indexOf(source.source_version_id); return at < 0 ? list : [...list.slice(0, at), ...list.slice(at + 1)] }) }
  }
  const chooseSourcePdf = (source: Source) => { setAttachTarget(source.source_version_id); sourceFileInput.current?.click() }
  // A failed retrieval is recorded on the candidate, so reload before act reports the error.
  const attachPdfCandidate = (source: Source, candidateId: string) => act(async () => {
    try { await api.attachPdfCandidate(id, source.source_version_id, candidateId) } finally { await load() }
  }, t('PDF attached after your version check. Its text was extracted page by page (no OCR).'))
  const removeSourcePdf = (source: Source, assetId: string) => setRemoveTarget({ source, assetId })
  const confirmRemoveSourcePdf = () => {
    if (!removeTarget) return
    const { source, assetId } = removeTarget
    setRemoveTarget(null)
    // Undo puts the same file back while no other PDF is in use for the source (D50).
    void act(() => api.removeAsset(id, source.source_version_id, assetId), t('PDF removed from the source.'),
      { label: t('Undo'), run: () => { void act(() => api.restoreAsset(id, source.source_version_id, assetId), t('PDF restored to the source.')) } })
  }
  const chooseReplacement = (source: Source, assetId: string) => { setReplacePick({ source, assetId }); replaceFileInput.current?.click() }
  const reviewReplacement = async (list: FileList | null) => {
    const file = list?.[0]
    if (!file || !replacePick) return
    try { setReplaceTarget({ ...replacePick, file, impact: await api.assetImpact(id, replacePick.source.source_version_id, replacePick.assetId) }) }
    catch (e) { toast('error', errorText(e)) }
  }
  const confirmReplacement = () => {
    if (!replaceTarget) return
    const { source, assetId, file } = replaceTarget
    setReplaceTarget(null)
    void act(async () => {
      const next = await api.replaceAsset(id, source.source_version_id, assetId, file)
      const fileOnly = next.file_restore && next.sources.find(item => item.source_version_id === source.source_version_id)?.access.assets.some(item => item.id === assetId)
      toast(next.file_restore ? fileRestoreTone(next.file_restore) : 'success', fileOnly ? fileRestoreText(next.file_restore!)
        : [t('PDF replaced. Its text was extracted page by page (no OCR); earlier evidence still opens the previous file.'), fileRestoreNote(next.file_restore)].filter(Boolean).join(' '))
    })
  }
  const reextract = (source: Source, assetId: string) => act(async () => {
    const { reextraction } = await api.reextractAsset(id, source.source_version_id, assetId)
    if (reextraction.outcome === 'rejected') toast('warning', t('The new extraction was not used: {reason}. The earlier text stays in use.', { reason: reextraction.rejection_reason ?? '' }))
    else toast('success', t(reextraction.outcome === 'unchanged' ? 'This text already comes from the current extractor.' : 'Text extracted again. Later answers and cells read the new text; earlier evidence still opens the text it cited.'))
  })
  const readWithOcr = (source: Source, assetId: string) => act(() => api.readWithOcr(id, source.source_version_id, assetId))
  const rereadEquations = (source: Source, assetId: string) => act(async () => {
    await api.rereadEquations(id, source.source_version_id, assetId)
    toast('success', t('The equations of this PDF are being read again in the background.'))
  })
  const importZotero = (source: ZoteroSource, key: string) => act(async () => {
    const { items, pdfs_added: pdfs, notes } = (await api.zoteroImport(id, source, key)).zotero_import
    setZoteroOpen(false)
    const added = `${t(items === 1 ? '{n} Zotero item added and included;' : '{n} Zotero items added and included;', { n: items })} ${t(pdfs === 1 ? '{n} PDF read page by page (no OCR).' : '{n} PDFs read page by page (no OCR).', { n: pdfs })}`
    if (notes.length) toast('warning', `${added} ${notes.map(n => `${n.title}: ${t(n.note, n.vars)}.`).join(' ')}`)
    else toast('success', added)
  })

  // A record's selection is its work's; another version follows it (D48).
  const workState = (source: Source) => (view.sources.find(s => s.work_id === source.work_id && s.version_role === 'record') ?? source).selection.state
  const inSourceOrder = (ids: string[]) => view.sources.filter(s => ids.includes(s.source_version_id))
  const askRemoval = async (ids: string[]) => {
    const chosen = inSourceOrder(ids)
    // Removing a record takes its other versions in this research with it; the confirmation counts them.
    const versions = view.sources.filter(s => s.version_role === 'other_version' && !ids.includes(s.source_version_id)
      && chosen.some(c => c.version_role === 'record' && c.work_id === s.work_id)).length
    setRemoval({ ids, versions, elsewhere: null })
    try {
      const works = new Set(chosen.map(s => s.work_id))
      const elsewhere = (await api.library()).entries.filter(e => works.has(e.work_id) && e.researches.some(r => r.id !== id)).length
      setRemoval(current => (current && current.ids === ids ? { ...current, elsewhere } : current))
    } catch { /* the confirmation leaves out the count of other research */ }
  }
  const confirmRemoval = () => {
    if (!removal) return
    const { ids } = removal
    setRemoval(null)
    let changed: string[] = []
    void act(async () => { changed = (await api.removeSources(id, ids)).changed_source_version_ids; setPicked([]) },
      t(ids.length === 1 ? 'Source removed from this research.' : '{n} sources removed from this research.', { n: ids.length }),
      { label: t('Undo'), run: () => { void act(() => api.restoreSources(id, changed), t('Restored to this research.')) } })
  }
  const startTable = (ids: string[]) => act(async () => {
    const created = await api.createTable(id, { title: t('Evidence table'), rows: inSourceOrder(ids).map(s => s.source_version_id) }, crypto.randomUUID())
    setPicked([])
    showTableFirst(created.table.id)
    openPanel('table')
  }, t(ids.length === 1 ? 'Table started with {n} row.' : 'Table started with {n} rows.', { n: ids.length }))
  const askTableStart = (ids: string[]) => {
    const notIncluded = inSourceOrder(ids).filter(s => workState(s) !== 'included').length
    if (notIncluded) setTableStart({ ids, notIncluded })
    else void startTable(ids)
  }
  const addToTable = (table: TableSummary, ids: string[]) => act(async () => {
    const current = await api.table(id, table.id)
    await api.addTableRows(id, table.id, inSourceOrder(ids).map(s => s.source_version_id), current.table.version)
    setPicked([])
    showTableFirst(table.id)
    openPanel('table')
  }, t('Rows added to {title}.', { title: table.title }))
  // Saves source versions to the Library (F14), one request per 500; the message counts what the server reports saved
  // and already there, and names a failed batch with what it left unsaved.
  const saveToLibrary = async (ids: string[]) => {
    const chosen = [...new Set(ids)]
    let saved = 0, already = 0, done = 0
    setBusy(true)
    try {
      for (let i = 0; i < chosen.length; i += 500) {
        const batch = chosen.slice(i, i + 500)
        const result = await libraryApi.saveItems(batch)
        saved += result.saved.length; already += result.already_saved.length; done += batch.length
      }
      toast('success', saved === 0 ? t(already === 1 ? '{n} source was already in the Library.' : '{n} sources were already in the Library.', { n: already })
        : [t(saved === 1 ? 'Saved {n} source to the Library.' : 'Saved {n} sources to the Library.', { n: saved }),
          already > 0 && t(already === 1 ? '{n} was already there.' : '{n} were already there.', { n: already })].filter(Boolean).join(' '))
    } catch (e) {
      toast('error', [done > 0 && t(saved === 1 ? 'Saved {n} source to the Library.' : 'Saved {n} sources to the Library.', { n: saved }),
        done > 0 && already > 0 && t(already === 1 ? '{n} was already there.' : '{n} were already there.', { n: already }),
        t('{n} not saved: {error}', { n: chosen.length - done, error: errorText(e) })].filter(Boolean).join(' '))
    } finally { setBusy(false) }
  }

  const ScopeIcon = scopeOptions[view.scope.source_scope].icon
  const EffortIcon = effortOptions[view.scope.effort].icon
  const titleButton = () => document.querySelector<HTMLElement>('.research-title-button')
  const beginTitleEdit = () => { setRevising(false); setTitleEditing(true) }
  const endTitleEdit = () => { setTitleEditing(false); focusWhenLost(titleButton) }
  const saveTitle = (next: string) => {
    endTitleEdit()
    if (!next || next === view.research.title) return
    void act(() => api.renameResearch(id, next, view.research.version), t('Research title saved.'), undefined)
  }
  // The model names the research (at most 15 words); the new title arrives with the typewriter transition.
  const suggestTitle = () => { endTitleEdit(); void startTitle() }
  // The stored title is the question cut to 160 characters until a valid answer names the research (D36); until then show it whole.
  const heading = view.scope.question.startsWith(view.research.title) ? view.scope.question : view.research.title
  // Each count is the way into the evidence it describes; the selection filter lives here so a count can set it.
  const showSources = (filter: StateFilter) => { setSourceFocus(null); setSourceFilter(filter); openPanel('sources') }
  // An abstract-stage work of the audit sample is chosen with the source list's own controls: the list opens at that
  // work alone, found by its id (two works can share a title).
  const showInSources = (workId: string) => { showSources('all'); setSourceFocus(workId) }
  const showAnswer = () => { panels.setWide(false); requestAnimationFrame(() => document.getElementById('research-answer')?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })) }
  // Reports are the research's artifacts: every answer that passed validation, newest first, with the number and title saved with it.
  const reports = view.answers.filter(a => a.status === 'structurally_valid').map(a => ({ answer: a, version: a.report_version ?? 0, title: a.report_title ?? heading }))
  const latestEvidenceReportRun = view.runs.find(r => r.kind === 'report' && r.target?.report_id === view.reportRuns[0]?.id)
  // The latest report's panel belongs to its card in the thread; an older version's panel opens from here.
  const olderReport = reports.find(r => r.answer.id === openReportId && r.answer.id !== answer?.id)
  const openTable = (tableId: string) => { showTableFirst(tableId); openPanel('table') }
  // Table cards sit under the report card, or at the end of the conversation before the first answer.
  const tableCards = tables && tables.length > 0 && <div className="table-artifacts">{tables.map(table => <TableCard key={table.id} table={table} onOpen={() => openTable(table.id)} />)}</div>
  const openPassage = (passageId: string, highlightText: string | null) => setPassageTarget({ passageId, highlightText, fromCitation: true })
  // A research whose current search finished may answer with nothing included: the answer records that (SW22).
  const answersWithoutInclude = view.scope.discovery_completed === true
  const queueCount = (view.counts.queue ?? 0) + (view.counts.look_again ?? 0)
  const showQueue = () => openPanel('queue')
  // The works waiting for the person's PDF (slice 18a), counted in the ⋯ menu's row for the PDFs panel.
  const waitingCount = view.counts.waiting_for_pdf ?? 0
  // Revise question turns the question bubble into the revise form (R7); Cancel and Save give focus back to the button.
  // A form that is already open keeps the revision it started from (only "Base my draft on revision N" moves it); asking
  // again only moves focus to the requested field.
  const reviseQuestion = (focus: 'question' | 'terms' = 'question') => {
    setTitleEditing(false)
    setRevising(form => (form ? { ...form, focus, ask: form.ask + 1 } : { focus, revision: view.research.current_scope_revision, ask: 0 }))
  }
  const endRevise = () => { setRevising(false); focusWhenLost(() => reviseButton.current) }
  // A newer question revision saved elsewhere (another window) while the form was open: the draft is kept, Save waits until
  // the person bases the draft on that revision, so an old draft never silently replaces a newer question. While the
  // revision is unchanged the research version may move (a rename); the backend's expected_version still refuses a change
  // this view has not received yet.
  const reviseConflict = revising && !savingRevision && revising.revision !== view.research.current_scope_revision ? view.research.current_scope_revision : null
  const saveRevision = async (text: string, terms: string | null) => {
    if (!revising || revising.revision !== view.research.current_scope_revision) return
    setSavingRevision(true)
    const saved = await act(() => api.reviseScope(id, text, view.research.version, terms), t('Question revised. Earlier answers stay visible and are marked as belonging to the previous revision.'))
    setSavingRevision(false)
    if (saved) endRevise()
  }
  const controlRun = (target: Run, action: 'pause' | 'resume' | 'cancel') => {
    const origin = document.activeElement
    void act(() => api.controlRun(target.id, action)).then(ok => { if (ok && action === 'resume') toRunStatus(target.id, origin) })
  }
  // A follow-up question (R30, D11): one `followup_answer` run answers it from the passages this research holds; no search
  // starts. One request at a time; the turn the server returns is shown at once and the list is read again on its events.
  // The question revision on screen goes with it, so a newer revision saved elsewhere answers 409 instead of asking under it.
  const anyActive = view.runs.some(r => ACTIVE.has(r.status))
  const askFollowup = async (question: string, idempotencyKey: string) => {
    if (asking) return false
    setAsking(true)
    try {
      followups.accept(await followupApi.ask(id, question, view.research.current_scope_revision, idempotencyKey))
      onChanged()
      return true
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message })); await load() }
      else toast('error', t('The follow-up question was not sent: {error}', { error: errorText(e) }))
      return false
    } finally { setAsking(false) }
  }
  // "Search for new works on this" (R31, D13): saves the turn's question as the next question revision, only on this click. The
  // revision's English key terms are cleared, since they described the earlier question. No search starts here; the
  // message names the revision the server saved and says how to start its search.
  const searchNewWorks = async (question: string) => {
    let saved: ResearchView | null = null
    if (await act(async () => { saved = await api.reviseScope(id, question, view.research.version, '') }) && saved) {
      toast('success', t(view.search_runs.length ? 'Saved as revision {n} of the question. No search has started; start it with Search again.' : 'Saved as revision {n} of the question. No search has started; start it with Search providers.', { n: (saved as ResearchView).research.current_scope_revision }))
    }
  }
  // The latest answer in the thread (S10): the run writing its next version, the earlier version of the same question
  // revision, a claim review still running, and the panels its pills and Next steps rows open.
  const answerRun = run && run.kind === 'answer' && active && answer && run.id !== answer.run_id ? run : null
  const latestVersion = reports[0]?.version ?? 0
  // The report panel's version select lists every valid report of the research (V1, V2 …).
  const reportVersions = reports.map(r => ({ id: r.answer.id, version: r.version })).sort((a, b) => a.version - b.version)
  // The Citation panel shows a claim of the shown answer or of a follow-up turn; a claim that is no longer there closes it.
  const citeClaim = !citeClaimId ? null : answer?.claims.find(c => c.id === citeClaimId) ?? (() => {
    for (const turn of followups.turns) for (const c of turn.answer?.claims ?? []) if (followupClaimId(turn, c) === citeClaimId) return followupClaim(turn, c, view.sources)
    return null
  })()
  // The report's version select shows another version in the same panel: its stack entry is renamed in place, so the
  // stack keeps one report entry and Back still returns to the panel below it.
  const replacePanel = panels.replace
  const switchReport = (answerId: string) => {
    if (openReportId) replacePanel(`report:${openReportId}`, `report:${answerId}`)
    setOpenReportId(answerId)
  }
  // The Export menu's PDF row opens the report panel of the version the menu exports, then the print dialog on it.
  const printShownReport = (answerId: string) => { setOpenReportId(answerId); void printReport(answerId, toast) }
  const openCitation = (target: CitationOpen) => setPassageTarget({ passageId: target.passageId, highlightText: target.anchor, fromCitation: true, view: target.view, find: target.find })
  const answerVersion = answer?.report_version ?? 0
  const answerThread: AnswerThreadContext | undefined = answer ? {
    writing: answerRun && answer.status === 'structurally_valid' && latestVersion > 0 ? { next: latestVersion + 1, late: answer.late_revision_status?.status === 'answering' } : null,
    previous: (() => { const earlier = reports.find(r => r.answer.id !== answer.id && r.answer.scope_revision === answer.scope_revision && r.version < answerVersion); return earlier ? { id: earlier.answer.id, version: earlier.version } : null })(),
    reviewPending: view.runs.some(r => r.kind === 'answer_review' && ACTIVE.has(r.status) && r.target?.answer_id === answer.id),
    included, hasTable: (tables?.length ?? 0) > 0,
    canNewAnswer: !busy && !active && Boolean(included || answersWithoutInclude),
    downloadMenu: answer.status === 'structurally_valid' ? <ExportMenu icon researchId={id} report={{ answer, title: answer.report_title ?? heading, version: answerVersion }}
      sources={view.sources} tables={tables} included={included} cited={citedListed} prisma={Boolean(view.counts.flow)} onPrintReport={printShownReport} /> : null,
    onPanel: (name, opener) => openPanel(name, { opener }),
    onShowSources: (filter, opener) => { setSourceFocus(null); setSourceFilter(filter); openPanel('sources', { opener }) },
    onRevise: () => reviseQuestion(),
    onNewAnswer: () => { void startAnswer() },
    onOpenReport: setOpenReportId,
    onCompare: () => { setChangesShown(true); setOpenReportId(answer.id) },
    citing: citeClaimId,
    onCite: claim => setCiteClaimId(claim.id),
    onAsk: text => setFollowupFill(previous => ({ text, request: (previous?.request ?? 0) + 1 })),
  } : undefined
  // A notice of the answer offers "Generate a new answer" when its evidence changed or it failed validation; the button
  // under the thread then leaves it to the notice, so the page has one.
  const answerOffersNew = Boolean(answer && (answer.status === 'unverified_draft' || (answer.status === 'structurally_valid' && (answer.source_text_changed || answer.applicability === 'stale_selection'))))
  // The too-broad notice's Search again (R21): the rewritten question becomes the next revision, which then searches.
  const rewriteAndSearch = async (question: string, keyTerms: string | null) => {
    if (!seedSearchReady) { toast('error', t('Choose a readable PDF to guide the search.')); return }
    await act(async () => {
      await api.reviseScope(id, question, view.research.version, keyTerms)
      await api.startRun(id, 'discovery', crypto.randomUUID())
    }, t('Question revised. The new revision searches.'))
  }
  // Move to Trash (R9) leaves the page; Undo restores the research from the Trash (D50) and opens it again.
  const moveToTrash = async () => {
    setBusy(true)
    try {
      await api.moveToTrash(id)
      onChanged()
      window.location.hash = '/'
      toast('success', t('Moved to Trash.'), { label: t('Undo'), run: () => {
        api.restore(id).then(() => { onChanged(); window.location.hash = `/research/${id}`; toast('success', t('Research restored.')) },
          (e: Error) => toast('error', t('Could not restore research: {message}', { message: e.message })))
      } })
    } catch (e) { toast('error', t('Could not move to Trash: {message}', { message: errorText(e) })) }
    finally { setBusy(false) }
  }
  // The research's latest run in the topbar chip; table, candidate and follow-up runs keep their own chips, which open the
  // panel that controls them.
  const mainRun = run && run.kind !== 'watch_check' && !CANDIDATE_KINDS.has(run.kind) && !TABLE_RUN_KINDS.has(run.kind)
    && (active || run.status === 'paused' || (run.status === 'failed' && TRANSCRIPT_KINDS.has(run.kind))) ? run : null
  // "Writing a new version" only once a valid report version exists; a clarification or an unverified draft is not one.
  const hasAnswer = reports.some(r => r.answer.run_id !== run?.id && r.answer.report_version !== null)
  // The earlier question revision and the report written for it (R12).
  const earlierRevision = view.research.current_scope_revision - 1
  const earlierReport = reports.find(r => r.answer.scope_revision === earlierRevision) ?? null
  // The ⋯ menu (R9): Rename, Activity, Candidates and Follow-up as drawn, Search again and Generate a new answer (§2.2),
  // then Move to Trash. From 1100px the rail opens the Sources, queue, PDF and table panels; under 1100px (no rail) the
  // menu keeps four rows for them, and for the report versions and evidence reports the rail lists (§0 rule 5).
  // A row with no mockup counterpart carries `research-menu-placement` (§2.2 and §0 rule 5).
  const panelRow = (name: string, label: string, Icon: typeof BookOpen, count: number | null, detail?: string) =>
    <DropdownMenuItem key={name} className={detail ? undefined : 'research-menu-placement'} onClick={() => { rowChosen.current = true; openPanel(name, { opener: moreButton.current }) }}>
      <Icon size={15} aria-hidden /><span>{t(label)}{count !== null && <> <span className="research-tab-count">{count}</span></>}{detail && <small>{t(detail)}</small>}</span>
    </DropdownMenuItem>
  return <PanelStackContext.Provider value={panels}><section className="research-view legacy-research">
    {/* The 46px topbar (mockup `.topbar`, R1–R9): the title, the chip of the latest run, "N waiting for you", Revise
        question, Export and the ⋯ menu. While the title is renamed its row takes the place of the title and the chips. */}
    <div className={`research-topbar${titleEditing ? ' is-editing' : ''}`} inert={Boolean(phone && panel)}>
      {titleEditing
        ? <TitleEditRow title={view.research.title} busy={busy} canSuggest={!active} onSave={saveTitle} onCancel={endTitleEdit} onSuggest={suggestTitle} />
        : <>
          <TitleButton text={heading} onStartEdit={beginTitleEdit} />
          {candidateRun && panel !== 'cands' && <button type="button" className="run-chip" aria-label={t('Open the Candidates panel to control this run')} onClick={() => { if (candidateRun.target?.candidate_id) setCandidateSelection({ id: candidateRun.target.candidate_id }); openPanel('cands') }}>
            <span className={`run-chip-dot${ACTIVE.has(candidateRun.status) ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels[candidateRun.kind])} · {t(runStatusLabels[candidateRun.status])}<ChevronRight size={13} aria-hidden />
          </button>}
          {watchRun && panel !== 'watch' && <button type="button" className="run-chip" aria-label={t('Open the Follow-up panel to control this run')} onClick={() => openPanel('watch')}>
            <span className={`run-chip-dot${ACTIVE.has(watchRun.status) ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels.watch_check)} · {t(runStatusLabels[watchRun.status])}<ChevronRight size={13} aria-hidden />
          </button>}
          {/* A table run is controlled in the Evidence table panel above its table; here its chip only opens that panel. */}
          {run && (active || run.status === 'paused') && TABLE_RUN_KINDS.has(run.kind) && panel !== 'table' && <button type="button" className="run-chip" title={t('Open the Evidence table panel to control this run')} onClick={() => openPanel('table')}>
            <span className={`run-chip-dot${active ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels[run.kind])} · {t(runStatusLabels[run.status])}<ChevronRight size={13} aria-hidden />
          </button>}
          {mainRun && <RunChip run={mainRun} hasAnswer={hasAnswer} busy={busy} inThread={TRANSCRIPT_KINDS.has(mainRun.kind) || mainRun.kind === 'followup_answer'} onControl={action => controlRun(mainRun, action)} />}
          {queueCount > 0 && <button type="button" className="wait-chip" onClick={showQueue}><Inbox size={16} aria-hidden />{t('{n} waiting for you', { n: queueCount })}</button>}
        </>}
      <Button ref={reviseButton} variant="ghost" size="sm" className="research-topbar-action research-revise" title={t('Revise question')} disabled={active} aria-expanded={Boolean(revising)}
        onClick={() => reviseQuestion()}><PencilLine size={16} className="size-4" aria-hidden /><span className="research-topbar-label">{t('Revise question')}</span></Button>
      {!titleEditing && <>
        <ExportMenu researchId={id} report={answer?.status === 'structurally_valid' ? { answer, title: answer.report_title ?? heading, version: answer.report_version ?? 0 } : null}
          sources={view.sources} tables={tables} included={included} cited={citedListed} prisma={Boolean(view.counts.flow)} onPrintReport={printShownReport} />
        <DropdownMenu onOpenChange={open => { if (open) rowChosen.current = false }}>
          <DropdownMenuTrigger render={<Button ref={moreButton} variant="ghost" size="icon-sm" className="research-more" aria-label={t('Research actions')} title={t('Research actions')} />}><Ellipsis size={16} aria-hidden /></DropdownMenuTrigger>
          <DropdownMenuContent align="start" sideOffset={6} collisionAvoidance={{ align: 'shift', fallbackAxisSide: 'none' }} className="research-actions-menu" finalFocus={() => (rowChosen.current ? false : moreButton.current)}>
            <DropdownMenuItem onClick={() => { rowChosen.current = true; beginTitleEdit() }}><PencilLine size={15} aria-hidden />{t('Rename')}</DropdownMenuItem>
            {panelRow('activity', 'Activity', Clock, null, 'Runs, status, time and model calls')}
            {panelRow('cands', 'Candidates', Lightbulb, candidateCount, 'Claims you test against the literature')}
            {panelRow('watch', 'Follow-up', Clock, followupCount.count, 'New works after this research ran')}
            {!railWide && <>
              <DropdownMenuSeparator />
              {panelRow('sources', 'Sources', BookOpen, view.sources.length)}
              {panelRow('queue', 'Awaiting your decision', Inbox, queueCount)}
              {panelRow('pdfs', 'Get more full text', FileText, waitingCount)}
              {panelRow('table', 'Evidence table', Table2, tables?.length ?? null)}
              {panelRow('funnel', 'Search funnel', Funnel, null)}
              {reports.filter(r => r.answer.id !== answer?.id).map(({ answer: older, version }) =>
                <DropdownMenuItem key={older.id} className="research-menu-placement" onClick={() => { rowChosen.current = true; setOpenReportId(older.id) }}>
                  <FileText size={15} aria-hidden /><span>{t('Report')} · V{version}</span>
                </DropdownMenuItem>)}
              {view.reportRuns.slice(1).map(item =>
                <DropdownMenuItem key={item.id} className="research-menu-placement" onClick={() => { rowChosen.current = true; setOpenEvidenceReportId(item.id) }}>
                  <FileText size={15} aria-hidden /><span>{t('Evidence report')}{item.report_version ? ` · V${item.report_version}` : ''}</span>
                </DropdownMenuItem>)}
            </>}
            {hasAcademic || answer ? <DropdownMenuSeparator /> : null}
            {hasAcademic && view.search_runs.length > 0 && <DropdownMenuItem className="research-menu-placement" disabled={busy || active || !seedSearchReady} onClick={() => { void startDiscovery() }}><Search size={15} aria-hidden /><span>{t('Search again')}</span></DropdownMenuItem>}
            {/* The Search plan panel (S23b) from anywhere: its plan step exists only once the current revision searched. */}
            {hasAcademic && <DropdownMenuItem className="research-menu-placement" onClick={() => { rowChosen.current = true; openPanel('plan', { opener: moreButton.current }) }}><PencilLine size={15} aria-hidden /><span>{t('Search plan')}</span></DropdownMenuItem>}
            {answer && <DropdownMenuItem className="research-menu-placement" disabled={busy || active || !(included || answersWithoutInclude)} onClick={() => { void startAnswer() }}><Sparkles size={15} aria-hidden /><span>{t('Generate a new answer')}</span></DropdownMenuItem>}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" disabled={busy || active} onClick={() => { void moveToTrash() }}><Trash2 size={15} aria-hidden />{t('Move to Trash')}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </>}
    </div>

    <div className={`research-split${panel ? ' has-panel' : ''}${panel && panels.wide ? ' is-wide' : ''}`}>
    {/* The thread scrolls on its own; the artifacts rail sits beside it while no panel is open. */}
    <div className="research-thread-col" inert={Boolean(phone && panel)}>
    <div className="research-thread-grid">
    <div className="research-body thread-inner">
    {earlierRevision > 0 && <EarlierRevision key={earlierRevision} researchId={id} revision={earlierRevision} intent={view.research.intent} answer={earlierReport} onOpenReport={setOpenReportId} />}
    {revising
      ? <RevisionForm question={view.scope.question} keyTerms={view.scope.key_terms ?? ''} nextRevision={view.research.current_scope_revision + 1} focus={revising.focus} focusRequest={revising.ask}
        conflict={reviseConflict} onRebase={() => setRevising(form => (form ? { ...form, revision: view.research.current_scope_revision } : form))}
        disabled={busy || active} onSubmit={(text, terms) => { void saveRevision(text, terms) }} onCancel={endRevise} />
      : <QuestionBubble question={view.scope.question} sourceScope={view.scope.source_scope} intent={view.research.intent} createdAt={view.scope.created_at} revision={view.research.current_scope_revision} />}
    {/* The evidence boundaries stay separate counts (AGENTS.md); each one opens the panel that can show it. Scope and depth close the line. */}
    <div className="session-meta research-facts" title={t('Unique, included, given and cited count works: versions of one work count once. “Given to the model” counts works whose passages were sent in the latest answer step; it is not a full-text reading claim.')}>
      <span className="research-revision">{t('Research')} · {t('revision {n}', { n: view.research.current_scope_revision })}</span>
      {/* A count is shown once it has something to say; a row of zeroes while the run works is noise, not a boundary. */}
      {([['unique', 'Unique works', 'all'], ['included', 'Included', 'included'], ['inspected', 'Given to the model', 'all'], ['cited', 'Cited', null]] as const)
        .map(([key, label, filter]) => [key, label, filter, key === 'cited' ? citedCount : view.counts[key]] as const)
        .filter(([, , , n]) => n > 0)
        .map(([key, label, filter, n]) => <button key={key} type="button" onClick={() => (filter ? showSources(filter) : showAnswer())}><strong>{n}</strong><span>{t(label)}</span></button>)}
      <span title={t('Where DEIXIS looks for sources')}><ScopeIcon size={13} aria-hidden />{t(scopeLabels[view.scope.source_scope])}</span>
      <span title={t('How much searching and reading a run may do')}><EffortIcon size={13} aria-hidden />{t('{effort} depth', { effort: t(effortLabels[view.scope.effort]) })}</span>
    </div>

      <div className="research-thread">
      {/* Table runs show on the Evidence tab and in Activity; the conversation tells search and answer runs. */}
      <Transcript view={{ ...view, runs: view.runs.filter(r => TRANSCRIPT_KINDS.has(r.kind)) }} modelText={modelText}
        onRetryFailedSearches={async target => { await act(() => api.controlRun(target.id, 'retry_failed'), t('Failed searches queued again.')) }}
        onChooseCodeQuery={async target => { await act(() => api.chooseCodeQuery(target.id), t('The run searches with the query built from the question’s words.')) }}
        onGiveKeyTerms={() => reviseQuestion('terms')}
        queueCount={queueCount} onOpenQueue={showQueue} onOpenPdfs={() => openPanel('pdfs')} onOpenFunnel={() => openPanel('funnel')}
        onControlRun={controlRun} onRewrite={rewriteAndSearch} busy={busy}
        onChooseModel={(target, role, opener, review) => setChooseModel({ run: target, role, opener, review })}
        onEditPlan={hasAcademic ? opener => openPanel('plan', { opener }) : undefined}
        emptyText={included ? t(included === 1 ? '{n} source is included. Generate an answer when your selection is ready.' : '{n} sources are included. Generate an answer when your selection is ready.', { n: included }) : t(hasAcademic ? 'Start an academic search, or attach PDFs.' : 'Attach PDFs, then generate an answer.')}
        latestAnswer={answer ? <><AnswerThread thread={answerThread} eventCursor={view.last_event_id} review={answerReview} researchId={id} title={answer.report_title ?? heading} version={answer.report_version ?? 0} answer={answer} sources={view.sources} busy={busy} dark={dark} reportOpen={openReportId === answer.id} onReportOpenChange={open => setOpenReportId(open ? answer.id : null)} onOpen={(passageId, highlightText) => setPassageTarget({ passageId, highlightText, fromCitation: true })} onAttachPdf={chooseSourcePdf}
          versions={reportVersions} latestVersion={latestVersion} onVersion={switchReport} changes={answer.status === 'structurally_valid' ? reportChanges(answer) : undefined} />{tableCards}</> : null} />
      {!answer && tableCards}
      {view.reportRuns[0] && <button type="button" className="report-artifact" onClick={() => setOpenEvidenceReportId(view.reportRuns[0].id)} aria-label={t('Open evidence report')}>
        <span className="report-artifact-preview" aria-hidden="true"><strong>{heading}</strong></span>
        <span className="report-artifact-copy"><span className="report-artifact-meta"><FileText size={13} aria-hidden />{view.reportRuns[0].status === 'valid' ? t('Evidence report · V{n}', { n: view.reportRuns[0].report_version ?? '' }) : view.reportRuns[0].status === 'draft' ? t('Evidence report · draft') : t('Evidence report · being written')}</span><strong>{heading}</strong>{view.reportRuns[0].status === 'in_progress' && <small role="status">{t(latestEvidenceReportRun?.status === 'paused' ? 'Report paused' : 'The report is being written.')}</small>}</span>
        <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
      </button>}
      {/* The PDFs guiding the search are chosen in the Search plan panel (§2.2, S23b). The thread keeps one line while
         something waits on the person: no readable PDF chosen yet, a chosen PDF that changed (accept its current text),
         or no search run yet. */}
      {seedLine && <div className="research-seed">
        <div><strong>{t('PDFs guiding the search')}</strong>
          {view.scope.seed_status === 'ready' || (view.scope.seed_status === 'stale' && view.scope.seeds.length)
            ? <p>{view.scope.seeds.map(seed => seed.title).join(' · ')}</p>
            : <p>{view.scope.seed_status === 'question_only'
                ? t('This earlier research searches from the question. Choose PDFs to guide a later search.')
                : t('Choose readable PDFs before searching scholarly providers.')}</p>}
        </div>
        {view.scope.seed_status === 'stale' && storedSeedIds.length > 0 &&
          <Button variant="outline" size="sm" disabled={busy || active} onClick={() => void saveSeeds(view.scope.seeds.map(seed => seed.source_version_id), true)}>{t('Use current PDF text')}</Button>}
        <Button variant="ghost" size="sm" className="quiet-action" onClick={e => openPanel('plan', { opener: e.currentTarget })}>{t('Choose PDFs')}</Button>
        {view.scope.seed_status === 'stale' && <Notice tone="attention">{t('A selected PDF changed or was removed. Select the current PDFs again before searching.')}</Notice>}
      </div>}
      {/* Before the first answer, the included sources without a PDF are named and the panel that gets them is one click
         away (D49); collecting, uploads and OCR live in that panel (UI parity S14, P40). */}
      {!answer && missingPdfs > 0 && !active && view.runs.some(r => r.kind === 'discovery' || r.kind === 'pdf_collection') && <p className="pdf-ready-lede thread-pdf-note">
        {t(missingPdfs === 1 ? '{n} included source has no PDF yet; an answer cites it from its abstract.' : '{n} included sources have no PDF yet; an answer cites them from their abstracts.', { n: missingPdfs })}{' '}
        <button type="button" className="link" onClick={e => openPanel('pdfs', { opener: e.currentTarget })}>{t('Get more full text')}</button></p>}
      {/* One next step after the last run: without an answer it is the primary action, with one the answer card's own "Open report" leads.
         While a run works there is no next step to offer, so the panel stays away rather than showing disabled buttons. */}
      {      active ? (run?.target?.pipeline ? <p className="pdf-ready-lede" role="status">{t('Building the study table. The app chose its columns itself; open the table to review them.')}</p> : null) : <><div className="answer-actions">
        {!answerOffersNew && <Button variant={answer ? 'outline' : 'default'} disabled={busy || active || !(included || answersWithoutInclude)} onClick={startAnswer}><Sparkles size={15} />{t(answer ? 'Generate a new answer' : 'Generate source-linked answer')}</Button>}
        {/* Searching again is a quiet text action; the first search of a research is still a button of its own. */}
        {hasAcademic && (view.search_runs.length
          ? <Button className="quiet-action" variant="ghost" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}>{t('Search again')}</Button>
          : <Button variant="outline" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}><Search size={15} />{t('Search providers')}</Button>)}
      </div><UploadedTextNote semantic={view.semantic} /></>}
      {/* Follow-up questions and their answers, oldest first (R31), then the sticky composer (R30). */}
      {followups.error && <Notice tone="error">{t('Could not load the follow-up questions: {error}', { error: followups.error })}</Notice>}
      {followups.turns.length > 0 && <div className="followup-turns">{followups.turns.map(turn => <FollowupTurnView key={turn.id} turn={turn} sources={view.sources}
        actions={{ busy: busy || asking, locked: anyActive, canSearch: hasAcademic, citing: citeClaimId, onCite: claim => setCiteClaimId(claim.id),
          // Resume hands focus to the run's chip in the topbar, as a resumed run of the thread does (controlRun).
          onControl: (runId, action) => { const target = view.runs.find(r => r.id === runId); if (target) controlRun(target, action); else void act(() => api.controlRun(runId, action)) },
          onAskAgain: question => { void askFollowup(question, crypto.randomUUID()) }, onSearchNew: turn => { void searchNewWorks(turn.question) } }} />)}</div>}
      <FollowupComposer disabledReason={anyActive ? t('Wait for the current run to finish before asking a follow-up.') : null} sending={asking}
        depthIcon={EffortIcon} depthLabel={t(effortLabels[view.scope.effort])} fill={followupFill} onSend={askFollowup}
        onAddPdfs={opener => openPanel('pdfs', { opener })} />
      </div>
    {/* The answer's PDF suggestions attach through the same picker as the Sources panel. */}
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void upload(e.target.files); e.target.value = '' }} />
    <input ref={sourceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void uploadToSource(e.target.files); e.target.value = '' }} />
    <input ref={replaceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void reviewReplacement(e.target.files); e.target.value = '' }} />

    </div>
    {/* Hidden, not removed, while a panel is open or the window is under 1100px: a panel opened from the rail hands focus back to its button. */}
    <Rail view={view} researchId={id} cited={citedCount} reports={reports} tables={tables} hidden={Boolean(panel)} candidateCount={candidateCount} followupCount={followupCount.count}
      openPanel={openPanel} onOpenReport={setOpenReportId} onOpenEvidenceReport={setOpenEvidenceReportId} onOpenTable={openTable} />
    </div>
    </div>
    {panel && <SplitPanel stack={panels} phone={phone} />}
    </div>

    {/* Each former tab is a panel; its content is unchanged and renders into the panel frame while it is open. */}
    <StackPanel name="sources" title={t('Sources')} icon={BookOpen} className="sources-panel-box">
      <section className="sources-panel" aria-labelledby="sources-heading">
      <TextRecoveryContext.Provider value={{ researchId: id, eventCursor: view.last_event_id, busy, acceptView: next => { setView(next); onChanged() }, reload: async () => { await load() } }}><SourcesPanel sources={view.sources} cited={citedClaims} citedVersions={citedVersionClaims} answerVersion={answer ? answerVersion : null} busy={busy} filter={sourceFilter} onFilter={setSourceFilter} cursor={view.last_event_id} effort={view.scope.effort} onChanged={async () => { await load(); onChanged() }} focus={sourceFocus} onFocus={setSourceFocus} picked={picked} onPick={setPicked} onRemoveFromResearch={source => { void askRemoval([source.source_version_id]) }}
        onSelect={(source, state) => act(() => api.select(id, source.source_version_id, state, source.selection.version))}
        onReason={(source, reason) => act(() => api.select(id, source.source_version_id, source.selection.state, source.selection.version, reason), t('Reason saved with your choice.'))}
        onOpen={source => setPdfTarget({ assetId: null, sourceVersionId: source.source_version_id, view: 'text' })}
        onAbstract={source => source.access.abstract_passage_id && setPassageTarget({ passageId: source.access.abstract_passage_id, highlightText: null, fromCitation: false })}
        onDiscoverPdf={source => { void discoverPdf(source) }} onAttachPdf={chooseSourcePdf} onAttachCandidate={(source, candidateId) => { void attachPdfCandidate(source, candidateId) }} onOpenPdf={(_, assetId) => setPdfTarget({ assetId })}
        onPlainText={(_, assetId) => setPdfTarget({ assetId, view: 'text' })}
        onRemoveAsset={removeSourcePdf} onReplaceAsset={chooseReplacement} onReextract={(source, assetId) => { void reextract(source, assetId) }} onRereadEquations={(source, assetId) => { void rereadEquations(source, assetId) }} pdfFinding={pdfFinding}
        ocr={{ tool: ocrTool, runs: view.runs, onRead: (source, assetId) => { void readWithOcr(source, assetId) } }}
        bar={{ researchId: id, active, onStartTable: askTableStart, onAddToTable: (table, ids) => { void addToTable(table, ids) }, onRemove: ids => { void askRemoval(ids) }, onSaveToLibrary: saveToLibrary }} /></TextRecoveryContext.Provider>
      {/* The live tools the mockup panel has no place for (§2.2), under the table: what the list means, adding sources,
         the English sentence, the search details and the removed sources. The flow counts are in the Search funnel panel. */}
      <div className="sources-extras">
      <div className="workspace-pane-head"><div><h2 id="sources-heading">{t('Sources and access')}</h2><p>{t('Only included sources are used when the answer is written. Undecided and excluded sources are left out.')}</p></div>
        <div className="section-actions">
          {included > 0 && <ExportLinks researchId={id} sources="included" />}
          {view.scope.source_scope !== 'academic' && <>
            <div className="source-add-actions">
              <Button className="source-action" variant="outline" disabled={busy} aria-expanded={zoteroOpen} onClick={() => setZoteroOpen(open => !open)}><ConnectionIcon id="zotero" />{t('Add from Zotero')}</Button>
              <Button className="source-action is-primary" variant="outline" disabled={busy} onClick={() => fileInput.current?.click()}><FileUp size={16} />{t('Attach PDF')}</Button>
            </div>
          </>}
        </div></div>
      {zoteroOpen && <ZoteroPanel busy={busy} onImport={importZotero} onClose={() => setZoteroOpen(false)} />}
      <EnglishQuestion researchId={id} view={view} busy={busy} onSaved={next => { setView(next); toast('success', t('English sentence saved for this question revision.')) }} />
      {view.search_runs.length > 0 && <details className="search-summary"><summary><span><Search size={14} aria-hidden />{t('Search details')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{t(view.search_runs.length === 1 ? '{n} provider search' : '{n} provider searches', { n: view.search_runs.length })}</small></summary><div className="search-summary-list">{view.search_runs.map(s => <div key={s.id}><span>“{s.query_text}”</span><small>{providerName(s.provider)} · {['completed', 'zero_results'].includes(s.status) ? t(s.status.replace('_', ' ')) : serviceErrorSentence({ kind: serviceKind(s.error?.service_kind ?? s.error?.error_kind ?? s.status, s.error?.http_status), service: providerName(s.provider), resetAt: s.error?.reset_at, effect: view.runs.find(r => r.id === s.run_id)?.status === 'completed' ? 'continued' : undefined })} · {t('{count} of {total} records', { count: s.result_count, total: s.provider_total ?? '?' })} · {t(s.access_mode)}{s.scope_revision !== view.research.current_scope_revision ? ` ${t('· for question revision {n}', { n: s.scope_revision })}` : ''}</small></div>)}</div></details>}
      {view.counts.removed > 0 && <p className="removed-summary"><ListMinus size={14} aria-hidden /><span>{t(view.counts.removed === 1 ? 'You removed {n} source from this research.' : 'You removed {n} sources from this research.', { n: view.counts.removed })}
        {view.counts.removed_found_again > 0 && ` ${t(view.counts.removed_found_again === 1 ? '{n} of them was found again by a later search and is not listed.' : '{n} of them were found again by a later search and are not listed.', { n: view.counts.removed_found_again })}`}</span>
        <a href="#/trash">{t('Show in Trash')}</a></p>}
      </div>
      </section>
    </StackPanel>
    <StackPanel name="queue" title={`${t('Awaiting your decision')} (${queueCount})`} icon={Inbox}>
      <HumanQueue researchId={id} view={view} dark={dark} onChanged={async () => { await load(); onChanged() }} />
    </StackPanel>
    <StackPanel name="pdfs" title={t('Get more full text')} icon={FileText}>
      <WaitingForPdf researchId={id} view={view} busy={busy} onChanged={async (announced?: string) => { if (announced) announcedRuns.current.add(announced); await load(); onChanged() }}
        included={<PdfReadiness researchId={id} view={view} busy={busy} act={async (action, success) => { await act(action, success) }} onUpload={chooseSourcePdf} ocrTool={ocrTool} onReadWithOcr={(source, assetId) => { void readWithOcr(source, assetId) }} />}
        answerAction={{ label: answer ? t('Generate a new answer (V{n})', { n: latestVersion + 1 }) : t('Generate source-linked answer'), disabled: busy || active || !(included || answersWithoutInclude), onClick: () => { void startAnswer() } }}
        onSearchAgain={hasAcademic && seedSearchReady ? startDiscovery : null} />
    </StackPanel>
    <StackPanel name="funnel" title={t('Search funnel')} icon={Funnel}>
      <FunnelPanel researchId={id} view={view} answer={answer ?? null} cited={citedCount} queueCount={queueCount} busy={busy} active={active}
        onPanel={(name, opener) => openPanel(name, { opener })} onShowSources={(filter, opener) => { setSourceFocus(null); setSourceFilter(filter); openPanel('sources', { opener }) }}
        onChanged={async () => { await load(); onChanged() }} />
      {/* The audit sample (slice 20) sits below the stages, collapsed (§2.2). */}
      <details className="funnel-more queue-panel"><summary><ChevronRight size={14} aria-hidden className="queue-decided-chevron" />{t('Audit sample')}</summary>
        <AuditSample researchId={id} lastEvent={view.last_event_id} onChanged={async () => { await load(); onChanged() }}
          onOpenSource={svid => setPdfTarget({ assetId: null, sourceVersionId: svid, view: 'text' })} onShowInSources={showInSources} />
      </details>
    </StackPanel>
    <StackPanel name="table" title={t('Evidence table')} icon={Table2} className="table-panel-box">
      <EvidenceTab researchId={id} view={view} dark={dark} initialTableId={focusTable?.id ?? null} tableRequest={focusTable?.request ?? 0} cell={focusTable?.cell ?? null} onCellShown={cellShown} modelText={modelText} onRunStarted={() => { void load(); onChanged() }} />
    </StackPanel>
    <StackPanel name="watch" title={t('Follow-up')} icon={Clock}>
      <FollowUpView researchId={id} view={view} dark={dark} onReload={followupCount.reload} onChanged={followupChanged} />
    </StackPanel>
    {answerReviewTarget && <ReviewSurface surface={answerReviews} researchId={id} targetKind="answer" targetId={answerReviewTarget.id} version={answerReviewTarget.version} eventCursor={view.last_event_id}
      runActive={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} sources={view.sources} sectionLabel={ref => ref} dark={dark} open={openPassage}
      changed={async () => { setAnswerReviewRevision(n => n + 1) }} />}
    <StackPanel name="cands" title={t('Candidates')} icon={Lightbulb} keepMounted>
      <CandidatesView researchId={id} view={view} dark={dark} modelText={modelText} selection={candidateSelection} onCount={setCandidateCount} onRunChanged={() => { void load(); onChanged() }}
        onOpenSource={svid => setPdfTarget({ assetId: null, sourceVersionId: svid, view: 'text' })} />
    </StackPanel>
    <StackPanel name="activity" title={t('Activity')} icon={Clock}>
      <ActivityPanel researchId={id} eventCursor={view.last_event_id} events={events} />
    </StackPanel>
    {/* The Search plan panel (P42, S23b; D12): the stored plan of the revision it names, edited and searched again. */}
    <StackPanel name="plan" title={t('Search plan')} icon={PencilLine}>
      <PlanPanel researchId={id} view={view} busy={busy} searchReady={seedSearchReady} answerRevision={answer ? answer.scope_revision : null}
        seeds={seedChoice} onAnnounced={runId => announcedRuns.current.add(runId)} onChanged={async () => { await load(); onChanged() }} onClose={closePanels} />
    </StackPanel>
    <ChooseModelDialog key={chooseModel?.run.id ?? 'none'} target={chooseModel} view={view} dark={dark} onClose={() => setChooseModel(null)} onChanged={next => { setView(next); onChanged() }}
      onReload={async () => { const read = await load(); onChanged(); return read }} onReviewStarted={async runId => { announcedRuns.current.add(runId); await load(); onChanged() }} />
    <ConfirmDialog open={Boolean(removeTarget)} dark={dark} title={t('Remove PDF?')}
      description={t('This PDF will not be used in future answers. Existing answers that used the source will be marked outdated.')}
      context={removeTarget?.source.title} confirmLabel={t('Remove PDF')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={confirmRemoveSourcePdf} onOpenChange={open => { if (!open) setRemoveTarget(null) }} />
    <ConfirmDialog open={Boolean(removal)} dark={dark} neutral
      title={t(removal?.ids.length === 1 ? 'Remove the source from this research?' : 'Remove {n} sources from this research?', { n: removal?.ids.length ?? 0 })}
      description={removal ? [t(removal.ids.length === 1 ? 'It leaves this research’s source list, answer input and tables; its table cells are kept. The library record and its PDF are not deleted, and earlier quotes keep opening. You can restore it from the notification or the Trash.' : 'They leave this research’s source list, answer input and tables; their table cells are kept. The library record and its PDF are not deleted, and earlier quotes keep opening. You can restore them from the notification or the Trash.'),
        removal.versions > 0 && t(removal.versions === 1 ? '{n} other version of these works goes with them.' : '{n} other versions of these works go with them.', { n: removal.versions }),
        removal.elsewhere ? t(removal.elsewhere === 1 ? '{n} of them is also used in other research, where nothing changes.' : '{n} of them are also used in other research, where nothing changes.', { n: removal.elsewhere }) : ''].filter(Boolean).join(' ') : ''}
      context={removal ? inSourceOrder(removal.ids).map(s => s.title).join(' · ') : undefined} confirmLabel={t('Remove from research')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={confirmRemoval} onOpenChange={open => { if (!open) setRemoval(null) }} />
    <ConfirmDialog open={Boolean(tableStart)} dark={dark} neutral
      title={t('Start a table from {n} sources?', { n: tableStart?.ids.length ?? 0 })}
      description={tableStart ? t(tableStart.notIncluded === 1 ? '{k} of them is not included. A table row does not change its selection, and the answer still reads included sources only.' : '{k} of them are not included. A table row does not change their selection, and the answer still reads included sources only.', { k: tableStart.notIncluded }) : ''}
      confirmLabel={t('Start table')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={() => { const target = tableStart; setTableStart(null); if (target) void startTable(target.ids) }} onOpenChange={open => { if (!open) setTableStart(null) }} />
    <ConfirmDialog open={Boolean(replaceTarget)} dark={dark} title={t('Replace PDF?')}
      description={replaceTarget ? `${t('{file} will be read in later answers and cells instead of the current file. The current file is not deleted: evidence that cites it keeps opening it.', { file: replaceTarget.file.name })} ${t(replaceTarget.impact.researches.length === 1 ? 'The source is used in {n} research;' : 'The source is used in {n} researches;', { n: replaceTarget.impact.researches.length })} ${t('{cells} evidence table cells and {quotes} answer quotes cite the current file.', { cells: replaceTarget.impact.cells, quotes: replaceTarget.impact.quotes })}` : ''}
      context={replaceTarget?.source.title} confirmLabel={t('Replace PDF')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={confirmReplacement} onOpenChange={open => { if (!open) setReplaceTarget(null) }} />
    {olderReport && <AnswerThread eventCursor={view.last_event_id} review={answerReview} researchId={id} title={olderReport.title} version={olderReport.version} answer={olderReport.answer} sources={view.sources} busy={busy} dark={dark} showCard={false}
      reviewPending={view.runs.some(r => r.kind === 'answer_review' && ACTIVE.has(r.status) && r.target?.answer_id === olderReport.answer.id)}
      reportOpen onReportOpenChange={open => { if (!open) setOpenReportId(null) }} onOpen={openPassage} onAttachPdf={chooseSourcePdf}
      versions={reportVersions} latestVersion={latestVersion} onVersion={switchReport} changes={reportChanges(olderReport.answer)} />}
    {openEvidenceReportId && <ReportView key={openEvidenceReportId} researchId={id} reportId={openEvidenceReportId} view={view} tables={tables} title={heading} dark={dark} onClose={() => setOpenEvidenceReportId(null)}
      onOpenCell={(tableId, cell) => { setOpenEvidenceReportId(null); showTableFirst(tableId, cell); openPanel('table') }}
      onOpenCandidate={candidate => { setOpenEvidenceReportId(null); setCandidateSelection({ ...candidate, id: candidate.card?.id ?? candidate.id }); openPanel('cands') }}
      onOpenCitation={(passageId, highlightText, expectHighlight) => setPassageTarget({ passageId, highlightText, fromCitation: expectHighlight, reportCitation: true })}
      onChanged={async () => { await load(); onChanged() }} />}
    <CitationPanel researchId={id} claim={citeClaim} sources={view.sources} onClose={() => setCiteClaimId(null)} onOpen={openCitation} />
    <PassageSheet asPanel={!passageTarget?.reportCitation} researchId={id} passageId={passageTarget?.passageId ?? null} assetId={pdfTarget?.assetId ?? null} sourceVersionId={pdfTarget?.sourceVersionId ?? null} initialView={pdfTarget ? pdfTarget.view ?? 'pdf' : passageTarget?.view ?? 'text'}
      findOnOpen={Boolean(passageTarget?.find)} latestAnswer={answer?.status === 'structurally_valid' ? { version: answerVersion, claims: answer.claims } : null}
      actions={passageTarget?.reportCitation ? undefined : { busy, finding: pdfFinding, onFind: discoverPdf, onAttach: chooseSourcePdf, onReplace: chooseReplacement,
        onRemove: source => { void askRemoval([source.source_version_id]) }, onReextract: (source, assetId) => { void reextract(source, assetId) }, onRereadEquations: (source, assetId) => { void rereadEquations(source, assetId) },
        ocr: { tool: ocrTool, runs: view.runs, onRead: (source, assetId) => { void readWithOcr(source, assetId) } } }} highlightText={passageTarget?.highlightText} expectHighlight={passageTarget?.fromCitation} citationLabels={passageTarget?.reportCitation ? { marked: t('Exact text cited in this report'), mark: t('Exact text cited in this report'), unmarked: t('This report citation has no located text anchor, so its passage opens without a mark.') } : undefined} sources={view.sources} dark={dark} onClose={() => { setPassageTarget(null); setPdfTarget(null) }}
      onRestoreSource={svid => { setPassageTarget(null); void act(() => api.restoreSources(id, [svid]), t('Restored to this research.')) }} />
  </section></PanelStackContext.Provider>
}
