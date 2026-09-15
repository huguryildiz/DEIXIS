import { useEffect, useState } from 'react'
import { FileText, Fingerprint, Link2, MapPin, Maximize2, Minimize2, Quote, ScanText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, assetUrl, type Passage } from './api'
import { locatorText, versionText } from './labels'
import { t, uiLocale } from './i18n'
import { PassageMathText } from './PassageMathText'

export function PassageSheet({ researchId, passageId, highlightText, dark, onClose }: { researchId: string; passageId: string | null; highlightText?: string | null; dark: boolean; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [error, setError] = useState('')
  const [showPdf, setShowPdf] = useState(false)
  const [full, setFull] = useState(false)
  const [allAuthors, setAllAuthors] = useState(false)

  useEffect(() => {
    if (!passageId) return
    let cancelled = false
    setPassage(null)
    setError('')
    setShowPdf(false)
    setAllAuthors(false)
    api.passage(researchId, passageId).then(p => { if (!cancelled) setPassage(p) }).catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [researchId, passageId])

  const source = passage?.source
  const abstract = passage?.kind === 'abstract'
  return <Sheet open={passageId !== null} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet source-sheet ${full ? 'is-full' : showPdf ? 'is-expanded' : ''} ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>{t('Source details')}</SheetTitle>
        <Button variant="ghost" size="icon-sm" className="sheet-expand" aria-label={t(full ? 'Collapse panel' : 'Expand to full page')} title={t(full ? 'Collapse panel' : 'Expand to full page')} onClick={() => setFull(v => !v)}>{full ? <Minimize2 /> : <Maximize2 />}</Button><SheetDescription className="sr-only">{passage ? t('Cited passage: {locator}', { locator: locatorText(passage) }) : t(error ? 'Unavailable' : 'Loading passage…')}</SheetDescription></SheetHeader>
      <div className="sheet-body">
        {error && <div className="legacy-boundary">{error}</div>}
        {!passage && !error && <p>{t('Loading passage…')}</p>}
        {passage && source && <>
          <h2 className="source-title">{source.title}</h2>
          {source.authors.length > 0 && <p className="source-byline">{source.authors.length > 3 && !allAuthors
            ? <>{source.authors.slice(0, 2).join(', ')}, <button className="author-more" onClick={() => setAllAuthors(true)}>{t('and {n} more', { n: source.authors.length - 2 })}</button></>
            : source.authors.join(', ')}</p>}
          <p className="source-byline">{[source.venue, source.year, source.version_label ? versionText(source.version_label) : t('version not stated by the provider'), source.origin === 'user_upload' && t('uploaded by you')].filter(Boolean).join(' · ')}</p>
          <div className="source-chips">
            {source.doi ? <a className="source-chip" href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><Link2 size={15} />DOI</a>
              : source.landing_url && <a className="source-chip" href={source.landing_url} target="_blank" rel="noreferrer"><Link2 size={15} />{t('Publisher page')}</a>}
            <span className="source-access"><FileText size={15} />{t(abstract ? 'Abstract only' : 'PDF text passage')}</span>
          </div>
          {passage.asset_id && passage.physical_page && <Button variant="outline" className="pdf-toggle" onClick={() => setShowPdf(v => !v)}><FileText />{showPdf ? t('Hide PDF page') : t('Open PDF page {n}', { n: passage.physical_page })}</Button>}
          {showPdf && passage.asset_id && <iframe className="pdf-frame" title={t('PDF page {n}', { n: passage.physical_page ?? '' })} src={assetUrl(researchId, passage.asset_id, passage.physical_page, highlightText)} />}

          <h3 className="source-section">{abstract ? t('Abstract') : t('Cited passage · {locator}', { locator: locatorText(passage) })}</h3>
          {/* PDF extraction keeps layout line breaks; join single breaks for reading. The stored passage is unchanged. */}
          <p className="passage-text"><PassageMathText text={passage.kind === 'pdf_page' ? passage.text.replace(/(?<!\n)\n(?!\n)/g, ' ') : passage.text} /></p>
          {passage.abstract_origin === 'provider_openalex_inverted_index' && <p className="source-fine">{t('Rebuilt from OpenAlex’s abstract index; wording and punctuation may differ from the publisher’s text.')}</p>}

          <dl className="source-facts">
            <dt><MapPin size={14} aria-hidden />{t('Location')}</dt><dd>{abstract ? t('Abstract · no page or full-text reading') : locatorText(passage)}{passage.payload_ref?.startsWith('chars:') ? ` ${t('· text span {span}', { span: passage.payload_ref.slice(6) })}` : ''}</dd>
            {passage.extraction_version && <><dt><ScanText size={14} aria-hidden />{t('Extraction')}</dt><dd>{t('{version} · no OCR', { version: passage.extraction_version })}</dd></>}
            {source.doi && <><dt><Fingerprint size={14} aria-hidden />{t('Identifier')}</dt><dd>doi:{source.doi}</dd></>}
            {source.cited_by_count !== null && <><dt><Quote size={14} aria-hidden />{t('Citations')}</dt><dd>{source.cited_by_count.toLocaleString(uiLocale())} · OpenAlex{source.cited_by_count_at ? `, ${source.cited_by_count_at.slice(0, 10)}` : ''}</dd></>}
          </dl>
          <p className="panel-note">{t('This shows where the citation points. Whether the passage supports the claim has not been checked by DEIXIS.')}</p>
        </>}
      </div>
    </SheetContent>
  </Sheet>
}
