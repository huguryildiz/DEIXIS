import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Quote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, ApiError, type ReportClaim, type ReportDetail, type ReportLink, type ReportSection, type ResearchView } from '../api'
import { MathText } from '../MathText'
import { pauseReasonText, reportChangeLabels, reportChangeViaLabels, reportRevisionLabels, reportSupportLabels } from '../labels'
import { Notice } from '../Notice'
import { t, uiLocale } from '../i18n'
import { useToast } from '../Toast'
import './report.css'

const DISPLAY = ['abstract', 'index_terms', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX']
const HEADINGS: Record<string, [string, string]> = {
  abstract: ['Abstract', 'Özet'], index_terms: ['Index Terms', 'Dizin Terimleri'],
  I: ['I. Introduction', 'I. Giriş'], II: ['II. Review Methodology', 'II. İnceleme Yöntemi'],
  III: ['III. Background and Taxonomy', 'III. Arka Plan ve Sınıflandırma'],
  IV: ['IV. Literature Synthesis', 'IV. Literatür Sentezi'],
  V: ['V. Comparative Findings', 'V. Karşılaştırmalı Bulgular'],
  VI: ['VI. Candidate Unanswered Aspects', 'VI. Cevaplanmamış Yön Adayları'],
  VII: ['VII. Future Directions', 'VII. Gelecek Yönelimler'],
  VIII: ['VIII. Limitations and Threats to Validity', 'VIII. Sınırlılıklar ve Geçerlilik Tehditleri'],
  IX: ['IX. Conclusion', 'IX. Sonuç'], references: ['References', 'Kaynaklar'],
}
const finished = new Set(['completed', 'failed', 'cancelled'])
const support = reportSupportLabels
const revision = reportRevisionLabels

function valueText(value: Record<string, unknown> | null, options: { id: string; label: string }[] | null) {
  if (!value) return ''
  if (typeof value.text === 'string') return value.text
  if (typeof value.number === 'number') return [value.number, value.unit].filter(Boolean).join(' ')
  if (value.answer === 'yes' || value.answer === 'no') return t(value.answer === 'yes' ? 'Yes' : 'No')
  if (Array.isArray(value.option_ids)) return value.option_ids.map(id => options?.find(option => option.id === id)?.label ?? id).join(', ')
  return ''
}

function ClaimEdit({ claim, conflicts, save, cancel, busy, error }: { claim: ReportClaim; conflicts: number; save: (text: string, note: string, expectedVersion: number) => void; cancel: () => void; busy: boolean; error: string }) {
  const [text, setText] = useState(claim.text)
  const [note, setNote] = useState('')
  // The version the draft was written against; after a 409 the person has been shown the latest text, so the kept
  // draft is saved against the version now on screen.
  const [expectedVersion, setExpectedVersion] = useState(claim.version)
  const [seenConflicts, setSeenConflicts] = useState(conflicts)
  if (conflicts !== seenConflicts) { setSeenConflicts(conflicts); setExpectedVersion(claim.version) }
  const field = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { field.current?.focus() }, [])
  return <form className="evidence-report-edit" onSubmit={event => { event.preventDefault(); save(text, note, expectedVersion) }} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); cancel() }
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); save(text, note, expectedVersion) }
  }}>
    <label>{t('Claim text')}<textarea ref={field} value={text} onChange={event => setText(event.target.value)} aria-invalid={Boolean(error)} /></label>
    <label>{t('Edit note (optional)')}<input value={note} onChange={event => setNote(event.target.value)} /></label>
    {error && <p role="alert">{error}</p>}
    <div><Button type="submit" disabled={busy || !text.trim()}>{t('Save')}</Button><Button type="button" variant="outline" onClick={cancel}>{t('Cancel')}</Button></div>
  </form>
}

export function ReportView({ researchId, reportId, view, title, dark, onClose, onOpenCitation, onChanged }: {
  researchId: string; reportId: string; view: ResearchView; title: string; dark: boolean; onClose: () => void
  onOpenCitation: (passageId: string, highlightText: string | null, expectHighlight: boolean) => void
  onChanged: () => Promise<void>
}) {
  const toast = useToast()
  const [report, setReport] = useState<ReportDetail | null>(null)
  const [error, setError] = useState('')
  const [evidenceView, setEvidenceView] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [editError, setEditError] = useState('')
  const [busy, setBusy] = useState(false)
  const [conflicts, setConflicts] = useState(0)
  useEffect(() => {
    let live = true
    api.report(researchId, reportId).then(next => { if (live) { setReport(next); setError('') } }, e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    return () => { live = false }
  }, [researchId, reportId, view.last_event_id])
  const refresh = async () => { const next = await api.report(researchId, reportId); setReport(next) }
  const save = async (claim: ReportClaim, body: { text?: string; note?: string | null; restore_from?: string }, expectedVersion = claim.version) => {
    setBusy(true); setEditError('')
    try {
      setReport(await api.editReportClaim(researchId, reportId, claim.id, { ...body, expected_version: expectedVersion }))
      setEditing(null)
      toast('success', t('Claim saved. Its citations were kept; the new text was not checked.'))
      await onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message }))
        await refresh()
        setConflicts(n => n + 1)
      } else if (e instanceof ApiError && e.status === 422) setEditError(e.message)
      else toast('error', e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  const acknowledge = async (section: ReportSection) => {
    setBusy(true)
    try {
      setReport(await api.acknowledgeReportChanges(researchId, reportId, section.section_id, section.evidence_changes.open.map(change => change.key)))
      toast('success', t('Marked as seen for this section. A later change marks it again.'))
      await onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { toast('warning', t('Not applied: {message}. The page now shows the latest state.', { message: e.message })); await refresh() }
      else toast('error', e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
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
  const labels = (id: string) => HEADINGS[id]?.[report?.language === 'tr' ? 1 : 0] ?? id
  const equationNumbers = new Map<string, number>()
  for (const id of DISPLAY) for (const claim of report?.sections.find(section => section.section_id === id)?.claims ?? [])
    if (claim.equation_ref && !equationNumbers.has(claim.equation_ref)) equationNumbers.set(claim.equation_ref, equationNumbers.size + 1)
  const table = report?.table_i
  const tableNode = table && <div className="evidence-report-table-scroll"><table className="evidence-report-table"><caption>{t(table.columns.length === 1 ? 'TABLE I. Evidence table as frozen for this report ({rows} sources, 1 column).' : 'TABLE I. Evidence table as frozen for this report ({rows} sources, {columns} columns).', { rows: table.rows.length, columns: table.columns.length })}</caption><thead><tr><th>{t('Source')}</th>{table.columns.map(column => <th key={column.column_id}>{column.name}</th>)}</tr></thead><tbody>{table.rows.map(row => <tr key={row.source_version_id}><th>{row.ref_number ? `[${row.ref_number}] ` : ''}{row.source_key ?? row.title ?? t('Source record unavailable')}</th>{table.columns.map(column => {
    const cell = table.cells.find(item => item.source_version_id === row.source_version_id && item.column_id === column.column_id)
    return <td key={column.column_id}>{cell ? cell.state === 'value' ? valueText(cell.value, column.options) : cell.state === 'not_verified' ? t('{value} (not verified: no quote linked)', { value: valueText(cell.value, column.options) }) : t(cell.state.replaceAll('_', ' ')) : '—'}</td>
  })}</tr>)}</tbody></table></div>
  return <Sheet open onOpenChange={open => { if (!open) onClose() }}><SheetContent className={`detail-sheet report-sheet ${dark ? 'dark' : ''}`}>
    <SheetHeader className="report-toolbar"><div className="report-toolbar-title"><FileText size={17} aria-hidden /><SheetTitle>{title}</SheetTitle></div><SheetDescription className="sr-only">{t('Evidence report')}</SheetDescription><div className="report-toolbar-actions"><Button variant="ghost" size="sm" aria-pressed={evidenceView} onClick={() => setEvidenceView(on => !on)}><Quote size={14} aria-hidden />{t('Evidence view')}</Button></div></SheetHeader>
    <div className="report-scroll"><article className="report-document evidence-report-document">
      {error && <Notice tone="error">{error}</Notice>}
      {!report ? <p>{t('Loading report…')}</p> : <>
        <header className="report-document-head"><p>{report.status === 'valid' ? t('Evidence report · V{n}', { n: report.report_version ?? '' }) : report.status === 'draft' ? t('DRAFT: {n} sections not validated', { n: report.sections.filter(section => section.status !== 'valid').length }) : t('Evidence report · being written')}</p><h1>{title}</h1><time>{new Date(report.created_at).toLocaleDateString(uiLocale(), { dateStyle: 'long' })}</time>{report.edited_after_version !== null && <small>{t('Edited by hand after version {n}; edited text was not checked again.', { n: report.edited_after_version })}</small>}{report.run?.status === 'paused' && <p role="status">{t('Paused: {reason}', { reason: pauseReasonText(report.run.pause_reason) || t('Report paused') })}</p>}</header>
        {report.evidence_changes.any && <Notice tone="attention">{t('Evidence changed after this report:')} {[
          report.evidence_changes.changed_cells && t(report.evidence_changes.changed_cells === 1 ? '{n} cell changed' : '{n} cells changed', { n: report.evidence_changes.changed_cells }),
          report.evidence_changes.removed_sources && t(report.evidence_changes.removed_sources === 1 ? '{n} source left' : '{n} sources left', { n: report.evidence_changes.removed_sources }),
          report.evidence_changes.added_sources && t(report.evidence_changes.added_sources === 1 ? '{n} source added' : '{n} sources added', { n: report.evidence_changes.added_sources }),
          report.evidence_changes.revised_columns && t(report.evidence_changes.revised_columns === 1 ? '{n} column revised' : '{n} columns revised', { n: report.evidence_changes.revised_columns }),
        ].filter(Boolean).join(', ')}. {t('The report text was not changed. Passage text was not checked.')}</Notice>}
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
            {(section.status === 'draft' || section.status === 'failed') && <Notice tone="attention">{t('This section was not validated and must be written again.')}</Notice>}
            {id === 'VI' && <p className="evidence-report-fine">{t('Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.')}</p>}
            {id === 'IV' && !hasTableRef && tableNode}
            {(id === 'II' || id === 'VIII') && section.draft?.text && <p className="evidence-report-paragraph"><MathText text={section.draft.text} /></p>}
            {paragraphs.map(number => <div key={number} className="evidence-report-paragraph-group"><p className="evidence-report-paragraph">{section.claims.filter(claim => claim.paragraph === number).map((claim, i) => {
              const unique = claim.evidence.filter((link, i, all) => all.findIndex(other => other.ref_number === link.ref_number) === i)  // first link per number
              return <span key={claim.id}>{i > 0 && ' '}<MathText text={claim.text} />{claim.equation_ref && <span className="evidence-report-equation">({equationNumbers.get(claim.equation_ref)})</span>}{unique.map((link, j) => {
                const ref = refs.get(link.ref_number)
                const possible = Boolean(link.passage_id || table?.cells.some(cell => cell.cell_id === link.cell_id && cell.evidence_passage_ids.length))
                return <span key={link.ref_number}>{j > 0 && ', '}<button type="button" className="cite-chip" disabled={!possible} title={possible ? undefined : t('No stored evidence passage can be opened for this citation.')} aria-label={t('Reference {n}: {title}', { n: link.ref_number, title: ref?.title ?? '' })} onClick={() => cited(link)}>[{link.ref_number}]</button></span>
              })}</span>
            })}</p>{evidenceView && section.claims.filter(claim => claim.paragraph === number).map(claim => <div className="evidence-report-claim-meta" key={claim.id}><span>{t(support[claim.support_type])}</span>{claim.edited && <strong>{t('Edited by you')}</strong>}{claim.warnings.map((warning, i) => <span key={i}>{t(warning.kind === 'math_not_well_formed' ? 'A formula may be malformed: {detail}' : 'The count was not checked again after the edit.', { detail: warning.detail ?? '' })}</span>)}<div>{claim.evidence.map((link, i) => <button type="button" key={i} title={link.anchor_text ?? ''} onClick={() => cited(link)}>[{link.ref_number}] {refs.get(link.ref_number)?.source_key} · {(link.anchor_text ?? '').slice(0, 120)}{(link.anchor_text?.length ?? 0) > 120 ? '…' : ''}</button>)}</div><Button variant="ghost" size="sm" disabled={!finished.has(report.run?.status ?? '') || busy} title={!finished.has(report.run?.status ?? '') ? t('A report can be edited once its run has finished.') : undefined} onClick={() => { setEditing(claim.id); setEditError('') }}>{t('Edit')}</Button>{claim.revisions.length > 0 && <details className="evidence-report-history"><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('History ({n})', { n: claim.revisions.length })}</summary><ol><li><span>{t('Model text')} · {new Date(report.created_at).toLocaleDateString(uiLocale())}</span><p>{claim.model_text}</p>{claim.text !== claim.model_text && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void save(claim, { restore_from: 'model' })}>{t('Restore')}</Button>}</li>{claim.revisions.map(item => <li key={item.id}><span>{t(revision[item.kind] ?? item.kind)} · {new Date(item.created_at).toLocaleDateString(uiLocale())}{item.note ? ` · ${item.note}` : ''}</span><p>{item.text}</p>{claim.text !== item.text && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void save(claim, { restore_from: item.id })}>{t('Restore')}</Button>}</li>)}</ol></details>}{editing === claim.id && <ClaimEdit claim={claim} conflicts={conflicts} busy={busy} error={editError} cancel={() => setEditing(null)} save={(text, note, expectedVersion) => void save(claim, { text, note }, expectedVersion)} />}</div>)}{id === 'IV' && firstTableParagraph === number && tableNode}</div>)}
            {!section.claims.length && !section.draft?.text && (section.draft?.insufficient_evidence?.length ? section.draft.insufficient_evidence.map((entry, index) => <p key={index}>{t('Not enough evidence: {reason}', { reason: entry.reason })}</p>) : <p>{t('No text was written for this section.')}</p>)}
          </section>
        })}<section className="evidence-report-section"><h2>{labels('references')}</h2><ol className="evidence-report-references">{report.references.map(ref => <li key={ref.number}><span>[{ref.number}] {ref.authors.join(', ')}{ref.authors.length ? ', ' : ''}</span>{ref.open_passage_id ? <button type="button" onClick={() => onOpenCitation(ref.open_passage_id!, null, false)}>{ref.title}</button> : ref.title}{ref.venue ? `, ${ref.venue}` : ''}{ref.year ? `, ${ref.year}` : ''}</li>)}</ol></section></div>
        <p className="evidence-report-provenance">{located === allLinks.length ? t('Anchors were located in the cited passages or cells.') : t('{n} of {m} citation anchors were located in their passages or cells; the others open without a mark.', { n: located, m: allLinks.length })} {t('Whether each passage supports its claim was not checked, and this report was not reviewed by a model or a person.')}</p>
      </>}
    </article></div>
  </SheetContent></Sheet>
}
