import { useEffect, useState } from 'react'
import { ChevronRight, ListChecks } from 'lucide-react'
import { api, type AnswerMethod } from './api'
import { t, uiLocale } from './i18n'
import { providerName } from './labels'
import './MethodBox.css'

// How the answer was reached, from stored rows only (no model call). Counts stay apart: found, read, tried, included,
// given and cited answer different questions, and what no row measures is said, not guessed.

const num = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
const maybe = (n: number | null) => (n === null ? t('not recorded') : num(n))

function oneLine(m: AnswerMethod) {
  const parts = [t(m.search.queries.length === 1 ? '{n} search' : '{n} searches', { n: num(m.search.queries.length) })]
  if (m.selection.works_found !== null) parts.push(t('{n} works found', { n: num(m.selection.works_found) }))
  if (m.selection.included !== null) parts.push(t('{n} included', { n: num(m.selection.included) }))
  parts.push(t('{n} cited', { n: num(m.evidence_base.cited_sources) }))
  return parts.join(' · ')
}

export function MethodBox({ researchId, answerId }: { researchId: string; answerId: string }) {
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
  return <details className="search-summary flow-block method-box">
    <summary><span><ListChecks size={14} aria-hidden />{t('Method')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{oneLine(method)}</small></summary>
    <div className="method-detail">
      <section>
        <p className="flow-head">{t('Approach')}</p>
        <p className="method-text">{t('{providers} searched.', { providers: providers.length ? providers.join(', ') : t('No provider was') })} {selection.abstract_read > 0 ? t('A model read {n} abstracts.', { n: num(selection.abstract_read) }) : t('No model reading of abstracts is recorded.')} {selection.full_text_read > 0 ? t('A model read selected passages from the full text of {n} works.', { n: num(selection.full_text_read) }) : t('No model reading of full texts is recorded.')} {selection.person_decisions > 0 ? t('You decided {n} works yourself.', { n: num(selection.person_decisions) }) : t('No decision by you is recorded.')}</p>
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
      </section>
      <section>
        <p className="flow-head">{t('Study selection')}</p>
        <ul className="flow-list">
          <li><span>{t('Works found')}</span><strong>{maybe(selection.works_found)}</strong></li>
          <li><span>{t('Screened (abstract-stage decision)')}</span><strong>{num(selection.screened)}</strong></li>
          <li><span>{t('Abstract read by the model')}</span><strong>{num(selection.abstract_read)}</strong></li>
          <li><span>{t('Full-text attempts that ran')}</span><strong>{num(selection.full_text_attempted)}</strong></li>
          <li><span>{t('Criterion not met')}</span><strong>{maybe(selection.not_met)}</strong></li>
          <li><span>{t('Included')}</span><strong>{maybe(selection.included)}</strong></li>
        </ul>
        {!selection.snapshot && <p className="flow-note">{t('This answer kept no snapshot of the flow when it started, so the flow counts are not shown.')}</p>}
        {selection.criterion && <p className="flow-note">{t('Criterion: {text}', { text: selection.criterion })}</p>}
        <p className="flow-note">{review.approved_by === 'user' ? t(review.edited ? 'You reviewed and edited the search vocabulary.' : 'You reviewed the search vocabulary.')
          : review.approved_by === 'unattended' ? t('Nobody reviewed the search vocabulary; the fast path went on without asking.') : review.approved_by === 'no_warning' ? t('Nobody reviewed the search vocabulary: the application raised no warning and went on.') : review.approved_by === 'warn_kept' ? t('Nobody reviewed the search vocabulary: the application warned that some terms multiply the matches, kept every one of them and went on. A model’s advice on them, when it gave any, is information only.') : review.approved_by === 'model_advice' ? t('Nobody reviewed the search vocabulary: a model advised on the application’s warnings and the application removed the terms it advised removing.') : t('Who approved the search vocabulary is not recorded.')}</p>
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
  </details>
}
