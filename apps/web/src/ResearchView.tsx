import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, ChevronRight, Clock, Ellipsis, FileText, FileUp, Inbox, Lightbulb, ListMinus, LoaderCircle, Pause, PencilLine, Play, Search, Sparkles, Table2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, ApiError, subscribe, type ActivityEvent, type Answer, type AssetImpact, type ResearchView, type Run, type OcrTool, type RunKind, type RunStatus, type Source, type TableSummary, type ZoteroSource } from './api'
import { serviceErrorSentence, serviceKind, fileRestoreNote, fileRestoreText, fileRestoreTone, pauseReasonText, providerName, runKindLabels, runStatusLabels, scopeLabels, searchQueryTriesLeft, seedSkipText, seedUseText } from './labels'
import { PassageSheet } from './PassageSheet'
import { TextRecoveryContext } from './TextRecoveryContext'
import { EvidenceTab, TABLE_RUN_KINDS } from './EvidenceTable'
import { Transcript } from './Transcript'
import { PdfReadiness } from './PdfReadiness'
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
import { FlowBlock } from './FlowReport'
import { WaitingForPdf } from './WaitingForPdf'
import { EnglishQuestion, UploadedTextNote } from './SemanticNotes'
import { AnswerBlock } from './research/AnswerBlock'
import { ActivityLog } from './research/ActivityLog'
import { ArtifactsTab, TableCard } from './research/ArtifactsTab'
import { ExportLinks, ExportMenu } from './research/ExportMenu'
import { RevisionForm } from './research/RevisionForm'
import { SelectionBar } from './research/SelectionBar'
import { SourceList, type StateFilter } from './research/SourceList'
import { SplitPanel, StackPanel } from './research/SplitPanel'
import { PanelStackContext, panelFromSegment, usePanelStack, usePhone, URL_PANELS } from './research/usePanelStack'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const TRANSCRIPT_KINDS = new Set<RunKind>(['discovery', 'pdf_collection', 'fulltext_fetch', 'fulltext_adjudication', 'pdf_ocr', 'answer', 'report', 'review'])
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
  // The tabs became a side panel beside the thread (R10): the URL's last segment names the open panel, old tab names included.
  const panels = usePanelStack(panelFromSegment(initialTab))
  const panel = panels.current
  const phone = usePhone()
  const [candidateCount, setCandidateCount] = useState<number | null>(null)
  const [candidateSelection, setCandidateSelection] = useState<CandidateSelection | null>(null)
  const [passageTarget, setPassageTarget] = useState<{ passageId: string; highlightText: string | null; fromCitation: boolean; reportCitation?: boolean } | null>(null)
  const [pdfTarget, setPdfTarget] = useState<{ assetId: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [ocrTool, setOcrTool] = useState<OcrTool | null>(null)
  // The counts under the question open the Sources tab, so the selection filter lives here rather than inside the list.
  const [sourceFilter, setSourceFilter] = useState<StateFilter>('all')
  // One work the audit sample sent the person to (slice 20): the Sources list shows that work alone, by its id.
  const [sourceFocus, setSourceFocus] = useState<string | null>(null)
  const openPanel = panels.open
  const [pdfFinding, setPdfFinding] = useState<string | null>(null)
  const [waitingFiles, setWaitingFiles] = useState<File[] | null>(null)
  const takeWaitingFiles = useCallback(() => setWaitingFiles(null), [])
  const [attachTarget, setAttachTarget] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<{ source: Source; assetId: string } | null>(null)
  // Replacing a PDF: the file is chosen first, then the confirmation names what still cites the old file (D45).
  const [replacePick, setReplacePick] = useState<{ source: Source; assetId: string } | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<{ source: Source; assetId: string; file: File; impact: AssetImpact } | null>(null)
  const [openReportId, setOpenReportId] = useState<string | null>(null)
  const [openEvidenceReportId, setOpenEvidenceReportId] = useState<string | null>(null)
  // Sources chosen for a table or for removal (D50). Kept only while the Sources tab is open.
  const [picked, setPicked] = useState<string[]>([])
  // Boxes ticked on the PDF list but not saved yet; null shows the PDFs the research stored.
  const [seedPick, setSeedPick] = useState<string[] | null>(null)
  const [removal, setRemoval] = useState<{ ids: string[]; versions: number; elsewhere: number | null } | null>(null)
  const [tableStart, setTableStart] = useState<{ ids: string[]; notIncluded: number } | null>(null)
  // The table to show, with a count of requests: asking for the same table again (a card clicked twice) still shows it.
  const [focusTable, setFocusTable] = useState<{ id: string; request: number } | null>(null)
  const showTableFirst = (tableId: string) => setFocusTable(previous => ({ id: tableId, request: (previous?.request ?? 0) + 1 }))
  const fileInput = useRef<HTMLInputElement>(null)
  const sourceFileInput = useRef<HTMLInputElement>(null)
  const replaceFileInput = useRef<HTMLInputElement>(null)
  const firstEvent = useRef<number | null>(null)
  // A run stopped for key terms sends the user here, to the one field that answers it.
  const keyTerms = useRef<HTMLInputElement>(null)
  const lastRun = useRef<{ id: string; status: RunStatus } | null>(null)
  // Runs another toast already announced when they were opened (a person's file whose attach opened its reading, 18b).
  const announcedRuns = useRef(new Set<string>())
  const titleInput = useRef<HTMLTextAreaElement>(null)
  const moreButton = useRef<HTMLButtonElement>(null)
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
  const followupCount = useFollowUpCount(id, lastEventId)
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
    if (previous.id !== current.id) { if (ACTIVE.has(current.status) && !announcedRuns.current.has(current.id)) toast('success', t('{label} started.', { label })); return }
    switch (current.status) {
      case 'completed': {
        if (current.kind !== 'discovery' && current.kind !== 'answer') { toast('success', current.kind === 'cell_recheck' ? t('Recheck finished. Its result waits as a proposal in the cell.') : t('{label} finished.', { label })); break }
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
  const answer = (view.answers.find(a => !(a.late_revision && a.status !== 'structurally_valid')) ?? view.answers[0]) as Answer | undefined
  const hasAcademic = view.scope.source_scope !== 'attached'
  const needsSeed = view.scope.source_scope === 'attached_and_academic' && view.scope.seed_mode === 'uploaded_seed'
  const seedSearchReady = !needsSeed || view.scope.seed_status === 'ready'
  // The backend decides which PDFs can guide a search; the page lists them and sends back the ticked ones in list order.
  const seedCandidates = view.scope.seed_candidates
  const storedSeedIds = view.scope.seeds.map(seed => seed.source_version_id).filter(sourceId => seedCandidates.some(c => c.source_version_id === sourceId))
  const tickedSeeds = seedPick ?? storedSeedIds
  const seedTitle = (sourceId: string) => view.sources.find(source => source.source_version_id === sourceId)?.title ?? sourceId
  const included = view.counts.included

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
  // Files dropped on the PDF panel of an sw research go to the waiting view's version-checked match (slice 18a).
  const waitingCount = view.counts.waiting_for_pdf ?? 0
  const dropForWaiting = (files: File[]) => { setWaitingFiles(files); openPanel('pdfs') }
  // The revision form stays at the end of the page; the top row only takes the person there.
  const reviseQuestion = () => {
    const field = document.getElementById('revise-question')
    field?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
    field?.focus({ preventScroll: true })
  }
  return <PanelStackContext.Provider value={panels}><section className="research-view legacy-research">
    {/* One 46px row carries the title, the live run and its controls, and the research-level actions, so they reach every tab.
        A table run is controlled on the Evidence tab above its table; here its chip only links there. */}
    <div className={`research-topbar${titleEditing ? ' is-editing' : ''}`} inert={Boolean(phone && panel)}>
      <div className="research-topbar-title">
        {titleEditing
          /* While the title is being edited the heading gives way to the field: a heading whose whole content is a field has no
             name to announce. The field restates the heading's type recipe (see .research-title-input) so nothing moves. */
          ? <textarea
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
          : <TypewriterTitle text={heading} onStartEdit={beginTitleEdit} />}
      </div>
      {titleEditing && <span className="research-title-hint" id="research-title-hint">
        {titleDraft.length > 120
          ? `${t('Enter saves, Escape cancels')} · ${t('{count} of 160 characters', { count: String(titleDraft.length) })}`
          : t('Enter saves, Escape cancels')}
      </span>}
      {candidateRun && panel !== 'cands' && <button type="button" className="run-chip" aria-label={t('Open the Candidates panel to control this run')} onClick={() => { if (candidateRun.target?.candidate_id) setCandidateSelection({ id: candidateRun.target.candidate_id }); openPanel('cands') }}>
        <span className={`run-chip-dot${ACTIVE.has(candidateRun.status) ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels[candidateRun.kind])} · {t(runStatusLabels[candidateRun.status])}<ChevronRight size={13} aria-hidden />
      </button>}
      {watchRun && panel !== 'watch' && <button type="button" className="run-chip" aria-label={t('Open the Follow-up panel to control this run')} onClick={() => openPanel('watch')}>
        <span className={`run-chip-dot${ACTIVE.has(watchRun.status) ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels.watch_check)} · {t(runStatusLabels[watchRun.status])}<ChevronRight size={13} aria-hidden />
      </button>}
      {run && (active || run.status === 'paused') && TABLE_RUN_KINDS.has(run.kind) ? panel !== 'table' && <button type="button" className="run-chip" title={t('Open the Evidence table panel to control this run')} onClick={() => openPanel('table')}>
        <span className={`run-chip-dot${active ? ' is-live' : ''}`} aria-hidden />{t(runKindLabels[run.kind])} · {t(runStatusLabels[run.status])}<ChevronRight size={13} aria-hidden />
      </button>
      : run && run.kind !== 'watch_check' && !CANDIDATE_KINDS.has(run.kind) && (active || run.status === 'paused') && <div className="run-strip">
        <span className={`run-strip-status${active ? ' is-live' : ' is-paused'}`} data-run-id={run.id} tabIndex={-1}>{active ? <LoaderCircle size={13} className="chat-spin" aria-hidden /> : <Pause size={12} aria-hidden />}{t(runKindLabels[run.kind])} · {t(runStatusLabels[run.status])}</span>
        {active && run.status !== 'pause_requested' && <Button variant="ghost" size="sm" className="run-strip-pause" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'pause'))}><Pause size={14} />{t('Pause')}</Button>}
        {run.status === 'paused'
          && !(run.pause_reason === 'search_query_failed' && searchQueryTriesLeft(run) === 0) && <Button variant="default" size="sm" disabled={busy} onClick={() => { const origin = document.activeElement; void act(() => api.controlRun(run.id, 'resume')).then(ok => { if (ok) toRunStatus(run.id, origin) }) }}><Play size={14} />{t('Resume')}</Button>}
        <Button variant="destructive" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(run.id, 'cancel'))}><X size={14} />{t('Cancel')}</Button>
      </div>}
      {!titleEditing && heading === view.scope.question && !active && run?.status !== 'paused' && <Button variant="ghost" size="sm" className="research-title-suggest research-topbar-action" disabled={busy} onClick={startTitle}
        title={t('The model names the research from its question and included sources, in at most 15 words.')}><Sparkles size={14} aria-hidden /><span className="research-topbar-label">{t('Suggest a short title')}</span></Button>}
      <Button variant="ghost" size="sm" className="research-topbar-action research-revise" title={t('Revise question')} onClick={reviseQuestion}><PencilLine size={14} aria-hidden /><span className="research-topbar-label">{t('Revise question')}</span></Button>
      <ExportMenu researchId={id} included={included > 0} cited={view.counts.cited > 0} prisma={Boolean(view.counts.flow)} />
      {/* Until the rail (S11) and the steps (S9) open their panels, this menu reaches every panel the tabs used to show. */}
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button ref={moreButton} variant="ghost" size="icon-sm" className="research-topbar-more" aria-label={t('Research actions')} title={t('Research actions')} />}><Ellipsis size={16} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="research-export-menu w-auto" finalFocus={false}>
          {([['sources', 'Sources', BookOpen, view.sources.length], ['queue', 'Awaiting your decision', Inbox, queueCount], ['pdfs', 'Get more full text', FileText, waitingCount],
            ['table', 'Evidence table', Table2, tables?.length ?? null], ['watch', 'Follow-up', Clock, followupCount.count], ['cands', 'Candidates', Lightbulb, candidateCount], ['activity', 'Activity', Clock, null]] as const)
            .map(([name, label, Icon, count]) => <DropdownMenuItem key={name} className="research-export-item" onClick={() => openPanel(name, { opener: moreButton.current })}>
              <Icon size={15} aria-hidden /><span>{t(label)}</span>{count !== null && <span className="research-tab-count">{count}</span>}
            </DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>

    <div className={`research-split${panel ? ' has-panel' : ''}${panel && panels.wide ? ' is-wide' : ''}`}>
    {/* The thread scrolls on its own; the artifacts rail (S11 fills it) sits beside it while no panel is open. */}
    <div className="research-thread-col" inert={Boolean(phone && panel)}>
    <div className="research-thread-grid">
    <div className="research-body thread-inner">
    {/* The evidence boundaries stay separate counts (AGENTS.md); each one opens the panel that can show it. Scope and depth close the line. */}
    <div className="session-meta research-facts" title={t('Unique, included, given and cited count works: versions of one work count once. “Given to the model” counts works whose passages were sent in the latest answer step; it is not a full-text reading claim.')}>
      <span className="research-revision">{t('Research')} · {t('revision {n}', { n: view.research.current_scope_revision })}</span>
      {/* A count is shown once it has something to say; a row of zeroes while the run works is noise, not a boundary. */}
      {([['unique', 'Unique works', 'all'], ['included', 'Included', 'included'], ['inspected', 'Given to the model', 'all'], ['cited', 'Cited', null]] as const)
        .filter(([key]) => view.counts[key] > 0)
        .map(([key, label, filter]) => <button key={key} type="button" onClick={() => (filter ? showSources(filter) : showAnswer())}><strong>{view.counts[key]}</strong><span>{t(label)}</span></button>)}
      <span title={t('Where DEIXIS looks for sources')}><ScopeIcon size={13} aria-hidden />{t(scopeLabels[view.scope.source_scope])}</span>
      <span title={t('How much searching and reading a run may do')}><EffortIcon size={13} aria-hidden />{t('{effort} depth', { effort: t(effortLabels[view.scope.effort]) })}</span>
    </div>

      <div className="research-thread">
      {/* Table runs show on the Evidence tab and in Activity; the conversation tells search and answer runs. */}
      <Transcript view={{ ...view, runs: view.runs.filter(r => TRANSCRIPT_KINDS.has(r.kind)) }} modelText={modelText}
        onRetryFailedSearches={async target => { await act(() => api.controlRun(target.id, 'retry_failed'), t('Failed searches queued again.')) }}
        onChooseCodeQuery={async target => { await act(() => api.chooseCodeQuery(target.id), t('The run searches with the query built from the question’s words.')) }}
        onGiveKeyTerms={() => { keyTerms.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' }); keyTerms.current?.focus({ preventScroll: true }) }}
        queueCount={queueCount} onOpenQueue={showQueue}
        emptyText={included ? t(included === 1 ? '{n} source is included. Generate an answer when your selection is ready.' : '{n} sources are included. Generate an answer when your selection is ready.', { n: included }) : t(hasAcademic ? 'Start an academic search, or attach PDFs.' : 'Attach PDFs, then generate an answer.')}
        latestAnswer={answer ? <><AnswerBlock eventCursor={view.last_event_id} runActive={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} researchId={id} title={answer.report_title ?? heading} version={answer.report_version ?? 0} answer={answer} sources={view.sources} busy={busy} dark={dark} reportOpen={openReportId === answer.id} onReportOpenChange={open => setOpenReportId(open ? answer.id : null)} onOpen={(passageId, highlightText) => setPassageTarget({ passageId, highlightText, fromCitation: true })} onAttachPdf={chooseSourcePdf} />{tableCards}</> : null} />
      {!answer && tableCards}
      {view.reportRuns[0] && <button type="button" className="report-artifact" onClick={() => setOpenEvidenceReportId(view.reportRuns[0].id)} aria-label={t('Open evidence report')}>
        <span className="report-artifact-preview" aria-hidden="true"><strong>{heading}</strong></span>
        <span className="report-artifact-copy"><span className="report-artifact-meta"><FileText size={13} aria-hidden />{view.reportRuns[0].status === 'valid' ? t('Evidence report · V{n}', { n: view.reportRuns[0].report_version ?? '' }) : view.reportRuns[0].status === 'draft' ? t('Evidence report · draft') : t('Evidence report · being written')}</span><strong>{heading}</strong>{view.reportRuns[0].status === 'in_progress' && <small role="status">{t(latestEvidenceReportRun?.status === 'paused' ? 'Report paused' : 'The report is being written.')}</small>}</span>
        <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
      </button>}
      {view.scope.source_scope === 'attached_and_academic' && <div className="research-seed">
        <div><strong>{t('PDFs guiding the search')}</strong>
          {view.scope.seed_status === 'ready' || (view.scope.seed_status === 'stale' && view.scope.seeds.length)
            ? <ul className="research-seed-uses">{view.scope.seeds.map(seed =>
                <li key={seed.source_version_id}><span>{seed.title}</span>{seedUseText(seed.use)}</li>)}</ul>
            : <p>{view.scope.seed_status === 'question_only'
                ? t('This earlier research searches from the question. Choose PDFs to guide a later search.')
                : t('Choose readable PDFs before searching scholarly providers.')}</p>}
        </div>
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
            <Button variant="outline" size="sm" disabled={busy || active || !tickedSeeds.length} onClick={() => void saveSeeds(tickedSeeds)}>{t('Use selected PDFs')}</Button>
            <small>{t('{n} of {max} chosen', { n: tickedSeeds.length, max: MAX_SEED_PDFS })}
              {tickedSeeds.length >= MAX_SEED_PDFS && seedCandidates.length > MAX_SEED_PDFS ? ` · ${t('untick one to choose another')}` : ''}
              {active ? ` · ${t('available when the run ends')}` : ''}</small>
          </div>
        </fieldset>}
        {view.scope.seed_status === 'stale' && storedSeedIds.length > 0 &&
          <Button variant="outline" size="sm" disabled={busy || active} onClick={() => void saveSeeds(view.scope.seeds.map(seed => seed.source_version_id), true)}>{t('Use current PDF text')}</Button>}
        {view.scope.seed_status === 'stale' && <Notice tone="attention">{t('A selected PDF changed or was removed. Select the current PDFs again before searching.')}</Notice>}
        {view.scope.seed_not_selected.length > 0 &&
          <Notice tone="info">{t('Only {max} PDFs can guide a search. Left out: {titles}.', { max: MAX_SEED_PDFS, titles: view.scope.seed_not_selected.map(item => item.title).join('; ') })}</Notice>}
        {view.scope.seed_skipped.length > 0 &&
          <Notice tone="attention">{t('Not used: {items}.', { items: view.scope.seed_skipped.map(item => `${seedTitle(item.source_version_id)} (${seedSkipText(item.reason)})`).join('; ') })}</Notice>}
        {view.scope.seed_status === 'ready' && view.scope.seeds.some(seed => seed.page_count != null && seed.text_pages < seed.page_count) &&
          <Notice tone="attention">{t('Some PDF pages have no extracted text; the search uses only the readable passages.')}</Notice>}
        {!seedCandidates.length && <Notice tone="attention">{t('Attach a PDF with readable text, or read scanned pages with OCR, to guide the search.')}</Notice>}
      </div>}
      {/* Before the first answer, the next step is getting the included sources' PDFs (D49); the panel carries the answer button. */}
      {!answer && included > 0 && !(active && run?.kind !== 'pdf_collection' && run?.kind !== 'pdf_ocr') && view.runs.some(r => r.kind === 'discovery' || r.kind === 'pdf_collection') ? <PdfReadiness researchId={id} view={view} busy={busy} hasAcademic={hasAcademic && seedSearchReady} act={async (action, success) => { await act(action, success) }} onSearchAgain={startDiscovery} onAnswer={startAnswer} onUpload={chooseSourcePdf} ocrTool={ocrTool} onReadWithOcr={(source, assetId) => { void readWithOcr(source, assetId) }} onDropFiles={dropForWaiting} /> :
      /* One next step after the last run: without an answer it is the primary action, with one the answer card's own "Open report" leads.
         While a run works there is no next step to offer, so the panel stays away rather than showing disabled buttons. */
      active ? (run?.target?.pipeline ? <p className="pdf-ready-lede" role="status">{t('Building the study table. The app chose its columns itself; open the table to review them.')}</p> : null) : <><div className="answer-actions">
        <Button variant={answer ? 'outline' : 'default'} disabled={busy || active || !(included || answersWithoutInclude)} onClick={startAnswer}><Sparkles size={15} />{t(answer ? 'Generate a new answer' : 'Generate source-linked answer')}</Button>
        {/* Searching again is a quiet text action; the first search of a research is still a button of its own. */}
        {hasAcademic && (view.search_runs.length
          ? <Button className="quiet-action" variant="ghost" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}>{t('Search again')}</Button>
          : <Button variant="outline" disabled={busy || active || !seedSearchReady} onClick={startDiscovery}><Search size={15} />{t('Search providers')}</Button>)}
      </div><UploadedTextNote semantic={view.semantic} /></>}
      </div>
    {/* The answer's PDF suggestions attach through the same picker as the Sources panel. */}
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void upload(e.target.files); e.target.value = '' }} />
    <input ref={sourceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void uploadToSource(e.target.files); e.target.value = '' }} />
    <input ref={replaceFileInput} type="file" accept=".pdf,application/pdf" hidden onChange={e => { void reviewReplacement(e.target.files); e.target.value = '' }} />

    <RevisionForm key={view.research.version} question={view.scope.question} disabled={busy || active}
      keyTerms={view.scope.key_terms ?? ''} keyTermsRef={keyTerms}
      onSubmit={(text, terms) => act(() => api.reviseScope(id, text, view.research.version, terms), t('Question revised. Earlier answers stay visible and are marked as belonging to the previous revision.'))} />
    </div>
    {/* Hidden, not removed, while a panel is open: a panel opened from the rail hands focus back to its button. */}
    <aside className="research-rail" aria-labelledby="research-rail-title" hidden={Boolean(panel)}>
      <h2 id="research-rail-title" className="research-rail-title">{t('Artifacts')} <span className="research-tab-count">{reports.length + view.reportRuns.length + (tables?.length ?? 0)}</span></h2>
      <ArtifactsTab reports={reports} tables={tables} reportRuns={view.reportRuns} heading={heading} onOpenReport={setOpenReportId} onOpenEvidenceReport={setOpenEvidenceReportId} onOpenTable={openTable} />
    </aside>
    </div>
    </div>
    {panel && <SplitPanel stack={panels} phone={phone} />}
    </div>

    {/* Each former tab is a panel; its content is unchanged and renders into the panel frame while it is open. */}
    <StackPanel name="sources" title={t('Sources')} icon={BookOpen}>
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
      {view.search_runs.length > 0 && <details className="search-summary"><summary><span><Search size={14} aria-hidden />{t('Search details')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{t(view.search_runs.length === 1 ? '{n} provider search' : '{n} provider searches', { n: view.search_runs.length })}</small></summary><div className="search-summary-list">{view.search_runs.map(s => <div key={s.id}><span>“{s.query_text}”</span><small>{providerName(s.provider)} · {['completed', 'zero_results'].includes(s.status) ? t(s.status.replace('_', ' ')) : serviceErrorSentence({ kind: serviceKind(s.error?.service_kind ?? s.error?.error_kind ?? s.status, s.error?.http_status), service: providerName(s.provider), resetAt: s.error?.reset_at, effect: view.runs.find(r => r.id === s.run_id)?.status === 'completed' ? 'continued' : undefined })} · {t('{count} of {total} records', { count: s.result_count, total: s.provider_total ?? '?' })} · {t(s.access_mode)}{s.scope_revision !== view.research.current_scope_revision ? ` ${t('· for question revision {n}', { n: s.scope_revision })}` : ''}</small></div>)}</div></details>}
      {view.counts.removed > 0 && <p className="removed-summary"><ListMinus size={14} aria-hidden /><span>{t(view.counts.removed === 1 ? 'You removed {n} source from this research.' : 'You removed {n} sources from this research.', { n: view.counts.removed })}
        {view.counts.removed_found_again > 0 && ` ${t(view.counts.removed_found_again === 1 ? '{n} of them was found again by a later search and is not listed.' : '{n} of them were found again by a later search and are not listed.', { n: view.counts.removed_found_again })}`}</span>
        <a href="#/trash">{t('Show in Trash')}</a></p>}
      <TextRecoveryContext.Provider value={{ researchId: id, eventCursor: view.last_event_id, busy, acceptView: next => { setView(next); onChanged() }, reload: load }}><SourceList sources={view.sources} busy={busy} filter={sourceFilter} onFilter={setSourceFilter} focus={sourceFocus} onFocus={setSourceFocus} picked={picked} onPick={setPicked} onRemoveFromResearch={source => { void askRemoval([source.source_version_id]) }}
        onSelect={(source, state) => act(() => api.select(id, source.source_version_id, state, source.selection.version))}
        onReason={(source, reason) => act(() => api.select(id, source.source_version_id, source.selection.state, source.selection.version, reason), t('Reason saved with your choice.'))}
        onAbstract={source => source.access.abstract_passage_id && setPassageTarget({ passageId: source.access.abstract_passage_id, highlightText: null, fromCitation: false })}
        onDiscoverPdf={source => { void discoverPdf(source) }} onAttachPdf={chooseSourcePdf} onAttachCandidate={(source, candidateId) => { void attachPdfCandidate(source, candidateId) }} onOpenPdf={(_, assetId) => setPdfTarget({ assetId })}
        onRemoveAsset={removeSourcePdf} onReplaceAsset={chooseReplacement} onReextract={(source, assetId) => { void reextract(source, assetId) }} onRereadEquations={(source, assetId) => { void rereadEquations(source, assetId) }} pdfFinding={pdfFinding}
        ocr={{ tool: ocrTool, runs: view.runs, onRead: (source, assetId) => { void readWithOcr(source, assetId) } }} /></TextRecoveryContext.Provider>
      {picked.length > 0 && <SelectionBar researchId={id} count={picked.length} busy={busy} active={active} onStartTable={() => askTableStart(picked)} onAddToTable={table => { void addToTable(table, picked) }}
        onRemove={() => { void askRemoval(picked) }} onClear={() => setPicked([])} />}
      </section>
    </StackPanel>
    <StackPanel name="queue" title={`${t('Awaiting your decision')} (${queueCount})`} icon={Inbox}>
      <HumanQueue researchId={id} view={view} dark={dark} onChanged={async () => { await load(); onChanged() }} onShowInSources={showInSources} />
    </StackPanel>
    <StackPanel name="pdfs" title={t('Get more full text')} icon={FileText}>
      <WaitingForPdf researchId={id} view={view} busy={busy} incoming={waitingFiles} onIncomingTaken={takeWaitingFiles} onChanged={async (announced?: string) => { if (announced) announcedRuns.current.add(announced); await load(); onChanged() }} />
    </StackPanel>
    <StackPanel name="table" title={t('Evidence table')} icon={Table2}>
      <EvidenceTab researchId={id} view={view} dark={dark} initialTableId={focusTable?.id ?? null} tableRequest={focusTable?.request ?? 0} modelText={modelText} onRunStarted={() => { void load(); onChanged() }} />
    </StackPanel>
    <StackPanel name="watch" title={t('Follow-up')} icon={Clock}>
      <FollowUpView researchId={id} view={view} dark={dark} onReload={followupCount.reload} onChanged={followupChanged} />
    </StackPanel>
    <StackPanel name="cands" title={t('Candidates')} icon={Lightbulb} keepMounted>
      <CandidatesView researchId={id} view={view} dark={dark} modelText={modelText} selection={candidateSelection} onCount={setCandidateCount} onRunChanged={() => { void load(); onChanged() }} />
    </StackPanel>
    <StackPanel name="activity" title={t('Activity')} icon={Clock}>
      <ActivityLog events={events} />
    </StackPanel>
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
    {olderReport && <AnswerBlock eventCursor={view.last_event_id} runActive={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} researchId={id} title={olderReport.title} version={olderReport.version} answer={olderReport.answer} sources={view.sources} busy={busy} dark={dark} showCard={false}
      reportOpen onReportOpenChange={open => { if (!open) setOpenReportId(null) }} onOpen={openPassage} onAttachPdf={chooseSourcePdf} />}
    {openEvidenceReportId && <ReportView researchId={id} reportId={openEvidenceReportId} view={view} title={heading} dark={dark} onClose={() => setOpenEvidenceReportId(null)}
      onOpenCandidate={candidate => { setOpenEvidenceReportId(null); setCandidateSelection({ ...candidate, id: candidate.card?.id ?? candidate.id }); openPanel('cands') }}
      onOpenCitation={(passageId, highlightText, expectHighlight) => setPassageTarget({ passageId, highlightText, fromCitation: expectHighlight, reportCitation: true })}
      onChanged={async () => { await load(); onChanged() }} />}
    <PassageSheet asPanel={!passageTarget?.reportCitation} researchId={id} passageId={passageTarget?.passageId ?? null} assetId={pdfTarget?.assetId ?? null} initialView={pdfTarget ? 'pdf' : 'text'} highlightText={passageTarget?.highlightText} expectHighlight={passageTarget?.fromCitation} citationLabels={passageTarget?.reportCitation ? { marked: t('Exact text cited in this report'), mark: t('Exact text cited in this report'), unmarked: t('This report citation has no located text anchor, so its passage opens without a mark.') } : undefined} sources={view.sources} dark={dark} onClose={() => { setPassageTarget(null); setPdfTarget(null) }}
      onRestoreSource={svid => { setPassageTarget(null); void act(() => api.restoreSources(id, [svid]), t('Restored to this research.')) }} />
  </section></PanelStackContext.Provider>
}
