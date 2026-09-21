import { useState } from 'react'
import { ChevronDown, ChevronRight, CornerUpLeft, Plus, X } from 'lucide-react'
import { ApiError, api, type ApprovalBlock, type ApprovalCriterion, type ApprovalSide, type ApprovalTerm, type ProtocolEdits, type Run, type RunApproval, type TermEdit } from './api'
import { approvedByText, blockLabels, blockNotes, blockOriginText, dropReasonText, termOriginText } from './labels'
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
  const editable = approval.status !== 'approved' && !checking
  if (approval.status === 'approved') return <ApprovedSummary approval={approval} />
  return <PendingCard run={run} approval={approval} editable={editable} checking={checking} onApproved={onApproved} />
}

function PendingCard({ run, approval, editable, checking, onApproved }: {
  run: Run; approval: RunApproval; editable: boolean; checking: boolean; onApproved: () => void | Promise<void>
}) {
  const proposal = approval.proposal
  const [ops, setOps] = useState<TermEdit[]>([])
  const [criterion, setCriterion] = useState<CriterionDraft | null>(null)
  const [note, setNote] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [addError, setAddError] = useState<{ block: ApprovalBlock; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

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

  const moved = ops.filter(op => op.op === 'move').length
  const removed = ops.filter(op => op.op === 'remove').length
  const addedCount = ops.filter(op => op.op === 'add').length
  const criterionEdited = criterion !== null
  const changed = ops.length > 0 || criterionEdited

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
    setNote('')
    setErrors([])
    setAddError(null)
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
                <span className="approval-count">{t('will be counted after approval')}</span>
                <span className="approval-badge">{termOriginText('user')}</span>
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
           moved && t(moved === 1 ? '{n} term moved' : '{n} terms moved', { n: moved }),
           criterionEdited && t('criterion corrected')].filter(Boolean).join(' · ')
        : t('No change: the proposal is approved as it stands.')}</p>
      {checking && <p className="approval-checking" role="status">{t('Your correction was sent. The terms you added are being counted against the literature; this card opens again if they cannot be searched.')}</p>}
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

  return <section className="approval-card is-approved">
    <button type="button" className="approval-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? <ChevronDown size={15} aria-hidden /> : <ChevronRight size={15} aria-hidden />}
      <span>{approvedByText(approval.approved_by)}</span>
      <small>{approval.edited ? t('corrected before searching') : t('approved as proposed')}</small>
    </button>
    {open && <div className="approval-diff">
      <DiffList title={t('Removed terms')} rows={gone} />
      <DiffList title={t('Added terms')} rows={fresh} />
      <DiffList title={t('Moved terms')} rows={movedRows} from={beforeAt} />
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
        <ul>{approved.queries.map(query => <li key={`${query.provider_id}:${query.query_text}`}><code>{query.query_text}</code></li>)}</ul>
      </div> : null}
    </div>}
  </section>
}

function DiffList({ title, rows, from }: { title: string; rows: Row[]; from?: Map<string, ApprovalBlock> }) {
  if (!rows.length) return null
  return <div className="approval-diff-group">
    <strong>{title}</strong>
    <ul>{rows.map(row => <li key={`${row.block}:${row.phrase}`}>
      <span dir="auto">{row.phrase}</span>
      <small>{from ? t('{before} → {after}', { before: t(blockLabels[from.get(norm(row.phrase))!]), after: t(blockLabels[row.block]) })
        : t(blockLabels[row.block])}</small>
    </li>)}</ul>
  </div>
}
