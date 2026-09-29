import { useState } from 'react'
import { FileText, Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ResearchView, type TableSummary } from '../api'
import { Depth } from '../PdfReadiness'
import { t } from '../i18n'
import { useToast } from '../Toast'

const working = new Set(['queued', 'running', 'pause_requested', 'paused'])

export function ReportReadiness({ researchId, view, tables, onTable, onChanged }: {
  researchId: string; view: ResearchView; tables: TableSummary[]; onTable: (id: string) => void; onChanged: () => Promise<void>
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const eligible = tables.filter(table => table.columns > 0)
  if (!eligible.length) return null
  const fill = view.runs.find(run => run.kind === 'table_fill' && working.has(run.status) && eligible.some(table => table.id === run.target?.table_id))
  const table = eligible.find(item => item.id === fill?.target?.table_id) ?? eligible[0]
  const activeReport = view.runs.some(run => run.kind === 'report' && working.has(run.status))
  const blockedByRun = view.runs.some(run => working.has(run.status))
  const ready = eligible.filter(item => item.report_ready.ready)
  if (activeReport && !fill) return null
  const action = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn(); await onChanged() } catch (error) { toast('error', error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  return <section className="pdf-ready report-ready" aria-label={t('Evidence report')}>
    {fill ? <>
      <div className="pdf-ready-head"><FileText size={17} aria-hidden /><h2>{t(fill.status === 'paused' ? 'Table fill paused' : 'Filling the evidence table')}</h2></div>
      <Depth cells={[[table.report_ready.cells_total - table.report_ready.cells_left, t('cells filled')], [table.report_ready.cells_left, t('cells left')]]} />
      <div className="report-ready-bar" role="progressbar" aria-valuenow={table.report_ready.cells_total - table.report_ready.cells_left} aria-valuemax={table.report_ready.cells_total} aria-label={t('Cells filled')}><span style={{ width: `${table.report_ready.cells_total ? (1 - table.report_ready.cells_left / table.report_ready.cells_total) * 100 : 0}%` }} /></div>
      <div className="pdf-ready-actions"><Button variant="outline" disabled={busy} onClick={() => void action(() => api.controlRun(fill.id, fill.status === 'paused' ? 'resume' : 'pause'))}>{fill.status === 'paused' ? <Play size={15} aria-hidden /> : <Pause size={15} aria-hidden />}{t(fill.status === 'paused' ? 'Resume' : 'Pause')}</Button><button type="button" className="text-link" onClick={() => onTable(table.id)}>{t('Open the table')}</button></div>
    </> : ready.length ? <>
      <div className="pdf-ready-head"><FileText size={17} aria-hidden /><h2>{t('Evidence report')}</h2></div>
      {ready.map(item => <div className="report-ready-choice" key={item.id}>
        <Button disabled={busy || blockedByRun} title={blockedByRun ? t('Available when the active run finishes') : undefined} aria-describedby={blockedByRun ? 'report-ready-reason' : undefined} onClick={() => void action(() => api.startReport(researchId, item.id, crypto.randomUUID()))}>{t('Write report')}{ready.length > 1 ? ` · ${item.title}` : ''}</Button>
        <p>{t('Writes a sectioned report from “{table}” and its quotes.', { table: item.title })}</p>
      </div>)}
      {blockedByRun && <span id="report-ready-reason" className="sr-only">{t('Available when the active run finishes')}</span>}
    </> : <p className="pdf-ready-lede">{table.report_ready.cells_total === 0 ? t('A report needs included sources and a filled column.') : t('A report needs a filled evidence table: {n} cells left in “{table}”.', { n: table.report_ready.cells_left, table: table.title })} <button type="button" className="text-link" onClick={() => onTable(table.id)}>{t('Open the table')}</button></p>}
  </section>
}
