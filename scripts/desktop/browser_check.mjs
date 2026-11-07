// Browser-level check of the packaged backend (P10 M2, Sol backlog from M1), run by desktop_acceptance.py:
//
//   node scripts/desktop/browser_check.mjs SIDECAR_BINARY DATA_BASE ENV_JSON     (cwd: web/, for its Playwright)
//
// For Chrome and (when installed for this Playwright) WebKit: start `SIDECAR serve --desktop` with a temp data folder (the control token as the first stdin
// line), load the page and check that every JS and CSS file loads and React renders; switch the theme to dark and the
// language to Turkish through the UI (the session-cookie + header saves), stop the backend with the token, start it
// again on another port (so the page's localStorage is empty: another origin) and check the page comes up dark and in
// Turkish from the backend's preference. Prints one JSON line. SYNTHETIC data only; never port 8765.
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import net from 'node:net'
import path from 'node:path'
import readline from 'node:readline'

const require = createRequire(path.join(process.cwd(), 'package.json'))
const { chromium, webkit } = require('@playwright/test')
const [binary, base, envJson] = process.argv.slice(2)
const env = JSON.parse(envJson)

function freePort() {
  return new Promise(resolve => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port === 8765 ? freePort() : port))
    })
  })
}

async function startBackend(data, token) {
  const port = await freePort()
  writeFileSync(path.join(data, 'desktop-port.json'), JSON.stringify({ port }))
  const child = spawn(binary, ['serve', '--desktop'], {
    env: { ...env, DEIXIS_DATA_DIR: data, DEIXIS_PORT: String(await freePort()) }, stdio: ['pipe', 'pipe', 'ignore'],
  })
  child.stdin.write(`${token}\n`)
  const line = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('no listening line in 90 s')), 90000)
    readline.createInterface({ input: child.stdout }).once('line', text => { clearTimeout(timer); resolve(text) })
  })
  const event = JSON.parse(line)
  if (event.event !== 'listening') throw new Error(`start failed: ${line}`)
  return { child, port: event.port, url: `http://127.0.0.1:${event.port}` }
}

async function stopBackend(backend, token) {
  await fetch(`${backend.url}/api/internal/shutdown`, { method: 'POST', headers: { 'X-Deixis-Control': token } })
  await new Promise(resolve => backend.child.exitCode !== null ? resolve() : backend.child.once('exit', resolve))
  return backend.child.exitCode
}

async function openPage(engine, url) {
  const browser = await engine.launch(engine.options)
  const page = await browser.newPage()
  const assets = []
  page.on('response', response => {
    if (/\.(js|css)(\?|$)/.test(response.url())) assets.push({ url: response.url(), status: response.status() })
  })
  const failed = []
  page.on('requestfailed', request => failed.push(request.url()))
  await page.goto(url)
  await page.locator('#root > *').first().waitFor({ timeout: 30000 })
  await page.getByRole('button', { name: 'New research' }).or(page.getByRole('link', { name: 'New research' })).first()
    .waitFor({ timeout: 30000 }).catch(() => {})
  return { browser, page, assets, failed }
}

async function preferences(url) {
  return (await fetch(`${url}/api/settings/preferences`)).json()
}

async function check(name, engine, facts) {
  const data = path.join(base, name)
  mkdirSync(data, { recursive: true })
  const token = randomBytes(16).toString('hex')
  const first = await startBackend(data, token)
  facts.first_port = first.port
  try {
    const { browser, page, assets, failed } = await openPage(engine, `${first.url}/`)
    facts.assets = assets.length
    facts.assets_ok = assets.length > 0 && assets.every(a => a.status === 200)
    facts.failed_requests = failed.slice(0, 5)
    facts.react = await page.locator('#root > *').count() > 0
    facts.step = 'theme'
    if (!(await page.locator('html').evaluate(el => el.classList.contains('dark')))) {
      await page.getByRole('button', { name: 'Switch to dark mode', exact: true }).click()
    }
    facts.step = 'settings'
    await page.goto(`${first.url}/#/settings/general`)  // the tab that holds the language row
    facts.step = 'language'
    await page.getByRole('group', { name: 'Interface language' }).getByRole('button', { name: 'Türkçe' }).click()
    facts.step = 'saved'

    for (let i = 0; i < 50; i++) {
      const saved = await preferences(first.url)
      if (saved.language === 'tr' && saved.theme === 'dark') break
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    facts.saved = await preferences(first.url)
    await browser.close()
  } finally {
    facts.first_exit = await stopBackend(first, token)
  }
  const second = await startBackend(data, token)
  facts.second_port = second.port
  try {
    const { browser, page } = await openPage(engine, `${second.url}/`)
    await page.waitForFunction(() => document.documentElement.lang === 'tr', null, { timeout: 15000 }).catch(() => {})
    facts.after_restart = await page.locator('html').evaluate(el => ({ lang: el.lang, dark: el.classList.contains('dark') }))
    await browser.close()
  } finally {
    facts.second_exit = await stopBackend(second, token)
  }
  facts.ok = facts.assets_ok && facts.react && facts.failed_requests.length === 0 && facts.saved.language === 'tr'
    && facts.saved.theme === 'dark' && facts.second_port !== facts.first_port && facts.after_restart.lang === 'tr'
    && facts.after_restart.dark && facts.first_exit === 0 && facts.second_exit === 0
  return facts
}

// Chrome as the web suite runs it (channel 'chrome'), and Playwright's WebKit when its build for this Playwright is
// installed. An older WebKit build does not speak this Playwright's protocol (it hangs), so it is not tried; downloading
// one is left to the person (`npx playwright install webkit`). The app's own WKWebView save is the acceptance's
// csrf_save row either way.
const engines = { chromium: { launch: options => chromium.launch(options), options: { channel: 'chrome' } } }
if (existsSync(webkit.executablePath())) engines.webkit = { launch: options => webkit.launch(options), options: {} }
const out = { webkit_installed: Boolean(engines.webkit) }
for (const [name, engine] of Object.entries(engines)) {
  const facts = {}
  try {
    await check(name, engine, facts)
  } catch (error) {
    facts.ok = false
    facts.error = String(error && error.message || error).split('\n')[0].slice(0, 300)
  }
  out[name] = facts
}
out.ok = out.chromium.ok && (!engines.webkit || out.webkit.ok)
console.log(JSON.stringify(out))
process.exit(0)
