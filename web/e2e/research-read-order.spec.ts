import { expect, test } from '@playwright/test'
import { createViewReads } from '../src/research/viewReads'

// Client unit tests (audit F5): the order ResearchView's `load` shows overlapping reads of one research in. Each view is
// the event id it was read at. Runs in the Playwright runner without a server or browser.
const ID = 'res_1'

test('an older read that answers last does not replace the newer view', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.answered(ID, newer, 11)).toBe(11)
  expect(reads.answered(ID, older, 10)).toBeNull()
})

test('an older read that answers first is kept back and the newer view is shown', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.answered(ID, older, 10)).toBeNull()
  expect(reads.answered(ID, newer, 11)).toBe(11)
})

test('reads that answer in order are each shown', () => {
  const reads = createViewReads<number>()
  const first = reads.start(ID)
  expect(reads.answered(ID, first, 10)).toBe(10)
  const second = reads.start(ID)
  expect(reads.answered(ID, second, 11)).toBe(11)
})

test('a newer read that fails after the older one answered shows the older view and the error', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.answered(ID, older, 10)).toBeNull()
  expect(reads.failed(ID, newer)).toEqual({ view: 10, showError: true })
})

test('a newer read that fails before the older one answers lets the older view through', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.failed(ID, newer)).toEqual({ view: null, showError: true })
  expect(reads.answered(ID, older, 10)).toBe(10)
})

test('an older read that fails after a newer view is shown shows no error', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.answered(ID, newer, 11)).toBe(11)
  expect(reads.failed(ID, older)).toEqual({ view: null, showError: false })
})

test('an older read that fails while a newer one is pending leaves the error to the newer read', () => {
  const reads = createViewReads<number>()
  const older = reads.start(ID)
  const newer = reads.start(ID)
  expect(reads.failed(ID, older)).toEqual({ view: null, showError: false })
  expect(reads.answered(ID, newer, 11)).toBe(11)
})
