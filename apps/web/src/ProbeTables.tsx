import type { ArmCount, Probes, SignalCapture, SignalTable, SourceCounts } from './api'
import { ConnectionIcon } from './connectionIcons'
import { t, uiLocale } from './i18n'
import { armKindLabels, providerName, queryOriginLabels, signalLabels, signalReasonText } from './labels'

// What an sw run's search and screening phases report against the person's probe set (slice 19). Every number is a
// count over stored rows. A work two agreeing runs included is never called verified, and no sentence here says a
// signal or an arm helps or does not: the stopping rule and switching a signal off are open requirements.

const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })
const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

// Per round, per source: the works, what no other source's search found, and what was included and confirmed.
export function ArmReport({ counts, probes, modelTerms }: { counts: SourceCounts; probes: Probes | null | undefined; modelTerms: boolean }) {
  const arms = counts.arms
  if (!arms) return null
  const confirmedAnywhere = (probes?.verified ?? 0) > 0
  // The "only" universe is named on every line: a source row against the other sources' searches, the chain row
  // against every search (D93).
  const found = (arm: ArmCount, chain: boolean) => [
    arms.read ? t(chain ? '{n} included by two agreeing runs, {only} not found by any search' : '{n} included by two agreeing runs, {only} no other source’s search found', { n: count(arm.included), only: count(arm.included_only) }) : '',
    confirmedAnywhere ? t(chain ? '{n} you confirmed, {only} not found by any search' : '{n} you confirmed, {only} no other source’s search found', { n: count(arm.verified), only: count(arm.verified_only) }) : '',
  ].filter(Boolean)
  return <div className="chat-arms">
    {counts.rounds.map((round, r) => <div key={round.round}>
      <p className="chat-arm-head">{t('Round {n}', { n: round.round })}</p>
      <ul className="chat-arm-list">{round.sources.map((source, i) => {
        const arm = arms.rounds[r]?.sources[i]
        return <li key={source.provider_id}>
          <span className="chat-arm-source"><ConnectionIcon id={source.provider_id} />{providerName(source.provider_id)}</span>
          <span>{t('{works} works from {rows} records, {only} no other source’s search found', { works: count(source.works), rows: count(arm?.rows ?? 0), only: count(source.only) })}</span>
          {arm && found(arm, false).map(text => <span key={text}>{text}</span>)}
          {arm?.by_origin && <span className="chat-arm-origin">{t('By query: {list}', { list: arm.by_origin.map(o => t(arms.read ? '{origin} {works} works, {included} included' : '{origin} {works} works', { origin: t(queryOriginLabels[o.origin] ?? o.origin), works: count(o.works), included: count(o.included) })).join(' · ') })}</span>}
        </li>
      })}</ul>
    </div>)}
    {counts.chain && arms.chain && <div>
      <p className="chat-arm-head">{t('Citation chaining')}</p>
      <ul className="chat-arm-list"><li>
        <span className="chat-arm-source"><ConnectionIcon id="openalex" />{providerName('openalex')}</span>
        <span>{t('{works} works from {rows} records, {only} not found by any search', { works: count(counts.chain.works), rows: count(arms.chain.rows), only: count(counts.chain.only) })}</span>
        {found(arms.chain, true).map(text => <span key={text}>{text}</span>)}
      </li></ul>
    </div>}
    <p className="chat-arm-head">{t('By arm, in the order the run searched')}</p>
    <ul className="chat-arm-list">{arms.kinds.map(kind => <li key={kind.kind}>
      <span className="chat-arm-source">{t(armKindLabels[kind.kind])}</span>
      {kind.ran ? <>
        <span>{t('{works} works, {new} new', { works: count(kind.works), new: count(kind.new_works) })}</span>
        {arms.read && <span>{t('{n} included, {new} new', { n: count(kind.included), new: count(kind.new_included) })}</span>}
        {confirmedAnywhere && <span>{t('{n} you confirmed, {new} new', { n: count(kind.verified), new: count(kind.new_verified) })}</span>}
      </> : <span>{t('not run')}</span>}
    </li>)}</ul>
    {modelTerms && <p className="chat-arm-note">{t('Terms the model proposed on the card went into the keyword queries; their works are counted there.')}</p>}
    {!arms.read && <p className="chat-arm-note">{t('Full text not read yet: included counts come with the reading.')}</p>}
  </div>
}

// The works the person confirmed or brought that no search or chain request of this question revision found (SW13.7).
// A stored hit of any run counts as found; a run that kept only some hits makes the rest `unknown`.
export function NotFoundReport({ probes }: { probes: Probes }) {
  const { status, works } = probes.not_found
  if (status === 'no_search' || probes.verified + probes.brought === 0) return null
  if (status === 'not_counted') return <p className="chat-arm-note">{t('Whether a search found your works was not counted for this question revision.')}</p>
  if (!works.length) return <p className="chat-arm-note">{t('A search or the citation chain of this question revision found every work you confirmed or brought.')}</p>
  return <div className="chat-arms">
    <p className="chat-arm-head">{status === 'partial'
      ? plural(works.length, 'Your work the counted searches did not find', 'Your works the counted searches did not find')
      : plural(works.length, 'Your work no search found', 'Your works no search found')}</p>
    {status === 'partial' && <p className="chat-arm-note">{t('An earlier run’s searches were not counted, so whether they found these is unknown.')}</p>}
    <ul className="chat-list chat-probe-list">{works.map(work => <li key={work.work_id}>
      <span className="chat-list-text">{work.title}{work.doi && <small>{t('DOI {doi}', { doi: work.doi })}</small>}</span>
      <small>{work.reasons.map(reason => t(reason === 'verified' ? 'you confirmed it' : 'you brought it')).join(' · ')}</small>
    </li>)}</ul>
  </div>
}

function captureText(row: SignalCapture) {
  const tied = [row.tied_100 ? t('{n} tied at the 100 cut', { n: row.tied_100 }) : '', row.tied_200 ? t('{n} tied at the 200 cut', { n: row.tied_200 }) : ''].filter(Boolean)
  return t('{top100} in the top 100, {top200} in the top 200', { top100: row.top_100, top200: row.top_200 }) + (tied.length ? ` (${tied.join(', ')})` : '')
}

function Captures({ rows }: { rows: SignalCapture[] }) {
  return <ul className="chat-arm-list">{rows.map(row => <li key={row.signal}>
    <span className="chat-arm-source">{t(signalLabels[row.signal] ?? row.signal)}</span><span>{captureText(row)}</span>
  </li>)}</ul>
}

// The signal table of one keyword ranking step: descriptive counts with their denominator, never a verdict (SW7.6).
export function SignalReport({ table, probes }: { table: SignalTable; probes: Probes | null | undefined }) {
  const ran = table.signals.filter(s => s.ran)
  const off = table.signals.filter(s => !s.ran)
  const min = probes?.judge_min ?? 30
  const person = table.person
  const decisions = probes ? [
    plural(probes.verified, '{n} work you confirmed', '{n} works you confirmed'),
    t('{n} not meeting the criterion', { n: probes.negatives.criterion_not_met }),
    t('{n} excluded from the list, kind not recorded', { n: probes.negatives.not_recorded }),
    t('out of scope not recorded'),
    probes.look_again ? plural(probes.look_again, '{n} to look at again', '{n} to look at again') : '',
  ].filter(Boolean).join(' · ') : ''
  return <div className="chat-arms">
    {probes && <p className="chat-arm-note">{probes.read
      ? t('Your decisions in this question revision: {list}. {agreed} included by two agreeing runs, not confirmed by you.', { list: decisions, agreed: probes.included_by_agreement })
      : t('Your decisions in this question revision: {list}.', { list: decisions })}</p>}
    <p className="chat-arm-head">{t('Ranking signals')}</p>
    <ul className="chat-arm-list">
      {ran.map(s => <li key={s.signal}><span className="chat-arm-source">{t(signalLabels[s.signal] ?? s.signal)}</span>
        <span>{s.available === null ? t('ran') : plural(s.available, 'scored {n} record', 'scored {n} records')}</span></li>)}
      {off.map(s => <li key={s.signal}><span className="chat-arm-source">{t(signalLabels[s.signal] ?? s.signal)}</span>
        <span>{t('not run: {reason}', { reason: signalReasonText(s.reason) })}</span></li>)}
    </ul>
    <p className="chat-arm-head">{plural(person.denominator, 'Your confirmed works in this ranking: {n}', 'Your confirmed works in this ranking: {n}')}</p>
    <p className="chat-arm-note">{person.status === 'too_few'
      ? t('Too few to judge a signal by (fewer than {min}).', { min })
      : t('Counts only; a comparison needs an outside reference set.')}</p>
    {person.denominator > 0 && <Captures rows={person.rows} />}
    {table.agreement.denominator > 0 && <>
      <p className="chat-arm-head">{plural(table.agreement.denominator, 'Included by two agreeing runs, in this ranking: {n}', 'Included by two agreeing runs, in this ranking: {n}')}</p>
      <p className="chat-arm-note">{t('These were read because they were near the top of this order; their places are not a signal’s success.')}</p>
      <Captures rows={table.agreement.rows} />
    </>}
    {table.embedding && <p className="chat-arm-note">{t('The embedding moved up {n} records. Decided after the ranking: {included} included by two agreeing runs, {verified} you confirmed; {before} decided before it; {unknown} with no readable order. A moved-up record could be decided because it was read.', {
      n: table.embedding.moved_up, included: table.embedding.moved_up_then_included, verified: table.embedding.moved_up_then_verified,
      before: table.embedding.moved_up_already_decided, unknown: table.embedding.moved_up_time_unknown })}</p>}
  </div>
}
