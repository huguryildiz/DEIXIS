import { useState } from 'react'
import { Button } from '@/components/ui/button'
import type { LineageComponent, LineageLink, LineageNode } from '../api'
import { SourceKey } from '../SourceKey'
import { t } from '../i18n'
import { authorText, edgeLabels, relationLabels, staleLabels, supportText, workText } from './labels'

export type PassageTarget = { passageId: string | null; sourceVersionId?: string; workId?: string; assetId?: string; highlightTexts?: string[]; initialPage?: number }
export type WorkProps = { nodes: Record<string, LineageNode>; onPassage: (target: PassageTarget) => void }
export function WorkName({ id, nodes, onPassage }: WorkProps & { id: string }) {
  const node = nodes[id]
  if (!node) return <span>{t('Source record unavailable')}</span>
  return <span className="lineage-work"><SourceKey value={node.source_key} />{node.year != null && <span>{node.year}</span>}
    <button type="button" className="lineage-source-title" data-stored-text onClick={() => onPassage({ passageId: null, sourceVersionId: id, workId: node.work_id })}>{node.title}</button>
    {!node.live && <span>{t('no longer in this table')}</span>}
  </span>
}
export function LinkRow({ link, component, nodes, onPassage, onEdit, onRemove }: WorkProps & {
  link: LineageLink & { not_live_ends?: ('from' | 'to')[] }; component?: LineageComponent
  onEdit: (link: LineageLink) => void; onRemove: (link: LineageLink) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const first = link.evidence[0]
  const others = component?.adjacency.find(a => a.source_version_id === link.to)?.in_from.filter(id => id !== link.from) ?? []
  const open = (item: LineageLink['evidence'][number]) => onPassage({ passageId: item.passage_id, highlightTexts: [item.anchor_text], initialPage: item.physical_page ?? 1 })
  return <li className={`lineage-link${component?.branches.includes(link.from) ? ' is-branch' : ''}`} data-link-id={link.link_id}>
    {component?.branches.includes(link.from) && <h4>{t('from {work}', { work: workText(nodes[link.from]) })}</h4>}
    <button type="button" className="lineage-link-open" aria-label={t('{from} to {to}, {relation}, {support}', { from: workText(nodes[link.from]), to: workText(nodes[link.to]), relation: t(relationLabels[link.relation]), support: supportText(link.support_type) })}
      disabled={!first} onClick={() => { setExpanded(true); if (first) open(first) }}>
      <span><SourceKey value={nodes[link.from]?.source_key} />{!nodes[link.from]?.source_key && <span data-stored-text>{nodes[link.from]?.title ?? t('Source record unavailable')}</span>} {nodes[link.from]?.year}</span>
      <span aria-hidden> → </span><span className="sr-only">{t('to')}</span>
      <span><SourceKey value={nodes[link.to]?.source_key} />{!nodes[link.to]?.source_key && <span data-stored-text>{nodes[link.to]?.title ?? t('Source record unavailable')}</span>} {nodes[link.to]?.year}</span>
      <span> · {t(relationLabels[link.relation])} · {supportText(link.support_type)}{link.edge_state && <> · {t('citation list: {state}', { state: t(edgeLabels[link.edge_state]) })}</>}</span>
      <span className="lineage-changed" data-stored-text>{link.what_changed}</span>
    </button>
    <p>{authorText(link.author)}{link.human_edited && <> · {t('human edited')}</>}{link.note != null && <> · <span data-stored-text className="lineage-stored">{link.note}</span></>}</p>
    <p><WorkName id={link.from} nodes={nodes} onPassage={onPassage} /> <span aria-hidden> → </span> <WorkName id={link.to} nodes={nodes} onPassage={onPassage} /></p>
    {others.length > 0 && <p>{t('also from {works}', { works: others.map(id => workText(nodes[id])).join(', ') })}</p>}
    {link.unexpected_no_citation_edge && <p>{t('the later work does not cite the earlier one in its stored reference list')}</p>}
    {link.year_order_warning && <p>{t('the later work has an earlier year than the source')}</p>}
    {link.not_head_ends.map(end => <p key={end}>{workText(nodes[link[end]])}: {t('this version is not the head of its work')}</p>)}
    {link.not_live_ends?.map(end => <p key={end}>{workText(nodes[link[end]])}: {t('no longer in this table')}</p>)}
    {link.output_status === 'unverified_draft' && <p>{t('draft, not structurally validated')}</p>}
    {link.stale_reasons.map(r => <p key={r}>{t(staleLabels[r])}</p>)}
    {!first && <p>{t('No stored evidence to open.')}</p>}
    <div className="lineage-actions">
      {link.evidence.length > 1 && <Button variant="ghost" size="sm" aria-expanded={expanded} onClick={() => setExpanded(v => !v)}>{t('Evidence items · {n}', { n: link.evidence.length })}</Button>}
      <Button variant="ghost" size="sm" onClick={() => onEdit(link)}>{t('Edit')}</Button>
      <Button variant="ghost" size="sm" onClick={() => onRemove(link)}>{t('Remove')}</Button>
    </div>
    {expanded && link.evidence.length > 1 && <ul>{link.evidence.map((item, i) => <li key={`${item.passage_id}:${i}`}>
      <button type="button" className="lineage-source-title" onClick={() => open(item)}>{t('Evidence {i} of {n}', { i: i + 1, n: link.evidence.length })}{item.physical_page != null && <> · {t('PDF p. {page}', { page: item.physical_page })}</>}{item.printed_label && <> · <span data-stored-text>{item.printed_label}</span></>}</button>
      <blockquote data-stored-text className="lineage-stored">{item.anchor_text}</blockquote>
    </li>)}</ul>}
  </li>
}
