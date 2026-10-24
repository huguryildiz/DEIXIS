import type { CandidateCard, CandidateCell, CandidateHit, CandidateMatrix } from '../api'
import { ChevronRight, TriangleAlert } from 'lucide-react'
import { ConnectionIcon as ProviderIcon } from '../connectionIcons'
import { providerName } from '../labels'
import { t } from '../i18n'
import { alignmentLabels, assessmentLabels, depthLabels, kindLabels, label, outcomeLabels, relationLabels, relationTones, runReasonLabels } from './labels'

export function QueryList({ matrix, heading = true }: { matrix: CandidateMatrix; heading?: boolean }) {
  return <>{heading && <h5>{t('Provider searches')} · {matrix.queries.length}</h5>}{matrix.queries.length ? <ul className="candidate-queries">{matrix.queries.map(query => <li key={query.position}>
    <p><ProviderIcon id={query.provider} />{providerName(query.provider)} · {label(outcomeLabels, query.status)} · {t('{n} records', { n: query.record_count })}</p>
    <p data-stored-text>{query.query_text}</p>{query.error_code && <p>{label(runReasonLabels, query.error_code)}</p>}
  </li>)}</ul> : <p>{t('None.')}</p>}
  <details><summary><ChevronRight size={14} aria-hidden />{t('Rendered queries')} · {matrix.search.rendered_queries.length}</summary>{matrix.search.rendered_queries.length ? <ul>{matrix.search.rendered_queries.map((query, i) => <li key={i}><ProviderIcon id={query.provider_id} />{providerName(query.provider_id)}<p data-stored-text>{query.query_text}</p><p data-stored-text>{query.rationale}</p>{query.dropped_terms?.length ? <p>{t('Terms omitted from {provider}:', { provider: providerName(query.provider_id) })} <span data-stored-text>{query.dropped_terms.join(', ')}</span></p> : <p>{t('Omitted terms: none.')}</p>}</li>)}</ul> : <p>{t('None.')}</p>}</details>
  <p>{t('Skipped terms:')} {matrix.search.skipped_terms.length ? <span data-stored-text>{matrix.search.skipped_terms.join(', ')}</span> : t('None.')}</p></>
}
// A matrix cell (mockup `.mx .rel`): the model's reading of one element, a warning mark when it is uncertain or the
// conditions are unclear, the condition alignment and the model's note.
function CellText({ cell }: { cell: CandidateCell }) {
  const attention = cell.relation === 'uncertain' || cell.condition_alignment === 'unclear'
  return <><span className={`rel ${relationTones[cell.relation] ?? 'none'}`}>{attention && <TriangleAlert size={11} aria-label={t('Needs attention')} />}{label(relationLabels, cell.relation)}</span>
    {cell.condition_alignment && <div className="src-m">{label(alignmentLabels, cell.condition_alignment)}</div>}<div className="src-m">{t('Model’s note:')} <span data-stored-text>{cell.note}</span></div></>
}
export function HitOutcome({ hit, matrix }: { hit: CandidateHit; matrix: CandidateMatrix }) {
  const summary = matrix.summary?.hits.find(h => h.source_version_id === hit.source_version_id)
  return <>{hit.assessment_state !== 'assessed' && <div className={`src-m${hit.assessment_state === 'insufficient_access' ? ' candidate-attention' : ''}`}>{label(assessmentLabels, hit.assessment_state)}</div>}
    {summary && <><div className="src-m">{t('Recorded outcome:')} {label(outcomeLabels, summary.outcome)}{summary.reason && <> · {label(runReasonLabels, summary.reason)}</>}</div>
      {(summary.omitted.page_limit || summary.omitted.message_size) ? <div className="src-m">{t('Passages omitted for the page limit: {page}; for message size: {size}.', { page: summary.omitted.page_limit ?? 0, size: summary.omitted.message_size ?? 0 })}</div> : null}</>}
  </>
}
// The claim matrix of one search (mockup "Claim matrix · Version n"): what the search found and kept, then each kept
// work against the version's elements. A work's title opens the evidence that search supplied to the model.
export function SearchMatrix({ card, matrix, onEvidence }: { card: CandidateCard; matrix: CandidateMatrix; onEvidence: (hit: CandidateHit, control: HTMLElement) => void }) {
  const version = card.versions.find(v => v.id === matrix.candidate_version_id)
  const facts = matrix.search_status.facts
  const counts = matrix.counts
  const incomplete = counts.kept - facts.assessed
  return <section className="candidate-matrix-section" aria-labelledby={`candidate-matrix-${matrix.kill_search_id}`}>
    <h4 className="sub" id={`candidate-matrix-${matrix.kill_search_id}`}>{t('Claim matrix')} · {t('Version {n}', { n: matrix.version })}</h4>
    <p className="foot-note">{t('Found {found} results in {queries} provider searches; {kept} works were kept for assessment, {assessed} of them were assessed; {cut} results ranked lower were not read; {duplicates} duplicates were merged.', { found: counts.found, queries: matrix.queries.length, kept: counts.kept, assessed: facts.assessed, cut: counts.rank_cut, duplicates: counts.duplicates })}{incomplete > 0 && <> {t('{n} kept works have an assessment that did not complete.', { n: incomplete })}</>}</p>
    <p className="foot-note">{t('Frozen reading depth of kept works: abstract {abstract}, stored passages {stored}, metadata only {metadata}. These counts do not count completed readings.', { abstract: facts.reading_depths.abstract, stored: facts.reading_depths.stored_passages, metadata: facts.reading_depths.metadata_only })}</p>
    {!version ? <p className="foot-note">{t('The version’s elements are unavailable; refresh the card.')}</p> : <div className="tbl-wrap candidate-matrix-wrap" tabIndex={0} role="region" aria-label={t('Claim matrix, scrolls sideways')}><table className="mx candidate-matrix"><caption className="sr-only">{t('Kept works against this version’s elements')}</caption><thead><tr><th scope="col">{t('Kept work')}</th>{version.elements.map((element, i) => <th scope="col" key={element.id}>E{i + 1} · {label(kindLabels, element.kind)}<div className="src-m" data-stored-text>{element.text}</div></th>)}</tr></thead>
      <tbody>{matrix.hits.map(hit => {
        const cells = matrix.cells[hit.source_version_id] ?? {}
        return <tr key={hit.source_version_id}><th scope="row"><div className="src-m">{t('Rank {n}', { n: hit.rank })}</div><button type="button" className="src-t candidate-work-title" data-candidate-focus={`title:${hit.source_version_id}`} data-stored-text onClick={e => onEvidence(hit, e.currentTarget)}>{hit.source.title}</button>
          <div className="src-m">{hit.source.year} <span data-stored-text>{hit.source.venue}</span></div>
          <div className="src-m">{label(depthLabels, hit.reading_depth)}{hit.assessment_state === 'assessed' && <> · {t('assessed')}</>}</div>
          {hit.assessment_state === 'assessed' && hit.states_whole_claim !== null && <div className="src-m">{t('States the whole claim: {answer}', { answer: t(hit.states_whole_claim ? 'yes' : 'no') })}</div>}
          <HitOutcome hit={hit} matrix={matrix} />{hit.work_relevance && <div className="src-m">{t('Work relevance:')} {label(outcomeLabels, hit.work_relevance)}</div>}
          {hit.note !== null && <div className="src-m">{t('Model’s note:')} <span data-stored-text>{hit.note}</span></div>}</th>
          {Object.keys(cells).length === 0 ? <td colSpan={version.elements.length}><span className="src-m">{t('No cells are published for this work: {reason}.', { reason: label(assessmentLabels, hit.assessment_state) })}</span></td> : version.elements.map(element => <td key={element.id}>{cells[element.id] ? <CellText cell={cells[element.id]} /> : <span className="src-m">{t('No cell was recorded for this element.')}</span>}</td>)}
        </tr>
      })}</tbody></table></div>}
    {!matrix.hits.length && <p className="foot-note">{t('No kept works were recorded.')}</p>}
    <p className="foot-note">{t('Only the works kept for assessment are listed. Lower-ranked results and merged duplicates are counted here, not listed.')} {t('Relations are model readings; whether a quote supports its element was not checked.')}</p>
    <details className="mk-more candidate-queries-more"><summary><ChevronRight size={14} aria-hidden />{t('Provider searches')} · {matrix.queries.length}</summary><QueryList matrix={matrix} heading={false} /></details>
    <details className="mk-more"><summary><ChevronRight size={14} aria-hidden />{t('Search terms the model wrote')}</summary>{(['setting', 'task', 'setting_backup', 'task_backup'] as const).map(block => <section key={block}><h5>{t({ setting: 'Setting terms', task: 'Task terms', setting_backup: 'Setting backup terms', task_backup: 'Task backup terms' }[block])}</h5>{matrix.search.query_block[block].length ? <ul>{matrix.search.query_block[block].map((term, i) => <li key={i}><span data-stored-text>{term.term}</span>{'kind' in term && <><p data-stored-text>{term.kind}</p><p data-stored-text>{term.why}</p></>}</li>)}</ul> : <p>{t('None.')}</p>}</section>)}</details>
  </section>
}
