import { expect, test } from '@playwright/test'
import { checkColour, checkPresence, checkType, contrast, deltaE2000, exceptionFor, hexToRgba, normaliseFamily, type Measured, type Rgba } from './gates'
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
    background: WHITE, icon: null, matches: ['*'], hasBorder: false, ...extra,
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

test('presence counts fixed lists', () => {
  const list = pair({ list: true })
  expect(checkPresence(list, { mock: el('#000', { found: 7 }), app: el('#000', { found: 4 }) }).join()).toContain('7 items in the mockup, 4 in the app')
  expect(checkPresence(list, { mock: null, app: el('#000') }).join()).toContain('not in the mockup')
})
