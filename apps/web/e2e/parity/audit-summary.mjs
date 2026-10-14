// Summary of a parity exception audit (gates.ts `audit`, S28): `node e2e/parity/audit-summary.mjs <audit.jsonl>`.
// Lists every entry of exceptions.ts with what the audited run saw: how often a geometry or style exception's difference
// was there, how often a colour exception or copy change applied, how many elements a placement or excluded control
// found. An entry with nothing is printed under "never applied"; whether it is stale is a person's call (a copy change
// or placement can belong to a state the parity surfaces do not open, and is then checked by a behaviour spec).
import { readFileSync } from 'node:fs'
import path from 'node:path'

const file = process.argv[2]
if (!file) throw new Error('usage: node e2e/parity/audit-summary.mjs <audit.jsonl>')
const lines = readFileSync(file, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
const source = readFileSync(path.join(import.meta.dirname, 'exceptions.ts'), 'utf8')

// The ids of one exported array, read from the source text.
function ids(name) {
  const start = source.indexOf(`export const ${name}`)
  if (start < 0) return []
  const end = source.indexOf('\n]\n', start)
  return [...source.slice(start, end).matchAll(/\{ id: '([^']+)'/g)].map(m => m[1])
}

const groups = {
  GEOMETRY_EXCEPTIONS: 'geometry', STYLE_EXCEPTIONS: 'style', COLOUR_EXCEPTIONS: 'colour', COPY_CHANGES: 'copy',
  PLACEMENTS: 'placement', EXCLUDED_MOCK_CONTROLS: 'excluded', DEFERRED_TARGETS: 'excluded', CHECK_ROWS: 'choice', SINGLE_CHOICE: 'choice',
}
const never = []
for (const [name, kind] of Object.entries(groups)) {
  console.log(`\n${name}`)
  for (const id of [...new Set(ids(name))]) {
    const rows = lines.filter(l => l.id === id && (l.kind === kind || (kind === 'choice' && l.kind.startsWith('choice'))))
    let note
    if (kind === 'geometry') {
      const needed = rows.filter(r => r.needed.length)
      const axes = [...new Set(needed.flatMap(r => r.needed))]
      const where = [...new Set(needed.map(r => `${r.pair.replace(/\[\d+\]$/, '')}@${r.width}`))]
      note = rows.length ? `${needed.length}/${rows.length} uses needed it (${axes.join(', ') || 'no axis'})${where.length ? ': ' + where.slice(0, 6).join(' ') : ''}` : ''
      if (rows.length && !needed.length) note = `applied ${rows.length}×, never needed`
    } else if (kind === 'style') {
      const needed = rows.filter(r => r.needed)
      note = rows.length ? `${needed.length}/${rows.length} uses differed` : ''
      if (rows.length && !needed.length) note = `applied ${rows.length}×, never needed`
    } else if (kind === 'colour' || kind === 'copy') {
      note = rows.length ? `applied ${rows.length}× (${[...new Set(rows.map(r => r.pair.replace(/\[\d+\]$/, '')))].slice(0, 4).join(' ')})` : ''
    } else {
      const found = rows.filter(r => r.count > 0)
      const bad = rows.filter(r => r.count < 0)
      note = bad.length ? `INVALID SELECTOR` : found.length ? `found on ${[...new Set(found.map(r => r.surface + (r.kind === 'choice-mock' ? ' (mockup)' : r.kind === 'choice-app' ? ' (app)' : '')))].join(' ')}` : ''
    }
    if (!note || note.startsWith('applied') && note.includes('never needed')) never.push(`${name} ${id}: ${note || 'not seen'}`)
    console.log(`  ${id}: ${note || '—'}`)
  }
}
console.log(`\nnever applied or never needed (${never.length}):\n  ${never.join('\n  ')}`)
