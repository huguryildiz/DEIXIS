import { useEffect, useRef } from 'react'
import { ShieldCheck } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type { ReviewDetail, ReviewTargetKind, Source } from '../api'
import { StackPanel } from '../research/SplitPanel'
import { usePanels } from '../research/usePanelStack'
import { t } from '../i18n'
import { commandInFlight, reviewIdentity } from './commands'
import { ReviewPane } from './ReviewPane'
import { ReviewRequest } from './ReviewRequest'
import type { ReviewSurfaceState } from './useReviewSurface'
import '../research/kit.css'
import './review.css'

// Reviews by another model (mockup `reviewDlg` and `reviewPanel`, P32/P33): the shield or a "Review with another
// model" row opens the request dialog; a started review and the "Reviewed by another model" lines open the review
// panel, stacked on the panel they were opened from. The owner keeps this state; the surface draws both.
export function ReviewSurface({ surface, researchId, targetKind, targetId, version, eventCursor, runActive, unavailableReason = '', sources, sectionLabel, sourceName, readOnly = false, dark = false, open, changed, apply }: {
  surface: ReviewSurfaceState; researchId: string; targetKind: ReviewTargetKind; targetId: string; version: number; eventCursor: number; runActive: boolean
  unavailableReason?: string; sources: Source[]; sectionLabel: (ref: string) => string; sourceName?: (id: string) => string; readOnly?: boolean; dark?: boolean
  open: (id: string, anchor: string, review?: ReviewDetail) => void; changed: () => void | Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const identity = reviewIdentity(researchId, targetKind, targetId)
  const name = `review:${targetKind}:${targetId}`
  // The panel leaves the stack with its target (a report closed, a candidate removed, another answer version).
  const removePanel = usePanels()?.remove
  useEffect(() => () => removePanel?.(name), [removePanel, name])
  const started = useRef(false)
  const { setDialog, openPanel, trigger } = surface
  // A request still on its way keeps the dialog open: closing it would hide whether the review started.
  const close = () => { if (!commandInFlight(identity)) setDialog(false) }
  const onStarted = async (id: string) => {
    started.current = true
    setDialog(false)
    await changed()
    requestAnimationFrame(() => {
      // The panel stacks on the one the dialog was opened from, so Back returns to its opener.
      const opener = trigger.current
      if (opener?.isConnected) opener.focus({ preventScroll: true })
      started.current = false
      openPanel(id)
    })
  }
  return <>
    {!readOnly && <Dialog open={surface.dialog} onOpenChange={next => { if (!next) close() }}>
      <DialogContent className={`review-dialog${dark ? ' dark' : ''}`} icon={<ShieldCheck size={16} aria-hidden />} title={t('Review with another model')} finalFocus={() => !started.current}>
        <ReviewRequest researchId={researchId} targetKind={targetKind} targetId={targetId} version={version} runActive={runActive} unavailableReason={unavailableReason}
          sectionLabel={sectionLabel} sourceName={sourceName} started={onStarted} cancel={close} />
      </DialogContent>
    </Dialog>}
    {/* Keyed by its target: another answer version or candidate version mounts a new panel instead of renaming this one,
        which the stack would read as this panel closing. */}
    <StackPanel key={`${name}:${version}`} name={name} open={Boolean(surface.panel)} onClose={surface.closePanel} title={t('Review with another model')} icon={ShieldCheck} className={`mk-detail-box review-panel-box${dark ? ' dark' : ''}`}>
      {surface.panel && <ReviewPane key={surface.panel.id ?? 'latest'} researchId={researchId} targetKind={targetKind} targetId={targetId} eventCursor={eventCursor} initial={surface.panel.id}
        sources={sources} sectionLabel={sectionLabel} open={open} changed={changed} apply={apply} />}
    </StackPanel>
  </>
}
