import type { Page } from '@playwright/test'
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { COLOUR_EXCEPTIONS, COPY_CHANGES, EXCLUDED_MOCK_CONTROLS, GEOMETRY_EXCEPTIONS, PLACEMENTS, type ColourException, type Use } from './exceptions'
import type { Pair, Theme } from './parity-map'

// The parity gate of plan §4.1 as reusable helpers. A slice runs them for its screens through parity.spec.ts; each
// helper returns failure lines instead of throwing, so one run lists every difference.

const WEB = path.resolve(import.meta.dirname, '..', '..')

// The main checkout, where the ignored `.local/` lives: a worktree's git common dir is the main checkout's `.git`.
function mainCheckout(): string {
  try {
    const common = execSync('git rev-parse --path-format=absolute --git-common-dir', { cwd: WEB, encoding: 'utf8' }).trim()
    return path.dirname(common)
  } catch {
    return path.resolve(WEB, '..', '..')
  }
}

export const MOCKUP = process.env.DEIXIS_PARITY_MOCKUP ?? path.join(mainCheckout(), '.local', 'design', 'elicit-style-mockup', 'index.html')
// Pixel diffs are a review aid only (plan §4.1); they never fail the check.
export const PARITY_OUT = process.env.DEIXIS_PARITY_OUT ?? path.join(mainCheckout(), '.local', 'parity')

// ---- the mockup page --------------------------------------------------------------------------------------------

const ORIGIN = 'http://parity-mockup.test'
const FONT_PACKAGES = {
  inter: { dir: '@fontsource-variable/inter', css: ['index.css'], from: 'Inter Variable', to: 'Inter' },
  serif: { dir: '@fontsource-variable/source-serif-4', css: ['index.css', 'wght-italic.css'], from: 'Source Serif 4 Variable', to: 'Source Serif 4' },
}

// The app's own bundled Inter and Source Serif 4 files, renamed to the family names the mockup asks for.
function fontsCss(): string {
  return Object.entries(FONT_PACKAGES).map(([key, pkg]) => pkg.css.map(file =>
    readFileSync(path.join(WEB, 'node_modules', pkg.dir, file), 'utf8')
      .replaceAll(`'${pkg.from}'`, `'${pkg.to}'`)
      .replaceAll('url(./files/', `url(${ORIGIN}/fonts/${key}/`)).join('\n')).join('\n')
}

/** The mockup wrapped in a doctype page with the app's local fonts. A missing file fails; it is never skipped.
 *  The published artifact gets a document skeleton with no body margin; the wrapper gives it the same (`body{margin:0}`).
 *  The "Mockup · example data" tags are mockup-only controls (§0 rule 2): the app has none, so they take no room here
 *  either (at 390 px one wraps the composer band onto a second row). */
export async function openMockup(page: Page): Promise<void> {
  if (!existsSync(MOCKUP)) throw new Error(`Parity mockup not found: ${MOCKUP}. Set DEIXIS_PARITY_MOCKUP to the v24 index.html.`)
  const source = readFileSync(MOCKUP, 'utf8').replace(/<link[^>]*fonts\.(googleapis|gstatic)\.com[^>]*>/g, '')
  const html = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    + `<link rel="stylesheet" href="${ORIGIN}/fonts.css"><style>body{margin:0}.mock-tag{display:none!important}</style>${source}`
  const css = fontsCss()
  await page.route('**/*', route => {
    const url = route.request().url()
    if (url === `${ORIGIN}/` || url === `${ORIGIN}/index.html`) return route.fulfill({ contentType: 'text/html; charset=utf-8', body: html })
    if (url === `${ORIGIN}/fonts.css`) return route.fulfill({ contentType: 'text/css', body: css })
    const font = url.match(/^http:\/\/parity-mockup\.test\/fonts\/(inter|serif)\/([\w.-]+\.woff2)$/)
    if (font) {
      const pkg = FONT_PACKAGES[font[1] as keyof typeof FONT_PACKAGES]
      return route.fulfill({ contentType: 'font/woff2', body: readFileSync(path.join(WEB, 'node_modules', pkg.dir, 'files', font[2])) })
    }
    return route.abort()  // the mockup runs offline: nothing else is fetched
  })
  await page.goto(`${ORIGIN}/index.html`)
  await page.evaluate(() => document.fonts.ready)
}

/** Runs one of the mockup's own globals (`setScenario`, `go`, `openPanel`, `menu`) and clears its toast. */
export async function driveMockup(page: Page, script: string): Promise<void> {
  await page.evaluate(script)
  await page.evaluate(() => { document.querySelectorAll('.toast').forEach(el => el.remove()) })
  await page.evaluate(() => document.fonts.ready)
}

// ---- measuring ----------------------------------------------------------------------------------------------------

export type Rgba = [number, number, number, number]
export type Measured = {
  found: number          // elements the selector matches, after exclusions
  visible: boolean
  order: number          // document position of the first match
  box: { x: number; y: number; width: number; height: number }
  style: Record<string, string>
  colours: Record<string, Rgba>
  background: Rgba       // what the element actually sits on, alpha composited
  icon: string | null
  text: string           // visible fixed text: no data text, no hidden text, text-transform applied
  matches: string[]      // exception selectors (mockup side) the element matches
  hasBorder: boolean
}

const STYLE_KEYS = ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'text-transform',
  'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'border-top-left-radius', 'border-top-right-radius',
  'border-bottom-right-radius', 'border-bottom-left-radius', 'box-shadow', 'border-top-width'] as const
const COLOUR_KEYS = ['color', 'background-color', 'border-top-color'] as const

/** Measures every element `selector` matches, in document order. `exclude` removes matches inside excluded mockup
 *  controls (rule 2) or declared app placements (§2.2); `probe` lists exception selectors to test with `Element.matches`;
 *  `dataText` lists selectors inside an element whose text is data (counts, titles), left out of its fixed text. */
export async function measureAll(page: Page, selector: string, exclude: string[], probe: string[], dataText: string[] = []): Promise<Measured[]> {
  // The mockup's icon table (its global `P`); the app has none and names its icons by lucide class.
  const icons = await page.evaluate('typeof P === "undefined" ? null : P') as Record<string, string> | null
  return page.evaluate(({ selector, exclude, probe, styleKeys, colourKeys, icons, dataText }) => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!
    // Any CSS colour (rgb, color(srgb …), oklab, color-mix results) to sRGB bytes plus alpha, through the canvas.
    const rgba = (css: string): [number, number, number, number] => {
      ctx.clearRect(0, 0, 1, 1)
      ctx.fillStyle = '#000'
      ctx.fillStyle = css
      ctx.fillRect(0, 0, 1, 1)
      const d = ctx.getImageData(0, 0, 1, 1).data
      return [d[0], d[1], d[2], d[3] / 255]
    }
    const over = (top: number[], under: number[]): [number, number, number, number] => {
      const a = top[3] + under[3] * (1 - top[3])
      if (a === 0) return [0, 0, 0, 0]
      const c = (i: number) => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a
      return [c(0), c(1), c(2), a]
    }
    const order = [...document.querySelectorAll('*')]
    // The text a reader sees: no hidden or visually hidden (sr-only) text, no data text, CSS text-transform applied.
    const shown = (node: Element): boolean => {
      const st = getComputedStyle(node)
      if (st.display === 'none' || st.visibility === 'hidden') return false
      const box = node.getBoundingClientRect()
      return !(box.width <= 1 && box.height <= 1 && st.overflow === 'hidden')
    }
    const textOf = (el: Element): string => {
      const parts: string[] = []
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        let ok = true
        for (let up = node.parentElement; up && ok; up = up === el ? null : up.parentElement) {
          if (dataText.some(sel => up!.matches(sel)) || !shown(up)) ok = false
        }
        if (!ok) continue
        const transform = getComputedStyle(node.parentElement!).textTransform
        const text = node.textContent ?? ''
        parts.push(transform === 'uppercase' ? text.toUpperCase() : transform === 'lowercase' ? text.toLowerCase() : text)
      }
      return parts.join(' ').replace(/\s+/g, ' ').trim()
    }
    const all = [...document.querySelectorAll(selector)].filter(el => !exclude.some(x => el.closest(x)))
    return all.map(node => {
      const el = node as HTMLElement
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      const style: Record<string, string> = {}
      for (const key of styleKeys) style[key] = cs.getPropertyValue(key)
      const colours: Record<string, [number, number, number, number]> = {}
      for (const key of colourKeys) colours[key] = rgba(cs.getPropertyValue(key))
      // The background the element sits on: its own and its ancestors' backgrounds, composited until opaque.
      let background: [number, number, number, number] = [0, 0, 0, 0]
      for (let up: Element | null = el; up && background[3] < 1; up = up.parentElement) {
        background = over(background, rgba(getComputedStyle(up).backgroundColor))
      }
      background = over(background, [255, 255, 255, 1])
      // Icon identity: a lucide class in the app, the path set of the mockup's own `P` table in the mockup.
      const svg = el.matches('svg') ? el : el.querySelector('svg')
      let icon: string | null = null
      if (svg) {
        const lucide = [...svg.classList].find(c => c.startsWith('lucide-'))
        if (lucide) icon = lucide.slice('lucide-'.length)
        else {
          // Compare as parsed markup: `<path …/>` in the table reads back as `<path …></path>`.
          const parsed = (body: string) => { const t = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); t.innerHTML = body; return t.innerHTML }
          icon = icons ? Object.entries(icons).find(([, body]) => parsed(body) === svg.innerHTML)?.[0] ?? null : null
        }
      }
      return {
        found: all.length,
        visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none',
        order: order.indexOf(el),
        box: { x: r.x, y: r.y, width: r.width, height: r.height },
        style, colours, background,
        icon,
        text: textOf(el),
        matches: probe.filter(sel => { try { return el.matches(sel) } catch { return false } }),
        hasBorder: parseFloat(cs.borderTopWidth) > 0,
      }
    })
  }, { selector, exclude, probe, styleKeys: [...STYLE_KEYS], colourKeys: [...COLOUR_KEYS], icons, dataText })
}

/** The first element `selector` matches (its `found` is the count of all matches). */
export async function measure(page: Page, selector: string, exclude: string[], probe: string[], dataText: string[] = []): Promise<Measured | null> {
  return (await measureAll(page, selector, exclude, probe, dataText))[0] ?? null
}

// ---- colour science -----------------------------------------------------------------------------------------------

function toLab([r, g, b]: Rgba): [number, number, number] {
  const lin = (v: number) => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  const [R, G, B] = [lin(r), lin(g), lin(b)]
  const X = (R * 0.4124564 + G * 0.3575761 + B * 0.1804375) / 0.95047
  const Y = R * 0.2126729 + G * 0.7151522 + B * 0.0721750
  const Z = (R * 0.0193339 + G * 0.1191920 + B * 0.9503041) / 1.08883
  const f = (t: number) => t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116
  return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))]
}

/** CIEDE2000 colour difference (Sharma, Wu and Dalal 2005). */
export function deltaE2000(a: Rgba, b: Rgba): number {
  const [L1, a1, b1] = toLab(a), [L2, a2, b2] = toLab(b)
  const rad = Math.PI / 180
  const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2), Cm = (C1 + C2) / 2
  const G = 0.5 * (1 - Math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
  const a1p = a1 * (1 + G), a2p = a2 * (1 + G)
  const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2)
  const h = (x: number, y: number) => { if (x === 0 && y === 0) return 0; const v = Math.atan2(y, x) / rad; return v < 0 ? v + 360 : v }
  const h1p = h(a1p, b1), h2p = h(a2p, b2)
  const dLp = L2 - L1, dCp = C2p - C1p
  let dhp = 0
  if (C1p * C2p !== 0) dhp = Math.abs(h2p - h1p) <= 180 ? h2p - h1p : h2p - h1p > 180 ? h2p - h1p - 360 : h2p - h1p + 360
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin(dhp / 2 * rad)
  const Lm = (L1 + L2) / 2, Cmp = (C1p + C2p) / 2
  let hm = h1p + h2p
  if (C1p * C2p !== 0) hm = Math.abs(h1p - h2p) <= 180 ? (h1p + h2p) / 2 : h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2
  const T = 1 - 0.17 * Math.cos((hm - 30) * rad) + 0.24 * Math.cos(2 * hm * rad) + 0.32 * Math.cos((3 * hm + 6) * rad) - 0.2 * Math.cos((4 * hm - 63) * rad)
  const dTheta = 30 * Math.exp(-(((hm - 275) / 25) ** 2))
  const Rc = 2 * Math.sqrt(Cmp ** 7 / (Cmp ** 7 + 25 ** 7))
  const Sl = 1 + 0.015 * (Lm - 50) ** 2 / Math.sqrt(20 + (Lm - 50) ** 2)
  const Sc = 1 + 0.045 * Cmp, Sh = 1 + 0.015 * Cmp * T
  const Rt = -Math.sin(2 * dTheta * rad) * Rc
  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))
}

export function hexToRgba(hex: string): Rgba {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h
  return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16), 1]
}

/** Composites a possibly transparent colour over an opaque background. */
export function flatten(top: Rgba, under: Rgba): Rgba {
  const a = top[3]
  return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1]
}

export function contrast(fg: Rgba, bg: Rgba): number {
  const lum = ([r, g, b]: Rgba) => {
    const l = (v: number) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
    return 0.2126 * l(r) + 0.7152 * l(g) + 0.0722 * l(b)
  }
  const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// Text needs 4.5:1, a meaning-carrying icon or dot 3:1, decoration nothing (plan §4.1).
export const CONTRAST_MIN: Record<Use, number> = { text: 4.5, icon: 3, dot: 3, decorative: 0 }

const hex = ([r, g, b, a]: Rgba) => '#' + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('') + (a < 1 ? `/${a.toFixed(2)}` : '')

// ---- the gate checks ----------------------------------------------------------------------------------------------

export type Variant = { width: number; theme: Theme }
export type Side = { mock: Measured | null; app: Measured | null }
const near = (a: number, b: number, tol: number) => Math.abs(a - b) <= tol

const baseId = (id: string) => id.replace(/(\[\d+\]|\{selected \d+\})+$/, '')

/** Presence: an active pair is found and visible on both sides. Lists are counted item by item in `checkList`. */
export function checkPresence(pair: Pair, m: Side): string[] {
  const out: string[] = []
  if (!m.mock) out.push(`${pair.id}: not in the mockup (${pair.mock})`)
  if (!m.app) out.push(`${pair.id}: not in the app (${pair.app})`)
  if (!m.mock || !m.app) return out
  if (m.mock.visible !== m.app.visible) out.push(`${pair.id}: visible in mockup ${m.mock.visible}, app ${m.app.visible}`)
  return out
}

/** Order: the active pairs of a surface appear in the same document order on both sides. */
export function checkOrder(pairs: Pair[], measured: Map<string, Side>): string[] {
  const seq = (side: 'mock' | 'app') => pairs.filter(p => !p.unordered && measured.get(p.id)?.[side])
    .sort((a, b) => measured.get(a.id)![side]!.order - measured.get(b.id)![side]!.order).map(p => p.id)
  const mock = seq('mock'), app = seq('app')
  return mock.join(' ') === app.join(' ') ? [] : [`order differs:\n  mockup ${mock.join(' → ')}\n  app    ${app.join(' → ')}`]
}

type Axis = 'x' | 'y' | 'width' | 'height'
/** Chrome geometry: x, y, width and height within ±2 px (a data list's rows: no y, their place depends on the data). */
export function checkChrome(pair: Pair, m: Side, axes: Axis[] = ['x', 'y', 'width', 'height']): string[] {
  if (!m.mock || !m.app) return []
  return axes.filter(k => !near(m.mock!.box[k], m.app!.box[k], 2))
    .map(k => `${pair.id}: ${k} mockup ${m.mock!.box[k].toFixed(1)} app ${m.app!.box[k].toFixed(1)} (±2)`)
}

/** Content blocks: x and width within ±2 px, no y; padding and line height equal. */
export function checkContent(pair: Pair, m: Side): string[] {
  if (!m.mock || !m.app) return []
  const out = checkChrome(pair, m, ['x', 'width'])
  for (const k of ['padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'line-height']) {
    if (m.mock.style[k] !== m.app.style[k]) out.push(`${pair.id}: ${k} mockup ${m.mock.style[k]} app ${m.app.style[k]}`)
  }
  return out
}

const FAMILY_ALIASES: Record<string, string> = { 'Inter Variable': 'Inter', 'Source Serif 4 Variable': 'Source Serif 4' }
export function normaliseFamily(family: string): string {
  const first = family.split(',')[0].trim().replace(/^["']|["']$/g, '')
  return FAMILY_ALIASES[first] ?? first
}
const px = (v: string) => (v === 'normal' ? 'normal' : /^-?[\d.]+px$/.test(v) ? `${Math.round(parseFloat(v) * 100) / 100}px` : v)

/** Typography: family (normalised), size, weight, line height, letter spacing and text transform equal. */
export function checkType(pair: Pair, m: Side): string[] {
  if (!m.mock || !m.app) return []
  const out: string[] = []
  const fm = normaliseFamily(m.mock.style['font-family']), fa = normaliseFamily(m.app.style['font-family'])
  if (fm !== fa) out.push(`${pair.id}: font-family mockup ${fm} app ${fa}`)
  for (const k of ['font-size', 'font-weight', 'line-height', 'text-transform']) {
    if (px(m.mock.style[k]) !== px(m.app.style[k])) out.push(`${pair.id}: ${k} mockup ${m.mock.style[k]} app ${m.app.style[k]}`)
  }
  const ls = (v: string) => (v === 'normal' ? '0px' : px(v))
  if (ls(m.mock.style['letter-spacing']) !== ls(m.app.style['letter-spacing'])) {
    out.push(`${pair.id}: letter-spacing mockup ${m.mock.style['letter-spacing']} app ${m.app.style['letter-spacing']}`)
  }
  return out
}

const norm = (t: string) => t.replace(/\s+/g, ' ').trim()
/** Fixed text: the visible text with data text left out (the pair's `dataText`), as rendered (text-transform applied).
 *  Mockup copy replaced under §2.3 (`COPY_CHANGES`) is expected in its replacement wording. */
export function checkText(pair: Pair, m: Side): string[] {
  if (!m.mock || !m.app) return []
  const change = COPY_CHANGES.find(c => norm(c.mock) === norm(m.mock!.text))
  const expected = change ? change.app : m.mock.text
  if (norm(expected) === norm(m.app.text)) return []
  return [`${pair.id}: text mockup "${norm(m.mock.text)}"${change ? ` (copy change ${change.id} → "${change.app}")` : ''}, app "${norm(m.app.text)}"`]
}

/** The colour exceptions that cover this mockup element, property and theme. */
export function exceptionFor(pair: Pair, property: string, theme: Theme, mock: Measured): ColourException | undefined {
  return COLOUR_EXCEPTIONS.find(e => e.property === property
    && (e.pairs?.includes(baseId(pair.id)) || e.selectors.some(sel => mock.matches.includes(sel)))
    && e.use === (pair.use ?? 'text')
    && deltaE2000(flatten(mock.colours[property], mock.background), hexToRgba(e.mock[theme])) <= 1)
}

/** Contrast of an element by use, on what it actually sits on (alpha composited). */
export function checkContrast(id: string, use: Use, el: Measured, where: string): string[] {
  const min = CONTRAST_MIN[use]
  if (!min) return []
  const fg = flatten(el.colours.color, el.background)
  const ratio = contrast(fg, el.background)
  return ratio + 1e-9 < min ? [`${id}: ${use} contrast ${ratio.toFixed(2)}:1 < ${min}:1 (${hex(fg)} on ${hex(el.background)}, ${where})`] : []
}

/** The `color` of one state: a declared exception's approved value (exact) and its contrast by use; otherwise the
 *  mockup's colour within ΔE2000 1, and, when the default state is an exception, still its contrast. */
function checkStateColour(pair: Pair, m: Side, v: Variant, state: string, fallback?: ColourException): string[] {
  if (!m.mock || !m.app) return []
  const where = `${v.theme} ${v.width} ${state}`
  const exception = exceptionFor(pair, 'color', v.theme, m.mock)
  const got = flatten(m.app.colours.color, m.app.background)
  if (exception) {
    const out = deltaE2000(got, hexToRgba(exception.approved[v.theme])) > 0.1
      ? [`${pair.id}: color app ${hex(got)} is not the approved ${exception.approved[v.theme]} of exception ${exception.id} (${where})`] : []
    return [...out, ...checkContrast(pair.id, exception.use, m.app, where)]
  }
  const want = flatten(m.mock.colours.color, m.mock.background)
  const d = deltaE2000(want, got)
  const out = d > 1 ? [`${pair.id}: color mockup ${hex(want)} app ${hex(got)} (ΔE2000 ${d.toFixed(2)} > 1, ${where})`] : []
  return fallback ? [...out, ...checkContrast(pair.id, fallback.use, m.app, where)] : out
}

/** Colour, radius, border and shadow in the default state: equal or ΔE2000 ≤ 1. A declared exception is compared to its
 *  approved D5 value (exact) instead, and its contrast is checked by use. */
export function checkColour(pair: Pair, m: Side, v: Variant): string[] {
  if (!m.mock || !m.app) return []
  const out: string[] = []
  for (const key of COLOUR_KEYS) {
    if (key === 'color') { out.push(...checkStateColour(pair, m, v, 'default')); continue }
    if (key === 'border-top-color' && !(m.mock.hasBorder && m.app.hasBorder)) continue
    const mc = m.mock.colours[key], ac = m.app.colours[key]
    if (mc[3] === 0 && ac[3] === 0) continue
    const exception = exceptionFor(pair, key, v.theme, m.mock)
    if (exception) {
      if (deltaE2000(ac, hexToRgba(exception.approved[v.theme])) > 0.1) out.push(`${pair.id}: ${key} app ${hex(ac)} is not the approved ${exception.approved[v.theme]} of exception ${exception.id}`)
      continue
    }
    const white: Rgba = [255, 255, 255, 1]
    const d = Math.abs(mc[3] - ac[3]) > 0.02 ? Infinity : deltaE2000(flatten(mc, white), flatten(ac, white))
    if (d > 1) out.push(`${pair.id}: ${key} mockup ${hex(mc)} app ${hex(ac)} (ΔE2000 ${Number.isFinite(d) ? d.toFixed(2) : 'alpha'} > 1)`)
  }
  for (const k of ['border-top-left-radius', 'border-top-right-radius', 'border-bottom-right-radius', 'border-bottom-left-radius', 'border-top-width']) {
    if (px(m.mock.style[k]) !== px(m.app.style[k])) out.push(`${pair.id}: ${k} mockup ${m.mock.style[k]} app ${m.app.style[k]}`)
  }
  const shadow = (s: string) => s.replace(/rgba?\([^)]*\)/g, c => c.replace(/\s+/g, '')).replace(/\s+/g, ' ').trim()
  if (shadow(m.mock.style['box-shadow']) !== shadow(m.app.style['box-shadow'])) {
    out.push(`${pair.id}: box-shadow mockup ${m.mock.style['box-shadow']} app ${m.app.style['box-shadow']}`)
  }
  return out
}

const iconOf = (pair: Pair, index: number) => (Array.isArray(pair.icon) ? pair.icon[index] : pair.icon)

/** Icons: the same mapped icon (mockup `P` name ↔ lucide name) for this item. */
export function checkIcon(pair: Pair, m: Side, index = 0): string[] {
  const icon = iconOf(pair, index)
  if (!m.mock || !m.app || !icon) return []
  const out: string[] = []
  if (m.mock.icon !== icon.mock) out.push(`${pair.id}: mockup icon ${m.mock.icon} is not the mapped ${icon.mock}`)
  if (m.app.icon !== icon.app) out.push(`${pair.id}: app icon ${m.app.icon} is not the mapped ${icon.app}`)
  return out
}

/** Icon box ±1 px, measured on the svg of the item at `index`. */
export async function checkIconBox(pair: Pair, mock: Page, app: Page, index = 0, id = pair.id, mockIndex = index): Promise<string[]> {
  if (!iconOf(pair, index)) return []
  const box = (page: Page, sel: string, exclude: string[], index: number) => page.evaluate(({ sel, exclude, index }) => {
    const el = [...document.querySelectorAll(sel)].filter(e => !exclude.some(x => e.closest(x)))[index]
    const svg = el?.matches('svg') ? el : el?.querySelector('svg')
    const r = svg?.getBoundingClientRect()
    return r ? { width: r.width, height: r.height } : null
  }, { sel, exclude, index })
  const [a, b] = [await box(mock, pair.mock, MOCK_EXCLUDE, mockIndex), await box(app, pair.app, APP_EXCLUDE, index)]
  if (!a || !b) return [`${id}: icon svg missing`]
  return (['width', 'height'] as const).filter(k => !near(a[k], b[k], 1)).map(k => `${id}: icon ${k} mockup ${a[k]} app ${b[k]} (±1)`)
}

/** Breakpoint 1024: only the rail and the Library's third pane hide, and panel and thread widths match. A pair flagged
 *  `breakpoint` is compared for visibility and width only. */
export function checkBreakpoint(pair: Pair, m: Side): string[] {
  if (!m.mock || !m.app) return [`${pair.id}: missing at 1024 (mockup ${!!m.mock}, app ${!!m.app})`]
  const out: string[] = []
  if (m.mock.visible !== m.app.visible) out.push(`${pair.id}: at 1024 visible in mockup ${m.mock.visible}, app ${m.app.visible}`)
  if (m.mock.visible && !near(m.mock.box.width, m.app.box.width, 2)) out.push(`${pair.id}: at 1024 width mockup ${m.mock.box.width} app ${m.app.box.width}`)
  return out
}

export const MOCK_EXCLUDE = EXCLUDED_MOCK_CONTROLS.map(c => c.selector)
export const APP_EXCLUDE = PLACEMENTS.flatMap(p => (p.app ? [p.app] : []))
export const PROBE = [...new Set(COLOUR_EXCEPTIONS.flatMap(e => e.selectors))]

/** Fixture facts a data list's expected count comes from (never the mockup's example count). */
export type FixtureContext = { researches: number; suggestions: number }

/** One item's checks: the pair's geometry, type, colour, fixed text and icon checks, on the item at `index`. */
async function checkItem(pair: Pair, item: Pair, m: Side, v: Variant, mock: Page, app: Page, index: number, data: boolean, mockIndex = index): Promise<string[]> {
  const out = checkPresence(item, m)
  if (out.length) return out
  if (pair.checks.includes('chrome')) {
    // A declared geometry exception (exceptions.ts) leaves out only its axes.
    const free = new Set(GEOMETRY_EXCEPTIONS.filter(e => e.pairs.includes(baseId(pair.id))).flatMap(e => e.axes))
    const axes = (data ? ['x', 'width', 'height'] as Axis[] : ['x', 'y', 'width', 'height'] as Axis[]).filter(a => !free.has(a))
    out.push(...checkChrome(item, m, axes))
  }
  if (pair.checks.includes('content')) out.push(...checkContent(item, m))
  if (pair.checks.includes('type')) out.push(...checkType(item, m))
  if (pair.checks.includes('colour')) out.push(...checkColour(item, m, v))
  if (pair.checks.includes('icon')) out.push(...checkIcon(pair, m, index).map(l => l.replace(pair.id, item.id)), ...await checkIconBox(pair, mock, app, index, item.id, mockIndex))
  if ((pair.text ?? pair.list === 'fixed') && !data) out.push(...checkText(item, m))
  return out
}

/** Lists. A fixed list (nav items, menu rows, tabs, head buttons, toolbars) has the same items as the mockup: count,
 *  order, visibility, geometry, type, colour, icon and fixed text item by item. A data list's count comes from the
 *  fixture records (`expected`), and each row is compared for layout and style only with the mockup row at the same
 *  place, or the mockup's last row when the data has more rows (a grid of cards keeps its columns). */
export async function checkList(pair: Pair, v: Variant, mock: Page, app: Page, ctx: FixtureContext): Promise<{ failures: string[]; first: Side }> {
  const mockItems = await measureAll(mock, pair.mock, MOCK_EXCLUDE, PROBE, pair.dataText?.mock)
  const appItems = await measureAll(app, pair.app, APP_EXCLUDE, [], pair.dataText?.app)
  const failures: string[] = []
  const data = pair.list === 'data'
  const want = data ? pair.expected?.(ctx) : mockItems.length
  if (want === undefined) failures.push(`${pair.id}: a data list needs \`expected\` from the fixture records`)
  else if (appItems.length !== want) failures.push(`${pair.id}: ${appItems.length} items in the app, expected ${want} (${data ? 'fixture records' : 'mockup'})`)
  if (!mockItems.length) failures.push(`${pair.id}: not in the mockup (${pair.mock})`)
  const count = data ? appItems.length : Math.min(mockItems.length, appItems.length)
  for (let i = 0; i < count && mockItems.length; i++) {
    const item = { ...pair, id: `${pair.id}[${i}]` }
    const m = Math.min(i, mockItems.length - 1)
    failures.push(...await checkItem(pair, item, { mock: mockItems[m], app: appItems[i] }, v, mock, app, i, data, m))
    if (pair.checks.includes('colour')) failures.push(...await checkColourStates(item, v, mock, app, i, m))
  }
  return { failures, first: { mock: mockItems[0] ?? null, app: appItems[0] ?? null } }
}

/** Marks the `index`-th match (after exclusions) so a state can be produced on exactly that element. */
async function target(page: Page, selector: string, exclude: string[], index: number): Promise<string | null> {
  const found = await page.evaluate(({ selector, exclude, index }) => {
    document.querySelectorAll('[data-parity-target]').forEach(el => el.removeAttribute('data-parity-target'))
    const el = [...document.querySelectorAll(selector)].filter(e => !exclude.some(x => e.closest(x)))[index]
    el?.setAttribute('data-parity-target', '')
    return !!el
  }, { selector, exclude, index })
  return found ? '[data-parity-target]' : null
}

async function hoverMeasure(page: Page, selector: string, exclude: string[], probe: string[], index: number): Promise<Measured | null> {
  const mark = await target(page, selector, exclude, index)
  if (!mark) return null
  await page.locator(mark).hover()
  const m = await measure(page, mark, [], probe)
  await page.mouse.move(0, 0)
  return m
}

/** A surface that changes on hover (a card that lifts): background, border colour and shadow in the hover state, as
 *  in the default state's colour check (ΔE2000 ≤ 1, shadows equal). */
function checkHoverSurface(pair: Pair, m: Side, v: Variant): string[] {
  if (!m.mock || !m.app) return []
  const out: string[] = []
  const white: Rgba = [255, 255, 255, 1]
  for (const key of ['background-color', 'border-top-color'] as const) {
    const mc = m.mock.colours[key], ac = m.app.colours[key]
    const d = Math.abs(mc[3] - ac[3]) > 0.02 ? Infinity : deltaE2000(flatten(mc, white), flatten(ac, white))
    if (d > 1) out.push(`${pair.id}: hover ${key} mockup ${hex(mc)} app ${hex(ac)} (${v.theme} ${v.width})`)
  }
  const shadow = (s: string) => s.replace(/rgba?\([^)]*\)/g, c => c.replace(/\s+/g, '')).replace(/\s+/g, ' ').trim()
  if (shadow(m.mock.style['box-shadow']) !== shadow(m.app.style['box-shadow'])) {
    out.push(`${pair.id}: hover box-shadow mockup ${m.mock.style['box-shadow']} app ${m.app.style['box-shadow']} (${v.theme} ${v.width})`)
  }
  return out
}

/** Hover and selected states of a pair's `color` (plan §4.1), for the item at `index` (a list checks every item, each
 *  with its own exception and contrast use). Hover moves the pointer over that very element on both pages; the selected
 *  state reads the pair's `selected` selectors (every selected item, matched by position). An exception element must
 *  declare which of these states it has (`states`). `mockIndex` is the mockup item compared with it (a data list
 *  compares every row with the mockup's first). */
export async function checkColourStates(pair: Pair, v: Variant, mock: Page, app: Page, index = 0, mockIndex = index): Promise<string[]> {
  const first = (await measureAll(mock, pair.mock, MOCK_EXCLUDE, PROBE, pair.dataText?.mock))[mockIndex]
  if (!first) return []
  const fallback = exceptionFor(pair, 'color', v.theme, first)
  if (fallback && !pair.states) return [`${pair.id}: exception ${fallback.id} applies; declare the element's states (hover, selected) in the map`]
  const out: string[] = []
  for (const state of pair.states ?? []) {
    if (fallback && !fallback.states.includes(state)) continue  // the exception does not cover this state
    if (state === 'hover') {
      const m = { mock: await hoverMeasure(mock, pair.mock, MOCK_EXCLUDE, PROBE, mockIndex), app: await hoverMeasure(app, pair.app, APP_EXCLUDE, [], index) }
      if (!m.mock || !m.app) { out.push(`${pair.id}: hover item missing (mockup ${!!m.mock}, app ${!!m.app})`); continue }
      out.push(...checkStateColour(pair, m, v, 'hover', fallback))
      if (pair.hoverSurface) out.push(...checkHoverSurface(pair, m, v))
    } else if (index === 0) {  // the selected items are one set per pair, checked once
      if (!pair.selected) { out.push(`${pair.id}: declares a selected state but no \`selected\` selectors`); continue }
      const [ms, as] = [await measureAll(mock, pair.selected.mock, MOCK_EXCLUDE, PROBE), await measureAll(app, pair.selected.app, APP_EXCLUDE, [])]
      if (!ms.length || !as.length) { out.push(`${pair.id}: selected item missing (mockup ${ms.length}, app ${as.length})`); continue }
      for (let k = 0; k < as.length; k++) {
        const m = { mock: ms[Math.min(k, ms.length - 1)], app: as[k] }
        out.push(...checkStateColour({ ...pair, id: as.length > 1 ? `${pair.id}{selected ${k}}` : pair.id }, m, v, 'selected',
          exceptionFor(pair, 'color', v.theme, m.mock) ?? fallback))
      }
    }
  }
  return out
}

/** Every gate of §4.1 for the active pairs of one surface and variant. Returns failure lines. */
export async function gateSurface(pairs: Pair[], v: Variant, mock: Page, app: Page, ctx: FixtureContext): Promise<string[]> {
  const failures: string[] = []
  const measured = new Map<string, Side>()
  for (const pair of pairs) {
    if (pair.list) {
      const { failures: f, first } = await checkList(pair, v, mock, app, ctx)
      failures.push(...f)
      measured.set(pair.id, first)
    } else {
      const side: Side = { mock: await measure(mock, pair.mock, MOCK_EXCLUDE, PROBE, pair.dataText?.mock), app: await measure(app, pair.app, APP_EXCLUDE, [], pair.dataText?.app) }
      measured.set(pair.id, side)
      failures.push(...await checkItem(pair, pair, side, v, mock, app, 0, false))
      if (pair.checks.includes('colour')) failures.push(...await checkColourStates(pair, v, mock, app))
    }
  }
  failures.push(...checkOrder(pairs, measured))
  return failures
}

// ---- pixel diffs (review aid, never a gate) -----------------------------------------------------------------------

const MASK = `*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important;caret-color:transparent!important;transition:none!important;animation:none!important}
*::placeholder{color:transparent!important}img,canvas,video,iframe,.thumb,.report-thumb{visibility:hidden!important}`

/** Writes `<name>.png`: mockup | app | difference, text transparent and data images hidden. Returns the file path. */
export async function writePixelDiff(mock: Page, app: Page, scratch: Page, name: string): Promise<string> {
  mkdirSync(PARITY_OUT, { recursive: true })
  const shot = async (page: Page, extra = '') => {
    const style = await page.addStyleTag({ content: MASK + extra })
    const png = await page.screenshot({ fullPage: false })
    await style.evaluate(node => (node as Element).remove())
    return png.toString('base64')
  }
  // The mockup's own controls (rule 2) are hidden in its picture too.
  const [a, b] = [await shot(mock, `${MOCK_EXCLUDE.join(',')}{visibility:hidden!important}`), await shot(app)]
  await scratch.setContent('<!doctype html><body style="margin:0;background:#888"><canvas id="c"></canvas></body>')
  const size = await scratch.evaluate(async ([a, b]) => {
    const load = (src: string) => new Promise<HTMLImageElement>(resolve => { const i = new Image(); i.onload = () => resolve(i); i.src = 'data:image/png;base64,' + src })
    const [ma, ap] = [await load(a), await load(b)]
    const w = Math.max(ma.width, ap.width), h = Math.max(ma.height, ap.height), gap = 8
    const c = document.getElementById('c') as HTMLCanvasElement
    c.width = w * 3 + gap * 2; c.height = h
    const ctx = c.getContext('2d')!
    ctx.drawImage(ma, 0, 0); ctx.drawImage(ap, w + gap, 0)
    const read = (img: HTMLImageElement) => { const t = document.createElement('canvas'); t.width = w; t.height = h; const x = t.getContext('2d')!; x.drawImage(img, 0, 0); return x.getImageData(0, 0, w, h).data }
    const da = read(ma), db = read(ap), out = ctx.createImageData(w, h)
    for (let i = 0; i < da.length; i += 4) {
      const diff = Math.abs(da[i] - db[i]) + Math.abs(da[i + 1] - db[i + 1]) + Math.abs(da[i + 2] - db[i + 2])
      const grey = (db[i] + db[i + 1] + db[i + 2]) / 3
      if (diff > 24) { out.data[i] = 230; out.data[i + 1] = 40; out.data[i + 2] = 40 } else { out.data[i] = out.data[i + 1] = out.data[i + 2] = 255 - (255 - grey) * 0.35 }
      out.data[i + 3] = 255
    }
    ctx.putImageData(out, (w + gap) * 2, 0)
    return { width: c.width, height: c.height }
  }, [a, b])
  await scratch.setViewportSize(size)
  const file = path.join(PARITY_OUT, `${name}.png`)
  writeFileSync(file, await scratch.locator('#c').screenshot())
  return file
}
