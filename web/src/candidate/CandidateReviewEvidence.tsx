import { useRef, type RefObject } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import type { ReviewDetail } from '../api'
import { HighlightedPassageText } from '../PassageSheet'
import { pageLocator } from '../labels'
import { t } from '../i18n'

export function CandidateReviewEvidence({ review, passageId, anchor, dark, returnFocus, onClose }: {
  review: ReviewDetail; passageId: string; anchor: string; dark: boolean; returnFocus: RefObject<HTMLElement | null>; onClose: () => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const passage = review.snapshot.passages?.find(p => p.passage_id === passageId)
  const source = review.snapshot.sources.find(s => s.source_id === passage?.source_id)
  // Only a published backend-located anchor can mark this frozen copy.
  const located = review.findings.some(f => f.finding.evidence.some(e => e.passage_id === passageId && e.anchor_text === anchor)) || review.supported_points.some(p => p.evidence.some(e => e.passage_id === passageId && e.anchor_text === anchor))
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet evidence-sheet candidate-evidence ${dark ? 'dark' : ''}`} initialFocus={heading} finalFocus={returnFocus}>
    <SheetHeader><SheetTitle ref={heading} tabIndex={-1}>{t('Evidence shown to the model')}</SheetTitle><SheetDescription>{t('Frozen passage from this review copy.')}</SheetDescription></SheetHeader>
    <div className="sheet-body">{passage ? <><h3 data-stored-text>{source?.title ?? t('an item no longer in the review copy')}</h3><p>{passage.locator.kind === 'abstract' ? t('abstract') : passage.locator.physical_page ? pageLocator(passage.locator.physical_page, false, passage.locator.printed_label) : t('Stored passage')}</p><div className="candidate-passage" data-stored-text><HighlightedPassageText passage={{ text: passage.text, kind: passage.locator.kind === 'abstract' ? 'abstract' : 'pdf_page' }} highlightTexts={located ? [anchor] : []} markLabel={t('Text located for the stored quote')} /></div></> : <p>{t('an item no longer in the review copy')}</p>}</div>
    <footer className="cell-foot"><p>{t('Semantic support not checked.')}</p><Button variant="outline" onClick={onClose}>{t('Close')}</Button></footer>
  </SheetContent></Sheet>
}
