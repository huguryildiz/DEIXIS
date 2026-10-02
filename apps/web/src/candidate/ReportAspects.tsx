import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type CandidateCard, type CandidateListItem, type ReportGap } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { errorText, kindLabels, label, statusLabels } from './labels'

export function ReportAspects({ researchId, reportId, eventCursor, valid, onOpen }: { researchId: string; reportId: string; eventCursor: number; valid: boolean; onOpen: (candidate: { id: string; card?: CandidateCard }) => void }) {
  const [rows, setRows] = useState<ReportGap[] | null>(null)
  const [candidates, setCandidates] = useState<CandidateListItem[]>([])
  const [error, setError] = useState('')
  const [opening, setOpening] = useState<string | null>(null)
  const generation = useRef(0)
  const load = useCallback(() => {
    const request = ++generation.current
    return Promise.allSettled([api.reportGaps(researchId, reportId), api.candidates(researchId)]).then(results => {
    if (request !== generation.current) return
    const [aspects, list] = results
    if (aspects.status === 'rejected' || list.status === 'rejected') { setError(errorText(aspects.status === 'rejected' ? aspects.reason : list.status === 'rejected' ? list.reason : '')); return }
    setRows(aspects.value); setCandidates(list.value); setError('')
    })
  }, [researchId, reportId])
  const invalidate = useCallback(() => { generation.current++ }, [])
  useEffect(() => { void load(); return invalidate }, [load, invalidate, eventCursor])
  async function investigate(row: ReportGap) {
    generation.current++; setOpening(row.id); setError('')
    try { const card = await api.openCandidate(researchId, { origin: 'report_gap', report_id: reportId, gap_row_id: row.id }); onOpen({ id: card.id, card }) }
    catch (e) { setError(errorText(e)) }
    finally { setOpening(null) }
  }
  return <section className="candidate-aspects" aria-label={t('Aspects you can investigate')}><h3>{t('Aspects you can investigate')}</h3>
    {!valid && <Notice tone="attention">{t('This section was not validated; the rows below are what the model proposed, not rows that passed the report’s checks.')}</Notice>}
    <p>{t('Each row is an aspect the report recorded. Investigating one opens a candidate card; nothing is searched until you start a search on the card.')}</p>
    <p>{t('The note above describes the report as it was written; a candidate’s own search status is on its card.')}</p>
    {error && <Notice tone="error">{error}<Button variant="ghost" onClick={() => void load()}>{t('Retry')}</Button></Notice>}
    {!rows ? !error && <p role="status">{t('Loading aspects…')}</p> : rows.length ? <ul>{rows.map(row => <li key={row.id}><p>{label(kindLabels, row.kind)}</p><p data-stored-text>{row.text}</p>
      <ul>{candidates.filter(c => c.origin_gap_row_id === row.id).map(candidate => <li key={candidate.id}><Button variant="ghost" onClick={() => onOpen({ id: candidate.id })}>{t('Open candidate')} · {label(statusLabels, candidate.status?.status ?? 'not_run')}{candidate.origin_changed && <> {t('(a later candidate was opened from this row)')}</>}</Button></li>)}</ul>
      <Button variant="outline" disabled={opening !== null} aria-describedby={opening !== null ? 'candidate-opening' : undefined} onClick={() => void investigate(row)}>{t('Investigate')}</Button>
    </li>)}</ul> : <p>{t('No aspects were recorded for this report.')}</p>}{opening !== null && <p id="candidate-opening" role="status">{t('Opening candidate…')}</p>}
  </section>
}
