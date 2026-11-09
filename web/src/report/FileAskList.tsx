import { useRef, useState } from 'react'
import { api, type FileAsks } from '../lib/api'
import { t } from '../lib/i18n'
import { stateLabels } from '../table/tableCsv'
import { Notice } from '../components/Notice'

// The works this research asked for a file for, each with the sub-question its own cell leaves open. The list is
// bounded by the depth's allowance, and the report is delivered whether or not a file arrives, so the copy asks
// rather than blocks. A row whose file has arrived keeps its place and says so.
export function FileAskList({ researchId, asks, onUploaded }: {
  researchId: string; asks: FileAsks; onUploaded: () => void
}) {
  const inputs = useRef<Record<string, HTMLInputElement | null>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  if (!asks.asks.length) return null
  const open = asks.asks.filter(ask => !ask.answered_at)
  const upload = async (sourceVersionId: string, list: FileList | null) => {
    const file = list?.[0]
    if (!file) return
    setBusy(sourceVersionId)
    setError('')
    try {
      await api.uploadToSource(researchId, sourceVersionId, file)
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }
  return <Notice tone={open.length ? 'attention' : 'info'}>
    <p>
      {open.length
        ? t(open.length === 1
          ? 'A file is asked for {n} source: the automatic routes retrieved none for it, and the question beside it is open on its own row.'
          : 'A file is asked for {n} sources: the automatic routes retrieved none for them, and the question beside each is open on its own row.',
          { n: open.length })
        : t('Every file asked for has arrived.')}
      {asks.limit !== null && <> {t('This research asks for at most {n}.', { n: asks.limit })}</>}
      {open.length > 0 && <> {t('The report is written without them too.')}</>}
    </p>
    {error && <p role="alert">{error}</p>}
    <ul>{asks.asks.map(ask => <li key={ask.work_id}>
      <span>{ask.source_key || ask.title || ask.work_id}</span>
      <span> · {t('Open question: {label}', { label: ask.axes.map(axis => axis.label).join('; ') })}</span>
      <span> · {ask.axes.map(axis => t(stateLabels[axis.state])).join('; ')}</span>
      {ask.answered_at
        ? <span> · {t('File added.')}</span>
        : <> <input ref={node => { inputs.current[ask.source_version_id] = node }} type="file"
                    accept=".pdf,application/pdf" hidden
                    onChange={event => { void upload(ask.source_version_id, event.target.files); event.target.value = '' }} />
          <button type="button" disabled={busy !== null}
                  onClick={() => inputs.current[ask.source_version_id]?.click()}>
            {busy === ask.source_version_id ? t('Adding…') : t('Add the PDF')}
          </button></>}
    </li>)}</ul>
  </Notice>
}
