import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type AnswerCandidate, type AnswerCandidates } from '../lib/api'
import { t } from '../lib/i18n'
import { errorText, label, statusLabels } from './labels'

// The candidates written from one answer (D98), read again whenever the research's event cursor moves. What is
// returned always belongs to `answerId`: rows read for another answer are never shown under this one, a response that
// arrives after the answer changed (or the thread unmounted) is dropped, and a failed first read shows no rows.
export function useAnswerCandidates(researchId: string, answerId: string, cursor: number, enabled: boolean) {
  const key = `${researchId}:${answerId}`
  const [state, setState] = useState<{ key: string; data: AnswerCandidates | null; error: string }>({ key, data: null, error: '' })
  const generation = useRef(0)
  const load = useCallback(() => {
    const request = ++generation.current
    return api.answerCandidates(researchId, answerId).then(
      fresh => { if (request === generation.current && fresh.answer_id === answerId) setState({ key, data: fresh, error: '' }) },
      e => { if (request === generation.current) setState(old => ({ key, data: old.key === key ? old.data : null, error: errorText(e) })) })
  }, [researchId, answerId, key])
  useEffect(() => {
    const requests = generation
    if (enabled) void load()
    return () => { requests.current++ }
  }, [load, cursor, enabled])
  const current = state.key === key
  return { data: current && state.data?.answer_id === answerId ? state.data : null, error: current ? state.error : '', reload: load }
}

// The status pill an aspect row shows when a claim was already written from it; it opens that candidate.
export function aspectPill(row: AnswerCandidate) {
  if (row.trashed_at) return t('Claim written · in the Trash')
  if (!row.current_version) return t('Claim written · no card yet')
  if (!row.current_version_searched) return t('Claim written · Card V{n} · not searched', { n: row.current_version })
  return t('Claim written · Card V{n} · {status}', { n: row.current_version, status: label(statusLabels, row.search!.status.status) })
}
