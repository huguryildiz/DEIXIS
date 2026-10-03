import { useState } from 'react'
import { Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type WatchItem } from '../api'
import { ConnectionIcon } from '../connectionIcons'
import { providerName } from '../labels'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { useFollowUpCommand } from './commands'
import { CommandFeedback } from './CommandFeedback'
import { dateText, timeText } from './labels'

export function ItemList({ items, researchId, reload }: { items: WatchItem[]; researchId: string; reload: () => Promise<void> }) {
  return <ul className="followup-items">{items.map(item => <Item key={item.id} item={item} items={items} researchId={researchId} reload={reload} />)}</ul>
}
function Item({ item, items, researchId, reload }: { item: WatchItem; items: WatchItem[]; researchId: string; reload: () => Promise<void> }) {
  const [dismissing, setDismissing] = useState(false)
  const [reason, setReason] = useState('')
  const toast = useToast()
  const dismiss = useFollowUpCommand(`item:${item.id}:dismiss`, saved => api.dismissWatchItem(researchId, item.id, saved.body, saved.key), reload, () => setDismissing(false))
  const record = item.record
  const url = item.landing_url ?? (item.doi ? `https://doi.org/${item.doi}` : null)
  const copyDoi = async () => {
    try { await navigator.clipboard.writeText(item.doi!); toast('success', t('DOI copied.')) }
    catch { toast('error', t('The DOI could not be copied: {doi}', { doi: item.doi! })) }
  }
  return <li className="followup-item" data-item-id={item.id}>
    <h4 data-stored-text>{record.title}</h4>
    <p className="followup-byline"><span data-stored-text>{record.authors.slice(0, 2).join(', ')}{record.authors.length > 2 && ` ${t('and {n} more', { n: record.authors.length - 2 })}`}</span>{record.year && <span>{record.year}</span>}
      <span className="followup-provider"><ConnectionIcon id={record.provider} />{providerName(record.provider)}</span>
      {item.doi && <a className="followup-doi" href={`https://doi.org/${item.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />{item.doi}</a>}
    </p>
    <p>{record.publication_date_source === 'openalex.publication_date' && record.publication_date ? t('Published {date}', { date: dateText(record.publication_date) }) : t('Publication date not returned')}</p>
    <p>{t('First seen here {time}', { time: timeText(item.first_seen_at) })}</p>
    {item.identity_uncertain && <p className="followup-note"><Info size={14} aria-hidden />{t('Records without a DOI may be announced again from another provider.')}</p>}
    {item.may_be_version_json.map((relation, index) => <p className="followup-note" key={`version-${index}`}><Info size={14} aria-hidden />{t(relation.against === 'library' ? 'May be another version of “{title}” (in your library)' : 'May be another version of “{title}” (seen before)', { title: relation.title ?? relation.id ?? '' })}</p>)}
    {item.relations.filter(relation => relation.relation === 'notice_of').map((relation, index) => <p className="followup-note" key={`notice-${index}`}><Info size={14} aria-hidden />{t('Notice about “{title}”', { title: relation.title ?? relation.id ?? '' })}</p>)}
    {item.status === 'merged' && <p>{t('Merged into another item')}{items.find(other => other.id === item.merged_into_item_id)?.record.title && `: ${items.find(other => other.id === item.merged_into_item_id)!.record.title}`}</p>}
    {item.status === 'dismissed' && <p>{t('Dismissed')}{item.dismissed_reason && `: ${item.dismissed_reason}`}{item.dismissed_at && ` · ${timeText(item.dismissed_at)}`}</p>}
    <div className="followup-actions">
      {url ? <a className="followup-publisher" href={url} target="_blank" rel="noreferrer">{t('Open at publisher')}</a> : <><Button variant="ghost" disabled aria-describedby={`publisher-reason-${item.id}`}>{t('Open at publisher')}</Button><span id={`publisher-reason-${item.id}`}>{t('No publisher URL or DOI was returned.')}</span></>}
      {item.doi && <Button variant="ghost" onClick={() => { void copyDoi() }}>{t('Copy DOI')}</Button>}
      {item.status === 'new' && !dismissing && <Button variant="ghost" disabled={dismiss.locked} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined} onClick={() => setDismissing(true)}>{t('Dismiss')}</Button>}
    </div>
    {dismissing && item.status === 'new' && <form className="followup-dismiss" onSubmit={event => { event.preventDefault(); dismiss.start({ reason: reason.trim() || null, expected_status: 'new' }) }}>
      <label htmlFor={`dismiss-${item.id}`}>{t('Reason (optional)')}</label>
      <textarea id={`dismiss-${item.id}`} maxLength={500} value={reason} disabled={dismiss.locked} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined} onChange={event => setReason(event.target.value)}
        onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setDismissing(false) } }} />
      <div className="followup-actions"><Button variant="outline" type="button" onClick={() => setDismissing(false)}>{t('Cancel')}</Button><Button disabled={dismiss.locked} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined} type="submit">{t('Confirm')}</Button></div>
    </form>}
    {dismiss.locked && <p id={`dismiss-reason-${item.id}`}>{t('Resolve the pending command before starting another.')}</p>}
    <CommandFeedback command={dismiss} />
  </li>
}
