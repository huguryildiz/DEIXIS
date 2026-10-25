import { useEffect, useState } from 'react'
import { ChevronRight, FileText } from 'lucide-react'
import { api, type Answer, type AnswerMethod } from '../lib/api'
import { t, uiLocale } from '../lib/i18n'
import { providerName } from '../lib/labels'
import { AnswerFlowNote } from './FlowReport'
import './MethodBox.css'

// How the answer was reached, from stored rows only (no model call). Counts stay apart: found, read, tried, included,
// given and cited answer different questions, and what no row measures is said, not guessed. The box under the answer
// (mockup `.methods`, R26) says it in one paragraph; "Full method" opens every count, and the answer's boundary (where
// the works stood when it started, what it was given; §2.2) closes it.

const num = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
const maybe = (n: number | null) => (n === null ? t('not recorded') : num(n))

// In an earlier report (`inReport`) the report itself closes with the answer's boundary, and there is no funnel to open.
export function MethodBox({ researchId, answer, reviewPending, onShowFunnel, inReport = false }: { researchId: string; answer: Answer; reviewPending: boolean; onShowFunnel?: (opener: HTMLElement) => void; inReport?: boolean }) {
  const answerId = answer.id
  const [method, setMethod] = useState<AnswerMethod | null>(null)
  useEffect(() => {
    let live = true
    api.answerMethod(researchId, answerId).then(data => { if (live) setMethod(data) }).catch(() => { /* the box is an extra; the answer stands without it */ })
    return () => { live = false }
  }, [researchId, answerId])
  if (!method) return null
  const { search, selection, extraction, limitations, evidence_base: base } = method
  const providers = [...new Set(search.queries.map(q => providerName(q.provider)))]
  const review = selection.vocabulary_review
  const years = base.year_min === null ? null : base.year_min === base.year_max ? String(base.year_min) : `${base.year_min}–${base.year_max}`
  const abstractOnly = answer.inputs_given?.depth?.abstract ?? 0
  const queries = search.queries.length
  const found = selection.works_found
  // An answer over attached PDFs only: nothing was searched or screened, so one sentence says so instead of three "not recorded".
  const pdfOnly = queries === 0 && selection.abstract_read === 0 && selection.full_text_read === 0
  // An older answer's start snapshot kept no reading counts (D92): they are not recounted from today's rows.
  const readingsUnknown = selection.abstract_read === null
  const followups = search.followup_searches
  return <section className="methods" aria-labelledby={`methods-${answerId}`}>
    <h4 id={`methods-${answerId}`}><FileText size={16} aria-hidden />{t('Methods')}</h4>
    <p>
      {pdfOnly ? t('This answer was made only from the PDFs you attached; no search was run.')
        : <>{queries === 0 ? t('No search was recorded for this question revision.')
        : <>{t(queries === 1 ? 'One search was sent to {providers}' : '{n} searches were sent to {providers}', { n: num(queries), providers: providers.join(', ') })}{search.chaining.ran ? t(', and citation chaining ran.') : t('; citation chaining did not run.')}</>}{' '}
      {followups && followups.length > 0 && <>{t(followups.length === 1 ? 'One follow-up search ran before this answer.' : '{n} follow-up searches ran before this answer.', { n: num(followups.length) })}{' '}</>}
      {readingsUnknown ? t('How many abstracts and full texts the model read was not recorded when this answer started.')
        : <>{selection.abstract_read !== null && selection.abstract_read > 0
        ? <>{found !== null ? t('The model read the abstracts of {read} of {found} works against the criterion', { read: num(selection.abstract_read), found: num(found) }) : t('The model read the abstracts of {read} works against the criterion', { read: num(selection.abstract_read) })}
          {found !== null && found > selection.abstract_read && onShowFunnel && <> (<button type="button" className="link" onClick={e => onShowFunnel(e.currentTarget)}>{t('see what was not read')}</button>)</>}.</>
        : t('No model reading of abstracts is recorded.')}{' '}
      {selection.full_text_read !== null && selection.full_text_read > 0
        ? <>{t(selection.full_text_read === 1 ? '{n} work was read in its full text (selected pages)' : '{n} works were read in their full text (selected pages)', { n: num(selection.full_text_read) })}{selection.included !== null ? t('; included when the answer started: {n}.', { n: num(selection.included) }) : '.'}</>
        : t('No model reading of full texts is recorded.')}</>}</>}{' '}
      {abstractOnly > 0 && <>{t(abstractOnly === 1 ? '{n} work was given to the answer from its abstract only; where cited it is labelled “From abstract”.' : '{n} works were given to the answer from their abstracts only; where cited they are labelled “From abstract”.', { n: num(abstractOnly) })}{' '}</>}
      <span className="ok">{t('Every citation resolves to a stored passage given to this step.')}</span>{' '}
      {answer.review?.status === 'completed' ? t('Claim support was reviewed by the reviewer model.')
        : answer.review ? t('The reviewer model’s claim review gave no usable result.')
        : reviewPending ? t('The reviewer model is reviewing claim support.') : t('Claim support was not reviewed by a reviewer model.')}
    </p>
    <details className="method-more">
      <summary><span>{t('Full method')}</span><ChevronRight size={13} aria-hidden className="search-summary-chevron" /></summary>
    <div className="method-detail">
      <section>
        <p className="flow-head">{t('Approach')}</p>
        <p className="method-text">{pdfOnly ? t('This answer was made only from the PDFs you attached; no search was run.') : <>{providers.length ? t('{providers} searched.', { providers: providers.join(', ') }) : t('No provider was searched.')} {readingsUnknown ? t('The model’s readings and your own decisions were not recorded when this answer started.') : <>{selection.abstract_read !== null && selection.abstract_read > 0 ? t('A model read {n} abstracts.', { n: num(selection.abstract_read) }) : t('No model reading of abstracts is recorded.')} {selection.full_text_read !== null && selection.full_text_read > 0 ? t('A model read selected passages from the full text of {n} works.', { n: num(selection.full_text_read) }) : t('No model reading of full texts is recorded.')}</>}</>} {readingsUnknown ? '' : selection.person_decisions !== null && selection.person_decisions > 0 ? t('You decided {n} works yourself.', { n: num(selection.person_decisions) }) : pdfOnly ? '' : t('No decision by you is recorded.')}</p>
        <p className="flow-note">{t('This is not a PRISMA-compliant review.')}</p>
      </section>
      <section>
        <p className="flow-head">{t('Search strategy')}</p>
        {search.queries.length > 0 ? <ul className="flow-list method-queries">{search.queries.map((q, i) => <li key={i}>
          <span><b>{providerName(q.provider)}</b> <code>{q.query}</code><small>{q.date.slice(0, 10)}{q.complete ? '' : ` · ${t('did not end complete')}`}</small></span>
          <strong>{q.provider_total !== null && q.provider_total !== q.records_read ? t('{read} of {total}', { read: num(q.records_read), total: num(q.provider_total) }) : num(q.records_read)}</strong>
        </li>)}</ul> : <p className="flow-note">{t('No search was recorded for this question revision.')}</p>}
        {search.planned_not_sent > 0 && <p className="flow-note">{t('{n} of {total} planned queries were not recorded as sent.', { n: num(search.planned_not_sent), total: num(search.planned) })}</p>}
        <p className="flow-note">{search.chaining.ran ? t('Citation chaining ran: {n} requests read {records} records.', { n: num(search.chaining.requests), records: num(search.chaining.records_read) }) : t('Citation chaining did not run.')}</p>
        {followups === null ? <p className="flow-note">{t('Follow-up searches before this answer: not recorded.')}</p>
          : followups && followups.length > 0 && <ul className="flow-list method-queries">{followups.map(f => <li key={f.run_id}>
            <span>{t('Follow-up search on {date}', { date: f.created_at.slice(0, 10) })}</span>
            <strong>{f.new_works === null ? t('not recorded') : t(f.new_works === 1 ? '{n} new work' : '{n} new works', { n: num(f.new_works) })}</strong>
          </li>)}</ul>}
      </section>
      <section>
        <p className="flow-head">{t('Study selection')}</p>
        <ul className="flow-list">
          <li><span>{t('Works found')}</span><strong>{maybe(selection.works_found)}</strong></li>
          <li><span>{t('Screened (abstract-stage decision)')}</span><strong>{maybe(selection.screened)}</strong></li>
          <li><span>{t('Abstract read by the model')}</span><strong>{maybe(selection.abstract_read)}</strong></li>
          <li><span>{t('Full-text attempts that ran')}</span><strong>{maybe(selection.full_text_attempted)}</strong></li>
          <li><span>{t('Criterion not met')}</span><strong>{maybe(selection.not_met)}</strong></li>
          <li><span>{t('Included')}</span><strong>{maybe(selection.included)}</strong></li>
        </ul>
        {!selection.snapshot && <p className="flow-note">{t('This answer kept no snapshot of the flow when it started, so the flow counts are not shown.')}</p>}
        {selection.criterion && <p className="flow-note">{t('Criterion: {text}', { text: selection.criterion })}</p>}
        <p className="flow-note">{review.approved_by === 'unattended' ? t('Nobody reviewed the search vocabulary; the fast path went on without asking.') : review.approved_by === 'user' || review.approved_by === 'user_edited' ? t('You edited and saved this search plan; it was searched as you saved it.') : t('Who approved the search vocabulary is not recorded.')}</p>
      </section>
      <section>
        <p className="flow-head">{t('Extraction')}</p>
        {extraction.table ? <>
          <p className="method-text">{t('A study table exists for this answer with {n} columns: {list}.', { n: num(extraction.columns.length), list: extraction.columns.join(', ') })}</p>
          {extraction.columns_accepted_automatically > 0 && <p className="flow-note">{t('{n} columns were accepted by the application without your review.', { n: num(extraction.columns_accepted_automatically) })}</p>}
        </> : <p className="flow-note">{t('No study table was built for this answer.')}</p>}
      </section>
      <section>
        <p className="flow-head">{t('Limitations')}</p>
        {limitations.access ? <ul className="flow-list">
          <li><span>{t('Sources given to the model')}</span><strong>{num(limitations.access.given)}</strong></li>
          <li><span>{t('With full text')}</span><strong>{num(limitations.access.full_text)}</strong></li>
          <li><span>{t('Abstract only')}</span><strong>{num(limitations.access.abstract_only)}</strong></li>
        </ul> : <p className="flow-note">{t('What was given to the model is not recorded for this answer.')}</p>}
        <p className="flow-note">{t('The answer lists {n} limitations, {access} of them about access.', { n: num(limitations.answer_limitations), access: num(limitations.access_limitations) })}</p>
      </section>
      <section>
        <p className="flow-head">{t('Evidence base')}</p>
        <p className="method-text">{years ? t('{n} cited sources, published {years}.', { n: num(base.cited_sources), years }) : t('{n} cited sources.', { n: num(base.cited_sources) })}</p>
        <ul className="method-unmeasured">{method.not_measured.map(item => <li key={item}>{t(item)}</li>)}</ul>
      </section>
    </div>
    {!inReport && <AnswerFlowNote answer={answer} />}
    </details>
  </section>
}
