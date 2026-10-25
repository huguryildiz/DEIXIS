import AxeBuilder from '@axe-core/playwright'
import { expect, type Locator, type Page } from '@playwright/test'
import { chooseTheme } from './panels'

// Accessibility checks the five specs share (release matrix X01 to X06). They replace the old a11y.spec.ts, cut in the
// 2026-10-25 test simplification; each spec scans the screens it already reaches instead of a frozen 26-screen list.

// X01 light 1280, X02 dark 1280, X03 light 390, X04 dark 390. Tag set as before; no rule is disabled.
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const COMBOS = [
  { id: 'X01', theme: 'light', width: 1280, height: 900 },
  { id: 'X02', theme: 'dark', width: 1280, height: 900 },
  { id: 'X03', theme: 'light', width: 390, height: 844 },
  { id: 'X04', theme: 'dark', width: 390, height: 844 },
] as const

const quiet = (page: Page) => page.waitForFunction(() => document.getAnimations().length === 0, undefined, { timeout: 5000 }).catch(() => {})

// Serious and critical axe findings on the current screen in all four states, as "screen state rule: selector" lines.
// base-ui's focus guards (the sentinels around an open popup) are focusable and aria-hidden by design and forward focus at
// once (W3C ACT 6cfa84, passed example 4); only those nodes of aria-hidden-focus are set aside. Ends at 1280 px, light.
export async function axeScan(page: Page, screen: string): Promise<string[]> {
  const found: string[] = []
  for (const combo of COMBOS) {
    await page.setViewportSize({ width: combo.width, height: combo.height })
    await page.emulateMedia({ reducedMotion: 'reduce' })  // no mid-fade colours; motion is X06
    await chooseTheme(page, combo.theme)
    await expect.poll(() => page.locator('html').evaluate(el => el.classList.contains('dark')), `${screen}: theme ${combo.theme}`).toBe(combo.theme === 'dark')
    await page.mouse.move(0, combo.height - 1)
    await quiet(page)
    const result = await new AxeBuilder({ page }).withTags(TAGS).analyze()
    expect(result.passes.length, `${screen} ${combo.id}: axe ran its rules`).toBeGreaterThan(0)
    for (const v of result.violations) {
      if (v.impact !== 'serious' && v.impact !== 'critical') continue
      const nodes = v.nodes.filter(node => !(v.id === 'aria-hidden-focus' && String(node.target.at(-1)).includes('data-base-ui-focus-guard')))
      for (const node of nodes.slice(0, 5)) found.push(`${screen} ${combo.id} ${v.id}: ${String(node.target[0]).slice(0, 120)}`)
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await chooseTheme(page, 'light')
  return found
}

// What the focused element and its nearest ancestors (an ancestor such as the composer draws the ring for the input
// inside) actually render as decoration: the outline, the box shadows, the borders and the ::before / ::after boxes. A
// part that draws nothing (no width, style none or hidden, a transparent colour, a shadow with no blur and no spread, a
// pseudo-element with no content, hidden or at opacity 0) is left empty. Runs in the page, so it is self-contained.
function renderedDecoration(el: Element): string[][] {
  const alpha = (color: string) => {
    if (!color || color === 'transparent') return 0
    const slash = color.match(/\/\s*([\d.]+)(%?)\s*\)$/)
    if (slash) return parseFloat(slash[1]) / (slash[2] ? 100 : 1)
    const rgba = color.match(/^rgba\(([^)]*)\)$/)
    if (rgba) return parseFloat(rgba[1].split(',')[3])
    return 1
  }
  const visibleStyle = (style: string) => style !== 'none' && style !== 'hidden'
  const shadows = (value: string) => {
    if (!value || value === 'none') return ''
    const parts: string[] = []
    let depth = 0, current = ''
    for (const ch of value) {
      if (ch === '(') depth++
      if (ch === ')') depth--
      if (ch === ',' && depth === 0) { parts.push(current.trim()); current = '' } else current += ch
    }
    parts.push(current.trim())
    return parts.filter(part => {
      const color = part.match(/[a-z-]+\([^)]*\)|transparent/)?.[0] ?? 'rgb(0, 0, 0)'
      const lengths = part.replace(color, '').replace('inset', '').trim().split(/\s+/).map(parseFloat)
      return alpha(color) > 0 && ((lengths[2] ?? 0) > 0 || (lengths[3] ?? 0) !== 0)
    }).join(', ')
  }
  const out: string[][] = []
  for (let node: Element | null = el, i = 0; node && i < 4; node = node.parentElement, i++) {
    const s = getComputedStyle(node)
    const outline = visibleStyle(s.outlineStyle) && parseFloat(s.outlineWidth) > 0 && alpha(s.outlineColor) > 0 ? `outline ${s.outlineWidth} ${s.outlineStyle} ${s.outlineColor}` : ''
    const border = (['Top', 'Right', 'Bottom', 'Left'] as const).map(side => {
      const width = s.getPropertyValue(`border-${side.toLowerCase()}-width`), style = s.getPropertyValue(`border-${side.toLowerCase()}-style`), color = s.getPropertyValue(`border-${side.toLowerCase()}-color`)
      return visibleStyle(style) && parseFloat(width) > 0 && alpha(color) > 0 ? `${side} ${width} ${style} ${color}` : ''
    }).filter(Boolean).join(', ')
    const pseudo = ['::before', '::after'].map(p => {
      const ps = getComputedStyle(node!, p)
      if (ps.content === 'none' || ps.content === 'normal' || ps.display === 'none' || ps.visibility !== 'visible' || parseFloat(ps.opacity) <= 0) return ''
      const fill = alpha(ps.backgroundColor) > 0 ? `background ${ps.backgroundColor}` : ''
      const shadow = shadows(ps.boxShadow)
      return fill || shadow ? `${p} ${fill} ${shadow}`.trim() : ''
    })
    out.push([outline, shadows(s.boxShadow), border, ...pseudo])
  }
  return out
}

// What shows that the focused element has focus: a decoration of the element or of an ancestor that renders with focus
// and is not rendered the same way without it, read once transitions have ended. A decoration that is there either way
// (the composer's resting shadow) or that draws nothing (a transparent or zero-width ring) is not an indicator. The
// element gets its focus back afterwards, so the Tab order goes on from it. Empty when nothing shows, or on the body.
export async function focusIndicator(page: Page): Promise<string> {
  const element = await page.evaluateHandle(() => document.activeElement)
  if (await element.evaluate(el => !el || el === document.body)) return ''
  await quiet(page)
  const on = await element.evaluate(renderedDecoration as (el: Element | null) => string[][])
  await element.evaluate(el => (el as HTMLElement).blur())
  await quiet(page)
  const off = await element.evaluate(renderedDecoration as (el: Element | null) => string[][])
  await element.evaluate(el => (el as HTMLElement).focus())
  await quiet(page)
  const kinds = ['outline', 'box-shadow', 'border', '::before', '::after']
  for (const [level, parts] of on.entries()) for (const [k, value] of parts.entries()) {
    if (value && value !== off[level]?.[k]) return level === 0 ? kinds[k] : `${kinds[k]} on ancestor ${level}`
  }
  return ''
}

const label = (page: Page) => page.evaluate(() => {
  const el = document.activeElement as HTMLElement | null
  if (!el) return 'nothing'
  return `${el.tagName.toLowerCase()}${el.getAttribute('aria-label') ? `[${el.getAttribute('aria-label')}]` : el.textContent?.trim() ? ` "${el.textContent.trim().slice(0, 30)}"` : ''}`
})

// Presses Tab until `target` has focus, at most `max` times. Every stop on the way is recorded with what showed its
// focus; a stop where nothing showed it, or where focus fell to the body, goes into `missing`.
export async function tabTo(page: Page, target: Locator, missing: string[], max = 80) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const where = await label(page)
    if (!(await focusIndicator(page))) missing.push(where)
    if (await target.evaluate(el => el === document.activeElement).catch(() => false)) return
  }
  throw new Error(`Tab did not reach the target in ${max} presses`)
}

// X06: computed durations and live animations at one moment. With reduced motion nothing may last above 0.01 ms, loop
// for ever, or scroll smoothly; the caller runs the same audit without the preference as the positive control.
export type Motion = { offenders: string[]; infinite: string[]; scrollBehavior: string }
export async function motionAudit(page: Page): Promise<Motion> {
  return page.evaluate(() => {
    const ms = (value: string) => value.split(',').map(s => s.trim()).map(s => s.endsWith('ms') ? parseFloat(s) : s.endsWith('s') ? parseFloat(s) * 1000 : 0)
    const name = (el: Element) => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '')
    const offenders = new Set<string>()
    for (const el of document.querySelectorAll('*')) for (const pseudo of [null, '::before', '::after'] as const) {
      const cs = getComputedStyle(el, pseudo)
      if (Math.max(...ms(cs.animationDuration)) > 0.011 || Math.max(...ms(cs.transitionDuration)) > 0.011) offenders.add(`${name(el)}${pseudo ?? ''} animation=${cs.animationDuration} transition=${cs.transitionDuration}`)
    }
    const infinite = document.getAnimations().filter(a => a.effect?.getComputedTiming().iterations === Infinity).map(a => (a as CSSAnimation).animationName ?? 'animation')
    return { offenders: [...offenders].slice(0, 25), infinite: [...new Set(infinite)], scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior }
  })
}

// X06: the 200% layout (a 1280 px window at 200% zoom is 640x450 CSS px at scale 2). No horizontal page scroll, and each
// named control is visible and not covered at its centre once it has focus (focus() scrolls it the way Tab does).
export async function layoutProblems(page: Page, screen: string, controls: Record<string, Locator>): Promise<string[]> {
  await quiet(page)
  const problems: string[] = []
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  if (width.scroll > width.client) problems.push(`${screen}: horizontal page scroll (${width.scroll} > ${width.client})`)
  for (const [name, locator] of Object.entries(controls)) {
    const target = locator.first()
    if (!(await target.isVisible().catch(() => false))) { problems.push(`${screen}: "${name}" not visible`); continue }
    await target.focus()
    const hit = await target.evaluate(el => {
      const r = el.getBoundingClientRect()
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      return { free: !!top && (el === top || el.contains(top) || top.contains(el)), top: top ? top.tagName.toLowerCase() + (typeof top.className === 'string' && top.className ? '.' + top.className.trim().split(/\s+/)[0] : '') : 'nothing' }
    })
    if (!hit.free) problems.push(`${screen}: "${name}" covered by ${hit.top}`)
  }
  return problems
}
