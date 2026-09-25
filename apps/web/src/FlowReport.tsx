import { ChevronRight, Download, Workflow } from 'lucide-react'
import { prismaSUrl, type Answer, type Counts, type FlowBucket, type FlowCounts, type Overrides } from './api'
import { flowBoxLabels, flowBucketLabels } from './labels'
import { t, uiLocale } from './i18n'

// Where every work of an sw research stands (slice 20). Counts only: a work two agreeing runs included is never called
// confirmed, the override count is never a rate, and the boxes are not added up.

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)

// The five of SW11.12 in one line.
function fiveText(flow: FlowCounts) {
  const five = flow.five
  return t('{included} included (two agreeing runs {agreed}, you confirmed {confirmed}) · {queued} in your queue, not looked at · {waiting} waiting for a PDF · {notRead} full text not read ({reading} in reading, {tried} not tried) · {notMet} criterion not met', {
    included: count(five.included), agreed: count(five.included_by_agreement), confirmed: count(five.confirmed),
    queued: count(five.queued), waiting: count(five.waiting_for_pdf), notRead: count(five.not_read),
    reading: count(five.not_read_in_reading), tried: count(five.not_read_not_tried), notMet: count(five.not_met),
  })
}

const ORDER = Object.keys(flowBucketLabels) as FlowBucket[]

// The Sources tab's flow block, beside the export links: the five in one line, every bucket and box when opened, and
// the PRISMA-S search report.
export function FlowBlock({ researchId, counts }: { researchId: string; counts: Counts }) {
  const flow = counts.flow
  if (!flow) return null
  return <details className="search-summary flow-block">
    <summary><span><Workflow size={14} aria-hidden />{t('Flow')}<ChevronRight size={13} aria-hidden className="search-summary-chevron" /></span><small>{fiveText(flow)}</small></summary>
    <div className="flow-detail">
      <div>
        <p className="flow-head">{t('Where each of the {n} works stands', { n: count(flow.works) })}</p>
        <ul className="flow-list">{ORDER.filter(key => flow.buckets[key] > 0).map(key => <li key={key}>
          <span>{t(flowBucketLabels[key])}</span><strong>{count(flow.buckets[key])}</strong>
        </li>)}</ul>
        {flow.buckets.other > 0 && <p className="flow-note">{t('Other, by reason code: {list}', { list: Object.entries(flow.other_reasons).map(([code, n]) => `${code} ${n}`).join(' · ') })}</p>}
        {flow.buckets.abstract_not_read > 0 && <p className="flow-note">{t('An abstract not read is not an exclusion: the work was not read.')}</p>}
        {Object.keys(flow.queue_by_reason).length > 0 && <p className="flow-note">{t('Your queue by reason: {list}', { list: Object.entries(flow.queue_by_reason).map(([code, n]) => `${code} ${n}`).join(' · ') })}</p>}
      </div>
      {counts.flow_boxes && <div>
        <p className="flow-head">{t('Counts in the style of PRISMA 2020')}</p>
        <ul className="flow-list">{counts.flow_boxes.boxes.map(box => <li key={box.key}>
          <span>{t(flowBoxLabels[box.key] ?? box.key)}</span><strong>{box.count === null ? t('not counted') : count(box.count)}</strong>
        </li>)}</ul>
        <p className="flow-note">{t('Incomplete: code and model runs did the screening, and you looked only at your queue and the audit sample. The counts are not added up.')}</p>
      </div>}
      <span className="export-links flow-report" role="group" aria-label={t('Search report (PRISMA-S)')}>
        <span className="export-links-label"><Download size={15} aria-hidden />{t('Search report (PRISMA-S)')}</span>
        <span className="export-formats">
          <a href={prismaSUrl(researchId, 'md')} download title={t('The search reported against the 16 PRISMA-S items, as Markdown')}>.md</a>
          <a href={prismaSUrl(researchId, 'json')} download title={t('The search reported against the 16 PRISMA-S items, as JSON')}>.json</a>
        </span>
      </span>
    </div>
  </details>
}

// Under an sw answer: where the flow stood when its run started, and what was given to the model, on separate lines.
export function AnswerFlowNote({ answer }: { answer: Answer }) {
  if (answer.start_snapshot === undefined) return null  // a legacy view
  const snapshot = answer.start_snapshot
  const given = answer.inputs_given
  return <div className="answer-flow" role="group" aria-label={t('Flow at the start of this answer')}>
    {snapshot ? <>
      <p>{t('When the answer started: included {included} (two agreeing runs {agreed}, you confirmed {confirmed}); in your queue, not looked at {queued}; waiting for a PDF {waiting}; full text not read {notRead} ({reading} in reading, {tried} not tried); criterion not met {notMet}.', {
        included: count(snapshot.flow.five.included), agreed: count(snapshot.flow.five.included_by_agreement),
        confirmed: count(snapshot.flow.five.confirmed), queued: count(snapshot.flow.five.queued),
        waiting: count(snapshot.flow.five.waiting_for_pdf), notRead: count(snapshot.flow.five.not_read),
        reading: count(snapshot.flow.five.not_read_in_reading), tried: count(snapshot.flow.five.not_read_not_tried),
        notMet: count(snapshot.flow.five.not_met) })}</p>
      {snapshot.included_without_answer_text > 0 && <p>{t(snapshot.included_without_answer_text === 1 ? '{n} included work gave the answer no text: its only text is your file, not read yet.' : '{n} included works gave the answer no text: their only text is your file, not read yet.', { n: count(snapshot.included_without_answer_text) })}</p>}
      {snapshot.included_state_changed && <p className="is-attention">{t('The state of the included sources changed while the answer ran.')}</p>}
      {snapshot.flow.look_again_in_answer > 0 && <p className="is-attention">{t(snapshot.flow.look_again_in_answer === 1 ? '{n} work rests on a decision you made under the earlier criterion.' : '{n} works rest on a decision you made under the earlier criterion.', { n: count(snapshot.flow.look_again_in_answer) })}</p>}
    </> : <p>{t('The flow at the start of this answer was not recorded.')}</p>}
    {given && <p>{t('Given to the model: works {sources}, passages {passages}.', { sources: count(given.sources), passages: count(given.passages) })}</p>}
  </div>
}

// The queue tab's first line (decision 4): how many of the person's decisions changed what code or the runs decided.
export function OverridesLine({ overrides }: { overrides: Overrides | null | undefined }) {
  if (!overrides) return null
  const apart = [
    overrides.apart.not_sure > 0 && t('not sure {n}', { n: count(overrides.apart.not_sure) }),
    overrides.apart.pdf_wrong > 0 && t('wrong PDF {n}', { n: count(overrides.apart.pdf_wrong) }),
    overrides.apart.look_again > 0 && t('to look at again {n}', { n: count(overrides.apart.look_again) }),
  ].filter(Boolean)
  return <p className="overrides-line">
    {overrides.decisions === 0
      ? t('You have not decided yet; this line says nothing about how right code or the model is.')
      : t(overrides.decisions === 1 ? 'Of your {n} decision, you changed a decision of code or the model runs in {m} (code {code}, model runs {model}).' : 'Of your {n} decisions, you changed a decision of code or the model runs in {m} (code {code}, model runs {model}).', {
        n: count(overrides.decisions), m: count(overrides.changed), code: count(overrides.changed_by.code), model: count(overrides.changed_by.model_agreement) })}
    {apart.length > 0 && ` ${t('Counted apart: {list}.', { list: apart.join(' · ') })}`}
  </p>
}
