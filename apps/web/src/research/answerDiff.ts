import type { Answer, Claim, Evidence, Limitation } from '../api'

// The answer diff (UI parity S21, P4/F11): what differs between two stored answer versions of one research, computed in
// the browser from the two records the view already holds. Nothing is inferred: claims are matched by their text
// (whitespace aside; among equal texts, first the one citing the same passages), a claim with the same text is compared by the passages it cites and its stored reading depth, and
// the limits are matched by kind and text. Claim reviews, titles and the other parts are not compared.

export type Basis = NonNullable<Claim['evidence_basis']>
// A reading depth as the badges of the report name it (P3): a claim citing both kinds carries both badges.
export const BASIS_BADGES: Record<Basis, Array<'abstract' | 'full_text'>> = { abstract: ['abstract'], full_text: ['full_text'], mixed: ['abstract', 'full_text'] }

// Which stored answer a version is compared with: the answer a late revision revises (late_revision.py stores it), else
// the nearest earlier valid report version. Only structurally valid answers carry a report version (store.py), so an
// unverified draft is never a comparison base; when the base cannot be used the box says why instead of diffing another.
export type ComparisonBase =
  | { kind: 'ok'; answer: Answer; version: number }
  | { kind: 'first' }
  | { kind: 'unavailable'; version: number | null; reason: 'missing' | 'not_valid' }

export function comparisonBase(shown: Answer, answers: Answer[]): ComparisonBase {
  const late = shown.late_revision
  if (late) {
    const base = answers.find(a => a.id === late.base_answer_id)
    if (!base) return { kind: 'unavailable', version: late.base_report_version, reason: 'missing' }
    if (base.status !== 'structurally_valid' || base.report_version === null) return { kind: 'unavailable', version: late.base_report_version, reason: 'not_valid' }
    return { kind: 'ok', answer: base, version: base.report_version }
  }
  const version = shown.report_version
  if (version === null) return { kind: 'first' }
  let base: Answer | undefined
  for (const a of answers) {
    if (a.id === shown.id || a.status !== 'structurally_valid' || a.report_version === null || a.report_version >= version) continue
    if (!base || a.report_version > base.report_version!) base = a
  }
  return base ? { kind: 'ok', answer: base, version: base.report_version! } : { kind: 'first' }
}

type ClaimChange = {
  added: boolean                                 // no claim of the base has this text
  basis: { from: Basis; to: Basis } | null       // same text; the stored reading depth differs (both answers store it)
  addedPassages: Set<string>                     // passages this claim cites that the base claim of the same text did not
  removedEvidence: Evidence[]                    // passages the base claim of the same text cited and this one does not
}

export type AnswerDiff = {
  claims: Map<string, ClaimChange>               // by the shown answer's claim id; only claims that changed
  removedClaims: Claim[]                         // base claims whose text no claim of the shown answer has
  added: number
  citationChanged: number                        // same text, different cited passages
  basisChanges: { from: Basis; to: Basis; count: number }[]
  // Works the base cited only through abstract passages and the shown answer cites through PDF text (one entry per work).
  fullTextNow: { workId: string; label: string }[]
  limitsAdded: Limitation[]                      // the shown answer's limitations the base does not have
  limitsRemoved: Limitation[]                    // the base's limitations the shown answer does not have
  scopes: { base: number; shown: number } | null // set when the two answers belong to different question revisions
  empty: boolean
}

const norm = (text: string) => text.normalize('NFC').replace(/\s+/g, ' ').trim()
const limitKey = (l: Limitation) => `${l.kind}\u0000${norm(l.text)}`

// Removes one item per match, so two equal texts in one answer match two in the other, not one.
function matcher<T>(items: T[], key: (item: T) => string) {
  const pool = new Map<string, T[]>()
  for (const item of items) { const k = key(item); pool.set(k, [...(pool.get(k) ?? []), item]) }
  return {
    take: (k: string) => { const list = pool.get(k); return list?.length ? list.shift()! : null },
    rest: () => [...pool.values()].flat(),
  }
}

// A claim's text with the set of passages it cites: two claims of the same text that only swap places match their own
// counterparts, so a reordering never reads as changed citations or depth.
const citedKey = (c: Claim) => `${norm(c.text)}\u0000${[...new Set(c.evidence.map(e => e.passage_id))].sort().join('\u0000')}`

// Pairs each shown claim with a base claim: first one of the same text citing the same passages, then, for the claims
// left, one of the same text in order. Each base claim is used once.
function pairClaims(base: Claim[], shown: Claim[]) {
  const exact = matcher(base, citedKey)
  const used = new Set<string>()
  const pairs = new Map<string, Claim>()
  for (const claim of shown) {
    const match = exact.take(citedKey(claim))
    if (match) { pairs.set(claim.id, match); used.add(match.id) }
  }
  const byText = matcher(base.filter(c => !used.has(c.id)), c => norm(c.text))
  for (const claim of shown) {
    if (pairs.has(claim.id)) continue
    const match = byText.take(norm(claim.text))
    if (match) { pairs.set(claim.id, match); used.add(match.id) }
  }
  return { pairs, unmatched: base.filter(c => !used.has(c.id)) }
}

export function diffAnswers(base: Answer, shown: Answer): AnswerDiff {
  const claims = new Map<string, ClaimChange>()
  const { pairs, unmatched } = pairClaims(base.claims, shown.claims)
  let added = 0
  let citationChanged = 0
  const transitions = new Map<string, { from: Basis; to: Basis; count: number }>()
  for (const claim of shown.claims) {
    const before = pairs.get(claim.id)
    if (!before) {
      added += 1
      claims.set(claim.id, { added: true, basis: null, addedPassages: new Set(), removedEvidence: [] })
      continue
    }
    const was = new Set(before.evidence.map(e => e.passage_id))
    const now = new Set(claim.evidence.map(e => e.passage_id))
    const addedPassages = new Set([...now].filter(id => !was.has(id)))
    const removedEvidence = before.evidence.filter((e, i, all) => !now.has(e.passage_id) && all.findIndex(x => x.passage_id === e.passage_id) === i)
    const from = before.evidence_basis, to = claim.evidence_basis
    const basis = from && to && from !== to ? { from, to } : null
    if (!addedPassages.size && !removedEvidence.length && !basis) continue
    if (addedPassages.size || removedEvidence.length) citationChanged += 1
    if (basis) {
      const key = `${basis.from}>${basis.to}`
      transitions.set(key, { ...basis, count: (transitions.get(key)?.count ?? 0) + 1 })
    }
    claims.set(claim.id, { added: false, basis, addedPassages, removedEvidence })
  }
  const removedClaims = unmatched

  // Per work: the passage kinds each answer cites for it.
  const kinds = (answer: Answer) => {
    const byWork = new Map<string, { kinds: Set<string>; label: string }>()
    for (const c of answer.claims) for (const e of c.evidence) {
      const entry = byWork.get(e.work_id) ?? { kinds: new Set<string>(), label: e.source_key ?? e.title }
      entry.kinds.add(e.kind)
      byWork.set(e.work_id, entry)
    }
    return byWork
  }
  const was = kinds(base)
  const fullTextNow = [...kinds(shown)].filter(([work, now]) => {
    const before = was.get(work)
    return before && [...before.kinds].every(k => k === 'abstract') && [...now.kinds].some(k => k !== 'abstract')
  }).map(([workId, now]) => ({ workId, label: now.label }))

  const baseLimits = matcher(base.limitations, limitKey)
  const limitsAdded = shown.limitations.filter(l => !baseLimits.take(limitKey(l)))
  const limitsRemoved = baseLimits.rest()

  const scopes = base.scope_revision !== shown.scope_revision ? { base: base.scope_revision, shown: shown.scope_revision } : null
  return {
    claims, removedClaims, added, citationChanged, basisChanges: [...transitions.values()], fullTextNow, limitsAdded, limitsRemoved, scopes,
    empty: !claims.size && !removedClaims.length && !limitsAdded.length && !limitsRemoved.length,
  }
}
