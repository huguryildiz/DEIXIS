// Writes backend/deixis/documents/katex_commands.json: the commands and environments the web app's KaTeX knows (D104).
//
// KaTeX has no public registry, so candidates are the string literals of its own bundle; a command is known when
// rendering it alone does not fail with "Undefined control sequence" (a missing argument is a different error), and an
// environment is known when \begin{x}\end{x} does not fail with "No such environment"; a control symbol (\1, \,)
// the same way as a command. The file carries KaTeX's version.
// Run from the repository root: node scripts/katex_commands.mjs
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(root, 'apps/web/package.json'))
const katex = require('katex')
const bundle = readFileSync(require.resolve('katex/dist/katex.js'), 'utf8')

const literals = new Set()
for (const m of bundle.matchAll(/"((?:\\\\)?[A-Za-z]+\*?)"|'((?:\\\\)?[A-Za-z]+\*?)'/g)) literals.add((m[1] ?? m[2]).replace(/^\\\\/, '\\'))

const commands = new Set()
const environments = new Set()
for (const literal of literals) {
  const name = literal.replace(/^\\/, '')
  if (/^[A-Za-z]+$/.test(name)) {
    try {
      katex.renderToString(`\\${name}`, { throwOnError: true, strict: 'ignore', displayMode: true })
      commands.add(name)
    } catch (e) {
      if (!String(e.message).includes('Undefined control sequence')) commands.add(name)
    }
  }
  try {
    katex.renderToString(`\\begin{${name}}\\end{${name}}`, { throwOnError: true, strict: 'ignore', displayMode: true })
    environments.add(name)
  } catch (e) {
    const message = String(e.message)
    if (!message.includes('No such environment') && !message.includes('Undefined control sequence')) environments.add(name)
  }
}
// Control symbols (a backslash and one printable ASCII character that is not a letter): known unless undefined.
const symbols = []
for (let code = 33; code < 127; code++) {
  const c = String.fromCharCode(code)
  if (/[A-Za-z]/.test(c)) continue
  try {
    katex.renderToString(`\\${c}`, { throwOnError: true, strict: 'ignore', displayMode: true })
    symbols.push(c)
  } catch (e) {
    if (!String(e.message).includes('Undefined control sequence')) symbols.push(c)
  }
}
const out = { katex_version: katex.version, commands: [...commands].sort(), environments: [...environments].sort(), symbols }
writeFileSync(join(root, 'backend/deixis/documents/katex_commands.json'), JSON.stringify(out, null, 1) + '\n')
console.log(`KaTeX ${out.katex_version}: ${out.commands.length} commands, ${out.environments.length} environments, ${out.symbols.length} control symbols`)
