import { type ReactNode } from 'react'
import { AlignLeft, Check, Copy, Download, Eye, EyeOff, Quote, ShieldCheck } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, FileTypeIcon } from '@/components/ui/dropdown-menu'
import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { StackPanel } from './SplitPanel'
import { answerDocxUrl, type Answer, type Verdict } from '../api'
import { MathText } from '../MathText'
import { BASIS_BADGES, type AnswerDiff, type Basis, type ComparisonBase } from './answerDiff'
import { verdictLabels } from '../labels'
import { verdictTones } from './reportMarkdown'
import { Option } from '../Home'
import { citationStyles, type CitationStyle } from '../citations'
import { t, uiLanguage, uiLocale } from '../i18n'

// The report panel (mockup `panel()` for `report`, P2/P3). Its head: the version select (when the question has more than
// one report), the citation style, Review with another model (the claim reviews of this answer, live) and the download
// menu (Markdown, PDF through the print dialog, Word; Copy as the live placement, §2.2). The shield opens the review request dialog (P32). "Show changes"
// (with more than one version) turns on the answer diff (P4, S21): the "Changes since Vn" box under the meta line and the
// marks in the text. The PDF row prints this panel as shown (S27, printPanel.ts). The document: the serif title, one meta line
// (Report · Vn · date · sources · the claim reviews' counts), then the report's own content.

export type ReportVersion = { id: string; version: number }

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

export function ReportPanel({ open, onOpenChange, dark, title, version, latestVersion, versions, onVersion, researchId, answer, style, onStyle, onReview, onCopy, onDownload, onPrint, compare, changes, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; dark: boolean; title: string; version: number; latestVersion: number
  versions: ReportVersion[]; onVersion: (answerId: string) => void
  researchId: string; answer: Answer
  style: CitationStyle; onStyle: (style: CitationStyle) => void
  onReview: (opener: HTMLElement) => void; onCopy: () => void; onDownload: () => void; onPrint: () => void
  compare?: { on: boolean; onToggle: () => void }; changes?: ReactNode; children: ReactNode
}) {
  // The works the answer cites, each once over its versions (the card's "N sources"), and the claim reviews' verdicts.
  const cited = new Set(answer.claims.flatMap(c => c.evidence.map(e => e.work_id))).size
  const verdicts = (Object.keys(verdictLabels) as Verdict[]).map(v => [v, answer.claims.filter(c => c.review?.verdict === v).length] as const).filter(([, n]) => n > 0)
  const lang = uiLanguage() === 'tr' ? 'tr' : 'en'
  const reviewLabel = t('Review with another model')
  const fmt = (format: string, detail: string) => <><FileTypeIcon format={format} /><b>{format}</b><span>{detail}</span></>
  return <StackPanel name={`report:${answer.id}`} open={open} onClose={() => onOpenChange(false)} title={title} icon={AlignLeft}
    className={`report-panel report-sheet${dark ? ' dark' : ''}`} actions={<div className="report-toolbar-actions">
      {versions.length > 1 && <Select value={answer.id} onValueChange={value => { if (value && value !== answer.id) onVersion(value as string) }}>
        <SelectTrigger className="report-select" aria-label={t('Version')}><SelectValue>{(value: string) => `V${versions.find(v => v.id === value)?.version ?? version}`}</SelectValue></SelectTrigger>
        <SelectContent align="end" alignItemWithTrigger={false}>
          {versions.map(v => <SelectItem key={v.id} value={v.id}>V{v.version}</SelectItem>)}
        </SelectContent>
      </Select>}
      {/* On a phone the button is an eye icon with its name kept for screen readers, so the head fits the screen. */}
      {versions.length > 1 && compare && <button type="button" className="ghost report-compare" title={compare.on ? t('Hide changes') : t('Show changes')} onClick={compare.onToggle}>
        {compare.on ? <EyeOff size={15} className="report-compare-icon" aria-hidden /> : <Eye size={15} className="report-compare-icon" aria-hidden />}
        <span className="report-compare-label">{compare.on ? t('Hide changes') : t('Show changes')}</span>
      </button>}
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
      <button type="button" className="ib report-review" aria-label={reviewLabel} title={reviewLabel} aria-haspopup="dialog" onClick={e => onReview(e.currentTarget)}>
        <ShieldCheck size={15} aria-hidden />
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger render={<button type="button" className="ib report-download" aria-label={t('Download report')} title={t('Download')} />}><Download size={15} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" sideOffset={6} className="research-export-menu report-export-menu">
          <DropdownMenuItem className="research-export-item menu-fmt" onClick={onDownload}>{fmt('MD', t('Markdown'))}</DropdownMenuItem>
          <DropdownMenuItem className="research-export-item menu-fmt" title={t('Opens the print dialog on this report; choose Save as PDF there.')} onClick={onPrint}>{fmt('PDF', t('Portable document'))}</DropdownMenuItem>
          <MenuPrimitive.LinkItem href={answerDocxUrl(researchId, answer.id, lang, style)} download closeOnClick data-slot="dropdown-menu-item" className="research-export-item menu-fmt">{fmt('DOCX', t('Word document'))}</MenuPrimitive.LinkItem>
          {/* Copying the report as Markdown (live, §2.2) sits with the files it matches. */}
          <DropdownMenuItem className="research-export-item menu-fmt export-placement" onClick={onCopy}><Copy size={15} aria-hidden /><b>{t('Copy')}</b><span>{t('Markdown to the clipboard')}</span></DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>}>
    <p className="sr-only">{t('Source-linked research report, version {n}.', { n: version })}</p>
    <div className="report-scroll">
      <article className="report-document" data-answer-id={answer.id}>
        <header className="report-document-head">
          <h1>{title}</h1>
          <div className="meta">
            <span>{t('Report')} · V{version}{version < latestVersion ? ` ${t('(earlier version)')}` : ''}</span><span aria-hidden>·</span>
            <time dateTime={answer.created_at}>{new Date(answer.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time><span aria-hidden>·</span>
            <span>{t(cited === 1 ? '{n} source' : '{n} sources', { n: count(cited) })}</span>
            {verdicts.map(([v, n]) => <span key={v} className={`badge-s v-${verdictTones[v]}`} title={t('The reviewer model’s reading of each claim against its cited passages; it is not independent verification.')}>{v === 'supported' && <Check size={11} aria-hidden />}{count(n)} {t(verdictLabels[v])}</span>)}
          </div>
        </header>
        {changes}
        {children}
      </article>
    </div>
  </StackPanel>
}

const basisLabel = (b: Basis) => BASIS_BADGES[b].map(k => t(k === 'abstract' ? 'From abstract' : 'Full text')).join(' + ')

// "Changes since Vn" (mockup `.changes`, P4): one line per kind of stored difference between the version shown and the
// version named in the heading, and nothing for a kind that did not change. When there is no usable earlier version the
// box says so instead of comparing with another record.
export function ChangesBox({ version, base, diff }: { version: number; base: ComparisonBase; diff: AnswerDiff | null }) {
  if (base.kind !== 'ok' || !diff) {
    const heading = base.kind === 'unavailable' && base.version !== null ? t('Changes since V{n}', { n: base.version }) : t('Changes')
    const text = base.kind === 'first' ? t('V{n} is the first version of this report; there is no earlier version to compare it with.', { n: version })
      : base.kind === 'unavailable' && base.reason === 'missing' ? t('The earlier answer this version revises is not in this research’s records, so no changes are shown.')
      : t('The earlier answer this version revises did not pass validation, so it is not compared.')
    return <section className="changes" aria-label={heading}><b>{heading}</b><p>{text}</p></section>
  }
  const b = base.version
  const n = (count: number) => new Intl.NumberFormat(uiLocale()).format(count)
  const heading = t('Changes since V{n}', { n: b })
  return <section className="changes" aria-label={heading}>
    <b>{heading}</b>
    {diff.empty && !diff.scopes ? <p>{t('No differences in claim wording, cited passages, reading depth or limits.')}</p> : <ul>
      {diff.scopes && <li>{t('V{b} answered revision {r} of the question; V{v} answers revision {s}.', { b, r: diff.scopes.base, v: version, s: diff.scopes.shown })}</li>}
      {diff.fullTextNow.length > 0 && <li>{t('Cited from full text in V{v}, only from abstracts in V{b}: {works}', { v: version, b, works: diff.fullTextNow.map(w => w.label).join(', ') })}</li>}
      {diff.basisChanges.map(c => <li key={`${c.from}>${c.to}`}>{t(c.count === 1 ? 'Badge on {n} claim changed from “{from}” to “{to}”' : 'Badges on {n} claims changed from “{from}” to “{to}”', { n: n(c.count), from: basisLabel(c.from), to: basisLabel(c.to) })}</li>)}
      {diff.citationChanged > 0 && <li>{t(diff.citationChanged === 1 ? '{n} claim keeps its wording but cites different passages' : '{n} claims keep their wording but cite different passages', { n: n(diff.citationChanged) })}</li>}
      {diff.added > 0 && <li>{t(diff.added === 1 ? '{n} claim added' : '{n} claims added', { n: n(diff.added) })}</li>}
      {diff.removedClaims.length > 0 && <li>{t(diff.removedClaims.length === 1 ? '{n} claim of V{b} is not in this version:' : '{n} claims of V{b} are not in this version:', { n: n(diff.removedClaims.length), b })}
        <ul className="changes-removed">{diff.removedClaims.map(c => <li key={c.id}><del><span className="sr-only">{t('Removed:')} </span><MathText text={c.text} /></del></li>)}</ul></li>}
      {(diff.limitsAdded.length > 0 || diff.limitsRemoved.length > 0) && <li>{t('Limits updated')}</li>}
    </ul>}
    <p className="changes-foot">{t('Compared: claim wording, the passages each claim cites, their reading depth and the limits. Claim reviews are not compared.')}</p>
  </section>
}
