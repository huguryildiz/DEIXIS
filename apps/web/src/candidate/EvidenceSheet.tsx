import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, type CandidateCard, type CandidateEvidence, type CandidateHit, type CandidateMatrix } from '../api'
import { HighlightedPassageText } from '../PassageSheet'
import { Notice } from '../Notice'
import { SourceKey } from '../SourceKey'
import { ConnectionIcon as ProviderIcon } from '../connectionIcons'
import { pageLocator, versionText } from '../labels'
import { t } from '../i18n'
import { alignmentLabels, depthLabels, errorText, label, relationLabels } from './labels'
import { HitOutcome } from './SearchMatrix'

export function EvidenceSheet({ researchId, card, matrix, hit, sourceKey, dark, returnFocus, onClose }: {
  researchId: string; card: CandidateCard; matrix: CandidateMatrix; hit: CandidateHit; sourceKey?: string | null; dark: boolean
  returnFocus: RefObject<HTMLElement | null>; onClose: () => void
}) {
  const [evidence, setEvidence] = useState<CandidateEvidence | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const load = useCallback(() => api.candidateHit(researchId, card.id, matrix.kill_search_id, hit.source_version_id), [researchId, card.id, matrix.kill_search_id, hit.source_version_id])
  useEffect(() => { let live = true; load().then(next => { if (live) { setEvidence(next); setError('') } }, e => { if (live) setError(errorText(e)) }); return () => { live = false } }, [load, retry, hit.assessment_state])
  const elements = card.versions.find(v => v.id === matrix.candidate_version_id)?.elements ?? []
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet evidence-sheet candidate-evidence ${dark ? 'dark' : ''}`} initialFocus={heading} finalFocus={returnFocus}>
    <SheetHeader><SheetTitle ref={heading} tabIndex={-1}>{t('Evidence shown to the model')}</SheetTitle><SheetDescription>{t('Located text for this work and this search.')}</SheetDescription></SheetHeader>
    <div className="sheet-body">
      {error && <Notice tone="error">{error}<Button variant="ghost" onClick={() => setRetry(n => n + 1)}>{t('Retry')}</Button></Notice>}
      {!evidence && !error && <p role="status">{t('Loading evidence…')}</p>}
      {evidence && <><SourceKey value={sourceKey} /><h3 className="candidate-claim" data-stored-text>{evidence.source.title}</h3><p>{evidence.source.year} <span data-stored-text>{evidence.source.venue}</span></p>
        {evidence.source.doi && <a className="ref-pill is-unstated" href={`https://doi.org/${evidence.source.doi.replace(/^https?:\/\/doi.org\//, '')}`} target="_blank" rel="noreferrer"><ProviderIcon id="doi" />{t('DOI')} <span data-stored-text>{evidence.source.doi}</span></a>}
        <p>{versionText(evidence.source.version_label)}</p><p>{label(depthLabels, hit.reading_depth)}</p>
        <h3>{t('Passages')} · {evidence.passages.length}</h3>{evidence.passages.length ? <><p>{t('These are the exact passages the model was given. Nothing else of this work was read.')}</p><ol>{evidence.passages.map(passage => {
          const quotes = evidence.quotes.filter(q => q.evidence_kind === 'abstract' ? passage.locator.kind === 'abstract' : q.passage_id === passage.passage_id)
          return <li key={passage.passage_id}><p>{passage.locator.kind === 'abstract' ? t('abstract') : passage.locator.physical_page ? pageLocator(passage.locator.physical_page, passage.text_source === 'europepmc_rendition', passage.locator.printed_label) : t('Stored passage')}</p>
            <div className="candidate-passage" data-stored-text><HighlightedPassageText passage={{ text: passage.text, kind: passage.locator.kind === 'abstract' ? 'abstract' : 'pdf_page' }} highlightTexts={quotes.map(q => q.quote).filter(quote => quote.length > 0 && passage.text.includes(quote))} markLabel={t('Text located for the stored quote')} /></div></li>
        })}</ol></> : <><p>{t('No assessed passages are stored for this work')}</p><HitOutcome hit={hit} matrix={matrix} /></>}
        <h3>{t('Stored quotes')} · {evidence.quotes.length}</h3>{evidence.quotes.length ? <ol>{evidence.quotes.map(quote => {
          const cell = quote.element_id ? matrix.cells[hit.source_version_id]?.[quote.element_id] : null
          const marked = evidence.passages.some(p => (quote.evidence_kind === 'abstract' ? p.locator.kind === 'abstract' : p.passage_id === quote.passage_id) && quote.quote.length > 0 && p.text.includes(quote.quote))
          return <li key={quote.id}><p>{quote.element_id ? <>{t('For element:')} <span data-stored-text>{elements.find(e => e.id === quote.element_id)?.text ?? quote.element_id}</span></> : t('For the whole claim')}</p><blockquote data-stored-text>{quote.quote}</blockquote>
            {cell && <p>{label(relationLabels, cell.relation)}{cell.condition_alignment && <> · {label(alignmentLabels, cell.condition_alignment)}</>}</p>}<p>{t('Located in the text shown to the model')}{!marked && <> · {t('not marked: shown separately')}</>}</p></li>
        })}</ol> : <p>{t('None.')}</p>}
      </>}
    </div><footer className="cell-foot"><p>{t('Semantic support not checked.')}</p><Button variant="outline" onClick={onClose}>{t('Close')}</Button></footer>
  </SheetContent></Sheet>
}
