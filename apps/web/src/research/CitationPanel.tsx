import { useEffect, useState } from 'react'
import { AlignLeft, FileText, Link, Search } from 'lucide-react'
import { api, type Claim, type Evidence, type Passage, type Source } from '../api'
import { locatorText, verdictLabels, versionText } from '../labels'
import { t } from '../i18n'
import { HighlightedPassageText } from '../PassageSheet'
import { StackPanel } from './SplitPanel'

// The Citation panel (mockup `citation()`, P11): what one claim of the answer cites, one entry per cited passage, each
// with its work, the quote around the backend-located anchor, where it sits and how the claim was reviewed. From an
// entry the passage opens in Source details at its anchor (the text, or the PDF page); a work without a PDF offers
// Find PDF there. Nothing here is recomputed: the passage, its anchor and the review are the answer's stored records.

// The passage text around the anchor: a page is long, so the quote shows about two sentences on each side of it.
const CONTEXT = 240
function excerpt(text: string, anchor: string | null): { text: string; located: boolean } {
  const at = anchor ? text.indexOf(anchor) : -1
  if (at < 0) return { text: text.length > 2 * CONTEXT ? `${text.slice(0, 2 * CONTEXT).trimEnd()}…` : text, located: false }
  let start = Math.max(0, at - CONTEXT), end = Math.min(text.length, at + anchor!.length + CONTEXT)
  if (start > 0) { const space = text.indexOf(' ', start); start = space >= 0 && space < at ? space + 1 : at }
  if (end < text.length) { const space = text.lastIndexOf(' ', end); end = space > at + anchor!.length ? space : at + anchor!.length }
  return { text: `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`, located: true }
}

export type CitationOpen = { passageId: string; anchor: string | null; view: 'text' | 'pdf'; find?: boolean }

function CitationEntry({ researchId, evidence, claim, source, onOpen }: { researchId: string; evidence: Evidence; claim: Claim; source: Source | undefined; onOpen: (target: CitationOpen) => void }) {
  const [passage, setPassage] = useState<Passage | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    api.passage(researchId, evidence.passage_id).then(value => { if (live) setPassage(value) }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [researchId, evidence.passage_id])
  const work = passage?.source
  const quote = passage ? excerpt(passage.text, evidence.anchor_text) : null
  const abstract = evidence.kind === 'abstract'
  // The PDF view opens the page the passage was read from; an abstract has no page, a removed file no view.
  const pdf = !abstract && passage?.asset_id && evidence.evidence_status !== 'pdf_removed'
  const findable = abstract && source && !source.access.assets.length && source.doi && !evidence.removed_from_research
  const authors = work?.authors ?? []
  const open = (view: 'text' | 'pdf', find = false) => onOpen({ passageId: evidence.passage_id, anchor: evidence.anchor_text, view, find })
  return <article className="cite-entry">
    <div className="venue"><FileText size={13} aria-hidden />{[work?.venue, work?.year].filter(Boolean).join(', ') || t('Venue not stated')}</div>
    <h3><button type="button" onClick={() => open('text')}>{work?.title ?? evidence.title}</button></h3>
    {authors.length > 0 && <div className="au">{authors.length > 6 ? `${authors.slice(0, 6).join(', ')}, ${t('and {n} more', { n: authors.length - 6 })}` : authors.join(', ')}</div>}
    {error ? <p className="quote">{error}</p> : quote ? <div className="quote">
      <HighlightedPassageText passage={{ text: quote.text, kind: passage!.kind }} highlightTexts={quote.located && evidence.anchor_text ? [evidence.anchor_text] : []} scroll={false} />
    </div> : <p className="quote">{t('Loading passage…')}</p>}
    {/* Its parts with the mockup's own "·" between them (a separate element, as in `.loc`). */}
    <div className="loc">
      {[<span key="at">{(l => l.charAt(0).toUpperCase() + l.slice(1))(locatorText(evidence))}</span>,
        <span key="version">{versionText(evidence.version_label)}</span>,
        quote && (quote.located ? <span key="anchor" className="ok-t">{t('Located in the passage')}</span> : <span key="anchor" className="warn-t">{t('No located anchor: the passage opens without a mark')}</span>),
        claim.review && <span key="review">{t('Reviewer: {reason}', { reason: t(verdictLabels[claim.review.verdict]) })}</span>,
      ].filter(Boolean).flatMap((part, i) => (i ? [<span key={`dot${i}`} className="loc-dot" aria-hidden="true">·</span>, part] : [part]))}
    </div>
    <div className="rowacts">
      <button type="button" onClick={() => open('text')}><AlignLeft size={14} aria-hidden />{t(abstract ? 'Open the abstract' : 'Open in the full text')}</button>
      {pdf && <button type="button" onClick={() => open('pdf')}><FileText size={14} aria-hidden />{t('Show in the PDF')}</button>}
      {findable && <button type="button" onClick={() => open('text', true)}><Search size={14} aria-hidden />{t('Find PDF')}</button>}
    </div>
  </article>
}

export function CitationPanel({ researchId, claim, sources, onClose, onOpen }: { researchId: string; claim: Claim | null; sources: Source[]; onClose: () => void; onOpen: (target: CitationOpen) => void }) {
  return <StackPanel name="cite" open={Boolean(claim)} onClose={onClose} title={t('Citation')} icon={Link} className="cite-panel">
    {claim && <div className="cit">
      <p className="sr-only">{t('What this claim cites: {claim}', { claim: claim.text })}</p>
      {claim.evidence.map(e => <CitationEntry key={e.passage_id} researchId={researchId} evidence={e} claim={claim} source={sources.find(s => s.source_version_id === e.source_version_id)} onOpen={onOpen} />)}
    </div>}
  </StackPanel>
}
