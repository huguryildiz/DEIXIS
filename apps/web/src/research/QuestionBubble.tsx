import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { scopeRevision, type Answer, type ResearchIntent, type ScopeRevision, type SourceScope } from '../api'
import { scopeLabels } from '../labels'
import { scopeOptions } from '../Home'
import { t, uiLocale } from '../i18n'

// The intent chip a research was started with, named in the bubble when it is not the default report (R13).
const intentLabels: Partial<Record<ResearchIntent, string>> = { papers: 'Find papers', table: 'Evidence table', compare: 'Compare methods' }

const savedAt = (iso: string) => new Date(iso).toLocaleString(uiLocale(), { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

// The question as the person's turn (mockup `.q`, R13): where DEIXIS looks (accent), the intent when it is not a report,
// the question, and when this revision was saved.
export function QuestionBubble({ question, sourceScope, intent, createdAt, revision }: {
  question: string; sourceScope: SourceScope; intent: ResearchIntent; createdAt: string; revision: number
}) {
  const ScopeIcon = scopeOptions[sourceScope].icon
  const intentLabel = intentLabels[intent]
  return <div className="chat-question">
    <b><ScopeIcon size={16} aria-hidden />{t(scopeLabels[sourceScope])}{intentLabel ? ` · ${t(intentLabel)}` : ''}</b>{' '}
    <span dir="auto">{question}</span>
    <time dateTime={createdAt}>{t('{date} · revision {n}', { date: savedAt(createdAt), n: revision })}</time>
  </div>
}

// "Revision N and its answer are kept · Show" (mockup `.revline`, R12). Show opens the earlier question, read only, and
// the card of the answer written for it, which opens that report.
export function EarlierRevision({ researchId, revision, intent, answer, onOpenReport }: {
  researchId: string; revision: number; intent: ResearchIntent; answer: { answer: Answer; version: number; title: string } | null
  onOpenReport: (answerId: string) => void
}) {
  const [shown, setShown] = useState(false)
  const [scope, setScope] = useState<ScopeRevision | null>(null)
  const [failed, setFailed] = useState('')
  useEffect(() => {
    if (!shown || scope?.revision === revision) return
    let live = true
    scopeRevision(researchId, revision).then(next => { if (live) { setScope(next); setFailed('') } }, (e: Error) => { if (live) setFailed(e.message) })
    return () => { live = false }
  }, [shown, researchId, revision, scope])
  const regionId = `earlier-revision-${revision}`
  return <>
    <div className="revline">
      <span>{t(answer ? 'Revision {n} and its answer are kept' : 'Revision {n} is kept', { n: revision })} · </span>
      <button type="button" className="revline-toggle" aria-expanded={shown} aria-controls={regionId} onClick={() => setShown(open => !open)}>{t(shown ? 'Hide' : 'Show')}</button>
    </div>
    {shown && <section id={regionId} className="earlier-revision" aria-label={t('Revision {n} (read only)', { n: revision })}>
      {scope ? <QuestionBubble question={scope.question} sourceScope={scope.source_scope} intent={intent} createdAt={scope.created_at} revision={scope.revision} />
        : <p className="session-meta" role={failed ? 'alert' : 'status'}>{failed ? t('Could not load revision {n}: {error}', { n: revision, error: failed }) : <span className="shimmer-text">{t('Loading revision {n}…', { n: revision })}</span>}</p>}
      {answer && <button type="button" className="report-artifact earlier-revision-answer" onClick={() => onOpenReport(answer.answer.id)}>
        <span className="report-artifact-preview" aria-hidden="true"><strong>{answer.title}</strong></span>
        <span className="report-artifact-copy"><span className="report-artifact-meta"><FileText size={13} aria-hidden />{t('Report')} · V{answer.version} · {t('earlier')}</span><strong>{answer.title}</strong></span>
      </button>}
    </section>}
  </>
}
