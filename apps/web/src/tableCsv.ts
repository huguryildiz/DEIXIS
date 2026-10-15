import { downloadName } from './downloadName'
import { type CellRevision, type CellState, type CellValue, type ResearchView, type Source, type TableColumn, type TableRow, type TableSummary, type TableView } from './api'
import { locatorText, versionText } from './labels'
import { citationStyle, formatReferenceText, type CitationStyle } from './citations'
import { t, uiLocale } from './i18n'

// The evidence table's words for cell states and values, and its CSV file. The table panel and the topbar Export menu
// (UI parity S8) write the same file. Split from EvidenceTable.tsx.

// Empty states read as words, never as colour alone.
export const stateLabels: Record<CellState, string> = {
  value: 'Value', not_verified: 'Value without linked evidence', unknown: 'Unclear in the source', not_reported: 'Not reported',
  not_applicable: 'Not applicable', inaccessible: 'No text', not_found_in_inspected_scope: 'Not found in the text read',
}
export const accessLabels: Record<TableRow['access_level'], string> = { pdf_available: 'PDF text', abstract: 'Abstract only', metadata: 'Metadata only' }

// A value keeps the shape of the column revision it was made under, so it is read from its own keys.
function valueText(column: TableColumn, value: CellValue | null) {
  if (!value) return ''
  if (value.option_ids) return value.option_ids.map(id => column.options?.find(o => o.id === id)?.label ?? id).join(', ')
  if (typeof value.number === 'number') return [value.number.toLocaleString(uiLocale(), { maximumFractionDigits: 12 }), value.unit].filter(Boolean).join(' ')
  if (value.answer) return t(value.answer === 'yes' ? 'Yes' : 'No')
  return value.text ?? ''
}

// The row head writes the source's full reference in the citation style chosen on the report.
function savedStyle(): CitationStyle {
  return citationStyle()
}

export const hasValue = (rev: CellRevision) => rev.state === 'value' || rev.state === 'not_verified'
export const revisionText = (column: TableColumn, rev: CellRevision) => (hasValue(rev) ? valueText(column, rev.value) : rev.state ? t(stateLabels[rev.state]) : '')

// The table as CSV: one value column and one evidence column (quote and locator) per table column. Current values only;
// proposals waiting for a decision are left out. The BOM lets spreadsheet apps read the file as UTF-8. Exported for
// tests/report/test_ooxml_exports.py, which runs it in node.
export function tableCsv(table: TableView, sources: Source[]) {
  const byId = new Map(sources.map(s => [s.source_version_id, s]))
  const style = savedStyle()
  const cells = new Map(table.cells.map(c => [`${c.column_id}:${c.source_version_id}`, c]))
  const quote = (v: string | number | null | undefined) => {
    const text = v == null ? '' : String(v)
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const head = [t('Key'), t('Reference'), t('Title'), t('Authors'), t('Year'), t('Version'), t('Access'), ...table.columns.flatMap(c => [c.name, t('{name} — evidence', { name: c.name })])]
  const lines = table.rows.map(row => { const source = byId.get(row.source_version_id); return [row.source_key ?? '', source ? formatReferenceText(style, source) : '', row.title, row.authors.join('; '), row.year, versionText(row.version_label), t(accessLabels[row.access_level]),
    ...table.columns.flatMap(col => {
      const current = cells.get(`${col.id}:${row.source_version_id}`)?.current
      if (!current) return ['', '']
      return [revisionText(col, current), current.evidence.map(e => [e.anchor_text && `“${e.anchor_text}”`, locatorText(e)].filter(Boolean).join(' — ')).join(' | ')]
    })] })
  return `\uFEFF${[head, ...lines].map(line => line.map(quote).join(',')).join('\r\n')}\r\n`
}

export function downloadTableCsv(table: TableView, sources: Source[]) {
  const url = URL.createObjectURL(new Blob([tableCsv(table, sources)], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = downloadName(table.table.title, [`V${table.table.version}`], 'csv', 'Evidence table')
  link.click()
  URL.revokeObjectURL(url)
}

// Why a report cannot be written from this table now, or '' when it can. The table panel's "Write a manuscript draft"
// and the evidence report’s "Write a new version" read the same rule from the table's stored `report_ready`.
export function reportGate(view: ResearchView, summary: TableSummary | undefined, columns: number, title: string) {
  const ready = summary?.report_ready
  const continueWithFailed = !ready?.ready && Boolean(ready?.can_continue_with_failed)
  const reason = view.runs.some(item => ['queued', 'running', 'pause_requested', 'paused'].includes(item.status))
    ? t('Available when the active run finishes')
    : !columns ? t('Add a column and fill its cells before writing a report.')
    : ready?.cells_total === 0 ? t('A report needs included sources and a filled column.')
    : !ready?.ready && !continueWithFailed ? t('A report needs a filled evidence table: {n} cells left in “{table}”.', { n: ready?.cells_left ?? 0, table: title }) : ''
  return { reason, continueWithFailed }
}
