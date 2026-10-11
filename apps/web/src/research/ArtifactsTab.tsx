import { ArrowUpRight, FileText, Table2 } from 'lucide-react'
import { type Answer, type ResearchView, type TableSummary } from '../api'
import { LATE_REVISION_LABEL } from '../labels'
import { t, uiLocale } from '../i18n'

const tableFacts = (table: TableSummary) => [t('Table'), t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns })].join(' · ')

// An evidence table as an artifact card beside the report card; it opens the table on the Evidence tab.
export function TableCard({ table, onOpen }: { table: TableSummary; onOpen: () => void }) {
  return <button type="button" className="report-artifact" onClick={onOpen} aria-label={t('Open table: {title}', { title: table.title })}>
    <span className="report-artifact-preview table-artifact-preview" aria-hidden="true">{Array.from({ length: 5 }, (_, r) => <i key={r} />)}</span>
    <span className="report-artifact-copy">
      <span className="report-artifact-meta"><Table2 size={13} strokeWidth={1.8} aria-hidden />{tableFacts(table)}</span>
      <strong>{table.title}</strong>
      <small className="table-artifact-access">{[table.access.pdf_available && t('{n} full text', { n: table.access.pdf_available }), table.access.abstract && t('{n} abstract only', { n: table.access.abstract }), table.access.metadata && t('{n} metadata only', { n: table.access.metadata })].filter(Boolean).join(' · ')}</small>
      {table.auto_columns > 0 && <small className="table-artifact-note">{t('Columns added automatically, no person reviewed them.')}</small>}
    </span>
    <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
  </button>
}

export function ArtifactsTab({ reports, tables, reportRuns, heading, onOpenReport, onOpenEvidenceReport, onOpenTable }: { reports: { answer: Answer; version: number; title: string }[]; tables: TableSummary[] | null; reportRuns: ResearchView['reportRuns']; heading: string; onOpenReport: (answerId: string) => void; onOpenEvidenceReport: (reportId: string) => void; onOpenTable: (tableId: string) => void }) {
  return reports.length || tables?.length || reportRuns.length ? <ul className="artifact-list">{reportRuns.map(item => <li key={item.id}><button type="button" onClick={() => onOpenEvidenceReport(item.id)}><FileText size={16} aria-hidden /><span><strong>{heading}</strong><small>{item.status === 'valid' ? t('Evidence report · V{n}', { n: item.report_version ?? '' }) : item.status === 'draft' ? t('Evidence report · draft') : t('Evidence report · being written')}</small></span><ArrowUpRight size={15} aria-hidden /></button></li>)}{reports.map(({ answer: a, version, title }) => <li key={a.id}><button type="button" onClick={() => onOpenReport(a.id)}>
    <FileText size={16} aria-hidden /><span><strong>{title}</strong><small>{t('Report')} · V{version}{a.late_revision ? ` · ${t(LATE_REVISION_LABEL)}` : ''}{a.applicability !== 'current' || a.late_revision_status?.status === 'published' ? ` · ${t('earlier')}` : ''} · {new Date(a.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })}</small></span><ArrowUpRight size={15} aria-hidden />
  </button></li>)}
    {tables?.map(table => <li key={table.id}><button type="button" onClick={() => onOpenTable(table.id)}>
      <Table2 size={16} aria-hidden /><span><strong>{table.title}</strong><small>{tableFacts(table)} · {new Date(table.updated_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })}</small></span><ArrowUpRight size={15} aria-hidden />
    </button></li>)}</ul> : <p className="empty-inline">{t('No reports yet. Generate a source-linked answer to create one.')}</p>
}
