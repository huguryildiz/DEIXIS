import type { ReactNode } from 'react'
import { ArrowRight, Lightbulb, Upload, X } from 'lucide-react'
import type { Source } from '../api'
import { t } from '../i18n'

// A short author-year tag ("Li24") from the stored record, the way the cards list works; the full key stays in the title.
export function shortTag(source: Source) {
  const surname = (source.authors[0] ?? '').trim().split(/[\s,]+/).filter(Boolean).at(-1) ?? ''
  const year = source.year === null ? '' : String(source.year % 100).padStart(2, '0')
  return `${surname.slice(0, 10)}${year}` || '—'
}

// Included works first by their stored rank (a priority signal, not a relevance verdict), unranked last.
export const byRank = (a: Source, b: Source) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER)

export function WorkRows({ works, onOpen, action }: { works: Source[]; onOpen?: (sourceVersionId: string) => void; action?: (source: Source) => ReactNode }) {
  return <ul className="card-works">{works.map(source => <li key={source.source_version_id}>
    <span className="card-tag" title={source.source_key ?? undefined}>{shortTag(source)}</span>
    {onOpen ? <button type="button" className="card-work-title" onClick={() => onOpen(source.source_version_id)}>{source.title}</button>
      : <span className="card-work-title">{source.title}</span>}
    {action?.(source)}
  </li>)}</ul>
}

// What to do once a search has finished and no answer exists yet: the answer leads, the other ways follow.
export function NextStepsCard({ included, children, onDismiss }: { included: number; children: ReactNode; onDismiss?: () => void }) {
  return <section className="next-card" aria-labelledby="next-card-title">
    <h4 id="next-card-title"><Lightbulb size={17} aria-hidden />{t('Recommended next steps')}</h4>
    <p>{included
      ? t(included === 1 ? 'The search included {n} work. You can now write a source-linked answer from it, or look at it in an evidence table.' : 'The search included {n} works. You can now write a source-linked answer from them, or compare them in an evidence table.', { n: included })
      : t('No work is included yet. Search again, or include works from the source list before writing an answer.')}</p>
    <div className="next-card-acts">{children}{onDismiss && <button type="button" className="next-card-dismiss" onClick={onDismiss}><X size={15} aria-hidden />{t('Dismiss')}</button>}</div>
  </section>
}

// Included works an answer can read only from their abstracts, with the way to get their full text.
export function PdfSuggestCard({ works, total, onOpen, onUpload }: { works: Source[]; total: number; onOpen?: (sourceVersionId: string) => void; onUpload: (opener: HTMLElement) => void }) {
  return <section className="pdf-card" aria-labelledby="pdf-card-title">
    <header><span className="pdf-card-icon" aria-hidden><Upload size={17} /></span>
      <div><h4 id="pdf-card-title">{t(total === 1 ? 'PDF suggested for {n} included work' : 'PDFs suggested for {n} included works', { n: total })}</h4>
        <p>{t('A PDF you add stays in this research’s library on this computer.')}</p></div></header>
    <div className="pdf-card-body">
      <p>{t(total === 1 ? 'An answer reads this work from its abstract only. Its full text lets the answer cite the passage itself.' : 'An answer reads these works from their abstracts only. Their full texts let the answer cite the passages themselves.')}</p>
      <WorkRows works={works} onOpen={onOpen} />
      {total > works.length && <p className="pdf-card-more">{t('and {n} more', { n: total - works.length })}</p>}
      <button type="button" className="pdf-card-upload" onClick={e => onUpload(e.currentTarget)}><Upload size={16} aria-hidden />{t('Get or upload PDFs')}</button>
    </div>
  </section>
}

export const OpenAllButton = ({ n, passed = false, onClick }: { n: number; passed?: boolean; onClick: (opener: HTMLElement) => void }) =>
  <button type="button" className="done-card-open" onClick={e => onClick(e.currentTarget)}>{passed
    ? t(n === 1 ? 'Open the {n} work that passed the abstract stage' : 'Open the {n} works that passed the abstract stage', { n })
    : t(n === 1 ? 'Open the {n} included source' : 'Open all {n} included sources', { n })}<ArrowRight size={16} aria-hidden /></button>
