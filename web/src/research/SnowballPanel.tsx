import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GitFork, Search } from 'lucide-react'
import { api, ApiError, screenMoreApi, snowballApi, type SnowballRound, type SnowballSeries, type SnowballSummary, type SnowballView } from '../lib/api'
import { Notice } from '../components/Notice'
import { useToast } from '../components/Toast'
import { t, uiLocale } from '../lib/i18n'
import './kit.css'
import './snowball.css'

// Citation snowballing (workflow/snowball.py): the person picks seeds, a round reads their reference lists and the
// works citing them from OpenAlex, and screens the new works with the abstract stage. A round includes nothing: a
// candidate is a work two model reads agreed on, for the person to look at. Every count here comes from the round's
// stored summary; found, screened, candidate and the person's later choice stay apart.

type Direction = 'backward' | 'forward'
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])

const errorText = (error: unknown) => (error instanceof ApiError || error instanceof Error ? error.message : t('Something went wrong.'))
const idempotency = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`)

export function SnowballPanel({ researchId, eventCursor, initialSeed, onOpenSource, onChanged }: {
  researchId: string; eventCursor: number; initialSeed: string | null
  onOpenSource: (sourceVersionId: string) => void; onChanged: () => Promise<unknown>
}) {
  const toast = useToast()
  const [view, setView] = useState<SnowballView | null>(null)
  const [error, setError] = useState('')
  const [seeds, setSeeds] = useState<ReadonlySet<string>>(new Set(initialSeed ? [initialSeed] : []))
  const [dois, setDois] = useState('')
  const [directions, setDirections] = useState<ReadonlySet<Direction>>(new Set(['backward', 'forward']))
  const [series, setSeries] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)

  const reload = useCallback(async () => {
    const request = ++generation.current
    try {
      const next = await snowballApi.view(researchId)
      if (request === generation.current) { setView(next); setError('') }
    } catch (e) { if (request === generation.current) setError(errorText(e)) }
  }, [researchId])
  useEffect(() => { void reload() }, [reload, eventCursor])
  useEffect(() => { if (initialSeed) { setSeeds(new Set([initialSeed])); setSeries(null) } }, [initialSeed])

  const titles = useMemo(() => new Map((view?.seed_options ?? []).map(o => [o.source_version_id, o.title])), [view])
  const doiList = dois.split(/[\s,]+/).map(d => d.trim()).filter(Boolean)
  const limits = view?.limits
  const count = seeds.size + doiList.length
  const running = view?.series.some(s => s.rounds.some(r => ACTIVE.has(r.status))) ?? false
  const blocked = !view?.available ? t('A search of this question must finish first.')
    : running ? t('A round is still running.')
    : count === 0 ? t('Choose at least one seed.')
    : limits && count > limits.max_seeds ? t('At most {n} seeds a round.', { n: limits.max_seeds })
    : directions.size === 0 ? t('Choose backward, forward or both.') : ''

  const start = async () => {
    setBusy(true)
    try {
      await snowballApi.start(researchId, { seeds: [...seeds], dois: doiList, directions: [...directions], series_id: series }, idempotency())
      toast('success', t(series ? 'The next round started.' : 'The first round started.'))
      setDois('')
      await reload(); await onChanged()
    } catch (e) { toast('error', errorText(e)) } finally { setBusy(false) }
  }

  const continueSeries = (s: SnowballSeries) => {
    setSeries(s.series_id)
    setSeeds(new Set(s.suggested_seeds))
    document.getElementById('snowball-start')?.scrollIntoView({ block: 'start' })
  }

  const toggle = (id: string) => setSeeds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const toggleDirection = (d: Direction) => setDirections(prev => { const next = new Set(prev); if (next.has(d)) next.delete(d); else next.add(d); return next })

  if (error && !view) return <div className="mk pad"><Notice tone="error">{error}<button type="button" className="ghost" onClick={() => void reload()}>{t('Retry')}</button></Notice></div>
  if (!view) return <div className="mk pad"><p role="status"><span className="shimmer-text">{t('Loading snowballing…')}</span></p></div>

  const options = view.seed_options.filter(o => !query || (o.title ?? '').toLocaleLowerCase(uiLocale()).includes(query.toLocaleLowerCase(uiLocale())))
  return <div className="mk pad snowball">
    <p>{t('Start from works you choose: a round reads the works they cite and the works citing them from OpenAlex, then screens the new ones from their abstracts. A round includes nothing; you decide.')}</p>
    {!view.available && <Notice tone="attention">{t('A search of this question must finish first. Snowballing screens with the vocabulary that search approved.')}</Notice>}

    <section id="snowball-start" className="sb-form" aria-labelledby="sb-form-h">
      <h3 id="sb-form-h">{series ? t('Next round') : t('New snowball')}</h3>
      {series && <p className="foot-note">{t('Seeds are preselected from the last round: its candidates and the works you included. Change them as you like.')}
        {' '}<button type="button" className="link" onClick={() => { setSeries(null); setSeeds(new Set()) }}>{t('Start a new series instead')}</button></p>}
      <label className="lbl sb-search"><span>{t('Seeds from this research')}</span>
        <span className="sb-q"><Search size={14} aria-hidden /><input className="field" value={query} onChange={e => setQuery(e.target.value)} placeholder={t('Filter by title')} /></span>
      </label>
      <ul className="sb-seeds">
        {options.map(o => <li key={o.source_version_id}>
          <label aria-disabled={!o.has_openalex_id || undefined}>
            <input type="checkbox" checked={seeds.has(o.source_version_id)} disabled={!o.has_openalex_id} onChange={() => toggle(o.source_version_id)}
              aria-describedby={o.has_openalex_id ? undefined : `sb-no-${o.source_version_id}`} />
            <span className="sb-t">{o.title ?? t('Untitled')}{o.year ? ` (${o.year})` : ''}</span>
            {o.state && <span className="pill">{t(o.state === 'included' ? 'Included' : o.state === 'uncertain' ? 'Not sure' : 'Undecided')}</span>}
            {!o.has_openalex_id && <span className="foot-note" id={`sb-no-${o.source_version_id}`}>{t('No OpenAlex record, so its reference list cannot be read')}</span>}
          </label>
        </li>)}
        {options.length === 0 && <li className="foot-note">{t('No source matches.')}</li>}
      </ul>
      <label className="lbl"><span>{t('Or add by DOI (one per line)')}</span>
        <textarea className="field" rows={2} value={dois} onChange={e => setDois(e.target.value)} placeholder="10.1109/…" />
        <small>{t('A DOI that names exactly one OpenAlex work joins the research as an undecided source and becomes a seed.')}</small>
      </label>
      <fieldset className="lbl sb-dirs"><legend>{t('Directions')}</legend>
        <label><input type="checkbox" checked={directions.has('backward')} onChange={() => toggleDirection('backward')} />{t('Backward: works the seeds cite')}</label>
        <label><input type="checkbox" checked={directions.has('forward')} onChange={() => toggleDirection('forward')} />{t('Forward: works citing the seeds, newest first')}</label>
      </fieldset>
      {limits && <p className="foot-note tnum">{t('Up to {seeds} seeds. A round sends OpenAlex at most {back} reference requests and {fwd} citing-work pages of {page}, and screens up to {screen} new works. A series has at most {rounds} rounds.',
        { seeds: limits.max_seeds, back: limits.backward_requests, fwd: limits.forward_requests, page: limits.page_size, screen: limits.screen_limit, rounds: limits.max_rounds })}</p>}
      <div className="acts">
        <button type="button" className="btn-pri" disabled={Boolean(blocked) || busy} aria-describedby={blocked ? 'sb-blocked' : undefined} onClick={() => void start()}>
          <GitFork size={16} aria-hidden />{series ? t('Start the next round') : t('Start round 1')}</button>
        {blocked && <span className="foot-note" id="sb-blocked">{blocked}</span>}
      </div>
    </section>

    {view.series.slice().reverse().map(s => <SeriesView key={s.series_id} series={s} titles={titles} note={view.signals_note}
      researchId={researchId} onOpenSource={onOpenSource} onContinue={() => continueSeries(s)} onChanged={async () => { await reload(); await onChanged() }} />)}
  </div>
}

function SeriesView({ series, titles, note, researchId, onOpenSource, onContinue, onChanged }: {
  series: SnowballSeries; titles: Map<string, string | null>; note: string; researchId: string
  onOpenSource: (sourceVersionId: string) => void; onContinue: () => void; onChanged: () => Promise<unknown>
}) {
  const last = series.rounds[series.rounds.length - 1]
  const reason = series.stale ? t('The question changed since this series. Its rounds stay as they were; start a new series.')
    : last.status !== 'completed' ? t('The last round has not finished.')
    : !series.can_continue ? t('This series reached its round limit.') : ''
  return <section className="sb-series" aria-label={t('Snowball series')}>
    <div className="sb-head"><h3>{t('Snowball series')}{series.stale && <span className="pill warn">{t('Earlier question')}</span>}</h3>
      <button type="button" className="ghost" disabled={Boolean(reason)} aria-describedby={reason ? `sb-r-${series.series_id}` : undefined} onClick={onContinue}>{t('Prepare the next round')}</button>
    </div>
    {reason && <p className="foot-note" id={`sb-r-${series.series_id}`}>{reason}</p>}
    {series.rounds.slice().reverse().map(r => <RoundView key={r.run_id} round={r} titles={titles} note={note} researchId={researchId} onOpenSource={onOpenSource} onChanged={onChanged} />)}
  </section>
}

function RoundView({ round, titles, note, researchId, onOpenSource, onChanged }: {
  round: SnowballRound; titles: Map<string, string | null>; note: string; researchId: string
  onOpenSource: (sourceVersionId: string) => void; onChanged: () => Promise<unknown>
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const s = round.summary
  const control = async (action: 'resume' | 'cancel') => {
    setBusy(true)
    try { await api.controlRun(round.run_id, action); await onChanged() } catch (e) { toast('error', errorText(e)) } finally { setBusy(false) }
  }
  const screenNext = async () => {
    setBusy(true)
    try { await screenMoreApi.screenMore(researchId, idempotency(), round.run_id); toast('success', t('Screening of the next works started.')); await onChanged() }
    catch (e) { toast('error', errorText(e)) } finally { setBusy(false) }
  }
  const quota = round.status === 'paused' && round.pause_reason === 'openalex_budget_exhausted'
  const resetAt = (round.error as { reset_at?: string } | null)?.reset_at
  const a = s?.admissions ?? {}
  const backwardAsked = s ? s.requests.filter(q => q.direction === 'backward').reduce((n, q) => n + q.asked, 0) : 0
  const forward = s ? s.requests.filter(q => q.direction === 'forward') : []
  const sent = (status: string) => !['cancelled', 'not_started', 'pending'].includes(status)
  // A later page closed without a request because the page before had no cursor: that page was the last, nothing was
  // left to ask. Summaries stored before `unsent` was kept per request only count it, under `no_cursor`.
  const lastPageBefore = (q: SnowballSummary['requests'][number]) => q.unsent === 'no_cursor'
    || (q.unsent === undefined && q.status === 'cancelled' && (q.page ?? 1) > 1 && !!s?.unsent.no_cursor)
  const notNeeded = forward.filter(lastPageBefore).length
  const notSent = forward.filter(q => !sent(q.status) && !lastPageBefore(q)).length
  const unsent = s ? Object.entries(s.unsent).reduce((n, [why, v]) => why === 'no_cursor' ? n : n + v, 0) : 0
  const rows: [string, string][] = s ? [
    [t('Seeds'), [String(s.seeds), s.unusable_seeds ? t('{n} without an OpenAlex record', { n: s.unusable_seeds }) : '',
      s.seeds_without_list ? t('{n} whose reference list could not be read', { n: s.seeds_without_list }) : ''].filter(Boolean).join(' · ')],
    [t('Reference ids'), [t('{n} named', { n: s.backward_ids }), t('{n} already in this research', { n: s.held }), t('{n} asked', { n: backwardAsked }),
      s.not_requested ? t('{n} not asked (request limit)', { n: s.not_requested }) : ''].filter(Boolean).join(' · ')],
    [t('Citing-work pages'), [t('{n} asked', { n: forward.filter(q => sent(q.status)).length }),
      notSent ? t('{n} not sent', { n: notSent }) : '', notNeeded ? t('{n} not needed (OpenAlex had no further page)', { n: notNeeded }) : '', ...forward.filter(q => q.page === 1 && q.provider_total !== null).map(q => t('{title}: {total} citing works in OpenAlex', { title: titles.get(q.seed ?? '') ?? t('seed'), total: q.provider_total ?? 0 }))].filter(Boolean).join(' · ')],
    [t('Came back'), [t('{n} new to this research', { n: a.new ?? 0 }), t('{n} already held', { n: a.existing ?? 0 }), a.seen ? t('{n} seen again this round', { n: a.seen }) : '',
      a.ambiguous ? t('{n} matching two works here (not added)', { n: a.ambiguous }) : '', a.no_record ? t('{n} with no OpenAlex record', { n: a.no_record }) : '',
      a.unresolved ? t('{n} unresolved (incomplete answer)', { n: a.unresolved }) : '', unsent ? t('{n} requests not sent', { n: unsent }) : ''].filter(Boolean).join(' · ')],
    [t('Abstract screening'), [t('{n} of {total} new works planned', { n: s.planned_for_screening, total: s.new_works }),
      t('{n} read by the model', { n: s.screening.model_read }), s.screening.code ? t('{n} decided by code without a read', { n: s.screening.code }) : '',
      s.screening.no_abstract ? t('{n} without an abstract', { n: s.screening.no_abstract }) : '', s.screening.not_read ? t('{n} not read', { n: s.screening.not_read }) : '',
      s.not_screened_limit ? t('{n} not planned (round limit)', { n: s.not_screened_limit }) : ''].filter(Boolean).join(' · ')],
    [t('Candidates'), t('{n} (two model reads agreed; not included)', { n: s.candidates.length })],
  ] : []
  const notScreened = round.items.filter(i => i.screening === 'not_read' && !i.removed).length
  return <article className="sb-round">
    <div className="sb-head"><h4>{t('Round {n}', { n: round.round })}</h4>
      <span className="pill">{round.directions.map(d => t(d === 'backward' ? 'backward' : 'forward')).join(' + ')}</span>
      {ACTIVE.has(round.status) && <span className="sb-live" role="status"><span className="spin" aria-hidden /><span className="shimmer-text">{t('Running…')}</span></span>}
      {round.status === 'failed' && <span className="pill warn">{t('Failed')}</span>}
      {round.status === 'cancelled' && <span className="pill">{t('Cancelled')}</span>}
    </div>
    {quota && <Notice tone="attention">{t('OpenAlex’s daily quota is used up.')} {resetAt && t('The quota renews around {time}.', { time: new Date(resetAt).toLocaleTimeString(uiLocale(), { hour: '2-digit', minute: '2-digit' }) })}
      <span className="acts"><button type="button" className="ghost" disabled={busy} onClick={() => void control('resume')}>{t('Resume')}</button></span></Notice>}
    {round.status === 'paused' && !quota && <Notice tone="attention">{t('This round is paused.')}<span className="acts"><button type="button" className="ghost" disabled={busy} onClick={() => void control('resume')}>{t('Resume')}</button></span></Notice>}
    {round.dois?.some(d => d.status !== 'added' && d.status !== 'in_research') && <p className="foot-note">{t('Some DOIs did not resolve to exactly one OpenAlex work and were not used: {dois}', { dois: round.dois.filter(d => d.status !== 'added' && d.status !== 'in_research').map(d => d.doi).join(', ') })}</p>}
    {s && <dl className="sb-counts">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="tnum">{v}</dd></div>)}</dl>}
    {round.items.length > 0 && <>
      <p className="foot-note">{note}</p>
      <ol className="sb-items">
        {round.items.slice(0, 200).map(item => <li key={item.work_id}>
          {item.source_version_id && !item.removed
            ? <button type="button" className="link sb-t" onClick={() => onOpenSource(item.source_version_id!)}>{item.title ?? t('Untitled')}</button>
            : <span className="sb-t">{item.title ?? t('Untitled')} · {t('Removed from this research')}</span>}
          <span className="foot-note tnum">{[item.year, t(item.seeds === 1 ? '1 seed links to it' : '{n} seeds link to it', { n: item.seeds }),
            item.directions.map(d => t(d === 'backward' ? 'cited by a seed' : 'cites a seed')).join(', ')].filter(Boolean).join(' · ')}</span>
          <span className="sb-tags">
            {item.person_state ? <span className="pill">{t(item.person_state === 'included' ? 'You included' : item.person_state === 'excluded' ? 'You excluded' : 'You set it back')}</span>
              : item.candidate ? <span className="pill">{t('Candidate')}</span>
              : item.screening === 'not_read' ? <span className="pill">{t('Not screened yet')}</span>
              : item.screening === 'no_abstract' ? <span className="pill">{t('No abstract to screen')}</span>
              : item.screening === 'code' ? <span className="pill">{t('Decided by code')}</span> : null}
          </span>
        </li>)}
      </ol>
      {round.items.length > 200 && <p className="foot-note">{t('{n} more new works are in the Sources panel.', { n: round.items.length - 200 })}</p>}
      {round.status === 'completed' && notScreened > 0 && <div className="acts"><button type="button" className="ghost" disabled={busy} onClick={() => void screenNext()}>{t('Screen the next 40')}</button></div>}
    </>}
    {s && round.items.length === 0 && <p className="foot-note">{t('This round brought no work that was new to this research.')}</p>}
    {s && round.items.length > 0 && s.candidates.length === 0 && <p className="foot-note">{t('No new candidate in this round. {n} works were not screened and {m} reference ids were not asked.', { n: s.not_screened_limit, m: s.not_requested })}</p>}
  </article>
}
