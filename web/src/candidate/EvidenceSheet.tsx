import { useCallback, useEffect, useState } from 'react'
import { CircleX, FileSearch } from 'lucide-react'
import { api, type CandidateCard, type CandidateEvidence, type CandidateHit, type CandidateMatrix } from '../api'
import { HighlightedPassageText } from '../PassageSheet'
import { SourceKey } from '../SourceKey'
import { ConnectionIcon as ProviderIcon } from '../connectionIcons'
import { pageLocator, versionText } from '../labels'
import { StackPanel } from '../research/SplitPanel'
import { t } from '../i18n'
import { alignmentLabels, depthLabels, errorText, label, relationLabels, relationTones } from './labels'
import { HitOutcome } from './SearchMatrix'

// The evidence one search supplied for one kept work (mockup `candEvPanel`, P36), stacked on the candidate: the
// passages frozen with the search with the located quotes marked, then each element's reading and its quote. These are
// the passages that search read, not the source as it is now; whether a quote supports its element was not checked.
export function EvidencePanel({ researchId, card, matrix, hit, sourceKey, dark, onOpenSource, onClose }: {
  researchId: string; card: CandidateCard; matrix: CandidateMatrix; hit: CandidateHit; sourceKey?: string | null; dark: boolean
  onOpenSource?: () => void; onClose: () => void
}) {
  const [evidence, setEvidence] = useState<CandidateEvidence | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const load = useCallback(() => api.candidateHit(researchId, card.id, matrix.kill_search_id, hit.source_version_id), [researchId, card.id, matrix.kill_search_id, hit.source_version_id])
  useEffect(() => { let live = true; load().then(next => { if (live) { setEvidence(next); setError('') } }, e => { if (live) setError(errorText(e)) }); return () => { live = false } }, [load, retry, hit.assessment_state])
  const elements = card.versions.find(v => v.id === matrix.candidate_version_id)?.elements ?? []
  const cells = matrix.cells[hit.source_version_id] ?? {}
  return <StackPanel name="cev" open onClose={onClose} title={t('Candidate evidence')} icon={FileSearch} className={`mk-detail-box candidate-evidence-box${dark ? ' dark' : ''}`}>
    <div className="candidates-view candidate-evidence mk pad detail">
      <div className="dhead"><div className="venue">{t('Evidence supplied to this search')} · {t('Version {n}', { n: matrix.version })} · {label(depthLabels, hit.reading_depth)}</div><h1 data-stored-text>{evidence?.source.title ?? hit.source.title}</h1></div>
      {error && <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{error}</span><div className="acts"><button type="button" className="ghost" onClick={() => setRetry(n => n + 1)}>{t('Retry')}</button></div></div></div>}
      {!evidence && !error && <p role="status" className="foot-note"><span className="shimmer-text">{t('Loading evidence…')}</span></p>}
      {evidence && <>
        <p className="dmeta">{sourceKey && <span><SourceKey value={sourceKey} /></span>}{evidence.source.year && <span>{evidence.source.year}</span>}{evidence.source.venue && <span data-stored-text>{evidence.source.venue}</span>}<span>{versionText(evidence.source.version_label)}</span></p>
        {evidence.source.doi && <div className="rowacts"><a href={`https://doi.org/${evidence.source.doi.replace(/^https?:\/\/doi.org\//, '')}`} target="_blank" rel="noreferrer"><ProviderIcon id="doi" />{t('DOI')} <span data-stored-text>{evidence.source.doi}</span></a></div>}
        <h4 className="sub">{t(evidence.passages.length === 1 ? 'Passage supplied (frozen with the search)' : 'Passages supplied (frozen with the search) · {n}', { n: evidence.passages.length })}</h4>
        {evidence.passages.length ? <>{evidence.passages.map(passage => {
          const quotes = evidence.quotes.filter(q => q.evidence_kind === 'abstract' ? passage.locator.kind === 'abstract' : q.passage_id === passage.passage_id)
          return <div key={passage.passage_id}><div className="quote candidate-passage" data-stored-text><HighlightedPassageText passage={{ text: passage.text, kind: passage.locator.kind === 'abstract' ? 'abstract' : 'pdf_page' }} highlightTexts={quotes.map(q => q.quote).filter(quote => quote.length > 0 && passage.text.includes(quote))} markLabel={t('Text located for the stored quote')} /></div>
            <p className="loc"><span>{passage.locator.kind === 'abstract' ? t('abstract') : passage.locator.physical_page ? pageLocator(passage.locator.physical_page, passage.text_source === 'europepmc_rendition', passage.locator.printed_label) : t('Stored passage')}</span></p></div>
        })}<p className="foot-note">{t('These are the exact passages the model was given. Nothing else of this work was read.')}</p></> : <><p className="foot-note">{t('No assessed passages are stored for this work')}</p><HitOutcome hit={hit} matrix={matrix} /></>}
        {(Object.keys(cells).length > 0 || evidence.quotes.some(q => q.element_id)) && <><h4 className="sub">{t('Element-level readings')}</h4><ul className="elist">{elements.map((element, i) => {
          const cell = cells[element.id]
          const quotes = evidence.quotes.filter(q => q.element_id === element.id)
          return <li key={element.id}><b>E{i + 1}</b><span>{cell ? <><span className={`rel ${relationTones[cell.relation] ?? 'none'}`}>{label(relationLabels, cell.relation)}</span>{cell.condition_alignment && <> · {label(alignmentLabels, cell.condition_alignment)}</>}</> : t('No cell was recorded for this element.')}
            {quotes.length ? quotes.map(quote => <small key={quote.id}>{t('Quote:')} “<span data-stored-text>{quote.quote}</span>” · {marked(evidence, quote) ? t('located in the supplied passage') : t('located in the text shown to the model; not marked: shown separately')}</small>) : <small>{t('No quote recorded for this element.')}</small>}</span></li>
        })}</ul></>}
        {evidence.quotes.some(q => !q.element_id) && <><h4 className="sub">{t('For the whole claim')}</h4>{evidence.quotes.filter(q => !q.element_id).map(quote => <div key={quote.id}><blockquote className="quote" data-stored-text>{quote.quote}</blockquote><p className="loc"><span>{marked(evidence, quote) ? t('located in the supplied passage') : t('located in the text shown to the model; not marked: shown separately')}</span></p></div>)}</>}
        <p className="foot-note">{t('These are the passages this search read, not the source as it is now. Whether a quote supports its element was not checked.')}{onOpenSource && <> <button type="button" className="link" onClick={onOpenSource}>{t('Open the source')}</button></>}</p>
      </>}
    </div>
  </StackPanel>
}

const marked = (evidence: CandidateEvidence, quote: CandidateEvidence['quotes'][number]) => evidence.passages.some(p => (quote.evidence_kind === 'abstract' ? p.locator.kind === 'abstract' : p.passage_id === quote.passage_id) && quote.quote.length > 0 && p.text.includes(quote.quote))
