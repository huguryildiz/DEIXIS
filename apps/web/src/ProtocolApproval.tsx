import { useState } from 'react'
import { ChevronDown, ChevronRight, CornerUpLeft, Plus, RotateCcw, X } from 'lucide-react'
import { ApiError, api, type ApprovalBlock, type ApprovalCriterion, type ApprovalSide, type ApprovalSuggestions, type ApprovalTerm, type ProtocolEdits, type Run, type RunApproval, type SearchQuerySide, type SuggestedTerm, type TermEdit } from './api'
import { approvedByText, blockLabels, blockNotes, blockOriginText, dropReasonText, pauseReasonText, providerName, queryWarningText, suggestionBlockerText, termKindText, termOriginText } from './labels'
import { t, uiLocale } from './i18n'
import { Notice } from './Notice'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

// The protocol approval of an sw discovery run (D80): what this run would search with, what it would include, and
// the user's correction of both before anything is frozen or sent.
//
// The card shows recorded backend state only. A run waiting for an approval never looks successful, a correction
// being checked locks the card, and "approved" appears when the view says so and not when the request returned.
// Draft corrections live in this component alone: they are not evidence and must not become a second source of
// truth beside the stored proposal, so a page reload drops them (slice 08b).

const BLOCKS: ApprovalBlock[] = ['setting', 'task', 'outcome', 'claim', 'exclusion']
const MAX_PARTS = 5
const MIN_PARTS = 2

// The same phrase shape the backend compares with: lower case, single spaces, no punctuation at either end.
const norm = (text: string) => text.toLowerCase().split(/\s+/).filter(Boolean).join(' ').replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '')

type Row = { phrase: string; block: ApprovalBlock; term: ApprovalTerm | null }
type CriterionDraft = {
  criterion: string; parts: { name: string; definition: string }[]
  cue_phrases: { phrase: string; part: string | null }[]; exclusion_title_words: string[]
}

// Every phrase of one side of the approval with the block it sits in. A term of a searched block carries its counts;
// a phrase of a side list has none of its own, because no query was ever counted for it.
function rowsOf(side: ApprovalSide): Row[] {
  return [
    ...side.terms.map(term => ({ phrase: term.phrase, block: term.block, term })),
    ...side.outcome_terms.map(phrase => ({ phrase, block: 'outcome' as ApprovalBlock, term: null })),
    ...side.claim_words.map(phrase => ({ phrase, block: 'claim' as ApprovalBlock, term: null })),
    ...side.exclusion_words.map(phrase => ({ phrase, block: 'exclusion' as ApprovalBlock, term: null })),
  ]
}

const draftOf = (criterion: ApprovalCriterion | null): CriterionDraft => ({
  criterion: criterion?.criterion ?? '',
  parts: criterion?.parts.map(part => ({ ...part })) ?? [{ name: '', definition: '' }, { name: '', definition: '' }],
  cue_phrases: criterion?.cue_phrases.map(cue => ({ phrase: cue.phrase, part: cue.part })) ?? [],
  exclusion_title_words: [...(criterion?.exclusion_title_words ?? [])],
})

export function ProtocolApproval({ run, approval, onApproved }: {
  run: Run; approval: RunApproval; onApproved: () => void | Promise<void>
}) {
  // A correction that emptied the vocabulary comes back paused with the submission still stored: the card opens
  // again so the user can send another one. It is locked only while the run is actually applying a submission.
  const checking = approval.status === 'submitted' && run.status !== 'paused'
  // The run is asking a model for other names. The card locks exactly as it does for a submission, and the draft
  // corrections stay in `PendingCard`: the component is not unmounted, only made read-only.
  const working = approval.suggestions.status === 'requested'
  const editable = approval.status !== 'approved' && !checking && !working
  if (approval.status === 'approved') return <ApprovedSummary approval={approval} />
  return <PendingCard run={run} approval={approval} editable={editable} checking={checking} working={working}
    onApproved={onApproved} />
}

function PendingCard({ run, approval, editable, checking, working, onApproved }: {
  run: Run; approval: RunApproval; editable: boolean; checking: boolean; working: boolean
  onApproved: () => void | Promise<void>
}) {
  const proposal = approval.proposal
  const [ops, setOps] = useState<TermEdit[]>([])
  const [criterion, setCriterion] = useState<CriterionDraft | null>(null)
  const [note, setNote] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [addError, setAddError] = useState<{ block: ApprovalBlock; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  // The code's query beside a model-written one (D92): null keeps the proposal's choice, a boolean is the user's.
  const [codeQuery, setCodeQuery] = useState<boolean | null>(null)
  const written = proposal.search_query?.status === 'ready' ? proposal.search_query : null
  const codeOn = written ? (codeQuery ?? written.code_query.searched) : false
  const codeChanged = written !== null && codeQuery !== null && codeQuery !== written.code_query.searched

  const rows = rowsOf(proposal)
  const known = new Set(rows.map(row => norm(row.phrase)))
  const opOf = (phrase: string) => ops.find(op => op.phrase === norm(phrase))
  const without = (phrase: string) => ops.filter(op => op.phrase !== norm(phrase))
  const setOp = (phrase: string, op: TermEdit | null) => setOps(op ? [...without(phrase), op] : without(phrase))

  const shown = (block: ApprovalBlock) => rows.filter(row => {
    const op = opOf(row.phrase)
    return op?.op === 'move' ? op.block === block : row.block === block
  })
  const added = (block: ApprovalBlock) => ops.filter(op => op.op === 'add' && op.block === block)

  // The names the model proposed on this card, by phrase. A draft `add` of one of them shows the count that was
  // already read and the `model` origin the server will derive; the correction itself says nothing about origin.
  const suggested = new Map(approval.suggestions.terms.map(row => [row.phrase, row]))

  const moved = ops.filter(op => op.op === 'move').length
  const removed = ops.filter(op => op.op === 'remove').length
  const addedCount = ops.filter(op => op.op === 'add').length
  const addedProposals = ops.filter(op => op.op === 'add' && suggested.has(op.phrase)).length
  const criterionEdited = criterion !== null
  const changed = ops.length > 0 || criterionEdited || codeChanged

  function addTerm(block: ApprovalBlock, text: string) {
    const phrase = norm(text)
    if (!phrase) return
    if (known.has(phrase) || ops.some(op => op.phrase === phrase)) {
      setAddError({ block, text: t('“{phrase}” is already in the search terms.', { phrase }) })
      return
    }
    setAddError(null)
    setOps([...ops, { op: 'add', phrase, block }])
  }

  function undoAll() {
    setOps([])
    setCriterion(null)
    setCodeQuery(null)
    setNote('')
    setErrors([])
    setAddError(null)
  }

  async function ask() {
    setBusy(true)
    setErrors([])
    try {
      // The route only records the request; the run asks the model and counts every proposal in the worker.
      await api.suggestTerms(run.id)
      await onApproved()
    } catch (e) {
      setErrors([e instanceof Error ? e.message : String(e)])
    } finally { setBusy(false) }
  }

  async function submit() {
    setBusy(true)
    setErrors([])
    const edits: ProtocolEdits = {
      terms: ops,
      criterion: criterion && {
        criterion: criterion.criterion, parts: criterion.parts,
        cue_phrases: criterion.cue_phrases, exclusion_title_words: criterion.exclusion_title_words,
      },
      note: note.trim() || null,
      ...(codeChanged ? { code_query: codeQuery } : {}),
    }
    try {
      await api.approveProtocol(run.id, edits)
      await onApproved()
    } catch (e) {
      // The draft is kept: a refused correction is refused whole, and retyping it would be the user's second cost.
      setErrors(e instanceof ApiError && e.errors.length ? e.errors : [e instanceof Error ? e.message : String(e)])
    } finally { setBusy(false) }
  }

  // A fault that names a phrase belongs beside that phrase's row; what names none closes the card.
  const errorsFor = (phrase: string) => errors.filter(error => error.includes(`'${norm(phrase)}'`))
  const placed = new Set(rows.map(row => row.phrase).concat(ops.map(op => op.phrase)).flatMap(errorsFor))
  const generalErrors = errors.filter(error => !placed.has(error))

  const criterionNow = criterion ?? draftOf(proposal.criterion)
  const editCriterion = (change: Partial<CriterionDraft>) => setCriterion({ ...criterionNow, ...change })

  return <section className="approval-card" aria-labelledby={`approval-${run.id}`}>
    {/* A div, not a <header>: the shell's bare `header` rule fixes a height and a flex row on every one of them. */}
    <div className="approval-head">
      <h3 id={`approval-${run.id}`}>{t('Before searching: the search terms and the inclusion criterion')}</h3>
      <p>{t('Nothing has been sent to a provider yet, except counts of how many records hold each term. Correct what is wrong, then approve.')}</p>
    </div>

    {written && <Notice tone="info">{t('A model wrote these search terms from the question. The counts, the backups and the warnings are the application’s own checks; the query built from the question’s words is offered below.')}</Notice>}
    {proposal.search_query?.status === 'failed' && <Notice tone="attention">{t('The model could not write the search query. You chose the query DEIXIS built from the question’s words.')}</Notice>}
    {proposal.too_broad && <Notice tone="attention">{t('Every term that would be searched is too frequent to stand alone. You can still approve; the run will stop again and say so.')}</Notice>}
    {!proposal.terms.some(term => !term.dropped) && <Notice tone="attention">{t('No term is left to build a provider query from. Add one below, or move one back into the setting or task block.')}</Notice>}

    <div className="approval-blocks">
      {BLOCKS.map(block => <div key={block} className="approval-block">
        <div className="approval-block-head">
          <strong>{t(blockLabels[block])}</strong>
          <small>{t(blockNotes[block])}</small>
        </div>
        <ul className="approval-terms">
          {shown(block).map(row => {
            const op = opOf(row.phrase)
            const rowErrors = errorsFor(row.phrase)
            return <li key={`${row.block}:${row.phrase}`} className={`approval-term${op?.op === 'remove' ? ' is-removed' : ''}${row.term?.dropped ? ' is-dropped' : ''}`}>
              <div className="approval-term-main">
                <span className="approval-phrase" dir="auto">{row.phrase}</span>
                <span className="approval-term-facts">
                  <TermFacts term={row.term} block={row.block} />
                  {row.term && written && <WrittenFacts side={written} phrase={row.phrase} />}
                  {/* The view records an origin only for the two searched blocks; a side-list phrase claims none. */}
                  {row.term && <span className="approval-badge">{termOriginText(row.term.origin)}</span>}
                  {(row.term || op?.op === 'move') && <span className="approval-badge">{blockOriginText(op?.op === 'move' ? 'user' : row.term!.block_origin)}</span>}
                  {op?.op === 'move' && <span className="approval-badge is-changed">{t('moved by you')}</span>}
                  {op?.op === 'remove' && <span className="approval-badge is-changed">{t('removed by you')}</span>}
                </span>
              </div>
              {editable && <div className="approval-term-actions">
                {op ? <Button variant="ghost" size="sm" onClick={() => setOp(row.phrase, null)}><CornerUpLeft size={13} />{t('Undo')}</Button> : <>
                  <Select value={block} onValueChange={value => setOp(row.phrase, String(value) === row.block ? null : { op: 'move', phrase: norm(row.phrase), block: String(value) as ApprovalBlock })}>
                    <SelectTrigger size="sm" aria-label={t('Block of “{phrase}”', { phrase: row.phrase })}>
                      <SelectValue>{value => t(blockLabels[value as ApprovalBlock])}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>{BLOCKS.map(target => <SelectItem key={target} value={target}>{t(blockLabels[target])}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button variant="ghost" size="sm" onClick={() => setOp(row.phrase, { op: 'remove', phrase: norm(row.phrase) })}><X size={13} />{t('Remove')}</Button>
                </>}
              </div>}
              {rowErrors.length > 0 && <p className="approval-row-error">{rowErrors.join(' ')}</p>}
            </li>
          })}
          {added(block).map(op => <li key={`add:${op.phrase}`} className="approval-term is-added">
            <div className="approval-term-main">
              <span className="approval-phrase" dir="auto">{op.phrase}</span>
              <span className="approval-term-facts">
                {/* A proposal the model made was already counted; a phrase the user typed is counted on approval. */}
                <span className="approval-count">{suggested.has(op.phrase)
                  ? <Records count={suggested.get(op.phrase)!.phrase_count} />
                  : t('will be counted after approval')}</span>
                <span className="approval-badge">{termOriginText(suggested.has(op.phrase) ? 'model' : 'user')}</span>
                <span className="approval-badge">{blockOriginText('user')}</span>
              </span>
            </div>
            {editable && <div className="approval-term-actions">
              <Button variant="ghost" size="sm" onClick={() => setOp(op.phrase, null)}><CornerUpLeft size={13} />{t('Undo')}</Button>
            </div>}
            {errorsFor(op.phrase).length > 0 && <p className="approval-row-error">{errorsFor(op.phrase).join(' ')}</p>}
          </li>)}
          {!shown(block).length && !added(block).length && <li className="approval-term is-empty"><span>{t('No term.')}</span></li>}
        </ul>
        {editable && <AddTerm block={block} onAdd={text => addTerm(block, text)} error={addError?.block === block ? addError.text : null} />}
      </div>)}
    </div>

    {written && <QuerySection side={written} queries={proposal.queries ?? []} on={codeOn} editable={editable}
      onChange={on => setCodeQuery(on === written.code_query.searched ? null : on)} />}

    <SuggestionSection suggestions={approval.suggestions} editable={editable} working={working} busy={busy}
      drafted={new Set(ops.filter(op => op.op === 'add').map(op => op.phrase))}
      onAdd={row => setOps([...without(row.phrase), { op: 'add', phrase: row.phrase, block: row.block }])}
      onUndo={phrase => setOp(phrase, null)} onAsk={() => void ask()} />

    <CriterionSection criterion={proposal.criterion} available={proposal.criterion_available}
      sought={proposal.sought_term_in_criterion} draft={criterion} now={criterionNow} editable={editable}
      onEdit={editCriterion} onWriteOwn={() => setCriterion(draftOf(null))} onUndo={() => setCriterion(null)} />

    <div className="approval-foot">
      {editable && <label className="approval-note">
        <span>{t('Note for the record (optional)')}</span>
        <Textarea value={note} onChange={e => setNote(e.target.value)} rows={2} maxLength={1000}
          placeholder={t('Why you corrected this. It is kept with the protocol.')} />
      </label>}
      <p className="approval-summary" role="status">{changed
        ? [removed && t(removed === 1 ? '{n} term removed' : '{n} terms removed', { n: removed }),
           addedCount && t(addedCount === 1 ? '{n} term added' : '{n} terms added', { n: addedCount }),
           // Counted apart: how many of the added terms are names the model proposed.
           addedProposals && t(addedProposals === 1 ? '{n} of them proposed by the model' : '{n} of them proposed by the model', { n: addedProposals }),
           moved && t(moved === 1 ? '{n} term moved' : '{n} terms moved', { n: moved }),
           codeChanged && t(codeOn ? 'the code’s query switched on' : 'the code’s query switched off'),
           criterionEdited && t('criterion corrected')].filter(Boolean).join(' · ')
        : t('No change: the proposal is approved as it stands.')}</p>
      {checking && <p className="approval-checking" role="status">{t('Your correction was sent. The terms you added are being counted against the literature; this card opens again if they cannot be searched.')}</p>}
      {working && <p className="approval-checking" role="status">{t('The model is proposing other names and each one is being counted. Your draft corrections are kept.')}</p>}
      {/* Announced whenever anything was refused, so a fault shown only beside its row is still spoken once. */}
      {errors.length > 0 && <div className="approval-errors" role="alert">
        <p>{t('The correction was not applied. Nothing was sent to a provider.')}</p>
        {generalErrors.length > 0 && <ul>{generalErrors.map(error => <li key={error}>{error}</li>)}</ul>}
      </div>}
      {editable && <div className="approval-actions">
        <Button variant="default" disabled={busy} onClick={() => void submit()}>{t('Approve and search')}</Button>
        <Button variant="ghost" disabled={busy || !changed} onClick={undoAll}>{t('Undo changes')}</Button>
      </div>}
    </div>
  </section>
}

// What the literature holds for a term, and the form it enters the query in. A count that was not read says so;
// it is never shown as 0, which would mean the opposite.
function TermFacts({ term, block }: { term: ApprovalTerm | null; block: ApprovalBlock }) {
  if (!term) return <span className="approval-count">{block === 'outcome' ? t('not searched; orders the records') : t('not searched')}</span>
  const count = term.in_query === 'root' ? term.root_count : term.phrase_count
  return <>
    <span className="approval-count">{count === null ? t('not counted')
      : t('{n} records', { n: count.toLocaleString(uiLocale()) })}</span>
    <span className="approval-badge">{term.in_query === 'root' ? t('enters as the word “{root}”', { root: term.root }) : t('enters as the whole phrase')}</span>
    {term.and_only && <span className="approval-badge">{t('too frequent alone; only combined')}</span>}
    {term.dropped && <span className="approval-badge is-dropped">{t('dropped: {reason}', { reason: dropReasonText(term.dropped) })}</span>}
  </>
}

// What the model said about one of its terms, and what code found when it counted the term with the other block
// (D92). The kind and the reason are the model's words and decide nothing; a warning is code's and removes nothing.
function WrittenFacts({ side, phrase }: { side: Extract<SearchQuerySide, { status: 'ready' }>; phrase: string }) {
  const meta = side.terms.find(term => term.phrase === phrase)
  const warnings = side.warnings.filter(warning => warning.phrase === phrase)
  if (!meta && !warnings.length) return null
  return <>
    {meta?.kind && <span className="approval-badge" title={meta.why ?? undefined}>{termKindText(meta.kind)}</span>}
    {meta?.backup_for && <span className="approval-badge">{t('backup for “{phrase}”', { phrase: meta.backup_for })}</span>}
    {meta?.with_other_block != null && <span className="approval-count">{t('{n} with the other block', { n: meta.with_other_block.toLocaleString(uiLocale()) })}</span>}
    {warnings.map(warning => <span key={warning.warning} className="approval-badge is-dropped">{queryWarningText(warning.warning)}</span>)}
    {meta?.why && <span className="approval-why" dir="auto">{meta.why}</span>}
  </>
}

// The queries the run would send: the model's, and beside it the query code built from the question's words, which
// the user may switch off (D92). The code's terms are shown, not edited.
function QuerySection({ side, queries, on, editable, onChange }: {
  side: Extract<SearchQuerySide, { status: 'ready' }>; queries: { provider_id: string; query_text: string; origin?: string }[]
  on: boolean; editable: boolean; onChange: (on: boolean) => void
}) {
  const code = side.code_query
  const byOrigin = (origin: string) => queries.filter(query => query.origin === origin)
  // With the switch on as proposed, only the code queries the request limit left are sent, so only those are listed.
  const compiled = on && code.searched
  const codeQueries = compiled ? byOrigin('code') : code.queries
  return <div className="approval-queries">
    <div className="approval-block-head">
      <strong>{t('Queries')}</strong>
      <small>{t('Each provider is searched with the model’s query and, when it is switched on, the query built from the question’s words.')}</small>
    </div>
    <div className="approval-query-group">
      <span className="approval-field-label">{t('The model’s query')}</span>
      <ul>{byOrigin('model').map(query => <li key={`model:${query.provider_id}`}><small>{providerName(query.provider_id)}</small> <code>{query.query_text}</code></li>)}</ul>
    </div>
    <div className={`approval-query-group${on ? '' : ' is-off'}`}>
      <label className="approval-switch">
        <input type="checkbox" checked={on} disabled={!editable || !code.available} onChange={e => onChange(e.target.checked)} />
        <span>{t('Also search with the query built from the question’s words')}</span>
      </label>
      {!code.available && <p className="approval-hint">{t('That query cannot be searched on its own: none was compiled, or every term was too frequent.')}</p>}
      <p className="approval-hint">{t('Its terms: {terms}', { terms: code.terms.map(term => `${term.form} (${t(blockLabels[term.block])})`).join(', ') || t('none') })}</p>
      {compiled && !codeQueries.length && <p className="approval-hint">{t('This search’s request limit leaves no room for it: only the model’s queries are sent.')}</p>}
      <ul>{codeQueries.map(query => <li key={`code:${query.provider_id}`}><small>{providerName(query.provider_id)}</small> <code>{query.query_text}</code></li>)}</ul>
    </div>
  </div>
}

// How many records hold a phrase. A count that was not read says so; it is never shown as 0, which would mean the
// opposite, and a count is never called a verification: it says the name exists in the literature, nothing more.
function Records({ count }: { count: number | null }) {
  return <>{count === null ? t('not counted')
    : t('{n} records hold this name', { n: count.toLocaleString(uiLocale()) })}</>
}

// Other names the user asked a model for (D82). Nothing here is in the search: a row enters the draft only when
// the user adds it, and a row code dropped cannot be added at all.
function SuggestionSection({ suggestions, editable, working, busy, drafted, onAdd, onUndo, onAsk }: {
  suggestions: ApprovalSuggestions; editable: boolean; working: boolean; busy: boolean
  drafted: Set<string>; onAdd: (row: SuggestedTerm) => void; onUndo: (phrase: string) => void; onAsk: () => void
}) {
  const open = suggestions.terms.filter(row => !drafted.has(row.phrase))
  return <div className="approval-block">
    <div className="approval-block-head">
      <strong>{t('Other names for these terms')}</strong>
      <small>{t('A model can propose names the literature uses for the same things. Nothing it proposes is searched unless you add it.')}</small>
    </div>

    {suggestions.status === 'ready' && <ul className="approval-terms" aria-live="polite">
      {open.map(row => <li key={`${row.synonym_of}:${row.phrase}`}
        className={`approval-term${row.dropped ? ' is-dropped' : ''}`}>
        <div className="approval-term-main">
          <span className="approval-phrase" dir="auto">{row.phrase}</span>
          <span className="approval-term-facts">
            <span className="approval-count">{t('another name for “{anchor}”', { anchor: row.synonym_of })}</span>
            {!row.dropped && <span className="approval-count"><Records count={row.phrase_count} /></span>}
            <span className="approval-badge">{termOriginText('model')}</span>
            <span className="approval-badge">{t('would enter the {block} block', { block: t(blockLabels[row.block]) })}</span>
            {row.dropped && <span className="approval-badge is-dropped">{t('cannot be added: {reason}', { reason: dropReasonText(row.dropped) })}</span>}
          </span>
        </div>
        {editable && !row.dropped && <div className="approval-term-actions">
          <Button variant="outline" size="sm" onClick={() => onAdd(row)}><Plus size={13} />{t('Add')}</Button>
        </div>}
      </li>)}
      {suggestions.terms.filter(row => drafted.has(row.phrase)).map(row =>
        <li key={`drafted:${row.phrase}`} className="approval-term">
          <div className="approval-term-main">
            <span className="approval-phrase" dir="auto">{row.phrase}</span>
            <span className="approval-term-facts">
              <span className="approval-count">{t('added to the {block} block above', { block: t(blockLabels[row.block]) })}</span>
              <span className="approval-badge is-changed">{t('added by you')}</span>
            </span>
          </div>
          {editable && <div className="approval-term-actions">
            <Button variant="ghost" size="sm" onClick={() => onUndo(row.phrase)}><CornerUpLeft size={13} />{t('Undo')}</Button>
          </div>}
        </li>)}
      {!suggestions.terms.length && <li className="approval-term is-empty"><span>{t('The model proposed no new name.')}</span></li>}
    </ul>}

    {suggestions.carried && suggestions.status === 'ready'
      && <p className="approval-hint">{t('These are the proposals from when this question was asked before; the model was not asked again.')}</p>}

    {suggestions.status === 'failed' && <>
      <p className="approval-hint" role="status">{pauseReasonText(suggestions.failure)}</p>
      {editable && suggestions.available && <div className="approval-actions">
        <Button variant="outline" size="sm" disabled={busy} onClick={onAsk}><RotateCcw size={13} />{t('Try again')}</Button>
      </div>}
      {!suggestions.available && suggestions.unavailable_reason
        && <p className="approval-hint">{suggestionBlockerText(suggestions.unavailable_reason)}</p>}
    </>}

    {/* Only one way in at a time: the retry above belongs to a failed request, the button below to a card that has
        not asked yet, and a card waiting for the worker offers neither. */}
    {(suggestions.status === 'requested' || working)
      && <p className="approval-hint" role="status">{t('The model is proposing other names; each one is being counted.')}</p>}
    {suggestions.status === 'none' && (suggestions.available
      ? editable && <div className="approval-actions">
          <Button variant="outline" size="sm" disabled={busy} onClick={onAsk}>{t('Ask the model for other names')}</Button>
          <span className="approval-hint">{t('One request per question. Each proposal is counted against the literature, and none enters the search unless you add it.')}</span>
        </div>
      : suggestions.unavailable_reason
        ? <p className="approval-hint">{suggestionBlockerText(suggestions.unavailable_reason)}</p>
        : null)}
  </div>
}

function AddTerm({ block, onAdd, error }: { block: ApprovalBlock; onAdd: (text: string) => void; error: string | null }) {
  const [text, setText] = useState('')
  const id = `approval-add-${block}`
  return <form className="approval-add" onSubmit={e => { e.preventDefault(); onAdd(text); setText('') }}>
    <label htmlFor={id}>{t('Add a term to {block}', { block: t(blockLabels[block]) })}</label>
    <div>
      <input id={id} value={text} onChange={e => setText(e.target.value)} maxLength={80} dir="auto" />
      <Button type="submit" variant="outline" size="sm" disabled={!text.trim()}><Plus size={13} />{t('Add')}</Button>
    </div>
    {error && <p className="approval-row-error" role="alert">{error}</p>}
  </form>
}

function CriterionSection({ criterion, available, sought, draft, now, editable, onEdit, onWriteOwn, onUndo }: {
  criterion: ApprovalCriterion | null; available: boolean; sought: boolean | null
  draft: CriterionDraft | null; now: CriterionDraft; editable: boolean
  onEdit: (change: Partial<CriterionDraft>) => void; onWriteOwn: () => void; onUndo: () => void
}) {
  const parts = now.parts
  const grouped = [...parts.map(part => ({ name: part.name, cues: now.cue_phrases.filter(cue => cue.part === part.name) })),
    { name: null, cues: now.cue_phrases.filter(cue => cue.part === null || !parts.some(part => part.name === cue.part)) }]
  const setCue = (index: number, change: Partial<{ phrase: string; part: string | null }>) =>
    onEdit({ cue_phrases: now.cue_phrases.map((cue, i) => (i === index ? { ...cue, ...change } : cue)) })

  return <div className="approval-criterion">
    <div className="approval-block-head">
      <strong>{t('Inclusion criterion')}</strong>
      <small>{t('Read at the full-text stage. In this version it orders nothing and decides nothing on its own.')}</small>
    </div>
    {!available && draft === null && <div className="approval-criterion-empty">
      <Notice tone="attention">{t('No criterion was proposed: the model was not reachable while this run worked. You can go on without one, or write one yourself.')}</Notice>
      {editable && <div className="approval-actions">
        <Button variant="outline" size="sm" onClick={onWriteOwn}>{t('Write a criterion')}</Button>
        <span className="approval-hint">{t('Approving without one searches with the terms above and records no criterion.')}</span>
      </div>}
    </div>}
    {(available || draft !== null) && <>
      {sought === false && <Notice tone="attention">{t('What the question looks for is not named in the criterion. Check that the criterion includes the right records.')}</Notice>}
      <label className="approval-field">
        <span>{t('Criterion')}</span>
        {editable ? <Textarea value={now.criterion} maxLength={600} rows={2} onChange={e => onEdit({ criterion: e.target.value })} />
          : <p className="approval-readonly">{now.criterion}</p>}
      </label>
      <div className="approval-parts">
        <span className="approval-field-label">{t('Parts ({min}–{max})', { min: MIN_PARTS, max: MAX_PARTS })}</span>
        {parts.map((part, i) => <div key={i} className="approval-part">
          {editable ? <>
            <input aria-label={t('Part {n} name', { n: i + 1 })} value={part.name} maxLength={60}
              onChange={e => onEdit({ parts: parts.map((p, j) => (i === j ? { ...p, name: e.target.value } : p)) })} />
            {/* A definition is a sentence the user has to read before deciding; it is not cut to one line. */}
            <Textarea aria-label={t('Part {n} definition', { n: i + 1 })} value={part.definition} maxLength={400} rows={2}
              onChange={e => onEdit({ parts: parts.map((p, j) => (i === j ? { ...p, definition: e.target.value } : p)) })} />
            <Button variant="ghost" size="sm" disabled={parts.length <= MIN_PARTS}
              onClick={() => onEdit({ parts: parts.filter((_, j) => j !== i) })}><X size={13} />{t('Remove')}</Button>
          </> : <p className="approval-readonly"><b>{part.name}</b> — {part.definition}</p>}
        </div>)}
        {editable && <Button variant="outline" size="sm" disabled={parts.length >= MAX_PARTS}
          onClick={() => onEdit({ parts: [...parts, { name: '', definition: '' }] })}><Plus size={13} />{t('Add a part')}</Button>}
      </div>
      <div className="approval-cues">
        <span className="approval-field-label">{t('Phrases that show a part is met')}</span>
        {grouped.filter(group => group.cues.length || group.name !== null).map(group => <div key={group.name ?? '—'} className="approval-cue-group">
          <small>{group.name ?? t('Not tied to a part')}</small>
          <ul>
            {group.cues.map(cue => {
              const index = now.cue_phrases.indexOf(cue)
              return <li key={index}>
                <span dir="auto">{cue.phrase}</span>
                {editable && <>
                  <Select value={cue.part} onValueChange={value => setCue(index, { part: value === null ? null : String(value) })}>
                    <SelectTrigger size="sm" aria-label={t('Part of “{phrase}”', { phrase: cue.phrase })}>
                      <SelectValue>{value => (value === null ? t('Not tied to a part') : String(value))}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={null}>{t('Not tied to a part')}</SelectItem>
                      {parts.filter(part => part.name.trim()).map(part => <SelectItem key={part.name} value={part.name}>{part.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button variant="ghost" size="sm" onClick={() => onEdit({ cue_phrases: now.cue_phrases.filter((_, i) => i !== index) })}><X size={13} />{t('Remove')}</Button>
                </>}
              </li>
            })}
            {!group.cues.length && <li className="is-empty"><span>{t('No phrase.')}</span></li>}
          </ul>
          {editable && <AddCue label={group.name} onAdd={phrase => onEdit({ cue_phrases: [...now.cue_phrases, { phrase, part: group.name }] })} />}
        </div>)}
      </div>
      <WordList label={t('Title words of records that are not this kind of study (kept with the protocol; not used yet)')} words={now.exclusion_title_words} editable={editable}
        onChange={words => onEdit({ exclusion_title_words: words })} />
      {criterion?.dropped_exclusion_title_words?.length ? <p className="approval-hint">
        {t('Dropped as words of the question itself: {words}', { words: criterion.dropped_exclusion_title_words.join(', ') })}</p> : null}
      {editable && draft !== null && <Button variant="ghost" size="sm" onClick={onUndo}><CornerUpLeft size={13} />{t('Undo the criterion changes')}</Button>}
    </>}
  </div>
}

function AddCue({ label, onAdd }: { label: string | null; onAdd: (phrase: string) => void }) {
  const [text, setText] = useState('')
  return <form className="approval-add" onSubmit={e => { e.preventDefault(); if (text.trim()) { onAdd(norm(text)); setText('') } }}>
    <label htmlFor={`cue-${label ?? 'none'}`}>{t('Add a phrase')}</label>
    <div>
      <input id={`cue-${label ?? 'none'}`} value={text} onChange={e => setText(e.target.value)} maxLength={80} dir="auto" />
      <Button type="submit" variant="outline" size="sm" disabled={!text.trim()}><Plus size={13} />{t('Add')}</Button>
    </div>
  </form>
}

function WordList({ label, words, editable, onChange }: { label: string; words: string[]; editable: boolean; onChange: (words: string[]) => void }) {
  const [text, setText] = useState('')
  return <div className="approval-words">
    <span className="approval-field-label">{label}</span>
    <ul>
      {words.map((word, i) => <li key={`${word}:${i}`}>
        <span dir="auto">{word}</span>
        {editable && <Button variant="ghost" size="sm" onClick={() => onChange(words.filter((_, j) => j !== i))}><X size={13} />{t('Remove')}</Button>}
      </li>)}
      {!words.length && <li className="is-empty"><span>{t('No word.')}</span></li>}
    </ul>
    {editable && <form className="approval-add" onSubmit={e => { e.preventDefault(); if (text.trim()) { onChange([...words, norm(text)]); setText('') } }}>
      <label htmlFor="approval-exclusion-word">{t('Add a word')}</label>
      <div>
        <input id="approval-exclusion-word" value={text} onChange={e => setText(e.target.value)} maxLength={40} dir="auto" />
        <Button type="submit" variant="outline" size="sm" disabled={!text.trim()}><Plus size={13} />{t('Add')}</Button>
      </div>
    </form>}
  </div>
}

// Once the protocol is frozen the card folds to one line. Opened, it shows the proposal beside what was approved,
// so a later reader can see what the user changed — and what an earlier approval could not be applied to.
function ApprovedSummary({ approval }: { approval: RunApproval }) {
  const [open, setOpen] = useState(false)
  const approved = approval.approved
  const before = rowsOf(approval.proposal)
  const after = approved ? rowsOf(approved) : []
  const beforeAt = new Map(before.map(row => [norm(row.phrase), row.block]))
  const afterAt = new Map(after.map(row => [norm(row.phrase), row.block]))
  const gone = before.filter(row => !afterAt.has(norm(row.phrase)))
  const fresh = after.filter(row => !beforeAt.has(norm(row.phrase)))
  const movedRows = after.filter(row => beforeAt.has(norm(row.phrase)) && beforeAt.get(norm(row.phrase)) !== row.block)
  const criterionChanged = JSON.stringify(approval.proposal.criterion?.criterion ?? null) !== JSON.stringify(approved?.criterion?.criterion ?? null)
  // Proposals that are not in the approved vocabulary: the user left them, or code had dropped them.
  const notAdded = approval.suggestions.terms.filter(row => !afterAt.has(norm(row.phrase)))

  return <section className="approval-card is-approved">
    <button type="button" className="approval-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? <ChevronDown size={15} aria-hidden /> : <ChevronRight size={15} aria-hidden />}
      <span>{approvedByText(approval.approved_by)}</span>
      <small>{approval.edited ? t('corrected before searching') : t('approved as proposed')}</small>
    </button>
    {open && <div className="approval-diff">
      <DiffList title={t('Removed terms')} rows={gone} />
      {/* The badge says which of the added terms the model proposed and the user took (D82). */}
      <DiffList title={t('Added terms')} rows={fresh} origin />
      <DiffList title={t('Moved terms')} rows={movedRows} from={beforeAt} />
      {notAdded.length > 0 && <div className="approval-diff-group">
        <strong>{t('Proposed, not added')}</strong>
        <p className="approval-hint">{t('The model proposed these other names; they were not added, so nothing was searched for them.')}</p>
        <ul>{notAdded.map(row => <li key={`open:${row.phrase}`}>
          <span dir="auto">{row.phrase}</span>
          <small>{row.dropped ? t('dropped: {reason}', { reason: dropReasonText(row.dropped) })
            : t('another name for “{anchor}”', { anchor: row.synonym_of })}</small>
        </li>)}</ul>
      </div>}
      {criterionChanged && <div className="approval-diff-group">
        <strong>{t('Criterion')}</strong>
        <p className="approval-readonly"><small>{t('Proposed')}</small> {approval.proposal.criterion?.criterion ?? t('none')}</p>
        <p className="approval-readonly"><small>{t('Approved')}</small> {approved?.criterion?.criterion ?? t('none')}</p>
      </div>}
      {!gone.length && !fresh.length && !movedRows.length && !criterionChanged
        && <p className="approval-hint">{t('The proposal was approved without a change.')}</p>}
      {approval.skipped_edits.length > 0 && <div className="approval-diff-group">
        <strong>{t('Not applied to this run')}</strong>
        <p className="approval-hint">{t('These corrections named a phrase this run’s proposal no longer holds; they stay on record.')}</p>
        <ul>{approval.skipped_edits.map(edit => <li key={`${edit.op}:${edit.phrase}`}>{t('{op} “{phrase}”', { op: t(edit.op), phrase: edit.phrase })}</li>)}</ul>
      </div>}
      {approved?.queries?.length ? <div className="approval-diff-group">
        <strong>{t('Queries sent')}</strong>
        <ul>{approved.queries.map(query => <li key={`${query.provider_id}:${query.query_text}`}>
          {query.origin && <small>{t(query.origin === 'model' ? 'model' : 'from the question’s words')}</small>} <code>{query.query_text}</code></li>)}</ul>
      </div> : null}
    </div>}
  </section>
}

function DiffList({ title, rows, from, origin }: {
  title: string; rows: Row[]; from?: Map<string, ApprovalBlock>; origin?: boolean
}) {
  if (!rows.length) return null
  return <div className="approval-diff-group">
    <strong>{title}</strong>
    <ul>{rows.map(row => <li key={`${row.block}:${row.phrase}`}>
      <span dir="auto">{row.phrase}</span>
      <small>{from ? t('{before} → {after}', { before: t(blockLabels[from.get(norm(row.phrase))!]), after: t(blockLabels[row.block]) })
        : t(blockLabels[row.block])}</small>
      {origin && row.term && <span className="approval-badge">{termOriginText(row.term.origin)}</span>}
    </li>)}</ul>
  </div>
}
