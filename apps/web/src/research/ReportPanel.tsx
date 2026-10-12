import { type ReactNode, type RefObject } from 'react'
import { AlignLeft, Check, Copy, Download, Quote, ShieldCheck } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, FileTypeIcon } from '@/components/ui/dropdown-menu'
import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { StackPanel } from './SplitPanel'
import { answerDocxUrl, type Answer, type Source, type Verdict } from '../api'
import { verdictLabels } from '../labels'
import { verdictTones } from './reportMarkdown'
import { ReviewPane } from '../review/ReviewPane'
import { Option } from '../Home'
import { citationStyles, type CitationStyle } from '../citations'
import { t, uiLanguage, uiLocale } from '../i18n'

// The report panel (mockup `panel()` for `report`, P2/P3). Its head: the version select (when the question has more than
// one report), the citation style, Review with another model (the claim reviews of this answer, live) and the download
// menu (Markdown, Word; Copy as the live placement, §2.2). "Show changes" is the answer diff (P4, S21) and the PDF row is
// print (S27); neither is drawn before it exists. The document: the serif title, one meta line (Report · Vn · date ·
// sources · the claim reviews' counts), then the report's own content.

export type ReportVersion = { id: string; version: number }

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

export function ReportPanel({ open, onOpenChange, dark, title, version, latestVersion, versions, onVersion, researchId, answer, sources, eventCursor, runActive, reviewMode, requestReview, reviewCount, reviewsButton, scrollRoot, style, onStyle, onToggleReviews, onCopy, onDownload, onOpenPassage, onReviewsChanged, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; dark: boolean; title: string; version: number; latestVersion: number
  versions: ReportVersion[]; onVersion: (answerId: string) => void
  researchId: string; answer: Answer; sources: Source[]; eventCursor: number; runActive: boolean; reviewMode: boolean; requestReview: boolean
  reviewCount: number; reviewsButton: RefObject<HTMLButtonElement | null>; scrollRoot: RefObject<HTMLDivElement | null>
  style: CitationStyle; onStyle: (style: CitationStyle) => void
  onToggleReviews: () => void; onCopy: () => void; onDownload: () => void; onOpenPassage: (passageId: string, highlightText: string | null) => void
  onReviewsChanged: () => Promise<void>; children: ReactNode
}) {
  // The works the answer cites, each once over its versions (the card's "N sources"), and the claim reviews' verdicts.
  const cited = new Set(answer.claims.flatMap(c => c.evidence.map(e => e.work_id))).size
  const verdicts = (Object.keys(verdictLabels) as Verdict[]).map(v => [v, answer.claims.filter(c => c.review?.verdict === v).length] as const).filter(([, n]) => n > 0)
  const lang = uiLanguage() === 'tr' ? 'tr' : 'en'
  const reviewLabel = reviewCount ? t(reviewCount === 1 ? 'Review with another model, {n} review' : 'Review with another model, {n} reviews', { n: reviewCount }) : t('Review with another model')
  const fmt = (format: string, detail: string) => <><FileTypeIcon format={format} /><b>{format}</b><span>{detail}</span></>
  return <StackPanel name={`report:${answer.id}`} open={open} onClose={() => onOpenChange(false)} title={title} icon={AlignLeft}
    className={`report-panel report-sheet${dark ? ' dark' : ''}`} actions={<div className="report-toolbar-actions">
      {versions.length > 1 && <Select value={answer.id} onValueChange={value => { if (value && value !== answer.id) onVersion(value as string) }}>
        <SelectTrigger className="report-select" aria-label={t('Version')}><SelectValue>{(value: string) => `V${versions.find(v => v.id === value)?.version ?? version}`}</SelectValue></SelectTrigger>
        <SelectContent align="end" alignItemWithTrigger={false}>
          {versions.map(v => <SelectItem key={v.id} value={v.id}>V{v.version}</SelectItem>)}
        </SelectContent>
      </Select>}
      <Select value={style} onValueChange={value => { if (value) onStyle(value as CitationStyle) }}>
        <SelectTrigger className="report-select" aria-label={t('Citation style')} title={t('How the cited sources are written')}><SelectValue>{(value: string) => <span className="report-select-sizer">
          {/* As wide as the longest style name, like the mockup's native select: the others hold the width unseen. */}
          {(Object.keys(citationStyles) as CitationStyle[]).map(k => <span key={k} className={k === value ? undefined : 'is-sizer'} aria-hidden={k === value ? undefined : true}>{t(citationStyles[k].label)}</span>)}
        </span>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content has-details" align="end" alignItemWithTrigger={false}>
          <div className="intake-select-heading" aria-hidden="true">{t('Citation style')}</div>
          {(Object.keys(citationStyles) as CitationStyle[]).map(k => <SelectItem key={k} value={k}><Option icon={Quote} title={t(citationStyles[k].label)} detail={t(citationStyles[k].detail)} /></SelectItem>)}
        </SelectContent>
      </Select>
      <button ref={reviewsButton} type="button" className="ib report-review" aria-label={reviewLabel} title={reviewLabel} aria-pressed={reviewMode} onClick={onToggleReviews}>
        <ShieldCheck size={15} aria-hidden />{reviewCount > 0 && <span className="ib-count" aria-hidden>{count(reviewCount)}</span>}
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger render={<button type="button" className="ib report-download" aria-label={t('Download report')} title={t('Download')} />}><Download size={15} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" sideOffset={6} className="research-export-menu report-export-menu">
          <DropdownMenuItem className="research-export-item menu-fmt" onClick={onDownload}>{fmt('MD', t('Markdown'))}</DropdownMenuItem>
          <MenuPrimitive.LinkItem href={answerDocxUrl(researchId, answer.id, lang, style)} download closeOnClick data-slot="dropdown-menu-item" className="research-export-item menu-fmt">{fmt('DOCX', t('Word document'))}</MenuPrimitive.LinkItem>
          {/* Copying the report as Markdown (live, §2.2) sits with the files it matches. */}
          <DropdownMenuItem className="research-export-item menu-fmt export-placement" onClick={onCopy}><Copy size={15} aria-hidden /><b>{t('Copy')}</b><span>{t('Markdown to the clipboard')}</span></DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>}>
    <p className="sr-only">{t('Source-linked research report, version {n}.', { n: version })}</p>
    <div className="report-scroll" ref={scrollRoot}>
      {reviewMode && <ReviewPane researchId={researchId} targetKind="answer" targetId={answer.id} version={version} eventCursor={eventCursor} runActive={runActive} sources={sources} sectionLabel={ref => ref} showRequest={requestReview} open={onOpenPassage} changed={onReviewsChanged} />}
      <article hidden={reviewMode} className="report-document">
        <header className="report-document-head">
          <h1>{title}</h1>
          <div className="meta">
            <span>{t('Report')} · V{version}{version < latestVersion ? ` ${t('(earlier version)')}` : ''}</span><span aria-hidden>·</span>
            <time dateTime={answer.created_at}>{new Date(answer.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time><span aria-hidden>·</span>
            <span>{t(cited === 1 ? '{n} source' : '{n} sources', { n: count(cited) })}</span>
            {verdicts.map(([v, n]) => <span key={v} className={`badge-s v-${verdictTones[v]}`} title={t('The reviewer model’s reading of each claim against its cited passages; it is not independent verification.')}>{v === 'supported' && <Check size={11} aria-hidden />}{count(n)} {t(verdictLabels[v])}</span>)}
          </div>
        </header>
        {children}
      </article>
    </div>
  </StackPanel>
}
