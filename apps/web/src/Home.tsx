import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Popover } from '@base-ui/react/popover'
import { ArrowUp, Brain, Check, ChevronDown, Cpu, FileText, FileUp, Gauge, LibraryBig, Lightbulb, Link2, Network, Paperclip, PenLine, Plus, RotateCw, ScanSearch, Search, ShieldCheck, SlidersHorizontal, Table2, Telescope, X, Zap, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from './Toast'
import { api, ApiError, homeApi, preferencesApi, type Connections, type Effort, type EffortLimits, type IntentOutcome, type ModelHealth, type ModelOption, type ModelRole, type ResearchIntent, type ResearchSummary, type RoleModelSetting, type SeedSelection, type SourceScope, type Suggestion } from './api'
import { connectionName, fileRestoreNote, fileRestoreTone, reasoningLabel, scopeLabels, shownVersion } from './labels'
import { t, uiLanguage, uiLocale } from './i18n'
import { ZoteroDialog, type ZoteroChoice } from './ZoteroDialog'
import { ConnectionIcon } from './connectionIcons'
import { Notice } from './Notice'
import { SemanticSetupNote } from './SemanticNotes'
import { defaultEffort, exposesEffortControl, listedEffort } from './modelEffort'

export const effortLabels: Record<Effort, string> = { quick: 'Quick', standard: 'Standard', detailed: 'Detailed' }

// Limits mirror TEST_EFFORT_BUDGETS in backend/deixis/domain/rules.py.
export const scopeOptions: Record<SourceScope, { icon: LucideIcon; detail: string }> = {
  academic: { icon: Search, detail: 'Searches scholarly sources to answer your question.' },
  attached: { icon: Paperclip, detail: 'Only the PDFs and Zotero items you add; no search runs' },
  attached_and_academic: { icon: FileText, detail: 'Searches using your PDFs and your question. Only included sources are used in the answer.' },
}
export const effortOptions: Record<Effort, { icon: LucideIcon }> = {
  quick: { icon: Zap },
  standard: { icon: Gauge },
  detailed: { icon: Telescope },
}

// The depth text, from the fast path's modes (`fast_path.MODES`): the same numbers the run is given, so a changed mode
// cannot leave this text behind. Without an answer from the server the depth carries no text at all. A model this
// computer runs has no read or answer deadline (D39), so its time depends on the computer and no minutes are shown.
function effortDetail(effort: Effort, limits: EffortLimits | null | undefined, local = false): string | undefined {
  const e = limits?.efforts?.[effort]
  if (!e) return undefined
  const number = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
  if (local) return t('Local model: no time limit, it depends on this computer · up to {papers} papers', { papers: number(e.papers) })
  return t('About {minutes} min · up to {papers} papers', { minutes: number(e.minutes), papers: number(e.papers) })
}
// Connections whose model runs on this computer (backend `openai_compat.LOCAL_CONNECTIONS`).
const LOCAL_CONNECTIONS = new Set(['ollama', 'local_server'])

// A row of the Home menus (mockup: icon, title, a grey line under it, an optional LATER badge at the right).
function MenuRow({ icon: Icon, title, detail, later }: { icon: LucideIcon; title: string; detail?: ReactNode; later?: boolean }) {
  return <span className="home-menu-row"><Icon size={16} aria-hidden /><span className="home-menu-text">{title}{detail && <small>{detail}</small>}</span>{later && <span className="home-menu-badge">{t('Later')}</span>}</span>
}

export function Option({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail?: ReactNode }) {
  return <span className="intake-option"><Icon size={16} /><span><strong>{title}</strong>{detail && <small>{detail}</small>}</span></span>
}

// The models of every connection in one list. An entry's id is `connection:model`, so each role can pick from any connection.
export type ConnectionModel = ModelOption & { connection: string; model: string }
export const modelKey = (connection: string, model: string) => `${connection}:${model}`
export const connectionModels = (connections: Connections): ConnectionModel[] =>
  Object.entries(connections.models).flatMap(([connection, health]) => (health.models ?? []).map(m => ({ ...m, id: modelKey(connection, m.id), connection, model: m.id })))
// A connection can run a step when it is ready, or when its saved key is only waiting for the first step to check it (E6).
export const canRun = (health?: ModelHealth) => !!health && (health.ready || health.verification === 'pending')
// Why implemented connections offer no model.
export const notReadyReasons = (connections: Connections) =>
  Object.values(connections.models).filter(h => !canRun(h)).map(h => `${connectionName(h.connection)}: ${h.reason ?? ''}`).join('; ')

// The most PDFs that guide one search (D3); the backend enforces it.
export const MAX_SEED_PDFS = 5

// Step roles and what each does; the composer and Settings describe them the same way. Text is English; callers use t().
export const modelRoles: Record<ModelRole, { label: string; icon: LucideIcon; hint: string }> = {
  answer: { label: 'Answer', icon: PenLine, hint: 'Writes the answer from the passages of the sources you include, linking each claim to its passage.' },
  literature: { label: 'Literature', icon: ScanSearch, hint: 'Plans the searches in the scholarly providers and proposes which results to include. You make the final selection.' },
  reviewer: { label: 'Reviewer', icon: ShieldCheck, hint: 'When an answer is ready, checks each claim against the passages it cites. It never changes the answer and is not independent verification.' },
}

// One model role (answer, literature, reviewer): a model and, when the model lists them, its reasoning effort.
// `choices` are non-model entries such as "Default" or "Off"; they have no effort.
export function ModelPicker({ role, icon: Icon, hint, models, value, onChange, effort, onEffort, choices = [], defaultOpen = false }: {
  role: string; icon: LucideIcon; hint: string; models: ConnectionModel[]; value: string; onChange: (value: string) => void
  effort: string | null; onEffort: (effort: string | null) => void; choices?: { value: string; title: string; detail: string }[]
  // The Home composer opens the palette of the role chosen in its Models menu straight away.
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [query, setQuery] = useState('')
  const [activeValue, setActiveValue] = useState(value)
  const searchRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const chosen = models.find(m => m.id === value)
  const efforts = exposesEffortControl(chosen) ? chosen?.reasoning_efforts ?? [] : []
  const name = (v: string) => choices.find(c => c.value === v)?.title ?? models.find(m => m.id === v)?.display_name ?? v
  const normalizedQuery = query.trim().toLocaleLowerCase(uiLocale())
  const matches = (...parts: Array<string | null | undefined>) => !normalizedQuery || parts.some(part => part?.toLocaleLowerCase(uiLocale()).includes(normalizedQuery))
  const visibleChoices = choices.filter(choice => matches(choice.title, choice.detail))
  const visibleModels = models.filter(model => matches(model.display_name, model.description, connectionName(model.connection)))
  const groups = [...new Set(visibleModels.map(model => model.connection))]
  const entries = [
    ...visibleChoices.map(choice => ({ value: choice.value, title: choice.title, detail: choice.detail, connection: null as string | null, isDefault: false })),
    ...visibleModels.map(model => ({ value: model.id, title: model.display_name, detail: model.description ?? '', connection: model.connection, isDefault: Boolean(model.is_default) })),
  ]
  const active = entries.find(entry => entry.value === activeValue) ?? entries.find(entry => entry.value === value) ?? entries[0]

  const choose = (next: string) => {
    onChange(next)
    setOpen(false)
  }
  const move = (direction: 1 | -1) => {
    if (!entries.length) return
    const current = entries.findIndex(entry => entry.value === active?.value)
    const next = (current + direction + entries.length) % entries.length
    setActiveValue(entries[next].value)
    requestAnimationFrame(() => document.getElementById(`${listId}-${next}`)?.scrollIntoView({ block: 'nearest' }))
  }
  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      move(event.key === 'ArrowDown' ? 1 : -1)
    } else if (event.key === 'Enter' && active) {
      event.preventDefault()
      choose(active.value)
    }
  }
  const optionId = (optionValue: string) => {
    const index = entries.findIndex(entry => entry.value === optionValue)
    return index < 0 ? undefined : `${listId}-${index}`
  }
  const option = (optionValue: string, title: string, detail: string, connection: string | null, isDefault = false) => (
    <button id={optionId(optionValue)} type="button" role="option" aria-selected={optionValue === value}
      className={`model-palette-option ${optionValue === active?.value ? 'is-active' : ''}`}
      onMouseMove={() => setActiveValue(optionValue)} onFocus={() => setActiveValue(optionValue)} onClick={() => choose(optionValue)}>
      <span className="model-palette-option-icon">{connection ? <ConnectionIcon id={connection} /> : <Icon size={16} />}</span>
      <span className="model-palette-option-copy"><strong>{title}</strong><small>{detail}</small></span>
      {isDefault && <span className="model-palette-badge">{t('Default')}</span>}
      <Check className="model-palette-check" size={15} aria-hidden />
    </button>
  )
  return <div className="model-role">
    <Popover.Root open={open} onOpenChange={next => { setOpen(next); if (next) { setQuery(''); setActiveValue(value) } }}>
      <Popover.Trigger data-slot="select-trigger" className="model-picker-trigger" aria-label={t('{role} model', { role })} title={hint}>
        <Icon size={15} /><span className="model-role-name">{role}</span><span className="model-picker-value">{name(value)}</span><ChevronDown size={14} className="model-picker-chevron" aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Backdrop className="model-palette-backdrop" />
        <Popover.Positioner className="model-palette-positioner" side="bottom" align="start" sideOffset={8} collisionPadding={14}>
          <Popover.Popup className="model-palette" initialFocus={searchRef}>
            <div className="model-palette-header">
              <Popover.Title className="model-palette-title">{t('{role} model', { role })}</Popover.Title>
              <Popover.Description className="model-palette-description">{hint}</Popover.Description>
              <label className="model-palette-search">
                <Search size={16} aria-hidden /><span className="sr-only">{t('Search models or providers')}</span>
                <input ref={searchRef} value={query} onChange={event => { setQuery(event.target.value); setActiveValue('') }}
                  onKeyDown={onSearchKeyDown} placeholder={t('Search models or providers')} role="combobox" aria-expanded="true"
                  aria-controls={listId} aria-activedescendant={active ? optionId(active.value) : undefined} autoComplete="off" />
              </label>
            </div>
            <div id={listId} className="model-palette-list" role="listbox" aria-label={t('{role} model', { role })}>
              {visibleChoices.length > 0 && <section className="model-palette-group" aria-label={t('Options')}>
                <div className="model-palette-group-label">{t('Options')}</div>
                {visibleChoices.map(choice => option(choice.value, choice.title, choice.detail, null))}
              </section>}
              {groups.map(connection => <section className="model-palette-group" aria-label={connectionName(connection)} key={connection}>
                <div className="model-palette-group-label"><ConnectionIcon id={connection} /><span>{connectionName(connection)}</span><small>{visibleModels.filter(model => model.connection === connection).length}</small></div>
                {visibleModels.filter(model => model.connection === connection).map(model => option(model.id, model.display_name, model.description ?? '', model.connection, Boolean(model.is_default)))}
              </section>)}
              {entries.length === 0 && <div className="model-palette-empty"><Search size={17} aria-hidden /><span>{t('No models match “{query}”', { query })}</span></div>}
            </div>
            {active && <div className="model-palette-preview" aria-live="polite">
              <span>{active.connection ? connectionName(active.connection) : role}{active.isDefault ? ` · ${t('Default')}` : ''}</span>
              <strong>{active.title}</strong>
              {active.detail && <p>{active.detail}</p>}
              <small>{t('Press Enter to select')}</small>
            </div>}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
    {efforts.length > 0 &&
      <Select value={effort ?? '__provider_default'} onValueChange={v => { if (v) onEffort(v === '__provider_default' ? null : v) }}>
        <SelectTrigger aria-label={t('{role} reasoning effort', { role })} title={t('How long the {role} model thinks', { role: role.toLocaleLowerCase(uiLocale()) })}><SelectValue>{(v: string) => <><Brain size={15} />{v === '__provider_default' ? t('Provider default') : reasoningLabel(v)}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
          <div className="intake-select-heading" aria-hidden="true">{t('{role} reasoning effort', { role })}</div>
          <p className="intake-select-description" aria-hidden="true">{t('How long the {role} model reasons before it replies. Higher settings take longer.', { role: role.toLocaleLowerCase(uiLocale()) })}</p>
          <SelectItem value="__provider_default"><Option icon={Brain} title={t('Provider default')} detail={t('Let the current model choose its default effort')} /></SelectItem>
          {efforts.map(e => <SelectItem key={e.id} value={e.id}><Option icon={Brain} title={reasoningLabel(e.id)} detail={[e.description, e.id === chosen?.default_reasoning_effort ? t('Model default') : ''].filter(Boolean).join(' · ') || undefined} /></SelectItem>)}
        </SelectContent>
      </Select>}
  </div>
}

// The mode chips under the composer (H13). Each sets what the research produces (its intent); "Ask my PDFs" is the
// attached-only scope with a drafted report. The chosen chip is the person's explicit choice, stored with the research.
type ModeChip = 'report' | 'papers' | 'table' | 'compare' | 'ask'
const modeChips: { id: ModeChip; label: string; icon: LucideIcon }[] = [
  { id: 'report', label: 'Draft report', icon: FileText },
  { id: 'papers', label: 'Find papers', icon: Search },
  { id: 'table', label: 'Evidence table', icon: Table2 },
  { id: 'compare', label: 'Compare methods', icon: Network },
  { id: 'ask', label: 'Ask my PDFs', icon: Paperclip },
]

// Why a table/compare discovery of the current question wrote no table (the view's current outcome only).
const outcomeText: Record<IntentOutcome['reason'], string> = {
  no_included_source: 'No study table: no source was included',
  scope_revised: 'No study table: the question was revised',
  run_active: 'No study table: another run was active',
}

// What changes on a research when its background work moves on; the shell's list is polled, and Home reads the
// research view and the suggestions again only when one of these changes.
const progressKey = (r: ResearchSummary) => `${r.id}:${r.updated_at}:${r.last_run_status ?? ''}:${r.answer_count}`

// The Resume card (H14): the most recently updated research, its latest report version and what waits for the person.
function ResumeCard({ research }: { research: ResearchSummary }) {
  // The facts carry the id they were read for, so another research's facts never show under this title.
  const [read, setRead] = useState<{ id: string; version: number | null; outcome: IntentOutcome | null } | null>(null)
  const facts = read?.id === research.id ? read : null
  const key = progressKey(research)
  useEffect(() => {
    let current = true
    api.research(research.id).then(view => {
      const latest = view.answers.filter(a => a.status === 'structurally_valid').sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
      if (current) setRead({ id: research.id, version: latest?.report_version != null ? shownVersion(latest) : null, outcome: view.intent_outcome })
    }, () => { if (current) setRead(null) })
    return () => { current = false }
  }, [research.id, key])
  const waiting = research.awaiting.queue + research.awaiting.pdf
  const parts = [
    facts?.version ? t('Report V{n}', { n: facts.version }) : null,
    facts?.outcome ? t(outcomeText[facts.outcome.reason]) : null,
    waiting ? t('{n} waiting for you', { n: waiting }) : null,
  ].filter(Boolean)
  // Queue rows and works waiting for the person's PDF are different things; the sum is shown, the split is told.
  const split = t('{queue} in the queue · {pdf} waiting for your PDF', { queue: research.awaiting.queue, pdf: research.awaiting.pdf })
  return <button type="button" className="card" onClick={() => { window.location.hash = `/research/${research.id}` }}>
    <span className="home-card-tag"><RotateCw aria-hidden />{t('Resume')}</span>
    <p>{research.title}</p>
    {parts.length > 0 && <small title={waiting ? split : undefined}><i className="home-card-dot" aria-hidden />{parts.join(' · ')}{waiting > 0 && <span className="sr-only"> ({split})</span>}</small>}
  </button>
}

// The first-run setup card (H2): shown while no model connection is ready, so nothing can start yet. Each row states
// what the connections list and the proxy setting hold now; none of it is a live test.
function SetupCard({ connections, reasons, proxy }: { connections: Connections; reasons: string; proxy: string | null | undefined }) {
  const keyless = connections.providers.filter(p => p.id === 'openalex' || p.id === 'crossref')
  const sourcesReady = keyless.length === 2 && keyless.every(p => p.implemented && p.access_mode !== null && p.access_mode !== 'not_configured')
  const settings = () => { window.location.hash = '/settings/connections' }
  const num = (n: number, ok: boolean) => <span className={`num ${ok ? 'ok' : ''}`} aria-hidden>{ok ? <Check /> : n}</span>
  return <section className="home-setup" aria-labelledby="home-setup-title">
    <h2 id="home-setup-title"><span>{t('Set up DEIXIS')}</span><small>{t('Three things before the first question. Nothing leaves this computer except the searches and the model calls you set up.')}</small></h2>
    <div className="home-setup-row">{num(1, false)}<p>{t('Answer and literature models')}<small>{t('Not connected. Use Codex CLI, Claude Code, or an API key.')}</small>{reasons && <small className="home-setup-reason">{reasons}</small>}</p>
      <button type="button" className="setup-connect" onClick={settings}>{t('Connect')}</button></div>
    <div className="home-setup-row">{num(2, sourcesReady)}<p>{t('Scholarly sources')}<small>{t('OpenAlex and Crossref work without a key. Configured · not tested live.')}</small></p>
      {sourcesReady ? <span className="st ok">{t('Ready')}</span> : <button type="button" className="setup-add" onClick={() => { window.location.hash = '/settings/sources' }}>{t('Connect')}</button>}</div>
    <div className="home-setup-row">{num(3, Boolean(proxy))}<p>{t('Institution proxy (optional)')}<small>{t('Lets you open PDFs your library pays for, through its sign-in.')}</small></p>
      {proxy ? <span className="st no">{t('Address saved')}</span> : <button type="button" className="setup-add" onClick={() => { window.location.hash = '/settings/access' }}>{t('Add')}</button>}</div>
  </section>
}

// The question box's placeholder types itself out letter by letter, then erases and types the next line: the default
// line first, then questions suggested from earlier answers. Static (the first line) when motion is reduced or the box
// has text.
function useTypewriter(lines: string[], active: boolean): string {
  const key = lines.join('\n')
  const [text, setText] = useState('')
  useEffect(() => {
    const all = key.split('\n')
    if (!active || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setText(all[0]); return }
    let line = 0, shown = 0, erasing = false
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      const full = all[line]
      if (!erasing) {
        shown += 1
        setText(full.slice(0, shown))
        if (shown >= full.length) { if (all.length === 1) return; erasing = true; timer = setTimeout(tick, 2600); return }
        timer = setTimeout(tick, 28 + Math.random() * 40)
      } else {
        shown -= 2
        setText(full.slice(0, Math.max(shown, 0)))
        if (shown <= 0) { erasing = false; shown = 0; line = (line + 1) % all.length; timer = setTimeout(tick, 400); return }
        timer = setTimeout(tick, 14)
      }
    }
    setText('')
    timer = setTimeout(tick, 300)
    return () => clearTimeout(timer)
  }, [key, active])
  return text
}

// `researches` is the shell's list (refreshed by its poll), newest first: the Resume card and the suggestions follow it.
export function Home({ onCreated, researches }: { onCreated: (id: string) => void; researches: ResearchSummary[] }) {
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<SourceScope>('academic')
  const [intent, setIntent] = useState<ResearchIntent>('report')
  // Home's real data: the latest research (Resume), stored unanswered aspects (Suggested) and the proxy setting.
  const latest = researches[0] ?? null
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [proxy, setProxy] = useState<string | null | undefined>(undefined)
  useEffect(() => { api.institutionProxy().then(result => setProxy(result.address), () => setProxy(null)) }, [])
  const listKey = researches.map(progressKey).join('|')
  useEffect(() => {
    let current = true
    homeApi.suggestions().then(result => { if (current) setSuggestions(result.suggestions) }, () => { if (current) setSuggestions([]) })
    return () => { current = false }
  }, [listKey])
  const placeholder = useTypewriter([t('Ask a research question. DEIXIS searches, screens, reads and links every claim to a passage.'), ...suggestions.slice(0, 5).map(s => s.text)], question === '')
  const [effort, setEffort] = useState<Effort>('standard')
  // The depth chosen in Settings → General; a pick made here before it arrives is kept.
  const effortPicked = useRef(false)
  useEffect(() => { preferencesApi.get().then(p => { if (!effortPicked.current) setEffort(p.default_effort) }, () => {}) }, [])
  const [limits, setLimits] = useState<EffortLimits | null>(null)
  useEffect(() => { api.effortLimits().then(setLimits, () => setLimits(null)) }, [])
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState('')
  const [reasoning, setReasoning] = useState<string | null>(null)
  const [literature, setLiterature] = useState('')
  const [literatureReasoning, setLiteratureReasoning] = useState<string | null>(null)
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  // The attached PDFs and the ones the person unchecked as search guides, kept in one state so every change to the
  // files and their check marks is one atomic update (two quick adds cannot drop a file or a mark).
  const [attached, setAttached] = useState<{ files: File[]; unguided: Set<string> }>({ files: [], unguided: new Set() })
  const files = attached.files
  // Attached PDFs the person unchecked in the guide rows: they are still read as sources but do not guide the search.
  const unguided = attached.unguided
  // A Zotero collection chosen before the research exists; it is imported right after the research is created.
  const [zotero, setZotero] = useState<ZoteroChoice | null>(null)
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const questionInput = useRef<HTMLTextAreaElement>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const toast = useToast()

  useEffect(() => {
    Promise.all([api.connections(), api.settings().catch(() => null)]).then(([result, saved]) => {
      setConnections(result)
      setDefaults(saved)
      const models = connectionModels(result)
      // Only a ready connection can run a step: a signed-out Codex still lists its models, so it must not be the start.
      const ready = models.filter(m => canRun(result.models[m.connection]))
      // Claude Code lists a "default" alias first; the composer names a real model, so the alias is skipped when another is listed.
      const named = ready.filter(m => m.model !== 'default')
      const preferred = named.find(m => m.is_default) ?? named[0] ?? ready[0]
      // A model that lists efforts without declaring a default (Claude Code) starts at medium, so the menu can name the effort.
      const fallbackEffort = (id: string) => defaultEffort(models, id)
        ?? (exposesEffortControl(models.find(m => m.id === id)) && listedEffort(models, id, 'medium') ? 'medium' : null)
      // A default from Settings applies while its connection is ready and still lists it; otherwise the composer starts from the first ready connection's default model.
      const start = (setting: RoleModelSetting | undefined) => {
        const saved = setting?.model ? modelKey(setting.model_connection, setting.model) : null
        const id = saved && ready.some(m => m.id === saved) ? saved : preferred?.id
        if (!id) return null
        return { id, effort: (id === saved ? listedEffort(models, id, setting?.reasoning_effort ?? null) : null) ?? fallbackEffort(id) }
      }
      const answer = start(saved?.answer)
      const literature = start(saved?.literature)
      if (answer) { setModel(answer.id); setReasoning(answer.effort) }
      if (literature) { setLiterature(literature.id); setLiteratureReasoning(literature.effort) }
    }).catch((e: Error) => setError(t('Could not read connections: {message}', { message: e.message })))
  }, [])

  const models = connections ? connectionModels(connections) : []
  const chosen = models.find(m => m.id === model)
  const efforts = chosen?.reasoning_efforts ?? []
  const needsFiles = scope === 'attached'
  const needsSource = scope !== 'academic'
  // A mixed search guides itself with its checked PDFs (Q3, D3). The check marks hold whether or not the rows are
  // shown: rows appear with two or more PDFs, and also for a single PDF the person unchecked, so it stays re-checkable.
  // A mixed search whose PDFs are all unchecked (and no Zotero collection) cannot start: nothing would guide it, and
  // turning it into an attached-only research would change the scope the person chose.
  const mixed = scope === 'attached_and_academic'
  const guidedFiles = files.filter(f => !unguided.has(f.name))
  const guideRows = mixed && (files.length > 1 || guidedFiles.length < files.length)
  const noGuide = mixed && files.length > 0 && !guidedFiles.length && !zotero
  // More checked PDFs than one search takes: the backend keeps five by D3's rule and lists the rest as not selected.
  const overLimit = guideRows && guidedFiles.length > MAX_SEED_PDFS
  const activeChip: ModeChip = scope === 'attached' && intent === 'report' ? 'ask' : intent

  // What guides the search: every eligible PDF, less the uploads the person unchecked. The backend picks five among
  // the rest by D3's rule and records the others as not selected; the unchecked uploads stay attached sources.
  function seedSelection(uploaded: Map<string, string>): SeedSelection {
    const excluded = files.filter(f => unguided.has(f.name)).map(f => uploaded.get(f.name)).filter((v): v is string => Boolean(v))
    return excluded.length ? { all_eligible: true, excluded_source_version_ids: excluded } : { all_eligible: true }
  }

  function chooseChip(chip: ModeChip) {
    if (chip === 'ask') { setScope('attached'); setIntent('report') }
    else {
      setIntent(chip)
      // Draft report searches again: leaving "Ask my PDFs" goes back to a scope with a search.
      if (chip === 'report' && scope === 'attached') setScope(files.length || zotero ? 'attached_and_academic' : 'academic')
    }
    questionInput.current?.focus()
  }
  function chooseScope(next: SourceScope) {
    setScope(next)
    if (next === 'attached' && intent === 'papers') setIntent('report')  // finding papers needs a search
  }
  const chipDisabled = (chip: ModeChip) => chip === 'papers' && scope === 'attached' ? t('Needs academic search')
    : chip === 'ask' && !files.length && !zotero ? t('Add a PDF first') : null


  async function addFiles(list: FileList | null) {
    if (!list) return
    const accepted: File[] = []
    const rejected: string[] = []
    for (const file of Array.from(list)) {
      const header = await file.slice(0, 5).text()
      if (header === '%PDF-') accepted.push(file); else rejected.push(file.name)
    }
    setAttached(old => {
      const next = [...new Map([...old.files, ...accepted].map(f => [f.name, f])).values()]
      // A new PDF starts checked. `unguided` holds only the person's own unchecks; the limit of five is the backend's
      // choice among the checked ones (D3), never an uncheck made here.
      return { files: next, unguided: new Set([...old.unguided].filter(name => next.some(f => f.name === name))) }
    })
    if (accepted.length && scope === 'academic') setScope('attached_and_academic')  // attachments must be part of the scope
    setError(rejected.length ? t('{files}: only PDF files can be attached.', { files: rejected.join(', ') }) : '')
  }

  async function submit() {
    if (!question.trim() || busy) return
    if (needsFiles && !files.length && !zotero) { setError(t('Attach at least one PDF to use “Attached files”.')); return }
    if (scope === 'attached_and_academic' && !files.length && !zotero) { setError(t('Add a PDF or Zotero collection to guide the search.')); return }
    if (noGuide) { setError(t('Choose at least one PDF to guide the search.')); return }
    const literatureChoice = models.find(m => m.id === literature)
    if (!chosen || !literatureChoice) { setError(t('Choose the answer and literature models first. DEIXIS does not pick them for you.')); return }
    setBusy(true)
    setError('')
    let id: string | null = null
    let step = ''
    try {
      const view = await api.create({ question: question.trim(), source_scope: scope, intent,
        seed_mode: scope === 'attached_and_academic' ? 'uploaded_seed' : 'question_only', effort, model_connection: chosen.connection, requested_model: chosen.model,
        reasoning_effort: efforts.some(e => e.id === reasoning) ? reasoning : null,
        literature_connection: literatureChoice.connection, literature_model: literatureChoice.model,
        literature_reasoning_effort: listedEffort(models, literature, literatureReasoning),
        review_mode: 'default', review_connection: null, review_model: null, review_reasoning_effort: null })
      id = view.research.id
      let latestView = view
      const uploaded = new Map<string, string>()
      step = 'Research saved, but DEIXIS could not attach the PDFs: {message}. You can retry from the research page.'
      for (const file of files) {
        const added = await api.upload(id, file)
        uploaded.set(file.name, added.uploaded_source_version_id)
        if (added.file_restore) toast(fileRestoreTone(added.file_restore), [t('PDF added and included. Its text was extracted page by page (no OCR).'), fileRestoreNote(added.file_restore)].filter(Boolean).join(' '))
        latestView = added
      }
      step = 'Research saved, but DEIXIS could not import the Zotero collection: {message}. You can retry from the research page.'
      if (zotero) {
        const imported = await api.zoteroImport(id, zotero.source, zotero.key)
        latestView = imported
        const { notes } = imported.zotero_import
        if (notes.length) toast('warning', notes.map(n => `${n.title}: ${t(n.note, n.vars)}.`).join(' '))
      }
      if (scope === 'attached_and_academic') {
        step = 'Research saved, but the PDFs could not guide the search: {message}. Choose a readable PDF on the research page.'
        try {
          latestView = await api.setSeeds(id, seedSelection(uploaded), latestView.research.version)
        } catch (e) {
          // 409 is a real conflict: another choice was stored meanwhile. Do not search on a guess; let the person check it.
          if (e instanceof ApiError && e.status === 409) { toast('warning', t('The PDF choice changed elsewhere; check it on the research page.')); onCreated(id); return }
          throw e
        }
        const left = latestView.scope.seed_not_selected.length
        if (left) toast('warning', t('{n} PDFs guide the search; {m} were left out (limit 5).', { n: latestView.scope.seeds.length, m: left }))
      }
      step = 'Research saved, but DEIXIS could not start the search: {message}. You can retry from the research page.'
      if (scope === 'academic' || (scope === 'attached_and_academic' && latestView.scope.seed_status === 'ready'))
        await api.startRun(id, 'discovery', crypto.randomUUID())
      // "Ask my PDFs": no search to wait for, so the source-linked answer over the attached files starts at once.
      if (scope === 'attached' && intent === 'report') {
        step = 'Research saved, but DEIXIS could not start the answer: {message}. You can start it from the research page.'
        await api.startRun(id, 'answer', crypto.randomUUID())
      }
      onCreated(id)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      // The research already exists once created: open it rather than leave the user on a form that looks unsaved.
      if (id) { toast('warning', t(step, { message })); onCreated(id) }
      else setError(message)
    } finally {
      setBusy(false)
    }
  }

  const modelName = (id: string) => models.find(m => m.id === id)?.display_name ?? id.slice(id.indexOf(':') + 1)
  const defaultName = defaults?.reviewer.model ? modelName(modelKey(defaults.reviewer.model_connection, defaults.reviewer.model)) : null
  // Bytes as the file manager shows them, so a large attachment is recognisable before it is uploaded.
  const fileSize = (bytes: number) => bytes >= 1_000_000 ? t('{n} MB', { n: (bytes / 1_000_000).toFixed(1) }) : t('{n} KB', { n: Math.max(1, Math.round(bytes / 1000)) })
  // A mixed search is guided by up to five of the attached PDFs (D3); with several files the checked ones' chips say so.
  const hasChips = files.length > 0 || Boolean(zotero)
  const chips = <div className="attachments" aria-label={hasChips ? t('PDFs to attach') : undefined}>
    {zotero && <div className="attachment-chip">
      <span className="attachment-chip-main"><span className="attachment-icon" aria-hidden><ConnectionIcon id="zotero" /></span><span className="attachment-name" title={zotero.name}>{zotero.name}</span><small>Zotero</small></span>
      <button type="button" className="attachment-remove" aria-label={t('Remove {name}', { name: zotero.name })} onClick={() => setZotero(null)}><X size={13} /></button>
    </div>}
    {files.map(file =>
      <div key={file.name} className="attachment-chip">
        <span className="attachment-chip-main">
          <span className="attachment-icon" aria-hidden><FileText size={13} /></span>
          <span className="attachment-name" title={file.name}>{file.name}</span><small>{guideRows && !unguided.has(file.name) ? t(overLimit ? 'may guide the search' : 'guides the search') : fileSize(file.size)}</small>
        </span>
        <button type="button" className="attachment-remove" aria-label={t('Remove {name}', { name: file.name })} onClick={() => setAttached(old => ({ files: old.files.filter(f => f.name !== file.name), unguided: new Set([...old.unguided].filter(name => name !== file.name)) }))}><X size={13} /></button>
      </div>)}
  </div>

  // The Models menu shows, read-only, the models from Settings: one row per role, "model · effort" under its name
  // (mockup order: literature, answer, reviewer). A row opens Settings → Models, where the defaults are changed.
  const withEffort = (name: string, effort: string | null) => effort ? `${name} · ${reasoningLabel(effort)}` : name
  // A Settings default whose connection is not ready is not used; the row says so instead of switching models silently.
  const notReady = (role: ModelRole) => {
    const saved = defaults?.[role]
    if (!saved?.model || canRun(connections?.models[saved.model_connection])) return null
    return t('{model} from Settings is not used: {connection} is not connected.', { model: modelName(modelKey(saved.model_connection, saved.model)), connection: connectionName(saved.model_connection) })
  }
  const roleRows: { role: ModelRole; summary: string; note: string | null }[] = [
    { role: 'literature', summary: withEffort(modelName(literature), listedEffort(models, literature, literatureReasoning)), note: notReady('literature') },
    { role: 'answer', summary: withEffort(modelName(model), efforts.some(e => e.id === reasoning) ? reasoning : null), note: notReady('answer') },
    { role: 'reviewer', summary: defaultName ? withEffort(defaultName, listedEffort(models, modelKey(defaults!.reviewer.model_connection, defaults!.reviewer.model!), defaults!.reviewer.reasoning_effort ?? null)) : t('no reviewer'), note: notReady('reviewer') },
  ]
  const noModel = Boolean(connections) && !models.length
  const openModelSettings = () => { window.location.hash = '#/settings/models' }

  // Home is one centred column: the band with the scope, the question, then one control row (+, files, Models, depth, send).
  return <section className="welcome home">
    <h1 className="sr-only" tabIndex={-1}>{uiLanguage() === 'tr' ? <><em>Sorunuz</em> sizi nereye götürüyor?</> : <>Where does your <em>question</em>{' '}lead?</>}</h1>
    <p className="intro sr-only">{t('Ask a question. DEIXIS finds publications, lets you choose the sources, and links each claim to a passage you can open.')}</p>
    {noModel && connections && <SetupCard connections={connections} reasons={notReadyReasons(connections)} proxy={proxy} />}
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit() }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void addFiles(e.dataTransfer.files) }}>
      <div className="composer-band">
        <Select value={scope} onValueChange={value => { if (value) chooseScope(value as SourceScope) }}>
          <SelectTrigger className="composer-scope" aria-label={t('Source scope')} title={t('Where DEIXIS looks for sources')}><SelectValue>{(value: string) => { const Icon = scopeOptions[value as SourceScope].icon; return <><Icon size={15} aria-hidden />{t(scopeLabels[value as SourceScope])}</> }}</SelectValue></SelectTrigger>
          <SelectContent className="home-menu" align="start" sideOffset={6} alignItemWithTrigger={false} collisionPadding={8} collisionAvoidance={{ align: 'shift', fallbackAxisSide: 'none' }}>
            <div className="home-menu-heading" aria-hidden="true">{t('Workflows')}</div>
            {(Object.keys(scopeLabels) as SourceScope[]).map(s => <SelectItem key={s} value={s} className="home-menu-item"><MenuRow icon={scopeOptions[s].icon} title={t(scopeLabels[s])} detail={t(scopeOptions[s].detail)} /></SelectItem>)}
            <SelectItem value="__systematic_review" className="home-menu-item" disabled><MenuRow icon={Table2} title={t('Systematic review')} detail={t('Protocol, two reviewers, PRISMA flow')} later /></SelectItem>
          </SelectContent>
        </Select>
      </div>
      <label className="composer-label sr-only" htmlFor="research-question">{t('What would you like to investigate?')}</label>
      <Textarea ref={questionInput} id="research-question" aria-label={t('Research question')} placeholder={placeholder} value={question}
        onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit() } }} />
      {scope === 'attached_and_academic' && files.length === 0 && zotero &&
        <p className="composer-hint">{t('The imported PDFs guide the search.')}</p>}
      <div className="composer-controls">
        <DropdownMenu>
          <DropdownMenuTrigger ref={addButton} type="button" className="composer-add" aria-label={t('Add sources')} title={t('Add sources (optional)')}><Plus size={16} /></DropdownMenuTrigger>
          <DropdownMenuContent className="home-menu" align="start" sideOffset={6}>
            <DropdownMenuItem className="home-menu-item" onClick={() => fileInput.current?.click()}><MenuRow icon={FileUp} title={t('Upload PDF')} detail={t('From this computer, up to 50 MB each. You can also drop files here.')} /></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" onClick={() => setZoteroOpen(true)}><MenuRow icon={LibraryBig} title={t('Zotero collection')} detail={t('Read-only, from Zotero on this computer or zotero.org. Imported when the research starts.')} /></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" disabled><MenuRow icon={FileText} title={t('Import BibTeX or RIS')} later /></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" disabled><MenuRow icon={Link2} title={t('Add by DOI')} later /></DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {chips}
        {models.length > 0
          ? <DropdownMenu>
              <DropdownMenuTrigger type="button" className="models-summary" title={t('Models for this research: answer, literature and reviewer')}>
                <Cpu size={15} aria-hidden /><span className="models-summary-label">{t('Models')}<span className="sr-only">: </span></span>
                {roleRows.map(row => <span className="sr-only" key={row.role}>{t(modelRoles[row.role].label)} {row.summary}. {row.note} </span>)}
              </DropdownMenuTrigger>
              <DropdownMenuContent className="home-menu" align="start" sideOffset={6} collisionAvoidance={{ align: 'shift', fallbackAxisSide: 'none' }}>
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="home-menu-heading">{t('Models')}</DropdownMenuLabel>
                  {roleRows.map(row => <DropdownMenuItem key={row.role} className="home-menu-item" onClick={openModelSettings}><MenuRow icon={Cpu} title={t(modelRoles[row.role].label)} detail={row.note ? <>{row.summary}<span className="home-menu-warn">{row.note}</span></> : row.summary} /></DropdownMenuItem>)}
                  <DropdownMenuItem className="home-menu-item" onClick={openModelSettings}><MenuRow icon={SlidersHorizontal} title={t('Change the defaults in Settings')} /></DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          : <button type="button" className="models-summary" disabled title={connections ? notReadyReasons(connections) : ''}><Cpu size={15} aria-hidden /><span className="models-summary-label">{t('Models')}</span><span className="sr-only">: {t(connections ? 'no connection ready' : 'checking…')}</span></button>}
        <Select value={effort} onValueChange={value => { if (value) { effortPicked.current = true; setEffort(value as Effort) } }}>
          <SelectTrigger className="composer-depth" aria-label={t('Research depth')} title={t('How much searching and reading a run may do')}><SelectValue>{(value: string) => { const Icon = effortOptions[value as Effort].icon; return <><Icon size={15} aria-hidden />{t(effortLabels[value as Effort])}</> }}</SelectValue></SelectTrigger>
          <SelectContent className="home-menu" align="start" sideOffset={6} alignItemWithTrigger={false} collisionPadding={8} collisionAvoidance={{ align: 'shift', fallbackAxisSide: 'none' }}>
            <div className="home-menu-heading" aria-hidden="true">{t('Depth')}</div>
            {(Object.keys(effortLabels) as Effort[]).map(d => <SelectItem key={d} value={d} className="home-menu-item"><MenuRow icon={effortOptions[d].icon} title={t(effortLabels[d])} detail={effortDetail(d, limits, LOCAL_CONNECTIONS.has(models.find(m => m.id === model)?.connection ?? ''))} /></SelectItem>)}
          </SelectContent>
        </Select>
        <Button className="send-button" type="submit" size="icon" disabled={!question.trim() || busy || !model || !literature || (needsSource && !files.length && !zotero) || noGuide} aria-label={t('Start research')} title={noModel ? t('Connect a model to start') : undefined}><ArrowUp size={17} /></Button>
      </div>
      {guideRows && <div className="guide" role="group" aria-labelledby="guide-lead">
        <span id="guide-lead">{t('PDFs guiding the search · their titles, abstracts and references shape the query.')}</span>
        {files.map(file => {
          const checked = !unguided.has(file.name)
          return <label key={file.name} title={file.name}>
            <input type="checkbox" checked={checked}
              onChange={() => setAttached(old => { const next = new Set(old.unguided); if (checked) next.add(file.name); else next.delete(file.name); return { ...old, unguided: next } })} />
            <span>{file.name}</span>
          </label>
        })}
        {overLimit && <span className="guide-limit">{t('Up to five guide the search; DEIXIS keeps the five whose first pages share the most words with your question.')}</span>}
        {noGuide && <span className="guide-none" role="status">{t('Choose at least one PDF to guide the search.')}</span>}
      </div>}
    </form>
    <ZoteroDialog open={zoteroOpen} onOpenChange={setZoteroOpen} destination="home" busy={busy} initial={zotero} returnFocus={addButton}
      onImport={choice => { setZotero(choice); setZoteroOpen(false); if (scope === 'academic') setScope('attached_and_academic') }} />
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void addFiles(e.target.files); e.target.value = '' }} />
    {noModel && <p className="hint home-connect-hint">{t('Connect a model to start')}</p>}
    {error && <Notice tone="error">{error}</Notice>}
    <div className="mode-chips" role="group" aria-label={t('What the research produces')}>
      {modeChips.map(({ id, label, icon: Icon }) => {
        const reason = chipDisabled(id)
        return <button key={id} type="button" className={`chip ${activeChip === id ? 'on' : ''}`} aria-pressed={activeChip === id}
          aria-disabled={reason ? true : undefined} aria-describedby={reason ? `chip-reason-${id}` : undefined} title={reason ?? undefined}
          onClick={() => { if (!reason) chooseChip(id) }}>
          <Icon aria-hidden />{t(label)}
        </button>
      })}
      {modeChips.map(({ id }) => { const reason = chipDisabled(id); return reason && <span key={id} id={`chip-reason-${id}`} className="sr-only">{reason}</span> })}
    </div>
    {(latest || suggestions.length > 0) && <div className="home-cards">
      {latest && <ResumeCard key={latest.id} research={latest} />}
      {suggestions.slice(0, 2).map(s => <button key={`${s.answer_id}:${s.text}`} type="button" className="card" onClick={() => { setQuestion(s.text); questionInput.current?.focus() }}>
        <span className="home-card-tag"><Lightbulb aria-hidden />{t('Suggested')}</span>
        <p>{s.text}</p>
        <small className="home-card-source">{s.research_title}</small>
      </button>)}
    </div>}
    <SemanticSetupNote />
    <p className="hint home-hint">{busy ? t('Saving research…') : t('⌘ / Ctrl + Enter starts the research · ? shows shortcuts · Nothing is downloaded from paywalled sites')}</p>
  </section>
}
