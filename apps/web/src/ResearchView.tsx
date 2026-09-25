import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Activity, ArrowUpDown, ArrowUpRight, BadgeCheck, Ban, BookOpenText, ChevronRight, CircleCheck, CircleDot, CircleX, Copy, Download, FilePlus2, FileText, FileUp, Filter, Hand, Info, ListChecks, ListMinus, ListPlus, LoaderCircle, Replace, RotateCcw, ScanText, Sigma, MessageSquareQuote, Pause, PencilLine, Play, Quote, RotateCw, Search, ShieldCheck, Sparkles, Table2, Trash2, Upload, UserPen, X, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip } from '@/components/ui/tooltip'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, ApiError, bibliographyUrl, subscribe, type ActivityEvent, type Answer, type AssetImpact, type Evidence, type Limitation, type ResearchView, type Run, type OcrTool, type RunKind, type RunStatus, type Source, type TableSummary, type ValidationIssue, type Verdict, type ZoteroSource } from './api'
import { accessParts, citedText, fetchReasonText, locatorText, pauseReasonText, providerName, queueAnsweredText, runKindLabels, runStatusLabels, scopeLabels, searchQueryTriesLeft, stepLabel, verdictLabels, versionText, versionTones } from './labels'
import { PassageSheet } from './PassageSheet'
import { Elapsed, EvidenceTab, TABLE_RUN_KINDS } from './EvidenceTable'
import { MathText } from './MathText'
import { Transcript } from './Transcript'
import { PdfReadiness } from './PdfReadiness'
import { ZoteroPanel } from './ZoteroPanel'
import { useToast, type ToastAction } from './Toast'
import { ConnectionIcon } from './connectionIcons'
import { ModelName } from './ModelName'
import { useModelText } from './modelText'
import { ConfirmDialog } from './ConfirmDialog'
import { effortLabels, effortOptions, Option, scopeOptions } from './Home'
import { citationStyles, formatReference, formatReferenceText, type CitationStyle } from './citations'
import { OCR_LABEL, ocrLanguagesText, ocrOffer } from './ocr'
import { OcrButton, OcrNote } from './OcrNote'
import { t, uiLocale } from './i18n'
import { SourceKey } from './SourceKey'
import { scrollBehavior } from './motion'
import { Notice } from './Notice'
import { HumanQueue } from './HumanQueue'
import { AnswerFlowNote, FlowBlock } from './FlowReport'
import { WaitingForPdf } from './WaitingForPdf'
import { EnglishQuestion, UploadedTextNote } from './SemanticNotes'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A research title wraps across the whole column, so the rename field grows with its text instead of scrolling sideways.
function sizeTitleField(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function TypewriterTitle({ text, onStartEdit }: { text: string; onStartEdit: () => void }) {
  const [shown, setShown] = useState(text)
  const previous = useRef(text)

  useEffect(() => {
    if (previous.current === text) return
    previous.current = text
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const frame = requestAnimationFrame(() => setShown(text))
      return () => cancelAnimationFrame(frame)
    }
    const started = performance.now()
    // Slow enough to read as typing: about 28 ms a character, within 0.6–2.6 s.
    const duration = Math.min(2600, Math.max(600, text.length * 28))
    let frame = 0
    const write = (now: number) => {
      const count = Math.ceil(Math.min(1, (now - started) / duration) * text.length)
      setShown(text.slice(0, count))
      if (count < text.length) frame = requestAnimationFrame(write)
    }
    frame = requestAnimationFrame(write)
    return () => cancelAnimationFrame(frame)
  }, [text])

  const writing = shown.length < text.length
  // The title is renamed in place: double-click, or Enter/F2 once the title has focus. The heading stays a heading, so the
  // full text keeps its aria-label; the sidebar's action menu is the labeled path for assistive technology.
  return <h1
    className={`research-title-text${writing ? ' is-typing' : ''}`}
    aria-label={text}
    tabIndex={0}
    title={t('Double-click to rename')}
    onDoubleClick={onStartEdit}
    onKeyDown={event => {
      if (event.key !== 'Enter' && event.key !== 'F2') return
      event.preventDefault()
      onStartEdit()
    }}
  ><span aria-hidden>{shown}</span></h1>
}

export function ResearchPage({ id, initialTab, dark, onChanged }: { id: string; initialTab?: string; dark: boolean; onChanged: () => void }) {
  const [view, setView] = useState<ResearchView | null>(null)
  const [titleEditing, setTitleEditing] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [error, setError] = useState('')
  const toast = useToast()
  const [tab, setTab] = useState(initialTab === 'sources' || initialTab === 'queue' || initialTab === 'waiting' || initialTab === 'evidence' || initialTab === 'artifacts' || initialTab === 'activity' ? initialTab : 'answer')
  const [passageTarget, setPassageTarget] = useState<{ passageId: string; highlightText: string | null; fromCitation: boolean } | null>(null)
  const [pdfTarget, setPdfTarget] = useState<{ assetId: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  // The counts under the question open the Sources tab, so the selection filter lives here rather than inside the list.
  const [sourceFilter, setSourceFilter] = useState<StateFilter>('all')
  // One work the audit sample sent the person to (slice 20): the Sources list shows that work alone, by its id.
  const [sourceFocus, setSourceFocus] = useState<string | null>(null)
  // Leaving the Sources tab ends that focus: coming back shows the whole list.
  const goTab = (next: string) => { if (next !== 'sources') setSourceFocus(null); setTab(next) }
  const [pdfFinding, setPdfFinding] = useState<string | null>(null)
  const [waitingFiles, setWaitingFiles] = useState<File[] | null>(null)
  const takeWaitingFiles = useCallback(() => setWaitingFiles(null), [])
  const [attachTarget, setAttachTarget] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<{ source: Source; assetId: string } | null>(null)
  // Replacing a PDF: the file is chosen first, then the confirmation names what still cites the old file (D45).
  const [replacePick, setReplacePick] = useState<{ source: Source; assetId: string } | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<{ source: Source; assetId: string; file: File; impact: AssetImpact } | null>(null)
  const [openReportId, setOpenReportId] = useState<string | null>(null)
  // Sources chosen for a table or for removal (D50). Kept only while the Sources tab is open.
  const [picked, setPicked] = useState<string[]>([])
  const [removal, setRemoval] = useState<{ ids: string[]; versions: number; elsewhere: number | null } | null>(null)
  const [tableStart, setTableStart] = useState<{ ids: string[]; notIncluded: number } | null>(null)
  const [focusTable, setFocusTable] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceFileInput = useRef<HTMLInputElement>(null)
  const replaceFileInput = useRef<HTMLInputElement>(null)
  const firstEvent = useRef<number | null>(null)
  const tabsRef = useRef<HTMLDivElement>(null)
  // A run stopped for key terms sends the user here, to the one field that answers it.
  const keyTerms = useRef<HTMLInputElement>(null)
  const jumped = useRef(false)
  const lastRun = useRef<{ id: string; status: RunStatus } | null>(null)
  // Runs another toast already announced when they were opened (a person's file whose attach opened its reading, 18b).
  const announcedRuns = useRef(new Set<string>())
  const titleInput = useRef<HTMLTextAreaElement>(null)
  // An edit session ends once: Enter, Escape or the blur that follows either one must not save a second time.
  const titleEditDone = useRef(true)
  const titleEditingRef = useRef(false)

  const load = useCallback(async () => {
    try {
      const next = await api.research(id)
      setView(next)
      // A reload arrives on every recorded event; it must not overwrite what is being typed into the open field.
      if (!titleEditingRef.current) setTitleDraft(next.research.title)
      setError('')
      if (firstEvent.current === null) firstEvent.current = next.last_event_id
    } catch (e) { setError(errorText(e)) }
  }, [id])
  useEffect(() => { void load() }, [load])
  // The field exists only while editing, so this is also where it takes focus, selects the current title for replacing, and
  // grows to the height the title needs at this width.
  useEffect(() => {
    titleEditingRef.current = titleEditing
    if (!titleEditing) return
    titleInput.current?.focus()
    titleInput.current?.select()
    sizeTitleField(titleInput.current)
  }, [titleEditing])
  // Tables of this research, for the Evidence count and the table cards; refreshed on every recorded event (a table created, edited, trashed or restored).
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  const lastEventId = view?.last_event_id
  useEffect(() => {
    let live = true
    api.tables(id).then(list => { if (live) setTables(list) }, () => { /* the count and cards are left out */ })
    return () => { live = false }
  }, [id, lastEventId])
  // Codex lists each model's default effort; a research created without an effort runs at that default.
  const modelText = useModelText()

  const loaded = view !== null
  useEffect(() => {
    // Opened at a tab (e.g. from quick find): bring the tabs into view and put keyboard focus on the chosen tab.
    if (!loaded || !initialTab || jumped.current) return
    jumped.current = true
    tabsRef.current?.scrollIntoView({ block: 'start' })
    tabsRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus({ preventScroll: true })
  }, [loaded, initialTab])

  useEffect(() => {
    if (!loaded) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = subscribe(id, firstEvent.current ?? 0, () => { clearTimeout(timer); timer = setTimeout(() => { void load(); onChanged() }, 250) })
    return () => { stop(); clearTimeout(timer) }
  }, [id, loaded, load, onChanged])

  // The local Tesseract is asked once a PDF has pages without text, so its rows can offer OCR or say why it is off (D51).
  const needsOcr = Boolean(view?.sources.some(s => s.access.assets.some(a => a.ocr?.pages_without_text && a.extraction_status !== 'succeeded')))
  useEffect(() => {
    if (!needsOcr) return
    api.ocr().then(setOcrTool).catch(e => toast('error', t('Could not check the OCR tool: {error}', { error: errorText(e) })))
  }, [needsOcr, toast])

  useEffect(() => {
    if (tab !== 'activity') return
    api.events(id).then(setEvents).catch(e => toast('error', t('Could not load activity: {error}', { error: errorText(e) })))
  }, [tab, id, view?.last_event_id, toast])

  // Runs finish in the background, often while another tab is open: announce each status change of the latest run.
  useEffect(() => {
    const current = view?.runs[0]
    if (!view || !current) return
    const previous = lastRun.current
    lastRun.current = { id: current.id, status: current.status }
    if (!previous || (previous.id === current.id && previous.status === current.status)) return
    const label = t(current.kind === 'answer' ? 'Answer generation' : runKindLabels[current.kind])
    const reason = pauseReasonText(current.pause_reason)
    if (previous.id !== current.id) { if (ACTIVE.has(current.status) && !announcedRuns.current.has(current.id)) toast('success', t('{label} started.', { label })); return }
    switch (current.status) {
      case 'completed': {
        if (current.kind !== 'discovery' && current.kind !== 'answer') { toast('success', current.kind === 'cell_recheck' ? t('Recheck finished. Its result waits as a proposal in the cell.') : t('{label} finished.', { label })); break }
        const answer = view.answers.find(a => a.run_id === current.id)
        if (current.kind === 'discovery') toast('success', t('Search & screening finished. Review the sources and include the ones to use.'))
        else if (answer?.status === 'structurally_valid') toast('success', t('Answer ready.'))
        else if (answer?.status === 'clarification') toast('warning', t('The model needs a clarification before it can answer.'))
        else if (answer?.status === 'no_evidence') toast('warning', t('No answer: no text passages were available for the included sources.'))
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
    setBusy(true)
    try { await action(); if (success) toast('success', success, undo); await load(); onChanged() }
    catch (e) {
      // 409: the research or run changed after this page loaded (another tab, or a run that moved on).
      if (e instanceof ApiError && e.status === 409) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message })); await load() }
      else toast('error', errorText(e))
    } finally { setBusy(false) }
  }

  if (error && !view) return <section className="research-view"><Notice tone="error">{t('Could not open this research: {error}', { error })}</Notice></section>
  if (!view) return <section className="research-view"><p className="session-meta">{t('Loading research…')}</p></section>

  const run = view.runs[0] as Run | undefined
  const active = run ? ACTIVE.has(run.status) : false
  const answer = view.answers[0] as Answer | undefined
  const hasAcademic = view.scope.source_scope !== 'attached'
  const needsSeed = view.scope.source_scope === 'attached_and_academic' && view.scope.seed_mode === 'uploaded_seed'
  const seedSearchReady = !needsSeed || view.scope.seed_status === 'ready'
  const seedCandidates = view.sources.filter(source =>
    (source.origin === 'user_upload' || source.added_by === 'zotero_import' || source.added_by === 'library')
    && source.has_pdf_text && source.access.assets.length > 0)
  const included = view.counts.included

  const startAnswer = () => act(() => api.startRun(id, 'answer', crypto.randomUUID()))
  const startDiscovery = () => {
    if (!seedSearchReady) { toast('error', t('Choose a readable PDF to guide the search.')); return }
    return act(() => api.startRun(id, 'discovery', crypto.randomUUID()))
  }
  const selectSeed = (sourceId: string) => act(() => api.setSeed(id, sourceId, view.research.version), t('PDF selected for the next search.'))
  const startTitle = () => act(() => api.startRun(id, 'research_title', crypto.randomUUID()))
  const upload = (list: FileList | null) => list && act(async () => { for (const file of Array.from(list)) await api.upload(id, file) }, t('PDF added and included. Its text was extracted page by page (no OCR).'))
  const uploadToSource = (list: FileList | null) => list && attachTarget && act(async () => {
    for (const file of Array.from(list)) await api.uploadToSource(id, attachTarget, file)
  }, t('PDF attached to this source. Its text was extracted page by page (no OCR).'))
  const discoverPdf = async (source: Source) => {
    setPdfFinding(source.source_version_id)
    try { await api.discoverPdf(id, source.source_version_id); await load(); onChanged() }
    catch (e) { toast('error', errorText(e)) }
    finally { setPdfFinding(null) }
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
    void act(() => api.replaceAsset(id, source.source_version_id, assetId, file), t('PDF replaced. Its text was extracted page by page (no OCR); earlier evidence still opens the previous file.'))
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
    if (notes.length) toast('warning', `${added} ${notes.map(n => `${n.title}: ${n.note}.`).join(' ')}`)
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
    setFocusTable(created.table.id)
    goTab('evidence')
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
    setFocusTable(table.id)
    goTab('evidence')
  }, t('Rows added to {title}.', { title: table.title }))

  const ScopeIcon = scopeOptions[view.scope.source_scope].icon
  const EffortIcon = effortOptions[view.scope.effort].icon
  const beginTitleEdit = () => { setTitleDraft(view.research.title); titleEditDone.current = false; setTitleEditing(true) }
  const cancelTitle = () => { titleEditDone.current = true; setTitleDraft(view.research.title); setTitleEditing(false) }
  const commitTitle = () => {
    if (titleEditDone.current) return
    titleEditDone.current = true
    const next = titleDraft.trim()
    setTitleEditing(false)
    if (!next || next === view.research.title) { setTitleDraft(view.research.title); return }
    void act(() => api.renameResearch(id, next, view.research.version), t('Research title saved.'), undefined)
  }
  // The stored title is the question cut to 160 characters until a valid answer names the research (D36); until then show it whole.
  const heading = view.scope.question.startsWith(view.research.title) ? view.scope.question : view.research.title
  // Each count is the way into the evidence it describes; the selection filter lives here so a count can set it.
  const showSources = (filter: StateFilter) => { setSourceFocus(null); setSourceFilter(filter); goTab('sources'); tabsRef.current?.scrollIntoView({ block: 'start' }) }
  // An abstract-stage work of the audit sample is chosen with the source list's own controls: the list opens at that
  // work alone, found by its id (two works can share a title).
  const showInSources = (workId: string) => { showSources('all'); setSourceFocus(workId) }
  const showAnswer = () => { goTab('answer'); requestAnimationFrame(() => document.getElementById('research-answer')?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })) }
  // Reports are the research's artifacts: every answer that passed validation, newest first, with the number and title saved with it.
  const reports = view.answers.filter(a => a.status === 'structurally_valid').map(a => ({ answer: a, version: a.report_version ?? 0, title: a.report_title ?? heading }))
  // The latest report's sheet lives in its card on the Answer tab; from any other tab, or for an older version, it opens here.
  const olderReport = reports.find(r => r.answer.id === openReportId && (r.answer.id !== answer?.id || tab !== 'answer'))
  const openTable = (tableId: string) => { setFocusTable(tableId); goTab('evidence'); tabsRef.current?.scrollIntoView({ block: 'start' }) }
  // Table cards sit under the report card, or at the end of the conversation before the first answer.
  const tableCards = tables && tables.length > 0 && <div className="table-artifacts">{tables.map(table => <TableCard key={table.id} table={table} onOpen={() => openTable(table.id)} />)}</div>
  const openPassage = (passageId: string, highlightText: string | null) => setPassageTarget({ passageId, highlightText, fromCitation: true })
  // The human queue is an sw research's own surface (slice 17); a legacy research has no such tab.
  const hasQueue = view.scope.search_workflow === 'sw'
  const queueCount = (view.counts.queue ?? 0) + (view.counts.look_again ?? 0)
  const showQueue = () => { goTab('queue'); setPicked([]); tabsRef.current?.scrollIntoView({ block: 'start' }) }
  // Files dropped on the PDF panel of an sw research go to the waiting view's version-checked match (slice 18a).
  const waitingCount = view.counts.waiting_for_pdf ?? 0
  const dropForWaiting = (files: File[]) => { setWaitingFiles(files); goTab('waiting'); setPicked([]); tabsRef.current?.scrollIntoView({ block: 'start' }) }
  return <section className="research-view legacy-research">
    {/* The hint takes the row that already exists above the title: reserving it there keeps the field from pushing the counts down
        while the title is edited, and it leaves the scope revision readable. */}
    <div className={`section-label${titleEditing ? ' is-editing' : ''}`}>
      <span>{t('Research')} <span>· {t('revision {n}', { n: view.research.current_scope_revision })}</span></span>
      {titleEditing && <span className="research-title-hint" id="research-title-hint">
        {titleDraft.length > 120
          ? `${t('Enter saves, Escape cancels')} · ${t('{count} of 160 characters', { count: String(titleDraft.length) })}`
          : t('Enter saves, Escape cancels')}
      </span>}
    </div>
    {titleEditing
      ? <div className="research-title-block">
        {/* While the title is being edited the heading gives way to the field: a heading whose whole content is a field has no
            name to announce. The field restates the heading's type recipe (see .research-title-input) so nothing moves. */}
        <textarea
          ref={titleInput}
          className="research-title-input"
          aria-label={t('Research title')}
          aria-describedby="research-title-hint"
          value={titleDraft}
          rows={1}
          maxLength={160}
          spellCheck={false}
          onChange={e => { setTitleDraft(e.target.value); sizeTitleField(e.target) }}
          onKeyDown={e => {
            if (e.key === 'Enter') { e.preventDefault(); commitTitle() }
            else if (e.key === 'Escape') { e.preventDefault(); cancelTitle() }
          }}
          onBlur={commitTitle}
        />
      </div>
      : <div className="research-title-block">
        <TypewriterTitle text={heading} onStartEdit={beginTitleEdit} />
        {heading === view.scope.question && !active && run?.status !== 'paused' && <Button variant="ghost" size="sm" className="research-title-suggest" disabled={busy} onClick={startTitle}
          title={t('The model names the research from its question and included sources, in at most 15 words.')}><Sparkles size={14} aria-hidden />{t('Suggest a short title')}</Button>}
      </div>}
    {/* The evidence boundaries stay separate counts (AGENTS.md); each one opens the tab that can show it. Scope and depth close the line. */}
    <div className="session-meta research-facts" title={t('Unique, included, given and cited count works: versions of one work count once. “Given to the model” counts works whose passages were sent in the latest answer step; it is not a full-text reading claim.')}>
      {/* A count is shown once it has something to say; a row of zeroes while the run works is noise, not a boundary. */}
      {([['found', 'Found', 'all'], ['unique', 'Unique works', 'all'], ['included', 'Included', 'included'], ['inspected', 'Given to the model', 'all'], ['cited', 'Cited', null]] as const)
        .filter(([key]) => view.counts[key] > 0)
        .map(([key, label, filter]) => <button key={key} type="button" onClick={() => (filter ? showSources(filter) : showAnswer())}><strong>{view.counts[key]}</strong><span>{t(label)}</span></button>)}
      <span title={t('Where DEIXIS looks for sources')}><ScopeIcon size={13} aria-hidden />{t(scopeLabels[view.scope.source_scope])}</span>
      <span title={t('How much searching and reading a run may do')}><EffortIcon size={13} aria-hidden />{t('{effort} depth', { effort: t(effortLabels[view.scope.effort]) })}</span>
    </div>

    <div ref={tabsRef}><Tabs className="research-tabs" value={tab} onValueChange={value => { goTab(String(value)); setPicked([]) }}>
      <div className="research-tabs-bar">
        <TabsList><TabsTrigger value="answer">{t('Answer')}</TabsTrigger><TabsTrigger value="sources">{t('Sources')} <span className="research-tab-count">{view.sources.length}</span></TabsTrigger>{hasQueue && <TabsTrigger value="queue">{t('Awaiting your decision')} <span className="research-tab-count">{queueCount}</span></TabsTrigger>}{hasQueue && <TabsTrigger value="waiting">{t('Waiting for your PDF')} <span className="research-tab-count">{waitingCount}</span></TabsTrigger>}<TabsTrigger value="evidence">{t('Evidence')}{tables && <> <span className="research-tab-count">{tables.length}</span></>}</TabsTrigger><TabsTrigger value="artifacts">{t('Artifacts')} <span className="research-tab-count">{reports.length + (tables?.length ?? 0)}</span></TabsTrigger><TabsTrigger value="activity">{t('Activity')}</TabsTrigger></TabsList>
        {/* The live run carries its own quiet Pause; these controls ride with the tabs so pause, resume and cancel stay reachable from every tab.
            A table run is controlled on the Evidence tab above its table; elsewhere the bar only links there. */}
        {run && (active || run.status === 'paused') && TABLE_RUN_KINDS.has(run.kind) ? tab !== 'evidence' && <button type="button" className="run-chip" title={t('Open the Evidence tab to control this run')} onClick={() => { goTab('evidence'); setPicked([]) }}>
          <span className={`run-chip-dot${active ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels[run.kind])} · {t(runStatusLabels[run.status])}<ChevronRight size={13} aria-hidden />
        </button>
        : run && (active || run.status === 'paused') && <div className="run-strip">
          <span className="run-strip-status">{active && <LoaderCircle size={13} className="chat-spin" aria-hidden />}{t(runKindLabels[run.kind])} · {t(runStatusLabels[run.status])}</span>
          {active && run.status !== 'pause_requested' && <Button variant="ghost" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'pause'))}><Pause size={14} />{t('Pause')}</Button>}
          {/* A run stopped for the approval has no plain Resume: it would freeze a protocol nobody saw, and the
              backend refuses it. The approval card in the timeline carries the only way on (D80). */}
          {run.status === 'paused' && run.pause_reason !== 'protocol_approval_needed'
            && !(run.pause_reason === 'search_query_failed' && searchQueryTriesLeft(run) === 0) && <Button variant="default" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'resume'))}><Play size={14} />{t('Resume')}</Button>}
          <Button variant="destructive" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'cancel'))}><X size={14} />{t('Cancel')}</Button>
        </div>}
      </div>

      <TabsContent value="answer">
        {/* Table runs show on the Evidence tab and in Activity; the conversation tells search and answer runs. */}
        <Transcript view={{ ...view, runs: view.runs.filter(r => r.kind === 'discovery' || r.kind === 'pdf_collection' || r.kind === 'fulltext_fetch' || r.kind === 'fulltext_adjudication' || r.kind === 'pdf_ocr' || r.kind === 'answer') }} modelText={modelText}
          onRetryFailedSearches={target => act(() => api.controlRun(target.id, 'retry_failed'), t('Failed searches queued again.'))}
          onProtocolApproved={async () => { toast('success', t('Correction recorded. The run is queued again.')); await load(); onChanged() }}
          onChooseCodeQuery={target => act(() => api.chooseCodeQuery(target.id), t('The run searches with the query built from the question’s words.'))}
          onGiveKeyTerms={() => { keyTerms.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' }); keyTerms.current?.focus({ preventScroll: true }) }}
          queueCount={hasQueue ? queueCount : 0} onOpenQueue={showQueue}
          emptyText={included ? t(included === 1 ? '{n} source is included. Generate an answer when your selection is ready.' : '{n} sources are included. Generate an answer when your selection is ready.', { n: included }) : t(hasAcademic ? 'Start an academic search, or attach PDFs.' : 'Attach PDFs, then generate an answer.')}
          latestAnswer={answer ? <><AnswerBlock researchId={id} title={answer.report_title ?? heading} version={answer.report_version ?? 0} answer={answer} sources={view.sources} busy={busy} dark={dark} reportOpen={openReportId === answer.id} onReportOpenChange={open => setOpenReportId(open ? answer.id : null)} onOpen={(passageId, highlightText) => setPassageTarget({ passageId, highlightText, fromCitation: true })} onAttachPdf={chooseSourcePdf} />{tableCards}</> : null} />
        {!answer && tableCards}
        {view.scope.source_scope === 'attached_and_academic' && <div className="research-seed">
          <div><strong>{t('PDF guiding the search')}</strong><p>{view.scope.seed_status === 'ready'
            ? t('{n} PDF passages were given to the search planner from {title}.', { n: view.scope.seed?.passage_count ?? 0, title: view.scope.seed?.title ?? '' })
            : view.scope.seed_status === 'question_only'
              ? t('This earlier research searches from the question. Choose a PDF to guide a later search.')
              : t('Choose a readable PDF before searching scholarly providers.')}</p></div>
          <Select value={view.scope.seed?.source_version_id ?? ''} onValueChange={value => { if (value) void selectSeed(value) }}>
            <SelectTrigger aria-label={t('PDF guiding the search')} disabled={busy || active || !seedCandidates.length}>
              <SelectValue placeholder={t('Choose PDF')}>{(value: string) =>
                seedCandidates.find(source => source.source_version_id === value)?.title ?? view.scope.seed?.title ?? t('Choose PDF')
              }</SelectValue>
            </SelectTrigger>
            <SelectContent align="end">{seedCandidates.map(source =>
              <SelectItem key={source.source_version_id} value={source.source_version_id}>{source.title}</SelectItem>)}</SelectContent>
          </Select>
          {view.scope.seed_status === 'stale' && view.scope.seed && seedCandidates.some(source => source.source_version_id === view.scope.seed?.source_version_id) &&
            <Button variant="outline" size="sm" disabled={busy || active} onClick={() => void selectSeed(view.scope.seed!.source_version_id)}>{t('Use current PDF text')}</Button>}
          {view.scope.seed_status === 'stale' && <Notice tone="attention">{t('The selected PDF changed or was removed. Select a current PDF again before searching.')}</Notice>}
          {view.scope.seed_status === 'ready' && view.scope.seed?.page_count != null && view.scope.seed.text_pages < view.scope.seed.page_count &&
            <Notice tone="attention">{t('Some PDF pages have no extracted text; the search uses only the readable passages.')}</Notice>}
          {!seedCandidates.length && <Notice tone="attention">{t('Attach a PDF with readable text, or read scanned pages with OCR, to guide the search.')}</Notice>}
        </div>}
        {/* Before the first answer, the next step is getting the included sources' PDFs (D49); the panel carries the answer button. */}
        {!answer && included > 0 && !(active && run?.kind !== 'pdf_collection' && run?.kind !== 'pdf_ocr') && view.runs.some(r => r.kind === 'discovery' || r.kind === 'pdf_collection') ? <PdfReadiness researchId={id} view={view} busy={busy} hasAcademic={hasAcademic && seedSearchReady} act={act} onSearchAgain={startDiscovery} onAnswer={startAnswer} onUpload={chooseSourcePdf} ocrTool={ocrTool} onReadWithOcr={(source, assetId) => { void readWithOcr(source, assetId) }} onDropFiles={hasQueue ? dropForWaiting : undefined} /> :
        /* One next step after the last run: without an answer it is the primary action, with one the answer card's own "Open report" leads.
           While a run works there is no next step to offer, so the panel stays away rather than showing disabled buttons. */
        active ? null : <><div className="answer-actions">
          <Button variant={answer ? 'outline' : 'default'} disabled={busy || active || !included} onClick={startAnswer}><Sparkles size={15} />{t(answer ? 'Generate a new answer' : 'Generate source-linked answer')}</Button>
          {/* Searching again is a quiet text action; the first search of a research is still a button of its own. */}
          {hasAcademic && (view.search_runs.length
            ? <Button className="quiet-action" variant="ghost" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}>{t('Search again')}</Button>
            : <Button variant="outline" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}><Search size={15} />{t('Search providers')}</Button>)}
        </div><UploadedTextNote semantic={view.semantic} /></>}
      </TabsContent>

      <TabsContent value="sources">
        <section className="sources-panel" aria-labelledby="sources-heading">
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
        <FlowBlock researchId={id} counts={view.counts} />
        {view.search_runs.length > 0 && <details className="search-summary"><summary><span><Search size={14} aria-hidden />{t('Search details')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{t(view.search_runs.length === 1 ? '{n} provider search' : '{n} provider searches', { n: view.search_runs.length })}</small></summary><div className="search-summary-list">{view.search_runs.map(s => <div key={s.id}><span>“{s.query_text}”</span><small>{providerName(s.provider)} · {t(s.status.replace('_', ' '))} · {t('{count} of {total} records', { count: s.result_count, total: s.provider_total ?? '?' })} · {t(s.access_mode)}{s.scope_revision !== view.research.current_scope_revision ? ` ${t('· for question revision {n}', { n: s.scope_revision })}` : ''}</small></div>)}</div></details>}
        {view.counts.removed > 0 && <p className="removed-summary"><ListMinus size={14} aria-hidden /><span>{t(view.counts.removed === 1 ? 'You removed {n} source from this research.' : 'You removed {n} sources from this research.', { n: view.counts.removed })}
          {view.counts.removed_found_again > 0 && ` ${t(view.counts.removed_found_again === 1 ? '{n} of them was found again by a later search and is not listed.' : '{n} of them were found again by a later search and are not listed.', { n: view.counts.removed_found_again })}`}</span>
          <a href="#/trash">{t('Show in Trash')}</a></p>}
        <SourceList sources={view.sources} busy={busy} filter={sourceFilter} onFilter={setSourceFilter} focus={sourceFocus} onFocus={setSourceFocus} picked={picked} onPick={setPicked} onRemoveFromResearch={source => { void askRemoval([source.source_version_id]) }}
          onSelect={(source, state) => act(() => api.select(id, source.source_version_id, state, source.selection.version))}
          onReason={(source, reason) => act(() => api.select(id, source.source_version_id, source.selection.state, source.selection.version, reason), t('Reason saved with your choice.'))}
          onAbstract={source => source.access.abstract_passage_id && setPassageTarget({ passageId: source.access.abstract_passage_id, highlightText: null, fromCitation: false })}
          onDiscoverPdf={source => { void discoverPdf(source) }} onAttachPdf={chooseSourcePdf} onAttachCandidate={(source, candidateId) => { void attachPdfCandidate(source, candidateId) }} onOpenPdf={(_, assetId) => setPdfTarget({ assetId })}
          onRemoveAsset={removeSourcePdf} onReplaceAsset={chooseReplacement} onReextract={(source, assetId) => { void reextract(source, assetId) }} onRereadEquations={(source, assetId) => { void rereadEquations(source, assetId) }} pdfFinding={pdfFinding}
          ocr={{ tool: ocrTool, runs: view.runs, onRead: (source, assetId) => { void readWithOcr(source, assetId) } }} />
        {picked.length > 0 && <SelectionBar researchId={id} count={picked.length} busy={busy} active={active} onStartTable={() => askTableStart(picked)} onAddToTable={table => { void addToTable(table, picked) }}
          onRemove={() => { void askRemoval(picked) }} onClear={() => setPicked([])} />}
        </section>
      </TabsContent>

      {hasQueue && <TabsContent value="queue">
        <HumanQueue researchId={id} view={view} dark={dark} onChanged={async () => { await load(); onChanged() }} onShowInSources={showInSources} />
      </TabsContent>}

      {hasQueue && <TabsContent value="waiting">
        <WaitingForPdf researchId={id} view={view} busy={busy} incoming={waitingFiles} onIncomingTaken={takeWaitingFiles} onChanged={async (announced?: string) => { if (announced) announcedRuns.current.add(announced); await load(); onChanged() }} />
      </TabsContent>}

      <TabsContent value="evidence">
        <EvidenceTab researchId={id} view={view} dark={dark} initialTableId={focusTable} modelText={modelText} onRunStarted={() => { void load(); onChanged() }} />
      </TabsContent>

      <TabsContent value="artifacts">
        {reports.length || tables?.length ? <ul className="artifact-list">{reports.map(({ answer: a, version, title }) => <li key={a.id}><button type="button" onClick={() => setOpenReportId(a.id)}>
          <FileText size={16} aria-hidden /><span><strong>{title}</strong><small>{t('Report')} · V{version}{a.applicability !== 'current' ? ` · ${t('earlier')}` : ''} · {new Date(a.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })}</small></span><ArrowUpRight size={15} aria-hidden />
        </button></li>)}
          {tables?.map(table => <li key={table.id}><button type="button" onClick={() => openTable(table.id)}>
            <Table2 size={16} aria-hidden /><span><strong>{table.title}</strong><small>{tableFacts(table)} · {new Date(table.updated_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })}</small></span><ArrowUpRight size={15} aria-hidden />
          </button></li>)}</ul> : <p className="empty-inline">{t('No reports yet. Generate a source-linked answer to create one.')}</p>}
      </TabsContent>

      <TabsContent value="activity">
        <ActivityLog events={events} />
      </TabsContent>
    </Tabs></div>
    {/* Outside the tabs: the answer's PDF suggestions attach through the same picker as the Sources tab. */}
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void upload(e.target.files); e.target.value = '' }} />
    <input ref={sourceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void uploadToSource(e.target.files); e.target.value = '' }} />
    <input ref={replaceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void reviewReplacement(e.target.files); e.target.value = '' }} />

    <RevisionForm key={view.research.version} question={view.scope.question} disabled={busy || active}
      keyTerms={view.scope.search_workflow === 'sw' ? view.scope.key_terms ?? '' : null} keyTermsRef={keyTerms}
      onSubmit={(text, terms) => act(() => api.reviseScope(id, text, view.research.version, terms), t('Question revised. Earlier answers stay visible and are marked as belonging to the previous revision.'))} />
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
    <PassageSheet researchId={id} passageId={passageTarget?.passageId ?? null} assetId={pdfTarget?.assetId ?? null} initialView={pdfTarget ? 'pdf' : 'text'} highlightText={passageTarget?.highlightText} expectHighlight={passageTarget?.fromCitation} sources={view.sources} dark={dark} onClose={() => { setPassageTarget(null); setPdfTarget(null) }}
      onRestoreSource={svid => { setPassageTarget(null); void act(() => api.restoreSources(id, [svid]), t('Restored to this research.')) }} />
    {olderReport && <AnswerBlock researchId={id} title={olderReport.title} version={olderReport.version} answer={olderReport.answer} sources={view.sources} busy={busy} dark={dark} showCard={false}
      reportOpen onReportOpenChange={open => { if (!open) setOpenReportId(null) }} onOpen={openPassage} onAttachPdf={chooseSourcePdf} />}
  </section>
}

const tableFacts = (table: TableSummary) => [t('Table'), t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns })].join(' · ')

// An evidence table as an artifact card beside the report card; it opens the table on the Evidence tab.
function TableCard({ table, onOpen }: { table: TableSummary; onOpen: () => void }) {
  return <button type="button" className="report-artifact" onClick={onOpen} aria-label={t('Open table: {title}', { title: table.title })}>
    <span className="report-artifact-preview table-artifact-preview" aria-hidden="true">{Array.from({ length: 5 }, (_, r) => <i key={r} />)}</span>
    <span className="report-artifact-copy">
      <span className="report-artifact-meta"><Table2 size={13} strokeWidth={1.8} aria-hidden />{tableFacts(table)}</span>
      <strong>{table.title}</strong>
    </span>
    <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
  </button>
}

function reportFilename(title: string, version: number) {
  const base = title.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase().slice(0, 80)
  return `${base || 'deixis-report'}-v${version}.md`
}

async function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  const field = document.createElement('textarea')
  field.value = text
  field.style.position = 'fixed'
  field.style.opacity = '0'
  document.body.appendChild(field)
  field.select()
  const copied = document.execCommand('copy')
  field.remove()
  if (!copied) throw new Error('copy failed')
}

function AnswerBlock({ researchId, title, version, answer, sources, busy, dark, reportOpen, onReportOpenChange, showCard = true, onOpen, onAttachPdf }: { researchId: string; title: string; version: number; answer: Answer; sources: Source[]; busy: boolean; dark: boolean; reportOpen: boolean; onReportOpenChange: (open: boolean) => void; showCard?: boolean; onOpen: (passageId: string, highlightText: string | null) => void; onAttachPdf: (source: Source) => void }) {
  const modelText = useModelText()
  const [style, setStyle] = useState<CitationStyle>(() => { try { const saved = localStorage.getItem('deixis-citation-style'); return saved && Object.keys(citationStyles).includes(saved) ? saved as CitationStyle : 'apa' } catch { return 'apa' } })
  const [copied, setCopied] = useState(false)
  const toast = useToast()
  const chooseStyle = (next: CitationStyle) => { setStyle(next); try { localStorage.setItem('deixis-citation-style', next) } catch { /* the choice still applies for this tab */ } }
  if (answer.status === 'clarification' && answer.clarification) {
    return <div className="legacy-answer"><div className="section-label">{t('Clarification needed')}</div><h2>{answer.clarification.question}</h2><p>{answer.clarification.why_it_matters}</p>{answer.clarification.options.length > 0 && <ul className="plain-list">{answer.clarification.options.map(o => <li key={o}>{o}</li>)}</ul>}<p className="legacy-mini-note">{t('Revise the question below to continue.')}</p></div>
  }
  if (answer.status === 'no_evidence') {
    return <><Notice tone="attention">{t('No text passages were available for the included sources (no abstract, no retrievable PDF text). No answer was generated.')}</Notice><AnswerFlowNote answer={answer} /></>
  }
  if (answer.status === 'unverified_draft') {
    return <div className="legacy-answer"><Notice tone="error">{t('The model output failed validation after one repair attempt, so it is not shown as a cited answer.')}<ul className="plain-list">{answer.validation.issues?.map(i => <li key={`${i.code}${i.path}`}>{t('{code} at {path}', { code: i.code, path: i.path })}</li>)}</ul></Notice>
      {answer.unverified_draft?.claims?.map(c => <p className="claim is-unverified" key={c.claim_label}><MathText text={c.text} /></p>)}<AnswerFlowNote answer={answer} /></div>
  }
  const refs = new Map<string, { n: number; e: Answer['claims'][number]['evidence'][number] }>()
  answer.claims.forEach(c => c.evidence.forEach(e => { if (!refs.has(e.passage_id)) refs.set(e.passage_id, { n: refs.size + 1, e }) }))
  // A citation names its source's key (D59); a claim citing two passages of one source adds each passage's place.
  const citeLabel = (claim: Answer['claims'][number], e: Evidence) => {
    if (!e.source_key) return `${refs.get(e.passage_id)?.n}`
    const repeated = claim.evidence.filter(x => x.source_version_id === e.source_version_id).length > 1
    return repeated ? `${e.source_key}, ${e.kind === 'abstract' ? t('abstract') : e.physical_page ? t('p. {page}', { page: e.physical_page }) : t('section')}` : e.source_key
  }
  // Consecutive claims with the same heading form one report section; answers saved before sections have no heading.
  const sections: { heading: string | null; claims: Answer['claims'] }[] = []
  answer.claims.forEach(c => { const last = sections[sections.length - 1]; if (last && last.heading === c.section) last.claims.push(c); else sections.push({ heading: c.section, claims: [c] }) })
  // An access limitation shown with the PDF suggestions is not repeated under Limits.
  const suggestion = pdfSuggestion(answer, sources)
  const limits = answer.limitations.filter(l => !suggestion?.notes.includes(l))
  const markdown = () => {
    const lines = [`# ${title}`, '', `${t('Report')} · V${version}`, '']
    if (answer.applicability === 'stale_scope') lines.push(`> ${t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}`, '')
    if (answer.applicability === 'stale_selection') lines.push(`> ${t('Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.')}`, '')
    if (answer.capability_notice) lines.push(`> ${answer.capability_notice}`, '')
    sections.forEach(({ heading, claims }) => {
      if (heading) lines.push(`## ${heading}`, '')
      claims.forEach(claim => {
        const citations = claim.evidence.map(e => `[${citeLabel(claim, e)}]`).join('')
        const inference = claim.support_type === 'analyst_inference' ? ` _(${t('interpretation')})_` : ''
        const review = claim.review ? ` _${t('Reviewer: {reason}', { reason: `${t(verdictLabels[claim.review.verdict])} — ${claim.review.reason}` })}_` : ''
        lines.push(`${claim.text}${citations ? ` ${citations}` : ''}${inference}${review}`, '')
      })
    })
    if (!answer.claims.length) lines.push(t('No claim could be linked to the passages given to the model.'), '')
    if (answer.unanswered_aspects.length) lines.push(`## ${t('Not answered by the inspected passages')}`, '', ...answer.unanswered_aspects.map(item => `- ${item}`), '')
    if (limits.length) lines.push(`## ${t('Limits')}`, '', ...limits.map(limit => `- **${t(limit.kind.replace('_', ' '))}:** ${limit.text}`), '')
    if (refs.size) {
      lines.push(`## ${t('Cited passages')}`, '')
      refs.forEach(({ n, e }) => {
        const source = sources.find(s => s.source_version_id === e.source_version_id)
        lines.push(`[${e.source_key ?? n}] ${source ? formatReferenceText(style, source) : e.title} — ${locatorText(e)}${e.text_source === 'ocr' ? ` (${t(OCR_LABEL)})` : ''}`)
      })
      lines.push('')
    }
    lines.push(`---`, '', t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.'))
    return `${lines.join('\n').trim()}\n`
  }
  const copyReport = async () => {
    try { await writeClipboard(markdown()); setCopied(true); toast('success', t('Report copied to clipboard.')) }
    catch { toast('error', t('Could not copy the report.')) }
  }
  const downloadReport = () => {
    const url = URL.createObjectURL(new Blob([markdown()], { type: 'text/markdown;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = reportFilename(title, version)
    link.click()
    URL.revokeObjectURL(url)
  }
  const preview = answer.claims.slice(0, 2).map(claim => claim.text).join(' ')
  const report = <div className="legacy-answer report-content">
    <div className="section-label">{t('Source-linked answer')}{answer.applicability === 'stale_scope' ? ` · ${t('earlier question revision')}` : answer.applicability === 'stale_selection' ? ` · ${t('earlier source selection')}` : ''}</div>
    {answer.applicability === 'stale_scope' && <Notice tone="attention">{t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}</Notice>}
    {answer.applicability === 'stale_selection' && <Notice tone="attention">{t('Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.')}</Notice>}
    {answer.source_text_changed && <Notice tone="attention">{t('A PDF this answer read was replaced, removed or had its text extracted again after the answer was generated. Its quotes still open the text that was read; generate a new answer to read the current text.')}</Notice>}
    {answer.capability_notice && <Notice tone="info">{answer.capability_notice}</Notice>}
    {sections.map(({ heading, claims }, index) => <section className="answer-section" key={index}>
      {heading && <h3>{heading}</h3>}
      {claims.map(claim => <p className="claim" key={claim.id}>
        <MathText text={claim.text} />{claim.support_type === 'analyst_inference' && <span className="support-badge">{t('interpretation')}</span>}
        {claim.evidence.map(e => <button key={e.passage_id} className="cite-chip" title={[e.title, versionText(e.version_label), locatorText(e), e.text_source === 'ocr' && t(OCR_LABEL), e.removed_from_research && t('Removed from this research')].filter(Boolean).join(' · ')} onClick={() => onOpen(e.passage_id, e.anchor_text)}>{e.source_key ? citeLabel(claim, e) : `[${refs.get(e.passage_id)?.n}]`}</button>)}
        {claim.review && <span className={`review-badge is-${claim.review.verdict}`} title={t('Reviewer: {reason}', { reason: claim.review.reason })}><ShieldCheck size={11} aria-hidden />{t(verdictLabels[claim.review.verdict])}</span>}
        {claim.review && claim.review.verdict !== 'supported' && <small className="review-reason">{t('Reviewer: {reason}', { reason: claim.review.reason })}</small>}
      </p>)}
    </section>)}
    {!answer.claims.length && <p>{t('No claim could be linked to the passages given to the model.')}</p>}
    {answer.unanswered_aspects.length > 0 && <><h3>{t('Not answered by the inspected passages')}</h3><ul className="plain-list">{answer.unanswered_aspects.map(a => <li key={a}><MathText text={a} /></li>)}</ul></>}
    {limits.length > 0 && <><h3>{t('Limits')}</h3><ul className="plain-list">{limits.map((l, i) => <li key={i}><em>{t(l.kind.replace('_', ' '))}:</em> <MathText text={l.text} /></li>)}</ul></>}
    {refs.size > 0 && <>
      <div className="reference-head"><h3>{t('Cited passages')}</h3>
        <div className="reference-tools"><ExportLinks researchId={researchId} sources="cited" />
        <Select value={style} onValueChange={value => { if (value) chooseStyle(value as CitationStyle) }}>
          <SelectTrigger aria-label={t('Citation style')} title={t('How the cited sources are written')}><SelectValue>{(value: string) => <><Quote size={14} />{t(citationStyles[value as CitationStyle].label)}</>}</SelectValue></SelectTrigger>
          <SelectContent className="intake-select-content has-details" align="end" alignItemWithTrigger={false}>
            <div className="intake-select-heading" aria-hidden="true">{t('Citation style')}</div>
            {(Object.keys(citationStyles) as CitationStyle[]).map(k => <SelectItem key={k} value={k}><Option icon={Quote} title={t(citationStyles[k].label)} detail={t(citationStyles[k].detail)} /></SelectItem>)}
          </SelectContent>
        </Select></div>
      </div>
      <ol className="reference-list">{[...refs.values()].map(({ n, e }) => {
        const source = sources.find(s => s.source_version_id === e.source_version_id)
        const locator = locatorText(e)
        return <li key={e.passage_id}><button onClick={() => onOpen(e.passage_id, e.anchor_text)}>
          {e.source_key ? <SourceKey value={e.source_key} className="ref-key" /> : <span className="ref-num">[{n}]</span>}
          <span className="ref-body">
            <span className="ref-text">{source ? formatReference(style, source) : e.title}</span>
            <span className="ref-pills">
              <span className={`ref-pill ${e.kind === 'abstract' ? 'is-abstract' : 'is-text'}`}>{e.kind === 'abstract' ? <BookOpenText size={12} aria-hidden /> : <FileText size={12} aria-hidden />}{locator.charAt(0).toUpperCase() + locator.slice(1)}</span>
              <span className={`ref-pill is-${versionTones[e.version_label ?? ''] ?? 'unstated'}`}><BadgeCheck size={12} aria-hidden />{versionText(e.version_label)}</span>
              {e.text_source === 'ocr' && <span className="ref-pill is-ocr"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}
              {e.removed_from_research && <span className="ref-pill is-removed"><ListMinus size={12} aria-hidden />{t('Removed from this research')}</span>}
            </span>
          </span>
        </button></li>
      })}</ol>
    </>}
    <p className="legacy-mini-note">{t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.')} {answer.model && <>{t('Model')}: <ModelName connection={answer.model.connection} text={modelText(answer.model.resolved_model ?? answer.model.requested_model ?? t('unknown'))} />.</>} {answer.inputs_given ? t('{passages} passages from {sources} sources were provided.', { passages: answer.inputs_given.passages, sources: answer.inputs_given.sources }) : ''}</p>
    <AnswerFlowNote answer={answer} />
    <ReviewNote review={answer.review} />
    <ChecksNote warnings={answer.validation.warnings} />
    {suggestion && <PdfSuggestions notes={suggestion.notes} sources={suggestion.sources} busy={busy} onAttachPdf={onAttachPdf} />}
  </div>
  return <>
    {/* The "Cited" count above the tabs scrolls here: the answer card is where the citations live. */}
    {showCard && <button type="button" id="research-answer" className="report-artifact" onClick={() => onReportOpenChange(true)} aria-label={t('Open report: {title}', { title })}>
      <span className="report-artifact-preview" aria-hidden="true"><strong>{title}</strong><span>{preview}</span></span>
      <span className="report-artifact-copy">
        <span className="report-artifact-meta"><Sparkles size={13} strokeWidth={1.8} aria-hidden />{t('Report')} · V{version}</span>
        <strong>{title}</strong>
      </span>
      <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
    </button>}
    {showCard && <AnswerFlowNote answer={answer} />}
    <Sheet open={reportOpen} onOpenChange={open => { onReportOpenChange(open); if (!open) setCopied(false) }}>
      <SheetContent className={`detail-sheet report-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader className="report-toolbar">
          <div className="report-toolbar-title"><FileText size={17} aria-hidden /><SheetTitle>{title}</SheetTitle></div>
          <SheetDescription className="sr-only">{t('Source-linked research report, version {n}.', { n: version })}</SheetDescription>
          <div className="report-toolbar-actions">
            <Button variant="ghost" size="sm" onClick={() => { void copyReport() }}>{copied ? <CircleCheck size={16} /> : <Copy size={16} />}{t(copied ? 'Copied' : 'Copy')}</Button>
            <Button variant="ghost" size="sm" onClick={downloadReport}><Download size={16} />{t('Download')}</Button>
          </div>
        </SheetHeader>
        <div className="report-scroll">
          <article className="report-document">
            <header className="report-document-head"><p>{t('Report')} · V{version}</p><h1>{title}</h1><time>{new Date(answer.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time></header>
            {report}
          </article>
        </div>
      </SheetContent>
    </Sheet>
  </>
}

// Sources the answer could read only from their abstracts and that still have no PDF. The model's access limitations name
// them and say what their full text would settle; an answer without such a limitation lists its cited sources that lack a PDF.
function pdfSuggestion(answer: Answer, sources: Source[]): { notes: Limitation[]; sources: Source[] } | null {
  if (answer.status !== 'structurally_valid' || answer.applicability === 'stale_scope') return null
  const lacking = (ids: string[]) => [...new Set(ids)]
    .map(id => sources.find(s => s.source_version_id === id && s.origin === 'provider' && !s.access.assets.length))
    .filter((s): s is Source => Boolean(s))
  const notes = answer.limitations.filter(l => l.kind === 'access' && lacking(l.source_ids).length > 0)
  const listed = lacking(notes.length ? notes.flatMap(l => l.source_ids) : answer.claims.flatMap(c => c.evidence.map(e => e.source_version_id)))
  return listed.length ? { notes, sources: listed } : null
}

function PdfSuggestions({ notes, sources, busy, onAttachPdf }: { notes: Limitation[]; sources: Source[]; busy: boolean; onAttachPdf: (source: Source) => void }) {
  const tip = t('Sources the answer read only from their abstracts and that have no PDF yet. An attached PDF is read page by page (no OCR).')
  return <section className="pdf-suggest" aria-labelledby="pdf-suggest-title">
    <div className="pdf-suggest-head">
      <Upload size={18} aria-hidden />
      <div>
        <strong id="pdf-suggest-title">{t('PDF uploads suggested')}<span className="pdf-suggest-info" title={tip}><Info size={14} aria-hidden /><span className="sr-only">{tip}</span></span></strong>
        <small>{t('Attached PDFs stay with this research; generate a new answer to use their text.')}</small>
      </div>
    </div>
    <div className="pdf-suggest-body">
      {notes.length ? notes.map((l, i) => <p key={i}><MathText text={l.text} /></p>)
        : <p>{t('The answer cited these sources from their abstracts only. Their full text can add details the abstracts leave out.')}</p>}
      <ul className="pdf-suggest-list">{sources.map(source => {
        const href = source.doi ? `https://doi.org/${source.doi}` : source.landing_url
        return <li key={source.source_version_id}>
          <SourceKey value={source.source_key} />
          <span className="pdf-suggest-title" title={source.title}>{source.title}</span>
          <span className="pdf-suggest-actions">
            {href && <a href={href} target="_blank" rel="noreferrer" title={t('Opens the source page in a new tab')}><ArrowUpRight size={14} aria-hidden />{t('Get PDF')}</a>}
            <button type="button" disabled={busy} onClick={() => onAttachPdf(source)} aria-label={t('Attach a PDF to {title}', { title: source.title })}><Upload size={14} aria-hidden />{t('Attach PDF')}</button>
          </span>
        </li>
      })}</ul>
    </div>
  </section>
}

const phrasingCodes = new Set(['sentence_without_phrasebank_frame', 'own_work_phrase_in_claim', 'plural_sources_for_one_source'])
const mathLabels: Record<string, string> = {
  math_not_well_formed: 'Math is not well formed',
  math_without_full_text: 'Math cites abstract text only',
  ocr_numbers_unchecked: 'Number or equation read only from OCR text',
  anchor_not_in_passage: 'Citation opens without a highlight',
  missing_citation_anchor: 'Citation opens without a highlight',
}
const checkCodes = new Set([...phrasingCodes, ...Object.keys(mathLabels)])

// Prose and math findings are listed with the answer; they never reject it (D19).
function ChecksNote({ warnings }: { warnings?: ValidationIssue[] }) {
  const found = (warnings ?? []).filter(w => checkCodes.has(w.code))
  if (!found.length) return null
  const phrasingOnly = found.every(w => phrasingCodes.has(w.code))
  const summary = phrasingOnly
    ? (found.length === 1 ? 'Phrasing check: {n} finding. It does not reject the answer.' : 'Phrasing check: {n} findings. They do not reject the answer.')
    : (found.length === 1 ? 'Answer checks: {n} finding. It does not reject the answer.' : 'Answer checks: {n} findings. They do not reject the answer.')
  return <details className="legacy-mini-note phrasing-note">
    <summary>{t(summary, { n: found.length })}</summary>
    <ul className="plain-list">{found.map((w, i) => <li key={i}>{mathLabels[w.code] && <strong>{t(mathLabels[w.code])}: </strong>}{w.message}</li>)}</ul>
  </details>
}


function ReviewNote({ review }: { review: Answer['review'] }) {
  const modelText = useModelText()
  if (!review) return null
  const model = review.model ? <> · <ModelName connection={review.model.connection} text={modelText(review.model.resolved_model ?? review.model.requested_model)} /></> : null
  if (review.status === 'failed') {
    return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden /><span>{model && <strong>{t('Reviewer')}{model}:</strong>} {t('The reviewer did not produce a usable review.')} {pauseReasonText(review.failure_reason)} {t('The answer is unchanged.')}</span></p>
  }
  const counts = (Object.keys(verdictLabels) as Verdict[]).map(v => [v, review.reviews.filter(r => r.verdict === v).length] as const).filter(([, n]) => n > 0)
  return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden /><span><strong>{t('Reviewer')}{model}:</strong> {counts.map(([v, n]) => `${n} ${t(verdictLabels[v])}`).join(' · ')}. {review.notes && `${review.notes} `}{t('This is an additional model’s reading of each claim against its cited passages. It does not change the answer and is not independent verification.')}</span></p>
}

// Bibliography files for reference managers, downloaded from the local API.
function ExportLinks({ researchId, sources }: { researchId: string; sources: 'included' | 'cited' }) {
  const label = t(sources === 'included' ? 'included sources' : 'cited sources')
  return <span className="export-links" role="group" aria-label={t('Export {label}', { label })}>
    <span className="export-links-label"><Download size={15} aria-hidden />{t(sources === 'included' ? 'Export included' : 'Export cited')}</span>
    <span className="export-formats">
      <a href={bibliographyUrl(researchId, 'bibtex', sources)} download title={t('BibTeX file of the {label} (LaTeX, Zotero, JabRef)', { label })}>.bib</a>
      <a href={bibliographyUrl(researchId, 'ris', sources)} download title={t('RIS file of the {label} (Zotero, EndNote, Mendeley)', { label })}>.ris</a>
    </span>
  </span>
}

function ReasonForm({ busy, onSave }: { busy: boolean; onSave: (reason: string) => void }) {
  const [text, setText] = useState('')
  return <form className="reason-form" onSubmit={e => { e.preventDefault(); if (text.trim()) onSave(text.trim()) }}>
    <input aria-label={t('Reason for excluding this source')} placeholder={t('Why exclude it? Optional; kept with your choice.')} maxLength={1000} value={text} onChange={e => setText(e.target.value)} />
    <Button type="submit" variant="outline" size="sm" disabled={busy || !text.trim()}>{t('Save reason')}</Button>
  </form>
}

type SourceSort = 'found' | 'relevant' | 'cited' | 'newest' | 'oldest' | 'title'
const sourceSorts: Record<SourceSort, string> = { relevant: 'Most relevant', found: 'Order found', cited: 'Most cited', newest: 'Newest first', oldest: 'Oldest first', title: 'Title A–Z' }
// Search position is not comparable across queries: the model's screening verdict decides, then similarity to the question
// when semantic search scored the source (D30), then the best position in the searches that found it.
const verdictOrder: Record<string, number> = { include: 0, uncertain: 1, exclude: 2 }
const verdictRank = (s: Source) => verdictOrder[s.selection.proposal ?? ''] ?? 3
const stateFilters = [['all', 'All'], ['included', 'Included'], ['pending', 'Undecided'], ['excluded', 'Excluded']] as const
type StateFilter = typeof stateFilters[number][0]
type PdfFilter = 'all' | 'with_pdf' | 'without_pdf'
const pdfFilterLabels: Record<PdfFilter, string> = { all: 'All PDFs', with_pdf: 'PDF attached', without_pdf: 'No PDF attached' }
// Sources without the value (no year, no citation count) go last in either direction.
const byNumber = (a: number | null, b: number | null, dir: 1 | -1) => a === null ? (b === null ? 0 : 1) : b === null ? -1 : dir * (a - b)
const sourceCompare: Record<SourceSort, (a: Source, b: Source) => number> = {
  found: () => 0,
  relevant: (a, b) => verdictRank(a) - verdictRank(b) || byNumber(a.similarity, b.similarity, -1) || byNumber(a.rank, b.rank, 1),
  cited: (a, b) => byNumber(a.cited_by_count, b.cited_by_count, -1),
  newest: (a, b) => byNumber(a.year, b.year, -1),
  oldest: (a, b) => byNumber(a.year, b.year, 1),
  title: (a, b) => a.title.localeCompare(b.title),
}

type SourceActions = { onRemoveFromResearch: (source: Source) => void; onSelect: (source: Source, state: Source['selection']['state']) => void; onReason: (source: Source, reason: string) => void; onAbstract: (source: Source) => void; onDiscoverPdf: (source: Source) => void; onAttachPdf: (source: Source) => void; onAttachCandidate: (source: Source, candidateId: string) => void; onOpenPdf: (source: Source, assetId: string) => void; onRemoveAsset: (source: Source, assetId: string) => void; onReplaceAsset: (source: Source, assetId: string) => void; onReextract: (source: Source, assetId: string) => void; onRereadEquations: (source: Source, assetId: string) => void; pdfFinding: string | null; ocr: OcrContext }
// What the Sources rows need to offer OCR (D51): the local tool, the runs that may be reading a PDF, and the action.
type OcrContext = { tool: OcrTool | null; runs: Run[]; onRead: (source: Source, assetId: string) => void }

function SourceList({ sources, busy, filter, onFilter, focus, onFocus, picked, onPick, onRemoveFromResearch, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onAttachCandidate, onOpenPdf, onRemoveAsset, onReplaceAsset, onReextract, onRereadEquations, pdfFinding, ocr }: { sources: Source[]; busy: boolean; filter: StateFilter; onFilter: (filter: StateFilter) => void; focus: string | null; onFocus: (workId: string | null) => void; picked: string[]; onPick: (ids: string[]) => void } & SourceActions) {
  const [pdfFilter, setPdfFilter] = useState<PdfFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SourceSort>('relevant')
  // Other versions follow their record and move with it; the filter and sort look at the record.
  const families: Source[][] = []
  for (const source of sources) {
    const last = families[families.length - 1]
    if (source.version_role === 'other_version' && last?.[0].work_id === source.work_id) last.push(source)
    else families.push([source])
  }
  const counts = { all: families.length, included: 0, pending: 0, excluded: 0 }
  families.forEach(([record]) => counts[record.selection.state]++)
  const hasPdf = (family: Source[]) => family.some(source => source.access.assets.length > 0)
  const pdfCounts = { all: families.length, with_pdf: families.filter(hasPdf).length, without_pdf: families.filter(family => !hasPdf(family)).length }
  const needle = query.trim().toLocaleLowerCase()
  const matches = (s: Source) => [s.title, s.venue, s.doi, ...s.authors].some(text => text?.toLocaleLowerCase().includes(needle))
  const focused = focus ? families.filter(f => f[0].work_id === focus) : null
  const shown = focused ?? families.filter(f => (filter === 'all' || f[0].selection.state === filter) && (pdfFilter === 'all' || (pdfFilter === 'with_pdf' ? hasPdf(f) : !hasPdf(f))) && (!needle || f.some(matches)))
    .sort((a, b) => sourceCompare[sort](a[0], b[0]))
  const shownIds = shown.flat().map(s => s.source_version_id)
  const allShownPicked = shownIds.length > 0 && shownIds.every(sid => picked.includes(sid))
  const togglePick = (sid: string, on: boolean) => onPick(on ? [...picked, sid] : picked.filter(p => p !== sid))
  if (!sources.length) return <p className="empty-inline">{t('No sources yet.')}</p>
  return <>
    {families.length > 1 && <div className="source-toolbar">
      <label className="source-pick-all"><input type="checkbox" checked={allShownPicked} disabled={!shownIds.length}
        ref={node => { if (node) node.indeterminate = !allShownPicked && shownIds.some(sid => picked.includes(sid)) }}
        onChange={e => onPick(e.target.checked ? [...new Set([...picked, ...shownIds])] : picked.filter(sid => !shownIds.includes(sid)))} /><span>{t('Select shown')}</span></label>
      <div className="source-filters" role="group" aria-label={t('Show sources')}>
        {stateFilters.map(([key, label]) => <button key={key} aria-pressed={!focused && filter === key} onClick={() => { onFocus(null); onFilter(key) }}>{t(label)}<span>{counts[key]}</span></button>)}
      </div>
      <label className="source-search"><Search size={14} aria-hidden /><input type="search" aria-label={t('Filter sources')} placeholder={t('Title, author, venue or DOI')} value={query} onChange={e => { onFocus(null); setQuery(e.target.value) }} /></label>
      <Select value={pdfFilter} onValueChange={value => { if (value) { onFocus(null); setPdfFilter(value as PdfFilter) } }}>
        <SelectTrigger className="source-pdf-filter" aria-label={t('Filter sources by PDF availability')}><SelectValue>{(value: string) => <><Filter size={14} />{t(pdfFilterLabels[value as PdfFilter])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" align="end" alignItemWithTrigger={false}>
          {(Object.keys(pdfFilterLabels) as PdfFilter[]).map(k => <SelectItem key={k} value={k}><span className="source-filter-option"><span>{t(pdfFilterLabels[k])}</span><small>{pdfCounts[k]}</small></span></SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={sort} onValueChange={value => { if (value) setSort(value as SourceSort) }}>
        <SelectTrigger aria-label={t('Sort sources')}><SelectValue>{(value: string) => <><ArrowUpDown size={14} />{t(sourceSorts[value as SourceSort])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" align="end" alignItemWithTrigger={false}>
          {(Object.keys(sourceSorts) as SourceSort[]).map(k => <SelectItem key={k} value={k}>{k === 'relevant' ? <span className="sort-option">{t(sourceSorts[k])}<small>{t('Model’s screening verdict first, then similarity to the question, then search position')}</small></span> : t(sourceSorts[k])}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>}
    {focused && <p className="source-focus">{t('Showing the one work the audit sample sent you to.')} <button type="button" onClick={() => { onFocus(null); onFilter('all'); setPdfFilter('all'); setQuery('') }}>{t('Show all sources')}</button></p>}
    <div className={`source-list${picked.length ? ' has-selection-bar' : ''}`}>{shown.flat().map(source => <SourceRow key={source.source_version_id} source={source} busy={busy}
      picked={picked.includes(source.source_version_id)} onPick={on => togglePick(source.source_version_id, on)} onRemoveFromResearch={() => onRemoveFromResearch(source)}
      duplicates={source.suspected_duplicates.map(d => ({ basis: d.basis, source: sources.find(s => s.source_version_id === d.source_version_id) }))}
      readsVersion={sources.find(s => s.source_version_id === source.answer_reads_version_id)}
      onSelect={state => onSelect(source, state)} onReason={reason => onReason(source, reason)} onAbstract={() => onAbstract(source)}
      onDiscoverPdf={() => onDiscoverPdf(source)} onAttachPdf={() => onAttachPdf(source)} onAttachCandidate={candidateId => onAttachCandidate(source, candidateId)} onOpenPdf={assetId => onOpenPdf(source, assetId)}
      onRemoveAsset={assetId => onRemoveAsset(source, assetId)} onReplaceAsset={assetId => onReplaceAsset(source, assetId)} onReextract={assetId => onReextract(source, assetId)} onRereadEquations={assetId => onRereadEquations(source, assetId)} finding={pdfFinding === source.source_version_id} ocr={ocr} />)}</div>
    {!shown.length && <p className="empty-inline source-empty">{t('No source matches this filter.')} <button onClick={() => { onFilter('all'); setPdfFilter('all'); setQuery(''); onFocus(null) }}>{t('Show all sources')}</button></p>}
  </>
}

// The bar under the Sources list while sources are chosen (D50): a table from them, rows for a table, or removal.
function SelectionBar({ researchId, count, busy, active, onStartTable, onAddToTable, onRemove, onClear }: { researchId: string; count: number; busy: boolean; active: boolean; onStartTable: () => void; onAddToTable: (table: TableSummary) => void; onRemove: () => void; onClear: () => void }) {
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  useEffect(() => { api.tables(researchId).then(setTables, () => setTables([])) }, [researchId])
  return <div className="selection-bar" role="region" aria-label={t('Chosen sources')}>
    <strong aria-live="polite">{t(count === 1 ? '{n} source chosen' : '{n} sources chosen', { n: count })}</strong>
    <div className="selection-bar-actions">
      <Button size="sm" disabled={busy} onClick={onStartTable}><Table2 size={14} aria-hidden />{t('Start table')}</Button>
      <DropdownMenu>
        <DropdownMenuTrigger disabled={busy || !tables?.length} render={<Button size="sm" variant="outline" />} title={tables && !tables.length ? t('This research has no table yet') : undefined}><ListPlus size={14} aria-hidden />{t('Add to table')}</DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto">{(tables ?? []).map(table => <DropdownMenuItem key={table.id} onClick={() => onAddToTable(table)}><Table2 size={15} />{table.title}</DropdownMenuItem>)}</DropdownMenuContent>
      </DropdownMenu>
      <Button size="sm" variant="outline" disabled={busy || active} title={active ? t('Available when the active run finishes') : undefined} onClick={onRemove}><ListMinus size={14} aria-hidden />{t('Remove from research')}</Button>
      <Button size="sm" variant="ghost" onClick={onClear}>{t('Clear')}</Button>
    </div>
  </div>
}

// The PDF lookup is one request, so this names the services it checks without claiming which one is running.
const PDF_LOOKUP_SERVICES = ['unpaywall', 'openalex', 'crossref']
function PdfSearchStatus() {
  const [since] = useState(() => new Date().toISOString())
  return <p className="pdf-search-status" role="status">
    <span className="sr-only">{t('Checking Unpaywall, OpenAlex and Crossref; Web Search will run if no verified PDF is retrieved…')}</span>
    <LoaderCircle size={14} className="pdf-search-spin" aria-hidden />
    <strong aria-hidden>{t('Finding PDF')}</strong>
    <span className="pdf-search-services" title={PDF_LOOKUP_SERVICES.map(providerName).join(', ')} aria-hidden>{PDF_LOOKUP_SERVICES.map(id => <ConnectionIcon key={id} id={id} />)}</span>
    <span className="pdf-search-muted" aria-hidden>{t('{n} open-access services', { n: PDF_LOOKUP_SERVICES.length })}</span>
    <span className="pdf-search-sep" aria-hidden />
    <span className="pdf-search-muted" aria-hidden><ConnectionIcon id="web_search" />{t('Web Search if needed')}</span>
    <Elapsed since={since} />
  </p>
}

function SourceRow({ source, busy, picked, onPick, onRemoveFromResearch, duplicates, readsVersion, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onAttachCandidate, onOpenPdf, onRemoveAsset, onReplaceAsset, onReextract, onRereadEquations, finding, ocr }: { source: Source; busy: boolean; picked: boolean; onPick: (on: boolean) => void; onRemoveFromResearch: () => void; onSelect: (state: Source['selection']['state']) => void; onReason: (reason: string) => void; onAbstract: () => void; onDiscoverPdf: () => void; onAttachPdf: () => void; onAttachCandidate: (candidateId: string) => void; onOpenPdf: (assetId: string) => void; onRemoveAsset: (assetId: string) => void; onReplaceAsset: (assetId: string) => void; onReextract: (assetId: string) => void; onRereadEquations: (assetId: string) => void; finding: boolean; ocr: OcrContext; duplicates: { basis: Source['suspected_duplicates'][number]['basis']; source?: Source }[]; readsVersion?: Source }) {
  const s = source.selection
  const other = source.version_role === 'other_version'
  const authors = source.authors.join(', ')
  const citationDetails = [source.volume && t('vol. {value}', { value: source.volume }), source.issue && t('no. {value}', { value: source.issue }), source.pages && t('pp. {value}', { value: source.pages })].filter(Boolean).join(', ')
  // A citation-style byline: who and when, then where it appeared and how often OpenAlex counts it cited.
  const byline = [authors, source.year].filter(Boolean).join(' · ')
  const venueLine = [citationDetails, citedText(source.cited_by_count)].filter(Boolean)
  const discoveries = source.access.pdf_discoveries
  const candidates = source.access.pdf_candidates
  const unusable = candidates.filter(c => c.access_status !== 'downloaded').length
  const lookupSummary = [t('{p} services · {n} checks', { p: new Set(discoveries.map(d => d.provider)).size, n: discoveries.length }), unusable && t(unusable === 1 ? '{n} file not usable' : '{n} files not usable', { n: unusable })].filter(Boolean).join(' · ')
  const primaryAction = source.access.assets.length ? 'pdf' : 'abstract'
  const ocrOffers = new Map(source.access.assets.map(asset => [asset.id, ocrOffer(asset, ocr.tool, ocr.runs)]))
  return <div className={`source-row has-pick is-${s.state}${other ? ' is-other-version' : ''}${picked ? ' is-picked' : ''}`}>
    <input type="checkbox" className="source-pick" checked={picked} onChange={e => onPick(e.target.checked)} aria-label={t('Select {title}', { title: source.title })} />
    <div className="source-main">
      {other && <span className="version-note">{t('Another version of the record above: {version}. It follows the record’s selection; passages cited from it are labelled with this version.', { version: versionText(source.version_label) })}</span>}
      <strong className="source-title"><SourceKey value={source.source_key} /><span>{source.title}</span></strong>
      {byline || source.venue || venueLine.length ? <div className="source-byline">
        {byline && <span>{byline}</span>}
        {(source.venue || venueLine.length > 0) && <span>{source.venue && <em>{source.venue}</em>}{source.venue && venueLine.length > 0 && ' · '}{venueLine.join(' · ')}</span>}
      </div> : <div className="source-byline"><span>{t(source.origin === 'user_upload' ? 'Uploaded PDF' : 'No bibliographic details from the provider')}</span></div>}
      <div className="source-status">
        {source.version_label && <span className={`source-fact is-${versionTones[source.version_label] ?? 'unstated'}`}>{versionText(source.version_label)}</span>}
        {accessParts(source).map(part => <span key={part.text} className={`source-fact is-${part.tone}`}>{part.text}</span>)}
        {readsVersion && <Tooltip content={t('This record has no PDF text, so answers read the PDF of {version} below. Passages cited from it are labelled with that version; the two are not counted as separate sources.', { version: versionText(readsVersion.version_label) })}><span className="source-fact is-plain" tabIndex={0}>{t('answers read {version}', { version: versionText(readsVersion.version_label) })}</span></Tooltip>}
        {source.cited_in_latest_answer && <span className="source-fact is-cited">{t('cited in the latest answer')}</span>}
        {source.similarity !== null && <Tooltip content={t(source.access.abstract_passage_id ? 'Embedding similarity between the research question and this source’s title and stored abstract. Used for ordering only; it is not a relevance judgment.' : 'Embedding similarity between the research question and this source’s title. No abstract was available. Used for ordering only; it is not a relevance judgment.')}><span className="source-fact is-similarity" tabIndex={0}>{t('Similarity {score}', { score: source.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })}</span></Tooltip>}
        {source.provider_records.length > 0 && <span className="source-fact is-plain">{t('Found in {providers}', { providers: source.provider_records.map(providerName).join(', ') })}</span>}
        {duplicates.length > 0 && <Tooltip content={<ul className="duplicate-tip">{duplicates.map((d, i) => <li key={i}>{d.source ? [versionText(d.source.version_label), d.source.provider_records.map(providerName).join(', ')].filter(Boolean).join(' · ') : t('a source not in this list')} — {t(d.basis === 'published_doi' ? 'a preprint that names the other record’s DOI' : 'same title')}</li>)}</ul>}><span className="source-fact is-plain is-duplicate" tabIndex={0}>{t(duplicates.length === 1 ? 'may duplicate {n} other source · not merged' : 'may duplicate {n} other sources · not merged', { n: duplicates.length })}</span></Tooltip>}
      </div>
      {source.applicability === 'stale_scope' && <p className="proposal is-stale">{t(s.proposal ? 'Found for question revision {n}; the proposal below was made for that question. Search again to screen it for the current question.' : 'Found for question revision {n}. Search again to screen it for the current question.', { n: source.found_in_revision ?? '?' })}</p>}
      {s.proposal && !other && <p className="proposal is-model"><span className="proposal-tag">{t('Model proposal:')}</span> <span><em className={`verdict is-${s.proposal}`}>{t(s.proposal)}</em> — {s.proposal_reason} <span>({t(s.proposal_basis?.replaceAll('_', ' ') ?? '')})</span>{s.origin === 'user' ? ` ${t('· overridden by you')}` : ''}</span></p>}
      {/* A selection the queue wrote reads as that answer; the backend names it from the stored link, never from the reason text. */}
      {s.origin === 'user' && (s.queue_answer || s.user_reason) && <p className="proposal"><UserPen size={13} aria-hidden />{s.queue_answer
        ? t('Your answer in the queue: {answer}', { answer: t(queueAnsweredText[s.queue_answer]) })
        : t('Your reason: {reason}', { reason: s.user_reason ?? '' })}</p>}
      {s.origin === 'user' && s.state === 'excluded' && !s.user_reason && <ReasonForm busy={busy} onSave={onReason} />}
      {finding && <PdfSearchStatus />}
      {source.access.assets.map(asset => asset.rejected_extraction && <p key={asset.id} className="proposal"><ScanText size={13} aria-hidden />{t('A later text extraction ({version}) was not used: {reason}. The earlier text stays in use.', { version: asset.rejected_extraction.extraction_version, reason: asset.rejected_extraction.rejection_reason })}</p>)}
      {[...ocrOffers.entries()].map(([assetId, offer]) => offer && <OcrNote key={assetId} offer={offer} />)}
      {source.access.replaced_assets.length > 0 && <p className="proposal"><Replace size={13} aria-hidden />{t(source.access.replaced_assets[0].original_filename ? 'Previous file {file} replaced on {date}. Evidence that cites it still opens it.' : 'Previous PDF replaced on {date}. Evidence that cites it still opens it.', { file: source.access.replaced_assets[0].original_filename ?? '', date: new Date(source.access.replaced_assets[0].removed_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) })}</p>}
      <div className="source-foot">
        {!finding && discoveries.length > 0 && <details className="source-provenance">
          <summary><ChevronRight size={14} className="source-provenance-chev" aria-hidden /><strong>{t(source.access.assets.length ? 'PDF attached' : 'No usable PDF found')}</strong><span>{lookupSummary}</span></summary>
          <PdfLookupTable source={source} busy={busy} onAttachCandidate={onAttachCandidate} />
        </details>}
        <div className="source-links">
          {source.access.assets.map(asset => <span className="source-asset-actions" key={asset.id}>
            <button type="button" className="is-primary" onClick={() => onOpenPdf(asset.id)} title={asset.original_filename ?? undefined}><FileText size={14} aria-hidden />{t('Open PDF')}</button>
            <button disabled={busy} onClick={() => onReplaceAsset(asset.id)} title={t('Use another file for this source version; evidence that cites the current file keeps it')}><Replace size={14} aria-hidden />{t('Replace PDF')}</button>
            {asset.current_extraction === false && <button disabled={busy} onClick={() => onReextract(asset.id)} title={t('Text extracted as {version}. Extract it again with the current extractor.', { version: asset.extraction_version ?? '?' })}><ScanText size={14} aria-hidden />{t('Extract text again')}</button>}
            {asset.equations?.state === 'failed' && <button disabled={busy} onClick={() => onRereadEquations(asset.id)} title={asset.equations.reason ?? undefined}><Sigma size={14} aria-hidden />{t('Read equations again')}</button>}
            {ocrOffers.get(asset.id) && <OcrButton offer={ocrOffers.get(asset.id)!} busy={busy} onRead={() => ocr.onRead(source, asset.id)} />}
            <button className="is-destructive" disabled={busy} onClick={() => onRemoveAsset(asset.id)} title={asset.original_filename ?? undefined}><Trash2 size={14} aria-hidden />{t('Remove PDF')}</button>
          </span>)}
          {source.access.abstract_passage_id && <button className={primaryAction === 'abstract' ? 'is-primary' : undefined} onClick={onAbstract}><BookOpenText size={14} aria-hidden />{t('Read abstract')}</button>}
          {source.doi && <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />DOI</a>}
          {source.doi && <button disabled={busy || finding} onClick={onDiscoverPdf}><Search size={14} aria-hidden />{finding ? <span className="shimmer-text">{t('Web Search is running…')}</span> : t(source.access.assets.length ? 'Refresh metadata' : 'Find PDF')}</button>}
          {!source.access.assets.length && <button disabled={busy || finding} onClick={onAttachPdf}><FileUp size={14} aria-hidden />{t('Attach PDF')}</button>}
          <button disabled={busy} onClick={onRemoveFromResearch} title={t('Take this source out of this research; the library record, its PDF and earlier quotes stay')}><ListMinus size={14} aria-hidden />{t('Remove from research')}</button>
        </div>
      </div>
    </div>
    {!other && <div className="selection-toggle" role="group" aria-label={t('Selection for {title}', { title: source.title })}>
      {(['included', 'pending', 'excluded'] as const).map(state => <button key={state} className={`is-${state}`} aria-pressed={s.state === state} disabled={busy || s.state === state} onClick={() => onSelect(state)}>{t(state === 'included' ? 'Include' : state === 'excluded' ? 'Exclude' : 'Undecided')}</button>)}
    </div>}
  </div>
}

// One row per lookup service: its checks collapse into a try count, and the files it offered sit in its row.
function PdfLookupTable({ source, busy, onAttachCandidate }: { source: Source; busy: boolean; onAttachCandidate: (candidateId: string) => void }) {
  const discoveries = source.access.pdf_discoveries
  const candidates = source.access.pdf_candidates
  const providers = [...new Set([...discoveries.map(d => d.provider), ...candidates.map(c => c.provider)])]
  return <div className="pdf-lookup-wrap"><table className="pdf-lookup">
    <thead><tr><th scope="col">{t('Service')}</th><th scope="col">{t('Result')}</th><th scope="col">{t('Checks')}</th><th scope="col">{t('Detail')}</th></tr></thead>
    <tbody>{providers.map(provider => {
      const checks = discoveries.filter(d => d.provider === provider)
      const files = candidates.filter(c => c.provider === provider)
      const last = checks[checks.length - 1]
      const result = files.some(c => c.access_status === 'downloaded') ? { tone: 'ok', text: t('PDF retrieved') }
        : files.length ? { tone: 'warn', text: t(files.length === 1 ? '{n} file not usable' : '{n} files not usable', { n: files.length }) }
        : last?.status === 'zero_results' ? { tone: '', text: t('No match') }
        : last?.status === 'completed' ? { tone: '', text: t('completed') }
        : { tone: 'bad', text: t((last?.status ?? 'failed').replaceAll('_', ' ')) }
      const otherTitles = Math.max(0, ...checks.map(d => d.other_title_count ?? 0))
      const notes = [...new Set(checks.map(d => [d.error_code?.replaceAll('_', ' '), d.http_status && `HTTP ${d.http_status}`].filter(Boolean).join(' · ')).filter(Boolean))]
      if (otherTitles) notes.unshift(t(otherTitles === 1 ? '{n} result under another title, not kept' : '{n} results under other titles, not kept', { n: otherTitles }))
      return <tr key={provider}>
        <td className="pdf-lookup-service"><ConnectionIcon id={provider} />{providerName(provider)}</td>
        <td className={result.tone && `is-${result.tone}`}>{result.text}</td>
        <td className="pdf-lookup-count">{checks.length}</td>
        <td>{files.length ? files.map(candidate => <span className="pdf-lookup-file" key={candidate.id}>
          {t(candidate.version_status === 'match' ? 'version verified' : candidate.version_status === 'different' ? 'different version' : 'version uncertain')} · {candidate.access_status === 'http_error' ? `HTTP ${candidate.http_status ?? '?'}` : t(candidate.access_status.replace('_', ' '))}{candidate.identity_status === 'unverified' && ` · ${t('title does not match')}`}{' · '}<a href={candidate.candidate_url} target="_blank" rel="noreferrer">{t('Open file')}</a>{candidate.version_status === 'uncertain' && (candidate.identity_status === 'doi_verified' || candidate.identity_status === 'title_verified') && !source.access.assets.length && <>{' · '}<button disabled={busy} onClick={() => onAttachCandidate(candidate.id)} title={t('Open the file first and check that it is this version of the work, not a preprint or another edition. An attached file’s pages can be cited in answers.')}>{t('Same version, attach')}</button></>}
        </span>) : notes.join('; ')}</td>
      </tr>
    })}</tbody>
  </table></div>
}

// `keyTerms` null: this research does not run the sw workflow, and its search words are not read from key terms.
function RevisionForm({ question, keyTerms, keyTermsRef, disabled, onSubmit }: {
  question: string; keyTerms: string | null; keyTermsRef: React.RefObject<HTMLInputElement | null>
  disabled: boolean; onSubmit: (text: string, keyTerms: string | null) => void
}) {
  const [text, setText] = useState(question)
  const [terms, setTerms] = useState(keyTerms ?? '')
  const changed = (text.trim() && text.trim() !== question) || terms.trim() !== (keyTerms ?? '').trim()
  return <form className="legacy-followup" onSubmit={e => { e.preventDefault(); if (changed && text.trim()) onSubmit(text.trim(), terms.trim() || null) }}>
    <label htmlFor="revise-question">{t('Revise the question')}</label>
    <textarea id="revise-question" value={text} onChange={e => setText(e.target.value)} />
    {keyTerms !== null && <div className="revise-key-terms">
      <label htmlFor="revise-key-terms">{t('English key terms (optional)')}</label>
      <input id="revise-key-terms" ref={keyTermsRef} value={terms} onChange={e => setTerms(e.target.value)} maxLength={500} dir="auto" />
      <small>{t('Blocks are separated by “;”, synonyms of one block by “,”; a group written “claim:” is the assertion under test and one written “not:” keeps records out.')}</small>
    </div>}
    <div><span>{t('Creates a new question revision. Sources and earlier answers are kept.')}</span><Button type="submit" disabled={disabled || !text.trim() || !changed}>{t('Save revision')}</Button></div>
  </form>
}

function activityDayKey(value: string) {
  const date = new Date(value)
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

function ActivityLog({ events }: { events: ActivityEvent[] }) {
  const groups = new Map<string, ActivityEvent[]>()
  events.slice().reverse().forEach(event => {
    const key = activityDayKey(event.created_at)
    groups.set(key, [...(groups.get(key) ?? []), event])
  })
  return <section className="activity-panel" aria-labelledby="activity-heading">
    <header className="workspace-pane-head"><div><h2 id="activity-heading">{t('Recorded activity')}</h2><p>{t(events.length === 1 ? '{n} recorded event' : '{n} recorded events', { n: events.length })}</p></div></header>
    {[...groups.values()].map(group => <section className="activity-day" key={activityDayKey(group[0].created_at)}>
      <h3>{new Date(group[0].created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</h3>
      <ol className="activity-list">{group.map(event => {
        const { icon, text, chips } = describeEvent(event)
        return <li key={event.id}>
          <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })}</time>
          <span className="activity-event"><span className="activity-icon">{icon}</span><span className="activity-copy">{text}</span>{chips.map((chip, i) => <span key={i} className={`activity-chip is-${chip.tone}`}>{chip.label}</span>)}</span>
        </li>
      })}</ol>
    </section>)}
    {!events.length && <p className="empty-inline">{t('No recorded activity.')}</p>}
  </section>
}

const selectionStates: Record<string, string> = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' }

type ChipTone = 'ok' | 'bad' | 'warn' | 'live' | 'neutral'
type EventChip = { label: string; tone: ChipTone }

const statusTones: Record<string, ChipTone> = {
  completed: 'ok', succeeded: 'ok', structurally_valid: 'ok',
  partial: 'warn', unverified_draft: 'warn', outcome_unknown: 'warn', rate_limited: 'warn', timeout: 'warn',
  failed: 'bad', auth_required: 'bad', entitlement_missing: 'bad', parse_error: 'bad',
  pending: 'live', running: 'live',
}
const statusChip = (status: unknown): EventChip => ({ label: t(String(status).replaceAll('_', ' ')), tone: statusTones[String(status)] ?? 'neutral' })
const selectionTones: Record<string, ChipTone> = { included: 'ok', excluded: 'bad', pending: 'warn' }

function describeEvent(event: ActivityEvent): { icon: ReactNode; text: string; chips: EventChip[] } {
  const p = event.payload as Record<string, string | number | null>
  const lucide = (Icon: LucideIcon, text: string, chips: EventChip[] = []) => ({ icon: <Icon size={15} aria-hidden />, text, chips })
  const brand = (id: string, text: string, chips: EventChip[] = []) => ({ icon: <ConnectionIcon id={id} />, text, chips })
  const reason = p.pause_reason ? [{ label: pauseReasonText(String(p.pause_reason)), tone: 'neutral' as const }] : []
  const errorChip = p.error_code ? [{ label: String(p.error_code), tone: 'neutral' as const }] : []
  switch (event.type) {
    case 'research_created': return lucide(FilePlus2, t('Research created'))
    case 'scope_revised': return lucide(PencilLine, t('Question revised (revision {n})', { n: String(p.scope_revision) }))
    case 'research_title_edited': return lucide(PencilLine, t('Research title edited'))
    case 'run_queued': return lucide(ListPlus, p.kind === 'discovery' || p.kind === 'answer' ? t(p.kind === 'discovery' ? 'Search run queued' : 'Answer run queued') : t('{label} queued', { label: t(runKindLabels[String(p.kind) as RunKind] ?? String(p.kind)) }))
    case 'run_started': return lucide(Play, t('Run started'))
    case 'run_completed': return lucide(CircleCheck, t('Run completed'), [statusChip('completed')])
    case 'run_paused': return lucide(Pause, t('Run paused'), reason)
    case 'run_failed': return lucide(CircleX, t('Run failed'), [statusChip('failed'), ...reason])
    case 'run_resumed': return lucide(RotateCw, t('Run resumed'))
    case 'run_cancelled': return lucide(Ban, t('Run cancelled'))
    case 'run_pause_requested': return lucide(Hand, t('Pause requested'))
    case 'step_started': return lucide(CircleDot, t('{step} started', { step: stepLabel(String(p.kind), String(p.operation_key)) }))
    case 'step_finished': {
      const pdfStep = p.kind === 'fetch_pdf' || p.kind === 'pdf_other_copy'
      const chips = p.error_code && pdfStep ? [{ label: fetchReasonText(String(p.error_code), typeof p.http_status === 'number' ? p.http_status : null), tone: 'neutral' as const }] : errorChip
      return lucide(ListChecks, stepLabel(String(p.kind), String(p.operation_key)), [statusChip(p.status), ...chips])
    }
    case 'model_call_started': return brand(String(p.connection), t('Model call sent to {connection}', { connection: String(p.connection) }), p.requested_model ? [{ label: String(p.requested_model), tone: 'neutral' }] : [])
    case 'search_recorded': return brand(String(p.provider), t('{provider} search', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} records', { count: String(p.result_count) }), tone: 'neutral' }])
    case 'pdf_discovery_recorded': return brand(String(p.provider), t('{provider} PDF lookup', { provider: providerName(String(p.provider)) }), [statusChip(p.status), { label: t('{count} candidates', { count: String(p.result_count) }), tone: 'neutral' }, ...errorChip])
    case 'asset_removed': return lucide(Trash2, t('PDF removed from a source'))
    case 'asset_replaced': return lucide(Replace, t('PDF replaced on a source'))
    case 'equations_failed': return lucide(Sigma, t('Reading a PDF’s equations failed'), [{ label: t('attempt {n}', { n: String(p.attempts) }), tone: 'warn' }])
    case 'asset_ocr_read': return lucide(ScanText, t('PDF pages read with OCR'), [p.outcome === 'current' ? { label: t('in use'), tone: 'ok' } : { label: t('not used'), tone: 'warn' }, { label: t('{k} of {n} pages with text', { k: String(p.pages_with_text), n: String(p.pages_read) }), tone: 'neutral' }, { label: ocrLanguagesText(Array.isArray(p.languages) ? p.languages.map(String) : []), tone: 'neutral' }])
    case 'asset_reextracted': return lucide(ScanText, t('PDF text extracted again'), [p.outcome === 'current' ? { label: t('in use'), tone: 'ok' } : { label: t('not used'), tone: 'warn' }, { label: String(p.extraction_version), tone: 'neutral' }])
    case 'selection_changed': return lucide(UserPen, t('You marked a source'), [{ label: t(selectionStates[String(p.state)] ?? String(p.state)), tone: selectionTones[String(p.state)] ?? 'neutral' }])
    case 'answer_saved': return lucide(MessageSquareQuote, t('Answer saved'), [statusChip(p.status)])
    case 'table_changed': return lucide(Table2, t('Evidence table changed'))
    case 'table_trashed': return lucide(Trash2, t('Evidence table moved to Trash'))
    case 'table_restored': return lucide(RotateCcw, t('Evidence table restored'))
    case 'table_purged': return lucide(Trash2, t('Evidence table permanently deleted'))
    case 'column_restored': return lucide(RotateCcw, t('Table column restored'))
    case 'source_removed': return lucide(ListMinus, t(Array.isArray(p.source_version_ids) && p.source_version_ids.length === 1 ? 'You removed a source from this research' : 'You removed {n} sources from this research', { n: Array.isArray(p.source_version_ids) ? p.source_version_ids.length : 0 }))
    case 'source_restored': return lucide(RotateCcw, t(Array.isArray(p.source_version_ids) && p.source_version_ids.length === 1 ? 'You restored a source to this research' : 'You restored {n} sources to this research', { n: Array.isArray(p.source_version_ids) ? p.source_version_ids.length : 0 }))
    case 'asset_restored': return lucide(RotateCcw, t('PDF restored to a source'))
    case 'cell_revision_saved': return lucide(PencilLine, t('Cell revision saved'), [{ label: t(String(p.kind).replaceAll('_', ' ')), tone: 'neutral' }])
    case 'answer_reviewed': return lucide(ShieldCheck, t('Answer review saved'), [statusChip(p.status)])
    default: return lucide(Activity, event.type)
  }
}
