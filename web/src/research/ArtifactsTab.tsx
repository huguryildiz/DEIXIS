import { ArrowUpRight, FileText, Table2 } from 'lucide-react'
import { type TableSummary } from '../lib/api'
import { t } from '../lib/i18n'
import { tableTitle } from '../lib/labels'

const tableFacts = (table: TableSummary) => [t('Table'), t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns })].join(' · ')

// An evidence table as an artifact card beside the report card; it opens the table on the Evidence tab.
export function TableCard({ table, heading, onOpen }: { table: TableSummary; heading: string; onOpen: () => void }) {
  return <button type="button" className="report-artifact" onClick={onOpen} aria-label={t('Open table: {title}', { title: tableTitle(table.title, heading) })}>
    <span className="report-artifact-preview table-artifact-preview" aria-hidden="true">{Array.from({ length: 5 }, (_, r) => <i key={r} />)}</span>
    <span className="report-artifact-copy">
      <span className="report-artifact-meta"><Table2 size={13} strokeWidth={1.8} aria-hidden />{tableFacts(table)}</span>
      <strong>{tableTitle(table.title, heading)}</strong>
      <small className="table-artifact-access">{[table.access.pdf_available && t('{n} full text', { n: table.access.pdf_available }), table.access.abstract && t('{n} abstract only', { n: table.access.abstract }), table.access.metadata && t('{n} metadata only', { n: table.access.metadata })].filter(Boolean).join(' · ')}</small>
      {table.auto_columns > 0 && <small className="table-artifact-note">{t('Columns added automatically, no person reviewed them.')}</small>}
    </span>
    <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
  </button>
}

// While a search or answer run works and no report or table exists yet, each missing artifact shows as a skeleton card:
// grey lines with numbered citation chips for the report, a ruled grid for the table. They open nothing.
export function PendingArtifacts({ report, table }: { report: boolean; table: boolean }) {
  if (!report && !table) return null
  return <div className="table-artifacts pending-artifacts" role="status">
    {report && <div className="report-artifact is-live is-pending">
      <span className="report-artifact-preview pending-report-preview" aria-hidden="true">
        <span><i /><b>1</b><i /></span><span><i /><b>2</b><b>3</b><i /></span><span><i /><b>4</b></span><span><i /></span>
      </span>
      <span className="report-artifact-copy"><strong>{t('Report')}</strong>
        <span className="report-artifact-meta"><FileText size={13} strokeWidth={1.8} aria-hidden />{t('Appears once papers start to be cited')}</span></span>
    </div>}
    {table && <div className="report-artifact is-live is-pending">
      <span className="report-artifact-preview table-artifact-preview pending-table-preview" aria-hidden="true">{Array.from({ length: 5 }, (_, r) => <i key={r} />)}</span>
      <span className="report-artifact-copy"><strong>{t('Evidence table')}</strong>
        <span className="report-artifact-meta"><Table2 size={13} strokeWidth={1.8} aria-hidden />{t('Appears once sources are included')}</span></span>
    </div>}
  </div>
}
