import { useEffect, useState } from 'react'
import { spendApi, type Effort, type SpendEstimate, type SpendRole, type SpendRoleChoice } from './api'
import { connectionName, money } from './labels'
import { t, uiLocale } from './i18n'

const roleNames: Record<SpendRole, string> = { literature: 'Literature model', answer: 'Answer model', reviewer: 'Reviewer model' }
const taskNames: Record<string, string> = {
  research_title: 'Research title', vocabulary_labels: 'Grouping the search terms', search_query: 'Writing the search query', criterion_proposal: 'Inclusion criterion',
  abstract_screening: 'Screening abstracts', fulltext_adjudication: 'Reading full text', grounded_answer: 'Writing the answer', answer_review: 'Reviewing the answer',
}
const range = (pair: [number, number]) => pair[0] === pair[1] ? pair[0].toLocaleString(uiLocale()) : `${pair[0].toLocaleString(uiLocale())}–${pair[1].toLocaleString(uiLocale())}`

// The cost range shown before a research starts, under the depth and model pickers (F4). It is a wide "at least / at most"
// built from call counts per step type, the real size of the instructions each call carries, and assumed sizes for what the
// sources and the model decide; the line under it lists them. Only models paid by API key are priced.
export function SpendEstimateNote({ effort, answer, literature, reviewer }: {
  effort: Effort; answer: SpendRoleChoice | null; literature: SpendRoleChoice | null; reviewer: SpendRoleChoice | null
}) {
  const [data, setData] = useState<SpendEstimate | null>(null)
  const key = JSON.stringify([effort, answer, literature, reviewer])
  useEffect(() => {
    if (!answer || !literature) return
    let live = true
    const timer = setTimeout(() => {
      spendApi.estimate({ effort, answer, literature, reviewer }).then(result => { if (live) setData(result) }, () => { if (live) setData(null) })
    }, 250)
    return () => { live = false; clearTimeout(timer) }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!answer || !literature || !data?.applies) return null
  const unpriced = data.roles.filter(r => r.kind === 'api' && !r.priced)
  const free = data.roles.filter(r => r.kind === 'subscription' || r.kind === 'local')
  return <div className="home-estimate" data-testid="spend-estimate">
    <p>
      {data.usd
        ? <><b>{t('Estimated cost: at least {low}, at most {high}.', { low: money(data.usd[0]), high: money(data.usd[1]) })}</b>{' '}</>
        : <b>{t('No cost estimate: DEIXIS has no price for this model.')}{' '}</b>}
      {unpriced.length > 0 && data.usd && t('Left out because no price is known: {models}.', { models: unpriced.map(r => `${t(roleNames[r.role])} (${r.model})`).join(', ') })}{' '}
      {t('The provider’s own bill is what counts.')}
    </p>
    <details>
      <summary>{t('How this is estimated')}</summary>
      <ul>
        {data.tasks.filter(task => data.roles.find(r => r.role === task.role)?.priced).map(task => <li key={task.task}>
          {t('{step}: {calls} calls, about {input} tokens in and {output} tokens out per call', {
            step: t(taskNames[task.task] ?? task.task), calls: range(task.calls), input: range(task.input_tokens), output: range(task.output_tokens) })}
        </li>)}
        <li>{t('The low figure is the fewest calls with the smallest inputs and no reasoning. The high figure is every call this depth allows, the largest inputs, every call that can be repaired is repaired once, and the model reasoning up to {n} tokens per call.', { n: Math.max(...Object.values(data.assumptions.reasoning_tokens)).toLocaleString(uiLocale()) })}</li>
        <li>{t('The instructions each call carries are measured. The length of abstracts, passages and answers is assumed, at {n} characters per token. Nothing here was measured on a real run.', { n: data.assumptions.chars_per_token })}</li>
        <li>{t('Cached input is priced as normal input. The price list is dated {date}.', { date: data.prices.as_of })}</li>
        <li>{data.embedding.paid
          ? t('Not included: semantic search runs on {provider}, which bills it separately.', { provider: connectionName(data.embedding.provider) })
          : t('Semantic search runs on this computer or is off, so it adds nothing.')}</li>
        <li>{t('Not included: the study table and follow-up questions.')}</li>
        {free.map(r => <li key={r.role}>{t(r.kind === 'subscription' ? '{role} runs on {model}, a subscription: no cost per call.' : '{role} runs on {model} on this computer: no cost per call.', { role: t(roleNames[r.role]), model: r.model ?? '' })}</li>)}
      </ul>
    </details>
  </div>
}
