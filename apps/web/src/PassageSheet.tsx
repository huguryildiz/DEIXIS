import { Fragment, useEffect, useRef, useState } from 'react'
import { BadgeCheck, BookOpenText, ExternalLink, FileText, Info, Link2, ListMinus, Maximize2, Minimize2, RotateCcw, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, assetUrl, type AssetText, type Passage, type Source } from './api'
import { locatorText, providerName, versionText, versionTones } from './labels'
import { t, uiLocale } from './i18n'
import { PassageMathText } from './PassageMathText'
import { ConnectionIcon } from './connectionIcons'
import { PdfViewer } from './PdfViewer'

function readablePassageText(kind: Passage['kind'], text: string) {
  // Keep paragraph breaks, but undo the single line breaks introduced by PDF layout extraction.
  return kind === 'pdf_page' ? text.replace(/(?<!\n)\n(?!\n)/g, ' ') : text
}

// Reading aids for extracted PDF text (D47): section headings stand out and author affiliation notes are folded away.
const SECTION_HEADING = /^(?:(?:[IVXL]+|\d+(?:\.\d+)*|[A-H])\.?\s+[A-Z][^.]{1,76}|Abstract|References|Acknowledge?ments?|Appendix)$/
const AUTHOR_NOTE = /\b(?:is|are) with the\b|\be-?mail:|^Corresponding author|^Manuscript received|^This work was (?:supported|funded)/i

function pagesOf(passages: AssetText['passages']) {
  const pages: AssetText['passages'][] = []
  for (const item of passages) {
    const last = pages[pages.length - 1]
    if (last && last[0].physical_page === item.physical_page) last.push(item)
    else pages.push([item])
  }
  return pages
}

function PdfPageText({ passages, showNotes }: { passages: AssetText['passages']; showNotes: boolean }) {
  // Passages are cut at a fixed length; a cut that did not end a sentence, or one inside a reference entry, continues the paragraph.
  const text = passages.map(item => readablePassageText(item.kind, item.text)).reduce((all, next) => {
    const last = all.slice(all.lastIndexOf('\n\n') + 1).trim()
    const continues = !/[.:?!)]$/.test(last) || (/^\[\d{1,4}\]\s/.test(last) && !/^\[\d{1,4}\]\s/.test(next))
    return !all ? next : continues ? `${all} ${next}` : `${all}\n\n${next}`
  }, '')
  const paragraphs = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
  return <>{paragraphs.map((paragraph, index) => SECTION_HEADING.test(paragraph)
    ? <h5 key={index} className="pdf-text-heading">{paragraph}</h5>
    : AUTHOR_NOTE.test(paragraph)
      ? showNotes && <p key={index} className="passage-text pdf-text-note"><PassageMathText text={paragraph} /></p>
      : <p key={index} className="passage-text"><PassageMathText text={paragraph} /></p>)}</>
}

// Marks every located anchor; overlapping anchors are merged into one mark, and the first mark is scrolled into view.
function HighlightedPassageText({ passage, highlightTexts }: { passage: Passage; highlightTexts: string[] }) {
  const highlightRef = useRef<HTMLElement>(null)
  const ranges: [number, number][] = []
  for (const [start, end] of highlightTexts.map(text => [passage.text.indexOf(text), passage.text.indexOf(text) + text.length]).filter(([start]) => start >= 0).sort((a, b) => a[0] - b[0])) {
    const last = ranges[ranges.length - 1]
    if (last && start <= last[1]) last[1] = Math.max(last[1], end)
    else ranges.push([start, end])
  }
  const first = ranges[0]?.[0] ?? -1

  useEffect(() => {
    if (first < 0) return
    const frame = requestAnimationFrame(() => highlightRef.current?.scrollIntoView({ block: 'center' }))
    return () => cancelAnimationFrame(frame)
  }, [passage, first])

  if (!ranges.length) return <PassageMathText text={readablePassageText(passage.kind, passage.text)} />

  return <>
    {ranges.map(([start, end], i) => <Fragment key={start}>
      <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(i ? ranges[i - 1][1] : 0, start))} />
      <mark ref={i === 0 ? highlightRef : undefined} className="citation-highlight" aria-label={t('Exact text cited in the answer')}>
        <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(start, end))} />
      </mark>
    </Fragment>)}
    <PassageMathText text={readablePassageText(passage.kind, passage.text.slice(ranges[ranges.length - 1][1]))} />
  </>
}

// pdfRemoved: the passage's PDF was removed from the source; its stored text still opens, the PDF view stays off.
// A passage also reports this itself (evidence_status, D45), as it does a replaced file or an earlier text extraction.
// sources: the research's source rows; the one matching the opened source adds its screening state, similarity and citation.
// onRestoreSource: offered when the passage's source was removed from this research (D50).
export function PassageSheet({ researchId, passageId, assetId = null, initialView = 'text', highlightText, highlightTexts, expectHighlight = false, pdfRemoved = false, sources, dark, onClose, onRestoreSource }: { researchId: string; passageId: string | null; assetId?: string | null; initialView?: 'text' | 'pdf'; highlightText?: string | null; highlightTexts?: string[]; expectHighlight?: boolean; pdfRemoved?: boolean; sources?: Source[]; dark: boolean; onClose: () => void; onRestoreSource?: (sourceVersionId: string) => void }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [assetText, setAssetText] = useState<AssetText | null>(null)
  const [error, setError] = useState('')
  const [full, setFull] = useState(false)
  const [allAuthors, setAllAuthors] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [viewMode, setViewMode] = useState<'text' | 'pdf'>(initialView)

  useEffect(() => {
    if (!passageId && !assetId) return
    let cancelled = false
    setPassage(null)
    setAssetText(null)
    setError('')
    setAllAuthors(false)
    setViewMode(initialView)
    const request = passageId
      ? api.passage(researchId, passageId).then(p => { if (!cancelled) setPassage(p) })
      : api.assetText(researchId, assetId!).then(value => { if (!cancelled) setAssetText(value) })
    request.catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [researchId, passageId, assetId, initialView])

  const source = passage?.source ?? assetText?.source
  const abstract = passage?.kind === 'abstract'
  const highlights = highlightTexts ?? (highlightText ? [highlightText] : [])
  const highlightAvailable = Boolean(passage && highlights.length && highlights.every(text => passage.text.includes(text)))
  const status = passage?.evidence_status ?? 'current'
  const removed = pdfRemoved || status === 'pdf_removed'
  const pdfAssetId = removed ? null : passage?.asset_id ?? assetText?.asset.id ?? null
  const row = source ? sources?.find(s => s.source_version_id === source.id) : undefined
  const selectionText = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' } as const
  return <Sheet open={passageId !== null || assetId !== null} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet source-sheet ${full ? 'is-full' : ''} ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>{t('Source details')}</SheetTitle>
        <Button variant="ghost" size="icon-sm" className="sheet-expand" aria-label={t(full ? 'Collapse panel' : 'Expand to full page')} title={t(full ? 'Collapse panel' : 'Expand to full page')} onClick={() => setFull(v => !v)}>{full ? <Minimize2 /> : <Maximize2 />}</Button><SheetDescription className="sr-only">{passage ? t('Cited passage: {locator}', { locator: locatorText(passage) }) : assetText ? t('PDF source') : t(error ? 'Unavailable' : 'Loading passage…')}</SheetDescription></SheetHeader>
      <div className="sheet-body">
        {error && <div className="legacy-boundary">{error}</div>}
        {!passage && !assetText && !error && <p>{t(assetId ? 'Loading PDF text…' : 'Loading passage…')}</p>}
        {(passage || assetText) && source && <>
          {(source.venue || source.year) && <p className="source-venue">{source.venue && <i>{source.venue}</i>}{source.venue && source.year && <span aria-hidden className="source-dot" />}{source.year}</p>}
          <h2 className="source-title">{source.title}</h2>
          {source.authors.length > 0 && <p className="source-byline">{source.authors.length > 3 && !allAuthors
            ? <>{source.authors.slice(0, 2).join(', ')}, <button className="author-more" onClick={() => setAllAuthors(true)}>{t('and {n} more', { n: source.authors.length - 2 })}</button></>
            : source.authors.join(', ')}</p>}
          <div className="source-chips">
            <span className={`ref-pill is-${versionTones[source.version_label ?? ''] ?? 'unstated'}`}><BadgeCheck size={12} aria-hidden />{source.version_label ? versionText(source.version_label) : t('version not stated by the provider')}</span>
            {assetText ? <span className="ref-pill is-text"><FileText size={12} aria-hidden />{t(assetText.passages.length ? 'PDF with extracted text' : 'PDF without extracted text')}</span>
              : abstract ? <span className="ref-pill is-abstract"><BookOpenText size={12} aria-hidden />{t('Abstract only')}</span>
              : <span className="ref-pill is-text"><FileText size={12} aria-hidden />{t('PDF text passage')}</span>}
            {source.origin === 'user_upload' && <span className="ref-pill">{t('uploaded by you')}</span>}
            {source.doi ? <a className="source-link-chip" href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer" title={t('Open DOI')}><ConnectionIcon id="doi" /><span>{source.doi}</span><ExternalLink size={12} aria-hidden /></a>
              : source.landing_url && <a className="source-link-chip" href={source.landing_url} target="_blank" rel="noreferrer"><Link2 size={13} aria-hidden /><span>{t('Publisher page')}</span><ExternalLink size={12} aria-hidden /></a>}
          </div>
          {row && <dl className="source-role">
            <div><dt>{t('Screening')}</dt><dd>{t(selectionText[row.selection.state])}</dd></div>
            <div><dt>{t('Similarity')}</dt><dd title={t('Used for ordering only; it is not a relevance judgment.')}>{row.similarity === null ? '—' : row.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd></div>
            <div><dt>{t('Latest answer')}</dt><dd>{t(row.cited_in_latest_answer ? 'Cited' : 'Not cited')}</dd></div>
          </dl>}
          <div className="source-view-tabs" role="tablist" aria-label={t('Source view')}>
            <button type="button" role="tab" aria-selected={viewMode === 'text'} aria-controls="source-text-view" onClick={() => setViewMode('text')}>{t(abstract ? 'Abstract' : 'Plain text')}</button>
            <button type="button" role="tab" aria-selected={viewMode === 'pdf'} aria-controls="source-pdf-view" disabled={!pdfAssetId} title={!pdfAssetId ? t(removed ? 'The PDF was removed from this source; its passages still open as text.' : 'PDF is not available for this source.') : undefined} onClick={() => setViewMode('pdf')}>PDF</button>
          </div>
          {passage?.removed_from_research && <p className="source-notice is-removed"><ListMinus size={15} aria-hidden /><span>{t('This source was removed from this research. Its passages still open where this research cites them; it is not listed or given to new answers and cells.')}
            {onRestoreSource && <> <button type="button" className="source-notice-action" onClick={() => onRestoreSource(passage.source.id)}><RotateCcw size={13} aria-hidden />{t('Restore to this research')}</button></>}</span></p>}
          {passage && status !== 'current' && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{status === 'pdf_replaced'
            ? t('This passage comes from a PDF that was later replaced. It opens the previous file, which is no longer read in new answers or cells.')
            : status === 'pdf_removed' ? t('This passage comes from a PDF that was removed from the source. Its stored text still opens; the PDF view is off.')
            : t('This passage comes from an earlier text extraction ({version}). New answers and cells read the current extraction, which may split or word the page differently.', { version: passage.extraction_version ?? '?' })}</p>}
          {viewMode === 'text' && passage?.text_source === 'marker' && (passage.equations_to_check
            ? <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(passage.equations_to_check === 1 ? 'Page read from the page image (Marker). {n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : 'Page read from the page image (Marker). {n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: passage.equations_to_check })}</p>
            : <p className="source-notice"><Info size={15} aria-hidden />{t('Page read from the page image (Marker). Equations are LaTeX; check them against the PDF page.')}</p>)}
          {viewMode === 'text' ? passage ? <div id="source-text-view" role="tabpanel">
            {abstract && !pdfAssetId && <p className="source-notice"><Info size={15} aria-hidden />{t('No PDF is attached, so only the abstract can be inspected. Claims citing this source rest on the abstract alone.')}</p>}
            <h3 className="source-section">{abstract ? t('Abstract') : t('Cited passage · {locator}', { locator: locatorText(passage) })}</h3>
            {expectHighlight && !highlightAvailable && <div className="citation-highlight-note">{t('This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.')}</div>}
            <p className="passage-text"><HighlightedPassageText passage={passage} highlightTexts={highlights} /></p>
          </div> : assetText ? <div id="source-text-view" role="tabpanel" className="asset-text-view">
            <h3 className="source-section">{t('Extracted PDF text')}{assetText.passages.some(item => item.text.split(/\n{2,}/).some(p => AUTHOR_NOTE.test(p.trim()))) && <button type="button" className="pdf-text-notes-toggle" onClick={() => setShowNotes(v => !v)}>{t(showNotes ? 'Hide author notes' : 'Show author notes')}</button>}</h3>
            {assetText.passages.length ? pagesOf(assetText.passages).map(page => <section className="pdf-text-page" key={page[0].id}>
              <h4>{page[0].physical_page ? t('PDF p. {page}', { page: page[0].physical_page }) : t('Extracted text')}</h4>
              {(page[0].equations_to_check ?? 0) > 0 && <p className="source-notice"><TriangleAlert size={15} aria-hidden />{t(page[0].equations_to_check === 1 ? '{n} equation on this page does not match the PDF’s own text and may be misread; check it against the PDF page.' : '{n} equations on this page do not match the PDF’s own text and may be misread; check them against the PDF page.', { n: page[0].equations_to_check ?? 0 })}</p>}
              <PdfPageText passages={page} showNotes={showNotes} />
            </section>) : <div className="legacy-boundary">{t('No text was extracted from this PDF.')}</div>}
          </div> : null : pdfAssetId && <div id="source-pdf-view" role="tabpanel" className="source-pdf-view">
            <PdfViewer url={assetUrl(researchId, pdfAssetId)} initialPage={passage?.physical_page ?? 1} title={source.title} />
          </div>}
        </>}
      </div>
      {row && (passage || assetText) && <footer className="source-sheet-foot">
        {row.provider_records.length > 0 && <span>{t('Found via')} {row.provider_records.map((id, i) => <Fragment key={id}>{i > 0 && ', '}<b>{providerName(id)}</b></Fragment>)}</span>}
        {row.added_at && <span>{t(row.origin === 'user_upload' ? 'Uploaded {date}' : 'Added {date}', { date: new Date(row.added_at).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short', year: 'numeric' }) })}</span>}
      </footer>}
    </SheetContent>
  </Sheet>
}
