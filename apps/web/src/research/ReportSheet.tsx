import { type ReactNode } from 'react'
import { CircleCheck, Copy, Download, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { type Answer, type Source } from '../api'
import { ReviewPane } from '../review/ReviewPane'
import { t, uiLocale } from '../i18n'
import type { RefObject } from 'react'

export function ReportSheet({ open, onOpenChange, dark, title, version, researchId, answer, sources, eventCursor, runActive, reviewMode, requestReview, copied, reviewCount, reviewsButton, scrollRoot, onToggleReviews, onCopy, onDownload, onOpenPassage, onReviewsChanged, children }: { open: boolean; onOpenChange: (open: boolean) => void; dark: boolean; title: string; version: number; researchId: string; answer: Answer; sources: Source[]; eventCursor: number; runActive: boolean; reviewMode: boolean; requestReview: boolean; copied: boolean; reviewCount: number; reviewsButton: RefObject<HTMLButtonElement | null>; scrollRoot: RefObject<HTMLDivElement | null>; onToggleReviews: () => void; onCopy: () => void; onDownload: () => void; onOpenPassage: (passageId: string, highlightText: string | null) => void; onReviewsChanged: () => Promise<void>; children: ReactNode }) {
  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent className={`detail-sheet report-sheet ${dark ? 'dark' : ''}`}>
      <SheetHeader className="report-toolbar">
        <div className="report-toolbar-title"><FileText size={17} aria-hidden /><SheetTitle>{title}</SheetTitle></div>
        <SheetDescription className="sr-only">{t('Source-linked research report, version {n}.', { n: version })}</SheetDescription>
        <div className="report-toolbar-actions">
          <Button ref={reviewsButton} variant="ghost" size="sm" aria-label={t('Reviews, {n}', { n: reviewCount })} aria-pressed={reviewMode} onClick={onToggleReviews}>{t('Reviews')} <span className="research-tab-count" aria-hidden>{reviewCount}</span></Button>
          <Button variant="ghost" size="sm" onClick={onCopy}>{copied ? <CircleCheck size={16} /> : <Copy size={16} />}<span className="report-head-label">{t(copied ? 'Copied' : 'Copy')}</span></Button>
          <Button variant="ghost" size="sm" onClick={onDownload}><Download size={16} /><span className="report-head-label">{t('Download')}</span></Button>
        </div>
      </SheetHeader>
      <div className="report-scroll" ref={scrollRoot}>
        {reviewMode && <ReviewPane researchId={researchId} targetKind="answer" targetId={answer.id} version={version} eventCursor={eventCursor} runActive={runActive} sources={sources} sectionLabel={ref => ref} showRequest={requestReview} open={onOpenPassage} changed={onReviewsChanged} />}
        <article hidden={reviewMode} className="report-document">
          <header className="report-document-head"><p>{t('Report')} · V{version}</p><h1>{title}</h1><time>{new Date(answer.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time></header>
          {children}
        </article>
      </div>
    </SheetContent>
  </Sheet>
}
