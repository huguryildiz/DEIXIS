import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Info, Search, TriangleAlert, X } from 'lucide-react'
import { api, ApiError, searchPlanApi, type ResearchView, type SearchPlanProvider, type SearchPlanView, type UserSearchPlan } from '../api'
import { providerName } from '../labels'
import { useToast } from '../Toast'
import { t } from '../i18n'
import './kit.css'
import './plan.css'

// The Search plan panel (UI parity S23b, P42; mockup `plan()`; D12). It shows the plan the server stores for the revision
// it names (api/search_plan_routes.py): the words of each block, the stored Query 1/Query 2 (read only: a person edits
// words, never query text), the criterion and the providers. "Search again with this plan" saves the edited plan as the
// next question revision and then asks for a discovery run; each outcome is reported from the server's answer, and a
// saved plan whose search did not start says so. Cancel drops the draft and sends nothing.
// While the panel is open the plan is read again on every recorded event: a newer revision saved elsewhere (another
// window, a PDF choice) is shown as a conflict that keeps the draft, and a reply that arrives after a newer request is
// dropped.

type Block = 'setting' | 'task'
type Draft = { setting: string[]; task: string[]; criterion: string | null; providers: SearchPlanProvider[] }
type Issue = { code: string; path: string; message: string }

const OPTIONAL: SearchPlanProvider[] = ['semantic_scholar', 'crossref', 'scopus']
const BLOCKS: Block[] = ['setting', 'task']
const BLOCK_LABELS: Record<Block, string> = { setting: 'Field or setting', task: 'What is looked for' }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])

const draftOf = (plan: UserSearchPlan): Draft => ({
  setting: plan.setting.map(row => row.term), task: plan.task.map(row => row.term),
  criterion: plan.criterion ? plan.criterion.text : null, providers: plan.providers,
})
// The plan the person saves: the stored one with the edited words, criterion sentence and providers. Backups, the
// criterion's parts, phrases, exclusion words and question elements go back unchanged.
const planOf = (stored: UserSearchPlan, draft: Draft): UserSearchPlan => ({
  ...stored,
  setting: draft.setting.map(term => ({ term })), task: draft.task.map(term => ({ term })),
  criterion: stored.criterion ? { ...stored.criterion, text: draft.criterion ?? '' } : null,
  providers: ['openalex', ...OPTIONAL.filter(provider => draft.providers.includes(provider))],
})
const same = (a: UserSearchPlan, b: UserSearchPlan) => JSON.stringify(a) === JSON.stringify(b)
// What the shown plan stands on: the revision, the frozen protocol it came from and where it came from. A newer value of
// any of them means the stored plan under the draft changed.
const baseKey = (view: SearchPlanView) => [view.scope_revision, view.based_on?.scope_revision, view.based_on?.protocol_revision, view.origin].join('|')
// The current revision holds this plan as the person saved it (not a plan read from an earlier search).
const ownPlan = (view: SearchPlanView) => view.origin === 'user' && (view.queries_preview || view.based_on?.scope_revision === view.scope_revision)
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

function fieldOf(path: string): string | null {
  const head = path.split('/')[1] ?? ''
  if (head === 'setting') return t('Field or setting')
  if (head === 'task') return t('What is looked for')
  if (head === 'setting_backup' || head === 'task_backup') return t('Backup words')
  if (head === 'criterion') return t('Inclusion criterion')
  if (head === 'providers') return t('Sources')
  return null
}
// A rule the plan breaks, in plain words where the code is known; otherwise the server's own sentence, unchanged.
function issueText(issue: Issue, plan: UserSearchPlan | null): string {
  const field = fieldOf(issue.path)
  const [, head, index] = issue.path.split('/')
  const term = plan && (head === 'setting' || head === 'task' || head === 'setting_backup' || head === 'task_backup') && index !== undefined
    ? plan[head][Number(index)]?.term ?? issue.message : issue.message
  const withField = (text: string) => (field ? `${field}: ${text}` : text)
  switch (issue.code) {
    case 'empty_query_block': return withField(t('add at least one word.'))
    case 'too_many_query_terms': return t('Use at most 6 search words in all.')
    case 'query_term_too_long': return t('“{term}” is longer than four words.', { term })
    case 'query_syntax_in_term': return t('“{term}” holds quotation marks, brackets or AND, OR, NOT.', { term })
    case 'query_term_empty': return withField(t('one word is empty.'))
    case 'duplicate_query_term': return t('“{term}” is listed twice.', { term })
    case 'provider_not_in_scope': return issue.message
    case 'user_plan_schema_invalid':
      if (/should be non-empty$/.test(issue.message) && (head === 'setting' || head === 'task')) return withField(t('add at least one word.'))
      if (/is too long$/.test(issue.message) && (head === 'setting' || head === 'task')) return withField(t('at most 5 words.'))
      return withField(issue.message)
    default: return withField(t(issue.message))
  }
}

export function PlanPanel({ researchId, view, busy, searchReady, answerRevision, seeds, onAnnounced, onChanged, onClose }: {
  researchId: string
  view: ResearchView
  busy: boolean
  // The research can search now (a research that must be guided by PDFs has a readable one chosen).
  searchReady: boolean
  // The question revision the shown answer belongs to, when there is one.
  answerRevision: number | null
  // The PDFs guiding the search and their choice (§2.2), for a research over files and academic search.
  seeds: ReactNode | null
  // A run this panel announced itself, so the page does not announce its start again over the panel's message.
  onAnnounced: (runId: string) => void
  onChanged: () => Promise<void>
  onClose: () => void
}) {
  const toast = useToast()
  const [loaded, setLoaded] = useState<SearchPlanView | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loadError, setLoadError] = useState('')
  // A newer plan of the research read while the draft differs from the plan it started from.
  const [conflict, setConflict] = useState<SearchPlanView | null>(null)
  // The rules the server refused the last save for; cleared when the draft changes.
  const [refused, setRefused] = useState<Issue[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [word, setWord] = useState('')
  const [block, setBlock] = useState<Block>('task')
  // Asking to read the plan again after a refresh failed.
  const [retry, setRetry] = useState(0)
  const request = useRef(0)
  const savingRef = useRef(false)
  // A start the server refused for a newer revision: that revision stays a conflict until the person chooses, even
  // though the draft equals the plan just saved.
  const pinned = useRef(false)
  const state = useRef<{ loaded: SearchPlanView | null; draft: Draft | null }>({ loaded: null, draft: null })
  useEffect(() => { state.current = { loaded, draft } })
  const addField = useRef<HTMLInputElement>(null)

  const dirty = Boolean(loaded?.plan && draft && !same(planOf(loaded.plan, draft), loaded.plan))
  const changeDraft = (change: (current: Draft) => Draft) => { setDraft(current => (current ? change(current) : current)); setRefused(null) }

  // Read on open and again on every recorded event and version change of the research. Only the newest request's reply is used.
  const eventCursor = view.last_event_id
  const version = view.research.version
  useEffect(() => {
    const ask = ++request.current
    searchPlanApi.get(researchId).then(fresh => {
      if (ask !== request.current || savingRef.current) return
      setLoadError('')
      const { loaded: shown, draft: current } = state.current
      const edited = Boolean(shown?.plan && current && !same(planOf(shown.plan, current), shown.plan))
      if (!shown || baseKey(fresh) === baseKey(shown)) {
        // Same stored plan: only its version moves (a rename); the draft stays.
        setLoaded(fresh)
        if (!shown || !edited) setDraft(fresh.plan ? draftOf(fresh.plan) : null)
        setConflict(null)
      } else if (!edited && !pinned.current) {
        setLoaded(fresh); setDraft(fresh.plan ? draftOf(fresh.plan) : null); setConflict(null); setRefused(null)
      } else setConflict(fresh)
    }, e => { if (ask === request.current) setLoadError(errorText(e)) })
  }, [researchId, eventCursor, version, retry])

  const active = view.runs.some(run => ACTIVE.has(run.status))
  const own = loaded ? ownPlan(loaded) : false

  const rebase = () => { if (conflict) { pinned.current = false; setLoaded(conflict); setConflict(null) } }
  const discard = () => { if (conflict) { pinned.current = false; setLoaded(conflict); setDraft(conflict.plan ? draftOf(conflict.plan) : null); setConflict(null); setRefused(null) } }

  const addWord = () => {
    const text = word.trim()
    if (!text) return
    changeDraft(current => ({ ...current, [block]: [...current[block], text] }))
    setWord('')
  }
  const removeWord = (from: Block, index: number) => {
    changeDraft(current => ({ ...current, [from]: current[from].filter((_, i) => i !== index) }))
    // Focus goes to the next word's remove button in the same block, else to the field that adds a word.
    requestAnimationFrame(() => {
      const buttons = document.querySelectorAll<HTMLButtonElement>(`.plan-panel .kw[data-block="${from}"] button`)
      ;(buttons[Math.min(index, buttons.length - 1)] ?? addField.current)?.focus()
    })
  }
  const toggleProvider = (provider: SearchPlanProvider, on: boolean) =>
    changeDraft(current => ({ ...current, providers: on ? [...current.providers, provider] : current.providers.filter(p => p !== provider) }))

  // Save (unless the current revision already holds this very plan), then ask for the search. Each message says what the
  // server did: a refused plan names its rules, a saved plan whose search was not started says so.
  const search = async () => {
    const shown = loaded
    if (!shown?.plan || !draft || saving || conflict) return
    setSaving(true); savingRef.current = true; setRefused(null)
    // The plan view the search is started for: the one shown, or the one the save answered with.
    let current = shown
    let saved = false
    // A newer revision read after a refusal: shown as a conflict that keeps the draft, unless the stored plan is the same.
    const reread = async (pin = false) => {
      const ask = ++request.current
      const fresh = await searchPlanApi.get(researchId).catch(() => null)
      if (fresh && ask === request.current) { if (baseKey(fresh) === baseKey(current)) setLoaded(fresh); else { pinned.current = pin; setConflict(fresh) } }
    }
    try {
      const plan = planOf(shown.plan, draft)
      if (!(own && same(plan, shown.plan))) {
        try {
          const next = await searchPlanApi.save(researchId, shown.expected_version, plan)
          request.current++  // a read sent before the save answers with the earlier revision: drop it
          setLoaded(next); setDraft(next.plan ? draftOf(next.plan) : null)
          current = next
          saved = true
        } catch (e) {
          if (e instanceof ApiError && e.status === 422) {
            const issues = (e.details?.issues as Issue[] | undefined) ?? []
            setRefused(issues.length ? issues : [{ code: e.code ?? 'refused', path: '/', message: e.message }])
          } else if (e instanceof ApiError && e.status === 409) {
            await reread()
            toast('warning', t('Not saved: the research changed after this plan was read. Your draft is kept.'))
          } else toast('error', t('The plan was not saved: {error}', { error: errorText(e) }))
          return
        }
      }
      try {
        // Bound to the revision that holds this plan (D14): if another window saved a newer one meanwhile, the server
        // refuses and creates no run, so a different plan is never searched under this message.
        const run = await api.startRun(researchId, 'discovery', crypto.randomUUID(), current.scope_revision)
        onAnnounced(run.id)
        toast('success', saved ? t('Plan saved as revision {n} of the question. The search started.', { n: run.scope_revision })
          : t('The search started with the plan saved for revision {n}.', { n: run.scope_revision }))
        onClose()
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) await reread(true)
        toast(saved ? 'warning' : 'error', saved ? t('Plan saved as revision {n} of the question. The search did not start: {error}', { n: current.scope_revision, error: errorText(e) })
          : t('The search did not start: {error}', { error: errorText(e) }))
      }
    } finally {
      setSaving(false); savingRef.current = false
      await onChanged()
    }
  }
  const cancel = () => { if (loaded?.plan) setDraft(draftOf(loaded.plan)); setRefused(null); onClose() }

  if (loadError && !loaded) return <div className="plan-panel mk pad"><p role="alert">{t('Could not load the search plan: {error}', { error: loadError })}</p></div>
  if (!loaded) return <div className="plan-panel mk pad"><p role="status">{t('Loading the search plan…')}</p></div>

  const plan = loaded.plan
  const nextRevision = loaded.scope_revision + 1
  const from = loaded.based_on?.scope_revision
  const origin = !plan ? t('No search of this question has frozen a plan yet; it shows here once the first search has planned.')
    : loaded.origin === 'model' ? t('The fast path wrote this plan from your question and ran it without asking.')
    : loaded.origin === 'code' ? t('Code built this plan from the question’s words and ran it without asking.')
    : t('This plan was saved by you.')
  // A frozen protocol says the plan was fixed for a search, not that its requests were sent or answered: the sentence says
  // frozen, and the plan step's lines say what the search did.
  const where = !plan ? '' : own ? t(loaded.queries_preview ? 'Saved for revision {n}; no search has frozen it yet.' : 'Saved for revision {n} and frozen by its search.', { n: loaded.scope_revision })
    : from === loaded.scope_revision ? t('Plan frozen for revision {n}.', { n: from })
    : t('Plan frozen for revision {b}; revision {n} has not frozen a plan yet.', { b: from ?? '?', n: loaded.scope_revision })
  const change = plan ? (answerRevision !== null
    ? t('Change anything and search again: saving makes revision {n}; the current answer stays with revision {a}.', { n: nextRevision, a: answerRevision })
    : t('Change anything and search again: saving makes revision {n}.', { n: nextRevision })) : ''
  const shownIssues = refused ?? (!dirty && loaded.issues.length ? loaded.issues : null)
  const draftPlan = plan && draft ? planOf(plan, draft) : null
  const wordsChanged = Boolean(plan && draft && (draft.setting.join('\n') !== plan.setting.map(r => r.term).join('\n') || draft.task.join('\n') !== plan.task.map(r => r.term).join('\n')))
  const backups = plan ? [...plan.setting_backup, ...plan.task_backup].map(row => row.term) : []
  const disabledReason = active ? t('Available when the run ends.') : !searchReady ? t('Choose a readable PDF to guide the search first.') : null
  const locked = saving || busy

  if (!loaded.editable) return <div className="plan-panel mk pad"><p>{t('This research reads attached files only; it has no search plan.')}</p></div>

  return <div className="plan-panel mk pad">
    <p>{[origin, where, change].filter(Boolean).join(' ')}</p>
    {loadError && <div className="notice bad plan-refresh" role="alert"><TriangleAlert aria-hidden /><div className="nb">
      <span>{t('Could not read the search plan again: {error}. The plan shown is the one last read; your draft is kept.', { error: loadError })}</span>
      <div className="acts"><button type="button" className="ghost" onClick={() => setRetry(n => n + 1)}>{t('Try again')}</button></div>
    </div></div>}
    {conflict && <div className="notice warn" role="alert"><TriangleAlert aria-hidden /><div className="nb">
      <span>{conflict.scope_revision !== loaded.scope_revision
        ? t('Revision {n} of this research was saved while you edited, in another window or by choosing PDFs. Your draft is kept.', { n: conflict.scope_revision })
        : t('The stored plan of revision {n} changed while you edited: a search of it froze a new plan. Your draft is kept.', { n: conflict.scope_revision })}</span>
      <div className="acts"><button type="button" className="ghost" onClick={rebase}>{t('Base my draft on revision {n}', { n: conflict.scope_revision })}</button>
        <button type="button" className="ghost" onClick={discard}>{t('Show the plan of revision {n}', { n: conflict.scope_revision })}</button></div>
    </div></div>}
    {shownIssues && <div className="notice warn plan-issues" role={refused ? 'alert' : undefined}><TriangleAlert aria-hidden /><div className="nb">
      <span><b>{t(refused ? 'Not saved. The plan breaks these rules:' : 'This plan breaks a rule, so it cannot be saved until you change it:')}</b></span>
      <ul>{shownIssues.map((issue, i) => <li key={i}>{issueText(issue, draftPlan ?? plan)}</li>)}</ul>
    </div></div>}
    {plan && draft && <>
      <div className="lbl">{t('Search words')}
        {BLOCKS.map(name => <div key={name} className="kw" data-block={name}>
          <small>{t(BLOCK_LABELS[name])}</small>
          {draft[name].map((term, i) => <span key={`${i}-${term}`}>{term}<button type="button" aria-label={t('Remove {word}', { word: term })} disabled={locked} onClick={() => removeWord(name, i)}><X aria-hidden /></button></span>)}
          {!draft[name].length && <em>{t('no word')}</em>}
        </div>)}
        {backups.length > 0 && <small className="plan-backups">{t('Backup words, used in order when a word finds no record on OpenAlex: {words}', { words: backups.join(', ') })}</small>}
      </div>
      <div className="plan-add">
        <label className="lbl">{t('Add a word')}<input ref={addField} className="field" value={word} disabled={locked} maxLength={80} placeholder={t('e.g. acoustic, disjoint paths · press Enter')}
          onChange={e => setWord(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); addWord() } }} /></label>
        <label className="lbl">{t('Add to')}<select className="field" value={block} disabled={locked} onChange={e => setBlock(e.target.value as Block)}>
          {BLOCKS.map(name => <option key={name} value={name}>{t(BLOCK_LABELS[name])}</option>)}
        </select></label>
      </div>
      {loaded.queries.map(query => <label key={query.label} className="lbl">{t('Query {n}', { n: query.label.replace(/^Query /, '') })}{' · '}{t(query.origin === 'model' ? 'model' : query.origin === 'user' ? 'your plan' : 'from the question’s words')}
        <textarea className="field mono" rows={2} readOnly value={query.query_text} /></label>)}
      {/* The English sentence the semantic search sends for this question revision (§2.2), as stored; read only here. */}
      {view.semantic?.english_question?.text && <div className="lbl plan-english">{t('English question for the semantic search')}<span>{view.semantic.english_question.text}</span></div>}
      <p className="plan-note">{[
        loaded.queries_preview && t('A preview: the query is compiled again from the words when the search starts, and a backup word takes the place of a word OpenAlex counts at zero.'),
        wordsChanged && t('The queries above are the stored ones; the edited words are compiled into a new query when the search starts.'),
        !own && t('Saved, the plan is searched with its own words only: the query built from the question’s words is not searched beside it.'),
      ].filter(Boolean).join(' ')}</p>
      {plan.criterion
        ? <label className="lbl">{t('Inclusion criterion')}<textarea className="field" rows={2} maxLength={600} value={draft.criterion ?? ''} disabled={locked} onChange={e => { const text = e.target.value; changeDraft(current => ({ ...current, criterion: text })) }} />
          <small>{t('Its parts and their phrases stay as stored: {parts}.', { parts: plan.criterion.parts.map(part => part.name).join(', ') })}</small></label>
        : <div className="lbl">{t('Inclusion criterion')}<small>{t('This plan has no inclusion criterion, and this panel cannot add one.')}</small></div>}
      <fieldset className="lbl" disabled={locked}><legend>{t('Sources')}</legend><div className="provs">
        {loaded.providers.map(provider => {
          const usable = provider.in_scope && provider.configured
          const checked = provider.required || draft.providers.includes(provider.provider_id)
          // A source that cannot run is never ticked here; one ticked before it stopped being usable can still be unticked.
          const disabled = provider.required || (!usable && !checked)
          const note = provider.required ? t('semantic and keyword · required: the search and the citation chain run on OpenAlex')
            : !provider.in_scope ? t('not among this research’s sources')
            : !provider.configured ? t('not set up · needs a key in Settings')
            : provider.provider_id === 'semantic_scholar' ? t('abstracts, and one bulk query at Detailed depth')
            : provider.provider_id === 'scopus' ? t('abstracts, once its full view is confirmed')
            : t('abstracts')
          return <label key={provider.provider_id}><input type="checkbox" checked={checked} disabled={disabled} onChange={e => toggleProvider(provider.provider_id, e.target.checked)} />
            <span>{providerName(provider.provider_id)}</span> <small>{note}</small></label>
        })}
      </div>
        {loaded.providers.some(provider => provider.not_covered.includes('pdf_link_lookup')) && <small className="plan-crossref"><Info aria-hidden />{t('Crossref is still asked for PDF links when full text is fetched, even when it is unticked here.')}</small>}
      </fieldset>
    </>}
    {seeds && <div className="lbl plan-seeds">{t('PDFs guiding the search')}
      {own && <small>{t('Choosing other PDFs saves a new revision without the plan saved for revision {n}.', { n: loaded.scope_revision })}</small>}
      {seeds}</div>}
    {plan && draft && <div className="rowbtns">
      {disabledReason && <small className="plan-wait">{disabledReason}</small>}
      <button type="button" className="ghost" disabled={saving} onClick={cancel}>{t('Cancel')}</button>
      <button type="button" className="btn-teal" disabled={locked || Boolean(conflict) || Boolean(disabledReason)} aria-busy={saving || undefined} onClick={() => { void search() }}><Search aria-hidden />{t('Search again with this plan')}</button>
    </div>}
  </div>
}
