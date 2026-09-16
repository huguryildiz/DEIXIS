import { Fragment, useEffect, useRef, useState } from 'react'
import { FileText, Fingerprint, Link2, MapPin, Maximize2, Minimize2, Quote, ScanText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, assetUrl, type AssetText, type Passage } from './api'
import { locatorText, versionText } from './labels'
import { t, uiLocale } from './i18n'
import { PassageMathText } from './PassageMathText'
import { ConnectionIcon } from './connectionIcons'
import { PdfViewer } from './PdfViewer'

function readablePassageText(kind: Passage['kind'], text: string) {
  // Keep paragraph breaks, but undo the single line breaks introduced by PDF layout extraction.
  return kind === 'pdf_page' ? text.replace(/(?<!\n)\n(?!\n)/g, ' ') : text
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
export function PassageSheet({ researchId, passageId, assetId = null, initialView = 'text', highlightText, highlightTexts, expectHighlight = false, pdfRemoved = false, dark, onClose }: { researchId: string; passageId: string | null; assetId?: string | null; initialView?: 'text' | 'pdf'; highlightText?: string | null; highlightTexts?: string[]; expectHighlight?: boolean; pdfRemoved?: boolean; dark: boolean; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [assetText, setAssetText] = useState<AssetText | null>(null)
  const [error, setError] = useState('')
  const [full, setFull] = useState(false)
  const [allAuthors, setAllAuthors] = useState(false)
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
  const pdfAssetId = pdfRemoved ? null : passage?.asset_id ?? assetText?.asset.id ?? null
  return <Sheet open={passageId !== null || assetId !== null} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet source-sheet ${full ? 'is-full' : ''} ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>{t('Source details')}</SheetTitle>
        <Button variant="ghost" size="icon-sm" className="sheet-expand" aria-label={t(full ? 'Collapse panel' : 'Expand to full page')} title={t(full ? 'Collapse panel' : 'Expand to full page')} onClick={() => setFull(v => !v)}>{full ? <Minimize2 /> : <Maximize2 />}</Button><SheetDescription className="sr-only">{passage ? t('Cited passage: {locator}', { locator: locatorText(passage) }) : assetText ? t('PDF source') : t(error ? 'Unavailable' : 'Loading passage…')}</SheetDescription></SheetHeader>
      <div className="sheet-body">
        {error && <div className="legacy-boundary">{error}</div>}
        {!passage && !assetText && !error && <p>{t(assetId ? 'Loading PDF text…' : 'Loading passage…')}</p>}
        {(passage || assetText) && source && <>
          <h2 className="source-title">{source.title}</h2>
          {source.authors.length > 0 && <p className="source-byline">{source.authors.length > 3 && !allAuthors
            ? <>{source.authors.slice(0, 2).join(', ')}, <button className="author-more" onClick={() => setAllAuthors(true)}>{t('and {n} more', { n: source.authors.length - 2 })}</button></>
            : source.authors.join(', ')}</p>}
          <p className="source-byline">{[source.venue, source.year, source.version_label ? versionText(source.version_label) : t('version not stated by the provider'), source.origin === 'user_upload' && t('uploaded by you')].filter(Boolean).join(' · ')}</p>
          <div className="source-chips">
            {source.doi ? <a className="source-chip" href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />DOI</a>
              : source.landing_url && <a className="source-chip" href={source.landing_url} target="_blank" rel="noreferrer"><Link2 size={15} />{t('Publisher page')}</a>}
            <span className="source-access"><FileText size={15} />{t(assetText ? (assetText.passages.length ? 'PDF with extracted text' : 'PDF without extracted text') : abstract ? 'Abstract only' : 'PDF text passage')}</span>
          </div>
          <div className="source-view-tabs" role="tablist" aria-label={t('Source view')}>
            <button type="button" role="tab" aria-selected={viewMode === 'text'} aria-controls="source-text-view" onClick={() => setViewMode('text')}>{t('Plain text')}</button>
            <button type="button" role="tab" aria-selected={viewMode === 'pdf'} aria-controls="source-pdf-view" disabled={!pdfAssetId} title={!pdfAssetId ? t(pdfRemoved ? 'The PDF was removed from this source; its passages still open as text.' : 'PDF is not available for this source.') : undefined} onClick={() => setViewMode('pdf')}>PDF</button>
          </div>
          {viewMode === 'text' ? passage ? <div id="source-text-view" role="tabpanel">
            <h3 className="source-section">{abstract ? t('Abstract') : t('Cited passage · {locator}', { locator: locatorText(passage) })}</h3>
            {expectHighlight && !highlightAvailable && <div className="citation-highlight-note">{t('This saved citation has no exact text anchor, so it cannot be highlighted. Generate a new answer to repair its citation anchors.')}</div>}
            <p className="passage-text"><HighlightedPassageText passage={passage} highlightTexts={highlights} /></p>
            {passage.abstract_origin === 'provider_openalex_inverted_index' && <p className="source-fine">{t('Rebuilt from OpenAlex’s abstract index; wording and punctuation may differ from the publisher’s text.')}</p>}

            <dl className="source-facts">
              <dt><MapPin size={14} aria-hidden />{t('Location')}</dt><dd>{abstract ? t('Abstract · no page or full-text reading') : locatorText(passage)}{passage.payload_ref?.startsWith('chars:') ? ` ${t('· text span {span}', { span: passage.payload_ref.slice(6) })}` : ''}</dd>
              {passage.extraction_version && <><dt><ScanText size={14} aria-hidden />{t('Extraction')}</dt><dd>{t('{version} · no OCR', { version: passage.extraction_version })}</dd></>}
              {source.doi && <><dt><Fingerprint size={14} aria-hidden />{t('Identifier')}</dt><dd>doi:{source.doi}</dd></>}
              {source.cited_by_count !== null && <><dt><Quote size={14} aria-hidden />{t('Citations')}</dt><dd>{source.cited_by_count.toLocaleString(uiLocale())} · OpenAlex{source.cited_by_count_at ? `, ${source.cited_by_count_at.slice(0, 10)}` : ''}</dd></>}
            </dl>
            <p className="panel-note">{t('This shows where the citation points. Whether the passage supports the claim has not been checked by DEIXIS.')}</p>
          </div> : assetText ? <div id="source-text-view" role="tabpanel" className="asset-text-view">
            <h3 className="source-section">{t('Extracted PDF text')}</h3>
            {assetText.passages.length ? assetText.passages.map((item, index) => <section className="pdf-text-page" key={item.id}>
              {(index === 0 || item.physical_page !== assetText.passages[index - 1]?.physical_page) && <h4>{item.physical_page ? t('PDF p. {page}', { page: item.physical_page }) : t('Extracted text')}</h4>}
              <p className="passage-text"><PassageMathText text={readablePassageText(item.kind, item.text)} /></p>
            </section>) : <div className="legacy-boundary">{t('No text was extracted from this PDF.')}</div>}
            <dl className="source-facts"><dt><MapPin size={14} aria-hidden />{t('Location')}</dt><dd>{t('{n} extracted pages', { n: assetText.asset.page_count ?? 0 })}</dd><dt><ScanText size={14} aria-hidden />{t('Extraction')}</dt><dd>{t(assetText.asset.extraction_status)} · {t('no OCR')}</dd></dl>
          </div> : null : pdfAssetId && <div id="source-pdf-view" role="tabpanel" className="source-pdf-view">
            <PdfViewer url={assetUrl(researchId, pdfAssetId)} initialPage={passage?.physical_page ?? 1} title={source.title} />
          </div>}
        </>}
      </div>
    </SheetContent>
  </Sheet>
}
