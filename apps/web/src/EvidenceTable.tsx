import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { AlignLeft, ArchiveRestore, ArrowUpRight, BookOpenText, Check, ChevronDown, Copy, Download, Ellipsis, FileText, Gauge, Info, Lightbulb, ListChecks, ListPlus, Network, Pause, PencilLine, Play, Plus, RotateCw, Table2, Trash2, TriangleAlert, X, Zap, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogBody, DialogContent, DialogFooter } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, FileTypeIcon } from '@/components/ui/dropdown-menu'
import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { api, ApiError, researchModelApi, tableExportUrl, type AnswerFormat, type CellEdit, type CellEvidence, type CellRevision, type CellState, type CellSummary, type CellValue, type CellView, type ColumnSpec, type ColumnSuggestion, type ResearchView, type Run, type Source, type TableColumn, type TableRow, type TableSummary, type TableTemplate, type TableView } from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { PassageSheet } from './PassageSheet'
import { ModelName } from './ModelName'
import { useModelText, type ModelText } from './modelText'
import { locatorText, runStatusLabels, versionText } from './labels'
import { OCR_LABEL } from './ocr'
import { formatReferenceText, useCitationStyle } from './citations'
import { useToast, type ToastAction } from './Toast'
import { t, uiLanguage, uiLocale } from './i18n'
import { DevelopmentLines } from './lineage/DevelopmentLines'
import type { PassageTarget } from './lineage/LinkRow'
import { StackPanel } from './research/SplitPanel'
import { usePanels } from './research/usePanelStack'
import './EvidenceTable.css'
import './lineage/lineage.css'
import { Notice } from './Notice'
import { focusWhenLost } from './focus'
import { UploadedTextNote } from './SemanticNotes'
import { accessLabels, downloadTableCsv, hasValue, reportGate, revisionText, stateLabels } from './tableCsv'

// The Evidence table panel (mockup `evtable()`, P21-P29; D37/D38): a table whose rows are source versions and whose
// cells are append-only revisions. The screen renders the recorded cell state; only the user's edit or decision changes
// a cell's value. The toolbar, the column menu, the cell panel (stacked on the table, Back returns) and the column
// dialog follow the mockup; the live tools it has no place for sit in its ⋯ menu (§2.2): add rows, development columns,
// development lines (stacked like the cell), the template's name, and Move to Trash.

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// Table runs are controlled where their work shows: the run line under the table's toolbar.
export const TABLE_RUN_KINDS = new Set(['table_fill', 'cell_recheck', 'table_column_recheck', 'table_columns', 'lineage_links'])
const tableRunLabels: Record<string, string> = { table_fill: 'Filling empty cells', cell_recheck: 'Rechecking a cell', table_column_recheck: 'Rechecking a column', table_columns: 'Suggesting columns', lineage_links: 'Development links' }
const MAX_WHOLE_PASSAGES = 48  // a source within this many passages (and 60,000 characters) is read whole
const MAX_RECHECK_PASSAGES = 16
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const newKey = () => crypto.randomUUID()
const conflict = (e: unknown) => e instanceof ApiError && e.status === 409

// The answer formats in the mockup's order, words and icons (`FMT`).
const formatLabels: Record<AnswerFormat, string> = { choice: 'Options', number_unit: 'Number and unit', yes_no: 'Yes / No', text: 'Short text' }
const formatIcons: Record<AnswerFormat, LucideIcon> = { choice: ListChecks, number_unit: Gauge, yes_no: Check, text: AlignLeft }
const editableStates: Exclude<CellState, 'not_verified'>[] = ['value', 'unknown', 'not_reported', 'not_applicable', 'not_found_in_inspected_scope', 'inaccessible']
// What each stored cell state means (the Cell states menu and the cell's second line). The words follow the cell draft
// contract (contracts/research/evidence-cell-draft.schema.json); "Not reported" is only ever a person's choice.
const stateNotes: Record<CellState, string> = {
  value: 'A value with a located quote', not_verified: 'No passage was linked to it', unknown: 'The text is ambiguous',
  not_reported: 'A person recorded that the source does not report it', not_found_in_inspected_scope: 'The passages read do not address it',
  not_applicable: 'Does not apply to this work', inaccessible: 'No abstract or full text to read',
}
const stateOrder: CellState[] = ['value', 'not_verified', 'unknown', 'not_reported', 'not_found_in_inspected_scope', 'not_applicable', 'inaccessible']
const authorLabels: Record<CellRevision['author'], string> = { model: 'Model', human: 'You', system: 'System' }
const depthLabels: Record<NonNullable<CellRevision['reading_depth']>, string> = { metadata: 'Metadata', abstract: 'Abstract', selected_sections: 'Selected pages', full_text: 'Full text' }
const kindLabels: Record<CellRevision['kind'], string> = {
  model_fill: 'Model filled the empty cell', model_proposal: 'Model proposal', system_fill: 'No stored text; recorded without a model call',
  human_edit: 'Your edit', accept_proposal: 'You used a proposal', dismiss_proposal: 'You kept the current value',
}
const decisionLabels: Record<NonNullable<CellRevision['decision']>, string> = { accepted: 'used', dismissed: 'not used', pending: 'waiting for your decision', superseded: 'replaced by a newer proposal' }
const selectionLabels: Record<string, string> = { included: 'Included in Sources', pending: 'Undecided in Sources', excluded: 'Excluded in Sources' }
const selectionOrder: Record<string, number> = { included: 0, pending: 1, excluded: 2 }

function formatText(column: Pick<ColumnSpec, 'answer_format' | 'unit_hint' | 'allow_multiple'> & { options: unknown[] | null }) {
  const parts = [t(formatLabels[column.answer_format])]
  if (column.answer_format === 'number_unit' && column.unit_hint) parts.push(column.unit_hint)
  if (column.answer_format === 'choice') parts.push(t(column.allow_multiple ? '{n} options, several allowed' : '{n} options, one allowed', { n: column.options?.length ?? 0 }))
  return parts.join(' · ')
}

const dateText = (value: string) => new Date(value).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })
// The row's short name: the work's source key (D59), as the mockup's "Çobanlar et al. 2020"; the title when it has none.
const shortName = (row: Pick<TableRow, 'source_key' | 'title'>) => row.source_key || row.title

function revisionMeta(rev: CellRevision, modelText: ModelText) {
  const rest = [dateText(rev.created_at), t('column definition {n}', { n: rev.column_revision }),
    rev.reading_depth && t('read from: {depth}', { depth: t(depthLabels[rev.reading_depth]) })].filter(Boolean).join(' · ')
  return <>{t(authorLabels[rev.author])}{rev.model?.connection && rev.model.resolved_model && <> · <ModelName connection={rev.model.connection} text={modelText(rev.model.resolved_model)} /></>} · {rest}</>
}

type EditorTarget = { mode: 'add' } | { mode: 'edit'; column: TableColumn } | { mode: 'suggestion'; suggestion: ColumnSuggestion; stepId: string }

// The live table run with its controls; a paused run offers Resume. Cancel asks first, since a cancelled run cannot be
// resumed. The lock itself is the toolbar's "Model actions locked" pill.
function TableRunLine({ run, detail, model, connection, busy, onControl }: { run: Run; detail: string; model: string; connection: string; busy: boolean; onControl: (action: 'pause' | 'resume' | 'cancel') => void }) {
  const live = ACTIVE.has(run.status)
  return <div className={`evidence-run${live ? ' is-live' : ''}`} data-run-id={run.id} role="status" tabIndex={-1}>
    <span className="evidence-run-signal" aria-hidden><i /></span>
    <strong>{t(tableRunLabels[run.kind])}</strong>
    {(run.status !== 'running' || detail) && <span className="evidence-run-detail">{[run.status !== 'running' && t(runStatusLabels[run.status]), detail].filter(Boolean).join(' · ')}</span>}
    <span className="evidence-run-model"><ModelName connection={connection} text={model} /></span>
    {live && <Elapsed since={run.created_at} />}
    <span className="evidence-run-end">
      <span className="evidence-run-controls">
        {live && run.status !== 'pause_requested' && <Button variant="ghost" size="sm" disabled={busy} onClick={() => onControl('pause')}><Pause size={13} aria-hidden />{t('Pause')}</Button>}
        {run.status === 'paused' && <Button variant="ghost" size="sm" disabled={busy} onClick={() => onControl('resume')}><Play size={13} aria-hidden />{t('Resume')}</Button>}
        <Button variant="ghost" size="sm" className="evidence-run-cancel" disabled={busy} onClick={() => onControl('cancel')}><X size={13} aria-hidden />{t('Cancel')}</Button>
      </span>
    </span>
  </div>
}

// Time since the run was created, ticking each second.
export function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id) }, [])
  const secs = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000))
  const text = secs >= 3600 ? `${Math.floor(secs / 3600)}:${String(Math.floor(secs / 60) % 60).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}` : `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
  return <span className="evidence-run-time" aria-hidden>{text}</span>
}

// The templates a table can start from (mockup menu `tpl`): one row per saved template, its columns under its name.
function TemplateMenu({ templates, busy, label, detail, onPick }: { templates: TableTemplate[] | null; busy: boolean; label: string; detail: string; onPick: (template: TableTemplate) => void }) {
  return <DropdownMenu>
    <DropdownMenuTrigger render={<button type="button" disabled={busy} />}><Copy size={16} aria-hidden /><span>{label}<small>{detail}</small></span></DropdownMenuTrigger>
    <DropdownMenuContent align="start" className="table-menu">
      <DropdownMenuGroup>
        <DropdownMenuLabel>{t('Templates')}</DropdownMenuLabel>
        {templates === null ? <p className="table-menu-note">{t('Loading templates…')}</p>
          : templates.length ? templates.map(tpl => <DropdownMenuItem key={tpl.id} onClick={() => onPick(tpl)}><Table2 size={15} aria-hidden /><span>{tpl.name}<small>{tpl.columns.map(c => c.name).join(' · ')}</small></span></DropdownMenuItem>)
          : <p className="table-menu-note">{t('No saved templates yet. A table’s columns can be saved as a template from its More table actions menu.')}</p>}
      </DropdownMenuGroup>
    </DropdownMenuContent>
  </DropdownMenu>
}

// initialTableId: the table to show first, e.g. one just started from chosen sources.
// tableRequest: counts the owner's requests to show initialTableId, so a table card clicked while the panel is open
// switches the table shown (the panel is not mounted anew). `cell`, with a request, opens that cell's panel too (an
// evidence report's "Open the current cell").
export function EvidenceTab({ researchId, view, dark, initialTableId = null, tableRequest = 0, cell: cellRequest = null, onCellShown, modelText, onRunStarted }: {
  researchId: string; view: ResearchView; dark: boolean; initialTableId?: string | null; tableRequest?: number
  cell?: { columnId: string; sourceId: string } | null; onCellShown?: () => void; modelText: ModelText; onRunStarted: () => void
}) {
  const toast = useToast()
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  const [chosen, setChosen] = useState<string | null>(initialTableId)
  const [cellTarget, setCellTarget] = useState<{ columnId: string; sourceId: string } | null>(cellRequest)
  const [shownRequest, setShownRequest] = useState(tableRequest)
  if (shownRequest !== tableRequest) {
    setShownRequest(tableRequest)
    if (initialTableId) setChosen(initialTableId)
    setCellTarget(cellRequest)
  }
  // A cell request is shown once: the owner forgets it, so reopening the table later does not reopen the cell.
  useEffect(() => { if (cellRequest) onCellShown?.() }, [cellRequest, onCellShown])
  const [trashedTables, setTrashedTables] = useState(0)
  const [table, setTable] = useState<TableView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [templates, setTemplates] = useState<TableTemplate[] | null>(null)
  const [editor, setEditor] = useState<EditorTarget | null>(null)
  const [removing, setRemoving] = useState<TableColumn | null>(null)
  const [removingAll, setRemovingAll] = useState(false)
  const [sourceTarget, setSourceTarget] = useState<string | null>(null)
  const [lineageOpen, setLineageOpen] = useState(false)
  const [lineagePassage, setLineagePassage] = useState<PassageTarget | null>(null)
  const [addRowsOpen, setAddRowsOpen] = useState(false)
  const [templateName, setTemplateName] = useState<string | null>(null)
  const [discarded, setDiscarded] = useState<string[]>([])
  const [focus, setFocus] = useState<[number, number]>([0, 0])
  const [cancelling, setCancelling] = useState<Run | null>(null)
  const grid = useRef<HTMLTableElement>(null)
  const [style] = useCitationStyle()

  const fetchTable = useCallback(async () => {
    const list = await api.tables(researchId)
    const id = list.find(x => x.id === chosen)?.id ?? list[0]?.id
    return { list, view: id ? await api.table(researchId, id) : null }
  }, [researchId, chosen])
  const load = useCallback(() => fetchTable().then(r => { setTables(r.list); setTable(r.view); setError('') }, e => setError(errorText(e))), [fetchTable])
  // The research page reloads on every recorded event, table and cell events included; a response for an older event is dropped.
  useEffect(() => {
    let live = true
    fetchTable().then(r => { if (live) { setTables(r.list); setTable(r.view); setError('') } }, e => { if (live) setError(errorText(e)) })
    return () => { live = false }
  }, [fetchTable, view.last_event_id])

  // Without a table, say whether this research has tables in the Trash (D50).
  const noTables = tables?.length === 0
  useEffect(() => {
    if (!noTables) return
    let live = true
    api.trash().then(trash => { if (live) setTrashedTables(trash.tables.filter(x => x.research_id === researchId).length) }, () => { /* the link is left out */ })
    return () => { live = false }
  }, [noTables, researchId, view.last_event_id])

  // Without a table, or with a table without columns, the saved templates are a start.
  const needsColumns = noTables || (table ? table.columns.length === 0 : false)
  useEffect(() => {
    if (!needsColumns) return
    let live = true
    api.tableTemplates().then(list => { if (live) setTemplates(list) }, () => { if (live) setTemplates([]) })
    return () => { live = false }
  }, [needsColumns, view.last_event_id])

  async function act(action: () => Promise<unknown>, success?: string, undo?: ToastAction) {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setBusy(true)
    try { await action(); if (success) toast('success', success, undo); await load(); return true }
    catch (e) {
      // 409: the table, column or run state changed after this screen loaded (another tab, or a run that moved on).
      if (conflict(e)) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: errorText(e) })); await load() }
      else toast('error', errorText(e))
      // On failure, restore the initiating control only after it is enabled again and focus is still lost.
      focusWhenLost(() => opener?.isConnected && !opener.matches(':disabled') ? opener : null, 2500, false, opener)
      return false
    } finally { setBusy(false) }
  }

  const run = view.runs[0] as Run | undefined
  const activeRun = run && ACTIVE.has(run.status) ? run : null
  const model = modelText(view.scope.requested_model, view.scope.reasoning_effort)
  const tableRun = run && TABLE_RUN_KINDS.has(run.kind) && (activeRun || run.status === 'paused') ? run : null
  const summary = tables?.find(item => item.id === table?.table.id)
  const { reason: reportReason, continueWithFailed } = reportGate(view, summary, table?.columns.length ?? 0, table?.table.title ?? '')
  const control = (target: Run, action: 'pause' | 'resume' | 'cancel') => act(() => api.controlRun(target.id, action))
  const cancelDialog = <ConfirmDialog open={Boolean(cancelling)} dark={dark} title={t('Cancel this run?')}
    description={t(cancelling?.kind === 'lineage_links' ? 'The run stops. Development decisions already recorded are kept. A cancelled run cannot be resumed.' : 'The run stops. Values already written stay in the table; the answer of a model call still in progress is not written. A cancelled run cannot be resumed; empty cells can be filled again later.')}
    confirmLabel={t('Cancel run')} cancelLabel={t('Keep running')} busy={busy}
    onConfirm={() => { const target = cancelling; setCancelling(null); if (target) void control(target, 'cancel') }}
    onOpenChange={open => { if (!open) setCancelling(null) }} />
  const runLine = (detail: string[]) => tableRun && <TableRunLine run={tableRun} detail={detail.join(' · ')} model={model} connection={view.scope.model_connection} busy={busy}
    onControl={action => (action === 'cancel' ? setCancelling(tableRun) : void control(tableRun, action))} />
  const createTable = (templateId?: string) => api.createTable(researchId, { title: t('Evidence table'), ...(templateId ? { template_id: templateId } : {}) }, newKey())
  const templateDetail = templates === null ? t('Columns saved from an earlier table') : templates.length ? t(templates.length === 1 ? '{n} saved' : '{n} saved', { n: templates.length }) : t('None saved yet')
  // "Suggest columns" (mockup `suggest`): the proposals arrive in a box above the table and none joins it until added.
  const suggestNote = t('Up to eight proposals; you accept each one')
  const suggestTitle = t('{model} · 1–2 calls', { model })

  // The open cell's row or column left the table (removed here or in another tab): its panel leaves the stack and the
  // table is shown again, never an empty panel.
  const removePanel = usePanels()?.remove
  const cellGone = Boolean(table && cellTarget && (!chosen || table.table.id === chosen) && (!table.columns.some(c => c.id === cellTarget.columnId) || !table.rows.some(r => r.source_version_id === cellTarget.sourceId)))
  useEffect(() => {
    if (!cellGone) return
    setCellTarget(null)
    removePanel?.('cell')
  }, [cellGone, removePanel])

  if (error && !tables) return <div className="table-panel"><Notice tone="error">{t('Could not load the evidence table: {error}', { error })}</Notice></div>
  if (!tables) return <div className="table-panel"><p className="empty-inline">{t('Loading the evidence table…')}</p></div>

  // No table yet: the three starts create it (mockup `.empty` with `.qopts`).
  if (!table) return <div className="table-panel">
    {runLine([])}
    {cancelDialog}
    <div className="empty evidence-empty"><div>
      <Table2 size={22} aria-hidden />
      <h2>{t('No table yet.')}</h2>
      <p>{t(view.counts.included === 1 ? 'It starts with the {n} included source; you can add or remove rows.' : 'It starts with the {n} included sources; you can add or remove rows.', { n: view.counts.included })} {t('Columns say what to pull from each source. Every value links back to the passage it came from.')}</p>
      <div className="qopts">
        <button type="button" disabled={busy || Boolean(activeRun)} title={activeRun ? t('Available when the active run finishes') : suggestTitle}
          onClick={() => act(async () => { const created = await createTable(); await api.suggestColumns(researchId, created.table.id, newKey()); onRunStarted() })}>
          <Lightbulb size={16} aria-hidden /><span>{t('Suggest columns from the question')}<small>{activeRun ? t('Available when the active run finishes') : suggestNote}</small></span>
        </button>
        <button type="button" disabled={busy} onClick={() => act(async () => { await createTable(); setEditor({ mode: 'add' }) })}>
          <Plus size={16} aria-hidden /><span>{t('Add a column')}<small>{t('Name it, describe it, choose a format')}</small></span>
        </button>
        <TemplateMenu templates={templates} busy={busy} label={t('Start from a template')} detail={templateDetail}
          onPick={tpl => { void act(() => createTable(tpl.id), t('Table started from “{name}”.', { name: tpl.name })) }} />
      </div>
      {trashedTables > 0 && <p className="evidence-trash-link"><ArchiveRestore size={14} aria-hidden />{t(trashedTables === 1 ? '{n} table of this research is in the Trash.' : '{n} tables of this research are in the Trash.', { n: trashedTables })} <a href="#/trash">{t('Show in Trash')}</a></p>}
    </div></div>
  </div>

  const tableId = table.table.id
  const { columns, rows, fill_estimate: estimate } = table
  const hasDevelopmentColumns = (['problem', 'change', 'uncertainty'] as const).every(role => columns.some(c => c.lineage_role === role))
  const cells = new Map<string, CellSummary>(table.cells.map(c => [`${c.column_id}:${c.source_version_id}`, c]))
  // Live state comes from the active run's stored target: the cells a fill plans to read, or the one cell a recheck reads.
  const filling = new Set<string>()
  if (activeRun?.kind === 'table_fill' && activeRun.target?.table_id === tableId) activeRun.target.sources?.forEach(s => s.column_ids.forEach(cid => filling.add(`${cid}:${s.source_version_id}`)))
  // A cell recheck reads its one cell; a column recheck (S27, F20) its planned cells in row order, each until its step
  // has finished (the step's key names the cell's source).
  const rechecking = new Set<string>()
  if (activeRun?.kind === 'cell_recheck' && activeRun.target?.table_id === tableId) rechecking.add(`${activeRun.target.column_id}:${activeRun.target.source_version_id}`)
  const columnRecheck = activeRun?.kind === 'table_column_recheck' && activeRun.target?.table_id === tableId ? activeRun : null
  const columnDone = new Set((columnRecheck?.steps ?? []).filter(step => step.operation_key.startsWith('column_recheck:') && (step.status === 'succeeded' || step.status === 'failed')).map(step => step.operation_key.slice('column_recheck:'.length)))
  columnRecheck?.target?.cells?.forEach(cell => { if (!columnDone.has(cell.source_version_id)) rechecking.add(`${columnRecheck.target?.column_id}:${cell.source_version_id}`) })
  const columnProgress = columnRecheck?.target?.cells?.length ? { done: columnRecheck.target.cells.filter(cell => columnDone.has(cell.source_version_id)).length, n: columnRecheck.target.cells.length } : null
  const suggesting = activeRun?.kind === 'table_columns' && activeRun.target?.table_id === tableId
  const fillable = !activeRun && estimate.sources > 0 && columns.length > 0
  // A planned source counts as done once every cell it was to fill has a value.
  const planned = activeRun?.kind === 'table_fill' && activeRun.target?.table_id === tableId ? activeRun.target.sources ?? [] : null
  const fillProgress = planned?.length ? { done: planned.filter(s => s.column_ids.every(cid => cells.get(`${cid}:${s.source_version_id}`)?.current)).length, n: planned.length } : null
  const suggestColumns = () => act(async () => { await api.suggestColumns(researchId, tableId, newKey()); onRunStarted() })
  // The toast names what the server planned: the cells it reads and the rows it skips for having no stored text.
  const recheckColumn = (col: TableColumn) => act(async () => {
    const run = await researchModelApi.recheckColumn(researchId, tableId, col.id, col.version, newKey())
    const planned = run.target?.cells?.length ?? 0, skipped = run.target?.rows_without_text?.length ?? 0
    toast('success', [t(planned === 1 ? 'Recheck of “{column}” started: {n} cell is read again. Its result will wait as a proposal.' : 'Recheck of “{column}” started: {n} cells are read again. Their results will wait as proposals.', { column: col.name, n: planned }),
      skipped > 0 && t(skipped === 1 ? '{n} row has no stored text and gets no call.' : '{n} rows have no stored text and get no call.', { n: skipped })].filter(Boolean).join(' '))
    onRunStarted()
  })
  const names = new Set(columns.map(c => c.name.trim().toLocaleLowerCase()))
  const suggestionRun = table.column_suggestions
  const suggestions = (suggestionRun?.columns ?? []).map((s, i) => ({ s, key: `${suggestionRun?.step_id}:${i}` }))
    .filter(({ s, key }) => !names.has(s.name.trim().toLocaleLowerCase()) && !discarded.includes(key))
  const [fr, fc] = [Math.min(focus[0], rows.length - 1), Math.min(focus[1], columns.length - 1)]
  const cellColumn = cellTarget && columns.find(c => c.id === cellTarget.columnId)
  const cellRow = cellTarget && rows.find(r => r.source_version_id === cellTarget.sourceId)
  const sourceById = new Map(view.sources.map(s => [s.source_version_id, s]))
  const openLineagePassage = async (target: PassageTarget) => {
    if (!target.sourceVersionId || sourceById.has(target.sourceVersionId)) { setLineagePassage(target); return }
    // Removed corpus members are absent from research.sources. Resolve their stored version through the Library,
    // as the Library source sheet does, without substituting another version or restoring membership.
    try {
      if (!target.workId) throw new Error(t('Source record unavailable'))
      const stored = await api.libraryWork(target.workId)
      const version = stored.versions.find(v => v.source_version_id === target.sourceVersionId)
      if (!version?.asset && !version?.abstract_passage_id) throw new Error(t('No stored text is available for this source version.'))
      setLineagePassage({ passageId: version?.asset ? null : version!.abstract_passage_id, assetId: version?.asset?.id })
    } catch (e) { toast('error', errorText(e)) }
  }
  const lang = uiLanguage() === 'tr' ? 'tr' : 'en'

  const moveFocus = (e: KeyboardEvent<HTMLTableElement>) => {
    if (!(e.target as HTMLElement).dataset.cell) return
    const steps: Record<string, [number, number]> = { ArrowRight: [fr, fc + 1], ArrowLeft: [fr, fc - 1], ArrowDown: [fr + 1, fc], ArrowUp: [fr - 1, fc], Home: [fr, 0], End: [fr, columns.length - 1] }
    const next = steps[e.key]
    if (!next) return
    e.preventDefault()
    const [r, c] = [Math.max(0, Math.min(next[0], rows.length - 1)), Math.max(0, Math.min(next[1], columns.length - 1))]
    setFocus([r, c])
    grid.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`)?.focus()
  }
  const saveColumn = (target: EditorTarget, spec: ColumnSpec) => act(async () => {
    if (target.mode === 'edit') await api.reviseColumn(researchId, tableId, target.column.id, spec, columns.find(c => c.id === target.column.id)?.version ?? target.column.version)
    else await api.addColumn(researchId, tableId, target.mode === 'suggestion' ? { ...spec, suggestion_step_id: target.stepId } : spec, table.table.version, newKey())
    setEditor(null)
  }, t(target.mode === 'edit' ? 'Column saved.' : 'Column added.')).then(ok => {
    // The button that opened the editor may be gone (the empty-table prompt): the new column's header, the last one, takes the focus then.
    if (ok && target.mode !== 'edit') focusWhenLost(() => Array.from(grid.current?.querySelectorAll<HTMLElement>('.evidence-col-head') ?? []).at(-1))
  })
  const suggestionSpec = (s: ColumnSuggestion): ColumnSpec => ({ name: s.name, instruction: s.instruction, answer_format: s.answer_format, options: s.options, allow_multiple: s.allow_multiple, unit_hint: s.unit_hint })
  const fillEmptyCells = async () => {
    const origin = document.activeElement
    let started: Run | undefined
    if (!await act(async () => { started = await api.fillTable(researchId, tableId, table.table.version, newKey()); onRunStarted() }) || !started) return
    const runId = started.id
    // Follow this fill's status line to the current cell when the line leaves, unless the person has moved focus elsewhere.
    focusWhenLost(() => document.querySelector<HTMLElement>(`.evidence-run[data-run-id="${runId}"]`) ?? grid.current?.querySelector<HTMLElement>('[data-cell][tabindex="0"]'), 120_000, true, origin)
  }
  // "Remove all columns" (mockup ⋯ menu): the column removal of one column, once per column in order. The first refusal
  // stops the rest; the message counts only the columns the server removed, and Undo restores exactly those.
  const removeAllColumns = async () => {
    const targets = columns.slice()
    const removed: TableColumn[] = []
    setBusy(true)
    let failure = ''
    try {
      for (const column of targets) {
        try { await api.removeColumn(researchId, tableId, column.id, column.version); removed.push(column) }
        catch (e) { failure = errorText(e); break }
      }
    } finally { setBusy(false) }
    const restoreAll = () => { void act(async () => {
      let restored = 0
      try { for (const column of removed) { await api.restoreColumn(researchId, tableId, column.id, column.version + 1); restored += 1 } }
      catch (e) { throw new Error(t('Restored {n} of {m} columns: {error}', { n: restored, m: removed.length, error: errorText(e) })) }
    }, t('Columns restored with their cells.')) }
    const undo = removed.length ? { label: t('Undo'), run: restoreAll } : undefined
    if (!failure) toast('success', t(removed.length === 1 ? '{n} column removed. Its cells stay stored.' : '{n} columns removed. Their cells stay stored.', { n: removed.length }), undo)
    else toast(removed.length ? 'warning' : 'error', removed.length ? t('Removed {n} of {m} columns; the rest were not removed: {error}', { n: removed.length, m: targets.length, error: failure }) : failure, undo)
    await load()
  }
  const lockTitle = t('Model actions are off until it finishes.')

  // The live tools with no place in the mockup (§2.2) follow its two rows in the ⋯ menu.
  const moreMenu = <DropdownMenu>
    <DropdownMenuTrigger render={<button type="button" className="ib" disabled={busy} aria-label={t('More table actions')} title={t('More table actions')} />}><Ellipsis size={16} aria-hidden /></DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="table-menu">
      <DropdownMenuItem disabled={!columns.length} onClick={() => setTemplateName(table.table.title)}><Copy size={15} aria-hidden /><span>{t('Save as template')}<small>{t('Keeps the columns, not the values')}</small></span></DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem disabled={!columns.length} onClick={() => setRemovingAll(true)}><X size={15} aria-hidden /><span>{t('Remove all columns')}<small>{t('Keeps the sources')}</small></span></DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem className="table-menu-placement" onClick={() => setAddRowsOpen(true)}><ListPlus size={15} aria-hidden /><span>{t('Add rows')}<small>{t('Sources of this research that are not rows yet')}</small></span></DropdownMenuItem>
      {!hasDevelopmentColumns && <DropdownMenuItem className="table-menu-placement" onClick={() => { void act(() => api.addDevelopmentColumns(researchId, tableId, table.table.version, newKey()), t('Development columns added.')) }}><Plus size={15} aria-hidden /><span>{t('Add development columns')}<small>{t('Problem, change and uncertainty, for the development lines')}</small></span></DropdownMenuItem>}
      <DropdownMenuItem className="table-menu-placement" onClick={() => setLineageOpen(true)}><Network size={15} aria-hidden /><span>{t('Development lines')}<small>{t('How the works build on each other')}</small></span></DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem className="table-menu-placement" onClick={() => {
        const version = table.table.version
        void act(() => api.trashTable(researchId, tableId, version), t('Table moved to Trash. Its cells and edits are kept.'),
          { label: t('Undo'), run: () => { void act(async () => { await api.restoreTable(researchId, tableId, version + 1); setChosen(tableId) }, t('Table restored.')) } })
      }}><Trash2 size={15} aria-hidden /><span>{t('Move to Trash')}</span></DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>

  return <div className="table-panel">
    {/* What a report from this table would leave out, then why it cannot be written yet (mockup `repGate`). */}
    {continueWithFailed && summary && <div className="notice warn table-failed"><TriangleAlert size={16} aria-hidden /><span>{t('{n} of {m} sources did not complete the table (missing cells: {cells}). These rows will be excluded from the report’s evidence assessment and aggregation denominators.', { n: summary.report_ready.failed_rows, m: summary.report_ready.included_rows, cells: summary.report_ready.cells_left })}</span></div>}
    {reportReason && <p id="evidence-report-reason" className={columns.length ? 'foot-note table-reason' : 'sr-only'}>{reportReason}</p>}
    <div className="toolbar evidence-toolbar">
      {columns.length ? <button type="button" className="ghost" disabled={busy} onClick={() => setEditor({ mode: 'add' })}><Plus size={15} aria-hidden />{t('Add column')}</button>
        : <span className="table-rows-count">{t(rows.length === 1 ? '{n} source' : '{n} sources', { n: rows.length })}</span>}
      {columns.length > 0 && <button type="button" className="ghost" disabled={busy || Boolean(activeRun)} title={suggestTitle} onClick={suggestColumns}><Lightbulb size={15} aria-hidden />{t('Suggest columns')}</button>}
      {columns.length > 0 && estimate.sources > 0 && <button type="button" className="ghost tint" disabled={busy || !fillable} onClick={fillEmptyCells}>
        <Zap size={15} aria-hidden />{t(estimate.sources === 1 ? 'Fill empty cells · {n} source · up to {calls} calls · {model}' : 'Fill empty cells · {n} sources · up to {calls} calls · {model}', { n: estimate.sources, calls: estimate.max_model_calls, model })}
      </button>}
      <button type="button" className="ghost" disabled={busy || Boolean(reportReason)} title={reportReason || undefined} aria-describedby={reportReason ? 'evidence-report-reason' : undefined}
        onClick={() => act(async () => { await api.startReport(researchId, tableId, newKey(), continueWithFailed ? { continueWithFailed: true } : undefined); onRunStarted() })}><AlignLeft size={15} aria-hidden />{t(continueWithFailed ? 'Write the report with missing rows' : 'Write a manuscript draft')}</button>
      {activeRun && <span className="lockb" title={lockTitle}><Pause size={13} aria-hidden />{t('Model actions locked')}</span>}
      <span className="spacer" />
      {columns.length > 0 && <DropdownMenu>
        <DropdownMenuTrigger render={<button type="button" className="ghost" />}><Info size={15} aria-hidden />{t('Cell states')}</DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="table-menu">
          <DropdownMenuGroup>
            <DropdownMenuLabel>{t('Cell states')}</DropdownMenuLabel>
            {stateOrder.map(state => <div key={state} className="table-menu-info" role="presentation">{t(stateLabels[state])}<small>{t(stateNotes[state])}</small></div>)}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>}
      {columns.length > 0 && <DropdownMenu>
        <DropdownMenuTrigger render={<button type="button" className="ib" aria-label={t('Download table')} title={t('Download')} />}><Download size={16} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" sideOffset={6} className="research-export-menu table-export-menu">
          <DropdownMenuItem className="research-export-item menu-fmt" disabled={!rows.length} title={t('Current values and their quotes as a CSV file; proposals waiting for a decision are left out.')} onClick={() => downloadTableCsv(table, view.sources)}><FileTypeIcon format="CSV" /><b>CSV</b><span>{t('Comma-separated values')}</span></DropdownMenuItem>
          {rows.length > 0 && <MenuPrimitive.LinkItem href={tableExportUrl(researchId, tableId, 'xlsx', lang, style)} download closeOnClick data-slot="dropdown-menu-item" className="research-export-item menu-fmt"><FileTypeIcon format="XLSX" /><b>XLSX</b><span>{t('Excel workbook')}</span></MenuPrimitive.LinkItem>}
          {rows.length > 0 && <MenuPrimitive.LinkItem href={tableExportUrl(researchId, tableId, 'docx', lang, style)} download closeOnClick data-slot="dropdown-menu-item" className="research-export-item menu-fmt"><FileTypeIcon format="DOCX" /><b>DOCX</b><span>{t('Word table')}</span></MenuPrimitive.LinkItem>}
        </DropdownMenuContent>
      </DropdownMenu>}
      {moreMenu}
      {tables.length > 1 && <select className="evidence-table-choice" aria-label={t('Table')} value={tableId} onChange={e => setChosen(e.target.value)}>{tables.map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select>}
    </div>
    {runLine(fillProgress ? [t('{done} / {n} sources', fillProgress)] : columnProgress ? [t('{column}: {done} / {n} cells', { column: columns.find(c => c.id === columnRecheck?.target?.column_id)?.name ?? '', ...columnProgress })] : suggesting ? [t('From the question and the rows’ abstracts')] : [])}
    {cancelDialog}
    {(fillable || (activeRun && !tableRun) || estimate.sources_without_text > 0 || estimate.sources_beyond_limit > 0 || columns.some(c => c.accepted_by === 'automatic')) && <div className="table-notes">
      {fillable && <UploadedTextNote semantic={view.semantic} />}
      {((activeRun && !tableRun) || estimate.sources_without_text > 0 || estimate.sources_beyond_limit > 0) && <p className="foot-note evidence-toolbar-note">
        {[activeRun && !tableRun && t('Model actions are off while a run is active.'),
          estimate.sources_without_text > 0 && t('{n} of the sources to fill have no stored text; they get “No text” without a model call.', { n: estimate.sources_without_text }),
          estimate.sources_beyond_limit > 0 && t('{n} more sources wait for another fill (at most 25 per run).', { n: estimate.sources_beyond_limit })].filter(Boolean).join(' ')}
      </p>}
      {columns.some(c => c.accepted_by === 'automatic') && <p className="foot-note">{t('The app added these columns from the model’s proposal after the answer. No person reviewed them.')}</p>}
    </div>}

    {templateName !== null && <form className="evidence-inline-form" onSubmit={e => { e.preventDefault(); if (templateName.trim()) void act(async () => { await api.saveTableTemplate(researchId, tableId, templateName.trim(), newKey()); setTemplateName(null) }, t('Template saved.')) }}>
      <label><span>{t('Template name')}</span><input value={templateName} maxLength={120} autoFocus onChange={e => setTemplateName(e.target.value)} /></label>
      <button type="submit" className="btn-pri" disabled={busy || !templateName.trim()}>{t('Save template')}</button>
      <button type="button" className="ghost" onClick={() => setTemplateName(null)}>{t('Cancel')}</button>
      <small>{t('Saves the column definitions for any research; rows and values are not saved.')}</small>
    </form>}
    {addRowsOpen && <AddRows sources={view.sources} table={table} busy={busy} onClose={() => setAddRowsOpen(false)}
      onAdd={ids => act(async () => { await api.addTableRows(researchId, tableId, ids, table.table.version); setAddRowsOpen(false) }, t('Rows added.'))} />}

    {/* The model's column suggestions (mockup `.sugg`): one row per proposal; none joins the table until added. */}
    {suggesting && <div className="sugg" role="status"><h5><span className="spin" aria-hidden />{t('Suggesting columns from the question…')}</h5></div>}
    {!suggesting && suggestionRun && suggestions.length > 0 && <section className="sugg evidence-suggestions" aria-labelledby="evidence-suggestions-title">
      <h5 id="evidence-suggestions-title"><Lightbulb size={14} aria-hidden />{t('Suggested from the question')}<span className="spacer" />
        <button type="button" className="ib" aria-label={t('Dismiss suggestions')} title={t('Hides the suggestions on this screen; they stay in the run record.')} onClick={() => setDiscarded([...discarded, ...suggestions.map(x => x.key)])}><X size={14} aria-hidden /></button></h5>
      {suggestions.map(({ s, key }) => <div key={key} className="sugg-row">
        <p>{s.name}<small>{s.instruction} · {formatText(s)}</small>{s.rationale && <small className="sugg-why">{s.rationale}</small>}</p>
        <button type="button" className="ghost" disabled={busy} onClick={() => act(() => api.addColumn(researchId, tableId, { ...suggestionSpec(s), suggestion_step_id: suggestionRun.step_id }, table.table.version, newKey()), t('{name} added, empty. Use Fill empty cells to fill it.', { name: s.name }))}><Plus size={14} aria-hidden />{t('Add')}</button>
        <button type="button" className="ghost" disabled={busy} onClick={() => setEditor({ mode: 'suggestion', suggestion: s, stepId: suggestionRun.step_id })}>{t('Edit')}</button>
        <button type="button" className="ghost" title={t('Hides the suggestion on this screen; it stays in the run record.')} onClick={() => setDiscarded([...discarded, key])}>{t('Discard')}</button>
      </div>)}
      {suggestionRun.notes && <p className="foot-note sugg-notes">{suggestionRun.notes}</p>}
    </section>}

    {!columns.length ? <div className="empty evidence-first"><div>
        <Table2 size={22} aria-hidden />
        <h2>{t(rows.length === 1 ? '{n} source, no columns yet' : '{n} sources, no columns yet', { n: rows.length })}</h2>
        <p>{t('Columns say what to pull from each source. Every value links back to the passage it came from.')}</p>
        <div className="qopts">
          <button type="button" disabled={busy || Boolean(activeRun)} title={activeRun ? t('Available when the active run finishes') : suggestTitle} onClick={suggestColumns}>
            <Lightbulb size={16} aria-hidden /><span>{t('Suggest columns from the question')}<small>{activeRun ? t('Available when the active run finishes') : suggestNote}</small></span>
          </button>
          <button type="button" disabled={busy} onClick={() => setEditor({ mode: 'add' })}><Plus size={16} aria-hidden /><span>{t('Add a column')}<small>{t('Name it, describe it, choose a format')}</small></span></button>
          <TemplateMenu templates={templates} busy={busy} label={t('Start from a template')} detail={templateDetail}
            onPick={tpl => { void act(() => api.applyTableTemplate(researchId, tableId, tpl.id, table.table.version, newKey()), t('Columns added from “{name}”.', { name: tpl.name })) }} />
        </div>
      </div></div>
      : !rows.length ? <p className="empty-inline">{t('The table has no rows. Add sources of this research as rows.')}</p>
      : <>
        <div className="tbl-wrap evidence-grid-wrap">
          <table ref={grid} className="evidence-grid" role="grid" aria-label={table.table.title} aria-describedby="evidence-grid-keys" onKeyDown={moveFocus}>
            <thead><tr>
              <th scope="col" className="evidence-corner">{t('Source')}</th>
              {columns.map(col => { const Icon = formatIcons[col.answer_format]; return <th scope="col" key={col.id}>
                <DropdownMenu>
                  <DropdownMenuTrigger render={<button type="button" className="th-b evidence-col-head" title={col.instruction} aria-describedby={`evidence-instruction-${col.id}`} />}>
                    <Icon size={13} aria-hidden /><span>{col.name}</span><ChevronDown size={13} aria-hidden />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="table-menu">
                    <DropdownMenuGroup>
                      <DropdownMenuLabel>{col.name}</DropdownMenuLabel>
                      <DropdownMenuItem onClick={() => setEditor({ mode: 'edit', column: col })}><PencilLine size={15} aria-hidden /><span>{t('Edit column')}<small>{formatText(col)}</small></span></DropdownMenuItem>
                      {/* One run over the column's rows (F20); each result waits as a proposal in its cell (mockup `reccol`). */}
                      <DropdownMenuItem className="column-recheck" disabled={busy || Boolean(activeRun)} title={activeRun ? t('Available when the active run finishes') : t('Each row with stored text is read again for this column; every result waits as a proposal, and the model does not see the current values.')}
                        onClick={() => { void recheckColumn(col) }}><RotateCw size={15} aria-hidden /><span>{t('Recheck this column')}<small>{activeRun ? t('Available when the active run finishes') : t(rows.length === 1 ? '{n} row · 1–2 calls · {model}' : '{n} rows · 1–2 calls each · {model}', { n: rows.length, model })}</small></span></DropdownMenuItem>
                      <DropdownMenuItem variant="destructive" disabled={busy} onClick={() => setRemoving(col)}><Trash2 size={15} aria-hidden /><span>{t('Remove column')}</span></DropdownMenuItem>
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
                <span id={`evidence-instruction-${col.id}`} className="sr-only">{col.instruction}</span>
              </th> })}
              <th scope="col" className="th-add-cell"><button type="button" className="th-b th-add" disabled={busy} aria-label={t('Add column at the end')} onClick={() => setEditor({ mode: 'add' })}><Plus size={13} aria-hidden />{t('Add column')}</button></th>
            </tr></thead>
            <tbody>{rows.map((row, r) => {
              const source = sourceById.get(row.source_version_id)
              return <tr key={row.source_version_id}>
                <th scope="row" className="evidence-row-head">
                  <div className="evidence-row-line">
                    {source ? <button type="button" className="src-t evidence-row-title evidence-row-open" title={formatReferenceText(style, source)} onClick={() => setSourceTarget(row.source_version_id)}>
                        {row.source_key ? <span className="source-key">{row.source_key}</span> : row.title}</button>
                      : <span className="src-t evidence-row-title" title={row.title}>{row.source_key ? <span className="source-key">{row.source_key}</span> : row.title}</span>}
                    <DropdownMenu>
                      <DropdownMenuTrigger className="evidence-row-menu" disabled={busy} aria-label={t('Row actions for {title}', { title: row.title })}><Ellipsis size={15} /></DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-auto">
                        <DropdownMenuItem variant="destructive" onClick={() => act(() => api.removeTableRow(researchId, tableId, row.source_version_id, table.table.version), t('Row removed from the table. Its cells are kept and return if you add the source again.'),
                          { label: t('Undo'), run: () => { void act(() => api.addTableRows(researchId, tableId, [row.source_version_id], table.table.version + 1), t('Row restored with its cells.')) } })}><Trash2 size={15} />{t('Remove from table')}</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <span className="src-m evidence-row-meta">{[row.year, t(accessLabels[row.access_level]), versionText(row.version_label), row.selection_state && t(selectionLabels[row.selection_state])].filter(Boolean).join(' · ')}</span>
                </th>
                {columns.map((col, c) => {
                  const id = `${col.id}:${row.source_version_id}`
                  return <td key={col.id} role="gridcell" className={cellTarget?.columnId === col.id && cellTarget.sourceId === row.source_version_id ? 'is-open' : undefined}>
                    <CellButton column={col} row={row} summary={cells.get(id)} live={rechecking.has(id) ? 'recheck' : filling.has(id) && !cells.get(id)?.current ? 'fill' : null}
                      position={`${r}:${c}`} focusable={r === fr && c === fc} onFocus={() => setFocus([r, c])}
                      onOpen={() => setCellTarget({ columnId: col.id, sourceId: row.source_version_id })} />
                  </td>
                })}
                <td className="th-add-cell" aria-hidden />
              </tr>
            })}</tbody>
          </table>
        </div>
        <span id="evidence-grid-keys" className="sr-only">{t('Arrow keys move between cells; Enter opens one.')}</span>
      </>}
    <p className="foot-note evidence-footnote">{t('Click a cell to see its quote and earlier values. Whether a quote supports its value was not checked.')}</p>
    <p className="foot-note table-counts">{table.counts.rows * table.counts.columns > 0 && <progress className="evidence-meter" max={table.counts.rows * table.counts.columns} value={table.counts.with_value} aria-hidden />}{t('{rows} rows · {columns} columns · {filled} cells with a value · {empty} empty · {pending} proposals waiting', { rows: table.counts.rows, columns: table.counts.columns, filled: table.counts.with_value, empty: table.counts.empty, pending: table.counts.pending_proposals })}{table.removed_rows.length ? ` · ${t('{n} removed rows keep their cells', { n: table.removed_rows.length })}` : ''}</p>

    {editor && <ColumnEditor key={editor.mode === 'edit' ? editor.column.id : editor.mode} target={editor} busy={busy} dark={dark} locked={Boolean(activeRun)}
      onSave={spec => saveColumn(editor, spec)} onClose={() => setEditor(null)} onRemove={column => { setEditor(null); setRemoving(column) }} />}
    <ConfirmDialog open={Boolean(removing)} dark={dark} title={t('Remove column?')}
      description={t('The column leaves the table. Its cells and their history stay stored; Undo in the notification brings the column back with them.')}
      context={removing?.name} confirmLabel={t('Remove column')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={() => { const column = removing; setRemoving(null); if (column) void act(() => api.removeColumn(researchId, tableId, column.id, column.version), t('Column removed.'),
        { label: t('Undo'), run: () => { void act(() => api.restoreColumn(researchId, tableId, column.id, column.version + 1), t('Column restored with its cells.')) } }) }}
      onOpenChange={open => { if (!open) setRemoving(null) }} />
    <ConfirmDialog open={removingAll} dark={dark} title={t('Remove all columns?')}
      description={t('Every column leaves the table; the rows stay. Each column’s cells and history stay stored, and Undo in the notification brings back the columns that were removed.')}
      context={columns.map(c => c.name).join(' · ')} confirmLabel={t('Remove all columns')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={() => { setRemovingAll(false); void removeAllColumns() }} onOpenChange={open => { if (!open) setRemovingAll(false) }} />
    {sourceTarget && <PassageSheet researchId={researchId} passageId={null} sourceVersionId={sourceTarget} sources={view.sources} dark={dark} onClose={() => setSourceTarget(null)} />}
    {lineagePassage && <PassageSheet researchId={researchId} passageId={lineagePassage.passageId} assetId={lineagePassage.assetId} sourceVersionId={lineagePassage.sourceVersionId} highlightTexts={lineagePassage.highlightTexts}
      citationLabels={{ marked: t('Located text in the later work'), unmarked: t('The quoted text could not be marked on this page. Inspect the stored passage and PDF.'), mark: t('Located text in the later work') }}
      initialPage={lineagePassage.initialPage} expectHighlight={Boolean(lineagePassage.highlightTexts?.length)} sources={view.sources} dark={dark} onClose={() => setLineagePassage(null)} />}
    {/* Development lines (§2.2: from the ⋯ menu, in the panel): stacked on the table, Back returns to it. */}
    <StackPanel name="lineage" open={lineageOpen} onClose={() => setLineageOpen(false)} title={t('Development lines')} icon={Network} className="table-panel-box lineage-panel">
      <div className="table-panel lineage-panel-body">
        {runLine([])}
        <DevelopmentLines key={tableId} researchId={researchId} tableId={tableId} tableVersion={table.table.version} eventCursor={view.last_event_id}
          activeRun={activeRun} lineageRun={view.runs.find(r => r.kind === 'lineage_links' && r.target?.table_id === tableId)} sources={view.sources}
          model={model} connection={view.scope.model_connection} dark={dark} onColumnsAdded={() => { void load() }} onRunStarted={onRunStarted} onPassage={target => { void openLineagePassage(target) }} />
      </div>
    </StackPanel>
    {cellTarget && cellColumn && cellRow && <CellPanel key={`${cellColumn.id}:${cellRow.source_version_id}`} researchId={researchId} tableId={tableId} column={cellColumn} row={cellRow} refresh={view.last_event_id}
      source={view.sources.find(s => s.source_version_id === cellRow.source_version_id)} activeRun={activeRun} rechecking={rechecking.has(`${cellColumn.id}:${cellRow.source_version_id}`)}
      model={model} dark={dark} onChanged={() => { void load() }} onRunStarted={onRunStarted} onOpenSource={() => setSourceTarget(cellRow.source_version_id)} onClose={() => setCellTarget(null)} />}
  </div>
}

// What became of a cited passage's file (D45); the label names it in words, not only by color.
const evidenceStatusLabels = { pdf_removed: 'PDF removed', pdf_replaced: 'Previous PDF', text_superseded: 'Earlier text' } as const

// One cell (mockup `cellHtml`): the value with its provenance under it, a state in muted italics with what it means, or
// "Filling…" while a fill reads this cell. The flags that need attention follow as words.
function CellButton({ column, row, summary, live, position, focusable, onFocus, onOpen }: { column: TableColumn; row: TableRow; summary: CellSummary | undefined; live: 'fill' | 'recheck' | null; position: string; focusable: boolean; onFocus: () => void; onOpen: () => void }) {
  const current = summary?.current ?? null
  const flags = summary?.flags ?? []
  const pending = summary?.pending_proposal ?? null
  const text = current ? revisionText(column, current) : t('Empty')
  // Amber: something waits for attention (a proposal, a changed column, cited text no longer in use); red: a proposal that failed validation.
  const marks = [
    pending && !flags.includes('proposal_invalid') && { tone: 'attention', label: t('New proposal') },
    flags.includes('proposal_invalid') && { tone: 'blocking', label: t('Invalid proposal') },
    flags.includes('stale_column') && { tone: 'attention', label: t('Column changed') },
    ...(['pdf_removed', 'pdf_replaced', 'text_superseded'] as const).map(flag => flags.includes(flag) && { tone: 'attention', label: t(evidenceStatusLabels[flag]) }),
    flags.includes('ocr_numbers_unchecked') && { tone: 'attention', label: t('OCR number') },
  ].filter((m): m is { tone: string; label: string } => Boolean(m))
  const value = current && hasValue(current)
  // Under a value: who wrote it and what was read; a value without a linked passage says so in amber (mockup `noev`).
  const provenance = value ? (current.state === 'not_verified' ? t('No linked quote') : [t(authorLabels[current.author]), current.reading_depth && t(depthLabels[current.reading_depth])].filter(Boolean).join(' · '))
    : current?.state ? t(stateNotes[current.state]) : current ? '' : t('Empty')
  const liveText = live === 'recheck' ? t('Rechecking…') : live === 'fill' ? t('Filling…') : ''
  return <button type="button" className={`cell evidence-cell${current ? '' : ' is-empty'}${current && !value ? ' is-state' : ''}`} data-cell={position} tabIndex={focusable ? 0 : -1}
    aria-label={[`${column.name}, ${row.title}`, text, provenance !== text ? provenance : '', liveText, ...marks.map(m => m.label)].filter(Boolean).join('. ')} onFocus={onFocus} onClick={onOpen}>
    {live === 'fill' ? <span className="evidence-cell-live" aria-hidden><span className="spin" />{liveText}</span>
      : value ? <span className="evidence-cell-value" aria-hidden>{text}</span>
      : <span className="nrc evidence-cell-value" aria-hidden>{current ? text : '—'}</span>}
    {live !== 'fill' && <small className={value && current.state === 'not_verified' ? 'warn-t' : current?.state === 'unknown' ? 'warn-t' : undefined} aria-hidden>{provenance}</small>}
    {live === 'recheck' && <span className="evidence-cell-live" aria-hidden><span className="spin" />{liveText}</span>}
    {marks.length > 0 && <span className="evidence-cell-flags" aria-hidden>{marks.map(m => <span key={m.label} className={`evidence-flag is-${m.tone}`}>{m.label}</span>)}</span>}
  </button>
}

function AddRows({ sources, table, busy, onAdd, onClose }: { sources: Source[]; table: TableView; busy: boolean; onAdd: (ids: string[]) => void; onClose: () => void }) {
  const [chosen, setChosen] = useState<string[]>([])
  const inTable = new Set(table.rows.map(r => r.source_version_id))
  const candidates = sources.filter(s => !inTable.has(s.source_version_id)).sort((a, b) => selectionOrder[a.selection.state] - selectionOrder[b.selection.state])
  return <section className="evidence-add-rows" aria-labelledby="evidence-add-rows-title">
    <h3 id="evidence-add-rows-title">{t('Add rows')}</h3>
    <p>{t('A row is one source version of this research. Another version of the same work is a separate row, and evidence never moves between versions.')}</p>
    {candidates.length ? <ul>{candidates.map(s => <li key={s.source_version_id}><label>
      <input type="checkbox" checked={chosen.includes(s.source_version_id)} onChange={e => setChosen(e.target.checked ? [...chosen, s.source_version_id] : chosen.filter(id => id !== s.source_version_id))} />
      <span><strong>{s.title}</strong><small>{[s.source_key, versionText(s.version_label), t(selectionLabels[s.selection.state])].filter(Boolean).join(' · ')}</small></span>
    </label></li>)}</ul> : <p className="empty-inline">{t('Every source of this research is already a row.')}</p>}
    <div className="evidence-actions">
      <button type="button" className="btn-pri" disabled={busy || !chosen.length} onClick={() => onAdd(chosen)}>{t(chosen.length === 1 ? 'Add {n} row' : 'Add {n} rows', { n: chosen.length })}</button>
      <button type="button" className="ghost" onClick={onClose}>{t('Close')}</button>
    </div>
  </section>
}

// The column dialog (mockup `addColDlg`): a name, the instruction the model reads, a format, and the format's own
// controls (options, unit). A new column starts empty; Fill empty cells fills it and says its calls before it starts.
function ColumnEditor({ target, busy, dark, locked, onSave, onRemove, onClose }: { target: EditorTarget; busy: boolean; dark: boolean; locked: boolean; onSave: (spec: ColumnSpec) => void; onRemove: (column: TableColumn) => void; onClose: () => void }) {
  const initial = target.mode === 'edit' ? target.column : target.mode === 'suggestion' ? target.suggestion : null
  const [name, setName] = useState(initial?.name ?? '')
  const [instruction, setInstruction] = useState(initial?.instruction ?? '')
  const [format, setFormat] = useState<AnswerFormat>(initial?.answer_format ?? 'text')
  const [options, setOptions] = useState<{ id?: string | null; label: string }[]>(initial?.options?.map(o => ({ ...o })) ?? [{ label: '' }, { label: '' }])
  const [multiple, setMultiple] = useState(initial?.allow_multiple ?? false)
  const [unit, setUnit] = useState(initial?.unit_hint ?? '')
  const [problem, setProblem] = useState('')
  const lineage = target.mode === 'edit' && Boolean(target.column.lineage_role)
  const submit = () => {
    const labels = options.map(o => o.label.trim()).filter(Boolean)
    if (!name.trim() || !instruction.trim()) return setProblem(t('A column needs a name and an instruction.'))
    if (format === 'choice' && (labels.length < 2 || new Set(labels.map(l => l.toLocaleLowerCase())).size !== labels.length)) return setProblem(t('An options column needs at least two distinct options.'))
    setProblem('')
    onSave({ name: name.trim(), instruction: instruction.trim(), answer_format: format, allow_multiple: format === 'choice' && multiple, unit_hint: format === 'number_unit' ? unit.trim() || null : null,
      options: format === 'choice' ? options.filter(o => o.label.trim()).map(o => (o.id ? { id: o.id, label: o.label.trim() } : { label: o.label.trim() })) : null })
  }
  const title = t(target.mode === 'edit' ? 'Edit column' : 'Add column')
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}>
    <DialogContent className={`column-dialog${dark ? ' dark' : ''}`} icon={<Table2 size={16} aria-hidden />} title={title}>
      <form className="column-dialog-form" onSubmit={e => { e.preventDefault(); submit() }}>
        <DialogBody>
          {target.mode === 'suggestion' && <p className="foot-note">{t('From a model suggestion. It joins the table only when you save it.')}</p>}
          <label className="lbl">{t('Name')}<input className="field" value={name} maxLength={80} autoFocus placeholder={t('e.g. Simulation tool')} onChange={e => setName(e.target.value)} /></label>
          <label className="lbl">{t('What should the model look for?')}
            <textarea className="field" value={instruction} maxLength={2000} rows={2} placeholder={t('One sentence. The model reads this as its instruction.')} onChange={e => setInstruction(e.target.value)} /></label>
          <fieldset className="lbl column-formats" disabled={lineage}><legend>{t('Format')}</legend>
            <div className="fmts">{(Object.keys(formatLabels) as AnswerFormat[]).map(f => { const Icon = formatIcons[f]; return <label key={f}>
              <input type="radio" name="answer-format" value={f} checked={format === f} onChange={() => setFormat(f)} /><Icon size={15} aria-hidden />{t(formatLabels[f])}
            </label> })}</div>
            {lineage && <small>{t('This column feeds the development lines and stays a text column.')}</small>}
          </fieldset>
          {format === 'choice' && <fieldset className="lbl column-options"><legend>{t('Options')}</legend>
            {options.map((option, i) => <div className="evidence-option" key={option.id ?? `new-${i}`}>
              <input className="field" aria-label={t('Option {n}', { n: i + 1 })} value={option.label} maxLength={120} onChange={e => setOptions(options.map((o, j) => (j === i ? { ...o, label: e.target.value } : o)))} />
              <button type="button" className="ib" aria-label={t('Remove option {n}', { n: i + 1 })} disabled={options.length <= 2} onClick={() => setOptions(options.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden /></button>
            </div>)}
            <span className="evidence-actions">
              <button type="button" className="ghost" disabled={options.length >= 20} onClick={() => setOptions([...options, { label: '' }])}><Plus size={14} aria-hidden />{t('Add option')}</button>
              <label className="evidence-check"><input type="checkbox" checked={multiple} onChange={e => setMultiple(e.target.checked)} /><span>{t('A source may have several options')}</span></label>
            </span>
          </fieldset>}
          {format === 'number_unit' && <label className="lbl">{t('Expected unit (optional)')}<input className="field" value={unit} maxLength={40} onChange={e => setUnit(e.target.value)} />
            <small>{t('Nothing is converted; a value keeps the unit its source states.')}</small></label>}
          {target.mode === 'edit' && <p className="evidence-flag-note"><TriangleAlert size={14} aria-hidden /><span>{t('A changed definition becomes a new column revision. Values made under the earlier definition stay and are marked “Column changed”.')}</span></p>}
          {problem && <p className="evidence-flag-note is-blocking" role="alert"><TriangleAlert size={14} aria-hidden /><span>{problem}</span></p>}
          {target.mode !== 'edit' && <p className="foot-note">{t(locked ? 'A run is in progress, so the column stays empty until you fill it.' : 'The column starts empty. Fill empty cells reads the text DEIXIS has for each source and shows its calls before it starts.')}</p>}
        </DialogBody>
        <DialogFooter>
          {target.mode === 'edit' && <button type="button" className="ghost column-remove" disabled={busy} onClick={() => onRemove(target.column)}><Trash2 size={14} aria-hidden />{t('Remove column')}</button>}
          <button type="button" className="ghost" disabled={busy} onClick={onClose}>{t('Cancel')}</button>
          <button type="submit" className="btn-pri" disabled={busy}>{t(target.mode === 'edit' ? 'Save column' : 'Add column')}</button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}

type Draft = { state: Exclude<CellState, 'not_verified'>; options: string[]; number: string; unit: string; asStated: string; answer: 'yes' | 'no' | ''; text: string; note: string; keepEvidence: boolean }

function draftFrom(column: TableColumn, rev: CellRevision | null): Draft {
  const value = rev?.value
  return { state: rev?.state && rev.state !== 'not_verified' ? rev.state : 'value', options: value?.option_ids ?? [], number: typeof value?.number === 'number' ? String(value.number) : '',
    unit: value?.unit ?? column.unit_hint ?? '', asStated: value?.as_stated ?? '', answer: value?.answer ?? '', text: value?.text ?? '',
    note: rev?.author === 'human' ? rev.note ?? '' : '', keepEvidence: Boolean(rev?.evidence.length) }
}

// The request body for a draft, or the reason it cannot be sent. A value keeps linked evidence only from the revision it corrects.
function editBody(column: TableColumn, draft: Draft, current: CellRevision | null, version: number): CellEdit | string {
  const note = draft.note.trim() || null
  if (draft.state !== 'value') return { state: draft.state, value: null, note, keep_evidence_from: null, expected_version: version }
  let value: CellValue
  if (column.answer_format === 'choice') {
    if (!draft.options.length) return t('Choose at least one option.')
    value = { option_ids: draft.options }
  } else if (column.answer_format === 'number_unit') {
    const number = Number(draft.number)
    if (!draft.number.trim() || !Number.isFinite(number)) return t('Enter a number.')
    value = { number, unit: draft.unit.trim() || null, as_stated: draft.asStated.trim() || null }
  } else if (column.answer_format === 'yes_no') {
    if (!draft.answer) return t('Choose yes or no.')
    value = { answer: draft.answer }
  } else {
    if (!draft.text.trim()) return t('Enter the value.')
    value = { text: draft.text.trim() }
  }
  const keep = draft.keepEvidence && current?.evidence.length ? current.id : null
  return { state: keep ? 'value' : 'not_verified', value, note, keep_evidence_from: keep, expected_version: version }
}

// What the passage section says for a cell without a value (mockup `pass`), from the stored state.
const passageNotes: Partial<Record<CellState, string>> = {
  unknown: 'The passage does not settle this column clearly.', not_found_in_inspected_scope: 'The passages read do not address this column.',
  not_applicable: 'This column does not apply to this work.', inaccessible: 'DEIXIS has no abstract or full text for this work.',
  not_reported: 'A person recorded that the source does not report this.',
}

// The cell panel (mockup `cellPanel`), stacked on the table: Back returns to it. The current value and what it rests
// on, the recheck and the edit, a pending proposal kept apart from the value, then the source, the passage, the column
// instruction and the cell's history.
function CellPanel({ researchId, tableId, column, row, refresh, source, activeRun, rechecking, model, dark, onChanged, onRunStarted, onOpenSource, onClose }: {
  researchId: string; tableId: string; column: TableColumn; row: TableRow; refresh: number; source: Source | undefined; activeRun: Run | null; rechecking: boolean
  model: string; dark: boolean; onChanged: () => void; onRunStarted: () => void; onOpenSource: () => void; onClose: () => void
}) {
  const toast = useToast()
  const modelText = useModelText()
  const [cell, setCell] = useState<CellView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  // The cell version the open edit was started from: a newer write from another tab, which reloads the cell under the
  // form, is refused with 409 instead of being overwritten silently. After a refusal the draft rests on the version shown.
  const [draftBase, setDraftBase] = useState<number | null>(null)
  const [problem, setProblem] = useState('')
  const [evidence, setEvidence] = useState<CellEvidence[] | null>(null)
  const sv = row.source_version_id

  const load = useCallback(() => api.cell(researchId, tableId, column.id, sv).then(c => { setCell(c); setError(''); return c }, e => { setError(errorText(e)); return null }), [researchId, tableId, column.id, sv])
  useEffect(() => {
    let live = true
    api.cell(researchId, tableId, column.id, sv).then(c => { if (live) { setCell(c); setError('') } }, e => { if (live) setError(errorText(e)) })
    return () => { live = false }
  }, [researchId, tableId, column.id, sv, refresh])

  // A refused write reloads the cell and keeps what the user typed, so nothing written is lost to a newer version.
  async function mutate(action: () => Promise<unknown>, success: string, after?: () => void) {
    setBusy(true)
    try { await action(); toast('success', success); after?.(); await load(); onChanged() }
    catch (e) {
      if (conflict(e)) {
        toast('warning', t(draft ? 'Not applied: {message}. The cell now shows the latest state; your draft is kept.' : 'Not applied: {message}. The page now shows the latest state.', { message: errorText(e) }))
        const fresh = await load()
        if (draft && fresh) setDraftBase(fresh.version)
        onChanged()
      }
      else toast('error', errorText(e))
    } finally { setBusy(false) }
  }

  // An upper bound: a short source is read whole, a longer one gives at most 16 passages (D38). One passage per extracted page.
  const available = source ? (source.access.abstract_passage_id ? 1 : 0) + source.access.assets.reduce((n, a) => n + (a.page_count ?? 0), 0) : 0
  const recheckPassages = available <= MAX_WHOLE_PASSAGES ? available : MAX_RECHECK_PASSAGES
  const current = cell?.current ?? null
  const pending = cell?.pending_proposal ?? null
  const flags = cell?.flags ?? []
  const showEvidence = (items: CellEvidence[]) => setEvidence(items)
  const save = () => {
    if (!cell || !draft) return
    const body = editBody(column, draft, current, draftBase ?? cell.version)
    if (typeof body === 'string') return setProblem(body)
    setProblem('')
    void mutate(() => api.editCell(researchId, tableId, column.id, sv, body, newKey()), t('Value saved.'), () => setDraft(null))
  }

  const quoteCount = (items: CellEvidence[]) => items.filter(item => item.anchor_text).length
  const limited = current?.reading_depth === 'abstract' || current?.reading_depth === 'metadata'
  const flag = (text: string, blocking = false) => <p className={`evidence-flag-note${blocking ? ' is-blocking' : ''}`}><TriangleAlert size={14} aria-hidden /><span>{text}</span></p>
  const FormatIcon = formatIcons[column.answer_format]
  const value = current && hasValue(current)
  const recheckLocked = busy || Boolean(activeRun) || !available || !cell
  const title = `${shortName(row)} · ${column.name}`
  return <StackPanel name="cell" open onClose={onClose} title={title} icon={Table2} className={`table-panel-box cell-panel${dark ? ' dark' : ''}`}>
    <div className="pad detail cell-detail">
      {error && <p className="evidence-flag-note is-blocking" role="alert"><TriangleAlert size={14} aria-hidden /><span>{error}</span></p>}
      {!cell && !error && <p role="status" className="foot-note">{t('Loading cell…')}</p>}
      {cell && <>
        <div className="dhead">
          <div className="venue"><FormatIcon size={16} aria-hidden />{column.name} · {t(formatLabels[column.answer_format])}</div>
          <h1 className={`evidence-current${value ? '' : ' is-state'}`}>{current ? revisionText(column, current) : t('Empty: no value recorded yet.')}</h1>
          {current?.value?.as_stated && <p className="foot-note">{t('As written in the source: {text}', { text: current.value.as_stated })}</p>}
        </div>
        {value && current.evidence.length > 0 && <p className="cell-chips">
          <span className="cell-chip is-ok">{t(quoteCount(current.evidence) === 1 ? '{n} quote found in the source' : '{n} quotes found in the source', { n: quoteCount(current.evidence) })}</span>
          <span className="cell-chip is-warn">{t('Semantic support not checked')}</span>
        </p>}
        {current && <p className="dmeta">
          <span className={current.state === 'not_verified' || current.state === 'unknown' ? 'warn-t' : undefined}>{current.state ? t(stateLabels[current.state]) : ''}</span>
          <span>{t(authorLabels[current.author])}{current.reading_depth ? ` · ${t(depthLabels[current.reading_depth])}` : ''}</span>
          {current.model?.connection && current.model.resolved_model && <span><ModelName connection={current.model.connection} text={modelText(current.model.resolved_model)} /></span>}
          <span>{dateText(current.created_at)}</span>
        </p>}
        {!draft && <div className="dacts">
          <button type="button" className={`btn-pri${rechecking ? ' is-working' : ''}`} disabled={recheckLocked} onClick={() => mutate(() => api.recheckCell(researchId, tableId, column.id, sv, cell.version, newKey()), t('Recheck started. Its result will wait as a proposal.'), onRunStarted)}>{rechecking ? <><span className="spin" aria-hidden />{t('Rechecking…')}</> : <><RotateCw size={14} aria-hidden />{t('Recheck this cell')}</>}</button>
          <button type="button" className="ghost" disabled={busy} onClick={() => { setProblem(''); setDraft(draftFrom(column, current)); setDraftBase(cell?.version ?? null) }}><PencilLine size={14} aria-hidden />{t('Edit value')}</button>
          {source && <button type="button" className="ib" aria-label={t('Open the source')} title={t('Open the source')} onClick={onOpenSource}><FileText size={16} aria-hidden /></button>}
        </div>}
        {!draft && !rechecking && <p className="foot-note cell-scope">{!available ? t('This source has no stored text, so a recheck has nothing to read.')
          : activeRun ? t('Another run is active; a recheck can start when it finishes.')
          : t(recheckPassages === 1 ? 'Only {source} · up to {n} passage · {model} · 1–2 calls. The result waits as a proposal; the model does not see the current value.' : 'Only {source} · up to {n} passages · {model} · 1–2 calls. The result waits as a proposal; the model does not see the current value.', { source: row.source_key || row.title, n: recheckPassages, model })}</p>}
        {activeRun && !rechecking && <div className="notice warn"><Pause size={15} aria-hidden /><span>{t('Model actions are locked while a run is in progress. Recheck becomes available when it finishes.')}</span></div>}
        {limited && value && <p className="cell-limit"><TriangleAlert size={14} aria-hidden /><span><strong>{t(current.reading_depth === 'abstract' ? 'Read from the abstract only.' : 'Read from the metadata only.')}</strong> {t('The full text of this source was not read.')}</span></p>}
        {current?.note && <p className="evidence-note"><span>{t(current.author === 'human' ? 'Your note' : 'Model note')}</span>{current.note}</p>}
        {flags.includes('stale_column') && current && flag(t('Made under an earlier definition of this column (revision {old}). It stays until you edit it or use a newer proposal.', { old: current.column_revision }))}
        {flags.includes('pdf_removed') && flag(t('A PDF this value cites was removed from the source. The cited passages still open as text; the PDF view is off.'))}
        {flags.includes('pdf_replaced') && flag(t('This value cites a PDF that was later replaced. Its evidence still opens the previous file; a recheck reads the current file.'))}
        {flags.includes('ocr_numbers_unchecked') && current && flag(t('This value states a number or equation read only from OCR text of a scanned page. It was not checked against the page; open the evidence and compare it with the PDF.'))}
        {flags.includes('text_superseded') && flag(t('This value cites an earlier text extraction of the PDF. Its evidence still opens that text; a recheck reads the current extraction.'))}

        {rechecking && !pending && <section className="evidence-block cell-waiting" aria-labelledby="evidence-slot-title">
          <h4 className="sub" id="evidence-slot-title">{t('Pending proposal')}<span className="cell-live" role="status"><span className="cell-pulse" aria-hidden />{t('Rechecking this cell…')}</span></h4>
          <div className="cell-slot" aria-hidden><i /><i /><i /></div>
          <p className="foot-note">{t('The result will appear here as a proposal; the current value does not change.')}</p>
        </section>}

        {pending && <section className={`evidence-block evidence-proposal${flags.includes('proposal_invalid') ? ' is-invalid' : ''}`} aria-labelledby="evidence-proposal-title">
          <h4 className="sub" id="evidence-proposal-title">{t('Pending proposal')}</h4>
          <div className="evidence-compare">
            <div><span>{t('Current')}</span><strong>{current ? revisionText(column, current) : t('Empty')}</strong><small>{current ? t(authorLabels[current.author]) : ''}</small></div>
            <div><span>{t('Proposal')}</span><strong>{revisionText(column, pending)}</strong><small>{revisionMeta(pending, modelText)}</small></div>
          </div>
          {flags.includes('proposal_before_edit') && flag(t('Requested before the cell last changed. Compare it with the current value before using it.'))}
          {flags.includes('ocr_numbers_unchecked') && !current && flag(t('This value states a number or equation read only from OCR text of a scanned page. It was not checked against the page; open the evidence and compare it with the PDF.'))}
          {flags.includes('proposal_invalid') && flag(t('This proposal failed validation after one repair. It is kept for the record and cannot be used.'), true)}
          {pending.note && <p className="evidence-note"><span>{t('Model note')}</span>{pending.note}</p>}
          {pending.evidence.length > 0 && <EvidenceList items={pending.evidence} onShow={showEvidence} />}
          <div className="evidence-actions">
            <button type="button" className="btn-pri" disabled={busy || flags.includes('proposal_invalid')} onClick={() => mutate(() => api.decideProposal(researchId, tableId, column.id, sv, pending.id, 'accept', cell.version, newKey()), t('The proposal’s value and evidence are now the cell’s value, recorded as your decision.'))}>{t('Use this value')}</button>
            <button type="button" className="ghost" disabled={busy} onClick={() => mutate(() => api.decideProposal(researchId, tableId, column.id, sv, pending.id, 'dismiss', cell.version, newKey()), t('Current value kept; the proposal stays in the history.'))}>{t('Keep current')}</button>
          </div>
          <p className="foot-note">{t('Using a proposal records its value as your decision. It does not mean its support was checked.')}</p>
        </section>}

        {draft && <section className="evidence-block" aria-labelledby="evidence-edit-title">
          <form className="evidence-form" aria-labelledby="evidence-edit-title" onSubmit={e => { e.preventDefault(); save() }}>
            <h4 className="sub" id="evidence-edit-title">{t('Edit value')}</h4>
            <label className="evidence-field"><span>{t('State')}</span>
              <select value={draft.state} onChange={e => setDraft({ ...draft, state: e.target.value as Draft['state'] })}>{editableStates.map(s => <option key={s} value={s}>{t(stateLabels[s])}</option>)}</select>
            </label>
            {draft.state === 'value' && <ValueInputs column={column} draft={draft} onChange={setDraft} />}
            {draft.state === 'value' && current && current.evidence.length > 0 && <label className="evidence-check">
              <input type="checkbox" checked={draft.keepEvidence} onChange={e => setDraft({ ...draft, keepEvidence: e.target.checked })} />
              <span>{t('Keep the evidence of the current value')}<small>{t('For a corrected unit or spelling. Without it the value is saved without linked evidence.')}</small></span>
            </label>}
            <label className="evidence-field"><span>{t('Note (optional)')}</span><textarea value={draft.note} maxLength={2000} rows={2} onChange={e => setDraft({ ...draft, note: e.target.value })} /></label>
            {problem && <p className="evidence-flag-note is-blocking" role="alert"><TriangleAlert size={14} aria-hidden /><span>{problem}</span></p>}
            <div className="evidence-actions">
              <button type="submit" className="btn-pri" disabled={busy}>{t('Save value')}</button>
              <button type="button" className="ghost" disabled={busy} onClick={() => setDraft(null)}>{t('Cancel')}</button>
            </div>
          </form>
        </section>}

        <h4 className="sub" id="evidence-quotes-title">{t('Evidence')}{current && current.evidence.length > 0 && <small>{t(quoteCount(current.evidence) === 1 ? '{n} quote' : '{n} quotes', { n: quoteCount(current.evidence) })}</small>}</h4>
        <div className="cell-source">{source ? <button type="button" className="src-t" onClick={onOpenSource}>{row.title}</button> : <span className="src-t">{row.title}</span>}
          <div className="src-m">{[row.source_key, row.year, versionText(row.version_label), t(accessLabels[row.access_level])].filter(Boolean).join(' · ')}</div></div>

        <div>
          {current && current.evidence.length > 0 && <EvidenceList items={current.evidence} onShow={showEvidence} />}
          {!current ? null
            : value && !current.evidence.length ? <div className="notice warn"><TriangleAlert size={15} aria-hidden /><span>{t('No linked evidence: this value was recorded without a passage. Recheck it, or treat it as unsupported.')}</span></div>
            : !value && current.state && passageNotes[current.state] ? <p className="foot-note">{t(passageNotes[current.state]!)}</p> : null}
        </div>

        <details className="cell-fold"><summary>{t('Column instruction')}</summary>
          <p className="foot-note cell-instruction">{column.instruction}</p>
        </details>

        <details className="cell-fold"><summary>{t('History ({n})', { n: cell.revisions.length })}</summary>
        {cell.revisions.length ? <ol className="hist evidence-history">{cell.revisions.slice().reverse().map(rev => <li key={rev.id}>
          <strong>{t(kindLabels[rev.kind])}{rev.decision ? ` · ${t(decisionLabels[rev.decision])}` : ''}{rev.output_status === 'unverified_draft' ? ` · ${t('failed validation')}` : ''}{rev.id === current?.id ? ` · ${t('current value')}` : ''}</strong>
          {rev.state && <span className="evidence-history-value">{revisionText(column, rev)}</span>}
          <small>{revisionMeta(rev, modelText)}</small>
          {rev.id !== current?.id && rev.note && <small>{rev.note}</small>}
          {rev.id !== current?.id && rev.evidence.length > 0 && <EvidenceList items={rev.evidence} onShow={showEvidence} />}
        </li>)}</ol> : <p className="foot-note">{t('None. Nothing has been recorded for this cell yet.')}</p>}
        </details>

        {current && <details className="cell-fold"><summary>{t('Details')}</summary>
          <dl className="cell-details">
            {current.model?.resolved_model && <><dt>{t('Model')}</dt><dd><code>{current.model.resolved_model}</code></dd></>}
            <dt>{t('Column definition')}</dt><dd>{t('revision {n}', { n: current.column_revision })}</dd>
            {current.reading_depth && <><dt>{t('Read from')}</dt><dd>{t(depthLabels[current.reading_depth])}</dd></>}
            {current.run_id && <><dt>{t('Run')}</dt><dd><code>{current.run_id}</code></dd></>}
          </dl>
          <p className="foot-note cell-support"><Info size={13} aria-hidden />{t('Semantic support not checked. DEIXIS located each quote in a passage of this source version; it did not check that the passage supports the value.')}</p>
        </details>}
      </>}
    </div>
    {evidence && <PassageSheet researchId={researchId} passageId={evidence[0].passage_id} highlightTexts={evidence.flatMap(e => e.anchor_text ? [e.anchor_text] : [])} expectHighlight pdfRemoved={evidence[0].evidence_status === 'pdf_removed'} sources={source ? [source] : undefined} dark={dark} onClose={() => setEvidence(null)} />}
  </StackPanel>
}

// One entry per passage: a revision can quote several spans of the same passage (D43), and the passage opens with all of them marked.
// Quotes read as quotations (mockup `.quote`); the locator and a quiet link to the source sit under them (`.loc`).
function EvidenceList({ items, onShow }: { items: CellEvidence[]; onShow: (items: CellEvidence[]) => void }) {
  const groups: CellEvidence[][] = []
  for (const item of items) {
    const group = groups.find(g => g[0].passage_id === item.passage_id)
    if (group) group.push(item)
    else groups.push([item])
  }
  return <ul className="evidence-list">{groups.map(group => {
    const first = group[0]
    const quotes = group.flatMap(item => item.anchor_text ? [item.anchor_text] : [])
    return <li key={first.passage_id}>
      {quotes.length ? <blockquote className="quote evidence-quotes">{quotes.map((quote, i) => <p key={i} className="evidence-quote"><mark>{quote}</mark>{/[.!?…:;)\]"”’]$/.test(quote.trim()) ? '' : '…'}</p>)}</blockquote>
        : <span className="foot-note">{t('No located quote for this passage.')}</span>}
      <span className="loc evidence-locator">{first.kind === 'abstract' ? <BookOpenText size={13} aria-hidden /> : <FileText size={13} aria-hidden />}{locatorText(first)}{first.evidence_status !== 'current' && <><TriangleAlert size={12} aria-hidden />{t(evidenceStatusLabels[first.evidence_status])}</>}{first.text_source === 'ocr' && <span className="evidence-ocr">{t(OCR_LABEL)}</span>}
        <button type="button" className="evidence-open" onClick={() => onShow(group)}>{t('Open in source')}<ArrowUpRight size={13} aria-hidden /></button></span>
    </li>
  })}</ul>
}

function ValueInputs({ column, draft, onChange }: { column: TableColumn; draft: Draft; onChange: (draft: Draft) => void }) {
  if (column.answer_format === 'choice') {
    return <fieldset className="evidence-field"><legend>{column.allow_multiple ? t('Options (one or more)') : t('Option')}</legend>
      {(column.options ?? []).map(option => <label key={option.id} className="evidence-check">
        <input type={column.allow_multiple ? 'checkbox' : 'radio'} name="cell-option" checked={draft.options.includes(option.id)}
          onChange={e => onChange({ ...draft, options: column.allow_multiple ? (e.target.checked ? [...draft.options, option.id] : draft.options.filter(id => id !== option.id)) : [option.id] })} />
        <span>{option.label}</span>
      </label>)}
    </fieldset>
  }
  if (column.answer_format === 'number_unit') {
    return <div className="evidence-number">
      <label className="evidence-field"><span>{t('Number')}</span><input type="number" step="any" inputMode="decimal" value={draft.number} onChange={e => onChange({ ...draft, number: e.target.value })} /></label>
      <label className="evidence-field"><span>{t('Unit')}</span><input value={draft.unit} maxLength={40} placeholder={column.unit_hint ?? ''} onChange={e => onChange({ ...draft, unit: e.target.value })} /></label>
      <label className="evidence-field is-wide"><span>{t('As written in the source (optional)')}</span><input value={draft.asStated} maxLength={200} onChange={e => onChange({ ...draft, asStated: e.target.value })} /></label>
    </div>
  }
  if (column.answer_format === 'yes_no') {
    return <fieldset className="evidence-field"><legend>{t('Answer')}</legend><div className="evidence-segments">
      {(['yes', 'no'] as const).map(answer => <label key={answer} className={draft.answer === answer ? 'is-selected' : undefined}>
        <input type="radio" name="cell-answer" checked={draft.answer === answer} onChange={() => onChange({ ...draft, answer })} />{t(answer === 'yes' ? 'Yes' : 'No')}
      </label>)}
    </div></fieldset>
  }
  return <label className="evidence-field"><span>{t('Value')}</span><small>{t('{n}/500 characters', { n: draft.text.length })}</small>
    <textarea value={draft.text} maxLength={500} rows={3} onChange={e => onChange({ ...draft, text: e.target.value })} /></label>
}
