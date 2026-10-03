import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Copy, Download, FileCode, FileText, Quote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, ApiError, type ReportClaim, type ReportDetail, type ReportLink, type ReportSection, type ResearchView, type ReviewFindingRow } from '../api'
import { MathText } from '../MathText'
import { failedRowReasonText, failedSectionReasonText, pauseReasonText, reportAssemblyDraftText, reportChangeLabels, reportChangeViaLabels, reportSupportLabels } from '../labels'
import { Notice } from '../Notice'
import { PassageFreshnessNotice } from './PassageFreshnessNotice'
import { t, uiLocale } from '../i18n'
import { useToast } from '../Toast'
import './report.css'
import { ReportAspects } from '../candidate/ReportAspects'
import type { CandidateSelection } from '../candidate/CandidatesView'
import { useReturnFocus } from '../candidate/focus'
import { ClaimEdit, type ClaimEditBody } from './ClaimEdit'
import { ClaimHistory } from './ClaimHistory'
import { EditCheckPanel } from './EditCheckPanel'
import { checkCounts } from './editLabels'
import { REPORT_HEADINGS as HEADINGS } from '../review/reportHeadings'
import { ReviewPane } from '../review/ReviewPane'
import { ReviewSummary } from '../review/ReviewSummary'
import { useReviewList } from '../review/useReviewList'
import { ApplyEditor } from '../review/ApplyEditor'
import { scrollBehavior } from '../motion'

const DISPLAY = ['abstract', 'index_terms', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX']
const finished = new Set(['completed', 'failed', 'cancelled'])

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally { window.setTimeout(() => URL.revokeObjectURL(url), 0) }
}

// The zip's .tex lists at most 20 export notes (D149); the header carries the total.
const LATEX_NOTES_LISTED = 20
const support = reportSupportLabels
const reviewCodes: Record<string, string> = {
  support_broken: 'Support no longer matches', count_error: 'Count', terminology_inconsistent: 'Terminology',
  abstract_body_mismatch: 'Abstract and body differ', equation_mismatch: 'Equation',
  comparability_error: 'Comparability', other: 'Other',
}
const reviewReasons: Record<string, string> = {
  input_too_large: 'the input was too large', budget_exhausted: 'the model-call budget was exhausted',
  nothing_to_review: 'there was nothing it could read',
  model_mismatch: 'the model did not match the selected model', model_call_failed: 'the model call failed',
  invalid_model_output: 'the model output was invalid',
}

function valueText(value: Record<string, unknown> | null, options: { id: string; label: string }[] | null) {
  if (!value) return ''
  if (typeof value.text === 'string') return value.text
  if (typeof value.number === 'number') return [value.number, value.unit].filter(Boolean).join(' ')
  if (value.answer === 'yes' || value.answer === 'no') return t(value.answer === 'yes' ? 'Yes' : 'No')
  if (Array.isArray(value.option_ids)) return value.option_ids.map(id => options?.find(option => option.id === id)?.label ?? id).join(', ')
  return ''
}

export function ReportView({ researchId, reportId, view, title, dark, onClose, onOpenCitation, onChanged, onOpenCandidate }: {
  researchId: string; reportId: string; view: ResearchView; title: string; dark: boolean; onClose: () => void
  onOpenCitation: (passageId: string, highlightText: string | null, expectHighlight: boolean) => void
  onChanged: () => Promise<void>
  onOpenCandidate: (candidate: CandidateSelection) => void
}) {
  const toast = useToast()
  const [report, setReport] = useState<ReportDetail | null>(null)
  const [error, setError] = useState('')
  const [evidenceView, setEvidenceView] = useState(false)
  const [reviewMode, setReviewMode] = useState(false)
  const [requestReview, setRequestReview] = useState(false)
  const reviewList = useReviewList(researchId, 'report', reportId, view.last_event_id)
  const reviewsButton = useRef<HTMLButtonElement>(null), scrollRoot = useRef<HTMLDivElement>(null), documentScroll = useRef(0)
  const [applying, setApplying] = useState<{ reviewId: string; finding: ReviewFindingRow; claim: ReportClaim } | null>(null)
  const mode = (on: boolean, request = false) => {
    if (on && !reviewMode) documentScroll.current = scrollRoot.current?.scrollTop ?? 0
    setRequestReview(request); setReviewMode(on)
    requestAnimationFrame(() => {
      if (scrollRoot.current) scrollRoot.current.scrollTop = on ? 0 : documentScroll.current
      if (!on) reviewsButton.current?.focus({ preventScroll: true })
    })
  }
  const [editing, setEditing] = useState<string | null>(null)
  const [editError, setEditError] = useState('')
  const [busy, setBusy] = useState(false)
  const [conflicts, setConflicts] = useState(0)
  const [exportBusy, setExportBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const seq = useRef(0), applied = useRef(0), live = useRef(true)
  const current = useRef<ReportDetail | null>(null)
  const mutating = useRef(false)
  const documentRoot = useRef<HTMLElement>(null)
  const claimFocus = useReturnFocus()
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const refresh = useCallback(() => {
    const ticket = ++seq.current
    return api.report(researchId, reportId).then(next => {
      if (live.current && ticket > applied.current) {
        applied.current = ticket; current.current = next; setReport(next); setError('')
      }
      return live.current ? current.current : null
    }, e => {
      if (live.current && ticket > applied.current) setError(e instanceof Error ? e.message : String(e))
      return null
    })
  }, [researchId, reportId])
  useEffect(() => {
    void refresh()
  }, [refresh, view.last_event_id])
  const applyMutation = (next: ReportDetail) => {
    if (!live.current) return
    // Stamp completion, not mutation start: reads begun during the write can still contain the old state.
    applied.current = ++seq.current; current.current = next; setReport(next); setError('')
  }
  const rememberClaim = (claimId: string) => {
    const resolve = () => documentRoot.current?.querySelector<HTMLButtonElement>(`[data-edit-claim="${CSS.escape(claimId)}"]`) ?? null
    const opener = resolve()
    if (opener) claimFocus.rememberFocus(opener, resolve)
  }
  // Focus moves to the opener while the form still holds it: removing the focused field first lets the modal pull focus to the sheet.
  const focusOpener = () => { const opener = claimFocus.returnFocus.current; if (opener?.isConnected) opener.focus({ preventScroll: true }) }
  const closeEdit = () => { focusOpener(); setEditing(null); setApplying(null); claimFocus.restoreFocus() }
  const openApply = async (reviewId: string, findingId: string) => {
    const [review, next] = await Promise.all([api.review(researchId, reviewId), api.report(researchId, reportId)])
    const finding = review.findings.find(f => f.id === findingId)
    const claim = next.sections.flatMap(s => s.claims).find(c => c.id === finding?.finding.target.record_id)
    if (!finding?.dependency_fingerprint || !claim) throw new Error(t('The claim is no longer available in this report.'))
    applyMutation(next); setEvidenceView(true); setEditing(claim.id); setApplying({ reviewId, finding, claim }); mode(false)
    requestAnimationFrame(() => {
      documentRoot.current?.querySelector(`[data-claim-key="${CSS.escape(claim.claim_key)}"]`)?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
      rememberClaim(claim.id)
      documentRoot.current?.querySelector<HTMLTextAreaElement>('.evidence-report-edit textarea')?.focus({ preventScroll: true })
    })
  }
  const markdown = async (action: 'copy' | 'download') => {
    setExportBusy(true)
    try {
      const { text, filename } = await api.reportMarkdown(researchId, reportId)
      if (action === 'copy') {
        await navigator.clipboard.writeText(text)
        toast('success', t('Markdown copied.'))
      } else {
        saveBlob(new Blob([text], { type: 'text/markdown' }), filename)
        toast('success', t('Markdown downloaded.'))
      }
    } catch (e) { toast('error', e instanceof Error ? e.message : String(e)) }
    finally { setExportBusy(false) }
  }
  const latex = async () => {
    setExportBusy(true)
    try {
      const { blob, filename, notes } = await api.reportLatex(researchId, reportId)
      saveBlob(blob, filename)
      if (notes === 0) toast('success', t('LaTeX downloaded: a zip with the .tex and .bib files.'))
      else toast('warning', notes === 1 ? t('LaTeX downloaded with 1 export note. It is listed in a comment block at the top of the .tex file.')
        : notes > LATEX_NOTES_LISTED ? t('LaTeX downloaded with {n} export notes. The first 20 are listed in a comment block at the top of the .tex file.', { n: notes })
        : t('LaTeX downloaded with {n} export notes. They are listed in a comment block at the top of the .tex file.', { n: notes }))
    } catch (e) { toast('error', e instanceof Error ? e.message : String(e)) }
    finally { setExportBusy(false) }
  }
  const save = async (claim: ReportClaim, body: ClaimEditBody, expectedVersion = claim.version) => {
    if (mutating.current) return
    mutating.current = true
    let formError = false, conflict = false, succeeded = false
    let confirming: Promise<ReportDetail | null> | null = null
    rememberClaim(claim.id)
    setBusy(true); setEditError('')
    try {
      const next = await api.editReportClaim(researchId, reportId, claim.id, { ...body, expected_version: expectedVersion })
      if (!live.current) return
      applyMutation(next)
      focusOpener()
      setEditing(null)
      succeeded = true
      claimFocus.restoreFocus()
      confirming = refresh()
      const keptIds = body.link_ids
      const removed = keptIds ? claim.evidence.filter(link => !keptIds.includes(link.link_id)).length : 0
      const removal = t(removed === 1 ? '{n} citation removed from this sentence' : '{n} citations removed from this sentence', { n: removed })
      toast('success', body.restore_from ? t('Version restored with its text and citations.') : removed
        ? t('Claim saved. {change}; the edit was not checked.', { change: body.text !== undefined ? t('text changed and {removal}', { removal }) : removal })
        : t('Claim saved. The new text was not checked.'))
      await onChanged()
    } catch (e) {
      if (!live.current) return
      if (e instanceof ApiError && e.status === 409) {
        conflict = true
        toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message }))
      } else if (e instanceof ApiError && e.status === 422 && body.restore_from === undefined) { formError = true; setEditError(e.message) }
      else toast('error', e instanceof Error ? e.message : String(e))
    } finally {
      if (live.current && !formError) {
        const recovered = await (confirming ?? refresh())
        if (live.current && conflict && recovered) setConflicts(n => n + 1)
      }
      mutating.current = false
      if (live.current) { setBusy(false); if (succeeded) claimFocus.restoreFocus() }
    }
  }
  const acknowledge = async (section: ReportSection) => {
    if (mutating.current) return
    mutating.current = true
    let confirming: Promise<ReportDetail | null> | null = null
    setBusy(true)
    try {
      const next = await api.acknowledgeReportChanges(researchId, reportId, section.section_id, section.evidence_changes.open.map(change => change.key))
      if (!live.current) return
      applyMutation(next)
      confirming = refresh()
      toast('success', t('Marked as seen for this section. A later change marks it again.'))
      await onChanged()
    } catch (e) {
      if (!live.current) return
      if (e instanceof ApiError && e.status === 409) toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message }))
      else toast('error', e instanceof Error ? e.message : String(e))
    } finally { if (live.current) await (confirming ?? refresh()); mutating.current = false; if (live.current) setBusy(false) }
  }
  const check = async () => {
    if (mutating.current) return
    mutating.current = true; setBusy(true); setChecking(true)
    let confirming: Promise<ReportDetail | null> | null = null
    try {
      const next = await api.checkReportEdits(researchId, reportId)
      if (!live.current) return
      applyMutation(next)
      confirming = refresh()
      if (next.edit_check) toast('success', t('Check recorded: {errors}, {warnings}. Whether the cited evidence supports each sentence was not checked.', checkCounts(next.edit_check.errors, next.edit_check.warnings)))
      await onChanged()
    } catch (e) {
      if (!live.current) return
      if (e instanceof ApiError && e.status === 409) toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message }))
      else toast('error', e instanceof Error ? e.message : String(e))
    } finally { if (live.current) await (confirming ?? refresh()); mutating.current = false; if (live.current) { setBusy(false); setChecking(false) } }
  }
  const refs = new Map(report?.references.map(ref => [ref.number, ref]) ?? [])
  const cited = (link: ReportLink) => {
    // A cell link opens the evidence passage whose quote holds the located anchor; an older link without a located
    // anchor opens the cell's first evidence passage without a mark.
    const passage = link.open_passage_id ?? report?.table_i?.cells.find(cell => cell.cell_id === link.cell_id)?.evidence_passage_ids[0]
    if (passage) onOpenCitation(passage, link.anchor_match && link.open_passage_id ? link.anchor_text : null, true)
  }
  const allLinks = report?.sections.flatMap(section => section.claims.flatMap(claim => claim.evidence)) ?? []
  const located = allLinks.filter(link => link.anchor_match !== null).length
  const removedClaims = report?.sections.flatMap(section => section.claims).filter(claim => claim.evidence_basis === 'none' && claim.support_type_note !== null).length ?? 0
  const sourceName = (sourceVersionId: string) => {
    const ref = report?.references.find(item => item.source_version_id === sourceVersionId)
    const row = report?.table_i?.rows.find(item => item.source_version_id === sourceVersionId)
    return ref?.source_key || ref?.title || row?.source_key || row?.title || sourceVersionId
  }
  const anchorNote = !allLinks.length && removedClaims ? t('No citation anchors remain after citations were removed by hand.')
    : located === allLinks.length ? t('Anchors were located in the cited passages or cells.')
    : t('{n} of {m} citation anchors were located in their passages or cells; the others open without a mark.', { n: located, m: allLinks.length })
  const labels = (id: string) => HEADINGS[id]?.[report?.language === 'tr' ? 1 : 0] ?? id
  const review = report?.review
  const reviewNote = !review
    ? t('No model or person review is recorded for this report; whether each passage supports its claim was not checked by code.')
    : review.status === 'not_reviewed'
      ? t('No accepted review result exists for this report ({reason}); whether the model read it in part is not established by this record.', { reason: t(reviewReasons[review.reason] ?? 'the review step failed') })
      : [t(review.findings.length === 1
          ? 'A model read the claims of {n} of {m} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged {k} possible problem. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code.'
          : 'A model read the claims of {n} of {m} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged {k} possible problems. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code.',
          { n: review.sections_reviewed.length, m: review.sections_reviewed.length + review.sections_not_reviewed.length, k: review.findings.length }),
        review.reverted.length ? t(review.reverted.length === 1
          ? 'The model flagged {r} rewritten sentence as possibly no longer matching its sources; it was returned to its original wording.'
          : 'The model flagged {r} rewritten sentences as possibly no longer matching their sources; they were returned to their original wording.', { r: review.reverted.length }) : '',
        review.sections_not_reviewed.length ? t('Not read: {sections}.', { sections: review.sections_not_reviewed.map(item => labels(item.section_id)).join(', ') }) : '', t("The review covers the model's base version; human edits were not reviewed.")].filter(Boolean).join(' ')
  const exportBlocked = !report || !finished.has(report.run?.status ?? '') || report.status === 'in_progress'
  const reviewUnavailable = !report || !finished.has(report.run?.status ?? '') || !['valid', 'draft'].includes(report.status)
    ? t('A report can be reviewed once its run has finished.') : ''
  const equationNumbers = new Map<string, number>()
  for (const id of DISPLAY) for (const claim of report?.sections.find(section => section.section_id === id)?.claims ?? [])
    if (claim.equation_ref && !equationNumbers.has(claim.equation_ref)) equationNumbers.set(claim.equation_ref, equationNumbers.size + 1)
  const table = report?.table_i
  const tableNode = table && <div className="evidence-report-table-scroll" tabIndex={0} role="region" aria-label={t('Evidence table, scrolls sideways')}><table className="evidence-report-table"><caption>{t(table.columns.length === 1 ? 'TABLE I. Evidence table as frozen for this report ({rows} sources, 1 column).' : 'TABLE I. Evidence table as frozen for this report ({rows} sources, {columns} columns).', { rows: table.rows.length, columns: table.columns.length })}</caption><thead><tr><th>{t('Source')}</th>{table.columns.map(column => <th key={column.column_id}>{column.name}</th>)}</tr></thead><tbody>{table.rows.map(row => <tr key={row.source_version_id}><th>{row.ref_number ? `[${row.ref_number}] ` : ''}{row.source_key ?? row.title ?? t('Source record unavailable')}</th>{table.columns.map(column => {
    const cell = table.cells.find(item => item.source_version_id === row.source_version_id && item.column_id === column.column_id)
    return <td key={column.column_id}>{cell ? cell.state === 'value' ? valueText(cell.value, column.options) : cell.state === 'not_verified' ? t('{value} (not verified: no quote linked)', { value: valueText(cell.value, column.options) }) : t(cell.state.replaceAll('_', ' ')) : '—'}</td>
  })}</tr>)}</tbody></table></div>
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet report-sheet ${dark ? 'dark' : ''}`}>
    <SheetHeader className="report-toolbar"><div className="report-toolbar-title"><FileText size={17} aria-hidden /><SheetTitle>{title}</SheetTitle></div><SheetDescription className="sr-only">{t('Evidence report')}</SheetDescription><div className="report-toolbar-actions"><Button ref={reviewsButton} variant="ghost" size="sm" aria-label={t('Reviews, {n}', { n: reviewList.reviews.length })} aria-pressed={reviewMode} onClick={() => mode(!reviewMode)}>{t('Reviews')} <span className="research-tab-count" aria-hidden>{reviewList.reviews.length}</span></Button><Button variant="ghost" size="sm" aria-pressed={evidenceView} onClick={() => setEvidenceView(on => !on)}><Quote size={14} aria-hidden />{t('Evidence view')}</Button><Button variant="ghost" size="sm" disabled={exportBlocked || exportBusy} title={exportBlocked ? t('A report can be exported once its run has finished.') : undefined} aria-label={t('Copy Markdown')} onClick={() => void markdown('copy')}><Copy size={14} aria-hidden /><span className="report-export-label">{t('Copy Markdown')}</span></Button><Button variant="ghost" size="sm" disabled={exportBlocked || exportBusy} title={exportBlocked ? t('A report can be exported once its run has finished.') : undefined} aria-label={t('Download .md')} onClick={() => void markdown('download')}><Download size={14} aria-hidden /><span className="report-export-label">{t('Download .md')}</span></Button><Button variant="ghost" size="sm" disabled={exportBlocked || exportBusy} title={exportBlocked ? t('A report can be exported once its run has finished.') : undefined} aria-label={t('Download LaTeX')} onClick={() => void latex()}><FileCode size={14} aria-hidden /><span className="report-export-label">{t('Download LaTeX')}</span></Button></div></SheetHeader>
    <div className="report-scroll" ref={scrollRoot}>
    {reviewMode && <ReviewPane researchId={researchId} targetKind="report" targetId={reportId} version={report?.report_version ?? 0} eventCursor={view.last_event_id} runActive={view.runs.some(run => ['queued', 'running', 'pause_requested'].includes(run.status))} unavailableReason={reviewUnavailable} sources={view.sources} sectionLabel={labels} showRequest={requestReview} open={(id, anchor) => onOpenCitation(id, anchor, true)} changed={async () => { await reviewList.refresh(); await onChanged() }} apply={openApply} />}
    <article ref={documentRoot} hidden={reviewMode} className="report-document evidence-report-document">
      {error && <Notice tone="error">{error}</Notice>}
      {!report ? <p>{t('Loading report…')}</p> : <>
        <header className="report-document-head"><p>{report.status === 'valid' ? t('Evidence report · V{n}', { n: report.report_version ?? '' }) : report.status === 'draft' ? (report.sections.every(section => section.status === 'valid') && reportAssemblyDraftText(report.run?.error)) || t('DRAFT: {n} sections not validated', { n: report.sections.filter(section => section.status !== 'valid').length }) : t('Evidence report · being written')}</p><h1>{title}</h1><time>{new Date(report.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time>
          <ReviewSummary reviews={reviewList.reviews} open={() => mode(true)} /><button type="button" className="review-entry" disabled={Boolean(reviewUnavailable)} aria-describedby={reviewUnavailable ? `report-review-unavailable-${reportId}` : undefined} onClick={() => mode(true, true)}>{t('Review with another model')}</button>
          {reviewUnavailable && <p id={`report-review-unavailable-${reportId}`}>{reviewUnavailable}</p>}
          <EditCheckPanel report={report} finished={finished.has(report.run?.status ?? '')} busy={busy} checking={checking} labels={labels} onCheck={() => void check()} />{report.run?.status === 'paused' && <p role="status">{t('Paused: {reason}', { reason: pauseReasonText(report.run.pause_reason) || t('Report paused') })}</p>}</header>
        {report.missing_rows && <Notice tone="attention">
          <p>{t('{n} of {m} sources did not complete the table (missing cells: {cells}). These rows were excluded from the report’s evidence assessment and aggregation denominators.', { n: report.missing_rows.counts.failed, m: report.missing_rows.counts.included, cells: report.missing_rows.counts.cells_missing })}</p>
          <ul>{report.missing_rows.failed_rows.map(row => <li key={row.source_version_id}>{row.source_key || row.title}: {failedRowReasonText(row.reason)}</li>)}</ul>
        </Notice>}
        {report.evidence_changes.any && <Notice tone="attention">{t('Evidence changed after this report:')} {[
          report.evidence_changes.changed_cells && t(report.evidence_changes.changed_cells === 1 ? '{n} cell changed' : '{n} cells changed', { n: report.evidence_changes.changed_cells }),
          report.evidence_changes.removed_sources && t(report.evidence_changes.removed_sources === 1 ? '{n} source left' : '{n} sources left', { n: report.evidence_changes.removed_sources }),
          report.evidence_changes.added_sources && t(report.evidence_changes.added_sources === 1 ? '{n} source added' : '{n} sources added', { n: report.evidence_changes.added_sources }),
          report.evidence_changes.revised_columns && t(report.evidence_changes.revised_columns === 1 ? '{n} column revised' : '{n} columns revised', { n: report.evidence_changes.revised_columns }),
        ].filter(Boolean).join(', ')}. {t('The report text was not changed. Passage text was not checked.')}</Notice>}
        <PassageFreshnessNotice freshness={report.passage_freshness} />
        <div className="report-content evidence-report-content">{DISPLAY.map(id => {
          const section = report.sections.find(item => item.section_id === id)
          if (!section) return null
          const paragraphs = [...new Set(section.claims.map(claim => claim.paragraph))]
          const hasTableRef = section.claims.some(claim => claim.table_ref === 'TABLE_I')
          const firstTableParagraph = section.claims.find(claim => claim.table_ref === 'TABLE_I')?.paragraph
          const changes = section.evidence_changes.open
          const reasons = [...new Set(changes.map(change => `${t(reportChangeLabels[change.kind] ?? change.kind)} ${change.via !== 'citation' ? t(reportChangeViaLabels[change.via] ?? change.via) : ''}`.trim()))]
          return <section className="evidence-report-section" key={id}><h2>{labels(id)}</h2>
            {changes.length > 0 && <div className="evidence-report-changes"><Notice tone="attention">{t('This section rests on evidence that changed after this report:')} {reasons.join('; ')}.</Notice>{evidenceView && <ul>{changes.map(change => <li key={change.key}>{t(reportChangeLabels[change.kind] ?? change.kind)} · {report.references.find(ref => ref.source_version_id === change.source_version_id)?.source_key ?? ''} · {table?.columns.find(column => column.column_id === change.column_id)?.name ?? ''}</li>)}</ul>}<Button size="sm" variant="outline" disabled={busy} onClick={() => void acknowledge(section)}>{t('Keep as is')}</Button></div>}
            {evidenceView && section.evidence_changes.acknowledged_count > 0 && <small>{t('{n} earlier changes kept as is.', { n: section.evidence_changes.acknowledged_count })}</small>}
            {(section.status === 'draft' || section.status === 'failed') && <Notice tone="attention">{section.validation?.issues?.[0]?.code ? t('This section was not validated and must be written again: {reason}.', { reason: failedSectionReasonText(section.validation.issues[0].code) }) : t('This section was not validated and must be written again.')}</Notice>}
            {id === 'VI' && <p className="evidence-report-fine">{t('Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.')}</p>}
            {id === 'IV' && !hasTableRef && tableNode}
            {(id === 'II' || id === 'VIII') && section.draft?.text && <p className="evidence-report-paragraph"><MathText text={section.draft.text} /></p>}
            {paragraphs.map(number => <div key={number} className="evidence-report-paragraph-group"><p className="evidence-report-paragraph">{section.claims.filter(claim => claim.paragraph === number).map((claim, i) => {
              const unique = claim.evidence.filter((link, i, all) => all.findIndex(other => other.ref_number === link.ref_number) === i)  // first link per number
              return <span key={claim.id}>{i > 0 && ' '}<MathText text={claim.text} />{claim.equation_ref && <span className="evidence-report-equation">({equationNumbers.get(claim.equation_ref)})</span>}{claim.evidence_basis === 'none' && claim.support_type_note !== null && <span className="evidence-report-no-citation"> {t('(no direct citation)')}</span>}{unique.map((link, j) => {
                const ref = refs.get(link.ref_number)
                const possible = Boolean(link.passage_id || table?.cells.some(cell => cell.cell_id === link.cell_id && cell.evidence_passage_ids.length))
                return <span key={link.ref_number}>{j > 0 && ', '}<button type="button" className="cite-chip" disabled={!possible} title={possible ? undefined : t('No stored evidence passage can be opened for this citation.')} aria-label={t('Reference {n}: {title}', { n: link.ref_number, title: ref?.title ?? '' })} onClick={() => cited(link)}>[{link.ref_number}]</button></span>
              })}</span>
            })}</p>{evidenceView && section.claims.filter(claim => claim.paragraph === number).map(claim => {
              const editReason = !finished.has(report.run?.status ?? '') ? t('A report can be edited once its run has finished.') : busy ? t('An operation is in progress.') : ''
              const editReasonId = `report-edit-reason-${claim.id}`
              return <div className="evidence-report-claim-meta" data-claim-key={claim.claim_key} key={claim.id}>
                <span data-stored-text>{claim.claim_key}</span>
                <span>{claim.support_type_note === 'model_written_type' ? t('{type} (type as the model wrote it; its citations were removed)', { type: t(support[claim.support_type]) }) : t(support[claim.support_type])}</span>
                {claim.edited && <strong>{t('Edited by you')}</strong>}
                {claim.edited_basis.length > 0 && <p>{t(claim.edited_basis.length === 1 ? 'Rests on edited claim {keys}.' : 'Rests on edited claims {keys}.', { keys: claim.edited_basis.join(', ') })} {claim.text === claim.model_text && t('This sentence was not changed.')}</p>}
                {claim.warnings.map((warning, i) => <span key={i}>{t(warning.kind === 'math_not_well_formed' ? 'A formula may be malformed: {detail}' : 'The count was not checked again after the edit.', { detail: warning.detail ?? '' })}</span>)}
                {claim.evidence_basis === 'none' && <p>{t('No direct citation.')}</p>}
                <div>{claim.evidence.map(link => <button type="button" key={link.link_id} data-link-id={link.link_id} title={link.anchor_text ?? ''} onClick={() => cited(link)}><span data-stored-text>[{link.ref_number}] {refs.get(link.ref_number)?.source_key} · {(link.anchor_text ?? '').slice(0, 120)}{(link.anchor_text?.length ?? 0) > 120 ? '…' : ''}</span></button>)}</div>
                {claim.removed_links.length > 0 && <details className="evidence-report-removed">
                  <summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Citations removed by hand ({n} of {m})', { n: claim.removed_links.length, m: claim.original_evidence_count })}</summary>
                  <ul>{claim.removed_links.map(link => <li key={link.link_id} data-stored-text>[{link.source_key || link.title || link.source_version_id}] · {link.anchor_text}</li>)}</ul>
                  <p>{t('History can bring them back.')}</p>
                </details>}
                <Button variant="ghost" size="sm" data-edit-claim={claim.id} disabled={Boolean(editReason)} focusableWhenDisabled aria-describedby={editReason ? editReasonId : undefined} title={!finished.has(report.run?.status ?? '') ? t('A report can be edited once its run has finished.') : undefined} onClick={() => { rememberClaim(claim.id); setEditing(claim.id); setEditError('') }}>{t('Edit')}</Button>
                {editReason && <p id={editReasonId}>{editReason}</p>}
                <ClaimHistory claim={claim} createdAt={report.created_at} busy={busy} restore={from => void save(claim, { restore_from: from })} />
                {editing === claim.id && (applying ? <ApplyEditor key={`${applying.reviewId}:${applying.finding.id}`} researchId={researchId} reportId={reportId} reviewId={applying.reviewId} finding={applying.finding} claim={applying.claim} sourceName={sourceName} cancel={closeEdit} refreshed={applyMutation} saved={async next => { applyMutation(next); closeEdit(); await reviewList.refresh(); await onChanged() }} /> : <ClaimEdit claim={claim} conflicts={conflicts} busy={busy} error={editError} cancel={closeEdit} sourceName={sourceName} save={(body, expectedVersion) => void save(claim, body, expectedVersion)} />)}
              </div>
            })}{id === 'IV' && firstTableParagraph === number && tableNode}</div>)}
            {!section.claims.length && !section.draft?.text && (section.draft?.insufficient_evidence?.length ? section.draft.insufficient_evidence.map((entry, index) => <p key={index}>{t('Not enough evidence: {reason}', { reason: entry.reason })}</p>) : <p>{t('No text was written for this section.')}</p>)}
            {id === 'VI' && <ReportAspects researchId={researchId} reportId={reportId} eventCursor={view.last_event_id} valid={section.status === 'valid'} onOpen={onOpenCandidate} />}
          </section>
        })}<section className="evidence-report-section"><h2>{labels('references')}</h2><ol className="evidence-report-references">{report.references.map(ref => <li key={ref.number}><span>[{ref.number}] {ref.authors.join(', ')}{ref.authors.length ? ', ' : ''}</span>{ref.open_passage_id ? <button type="button" onClick={() => onOpenCitation(ref.open_passage_id!, null, false)}>{ref.title}</button> : ref.title}{ref.venue ? `, ${ref.venue}` : ''}{ref.year ? `, ${ref.year}` : ''}</li>)}</ol></section></div>
        <p className="evidence-report-provenance">{anchorNote} {removedClaims > 0 && t(removedClaims === 1 ? '1 claim has no direct citation after citations were removed by hand.' : '{n} claims have no direct citations after citations were removed by hand.', { n: removedClaims })} {t('Claim check (automatic; it can return a rewritten sentence to its original wording):')} {reviewNote}</p>
        {review?.status === 'reviewed' && review.findings.length > 0 && <details className="evidence-report-history"><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Review findings ({k})', { k: review.findings.length })}</summary><p>{t('Model findings')}</p><ul>{review.findings.map((finding, index) => <li key={index}>{finding.section_id ? labels(finding.section_id) : t('Report')} · {t(reviewCodes[finding.code] ?? 'Other')} · {finding.text}</li>)}</ul></details>}
      </>}
    </article></div>
  </SheetContent></Sheet>
}
