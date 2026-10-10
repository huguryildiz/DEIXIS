import { Fragment, useState } from 'react'
import { ChevronDown, ChevronRight, CornerUpLeft, Plus, RotateCcw, TriangleAlert, X } from 'lucide-react'
import { ApiError, api, type ApprovalBlock, type ApprovalCriterion, type ApprovalSide, type ApprovalSuggestions, type ApprovalTerm, type CitationChaining, type ProtocolEdits, type Run, type RunApproval, type SearchQuerySide, type SourceRouting, type SuggestedTerm, type TermEdit } from './api'
import { approvedByText, blockLabels, blockNotes, blockOriginText, dropReasonText, pauseReasonText, providerName, queryWarningText, routeReasonText, suggestionBlockerText, termKindText, termOriginText } from './labels'
import { t, uiLocale } from './i18n'
import { Notice } from './Notice'
import { ModelName } from './ModelName'
import { useModelText, type ModelText } from './modelText'
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
//
// The main view is one sentence, the warnings about it, the criterion and one button. Everything else the card used
// to show sits behind "Change the words" (the two searched groups) and "Advanced" (the rest), so nothing is dropped.

const BLOCKS: ApprovalBlock[] = ['setting', 'task', 'outcome', 'claim', 'exclusion']
const SENTENCE_BLOCKS: ApprovalBlock[] = ['setting', 'task']
const SIDE_BLOCKS: ApprovalBlock[] = ['outcome', 'claim', 'exclusion']
const MAX_PARTS = 5
const MIN_PARTS = 2

// The two searched groups in plain words: the first must be mentioned, and so must one of the second.
const groupLabel = (block: ApprovalBlock) => t(block === 'setting' ? 'Must mention one of' : block === 'task' ? 'And one of' : blockLabels[block])

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

// One warning about a term that multiplies the matches, with the model's advice when it gave any (D232). The counts do not
// say whether the extra papers are wanted. The advice moves the filled button to the recommended choice and decides
// nothing: both buttons stay.
function WarningBox({ warning, model, modelText, locale, editable, onRemove, onKeep }: {
  warning: NonNullable<RunApproval['warnings']>[number]; model: RunApproval['advice_model'] | null
  modelText: ModelText; locale: string; editable: boolean; onRemove: () => void; onKeep: () => void
}) {
  const advice = warning.advice ?? null
  const keepAdvised = advice?.recommendation === 'keep'
  const title = t('“{phrase}” multiplies the matches', { phrase: warning.phrase })
  return <div className="approval-warning" role="group" aria-label={title}>
    <div className="approval-warning-head">
      <TriangleAlert size={20} aria-hidden />
      <div>
        <strong>{title}</strong>
        {!advice && <p>{t('With it the search matches many more papers. The numbers do not say whether those papers are wanted.')}</p>}
        {advice && <p className="approval-advice">
          {model && <><ModelName connection={model.connection} text={modelText(model.model)} />{' '}</>}
          <span dir="auto">{advice.recommendation === 'keep' ? t('suggests keeping it:') : t('suggests removing it:')} {advice.reason}</span>
        </p>}
      </div>
    </div>
    <div className="approval-stats">
      <div className="approval-stat"><b>{warning.matches.toLocaleString(locale)}</b><span>{t('papers with it')}</span></div>
      <div className="approval-stat is-better"><b>{warning.matches_without_term.toLocaleString(locale)}</b><span>{t('papers without it')}</span></div>
    </div>
    <div className="approval-warning-actions">
      <Button variant={keepAdvised ? 'outline' : 'default'} className="approval-btn" disabled={!editable} onClick={onRemove}>{t('Remove it')}</Button>
      <Button variant={keepAdvised ? 'default' : 'outline'} className="approval-btn" disabled={!editable} onClick={onKeep}>{t('Keep it')}</Button>
    </div>
  </div>
}

function PendingCard({ run, approval, editable, checking, working, onApproved }: {
  run: Run; approval: RunApproval; editable: boolean; checking: boolean; working: boolean
  onApproved: () => void | Promise<void>
}) {
  const proposal = approval.proposal
  const modelText = useModelText()
  const [ops, setOps] = useState<TermEdit[]>([])
  const [criterion, setCriterion] = useState<CriterionDraft | null>(null)
  const [note, setNote] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [addError, setAddError] = useState<{ block: ApprovalBlock; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [wordsOpen, setWordsOpen] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  // "Keep it": the warnings the user looked at and chose to leave. Only this approval hides them; nothing is stored.
  const [kept, setKept] = useState<Set<string>>(new Set())
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

  // The phrases the sentence names: what would be searched, after the draft. A dropped term is not searched.
  const sentenceOf = (block: ApprovalBlock) => [
    ...shown(block).filter(row => !row.term?.dropped && opOf(row.phrase)?.op !== 'remove').map(row => row.phrase),
    ...added(block).map(op => op.phrase),
  ]
  const [first, second] = [sentenceOf('setting'), sentenceOf('task')]
  const warnings = (approval.warnings ?? []).filter(warning => !kept.has(norm(warning.phrase)))
  const warned = new Set(warnings.filter(warning => opOf(warning.phrase)?.op !== 'remove').map(warning => norm(warning.phrase)))

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
    setKept(new Set())
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

  const pill = (phrase: string) => <span className={`approval-pill${warned.has(norm(phrase)) ? ' is-warn' : ''}`} dir="auto">{phrase}</span>
  const locale = uiLocale()
  const headId = `approval-${run.id}`
  const wordsId = `approval-words-${run.id}`
  const advancedId = `approval-advanced-${run.id}`

  // One group of terms with its editing: the searched groups under "Change the words" and the three side lists
  // under "Advanced". `targets` are the groups a term can be moved to from here.
  const renderBlock = (block: ApprovalBlock, targets: ApprovalBlock[], labelOf: (block: ApprovalBlock) => string, blockNote?: string) =>
    <div key={block} className="approval-block">
      <div className="approval-block-head">
        <strong>{labelOf(block)}</strong>
        {blockNote && <small>{blockNote}</small>}
      </div>
      <ul className="approval-terms">
        {shown(block).map(row => {
          const op = opOf(row.phrase)
          const rowErrors = errorsFor(row.phrase)
          return <li key={`${row.block}:${row.phrase}`} className={`approval-term${op?.op === 'remove' ? ' is-removed' : ''}${row.term?.dropped ? ' is-dropped' : ''}`}>
            <div className="approval-term-main">
              <span className="approval-phrase" dir="auto">{row.phrase}</span>
              <span className="approval-term-facts">
                <TermFacts term={row.term} block={row.block} brief />
                {op?.op === 'move' && <span className="approval-badge is-changed">{t('moved by you')}</span>}
                {op?.op === 'remove' && <span className="approval-badge is-changed">{t('removed by you')}</span>}
              </span>
            </div>
            {editable && <div className="approval-term-actions">
              {op ? <Button variant="ghost" size="sm" onClick={() => setOp(row.phrase, null)}><CornerUpLeft size={13} />{t('Undo')}</Button> : <>
                <Select value={block} onValueChange={value => setOp(row.phrase, String(value) === row.block ? null : { op: 'move', phrase: norm(row.phrase), block: String(value) as ApprovalBlock })}>
                  <SelectTrigger size="sm" aria-label={t('Block of “{phrase}”', { phrase: row.phrase })}>
                    <SelectValue>{value => labelOf(value as ApprovalBlock)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>{targets.map(target => <SelectItem key={target} value={target}>{labelOf(target)}</SelectItem>)}</SelectContent>
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
      {editable && <AddTerm block={block} label={t('Add a word to “{group}”', { group: labelOf(block) })} onAdd={text => addTerm(block, text)} error={addError?.block === block ? addError.text : null} />}
    </div>

  return <section className="approval-card is-pending" aria-labelledby={headId}>
    {/* A div, not a <header>: the shell's bare `header` rule fixes a height and a flex row on every one of them. */}
    <div className="approval-head">
      <h3 id={headId}>{warnings.length > 0 ? t('One thing to check before searching') : t('Check what will be searched')}</h3>
      <p>{t('Nothing has been searched yet. Check the words below, then start.')}</p>
    </div>

    <div className="approval-main">
      <div className="approval-sentence-block">
        <span className="approval-label">{t('We will look for papers about')}</span>
        <p className="approval-sentence">
          {first.map((phrase, i) => <Fragment key={`a:${phrase}`}>{i > 0 && ' '}{pill(phrase)}</Fragment>)}
          {first.length > 0 && second.length > 0 && <> {t('and')} </>}
          {second.map((phrase, i) => <Fragment key={`b:${phrase}`}>{i > 0 && (i === second.length - 1 ? ` ${t('or')} ` : ', ')}{pill(phrase)}</Fragment>)}
          {!first.length && !second.length && <span className="approval-none">{t('No term is left.')}</span>}
        </p>
      </div>

      {warnings.map(warning => opOf(warning.phrase)?.op === 'remove'
        ? <div key={warning.phrase} className="approval-warned-removed">
            <span>{t('“{phrase}” is removed from the search.', { phrase: warning.phrase })}</span>
            {editable && <Button variant="ghost" size="sm" onClick={() => setOp(warning.phrase, null)}><CornerUpLeft size={13} />{t('Undo')}</Button>}
          </div>
        : <WarningBox key={warning.phrase} warning={warning} model={approval.advice_model ?? null} modelText={modelText} locale={locale} editable={editable}
            onRemove={() => setOp(warning.phrase, { op: 'remove', phrase: norm(warning.phrase) })}
            onKeep={() => setKept(new Set([...kept, norm(warning.phrase)]))} />)}
      {proposal.search_query?.status === 'failed' && <Notice tone="attention">{t('The model could not write the search query. You chose the query DEIXIS built from the question’s words.')}</Notice>}
      {proposal.too_broad && <Notice tone="attention">{t('Every term that would be searched is too frequent to stand alone. You can still approve; the run will stop again and say so.')}</Notice>}
      {!proposal.terms.some(term => !term.dropped) && <Notice tone="attention">{t('No term is left to build a provider query from. Add one under “Change the words”.')}</Notice>}
    </div>

    <CriterionMain id={`approval-criterion-${run.id}`} available={proposal.criterion_available}
      sought={proposal.sought_term_in_criterion} draft={criterion} now={criterionNow} editable={editable}
      onEdit={editCriterion} onWriteOwn={() => setCriterion(draftOf(null))} />

    {changed && <p className="approval-summary" role="status">
      <span>{[removed && t(removed === 1 ? '{n} term removed' : '{n} terms removed', { n: removed }),
        addedCount && t(addedCount === 1 ? '{n} term added' : '{n} terms added', { n: addedCount }),
        // Counted apart: how many of the added terms are names the model proposed.
        addedProposals && t(addedProposals === 1 ? '{n} of them proposed by the model' : '{n} of them proposed by the model', { n: addedProposals }),
        moved && t(moved === 1 ? '{n} term moved' : '{n} terms moved', { n: moved }),
        codeChanged && t(codeOn ? 'the code’s query switched on' : 'the code’s query switched off'),
        criterionEdited && t('criterion corrected')].filter(Boolean).join(' · ')}</span>
      {editable && <Button variant="ghost" size="sm" disabled={busy} onClick={undoAll}>{t('Undo changes')}</Button>}
    </p>}
    {checking && <p className="approval-checking" role="status">{t('Your correction was sent. The terms you added are being counted against the literature; this card opens again if they cannot be searched.')}</p>}
    {working && <p className="approval-checking" role="status">{t('The model is proposing other names and each one is being counted. Your draft corrections are kept.')}</p>}
    {/* Announced whenever anything was refused, so a fault shown only beside its row is still spoken once. */}
    {errors.length > 0 && <div className="approval-errors" role="alert">
      <p>{t('The correction was not applied. Nothing was sent to a provider.')}</p>
      {generalErrors.length > 0 && <ul>{generalErrors.map(error => <li key={error}>{error}</li>)}</ul>}
    </div>}

    <div className="approval-foot">
      <div className="approval-links">
        <button type="button" className="approval-link" aria-expanded={wordsOpen} aria-controls={wordsId} onClick={() => setWordsOpen(!wordsOpen)}>{t('Change the words')}</button>
        <button type="button" className="approval-link" aria-expanded={advancedOpen} aria-controls={advancedId} onClick={() => setAdvancedOpen(!advancedOpen)}>{t('Advanced')}</button>
      </div>
      {editable && <Button variant="default" className="approval-start" disabled={busy} onClick={() => void submit()}>{t('Start searching')}</Button>}
    </div>

    {wordsOpen && <div className="approval-panel" id={wordsId}>
      {SENTENCE_BLOCKS.map(block => renderBlock(block, SENTENCE_BLOCKS, groupLabel))}
    </div>}

    {advancedOpen && <div className="approval-panel" id={advancedId}>
      {written && <div className="approval-provenance"><Notice tone="info">{t('A model wrote these search terms from the question. The counts, the backups and the warnings are the application’s own checks; the query built from the question’s words is offered below.')}</Notice></div>}

      <div className="approval-block">
        <div className="approval-block-head">
          <strong>{t('How each search term was chosen')}</strong>
          <small>{t('Who wrote it, how it enters the query and how many records hold it.')}</small>
        </div>
        <ul className="approval-terms">
          {rows.filter(row => row.term).map(row => <li key={`${row.block}:${row.phrase}`} className={`approval-term is-detail${row.term?.dropped ? ' is-dropped' : ''}`}>
            <div className="approval-term-main">
              <span className="approval-phrase" dir="auto">{row.phrase}</span>
              <span className="approval-term-facts">
                <TermFacts term={row.term} block={row.block} />
                {written && <WrittenFacts side={written} phrase={row.phrase} />}
                <span className="approval-badge">{termOriginText(row.term!.origin)}</span>
                <span className="approval-badge">{blockOriginText(row.term!.block_origin)}</span>
                <span className="approval-badge">{t(blockLabels[row.block])}</span>
              </span>
            </div>
          </li>)}
        </ul>
      </div>

      {SIDE_BLOCKS.map(block => renderBlock(block, BLOCKS, target => t(blockLabels[target]), t(blockNotes[block])))}

      {written && <QuerySection side={written} queries={proposal.queries ?? []} on={codeOn} editable={editable}
        onChange={on => setCodeQuery(on === written.code_query.searched ? null : on)} />}

      {approval.routing && <RoutingSection routing={approval.routing} />}

      {approval.chaining && <ChainingSection chaining={approval.chaining} />}

      <SuggestionSection suggestions={approval.suggestions} editable={editable} working={working} busy={busy}
        drafted={new Set(ops.filter(op => op.op === 'add').map(op => op.phrase))}
        onAdd={row => setOps([...without(row.phrase), { op: 'add', phrase: row.phrase, block: row.block }])}
        onUndo={phrase => setOp(phrase, null)} onAsk={() => void ask()} />

      <CriterionAdvanced criterion={proposal.criterion} available={proposal.criterion_available}
        draft={criterion} now={criterionNow} editable={editable} onEdit={editCriterion} onUndo={() => setCriterion(null)} />

      {editable && <div className="approval-block">
        <label className="approval-note">
          <span>{t('Note for the record (optional)')}</span>
          <Textarea value={note} onChange={e => setNote(e.target.value)} rows={2} maxLength={1000}
            placeholder={t('Why you corrected this. It is kept with the protocol.')} />
        </label>
      </div>}
    </div>}
  </section>
}

// What the literature holds for a term, and the form it enters the query in. A count that was not read says so;
// it is never shown as 0, which would mean the opposite. `brief` is the editing row: the count and why it is out.
function TermFacts({ term, block, brief = false }: { term: ApprovalTerm | null; block: ApprovalBlock; brief?: boolean }) {
  if (!term) return <span className="approval-count">{block === 'outcome' ? t('not searched; orders the records') : t('not searched')}</span>
  const count = term.in_query === 'root' ? term.root_count : term.phrase_count
  return <>
    <span className="approval-count">{count === null ? t('not counted')
      : t('{n} records', { n: count.toLocaleString(uiLocale()) })}</span>
    {!brief && <span className="approval-badge">{term.in_query === 'root' ? t('enters as the word “{root}”', { root: term.root }) : t('enters as the whole phrase')}</span>}
    {!brief && term.and_only && <span className="approval-badge">{t('too frequent alone; only combined')}</span>}
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

// Which sources the run searches and why (D93): read by code from the field distribution of the gate query, before
// this card. The list is shown, not edited; a source is left out of a research in its scope.
function RoutingSection({ routing }: { routing: SourceRouting }) {
  const percent = (share: number) => `${Math.round(share * 100)}%`
  const total = routing.total?.toLocaleString(uiLocale())
  const fieldsOf = (fields?: string[]) => (fields ?? []).join(' + ')
  const chosenText = (row: SourceRouting['chosen'][number]) =>
    row.reason === 'share' && row.share !== undefined && total !== undefined
      ? t('{fields}, {share} of {total} records', { fields: fieldsOf(row.fields), share: percent(row.share), total })
      : routeReasonText(row.reason)
  const queried = routing.queried ?? routing.providers
  const searched = routing.chosen.filter(row => queried.includes(row.provider_id))
  const unqueried = routing.chosen.filter(row => !queried.includes(row.provider_id))
  const leftText = (row: SourceRouting['left_out'][number]) =>
    row.reason === 'share_below' && row.share !== undefined ? t('share {share}', { share: percent(row.share) }) : routeReasonText(row.reason)
  return <div className="approval-routing">
    <div className="approval-block-head">
      <strong>{t('Sources')}</strong>
      <small>{t('OpenAlex and Semantic Scholar are always searched. A field-specific source is searched when its fields hold at least {share} of the records the query finds. To leave a source out, remove it from the research’s sources.', { share: percent(routing.route_share) })}</small>
    </div>
    {routing.status === 'unavailable' && <Notice tone="attention">{t('The field distribution could not be read, so every source in this research’s scope is searched.')}</Notice>}
    {routing.status === 'not_needed' && <p className="approval-hint">{t('No field-specific source is in this research’s scope, so the distribution was not asked for.')}</p>}
    {routing.status === 'read' && total !== undefined && <p className="approval-hint">{t('Read from {total} records of the query {query}', { total, query: routing.query ?? '' })}</p>}
    <div className="approval-query-group">
      <span className="approval-field-label">{t('Searched')}</span>
      <ul>{searched.map(row => <li key={row.provider_id}><small>{providerName(row.provider_id)}</small> {chosenText(row)}</li>)}</ul>
    </div>
    {unqueried.length > 0 && <div className="approval-query-group is-off">
      <span className="approval-field-label">{t('Chosen, no query in the first round')}</span>
      <small>{t('This effort’s query limit leaves these sources no first-round query.')}</small>
      <ul>{unqueried.map(row => <li key={row.provider_id}><small>{providerName(row.provider_id)}</small> {chosenText(row)}</li>)}</ul>
    </div>}
    {routing.left_out.length > 0 && <div className="approval-query-group is-off">
      <span className="approval-field-label">{t('Not searched')}</span>
      <ul>{routing.left_out.map(row => <li key={row.provider_id}><small>{providerName(row.provider_id)}</small> {leftText(row)}</li>)}</ul>
    </div>}
  </div>
}

// The fast chain this run will follow (`fast_chain_v1`), as its budget froze it: OpenAlex only. It starts during the
// search, from the first works of OpenAlex's semantic search (the ranking fills in when that search gives fewer), and
// only replies that arrive before the arrival cutoff (the ranking deadline minus `arrival_margin_ms`) add works. The seeds themselves are listed in the run view.
function ChainingSection({ chaining }: { chaining: CitationChaining }) {
  return <div className="approval-chaining">
    <div className="approval-block-head">
      <strong>{t('Citation chaining')}</strong>
      <small>{t('OpenAlex only. While the search runs, OpenAlex is asked for the works that the first {seeds} works of its semantic search cite, and for the works that cite them; when that search gives fewer works, the ranking fills the list. Works you verified are not used as seeds. A new work is kept when a setting or task term stands in its title or abstract and its reply arrives a few seconds before the ranking stage ends; the seeds are listed in the run once the search is done.', { seeds: chaining.seeds })}</small>
    </div>
    <p className="approval-hint">{t('Up to {backward} reference requests and {forward} citing requests · up to {cap} citing works per request · at most {attempts} attempts with retries', { backward: chaining.backward_requests, forward: chaining.forward_requests, cap: chaining.citing_cap, attempts: chaining.attempt_limit })}</p>
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

function AddTerm({ block, label, onAdd, error }: { block: ApprovalBlock; label: string; onAdd: (text: string) => void; error: string | null }) {
  const [text, setText] = useState('')
  const id = `approval-add-${block}`
  return <form className="approval-add" onSubmit={e => { e.preventDefault(); onAdd(text); setText('') }}>
    <label htmlFor={id}>{label}</label>
    <div>
      <input id={id} value={text} onChange={e => setText(e.target.value)} maxLength={80} dir="auto" />
      <Button type="submit" variant="outline" size="sm" disabled={!text.trim()}><Plus size={13} />{t('Add')}</Button>
    </div>
    {error && <p className="approval-row-error" role="alert">{error}</p>}
  </form>
}

// The criterion as the main view shows it: one sentence the user can read and correct. The parts, cue phrases and
// excluded words that belong to it are in CriterionAdvanced.
function CriterionMain({ id, available, sought, draft, now, editable, onEdit, onWriteOwn }: {
  id: string; available: boolean; sought: boolean | null
  draft: CriterionDraft | null; now: CriterionDraft; editable: boolean
  onEdit: (change: Partial<CriterionDraft>) => void; onWriteOwn: () => void
}) {
  return <div className="approval-criterion-main">
    {!available && draft === null && <div className="approval-criterion-empty">
      <Notice tone="attention">{t('No criterion was proposed: the model was not reachable while this run worked. You can go on without one, or write one yourself.')}</Notice>
      {editable && <div className="approval-actions">
        <Button variant="outline" className="approval-btn" onClick={onWriteOwn}>{t('Write a criterion')}</Button>
        <span className="approval-hint">{t('Approving without one searches with the terms above and records no criterion.')}</span>
      </div>}
    </div>}
    {(available || draft !== null) && <>
      <label htmlFor={id} className="approval-label">{t('A paper is used as a source when it')}</label>
      {editable ? <Textarea id={id} className="approval-criterion-text" value={now.criterion} maxLength={600} rows={2} onChange={e => onEdit({ criterion: e.target.value })} />
        : <p id={id} className="approval-readonly">{now.criterion}</p>}
      {sought === false && <Notice tone="attention">{t('What the question looks for is not named in the criterion. Check that the criterion includes the right records.')}</Notice>}
    </>}
  </div>
}

function CriterionAdvanced({ criterion, available, draft, now, editable, onEdit, onUndo }: {
  criterion: ApprovalCriterion | null; available: boolean
  draft: CriterionDraft | null; now: CriterionDraft; editable: boolean
  onEdit: (change: Partial<CriterionDraft>) => void; onUndo: () => void
}) {
  if (!available && draft === null) return null
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
      <small>{approval.approved_by === 'unattended' ? t('not reviewed, fast path') : approval.approved_by === 'warn_kept' ? t('not reviewed, warned terms kept') : approval.approved_by === 'model_advice' ? t('not reviewed, the model advised') : approval.edited ? t('corrected before searching') : approval.approved_by === 'no_warning' ? t('not reviewed, no warning') : t('approved as proposed')}</small>
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
        && <p className="approval-hint">{approval.approved_by === 'unattended' ? t('Nobody reviewed the search vocabulary; the fast path went on without asking.') : approval.approved_by === 'no_warning' ? t('The search went on without asking because no term inflated the matches.') : t('The proposal was approved without a change.')}</p>}
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
