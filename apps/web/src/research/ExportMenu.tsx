import { ChevronDown, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { bibliographyUrl, prismaSUrl } from '../api'
import { t } from '../i18n'

// Bibliography files for reference managers, downloaded from the local API.
export function ExportLinks({ researchId, sources }: { researchId: string; sources: 'included' | 'cited' }) {
  const label = t(sources === 'included' ? 'included sources' : 'cited sources')
  return <span className="export-links" role="group" aria-label={t('Export {label}', { label })}>
    <span className="export-links-label"><Download size={15} aria-hidden />{t(sources === 'included' ? 'Export included' : 'Export cited')}</span>
    <span className="export-formats">
      <a href={bibliographyUrl(researchId, 'bibtex', sources)} download title={t('BibTeX file of the {label} (LaTeX, Zotero, JabRef)', { label })}>.bib</a>
      <a href={bibliographyUrl(researchId, 'ris', sources)} download title={t('RIS file of the {label} (Zotero, EndNote, Mendeley)', { label })}>.ris</a>
    </span>
  </span>
}

// The research-level downloads that already exist, in one menu: bibliography files for reference managers and the
// PRISMA-S search report. A group shows only when its file has something in it.
export function ExportMenu({ researchId, included, cited, prisma }: { researchId: string; included: boolean; cited: boolean; prisma: boolean }) {
  if (!included && !cited && !prisma) return null
  const link = (href: string, format: string, title: string) => <MenuPrimitive.LinkItem key={href} href={href} download title={title} closeOnClick className="research-export-item">
    <Download size={15} aria-hidden /><span>{format}</span>
  </MenuPrimitive.LinkItem>
  const bibliography = (sources: 'included' | 'cited') => {
    const label = t(sources === 'included' ? 'included sources' : 'cited sources')
    return <DropdownMenuGroup>
      <DropdownMenuLabel className="research-export-label">{t(sources === 'included' ? 'Export included' : 'Export cited')}</DropdownMenuLabel>
      {link(bibliographyUrl(researchId, 'bibtex', sources), 'BibTeX (.bib)', t('BibTeX file of the {label} (LaTeX, Zotero, JabRef)', { label }))}
      {link(bibliographyUrl(researchId, 'ris', sources), 'RIS (.ris)', t('RIS file of the {label} (Zotero, EndNote, Mendeley)', { label }))}
    </DropdownMenuGroup>
  }
  return <DropdownMenu>
    <DropdownMenuTrigger render={<Button variant="default" size="sm" className="research-export" />}><Download size={14} aria-hidden />{t('Export')}<ChevronDown size={13} aria-hidden /></DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="research-export-menu w-auto">
      {included && bibliography('included')}
      {cited && bibliography('cited')}
      {prisma && <DropdownMenuGroup>
        <DropdownMenuLabel className="research-export-label">{t('Search report (PRISMA-S)')}</DropdownMenuLabel>
        {link(prismaSUrl(researchId, 'md'), 'Markdown (.md)', t('The search reported against the 16 PRISMA-S items, as Markdown'))}
        {link(prismaSUrl(researchId, 'json'), 'JSON (.json)', t('The search reported against the 16 PRISMA-S items, as JSON'))}
      </DropdownMenuGroup>}
    </DropdownMenuContent>
  </DropdownMenu>
}
