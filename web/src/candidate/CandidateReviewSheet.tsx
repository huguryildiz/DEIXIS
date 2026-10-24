import { useEffect, useState } from 'react'
import { CircleX, FileCheck2 } from 'lucide-react'
import { api, type CandidateCard, type CandidateVersion, type ResearchView, type ReviewDetail } from '../api'
import { t } from '../i18n'
import { ReviewSummary } from '../review/ReviewSummary'
import { ReviewSurface } from '../review/ReviewSurface'
import type { ReviewSurfaceState } from '../review/useReviewSurface'
import { useReviewList } from '../review/useReviewList'
import { CandidateReviewEvidence } from './CandidateReviewEvidence'
import { useReturnFocus } from './focus'

const latestSearch = (card: CandidateCard, version: CandidateVersion) =>
  card.searches.filter(s => s.candidate_version_id === version.id).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))[0]
// Why a version cannot be reviewed now, or '' when it can.
function unavailable(card: CandidateCard, version: CandidateVersion, active: boolean) {
  const latest = latestSearch(card, version)
  return active ? t('Another run is active in this research.') : !latest ? t('A review reads a finished search of this version. Run the search first.') : !['completed', 'failed', 'stopped'].includes(latest.outcome) ? t('The latest search of this version has not finished.') : ''
}

// One version's review entry (P32/P33): "Review with another model" opens the request dialog (the current version only)
// and the summary line opens the review panel. Both go through the candidate's one review surface, which keeps the
// version they were opened for.
export function CandidateReviewEntry({ card, version, view, current, active, surface, revision, onTarget }: {
  card: CandidateCard; version: CandidateVersion; view: ResearchView; current: boolean; active: boolean
  surface: ReviewSurfaceState; revision: number; onTarget: (version: CandidateVersion) => void
}) {
  // `revision` counts the review writes made here (a decision makes no research event), so the summary reads them too.
  const { reviews, error } = useReviewList(view.research.id, 'candidate', version.id, view.last_event_id + revision)
  const reasonId = `candidate-review-reason-${version.id}`
  const reason = unavailable(card, version, active)
  if (card.trashed_at) return null
  return <>
    {current && <button type="button" className="ghost candidate-review-open" aria-haspopup="dialog" disabled={Boolean(reason)} aria-describedby={reason ? reasonId : undefined} onClick={e => { onTarget(version); surface.openDialog(e.currentTarget) }}><FileCheck2 aria-hidden />{t('Review with another model')}</button>}
    {current && reason && <span id={reasonId} className="foot-note candidate-review-reason">{reason}</span>}
    {error && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{error}</span></div>}
    <ReviewSummary reviews={reviews} open={() => { onTarget(version); surface.openPanel() }} />
  </>
}

// The candidate's review dialog and panel, mounted once on the candidate so an open review stays on its version when a
// newer version or search arrives (the panel then says the review is stale). A located quote opens the frozen passage
// of the review copy.
export function CandidateReviewHost({ card, version, view, dark, active, surface, changed }: {
  card: CandidateCard; version: CandidateVersion; view: ResearchView; dark: boolean; active: boolean; surface: ReviewSurfaceState; changed: () => void
}) {
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({})
  const [evidence, setEvidence] = useState<{ review: ReviewDetail; passageId: string; anchor: string } | null>(null)
  const evidenceFocus = useReturnFocus()
  const latestId = latestSearch(card, version)?.id
  const wanted = surface.dialog || Boolean(surface.panel)
  useEffect(() => {
    if (!wanted || !latestId) return
    let live = true
    api.candidateMatrix(view.research.id, card.id, latestId).then(matrix => { if (live) setSourceNames(Object.fromEntries(matrix.hits.map(hit => [hit.source_version_id, hit.source.title]))) }).catch(() => {})
    return () => { live = false }
  }, [wanted, latestId, view.research.id, card.id])
  if (card.trashed_at) return null
  return <>
    <ReviewSurface surface={surface} researchId={view.research.id} targetKind="candidate" targetId={version.id} version={version.version} eventCursor={view.last_event_id}
      runActive={view.runs.some(r => ['queued', 'running', 'pause_requested'].includes(r.status))} unavailableReason={unavailable(card, version, active)} readOnly={version.id !== card.current_version_id} sources={view.sources} sectionLabel={ref => ref}
      sourceName={id => sourceNames[id] ?? t('an item no longer in the review copy')} dark={dark} changed={async () => { changed() }} open={(passageId, anchor, review) => {
        if (!review) return
        const opener = document.activeElement
        if (opener instanceof HTMLElement) evidenceFocus.rememberFocus(opener)
        setEvidence({ review, passageId, anchor })
      }} />
    {evidence && <CandidateReviewEvidence {...evidence} dark={dark} returnFocus={evidenceFocus.returnFocus} onClose={() => { setEvidence(null); evidenceFocus.restoreFocus() }} />}
  </>
}
