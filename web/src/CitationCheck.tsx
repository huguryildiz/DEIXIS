import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { CircleCheck, CircleDashed, CircleSlash, Download, FileCheck2, LoaderCircle, Paperclip, Play, TriangleAlert } from 'lucide-react'
import { ApiError, citationApi, type CitationCheckView, type CitationCounters, type CitationDraftSummary, type CitationEntry, type CitationEvidence, type CitationMarker, type CitationModel, type CitationPart, type CitationPair, type CitationPreview, type CitationPreviewPair, type CitationRecord } from './api'
import { Notice } from './Notice'
import { ModelName } from './ModelName'
import { useModelText } from './modelText'
import { PassageSheet } from './PassageSheet'
import {
  citationAssessmentLabels, citationFlagLabels, citationRefusals, citationResolutionReasons, citationResultLabels, citationStatusLabels,
  citationTextNotes, citationTextOrigins, money, pauseDetailText, pauseReasonText, runStatusLabels,
} from './labels'
import { t, uiLocale } from './i18n'
import './CitationCheck.css'

// Verify Citations (D86, D96, D99, V4): a Library tool with its own screen. A person gives a draft and its
// bibliography; code reads the markers and looks the entries up, fetches each cited work's text and freezes which
// passages each citation is given; a model then reads each (citation, work) pair and code decides the result from the
// backend's located quotes. Every count, title and result on this screen comes from the stored view.

const num = (n: number) => n.toLocaleString(uiLocale())
const errorText = (e: unknown) => e instanceof ApiError && e.code && citationRefusals[e.code] ? t(citationRefusals[e.code]) : e instanceof Error ? e.message : String(e)
const authorsLine = (source: CitationRecord) => {
  const names = source.authors ?? []
  const head = names.length > 3 ? `${names.slice(0, 3).join(', ')} ${t('et al.')}` : names.join(', ')
  return [head, source.year ?? ''].filter(Boolean).join(' · ')
}

export function CitationCheckPage({ id, dark, onOpen, onLibrary, onSettings }: {
  id: string | null; dark: boolean; onOpen: (id: string | null) => void; onLibrary: () => void; onSettings: () => void
}) {
  return <section className="cc-page">
    <p className="cc-crumb"><button type="button" onClick={onLibrary}>{t('Library')}</button> / {id
      ? <button type="button" onClick={() => onOpen(null)}>{t('Verify citations')}</button> : <span>{t('Verify citations')}</span>}</p>
    {id ? <DraftView key={id} id={id} dark={dark} onSettings={onSettings} /> : <StartView onOpen={draft => onOpen(draft)} />}
  </section>
}

// ------------------------------------------------------------------------------------------------- start

function StartView({ onOpen }: { onOpen: (id: string) => void }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [bib, setBib] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState<CitationDraftSummary[] | null>(null)
  const [listError, setListError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const bibInput = useRef<HTMLInputElement>(null)
  useEffect(() => { citationApi.list().then(setDrafts, (e: Error) => setListError(e.message)) }, [])
  const ready = Boolean(file || text.trim())
  async function submit() {
    setBusy(true); setError('')
    try { onOpen((await citationApi.create(file ? { file } : { text }, bib)).id) } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }
  return <>
    <h1 tabIndex={-1}>{t('Verify citations')}</h1>
    <p className="cc-sub">{t('Give a draft and its bibliography. DEIXIS finds each citation, opens the cited work and looks for what the citing sentence says in passages of that work. It does not rewrite the draft or judge it.')}</p>
    <div className="cc-box cc-start">
      <label className="cc-field">{t('Paste the draft')}
        <textarea className="field" rows={8} value={text} disabled={Boolean(file)} onChange={event => setText(event.target.value)}
          placeholder={t('Paste text with citations such as \\cite{key}, [3] or (Zeng et al., 2022).')} />
      </label>
      <div className="cc-files">
        <div className="cc-file">
          <span className="cc-file-h">{t('Or upload the draft')}</span>
          <span className="cc-file-row">
            <button type="button" className="ghost" onClick={() => fileInput.current?.click()}><Paperclip size={16} aria-hidden />{t('Choose draft file')}</button>
            <span className="cc-file-name">{file ? file.name : t('.md, .tex, .docx or .txt')}</span>
            {file && <button type="button" className="cc-link" onClick={() => setFile(null)}>{t('Remove')}</button>}
          </span>
          <input ref={fileInput} type="file" hidden accept=".md,.markdown,.tex,.docx,.txt" aria-label={t('Draft file')}
            onChange={event => { setFile(event.target.files?.[0] ?? null); event.target.value = '' }} />
        </div>
        <div className="cc-file">
          <span className="cc-file-h">{t('Bibliography (optional)')}</span>
          <span className="cc-file-row">
            <button type="button" className="ghost" onClick={() => bibInput.current?.click()}><Paperclip size={16} aria-hidden />{t('Choose bibliography file')}</button>
            <span className="cc-file-name">{bib ? bib.name : t('BibTeX or RIS. Without it, the draft’s own reference list is read.')}</span>
            {bib && <button type="button" className="cc-link" onClick={() => setBib(null)}>{t('Remove')}</button>}
          </span>
          <input ref={bibInput} type="file" hidden accept=".bib,.ris,.txt" aria-label={t('Bibliography file')}
            onChange={event => { setBib(event.target.files?.[0] ?? null); event.target.value = '' }} />
        </div>
      </div>
      <p className="cc-fine">{t('A .docx is read for its paragraph text only; footnotes and field codes are left out.')}</p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="cc-acts">
        <button type="button" className="btn-teal" disabled={!ready || busy} aria-busy={busy} onClick={() => void submit()}>
          {busy ? <LoaderCircle size={16} className="cc-spin" aria-hidden /> : <FileCheck2 size={16} aria-hidden />}{t('Read the citations')}</button>
        <span className="cc-fine">{t('Code reads the markers. No model is used until you start the check.')}</span>
      </div>
    </div>
    <h2 className="cc-h2">{t('Earlier checks')}</h2>
    {listError ? <Notice tone="error">{t('Could not read the earlier checks: {message}', { message: listError })}</Notice>
      : drafts === null ? <p className="cc-muted" role="status"><span className="shimmer-text">{t('Loading…')}</span></p>
      : !drafts.length ? <p className="cc-muted">{t('No check yet.')}</p>
      : <ul className="cc-drafts">{drafts.map(d => <li key={d.id}>
        <button type="button" onClick={() => onOpen(d.id)}>
          <b>{d.original_filename ?? t('Pasted text')}</b>
          <span>{[new Date(d.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }),
            t('{n} citations', { n: num(d.occurrences) }), t('{n} pairs', { n: num(d.pairs) }), t('{n} completed', { n: num(d.pairs_done) }), t('{n} could not be checked', { n: num(d.pairs_could_not_check) }),
            d.check_status ? t(runStatusLabels[d.check_status]) : t('Not checked')].join(' · ')}</span>
        </button>
      </li>)}</ul>}
  </>
}

// ------------------------------------------------------------------------------------------------- one draft

type Busy = 'resolve' | 'acquire' | 'freeze' | 'preview' | 'check' | `upload:${string}` | null
type Sheet = { passageId: string; highlight: string | null }
// Source details opened from a located quote: the words marked are the ones the backend located for this check.
const sheetLabels = () => ({ heading: t('Located quote'), mark: t('Words the backend located for this citation'),
  marked: t('Marked: the words the backend located in this passage for the citation check.'),
  unmarked: t('The located words could not be marked in this passage. Nothing else is marked.') })

function DraftView({ id, dark, onSettings }: { id: string; dark: boolean; onSettings: () => void }) {
  const [view, setView] = useState<CitationCheckView | null>(null)
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState<Busy>(null)
  const [error, setError] = useState<{ text: string; code: string | null } | null>(null)
  const [preview, setPreview] = useState<CitationPreview | null>(null)
  const [sheet, setSheet] = useState<Sheet | null>(null)
  useEffect(() => { citationApi.get(id).then(setView, (e: Error) => setLoadError(e.message)) }, [id])

  const stage = view ? stageOf(view) : null
  const revision = view?.plan.revision ?? null
  const loadPreview = useCallback(async () => {
    setBusy('preview')
    try { setPreview(await citationApi.preview(id)) } catch (e) { setError({ text: errorText(e), code: e instanceof ApiError ? e.code : null }) } finally { setBusy(null) }
  }, [id])
  // The preview is read once the plan is frozen and pairs wait; reading it records which revision and model were shown.
  useEffect(() => {
    if (stage !== 'preview') return
    let live = true
    citationApi.preview(id).then(value => { if (live) setPreview(value) },
      e => { if (live) setError({ text: errorText(e), code: e instanceof ApiError ? e.code : null }) })
    return () => { live = false }
  }, [stage, revision, id])
  // While a check runs (started here, or found running when the page opened), the stored view is read every second
  // so the counts and rows fill in as each pair ends; polling stops once the stored run has ended.
  const runStatus = view?.check_run?.status
  const polling = busy === 'check' || runStatus === 'queued' || runStatus === 'running' || runStatus === 'pause_requested'
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => { citationApi.get(id).then(setView, () => {}) }, 1000)
    return () => clearInterval(timer)
  }, [polling, id])
  // While a cited work's PDF is being read again in the background, the view is read every five seconds, so the
  // freeze is offered once the re-extraction ends.
  const reextracting = (view?.reextraction_waiting?.length ?? 0) > 0
  useEffect(() => {
    if (!reextracting) return
    const timer = setInterval(() => { citationApi.get(id).then(setView, () => {}) }, 5000)
    return () => clearInterval(timer)
  }, [reextracting, id])

  async function act(kind: Exclude<Busy, null>, call: () => Promise<CitationCheckView>) {
    setBusy(kind); setError(null)
    try { setView(await call()) } catch (e) {
      const code = e instanceof ApiError ? e.code : null
      setError({ text: errorText(e), code })
      // A preview the check refused is read again, so the person reads what will now be sent.
      if (code === 'plan_not_previewed' || code === 'model_not_previewed' || code === 'plan_revision_mismatch') {
        citationApi.get(id).then(setView, () => {}); citationApi.preview(id).then(setPreview, () => {})
      }
    } finally { setBusy(null) }
  }
  const start = (model: CitationModel, rev: number) => void act('check', () => citationApi.check(id, rev, model))
  // A plan whose text changed is frozen again only on the person's request; its earlier plan is kept (D96).
  const refreeze = () => void act('freeze', () => citationApi.freeze(id, true))

  if (loadError) return <Notice tone="error">{t('Could not read this check: {message}', { message: loadError })}</Notice>
  if (!view) return <p className="cc-muted" role="status"><span className="shimmer-text">{t('Loading…')}</span></p>
  const c = view.counters
  const running = polling
  const ended = (c.pairs_done ?? 0) + (c.pairs_could_not_check ?? 0)
  return <>
    <div className="cc-head">
      <div>
        <h1 tabIndex={-1}>{view.original_filename ?? t('Pasted text')}</h1>
        <p className="cc-sub">{[t('Given {date}', { date: new Date(view.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) }),
          view.bibliography.filename ? t('bibliography {name}', { name: view.bibliography.filename }) : view.bibliography.origin === 'none' ? t('no bibliography found') : t('the draft’s own reference list')].join(' · ')}</p>
      </div>
      <div className="cc-export" role="group" aria-label={t('Export')}>
        <a className="ghost" href={citationApi.exportUrl(id, 'csv')} download><Download size={16} aria-hidden />{t('Export CSV')}</a>
        <a className="ghost" href={citationApi.exportUrl(id, 'md')} download><Download size={16} aria-hidden />{t('Export Markdown')}</a>
      </div>
    </div>
    <Counters counters={c} />
    <div className="cc-box cc-step" aria-live="polite">
      {running ? <Running counters={c} />
        : <NextStep view={view} stage={stage!} busy={busy} preview={preview} onSettings={onSettings}
          onResolve={() => void act('resolve', () => citationApi.resolve(id))}
          onAcquire={() => void act('acquire', () => citationApi.acquire(id))}
          onFreeze={() => void act('freeze', () => citationApi.freeze(id))}
          onPreview={() => void loadPreview()} onRefreeze={refreeze}
          onStart={start} />}
      {error && <Notice tone={error.code === 'plan_stale' || error.code === 'no_model' ? 'attention' : 'error'}>{error.text}
        {error.code === 'plan_stale' && <span className="cc-inline-acts"><button type="button" className="ghost" disabled={busy !== null} onClick={refreeze}>{t('Freeze the plan again')}</button></span>}</Notice>}
    </div>
    <p className="cc-fine cc-meaning">{t('“Found” is a model’s reading of the passages it was given, checked by code against their exact words. It is not scientific validation. “Not found” covers only the given passages, not the whole work.')}</p>
    <h2 className="cc-h2">{t('Citations')}</h2>
    {view.markers.length ? <CitationTable view={view} onQuote={(evidence) => setSheet({ passageId: evidence.passage_id, highlight: evidence.anchor_text })}
      onWork={passageId => setSheet({ passageId, highlight: null })} />
      : <p className="cc-muted">{t('No citation marker was found in the draft.')}</p>}
    <h2 className="cc-h2">{t('Bibliography')}</h2>
    <Entries view={view} busy={busy} locked={running || ended > 0}
      onAttach={(entry, file) => void act(`upload:${entry.id}`, () => citationApi.attachPdf(id, entry.id, file))} />
    {sheet && <PassageSheet researchId={view.research_id} passageId={sheet.passageId} highlightText={sheet.highlight}
      expectHighlight={Boolean(sheet.highlight)} passageOnly citationLabels={sheet.highlight ? sheetLabels() : undefined} dark={dark} onClose={() => setSheet(null)} />}
  </>
}

type Stage = 'resolve' | 'acquire' | 'freeze' | 'preview' | 'paused' | 'done' | 'nothing'

function stageOf(view: CitationCheckView): Stage {
  const named = new Set(view.markers.flatMap(m => m.pairs.map(p => p.bib_entry_id)).filter(Boolean))
  const entries = view.entries.filter(e => named.has(e.id))
  const c = view.counters
  if (!c.pairs) return 'nothing'
  if (entries.some(e => e.resolution.status === 'pending' || e.resolution.status === 'lookup_failed')) return 'resolve'
  if (entries.some(e => e.resolution.status === 'resolved' && e.text.status === 'pending')) return 'acquire'
  if (!view.plan.revision) return 'freeze'
  if (view.check_run && (view.check_run.status === 'paused' || view.check_run.status === 'failed') && (c.pairs_to_send ?? 0) > 0) return 'paused'
  if ((c.pairs_to_send ?? 0) > 0) return 'preview'
  return 'done'
}

function Counters({ counters: c }: { counters: CitationCounters }) {
  const dash = (n: number | null) => n === null ? '–' : num(n)
  const item = (label: string, value: number | null, title?: string) => <li title={title}><b className="tnum">{dash(value)}</b><span>{t(label)}</span></li>
  const notStarted = t('Not started')
  return <div className="cc-counters">
    <section aria-label={t('In the draft')}>
      <h3>{t('In the draft')}</h3>
      <ul>
        {item('citations', c.occurrences)}
        {item('recognized', c.occurrences_recognized)}
        {item('ambiguous', c.occurrences_ambiguous)}
        {item('not read', c.occurrences_unrecognized)}
      </ul>
    </section>
    <section aria-label={t('Cited works')}>
      <h3>{t('Cited works')}</h3>
      <ul>
        {item('cited works', c.sources_unique)}
        {item('linked to a record', c.sources_resolved)}
        {item('full text', c.sources_with_text.full_text)}
        {item('abstract only', c.sources_with_text.abstract)}
        {item('metadata only', c.sources_with_text.metadata_only)}
      </ul>
    </section>
    <section aria-label={t('Pairs')}>
      <h3>{t('Pairs')}</h3>
      <ul>
        {item('pairs', c.pairs)}
        {item('in the plan', c.pairs_in_plan, c.pairs_in_plan === null ? t('The plan is not frozen yet') : undefined)}
        {item('beyond the cap', c.pairs_out_of_cap)}
        {item('sent to the model', c.pairs_sent_to_model, c.pairs_sent_to_model === null ? notStarted : undefined)}
        {item('completed', c.pairs_done, c.pairs_done === null ? notStarted : undefined)}
        {item('passage found', c.pairs_found, c.pairs_found === null ? notStarted : undefined)}
        {item('not found in given passages', c.pairs_not_found_in_given, c.pairs_not_found_in_given === null ? notStarted : undefined)}
        {item('could not be checked', c.pairs_could_not_check, c.pairs_could_not_check === null ? notStarted : undefined)}
      </ul>
    </section>
  </div>
}

// Progress over the plan's checkable pairs: those ended (completed or could not be checked) plus those still waiting, read
// from the same stored counts, so a resumed check never shows more ended than its total.
function Running({ counters: c }: { counters: CitationCounters }) {
  const ended = (c.pairs_done ?? 0) + (c.pairs_could_not_check ?? 0)
  const total = ended + (c.pairs_to_send ?? 0)
  const sent = c.pairs_sent_to_model ?? 0
  const share = total ? Math.min(100, Math.round((ended / total) * 100)) : 0
  return <div className="cc-running" role="status">
    <p className="cc-step-h"><LoaderCircle size={16} className="cc-spin" aria-hidden />{t('Checking the citations')}</p>
    <div className="cc-progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={ended} aria-label={t('Pairs ended')}><i style={{ width: `${share}%` }} /></div>
    <p className="cc-fine">{t('{ended} of {total} pairs ended · {sent} sent to the model so far. Each pair is read once; a stopped check goes on from the first pair without a result.', { ended: num(ended), total: num(total), sent: num(sent) })}</p>
  </div>
}

function NextStep({ view, stage, busy, preview, onSettings, onResolve, onAcquire, onFreeze, onPreview, onRefreeze, onStart }: {
  view: CitationCheckView; stage: Stage; busy: Busy; preview: CitationPreview | null; onSettings: () => void
  onResolve: () => void; onAcquire: () => void; onFreeze: () => void; onPreview: () => void; onRefreeze: () => void; onStart: (model: CitationModel, revision: number) => void
}) {
  const c = view.counters
  const action = (label: string, onClick: () => void, kind: Busy, icon: ReactNode = <Play size={16} aria-hidden />) =>
    <button type="button" className="btn-teal" disabled={busy !== null} aria-busy={busy === kind} onClick={onClick}>
      {busy === kind ? <LoaderCircle size={16} className="cc-spin" aria-hidden /> : icon}{t(label)}</button>
  const pendingLookups = view.entries.filter(e => e.resolution.status === 'pending' || e.resolution.status === 'lookup_failed').length
  const pendingText = view.entries.filter(e => e.resolution.status === 'resolved' && e.text.status === 'pending').length
  const acquisition = view.text_acquisition
  if (stage === 'nothing') return <p className="cc-step-h">{t('No citation could be paired with a bibliography entry, so there is nothing to check.')}</p>
  if (stage === 'resolve') return <>
    <p className="cc-step-h">{t('Step 1 of 4 · Look up the bibliography')}</p>
    <p className="cc-step-p">{t('{n} entries are not linked to a record yet. DEIXIS asks OpenAlex by DOI or arXiv id, else by a close title. No model is used.', { n: num(pendingLookups) })}</p>
    <div className="cc-acts">{action('Look up entries', onResolve, 'resolve')}</div>
  </>
  if (stage === 'acquire') return <>
    <p className="cc-step-h">{t('Step 2 of 4 · Get the text of each cited work')}</p>
    <p className="cc-step-p">{t('{n} works have no text decided yet. Your PDF is read first, then a PDF DEIXIS already holds, then an open-access copy, then the abstract. You can attach your own PDF to an entry below first.', { n: num(pendingText) })}</p>
    {acquisition?.status === 'paused' && <Notice tone="attention">{t('Today’s OpenAlex budget is used up, so some works still wait.')}{acquisition.reset_at ? ` ${t('It returns at {time}.', { time: new Date(acquisition.reset_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) })}` : ''}</Notice>}
    <div className="cc-acts">{action('Get the text', onAcquire, 'acquire')}</div>
  </>
  const waiting = view.reextraction_waiting ?? []
  const nextTry = waiting.map(w => w.next_at).filter((at): at is string => Boolean(at)).sort()[0]
  if (stage === 'freeze') return <>
    <p className="cc-step-h">{t('Step 3 of 4 · Freeze the passage plan')}</p>
    <p className="cc-step-p">{t('For each citation, the {k} passages of the cited work that share the most words with the sentence are chosen and fixed. The preview and the check read only this plan. At most {cap} pairs go to the model, in draft order.', { k: view.plan.passages_per_pair, cap: num(view.plan.cap) })}</p>
    {waiting.length > 0 && <Notice tone="attention">{t('Wait for re-extraction: the PDFs of entries {entries} are being read again for their equations. A plan frozen now would go stale when that ends; this page checks again every few seconds.', { entries: waiting.map(w => w.entry_ordinal).join(', ') })}
      {nextTry ? ` ${t('The next try is at {time}.', { time: new Date(nextTry).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) })}` : ''}</Notice>}
    <div className="cc-acts">{waiting.length > 0
      ? <button type="button" className="btn-teal" disabled><LoaderCircle size={16} className="cc-spin" aria-hidden />{t('Wait for re-extraction')}</button>
      : action('Freeze the plan', onFreeze, 'freeze')}</div>
  </>
  if (stage === 'paused' && view.check_run) {
    const run = view.check_run
    const reason = pauseReasonText(run.pause_reason, run.error)
    return <>
      <p className="cc-step-h"><TriangleAlert size={16} aria-hidden className="cc-warn-icon" />{t(run.status === 'failed' ? 'The check stopped with an error' : 'The check is paused')}</p>
      <p className="cc-step-p">{[reason || t(runStatusLabels[run.status]), ...pauseDetailText({ ...run, error: run.error ?? null })].filter(Boolean).join(' ')}</p>
      <p className="cc-step-p">{t('{done} pairs ended; {left} are waiting. Pairs already checked are not sent again.', { done: num((c.pairs_done ?? 0) + (c.pairs_could_not_check ?? 0)), left: num(c.pairs_to_send ?? 0) })}</p>
      {run.model && run.plan_revision ? <div className="cc-acts">{action('Continue the check', () => onStart(run.model!, run.plan_revision!), 'check')}</div> : null}
    </>
  }
  if (stage === 'done') return <>
    <p className="cc-step-h"><CircleCheck size={16} aria-hidden className="cc-ok-icon" />{t('Check finished')}</p>
    <p className="cc-step-p">{t('{done} pairs completed, {cnc} could not be checked. Pairs with no text, no record or beyond the cap were not sent.', { done: num(c.pairs_done ?? 0), cnc: num(c.pairs_could_not_check ?? 0) })}</p>
  </>
  return <PreviewBox preview={preview} busy={busy} onSettings={onSettings} onPreview={onPreview} onRefreeze={onRefreeze} onStart={onStart} />
}

function PreviewBox({ preview, busy, onSettings, onPreview, onRefreeze, onStart }: {
  preview: CitationPreview | null; busy: Busy; onSettings: () => void; onPreview: () => void; onRefreeze: () => void; onStart: (model: CitationModel, revision: number) => void
}) {
  const modelText = useModelText()
  if (!preview) return <p className="cc-muted" role="status"><span className="shimmer-text">{t('Reading the preview…')}</span></p>
  const cost = preview.cost
  const model = cost.connection && cost.model ? { connection: cost.connection, model: cost.model, reasoning_effort: cost.reasoning_effort } : null
  const stale = preview.selected.filter(p => p.stale).length
  return <div className="cc-preview">
    <p className="cc-step-h">{t('Step 4 of 4 · Preview, then start')}</p>
    <ul className="cc-facts">
      <li><span>{t('Model')}</span>{model ? <ModelName connection={model.connection} text={modelText(model.model, model.reasoning_effort)} />
        : <span className="cc-none">{t('none chosen')}</span>}</li>
      <li><span>{t('Cost')}</span><CostText preview={preview} /></li>
      <li><span>{t('Pairs to send')}</span>{t('{n}, in draft order', { n: num(preview.selected.length) })}</li>
      <li><span>{t('Beyond the cap')}</span>{t('{n} (cap {cap})', { n: num(preview.out_of_cap.length), cap: num(preview.cap) })}</li>
      <li><span>{t('Passages per pair')}</span>{t('up to {k}', { k: preview.passages_per_pair })}</li>
      <li><span>{t('Model calls')}</span>{cost.calls ? t('{low} to {high}, with at most one repair per pair', { low: num(cost.calls[0]), high: num(cost.calls[1]) }) : t('{n}, plus at most one repair per pair', { n: num(preview.selected.length) })}</li>
    </ul>
    {!model && <Notice tone="attention">{t('No literature model is chosen. Choose one in Settings, then preview again.')}
      <span className="cc-inline-acts"><button type="button" className="ghost" onClick={onSettings}>{t('Open Settings')}</button>
        <button type="button" className="ghost" disabled={busy !== null} onClick={onPreview}>{t('Preview again')}</button></span></Notice>}
    {stale > 0 && <Notice tone="attention">{t('The text of {n} planned pairs changed after the freeze. The check will refuse until the plan is frozen again.', { n: num(stale) })}
      <span className="cc-inline-acts"><button type="button" className="ghost" disabled={busy !== null} onClick={onRefreeze}>{t('Freeze the plan again')}</button></span></Notice>}
    <details className="cc-list" open={preview.selected.length <= 8}>
      <summary>{t('Pairs that will be sent ({n})', { n: num(preview.selected.length) })}</summary>
      <ol>{preview.selected.map(p => <PreviewRow key={p.id} pair={p} />)}</ol>
    </details>
    {preview.out_of_cap.length > 0 && <details className="cc-list">
      <summary>{t('Pairs beyond the cap, not sent ({n})', { n: num(preview.out_of_cap.length) })}</summary>
      <ol>{preview.out_of_cap.map(p => <PreviewRow key={p.id} pair={p} />)}</ol>
    </details>}
    <div className="cc-acts">
      <button type="button" className="btn-teal" disabled={!model || busy !== null} aria-disabled={!model || undefined}
        aria-describedby={!model ? 'cc-start-reason' : undefined} onClick={() => { if (model) onStart(model, preview.plan_revision) }}>
        <Play size={16} aria-hidden />{t('Start the check')}</button>
      {!model && <span id="cc-start-reason" className="cc-fine">{t('Start waits for a model.')}</span>}
      {model && <button type="button" className="ghost" disabled={busy !== null} onClick={onPreview}>{t('Preview again')}</button>}
    </div>
  </div>
}

function CostText({ preview }: { preview: CitationPreview }) {
  const cost = preview.cost
  if (cost.usd === 'unknown') return <span>{t('Unknown')} <span className="cc-fine">{t(cost.reason === 'no_model' ? '(no model is chosen)' : '(DEIXIS has no price for this model)')}</span></span>
  if (Array.isArray(cost.usd)) return <span>{t('at least {low}, at most {high}', { low: money(cost.usd[0]), high: money(cost.usd[1]) })} <span className="cc-fine">{t('(estimate; the provider’s bill is what counts)')}</span></span>
  if (cost.applies === false) return <span>{t(cost.kind === 'local' ? 'No cost per call: the model runs on this computer' : 'No cost per call: the model runs on a subscription')}</span>
  return <span>{t('Unknown')}</span>
}

function PreviewRow({ pair }: { pair: CitationPreviewPair }) {
  const read = pair.depth === 'abstract' ? t('abstract') : pair.depth === 'full_text' ? t('all {n} passages', { n: num(pair.passages_given ?? 0) })
    : pair.depth ? t('{k} of {n} passages', { k: num(pair.passages_given ?? 0), n: num(pair.passages_total ?? 0) }) : null
  return <li>
    <span className="cc-pr-target">{pair.target}</span>
    <span className="cc-pr-title">{pair.source?.title ?? t('No record')}</span>
    {read && <span className="cc-pr-read">{read}</span>}
    {pair.stale && <span className="cc-flag">{t('text changed')}</span>}
  </li>
}

// ------------------------------------------------------------------------------------------------- the table

function MarkedSentence({ marker }: { marker: CitationMarker }) {
  const offset = marker.sentence_span[0]
  const [a, b] = [marker.span[0] - offset, marker.span[1] - offset]
  if (a < 0 || b > marker.sentence.length || a >= b) return <>{marker.sentence}</>
  return <>{marker.sentence.slice(0, a)}<mark className="cc-marker">{marker.sentence.slice(a, b)}</mark>{marker.sentence.slice(b)}</>
}

const tableNotRead = 'The table’s layout was not read (merged cells, a nested table or a header over several rows), so this citation is not checked.'
const unreadReason: Record<CitationMarker['style'], string> = {
  latex: 'The keys inside this \\cite could not be read.',
  numeric: 'The bracket is not a list or range of reference numbers DEIXIS reads.',
  author_year: 'The names and year could not be read as one citation, or the names may start earlier than DEIXIS looks.',
}

function pairReason(pair: CitationPair): string | null {
  if (pair.status === 'ambiguous') return t('{target} fits more than one entry, or an entry of that year has authors that cannot be read. It is not matched by guess.', { target: pair.target })
  if (pair.status === 'unresolved') return pair.bib_entry_id ? t('The entry has no record.') : t('No bibliography entry has {target}.', { target: pair.target })
  if (pair.status === 'no_text') return t('Only the record’s metadata is held, so no model was asked.')
  if (pair.status === 'could_not_check') {
    const code = pair.check?.error?.code
    return t(code === 'message_too_large' ? 'The passages were too long to send.' : 'The model’s answer did not pass the checks, also after one repair. Its raw answer is kept.')
  }
  return null
}

// What the pair was given (or will be given), written the same way before and after the check and never naming the
// result: the Result column says what was found, and under each quote where that quote came from.
function readText(pair: CitationPair): string | null {
  const basis = pair.check?.basis
  const depth = basis?.depth ?? pair.plan?.depth
  if (!depth) return null
  if (depth === 'abstract') return t('Abstract only')
  const given = basis ? basis.passages_given : pair.plan!.passage_ids.length
  const total = basis ? basis.passages_total : pair.plan!.passages_total ?? given
  return t(depth === 'full_text' ? 'Full text · {k} of {n} passages given' : '{k} of {n} passages given', { k: num(given), n: num(total) })
}

const quoteOrigin = (evidence: CitationEvidence) => t(evidence.passage_kind === 'abstract' ? 'Quote from the abstract' : 'Quote from the PDF text')

const statusIcon = (status: CitationPair['status']) => status === 'done' ? <CircleCheck size={14} aria-hidden />
  : status === 'planned' ? <CircleDashed size={14} aria-hidden /> : status === 'could_not_check' ? <TriangleAlert size={14} aria-hidden /> : <CircleSlash size={14} aria-hidden />

function CitationTable({ view, onQuote, onWork }: { view: CitationCheckView; onQuote: (evidence: CitationEvidence) => void; onWork: (passageId: string) => void }) {
  const pending = (pair: CitationPair) => pair.bib_entry_id ? view.entries.find(e => e.id === pair.bib_entry_id)?.resolution.status === 'pending' : false
  return <div className="cc-table-wrap"><table className="cc-table">
    <colgroup><col className="cc-c-n" /><col className="cc-c-s" /><col className="cc-c-w" /><col className="cc-c-r" /><col className="cc-c-x" /><col className="cc-c-t" /></colgroup>
    <thead><tr>
      <th scope="col" className="cc-n">#</th><th scope="col">{t('Sentence')}</th><th scope="col">{t('Cited work')}</th>
      <th scope="col">{t('What was read')}</th><th scope="col">{t('Result')}</th><th scope="col">{t('Status')}</th>
    </tr></thead>
    {view.markers.map(marker => {
      const pairs = marker.pairs
      const sentence = <td className="cc-sentence" rowSpan={Math.max(1, pairs.length)} data-label={t('Sentence')}><MarkedSentence marker={marker} />
        {marker.claim && <span className="cc-reason">{marker.claim_context ? t('Checked as the table row: {row}', { row: marker.claim }) : t('Checked as: {claim}', { claim: marker.claim })}</span>}</td>
      const n = <th scope="rowgroup" className="cc-n" rowSpan={Math.max(1, pairs.length)}>{marker.ordinal}</th>
      if (!pairs.length) return <tbody key={marker.id} data-marker={marker.ordinal}><tr data-status="unrecognized">
        {n}{sentence}<td data-label={t('Cited work')} className="cc-none">{marker.raw}</td><td data-label={t('What was read')} className="cc-none">–</td>
        <td data-label={t('Result')} className="cc-none">–</td>
        <td data-label={t('Status')}><span className="cc-status" data-status="unrecognized">{statusIcon('unrecognized')}{t(citationStatusLabels.unrecognized)}</span>
          <span className="cc-reason">{t(marker.parse_reason === 'table_layout_not_read' ? tableNotRead : unreadReason[marker.style])}</span></td>
      </tr></tbody>
      return <tbody key={marker.id} data-marker={marker.ordinal}>{pairs.map((pair, i) => {
        const reason = pairReason(pair)
        const notLooked = pair.status === 'planned' && pending(pair)
        const read = readText(pair)
        const firstPassage = pair.plan?.passage_ids[0]
        return <tr key={pair.id} data-pair={pair.ordinal} data-status={pair.status} data-result={pair.result ?? undefined} className={i ? 'cc-subrow' : undefined}>
          {i === 0 && n}{i === 0 && sentence}
          <td data-label={t('Cited work')} className="cc-work">
            <span className="cc-target">{pair.target}</span>
            {pair.source ? <>
              {firstPassage ? <button type="button" className="cc-title" onClick={() => onWork(firstPassage)}>{pair.source.title}</button> : <span className="cc-title">{pair.source.title}</span>}
              <span className="cc-authors">{authorsLine(pair.source)}</span>
            </> : <span className="cc-none">{notLooked ? '–' : t('No record')}</span>}
            {pair.flags.length > 0 && <span className="cc-flags">{pair.flags.map(f => <span key={f} className="cc-flag" data-flag={f}>{t(citationFlagLabels[f])}</span>)}</span>}
          </td>
          <td data-label={t('What was read')} className="cc-read">{read ?? <span className="cc-none">–</span>}</td>
          <td data-label={t('Result')} className="cc-result">
            {pair.result ? <span className="cc-pill" data-result={pair.result}>{t(citationResultLabels[pair.result])}</span> : <span className="cc-none">–</span>}
            {pair.check?.parts && pair.result && <Parts parts={pair.check.parts} onQuote={onQuote} />}
          </td>
          <td data-label={t('Status')}>
            <span className="cc-status" data-status={pair.status}>{statusIcon(pair.status)}{notLooked ? t('Not looked up yet') : t(citationStatusLabels[pair.status])}</span>
            {reason && <span className="cc-reason">{reason}</span>}
            {pair.plan?.stale && pair.status === 'planned' && <span className="cc-reason">{t('The text changed after the freeze.')}</span>}
            {pair.status === 'could_not_check' && pair.check?.raw_output && <details className="cc-raw"><summary>{t('Raw answer')}</summary><pre>{pair.check.raw_output}</pre></details>}
          </td>
        </tr>
      })}</tbody>
    })}
  </table></div>
}

// The located quotes of each part; a sentence the model read as one part shows its quotes alone, since the result
// already names its assessment, and a sentence in several parts names each part and how it was read.
// A part is cut from the sentence with its markers removed, which can leave a space before the closing punctuation.
const tidy = (text: string) => text.replace(/\s+([.,;:!?])/g, '$1')

function Parts({ parts, onQuote }: { parts: CitationPart[]; onQuote: (evidence: CitationEvidence) => void }) {
  const whole = parts.length === 1
  if (whole && !parts[0].evidence.some(e => e.located)) return null
  return <ul className="cc-parts">{parts.map((part, i) => <li key={i} data-assessment={part.assessment}>
    {!whole && <span className="cc-part-h"><span className="cc-part-a">{t(citationAssessmentLabels[part.assessment])}</span> {tidy(part.text)}</span>}
    {part.evidence.filter(e => e.located && e.anchor_text).map((e, j) => <span key={j} className="cc-quote-wrap">
      <button type="button" className="cc-quote" onClick={() => onQuote(e)}>“{e.anchor_text}”</button>
      <span className="cc-origin">{quoteOrigin(e)}</span>
    </span>)}
  </li>)}</ul>
}

// ------------------------------------------------------------------------------------------------- bibliography

function entryResolution(entry: CitationEntry): string {
  const r = entry.resolution
  if (r.status === 'resolved') return t(r.origin === 'user' ? 'Linked by you' : r.method === 'doi' ? 'Linked by DOI' : r.method === 'arxiv' ? 'Linked by arXiv id' : 'Linked by title')
  if (r.status === 'pending') return t('Not looked up yet')
  const reason = r.reason && citationResolutionReasons[r.reason] ? t(citationResolutionReasons[r.reason]) : r.reason ?? ''
  return `${t(r.status === 'lookup_failed' ? 'Lookup failed' : 'No record')}${reason ? `: ${reason}` : ''}`
}

function entryText(entry: CitationEntry): string | null {
  if (entry.resolution.status !== 'resolved') return null
  const text = entry.text
  const note = text.note && citationTextNotes[text.note] ? t(citationTextNotes[text.note]) : null
  if (text.status === 'pending') return note ?? t('Text not decided yet')
  const from = text.origin ? t(citationTextOrigins[text.origin] ?? text.origin) : null
  const version = text.version === 'upload' ? t('your upload') : text.version === 'preprint' ? t('preprint') : text.version === 'publisher' ? t('publisher version') : null
  const head = text.available === 'full_text' ? t('Full text from {from}', { from: from ?? '' }) : text.available === 'abstract' ? t('Abstract only') : t('Metadata only')
  return [head, text.available === 'metadata_only' ? null : version, note].filter(Boolean).join(' · ')
}

function Entries({ view, busy, locked, onAttach }: { view: CitationCheckView; busy: Busy; locked: boolean; onAttach: (entry: CitationEntry, file: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [target, setTarget] = useState<CitationEntry | null>(null)
  if (!view.entries.length) return <p className="cc-muted">{t('No bibliography entry was read. Upload a BibTeX or RIS file, or end the draft with a reference list.')}</p>
  return <>
    <ul className="cc-entries">{view.entries.map(entry => {
      const text = entryText(entry)
      return <li key={entry.id} data-entry={entry.key ?? entry.number ?? entry.ordinal} data-resolution={entry.resolution.status}>
        <span className="cc-target">{entry.key ?? (entry.number !== null ? `[${entry.number}]` : `#${entry.ordinal}`)}</span>
        <div className="cc-entry-body">
          {entry.source ? <span className="cc-title">{entry.source.title}</span>
            : <span className="cc-asw"><span className="cc-fine">{t('As written:')}</span> {entry.as_written.title ?? entry.raw_entry}</span>}
          {entry.source && <span className="cc-authors">{authorsLine(entry.source)}</span>}
          <span className="cc-entry-state" data-state={entry.resolution.status}>{entryResolution(entry)}{text ? ` · ${text}` : ''}</span>
          {entry.flags.length > 0 && <span className="cc-flags">{entry.flags.map(f => <span key={f} className="cc-flag" data-flag={f}>{t(citationFlagLabels[f])}</span>)}</span>}
        </div>
        {entry.resolution.status === 'resolved' && !locked && <button type="button" className="ghost cc-attach" disabled={busy !== null}
          aria-busy={busy === `upload:${entry.id}`} onClick={() => { setTarget(entry); input.current?.click() }}>
          {busy === `upload:${entry.id}` ? <LoaderCircle size={16} className="cc-spin" aria-hidden /> : <Paperclip size={16} aria-hidden />}{t(entry.upload ? 'Replace my PDF' : 'Attach my PDF')}</button>}
      </li>
    })}</ul>
    <input ref={input} type="file" hidden accept="application/pdf,.pdf" aria-label={t('PDF for this entry')}
      onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file && target) onAttach(target, file) }} />
  </>
}
