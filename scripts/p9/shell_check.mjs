// P9 H1 shell check: does the served UI render its home screen's question box in system Chrome?
//
// Usage: node shell_check.mjs <export dir> <url> <screenshot path>
// Loads Playwright from the exported checkout, aborts every request whose origin is not the served one, opens the
// URL, waits up to 30 s for the "Research question" box and prints one JSON line. Exit 0 only when the box showed.
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'

const [exportDir, url, screenshot] = process.argv.slice(2)
if (!exportDir || !url || !screenshot) {
  console.log(JSON.stringify({ ok: false, error: 'usage: shell_check.mjs <export dir> <url> <screenshot path>' }))
  process.exit(2)
}

const started = Date.now()
const origin = new URL(url).origin
const launchArgs = ['--use-mock-keychain']
const result = {
  ok: false,
  title: null,
  external_requests_blocked: 0,
  blocked_origins: [],
  console_errors: 0,
  launch_args: launchArgs,
  seconds: 0,
}

let browser
try {
  const require = createRequire(path.join(exportDir, 'apps/web/package.json'))
  const { chromium } = require('@playwright/test')
  browser = await chromium.launch({ channel: 'chrome', headless: true, args: launchArgs })
  const context = await browser.newContext()
  await context.route('**/*', (route) => {
    const target = route.request().url()
    if (target.startsWith(origin + '/') || target.startsWith('data:') || target.startsWith('blob:')) return route.continue()
    result.external_requests_blocked += 1
    const other = new URL(target).origin
    if (!result.blocked_origins.includes(other)) result.blocked_origins.push(other)
    return route.abort()
  })
  const page = await context.newPage()
  page.on('console', (message) => {
    if (message.type() === 'error') result.console_errors += 1
  })
  page.on('pageerror', () => {
    result.console_errors += 1
  })
  await page.goto(url, { waitUntil: 'load', timeout: 30000 })
  result.title = await page.title()
  try {
    await page.getByLabel('Research question').first().waitFor({ state: 'visible', timeout: 30000 })
    result.ok = true
  } catch (error) {
    result.error = 'question box not visible: ' + String(error.message).split('\n')[0]
  }
  await page.screenshot({ path: screenshot }).catch(() => {})
} catch (error) {
  result.error = String(error && error.message ? error.message : error).split('\n')[0]
} finally {
  if (browser) await browser.close().catch(() => {})
  result.seconds = Math.round((Date.now() - started) / 100) / 10
  console.log(JSON.stringify(result))
}
process.exit(result.ok ? 0 : 1)
