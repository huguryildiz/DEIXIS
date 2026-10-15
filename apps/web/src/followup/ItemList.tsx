import { useState } from 'react'
import { Copy, Info, Link, X } from 'lucide-react'
import { api, type Watch, type WatchItem } from '../api'
import { ConnectionIcon } from '../connectionIcons'
import { providerName } from '../labels'
import { useToast } from '../Toast'
import { t } from '../i18n'
import { useFollowUpCommand } from './commands'
import { CommandFeedback } from './CommandFeedback'
import { dateText, timeText } from './labels'

const foundByLabels: Record<Watch['kind'], string> = { protocol_queries: 'search queries', citing_works: 'citing works' }

// The records a follow-up found (mockup `.rec`): the title, when it was published and first seen here and which
// follow-up found it, then Open at publisher, Copy DOI link and Dismiss with an optional reason.
export function ItemList({ items, researchId, watches, reload }: { items: WatchItem[]; researchId: string; watches: Watch[]; reload: () => Promise<void> }) {
  return <ul className="followup-items">{items.map(item => <Item key={item.id} item={item} items={items} researchId={researchId} watches={watches} reload={reload} />)}</ul>
}
function Item({ item, items, researchId, watches, reload }: { item: WatchItem; items: WatchItem[]; researchId: string; watches: Watch[]; reload: () => Promise<void> }) {
  const [dismissing, setDismissing] = useState(false)
  const [reason, setReason] = useState('')
  const toast = useToast()
  const dismiss = useFollowUpCommand(`item:${item.id}:dismiss`, saved => api.dismissWatchItem(researchId, item.id, saved.body, saved.key), reload, () => setDismissing(false))
  const record = item.record
  const url = item.landing_url ?? (item.doi ? `https://doi.org/${item.doi}` : null)
  const copyDoi = async () => {
    try { await navigator.clipboard.writeText(`https://doi.org/${item.doi!.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '')}`); toast('success', t('DOI link copied.')) }
    catch { toast('error', t('The DOI could not be copied: {doi}', { doi: item.doi! })) }
  }
  const finders = [...new Set(item.found_by.flatMap(entry => {
    const id = entry && typeof entry === 'object' && 'watch_id' in entry ? (entry as { watch_id?: unknown }).watch_id : null
    const kind = watches.find(watch => watch.id === id)?.kind
    return kind ? [t(foundByLabels[kind])] : []
  }))]
  const published = record.publication_date_source === 'openalex.publication_date' && record.publication_date ? t('Published {date}', { date: dateText(record.publication_date) }) : t('Publication date not returned')
  return <li className="rec followup-item" data-item-id={item.id}>
    <b data-stored-text>{record.title}</b>
    <small>{published} · {t('first seen here {time}', { time: timeText(item.first_seen_at) })}{finders.length > 0 && <> · {finders.join(', ')}</>}</small>
    <small className="followup-byline"><span data-stored-text>{record.authors.slice(0, 2).join(', ')}{record.authors.length > 2 && ` ${t('and {n} more', { n: record.authors.length - 2 })}`}</span>{record.year && <span>{record.year}</span>}
      <span className="followup-provider"><ConnectionIcon id={record.provider} />{providerName(record.provider)}</span>
      {item.doi && <a className="followup-doi" href={`https://doi.org/${item.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />{item.doi}</a>}
    </small>
    {item.identity_uncertain && <small className="followup-note"><Info size={13} aria-hidden />{t('Records without a DOI may be announced again from another provider.')}</small>}
    {item.may_be_version_json.map((relation, index) => <small className="followup-note" key={`version-${index}`}><Info size={13} aria-hidden />{t(relation.against === 'library' ? 'May be another version of “{title}” (in your library)' : 'May be another version of “{title}” (seen before)', { title: relation.title ?? relation.id ?? '' })}</small>)}
    {item.relations.filter(relation => relation.relation === 'notice_of').map((relation, index) => <small className="followup-note" key={`notice-${index}`}><Info size={13} aria-hidden />{t('Notice about “{title}”', { title: relation.title ?? relation.id ?? '' })}</small>)}
    {item.status === 'merged' && <small>{t('Merged into another item')}{items.find(other => other.id === item.merged_into_item_id)?.record.title && `: ${items.find(other => other.id === item.merged_into_item_id)!.record.title}`}</small>}
    {item.status === 'dismissed' && <small>{t('Dismissed')}{item.dismissed_reason && `: ${item.dismissed_reason}`}{item.dismissed_at && ` · ${timeText(item.dismissed_at)}`}</small>}
    {dismissing && item.status === 'new' ? <form className="why-f followup-dismiss" onSubmit={event => { event.preventDefault(); dismiss.start({ reason: reason.trim() || null, expected_status: 'new' }) }}>
      <label className="lbl" htmlFor={`dismiss-${item.id}`}>{t('Reason (optional)')}<input id={`dismiss-${item.id}`} className="field" maxLength={500} value={reason} disabled={dismiss.locked} autoFocus placeholder={t('e.g. off topic')} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined} onChange={event => setReason(event.target.value)}
        onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); event.preventDefault(); setDismissing(false) } }} /></label>
      <button type="submit" className="btn-pri" disabled={dismiss.locked} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined}>{t('Dismiss')}</button>
      <button type="button" className="ghost" onClick={() => setDismissing(false)}>{t('Cancel')}</button>
    </form> : <div className="rowacts">
      {url ? <a className="followup-publisher" href={url} target="_blank" rel="noreferrer"><Link aria-hidden />{t('Open at publisher')}</a> : <><button type="button" disabled aria-describedby={`publisher-reason-${item.id}`}><Link aria-hidden />{t('Open at publisher')}</button><span id={`publisher-reason-${item.id}`} className="foot-note">{t('No publisher URL or DOI was returned.')}</span></>}
      {item.doi && <button type="button" onClick={() => { void copyDoi() }}><Copy aria-hidden />{t('Copy DOI link')}</button>}
      {item.status === 'new' && <button type="button" disabled={dismiss.locked} aria-describedby={dismiss.locked ? `dismiss-reason-${item.id}` : undefined} onClick={() => setDismissing(true)}><X aria-hidden />{t('Dismiss')}</button>}
    </div>}
    {dismiss.locked && <small id={`dismiss-reason-${item.id}`}>{t('Resolve the pending command before starting another.')}</small>}
    <CommandFeedback command={dismiss} />
  </li>
}
