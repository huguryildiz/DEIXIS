import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { BookOpenText, Ellipsis, FileText, LayoutTemplate, ListPlus, PencilLine, Plus, RotateCw, Save, Sparkles, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, ApiError, type AnswerFormat, type CellEdit, type CellEvidence, type CellRevision, type CellState, type CellSummary, type CellValue, type CellView, type ColumnSpec, type ColumnSuggestion, type ResearchView, type Run, type Source, type TableColumn, type TableRow, type TableSummary, type TableTemplate, type TableView } from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { PassageSheet } from './PassageSheet'
import { locatorText, versionText } from './labels'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'
import './EvidenceTable.css'

// The Evidence tab (P5 slice 1, D37/D38): a table whose rows are source versions and whose cells are append-only
// revisions. The screen renders the recorded cell state; only the user's edit or decision changes a cell's value.

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const MAX_WHOLE_PASSAGES = 48  // a source within this many passages (and 60,000 characters) is read whole
const MAX_RECHECK_PASSAGES = 16
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const newKey = () => crypto.randomUUID()
const conflict = (e: unknown) => e instanceof ApiError && e.status === 409

const formatLabels: Record<AnswerFormat, string> = { choice: 'Options', number_unit: 'Number and unit', yes_no: 'Yes–No', text: 'Short text' }
// Empty states read as words, never as colour alone.
const stateLabels: Record<CellState, string> = {
  value: 'Value', not_verified: 'Value without linked evidence', unknown: 'Unclear in the source', not_reported: 'Not reported',
  not_applicable: 'Not applicable', inaccessible: 'No text', not_found_in_inspected_scope: 'Not found in the text read',
}
const editableStates: Exclude<CellState, 'not_verified'>[] = ['value', 'unknown', 'not_reported', 'not_applicable', 'not_found_in_inspected_scope', 'inaccessible']
const authorLabels: Record<CellRevision['author'], string> = { model: 'Model', human: 'You', system: 'System' }
const depthLabels: Record<NonNullable<CellRevision['reading_depth']>, string> = { metadata: 'Metadata', abstract: 'Abstract', selected_sections: 'Selected pages', full_text: 'Full text' }
const kindLabels: Record<CellRevision['kind'], string> = {
  model_fill: 'Model filled the empty cell', model_proposal: 'Model proposal', system_fill: 'No stored text; recorded without a model call',
  human_edit: 'Your edit', accept_proposal: 'You used a proposal', dismiss_proposal: 'You kept the current value',
}
const decisionLabels: Record<NonNullable<CellRevision['decision']>, string> = { accepted: 'used', dismissed: 'not used', pending: 'waiting for your decision', superseded: 'replaced by a newer proposal' }
const accessLabels: Record<TableRow['access_level'], string> = { pdf_available: 'PDF text', abstract: 'Abstract only', metadata: 'Metadata only' }
const selectionLabels: Record<string, string> = { included: 'Included in Sources', pending: 'Undecided in Sources', excluded: 'Excluded in Sources' }
const selectionOrder: Record<string, number> = { included: 0, pending: 1, excluded: 2 }

// A short author–year key such as "Gur23", as in the answer's PDF suggestions.
function sourceKey(authors: string[], title: string, year: number | null) {
  const author = authors[0]?.trim()
  const name = author ? (author.includes(',') ? author.split(',')[0] : author.split(/\s+/).pop() ?? '') : title
  const stem = name.replace(/ı/g, 'i').normalize('NFD').replace(/[^A-Za-z]/g, '').slice(0, 3)
  return stem ? `${stem.charAt(0).toUpperCase()}${stem.slice(1).toLowerCase()}${year ? String(year).slice(-2) : ''}` : ''
}

function formatText(column: Pick<ColumnSpec, 'answer_format' | 'unit_hint' | 'allow_multiple'> & { options: unknown[] | null }) {
  const parts = [t(formatLabels[column.answer_format])]
  if (column.answer_format === 'number_unit' && column.unit_hint) parts.push(column.unit_hint)
  if (column.answer_format === 'choice') parts.push(t(column.allow_multiple ? '{n} options, several allowed' : '{n} options, one allowed', { n: column.options?.length ?? 0 }))
  return parts.join(' · ')
}

// A value keeps the shape of the column revision it was made under, so it is read from its own keys.
function valueText(column: TableColumn, value: CellValue | null) {
  if (!value) return ''
  if (value.option_ids) return value.option_ids.map(id => column.options?.find(o => o.id === id)?.label ?? id).join(', ')
  if (typeof value.number === 'number') return [value.number.toLocaleString(uiLocale(), { maximumFractionDigits: 12 }), value.unit].filter(Boolean).join(' ')
  if (value.answer) return t(value.answer === 'yes' ? 'Yes' : 'No')
  return value.text ?? ''
}
const hasValue = (rev: CellRevision) => rev.state === 'value' || rev.state === 'not_verified'
const revisionText = (column: TableColumn, rev: CellRevision) => (hasValue(rev) ? valueText(column, rev.value) : rev.state ? t(stateLabels[rev.state]) : '')
const dateText = (value: string) => new Date(value).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })

function revisionMeta(rev: CellRevision) {
  const model = rev.model ? rev.model.resolved_model ?? rev.model.connection : null
  return [model ? `${t(authorLabels[rev.author])} · ${model}` : t(authorLabels[rev.author]), dateText(rev.created_at),
    t('column definition {n}', { n: rev.column_revision }), rev.reading_depth && t('read from: {depth}', { depth: t(depthLabels[rev.reading_depth]) }),
    rev.run_id && t('run {id}', { id: rev.run_id })].filter(Boolean).join(' · ')
}

type EditorTarget = { mode: 'add' } | { mode: 'edit'; column: TableColumn } | { mode: 'suggestion'; suggestion: ColumnSuggestion; stepId: string }
type ModelText = (model: string | null, effort: string | null) => string

export function EvidenceTab({ researchId, view, dark, modelText, onRunStarted }: { researchId: string; view: ResearchView; dark: boolean; modelText: ModelText; onRunStarted: () => void }) {
  const toast = useToast()
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const [table, setTable] = useState<TableView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [templates, setTemplates] = useState<TableTemplate[] | null>(null)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [editor, setEditor] = useState<EditorTarget | null>(null)
  const [removing, setRemoving] = useState<TableColumn | null>(null)
  const [cellTarget, setCellTarget] = useState<{ columnId: string; sourceId: string } | null>(null)
  const [addRowsOpen, setAddRowsOpen] = useState(false)
  const [templateName, setTemplateName] = useState<string | null>(null)
  const [discarded, setDiscarded] = useState<string[]>([])
  const [hint, setHint] = useState<string | null>(null)
  const [focus, setFocus] = useState<[number, number]>([0, 0])
  const grid = useRef<HTMLTableElement>(null)

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

  async function act(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    try { await action(); if (success) toast('success', success); await load() }
    catch (e) {
      // 409: the table, column or run state changed after this screen loaded (another tab, or a run that moved on).
      if (conflict(e)) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: errorText(e) })); await load() }
      else toast('error', errorText(e))
    } finally { setBusy(false) }
  }

  const run = view.runs[0] as Run | undefined
  const activeRun = run && ACTIVE.has(run.status) ? run : null
  const model = modelText(view.scope.requested_model, view.scope.reasoning_effort)
  const createTable = (templateId?: string) => api.createTable(researchId, { title: t('Evidence table'), ...(templateId ? { template_id: templateId } : {}) }, newKey())
  const openTemplates = () => {
    setTemplatesOpen(open => !open)
    api.tableTemplates().then(setTemplates).catch(e => toast('error', errorText(e)))
  }

  if (error && !tables) return <div className="legacy-boundary">{t('Could not load the evidence table: {error}', { error })}</div>
  if (!tables) return <p className="empty-inline">{t('Loading the evidence table…')}</p>

  const intro = t('Rows are source versions of this research; each cell links to passages of its own row’s version. A model fills only empty cells; anything else it returns waits for your decision.')
  if (!table) return <section className="evidence-panel" aria-labelledby="evidence-heading">
    <div className="workspace-pane-head"><div><h2 id="evidence-heading">{t('Evidence table')}</h2><p>{intro}</p></div></div>
    <div className="evidence-empty">
      <p>{t('No table yet.')} {t(view.counts.included === 1 ? 'It starts with the {n} included source; you can add or remove rows.' : 'It starts with the {n} included sources; you can add or remove rows.', { n: view.counts.included })}</p>
      <div className="evidence-empty-actions">
        <button type="button" className="evidence-start" disabled={busy || Boolean(activeRun)} onClick={() => act(async () => { const created = await createTable(); await api.suggestColumns(researchId, created.table.id, newKey()); onRunStarted() })}>
          <Sparkles size={17} aria-hidden /><span><strong>{t('Suggest columns from the question')}</strong><small>{activeRun ? t('Available when the active run finishes') : t('{model} · 1–2 calls', { model })}</small></span>
        </button>
        <button type="button" className="evidence-start" disabled={busy} onClick={() => act(async () => { await createTable(); setEditor({ mode: 'add' }) })}>
          <Plus size={17} aria-hidden /><span><strong>{t('Add a column')}</strong><small>{t('A name, an instruction and an answer format')}</small></span>
        </button>
        <button type="button" className="evidence-start" disabled={busy} aria-expanded={templatesOpen} onClick={openTemplates}>
          <LayoutTemplate size={17} aria-hidden /><span><strong>{t('Start from a template')}</strong><small>{t('Columns saved from an earlier table')}</small></span>
        </button>
      </div>
      {templatesOpen && <div className="evidence-templates">
        {templates === null ? <p>{t('Loading templates…')}</p> : templates.length ? <ul>{templates.map(tpl => <li key={tpl.id}>
          <button type="button" disabled={busy} onClick={() => act(() => createTable(tpl.id), t('Table started from “{name}”.', { name: tpl.name }))}>
            <strong>{tpl.name}</strong><small>{tpl.columns.map(c => c.name).join(' · ')}</small>
          </button>
        </li>)}</ul> : <p>{t('No saved templates yet. A table’s columns can be saved as a template from its toolbar.')}</p>}
      </div>}
    </div>
  </section>

  const tableId = table.table.id
  const { columns, rows, fill_estimate: estimate } = table
  const cells = new Map<string, CellSummary>(table.cells.map(c => [`${c.column_id}:${c.source_version_id}`, c]))
  // Live state comes from the active run's stored target: the cells a fill plans to read, or the one cell a recheck reads.
  const filling = new Set<string>()
  if (activeRun?.kind === 'table_fill' && activeRun.target?.table_id === tableId) activeRun.target.sources?.forEach(s => s.column_ids.forEach(cid => filling.add(`${cid}:${s.source_version_id}`)))
  const rechecking = activeRun?.kind === 'cell_recheck' && activeRun.target?.table_id === tableId ? `${activeRun.target.column_id}:${activeRun.target.source_version_id}` : null
  const suggesting = activeRun?.kind === 'table_columns' && activeRun.target?.table_id === tableId
  const names = new Set(columns.map(c => c.name.trim().toLocaleLowerCase()))
  const suggestionRun = table.column_suggestions
  const suggestions = (suggestionRun?.columns ?? []).map((s, i) => ({ s, key: `${suggestionRun?.step_id}:${i}` }))
    .filter(({ s, key }) => !names.has(s.name.trim().toLocaleLowerCase()) && !discarded.includes(key))
  const [fr, fc] = [Math.min(focus[0], rows.length - 1), Math.min(focus[1], columns.length - 1)]
  const hintColumn = columns.find(c => c.id === hint)
  const cellColumn = cellTarget && columns.find(c => c.id === cellTarget.columnId)
  const cellRow = cellTarget && rows.find(r => r.source_version_id === cellTarget.sourceId)

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
  }, t(target.mode === 'edit' ? 'Column saved.' : 'Column added.'))
  const suggestionSpec = (s: ColumnSuggestion): ColumnSpec => ({ name: s.name, instruction: s.instruction, answer_format: s.answer_format, options: s.options, allow_multiple: s.allow_multiple, unit_hint: s.unit_hint })

  return <section className="evidence-panel" aria-labelledby="evidence-heading">
    <div className="workspace-pane-head"><div>
      <h2 id="evidence-heading">{table.table.title}</h2>
      <p>{t('{rows} rows · {columns} columns · {filled} cells with a value · {empty} empty · {pending} proposals waiting', { rows: table.counts.rows, columns: table.counts.columns, filled: table.counts.with_value, empty: table.counts.empty, pending: table.counts.pending_proposals })}{table.removed_rows.length ? ` · ${t('{n} removed rows keep their cells', { n: table.removed_rows.length })}` : ''}</p>
    </div>
      {tables.length > 1 && <select className="evidence-table-choice" aria-label={t('Table')} value={tableId} onChange={e => setChosen(e.target.value)}>{tables.map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select>}
    </div>

    <div className="evidence-toolbar">
      <Button className="evidence-fill" disabled={busy || Boolean(activeRun) || !estimate.sources || !columns.length}
        onClick={() => act(async () => { await api.fillTable(researchId, tableId, table.table.version, newKey()); onRunStarted() })}>
        <Sparkles size={15} aria-hidden />{!estimate.sources ? t('No empty cells to fill') : t(estimate.sources === 1 ? 'Fill empty cells · {n} source · up to {calls} calls · {model}' : 'Fill empty cells · {n} sources · up to {calls} calls · {model}', { n: estimate.sources, calls: estimate.max_model_calls, model })}
      </Button>
      <Button variant="outline" disabled={busy} onClick={() => setEditor({ mode: 'add' })}><Plus size={15} aria-hidden />{t('Add column')}</Button>
      <Button variant="outline" disabled={busy || Boolean(activeRun)} onClick={() => act(async () => { await api.suggestColumns(researchId, tableId, newKey()); onRunStarted() })} title={t('{model} · 1–2 calls', { model })}><Sparkles size={15} aria-hidden />{t('Suggest columns')}</Button>
      <Button variant="outline" disabled={busy} aria-expanded={addRowsOpen} onClick={() => setAddRowsOpen(open => !open)}><ListPlus size={15} aria-hidden />{t('Add rows')}</Button>
      <Button variant="outline" disabled={busy || !columns.length} aria-expanded={templateName !== null} onClick={() => setTemplateName(name => (name === null ? table.table.title : null))}><Save size={15} aria-hidden />{t('Save as template')}</Button>
    </div>
    {(activeRun || estimate.sources_without_text > 0 || estimate.sources_beyond_limit > 0) && <p className="evidence-toolbar-note">
      {[activeRun && t('Model actions are off while a run is active.'),
        estimate.sources_without_text > 0 && t('{n} of the sources to fill have no stored text; they get “No text” without a model call.', { n: estimate.sources_without_text }),
        estimate.sources_beyond_limit > 0 && t('{n} more sources wait for another fill (at most 25 per run).', { n: estimate.sources_beyond_limit })].filter(Boolean).join(' ')}
    </p>}

    {templateName !== null && <form className="evidence-inline-form" onSubmit={e => { e.preventDefault(); if (templateName.trim()) void act(async () => { await api.saveTableTemplate(researchId, tableId, templateName.trim(), newKey()); setTemplateName(null) }, t('Template saved.')) }}>
      <label><span>{t('Template name')}</span><input value={templateName} maxLength={120} onChange={e => setTemplateName(e.target.value)} /></label>
      <Button type="submit" disabled={busy || !templateName.trim()}>{t('Save template')}</Button>
      <Button type="button" variant="outline" onClick={() => setTemplateName(null)}>{t('Cancel')}</Button>
      <small>{t('Saves the column definitions for any research; rows and values are not saved.')}</small>
    </form>}
    {addRowsOpen && <AddRows sources={view.sources} table={table} busy={busy} onClose={() => setAddRowsOpen(false)}
      onAdd={ids => act(async () => { await api.addTableRows(researchId, tableId, ids, table.table.version); setAddRowsOpen(false) }, t('Rows added.'))} />}

    {suggesting && <p className="evidence-live" role="status"><span className="shimmer-text">{t('Suggesting columns from the question and the rows’ abstracts…')}</span></p>}
    {suggestionRun && suggestions.length > 0 && <section className="evidence-suggestions" aria-labelledby="evidence-suggestions-title">
      <h3 id="evidence-suggestions-title">{t('Suggested columns')}<small>{t('Model suggestions; none joins the table until you add it.')}</small></h3>
      <ul>{suggestions.map(({ s, key }) => <li key={key}>
        <div><strong>{s.name}</strong><span className="evidence-format">{formatText(s)}</span><p>{s.instruction}</p>{s.rationale && <small>{s.rationale}</small>}</div>
        <div className="evidence-actions">
          <Button size="sm" disabled={busy} onClick={() => act(() => api.addColumn(researchId, tableId, { ...suggestionSpec(s), suggestion_step_id: suggestionRun.step_id }, table.table.version, newKey()), t('Column added.'))}>{t('Add')}</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditor({ mode: 'suggestion', suggestion: s, stepId: suggestionRun.step_id })}>{t('Edit')}</Button>
          <Button size="sm" variant="ghost" title={t('Hides the suggestion on this screen; it stays in the run record.')} onClick={() => setDiscarded([...discarded, key])}>{t('Discard')}</Button>
        </div>
      </li>)}</ul>
      {suggestionRun.notes && <p className="legacy-mini-note">{suggestionRun.notes}</p>}
    </section>}

    {!columns.length ? <p className="empty-inline">{t('Add a column to start the table.')}</p>
      : !rows.length ? <p className="empty-inline">{t('The table has no rows. Add sources of this research as rows.')}</p>
      : <>
        <p className="evidence-hint" aria-hidden>{hintColumn ? <><strong>{hintColumn.name}</strong> — {hintColumn.instruction}</> : t('Point to or focus a column heading to read its instruction. Arrow keys move between cells; Enter opens one.')}</p>
        <div className="evidence-grid-wrap">
          <table ref={grid} className="evidence-grid" role="grid" aria-label={table.table.title} onKeyDown={moveFocus}>
            <thead><tr>
              <th scope="col" className="evidence-corner">{t('Source')}</th>
              {columns.map(col => <th scope="col" key={col.id}>
                <button type="button" className="evidence-col-head" title={t('Edit column')} aria-describedby={`evidence-instruction-${col.id}`}
                  onFocus={() => setHint(col.id)} onMouseEnter={() => setHint(col.id)} onClick={() => setEditor({ mode: 'edit', column: col })}>
                  <span>{col.name}</span><small>{formatText(col)}</small>
                </button>
                <span id={`evidence-instruction-${col.id}`} className="sr-only">{col.instruction}</span>
              </th>)}
            </tr></thead>
            <tbody>{rows.map((row, r) => {
              const key = sourceKey(row.authors, row.title, row.year)
              return <tr key={row.source_version_id}>
                <th scope="row" className="evidence-row-head">
                  <div className="evidence-row-line">
                    {key && <span className="evidence-key">{key}</span>}
                    <span className="evidence-row-title" title={row.title}>{row.title}</span>
                    <DropdownMenu>
                      <DropdownMenuTrigger className="evidence-row-menu" disabled={busy} aria-label={t('Row actions for {title}', { title: row.title })}><Ellipsis size={15} /></DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-auto">
                        <DropdownMenuItem variant="destructive" onClick={() => act(() => api.removeTableRow(researchId, tableId, row.source_version_id, table.table.version), t('Row removed from the table. Its cells are kept and return if you add the source again.'))}><Trash2 size={15} />{t('Remove from table')}</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <span className="evidence-row-meta">{[row.year, versionText(row.version_label), t(accessLabels[row.access_level]), row.selection_state && t(selectionLabels[row.selection_state])].filter(Boolean).join(' · ')}</span>
                </th>
                {columns.map((col, c) => {
                  const id = `${col.id}:${row.source_version_id}`
                  return <td key={col.id} role="gridcell">
                    <CellButton column={col} row={row} summary={cells.get(id)} live={rechecking === id ? 'recheck' : filling.has(id) && !cells.get(id)?.current ? 'fill' : null}
                      position={`${r}:${c}`} focusable={r === fr && c === fc} onFocus={() => { setFocus([r, c]); setHint(col.id) }}
                      onOpen={() => setCellTarget({ columnId: col.id, sourceId: row.source_version_id })} />
                  </td>
                })}
              </tr>
            })}</tbody>
          </table>
        </div>
      </>}
    <p className="legacy-mini-note evidence-footnote">{t('Semantic support not checked. Each quote was located in a passage of its row’s source version; whether that passage supports the value has not been checked.')}</p>

    {editor && <ColumnEditor key={editor.mode === 'edit' ? editor.column.id : editor.mode} target={editor} busy={busy} dark={dark}
      onSave={spec => saveColumn(editor, spec)} onClose={() => setEditor(null)} onRemove={column => { setEditor(null); setRemoving(column) }} />}
    <ConfirmDialog open={Boolean(removing)} dark={dark} title={t('Remove column?')}
      description={t('The column leaves the table. Its cells and their history stay stored, but this screen offers no way to bring the column back yet.')}
      context={removing?.name} confirmLabel={t('Remove column')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={() => { const column = removing; setRemoving(null); if (column) void act(() => api.removeColumn(researchId, tableId, column.id, column.version), t('Column removed.')) }}
      onOpenChange={open => { if (!open) setRemoving(null) }} />
    {cellTarget && cellColumn && cellRow && <CellPanel researchId={researchId} tableId={tableId} column={cellColumn} row={cellRow} refresh={view.last_event_id}
      source={view.sources.find(s => s.source_version_id === cellRow.source_version_id)} activeRun={activeRun} rechecking={rechecking === `${cellColumn.id}:${cellRow.source_version_id}`}
      model={model} dark={dark} onChanged={() => { void load() }} onRunStarted={onRunStarted} onClose={() => setCellTarget(null)} />}
  </section>
}

// What became of a cited passage's file (D45); the label names it in words, not only by color.
const evidenceStatusLabels = { pdf_removed: 'PDF removed', pdf_replaced: 'Previous PDF', text_superseded: 'Earlier text' } as const

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
  ].filter((m): m is { tone: string; label: string } => Boolean(m))
  const provenance = current ? [t(authorLabels[current.author]), current.reading_depth && t(depthLabels[current.reading_depth]), current.state === 'not_verified' && t('no linked evidence')].filter(Boolean).join(' · ') : ''
  const liveText = live === 'recheck' ? t('Rechecking…') : live === 'fill' ? t('Filling…') : ''
  return <button type="button" className={`evidence-cell${current ? '' : ' is-empty'}${current && !hasValue(current) ? ' is-state' : ''}`} data-cell={position} tabIndex={focusable ? 0 : -1}
    aria-label={[`${column.name}, ${row.title}`, text, provenance, liveText, ...marks.map(m => m.label)].filter(Boolean).join('. ')} onFocus={onFocus} onClick={onOpen}>
    {live === 'fill' ? <span className="evidence-cell-live shimmer-text" aria-hidden>{liveText}</span> : <span className="evidence-cell-value" aria-hidden>{text}</span>}
    {provenance && <span className="evidence-cell-marks" aria-hidden>{provenance}</span>}
    {live === 'recheck' && <span className="evidence-cell-live shimmer-text" aria-hidden>{liveText}</span>}
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
      <span><strong>{s.title}</strong><small>{[sourceKey(s.authors, s.title, s.year), versionText(s.version_label), t(selectionLabels[s.selection.state])].filter(Boolean).join(' · ')}</small></span>
    </label></li>)}</ul> : <p className="empty-inline">{t('Every source of this research is already a row.')}</p>}
    <div className="evidence-actions">
      <Button disabled={busy || !chosen.length} onClick={() => onAdd(chosen)}>{t(chosen.length === 1 ? 'Add {n} row' : 'Add {n} rows', { n: chosen.length })}</Button>
      <Button variant="outline" onClick={onClose}>{t('Close')}</Button>
    </div>
  </section>
}

function ColumnEditor({ target, busy, dark, onSave, onRemove, onClose }: { target: EditorTarget; busy: boolean; dark: boolean; onSave: (spec: ColumnSpec) => void; onRemove: (column: TableColumn) => void; onClose: () => void }) {
  const initial = target.mode === 'edit' ? target.column : target.mode === 'suggestion' ? target.suggestion : null
  const [name, setName] = useState(initial?.name ?? '')
  const [instruction, setInstruction] = useState(initial?.instruction ?? '')
  const [format, setFormat] = useState<AnswerFormat>(initial?.answer_format ?? 'text')
  const [options, setOptions] = useState<{ id?: string | null; label: string }[]>(initial?.options?.map(o => ({ ...o })) ?? [{ label: '' }, { label: '' }])
  const [multiple, setMultiple] = useState(initial?.allow_multiple ?? false)
  const [unit, setUnit] = useState(initial?.unit_hint ?? '')
  const [problem, setProblem] = useState('')
  const submit = () => {
    const labels = options.map(o => o.label.trim()).filter(Boolean)
    if (!name.trim() || !instruction.trim()) return setProblem(t('A column needs a name and an instruction.'))
    if (format === 'choice' && (labels.length < 2 || new Set(labels.map(l => l.toLocaleLowerCase())).size !== labels.length)) return setProblem(t('An options column needs at least two distinct options.'))
    setProblem('')
    onSave({ name: name.trim(), instruction: instruction.trim(), answer_format: format, allow_multiple: format === 'choice' && multiple, unit_hint: format === 'number_unit' ? unit.trim() || null : null,
      options: format === 'choice' ? options.filter(o => o.label.trim()).map(o => (o.id ? { id: o.id, label: o.label.trim() } : { label: o.label.trim() })) : null })
  }
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet evidence-sheet ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>{t(target.mode === 'edit' ? 'Edit column' : 'Add column')}</SheetTitle>
        <SheetDescription className={target.mode === 'suggestion' ? undefined : 'sr-only'}>{target.mode === 'suggestion' ? t('From a model suggestion. It joins the table only when you save it.') : t('Column definition')}</SheetDescription></SheetHeader>
      <form className="sheet-body evidence-form" onSubmit={e => { e.preventDefault(); submit() }}>
        <label className="evidence-field"><span>{t('Short name')}</span><input value={name} maxLength={80} onChange={e => setName(e.target.value)} /></label>
        <label className="evidence-field"><span>{t('Instruction')}</span><small>{t('Write it as you would for a person reading one source.')}</small>
          <textarea value={instruction} maxLength={2000} rows={4} onChange={e => setInstruction(e.target.value)} /></label>
        <fieldset className="evidence-field"><legend>{t('Answer format')}</legend>
          <div className="evidence-segments">{(Object.keys(formatLabels) as AnswerFormat[]).map(f => <label key={f} className={format === f ? 'is-selected' : undefined}>
            <input type="radio" name="answer-format" value={f} checked={format === f} onChange={() => setFormat(f)} />{t(formatLabels[f])}
          </label>)}</div>
        </fieldset>
        {format === 'choice' && <fieldset className="evidence-field"><legend>{t('Options')}</legend>
          {options.map((option, i) => <div className="evidence-option" key={option.id ?? `new-${i}`}>
            <input aria-label={t('Option {n}', { n: i + 1 })} value={option.label} maxLength={120} onChange={e => setOptions(options.map((o, j) => (j === i ? { ...o, label: e.target.value } : o)))} />
            <Button type="button" variant="ghost" size="icon-sm" aria-label={t('Remove option {n}', { n: i + 1 })} disabled={options.length <= 2} onClick={() => setOptions(options.filter((_, j) => j !== i))}><Trash2 size={14} /></Button>
          </div>)}
          <Button type="button" variant="outline" size="sm" disabled={options.length >= 20} onClick={() => setOptions([...options, { label: '' }])}><Plus size={14} aria-hidden />{t('Add option')}</Button>
          <label className="evidence-check"><input type="checkbox" checked={multiple} onChange={e => setMultiple(e.target.checked)} /><span>{t('A source may have several options')}</span></label>
        </fieldset>}
        {format === 'number_unit' && <label className="evidence-field"><span>{t('Expected unit (optional)')}</span><small>{t('Nothing is converted; a value keeps the unit its source states.')}</small>
          <input value={unit} maxLength={40} onChange={e => setUnit(e.target.value)} /></label>}
        {target.mode === 'edit' && <p className="evidence-flag-note is-attention">{t('A changed definition becomes a new column revision. Values made under the earlier definition stay and are marked “Column changed”.')}</p>}
        {problem && <p className="evidence-flag-note is-blocking" role="alert">{problem}</p>}
        <div className="evidence-actions">
          <Button type="submit" disabled={busy}>{t(target.mode === 'edit' ? 'Save column' : 'Add column')}</Button>
          <Button type="button" variant="outline" onClick={onClose}>{t('Cancel')}</Button>
          {target.mode === 'edit' && <Button type="button" variant="destructive" className="evidence-remove" disabled={busy} onClick={() => onRemove(target.column)}><Trash2 size={14} aria-hidden />{t('Remove column')}</Button>}
        </div>
      </form>
    </SheetContent>
  </Sheet>
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

function CellPanel({ researchId, tableId, column, row, refresh, source, activeRun, rechecking, model, dark, onChanged, onRunStarted, onClose }: {
  researchId: string; tableId: string; column: TableColumn; row: TableRow; refresh: number; source: Source | undefined; activeRun: Run | null; rechecking: boolean
  model: string; dark: boolean; onChanged: () => void; onRunStarted: () => void; onClose: () => void
}) {
  const toast = useToast()
  const [cell, setCell] = useState<CellView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [problem, setProblem] = useState('')
  const [evidence, setEvidence] = useState<CellEvidence[] | null>(null)
  const sv = row.source_version_id

  const load = useCallback(() => api.cell(researchId, tableId, column.id, sv).then(c => { setCell(c); setError('') }, e => setError(errorText(e))), [researchId, tableId, column.id, sv])
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
      if (conflict(e)) { toast('warning', t(draft ? 'Not applied: {message}. The cell now shows the latest state; your draft is kept.' : 'Not applied: {message}. The page now shows the latest state.', { message: errorText(e) })); await load(); onChanged() }
      else toast('error', errorText(e))
    } finally { setBusy(false) }
  }

  const key = sourceKey(row.authors, row.title, row.year)
  // An upper bound: a short source is read whole, a longer one gives at most 16 passages (D38). One passage per extracted page.
  const available = source ? (source.access.abstract_passage_id ? 1 : 0) + source.access.assets.reduce((n, a) => n + (a.page_count ?? 0), 0) : 0
  const recheckPassages = available <= MAX_WHOLE_PASSAGES ? available : MAX_RECHECK_PASSAGES
  const current = cell?.current ?? null
  const pending = cell?.pending_proposal ?? null
  const flags = cell?.flags ?? []
  const showEvidence = (items: CellEvidence[]) => setEvidence(items)
  const save = () => {
    if (!cell || !draft) return
    const body = editBody(column, draft, current, cell.version)
    if (typeof body === 'string') return setProblem(body)
    setProblem('')
    void mutate(() => api.editCell(researchId, tableId, column.id, sv, body, newKey()), t('Value saved.'), () => setDraft(null))
  }

  return <Sheet open onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet evidence-sheet evidence-cell-sheet ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>{column.name}</SheetTitle><SheetDescription>{row.title}</SheetDescription></SheetHeader>
      <div className="sheet-body evidence-cell-body">
        <p className="evidence-cell-source">{[key, row.year, versionText(row.version_label), t(accessLabels[row.access_level])].filter(Boolean).join(' · ')}</p>
        {error && <div className="legacy-boundary">{error}</div>}
        {!cell && !error && <p>{t('Loading cell…')}</p>}
        {cell && <>
          <section className="evidence-block" aria-labelledby="evidence-current-title">
            <h3 id="evidence-current-title">{t('Current value')}</h3>
            {current ? <>
              <p className={`evidence-current${hasValue(current) ? '' : ' is-state'}`}>{revisionText(column, current)}</p>
              {current.value?.as_stated && <p className="evidence-sub">{t('As written in the source: {text}', { text: current.value.as_stated })}</p>}
              <p className="evidence-sub">{revisionMeta(current)}</p>
              {current.note && <p className="evidence-note"><span>{t(current.author === 'human' ? 'Your note' : 'Model note')}</span>{current.note}</p>}
            </> : <p className="evidence-current is-state">{t('Empty: no value recorded yet.')}</p>}
            {rechecking && <p className="evidence-live" role="status"><span className="shimmer-text">{t('Rechecking this cell…')}</span></p>}
            {flags.includes('stale_column') && current && <p className="evidence-flag-note is-attention">{t('Made under an earlier definition of this column (revision {old}). It stays until you edit it or use a newer proposal.', { old: current.column_revision })}</p>}
            {flags.includes('pdf_removed') && <p className="evidence-flag-note is-attention">{t('A PDF this value cites was removed from the source. The cited passages still open as text; the PDF view is off.')}</p>}
            {flags.includes('pdf_replaced') && <p className="evidence-flag-note is-attention">{t('This value cites a PDF that was later replaced. Its evidence still opens the previous file; a recheck reads the current file.')}</p>}
            {flags.includes('text_superseded') && <p className="evidence-flag-note is-attention">{t('This value cites an earlier text extraction of the PDF. Its evidence still opens that text; a recheck reads the current extraction.')}</p>}
            {current && hasValue(current) && (current.evidence.length ? <EvidenceList items={current.evidence} onShow={showEvidence} />
              : <p className="evidence-sub">{t('No linked evidence: this value was recorded without a passage.')}</p>)}
          </section>

          {pending && <section className={`evidence-block evidence-proposal${flags.includes('proposal_invalid') ? ' is-invalid' : ''}`} aria-labelledby="evidence-proposal-title">
            <h3 id="evidence-proposal-title">{t('Pending proposal')}</h3>
            <div className="evidence-compare">
              <div><span>{t('Current')}</span><strong>{current ? revisionText(column, current) : t('Empty')}</strong><small>{current ? t(authorLabels[current.author]) : ''}</small></div>
              <div><span>{t('Proposal')}</span><strong>{revisionText(column, pending)}</strong><small>{revisionMeta(pending)}</small></div>
            </div>
            {flags.includes('proposal_before_edit') && <p className="evidence-flag-note is-attention">{t('Requested before the cell last changed. Compare it with the current value before using it.')}</p>}
            {flags.includes('proposal_invalid') && <p className="evidence-flag-note is-blocking">{t('This proposal failed validation after one repair. It is kept for the record and cannot be used.')}</p>}
            {pending.note && <p className="evidence-note"><span>{t('Model note')}</span>{pending.note}</p>}
            {pending.evidence.length > 0 && <EvidenceList items={pending.evidence} onShow={showEvidence} />}
            <div className="evidence-actions">
              <Button disabled={busy || flags.includes('proposal_invalid')} onClick={() => mutate(() => api.decideProposal(researchId, tableId, column.id, sv, pending.id, 'accept', cell.version, newKey()), t('The proposal’s value and evidence are now the cell’s value, recorded as your decision.'))}>{t('Use this value')}</Button>
              <Button variant="outline" disabled={busy} onClick={() => mutate(() => api.decideProposal(researchId, tableId, column.id, sv, pending.id, 'dismiss', cell.version, newKey()), t('Current value kept; the proposal stays in the history.'))}>{t('Keep current')}</Button>
            </div>
            <p className="legacy-mini-note">{t('Using a proposal records its value as your decision. It does not mean its support was checked.')}</p>
          </section>}

          <section className="evidence-block" aria-label={t('Change this cell')}>
            {!draft && <div className="evidence-actions">
              <Button variant="outline" disabled={busy} onClick={() => { setProblem(''); setDraft(draftFrom(column, current)) }}><PencilLine size={14} aria-hidden />{t('Edit value')}</Button>
              <Button variant="outline" disabled={busy || Boolean(activeRun) || !available} onClick={() => mutate(() => api.recheckCell(researchId, tableId, column.id, sv, cell.version, newKey()), t('Recheck started. Its result will wait as a proposal.'), onRunStarted)}><RotateCw size={14} aria-hidden />{t('Recheck this cell')}</Button>
            </div>}
            {!draft && <p className="evidence-sub">{!available ? t('This source has no stored text, so a recheck has nothing to read.')
              : activeRun ? t('Another run is active; a recheck can start when it finishes.')
              : t(recheckPassages === 1 ? 'Only {source} · up to {n} passage · {model} · 1–2 calls. The result waits as a proposal; the model does not see the current value.' : 'Only {source} · up to {n} passages · {model} · 1–2 calls. The result waits as a proposal; the model does not see the current value.', { source: key || row.title, n: recheckPassages, model })}</p>}
            {draft && <form className="evidence-form" aria-labelledby="evidence-edit-title" onSubmit={e => { e.preventDefault(); save() }}>
              <h3 id="evidence-edit-title">{t('Edit value')}</h3>
              <label className="evidence-field"><span>{t('State')}</span>
                <select value={draft.state} onChange={e => setDraft({ ...draft, state: e.target.value as Draft['state'] })}>{editableStates.map(s => <option key={s} value={s}>{t(stateLabels[s])}</option>)}</select>
              </label>
              {draft.state === 'value' && <ValueInputs column={column} draft={draft} onChange={setDraft} />}
              {draft.state === 'value' && current && current.evidence.length > 0 && <label className="evidence-check">
                <input type="checkbox" checked={draft.keepEvidence} onChange={e => setDraft({ ...draft, keepEvidence: e.target.checked })} />
                <span>{t('Keep the evidence of the current value')}<small>{t('For a corrected unit or spelling. Without it the value is saved without linked evidence.')}</small></span>
              </label>}
              <label className="evidence-field"><span>{t('Note (optional)')}</span><textarea value={draft.note} maxLength={2000} rows={2} onChange={e => setDraft({ ...draft, note: e.target.value })} /></label>
              {problem && <p className="evidence-flag-note is-blocking" role="alert">{problem}</p>}
              <div className="evidence-actions">
                <Button type="submit" disabled={busy}>{t('Save value')}</Button>
                <Button type="button" variant="outline" disabled={busy} onClick={() => setDraft(null)}>{t('Cancel')}</Button>
              </div>
            </form>}
          </section>

          {cell.revisions.length > 0 && <details className="evidence-history">
            <summary>{t(cell.revisions.length === 1 ? 'History · {n} revision' : 'History · {n} revisions', { n: cell.revisions.length })}</summary>
            <ol>{cell.revisions.slice().reverse().map(rev => <li key={rev.id}>
              <strong>{t(kindLabels[rev.kind])}{rev.decision ? ` · ${t(decisionLabels[rev.decision])}` : ''}{rev.output_status === 'unverified_draft' ? ` · ${t('failed validation')}` : ''}</strong>
              {rev.state && <span className="evidence-history-value">{revisionText(column, rev)}</span>}
              <small>{revisionMeta(rev)}</small>
              {rev.note && <small>{rev.note}</small>}
              {rev.evidence.length > 0 && <EvidenceList items={rev.evidence} onShow={showEvidence} />}
            </li>)}</ol>
          </details>}
          <p className="panel-note">{t('Semantic support not checked. DEIXIS located each quote in a passage of this source version; it did not check that the passage supports the value.')}</p>
        </>}
      </div>
      {evidence && <PassageSheet researchId={researchId} passageId={evidence[0].passage_id} highlightTexts={evidence.flatMap(e => e.anchor_text ? [e.anchor_text] : [])} expectHighlight pdfRemoved={evidence[0].evidence_status === 'pdf_removed'} sources={source ? [source] : undefined} dark={dark} onClose={() => setEvidence(null)} />}
    </SheetContent>
  </Sheet>
}

// One entry per passage: a revision can quote several spans of the same passage (D43), and the passage opens with all of them marked.
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
      <span className="evidence-locator">{first.kind === 'abstract' ? <BookOpenText size={13} aria-hidden /> : <FileText size={13} aria-hidden />}{locatorText(first)}{first.evidence_status !== 'current' && <><TriangleAlert size={12} aria-hidden />{t(evidenceStatusLabels[first.evidence_status])}</>}</span>
      {quotes.length ? <div className="evidence-quotes">{quotes.map((quote, i) => <q key={i} className="evidence-quote"><mark>{quote}</mark></q>)}</div>
        : <span className="evidence-sub">{t('No located quote for this passage.')}</span>}
      <Button variant="outline" size="sm" onClick={() => onShow(group)}>{t('Show evidence')}</Button>
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
