import { expect, test } from '@playwright/test'
import { checkColour, checkColourStates, checkList, checkType, contrast, deltaE2000, exceptionFor, hexToRgba, normaliseFamily, type Measured, type Rgba } from './gates'
import type { Pair } from './parity-map'

// The gate helpers on fixed numbers, so a colour exception or contrast rule that never fires on today's active pairs is
// still known to work. No browser, no server.

const WHITE: Rgba = [255, 255, 255, 1]
function el(colour: string, extra: Partial<Measured> = {}): Measured {
  return {
    found: 1, visible: true, order: 0, box: { x: 0, y: 0, width: 10, height: 10 },
    style: { 'font-family': '"Inter Variable", sans-serif', 'font-size': '12px', 'font-weight': '400', 'line-height': '18px',
      'letter-spacing': 'normal', 'text-transform': 'none', 'border-top-left-radius': '0px', 'border-top-right-radius': '0px',
      'border-bottom-right-radius': '0px', 'border-bottom-left-radius': '0px', 'border-top-width': '0px', 'box-shadow': 'none' },
    colours: { color: hexToRgba(colour), 'background-color': [0, 0, 0, 0], 'border-top-color': [0, 0, 0, 0] },
    background: WHITE, icon: null, text: '', matches: ['*'], hasBorder: false, ...extra,
  }
}
const pair = (over: Partial<Pair> = {}): Pair => ({ id: 'x', surface: 'home', mock: '.x', app: '.x', checks: ['colour'], status: 'active', ...over })

test('ΔE2000 and contrast', () => {
  expect(deltaE2000(hexToRgba('#3b5b9a'), hexToRgba('#3b5b9a'))).toBe(0)
  // Published sRGB reference values: red–green 86.61, black–white 100.
  expect(deltaE2000(hexToRgba('#ff0000'), hexToRgba('#00ff00'))).toBeCloseTo(86.61, 1)
  expect(deltaE2000(hexToRgba('#000000'), hexToRgba('#ffffff'))).toBeCloseTo(100, 1)
  expect(deltaE2000(hexToRgba('#6b7280'), hexToRgba('#5b6475'))).toBeGreaterThan(1)
  expect(deltaE2000(hexToRgba('#9aa1ab'), hexToRgba('#9aa1ac'))).toBeLessThan(1)
  expect(contrast(hexToRgba('#000000'), WHITE)).toBeCloseTo(21, 5)
  expect(contrast(hexToRgba('#5b6475'), WHITE)).toBeGreaterThan(4.5)
  expect(contrast(hexToRgba('#9aa0a8'), WHITE)).toBeLessThan(4.5)
})

test('font families are normalised', () => {
  expect(normaliseFamily('"Inter Variable", sans-serif')).toBe('Inter')
  expect(normaliseFamily('Inter, -apple-system, sans-serif')).toBe('Inter')
  expect(normaliseFamily("'Source Serif 4 Variable', serif")).toBe('Source Serif 4')
  expect(checkType(pair({ checks: ['type'] }), { mock: el('#000', { style: { ...el('#000').style, 'font-family': 'Inter, sans-serif', 'letter-spacing': '0px' } }), app: el('#000') })).toEqual([])
})

test('a declared exception is compared to its approved value and checked for contrast', () => {
  // Mockup --muted text (#6b7280); the app keeps D5's #5b6475: passes.
  expect(exceptionFor(pair(), 'color', 'light', el('#6b7280'))?.id).toBe('muted-text')
  expect(checkColour(pair(), { mock: el('#6b7280'), app: el('#5b6475') }, { width: 1280, theme: 'light' })).toEqual([])
  // The app copying the mockup value is not the approved value.
  expect(checkColour(pair(), { mock: el('#6b7280'), app: el('#6b7280') }, { width: 1280, theme: 'light' }).join()).toContain('approved')
  // --faint text in the mockup must be --muted in the app; --faint itself fails as text (value and contrast).
  const faint = el('#9aa0a8', { matches: ['*', '.hint'] })
  expect(exceptionFor(pair(), 'color', 'light', faint)?.id).toBe('faint-text-is-muted')
  const asFaint = checkColour(pair(), { mock: faint, app: el('#9aa0a8') }, { width: 1280, theme: 'light' }).join('\n')
  expect(asFaint).toContain('approved')
  expect(asFaint).toContain('contrast')
  // The approved value on a surface where it does not reach 4.5:1 still fails: keeping a token never waives contrast.
  const dim = el('#5b6475', { background: hexToRgba('#3b4046') })
  expect(checkColour(pair(), { mock: el('#6b7280'), app: dim }, { width: 1280, theme: 'light' }).join()).toContain('contrast')
  // A colour with no exception must match within ΔE2000 1.
  expect(checkColour(pair(), { mock: el('#1f2328'), app: el('#3b4046') }, { width: 1280, theme: 'light' }).join()).toContain('ΔE2000')
  // An icon exception does not cover text.
  expect(exceptionFor(pair({ use: 'icon' }), 'color', 'light', faint)).toBeUndefined()
})

// The list and state checks on real pages with small SYNTHETIC documents: the browser produces hover and selected.
const css = (rules: string) => `<style>body{margin:0;font:14px/20px sans-serif}nav{display:flex;flex-direction:column;width:200px}button{all:unset;display:block;height:30px}${rules}</style>`
const NAV = (items: string[]) => `<nav>${items.join('')}</nav>`

test('a fixed list is compared item by item: count, order, visibility, size and fixed text', async ({ browser }) => {
  const mock = await browser.newPage(), app = await browser.newPage()
  try {
    const v = { width: 1280, theme: 'light' as const }
    const ctx = { researches: 1, suggestions: 0, library: 0 }
    const pair = { id: 'nav', surface: 'home' as const, mock: 'nav button', app: 'nav button', checks: ['chrome' as const], list: 'fixed' as const, status: 'active' as const, dataText: { mock: ['.cnt'], app: ['.cnt'] } }
    await mock.setContent(css('') + NAV(['<button>New research</button>', '<button>Search</button>', '<button>Awaiting you<span class="cnt">3</span></button>']))
    // Same items, a different count badge (data): passes.
    await app.setContent(css('') + NAV(['<button>New research</button>', '<button>Search</button>', '<button>Awaiting you<span class="cnt">7</span></button>']))
    expect((await checkList(pair, v, mock, app, ctx)).failures).toEqual([])
    // Swapped, hidden later item, mis-sized later item, changed label: each is caught.
    await app.setContent(css('') + NAV(['<button>Search</button>', '<button>New research</button>', '<button style="height:40px">Awaiting</button>']))
    const swapped = (await checkList(pair, v, mock, app, ctx)).failures.join('\n')
    expect(swapped).toContain('nav[0]: text mockup "New research", app "Search"')
    expect(swapped).toContain('nav[2]: height')
    expect(swapped).toContain('nav[2]: text mockup "Awaiting you", app "Awaiting"')
    await app.setContent(css('') + NAV(['<button>New research</button>', '<button>Search</button>', '<button style="visibility:hidden">Awaiting you</button>']))
    expect((await checkList(pair, v, mock, app, ctx)).failures.join('\n')).toContain('nav[2]: visible in mockup true, app false')
    await app.setContent(css('') + NAV(['<button>New research</button>', '<button>Search</button>']))
    expect((await checkList(pair, v, mock, app, ctx)).failures.join('\n')).toContain('2 items in the app, expected 3 (mockup)')
    // A data list takes its count from the fixture, not the mockup's example rows.
    const rows = { ...pair, id: 'rows', list: 'data' as const, expected: (c: { researches: number }) => c.researches }
    expect((await checkList(rows, v, mock, app, ctx)).failures.join('\n')).toContain('2 items in the app, expected 1 (fixture records)')
    // A §2.3 copy change is expected in its replacement wording.
    await mock.setContent(css('') + NAV(['<button>Read in full</button>']))
    await app.setContent(css('') + NAV(['<button>Read in full</button>']))
    expect((await checkList(pair, v, mock, app, ctx)).failures.join('\n')).toContain('copy change read-in-full')
    await app.setContent(css('') + NAV(['<button>Full text read</button>']))
    expect((await checkList(pair, v, mock, app, ctx)).failures).toEqual([])
  } finally {
    await Promise.all([mock.close(), app.close()])
  }
})

test('an exception element is checked in default, hover and selected states against its approved value', async ({ browser }) => {
  const mock = await browser.newPage(), app = await browser.newPage()
  try {
    const v = { width: 1280, theme: 'light' as const }
    // Mockup: --faint text (#9aa0a8) in every state, the selected row too. The app must show --muted (#5b6475).
    await mock.setContent(css('.hint{color:#9aa0a8}.hint:hover{color:#9aa0a8}') + '<nav><button class="hint">a</button><button class="hint on">b</button></nav>')
    const pair = { id: 'hint', surface: 'home' as const, mock: '.hint', app: '.hint', checks: ['colour' as const], status: 'active' as const,
      states: ['hover' as const, 'selected' as const], selected: { mock: '.hint.on', app: '.hint.on' } }
    await app.setContent(css('.hint{color:#5b6475}.hint:hover{color:#5b6475}') + '<nav><button class="hint">a</button><button class="hint on">b</button></nav>')
    expect(await checkColourStates(pair, v, mock, app)).toEqual([])
    // Hover drifts to the mockup's faint value: wrong value and too little contrast.
    await app.setContent(css('.hint{color:#5b6475}.hint:hover{color:#9aa0a8}') + '<nav><button class="hint">a</button><button class="hint on">b</button></nav>')
    const hover = (await checkColourStates(pair, v, mock, app)).join('\n')
    expect(hover).toMatch(/hint: color app #9aa0a8 is not the approved #5b6475 .*hover/)
    expect(hover).toMatch(/hint: text contrast .*hover/)
    // The selected row keeps the approved colour but on a dark selected surface: contrast fails there.
    await app.setContent(css('.hint{color:#5b6475}.hint.on{background:#3b4046}') + '<nav><button class="hint">a</button><button class="hint on">b</button></nav>')
    expect((await checkColourStates(pair, v, mock, app)).join('\n')).toMatch(/hint: text contrast .*selected/)
    // An exception element must say which states it has.
    expect((await checkColourStates({ ...pair, states: undefined }, v, mock, app)).join()).toContain('declare the element')
  } finally {
    await Promise.all([mock.close(), app.close()])
  }
})

test('in a list, every item is checked in its states: a wrong hover on the second item alone is rejected', async ({ browser }) => {
  const mock = await browser.newPage(), app = await browser.newPage()
  try {
    const v = { width: 1280, theme: 'light' as const }
    const ctx = { researches: 1, suggestions: 0, library: 0 }
    const rows = '<nav><button class="hint">a</button><button class="hint">b</button><button class="hint">c</button></nav>'
    await mock.setContent(css('.hint{color:#9aa0a8}') + rows)
    const pair = { id: 'hints', surface: 'home' as const, mock: '.hint', app: '.hint', checks: ['colour' as const], list: 'fixed' as const,
      status: 'active' as const, states: ['hover' as const] }
    await app.setContent(css('.hint{color:#5b6475}') + rows)
    expect((await checkList(pair, v, mock, app, ctx)).failures).toEqual([])
    await app.setContent(css('.hint{color:#5b6475}.hint:nth-child(2):hover{color:#9aa0a8}') + rows)
    const failures = (await checkList(pair, v, mock, app, ctx)).failures
    expect(failures.join('\n')).toMatch(/hints\[1\]: color app #9aa0a8 is not the approved #5b6475 .*hover/)
    expect(failures.join('\n')).toMatch(/hints\[1\]: text contrast .*hover/)
    expect(failures.filter(f => /hints\[(0|2)\]/.test(f))).toEqual([])
  } finally {
    await Promise.all([mock.close(), app.close()])
  }
})
