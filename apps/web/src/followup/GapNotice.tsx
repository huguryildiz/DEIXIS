import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, type Watch, type WatchCheck, type WatchGap } from '../api'
import { Notice } from '../Notice'
import { t } from '../i18n'
import { CheckDetail } from './CheckDetail'
import { Disclosure } from './Disclosure'
import { gapOutcomeText, stateLabels, timeText } from './labels'

// Page-session acknowledgement only. The stored gap remains readable; reload creates a new session.
const acknowledged = new Set<string>()
function GapText({ gap }: { gap: WatchGap }) {
  return <><p>{t('Not checked between {from} and {to}.', { from: timeText(gap.first_missed_due), to: timeText(gap.noticed_at) })}</p>
    <p>{t(gap.missed_periods === 1 ? '{n} scheduled check missed.' : '{n} scheduled checks missed.', { n: gap.missed_periods })} {gapOutcomeText(gap)}</p>
    {gap.observed_until === null && <p>{t('DEIXIS cannot tell whether the computer was closed, asleep or busy before it opened.')}</p>}</>
}
export function GapNotice({ researchId, watch }: { researchId: string; watch: Watch }) {
  const [hidden, setHidden] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<WatchCheck | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const gap = watch.gaps[0]
  const showCheck = async (cid: string) => {
    setLoading(true)
    try { setLoaded(await api.watchCheck(researchId, watch.id, cid)); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setLoading(false) }
  }
  if (!gap) return null
  return <div className="followup-gaps">
    {!acknowledged.has(gap.id) && hidden !== gap.id && <Notice tone="attention">
      <div data-gap-id={gap.id}><GapText gap={gap} />
        {gap.catch_up_check_id && (gap.catch_up_check_id === watch.last_check?.id
          ? <p>{t('Catch-up check')} · {t(stateLabels[watch.last_check.state])}</p>
          : <><Button variant="outline" disabled={loading} aria-describedby={`gap-loading-${gap.id}`} onClick={() => { void showCheck(gap.catch_up_check_id!) }}>{t('Show catch-up check')}</Button><span id={`gap-loading-${gap.id}`} role="status">{loading ? t('Loading follow-up…') : ''}</span></>)}
        <Button variant="ghost" onClick={() => { acknowledged.add(gap.id); setHidden(gap.id) }}>{t('Acknowledge')}</Button>
      </div>
    </Notice>}
    {error && <Notice tone="error">{error} <Button variant="outline" onClick={() => { if (gap.catch_up_check_id) void showCheck(gap.catch_up_check_id) }}>{t('Retry')}</Button></Notice>}
    {loaded && <CheckDetail check={loaded} />}
    <Disclosure title={t('Gaps not checked ({n})', { n: watch.gaps.length })}>
      {watch.gaps.map(saved => <div className="followup-gap-row" key={saved.id} data-gap-id={saved.id}><GapText gap={saved} /></div>)}
    </Disclosure>
  </div>
}
