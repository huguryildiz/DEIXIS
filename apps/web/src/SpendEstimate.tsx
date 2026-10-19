import { useEffect, useState } from 'react'
import { ChevronDown, Coins } from 'lucide-react'
import { spendApi, type Effort, type SpendEstimate, type SpendRole, type SpendRoleChoice } from './api'
import { connectionName, money } from './labels'
import { t, uiLocale } from './i18n'

const roleNames: Record<SpendRole, string> = { literature: 'Literature model', answer: 'Answer model', reviewer: 'Reviewer model' }
// The cost range shown before a research starts, under the depth and model pickers (F4). It is a wide "at least / at most"
// built from call counts per step type, the real size of the instructions each call carries, and assumed sizes for what the
// sources and the model decide; the line under it lists them. Only models paid by API key are priced.
export function SpendEstimateNote({ effort, answer, literature, reviewer }: {
  effort: Effort; answer: SpendRoleChoice | null; literature: SpendRoleChoice | null; reviewer: SpendRoleChoice | null
}) {
  // The answer is kept with the selection it was asked for, so a different model or depth shows nothing until its own
  // answer arrives and a late answer for an older selection is never shown.
  const [answered, setAnswered] = useState<{ key: string; value: SpendEstimate } | null>(null)
  const key = JSON.stringify([effort, answer, literature, reviewer])
  useEffect(() => {
    if (!answer || !literature) return
    let live = true
    const timer = setTimeout(() => {
      spendApi.estimate({ effort, answer, literature, reviewer }).then(result => { if (live) setAnswered({ key, value: result }) }, () => {})
    }, 250)
    return () => { live = false; clearTimeout(timer) }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const data = answered?.key === key ? answered.value : null
  // Nothing is shown unless a selected model is paid by API key: a subscription or a local model has no per-call cost.
  if (!answer || !literature || !data?.applies) return null
  const unpriced = data.roles.filter(r => r.kind === 'api' && !r.priced)
  const free = data.roles.filter(r => r.kind === 'subscription' || r.kind === 'local')
  return <div className="home-estimate" data-testid="spend-estimate">
    <details>
      <summary className="estimate-line">
        <Coins className="estimate-icon" size={15} aria-hidden />
        {data.usd
          ? <span className="estimate-figure"><span className="estimate-label">{t('Estimated cost')}</span>
              <b title={t('Estimated cost: at least {low}, at most {high}.', { low: money(data.usd[0]), high: money(data.usd[1]) })}>{money(data.usd[0])}<span className="estimate-dash">–</span>{money(data.usd[1])}</b></span>
          : <b className="estimate-figure">{t('No cost estimate: DEIXIS has no price for this model.')}</b>}
        <span className="estimate-note">
          {unpriced.length > 0 && data.usd && <>{t('Left out because no price is known: {models}.', { models: unpriced.map(r => `${t(roleNames[r.role])} (${r.model})`).join(', ') })}{' '}</>}
          {t('The provider’s own bill is what counts.')}
        </span>
        <span className="estimate-toggle">{t('How this is estimated')}<ChevronDown size={14} aria-hidden /></span>
      </summary>
      <ul>
        <li>{t('Low: the fewest calls, the smallest inputs, no reasoning. High: every call this depth allows, the largest inputs, each call that can be repaired repaired once, and up to {n} tokens of reasoning per call.', { n: Math.max(...Object.values(data.assumptions.reasoning_tokens)).toLocaleString(uiLocale()) })}</li>
        <li>{t('Instruction sizes are measured; the length of abstracts, passages and answers is assumed ({n} characters per token). Cached input is priced as normal input. Price list dated {date}. Nothing was measured on a real run.', { n: data.assumptions.chars_per_token, date: data.prices.as_of })}</li>
        <li>{data.embedding.paid && data.reranking?.paid && data.reranking.provider === data.embedding.provider
          ? t('Not included: semantic search and reranking on {provider}, billed separately, the study table and follow-up questions.', { provider: connectionName(data.embedding.provider) })
          : data.embedding.paid
            ? t('Not included: semantic search on {provider}, billed separately, the study table and follow-up questions.', { provider: connectionName(data.embedding.provider) })
            : data.reranking?.paid
              ? t('Not included: reranking on {provider}, billed separately, the study table and follow-up questions.', { provider: connectionName(data.reranking.provider ?? '') })
              : t('Not included: the study table and follow-up questions. Semantic search adds nothing here.')}</li>
        {data.embedding.paid && data.reranking?.paid && data.reranking.provider !== data.embedding.provider
          && <li>{t('Reranking on {provider} is billed separately too.', { provider: connectionName(data.reranking.provider ?? '') })}</li>}
        {free.map(r => <li key={r.role}>{t(r.kind === 'subscription' ? '{role} runs on {model}, a subscription: no cost per call.' : '{role} runs on {model} on this computer: no cost per call.', { role: t(roleNames[r.role]), model: r.model ?? '' })}</li>)}
      </ul>
    </details>
  </div>
}
