import { useContext, useEffect, useId, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, ScanText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { api, ApiError, type Asset, type RecoveryHistory } from './api'
import { fileRestoreText, recoveryReasonText, textRecoveryReasonText, textRecoveryResultText, textRetryResultText, textRetryTone } from './labels'
import { t, uiLocale } from './i18n'
import { Notice } from './Notice'
import { useToast } from './Toast'

import { TextRecoveryContext } from './TextRecoveryContext'

export function TextRecovery({ asset, sourceId }: { asset: Asset; sourceId: string }) {
  const context = useContext(TextRecoveryContext)
  const toast = useToast()
  const [requesting, setRequesting] = useState(false)
  const [waitingAt, setWaitingAt] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<RecoveryHistory | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [historyRevision, setHistoryRevision] = useState(0)
  const button = useRef<HTMLButtonElement>(null)
  const result = useRef<HTMLParagraphElement>(null)
  const restoreFocus = useRef(false)
  const reasonId = useId()
  const capability = asset.text_recovery
  const running = requesting || capability?.latest_operation?.lifecycle === 'running' || (waitingAt !== null && context?.eventCursor === waitingAt)
  const showButton = Boolean(capability && ['failed', 'partial', 'no_text'].includes(capability.status) && !['already_current', 'password_protected'].includes(capability.reason ?? ''))
  const visible = Boolean(capability && (['failed', 'partial', 'no_text'].includes(capability.status) || capability.latest_operation || capability.latest_file_restore))
  const eventCursor = context?.eventCursor
  const operationId = capability?.latest_operation?.operation_id
  const operationLifecycle = capability?.latest_operation?.lifecycle
  const restoreId = capability?.latest_file_restore?.operation_id
  const restoreLifecycle = capability?.latest_file_restore?.lifecycle
  const researchId = context?.researchId

  useEffect(() => {
    if (!open || !researchId) return
    let cancelled = false
    api.recoveryHistory(researchId, sourceId, asset.id).then(value => {
      if (!cancelled) { setHistory(value); setHistoryError('') }
    }, e => { if (!cancelled) setHistoryError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [open, researchId, sourceId, asset.id, eventCursor, operationId, operationLifecycle, restoreId, restoreLifecycle, historyRevision])

  useEffect(() => {
    if (!restoreFocus.current || requesting) return
    restoreFocus.current = false
    // Only this component's retry owns focus; parent focus handlers remain separate.
    if (document.activeElement === button.current || document.activeElement === document.body) (button.current ?? result.current)?.focus()
  }, [requesting, showButton])

  if (!context || !capability || !visible) return null
  const blocked = running || !capability.can_retry_text || context.busy
  const disabledReason = running ? t('Text retry is running…') : context.busy ? t('Another action is running.') : textRecoveryReasonText(capability.reason)
  const resultText = running ? t('Text retry is running…') : textRecoveryResultText(capability)
  const retry = async () => {
    if (blocked || !capability.current_extraction_id) return
    setError(''); setRequesting(true); restoreFocus.current = true
    try {
      const next = await api.retryText(context.researchId, sourceId, asset.id, {
        mode: 'retry_failed_or_partial', expected_current_extraction_id: capability.current_extraction_id, idempotency_key: crypto.randomUUID(),
      })
      context.acceptView(next)
      setWaitingAt(next.recovery.lifecycle === 'running' ? next.last_event_id : null)
      const nextCapability = next.sources.find(source => source.source_version_id === sourceId)?.access.assets.find(item => item.id === asset.id)?.text_recovery
      toast(textRetryTone(next.recovery), nextCapability ? textRecoveryResultText(nextCapability) : textRetryResultText(next.recovery, null))
    } catch (e) {
      const message = e instanceof ApiError && e.status === 404 && e.message === 'File missing'
        ? textRecoveryReasonText('file_missing') : e instanceof Error ? e.message : String(e)
      setError(message); toast('error', message)
      if (e instanceof ApiError && ['baseline_changed', 'operation_running'].includes(e.code ?? '')) await context.reload()
    } finally { setRequesting(false); setHistoryRevision(value => value + 1) }
  }
  const entries = history ? [
    ...history.text_retries.map(item => ({ kind: 'text' as const, date: item.operation.created_at, id: item.operation.operation_id, item })),
    ...history.file_restores.map(file => ({ kind: 'file' as const, date: file.created_at, id: file.operation_id, file })),
  ].sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id)) : []
  return <section className="text-recovery" aria-label={t('PDF text recovery')}>
    <p ref={result} tabIndex={-1} className={`text-recovery-result${capability.reason === 'password_protected' ? ' is-error' : ''}`} role="status">{resultText}</p>
    {showButton && <div className="text-recovery-action">
      <Tooltip content={blocked ? disabledReason : t('Try reading the stored PDF text once.')}>
        <Button ref={button} size="sm" variant="outline" aria-disabled={blocked || undefined} aria-describedby={blocked ? reasonId : undefined} onClick={() => void retry()}><ScanText size={14} aria-hidden />{t(capability.status === 'no_text' ? 'Check PDF text again' : 'Retry text extraction')}</Button>
      </Tooltip>
      {blocked && <span id={reasonId} className="sr-only">{disabledReason}</span>}
    </div>}
    {error && <Notice tone="error">{error}</Notice>}
    <button type="button" className="text-recovery-disclosure" aria-expanded={open} aria-controls={`${reasonId}-history`} onClick={() => setOpen(value => !value)}>
      {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}{t('Text recovery history')}{history && <span> ({entries.length})</span>}
    </button>
    {open && <div id={`${reasonId}-history`}>
      {historyError && <Notice tone="error">{historyError}</Notice>}
      {!history && !historyError && <p role="status">{t('Loading recovery history…')}</p>}
      {history && <>
        {!entries.length && <p>{t('No recorded recovery operations.')}</p>}
        <ol className="text-recovery-history">{entries.map(entry => <li key={entry.id}>
          <p><time dateTime={entry.date}>{new Date(entry.date).toLocaleString(uiLocale())}</time> · {t(entry.kind === 'text' ? 'Text retry' : 'File restore')}</p>
          <p>{entry.kind === 'text' ? textRetryResultText(entry.item.operation, null, true) : fileRestoreText(entry.file, true)}</p>
          {entry.kind === 'text' && <>
            {entry.item.operation.candidate_status && <p>{t('Candidate status: {status}.', { status: t(entry.item.operation.candidate_status.replaceAll('_', ' ')) })}</p>}
            {entry.item.candidate?.error && <p>{t('Recorded error: {error}', { error: t(entry.item.candidate.error) })}</p>}
            {entry.item.operation.coverage && <p>{t('Pages with text before: {before}; after: {after}.', { before: entry.item.operation.coverage.old_text_pages.join(', ') || t('none'), after: entry.item.operation.coverage.new_text_pages.join(', ') || t('none') })}</p>}
            <p>{t('Not measured: whether the words match the PDF.')}</p>
          </>}
          <details><summary>{t('Details')}</summary><dl className="text-recovery-identifiers">
            {entry.kind === 'text' ? <>
              {entry.item.candidate && <>
                <div><dt>{t('Extraction ID')}</dt><dd>{entry.item.candidate.extraction_id}</dd></div>
                <div><dt>{t('Extraction version (occurrence)')}</dt><dd>{entry.item.candidate.extraction_version}</dd></div>
                <div><dt>{t('Extractor profile')}</dt><dd>{entry.item.candidate.extractor_profile}</dd></div>
              </>}
              <div><dt>{t('Input integrity')}</dt><dd>{entry.item.operation.input_integrity ?? t('not recorded')}</dd></div>
              {entry.item.operation.reason && <div><dt>{t('Reason')}</dt><dd>{recoveryReasonText(entry.item.operation.reason)}</dd></div>}
            </> : <>
              <div><dt>{t('Before integrity')}</dt><dd>{entry.file.before_integrity ?? t('not recorded')}</dd></div>
              <div><dt>{t('After integrity')}</dt><dd>{entry.file.after_integrity ?? t('not recorded')}</dd></div>
            </>}
          </dl></details>
        </li>)}</ol>
        {history.text_retries_truncated && <p>{t('Latest 20 text retries shown.')}</p>}
        {history.file_restores_truncated && <p>{t('Latest 20 file restores shown.')}</p>}
      </>}
    </div>}
  </section>
}
