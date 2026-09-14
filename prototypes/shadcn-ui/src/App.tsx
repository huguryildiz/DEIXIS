import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowUpRight, Bell, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, FileText, FileUp, FlaskConical, History, Library, Link2, Menu, Moon, Plus, Search, Settings2, ShieldCheck, Sparkles, Sun, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { LegacyAlerts, LegacyConnections, LegacyLibrary, SampleResearch } from './LegacyWorkspace'
import './App.css'

type ResearchIntent = 'Find papers' | 'Compare papers' | 'Evaluate an idea' | 'Draft a report'
type Session = { id: string; question: string; depth: string; scope: string; files: string[]; intent?: ResearchIntent }
type LocalAttachment = { file: File; kind: 'PDF' | 'BibTeX' | 'RIS' }
type ReviewTarget = 'candidate' | 'claim' | 'report'
type ReviewFocus = 'Source support' | 'Assumptions & feasibility' | 'Prior-art comparison'
type ReviewStage = 'setup' | 'report'
type FeedbackStatus = 'idle' | 'fed-back' | 'revision-requested'
type ReviewState = {
  target: ReviewTarget
  model: string
  focus: ReviewFocus
  additionalSearch: boolean
  snapshotId: string
  startedAt: string
  selectedFindingIds: string[]
  feedbackStatus: FeedbackStatus
}

const intakeActions: ResearchIntent[] = ['Find papers', 'Compare papers', 'Evaluate an idea', 'Draft a report']
const models = [
  { value: 'Aster · demo connection', name: 'Aster', detail: 'General review · simulated' },
  { value: 'Lumen · demo connection', name: 'Lumen', detail: 'Critical reading · simulated' },
  { value: 'Orion · demo connection', name: 'Orion', detail: 'Methods review · simulated' },
]
const reviewTargets: { value: ReviewTarget; label: string; detail: string }[] = [
  { value: 'report', label: 'Demo report', detail: 'The current question and its draft workspace' },
  { value: 'claim', label: 'Sample claim', detail: 'A single sample claim from this workspace' },
  { value: 'candidate', label: 'Sample candidate', detail: 'A possible research direction to challenge' },
]
const reviewFocuses: { value: ReviewFocus; detail: string }[] = [
  { value: 'Source support', detail: 'Does the supplied material support the wording?' },
  { value: 'Assumptions & feasibility', detail: 'Which assumptions need to be made explicit?' },
  { value: 'Prior-art comparison', detail: 'What comparison would make the question testable?' },
]
const demoFindings = [
  { id: 'scope', tag: 'Scope', title: 'Define the comparison boundary', claim: 'Sample review prompt: which comparison criteria should this research use?', evidence: 'Demo snapshot · question text only · no inspected passage', implication: 'A future review should name the metrics, operating assumptions, or context being compared.', recommendation: 'Add a short comparison boundary before collecting sources.', uncertainty: 'The underlying methods and their published evidence are not available in this demo.' },
  { id: 'assumption', tag: 'Assumption', title: 'Separate stated and inferred assumptions', claim: 'Sample review prompt: distinguish model, data and deployment assumptions where relevant.', evidence: 'Demo snapshot · no source material supplied', implication: 'Different readers may test different meanings of “assumptions.”', recommendation: 'List the assumption categories that matter for this question.', uncertainty: 'No domain-specific assumptions were inspected or verified.' },
  { id: 'evidence', tag: 'Evidence gap', title: 'A prior-art conclusion needs inspected sources', claim: 'The current workspace does not contain evidence that can support a prior-art comparison.', evidence: 'Demo snapshot · evidence set empty', implication: 'This review can flag a missing input, but cannot establish novelty or support.', recommendation: 'Retrieve and inspect the closest sources before making a comparative claim.', uncertainty: 'No academic search or model call has been made.' },
]
const sampleSession: Session = { id: 'sample-green-roofs', question: 'How do green roofs affect summer building energy demand?', depth: 'Standard', scope: 'Fixed synthetic sample', files: [] }

function readSessions(): Session[] {
  try { const value: unknown = JSON.parse(localStorage.getItem('quaestio-ui-sessions') || '[]'); return Array.isArray(value) ? value.filter((s): s is Session => s && typeof s.id === 'string' && typeof s.question === 'string' && typeof s.depth === 'string' && typeof s.scope === 'string' && Array.isArray(s.files) && s.files.every((f: unknown) => typeof f === 'string')) : [] } catch { return [] }
}

function initialReviewState(): ReviewState {
  return { target: 'report', model: models[0].value, focus: 'Source support', additionalSearch: false, snapshotId: '', startedAt: '', selectedFindingIds: [], feedbackStatus: 'idle' }
}

function AttachmentPreview({ attachment, dark, onClose }: { attachment: LocalAttachment | null; dark: boolean; onClose: () => void }) {
  const pdfFrame = useRef<HTMLIFrameElement>(null)
  const [text, setText] = useState('')
  useEffect(() => {
    if (!attachment) return
    let cancelled = false
    if (attachment.kind === 'PDF') {
      const objectUrl = URL.createObjectURL(attachment.file)
      if (pdfFrame.current) pdfFrame.current.src = objectUrl
      return () => URL.revokeObjectURL(objectUrl)
    }
    void attachment.file.slice(0, 64 * 1024).text().then(value => { if (!cancelled) setText(value) }).catch(() => { if (!cancelled) setText('This file could not be previewed in the browser.') })
    return () => { cancelled = true }
  }, [attachment])
  return <Sheet open={attachment !== null} onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet attachment-preview ${dark ? 'dark' : ''}`}><SheetHeader><SheetTitle>{attachment?.file.name || 'Local file preview'}</SheetTitle><SheetDescription>{attachment?.kind} · browser-only preview, not a research import</SheetDescription></SheetHeader><div className="sheet-body"><p>The file stays in this browser tab. No text is extracted for research and no source claim is verified.</p>{attachment?.kind === 'PDF' ? <iframe ref={pdfFrame} title={`Preview of ${attachment.file.name}`} /> : <><pre>{text || 'Opening file…'}</pre>{attachment && attachment.file.size > 64 * 1024 && <p>Only the first 64 KB is shown.</p>}</>}</div></SheetContent></Sheet>
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>(readSessions)
  const [active, setActive] = useState<Session | null>(null)
  const [view, setView] = useState('research')
  const [libraryCollection, setLibraryCollection] = useState('all')
  const [question, setQuestion] = useState('')
  const [intent, setIntent] = useState<ResearchIntent | null>(null)
  const [depth, setDepth] = useState('Standard')
  const [scope, setScope] = useState('Academic search')
  const [files, setFiles] = useState<string[]>([])
  const [localAttachments, setLocalAttachments] = useState<LocalAttachment[]>([])
  const [previewAttachment, setPreviewAttachment] = useState<LocalAttachment | null>(null)
  const [panel, setPanel] = useState<'evidence' | 'settings' | null>(null)
  const [sidebar, setSidebar] = useState(false)
  const [filter, setFilter] = useState('')
  const [notice, setNotice] = useState('')
  const [dark, setDark] = useState(() => { try { const theme = localStorage.getItem('quaestio-ui-theme'); return theme ? theme === 'dark' : true } catch { return true } })
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewStage, setReviewStage] = useState<ReviewStage>('setup')
  const [reviewSessionId, setReviewSessionId] = useState<string | null>(null)
  const [reviewDraft, setReviewDraft] = useState<ReviewState>(initialReviewState)
  const [reviewStates, setReviewStates] = useState<Record<string, ReviewState>>({})
  const fileInput = useRef<HTMLInputElement>(null)
  const questionInput = useRef<HTMLTextAreaElement>(null)
  const reviewTrigger = useRef<HTMLButtonElement | null>(null)

  useEffect(() => { document.documentElement.classList.toggle('dark', dark); return () => document.documentElement.classList.remove('dark') }, [dark])
  useEffect(() => { window.scrollTo(0, 0) }, [view])

  function save(next: Session[]) { setSessions(next); try { localStorage.setItem('quaestio-ui-sessions', JSON.stringify(next)) } catch { setNotice('Browser storage is unavailable. This session will not survive a reload.') } }
  function start(text = question) { if (!text.trim()) return; if (scope === 'Attached files' && !files.length) { setNotice('Attach at least one file before choosing “Attached files”.'); return } const next = { id: crypto.randomUUID(), question: text.trim(), depth, scope, files, intent: intent || undefined }; save([next, ...sessions]); setActive(next); setView('research'); setQuestion(''); setFiles([]); setLocalAttachments([]); setIntent(null); setSidebar(false) }
  function newResearch() { setActive(null); setView('research'); setSidebar(false); setNotice('') }
  function openSample() { setActive(sampleSession); setView('sample'); setSidebar(false) }
  function openLibrary(collection: 'all' | 'methods' = 'all') { setLibraryCollection(collection); setView('library'); setSidebar(false) }
  function toggleTheme() { setDark(!dark); try { localStorage.setItem('quaestio-ui-theme', dark ? 'light' : 'dark') } catch { /* Theme still works for this session. */ } }
  async function attach(list: FileList | null) {
    if (!list?.length) return
    const accepted: LocalAttachment[] = []
    const rejected: string[] = []
    for (const file of Array.from(list)) {
      const name = file.name.toLowerCase()
      const kind = name.endsWith('.pdf') ? 'PDF' : name.endsWith('.bib') ? 'BibTeX' : name.endsWith('.ris') ? 'RIS' : null
      if (!kind || (kind === 'PDF' && await file.slice(0, 5).text() !== '%PDF-')) { rejected.push(file.name); continue }
      accepted.push({ file, kind })
    }
    if (accepted.length) {
      setLocalAttachments(old => [...new Map([...old, ...accepted].map(item => [item.file.name, item])).values()])
      setFiles(old => [...new Set([...old, ...accepted.map(item => item.file.name)])])
    }
    setNotice(`${accepted.length ? `${accepted.length} file(s) selected for local preview; sessions keep filenames only.` : ''}${rejected.length ? ` ${rejected.join(', ')}: unsupported or invalid file.` : ''}`.trim())
  }
  function exportReport() { if (!active) return; const blob = new Blob([`# ${active.question}\n\nUI prototype — no research executed.\n\nTask: ${active.intent || 'General research'}\nDepth: ${active.depth}\nScope: ${active.scope}\n\nNo verified findings or source evidence are available.\n`], { type: 'text/markdown' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'deixis-demo.md'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }

  function openReview(target: ReviewTarget = 'report', trigger?: HTMLButtonElement) {
    if (trigger) reviewTrigger.current = trigger
    if (!active) return
    const previous = reviewStates[active.id]
    setReviewSessionId(active.id)
    setReviewDraft(previous ? { ...previous } : { ...initialReviewState(), target })
    setReviewStage(previous?.snapshotId ? 'report' : 'setup')
    setReviewOpen(true)
  }
  function closeReview() {
    setReviewOpen(false)
    setReviewSessionId(null)
    requestAnimationFrame(() => reviewTrigger.current?.focus())
  }
  function updateReviewDraft<K extends keyof ReviewState>(key: K, value: ReviewState[K]) { setReviewDraft(old => ({ ...old, [key]: value })) }
  function startReview() {
    if (!active) return
    const startedAt = new Date().toISOString()
    const state = { ...reviewDraft, snapshotId: `demo-${crypto.randomUUID().slice(0, 8)}`, startedAt, selectedFindingIds: [], feedbackStatus: 'idle' as FeedbackStatus }
    setReviewStates(old => ({ ...old, [active.id]: state }))
    setReviewDraft(state)
    setReviewStage('report')
  }
  function toggleFinding(id: string) {
    if (!reviewSessionId) return
    setReviewStates(old => { const current = old[reviewSessionId]; if (!current) return old; const selected = current.selectedFindingIds.includes(id) ? current.selectedFindingIds.filter(item => item !== id) : [...current.selectedFindingIds, id]; return { ...old, [reviewSessionId]: { ...current, selectedFindingIds: selected, feedbackStatus: 'idle' } } })
  }
  function sendFeedback(kind: Exclude<FeedbackStatus, 'idle'>) {
    if (!reviewSessionId) return
    const current = reviewStates[reviewSessionId]
    if (!current?.selectedFindingIds.length) { setNotice('Select at least one demo finding before sending review context.'); return }
    setReviewStates(old => ({ ...old, [reviewSessionId]: { ...old[reviewSessionId], feedbackStatus: kind } }))
    setNotice(kind === 'fed-back' ? 'Demo only: selected findings are queued as revision context. Main research is unchanged.' : 'Demo only: a revision request is staged for the next version. Main research is unchanged.')
  }
  function currentReview() { return reviewSessionId ? reviewStates[reviewSessionId] : undefined }
  const library = [...new Set(sessions.flatMap(s => s.files))]
  const reviewActive = currentReview() || reviewDraft
  const reviewSession = reviewSessionId ? sessions.find(s => s.id === reviewSessionId) || active : active

  return <div className={`app ${dark ? 'dark' : ''}`}>
    {sidebar && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'is-open' : ''}`}>
      <button className="brand" aria-label="DEIXIS home" onClick={newResearch}><span className="brand-mark" aria-hidden="true" /><span>DEIXIS</span></button>
      <Button className="new-button" variant="outline" onClick={newResearch}><Plus size={16} />New research</Button>
      <nav aria-label="Main navigation">
        <button className={view === 'research' ? 'selected' : ''} onClick={() => { setView('research'); setSidebar(false) }}><FlaskConical size={17} /> Research</button>
        <button className={view === 'sample' ? 'selected' : ''} onClick={openSample}><BookOpen size={17} /> Sample workspace</button>
        <button className={view === 'library' ? 'selected' : ''} onClick={() => openLibrary()}><Library size={17} /> Library <span className="nav-count">{library.length || ''}</span></button>
        <button className={view === 'connections' ? 'selected' : ''} onClick={() => { setView('connections'); setSidebar(false) }}><Settings2 size={17} /> Connections</button>
        <button className={view === 'alerts' ? 'selected' : ''} onClick={() => { setView('alerts'); setSidebar(false) }}><Bell size={17} /> Research alerts</button>
        <button className={view === 'history' ? 'selected' : ''} onClick={() => { setView('history'); setSidebar(false) }}><History size={17} /> History</button>
      </nav>
      <div className="recents-label">RECENT RESEARCH</div>
      <div className="recent-list">{sessions.length ? sessions.slice(0, 6).map(s => <button key={s.id} onClick={() => { setActive(s); setView('research'); setSidebar(false) }} title={s.question}>{s.question}</button>) : <p>Your questions will<br />find a home here.</p>}</div>
      <div className="sidebar-bottom"><span className="local-dot" /> Local workspace <button aria-label="Settings" onClick={() => setPanel('settings')}><Settings2 size={16} /></button></div>
    </aside>
    <div className="main-shell">
      <header><div className="breadcrumb"><Button variant="ghost" size="icon" className="mobile-menu" aria-label="Open navigation" onClick={() => setSidebar(true)}><Menu /></Button><span>Workspace</span><ChevronRight size={13} /><strong>{view === 'library' ? 'Library' : view === 'history' ? 'History' : view === 'sample' ? 'Sample research' : view === 'connections' ? 'Connections' : view === 'alerts' ? 'Research alerts' : active ? 'Research' : 'New research'}</strong></div><div className="header-actions"><span className="prototype-label">UI prototype</span><Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={dark ? 'Use light theme' : 'Use dark theme'}>{dark ? <Sun size={17} /> : <Moon size={17} />}</Button></div></header>
      <main>
      {view === 'research' && !active && <section className="welcome">
        <div className="eyebrow"><span /> A LITTLE CURIOSITY. A CLEARER PICTURE.</div>
        <h1>Where does your<br /><em>question</em>{' '}lead?</h1>
        <p className="intro">Explore the literature. Follow the evidence.<br />Make room for your next research idea.</p>
        <form className="composer" onSubmit={e => { e.preventDefault(); start() }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void attach(e.dataTransfer.files) }}>
          <label className="composer-label" htmlFor="research-question">What would you like to investigate?</label>
          <Textarea id="research-question" ref={questionInput} aria-label="Research question" placeholder="How do green roofs affect summer building energy demand?" value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); start() } }} />
          {localAttachments.length > 0 && <div className="attachments" aria-label="Files selected for local preview">{localAttachments.map(item => <div className="attachment-chip" key={item.file.name}><button type="button" onClick={() => setPreviewAttachment(item)} title={`Preview ${item.file.name}`}><FileText size={13} /><span>{item.file.name}</span><small>{item.kind}</small></button><button type="button" aria-label={`Remove ${item.file.name}`} onClick={() => { setFiles(old => old.filter(name => name !== item.file.name)); setLocalAttachments(old => old.filter(attachment => attachment.file.name !== item.file.name)) }}><X size={13} /></button></div>)}</div>}
          <div className="composer-controls">
            <div className="composer-options">
              <DropdownMenu><DropdownMenuTrigger type="button" className="composer-add" aria-label="Add sources"><Plus size={18} /></DropdownMenuTrigger><DropdownMenuContent className="intake-menu" align="start"><DropdownMenuGroup><DropdownMenuLabel>ADD SOURCES</DropdownMenuLabel><DropdownMenuItem className="intake-menu-item" onClick={() => fileInput.current?.click()}><FileUp size={17} /><span><strong>Attach file</strong><small>PDF, BibTeX or RIS · local preview</small></span></DropdownMenuItem><DropdownMenuItem className="intake-menu-item" disabled><Library size={17} /><span><strong>Add from library</strong><small>Requires a persistent library</small></span></DropdownMenuItem><DropdownMenuItem className="intake-menu-item" disabled><Link2 size={17} /><span><strong>Add by DOI</strong><small>Requires source lookup</small></span></DropdownMenuItem></DropdownMenuGroup></DropdownMenuContent></DropdownMenu>
              <Select value={scope} onValueChange={value => { if (value) setScope(value) }}><SelectTrigger aria-label="Source scope"><SelectValue /></SelectTrigger><SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}><SelectItem value="Academic search">Academic search</SelectItem><SelectItem value="Attached files">Attached files</SelectItem><SelectItem value="Files + academic search">Files + academic search</SelectItem></SelectContent></Select>
              <Select value={depth} onValueChange={value => { if (value) setDepth(value) }}><SelectTrigger aria-label="Research depth"><SelectValue /></SelectTrigger><SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>{['Quick', 'Standard', 'Detailed'].map(d => <SelectItem key={d} value={d}>{d}</SelectItem>)}</SelectContent></Select>
              <DropdownMenu><DropdownMenuTrigger type="button" className="composer-model" aria-label="Model connection">Model: not connected <ChevronDown size={14} /></DropdownMenuTrigger><DropdownMenuContent className="intake-menu model-menu" align="start"><DropdownMenuGroup><DropdownMenuLabel>MODEL CONNECTION</DropdownMenuLabel><p>No model has been verified for this browser-only prototype.</p><DropdownMenuItem className="intake-menu-item" onClick={() => { setView('connections'); setSidebar(false) }}><Settings2 size={17} /><span><strong>Manage connections</strong><small>Check availability and access</small></span><ArrowUpRight size={15} /></DropdownMenuItem></DropdownMenuGroup></DropdownMenuContent></DropdownMenu>
            </div>
            <Button className="send-button" type="submit" size="icon" disabled={!question.trim() || (scope === 'Attached files' && !files.length)} aria-label="Open demo research"><ArrowUpRight size={20} /></Button>
          </div>
        </form>
        <input ref={fileInput} type="file" accept=".pdf,.bib,.ris,application/pdf" multiple hidden onChange={e => { void attach(e.target.files); e.target.value = '' }} />
        <div className="composer-caption"><span>{scope === 'Attached files' && !files.length ? 'Attach a file to use this scope.' : `${intent ? `${intent} selected · ` : 'Files optional · '}no academic search or model call runs in this preview.`}</span><span>⌘ / Ctrl + Enter</span></div>
        <div className="starting-points" aria-label="Research task shortcuts">{intakeActions.map(action => <button key={action} className={intent === action ? 'active' : ''} aria-pressed={intent === action} onClick={() => { setIntent(action); questionInput.current?.focus() }}>{action}<ArrowUpRight size={16} /></button>)}</div>
        <div className="resume-section"><div className="resume-heading"><h2>Pick up where you left off</h2><span>LOCAL RESEARCH SPACES</span></div><div className="resume-list">{sessions.slice(0, 3).map(session => <button key={session.id} onClick={() => { setActive(session); setView('research') }}><History size={18} /><span><strong>{session.question}</strong><small>Saved question · research not run</small></span><ArrowUpRight size={16} /></button>)}<button onClick={openSample}><BookOpen size={18} /><span><strong>Green roofs & cooling</strong><small>Synthetic research workspace · evidence and report</small></span><ArrowUpRight size={16} /></button><button onClick={() => openLibrary('methods')}><Library size={18} /><span><strong>Methods for field studies</strong><small>Synthetic library collection · browse sources</small></span><ArrowUpRight size={16} /></button></div></div>
        <div className="demo-note">Interactive design preview · no searches or model calls are made.</div>
      </section>}
      {view === 'sample' && <SampleResearch onReview={trigger => openReview('report', trigger)} onManageCorpus={() => openLibrary()} />}
      {view === 'research' && active && <section className="research-view"><div className="section-label">RESEARCH WORKSPACE <span> / DEMO</span></div><h1>{active.question}</h1><p className="session-meta">{active.intent ? `${active.intent} · ` : ''}{active.depth} depth · {active.scope}</p><Tabs defaultValue="answer" key={active.id}><TabsList><TabsTrigger value="answer">Answer</TabsTrigger><TabsTrigger value="sources">Sources</TabsTrigger><TabsTrigger value="evidence">Evidence</TabsTrigger><TabsTrigger value="report">Report</TabsTrigger></TabsList><TabsContent value="answer"><div className="status-line"><span className="local-dot" />Question saved locally · Research has not started</div><h2>A question worth investigating.</h2><p>This preview shows how your research workspace will feel. A connected research service would retrieve papers, inspect the evidence and build a source-linked answer here.</p><h3>What would we examine?</h3><ol><li>The scope and assumptions behind your question.</li><li>The closest existing methods and relevant comparisons.</li><li>What the evidence supports, and what remains uncertain.</li></ol><div className="review-launch"><div><strong>Need a second reading?</strong><span>Open a bounded review with a demo model and inspect its separate report.</span></div><Button variant="outline" onClick={event => openReview('report', event.currentTarget)}><Sparkles size={16} />Review with another model</Button></div><button className="evidence-link" onClick={() => setPanel('evidence')}><BookOpen size={16} /> Preview the evidence panel <ArrowUpRight size={15} /></button></TabsContent><TabsContent value="sources"><h2>Your source collection</h2><p>No academic sources have been retrieved. Attached filenames below are demo placeholders, not inspected evidence.</p>{active.files.length ? active.files.map(f => <div className="file-row" key={f}><FileText size={18} /><span>{f}</span><small>Not inspected</small></div>) : <div className="empty-inline">Sources will appear here when a research service is connected.</div>}</TabsContent><TabsContent value="evidence"><h2>Evidence, with its context.</h2><p>Each finding should link to an inspected source passage. No findings are available in this demo.</p><div className="table-wrap"><table><thead><tr><th>Finding</th><th>Source</th><th>Evidence status</th><th>Action</th></tr></thead><tbody><tr><td>Example cell</td><td>Not connected</td><td>No evidence</td><td><button className="evidence-link" onClick={() => setPanel('evidence')}>Show evidence</button></td></tr></tbody></table></div></TabsContent><TabsContent value="report"><div className="report-heading"><div><h2>A report you can take with you.</h2><p>The exported Markdown contains your question and selected scope, explicitly marked as a demo. It contains no research findings.</p></div><span className="demo-pill">Demo report</span></div><div className="report-actions"><Button variant="outline" onClick={exportReport}><FileText size={16} />Export demo Markdown</Button><Button onClick={event => openReview('report', event.currentTarget)}><Sparkles size={16} />Review with another model</Button></div><div className="report-note"><CircleHelp size={16} /><span>The review is optional, bounded, and kept separate from the main research.</span></div></TabsContent></Tabs></section>}
      {view === 'history' && <section className="collection"><div className="section-label">YOUR WORKSPACE</div><h1>Research history</h1><p>Return to a question and keep your place.</p><label className="search-field"><Search size={17} /><input placeholder="Find a question…" aria-label="Search history" value={filter} onChange={e => setFilter(e.target.value)} /></label>{sessions.filter(s => s.question.toLowerCase().includes(filter.toLowerCase())).map(s => <button className="history-row" key={s.id} onClick={() => { setActive(s); setView('research') }}><div><strong>{s.question}</strong><small>{s.depth} · Demo session</small></div><ArrowUpRight size={17} /></button>)}{!sessions.filter(s => s.question.toLowerCase().includes(filter.toLowerCase())).length && <div className="empty-inline">{sessions.length ? 'No matching questions.' : 'No research yet. Start with a question.'}</div>}</section>}
      <div style={{ display: view === 'library' ? 'contents' : 'none' }}><LegacyLibrary collection={libraryCollection} onCollectionChange={setLibraryCollection} savedFilenames={library} onResearch={openSample} onNotice={setNotice} /></div>
      {view === 'connections' && <LegacyConnections />}
      {view === 'alerts' && <LegacyAlerts onNotice={setNotice} />}
      {notice && <div role="status" className="notice">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16} /></button></div>}
      </main><footer><span>DEIXIS — Every cell points to its source.</span><span>Alternative interface / 01</span></footer>
    </div>
    <Sheet open={panel !== null} onOpenChange={open => { if (!open) setPanel(null) }}><SheetContent className={`detail-sheet ${dark ? 'dark' : ''}`}><SheetHeader><SheetTitle>{panel === 'settings' ? 'Workspace settings' : 'Behind the finding'}</SheetTitle><SheetDescription>{panel === 'settings' ? 'Preferences for this local UI preview.' : 'A source should always be one step away.'}</SheetDescription></SheetHeader><div className="sheet-body">{panel === 'settings' ? <><div className="section-label">APPEARANCE</div><Button variant="outline" onClick={toggleTheme}>{dark ? <Sun size={16} /> : <Moon size={16} />}{dark ? 'Use light theme' : 'Use dark theme'}</Button><h3>Model connection</h3><p>Demo only. No API keys, model connections or research services are configured.</p><h3>Local storage</h3><p>Question text, selected options and PDF filenames are saved in this browser. PDF contents are not read or stored.</p></> : <><span className="evidence-status">No inspected source</span><h3>Source passage</h3><blockquote>A verified passage will appear here after a source has been inspected.</blockquote><dl><dt>Publication / version</dt><dd>Not available</dd><dt>Page or location</dt><dd>Not available</dd><dt>Author statement / interpretation</dt><dd>Not assessed</dd></dl><p className="panel-note">This panel demonstrates the interaction. It does not contain a scientific claim or an invented citation.</p></>}</div></SheetContent></Sheet>
    <Sheet open={reviewOpen} onOpenChange={open => { if (!open) closeReview() }}>
      <SheetContent className={`review-sheet ${dark ? 'dark' : ''}`} side="right">
        <SheetHeader className="review-header"><div className="review-kicker"><span className="review-mark"><Sparkles size={15} /></span><span>OPTIONAL REVIEW · DEMO</span></div><SheetTitle>{reviewStage === 'report' ? 'Review report' : 'Review with another model'}</SheetTitle><SheetDescription>{reviewStage === 'report' ? 'A separate assessment linked to this demo snapshot.' : 'Choose a bounded review before anything is sent.'}</SheetDescription></SheetHeader>
        <div className="review-body">
          {reviewStage === 'setup' && reviewSession && <>
            <div className="review-demo-banner"><ShieldCheck size={17} /><div><strong>No real model request</strong><span>All model choices are placeholders. Nothing leaves this browser; no searches or model calls run.</span></div></div>
            <div className="review-section"><div className="section-label">1 · REVIEW TARGET</div><div className="review-targets">{reviewTargets.map(item => <button key={item.value} className={reviewDraft.target === item.value ? 'is-selected' : ''} aria-pressed={reviewDraft.target === item.value} onClick={() => updateReviewDraft('target', item.value)}><span><strong>{item.label}</strong><small>{item.detail}</small></span>{reviewDraft.target === item.value && <Check size={16} />}</button>)}</div></div>
            <div className="review-section"><div className="section-label">2 · MODEL CONNECTION</div><Select value={reviewDraft.model} onValueChange={value => { if (value) updateReviewDraft('model', value) }}><SelectTrigger aria-label="Review model" className="review-select"><SelectValue /></SelectTrigger><SelectContent>{models.map(model => <SelectItem value={model.value} key={model.value}><span className="select-model"><strong>{model.name}</strong><small>{model.detail}</small></span></SelectItem>)}</SelectContent></Select><p className="field-note">A different model is another assessment, not proof of independence or correctness.</p></div>
            <div className="review-section"><div className="section-label">3 · REVIEW FOCUS</div><div className="focus-options">{reviewFocuses.map(item => <label key={item.value} className={reviewDraft.focus === item.value ? 'is-selected' : ''}><input type="radio" name="review-focus" checked={reviewDraft.focus === item.value} onChange={() => updateReviewDraft('focus', item.value)} /><span><strong>{item.value}</strong><small>{item.detail}</small></span></label>)}</div></div>
            <div className="review-section"><div className="section-label">4 · SNAPSHOT SCOPE</div><div className="snapshot-card"><div className="snapshot-row"><span>Target</span><strong>{reviewTargets.find(item => item.value === reviewDraft.target)?.label}</strong></div><div className="snapshot-row"><span>Question</span><strong>{reviewSession.question}</strong></div><div className="snapshot-row"><span>Sample content</span><strong>{reviewDraft.target === 'report' ? 'Question and selected scope; no generated research report.' : reviewDraft.target === 'claim' ? 'Illustrative claim: an approach improves an outcome under stated conditions. No actual finding.' : 'Illustrative direction: compare approaches under an explicit assumption. Not a selected research topic.'}</strong></div><div className="snapshot-row"><span>Outgoing content</span><strong>Question text, selected target and available filenames</strong></div><div className="snapshot-row"><span>Evidence access</span><strong>{reviewSession.files.length ? 'Filenames only · contents not inspected' : 'No inspected evidence supplied'}</strong></div><div className="snapshot-row"><span>Budget</span><strong>Demo placeholder · no spend estimate</strong></div><div className="snapshot-id"><span>Immutable input snapshot</span><code>Created when review starts</code></div></div><label className="search-toggle"><input type="checkbox" checked={reviewDraft.additionalSearch} onChange={e => updateReviewDraft('additionalSearch', e.target.checked)} /><span><strong>Allow additional search</strong><small>{reviewDraft.additionalSearch ? 'Simulated option enabled · no search will run' : 'Off by default · use supplied evidence only'}</small></span><span className="toggle-track" aria-hidden="true"><span /></span></label></div>
            <div className="review-footer"><Button className="review-start" onClick={startReview}><Sparkles size={16} />Start bounded demo review</Button><p>Starting authorizes this optional review. The reviewer has no write access to the main research.</p></div>
          </>}
          {reviewStage === 'report' && reviewSession && <>
            <div className="report-meta"><button className="back-button" onClick={() => setReviewStage('setup')}><ArrowLeft size={15} />Review settings</button><span className="demo-pill">Demo finding set</span></div>
            <div className="review-report-title"><h2>{reviewTargets.find(item => item.value === reviewActive.target)?.label}</h2><p>Reviewed by <strong>{reviewActive.model}</strong> · {reviewActive.focus}</p></div>
            <div className="review-integrity"><ShieldCheck size={16} /><span><strong>Separate report.</strong> No real evidence was inspected. The same illustrative prompts are shown for every model and focus; they are not an assessment of your question.</span></div>
            <div className="snapshot-summary"><div><span>Snapshot</span><code>{reviewActive.snapshotId}</code></div><div><span>Started</span><strong>{reviewActive.startedAt ? new Date(reviewActive.startedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Demo run'}</strong></div><div><span>Search</span><strong>{reviewActive.additionalSearch ? 'Additional search selected (simulated)' : 'Supplied evidence only'}</strong></div></div>
            <div className="review-section findings-section"><div className="section-label">FINDINGS TO CONSIDER</div><p className="findings-help">Sample content, not generated analysis. Select a finding to carry into a future revision request. Nothing is applied automatically.</p><div className="findings-list">{demoFindings.map(finding => <label className={`finding-card ${reviewActive.selectedFindingIds.includes(finding.id) ? 'is-selected' : ''}`} key={finding.id}><input type="checkbox" checked={reviewActive.selectedFindingIds.includes(finding.id)} onChange={() => toggleFinding(finding.id)} /><span className="finding-check">{reviewActive.selectedFindingIds.includes(finding.id) && <Check size={13} />}</span><span className="finding-content"><span className="finding-tag">{finding.tag} · demo</span><strong>{finding.title}</strong><span className="finding-claim">{finding.claim}</span><span className="finding-label">Evidence reference</span><span className="finding-evidence">{finding.evidence}</span><span className="finding-label">Possible implication</span><span className="finding-detail">{finding.implication}</span><span className="finding-label">Suggested change</span><span className="finding-detail">{finding.recommendation}</span><span className="finding-uncertainty"><CircleHelp size={13} />{finding.uncertainty}</span></span></label>)}</div></div>
            <div className="feedback-box"><div><strong>{reviewActive.selectedFindingIds.length ? `${reviewActive.selectedFindingIds.length} finding${reviewActive.selectedFindingIds.length === 1 ? '' : 's'} selected` : 'Select findings for the next step'}</strong><span>Choose whether to feed context back or stage a revision request.</span></div><div className="feedback-actions"><Button variant="outline" onClick={() => sendFeedback('fed-back')} disabled={!reviewActive.selectedFindingIds.length}><ArrowUpRight size={15} />Feed back</Button><Button onClick={() => sendFeedback('revision-requested')} disabled={!reviewActive.selectedFindingIds.length}>Request revision</Button></div>{reviewActive.feedbackStatus !== 'idle' && <div className="feedback-status" role="status"><Check size={14} />{reviewActive.feedbackStatus === 'fed-back' ? 'Demo context queued for the main workflow.' : 'Demo revision request staged for a future version.'} Main research remains unchanged.</div>}</div>
            <p className="report-limit">A failed or incomplete run would not count as a successful review. This report is only a UI demonstration.</p>
          </>}
        </div>
      </SheetContent>
    </Sheet>
    <AttachmentPreview key={previewAttachment?.file.name || 'closed'} attachment={previewAttachment} dark={dark} onClose={() => setPreviewAttachment(null)} />
  </div>
}
