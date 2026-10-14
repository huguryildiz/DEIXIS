import { type OpenAlexBudgetToday, type Run } from '../api'
import { t, uiLocale } from '../i18n'
import { number, roleWords, timeText, useOpenAlexBudget, useRunUsage } from './usageData'

function budgetSentence(budget: OpenAlexBudgetToday): string {
  const at = budget.as_of ? timeText(budget.as_of) : ''
  if (budget.used_fraction !== null) return t('OpenAlex: {p}% of today’s budget used, in its last stored response ({time}).', { p: Math.round(budget.used_fraction * 100), time: at })
  if (budget.remaining !== null) return budget.unit === 'usd'
    ? t('OpenAlex: ${x} left today, in its last stored response ({time}).', { x: budget.remaining.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }), time: at })
    : t(budget.remaining === 1 ? 'OpenAlex: {n} credit left today, in its last stored response ({time}).' : 'OpenAlex: {n} credits left today, in its last stored response ({time}).', { n: number(budget.remaining), time: at })
  return t('OpenAlex: no budget figure is stored since the daily reset (midnight UTC), so today’s budget is not known.')
}

// The run's Usage box (mockup `.usage-box`): the model calls of this run by role against its limit, and for a search run
// OpenAlex's budget today. The calls and the roles they are split into come from one stored answer.
export function RunUsageBox({ run, cursor }: { run: Run; cursor: number }) {
  const usage = useRunUsage(run.id, cursor)
  const budget = useOpenAlexBudget(run.kind === 'discovery', cursor)
  const limit = run.budget.max_model_calls ?? 0
  const calls = (() => {
    if (!usage.value) return usage.failed ? t('The model calls of this run could not be read.') : t('Reading the model calls of this run…')
    const { total, roles } = usage.value
    if (total === 0) return t('No model was asked in this run.')
    const split = roles.filter(r => r.calls > 0).map(r => t('{role} {n}', { role: t(roleWords[r.role]), n: number(r.calls) })).join(', ')
    return limit && total <= limit
      ? t(total === 1 ? 'The models were asked once (limit {limit}): {split}.' : 'The models were asked {n} times (limit {limit}): {split}.', { n: number(total), limit: number(limit), split })
      : t(total === 1 ? 'The models were asked once: {split}.' : 'The models were asked {n} times: {split}.', { n: number(total), split })
  })()
  return <li className="usage-box">
    <span>{calls}{usage.value && usage.failed ? ` ${t('(not refreshed: the last read failed)')}` : ''}</span>
    {run.kind === 'discovery' && <span>{budget.value ? budgetSentence(budget.value) : budget.failed ? t('OpenAlex’s budget today could not be read.') : t('Reading OpenAlex’s budget today…')}</span>}
  </li>
}

