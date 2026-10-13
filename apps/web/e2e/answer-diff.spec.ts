import { expect, test } from '@playwright/test'
import type { Answer, Claim, Evidence } from '../src/api'
import { comparisonBase, diffAnswers } from '../src/research/answerDiff'

// UI parity S21 (P4/F11): the answer diff as a pure function over two stored answers, run in Node without a browser.
// Every record is SYNTHETIC and built here, so each expected value is written out exactly.

const ev = (passage: string, work: string, kind: Evidence['kind'], key: string | null = work.toUpperCase()): Evidence => ({
  passage_id: passage, source_version_id: `sv-${work}`, work_id: work, source_key: key, kind, physical_page: kind === 'pdf_page' ? 3 : null,
  printed_label: null, reading_depth: kind === 'abstract' ? 'abstract' : 'selected_sections', title: `SYNTHETIC ${work}`, version_label: null,
  anchor_text: null, evidence_status: 'current', text_source: kind === 'abstract' ? null : 'text_layer', removed_from_research: false,
})
const claim = (id: string, text: string, evidence: Evidence[], basis: Claim['evidence_basis'] = null): Claim => ({
  id, label: id, section: 'SYNTHETIC', text, support_type: 'source_stated', semantic_review: '', evidence, review: null, evidence_basis: basis,
})
const answer = (id: string, version: number | null, claims: Claim[], extra: Partial<Answer> = {}): Answer => ({
  id, run_id: `run-${id}`, status: 'structurally_valid', scope_revision: 1, applicability: 'current', answer_language: 'en', created_at: '2026-10-13T00:00:00Z',
  report_version: version, report_title: 'SYNTHETIC', claims, limitations: [], unanswered_aspects: [], capability_notice: null, clarification: null,
  unverified_draft: null, validation: {}, model: null, inputs_given: null, source_text_changed: false, start_snapshot: null, review: null, ...extra,
})

test.describe('answerDiff (S21)', () => {
  test('claims by text, citations, reading depth and limits; nothing else is called a change', () => {
    const base = answer('a1', 1, [
      claim('k1', 'SYNTHETIC kept claim.', [ev('p1', 'w1', 'abstract')], 'abstract'),
      claim('k2', 'SYNTHETIC  upgraded   claim.', [ev('p2', 'w2', 'abstract')], 'abstract'),
      claim('k3', 'SYNTHETIC dropped claim.', [ev('p1', 'w1', 'abstract')], 'abstract'),
      claim('k4', 'SYNTHETIC recited claim.', [ev('p1', 'w1', 'abstract'), ev('p5', 'w3', 'abstract')], 'abstract'),
    ], { limitations: [{ kind: 'scope', text: 'SYNTHETIC old limit.', source_ids: [] }, { kind: 'access', text: 'SYNTHETIC kept limit.', source_ids: [] }] })
    const shown = answer('a2', 2, [
      claim('n1', 'SYNTHETIC kept claim.', [ev('p1', 'w1', 'abstract')], 'abstract'),
      // Whitespace aside the same wording: matched; its passage changed from w2's abstract to w2's PDF page.
      claim('n2', 'SYNTHETIC upgraded claim.', [ev('p3', 'w2', 'pdf_page')], 'full_text'),
      claim('n3', 'SYNTHETIC new claim.', [ev('p3', 'w2', 'pdf_page')], 'full_text'),
      // Same text, one citation swapped for another abstract: a citation change, no depth change.
      claim('n4', 'SYNTHETIC recited claim.', [ev('p1', 'w1', 'abstract'), ev('p6', 'w3', 'abstract')], 'abstract'),
    ], { limitations: [{ kind: 'access', text: 'SYNTHETIC kept limit.', source_ids: [] }, { kind: 'scope', text: 'SYNTHETIC new limit.', source_ids: [] }] })
    const d = diffAnswers(base, shown)
    expect([...d.claims.keys()]).toEqual(['n2', 'n3', 'n4'])
    expect(d.claims.get('n2')).toEqual({ added: false, basis: { from: 'abstract', to: 'full_text' }, addedPassages: new Set(['p3']), removedEvidence: [base.claims[1].evidence[0]] })
    expect(d.claims.get('n3')).toEqual({ added: true, basis: null, addedPassages: new Set(), removedEvidence: [] })
    expect(d.claims.get('n4')).toEqual({ added: false, basis: null, addedPassages: new Set(['p6']), removedEvidence: [base.claims[3].evidence[1]] })
    expect(d.removedClaims.map(c => c.id)).toEqual(['k3'])
    expect([d.added, d.citationChanged]).toEqual([1, 2])
    expect(d.basisChanges).toEqual([{ from: 'abstract', to: 'full_text', count: 1 }])
    expect(d.fullTextNow).toEqual([{ workId: 'w2', label: 'W2' }])
    expect(d.limitsAdded.map(l => l.text)).toEqual(['SYNTHETIC new limit.'])
    expect(d.limitsRemoved.map(l => l.text)).toEqual(['SYNTHETIC old limit.'])
    expect([d.scopes, d.empty]).toEqual([null, false])
  })

  test('identical text with other citations is a citation change only; identical answers are empty', () => {
    const base = answer('a1', 1, [claim('k1', 'SYNTHETIC claim.', [ev('p1', 'w1', 'abstract')])])
    const recited = answer('a2', 2, [claim('n1', 'SYNTHETIC claim.', [ev('p9', 'w9', 'abstract', null)])])
    const d = diffAnswers(base, recited)
    expect([d.added, d.removedClaims.length, d.citationChanged, d.basisChanges.length, d.fullTextNow.length]).toEqual([0, 0, 1, 0, 0])
    // A depth stored on one side only (answers outside the fast path store none) is not a depth change.
    expect(d.claims.get('n1')?.basis).toBeNull()
    const same = diffAnswers(base, answer('a3', 2, [claim('n1', 'SYNTHETIC claim.', [ev('p1', 'w1', 'abstract')])]))
    expect([same.claims.size, same.removedClaims.length, same.empty]).toEqual([0, 0, true])
    // A changed letter is a different text: one claim removed, one added.
    const reworded = diffAnswers(base, answer('a4', 2, [claim('n1', 'SYNTHETIC claim!', [ev('p1', 'w1', 'abstract')])]))
    expect([reworded.added, reworded.removedClaims.length]).toEqual([1, 1])
    // Two claims of the same text match two, not one.
    const twice = diffAnswers(answer('a5', 1, [claim('k1', 'SYNTHETIC twin.', []), claim('k2', 'SYNTHETIC twin.', [])]), answer('a6', 2, [claim('n1', 'SYNTHETIC twin.', [])]))
    expect([twice.added, twice.removedClaims.map(c => c.id)]).toEqual([0, ['k2']])
    // Different question revisions are named.
    expect(diffAnswers(base, answer('a7', 2, base.claims, { scope_revision: 2 })).scopes).toEqual({ base: 1, shown: 2 })
  })

  test('the comparison base is the stored version a late revision revises, else the nearest earlier valid version', () => {
    const v1 = answer('a1', 1, [])
    const draft = answer('d1', null, [], { status: 'unverified_draft' })
    const v2 = answer('a2', 2, [])
    const v3 = answer('a3', 3, [])
    const all = [v3, draft, v2, v1]
    expect(comparisonBase(v3, all)).toEqual({ kind: 'ok', answer: v2, version: 2 })
    expect(comparisonBase(v2, all)).toEqual({ kind: 'ok', answer: v1, version: 1 })
    expect(comparisonBase(v1, all)).toEqual({ kind: 'first' })
    const late = { kind: 'updated_with_full_text' as const, base_answer_id: 'a1', base_report_version: 1, upgraded_sources: 1, late_excluded: 0 }
    expect(comparisonBase(answer('a4', 4, [], { late_revision: late }), all)).toEqual({ kind: 'ok', answer: v1, version: 1 })
    expect(comparisonBase(answer('a4', 4, [], { late_revision: { ...late, base_answer_id: 'gone' } }), all)).toEqual({ kind: 'unavailable', version: 1, reason: 'missing' })
    expect(comparisonBase(answer('a4', 4, [], { late_revision: { ...late, base_answer_id: 'd1', base_report_version: null } }), all)).toEqual({ kind: 'unavailable', version: null, reason: 'not_valid' })
  })
})
