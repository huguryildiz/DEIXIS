import { useEffect, useId, useRef, useState } from 'react'
import { CircleX, Eye, ScanSearch } from 'lucide-react'
import { DialogBody, DialogFooter } from '@/components/ui/dialog'
import { api, type Connections, type ReviewFocus, type ReviewPreview, type ReviewRequest as RequestBody, type ReviewNotReviewed, type ReviewTargetKind } from '../api'
import { connectionModels, ModelPicker, modelKey, notReadyReasons } from '../Home'
import { defaultEffort, listedEffort } from '../modelEffort'
import { ConnectionIcon } from '../connectionIcons'
import { connectionName } from '../labels'
import { t, uiLocale } from '../i18n'
import { scrollBehavior } from '../motion'
import { newCommand, pendingCommand, reviewIdentity, useWriteCommand } from './commands'
import { RetryNotice } from './RetryNotice'
import { NotReviewed } from './NotReviewed'

// The review request inside the "Review with another model" dialog (mockup `reviewDlg`): the focus, the model, an
// optional note, then Preview, which shows what will be sent as counts (claims or elements, passages, characters, estimated tokens),
// the groups and the send limits, and what is left out (mockup `.sendbox`); it does not show the full claim or passage text. Start review is enabled only
// after that preview was shown; any change asks for a new preview.
export function ReviewRequest({ researchId, targetKind, targetId, version, runActive, unavailableReason = '', sectionLabel, sourceName, started, cancel }: {
  researchId: string; targetKind: ReviewTargetKind; targetId: string; version: number; runActive: boolean
  unavailableReason?: string; sourceName?: (id: string) => string; sectionLabel: (ref: string) => string; started: (id: string) => void | Promise<void>
  cancel: () => void
}) {
  const identity = reviewIdentity(researchId, targetKind, targetId)
  const [restored] = useState(() => pendingCommand(identity))
  const [restoredBody] = useState(() => restored ? JSON.parse(restored.body) as RequestBody : null)
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState(restoredBody ? modelKey(restoredBody.connection, restoredBody.model) : '')
  const [effort, setEffort] = useState<string | null>(restoredBody?.reasoning_effort ?? null)
  const [focus, setFocus] = useState<ReviewFocus>(restoredBody?.focus ?? 'source_support')
  const [note, setNote] = useState(restoredBody?.owner_note ?? '')
  const [preview, setPreview] = useState<{ value: ReviewPreview; body: RequestBody; key: string } | null>(null)
  const [shown, setShown] = useState(false)
  const [stale, setStale] = useState(false)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [error, setError] = useState('')
  const [omitted, setOmitted] = useState<ReviewNotReviewed[]>([])
  const heading = useRef<HTMLHeadingElement>(null)
  const previewTicket = useRef(0)
  const reasonId = useId(), radioName = useId(), noteId = useId()
  const command = useWriteCommand(identity, c => api.startReview(researchId, c.body, c.key), async result => {
    setPreview(null); await started(result.review.id)
  }, e => {
    setError(e.message)
    // A refused start shows Preview again: what would be sent next is read afresh, never assumed from the refused one.
    setPreview(null); setShown(false)
    if (e.code === 'nothing_reviewable') setOmitted((e.details?.not_reviewed as ReviewNotReviewed[] | undefined) ?? [])
  })
  useEffect(() => {
    let live = true
    const ticketRef = previewTicket
    Promise.all([api.connections(), api.settings().catch(() => null)]).then(([result, saved]) => {
      if (!live) return
      setConnections(result)
      if (restored) return
      const models = connectionModels(result)
      const setting = [saved?.reviewer, saved?.answer].find(s => s?.model && models.some(m => m.id === modelKey(s.model_connection, s.model!)))
      const chosen = setting?.model ? models.find(m => m.id === modelKey(setting.model_connection, setting.model!)) : models.find(m => m.is_default) ?? models[0]
      if (chosen) { setModel(chosen.id); setEffort((setting ? listedEffort(models, chosen.id, setting.reasoning_effort) : null) ?? defaultEffort(models, chosen.id)) }
    }).catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    return () => { live = false; ticketRef.current++ }
  }, [restored])
  useEffect(() => {
    if (!preview) return
    heading.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'nearest' })
    heading.current?.focus({ preventScroll: true })
    // Start is enabled only after the disclosure was committed to the document and exposed.
    const frame = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(frame)
  }, [preview])
  const change = () => { previewTicket.current++; if (preview) setStale(true); setPreview(null); setShown(false); setError(''); setOmitted([]) }
  const models = connections ? connectionModels(connections) : []
  const chosen = models.find(m => m.id === model)
  const noModel = t('No model connection is ready, so no model can be chosen: {reason}', { reason: connections ? notReadyReasons(connections) : t('Checking…') })
  const body = (): RequestBody | null => chosen ? { target_kind: targetKind, target_id: targetId, focus, owner_note: note.trim() || null, connection: chosen.connection, model: chosen.model, reasoning_effort: effort } : null
  const previewReview = async () => {
    const request = body()
    if (!request || unavailableReason || command.pending || previewBusy) return
    const ticket = ++previewTicket.current
    setPreviewBusy(true); setError(''); setOmitted([])
    try {
      const value = await api.previewReview(researchId, request)
      if (ticket === previewTicket.current) { setPreview({ value, body: request, key: crypto.randomUUID() }); setStale(false) }
    } catch (e) {
      if (ticket !== previewTicket.current) return
      setError(e instanceof Error ? e.message : String(e))
      if (e && typeof e === 'object' && 'code' in e && e.code === 'nothing_reviewable' && 'details' in e) setOmitted((e.details as { not_reviewed?: ReviewNotReviewed[] } | null)?.not_reviewed ?? [])
    } finally { setPreviewBusy(false) }
  }
  const needsPreview = !preview || !shown
  const disabledReason = unavailableReason || (command.pending ? t('The last request may or may not have been saved.') : runActive ? t('Another run is active in this research.') : '')
  const number = (n: number) => new Intl.NumberFormat(uiLocale(), { maximumFractionDigits: 0 }).format(n)
  const hint = previewBusy ? t('Preparing preview…') : stale ? t('Settings changed; preview again.') : t('Preview what will be sent first.')
  const groups = preview?.value.estimated_input_tokens_per_group.length ?? 0
  const counts = preview && (targetKind === 'candidate'
    ? t('Elements {e} · Sources with matrix rows {s} · Passages {p} · Characters {c}', { e: number(preview.value.element_count), s: number(preview.value.matrix_source_count), p: number(preview.value.passage_count), c: number(preview.value.characters_to_be_sent) })
    : t('Claims {n} · Passages {p} · Characters {c}', { n: number(preview.value.claim_count), p: number(preview.value.passage_count), c: number(preview.value.characters_to_be_sent) }))
  return <form className="review-request mk" onSubmit={event => { event.preventDefault(); if (preview && !needsPreview && !disabledReason) void command.send(newCommand({ ...preview.body, snapshot_sha256: preview.value.snapshot_sha256, preview_fingerprint: preview.value.preview_fingerprint }, preview.key)) }}>
    <DialogBody>
      <p className="foot-note review-request-target">{t(targetKind === 'candidate' ? 'Candidate · version {n}' : targetKind === 'answer' ? 'Answer · V{n}' : 'Evidence report · V{n}', { n: version })}</p>
      <fieldset className="lbl" disabled={Boolean(command.pending)} role="radiogroup" aria-label={t('Review focus')}><legend>{t('Review focus')}</legend>
        <div className="opts">
          <label><input type="radio" name={radioName} checked={focus === 'source_support'} onChange={() => { change(); setFocus('source_support') }} /><span>{t('Source support')}<small>{t('Does each claim follow from what it cites')}</small></span></label>
          <label><input type="radio" name={radioName} checked={focus === 'assumptions_and_consistency'} onChange={() => { change(); setFocus('assumptions_and_consistency') }} /><span>{t('Assumptions and consistency')}<small>{t('Unstated assumptions, contradictions, scope wider than the evidence; findings are reviewer inference')}</small></span></label>
        </div>
      </fieldset>
      <fieldset className="lbl review-model" disabled={Boolean(command.pending)}><legend>{t('Model')}</legend>
        {models.length > 0 ? <ModelPicker role={t('Review')} icon={ScanSearch} hint={t('The model reads the stored review copy.')} models={models} value={model} onChange={id => { change(); setModel(id); setEffort(defaultEffort(models, id)) }} effort={effort} onEffort={value => { change(); setEffort(value) }} /> : <p id={`${reasonId}-model`} className="foot-note">{noModel}</p>}
      </fieldset>
      <label className="lbl" htmlFor={noteId}>{t('Note (optional)')}
        <textarea id={noteId} className="field" rows={2} data-stored-text maxLength={500} value={note} readOnly={Boolean(command.pending)} placeholder={t('Sent to the model as your instruction')} aria-describedby={`${noteId}-hint`} onChange={e => { change(); setNote(e.target.value) }} />
        <small id={`${noteId}-hint`}>{t('{n} of 500 characters', { n: note.length })}</small>
      </label>
      {preview ? <section className="sendbox review-disclosure" aria-labelledby={`${reasonId}-disclosure`}>
        <h3 id={`${reasonId}-disclosure`} ref={heading} tabIndex={-1}>{t('What will be sent')}</h3>
        <span>{counts}</span>
        <span>{t('Estimated input tokens: {n} (estimated, four characters per token)', { n: number(preview.value.estimated_input_tokens_total) })}</span>
        <span>{t(groups === 1 ? 'Sent in {n} group.' : 'Sent in {n} groups.', { n: groups })} {t('Cost is not estimated.')} {t('The model reads the stored review copy.')}</span>
        <span className="review-connection"><ConnectionIcon id={preview.value.connection} />{preview.value.connection_display_name && preview.value.connection_display_name !== preview.value.connection ? preview.value.connection_display_name : connectionName(preview.value.connection)}</span>
        <span>{t(preview.value.logical_steps === 1 ? '{n} logical step' : '{n} logical steps', { n: preview.value.logical_steps })} · {t(preview.value.steps_with_repair_bound === 1 ? '{n} step with repair' : '{n} steps with repair', { n: preview.value.steps_with_repair_bound })} · {t(preview.value.total_send_bound === 1 ? 'at most {n} model call' : 'at most {n} model calls', { n: preview.value.total_send_bound })}</span>
        {groups > 1 && <span>{t('Per group: {tokens}', { tokens: preview.value.estimated_input_tokens_per_group.map(number).join(', ') })}</span>}
        {preview.value.not_reviewed.length > 0 && <><b>{t('Not reviewed')}</b><NotReviewed rows={preview.value.not_reviewed} sourceName={sourceName} sectionLabel={sectionLabel} /></>}
      </section> : <div className="review-preview-row">
        <button type="button" className="ghost" disabled={Boolean(unavailableReason) || !chosen || previewBusy || Boolean(command.pending)} aria-describedby={unavailableReason ? reasonId : !chosen ? `${reasonId}-model` : `${reasonId}-hint`} onClick={() => void previewReview()}><Eye aria-hidden />{t('Preview')}</button>
        <span id={`${reasonId}-hint`} className="foot-note" role={previewBusy ? 'status' : undefined}>{hint}</span>
      </div>}
      {error && <div className="notice bad" role="alert"><CircleX aria-hidden /><div className="nb"><span>{error}</span>{omitted.length > 0 && <NotReviewed rows={omitted} sourceName={sourceName} sectionLabel={sectionLabel} />}</div></div>}
      {disabledReason && <p id={reasonId} className="foot-note review-lock">{disabledReason}</p>}
      {command.pending && !command.busy && <RetryNotice busy={command.busy} retry={() => void command.retry()} />}
    </DialogBody>
    <DialogFooter>
      <button type="button" className="ghost" disabled={command.busy} onClick={cancel}>{t('Cancel')}</button>
      <button type="submit" className="btn-pri" disabled={needsPreview || Boolean(disabledReason) || command.busy} aria-describedby={disabledReason ? reasonId : needsPreview ? `${reasonId}-hint` : undefined}>{t('Start review')}</button>
    </DialogFooter>
  </form>
}
