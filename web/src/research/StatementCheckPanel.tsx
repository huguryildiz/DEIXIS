import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleCheck, Download, LoaderCircle, Play, RotateCw, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError, statementApi, type CitationEvidence, type CitationPart, type StatementCheckBrief, type StatementCheckItem, type StatementCheckView, type StatementCounters, type StatementPreview, type StatementSupportClass } from '../lib/api'
import { Notice } from '../components/Notice'
import { ModelName } from '../components/ModelName'
import { useModelText } from '../lib/modelText'
import {
  citationAssessmentLabels, money, pauseDetailText, pauseReasonText, runStatusLabels, statementErrorText, statementExcludedReasons,
  statementClassLabels, statementRefusals, statementStaleReasons,
} from '../lib/labels'
import { t, uiLocale } from '../lib/i18n'
import '../citecheck/CitationCheck.css'
import './statement.css'

// Reverse citation search R3 (plan `notes/plans/reverse-citation-search-plan.md`, D100, D103): the statement check of a
// statement research, in its thread instead of an answer. It shows the latest revision (`latest_check_id`), or an
// earlier one the person picks, with its currency read now; each work's result, reading depth and the backend's located
// quotes. Every count, title and result here comes from the stored view; nothing is computed from model prose.

const num = (n: number) => n.toLocaleString(uiLocale())
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
// The classes the backend presents completed works in (R4b, D108); `support_not_shown` exists from rule 2 on.
const CLASSES: StatementSupportClass[] = ['found_whole', 'found_partial', 'support_not_shown', 'not_found_in_given']

export type StatementQuote = { passageId: string; anchor: string }

export function StatementCheckPanel({ researchId, scopeRevision, eventCursor, runActive, discoveryDone, onOpenQuote, onOpenSource, onChanged }: {
  researchId: string; scopeRevision: number; eventCursor: number | string | null; runActive: boolean; discoveryDone: boolean
  onOpenQuote: (quote: StatementQuote) => void; onOpenSource: (sourceVersionId: string) => void; onChanged: () => void
}) {
  const [checks, setChecks] = useState<{ latest: string | null; list: StatementCheckBrief[] } | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [view, setView] = useState<StatementCheckView | null>(null)
  const [preview, setPreview] = useState<StatementPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const shownId = picked ?? checks?.latest ?? null
  // Reads overlap (events, the poll, a revision chosen): each read takes a number, and its answer is kept only when no
  // later read has been kept already and the revision chosen is still the one it asked for. A slow, older answer (a
  // revision still `current`) can then never overwrite a newer one (`stale`), nor show a revision the person left.
  const generation = useRef(0)
  const kept = useRef(0)
  const target = useRef<string | null>(null)
  const choose = (id: string | null) => { target.current = id; setPicked(id) }

  const load = useCallback(async () => {
    const mine = ++generation.current
    const asked = target.current
    const current = () => mine > kept.current && asked === target.current
    try {
      const list = await statementApi.list(researchId)
      const id = asked ?? list.latest_check_id
      const [next, priced] = id ? await Promise.all([statementApi.get(id), statementApi.preview(id).catch(() => null)]) : [null, null]
      if (!current()) return
      kept.current = mine
      setChecks({ latest: list.latest_check_id, list: list.checks })
      setView(next); setPreview(priced)
    } catch (e) { if (current()) setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId])
  useEffect(() => { void load() }, [load, eventCursor, picked])
  // While the shown revision's run works (or waits for attached files), the stored view is read every second.
  const runStatus = view?.run?.status
  const polling = (runStatus && ACTIVE.has(runStatus)) || Boolean(preview?.waiting)
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => { void load() }, 1000)
    return () => clearInterval(timer)
  }, [polling, load])

  // A new revision of the same sentence: a new request id, on the question revision this page shows, on the
  // literature model in Settings now (stored with the revision before it is priced).
  async function checkAgain() {
    setBusy(true); setError(null)
    try {
      await api.startStatementCheck(researchId, crypto.randomUUID(), scopeRevision)
      choose(null)
      onChanged()
      await load()
    } catch (e) {
      setError(e instanceof ApiError && e.code && statementRefusals[e.code] ? t(statementRefusals[e.code]) : e instanceof Error ? e.message : String(e))
      if (e instanceof ApiError && e.code === 'revision_mismatch') onChanged()
    } finally { setBusy(false) }
  }
  // A paused check goes on with the same revision and its frozen model (the run's resume path); no new revision.
  async function resume(runId: string) {
    setBusy(true); setError(null)
    try { await api.controlRun(runId, 'resume'); onChanged(); await load() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  const waitReason = runActive ? t('Wait until the current run ends.') : null
  const again = (label: string) => <span className="sc-again">
    <Button variant="outline" size="sm" disabled={busy || runActive} aria-disabled={busy || runActive || undefined}
      aria-describedby={waitReason ? 'sc-again-reason' : undefined} onClick={() => { void checkAgain() }}>
      {busy ? <LoaderCircle className="cc-spin" aria-hidden /> : <RotateCw aria-hidden />}{t(label)}</Button>
    {waitReason && <span id="sc-again-reason" className="cc-fine">{waitReason}</span>}
  </span>

  return <section className="sc-panel" aria-labelledby="sc-heading">
    <div className="sc-head">
      <div>
        <h2 id="sc-heading">{t('Statement check')}</h2>
        {view && <p className="sc-sub">{[t('Revision {n}', { n: view.revision }), new Date(view.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }),
          view.currency === 'current' ? t('Current') : t('Out of date')].join(' · ')}</p>}
      </div>
      {view && <span className="export-links" role="group" aria-label={t('Export the statement check')}>
        <span className="export-links-label"><Download size={15} aria-hidden />{t('Export')}</span>
        <span className="export-formats">
          <a href={statementApi.exportUrl(view.id, 'csv')} download>CSV</a>
          <a href={statementApi.exportUrl(view.id, 'md')} download>Markdown</a>
        </span>
      </span>}
    </div>
    {/* The sentence this revision checked, as stored with it: an older revision keeps its own sentence. */}
    {view && <p className="sc-sentence"><span className="sc-sentence-h">{t('Checked sentence')}</span> <q>{view.sentence}</q></p>}
    {error && <Notice tone="error">{error}</Notice>}
    {checks === null ? <p className="cc-muted" role="status"><span className="shimmer-text">{t('Loading…')}</span></p>
      : !view ? <div className="sc-box">
        <p className="cc-step-p">{discoveryDone ? t('No statement check has run yet. It reads each work the search reached against the statement.')
          : t('The check starts by itself when the search and reading end.')}</p>
        {discoveryDone && again('Check the statement')}
      </div>
      : <>
        {!view.is_latest && <Notice tone="attention">{t('This is revision {n}; the latest is revision {m}.', { n: view.revision, m: checks.list[0]?.revision ?? view.revision })}
          <span className="cc-inline-acts"><Button variant="outline" size="sm" onClick={() => choose(null)}>{t('Show the latest')}</Button></span></Notice>}
        {view.currency === 'stale' && <Notice tone="attention">
          {t('This check is out of date: {reason}. Its results are kept, but they are not current.', { reason: t(statementStaleReasons[view.stale_reason ?? ''] ?? view.stale_reason ?? '') })}
          {view.is_latest && <span className="cc-inline-acts">{again('Check again')}</span>}</Notice>}
        <RunState view={view} busy={busy} onResume={runId => { void resume(runId) }} />
        <Facts preview={preview} finished={view.status === 'finished'} />
        <Counters c={view.counters} />
        <p className="cc-fine sc-meaning">{t('“Supports” is a model’s reading of the passages it was given, checked by code against their exact words. It is not scientific validation, and a statement no work supports here is not shown to be unsupported in the literature.')}</p>
        <Groups view={view} onOpenQuote={onOpenQuote} onOpenSource={onOpenSource} />
        <div className="sc-foot">
          {view.is_latest && view.currency === 'current' && again('Check again')}
          {checks.list.length > 1 && <details className="cc-list sc-revisions">
            <summary>{t('All revisions ({n})', { n: checks.list.length })}</summary>
            <ol>{checks.list.map(check => <li key={check.id}>
              <button type="button" className="cc-link" aria-current={check.id === shownId || undefined} onClick={() => choose(check.is_latest ? null : check.id)}>
                {t('Revision {n}', { n: check.revision })}</button>
              <span className="cc-fine">{[new Date(check.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }),
                check.currency === 'current' ? t('Current') : t('Out of date: {reason}', { reason: t(statementStaleReasons[check.stale_reason ?? ''] ?? check.stale_reason ?? '') }),
                check.is_latest ? t('latest') : null].filter(Boolean).join(' · ')}</span>
            </li>)}</ol>
          </details>}
        </div>
      </>}
  </section>
}

function RunState({ view, busy, onResume }: { view: StatementCheckView; busy: boolean; onResume: (runId: string) => void }) {
  const run = view.run
  const c = view.counters
  const waiting = c.by_status.planned
  if (!run) return null
  if (view.attachment_snapshot?.status === 'waiting' && !ACTIVE.has(run.status)) {
    // Paused before any work is listed: an attached file was still being read (`attachments_extracting`).
    return <div className="sc-box" role="status">
      <p className="cc-step-h"><TriangleAlert size={16} aria-hidden className="cc-warn-icon" />{t('Waiting for the attached files to be read')}</p>
      <p className="cc-step-p">{t('The list of works is frozen once every attached file is read, so nothing was checked yet. When the files are read, continue the check; if one is still being read, it waits again.')}</p>
      {run.status === 'paused' && <div className="cc-acts"><Button size="sm" disabled={busy} onClick={() => onResume(run.id)}><Play aria-hidden />{t('Continue the check')}</Button></div>}
    </div>
  }
  if (ACTIVE.has(run.status)) {
    const ended = c.by_status.done + c.by_status.could_not_check
    const total = ended + waiting
    return <div className="sc-box cc-running" role="status">
      <p className="cc-step-h"><LoaderCircle size={16} className="cc-spin" aria-hidden />{view.attachment_snapshot?.status === 'waiting' ? t('Waiting for the attached files to be read') : t('Checking the works')}</p>
      {total > 0 && <div className="cc-progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={ended} aria-label={t('Works checked')}><i style={{ width: `${Math.round((ended / total) * 100)}%` }} /></div>}
      <p className="cc-fine">{t('{ended} of {total} works ended · {sent} sent to the model so far.', { ended: num(ended), total: num(total), sent: num(c.sent_to_model) })}</p>
    </div>
  }
  if ((run.status === 'paused' || run.status === 'failed') && waiting > 0) {
    return <div className="sc-box">
      <p className="cc-step-h"><TriangleAlert size={16} aria-hidden className="cc-warn-icon" />{t(run.status === 'failed' ? 'The check stopped with an error' : 'The check is paused')}</p>
      <p className="cc-step-p">{[pauseReasonText(run.pause_reason) || t(runStatusLabels[run.status]), ...pauseDetailText({ ...run, error: null })].filter(Boolean).join(' ')}</p>
      <p className="cc-step-p">{t('{n} works are waiting. Works already checked are not sent again.', { n: num(waiting) })}</p>
      {run.status === 'paused' && <div className="cc-acts"><Button size="sm" disabled={busy} onClick={() => onResume(run.id)}><Play aria-hidden />{t('Continue the check')}</Button></div>}
    </div>
  }
  if (view.status === 'finished') return <p className="sc-done"><CircleCheck size={16} aria-hidden className="cc-ok-icon" />{t('Check finished: {done} works completed, {cnc} could not be checked.', { done: num(c.completed), cnc: num(c.by_status.could_not_check) })}</p>
  return null
}

// What the revision sends, on the model stored with it at the request; the cost is unknown (never zero) while
// attached files are still being read.
function Facts({ preview, finished }: { preview: StatementPreview | null; finished: boolean }) {
  const modelText = useModelText()
  if (!preview) return null
  const cost = preview.cost
  const costText = preview.waiting || cost.usd === 'unknown'
    ? <span>{t('Unknown')} <span className="cc-fine">{t(preview.waiting ? '(the attached files are still being read)' : cost.reason === 'no_model' ? '(no model is chosen)' : '(DEIXIS has no price for this model)')}</span></span>
    : Array.isArray(cost.usd) ? <span>{t('at least {low}, at most {high}', { low: money(cost.usd[0]), high: money(cost.usd[1]) })} <span className="cc-fine">{t('(estimate; the provider’s bill is what counts)')}</span></span>
    : cost.applies === false ? <span>{t(cost.kind === 'local' ? 'No cost per call: the model runs on this computer' : 'No cost per call: the model runs on a subscription')}</span>
    : <span>{t('Unknown')}</span>
  return <ul className="cc-facts sc-facts">
    <li><span>{t('Model')}</span><ModelName connection={preview.model.connection} text={modelText(preview.model.model, preview.model.reasoning_effort ?? null)} /></li>
    <li><span>{t('Cost')}</span>{costText}</li>
    <li><span>{t(finished ? 'Works in this check' : 'Works to check')}</span>{preview.waiting ? t('Not frozen yet') : t('{n} (cap {cap})', { n: num(preview.listed - preview.no_text), cap: num(preview.work_cap) })}</li>
    <li><span>{t('Passages per work')}</span>{t('up to {k}', { k: preview.passages_per_item })}</li>
  </ul>
}

// The statement-check box: one revision's own counts, apart from the search counts above (found, screened, read).
function Counters({ c }: { c: StatementCounters }) {
  const item = (label: string, value: number) => <li><b className="tnum">{num(value)}</b><span>{t(label)}</span></li>
  // Every result count is the backend's class count (`counters.classes`), never the stored results recounted here.
  const classes = c.support_rule_version >= 2 ? CLASSES : CLASSES.filter(name => name !== 'support_not_shown')
  const depth = (name: StatementSupportClass) => {
    const by = c.classes_by_depth[name]
    return t('abstract only {a} · selected passages {s} · full text {f}', { a: num(by.abstract), s: num(by.selected_passages), f: num(by.full_text) })
  }
  return <>
    <div className="cc-counters sc-counters">
      <section aria-label={t('Works')}>
        <h3>{t('Works')}</h3>
        <ul>
          {item('candidates', c.candidates)}
          {item('listed', c.listed)}
          {item('beyond the cap', c.out_of_cap)}
          {item('left out with a reason', c.excluded_reason)}
          {item('you excluded', c.person_excluded)}
          {item('no text', c.by_status.no_text)}
        </ul>
      </section>
      <section aria-label={t('Check')}>
        <h3>{t('Check')}</h3>
        <ul>
          {item('sent to the model', c.sent_to_model)}
          {item('completed', c.completed)}
          {item('support the whole statement', c.classes.found_whole)}
          {item('support part of it', c.classes.found_partial)}
          {c.support_rule_version >= 2 && item('support not shown clearly enough', c.classes.support_not_shown)}
          {item('not found in given passages', c.classes.not_found_in_given)}
          {item('could not be checked', c.by_status.could_not_check)}
          {item('waiting', c.by_status.planned)}
        </ul>
      </section>
    </div>
    <details className="cc-list sc-depths">
      <summary>{t('Results by reading depth')}</summary>
      <ul>
        {classes.map(name => <li key={name}><span>{t(statementClassLabels[name])}</span> <span className="cc-fine">{depth(name)}</span></li>)}
        <li><span>{t('Works with a located quote')}</span> <span className="cc-fine">{t('from the abstract {a} · from PDF pages {p}', { a: num(c.works_with_located_quotes_from.abstract), p: num(c.works_with_located_quotes_from.pages) })}</span></li>
      </ul>
    </details>
  </>
}

// What a work was given, written the same way for every result: abstract only, all passages of a complete
// extraction, or the selected passages with how many were not given.
function depthText(item: StatementCheckItem): string | null {
  if (!item.depth) return null
  if (item.depth === 'abstract') return t('Abstract only')
  const given = item.passages_given ?? 0, notGiven = item.passages_not_given ?? 0
  if (item.depth === 'full_text') return t('Full text · all {n} passages given', { n: num(given) })
  if (!notGiven && item.extraction_complete === false) return t('All {n} extracted passages; the extraction is incomplete', { n: num(given) })
  return t('{k} selected passages given; {m} not given', { k: num(given), m: num(notGiven) })
}

const versionLabel: Record<string, string> = { upload: 'your upload', preprint: 'preprint', publisher: 'publisher version' }
const quoteOrigin = (evidence: CitationEvidence) => t(evidence.passage_kind === 'abstract' ? 'Quote from the abstract' : 'Quote from the PDF text')

// A completed work goes to the group of its backend class (`support_class`); the screen never derives it from parts.
type GroupKey = StatementSupportClass | 'could_not_check' | 'planned' | 'not_checked' | 'person_excluded'
const groupOf = (item: StatementCheckItem): GroupKey => item.eligibility === 'person_excluded' ? 'person_excluded'
  : item.eligibility !== 'listed' || item.status === 'no_text' ? 'not_checked'
  : item.status === 'done' && item.support_class ? item.support_class : item.status === 'could_not_check' ? 'could_not_check' : 'planned'
const GROUPS: { key: GroupKey; title: string }[] = [
  { key: 'found_whole', title: 'Supports the whole statement' },
  { key: 'found_partial', title: 'Supports part of the statement' },
  { key: 'support_not_shown', title: 'Support not shown clearly enough' },
  { key: 'not_found_in_given', title: 'Not found in the given passages' },
  { key: 'could_not_check', title: 'Could not be checked' },
  { key: 'planned', title: 'Waiting to be checked' },
  { key: 'not_checked', title: 'Not checked' },
  { key: 'person_excluded', title: 'You excluded' },
]

function Groups({ view, onOpenQuote, onOpenSource }: { view: StatementCheckView; onOpenQuote: (quote: StatementQuote) => void; onOpenSource: (svid: string) => void }) {
  const grouped = new Map<GroupKey, StatementCheckItem[]>()
  for (const item of view.items) grouped.set(groupOf(item), [...(grouped.get(groupOf(item)) ?? []), item])
  if (!view.items.length) return <p className="cc-muted">{view.attachment_snapshot?.status === 'waiting' ? t('The list of works is frozen once the attached files are read.') : t('No work was listed for this check.')}</p>
  return <div className="sc-groups">{GROUPS.filter(group => grouped.get(group.key)?.length).map(group => {
    const rows = grouped.get(group.key)!
    return <section key={group.key} className="sc-group" data-group={group.key} aria-labelledby={`sc-g-${group.key}`}>
      <h3 id={`sc-g-${group.key}`}>{t(group.title)} <span className="sc-count">{num(rows.length)}</span></h3>
      {group.key === 'support_not_shown' && <p className="sc-note">{t('The model found only partial overlap in the passages it was given and marked no part of the statement as stated, so these works are not counted as support.')}</p>}
      {group.key === 'not_found_in_given' && <p className="sc-note">{t('The model did not find this statement in the passages it was given. This does not mean the work contradicts it.')}</p>}
      <ul>{rows.map(item => <Row key={item.id} item={item} onOpenQuote={onOpenQuote} onOpenSource={onOpenSource} />)}</ul>
    </section>
  })}</div>
}

function Row({ item, onOpenQuote, onOpenSource }: { item: StatementCheckItem; onOpenQuote: (quote: StatementQuote) => void; onOpenSource: (svid: string) => void }) {
  const read = depthText(item)
  const meta = [item.year, item.text_version ? t(versionLabel[item.text_version] ?? item.text_version) : null, item.doi].filter(Boolean).join(' · ')
  const cls = item.support_class
  const supports = cls === 'found_whole' || cls === 'found_partial' || cls === 'support_not_shown'
  const notFound = cls === 'not_found_in_given'
  const reason = item.eligibility === 'out_of_cap' ? t('Beyond the cap of works sent to the model')
    : item.eligibility === 'excluded_reason' ? t(statementExcludedReasons[item.excluded_reason ?? ''] ?? (item.excluded_reason ?? '').replaceAll('_', ' '))
    : item.status === 'no_text' ? t('No text to read, so no model was asked')
    : item.status === 'could_not_check' && item.error ? t(statementErrorText[item.error.code] ?? 'The check could not be completed.') : null
  return <li className="sc-row" data-item={item.ordinal} data-status={item.status ?? item.eligibility} data-result={item.result ?? undefined}>
    <div className="sc-work">
      <button type="button" className="cc-title" onClick={() => onOpenSource(item.source_version_id)}>{item.title ?? t('Untitled record')}</button>
      {meta && <span className="cc-authors">{meta}</span>}
      {item.entry === 'person_included' && <span className="sc-entry">{t('You included it')}</span>}
    </div>
    <div className="sc-result">
      {cls && <span className="cc-pill" data-result={cls}>{t(statementClassLabels[cls])}</span>}
      {/* Where the class comes from, in neutral words: the stored result (kept as it was in the data) is the partial
          overlap rule 2 no longer counts as support, so it is never named with a support label here. */}
      {cls === 'support_not_shown' && item.result && <span className="sc-model">{t('Stored result before the support rule: partial overlap')}</span>}
      {read && <span className="sc-read">{read}</span>}
      {reason && <span className="cc-reason">{reason}</span>}
      {supports && <span className="sc-model">{t('The model’s assessment; read the passage.')}</span>}
      {notFound && <span className="sc-model">{t('The model’s assessment of the passages it was given.')}</span>}
      {item.parts && item.result && <Parts parts={item.parts} onOpenQuote={onOpenQuote} />}
    </div>
  </li>
}

// The model's parts, each with its text and labelled as the model's assessment (a one-part reading too), with only the
// quotes the backend located; a quote the backend could not locate is never shown as one.
function Parts({ parts, onOpenQuote }: { parts: CitationPart[]; onOpenQuote: (quote: StatementQuote) => void }) {
  return <ul className="cc-parts">{parts.map((part, i) => <li key={i} data-assessment={part.assessment}>
    <span className="cc-part-h"><span className="cc-part-a">{t('Model: {assessment}', { assessment: t(citationAssessmentLabels[part.assessment]) })}</span> {part.text}</span>
    {part.evidence.filter(e => e.located && e.anchor_text).map((e, j) => <span key={j} className="cc-quote-wrap">
      <button type="button" className="cc-quote" onClick={() => onOpenQuote({ passageId: e.passage_id, anchor: e.anchor_text! })}>“{e.anchor_text}”</button>
      <span className="cc-origin">{quoteOrigin(e)}</span>
    </span>)}
  </li>)}</ul>
}
