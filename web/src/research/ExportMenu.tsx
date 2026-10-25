import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, FileTypeIcon } from '@/components/ui/dropdown-menu'
import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { answerDocxUrl, api, bibliographyUrl, prismaSUrl, tableExportUrl, type Answer, type Source, type TableSummary } from '../lib/api'
import { downloadTableCsv } from '../table/tableCsv'
import { useCitationStyle } from '../lib/citations'
import { useToast } from '../components/Toast'
import { t, uiLanguage } from '../lib/i18n'
import { tableTitle } from '../lib/labels'
import { downloadReportMarkdown } from './reportMarkdown'

// Bibliography files for reference managers, downloaded from the local API. Cited sources are the ones `answerId` cites
// (a report's own export), so an earlier report exports its own sources.
export function ExportLinks({ researchId, sources, answerId }: { researchId: string; sources: 'included' | 'cited'; answerId?: string }) {
  const label = t(sources === 'included' ? 'included sources' : 'cited sources')
  return <span className="export-links" role="group" aria-label={t('Export {label}', { label })}>
    <span className="export-links-label"><Download size={15} aria-hidden />{t(sources === 'included' ? 'Export included' : 'Export cited')}</span>
    <span className="export-formats">
      <a href={bibliographyUrl(researchId, 'bibtex', sources, answerId)} download title={t('BibTeX file of the {label} (LaTeX, Zotero, JabRef)', { label })}>.bib</a>
      <a href={bibliographyUrl(researchId, 'ris', sources, answerId)} download title={t('RIS file of the {label} (Zotero, EndNote, Mendeley)', { label })}>.ris</a>
    </span>
  </span>
}

export type ExportReport = { answer: Answer; title: string; version: number }

// The topbar's Export menu (mockup `menu('export')`, R8): Report, Evidence table and Sources groups of file rows. A row
// is shown only when its file can be made now: the report's Markdown (written here, as the report panel's Download
// writes it), its PDF (the browser's print dialog on the report panel, `onPrintReport`, S27) and its Word file, the
// table's CSV (written here) and its Excel and Word files, the bibliographies and the PRISMA-S search report (§2.2).
// Like the mockup's menu(), the list opens under the trigger at its left edge and slides back inside the window.
// `icon`: the answer's download button in the thread (mockup `.ib` with `data-menu="export"`) opens the same menu.
// `cited`: the works the report's answer cites that are still in this research (what its BibTeX lists); the row exports
// that answer's sources, so it needs the report.
export function ExportMenu({ researchId, report, sources, tables, included, cited, prisma, icon = false, onPrintReport }: {
  researchId: string; report: ExportReport | null; sources: Source[]; tables: TableSummary[] | null
  included: number; cited: number; prisma: boolean; icon?: boolean; onPrintReport: (answerId: string) => void
}) {
  const toast = useToast()
  const [style] = useCitationStyle()
  // A table exports once it has columns and rows; with several, the one changed last (its title names it).
  const exportable = (tables ?? []).filter(table => table.rows > 0 && table.columns > 0)
  const table = exportable.reduce<TableSummary | null>((latest, item) => (!latest || item.updated_at > latest.updated_at ? item : latest), null)
  if (!report && !table && !included && !prisma) return null
  const lang = uiLanguage() === 'tr' ? 'tr' : 'en'
  const row = (format: string, detail: string) => <><FileTypeIcon format={format} /><b>{format}</b><span>{detail}</span></>
  // A row with no mockup counterpart (the PRISMA-S search report, §2.2) carries `export-placement`.
  const link = (href: string, format: string, detail: string, extra = '') => <MenuPrimitive.LinkItem key={href} href={href} download closeOnClick data-slot="dropdown-menu-item" className={`research-export-item menu-fmt ${extra}`.trim()}>
    {row(format, detail)}
  </MenuPrimitive.LinkItem>
  const tableCsv = async (item: TableSummary) => {
    try { downloadTableCsv(await api.table(researchId, item.id), sources) }
    catch (e) { toast('error', e instanceof Error ? e.message : String(e)) }
  }
  return <DropdownMenu>
    {icon
      ? <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" className="answer-ib" aria-label={t('Download')} title={t('Download')} />}><Download size={16} aria-hidden /></DropdownMenuTrigger>
      : <DropdownMenuTrigger render={<Button variant="default" size="sm" className="research-export" />}><Download size={16} className="size-4" aria-hidden />{t('Export')}</DropdownMenuTrigger>}
    <DropdownMenuContent align="start" sideOffset={6} collisionAvoidance={{ align: 'shift', fallbackAxisSide: 'none' }} className="research-export-menu">
      {report && <DropdownMenuGroup>
        <DropdownMenuLabel>{t('Report')}</DropdownMenuLabel>
        <DropdownMenuItem className="research-export-item menu-fmt" onClick={() => downloadReportMarkdown(report.answer, sources, report.title, report.version, style)}>{row('MD', t('Markdown'))}</DropdownMenuItem>
        <DropdownMenuItem className="research-export-item menu-fmt" title={t('Opens the report and the print dialog; choose Save as PDF there.')} onClick={() => onPrintReport(report.answer.id)}>{row('PDF', t('Portable document'))}</DropdownMenuItem>
        {link(answerDocxUrl(researchId, report.answer.id, lang, style), 'DOCX', t('Word document'))}
      </DropdownMenuGroup>}
      {table && <DropdownMenuGroup>
        <DropdownMenuLabel>{exportable.length > 1 ? `${t('Evidence table')} · ${tableTitle(table.title)}` : t('Evidence table')}</DropdownMenuLabel>
        <DropdownMenuItem className="research-export-item menu-fmt" onClick={() => { void tableCsv(table) }}>{row('CSV', t('Comma-separated values'))}</DropdownMenuItem>
        {link(tableExportUrl(researchId, table.id, 'xlsx', lang, style), 'XLSX', t('Excel workbook'))}
        {link(tableExportUrl(researchId, table.id, 'docx', lang, style), 'DOCX', t('Word table'))}
      </DropdownMenuGroup>}
      {((report && cited > 0) || included > 0 || prisma) && <DropdownMenuGroup>
        <DropdownMenuLabel>{t('Sources')}</DropdownMenuLabel>
        {report && cited > 0 && link(bibliographyUrl(researchId, 'bibtex', 'cited', report.answer.id), 'BIB', t(cited === 1 ? 'BibTeX · {n} cited source' : 'BibTeX · {n} cited sources', { n: cited }))}
        {included > 0 && link(bibliographyUrl(researchId, 'ris', 'included'), 'RIS', t(included === 1 ? 'RIS · {n} included source' : 'RIS · {n} included sources', { n: included }))}
        {prisma && link(prismaSUrl(researchId, 'md'), 'MD', t('PRISMA-S search report'), 'export-placement')}
        {prisma && link(prismaSUrl(researchId, 'json'), 'JSON', t('PRISMA-S search report'), 'export-placement')}
      </DropdownMenuGroup>}
    </DropdownMenuContent>
  </DropdownMenu>
}
