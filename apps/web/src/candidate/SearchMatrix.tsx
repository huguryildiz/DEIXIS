import type { CandidateCard, CandidateCell, CandidateHit, CandidateMatrix } from '../api'
import { Button } from '@/components/ui/button'
import { TriangleAlert } from 'lucide-react'
import { ConnectionIcon as ProviderIcon } from '../connectionIcons'
import { providerName } from '../labels'
import { t } from '../i18n'
import { alignmentLabels, assessmentLabels, depthLabels, kindLabels, label, outcomeLabels, relationLabels, runReasonLabels } from './labels'

export function QueryList({ matrix }: { matrix: CandidateMatrix }) {
  return <><h4>{t('Provider searches')} · {matrix.queries.length}</h4>{matrix.queries.length ? <ul className="candidate-queries">{matrix.queries.map(query => <li key={query.position}>
    <p><ProviderIcon id={query.provider} />{providerName(query.provider)} · {label(outcomeLabels, query.status)} · {t('{n} records', { n: query.record_count })}</p>
    <p data-stored-text>{query.query_text}</p>{query.error_code && <p>{label(runReasonLabels, query.error_code)}</p>}
  </li>)}</ul> : <p>{t('None.')}</p>}
  <details><summary>{t('Rendered queries')} · {matrix.search.rendered_queries.length}</summary>{matrix.search.rendered_queries.length ? <ul>{matrix.search.rendered_queries.map((query, i) => <li key={i}><ProviderIcon id={query.provider_id} />{providerName(query.provider_id)}<p data-stored-text>{query.query_text}</p><p data-stored-text>{query.rationale}</p>{query.dropped_terms?.length ? <p>{t('Terms omitted from {provider}:', { provider: providerName(query.provider_id) })} <span data-stored-text>{query.dropped_terms.join(', ')}</span></p> : <p>{t('Omitted terms: none.')}</p>}</li>)}</ul> : <p>{t('None.')}</p>}</details>
  <p>{t('Skipped terms:')} {matrix.search.skipped_terms.length ? <span data-stored-text>{matrix.search.skipped_terms.join(', ')}</span> : t('None.')}</p></>
}
export function CellText({ cell }: { cell: CandidateCell }) {
  const attention = cell.relation === 'uncertain' || cell.condition_alignment === 'unclear'
  return <div className={attention ? 'candidate-attention' : ''}>{attention && <TriangleAlert size={14} aria-hidden />}<span>{label(relationLabels, cell.relation)}</span>
    {cell.condition_alignment && <span> · {label(alignmentLabels, cell.condition_alignment)}</span>}<p>{t('Model’s note:')} <span data-stored-text>{cell.note}</span></p></div>
}
export function HitOutcome({ hit, matrix }: { hit: CandidateHit; matrix: CandidateMatrix }) {
  const summary = matrix.summary?.hits.find(h => h.source_version_id === hit.source_version_id)
  return <><p className={hit.assessment_state === 'insufficient_access' ? 'candidate-attention' : ''}>{hit.assessment_state === 'insufficient_access' && <TriangleAlert size={14} aria-hidden />}{label(assessmentLabels, hit.assessment_state)}</p>
    {summary && <><p>{t('Recorded outcome:')} {label(outcomeLabels, summary.outcome)}{summary.reason && <> · {label(runReasonLabels, summary.reason)}</>}</p>
      <p>{t('Passages omitted for the page limit: {page}; for message size: {size}.', { page: summary.omitted.page_limit ?? 0, size: summary.omitted.message_size ?? 0 })}</p></>}
  </>
}
export function SearchMatrix({ card, matrix, onEvidence }: { card: CandidateCard; matrix: CandidateMatrix; onEvidence: (hit: CandidateHit, control: HTMLElement) => void }) {
  const version = card.versions.find(v => v.id === matrix.candidate_version_id)
  const facts = matrix.search_status.facts
  const counts = matrix.counts
  return <section className="candidate-section candidate-matrix-section" aria-label={t('Claim matrix')}>
    <h3>{t('Claim matrix')} · {t('Version {n}', { n: matrix.version })}</h3>
    <p>{t('Found {found} results in {queries} provider searches; {kept} works were kept for assessment, {assessed} of them were assessed; {cut} results ranked lower were not read; {duplicates} duplicates were merged.', { found: counts.found, queries: matrix.queries.length, kept: counts.kept, assessed: facts.assessed, cut: counts.rank_cut, duplicates: counts.duplicates })}</p>
    <p>{t('{n} kept works have an assessment that did not complete.', { n: counts.kept - facts.assessed })}</p>
    <p>{t('Frozen reading depth of kept works: abstract {abstract}, stored passages {stored}, metadata only {metadata}. These counts do not count completed readings.', { abstract: facts.reading_depths.abstract, stored: facts.reading_depths.stored_passages, metadata: facts.reading_depths.metadata_only })}</p>
    <p>{t('Only the works kept for assessment are listed. Lower-ranked results and merged duplicates are counted here, not listed.')}</p>
    <QueryList matrix={matrix} />
    <details><summary>{t('Search terms the model wrote')}</summary>{(['setting', 'task', 'setting_backup', 'task_backup'] as const).map(block => <section key={block}><h4>{t({ setting: 'Setting terms', task: 'Task terms', setting_backup: 'Setting backup terms', task_backup: 'Task backup terms' }[block])}</h4>{matrix.search.query_block[block].length ? <ul>{matrix.search.query_block[block].map((term, i) => <li key={i}><span data-stored-text>{term.term}</span>{'kind' in term && <><p data-stored-text>{term.kind}</p><p data-stored-text>{term.why}</p></>}</li>)}</ul> : <p>{t('None.')}</p>}</section>)}</details>
    {!version ? <p>{t('The version’s elements are unavailable; refresh the card.')}</p> : <table className="candidate-matrix"><caption>{t('Kept works against this version’s elements')}</caption><thead><tr><th scope="col">{t('Work')}</th>{version.elements.map(element => <th scope="col" key={element.id}>{label(kindLabels, element.kind)}<p data-stored-text>{element.text}</p></th>)}</tr></thead>
      <tbody>{matrix.hits.map(hit => {
        const cells = matrix.cells[hit.source_version_id] ?? {}
        return <tr key={hit.source_version_id}><th scope="row"><p>{t('Rank {n}', { n: hit.rank })}</p><button type="button" className="candidate-work-title" data-candidate-focus={`title:${hit.source_version_id}`} data-stored-text onClick={e => onEvidence(hit, e.currentTarget)}>{hit.source.title}</button>
          <p>{hit.source.year} <span data-stored-text>{hit.source.venue}</span></p><span className={`ref-pill is-${hit.reading_depth === 'abstract' ? 'abstract' : hit.reading_depth === 'stored_passages' ? 'text' : 'unstated'}`}>{label(depthLabels, hit.reading_depth)}</span>
          <HitOutcome hit={hit} matrix={matrix} />{hit.work_relevance && <p>{t('Work relevance:')} {label(outcomeLabels, hit.work_relevance)}</p>}
          {hit.assessment_state === 'assessed' && hit.states_whole_claim !== null && <p>{t('States the whole claim: {answer}', { answer: t(hit.states_whole_claim ? 'yes' : 'no') })}</p>}
          {hit.note !== null && <p>{t('Model’s note:')} <span data-stored-text>{hit.note}</span></p>}
          <Button size="sm" variant="ghost" data-candidate-focus={`evidence:${hit.source_version_id}`} onClick={e => onEvidence(hit, e.currentTarget)}>{t('Show evidence')}</Button></th>
          {Object.keys(cells).length === 0 ? <td colSpan={version.elements.length}><p>{t('No cells are published for this work: {reason}.', { reason: label(assessmentLabels, hit.assessment_state) })}</p></td> : version.elements.map(element => <td key={element.id}><div className="candidate-mobile-element">{label(kindLabels, element.kind)}: <span data-stored-text>{element.text}</span></div>{cells[element.id] ? <CellText cell={cells[element.id]} /> : <p>{t('No cell was recorded for this element.')}</p>}</td>)}
        </tr>
      })}</tbody></table>}
    {!matrix.hits.length && <p>{t('No kept works were recorded.')}</p>}
  </section>
}
