import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Popover } from '@base-ui/react/popover'
import { ArrowUp, BookMarked, Brain, Check, ChevronDown, Cpu, FileText, FileUp, Gauge, Link2, Paperclip, PenLine, Plus, ScanSearch, Search, ShieldCheck, SlidersHorizontal, Table2, Telescope, X, Zap, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from './Toast'
import { api, ApiError, type Connections, type Effort, type EffortLimits, type ModelOption, type ModelRole, type RoleModelSetting, type SourceScope } from './api'
import { connectionName, fileRestoreNote, fileRestoreTone, isPlannedModel, reasoningLabel, scopeLabels } from './labels'
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
  attached: { icon: Paperclip, detail: 'Only the PDFs you add; no search runs' },
  attached_and_academic: { icon: FileText, detail: 'Searches using your PDFs and your question. Only included sources are used in the answer.' },
}
export const effortOptions: Record<Effort, { icon: LucideIcon }> = {
  quick: { icon: Zap },
  standard: { icon: Gauge },
  detailed: { icon: Telescope },
}

// The depth text, from the fast path's modes (`fast_path.MODES`): the same numbers the run is given, so a changed mode
// cannot leave this text behind. Without an answer from the server the depth carries no text at all.
function effortDetail(effort: Effort, limits: EffortLimits | null | undefined): string | undefined {
  const e = limits?.efforts?.[effort]
  if (!e) return undefined
  const number = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
  return t('About {minutes} min · up to {papers} papers', { minutes: number(e.minutes), papers: number(e.papers) })
}

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
// Why implemented connections offer no model.
export const notReadyReasons = (connections: Connections) =>
  Object.values(connections.models).filter(h => !h.ready && !isPlannedModel(h.reason)).map(h => `${connectionName(h.connection)}: ${h.reason ?? ''}`).join('; ')

// The most PDFs that guide one search (D3); the backend enforces it.
export const MAX_SEED_PDFS = 5
const DEFAULT_REVIEWER = '__default'
const NO_REVIEW = '__off'

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
        <SelectTrigger aria-label={t('{role} reasoning effort', { role })} title={t('How long the {role} model thinks', { role: role.toLocaleLowerCase(uiLocale()) })}><SelectValue>{(v: string) => <><Brain size={15} />{reasoningLabel(v)}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content has-details" align="start" alignItemWithTrigger={false}>
          <div className="intake-select-heading" aria-hidden="true">{t('{role} reasoning effort', { role })}</div>
          <p className="intake-select-description" aria-hidden="true">{t('How long the {role} model reasons before it replies. Higher settings take longer.', { role: role.toLocaleLowerCase(uiLocale()) })}</p>
          <SelectItem value="__provider_default"><Option icon={Brain} title={t('Provider default')} detail={t('Let the current model choose its default effort')} /></SelectItem>
          {efforts.map(e => <SelectItem key={e.id} value={e.id}><Option icon={Brain} title={reasoningLabel(e.id)} detail={[e.description, e.id === chosen?.default_reasoning_effort ? t('Model default') : ''].filter(Boolean).join(' · ') || undefined} /></SelectItem>)}
        </SelectContent>
      </Select>}
  </div>
}

export function Home({ onCreated }: { onCreated: (id: string) => void }) {
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<SourceScope>('academic')
  const [effort, setEffort] = useState<Effort>('standard')
  const [limits, setLimits] = useState<EffortLimits | null>(null)
  useEffect(() => { api.effortLimits().then(setLimits, () => setLimits(null)) }, [])
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState('')
  const [reasoning, setReasoning] = useState<string | null>(null)
  const [literature, setLiterature] = useState('')
  const [literatureReasoning, setLiteratureReasoning] = useState<string | null>(null)
  const [reviewer, setReviewer] = useState(DEFAULT_REVIEWER)
  const [reviewerReasoning, setReviewerReasoning] = useState<string | null>(null)
  const [defaults, setDefaults] = useState<Record<ModelRole, RoleModelSetting> | null>(null)
  // The role whose picker is open under the controls (chosen in the Models menu).
  const [pickerRole, setPickerRole] = useState<ModelRole | null>(null)
  // Each choice in the menu remounts the picker, so choosing the same role again opens its list again.
  const [pickerNonce, setPickerNonce] = useState(0)
  const [files, setFiles] = useState<File[]>([])
  // A Zotero collection chosen before the research exists; it is imported right after the research is created.
  const [zotero, setZotero] = useState<ZoteroChoice | null>(null)
  const [zoteroOpen, setZoteroOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const toast = useToast()

  useEffect(() => {
    Promise.all([api.connections(), api.settings().catch(() => null)]).then(([result, saved]) => {
      setConnections(result)
      setDefaults(saved)
      const models = connectionModels(result)
      const preferred = models.find(m => m.is_default) ?? models[0]
      // A default from Settings applies while its connection still lists it; otherwise the composer starts from Codex's default model.
      const start = (setting: RoleModelSetting | undefined) => {
        const saved = setting?.model ? modelKey(setting.model_connection, setting.model) : null
        const id = saved && models.some(m => m.id === saved) ? saved : preferred?.id
        if (!id) return null
        return { id, effort: (id === saved ? listedEffort(models, id, setting?.reasoning_effort ?? null) : null) ?? defaultEffort(models, id) }
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

  function chooseModel(id: string, list = models) {
    const next = list.find(m => m.id === id)
    setModel(id)
    // Each model lists its own efforts; use the provider-declared default when one exists.
    setReasoning(next?.default_reasoning_effort ?? null)
  }

  async function addFiles(list: FileList | null) {
    if (!list) return
    const accepted: File[] = []
    const rejected: string[] = []
    for (const file of Array.from(list)) {
      const header = await file.slice(0, 5).text()
      if (header === '%PDF-') accepted.push(file); else rejected.push(file.name)
    }
    setFiles(old => [...new Map([...old, ...accepted].map(f => [f.name, f])).values()])
    if (accepted.length && scope === 'academic') setScope('attached_and_academic')  // attachments must be part of the scope
    setError(rejected.length ? t('{files}: only PDF files can be attached.', { files: rejected.join(', ') }) : '')
  }

  async function submit() {
    if (!question.trim() || busy) return
    if (needsFiles && !files.length && !zotero) { setError(t('Attach at least one PDF to use “Attached files”.')); return }
    if (scope === 'attached_and_academic' && !files.length && !zotero) { setError(t('Add a PDF or Zotero collection to guide the search.')); return }
    const literatureChoice = models.find(m => m.id === literature)
    if (!chosen || !literatureChoice) { setError(t('Choose the answer and literature models first. DEIXIS does not pick them for you.')); return }
    setBusy(true)
    setError('')
    let id: string | null = null
    let step = ''
    const customReviewer = reviewer !== DEFAULT_REVIEWER && reviewer !== NO_REVIEW
    const reviewerChoice = customReviewer ? models.find(m => m.id === reviewer) : undefined
    try {
      const view = await api.create({ question: question.trim(), source_scope: scope,
        seed_mode: scope === 'attached_and_academic' ? 'uploaded_seed' : 'question_only', effort, model_connection: chosen.connection, requested_model: chosen.model,
        reasoning_effort: efforts.some(e => e.id === reasoning) ? reasoning : null,
        literature_connection: literatureChoice.connection, literature_model: literatureChoice.model,
        literature_reasoning_effort: listedEffort(models, literature, literatureReasoning),
        review_mode: customReviewer ? 'custom' : reviewer === NO_REVIEW ? 'off' : 'default',
        review_connection: reviewerChoice?.connection ?? null, review_model: reviewerChoice?.model ?? null,
        review_reasoning_effort: customReviewer ? listedEffort(models, reviewer, reviewerReasoning) : null })
      id = view.research.id
      let latestView = view
      step = 'Research saved, but DEIXIS could not attach the PDFs: {message}. You can retry from the research page.'
      for (const file of files) {
        const added = await api.upload(id, file)
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
          latestView = await api.setSeeds(id, { all_eligible: true }, latestView.research.version)
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
  const reviewerChoices = [
    { value: DEFAULT_REVIEWER, title: defaultName ? t('Default · {name}', { name: defaultName }) : t('Default · none set'),
      detail: t(defaultName ? 'The reviewer set in Settings for all researches' : 'No reviewer is set in Settings, so answers are not reviewed') },
    { value: NO_REVIEW, title: t('Off'), detail: t('Answers of this research are not reviewed') },
  ]
  const reviewerSummary = reviewer === NO_REVIEW ? t('Off') : reviewer === DEFAULT_REVIEWER ? defaultName ?? t('no reviewer') : modelName(reviewer)
  // Bytes as the file manager shows them, so a large attachment is recognisable before it is uploaded.
  const fileSize = (bytes: number) => bytes >= 1_000_000 ? t('{n} MB', { n: (bytes / 1_000_000).toFixed(1) }) : t('{n} KB', { n: Math.max(1, Math.round(bytes / 1000)) })
  // A mixed search is guided by up to five of the attached PDFs (D3); with several files the chips say so.
  const guiding = scope === 'attached_and_academic' && files.length > 1
  const hasChips = files.length > 0 || Boolean(zotero)
  const chips = <div className="attachments" aria-label={hasChips ? t('PDFs to attach') : undefined}>
    {zotero && <div className="attachment-chip">
      <span className="attachment-chip-main"><span className="attachment-icon" aria-hidden><ConnectionIcon id="zotero" /></span><span className="attachment-name" title={zotero.name}>{zotero.name}</span><small>Zotero</small></span>
      <button type="button" className="attachment-remove" aria-label={t('Remove {name}', { name: zotero.name })} onClick={() => setZotero(null)}><X size={13} /></button>
    </div>}
    {files.map((file, index) =>
      <div key={file.name} className="attachment-chip">
        <span className="attachment-chip-main">
          <span className="attachment-icon" aria-hidden><FileText size={13} /></span>
          <span className="attachment-name" title={file.name}>{file.name}</span><small>{guiding && index < MAX_SEED_PDFS ? t('guides the search') : fileSize(file.size)}</small>
        </span>
        <button type="button" className="attachment-remove" aria-label={t('Remove {name}', { name: file.name })} onClick={() => setFiles(old => old.filter(f => f.name !== file.name))}><X size={13} /></button>
      </div>)}
  </div>

  // The Models menu: one row per real role, "model · effort" under its name (mockup order: literature, answer, reviewer).
  const withEffort = (name: string, effort: string | null) => effort ? `${name} · ${reasoningLabel(effort)}` : name
  const roleRows: { role: ModelRole; summary: string }[] = [
    { role: 'literature', summary: withEffort(modelName(literature), listedEffort(models, literature, literatureReasoning)) },
    { role: 'answer', summary: withEffort(modelName(model), efforts.some(e => e.id === reasoning) ? reasoning : null) },
    { role: 'reviewer', summary: reviewer === NO_REVIEW || reviewerSummary === t('no reviewer') ? reviewerSummary : withEffort(reviewerSummary, reviewer === DEFAULT_REVIEWER ? listedEffort(models, modelKey(defaults!.reviewer.model_connection, defaults!.reviewer.model!), defaults!.reviewer.reasoning_effort ?? null) : listedEffort(models, reviewer, reviewerReasoning)) },
  ]
  const noModel = Boolean(connections) && !models.length

  // Home is one centred column: the band with the scope, the question, then one control row (+, files, Models, depth, send).
  return <section className="welcome home">
    <h1 className="sr-only" tabIndex={-1}>{uiLanguage() === 'tr' ? <><em>Sorunuz</em> sizi nereye götürüyor?</> : <>Where does your <em>question</em>{' '}lead?</>}</h1>
    <p className="intro sr-only">{t('Ask a question. DEIXIS finds publications, lets you choose the sources, and links each claim to a passage you can open.')}</p>
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit() }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void addFiles(e.dataTransfer.files) }}>
      <div className="composer-band">
        <Select value={scope} onValueChange={value => { if (value) setScope(value as SourceScope) }}>
          <SelectTrigger className="composer-scope" aria-label={t('Source scope')} title={t('Where DEIXIS looks for sources')}><SelectValue>{(value: string) => { const Icon = scopeOptions[value as SourceScope].icon; return <><Icon size={15} aria-hidden />{t(scopeLabels[value as SourceScope])}</> }}</SelectValue></SelectTrigger>
          <SelectContent className="home-menu" align="start" alignItemWithTrigger={false}>
            <div className="home-menu-heading" aria-hidden="true">{t('Workflows')}</div>
            {(Object.keys(scopeLabels) as SourceScope[]).map(s => <SelectItem key={s} value={s} className="home-menu-item"><MenuRow icon={scopeOptions[s].icon} title={t(scopeLabels[s])} detail={t(scopeOptions[s].detail)} /></SelectItem>)}
            <SelectItem value="__systematic_review" className="home-menu-item" disabled><MenuRow icon={Table2} title={t('Systematic review')} detail={t('Protocol, two reviewers, PRISMA flow')} later /></SelectItem>
          </SelectContent>
        </Select>
      </div>
      <label className="composer-label sr-only" htmlFor="research-question">{t('What would you like to investigate?')}</label>
      <Textarea id="research-question" aria-label={t('Research question')} placeholder={t('Ask a research question. DEIXIS searches, screens, reads and links every claim to a passage.')} value={question}
        onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit() } }} />
      {scope === 'attached_and_academic' && files.length === 0 && zotero &&
        <p className="composer-hint">{t('The imported PDFs guide the search.')}</p>}
      <div className="composer-controls">
        <DropdownMenu>
          <DropdownMenuTrigger ref={addButton} type="button" className="composer-add" aria-label={t('Add sources')} title={t('Add sources (optional)')}><Plus size={16} /></DropdownMenuTrigger>
          <DropdownMenuContent className="home-menu" align="start" sideOffset={6}>
            <DropdownMenuItem className="home-menu-item" onClick={() => fileInput.current?.click()}><MenuRow icon={FileUp} title={t('Upload PDF')} detail={t('From this computer, up to 50 MB each. You can also drop files here.')} /></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" onClick={() => setZoteroOpen(true)}><span className="home-menu-row"><ConnectionIcon id="zotero" /><span className="home-menu-text">{t('Zotero collection')}<small>{t('Read-only, from Zotero on this computer or zotero.org. Imported when the research starts.')}</small></span></span></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" disabled><MenuRow icon={BookMarked} title={t('Import BibTeX or RIS')} later /></DropdownMenuItem>
            <DropdownMenuItem className="home-menu-item" disabled><MenuRow icon={Link2} title={t('Add by DOI')} later /></DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {chips}
        {models.length > 0
          ? <DropdownMenu>
              <DropdownMenuTrigger type="button" className="models-summary" title={t('Models for this research: answer, literature and reviewer')}>
                <Cpu size={15} aria-hidden /><span className="models-summary-label">{t('Models')}<span className="sr-only">: </span></span>
                {roleRows.map(row => <span className="sr-only" key={row.role}>{t(modelRoles[row.role].label)} {row.summary}. </span>)}
              </DropdownMenuTrigger>
              <DropdownMenuContent className="home-menu" align="end" sideOffset={6}>
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="home-menu-heading">{t('Models')}</DropdownMenuLabel>
                  {roleRows.map(row => <DropdownMenuItem key={row.role} className="home-menu-item" onClick={() => { setPickerRole(row.role); setPickerNonce(n => n + 1) }}><MenuRow icon={Cpu} title={t(modelRoles[row.role].label)} detail={row.summary} /></DropdownMenuItem>)}
                  <DropdownMenuItem className="home-menu-item" onClick={() => { window.location.hash = '#/settings' }}><MenuRow icon={SlidersHorizontal} title={t('Change the defaults in Settings')} /></DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          : <button type="button" className="models-summary" disabled title={connections ? notReadyReasons(connections) : ''}><Cpu size={15} aria-hidden /><span className="models-summary-label">{t('Models')}</span><span className="sr-only">: {t(connections ? 'no connection ready' : 'checking…')}</span></button>}
        <Select value={effort} onValueChange={value => { if (value) setEffort(value as Effort) }}>
          <SelectTrigger className="composer-depth" aria-label={t('Research depth')} title={t('How much searching and reading a run may do')}><SelectValue>{(value: string) => { const Icon = effortOptions[value as Effort].icon; return <><Icon size={15} aria-hidden />{t(effortLabels[value as Effort])}</> }}</SelectValue></SelectTrigger>
          <SelectContent className="home-menu" align="end" alignItemWithTrigger={false}>
            <div className="home-menu-heading" aria-hidden="true">{t('Depth')}</div>
            {(Object.keys(effortLabels) as Effort[]).map(d => <SelectItem key={d} value={d} className="home-menu-item"><MenuRow icon={effortOptions[d].icon} title={t(effortLabels[d])} detail={effortDetail(d, limits)} /></SelectItem>)}
          </SelectContent>
        </Select>
        <Button className="send-button" type="submit" size="icon" disabled={!question.trim() || busy || !model || !literature || (needsSource && !files.length && !zotero)} aria-label={t('Start research')} title={noModel ? t('Connect a model to start') : undefined}><ArrowUp size={17} /></Button>
      </div>
      {pickerRole && models.length > 0 && <div className="composer-options composer-models">
        {pickerRole === 'answer' && <ModelPicker key={pickerNonce} defaultOpen role={t(modelRoles.answer.label)} icon={modelRoles.answer.icon} hint={t(modelRoles.answer.hint)} models={models} value={model}
          onChange={id => chooseModel(id)} effort={reasoning} onEffort={setReasoning} />}
        {pickerRole === 'literature' && <ModelPicker key={pickerNonce} defaultOpen role={t(modelRoles.literature.label)} icon={modelRoles.literature.icon} hint={t(modelRoles.literature.hint)} models={models} value={literature}
          onChange={id => { setLiterature(id); setLiteratureReasoning(defaultEffort(models, id)) }} effort={literatureReasoning} onEffort={setLiteratureReasoning} />}
        {pickerRole === 'reviewer' && <ModelPicker key={pickerNonce} defaultOpen role={t(modelRoles.reviewer.label)} icon={modelRoles.reviewer.icon} hint={t(modelRoles.reviewer.hint)}
          models={models} value={reviewer} onChange={id => { setReviewer(id); setReviewerReasoning(defaultEffort(models, id)) }}
          effort={reviewerReasoning} onEffort={setReviewerReasoning} choices={reviewerChoices} />}
        <button type="button" className="models-picker-close" aria-label={t('Close')} onClick={() => setPickerRole(null)}><X size={14} /></button>
      </div>}
    </form>
    <ZoteroDialog open={zoteroOpen} onOpenChange={setZoteroOpen} destination="home" busy={busy} initial={zotero} returnFocus={addButton}
      onImport={choice => { setZotero(choice); setZoteroOpen(false); if (scope === 'academic') setScope('attached_and_academic') }} />
    <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void addFiles(e.target.files); e.target.value = '' }} />
    {noModel && <p className="hint">{t('Connect a model to start')}</p>}
    {connections && !models.length && <Notice tone="attention">{t('No model connection is ready: {reason}. A research needs a model that a connection lists; model steps pause until the chosen connection is ready, and no other model is used instead.', { reason: notReadyReasons(connections) })}</Notice>}
    <SemanticSetupNote />
    {error && <Notice tone="error">{error}</Notice>}
    <p className="hint home-hint">{busy ? t('Saving research…') : t('⌘ / Ctrl + Enter starts the research · ? shows shortcuts · Nothing is downloaded from paywalled sites')}</p>
  </section>
}
