import { type Answer, type ResearchView } from '../lib/api'
import { t, uiLocale } from '../lib/i18n'

// "How this answer was built": the search-to-answer counts as one list a person can read top down, each step a subset
// of the one above it. Every number is a stored count (the flow buckets, the funnel, the answer's own citations); the
// rows of one level add up to the row above. A row with nothing to say is left out.
type Row = { label: string; n: number; note?: string; level: number; onClick?: () => void; strong?: boolean }

export function AnswerBasis({ view, answer, onSources, onAnswer }: {
  view: ResearchView; answer: Answer | null | undefined; onSources: (filter: 'all' | 'included') => void; onAnswer: () => void
}) {
  const funnel = view.counts.funnel
  const b = view.counts.flow?.buckets
  if (!funnel || !b) return null
  const num = (n: number) => n.toLocaleString(uiLocale())

  const notScreened = b.not_screened + b.abstract_not_read
  const outOfScope = b.out_of_scope_model + b.out_of_scope_code
  const byTitle = funnel.candidates_by_title ?? 0
  const readFull = view.counts.fulltext_read_works ?? 0
  const met = b.confirmed + b.included
  const notMet = b.not_met + b.person_not_met
  const forYou = b.queued + b.look_again + b.person_unsure
  const noPdf = b.waiting_for_pdf + b.candidate_not_fetched + b.not_read_yet
  const otherwise = b.person_excluded + b.abstract_by_choice + b.other
  const included = view.counts.included

  // The works the answer cites, by how deep it read them: from full text when any cited passage is not an abstract.
  const depth = new Map<string, boolean>()
  answer?.claims.forEach(c => c.evidence.forEach(e => depth.set(e.work_id, (depth.get(e.work_id) ?? false) || e.kind !== 'abstract')))
  const cited = depth.size
  const citedAbstract = [...depth.values()].filter(full => !full).length
  const includedWorks = new Set(view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included').map(s => s.work_id))
  const citedOutside = [...depth.keys()].filter(w => !includedWorks.has(w)).length

  const rows: Row[] = [
    { label: t('Found'), n: funnel.unique, level: 0, onClick: () => onSources('all') },
    { label: t('Not screened'), n: notScreened, level: 1, note: t('Past this run’s reading limit, not judged') },
    { label: t('No abstract to read'), n: b.abstract_open, level: 1, note: t('Left open, not excluded') },
    { label: t('Survey or review'), n: b.survey, level: 1, note: t('Set aside by its title') },
    { label: t('Out of scope'), n: outOfScope, level: 1, note: t('By the abstract') },
    { label: t('Decided another way'), n: otherwise, level: 1 },
    { label: t('Passed to full text'), n: funnel.candidates, level: 1, note: byTitle > 0
      ? t('{read} after a model read the abstract · {title} on their title', { read: num(funnel.candidates - byTitle), title: num(byTitle) }) : undefined },
    { label: t('Full text read'), n: readFull, level: 2, note: [met && t('{n} met the criterion', { n: num(met) }), notMet && t('{n} did not', { n: num(notMet) }),
      forYou && t('{n} waiting for you', { n: num(forYou) })].filter(Boolean).join(' · ') || undefined },
    { label: t('No PDF found'), n: noPdf, level: 2, note: t('Neither included nor excluded; add the PDF to read it') },
    { label: t('Included'), n: included, level: 0, strong: true, onClick: () => onSources('included'), note: t('The report reads these') },
    ...(answer ? [{ label: t('Cited in the answer'), n: cited, level: 0, strong: true, onClick: onAnswer,
      note: cited ? [t('{n} from full text', { n: num(cited - citedAbstract) }), citedAbstract && t('{n} from the abstract only', { n: num(citedAbstract) }),
        citedOutside && citedOutside !== citedAbstract && t('{n} not included', { n: num(citedOutside) })].filter(Boolean).join(' · ') : undefined }] : []),
  ].filter(row => row.n > 0 || row.level === 0)

  const lead = [t('{found} works found, {n} included.', { found: num(funnel.unique), n: num(included) }),
    answer && cited > 0 && (citedAbstract
      ? t('The answer cites {n} sources, {abstract} of them from the abstract only.', { n: num(cited), abstract: num(citedAbstract) })
      : t('The answer cites {n} sources, all read in full text.', { n: num(cited) }))].filter(Boolean).join(' ')

  return <section className="answer-basis" aria-labelledby="answer-basis-title">
    <h3 id="answer-basis-title">{t(answer ? 'How this answer was built' : 'From search to sources')}</h3>
    <p className="answer-basis-lead">{lead}</p>
    <ul className="answer-basis-rows">
      {rows.map(row => {
        const body = <><span className="answer-basis-label">{row.label}</span><b className="tnum">{num(row.n)}</b>{row.note && <span className="answer-basis-note">{row.note}</span>}</>
        return <li key={row.label} className={`is-level-${row.level}${row.strong ? ' is-strong' : ''}`}>
          {row.onClick ? <button type="button" onClick={row.onClick}>{body}</button> : <div>{body}</div>}
        </li>
      })}
    </ul>
  </section>
}
