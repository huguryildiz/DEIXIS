// P9 H5 capacity browser steps: what a person waits for in real Chrome on a large synthetic library.
//
// Usage: node capacity_browser.mjs '<json args>'   (capacity.py builds the args and reads the one JSON line printed)
// args: { web, url, researchId, label, expectedSources, steps, timeoutMs, pages?, pdfMarkers? }
//   web      the repository's apps/web folder (Playwright is loaded from its node_modules)
//   label    the research screen's heading text (computed by capacity.py from the same rule ResearchView.tsx uses)
//   steps    any of: k01, k04, k04c-abstract, k04c-pdf, two-tab, pdf
//   pdfMarkers  {work number: unique text of page 1 of its stored PDF}; k04c-pdf waits for the marker of the row it clicked
//
// Every step runs in a fresh browser context (cold JS and HTTP cache) and every request to another origin is aborted and
// counted. Waits poll on animation frames (page.waitForFunction, polling 'raf'), because expect().toHaveText() backs off
// to one-second polls and would add up to a second to a two-second threshold. A step that does not finish inside
// timeoutMs is reported with ok: false, timeout: true and the seconds it waited, never as a missing number; a K01/two-tab
// readiness timeout also carries `readiness` (the two screen conditions, each on its own). After every step the result so far
// is printed as one JSON line, so the last complete line is the result even when the process is killed mid-run.
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { performance } from 'node:perf_hooks'

const args = JSON.parse(process.argv[2] || '{}')
const origin = new URL(args.url).origin
const timeout = args.timeoutMs || 120000
const launchArgs = ['--use-mock-keychain', '--disable-background-networking', '--disable-component-update']
const out = {
  ok: false, steps: {}, external_requests_blocked: 0, blocked_origins: [], console_errors: 0,
  launch_args: launchArgs, chrome_version: null, selectors: {
    k01_title: 'h1.research-title-text[aria-label=<label>] (visible)',
    k01_count: '[data-slot=tabs-trigger] starting "Sources" > .research-tab-count == sources.length of the API response',
    k04b_row: '.source-row (visible)',
    k04a_option: '[role=group][aria-labelledby=qf-group-Sources] [role=option] (visible)',
    k04c_abstract_click: '.source-links button with text "Read abstract" (first)',
    k04c_abstract_stop: '.source-sheet .passage-text (visible)',
    k04c_pdf_click: '.source-asset-actions button.is-primary ("Open PDF", first), then .source-view-tabs button[role=tab] "Plain text"',
    k04c_pdf_stop: '.asset-text-view .pdf-text-page .passage-text containing the unique page-1 marker of the clicked row\'s PDF (args.pdfMarkers[work number in the row title]) (visible)',
    k05_page_input: 'input[aria-label="Page number"]', k05_canvas: '.pdf-viewer canvas',
  },
}

const visible = `(el) => { if (!el) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }`

// canvasInfo(canvas): a sample of 128 evenly spaced pixel rows. dark = sampled pixels that are drawn and not near white
// (blank means too few of them); digest = FNV-1a over every sampled byte, so two different pages differ.
const canvasInfoSource = `(c) => {
  const w = c.width, h = c.height
  if (!w || !h) return { w, h, dark: 0, digest: 'empty' }
  const ctx = c.getContext('2d')
  let dark = 0, hash = 2166136261
  const step = Math.max(1, Math.floor(h / 128))
  for (let y = 0; y < h; y += step) {
    const d = ctx.getImageData(0, y, w, 1).data
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] > 0 && (d[i] + d[i + 1] + d[i + 2]) / 3 < 200) dark++
    }
    for (let i = 0; i < d.length; i += 3) { hash ^= d[i]; hash = Math.imul(hash, 16777619) }
  }
  return { w, h, dark, digest: (hash >>> 0).toString(16) }
}`

// stable(key, digest): true once the sampled digest has stayed the same for 100 ms of polls. pdf.js draws text first and the
// JPEG later, so one dark-enough sample can be a partial paint; the 100 ms are inside the recorded time.
// It also notes (window.__h5first[key]) the first poll at which the caller's other conditions held, before any stability wait.
const stableSource = `(key, digest) => {
  const now = performance.now()
  const firsts = (window.__h5first = window.__h5first || {})
  if (firsts[key] === undefined) firsts[key] = now
  const state = (window.__h5state = window.__h5state || {})
  if (!state[key] || state[key].digest !== digest) { state[key] = { digest, since: now }; return false }
  return now - state[key].since >= 100
}`

function note(request) {
  const target = request.url()
  if (target.startsWith(origin + '/') || target.startsWith('data:') || target.startsWith('blob:')) return true
  out.external_requests_blocked += 1
  const other = new URL(target).origin
  if (!out.blocked_origins.includes(other)) out.blocked_origins.push(other)
  return false
}

async function session(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  await context.route('**/*', (route) => (note(route.request()) ? route.continue() : route.abort()))
  await context.addInitScript(`window.__h5canvas = ${canvasInfoSource}; window.__h5stable = ${stableSource}`)
  const watch = (page) => {
    page.on('console', (m) => { if (m.type() === 'error') out.console_errors += 1 })
    page.on('pageerror', () => { out.console_errors += 1 })
  }
  context.on('page', watch)
  return context
}

async function until(page, source, arg, polling, limit) {
  // Resolves with the value the function returned (truthy), polled on animation frames unless a number is given.
  // A string is an expression to Playwright, and a function expression is truthy at once; so call it explicitly.
  const handle = await page.waitForFunction(`(${source})(${JSON.stringify(arg === undefined ? null : arg)})`, undefined, { polling: polling || 'raf', timeout: limit || timeout })
  return handle.jsonValue()
}

// screenState: the two K01-ui conditions, evaluated separately (the poll uses both; a timeout reports each one).
const screenState = `({ label, count }) => {
  const visible = ${visible}
  const h = document.querySelector('h1.research-title-text')
  const trigger = [...document.querySelectorAll('[data-slot=tabs-trigger]')].find((el) => el.textContent.trim().startsWith('Sources'))
  const c = trigger && trigger.querySelector('.research-tab-count')
  return {
    title_ok: visible(h) && h.getAttribute('aria-label') === label,
    title_visible: visible(h), title_aria_label: h ? h.getAttribute('aria-label') : null,
    tab_count_ok: !!c && c.textContent.trim() === String(count),
    tab_count_text: c ? c.textContent.trim() : null, expected_count: count,
  }
}`
const screenReady = `(arg) => { const s = (${screenState})(arg); return s.title_ok && s.tab_count_ok ? performance.now() : false }`
const sourceRow = `() => { const visible = ${visible}; return visible(document.querySelector('.source-row')) ? performance.now() : false }`

async function timed(name, body) {
  const started = performance.now()
  const startEpoch = Date.now()
  try {
    const value = await body(started, startEpoch)
    out.steps[name] = { ok: true, seconds: (performance.now() - started) / 1000, start_epoch_ms: startEpoch, end_epoch_ms: Date.now(), ...value }
  } catch (error) {
    out.steps[name] = {
      ok: false, seconds: (performance.now() - started) / 1000, start_epoch_ms: startEpoch, end_epoch_ms: Date.now(),
      timeout: !!error && error.name === 'TimeoutError',  // capacity.py reads a timeout as a measured result, anything else as a harness failure
      error: String(error && error.message ? error.message : error).split('\n')[0],
      ...(error && error.readiness ? { readiness: error.readiness } : {}),
    }
  }
}

// emit: the result so far, one JSON line (capacity.py reads the last complete one, so a killed node keeps its finished steps).
const emit = () => console.log(JSON.stringify(out))

const base = (suffix) => `${args.url}/#/research/${args.researchId}${suffix}`

async function loadScreen(page) {
  // goto and the ready wait share one deadline of timeoutMs, so a step that says ok never took longer than that in total.
  const began = performance.now()
  const arg = { label: args.label, count: args.expectedSources }
  try {
    await page.goto(base(''), { waitUntil: 'commit', timeout: timeout })
    return await until(page, screenReady, arg, undefined, Math.max(1, timeout - (performance.now() - began)))
  } catch (error) {
    // on a timeout say which of the two conditions was not met (title aria-label visible, tab count equal), in the text and in the step
    let readiness = null
    try {  // a page whose main thread is stuck must not hang the diagnosis: 5 s at most
      readiness = await Promise.race([
        page.evaluate(`(${screenState})(${JSON.stringify(arg)})`),
        new Promise((_, reject) => setTimeout(() => reject(new Error('page.evaluate did not answer in 5 s')), 5000)),
      ])
    } catch (inner) { readiness = { unavailable: String(inner.message).split('\n')[0] } }
    error.readiness = readiness
    const first = String(error && error.message ? error.message : error).split('\n')[0]
    error.message = readiness.unavailable ? `${first}; readiness not readable: ${readiness.unavailable}`
      : `${first}; title aria-label visible: ${readiness.title_ok} (visible ${readiness.title_visible}, aria-label ${JSON.stringify(readiness.title_aria_label)}); `
        + `tab count equal: ${readiness.tab_count_ok} (text ${JSON.stringify(readiness.tab_count_text)}, expected ${readiness.expected_count})`
    throw error
  }
}

async function loadSources(context) {
  const page = await context.newPage()
  await page.goto(base('/sources'), { waitUntil: 'commit', timeout: timeout })
  await until(page, sourceRow)
  return page
}

async function run() {
  const require = createRequire(path.join(args.web, 'package.json'))
  const { chromium } = require('@playwright/test')
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: launchArgs })
  out.chrome_version = browser.version()
  try {
    for (const step of args.steps) {
      if (step === 'k01') {
        const context = await session(browser)
        const page = await context.newPage()
        await timed('k01', async () => ({ page_ms: await loadScreen(page), stops_at: 'title aria-label equal and Sources count equal' }))
        await context.close()
      } else if (step === 'k04') {
        const context = await session(browser)
        const page = await context.newPage()
        let ready = false
        await timed('k04b', async () => {
          await page.goto(base('/sources'), { waitUntil: 'commit', timeout: timeout })
          const pageMs = await until(page, sourceRow)
          ready = true
          return { page_ms: pageMs, stops_at: 'first .source-row visible' }
        })
        let typed = ready
        if (ready) {
          try {
            await page.keyboard.press('Meta+K')
            await page.locator('input[role=combobox]').fill('alpha', { timeout })
          } catch (error) {
            typed = false
            out.steps.k04a = { ok: false, seconds: 0, error: 'Quick find did not open or take the query: ' + String(error && error.message ? error.message : error).split('\n')[0] }
          }
        }
        if (typed) {
          await timed('k04a', async () => ({
            page_ms: await until(page, `() => { const visible = ${visible}; return visible(document.querySelector('[role=group][aria-labelledby="qf-group-Sources"] [role=option]')) ? performance.now() : false }`),
            stops_at: 'first Sources option visible; starts when fill() returns; includes the dialog\'s 120 ms debounce',
          }))
        } else if (!ready) {
          out.steps.k04a = { ok: false, seconds: 0, error: 'the Sources list never showed a row' }
        }
        await context.close()
      } else if (step === 'k04c-abstract') {
        const context = await session(browser)
        let page = null
        try { page = await loadSources(context) } catch (error) { out.steps[step] = { ok: false, seconds: 0, error: 'sources never loaded: ' + String(error.message).split('\n')[0] } }
        if (page) {
          await timed(step, async () => {
            await page.locator('.source-links button', { hasText: 'Read abstract' }).first().click({ timeout })
            return { page_ms: await until(page, `() => { const visible = ${visible}; return visible(document.querySelector('.source-sheet .passage-text')) ? performance.now() : false }`), stops_at: '.source-sheet .passage-text visible; starts before the click() call, which includes its own actionability wait' }
          })
        }
        await context.close()
      } else if (step === 'k04c-pdf') {
        const context = await session(browser)
        let page = null
        try { page = await loadSources(context) } catch (error) { out.steps[step] = { ok: false, seconds: 0, error: 'sources never loaded: ' + String(error.message).split('\n')[0] } }
        if (page) {
          // the row whose "Open PDF" is clicked: its title names the work, the work names the unique page-1 text to wait for
          const row = page.locator('.source-row', { has: page.locator('.source-asset-actions button.is-primary') }).first()
          let marker = null
          try {
            const work = /capacity study (\d+) on/.exec(await row.innerText({ timeout }))
            marker = work && args.pdfMarkers ? args.pdfMarkers[work[1]] : null
          } catch (error) { /* reported below */ }
          if (!marker) out.steps[step] = { ok: false, seconds: 0, error: 'no stored-PDF row, or no marker for its work number' }
          else await timed(step, async () => {
            await row.locator('.source-asset-actions button.is-primary').first().click({ timeout })
            await page.locator('.source-view-tabs button[role=tab]', { hasText: 'Plain text' }).click({ timeout })
            return {
              page_ms: await until(page, `(marker) => { const visible = ${visible}; return [...document.querySelectorAll('.asset-text-view .pdf-text-page .passage-text')].some((el) => el.textContent.includes(marker) && visible(el)) ? performance.now() : false }`, marker),
              stops_at: 'the unique page-1 text of that row\'s PDF visible after Open PDF click and Plain text click (both counted; the pdf.js worker may render meanwhile)',
            }
          })
        }
        await context.close()
      } else if (step === 'two-tab') {
        const context = await session(browser)
        const first = await context.newPage()
        let firstReady = true
        try { await loadScreen(first) } catch (error) { firstReady = false }
        const second = await context.newPage()
        await timed('two-tab', async () => ({
          first_tab_ready: firstReady,
          page_ms: await loadScreen(second),
          stops_at: 'second tab (new page, same context) K01-ui ready while the first tab holds its own EventSource',
        }))
        await context.close()
      } else if (step === 'pdf') {
        const context = await session(browser)
        let page = null
        try { page = await loadSources(context) } catch (error) { out.steps.pdf_first_page = { ok: false, seconds: 0, error: 'sources never loaded: ' + String(error.message).split('\n')[0] } }
        if (page) {
          let pageOne = null
          await timed('pdf_first_page', async () => {
            await page.locator('.source-asset-actions button.is-primary').first().click({ timeout })
            const ready = await until(page, `(pages) => {
              const viewer = document.querySelector('.pdf-viewer')
              if (!viewer || viewer.querySelector('.pdf-document p')) return false
              const total = viewer.querySelector('.pdf-page-controls span')
              if (!total || !total.textContent.includes('/ ' + pages)) return false
              const canvas = viewer.querySelector('canvas')
              if (!canvas) return false
              const info = window.__h5canvas(canvas)
              if (info.dark < 50) { window.__h5state && delete window.__h5state.first; return false }
              return window.__h5stable('first', info.digest) ? { ms: performance.now(), stable_wait_ms: performance.now() - window.__h5first.first, digest: info.digest, w: info.w, h: info.h, dark: info.dark, label: canvas.getAttribute('aria-label') } : false
            }`, args.pages, 50)
            pageOne = ready
            return {
              page_ms: ready.ms, stable_wait_ms: ready.stable_wait_ms, canvas: { w: ready.w, h: ready.h, dark: ready.dark, label: ready.label },
              stops_at: '"Loading PDF…" gone, toolbar shows "/ ' + args.pages + '", canvas non-zero and not blank (at least 50 pixels, sampled from 128 evenly spaced rows, drawn and darker than 200; polled every 50 ms) and the pixel digest unchanged for 100 ms (pdf.js draws text first and the image later; the 100 ms are inside the time)',
            }
          })
          if (pageOne) {
            await timed('pdf_jump', async () => {
              await page.locator('input[aria-label="Page number"]').fill('400', { timeout })
              const ready = await until(page, `(before) => {
                const canvas = document.querySelector('.pdf-viewer canvas')
                if (!canvas || !(canvas.getAttribute('aria-label') || '').includes('p. 400')) return false
                const info = window.__h5canvas(canvas)
                if (info.dark < 50 || info.digest === before) { window.__h5state && delete window.__h5state.jump; return false }
                return window.__h5stable('jump', info.digest) ? { ms: performance.now(), stable_wait_ms: performance.now() - window.__h5first.jump, digest: info.digest, label: canvas.getAttribute('aria-label') } : false
              }`, pageOne.digest, 50)
              return {
                page_ms: ready.ms, stable_wait_ms: ready.stable_wait_ms, canvas: { label: ready.label },
                stops_at: 'canvas aria-label names page 400 AND the sampled pixel digest differs from the page 1 digest AND the canvas is not blank AND that digest is unchanged for 100 ms (the label alone changes before the page is drawn, and pdf.js draws text before the image; the 100 ms are inside the time); starts before fill()',
              }
            })
          } else {
            out.steps.pdf_jump = { ok: false, seconds: 0, error: 'first page never drew' }
          }
        }
        await context.close()
      } else {
        out.steps[step] = { ok: false, seconds: 0, error: 'unknown step' }
      }
      emit()
    }
    out.ok = true
  } finally {
    await browser.close().catch(() => {})
  }
}

try {
  await run()
} catch (error) {
  out.error = String(error && error.message ? error.message : error).split('\n')[0]
}
emit()
process.exit(out.ok ? 0 : 1)
