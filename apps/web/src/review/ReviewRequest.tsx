import { useEffect, useId, useRef, useState } from 'react'
import { ScanSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type Connections, type ReviewFocus, type ReviewPreview, type ReviewRequest as RequestBody, type ReviewNotReviewed } from '../api'
import { connectionModels, ModelPicker, modelKey, notReadyReasons } from '../Home'
import { defaultEffort, listedEffort } from '../modelEffort'
import { ConnectionIcon } from '../connectionIcons'
import { connectionName } from '../labels'
import { Notice } from '../Notice'
import { t, uiLocale } from '../i18n'
import { scrollBehavior } from '../motion'
import { newCommand, pendingCommand, useWriteCommand } from './commands'
import { RetryNotice } from './RetryNotice'
import { NotReviewed } from './NotReviewed'

export function ReviewRequest({ researchId, targetKind, targetId, version, runActive, unavailableReason = '', sectionLabel, started }: {
  researchId: string; targetKind: 'answer' | 'report'; targetId: string; version: number; runActive: boolean
  unavailableReason?: string; sectionLabel: (ref: string) => string; started: (id: string) => void | Promise<void>
}) {
  const identity = `${researchId}:${targetKind}:${targetId}:start`
  const [restored] = useState(() => pendingCommand(identity))
  const [restoredBody] = useState(() => restored ? JSON.parse(restored.body) as RequestBody : null)
  const [connections, setConnections] = useState<Connections | null>(null)
  const [model, setModel] = useState(restoredBody ? modelKey(restoredBody.connection, restoredBody.model) : '')
  const [effort, setEffort] = useState<string | null>(restoredBody?.reasoning_effort ?? null)
  const [focus, setFocus] = useState<ReviewFocus>(restoredBody?.focus ?? 'source_support')
  const [note, setNote] = useState(restoredBody?.owner_note ?? '')
  const [preview, setPreview] = useState<{ value: ReviewPreview; body: RequestBody; key: string } | null>(null)
  const [shown, setShown] = useState(false)
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
    setPreview(p => p ? { ...p, key: crypto.randomUUID() } : null)
    if (e.code === 'target_changed' || e.code === 'preview_changed') { setPreview(null); setShown(false) }
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
  const change = () => { previewTicket.current++; setPreview(null); setShown(false); setError(''); setOmitted([]) }
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
      if (ticket === previewTicket.current) setPreview({ value, body: request, key: crypto.randomUUID() })
    } catch (e) {
      if (ticket !== previewTicket.current) return
      setError(e instanceof Error ? e.message : String(e))
      if (e && typeof e === 'object' && 'code' in e && e.code === 'nothing_reviewable' && 'details' in e) setOmitted((e.details as { not_reviewed?: ReviewNotReviewed[] } | null)?.not_reviewed ?? [])
    } finally { setPreviewBusy(false) }
  }
  const disabledReason = unavailableReason || (command.pending ? t('The last request may or may not have been saved.') : runActive ? t('Another run is active in this research.') : !preview || !shown ? t('Preview the review first.') : '')
  const number = (n: number) => new Intl.NumberFormat(uiLocale(), { maximumFractionDigits: 0 }).format(n)
  return <form className="review-request" onSubmit={event => { event.preventDefault(); if (preview && !disabledReason) void command.send(newCommand({ ...preview.body, snapshot_sha256: preview.value.snapshot_sha256, preview_fingerprint: preview.value.preview_fingerprint }, preview.key)) }}>
    <h3>{t('Review with another model')}</h3>
    <p>{t(targetKind === 'answer' ? 'Answer · V{n}' : 'Evidence report · V{n}', { n: version })}</p>
    <fieldset disabled={Boolean(command.pending)} role="radiogroup" aria-label={t('Review focus')}><legend>{t('Review focus')}</legend>
      <label><input type="radio" name={radioName} checked={focus === 'source_support'} onChange={() => { change(); setFocus('source_support') }} />{t('Source support: does each claim follow from what it cites')}</label>
      <label><input type="radio" name={radioName} checked={focus === 'assumptions_and_consistency'} onChange={() => { change(); setFocus('assumptions_and_consistency') }} />{t('Assumptions and consistency: unstated assumptions, contradictions, scope wider than the evidence; findings are reviewer inference')}</label>
    </fieldset>
    <fieldset disabled={Boolean(command.pending)} className="review-model"><legend>{t('Model')}</legend>
      {models.length > 0 ? <ModelPicker role={t('Review')} icon={ScanSearch} hint={t('The model reads the stored review copy.')} models={models} value={model} onChange={id => { change(); setModel(id); setEffort(defaultEffort(models, id)) }} effort={effort} onEffort={value => { change(); setEffort(value) }} /> : <p id={`${reasonId}-model`}>{noModel}</p>}
    </fieldset>
    <label htmlFor={noteId}>{t('Note (optional)')}</label><textarea id={noteId} data-stored-text maxLength={500} value={note} readOnly={Boolean(command.pending)} aria-describedby={`${noteId}-hint`} onChange={e => { change(); setNote(e.target.value) }} />
    <p id={`${noteId}-hint`}>{t('Sent to the model as your instruction.')} {t('{n} of 500 characters', { n: note.length })}</p>
    <Button type="button" variant="outline" disabled={Boolean(unavailableReason) || !chosen || previewBusy || Boolean(command.pending)} aria-describedby={unavailableReason ? reasonId : !chosen ? `${reasonId}-model` : previewBusy ? `${reasonId}-preview` : command.pending ? reasonId : undefined} onClick={() => void previewReview()}>{t('Preview')}</Button>
    {previewBusy && <p id={`${reasonId}-preview`} role="status">{t('Preparing preview…')}</p>}
    {error && <Notice tone="error">{error}{omitted.length > 0 && <NotReviewed rows={omitted} sectionLabel={sectionLabel} />}</Notice>}
    {preview && <section className="review-disclosure" aria-labelledby={`${reasonId}-disclosure`}>
      <h4 id={`${reasonId}-disclosure`} ref={heading} tabIndex={-1}>{t('What will be sent')}</h4>
      <dl><div><dt>{t('Claims')}</dt><dd>{number(preview.value.claim_count)}</dd></div><div><dt>{t('Passages')}</dt><dd>{number(preview.value.passage_count)}</dd></div><div><dt>{t('Characters')}</dt><dd>{number(preview.value.characters_to_be_sent)}</dd></div></dl>
      <p className="review-connection"><ConnectionIcon id={preview.value.connection} />{preview.value.connection_display_name && preview.value.connection_display_name !== preview.value.connection ? preview.value.connection_display_name : connectionName(preview.value.connection)}</p>
      <p>{t(preview.value.logical_steps === 1 ? '{n} logical step' : '{n} logical steps', { n: preview.value.logical_steps })} · {t(preview.value.steps_with_repair_bound === 1 ? '{n} step with repair' : '{n} steps with repair', { n: preview.value.steps_with_repair_bound })} · {t(preview.value.total_send_bound === 1 ? 'at most {n} model call' : 'at most {n} model calls', { n: preview.value.total_send_bound })}</p>
      <p>{t('Estimated input tokens: {n}', { n: number(preview.value.estimated_input_tokens_total) })} · {t('estimated, four characters per token')}</p>
      <p>{t('Per group: {tokens}', { tokens: preview.value.estimated_input_tokens_per_group.map(number).join(', ') })}</p><p>{t('Cost is not estimated.')}</p>
      {preview.value.not_reviewed.length > 0 && <><h4>{t('Not reviewed')}</h4><NotReviewed rows={preview.value.not_reviewed} sectionLabel={sectionLabel} /></>}
    </section>}
    <div className="review-actions"><Button type="submit" disabled={Boolean(disabledReason) || command.busy} aria-describedby={disabledReason ? reasonId : undefined}>{t('Start review')}</Button></div>
    {disabledReason && <p id={reasonId}>{disabledReason}</p>}
    {command.pending && !command.busy && <RetryNotice busy={command.busy} retry={() => void command.retry()} />}
  </form>
}
