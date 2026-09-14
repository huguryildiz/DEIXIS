import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, assetUrl, type Passage } from './api'
import { locatorText } from './labels'

export function PassageSheet({ researchId, passageId, dark, onClose }: { researchId: string; passageId: string | null; dark: boolean; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [error, setError] = useState('')
  const [showPdf, setShowPdf] = useState(false)

  useEffect(() => {
    if (!passageId) return
    let cancelled = false
    setPassage(null)
    setError('')
    setShowPdf(false)
    api.passage(researchId, passageId).then(p => { if (!cancelled) setPassage(p) }).catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [researchId, passageId])

  const source = passage?.source
  return <Sheet open={passageId !== null} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className={`detail-sheet legacy-inspector ${showPdf ? 'is-expanded' : ''} ${dark ? 'dark' : ''}`}>
      <SheetHeader><SheetTitle>Behind the citation</SheetTitle><SheetDescription>{passage ? locatorText(passage) : error ? 'Unavailable' : 'Loading passage…'}</SheetDescription></SheetHeader>
      <div className="sheet-body">
        {error && <div className="legacy-boundary">{error}</div>}
        {passage && source && <>
          <span className="evidence-status">{passage.kind === 'abstract' ? 'Abstract only · no page or full-text reading' : 'Retrieved PDF text passage'}</span>
          {/* PDF extraction keeps layout line breaks; join single breaks for reading. The stored passage is unchanged. */}
          <blockquote className="passage-text">{passage.kind === 'pdf_page' ? passage.text.replace(/(?<!\n)\n(?!\n)/g, ' ') : passage.text}</blockquote>
          {passage.abstract_origin === 'provider_openalex_inverted_index' && <p>Rebuilt from OpenAlex’s abstract index; wording and punctuation may differ from the publisher’s text.</p>}
          <dl>
            <dt>Publication</dt><dd>{source.title}</dd>
            <dt>Authors · year · venue</dt><dd>{[source.authors.slice(0, 4).join(', ') + (source.authors.length > 4 ? ' et al.' : ''), source.year, source.venue].filter(Boolean).join(' · ') || 'Not recorded'}</dd>
            <dt>Version</dt><dd>{source.version_label ?? 'Not stated by the provider'}{source.origin === 'user_upload' ? ' · uploaded by you' : ''}</dd>
            <dt>Location</dt><dd>{locatorText(passage)}{passage.payload_ref?.startsWith('chars:') ? ` · text span ${passage.payload_ref.slice(6)}` : ''}</dd>
            {passage.extraction_version && <><dt>Extraction</dt><dd>{passage.extraction_version} · no OCR</dd></>}
            {(source.doi || source.landing_url) && <><dt>Identifier</dt><dd>{source.doi ? <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer">doi:{source.doi}</a> : <a href={source.landing_url!} target="_blank" rel="noreferrer">Publisher page</a>}</dd></>}
          </dl>
          {passage.asset_id && passage.physical_page && <Button variant="outline" className="pdf-toggle" onClick={() => setShowPdf(v => !v)}>{showPdf ? 'Hide PDF page' : `Open PDF page ${passage.physical_page}`}</Button>}
          {showPdf && passage.asset_id && <iframe className="pdf-frame" title={`PDF page ${passage.physical_page}`} src={assetUrl(researchId, passage.asset_id, passage.physical_page)} />}
          <p className="panel-note">This shows where the citation points. Whether the passage supports the claim has not been checked by DEIXIS.</p>
        </>}
      </div>
    </SheetContent>
  </Sheet>
}
