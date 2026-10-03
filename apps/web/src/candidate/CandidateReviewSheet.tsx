import { useEffect, useRef, useState, type RefObject } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, type CandidateCard, type CandidateVersion, type ResearchView, type ReviewDetail } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { ReviewPane } from '../review/ReviewPane'
import { ReviewSummary } from '../review/ReviewSummary'
import { useReviewList } from '../review/useReviewList'
import { CandidateReviewEvidence } from './CandidateReviewEvidence'
import { useReturnFocus } from './focus'

export function CandidateReviewEntry({ card, version, view, dark, current, active, changed }: {
  card: CandidateCard; version: CandidateVersion; view: ResearchView; dark: boolean; current: boolean; active: boolean; changed: () => void
}) {
  const { reviews, error, refresh } = useReviewList(view.research.id, 'candidate', version.id, view.last_event_id)
  const [mode, setMode] = useState<'list' | 'request' | null>(null)
  const [openedVersion, setOpenedVersion] = useState<CandidateVersion | null>(null)
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({})
  const root = useRef<HTMLDivElement>(null)
  const focus = useReturnFocus()
  const latest = card.searches.filter(s => s.candidate_version_id === version.id).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))[0]
  const latestId = latest?.id
  useEffect(() => {
    if (mode !== 'request' || !latestId) return
    let live = true
    api.candidateMatrix(view.research.id, card.id, latestId).then(matrix => { if (live) setSourceNames(Object.fromEntries(matrix.hits.map(hit => [hit.source_version_id, hit.source.title]))) }).catch(() => {})
    return () => { live = false }
  }, [mode, latestId, view.research.id, card.id])
  const reason = active ? t('Another run is active in this research.') : !latest ? t('A review reads a finished search of this version. Run the search first.') : !['completed', 'failed', 'stopped'].includes(latest.outcome) ? t('The latest search of this version has not finished.') : ''
  const open = (next: 'list' | 'request') => {
    const opener = document.activeElement
    if (opener instanceof HTMLElement) focus.rememberFocus(opener, () => opener.isConnected ? opener : root.current?.querySelector<HTMLElement>('button') ?? null)
    setOpenedVersion(version); setMode(next)
  }
  const reviewChanged = async () => { await refresh(); changed() }
  if (card.trashed_at) return null
  return <div ref={root} className="candidate-section">
    {error && <Notice tone="error">{error}</Notice>}
    <ReviewSummary reviews={reviews} open={() => open('list')} />
    {current && <><Button variant="ghost" size="sm" disabled={Boolean(reason)} aria-describedby={reason ? `candidate-review-reason-${version.id}` : undefined} onClick={() => open('request')}>{t('Review with another model')}</Button>{reason && <p id={`candidate-review-reason-${version.id}`}>{reason}</p>}</>}
    {mode && <CandidateReviewSheet view={view} version={openedVersion ?? version} dark={dark} readOnly={!current || openedVersion?.id !== card.current_version_id} showRequest={mode === 'request'} sourceNames={sourceNames} unavailableReason={reason} returnFocus={focus.returnFocus} changed={reviewChanged} onClose={() => { setMode(null); void refresh(); focus.restoreFocus() }} />}
  </div>
}

export function CandidateReviewSheet({ view, version, dark, readOnly, showRequest, sourceNames, unavailableReason, returnFocus, changed, onClose }: {
  view: ResearchView; version: CandidateVersion; dark: boolean; readOnly: boolean; showRequest: boolean; unavailableReason: string
  returnFocus: RefObject<HTMLElement | null>; changed: () => void | Promise<void>; onClose: () => void
  sourceNames: Record<string, string>
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const [evidence, setEvidence] = useState<{ review: ReviewDetail; passageId: string; anchor: string } | null>(null)
  const evidenceFocus = useReturnFocus()
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet report-sheet ${dark ? 'dark' : ''}`} initialFocus={heading} finalFocus={returnFocus}>
    <SheetHeader><SheetTitle ref={heading} tabIndex={-1}>{t('Review by another model')}</SheetTitle><SheetDescription>{t('The model reads the stored review copy.')}</SheetDescription></SheetHeader>
    <div className="sheet-body"><ReviewPane researchId={view.research.id} targetKind="candidate" targetId={version.id} version={version.version} eventCursor={view.last_event_id} runActive={view.runs.some(r => ['queued', 'running', 'pause_requested'].includes(r.status))} unavailableReason={readOnly ? '' : unavailableReason} readOnly={readOnly} showRequest={showRequest} sources={view.sources} sectionLabel={ref => ref} sourceName={id => sourceNames[id] ?? t('an item no longer in the review copy')} changed={changed} open={(passageId, anchor, review) => {
      if (!review) return
      const opener = document.activeElement
      if (opener instanceof HTMLElement) evidenceFocus.rememberFocus(opener)
      setEvidence({ review, passageId, anchor })
    }} /></div>
    <footer className="cell-foot"><Button variant="outline" onClick={onClose}>{t('Close')}</Button></footer>
    {evidence && <CandidateReviewEvidence {...evidence} dark={dark} returnFocus={evidenceFocus.returnFocus} onClose={() => { setEvidence(null); evidenceFocus.restoreFocus() }} />}
  </SheetContent></Sheet>
}
