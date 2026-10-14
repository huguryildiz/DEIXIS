import { useCallback, useEffect, useRef, useState } from 'react'
import { usageApi, type OpenAlexBudgetToday, type Run, type Usage, type UsageRole } from '../api'
import { t, uiLocale } from '../i18n'

// What runs spent (R17, RL8; UI parity S27), read from what the app stored: model calls are the run's stored model
// sessions grouped by Settings role (api/usage_routes.py), never an estimate; the OpenAlex figure is the newest stored
// OpenAlex response since the daily reset (midnight UTC), shown with its time and named as that response, never as a
// live reading. A figure the records do not hold is said to be unknown, never 0.

export const number = (n: number) => n.toLocaleString(uiLocale())
export const timeText = (iso: string) => new Date(iso).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' })
export const roleWords: Record<UsageRole, string> = { literature: 'literature', answer: 'answer', reviewer: 'reviewer' }

// A read that follows the research's events: one request at a time, a later event while it runs asks once more after
// it, and an answer that arrives after a newer read started is dropped. `failed` is set when the latest read failed;
// the last good answer is kept beside it.
// `key` names what is read (null: nothing); a new key starts afresh and drops the answers of the old one.
function useStoredRead<T>(key: string | null, read: () => Promise<T>, cursor: number) {
  const [state, setState] = useState<{ key: string | null; value: T | null; failed: boolean }>({ key: null, value: null, failed: false })
  const flight = useRef({ running: false, again: false, seq: 0, key: null as string | null, read })
  useEffect(() => {
    const f = flight.current
    f.read = read
    if (f.key !== key) { f.key = key; f.seq++ }  // an answer still coming for the previous key is dropped
    const go = () => {
      if (f.key === null) return
      if (f.running) { f.again = true; return }
      const seq = ++f.seq, asked = f.key
      f.running = true
      f.read().then(value => { if (seq === f.seq) setState({ key: asked, value, failed: false }) },
        () => { if (seq === f.seq) setState(previous => ({ key: asked, value: previous.key === asked ? previous.value : null, failed: true })) })
        .finally(() => {
          f.running = false
          if (f.again) { f.again = false; go() }
        })
    }
    go()
  }, [key, cursor, read])
  return state.key === key ? state : { key, value: null, failed: false }
}

export function useRunUsage(runId: string | null, cursor: number) {
  const read = useCallback(() => usageApi.usageOfRun(runId ?? ''), [runId])
  return useStoredRead<Usage>(runId && `run:${runId}`, read, cursor)
}

export function useOpenAlexBudget(enabled: boolean, cursor: number) {
  return useStoredRead<OpenAlexBudgetToday>(enabled ? 'openalex' : null, usageApi.openAlexBudgetToday, cursor)
}

// The budget as a short figure (the rail) and as a sentence (the run's Usage box). With a limit header it is the share
// used; without one, what is left in OpenAlex's own unit (dollars or credits, never converted, §2.3).
export function budgetFigure(budget: OpenAlexBudgetToday): string | null {
  if (budget.used_fraction !== null) return t('{p}%', { p: Math.round(budget.used_fraction * 100) })
  if (budget.remaining === null) return null
  return budget.unit === 'usd' ? t('${x} left', { x: budget.remaining.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })
    : t(budget.remaining === 1 ? '{n} credit left' : '{n} credits left', { n: number(budget.remaining) })
}

export function budgetAsOf(budget: OpenAlexBudgetToday): string | null {
  return budget.as_of ? t('Last stored response, {time}', { time: timeText(budget.as_of) }) : null
}

// The run whose calls the rail's Usage box shows: the newest run of the research that had a model-call limit.
export function usageRun(runs: Run[]): Run | null {
  return runs.find(run => (run.budget.max_model_calls ?? 0) > 0) ?? null
}
