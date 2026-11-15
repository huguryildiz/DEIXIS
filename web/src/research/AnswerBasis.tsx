import { useState, type ReactNode } from 'react'
import { BookOpen, ChevronRight } from 'lucide-react'
import { type Answer, type ResearchView } from '../lib/api'
import { t, uiLocale } from '../lib/i18n'
import { statementExcludedReasons } from '../lib/labels'

// "How this answer was built": the search-to-answer counts as one list a person can read top down, each step a subset
// of the one above it. Every number is a stored count (the flow buckets, the funnel, the answer's own citations); the
// rows of one level add up to the row above. A row with nothing to say is left out.
type Row = { label: string; n: number; note?: string; level: number; onClick?: () => void; strong?: boolean }
// One bar segment: a share of the bar's own total, coloured by its tone, named again in the legend beside its count.
export type Part = { label: string; n: number; tone: 'idle' | 'open' | 'out' | 'next' | 'read' }

// A stacked bar with its legend: widths are shares of the parts' own sum, so the bar always fills its row.
export function Bar({ title, parts, num, aside }: { title: string; parts: Part[]; num: (n: number) => string; aside?: ReactNode }) {
  const shown = parts.filter(part => part.n > 0)
  const total = shown.reduce((sum, part) => sum + part.n, 0)
  if (total === 0) return null
  const text = shown.map(part => `${part.label} ${num(part.n)}`).join(', ')
  return <div className="answer-basis-bar">
    <span className="answer-basis-bar-title">{title}{aside && <span className="answer-basis-bar-aside">{aside}</span>}</span>
    <span className="answer-basis-bar-track" role="img" aria-label={`${title}: ${text}`}>
      {shown.map(part => <span key={part.label} className={`is-${part.tone}`} style={{ flexGrow: part.n }} title={`${part.label} ${num(part.n)}`} />)}
    </span>
    <ul className="answer-basis-legend" aria-hidden>
      {shown.map(part => <li key={part.label}><span className={`answer-basis-dot is-${part.tone}`} />{part.label} <b className="tnum">{num(part.n)}</b></li>)}
    </ul>
  </div>
}

type BasisProps = { view: ResearchView; answer: Answer | null | undefined; onSources: (filter: 'all' | 'included') => void; onAnswer: () => void }

// The stored counts both basis pieces read; null when the research has no search funnel (attached PDFs only).
function basisCounts({ view, answer, onSources, onAnswer }: BasisProps) {
  const funnel = view.counts.funnel
  const b = view.counts.flow?.buckets
  if (!funnel || !b) return null
  const num = (n: number) => n.toLocaleString(uiLocale())

  const notScreened = b.not_screened + b.abstract_not_read
  const outOfScope = b.out_of_scope_model + (b.out_of_scope_one_read ?? 0) + b.out_of_scope_code
  const byTitle = funnel.candidates_by_title ?? 0
  const readFull = view.counts.fulltext_read_works ?? 0
  const met = b.confirmed + b.included
  const notMet = b.not_met + b.person_not_met
  const forYou = b.queued + b.look_again + b.person_unsure
  // Three different reasons a passed work has no full-text read: no PDF found, text on hand but not read, not tried.
  const noPdf = b.waiting_for_pdf
  const notRead = b.not_read_yet
  const notTried = b.candidate_not_fetched
  const otherwise = b.person_excluded + b.abstract_by_choice + b.other
  const included = view.counts.included

  // The works the answer cites, by how deep it read them: from full text when any cited passage is not an abstract.
  const depth = new Map<string, boolean>()
  answer?.claims.forEach(c => c.evidence.forEach(e => depth.set(e.work_id, (depth.get(e.work_id) ?? false) || e.kind !== 'abstract')))
  const cited = depth.size
  const citedAbstract = [...depth.values()].filter(full => !full).length
  const includedWorks = new Set(view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included').map(s => s.work_id))
  const citedOutside = [...depth.keys()].filter(w => !includedWorks.has(w)).length

  const roles = answer?.answer_roles
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
    { label: t('Text on hand, not read'), n: notRead, level: 2, note: t('Its text is stored but was not read before the cutoff') },
    { label: t('Full text not tried'), n: notTried, level: 2, note: t('Past this run’s full-text limit, not judged') },
    { label: t('Included'), n: included, level: 0, strong: true, onClick: () => onSources('included'), note: t('The report reads these') },
    ...(roles ? [
      { label: t('Given as included'), n: roles.counts.included, level: 1, note: t('Met the whole criterion, or you included them') },
      { label: t('Given as closest work'), n: roles.counts.closest, level: 1, note: t('Full text read, did not meet the whole criterion; nearest evidence, not a match') },
      { label: t('Given from the abstract only'), n: roles.counts.abstract, level: 1 },
      { label: t(statementExcludedReasons.passage_budget), n: roles.left_out.passage_budget ?? 0, level: 1 },
      { label: t(statementExcludedReasons.closest_over_cap), n: roles.left_out.closest_over_cap ?? 0, level: 1 },
      { label: t(statementExcludedReasons.closest_no_part), n: roles.left_out.closest_no_part ?? 0, level: 1 },
    ] : []),
    ...(answer ? [{ label: t('Cited in the answer'), n: cited, level: 0, strong: true, onClick: onAnswer,
      note: cited ? [t('{n} from full text', { n: num(cited - citedAbstract) }), citedAbstract && t('{n} from the abstract only', { n: num(citedAbstract) }),
        citedOutside && citedOutside !== citedAbstract && t('{n} not included', { n: num(citedOutside) })].filter(Boolean).join(' · ') : undefined }] : []),
  ].filter(row => row.n > 0 || row.level === 0)

  const lead = [t('{found} works found, {n} included.', { found: num(funnel.unique), n: num(included) }),
    answer && cited > 0 && (citedAbstract
      ? t('The answer cites {n} sources, {abstract} of them from the abstract only.', { n: num(cited), abstract: num(citedAbstract) })
      : t('The answer cites {n} sources, all read in full text.', { n: num(cited) })),
    roles && roles.counts.closest > 0 && t(roles.counts.closest === 1 ? '{n} closest work was read as nearest evidence, not as a match.' : '{n} closest works were read as nearest evidence, not as matches.', { n: num(roles.counts.closest) })].filter(Boolean).join(' ')

  const found: Part[] = [
    { label: t('Passed to full text'), n: funnel.candidates, tone: 'next' },
    { label: t('Set aside'), n: b.survey + outOfScope + otherwise, tone: 'out' },
    { label: t('No abstract to read'), n: b.abstract_open, tone: 'open' },
    { label: t('Not screened'), n: notScreened, tone: 'idle' },
  ]
  const fullText: Part[] = [
    { label: t('Met the criterion'), n: met, tone: 'read' },
    { label: t('Did not meet it'), n: notMet, tone: 'out' },
    { label: t('Waiting for you'), n: forYou, tone: 'next' },
    { label: t('No PDF found'), n: noPdf, tone: 'open' },
    { label: t('Text on hand, not read'), n: notRead, tone: 'idle' },
    { label: t('Full text not tried'), n: notTried, tone: 'idle' },
  ]
  return { funnel, num, readFull, met, noPdf, notRead, notTried, rows, lead, found, fullText }
}

// Inside the search step's details: the summary sentence and the bar of what became of the works found.
export function SearchBasis(props: BasisProps) {
  const c = basisCounts(props)
  if (!c) return null
  return <div className="chat-basis">
    <p className="answer-basis-lead">{c.lead}</p>
    <Bar title={t('{n} works found', { n: c.num(c.funnel.unique) })} parts={c.found} num={c.num} />
  </div>
}

// The full-text step of the timeline: one quiet line of counts. Its details, closed by default, hold the full-text bar
// and the whole list from found down to cited.
export function FulltextLine(props: BasisProps) {
  const [open, setOpen] = useState(false)
  const c = basisCounts(props)
  if (!c) return null
  const { num } = c
  // Read, met and no-PDF counts; a count of zero is left out, and a search that passed nothing says so.
  const text = c.readFull || c.funnel.candidates
    ? [t(c.readFull === 1 ? '{n} full text read' : '{n} full texts read', { n: num(c.readFull) }), c.met > 0 && t('{n} met the criterion', { n: num(c.met) }),
      c.noPdf > 0 && t('{n} without a PDF', { n: num(c.noPdf) }), c.notRead > 0 && t('{n} on hand, not read', { n: num(c.notRead) }),
      c.notTried > 0 && t('{n} not tried', { n: num(c.notTried) })].filter(Boolean).join(' · ')
    : t('No full text read')
  return <section className="chat-turn is-line">
    <div className="chat-group">
      <div className="chat-head">
        <button type="button" className="chat-toggle" aria-expanded={open} aria-controls="answer-basis-rows" onClick={() => setOpen(!open)}>
          <span className="chat-line-icon" aria-hidden><BookOpen size={14} /></span>
          <span className="chat-line-text">{text}</span>
          <ChevronRight size={15} className="chat-line-chev" aria-hidden />
        </button>
      </div>
      {open && <div className="chat-basis" id="answer-basis-rows">
        <Bar title={t('{n} passed to full text', { n: num(c.funnel.candidates) })} parts={c.fullText} num={num} />
        <h3>{t(props.answer ? 'How this answer was built' : 'From search to sources')}</h3>
        <ul className="answer-basis-rows">
          {c.rows.map(row => {
            const body = <><span className="answer-basis-label">{row.label}</span><b className="tnum">{num(row.n)}</b>{row.note && <span className="answer-basis-note">{row.note}</span>}</>
            return <li key={row.label} className={`is-level-${row.level}${row.strong ? ' is-strong' : ''}`}>
              {row.onClick ? <button type="button" onClick={row.onClick}>{body}</button> : <div>{body}</div>}
            </li>
          })}
        </ul>
      </div>}
    </div>
  </section>
}
